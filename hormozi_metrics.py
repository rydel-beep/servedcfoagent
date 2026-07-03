"""
hormozi_metrics.py
------------------
Pure functions computing Hormozi-framework unit-economics metrics.
Each takes the snapshot dict and returns a standardised metric block.
"""
from __future__ import annotations


def _get(snap: dict, path: str):
    """Navigate a dotted path into a nested dict. Returns None if missing."""
    obj = snap
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def _resolved_ad_spend(snap: dict):
    """Authoritative ad spend for unit economics: Meta live (primary) → Xero (fallback).

    Returns (value, source, window_days). snapshot.ad_spend_resolved is built in
    snapshot.py; fall back to the raw Xero line for older snapshots without it.
    """
    r = snap.get("ad_spend_resolved")
    if isinstance(r, dict) and r.get("value") is not None:
        return r.get("value"), r.get("source"), r.get("window_days")
    legacy = _get(snap, "xero.xero_ad_spend")
    return legacy, ("xero_advertising" if legacy is not None else None), 30


def _resolved_setter_comm(snap: dict):
    """Window-matched setter commission for loaded CAC: $50/set + 5%-of-cash, read ACTUAL
    from the SETTER PAYOUT LOG (snapshot.loaded_cac). Falls back to the scorecard
    $50/qualified-set figure if the log is unavailable. Returns (value, source).
    """
    lc = snap.get("loaded_cac") or {}
    v = lc.get("setter_comm")
    if v is not None:
        return v, "setter_payout_log_actual"
    return (_get(snap, "sales.payout.total_owed") or 0), "scorecard_50_per_set_only"


def _metric(
    value, benchmark, status: str, dollar_gap, read: str,
    confidence: str, inputs_used: dict,
) -> dict:
    return {
        "value": value,
        "benchmark": benchmark,
        "status": status,
        "dollar_gap": dollar_gap,
        "read": read,
        "confidence": confidence,
        "inputs_used": inputs_used,
    }


# ── M1: LTGP:CAC ──────────────────────────────────────────────────────────

# ── THE ONE ENGINE (2026-07-03) ──────────────────────────────────────────────
# LTGP:CAC, LTV:CAC, loaded CAC and ROAS are computed by ONE engine — the range-aware
# unit_economics(trailing 30d) — so the snapshot, chat, voice, tiles and brief can never
# disagree. These m1/m2/m7/m8 wrappers DELEGATE to it (no independent formula survives).
def _engine_30d() -> dict:
    from range_unit_economics import unit_economics
    from helpers import today_sydney
    import datetime as _dt
    t = today_sydney()
    return unit_economics(str(t - _dt.timedelta(days=29)), str(t))


def _band(v, good: float, watch: float) -> str:
    if v is None:
        return "unknown"
    if v >= good:
        return "healthy"
    if v >= watch:
        return "watch"
    return "critical"


def _eng_inputs(c: dict, basis: str) -> dict:
    return {"engine": "unit_economics(trailing 30d)", "basis": basis,
            "closes": c.get("closes"), "avg_contract": c.get("avg_contract"),
            "gross_margin_pct": c.get("gross_margin_pct"), "cac_loaded": c.get("cac_loaded"),
            "ltgp": c.get("ltgp"), "ad_spend": c.get("ad_spend"),
            "contract_value_total": c.get("contract_value_total"),
            "window_days": (c.get("window") or {}).get("days")}


def m1_ltgp_cac(snap: dict, targets: dict | None = None, eng: dict | None = None) -> dict:
    """Lifetime gross profit to loaded CAC — delegated to the one engine (contract basis)."""
    e = eng if eng is not None else _engine_30d()
    c = e.get("components") or {}
    v = e.get("ltgp_cac")
    target = (targets or {}).get("ltgp_cac_target", 3.0)
    inp = _eng_inputs(c, "avg contract × gross margin ÷ loaded CAC (tracker-won closes)")
    if v is None:
        return _metric(None, target, "unknown", None,
                       "; ".join(e.get("caveats") or ["no closes in the 30d window"]), "medium", inp)
    read = (f"LTGP:CAC {v}× — LTGP ${c.get('ltgp', 0):,.0f} ÷ loaded CAC ${c.get('cac_loaded', 0):,.0f} "
            f"({c.get('closes')} closes, {inp['window_days']}d)")
    return _metric(v, target, _band(v, target, target * 2 / 3), None, read, "high", inp)


# ── M2: Fully-loaded CAC breakdown ────────────────────────────────────────

