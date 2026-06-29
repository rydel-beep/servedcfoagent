"""
sheet_mirror.py
---------------
Live-backed cache: a faithful Postgres MIRROR of the source sheet tabs.

  RAW SHEETS → SYNC JOB (only thing hitting the Sheets API; by tab NAME)
            → POSTGRES MIRROR (sheet_mirror: raw rows as jsonb) → EDITH reads the mirror

Why: EDITH used to read a slow periodic snapshot, so recent sheet edits (e.g. the last
few closes) were invisible until the next rebuild. The mirror gives DB-speed reads AND
near-live accuracy: a tight sync loop (~90s) keeps it current, and a voice/text "resync"
forces it instantly. Only the sync touches the API (no per-question Sheets pull).

CONTRACT:
- Faithful copy — the sync stores RAW rows (no business-logic transform). Metrics parse
  the mirror exactly as they parsed the CSV.
- Loud failure — a failed sync keeps the last-good mirror and flags sync_state; never a
  silent stale number. One tab failing never breaks the others.
- Graceful Postgres-down — read_tab returns None so callers fall back to a direct live read.
- Read-only from Sheets. Reuses the existing memory Postgres (db.get_conn()).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import threading
import time

import requests

import db
from config import (SHEET_CONFIG, FINANCE_SHEET_CONFIG, HTTP_TIMEOUT,
                    SHEET_SYNC_INTERVAL_SECONDS, SHEET_MIRROR_ENABLED,
                    SHEET_MIRROR_MAX_STALE_SECONDS)
from helpers import now_sydney

logger = logging.getLogger(__name__)

# ── Mirrored tabs (focused scope) ─────────────────────────────────────────────
# Read BY NAME where the name is correct; BY GID only where the name points at the
# WRONG tab (Health: the tab literally named "Health" is an MRR-projection view —
# the real roster is gid 1407663952, proven in the data-accuracy round). The mirror
# must faithfully copy what each consumer actually reads.
MIRRORED_TABS: dict[str, dict] = {
    "ltc_tracker":       {"book": SHEET_CONFIG["sheet_id"],         "tab": "Lead-to-Cash Tracker",
                          "feeds": "funnel (closes/leads/sets/shows), cash collected, closer comms, won deals"},
    "team_scorecard":    {"book": SHEET_CONFIG["sheet_id"],         "tab": "Team Scorecard",
                          "feeds": "computed funnel cells, setter scorecard payout"},
    "setter_payout_log": {"book": SHEET_CONFIG["sheet_id"],         "tab": "SETTER PAYOUT LOG",
                          "feeds": "setter commission ($50/set + 5% cash) for loaded CAC"},
    "setter_deep_dive":  {"book": SHEET_CONFIG["sheet_id"],         "tab": "Setter Deep-Dive",
                          "feeds": "setter activity (dials, speed-to-lead)"},
    "health":            {"book": FINANCE_SHEET_CONFIG["sheet_id"], "tab": "Health (roster)",
                          "gid": 1407663952,
                          "feeds": "active-client roster, current/next MRR, churn risk"},
    "recognized":        {"book": FINANCE_SHEET_CONFIG["sheet_id"], "tab": "RECOGNIZED",
                          "feeds": "recognized revenue, forward-MRR (churn-adjusted)"},
    "salary":            {"book": FINANCE_SHEET_CONFIG["sheet_id"], "tab": "SALARY",
                          "feeds": "payroll baseline, team_model, true_team_cost, burn"},
}

_sync_lock = threading.Lock()      # background loop + manual resync must not collide
_loop_started = False
_loop_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS sheet_mirror (
  tab        text  NOT NULL,
  row_index  int   NOT NULL,
  cells      jsonb NOT NULL,
  row_hash   text  NOT NULL,
  synced_at  timestamptz NOT NULL,
  PRIMARY KEY (tab, row_index)
);
CREATE TABLE IF NOT EXISTS sheet_sync_state (
  tab            text PRIMARY KEY,
  book_id        text,
  tab_name       text,
  feeds          text,
  last_sync_at            timestamptz,
  last_change_detected_at timestamptz,
  last_sync_status text,
  row_count      int,
  content_hash   text,
  last_error     text
);
"""


