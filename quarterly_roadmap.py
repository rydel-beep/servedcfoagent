"""
quarterly_roadmap.py
-------------------
THE MARKETING ROADMAP (G5) — a scaling roadmap, not just targets. From the quarter's actuals + the
3x model, build: channel decomposition (GHL lead-source), the monthly lead RAMP (graduated, not
flat) with a spend schedule, a CPL-drift assumption BAND (0/+15/+30%) with CAC + LTGP:CAC
consequences, a creative-cadence implication, weekly checkpoints with thresholds, and a sequenced,
dated Q3 action list.

Everything is arithmetic on the pack's verbatim numbers + STATED, adjustable assumptions. Where a
feed is thin (e.g. Meta campaign-level CPL), the section says so and models with a labelled
assumption — never silently pretends.
"""
from __future__ import annotations

import calendar
import datetime as dt
import logging

logger = logging.getLogger(__name__)

DRIFT_BAND = (0.0, 0.15, 0.30)   # CPL drift scenarios at 3x spend


def _channel_mix() -> dict:
    """Current lead-source mix from the GHL mirror (opportunity.source). 98% fill (Phase 0)."""
    try:
        import ghl_mirror
        rows = ghl_mirror.read_opportunities(open_only=True, exclude_test=True)
        from collections import Counter
        c = Counter()
        for o in rows:
            src = (o.get("source") or "(unknown)").strip().lower()
            # normalise the obvious duplicates
            if "facebook" in src or "meta" in src or "paid social" in src:
                src = "Meta / Facebook"
            elif "landing" in src:
                src = "Landing page"
            elif src in ("(unknown)", ""):
                src = "(unknown)"
            else:
                src = src.title()
            c[src] += 1
        total = sum(c.values()) or 1
        mix = [{"source": k, "leads": v, "share_pct": round(100 * v / total, 1)}
               for k, v in c.most_common(8)]
        return {"available": True, "total_open": total, "mix": mix,
                "fill_note": "GHL lead-source, ~98% populated; Meta is the dominant paid channel."}
    except Exception as e:
        logger.info("channel_mix failed: %s", e)
        return {"available": False, "reason": str(e)}


def _next_quarter_months(today: dt.date) -> list[str]:
    q = (today.month - 1) // 3 + 1
    nq = q + 1; y = today.year
    if nq == 5:
        nq, y = 1, y + 1
    start = (nq - 1) * 3 + 1
    return [dt.date(y, start + i, 1).strftime("%b %Y") for i in range(3)]


def _ramp(current_q_leads: int, target_q_leads: int, months: list[str]) -> list[dict]:
    """A graduated 3-month ramp (increasing, not flat) that sums to the quarterly target. Weights
    40/33/27 reversed → builds toward the run-rate needed by quarter end."""
    weights = [0.28, 0.34, 0.38]
    out = []
    for m, w in zip(months, weights):
        out.append({"month": m, "leads": round(target_q_leads * w)})
    # correct rounding so it sums exactly to target
    diff = target_q_leads - sum(x["leads"] for x in out)
    if out:
        out[-1]["leads"] += diff
    return out