def m2_cac_breakdown(snap: dict, eng: dict | None = None) -> dict:
    """Fully-loaded CAC — delegated to the one engine (loaded ÷ tracker-won closes)."""
    e = eng if eng is not None else _engine_30d()
    c = e.get("components") or {}
    v = e.get("cac_loaded")
    avg_gp = round(c["avg_contract"] * (c["gross_margin_pct"] / 100), 2) \
        if c.get("avg_contract") and c.get("gross_margin_pct") is not None else None
    inp = _eng_inputs(c, "ad + closer + setter comms ÷ tracker-won closes (Meta-only ad spend)")
    inp["avg_gp_per_close"] = avg_gp
    inp["breakdown"] = c.get("cac_breakdown")
    if v is None:
        return _metric(None, None, "unknown", None,
                       "; ".join(e.get("caveats") or ["no closes in the 30d window"]), "medium", inp)
    if avg_gp is not None and v > avg_gp:
        status, read = "critical", (f"CAC ${v:,.0f} exceeds gross profit/close ${avg_gp:,.0f}. "
                                    f"{c.get('cac_breakdown', '')}")
    elif avg_gp is not None:
        status, read = "healthy", f"CAC ${v:,.0f} vs gross profit ${avg_gp:,.0f}/close — covered. {c.get('cac_breakdown', '')}"
    else:
        status, read = "unknown", f"CAC ${v:,.0f}/close. {c.get('cac_breakdown', '')}"
    return _metric(v, avg_gp, status, None, read, "high", inp)


# ── M3: Payback period ────────────────────────────────────────────────────

def m3_payback_days(snap: dict, targets: dict | None = None) -> dict:
    """How many days to recover CAC from cash collected."""
    target = (targets or {}).get("payback_target", 30)
    watch_line = target * 2
    avg_cash = _get(snap, "sales.deep.money.avg_cash")
    closes = _get(snap, "sales.funnel.closes")
    setter_comm = _get(snap, "costs.setter_commission") or 0
    closer_comm = _get(snap, "costs.closer_commission") or 0
    setter_payout, setter_comm_source = _resolved_setter_comm(snap)
    ad_spend, ad_spend_source, ad_spend_window = _resolved_ad_spend(snap)
    cash_collected = _get(snap, "sheets.cash_collected")

    # Fallback avg_cash
    if avg_cash is None and cash_collected and closes and closes > 0:
        avg_cash = round(cash_collected / closes, 2)

    inputs = {
        "avg_cash": avg_cash,
        "closes": closes,
        "ad_spend": ad_spend,
        "ad_spend_source": ad_spend_source,
        "ad_spend_window_days": ad_spend_window,
        "setter_payout": setter_payout,
        "closer_commission": closer_comm,
    }

    missing = []
    if avg_cash is None or avg_cash == 0:
        missing.append("avg_cash")
    if closes is None or closes == 0:
        missing.append("closes")
    if ad_spend is None:
        missing.append("ad_spend")

    confidence = "low" if len(missing) >= 2 else ("medium" if missing else "high")

    if not closes or not avg_cash or avg_cash == 0:
        return _metric(
            None, target, "unknown", None,
            f"Cannot compute — missing: {', '.join(missing)}",
            confidence, inputs,
        )

    total_acq_cost = (ad_spend or 0) + setter_payout + closer_comm
    cac_loaded = total_acq_cost / closes
    daily_cash = avg_cash / 30
    payback = round(cac_loaded / daily_cash, 1) if daily_cash > 0 else None

    inputs["cac_loaded"] = round(cac_loaded, 2)
    inputs["daily_cash_per_close"] = round(daily_cash, 2)
    inputs["payback_days"] = payback
    inputs["target"] = target

    if payback is None:
        return _metric(
            None, target, "unknown", None,
            "Daily cash per close is zero", confidence, inputs,
        )

    if payback <= target:
        status = "healthy"
        dollar_gap = None
        read = (f"New clients pay back in {payback:.0f} days — "
                f"you can self-fund growth from cashflow")
    elif payback <= watch_line:
        status = "watch"
        exposure = round((payback - target) * (closes / 30) * avg_cash, 2)
        dollar_gap = exposure
        read = (f"New clients pay back in {payback:.0f} days — "
                f"{payback - target:.0f} days of working-capital exposure per close")
    else:
        status = "critical"
        exposure = round((payback - target) * (closes / 30) * avg_cash, 2)
        dollar_gap = exposure
        read = (f"New clients pay back in {payback:.0f} days — "
                f"every close is a cash drain for {payback:.0f} days")

    return _metric(payback, target, status, dollar_gap, read, confidence, inputs)


# ── M4: Gross margin ──────────────────────────────────────────────────────