def migrate() -> bool:
    """Idempotent: create the mirror tables. Safe to re-run. False if DB unavailable."""
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as conn:
            conn.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("sheet_mirror migrate failed: %s", e)
        return False


# ── Live fetch (the only Sheets API hit) ─────────────────────────────────────

def _live_fetch(book_id: str, tab_name: str, gid: int | None = None) -> list[list[str]]:
    """Read a tab as raw rows — by gid when given (name points at the wrong tab),
    else by name. Raises on non-200 / network error."""
    if gid is not None:
        url = f"https://docs.google.com/spreadsheets/d/{book_id}/export?format=csv&gid={gid}"
    else:
        url = (f"https://docs.google.com/spreadsheets/d/{book_id}"
               f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab_name)}")
    backoff = 2.0
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
            if resp.status_code == 200:
                return list(csv.reader(io.StringIO(resp.text)))
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
            if resp.status_code not in (429, 500, 502, 503):
                raise last_exc
        except requests.RequestException as e:
            last_exc = e
        if attempt < 2:
            time.sleep(backoff)
            backoff *= 2
    raise last_exc or RuntimeError("fetch failed")


def _row_hash(row: list[str]) -> str:
    return hashlib.md5(json.dumps(row, ensure_ascii=False).encode("utf-8")).hexdigest()


def _content_hash(rows: list[list[str]]) -> str:
    return hashlib.md5(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


# ── Sync one tab (atomic, loud on failure) ───────────────────────────────────

def sync_tab(key: str) -> dict:
    """Pull a tab live and reconcile the mirror. Returns a small status dict.

    Unchanged (same content hash) → only bump last_sync_at (checked, not changed).
    Changed → replace the tab's mirror rows atomically + stamp last_change_detected_at.
    Failure → keep the last-good mirror, set last_sync_status=failed + last_error (loud).
    """
    meta = MIRRORED_TABS.get(key)
    if not meta:
        return {"tab": key, "status": "unknown_tab"}
    if not db.db_configured():
        return {"tab": key, "status": "db_unavailable"}

    now = now_sydney()
    try:
        rows = _live_fetch(meta["book"], meta["tab"], meta.get("gid"))
    except Exception as e:
        # Loud failure — keep last-good mirror, flag sync_state.
        try:
            with db.get_conn() as conn:
                conn.execute(
                    """INSERT INTO sheet_sync_state (tab, book_id, tab_name, feeds,
                         last_sync_at, last_sync_status, last_error)
                       VALUES (%s,%s,%s,%s,%s,'failed',%s)
                       ON CONFLICT (tab) DO UPDATE SET
                         last_sync_at=EXCLUDED.last_sync_at,
                         last_sync_status='failed', last_error=EXCLUDED.last_error""",
                    (key, meta["book"], meta["tab"], meta["feeds"], now, str(e)[:300]),
                )
        except Exception as e2:
            logger.warning("sync_tab %s state-write failed: %s", key, e2)
        logger.warning("sync_tab %s fetch failed: %s", key, e)
        return {"tab": key, "status": "failed", "error": str(e)[:160]}

    chash = _content_hash(rows)
    try:
        with db.get_conn() as conn:
            cur = conn.execute("SELECT content_hash FROM sheet_sync_state WHERE tab=%s", (key,))
            prev = cur.fetchone()
            unchanged = bool(prev and prev.get("content_hash") == chash)
            if unchanged:
                conn.execute(
                    "UPDATE sheet_sync_state SET last_sync_at=%s, last_sync_status='ok', "
                    "last_error=NULL, row_count=%s WHERE tab=%s",
                    (now, len(rows), key),
                )
                return {"tab": key, "status": "ok", "changed": False, "rows": len(rows)}

            # Changed → atomic replace (handles inserts, updates, AND removals).
            with conn.transaction():
                conn.execute("DELETE FROM sheet_mirror WHERE tab=%s", (key,))
                with conn.cursor() as c2:
                    c2.executemany(
                        "INSERT INTO sheet_mirror (tab,row_index,cells,row_hash,synced_at) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        [(key, i, json.dumps(r, ensure_ascii=False), _row_hash(r), now)
                         for i, r in enumerate(rows)],
                    )
                conn.execute(
                    """INSERT INTO sheet_sync_state (tab, book_id, tab_name, feeds,
                         last_sync_at, last_change_detected_at, last_sync_status, row_count,
                         content_hash, last_error)
                       VALUES (%s,%s,%s,%s,%s,%s,'ok',%s,%s,NULL)
                       ON CONFLICT (tab) DO UPDATE SET
                         last_sync_at=EXCLUDED.last_sync_at,
                         last_change_detected_at=EXCLUDED.last_change_detected_at,
                         last_sync_status='ok', row_count=EXCLUDED.row_count,
                         content_hash=EXCLUDED.content_hash, last_error=NULL,
                         book_id=EXCLUDED.book_id, tab_name=EXCLUDED.tab_name, feeds=EXCLUDED.feeds""",
                    (key, meta["book"], meta["tab"], meta["feeds"], now, now, len(rows), chash),
                )
            return {"tab": key, "status": "ok", "changed": True, "rows": len(rows)}
    except Exception as e:
        logger.warning("sync_tab %s db write failed: %s", key, e)
        return {"tab": key, "status": "db_error", "error": str(e)[:160]}


