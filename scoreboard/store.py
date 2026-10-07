"""store.py — the scoreboard's OWN raw tables.

  sb_raw      (source, kind, id) → the record as the source returned it,
              with first_seen and synced_at. One row per source id, so a
              record pulled twice is still one row.
  sb_sync     (job) → last try, last success, rows, error — the freshness line.
  sb_journal  every human decision (a confirmed link, a confirmed figure),
              who made it, when, in their words. Append-only.

Postgres when configured (the existing db connection); an in-process dict
otherwise, so tests and local runs never touch production.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading

import db

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS sb_raw (
  source     TEXT NOT NULL,
  kind       TEXT NOT NULL,
  id         TEXT NOT NULL,
  data       JSONB NOT NULL,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  synced_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source, kind, id)
);
CREATE TABLE IF NOT EXISTS sb_sync (
  job        TEXT PRIMARY KEY,
  last_try   TIMESTAMPTZ,
  last_ok    TIMESTAMPTZ,
  rows       INTEGER,
  error      TEXT,
  note       TEXT
);
CREATE TABLE IF NOT EXISTS sb_journal (
  n          SERIAL PRIMARY KEY,
  at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor      TEXT NOT NULL,
  action     TEXT NOT NULL,
  key        TEXT NOT NULL,
  data       JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS sb_lease (
  job        TEXT PRIMARY KEY,
  until      TIMESTAMPTZ NOT NULL
);
"""

_lock = threading.Lock()
_MEM: dict = {"raw": {}, "sync": {}, "journal": []}
_migrated = False


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def use_db() -> bool:
    return db.db_configured()


def migrate() -> bool:
    global _migrated
    if not use_db():
        return False
    if _migrated:
        return True
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        _migrated = True
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("scoreboard migrate failed: %s", e)
        return False


def reset_memory() -> None:
    """Tests only."""
    with _lock:
        _MEM["raw"].clear(); _MEM["sync"].clear(); _MEM["journal"].clear()
        _MEM.pop("lease", None)


# ── raw ─────────────────────────────────────────────────────────────────────

def upsert(source: str, kind: str, records: dict[str, dict]) -> int:
    """Write records {id: data}. Same id = same row (updated, first_seen kept)."""
    if not records:
        return 0
    now = _now()
    if use_db() and migrate():
        with db.get_conn() as c:
            with c.cursor() as cur:
                cur.executemany(
                    "INSERT INTO sb_raw (source, kind, id, data) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (source, kind, id) DO UPDATE SET data=EXCLUDED.data, synced_at=now()",
                    [(source, kind, str(k), json.dumps(v, default=str)) for k, v in records.items()])
        return len(records)
    with _lock:
        tab = _MEM["raw"].setdefault((source, kind), {})
        for k, v in records.items():
            prev = tab.get(str(k))
            tab[str(k)] = {"data": json.loads(json.dumps(v, default=str)),
                           "first_seen": prev["first_seen"] if prev else now, "synced_at": now}
    return len(records)


def insert_if_absent(source: str, kind: str, rid: str, data: dict) -> bool:
    """For first-seen facts that must never move (the stage recorder)."""
    if use_db() and migrate():
        with db.get_conn() as c:
            cur = c.execute("INSERT INTO sb_raw (source, kind, id, data) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT DO NOTHING", (source, kind, rid, json.dumps(data, default=str)))
            return bool(getattr(cur, "rowcount", 0))
    with _lock:
        tab = _MEM["raw"].setdefault((source, kind), {})
        if rid in tab:
            return False
        tab[rid] = {"data": data, "first_seen": _now(), "synced_at": _now()}
        return True


def read(source: str, kind: str) -> dict[str, dict]:
    if use_db() and migrate():
        with db.get_conn() as c:
            rows = c.execute("SELECT id, data FROM sb_raw WHERE source=%s AND kind=%s",
                             (source, kind)).fetchall()
        return {r["id"]: r["data"] for r in rows}
    with _lock:
        return {k: v["data"] for k, v in (_MEM["raw"].get((source, kind)) or {}).items()}