def m4_gross_margin(snap: dict, targets: dict | None = None) -> dict:
    """Current gross margin vs agency benchmark."""
    _t = targets or {}
    benchmark = _t.get("gross_margin_floor", 45.0)
    healthy_target = _t.get("gross_margin_target", 50.0)
    margin = _get(snap, "xero.gross_margin_pct")
    revenue = _get(snap, "xero.revenue")
    gross_profit = _get(snap, "xero.gross_profit")

    inputs = {"gross_margin_pct": margin, "revenue": revenue, "gross_profit": gross_profit}
    confidence = "high" if margin is not None else "low"

    if margin is None:
        return _metric(
            None, benchmark, "unknown", None,
            "Gross margin unavailable — Xero not connected",
            confidence, inputs,
        )

    if margin >= healthy_target:
        status = "healthy"
        dollar_gap = None
        read = f"Gross margin {margin}% — healthy for a services agency"
    elif margin >= benchmark:
        status = "watch"
        gap = round((healthy_target - margin) / 100 * (revenue or 0), 2)
        dollar_gap = gap
        read = (f"Gross margin {margin}% — {healthy_target - margin:.1f} points below "
                f"the {healthy_target}% healthy target; ${gap:,.0f}/mo revenue leaking to COGS")
    else:
        status = "critical"
        gap = round((benchmark - margin) / 100 * (revenue or 0), 2)
        dollar_gap = gap
        read = (f"Gross margin {margin}% — below the {benchmark}% floor; "
                f"every dollar of revenue leaves less for ops and profit")

    return _metric(margin, benchmark, status, dollar_gap, read, confidence, inputs)


# ── M5: Operating efficiency ──────────────────────────────────────────────

def m5_op_efficiency(snap: dict, true_team_cost: float | None = None,
                     targets: dict | None = None) -> dict:
    """Revenue per fixed-cost dollar (true_team_cost as denominator)."""
    op_target = (targets or {}).get("op_efficiency_target", 1.5)
    revenue = _get(snap, "xero.revenue")
    opex = _get(snap, "xero.operating_expenses")
    fixed_cost = true_team_cost

    inputs = {
        "revenue": revenue,
        "operating_expenses_xero": opex,
        "true_team_cost": fixed_cost,
        "note": ("Uses true_team_cost (SALARY tab + owner gross + super) as fixed "
                 "cost denominator — see categoriser for breakdown"),
    }

    missing = []
    if revenue is None:
        missing.append("revenue (Xero)")
    if fixed_cost is None:
        missing.append("true_team_cost")

    confidence = "low" if len(missing) >= 2 else ("medium" if missing else "high")

    if revenue is None or fixed_cost is None or fixed_cost == 0:
        return _metric(
            None, op_target, "unknown", None,
            f"Cannot compute — missing: {', '.join(missing)}",
            confidence, inputs,
        )

    ratio = round(revenue / fixed_cost, 2)
    inputs["ratio"] = ratio
    inputs["fixed_cost_used"] = fixed_cost
    inputs["target"] = op_target

    benchmark = op_target
    watch_line = op_target * 2 / 3
    if ratio >= benchmark:
        status = "healthy"
        dollar_gap = None
        read = (f"Every $1 of fixed cost generates ${ratio:.2f} of revenue — "
                f"above the ${benchmark:.2f} target")
    elif ratio >= watch_line:
        status = "watch"
        needed_rev = round(benchmark * fixed_cost, 2)
        dollar_gap = round(needed_rev - revenue, 2)
        read = (f"Every $1 of fixed cost generates ${ratio:.2f} of revenue — "
                f"${dollar_gap:,.0f}/mo below the ${benchmark:.2f} target")
    else:
        status = "critical"
        needed_rev = round(benchmark * fixed_cost, 2)
        dollar_gap = round(needed_rev - revenue, 2)
        read = (f"Every $1 of fixed cost generates ${ratio:.2f} of revenue — "
                f"costs exceed revenue output; ${dollar_gap:,.0f}/mo shortfall")

    return _metric(ratio, benchmark, status, dollar_gap, read, confidence, inputs)


# ── M6: Sales velocity ────────────────────────────────────────────────────

