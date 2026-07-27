"""
ghl_mirror.py
-------------
Row-level GHL mirror (opportunities + contacts + notes → Postgres), the same proven pattern as
sheet_mirror: faithful rows + sync metadata, idempotent/atomic upserts, change-detection, deletion
propagation, a background loop, "resync" coverage, and per-source freshness. EDITH then reads leads
at DB speed instead of hammering the GHL API.

Reuses the app's existing GHL Private Integration Token (full scope — verified Phase 0) via
ghl_pull. Rate-limit-respectful: opps are cheap (paginated search); contacts+notes are throttled
under the 100-req/10s burst. The reactivation universe is OPEN opportunities in the sales pipeline,
so the contact/notes sweep is bounded to those (~1.3k), not the whole CRM.

PII discipline: names/emails/phones/notes live ONLY in these auth-gated mirror tables (never in
memory_facts, never logged plaintext). Reads happen through this module; nothing here writes to the
snapshot's public surfaces.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import db
import ghl_pull
from config import GHL_BASE, GHL_API_KEY, GHL_LOCATION_ID, HTTP_TIMEOUT
from helpers import now_sydney

logger = logging.getLogger(__name__)

import requests

_SYNC_INTERVAL = 900          # opps every 15 min on the loop; contacts/notes incremental
_THROTTLE = 0.12              # ~8 req/s — comfortably under the 100/10s burst
_sync_lock = threading.Lock()
_loop_lock = threading.Lock()
_loop_started = False

_DDL = """
CREATE TABLE IF NOT EXISTS ghl_opportunities (
    id                     TEXT PRIMARY KEY,
    contact_id             TEXT,
    name                   TEXT,
    pipeline_stage_id      TEXT,
    stage_name             TEXT,
    status                 TEXT,
    monetary_value         DOUBLE PRECISION,
    source                 TEXT,
    assigned_to            TEXT,
    created_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ,
    last_stage_change_at   TIMESTAMPTZ,
    last_status_change_at  TIMESTAMPTZ,
    raw                    JSONB,
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted                BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_ghl_opps_stage ON ghl_opportunities (stage_name);
CREATE INDEX IF NOT EXISTS idx_ghl_opps_status ON ghl_opportunities (status);
CREATE INDEX IF NOT EXISTS idx_ghl_opps_contact ON ghl_opportunities (contact_id);

CREATE TABLE IF NOT EXISTS ghl_contacts (
    id            TEXT PRIMARY KEY,
    first_name    TEXT,
    last_name     TEXT,
    email         TEXT,
    phone         TEXT,
    tags          JSONB,
    date_added    TIMESTAMPTZ,
    date_updated  TIMESTAMPTZ,
    raw           JSONB,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted       BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_ghl_contacts_email ON ghl_contacts (lower(email));

CREATE TABLE IF NOT EXISTS ghl_notes (
    id            TEXT PRIMARY KEY,
    contact_id    TEXT,
    body          TEXT,
    title         TEXT,
    user_id       TEXT,
    date_added    TIMESTAMPTZ,
    body_hash     TEXT,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted       BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_ghl_notes_contact ON ghl_notes (contact_id);

CREATE TABLE IF NOT EXISTS ghl_sync_state (
    source                   TEXT PRIMARY KEY,
    last_sync_at             TIMESTAMPTZ,
    last_change_detected_at  TIMESTAMPTZ,
    row_count                INTEGER,
    ok                       BOOLEAN,
    error                    TEXT,
    last_full_backfill_at    TIMESTAMPTZ
);
"""


def migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("ghl_mirror migrate failed: %s", e)
        return False


def enabled() -> bool:
    return bool(GHL_API_KEY and GHL_LOCATION_ID and db.db_configured())


# ── Low-level GHL reads (contacts + notes; opps/stages reuse ghl_pull) ────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28"}


def _get(path: str, params: dict | None = None) -> tuple[dict | None, int]:
    """GET with 429/5xx backoff. Returns (json|None, status)."""
    for attempt in range(4):
        try:
            r = requests.get(f"{GHL_BASE}{path}", headers=_headers(), params=params or {},
                             timeout=(5, HTTP_TIMEOUT))
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(2 ** attempt, 8))
                continue
            return (r.json() if r.ok else None), r.status_code
        except requests.RequestException as e:
            logger.info("ghl _get %s failed (attempt %d): %s", path, attempt, e)
            time.sleep(min(2 ** attempt, 8))
    return None, 0


def _fetch_contact(cid: str) -> dict | None:
    d, _ = _get(f"/contacts/{cid}")
    return (d or {}).get("contact") if d else None


def _fetch_notes(cid: str) -> list[dict]:
    d, _ = _get(f"/contacts/{cid}/notes")
    return (d or {}).get("notes", []) if d else []


def _ts(v):
    """GHL ISO string → passthrough (psycopg casts to timestamptz). None-safe."""
    return v or None


def _hash(s: str) -> str:
    import hashlib
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


# ── Sync: opportunities ──────────────────────────────────────────────────────

def sync_opportunities() -> dict:
    """Pull all opps in the sales pipeline; upsert; propagate deletions; update sync_state."""
    if not enabled():
        return {"ok": False, "reason": "ghl not configured"}
    migrate()
    stages = ghl_pull._fetch_pipeline_stages()
    res = ghl_pull._fetch_all_opportunities()
    opps = res.get("opps") or []
    complete = res.get("complete", False)
    if not opps and not complete:
        _mark_state("opportunities", ok=False, error=res.get("reason") or "no opps / incomplete")
        return {"ok": False, "reason": res.get("reason")}
    changed = 0
    seen_ids = []
    try:
        with db.get_conn() as c:
            for o in opps:
                oid = o.get("id")
                if not oid:
                    continue
                seen_ids.append(oid)
                stage_name = stages.get(o.get("pipelineStageId"), o.get("pipelineStageId"))
                r = c.execute(
                    """INSERT INTO ghl_opportunities
                       (id, contact_id, name, pipeline_stage_id, stage_name, status, monetary_value,
                        source, assigned_to, created_at, updated_at, last_stage_change_at,
                        last_status_change_at, raw, synced_at, deleted)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), FALSE)
                       ON CONFLICT (id) DO UPDATE SET
                         contact_id=EXCLUDED.contact_id, name=EXCLUDED.name,
                         pipeline_stage_id=EXCLUDED.pipeline_stage_id, stage_name=EXCLUDED.stage_name,
                         status=EXCLUDED.status, monetary_value=EXCLUDED.monetary_value,
                         source=EXCLUDED.source, assigned_to=EXCLUDED.assigned_to,
                         created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at,
                         last_stage_change_at=EXCLUDED.last_stage_change_at,
                         last_status_change_at=EXCLUDED.last_status_change_at,
                         raw=EXCLUDED.raw, synced_at=now(), deleted=FALSE
                       WHERE ghl_opportunities.updated_at IS DISTINCT FROM EXCLUDED.updated_at
                          OR ghl_opportunities.deleted""",
                    (oid, o.get("contactId"), o.get("name"), o.get("pipelineStageId"), stage_name,
                     (o.get("status") or "open").lower(), float(o.get("monetaryValue") or 0),
                     o.get("source"), o.get("assignedTo"), _ts(o.get("createdAt")), _ts(o.get("updatedAt")),
                     _ts(o.get("lastStageChangeAt")), _ts(o.get("lastStatusChangeAt")),
                     json.dumps(o)))
                if r.rowcount:
                    changed += 1
            # deletion propagation — anything not seen this full sync is gone from GHL
            if complete and seen_ids:
                c.execute("UPDATE ghl_opportunities SET deleted=TRUE, synced_at=now() "
                          "WHERE deleted=FALSE AND NOT (id = ANY(%s))", (seen_ids,))
        _mark_state("opportunities", ok=complete, error=None if complete else res.get("reason"),
                    row_count=len(seen_ids), changed=changed)
        return {"ok": True, "count": len(seen_ids), "changed": changed, "complete": complete}
    except Exception as e:
        logger.exception("sync_opportunities failed")
        _mark_state("opportunities", ok=False, error=str(e))
        return {"ok": False, "reason": str(e)}


# ── Sync: contacts + notes (bounded to the reactivation universe) ─────────────

def _open_contact_ids(limit: int | None = None) -> list[str]:
    """Distinct contact_ids of OPEN opportunities (the reactivation universe)."""
    try:
        with db.get_conn() as c:
            q = ("SELECT DISTINCT contact_id FROM ghl_opportunities "
                 "WHERE deleted=FALSE AND status='open' AND contact_id IS NOT NULL")
            if limit:
                q += f" LIMIT {int(limit)}"
            return [r["contact_id"] for r in c.execute(q).fetchall()]
    except Exception as e:
        logger.info("_open_contact_ids failed: %s", e)
        return []


def sync_contacts_and_notes(contact_ids: list[str] | None = None, cap: int | None = None) -> dict:
    """Fetch + upsert contacts and their notes for the given contact_ids (default: all open-opp
    contacts). Throttled. Note change-detection via body_hash so summaries regenerate only on change."""
    if not enabled():
        return {"ok": False, "reason": "ghl not configured"}
    migrate()
    ids = contact_ids if contact_ids is not None else _open_contact_ids(cap)
    if not ids:
        return {"ok": True, "contacts": 0, "notes": 0, "note": "no open-opp contacts to sync"}
    c_ok = n_ok = notes_changed = errors = 0
    try:
        with db.get_conn() as c:
            for cid in ids:
                contact = _fetch_contact(cid)
                if contact:
                    c.execute(
                        """INSERT INTO ghl_contacts
                           (id, first_name, last_name, email, phone, tags, date_added, date_updated, raw, synced_at, deleted)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), FALSE)
                           ON CONFLICT (id) DO UPDATE SET
                             first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name,
                             email=EXCLUDED.email, phone=EXCLUDED.phone, tags=EXCLUDED.tags,
                             date_added=EXCLUDED.date_added, date_updated=EXCLUDED.date_updated,
                             raw=EXCLUDED.raw, synced_at=now(), deleted=FALSE""",
                        (cid, contact.get("firstName"), contact.get("lastName"), contact.get("email"),
                         contact.get("phone"), json.dumps(contact.get("tags") or []),
                         _ts(contact.get("dateAdded")), _ts(contact.get("dateUpdated")), json.dumps(contact)))
                    c_ok += 1
                else:
                    errors += 1
                # notes for this contact
                notes = _fetch_notes(cid)
                seen_note_ids = []
                for nt in notes:
                    nid = nt.get("id")
                    if not nid:
                        continue
                    seen_note_ids.append(nid)
                    bh = _hash(nt.get("body") or "")
                    r = c.execute(
                        """INSERT INTO ghl_notes (id, contact_id, body, title, user_id, date_added, body_hash, synced_at, deleted)
                           VALUES (%s,%s,%s,%s,%s,%s,%s, now(), FALSE)
                           ON CONFLICT (id) DO UPDATE SET
                             body=EXCLUDED.body, title=EXCLUDED.title, user_id=EXCLUDED.user_id,
                             date_added=EXCLUDED.date_added, body_hash=EXCLUDED.body_hash,
                             synced_at=now(), deleted=FALSE
                           WHERE ghl_notes.body_hash IS DISTINCT FROM EXCLUDED.body_hash OR ghl_notes.deleted""",
                        (nid, cid, nt.get("body"), nt.get("title"), nt.get("userId"),
                         _ts(nt.get("dateAdded")), bh))
                    if r.rowcount:
                        notes_changed += 1
                    n_ok += 1
                # deletion propagation for this contact's notes
                if seen_note_ids:
                    c.execute("UPDATE ghl_notes SET deleted=TRUE, synced_at=now() "
                              "WHERE contact_id=%s AND deleted=FALSE AND NOT (id = ANY(%s))",
                              (cid, seen_note_ids))
                time.sleep(_THROTTLE)
        _mark_state("contacts_notes", ok=(errors == 0), error=(f"{errors} contact fetch errors" if errors else None),
                    row_count=c_ok, changed=notes_changed)
        return {"ok": True, "contacts": c_ok, "notes": n_ok, "notes_changed": notes_changed, "errors": errors}
    except Exception as e:
        logger.exception("sync_contacts_and_notes failed")
        _mark_state("contacts_notes", ok=False, error=str(e))
        return {"ok": False, "reason": str(e)}


def unsynced_open_contact_ids(cap: int = 200) -> list[str]:
    """Open-opp contact_ids not yet mirrored into ghl_contacts (drains the initial backfill)."""
    try:
        with db.get_conn() as c:
            return [r["contact_id"] for r in c.execute(
                """SELECT DISTINCT o.contact_id FROM ghl_opportunities o
                   LEFT JOIN ghl_contacts c ON c.id = o.contact_id
                   WHERE o.deleted=FALSE AND o.status='open' AND o.contact_id IS NOT NULL AND c.id IS NULL
                   LIMIT %s""", (int(cap),)).fetchall()]
    except Exception as e:
        logger.info("unsynced_open_contact_ids failed: %s", e)
        return []


def remaining_backfill() -> int:
    try:
        with db.get_conn() as c:
            return c.execute(
                """SELECT count(DISTINCT o.contact_id) n FROM ghl_opportunities o
                   LEFT JOIN ghl_contacts c ON c.id = o.contact_id
                   WHERE o.deleted=FALSE AND o.status='open' AND o.contact_id IS NOT NULL AND c.id IS NULL"""
            ).fetchone()["n"]
    except Exception:
        return -1


def backfill_chunk(cap: int = 150) -> dict:
    """One resumable backfill step: ensure opps synced, then sync up to `cap` un-mirrored contacts
    (+ their notes). Call repeatedly until remaining == 0. Bounded to fit the request timeout."""
    with _sync_lock:
        o = sync_opportunities()
        ids = unsynced_open_contact_ids(cap)
        cn = sync_contacts_and_notes(contact_ids=ids) if ids else {"ok": True, "contacts": 0, "notes": 0}
        rem = remaining_backfill()
        if rem == 0:
            _mark_state("contacts_notes", ok=cn.get("ok", True), full_backfill=True)
        return {"opportunities": o, "chunk_contacts": cn.get("contacts", 0),
                "chunk_notes": cn.get("notes", 0), "remaining_contacts": rem, "counts": counts()}


def sync_all(full: bool = False, cap: int | None = None) -> dict:
    """Opps first (cheap), then contacts+notes for open-opp contacts. `full`/`cap` bound the sweep."""
    with _sync_lock:
        o = sync_opportunities()
        cn = sync_contacts_and_notes(cap=cap)
        if full:
            _mark_state("contacts_notes", ok=cn.get("ok", False), full_backfill=True)
        return {"opportunities": o, "contacts_notes": cn}


# ── Sync-state / freshness ───────────────────────────────────────────────────

def _mark_state(source: str, ok: bool, error: str | None = None, row_count: int | None = None,
                changed: int = 0, full_backfill: bool = False) -> None:
    try:
        with db.get_conn() as c:
            c.execute(
                """INSERT INTO ghl_sync_state (source, last_sync_at, last_change_detected_at, row_count, ok, error, last_full_backfill_at)
                   VALUES (%s, now(), CASE WHEN %s>0 THEN now() ELSE NULL END, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END)
                   ON CONFLICT (source) DO UPDATE SET
                     last_sync_at=now(),
                     last_change_detected_at=CASE WHEN %s>0 THEN now() ELSE ghl_sync_state.last_change_detected_at END,
                     row_count=COALESCE(EXCLUDED.row_count, ghl_sync_state.row_count),
                     ok=EXCLUDED.ok, error=EXCLUDED.error,
                     last_full_backfill_at=CASE WHEN %s THEN now() ELSE ghl_sync_state.last_full_backfill_at END""",
                (source, changed, row_count, ok, error, full_backfill, changed, full_backfill))
    except Exception as e:
        logger.info("ghl _mark_state failed: %s", e)


def get_sources() -> list[dict]:
    """Freshness rows for the transparency panel."""
    out = []
    if not db.db_configured():
        return out
    try:
        with db.get_conn() as c:
            for r in c.execute("SELECT * FROM ghl_sync_state ORDER BY source").fetchall():
                d = dict(r)
                for k in ("last_sync_at", "last_change_detected_at", "last_full_backfill_at"):
                    if d.get(k) is not None:
                        d[k] = d[k].isoformat()
                out.append(d)
    except Exception as e:
        logger.info("ghl get_sources failed: %s", e)
    return out


# ── Reads (DB speed) ─────────────────────────────────────────────────────────

def read_opportunities(open_only: bool = True) -> list[dict]:
    if not db.db_configured():
        return []
    try:
        with db.get_conn() as c:
            q = "SELECT * FROM ghl_opportunities WHERE deleted=FALSE"
            if open_only:
                q += " AND status='open'"
            return [dict(r) for r in c.execute(q).fetchall()]
    except Exception as e:
        logger.info("read_opportunities failed: %s", e)
        return []


def read_notes_for_contact(cid: str) -> list[dict]:
    if not db.db_configured() or not cid:
        return []
    try:
        with db.get_conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM ghl_notes WHERE contact_id=%s AND deleted=FALSE ORDER BY date_added",
                (cid,)).fetchall()]
    except Exception as e:
        logger.info("read_notes_for_contact failed: %s", e)
        return []


def read_contact(cid: str) -> dict | None:
    if not db.db_configured() or not cid:
        return None
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT * FROM ghl_contacts WHERE id=%s AND deleted=FALSE", (cid,)).fetchone()
            return dict(r) if r else None
    except Exception as e:
        logger.info("read_contact failed: %s", e)
        return None


def counts() -> dict:
    """Quick row counts for integrity + freshness."""
    if not db.db_configured():
        return {}
    try:
        with db.get_conn() as c:
            def n(t, w=""):
                return c.execute(f"SELECT count(*) n FROM {t} {w}").fetchone()["n"]
            return {
                "opportunities": n("ghl_opportunities", "WHERE deleted=FALSE"),
                "opportunities_open": n("ghl_opportunities", "WHERE deleted=FALSE AND status='open'"),
                "contacts": n("ghl_contacts", "WHERE deleted=FALSE"),
                "notes": n("ghl_notes", "WHERE deleted=FALSE"),
            }
    except Exception as e:
        logger.info("ghl counts failed: %s", e)
        return {}


# ── Background loop + resync coverage ────────────────────────────────────────

def _loop():
    logger.info("ghl_mirror sync loop started (every %ds)", _SYNC_INTERVAL)
    while True:
        try:
            sync_opportunities()   # cheap, frequent; contacts/notes sync via resync + periodic backfill
        except Exception as e:
            logger.warning("ghl_mirror loop error: %s", e)
        time.sleep(_SYNC_INTERVAL)


def start_sync_loop() -> bool:
    global _loop_started
    if not enabled():
        return False
    with _loop_lock:
        if _loop_started:
            return False
        _loop_started = True
        threading.Thread(target=_loop, daemon=True, name="ghl-mirror-sync").start()
        return True