def counts() -> list[dict]:
    if use_db() and migrate():
        with db.get_conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT source, kind, count(*) AS n, max(synced_at) AS latest FROM sb_raw "
                "GROUP BY source, kind ORDER BY source, kind").fetchall()]
    with _lock:
        return [{"source": s, "kind": k, "n": len(t)} for (s, k), t in sorted(_MEM["raw"].items())]


# ── leases (two web workers → one runner per job) ──────────────────────────

def claim(job: str, seconds: int) -> bool:
    if use_db() and migrate():
        with db.get_conn() as c:
            r = c.execute(
                "INSERT INTO sb_lease (job, until) VALUES (%s, now() + make_interval(secs => %s)) "
                "ON CONFLICT (job) DO UPDATE SET until = EXCLUDED.until WHERE sb_lease.until < now() "
                "RETURNING job", (job, seconds)).fetchone()
        return bool(r)
    with _lock:
        leases = _MEM.setdefault("lease", {})
        t = dt.datetime.now(dt.timezone.utc)
        if leases.get(job) and leases[job] > t:
            return False
        leases[job] = t + dt.timedelta(seconds=seconds)
        return True


# ── sync state ──────────────────────────────────────────────────────────────

def mark(job: str, ok: bool, rows: int | None = None, error: str | None = None,
         note: str | None = None) -> None:
    now = _now()
    if use_db() and migrate():
        with db.get_conn() as c:
            c.execute(
                "INSERT INTO sb_sync (job, last_try, last_ok, rows, error, note) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (job) DO UPDATE SET last_try=EXCLUDED.last_try, "
                "last_ok=COALESCE(EXCLUDED.last_ok, sb_sync.last_ok), "
                "rows=COALESCE(EXCLUDED.rows, sb_sync.rows), error=EXCLUDED.error, "
                "note=COALESCE(EXCLUDED.note, sb_sync.note)",
                (job, now, now if ok else None, rows, None if ok else (error or "failed")[:400], note))
        return
    with _lock:
        prev = _MEM["sync"].get(job) or {}
        _MEM["sync"][job] = {"job": job, "last_try": now, "last_ok": now if ok else prev.get("last_ok"),
                             "rows": rows if rows is not None else prev.get("rows"),
                             "error": None if ok else (error or "failed")[:400],
                             "note": note or prev.get("note")}


def sync_state() -> dict[str, dict]:
    if use_db() and migrate():
        with db.get_conn() as c:
            rows = c.execute("SELECT * FROM sb_sync").fetchall()
        return {r["job"]: {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
                for r in rows}
    with _lock:
        return {k: dict(v) for k, v in _MEM["sync"].items()}


# ── journal ─────────────────────────────────────────────────────────────────

def journal_add(actor: str, action: str, key: str, data: dict) -> dict:
    rec = {"at": _now(), "actor": actor, "action": action, "key": key, "data": data}
    if use_db() and migrate():
        with db.get_conn() as c:
            c.execute("INSERT INTO sb_journal (actor, action, key, data) VALUES (%s,%s,%s,%s)",
                      (actor, action, key, json.dumps(data, default=str)))
        return rec
    with _lock:
        _MEM["journal"].append(rec)
    return rec


def journal() -> list[dict]:
    if use_db() and migrate():
        with db.get_conn() as c:
            rows = c.execute("SELECT at, actor, action, key, data FROM sb_journal ORDER BY n").fetchall()
        return [{**dict(r), "at": r["at"].isoformat()} for r in rows]
    with _lock:
        return list(_MEM["journal"])


def decisions() -> dict[str, dict]:
    """The latest journaled decision per key (a later entry supersedes; an
    'undo' entry removes)."""
    out: dict[str, dict] = {}
    for j in journal():
        if j["action"] == "undo":
            out.pop(j["key"], None)
        else:
            out[j["key"]] = j
    return out