def m6_sales_velocity(snap: dict) -> dict:
    """Hormozi velocity = (leads × close_rate × avg_contract) / cycle_days."""
    leads = _get(snap, "sales.funnel.leads_in")
    close_rate_pct = _get(snap, "sales.funnel.lead_to_close_pct")
    avg_contract = _get(snap, "sales.deep.money.avg_contract")
    median_days = _get(snap, "sales.velocity.days_lead_to_cash_median")

    # Default cycle to 14 if not derivable
    cycle_days = median_days if median_days and median_days > 0 else 14
    cycle_source = "computed median" if median_days and median_days > 0 else "default (14 days)"

    inputs = {
        "leads_30d": leads,
        "close_rate_pct": close_rate_pct,
        "avg_contract": avg_contract,
        "cycle_days": cycle_days,
        "cycle_source": cycle_source,
    }

    missing = []
    if leads is None:
        missing.append("leads")
    if close_rate_pct is None:
        missing.append("close_rate")
    if avg_contract is None:
        missing.append("avg_contract")

    confidence = "low" if len(missing) >= 2 else ("medium" if missing else "high")

    if leads is None or close_rate_pct is None or avg_contract is None:
        return _metric(
            None, None, "unknown", None,
            f"Cannot compute — missing: {', '.join(missing)}",
            confidence, inputs,
        )

    close_rate = close_rate_pct / 100
    velocity = round((leads * close_rate * avg_contract) / cycle_days, 2)
    inputs["velocity"] = velocity

    read = (f"${velocity:,.0f} of contracted revenue per day at current funnel — "
            f"the engine's daily output ({cycle_source})")

    # No fixed benchmark — track trend
    return _metric(velocity, None, "unknown", None, read, confidence, inputs)


# ── M7: LTV:CAC (full revenue, no margin) ────────────────────────────────

def m7_ltv_to_cac(snap: dict, eng: dict | None = None) -> dict:
    """LTV (full contract, no margin) ÷ loaded CAC — delegated to the one engine."""
    e = eng if eng is not None else _engine_30d()
    c = e.get("components") or {}
    v = e.get("ltv_cac")
    inp = _eng_inputs(c, "avg contract value (no margin) ÷ loaded CAC (tracker-won closes)")
    if v is None:
        return _metric(None, None, "unknown", None,
                       "; ".join(e.get("caveats") or ["no closes in the 30d window"]), "medium", inp)
    read = (f"LTV:CAC {v}× — avg contract ${c.get('avg_contract', 0):,.0f} ÷ loaded CAC "
            f"${c.get('cac_loaded', 0):,.0f} (full revenue before margin, {c.get('closes')} closes)")
    return _metric(v, None, _band(v, 3.0, 2.0), None, read, "high", inp)


# ── M8: ROAS (contracted, Meta-based) ────────────────────────────────────

def m8_roas(snap: dict, targets: dict | None = None, eng: dict | None = None) -> dict:
    """ROAS = CONTRACTED revenue ÷ Meta spend (Rydel-locked 2026-07-03) — one engine."""
    e = eng if eng is not None else _engine_30d()
    c = e.get("components") or {}
    v = e.get("roas")
    target = (targets or {}).get("roas_target", 3.0)
    inp = _eng_inputs(c, "contracted revenue ÷ Meta ad spend (spend-in-window)")
    inp["contracted_revenue"] = c.get("contract_value_total")
    if v is None:
        return _metric(None, target, "unknown", None,
                       "; ".join(e.get("caveats") or ["no closes / no spend in the 30d window"]),
                       "medium", inp)
    read = (f"ROAS {v}× — ${c.get('contract_value_total', 0):,.0f} contracted revenue ÷ "
            f"${c.get('ad_spend', 0):,.0f} Meta spend ({inp['window_days']}d, contracted basis)")
    return _metric(v, target, _band(v, target, target / 2), None, read, "high", inp)


# ── Compute all metrics ───────────────────────────────────────────────────

def compute_all(snap: dict, true_team_cost: float | None = None,
                targets: dict | None = None) -> dict:
    """Return all Hormozi metrics keyed by name.

    LTGP:CAC / LTV:CAC / loaded CAC / ROAS delegate to ONE engine (unit_economics 30d),
    computed once here and shared — so the snapshot can never disagree with chat/tiles.
    """
    t = targets or {}
    eng = _engine_30d()  # ONE engine call, shared by the four delegated metrics + the greeting
    ec = eng.get("components") or {}
    ecoh = eng.get("cohort") or {}
    return {
        "ltgp_cac": m1_ltgp_cac(snap, t, eng),
        "ltgp_to_cac": m1_ltgp_cac(snap, t, eng),  # alias for KPI strip
        "ltv_to_cac": m7_ltv_to_cac(snap, eng),
        "cac_loaded": m2_cac_breakdown(snap, eng),
        "payback_days": m3_payback_days(snap, t),
        "gross_margin": m4_gross_margin(snap, t),
        "op_efficiency": m5_op_efficiency(snap, true_team_cost, t),
        "sales_velocity": m6_sales_velocity(snap),
        "roas": m8_roas(snap, t, eng),
        # The greeting reads THIS (same engine, no re-computation) — never the scorecard.
        "_sales_headline": {"sets": ecoh.get("sets"), "closes": ec.get("closes"),
                            "close_rate": ecoh.get("show_to_close_pct"),
                            "new_deal_cash": ec.get("new_deal_cash")},
    }
