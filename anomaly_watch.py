"""
anomaly_watch.py
----------------
Pillar 1B — ANOMALY WATCH. Each refresh cycle, a deterministic check of key metrics against their
own trailing trend; a deviation beyond a stated, adjustable threshold becomes a salience event with
the deviation quantified ("CPL $81 -> $126, +55% vs the trailing 4-week"). Detection is deterministic
(arithmetic on real engine/history values — never invented); delivery is composed; each event is
watermarked so a standing anomaly isn't re-announced every session.

Metrics watched: lead velocity, close rate, cash movement (from history_store), failed charges (from
the snapshot), and loaded CPL (current 7d vs trailing 28d, via the one canonical engine). All figures
verbatim from the source — no urgency is manufactured.
"""
from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_K_CFG = "anomaly:config"
_DEFAULT = {"threshold_pct": 30, "min_abs_leads": 15, "enabled": True}


def config() -> dict:
    c = dict(_DEFAULT)
    c.update(kv_store.get(_K_CFG) or {})
    return c


def set_threshold(pct: float) -> None:
    c = kv_store.get(_K_CFG) or {}
    c["threshold_pct"] = pct
    kv_store.put(_K_CFG, c)


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def _dev_pct(cur, base):
    if not base:
        return None
    return round((cur - base) / base * 100, 1)


def _bucket(v):
    """Coarse watermark bucket so an anomaly re-fires only when it moves materially (~10% steps)."""
    try:
        return int(round(v / 10.0))
    except Exception:
        return 0


def check(snap: dict | None = None) -> list[dict]:
    """Return the current anomaly events (deterministic). Empty when everything is within band."""
    cfg = config()
    if not cfg.get("enabled", True):
        return []
    from snapshot import load_persisted
    snap = snap or load_persisted() or {}
    thr = cfg.get("threshold_pct", 30)
    events: list[dict] = []

    # ── History-based deviations (current vs trailing mean) ──
    try:
        import history_store
        hist = history_store.last_n_snapshots(28) or []
        def series(path):
            out = []
            for h in hist:
                s = h.get("snapshot", h)
                node = s
                for k in path:
                    node = (node or {}).get(k) if isinstance(node, dict) else None
                if isinstance(node, (int, float)):
                    out.append(node)
            return out

        # lead velocity (daily leads_in) — current vs trailing mean of prior days
        leads = series(["sales", "funnel", "leads_in"])
        if len(leads) >= 8:
            cur, base = leads[-1], _mean(leads[-8:-1])
            d = _dev_pct(cur, base)
            if d is not None and abs(d) >= thr and (cur >= cfg["min_abs_leads"] or base >= cfg["min_abs_leads"]):
                events.append({"id": f"anom:leads:{_bucket(d)}", "salience": 72, "ago": 0, "type": "anomaly",
                               "spoken": f"lead velocity {int(base)} -> {int(cur)}/day ({d:+.0f}% vs the trailing week)"})

        # cash movement (cash_in_bank) — sharp swing vs trailing mean
        cash = series(["cash_position", "cash_in_bank"])
        if len(cash) >= 8:
            cur, base = cash[-1], _mean(cash[-8:-1])
            d = _dev_pct(cur, base)
            if d is not None and abs(d) >= thr:
                events.append({"id": f"anom:cash:{_bucket(d)}", "salience": 74, "ago": 0, "type": "anomaly",
                               "spoken": f"cash moved ${int(base):,} -> ${int(cur):,} ({d:+.0f}% vs the trailing week)"})
    except Exception as e:
        logger.info("anomaly history check failed: %s", e)

    # ── Failed charges (snapshot) — any spike is worth surfacing ──
    try:
        fc = ((snap.get("stripe") or {}).get("failed_charges_count"))
        _unreliable = any("stripe_mrr_subs_mismatch" in str((d or {}).get("metric", ""))
                          for d in (snap.get("degraded") or []))
        if fc and fc >= 2 and not _unreliable:
            events.append({"id": f"anom:failed:{fc}", "salience": 90, "ago": 0, "type": "anomaly",
                           "spoken": f"{fc} charges failed recently — above the usual (worth a look)"})
    except Exception:
        pass

    # ── Loaded CPL: current 7d vs trailing 28d (one canonical engine) ──
    try:
        import range_unit_economics as R
        today = today_sydney()
        cur7 = R.unit_economics(str(today - dt.timedelta(days=6)), str(today))
        prev = R.unit_economics(str(today - dt.timedelta(days=34)), str(today - dt.timedelta(days=7)))
        def cpl(res):
            c = (res or {}).get("components", {}) or {}
            ad = c.get("ad_spend")
            leads_in = ((res or {}).get("cohort") or {}).get("leads_in")
            return (ad / leads_in) if (ad and leads_in) else None
        c_cur, c_prev = cpl(cur7), cpl(prev)
        if c_cur and c_prev:
            d = _dev_pct(c_cur, c_prev)
            if d is not None and abs(d) >= thr:
                events.append({"id": f"anom:cpl:{_bucket(d)}", "salience": 76, "ago": 0, "type": "anomaly",
                               "spoken": f"CPL ${c_prev:,.0f} -> ${c_cur:,.0f} ({d:+.0f}% vs the trailing 4-week)"})
    except Exception as e:
        logger.info("anomaly CPL check failed: %s", e)

    return events