def sync_all(tabs: list[str] | None = None) -> dict:
    """Sync every mirrored tab (or a subset). Guarded so background + manual don't collide."""
    keys = tabs or list(MIRRORED_TABS.keys())
    migrate()
    with _sync_lock:
        results = {k: sync_tab(k) for k in keys}
    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    changed = [k for k, r in results.items() if r.get("changed")]
    return {"synced": len(keys), "ok": ok, "changed": changed, "results": results,
            "as_of": now_sydney().isoformat()}


# ── Read from the mirror (DB-speed; None → caller falls back to live) ─────────

def read_tab(key: str) -> list[list[str]] | None:
    """Return a tab's rows from the mirror as raw rows, or None if unavailable/stale."""
    if not (SHEET_MIRROR_ENABLED and db.db_configured()):
        return None
    try:
        with db.get_conn() as conn:
            st = conn.execute(
                "SELECT last_sync_at, last_sync_status FROM sheet_sync_state WHERE tab=%s", (key,)
            ).fetchone()
            if not st or not st.get("last_sync_at"):
                return None
            age = (now_sydney() - st["last_sync_at"]).total_seconds()
            if age > SHEET_MIRROR_MAX_STALE_SECONDS:
                logger.info("mirror %s stale (%.0fs) — caller should live-fetch", key, age)
                return None
            rows = conn.execute(
                "SELECT cells FROM sheet_mirror WHERE tab=%s ORDER BY row_index", (key,)
            ).fetchall()
            if not rows:
                return None
            return [r["cells"] for r in rows]
    except Exception as e:
        logger.info("mirror read %s failed (%s) — caller live-fetches", key, e)
        return None


_NAME_TO_KEY = {m["tab"]: k for k, m in MIRRORED_TABS.items() if not m.get("gid")}
_GID_TO_KEY = {m["gid"]: k for k, m in MIRRORED_TABS.items() if m.get("gid")}


def read_by_name(tab_name: str) -> list[list[str]] | None:
    """Mirror rows for a tab the consumer fetches BY NAME (None → live fallback)."""
    key = _NAME_TO_KEY.get(tab_name)
    return read_tab(key) if key else None


def read_by_gid(gid: int) -> list[list[str]] | None:
    """Mirror rows for a tab the consumer fetches BY GID (None → live fallback)."""
    key = _GID_TO_KEY.get(gid)
    return read_tab(key) if key else None


def get_sources() -> list[dict]:
    """sync_state for the transparency panel + voice 'what's plugged into your system'."""
    out = []
    if not db.db_configured():
        return out
    try:
        with db.get_conn() as conn:
            for r in conn.execute(
                "SELECT * FROM sheet_sync_state ORDER BY tab"
            ).fetchall():
                d = dict(r)
                for k in ("last_sync_at", "last_change_detected_at"):
                    if d.get(k) is not None:
                        d[k] = d[k].isoformat()
                out.append(d)
    except Exception as e:
        logger.info("get_sources failed: %s", e)
    return out


# ── Voice/text commands: immediate resync + "what's plugged in" ──────────────
import re as _re