def build_roadmap(review: dict, assumptions: dict | None = None) -> dict:
    from helpers import today_sydney
    today = today_sydney()
    cur = review.get("current", {})
    tx = review.get("three_x", {})
    funnel = (cur.get("sales") or {}).get("funnel") or {}
    comp = (cur.get("unit_economics") or {}).get("components", {}) or {}
    spend = tx.get("spend", {}) or {}
    a = dict(tx.get("assumptions") or {})
    if assumptions:
        a.update({k: v for k, v in assumptions.items() if v is not None})
    M = float(a.get("multiple", 3.0))

    cur_leads = funnel.get("leads_in")
    target_leads = tx.get("funnel", {}).get("volume_path", {}).get("leads_required")
    cpl = spend.get("cost_per_lead_current")
    cac = comp.get("cac_loaded")
    ltgp_cac = (cur.get("unit_economics") or {}).get("ltgp_cac")
    floor = a.get("ltgp_cac_floor", 3.0)
    months = _next_quarter_months(today)

    # RAMP + spend schedule
    ramp = _ramp(cur_leads or 0, target_leads or 0, months) if target_leads else []
    for r in ramp:
        r["spend"] = round(r["leads"] * cpl) if cpl else None

    # CPL-DRIFT BAND: consequence of CPL rising at scale
    band = []
    if cpl and target_leads and cac:
        for d in DRIFT_BAND:
            drift_cpl = cpl * (1 + d)
            q_spend = round(drift_cpl * target_leads)
            # CAC scales with the ad-spend share of CAC; approximate CAC drift ∝ CPL drift on the ad component
            drift_cac = round(cac * (1 + d))     # conservative: whole CAC drifts with CPL
            drift_ltgp = round(ltgp_cac / (1 + d), 2) if ltgp_cac else None
            band.append({"cpl_drift_pct": round(d * 100),
                         "cpl": round(drift_cpl, 2), "quarter_ad_spend": q_spend,
                         "cac_at_scale": drift_cac, "ltgp_cac_at_scale": drift_ltgp,
                         "stays_above_floor": (drift_ltgp is not None and drift_ltgp >= floor)})

    # CREATIVE CADENCE (assumption-labelled)
    creative = {
        "assumption": "Served runs ~1 creative batch/week; a 3x spend ramp needs proportionally more "
                      "tested angles to avoid fatigue.",
        "implication": (f"Scaling ad spend to ~{spend.get('ad_spend_required') and '${:,.0f}'.format(spend['ad_spend_required']) or 'the ramp'} "
                        "means roughly 2-3x the creative test volume — plan the batch cadence up front. "
                        "(Batch-economics feed not wired; stated as an assumption to confirm.)"),
    }

    # WEEKLY CHECKPOINTS with on-track thresholds
    checkpoints = [
        {"metric": "CPL", "on_track": f"<= ${round(cpl*1.15):,}" if cpl else "within +15% of baseline",
         "why": "the drift band's inner bound"},
        {"metric": "Lead volume vs ramp line", "on_track": ">= that week's ramp target", "why": "the leading indicator"},
        {"metric": "Lead->set %", "on_track": f">= {funnel.get('lead_to_set_pct','~26')}%", "why": "setter throughput holds"},
        {"metric": "Set->show %", "on_track": f">= {funnel.get('set_to_show_pct','~70')}%", "why": "show discipline holds"},
        {"metric": "LTGP:CAC to-date", "on_track": f">= {floor}x", "why": "unit economics stay fundable"},
        {"metric": "Payroll:MRR", "on_track": f"<= {int(a.get('payroll_mrr_gate',0.4)*100)}%", "why": "the delivery-cost gate"},
    ]

    # SEQUENCED, DATED ACTIONS (owners left for Rydel)
    hires = (tx.get("capacity") or {}).get("hires_needed")
    lead_wk = a.get("hire_lead_time_weeks", 4)
    actions = []
    if hires:
        actions.append({"when": "Week 1", "action": f"Start {hires} delivery hire(s) — {lead_wk}wk to productive, "
                        "stepwise as clients land; capacity is the binding constraint."})
    if ramp:
        actions.append({"when": "Week 1-2", "action": f"Lift Meta spend toward {months[0]}'s "
                        f"${ramp[0].get('spend'):,} and instrument the ramp line for weekly tracking." if ramp[0].get("spend") else
                        "Lift Meta spend to the ramp schedule and track weekly."})
    actions.append({"when": "Week 1", "action": "Instrument churn now (MRR snapshots + write-back audit) so "
                    "the net-growth math becomes computable next quarter."})
    actions.append({"when": "Weeks 2-6", "action": "Scale creative test cadence to match the spend ramp; "
                    "watch CPL against the drift band's +15% inner bound."})
    if ramp and len(ramp) > 1:
        actions.append({"when": months[1], "action": f"Hit {ramp[1]['leads']} leads / ${ramp[1].get('spend'):,} spend; "
                        "re-check LTGP:CAC stays above the floor before stepping to month 3." if ramp[1].get("spend") else
                        f"Hit {ramp[1]['leads']} leads; re-check economics before month 3."})

    return {
        "available": bool(target_leads and cpl),
        "reason": None if (target_leads and cpl) else "needs current leads + CPL from the pack",
        "channel_mix": _channel_mix(),
        "current_leads": cur_leads, "target_leads": target_leads, "multiple": M,
        "cpl_current": cpl, "months": months,
        "ramp": ramp, "cpl_drift_band": band, "creative": creative,
        "checkpoints": checkpoints, "actions": actions,
        "framing": "A scaling roadmap — the ramp, the spend, the drift band, and the sequence. "
                   "Assumptions are stated and adjustable; where a feed is thin it's labelled.",
    }
