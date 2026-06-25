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

def m1_ltgp_cac(snap: dict, targets: dict | None = None) -> dict:
    """Lifetime gross profit to fully-loaded customer acquisition cost."""
    target = (targets or {}).get("ltgp_cac_target", 3.0)
    watch_line = target * 2 / 3  # proportional watch band below the target
    avg_contract = _get(snap, "sales.deep.money.avg_contract")
    gross_margin_pct = _get(snap, "xero.gross_margin_pct")
    closes = _get(snap, "sales.funnel.closes")
    setter_comm = _get(snap, "costs.setter_commission") or 0
    closer_comm = _get(snap, "costs.closer_commission") or 0
    setter_payout, setter_comm_source = _resolved_setter_comm(snap)
    ad_spend, ad_spend_source, ad_spend_window = _resolved_ad_spend(snap)

    inputs = {
        "avg_contract": avg_contract,
        "gross_margin_pct": gross_margin_pct,
        "closes": closes,
        "setter_commission": setter_comm,
        "closer_commission": closer_comm,
        "closer_commission_source": "sheet_commission_closer_actual",
        "setter_payout": setter_payout,
        "setter_comm_source": setter_comm_source,
        "ad_spend": ad_spend,
        "ad_spend_source": ad_spend_source,
        "ad_spend_window_days": ad_spend_window,
    }

    # Confidence
    missing = []
    if avg_contract is None:
        missing.append("avg_contract")
    if gross_margin_pct is None:
        missing.append("gross_margin_pct (Xero)")
    if closes is None or closes == 0:
        missing.append("closes")
    if ad_spend is None:
        missing.append("ad_spend")

    if len(missing) >= 2:
        confidence = "low"
    elif missing:
        confidence = "medium"
    else:
        confidence = "high"

    if avg_contract is None or gross_margin_pct is None or not closes:
        return _metric(
            None, target, "unknown", None,
            f"Cannot compute — missing: {', '.join(missing)}",
            confidence, inputs,
        )

    ltgp = avg_contract * (gross_margin_pct / 100)

    # CAC = (ad_spend + setter payouts + closer commission) / closes
    total_acq_cost = (ad_spend or 0) + setter_payout + closer_comm
    cac_loaded = round(total_acq_cost / closes, 2) if closes > 0 else None

    if cac_loaded is None or cac_loaded == 0:
        return _metric(
            None, target, "unknown", None,
            "CAC is zero — no acquisition costs recorded",
            confidence, inputs,
        )

    ratio = round(ltgp / cac_loaded, 2)
    inputs["ltgp"] = round(ltgp, 2)
    inputs["cac_loaded"] = cac_loaded
    inputs["ratio"] = ratio
    inputs["target"] = target

    if ratio >= target:
        status = "healthy"
        read = (f"${ltgp:,.0f} gross profit per ${cac_loaded:,.0f} acquisition cost "
                f"({ratio}×) — above the {target:g}× line")
        dollar_gap = None
    elif ratio >= watch_line:
        status = "watch"
        gap = round((target * cac_loaded - ltgp) * closes, 2)
        read = (f"${ltgp:,.0f} gross profit per ${cac_loaded:,.0f} acquisition cost "
                f"({ratio}×) — approaching the {target:g}× floor; ${gap:,.0f}/mo gap to close")
        dollar_gap = gap
    else:
        status = "critical"
        gap = round((target * cac_loaded - ltgp) * closes, 2)
        read = (f"${ltgp:,.0f} gross profit per ${cac_loaded:,.0f} acquisition cost "
                f"({ratio}×) — below {target:g}×; buying revenue that doesn't pay back fast enough")
        dollar_gap = gap

    return _metric(ratio, target, status, dollar_gap, read, confidence, inputs)


# ── M2: Fully-loaded CAC breakdown ────────────────────────────────────────

