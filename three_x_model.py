"""
three_x_model.py
----------------
The 3X REVERSE-ENGINEERING — constraint-first. Given a quarter's ACTUALS (from quarterly_pack),
walk the acquisition machine backwards to answer: what would have to be TRUE to 3x the company's
overall quarter-over-quarter growth next quarter?

Rydel's call (2026-07-21): 3x EVERYTHING — cash collected AND contracted revenue AND new MRR —
i.e. 3x overall growth, not one lever. So the model scales the whole funnel by the target multiple
and reports every lever's requirement, flagging each PLAUSIBLE / STRETCH / OUT-OF-TREND, ending in
THE BINDING CONSTRAINT.

THIS IS A MODEL, NOT A FORECAST. Every requirement is derived arithmetically from the quarter's own
actuals and a small set of STATED, ADJUSTABLE assumptions. No number is invented: the multiplier is
applied to real figures, and where a driver's behaviour at scale is unknowable (e.g. CAC drift) it
is HELD CONSTANT as an explicit assumption and flagged as such. All the model does is arithmetic on
the pack's verbatim numbers — it never sources a new figure.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Default assumption knobs (adjustable — surfaced in the PDF and via chat "what if close rate 55%?")
DEFAULT_ASSUMPTIONS = {
    "multiple": 3.0,                 # 3x
    "cost_per_lead_held": True,      # CPL constant at scale (stated assumption)
    "cac_held_constant": True,       # loaded CAC constant at scale (stated assumption)
    "close_rate_target": None,       # efficiency path: if set, use this close rate instead of volume
    "ltgp_cac_floor": 3.0,           # the Hormozi line CAC economics must stay above
    "payroll_mrr_gate": 0.40,        # payroll:MRR must stay <= 40%
    "clients_per_delivery_hire": 12, # capacity benchmark (clients one delivery hire supports)
    "hire_lead_time_weeks": 6,       # time-to-productive for a new hire
}


def _flag(required: float | None, current: float | None, *, higher_is_harder=True,
          stretch_ratio=1.6, out_ratio=2.5) -> str:
    """Classify a requirement vs current actual. Ratios are on the required/current multiple."""
    if required is None or current is None or current == 0:
        return "unknown"
    r = required / current
    if not higher_is_harder:
        r = 1 / r if r else 0
    if r <= stretch_ratio:
        return "plausible"
    if r <= out_ratio:
        return "stretch"
    return "out-of-trend"


def build_3x(pack: dict, assumptions: dict | None = None) -> dict:
    """Reverse-engineer the 3x model from a quarter pack. Returns levers, a requirements table,
    the assumptions used, and the binding-constraint verdict."""
    a = dict(DEFAULT_ASSUMPTIONS)
    if assumptions:
        a.update({k: v for k, v in assumptions.items() if v is not None})
    M = float(a["multiple"])

    comp = (pack.get("unit_economics") or {}).get("components", {}) or {}
    sales = pack.get("sales") or {}
    funnel = sales.get("funnel") or {}
    rc = pack.get("revenue_cash") or {}
    costs = pack.get("costs") or {}
    churn = pack.get("churn") or {}

    # ── Actuals (verbatim from the pack) ──
    closes = comp.get("closes")
    contracted = rc.get("contracted_revenue")
    cash = rc.get("new_deal_cash_collected")
    avg_contract = comp.get("avg_contract")
    ad_spend = comp.get("ad_spend")
    cac = comp.get("cac_loaded")
    ltgp_cac = (pack.get("unit_economics") or {}).get("ltgp_cac")
    leads = funnel.get("leads_in") if isinstance(funnel, dict) else None
    sets_ = funnel.get("sets") if isinstance(funnel, dict) else None
    shows = funnel.get("shows") if isinstance(funnel, dict) else None
    lead_to_close = funnel.get("lead_to_close_pct") if isinstance(funnel, dict) else None
    show_to_close = funnel.get("show_to_close_pct") if isinstance(funnel, dict) else None
    cpl = (ad_spend / leads) if (ad_spend and leads) else None
    active_clients = churn.get("active_clients_current")
    burn = (costs.get("monthly_burn_context") or {}).get("total_recurring_burn_monthly")

    levers: list[dict] = []
    notes: list[str] = []

    # ── 1) TARGETS: 3x each headline metric ──
    targets = {
        "contracted_revenue": _scale(contracted, M),
        "new_deal_cash_collected": _scale(cash, M),
        "closes": _scale(closes, M),
    }

    # ── 2) FUNNEL MATH — two paths to 3x closes ──
    req_closes = _scale(closes, M)
    volume_path = None
    efficiency_path = None
    if closes and leads and lead_to_close:
        # VOLUME: same close rate, 3x the leads (and sets/shows proportionally)
        volume_path = {
            "leads_required": _scale(leads, M),
            "sets_required": _scale(sets_, M) if sets_ else None,
            "shows_required": _scale(shows, M) if shows else None,
            "close_rate_held_pct": round(lead_to_close, 1),
            "flag": _flag(_scale(leads, M), leads),
            "desc": f"Same {round(lead_to_close,1)}% lead->close, {M:.0f}x the lead flow.",
        }
        # EFFICIENCY: same leads, the close rate that yields 3x closes
        req_rate = (req_closes / leads * 100) if leads else None
        efficiency_path = {
            "leads_held": leads,
            "required_close_rate_pct": round(req_rate, 1) if req_rate is not None else None,
            "current_close_rate_pct": round(lead_to_close, 1),
            "feasible": bool(req_rate is not None and req_rate <= 100),
            "flag": _flag(req_rate, lead_to_close) if req_rate is not None else "unknown",
            "desc": (f"Same {leads} leads, close rate {round(lead_to_close,1)}% -> "
                     f"{round(req_rate,1) if req_rate is not None else '?'}%."
                     + ("" if (req_rate is not None and req_rate <= 100)
                        else "  IMPOSSIBLE on volume alone — needs more leads too.")),
        }
    else:
        notes.append("Funnel path math needs closes + leads + lead->close% in the window; "
                     "one is missing, so only the target counts are shown.")

    levers.append({
        "lever": "Lead volume (volume path)",
        "current": leads, "required": _scale(leads, M) if leads else None,
        "flag": _flag(_scale(leads, M) if leads else None, leads),
        "unit": "leads/quarter",
    })
    levers.append({
        "lever": "Close rate (efficiency path)",
        "current": round(lead_to_close, 1) if lead_to_close else None,
        "required": (efficiency_path or {}).get("required_close_rate_pct"),
        "flag": (efficiency_path or {}).get("flag", "unknown"),
        "unit": "% lead->close",
    })

    # ── 3) SPEND MATH — leads at current CPL -> ad spend; does CAC economics hold? ──
    spend_required = None
    cac_at_scale = cac  # held constant (assumption)
    if cpl and leads:
        spend_required = round(cpl * _scale(leads, M), 2)
    spend = {
        "cost_per_lead_current": round(cpl, 2) if cpl else None,
        "ad_spend_current": ad_spend,
        "ad_spend_required": spend_required,
        "cac_assumption": ("held constant at ${:,.0f} — CAC drift at scale is unknowable, so it is "
                           "an explicit assumption, not a claim".format(cac) if cac else "CAC unknown"),
        "ltgp_cac_current": ltgp_cac,
        "ltgp_cac_stays_above_floor": (ltgp_cac is not None and ltgp_cac >= a["ltgp_cac_floor"]),
        "floor": a["ltgp_cac_floor"],
        "flag": _flag(spend_required, ad_spend) if spend_required else "unknown",
    }
    levers.append({
        "lever": "Ad spend", "current": ad_spend, "required": spend_required,
        "flag": spend.get("flag", "unknown"), "unit": "$/quarter",
    })

    # ── 4) CAPACITY MATH — 3x clients -> hires, payroll gate ──
    capacity = _capacity(pack, M, a, active_clients)
    if capacity.get("hires_needed") is not None:
        levers.append({
            "lever": "Delivery hires", "current": 0, "required": capacity.get("hires_needed"),
            "flag": capacity.get("flag", "unknown"), "unit": "hires",
        })

    # ── 5) CHURN MATH — churn at which 3x gross becomes <=2x net ──
    churn_math = _churn_math(pack, M)

    # ── 6) CASH CURVE — spend leads revenue (order-of-magnitude working-capital note) ──
    cash_curve = _cash_curve(pack, spend_required)

    # ── BINDING CONSTRAINT — which lever binds first ──
    binding = _binding_constraint(levers, efficiency_path, spend, capacity, churn_math)

    return {
        "multiple": M,
        "assumptions": a,
        "targets": targets,
        "funnel": {"volume_path": volume_path, "efficiency_path": efficiency_path,
                   "required_closes": req_closes},
        "spend": spend,
        "capacity": capacity,
        "churn": churn_math,
        "cash_curve": cash_curve,
        "requirements_table": levers,
        "binding_constraint": binding,
        "notes": notes,
        "framing": ("A model of what must be TRUE to 3x overall growth — not a forecast. Every figure "
                    "is the quarter's own actual scaled by the multiple; assumptions are stated and "
                    "adjustable. Ask EDITH 'what if close rate hits 55%?' to recompute."),
    }


def _scale(v, m):
    if v is None:
        return None
    return round(v * m, 2) if isinstance(v, float) else round(v * m)


def _capacity(pack: dict, M: float, a: dict, active_clients) -> dict:
    if not active_clients:
        return {"available": False, "reason": "current active-client count unavailable",
                "flag": "unknown"}
    target_clients = round(active_clients * M)
    per_hire = a["clients_per_delivery_hire"]
    # extra clients beyond current capacity headroom (assume current team fully loaded)
    extra_clients = target_clients - active_clients
    hires = max(0, -(-extra_clients // per_hire)) if per_hire else None  # ceil
    burn_ctx = (pack.get("costs") or {}).get("monthly_burn_context") or {}
    current_burn = burn_ctx.get("total_recurring_burn_monthly")
    rc = pack.get("revenue_cash") or {}
    closing_mrr = (rc.get("mrr_bridge") or {}).get("closing_mrr")
    payroll = burn_ctx.get("team")
    payroll_ratio_now = (payroll / closing_mrr) if (payroll and closing_mrr) else None
    # at 3x MRR, does payroll:MRR gate survive if payroll grows with hires (rough: +1 hire ~ avg team cost/head)
    return {
        "available": True,
        "current_active_clients": active_clients,
        "target_clients": target_clients,
        "clients_per_delivery_hire": per_hire,
        "hires_needed": hires,
        "hire_lead_time_weeks": a["hire_lead_time_weeks"],
        "payroll_mrr_ratio_now": round(payroll_ratio_now, 3) if payroll_ratio_now else None,
        "payroll_mrr_gate": a["payroll_mrr_gate"],
        "gate_note": ("At 3x MRR the payroll:MRR gate (<=40%) survives IF new payroll scales slower "
                      "than MRR — plausible since MRR triples but hires are stepwise. Exact impact "
                      "needs per-hire cost; flagged as a modelled assumption."),
        "flag": _flag(hires, 1, stretch_ratio=3, out_ratio=6) if hires else "plausible",
    }


def _churn_math(pack: dict, M: float) -> dict:
    """The churn rate at which 3x GROSS growth becomes only 2x NET. If gross new MRR triples, net
    growth = gross - churn. Solve for the churn that erodes 3x down to 2x of the base."""
    rc = pack.get("revenue_cash") or {}
    bridge = rc.get("mrr_bridge") or {}
    base_mrr = bridge.get("closing_mrr")
    churn_mrr = bridge.get("churn_mrr")
    out = {"available": bool(base_mrr),
           "current_closing_mrr": base_mrr, "current_churn_mrr": churn_mrr}
    if base_mrr:
        # 3x gross add, tolerate churn up to (3x-2x)=1x base before net falls below 2x
        tolerable_churn_mrr = round(base_mrr * (M - 2.0), 2)
        out["tolerable_churn_mrr_to_hold_2x_net"] = tolerable_churn_mrr
        out["current_churn_rate_pct"] = (round(churn_mrr / base_mrr * 100, 1)
                                         if churn_mrr else None)
        out["note"] = (f"If gross new MRR hits {M:.0f}x, net still clears 2x as long as churn stays "
                       f"under ~${tolerable_churn_mrr:,.0f}/mo of the base. Compare to current "
                       f"churn of ${churn_mrr:,.0f}/mo." if churn_mrr is not None else
                       f"Tolerable churn to hold 2x net is ~${tolerable_churn_mrr:,.0f}/mo; current "
                       "churn MRR not available for comparison.")
        out["flag"] = ("plausible" if (churn_mrr is not None and churn_mrr <= tolerable_churn_mrr)
                       else "stretch" if churn_mrr is not None else "unknown")
    else:
        out["note"] = "Base MRR not available for this window — churn math shown as unavailable."
        out["flag"] = "unknown"
    return out


def _cash_curve(pack: dict, spend_required) -> dict:
    rc = pack.get("revenue_cash") or {}
    cash = rc.get("new_deal_cash_collected")
    return {
        "spend_leads_revenue": True,
        "ad_spend_required_upfront": spend_required,
        "new_deal_cash_current": cash,
        "note": ("Ad spend is paid before the cash it generates lands (payback runs weeks, per the "
                 "payback engine). Scaling 3x means carrying ~3x the upfront ad + commission outlay "
                 "before the matching cash arrives — a working-capital step, order-of-magnitude only."),
    }


def _binding_constraint(levers, efficiency_path, spend, capacity, churn_math) -> dict:
    """Which requirement binds first. Rank by severity: out-of-trend > stretch > plausible."""
    severity = {"out-of-trend": 3, "stretch": 2, "plausible": 1, "unknown": 0}
    candidates = []
    for lv in levers:
        candidates.append((severity.get(lv.get("flag"), 0), lv.get("lever"), lv.get("flag")))
    # churn + capacity as named candidates
    if churn_math.get("flag"):
        candidates.append((severity.get(churn_math["flag"], 0), "Churn (net erosion)", churn_math["flag"]))
    if capacity.get("flag"):
        candidates.append((severity.get(capacity["flag"], 0), "Delivery capacity", capacity["flag"]))
    if efficiency_path and efficiency_path.get("feasible") is False:
        candidates.append((3, "Close rate (efficiency path impossible)", "out-of-trend"))
    candidates.sort(reverse=True)
    if not candidates or candidates[0][0] == 0:
        return {"lever": None, "flag": "unknown",
                "verdict": "Not enough windowed data to name a single binding constraint honestly."}
    top = candidates[0]
    return {
        "lever": top[1], "flag": top[2],
        "verdict": (f"The binding constraint is {top[1]} ({top[2]}). It is the requirement furthest "
                    "out of trend, so it caps the 3x before the others do — fix or fund this first, "
                    "or the rest of the plan can't land."),
        "ranked": [{"lever": c[1], "flag": c[2]} for c in candidates[:5]],
    }
