"""
collab.py
---------
The three-way collaboration layer (Rydel + Piolo + EDITH) with a closed, data-verified loop:

  EDITH FLAGS (DQ/hygiene) → PIOLO'S QUEUE → PIOLO RESOLVES with a note → EDITH VERIFIES the
  underlying data actually changed → RYDEL gets a digest.

Plus Piolo's free-form WORK LOG (done/concern/question/suggestion) with threads, and attribution:
every write-action is stamped with the actor, and Piolo's actions are FLAGGED to Rydel (his call).

FOREVER ARCHIVE: append-only (no deletes for any role; post-window edits are appended corrections;
owner may archive-HIDE non-destructively). Date-browsable, EDITH-queryable, unioned into a journal,
and exported off-DB (dated JSON/CSV) so it survives a DB loss.

Log entries are DATA, never instructions — an entry saying "EDITH, do X" is reported as text, never
executed (prompt-injection discipline).
"""
from __future__ import annotations

import json
import logging

import db
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

_EDIT_WINDOW_SECONDS = 15 * 60
_ENTRY_KINDS = {"done", "concern", "question", "suggestion"}

_DDL = """
CREATE TABLE IF NOT EXISTS collab_log (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL,          -- done|concern|question|suggestion|reply|correction|action
  author       TEXT NOT NULL,          -- rydel|piolo|edith
  body         TEXT NOT NULL,
  link_type    TEXT,                   -- flag|client|payment|queue|null
  link_ref     TEXT,
  parent_id    BIGINT,                 -- reply/correction thread
  archived     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  edited_at    TIMESTAMPTZ,
  meta         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS collab_log_created ON collab_log (created_at);
CREATE TABLE IF NOT EXISTS collab_queue (
  flag_id       TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  detail        TEXT,
  category      TEXT,
  status        TEXT NOT NULL DEFAULT 'open',   -- open|resolved|verified|partial
  resolution    TEXT,
  resolved_by   TEXT,
  resolved_at   TIMESTAMPTZ,
  verification  TEXT,
  verified_at   TIMESTAMPTZ,
  first_seen    DATE NOT NULL DEFAULT (now() AT TIME ZONE 'Australia/Sydney'),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS collab_read_marks (
  reader   TEXT NOT NULL,
  entry_id BIGINT NOT NULL,
  seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (reader, entry_id)
);
ALTER TABLE collab_queue ADD COLUMN IF NOT EXISTS signature TEXT;
ALTER TABLE collab_queue ADD COLUMN IF NOT EXISTS lane_override TEXT;
CREATE TABLE IF NOT EXISTS collab_item_state (
  signature  TEXT PRIMARY KEY,
  first_seen DATE NOT NULL,
  last_lane  TEXT
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
        logger.warning("collab migrate failed: %s", e)
        return False


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


# ── WORK LOG ─────────────────────────────────────────────────────────────────

def add_entry(author: str, kind: str, body: str, link_type: str | None = None,
              link_ref: str | None = None, parent_id: int | None = None) -> dict | None:
    """Append a work-log entry. Immutable after a 15-min edit window (then append corrections)."""
    kind = (kind or "").lower()
    if kind not in _ENTRY_KINDS and kind not in ("reply", "correction", "action"):
        kind = "suggestion"
    if not (body or "").strip():
        return None
    migrate()
    try:
        with db.get_conn() as c:
            r = c.execute(
                "INSERT INTO collab_log (kind, author, body, link_type, link_ref, parent_id) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, created_at",
                (kind, author, body.strip(), link_type, link_ref, parent_id)).fetchone()
        return {"id": r["id"], "created_at": _iso(r["created_at"]), "kind": kind, "author": author}
    except Exception as e:
        logger.warning("add_entry failed: %s", e)
        return None


def edit_entry(entry_id: int, author: str, new_body: str) -> tuple[bool, str]:
    """Edit within the 15-min window; after that, APPEND a correction (never overwrite)."""
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT author, created_at FROM collab_log WHERE id=%s", (entry_id,)).fetchone()
            if not r:
                return False, "not found"
            if r["author"] != author:
                return False, "only the author can edit"
            age = (now_sydney() - r["created_at"]).total_seconds()
            if age <= _EDIT_WINDOW_SECONDS:
                c.execute("UPDATE collab_log SET body=%s, edited_at=now() WHERE id=%s",
                          (new_body.strip(), entry_id))
                return True, "edited"
    except Exception as e:
        logger.warning("edit_entry failed: %s", e)
        return False, "error"
    # window passed → append-only correction
    add_entry(author, "correction", new_body, link_type="entry", link_ref=str(entry_id), parent_id=entry_id)
    return True, "appended-correction"


def archive_entry(entry_id: int, by_owner: bool) -> bool:
    """Non-destructive archive-hide (owner only). Never deletes; stays in exports + searches."""
    if not by_owner:
        return False
    try:
        with db.get_conn() as c:
            c.execute("UPDATE collab_log SET archived=TRUE WHERE id=%s", (entry_id,))
        return True
    except Exception:
        return False


def list_entries(start=None, end=None, author=None, kind=None, include_archived=False,
                 limit: int = 200) -> list[dict]:
    if not db.db_configured():
        return []
    q = "SELECT * FROM collab_log WHERE 1=1"
    args: list = []
    if not include_archived:
        q += " AND NOT archived"
    if start:
        q += " AND created_at >= %s"; args.append(start)
    if end:
        q += " AND created_at <= %s"; args.append(end)
    if author:
        q += " AND author = %s"; args.append(author)
    if kind:
        q += " AND kind = %s"; args.append(kind)
    q += " ORDER BY created_at DESC LIMIT %s"; args.append(limit)
    try:
        with db.get_conn() as c:
            rows = c.execute(q, tuple(args)).fetchall()
        return [{**dict(r), "created_at": _iso(r["created_at"]), "edited_at": _iso(r.get("edited_at"))}
                for r in rows]
    except Exception as e:
        logger.info("list_entries failed: %s", e)
        return []


def thread(entry_id: int) -> list[dict]:
    """An entry + its replies/corrections in order."""
    try:
        with db.get_conn() as c:
            rows = c.execute("SELECT * FROM collab_log WHERE id=%s OR parent_id=%s ORDER BY created_at",
                             (entry_id, entry_id)).fetchall()
        return [{**dict(r), "created_at": _iso(r["created_at"])} for r in rows]
    except Exception:
        return []


def mark_seen(reader: str, entry_id: int) -> None:
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO collab_read_marks (reader, entry_id) VALUES (%s,%s) "
                      "ON CONFLICT DO NOTHING", (reader, entry_id))
    except Exception:
        pass


# ── ACTIONS (attribution + flag Piolo's writes to Rydel) ─────────────────────

def record_action(actor: dict, description: str, link_type: str | None = None,
                  link_ref: str | None = None) -> None:
    """Attribute a write-action to its actor. Piolo's actions are FLAGGED to Rydel (his call):
    they land in the log as kind='action' so the digest + salience surface them to the owner."""
    who = (actor or {}).get("user", "rydel")
    add_entry(who, "action", description, link_type=link_type, link_ref=link_ref)


# ── QUEUE (flags → resolve → EDITH verifies) ─────────────────────────────────

def _live_flags(snap: dict | None = None) -> list[dict]:
    """The current open hygiene/DQ items, from the action feed (deterministic)."""
    try:
        import action_feed
        feed = action_feed.build_action_feed(snap)
        return [{"flag_id": _flag_id(it), "title": it["title"], "detail": it.get("action"),
                 "category": it.get("category")}
                for it in feed.get("items", [])
                if it.get("category") in ("reconciliation", "data_quality")]
    except Exception as e:
        logger.info("_live_flags failed: %s", e)
        return []


def _flag_id(item: dict) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", (item.get("category", "") + ":" + item.get("title", ""))[:120].lower())


# ── EVIDENCE SIGNATURES (queue fix 2026-08-10 — the done-that-sticks key) ────
# The old identity was slug(category+title) — the DISPLAY TITLE with its live
# numbers. Every metric drift (an MRR figure, a count, an age) re-opened
# already-resolved items and orphaned their resolutions (diagnosed in
# dashboard/PIOLO_QUEUE_DIAGNOSIS.md with prod evidence). The signature
# normalizes VOLATILE tokens (numbers/money/ages) out of title+action, so:
#   · routine drift (72,275 → 59,316; "1 deal" → still the same deal-set;
#     "pending 3d" → "4d") keeps the SAME signature → a dismissal STICKS;
#   · a genuinely new state (a new name joins the list, the fix path changes)
#     changes the signature → the item RE-ARMS with its new reason.
# "Done" means "I handled THIS state" — never "hide this subject forever".

def _normalize_evidence(s: str) -> str:
    """Volatile tokens (numbers, money, ages) are DROPPED, not replaced — a
    blank cell ('contract —') and a filled one ('contract 12500.0') are the
    same task-state; the stable words (names, fields, fix-paths) carry the
    identity. Trade-off accepted: two items distinguished ONLY by a bare
    number would collide — no queue category does that today."""
    import re
    s = (s or "").lower()
    s = re.sub(r"\$?\s*\d[\d,\.]*\s*k?\b", " ", s)     # money/counts/ages dropped
    s = re.sub(r"[^a-z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def flag_signature(item: dict) -> str:
    import hashlib
    basis = (item.get("category", "") + "|" + _normalize_evidence(item.get("title", ""))
             + "|" + _normalize_evidence(item.get("detail") or item.get("action") or ""))
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


# ── CLIENT LIFECYCLE (relevance signal — IDs/lifecycle, not name guesses) ────

def _churned_subjects() -> dict:
    """{normalized-name: churn_context} from the lifecycle engines: owner churn
    declarations (#135), the sheet's non-Active rows (renewal scan snapshot),
    and the confirmed-churned constants. Read-only; best-effort per source."""
    out: dict = {}
    try:
        import client_overrides as co
        for o in co.audit_log(200):
            if o.get("change_type") == "churn" and o.get("active", True):
                out[co._norm(o["client_name"])] = (
                    f"client churned {str(o.get('effective_date') or '')[:10]} (declared)")
    except Exception:
        pass
    try:
        import kv_store
        import client_overrides as co
        rows = (kv_store.get("renewal:last_scan") or {}).get("rows") or {}
        for nm, r in rows.items():
            st = (r.get("status") or "").strip().lower()
            if st and st != "active":
                out.setdefault(nm, f"client {st} per the MRR sheet")
    except Exception:
        pass
    try:
        import client_overrides as co
        from forward_mrr import KNOWN_CHURNED
        for n in KNOWN_CHURNED:
            out.setdefault(co._norm(n), "known churned client")
    except Exception:
        pass
    return {k: v for k, v in out.items() if len(k) >= 5}


def _subject_churn(item: dict, churned: dict) -> str | None:
    """The churn context if this item's subject is a churned client, else None."""
    try:
        import client_overrides as co
        blob = co._norm((item.get("title") or "") + " " + (item.get("detail") or ""))
    except Exception:
        return None
    for nm, ctx in churned.items():
        if nm in blob:
            return ctx
    return None


def _material(item: dict) -> bool:
    """THE MATERIALITY GUARD: money-bearing / close-level items NEVER age out
    quietly (the action-zone ruling — an $18k dateless close doesn't vanish
    because it's old). Floor configurable via kv queue:materiality_floor."""
    import re
    floor = 1000.0
    try:
        import kv_store
        floor = float(kv_store.get("queue:materiality_floor") or 1000.0)
    except Exception:
        pass
    blob = (item.get("title") or "") + " " + (item.get("detail") or "")
    for m in re.finditer(r"\$?\s*([\d][\d,]*(?:\.\d+)?)", blob):
        try:
            if float(m.group(1).replace(",", "")) >= floor:
                return True
        except ValueError:
            continue
    return bool(re.search(r"\bwon\b|\bclose\b|\bcontract\b", blob.lower()))


_STALE_DAYS = 90   # low-materiality items unactioned this long → aged (config-able)


def queue(snap: dict | None = None) -> list[dict]:
    """Piolo's queue — ONE generator, three lanes (queue fix 2026-08-10):
      ACTIVE — act-soon; the only lane counts/badges/EDITH report.
      AGED — demoted with a stamped reason (churned subject · stale+immaterial),
        collapsed view, one-click restore. Excluded ≠ deleted.
      DONE — dismissals keyed by EVIDENCE SIGNATURE: suppressed while the
        state is unchanged; a changed state re-arms as a NEW item. Un-dismiss
        restores. Resolved items whose flag stopped reproducing auto-verify
        ("resolved at source").
    Every lane transition is journaled once (collab_item_state.last_lane)."""
    migrate()
    live = _live_flags(snap)
    states: dict = {}
    by_sig: dict = {}
    try:
        with db.get_conn() as c:
            for r in c.execute("SELECT * FROM collab_queue").fetchall():
                states[r["flag_id"]] = dict(r)
                if r.get("signature"):
                    by_sig[r["signature"]] = dict(r)
    except Exception:
        pass

    # persisted first-seen + last-lane per signature (age must be REAL — the
    # old code stamped untouched items 'today' on every build)
    today = today_sydney()
    item_state: dict = {}
    try:
        with db.get_conn() as c:
            for r in c.execute("SELECT * FROM collab_item_state").fetchall():
                item_state[r["signature"]] = dict(r)
    except Exception:
        pass

    churned = _churned_subjects()
    out = []
    live_sigs = set()
    transitions = []
    for f in live:
        sig = flag_signature(f)
        live_sigs.add(sig)
        st = states.get(f["flag_id"]) or {}
        # legacy rows matched by flag_id get their signature backfilled — the
        # pre-fix 'partial' nag rows convert to proper suppressions
        if st and not st.get("signature"):
            try:
                with db.get_conn() as c:
                    c.execute("UPDATE collab_queue SET signature=%s WHERE flag_id=%s",
                              (sig, f["flag_id"]))
                st["signature"] = sig
                by_sig[sig] = st
            except Exception:
                pass
        srow = by_sig.get(sig) or st
        ist = item_state.get(sig)
        first_seen = (ist or {}).get("first_seen") or today
        if ist is None:
            try:
                with db.get_conn() as c:
                    c.execute("INSERT INTO collab_item_state (signature, first_seen) "
                              "VALUES (%s,%s) ON CONFLICT (signature) DO NOTHING",
                              (sig, today))
            except Exception:
                pass
        age_days = (today - first_seen).days if hasattr(first_seen, "toordinal") else 0
        material = _material(f)

        # lane classification
        lane, lane_reason = "active", None
        if srow.get("status") in ("resolved", "verified"):
            lane = "done"
            lane_reason = ("resolved — source unchanged (suppressed; re-arms if "
                           "the state changes)")
        elif srow.get("lane_override") == "active":
            lane, lane_reason = "active", "restored by owner"
        else:
            churn_ctx = _subject_churn(f, churned)
            if churn_ctx:
                lane, lane_reason = "aged", f"{churn_ctx} — archaeology, not a task"
            elif age_days > _STALE_DAYS and not material:
                lane, lane_reason = "aged", (f"unactioned {age_days}d and below the "
                                             f"materiality floor")
        if lane != "aged" and lane != "done" and material and age_days > _STALE_DAYS:
            lane_reason = f"{age_days}d old but MATERIAL — stays active (money guard)"

        prev_lane = (ist or {}).get("last_lane")
        if prev_lane != lane:
            transitions.append((sig, lane, lane_reason, f.get("title", "")[:80]))
        out.append({**f, "signature": sig, "lane": lane, "lane_reason": lane_reason,
                    "material": material, "age_days": age_days,
                    "first_seen": str(first_seen),
                    "status": srow.get("status", "open"),
                    "resolution": srow.get("resolution"),
                    "resolved_by": srow.get("resolved_by"),
                    "verification": srow.get("verification"),
                    "still_present": True})

    # dismissals whose signature no longer reproduces → RESOLVED AT SOURCE
    # (auto-verified, Done view) — never left hanging, never silently dropped
    for sig, srow in by_sig.items():
        if sig in live_sigs or srow.get("status") not in ("resolved", "partial"):
            continue
        if srow.get("status") != "verified":
            try:
                with db.get_conn() as c:
                    c.execute("UPDATE collab_queue SET status='verified', "
                              "verification=%s, verified_at=now(), updated_at=now() "
                              "WHERE flag_id=%s",
                              ("✓ verified — resolved at source; the flag no longer "
                               "reproduces", srow["flag_id"]))
            except Exception:
                pass
        out.append({"flag_id": srow["flag_id"], "signature": sig,
                    "title": srow.get("title", sig), "category": srow.get("category"),
                    "lane": "done", "lane_reason": "resolved at source (auto-verified)",
                    "status": "verified", "resolution": srow.get("resolution"),
                    "resolved_by": srow.get("resolved_by"),
                    "verification": "✓ verified — resolved at source; the flag no "
                                    "longer reproduces",
                    "still_present": False})

    # journal lane transitions ONCE (not per build)
    for sig, lane, reason, title in transitions:
        try:
            with db.get_conn() as c:
                c.execute("UPDATE collab_item_state SET last_lane=%s WHERE signature=%s",
                          (lane, sig))
            if lane in ("aged", "done"):
                record_action({"user": "edith", "role": "system"},
                              f"queue: “{title}” → {lane}"
                              + (f" ({reason})" if reason else ""),
                              link_type="queue", link_ref=sig)
        except Exception:
            pass
    return out


def queue_lanes(snap: dict | None = None) -> dict:
    """The lane split every surface reads: active (the real count), aged, done."""
    q = queue(snap)
    return {"active": [i for i in q if i["lane"] == "active"],
            "aged": [i for i in q if i["lane"] == "aged"],
            "done": [i for i in q if i["lane"] == "done"]}


def resolve_item(flag_id: str, note: str, actor: dict) -> dict:
    """Piolo marks a queue item done. QUEUE FIX 2026-08-10: the dismissal keys
    to the item's EVIDENCE SIGNATURE and the generator SUPPRESSES it into the
    Done view — it clears NOW and stays cleared while the state is unchanged.
    If the underlying facts change (new signature), the item re-arms as new.
    EDITH's verification still runs: once the flag stops reproducing at source,
    the dismissal upgrades to verified automatically (inside queue())."""
    migrate()
    who = (actor or {}).get("user", "piolo")
    live = {f["flag_id"]: f for f in _live_flags()}
    item = live.get(flag_id)
    title = (item or {}).get("title", flag_id)
    sig = flag_signature(item) if item else None
    try:
        with db.get_conn() as c:
            c.execute(
                "INSERT INTO collab_queue (flag_id, title, status, resolution, resolved_by, "
                "resolved_at, signature, verification) "
                "VALUES (%s,%s,'resolved',%s,%s,now(),%s,%s) ON CONFLICT (flag_id) DO UPDATE SET "
                "status='resolved', resolution=EXCLUDED.resolution, resolved_by=EXCLUDED.resolved_by, "
                "resolved_at=now(), signature=EXCLUDED.signature, "
                "verification=EXCLUDED.verification, lane_override=NULL, updated_at=now()",
                (flag_id, title, note, who, sig,
                 "resolved — suppressed while this state holds; EDITH verifies "
                 "once the source changes"))
    except Exception as e:
        logger.warning("resolve_item failed: %s", e)
        return {"ok": False}
    record_action(actor, f"resolved queue item “{title}”: {note}", link_type="flag", link_ref=flag_id)
    return {"ok": True, "flag_id": flag_id, "signature": sig, "status": "resolved",
            "suppressed": True}


def un_dismiss(flag_id: str, actor: dict) -> dict:
    """Reverse a dismissal — the item returns to ACTIVE. Journaled. Owner-side
    admin per the access matrix (the route gates it)."""
    migrate()
    try:
        with db.get_conn() as c:
            row = c.execute("SELECT * FROM collab_queue WHERE flag_id=%s",
                            (flag_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "no dismissal recorded for that item"}
            c.execute("UPDATE collab_queue SET status='open', verification=NULL, "
                      "updated_at=now() WHERE flag_id=%s", (flag_id,))
    except Exception as e:
        logger.warning("un_dismiss failed: %s", e)
        return {"ok": False, "error": str(e)[:80]}
    record_action(actor, f"un-dismissed queue item “{(dict(row).get('title') or flag_id)[:80]}”",
                  link_type="queue", link_ref=flag_id)
    return {"ok": True}


def restore_to_active(signature: str, actor: dict) -> dict:
    """Owner overrides an AGED demotion — 'the system judged wrong'. Journaled,
    sticky (lane_override survives rebuilds)."""
    migrate()
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT flag_id FROM collab_queue WHERE signature=%s",
                          (signature,)).fetchone()
            if r:
                c.execute("UPDATE collab_queue SET lane_override='active', updated_at=now() "
                          "WHERE signature=%s", (signature,))
            else:
                c.execute("INSERT INTO collab_queue (flag_id, title, status, signature, "
                          "lane_override) VALUES (%s,%s,'open',%s,'active') "
                          "ON CONFLICT (flag_id) DO UPDATE SET lane_override='active', "
                          "signature=EXCLUDED.signature, updated_at=now()",
                          (f"sig:{signature}", f"(restored item {signature})", signature))
            c.execute("UPDATE collab_item_state SET last_lane='active' WHERE signature=%s",
                      (signature,))
    except Exception as e:
        logger.warning("restore_to_active failed: %s", e)
        return {"ok": False, "error": str(e)[:80]}
    record_action(actor, f"restored queue item {signature} to ACTIVE (override)",
                  link_type="queue", link_ref=signature)
    return {"ok": True}


def sentinel_watch() -> dict:
    """Queue-health watch (rides ad_sentinel L2): lane sizes + aged growth."""
    import kv_store
    lanes = queue_lanes()
    counts = {k: len(v) for k, v in lanes.items()}
    prev = kv_store.get("collab:queue_watch") or {}
    growth = counts["aged"] - int(prev.get("aged") or 0)
    kv_store.put("collab:queue_watch", {**counts, "at": str(today_sydney())})
    if growth >= 5:
        try:
            flags = kv_store.get("ads_truth:flags") or []
            flags.append({"metric": "ads_truth",
                          "reason": f"Piolo queue: aged lane grew by {growth} overnight "
                                    f"(now {counts['aged']}) — worth a look at the "
                                    f"demotion reasons"})
            kv_store.put("ads_truth:flags", flags[-60:])
        except Exception:
            pass
    return {**counts, "aged_growth": growth}


def verify_item(flag_id: str, snap: dict | None = None) -> dict:
    """EDITH re-checks the underlying condition against fresh data. The flag clears only if the
    condition is GONE — never on the resolver's say-so alone. Stated factually, not accusatorially."""
    still_live = flag_id in {f["flag_id"] for f in _live_flags(snap)}
    verification = ("✓ verified — the tracker no longer shows this; the flag has cleared."
                    if not still_live else
                    "⚠ still open — the data hasn’t changed yet (may need a resync, or the row didn’t "
                    "save). It stays until the tracker reflects it.")
    status = "verified" if not still_live else "partial"
    try:
        with db.get_conn() as c:
            c.execute("UPDATE collab_queue SET status=%s, verification=%s, verified_at=now(), "
                      "updated_at=now() WHERE flag_id=%s", (status, verification, flag_id))
    except Exception:
        pass
    return {"ok": True, "flag_id": flag_id, "status": status, "verification": verification}


def queue_count(snap: dict | None = None) -> int:
    """ACTIVE items only — 'Piolo has 6 tasks' means 6 real ones, never
    6 + 40 archaeology (queue fix 2026-08-10)."""
    return sum(1 for q in queue(snap) if q.get("lane") == "active")


# ── DIGEST (Rydel's "Piolo since you last looked" — watermarked) ─────────────

def digest(reader: str = "rydel", advance: bool = True) -> dict:
    """What Piolo has done/raised since Rydel last looked. Watermarked so it's not re-shown."""
    import kv_store
    wm = (kv_store.get("collab:digest_watermark") or {}).get(reader)
    entries = list_entries(start=wm, author="piolo", limit=100)
    entries = [e for e in entries if e["created_at"] != wm]     # strict after
    buckets = {"action": [], "done": [], "concern": [], "question": [], "suggestion": []}
    for e in entries:
        buckets.setdefault(e["kind"], []).append(e)
    if advance and entries:
        marks = kv_store.get("collab:digest_watermark") or {}
        marks[reader] = entries[0]["created_at"]      # newest (list is DESC)
        kv_store.put("collab:digest_watermark", marks)
    return {"since": wm, "count": len(entries), **{k: v for k, v in buckets.items()},
            "has_questions": bool(buckets["question"]), "has_concerns": bool(buckets["concern"])}


def digest_line() -> str | None:
    """A one-line salience headline for a new concern/question from Piolo (does NOT advance the wm)."""
    import kv_store
    wm = (kv_store.get("collab:salience_watermark") or {}).get("rydel")
    fresh = [e for e in list_entries(author="piolo", limit=20)
             if e["kind"] in ("concern", "question") and (not wm or e["created_at"] > wm)]
    if not fresh:
        return None
    e = fresh[0]
    return f"Piolo raised a {e['kind']}: {e['body'][:80]}"


def mark_salience_seen():
    import kv_store
    latest = list_entries(author="piolo", limit=1)
    if latest:
        m = kv_store.get("collab:salience_watermark") or {}
        m["rydel"] = latest[0]["created_at"]
        kv_store.put("collab:salience_watermark", m)


# ── FOREVER ARCHIVE — date browsing, search, month summary, journal, export ──

def month_summary(year: int, month: int) -> dict:
    import calendar
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d} 23:59:59"
    ents = list_entries(start=start, end=end, include_archived=True, limit=1000)
    by_kind = {}
    for e in ents:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    verified = 0
    for q in queue():
        if q.get("status") == "verified":
            verified += 1
    return {"period": f"{calendar.month_name[month]} {year}", "total": len(ents),
            "by_kind": by_kind, "verified_resolutions": verified}