def m2_cac_breakdown(snap: dict) -> dict:
    """Fully-loaded CAC with per-offer attribution."""
    avg_contract = _get(snap, "sales.deep.money.avg_contract")
    gross_margin_pct = _get(snap, "xero.gross_margin_pct")
    closes = _get(snap, "sales.funnel.closes")
    setter_comm = _get(snap, "costs.setter_commission") or 0
    closer_comm = _get(snap, "costs.closer_commission") or 0
    setter_payout, setter_comm_source = _resolved_setter_comm(snap)
    ad_spend, ad_spend_source, ad_spend_window = _resolved_ad_spend(snap)
    offer_mix = _get(snap, "sales.deep.money.offer_mix") or []

    inputs = {
        "closes": closes,
        "setter_commission": setter_comm,
        "closer_commission": closer_comm,
        "closer_commission_source": "sheet_commission_closer_actual",
        "setter_payout": setter_payout,
        "setter_comm_source": setter_comm_source,
        "ad_spend": ad_spend,
        "ad_spend_source": ad_spend_source,
        "ad_spend_window_days": ad_spend_window,
        "offer_mix": offer_mix,
    }

    missing = []
    if closes is None or closes == 0:
        missing.append("closes")
    if ad_spend is None:
        missing.append("ad_spend")
    if gross_margin_pct is None:
        missing.append("gross_margin_pct")

    confidence = "low" if len(missing) >= 2 else ("medium" if missing else "high")

    if not closes:
        return _metric(
            None, None, "unknown", None,
            f"Cannot compute — missing: {', '.join(missing)}",
            confidence, inputs,
        )

    total_acq_cost = (ad_spend or 0) + setter_payout + closer_comm
    cac_loaded = round(total_acq_cost / closes, 2)

    # Benchmark: avg gross profit per close
    avg_gp = None
    if avg_contract is not None and gross_margin_pct is not None:
        avg_gp = round(avg_contract * (gross_margin_pct / 100), 2)

    inputs["cac_loaded"] = cac_loaded
    inputs["avg_gp_per_close"] = avg_gp

    # Per-offer CAC attribution (proportional to offer share)
    per_offer = []
    if offer_mix and closes > 0:
        for o in offer_mix:
            share = o.get("pct", 0) / 100
            attributed_cac = round(cac_loaded * share, 2) if share > 0 else 0
            per_offer.append({
                "offer": o["offer"],
                "count": o["count"],
                "share_pct": o["pct"],
                "attributed_cac": attributed_cac,
            })
    inputs["per_offer_cac"] = per_offer

    # Fully-loaded breakdown (Meta-only ad spend; comms actual-from-sheet/log).
    setter_lbl = "log" if setter_comm_source == "setter_payout_log_actual" else "scorecard"
    bd = (f"Loaded: ad ${ad_spend or 0:,.0f} (Meta) + closer ${closer_comm:,.0f} (sheet) "
          f"+ setter ${setter_payout:,.0f} ({setter_lbl}) = ${total_acq_cost:,.0f} ÷ {closes} closes")
    inputs["breakdown"] = bd

    if avg_gp is not None and cac_loaded > avg_gp:
        status = "critical"
        per_close_loss = round(cac_loaded - avg_gp, 2)
        dollar_gap = round(per_close_loss * closes, 2)
        read = (f"CAC ${cac_loaded:,.0f} exceeds gross profit per close ${avg_gp:,.0f} "
                f"— losing ${per_close_loss:,.0f}/deal, ${dollar_gap:,.0f}/mo. {bd}")
    elif avg_gp is not None:
        status = "healthy"
        dollar_gap = None
        read = (f"CAC ${cac_loaded:,.0f} vs gross profit ${avg_gp:,.0f}/close — "
                f"acquisition cost is covered. {bd}")
    else:
        status = "unknown"
        dollar_gap = None
        read = f"CAC ${cac_loaded:,.0f}/close — gross profit unknown (Xero needed for benchmark). {bd}"

    return _metric(cac_loaded, avg_gp, status, dollar_gap, read, confidence, inputs)


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

def m7_ltv_to_cac(snap: dict) -> dict:
    """Lifetime value (full contract, no margin) to fully-loaded CAC."""
    avg_contract = _get(snap, "sales.deep.money.avg_contract")
    closes = _get(snap, "sales.funnel.closes")
    setter_comm = _get(snap, "costs.setter_commission") or 0
    closer_comm = _get(snap, "costs.closer_commission") or 0
    setter_payout, setter_comm_source = _resolved_setter_comm(snap)
    ad_spend, ad_spend_source, ad_spend_window = _resolved_ad_spend(snap)

    inputs = {
        "avg_contract": avg_contract,
        "closes": closes,
        "ad_spend": ad_spend,
    }

    if avg_contract is None or not closes:
        return _metric(None, None, "unknown", None,
                       "Cannot compute — missing data", "low", inputs)

    total_acq_cost = (ad_spend or 0) + setter_payout + closer_comm
    cac_loaded = round(total_acq_cost / closes, 2) if closes > 0 else None

    if cac_loaded is None or cac_loaded == 0:
        return _metric(None, None, "unknown", None,
                       "CAC is zero", "low", inputs)

    ratio = round(avg_contract / cac_loaded, 2)
    inputs["cac_loaded"] = cac_loaded
    inputs["ratio"] = ratio

    read = (f"${avg_contract:,.0f} full contract value per ${cac_loaded:,.0f} CAC "
            f"({ratio}x) — full revenue before margin")

    return _metric(ratio, None, "unknown", None, read, "high" if ad_spend else "medium", inputs)


