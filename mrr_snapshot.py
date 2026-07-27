"""
mrr_snapshot.py
--------------
MRR snapshotting (G3) — persist a monthly + quarter-boundary snapshot of roster MRR to Postgres so
future quarters get REAL opening->closing MRR bridges (today only the closing side is known live).
Also derives churned MRR per window from the client write-back audit (churn events carry client +
MRR + date) + roster diffs, giving the bridge its churn leg.

"Start now": the first snapshot is taken on boot; the report states from which date full bridges
become available.
"""
from __future__ import annotations

import logging

import db
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS mrr_snapshots (
    snap_date    DATE PRIMARY KEY,
    current_mrr  DOUBLE PRECISION,
    client_count INTEGER,
    per_client   JSONB,
    taken_at     TIMESTAMPTZ NOT NULL DEFAULT now()
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
        logger.warning("mrr_snapshot migrate failed: %s", e)
        return False


def take_snapshot(force: bool = False) -> dict:
    """Persist today's roster MRR snapshot (idempotent per day). Called on boot + monthly/quarter
    boundaries by the refresh loop."""
    if not db.db_configured():
        return {"ok": False, "reason": "db not configured"}
    migrate()
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        health = snap.get("client_health") or {}
        current_mrr = health.get("current_mrr")
        clients = health.get("clients") or []
        per_client = {}
        for cli in clients:
            nm = (cli.get("name") or cli.get("business") or "").strip()
            if nm:
                per_client[nm] = cli.get("current_mrr") or cli.get("mrr")
        today = today_sydney()
        with db.get_conn() as c:
            existing = c.execute("SELECT 1 FROM mrr_snapshots WHERE snap_date=%s", (today,)).fetchone()
            if existing and not force:
                return {"ok": True, "skipped": "already snapshotted today"}
            c.execute(
                """INSERT INTO mrr_snapshots (snap_date, current_mrr, client_count, per_client, taken_at)
                   VALUES (%s,%s,%s,%s, now())
                   ON CONFLICT (snap_date) DO UPDATE SET
                     current_mrr=EXCLUDED.current_mrr, client_count=EXCLUDED.client_count,
                     per_client=EXCLUDED.per_client, taken_at=now()""",
                (today, current_mrr, len(per_client), _json(per_client)))
        return {"ok": True, "date": str(today), "current_mrr": current_mrr, "clients": len(per_client)}
    except Exception as e:
        logger.exception("take_snapshot failed")
        return {"ok": False, "reason": str(e)}


def _json(o):
    import json
    return json.dumps(o)


def snapshot_on_date(d) -> dict | None:
    """Nearest snapshot on or before date `d` (for a window's opening MRR)."""
    if not db.db_configured():
        return None
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT * FROM mrr_snapshots WHERE snap_date <= %s ORDER BY snap_date DESC LIMIT 1",
                          (str(d),)).fetchone()
            return dict(r) if r else None
    except Exception as e:
        logger.info("snapshot_on_date failed: %s", e)
        return None


def first_snapshot_date() -> str | None:
    if not db.db_configured():
        return None
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT min(snap_date) d FROM mrr_snapshots").fetchone()
            return str(r["d"]) if r and r["d"] else None
    except Exception:
        return None


def churn_mrr_in_window(start, end) -> dict:
    """Derive churned MRR in [start,end] from the client write-back audit (churn/downgrade events
    carry client + MRR delta + date). Returns {available, churn_mrr, events} — available:False
    (never a fabricated number) when the audit has no churn events for the window."""
    try:
        import client_overrides
        audit = client_overrides.audit_log(500) if hasattr(client_overrides, "audit_log") else []
        churn = 0.0
        events = []
        import datetime as dt
        w0 = dt.date.fromisoformat(str(start)[:10]); w1 = dt.date.fromisoformat(str(end)[:10])
        for a in audit or []:
            ct = (a.get("change_type") or "").lower()
            if "churn" not in ct and "downgrade" not in ct and "cancel" not in ct:
                continue
            when = a.get("created_at")
            try:
                wd = dt.date.fromisoformat(str(when)[:10])
            except Exception:
                continue
            if not (w0 <= wd <= w1):
                continue
            delta = a.get("mrr_delta") or a.get("mrr") or 0
            try:
                churn += abs(float(delta))
            except (TypeError, ValueError):
                pass
            events.append({"client": a.get("client_name"), "type": ct, "date": str(wd)})
        if not events:
            return {"available": False, "reason": "no churn/downgrade events in the write-back audit for this window"}
        return {"available": True, "churn_mrr": round(churn, 2), "events": events}
    except Exception as e:
        logger.info("churn_mrr_in_window failed: %s", e)
        return {"available": False, "reason": str(e)}