_RESYNC_RE = _re.compile(
    r"\b(re-?sync|sync (now|your data|the (tracker|sheets|data))|refresh your data|"
    r"pull (the )?latest|update your data|get current)\b", _re.I)
_SOURCES_RE = _re.compile(
    r"(what('?s| is| are)?.*(plugged|reading|data sources?|connected to|hooked))|"
    r"(what data are you (reading|using|on))|(how fresh.*data)|"
    r"(is your data (current|fresh|up.?to.?date|stale))", _re.I)


def handle_resync_command(text: str, rebuild_snapshot: bool = True) -> tuple[str | None, bool]:
    """Immediate sync of all mirrored tabs (+ snapshot rebuild) on a voice/text 'resync'.

    Returns (reply, handled). handled=False → not a resync command (fall through).
    """
    if not text or not _RESYNC_RE.search(text):
        return None, False
    res = sync_all()
    latest = None
    if rebuild_snapshot:
        try:
            from snapshot import build_snapshot
            snap = build_snapshot()
            import app as _app
            _app._current_snapshot = snap
            wb = ((snap.get("sales") or {}).get("won_businesses") or [])
            dated = [w for w in wb if w.get("close_date")]
            if dated:
                w = sorted(dated, key=lambda x: str(x.get("close_date")))[-1]
                latest = f"{w.get('name')} ({w.get('close_date')})"
        except Exception as e:
            logger.warning("resync snapshot rebuild failed: %s", e)
    parts = []
    for k, r in res["results"].items():
        nm = MIRRORED_TABS[k]["tab"]
        tag = " (updated)" if r.get("changed") else (" ⚠" if r.get("status") != "ok" else "")
        parts.append(f"{nm} {r.get('rows', '?')} rows{tag}")
    reply = "Synced — " + "; ".join(parts) + "."
    if latest:
        reply += f" Latest close: {latest}."
    # Latest LEAD entered (distinct from latest close) — the leads-visibility gap.
    try:
        from leads_view import latest_lead
        ll = latest_lead()
        if ll:
            biz = f" ({ll['business']})" if ll.get("business") and ll["business"] != ll["name"] else ""
            reply += (f" Latest lead: {ll['name']}{biz} — {ll['date']}"
                      + (f" {ll['time']}" if ll.get("time") else "") + ".")
    except Exception as e:
        logger.info("resync latest_lead unavailable: %s", e)
    return reply, True


def handle_sources_query(text: str) -> tuple[str | None, bool]:
    """Answer 'what's plugged into your system / is your data current' from sync_state."""
    if not text or not _SOURCES_RE.search(text):
        return None, False
    srcs = get_sources()
    if not srcs:
        return ("My data layer (the Postgres mirror) isn't reporting yet — I'm reading sheets "
                "live in the meantime."), True
    failed = [s for s in srcs if s.get("last_sync_status") != "ok"]
    bits = []
    for s in srcs:
        when = (s.get("last_sync_at") or "")[:16].replace("T", " ")
        flag = "" if s.get("last_sync_status") == "ok" else " ⚠ FAILED"
        bits.append(f"{s.get('tab_name')} ({s.get('row_count')} rows, synced {when}){flag}")
    head = ("All sources current. " if not failed
            else f"Heads up — {len(failed)} source(s) failed to sync. ")
    return head + "I'm reading: " + "; ".join(bits) + ".", True


# ── Background sync loop ──────────────────────────────────────────────────────

def _loop():
    logger.info("sheet_mirror sync loop started (every %ds)", SHEET_SYNC_INTERVAL_SECONDS)
    while True:
        try:
            sync_all()
        except Exception as e:
            logger.warning("sheet_mirror loop iteration failed: %s", e)
        time.sleep(SHEET_SYNC_INTERVAL_SECONDS)


def start_sync_loop() -> bool:
    """Start the background sync thread once. No-op if disabled or already running."""
    global _loop_started
    if not (SHEET_MIRROR_ENABLED and db.db_configured()):
        return False
    with _loop_lock:
        if _loop_started:
            return False
        _loop_started = True
        threading.Thread(target=_loop, daemon=True, name="sheet-mirror-sync").start()
        return True