# ── M8: ROAS (Meta-based) ─────────────────────────────────────────────────

def m8_roas(snap: dict, targets: dict | None = None) -> dict:
    """Return on ad spend = new contracted revenue / ad spend, window-consistent.

    Defined as (closes × avg_contract) / ad_spend over the SAME window — i.e. new
    business won per $1 of ad spend. Labelled Meta-based (Google not yet included).
    """
    target = (targets or {}).get("roas_target", 3.0)
    watch_line = target / 2
    closes = _get(snap, "sales.funnel.closes")
    avg_contract = _get(snap, "sales.deep.money.avg_contract")
    ad_spend, ad_spend_source, ad_spend_window = _resolved_ad_spend(snap)
    funnel_window = _get(snap, "sales.window_days") or 30

    inputs = {
        "closes": closes,
        "avg_contract": avg_contract,
        "ad_spend": ad_spend,
        "ad_spend_source": ad_spend_source,
        "ad_spend_window_days": ad_spend_window,
        "funnel_window_days": funnel_window,
        "platform": "meta" if ad_spend_source == "meta_live" else ad_spend_source,
        "definition": "new contracted revenue (closes × avg_contract) / ad spend, same window",
        "window_consistent": (ad_spend_window == funnel_window),
    }

    missing = []
    if not closes:
        missing.append("closes")
    if avg_contract is None:
        missing.append("avg_contract")
    if ad_spend is None:
        missing.append("ad_spend")
    confidence = "low" if len(missing) >= 2 else ("medium" if missing else "high")

    if not closes or avg_contract is None or not ad_spend or ad_spend == 0:
        return _metric(
            None, target, "unknown", None,
            f"Cannot compute — missing: {', '.join(missing) or 'ad_spend is zero'}",
            confidence, inputs,
        )

    new_revenue = closes * avg_contract
    roas = round(new_revenue / ad_spend, 2)
    inputs["new_contracted_revenue"] = round(new_revenue, 2)
    inputs["roas"] = roas
    inputs["target"] = target
    label = "Meta" if ad_spend_source == "meta_live" else "Xero-ad-line"

    if roas >= target:
        status = "healthy"
    elif roas >= watch_line:
        status = "watch"
    else:
        status = "critical"
    read = (f"${roas:.2f} of new contracted revenue per $1 of {label} ad spend "
            f"(${new_revenue:,.0f} won / ${ad_spend:,.0f} spend, {funnel_window}d) — "
            f"Meta-based; Google not yet included")

    return _metric(roas, target, status, None, read, confidence, inputs)


# ── Compute all metrics ───────────────────────────────────────────────────

def compute_all(snap: dict, true_team_cost: float | None = None,
                targets: dict | None = None) -> dict:
    """Return all Hormozi metrics keyed by name.

    targets: Rydel-set benchmark/goalpost overrides (manual_targets.get_resolved()).
    Each metric uses targets.get(key, <documented default>) for its benchmark line,
    so the healthy/below-target classification reflects Rydel's goalposts.
    """
    t = targets or {}
    return {
        "ltgp_cac": m1_ltgp_cac(snap, t),
        "ltgp_to_cac": m1_ltgp_cac(snap, t),  # alias for KPI strip
        "ltv_to_cac": m7_ltv_to_cac(snap),
        "cac_loaded": m2_cac_breakdown(snap),
        "payback_days": m3_payback_days(snap, t),
        "gross_margin": m4_gross_margin(snap, t),
        "op_efficiency": m5_op_efficiency(snap, true_team_cost, t),
        "sales_velocity": m6_sales_velocity(snap),
        "roas": m8_roas(snap, t),
    }