def search(query: str, limit: int = 20) -> list[dict]:
    """Deterministic substring/trigram-ish search over the full archive (verbatim records)."""
    if not query or not db.db_configured():
        return []
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT * FROM collab_log WHERE body ILIKE %s ORDER BY created_at DESC LIMIT %s",
                (f"%{query.strip()}%", limit)).fetchall()
        return [{**dict(r), "created_at": _iso(r["created_at"])} for r in rows]
    except Exception as e:
        logger.info("search failed: %s", e)
        return []


def journal(start=None, end=None, role: str = "owner", limit: int = 100) -> list[dict]:
    """The unified company journal — a READ-ONLY union over existing audit trails in date order:
    work log + client write-back + target changes + incidents. No new write paths."""
    events: list[dict] = []
    for e in list_entries(start=start, end=end, limit=limit):
        events.append({"at": e["created_at"], "source": "worklog",
                       "who": e["author"], "text": f"[{e['kind']}] {e['body'][:120]}"})
    try:
        import client_overrides
        for o in client_overrides.audit_log(50):
            events.append({"at": _iso(o.get("created_at")), "source": "write-back",
                           "who": "rydel/piolo", "text": f"{o['client_name']} → {o['change_type']}"})
    except Exception:
        pass
    try:
        import incident_log
        for i in incident_log.recent(20):
            events.append({"at": i.get("ts"), "source": "incident", "who": "edith",
                           "text": f"incident: {i.get('claimed', '')[:80]}"})
    except Exception:
        pass
    events = [e for e in events if e.get("at")]
    events.sort(key=lambda x: str(x["at"]), reverse=True)
    return events[:limit]


