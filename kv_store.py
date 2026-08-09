"""
kv_store.py
-----------
Tiny Postgres key→JSON store for small persistent app state that must survive refreshes and
redeploys (Railway local files don't) — greeting watermark, told-events, location override,
recent greeting shapes. Namespaced keys, JSONB values. Degrades to an in-process dict if
Postgres is unavailable (so local/dev never crashes; state just isn't durable there).
"""
from __future__ import annotations

import json
import logging

import db

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS kv_store (
  k          TEXT PRIMARY KEY,
  v          JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_MEM: dict[str, object] = {}   # fallback when no DB


def _migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("kv_store migrate failed: %s", e)
        return False


def get(key: str, default=None):
    if not db.db_configured():
        return _MEM.get(key, default)
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT v FROM kv_store WHERE k=%s", (key,)).fetchone()
        return r["v"] if r else default
    except Exception:
        return _MEM.get(key, default)


def put(key: str, value) -> None:
    _MEM[key] = value
    if not db.db_configured():
        return
    _migrate()
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO kv_store (k, v) VALUES (%s, %s) "
                      "ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v, updated_at=now()",
                      (key, json.dumps(value)))
    except Exception as e:
        logger.warning("kv_store put(%s) failed: %s", key, e)


def put_if_absent(key: str, value) -> bool:
    """ATOMIC set-if-absent — the single-flight claim primitive (audit F16).
    True = this caller claimed the key; False = someone else already holds it.
    Postgres INSERT … ON CONFLICT DO NOTHING is the atomicity; the in-memory
    fallback is best-effort (single-process anyway)."""
    if not db.db_configured():
        if key in _MEM:
            return False
        _MEM[key] = value
        return True
    _migrate()
    try:
        with db.get_conn() as c:
            cur = c.execute("INSERT INTO kv_store (k, v) VALUES (%s, %s) "
                            "ON CONFLICT (k) DO NOTHING", (key, json.dumps(value)))
            claimed = cur.rowcount == 1
        if claimed:
            _MEM[key] = value
        return claimed
    except Exception as e:
        # FAIL-CLOSED (review finding 9b): on a DB error we CANNOT know whether
        # someone else holds the claim — returning True in both workers is
        # exactly the double-run F16 exists to prevent. Skipping a run is the
        # cheaper failure; callers retry on their next tick.
        logger.warning("kv_store put_if_absent(%s) failed — claim REFUSED "
                       "(fail-closed): %s", key, e)
        return False


def delete(key: str) -> None:
    _MEM.pop(key, None)
    if not db.db_configured():
        return
    try:
        with db.get_conn() as c:
            c.execute("DELETE FROM kv_store WHERE k=%s", (key,))
    except Exception:
        pass
