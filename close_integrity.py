"""
close_integrity.py
------------------
THE STANDING CROSS-SYSTEM RECONCILIATION (CLOSE_INTEGRITY_AND_SIGNAL_REPORT Phase 2).
Rydel's data-integrity doctrine, encoded: ONE AUTHORITY (the sales tracker, counted by
its Close Date), OTHERS VALIDATE (GHL closed-won stage via the mirror; Stripe cash via
the existing matcher), DISAGREEMENTS SURFACE — never silently reconciled. No number is
quietly changed to make systems agree; a mismatch is data to show.

Runs daily (kv-stamped tick inside the attribution loop) and on demand. Read-only:
tracker mirror + ghl_opportunities mirror + the Stripe reconcile output. Products:
  - the matrix {tracker, ghl, stripe} per window + classified disagreements,
  - the DATA HYGIENE items (blank Close Dates, missing Input Dates, dead GHL lane,
    unplaced payers) → kv for the /ads hygiene panel + the action feed (Piolo's queue),
  - salience: a NEW disagreement id announces once, watermarked.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

logger = logging.getLogger(__name__)

_KV_MATRIX = "integrity:matrix"
_KV_PENDING = "integrity:pending"      # salience-pending new disagreement ids
_KV_TICK = "integrity:daily_tick"

OPS_RULE = ("Closed deals must be moved to the GHL closed-won stage the SAME DAY the "
            "tracker records the close — the stage lane is the tracker's validator; "
            "a dead lane validates nothing.")


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def _tracker_won_rows():
    import attribution_engine as AE
    rows = AE._tracker_rows_clean()
    hi = next((i for i, r in enumerate(rows[:8])
               if any("lead name" in (c or "").lower() for c in r)), 0) if rows else 0
    cm = AE.tracker_cols(rows[hi]) if rows else {}
    out = []
    for r in rows[hi + 1:] if rows else []:
        def g(k):
            i = cm.get(k)
            return r[i].strip() if (i is not None and i < len(r)) else ""
        if not g("name"):
            continue
        if g("closer_outcome").lower() == "won":
            out.append({"name": g("name"), "email": _norm(g("email")),
                        "close_date": AE._date(g("close_date")),
                        "close_raw": g("close_date"),
                        "input_date": AE._date(g("input_date")),
                        "contract": AE._money(g("contract")),
                        "cash": AE._money(g("cash"))})
    return out


def _ghl_won_in_window(w0: dt.date, w1: dt.date):
    """Won opportunities from the MIRROR (zero API cost). (count_in_window, total)."""
    import db
    if not db.db_configured():
        return None, None
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT contact_id, name, last_status_change_at FROM ghl_opportunities "
                "WHERE status = 'won' AND deleted = FALSE").fetchall()
        total = len(rows)
        n = sum(1 for r in rows if r.get("last_status_change_at")
                and w0 <= r["last_status_change_at"].date() <= w1)
        return n, total
    except Exception as e:
        logger.info("ghl mirror won read failed: %s", e)
        return None, None


def run_matrix(days: int = 30) -> dict:
    """The three-way matrix + classified disagreements for the trailing window."""
    from helpers import today_sydney
    w1 = today_sydney()
    w0 = w1 - dt.timedelta(days=days - 1)
    won = _tracker_won_rows()
    in_window = [t for t in won if t["close_date"] and w0 <= t["close_date"] <= w1]
    blank_dates = [t for t in won if t["close_date"] is None]
    no_input = [t for t in won if t["input_date"] is None]

    ghl_n, ghl_total = _ghl_won_in_window(w0, w1)

    stripe = {}
    disagreements = []
    try:
        import stripe_reconcile
        rep = (stripe_reconcile.reconcile_stripe_tracker() or {}).get(
            "stripe_reconciliation", {})
        stripe = {"checked": rep.get("checked_charges"),
                  "missing_from_tracker": len(rep.get("paid_missing_from_tracker") or []),
                  "needs_review": len(rep.get("needs_review") or [])}
        for p in (rep.get("paid_missing_from_tracker") or [])[:10]:
            disagreements.append({
                "id": f"integrity:stripe_missing:{_norm(str(p.get('customer')))}",
                "kind": "stripe_paid_missing_from_tracker", "severity": 1,
                "detail": f"Stripe payment {p.get('customer')} ${p.get('amount')} has no "
                          f"tracker row — a possibly untracked deal",
                "fix": "add the deal to the tracker, or confirm the payer alias",
                "owner": "sales/tracker maintainer"})
        for p in (rep.get("needs_review") or [])[:10]:
            disagreements.append({
                "id": f"integrity:stripe_review:{_norm(str(p.get('customer')))}",
                "kind": "stripe_payer_unplaced", "severity": 3,
                "detail": f"Stripe payer “{p.get('customer')}” ${p.get('amount')} not "
                          f"matched to a business",
                "fix": "confirm the alias in chat (\"payment from X is <business>\")",
                "owner": "Rydel/EDITH"})
    except Exception as e:
        stripe = {"error": type(e).__name__}

    if ghl_n is not None and len(in_window) > ghl_n:
        disagreements.append({
            "id": f"integrity:ghl_lane:{days}d:{len(in_window)}v{ghl_n}",
            "kind": "ghl_stage_lag", "severity": 2,
            "detail": f"{len(in_window)} tracker close(s) in {days}d but only {ghl_n} "
                      f"GHL opportunity(ies) moved to closed-won — the stage lane lags",
            "fix": OPS_RULE, "owner": "sales team"})
    for t in blank_dates:
        disagreements.append({
            "id": f"integrity:blank_close_date:{_norm(t['name'])}",
            "kind": "tracker_blank_close_date", "severity": 2,
            "detail": f"{t['name']}: won but Close Date blank (contract "
                      f"{t['contract'] or '—'}) — invisible to every windowed figure",
            "fix": "fill the Close Date on the tracker row",
            "owner": "tracker maintainer (Piolo to route)"})
    for t in no_input:
        disagreements.append({
            "id": f"integrity:blank_input_date:{_norm(t['name'])}",
            "kind": "tracker_blank_input_date", "severity": 3,
            "detail": f"{t['name']}: won row missing Input Date — excluded from cohort "
                      f"funnels",
            "fix": "fill the Input Date on the tracker row",
            "owner": "tracker maintainer (Piolo to route)"})

    agree = ghl_n == len(in_window) if ghl_n is not None else None
    return {
        "window_days": days, "as_of": str(w1),
        "authority": "sales tracker · Close Date (Rydel-confirmed, DECISIONS #118)",
        "tracker_closes": len(in_window),
        "tracker_names": [t["name"] for t in in_window],
        "ghl_won_in_window": ghl_n, "ghl_won_total": ghl_total,
        "stripe": stripe,
        "agreement": {"tracker_vs_ghl": agree,
                      "tracker_vs_stripe_cash": (stripe.get("missing_from_tracker") == 0
                                                 if "missing_from_tracker" in stripe else None)},
        "disagreements": disagreements,
        "ops_rule": OPS_RULE,
    }


def refresh(days: int = 30) -> dict:
    """Run + persist the matrix; queue NEW disagreement ids for salience (once each)."""
    import kv_store
    m = run_matrix(days)
    kv_store.put(_KV_MATRIX, m)
    pending = kv_store.get(_KV_PENDING) or []
    known = {p.get("id") for p in pending}
    for d in m["disagreements"]:
        if d["severity"] <= 2 and d["id"] not in known:
            pending.append({"id": d["id"], "detail": d["detail"], "fix": d["fix"]})
    kv_store.put(_KV_PENDING, pending[-40:])
    return m


def latest() -> dict | None:
    import kv_store
    return kv_store.get(_KV_MATRIX)


def daily_tick() -> bool:
    """kv-stamped once-a-day refresh (called from the attribution loop)."""
    import kv_store
    from helpers import today_sydney
    stamp = kv_store.get(_KV_TICK)
    today = str(today_sydney())
    if stamp == today:
        return False
    try:
        refresh(30)
        kv_store.put(_KV_TICK, today)
        return True
    except Exception as e:
        logger.warning("integrity daily tick failed: %s", e)
        return False


# ── EDITH: "do the systems agree on closes?" / "what's out of sync?" ─────────

_AGREE_RE = re.compile(
    r"do (the )?systems? agree|systems? (in )?sync|out of sync|close[- ]count.*(match|agree)|"
    r"(agree|match).*(closes|close count)|data (integrity|hygiene)", re.I)


def handle_integrity_command(text: str) -> tuple[str | None, bool]:
    if not text or not _AGREE_RE.search(text):
        return None, False
    m = latest()
    if not m:
        try:
            m = refresh(30)
        except Exception:
            return "I can't run the cross-system check right now — the mirrors are unavailable.", True
    parts = [f"Closes, last {m['window_days']} days — the tracker (the authority) says "
             f"{m['tracker_closes']}: {', '.join(m['tracker_names'][:6]) or 'none'}."]
    if m.get("ghl_won_in_window") is not None:
        parts.append(f"GHL shows {m['ghl_won_in_window']} moved to closed-won in the same "
                     f"window" + (" — in sync." if m["agreement"]["tracker_vs_ghl"]
                                  else " — the stage lane lags; flagged."))
    st = m.get("stripe") or {}
    if st.get("missing_from_tracker") is not None:
        parts.append(f"Stripe: {st.get('checked')} charges checked, "
                     f"{st['missing_from_tracker']} missing from the tracker.")
    n = len(m["disagreements"])
    parts.append(f"{n} open hygiene item(s)." if n else "No open hygiene items.")
    if n:
        d = m["disagreements"][0]
        parts.append(f"Top: {d['detail']} — fix: {d['fix']}")
    return " ".join(parts), True