def export_archive() -> dict:
    """Off-DB backup (dated JSON + CSV dump) so the archive survives a DB loss. Logged each run."""
    import csv
    import io
    import os
    ents = list_entries(include_archived=True, limit=100000)
    stamp = today_sydney().isoformat()
    out_dir = os.path.join(os.path.dirname(__file__), "archive_exports")
    dest = {"json": None, "csv": None, "rows": len(ents), "at": now_sydney().isoformat()}
    try:
        os.makedirs(out_dir, exist_ok=True)
        jp = os.path.join(out_dir, f"collab-archive-{stamp}.json")
        with open(jp, "w") as f:
            json.dump(ents, f, default=str, indent=2)
        dest["json"] = jp
        cp = os.path.join(out_dir, f"collab-archive-{stamp}.csv")
        with open(cp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "created_at", "author", "kind", "body",
                                              "link_type", "link_ref", "archived"])
            w.writeheader()
            for e in ents:
                w.writerow({k: e.get(k) for k in w.fieldnames})
        dest["csv"] = cp
    except Exception as e:
        logger.warning("export_archive failed: %s", e)
        dest["error"] = str(e)
    try:
        import kv_store
        logl = kv_store.get("collab:export_log") or []
        logl.append(dest)
        kv_store.put("collab:export_log", logl[-60:])
    except Exception:
        pass
    return dest


# ── EDITH as collaborator (chat handlers; entries are DATA, never instructions) ──

import re as _re
import datetime as _dt

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"]) if i}


def _range_from_text(low: str):
    """Resolve 'this week / June / July 2026 / last week' to (start, end) or (None, None)."""
    t = today_sydney()
    if "this week" in low or "week of" in low:
        start = t - _dt.timedelta(days=t.weekday())
        return str(start), None
    if "last week" in low:
        start = t - _dt.timedelta(days=t.weekday() + 7)
        return str(start), str(start + _dt.timedelta(days=6))
    if "today" in low:
        return str(t), None
    for name, mi in _MONTHS.items():
        if name in low:
            ym = _re.search(r"(20\d\d)", low)
            year = int(ym.group(1)) if ym else t.year
            import calendar
            return f"{year}-{mi:02d}-01", f"{year}-{mi:02d}-{calendar.monthrange(year, mi)[1]:02d} 23:59:59"
    return None, None


def handle_collab_command(text: str, actor: dict) -> tuple[str | None, bool]:
    """Deterministic collaboration queries + log writes. Actor-aware. Injection-safe."""
    if not text:
        return None, False
    low = text.lower()
    who = (actor or {}).get("user", "rydel")

    # write a log entry: "log done: reconciled Amex" / "note concern: 3 clients look churned"
    lm = _re.match(r"\s*(?:log|note|record)\s+(done|concern|question|suggestion)\s*[:\-]\s*(.+)",
                   text, _re.I)
    if lm:
        e = add_entry(who, lm.group(1).lower(), lm.group(2).strip())
        return (f"Logged your {lm.group(1).lower()}." if e else "Couldn't save that."), True

    # reply to Piolo: "reply to Piolo: yes treat Jagjeet as a renewal"
    rm = _re.match(r"\s*(?:reply|respond|tell piolo|message piolo)\b.*?[:\-]\s*(.+)", text, _re.I)
    if rm and ("piolo" in low or "reply" in low):
        e = add_entry(who, "reply", rm.group(1).strip(), link_type="thread")
        return ("Posted to Piolo — he'll see it on his next visit." if e else "Couldn't post that."), True

    # export the archive
    if _re.search(r"\bexport (the )?(archive|log|journal)\b|\bback ?up the (archive|log)\b", low):
        d = export_archive()
        return (f"Exported {d['rows']} entries to a dated dump ({d.get('json') and 'JSON+CSV'}). "
                "It's logged and reloadable if the DB is ever lost." if d.get("json")
                else "Export couldn't write the dump file — check the server."), True

    # my queue / what's in my queue — ACTIVE lane only; aged named separately
    if _re.search(r"\b(my queue|what'?s in (my|the) queue|piolo'?s queue|the queue|open (flags|items))\b", low):
        lanes = queue_lanes()
        act, aged = lanes["active"], lanes["aged"]
        if not act:
            tail = (f" ({len(aged)} aged/irrelevant item(s) sit in the collapsed "
                    f"view — ask for 'the aged queue' to hear them)") if aged else ""
            return f"Queue's clear — nothing active.{tail}", True
        lines = [f"• {x['title']}" + (f" — {x['detail']}" if x.get("detail") else "")
                 for x in act[:6]]
        tail = f"\n(+{len(aged)} aged/irrelevant, collapsed — not counted)" if aged else ""
        return f"{len(act)} active: \n" + "\n".join(lines) + tail, True

    # the aged / archaeology view on request
    if _re.search(r"\b(aged|archived|irrelevant|archaeolog\w*) (queue|items|flags)\b", low):
        aged = queue_lanes()["aged"]
        if not aged:
            return "Nothing in the aged view — every open item is live.", True
        lines = [f"• {x['title'][:80]} — {x.get('lane_reason')}" for x in aged[:8]]
        return (f"{len(aged)} aged/irrelevant (demoted with reasons, restorable):\n"
                + "\n".join(lines)), True

    # what did Piolo do / concerns / questions (+ optional date range)
    if _re.search(r"\bwhat did piolo\b|\bpiolo('?s)? (work|activity|do|done|log)\b|"
                  r"\b(concerns?|questions?|suggestions?) (from|by|piolo)\b|\bany concerns\b|"
                  r"\bwhat (has |did )?piolo\b", low):
        start, end = _range_from_text(low)
        kind = ("concern" if "concern" in low else "question" if "question" in low
                else "suggestion" if "suggest" in low else None)
        ents = list_entries(start=start, end=end, author="piolo", kind=kind, limit=15)
        if not ents:
            span = "in that period" if start else "recently"
            return f"Nothing from Piolo {span}.", True
        lines = [f"• [{e['kind']}] {e['body'][:90]} ({e['created_at'][:10]})" for e in ents[:8]]
        return (f"Piolo — {len(ents)} " + (f"{kind}s" if kind else "entries") + ":\n" + "\n".join(lines)), True

    # archive search: "when did we first notice X", "every concern about churn", "what did we resolve..."
    if _re.search(r"\b(when did (we|i)|first notice|every (concern|question|entry)|search the (log|archive)|"
                  r"what did (we|i) (resolve|flag|do))\b", low):
        start, end = _range_from_text(low)
        kw = _re.sub(r"\b(when did we first notice|search the (log|archive) for|every|show me|what did we|"
                     r"about|the|concern|question|first|notice)\b", " ", low).strip()
        hits = search(kw, 12) if len(kw) >= 3 else list_entries(start=start, end=end, limit=12)
        if not hits:
            return "Nothing in the archive matches that.", True
        return ("From the archive:\n" + "\n".join(
            f"• {h['created_at'][:10]} [{h['kind']}/{h['author']}] {h['body'][:90]}" for h in hits[:8])), True

    return None, False


