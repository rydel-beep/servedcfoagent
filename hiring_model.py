"""
hiring_model.py
---------------
Hiring affordability analysis. For any proposed hire (or stack of hires),
computes affordability, financial impact, payback, 3-month forecast,
and additional sales needed.

Uses the dual-basis financial position model — never invents its own.
All analysis, no decisions — the hire decision is Rydel's.
"""
from __future__ import annotations

import math


def json_safe(obj):
    """Recursively replace Infinity/NaN with None for valid JSON."""
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    return obj


def _safe_round(val, decimals=2):
    if val is None:
        return None
    if isinstance(val, float) and (math.isinf(val) or math.isnan(val)):
        return None
    return round(val, decimals)


def _graded_sustainability(team_cost_pct: float | None, cash_balance: float | None, monthly_net: float | None) -> dict:
    """Return graded sustainability status, not binary.

    Grades:
    - healthy: team ratio < 50% AND cash positive
    - tight: team ratio 50-80% OR cash declining but positive
    - unsustainable: team ratio > 80% OR cash negative OR net deeply negative
    """
    if team_cost_pct is not None and team_cost_pct > 80:
        return {
            "grade": "unsustainable",
            "color": "red",
            "reason": f"Team cost is {team_cost_pct}% of MRR",
        }
    if cash_balance is not None and cash_balance < 0:
        return {
            "grade": "unsustainable",
            "color": "red",
            "reason": f"Cash balance negative (${cash_balance:,.0f})",
        }
    if monthly_net is not None and monthly_net < -5000:
        return {
            "grade": "unsustainable",
            "color": "red",
            "reason": f"Net loss ${abs(monthly_net):,.0f}/mo",
        }
    if team_cost_pct is not None and team_cost_pct > 50:
        return {
            "grade": "tight",
            "color": "amber",
            "reason": f"Team cost is {team_cost_pct}% of MRR",
        }
    if monthly_net is not None and monthly_net < 0:
        return {
            "grade": "tight",
            "color": "amber",
            "reason": f"Slightly negative (${monthly_net:,.0f}/mo)",
        }
    return {
        "grade": "healthy",
        "color": "green",
        "reason": "Team ratio and cash position healthy",
    }


def _net_status(monthly_net: float | None) -> dict:
    """Return status dict for a monthly net figure."""
    if monthly_net is None:
        return {"status": "unknown", "label": "Data unavailable"}
    if monthly_net > 0:
        return {"status": "surplus", "label": f"Surplus ${monthly_net:,.0f}/mo"}
    if monthly_net == 0:
        return {"status": "breakeven", "label": "Breakeven"}
    return {"status": "burn", "label": f"Burning ${abs(monthly_net):,.0f}/mo"}


def _compute_forecast(
    current_mrr: float,
    monthly_net: float,
    growth_rate_pct: float | None,
    total_added_cost: float,
    months: int = 3,
) -> list[dict]:
    """Project monthly financials for the next N months.

    Uses current MRR + growth rate to project revenue, then subtracts
    existing costs + new hire cost.
    """
    rate = (growth_rate_pct or 0) / 100
    forecast = []
    mrr = current_mrr

    for m in range(1, months + 1):
        mrr = mrr * (1 + rate)
        # Revenue growth adds to net proportionally
        # monthly_net already accounts for current costs at current revenue
        # Revenue delta = (new_mrr - current_mrr) contributes to net
        revenue_delta = mrr - current_mrr
        projected_net = monthly_net + revenue_delta - total_added_cost
        cumulative_surplus = projected_net * m  # simplified

        forecast.append({
            "month": m,
            "projected_mrr": round(mrr, 2),
            "revenue_growth": round(revenue_delta, 2),
            "projected_net": round(projected_net, 2),
            "status": _net_status(projected_net),
            "cumulative_cash_impact": round(cumulative_surplus, 2),
            "can_afford_at_this_point": projected_net > 0,
        })

    return forecast


def _forward_verdict(
    fwd_forecast: list[dict],
    total_added_cost: float,
    sustainable_until: str | None,
    clients_to_fund: float | None,
    binding_constraint: str | None,
) -> str:
    """Generate a plain-English verdict from the forward sustainability lens."""
    if not fwd_forecast:
        return "Forward MRR data unavailable — judge against trailing net only."

    # Check first month
    first = fwd_forecast[0]
    sustainable_now = first.get("can_sustain", False)

    # Count sustainable months
    sus_count = sum(1 for f in fwd_forecast if f.get("can_sustain"))

    parts = []
    if sustainable_now and sus_count == len(fwd_forecast):
        parts.append(f"Sustainable across all {len(fwd_forecast)} months of forward MRR.")
    elif sustainable_now:
        parts.append(
            f"Sustainable now, but churn makes it tight by {sustainable_until}. "
            f"Sustained for {sus_count}/{len(fwd_forecast)} forward months."
        )
    else:
        parts.append(
            f"Not sustainable against forward recognized MRR — "
            f"net negative from {fwd_forecast[0]['month']}."
        )

    if clients_to_fund is not None:
        parts.append(f"Requires ~{clients_to_fund} client contributions to fund.")

    if binding_constraint:
        parts.append(f"Binding constraint: {binding_constraint}.")

    return " ".join(parts)


def compute_single_hire(
    proposed_cost: float,
    proposed_role: str,
    is_revenue_generating: bool,
    avg_cash_per_close: float | None,
    close_rate_pct: float | None,
    gross_margin_pct: float | None,
    avg_contract_value: float | None,
) -> dict:
    """Compute per-role analysis for a single proposed hire."""
    result = {
        "role": proposed_role,
        "monthly_cost": round(proposed_cost, 2),
        "is_revenue_generating": is_revenue_generating,
    }

    if is_revenue_generating and avg_cash_per_close and avg_cash_per_close > 0:
        closes_to_cover = proposed_cost / avg_cash_per_close
        result["closes_to_self_fund"] = round(closes_to_cover, 1)
        result["self_funding_note"] = (
            f"Needs {round(closes_to_cover, 1)} closes/mo "
            f"at ${round(avg_cash_per_close):,.0f} avg cash/close to cover cost"
        )
    else:
        if gross_margin_pct and gross_margin_pct > 0:
            mrr_needed = proposed_cost / (gross_margin_pct / 100)
            result["additional_mrr_needed"] = round(mrr_needed, 2)
            result["offset_note"] = (
                f"Needs ${round(mrr_needed):,.0f}/mo additional MRR "
                f"at {round(gross_margin_pct, 1)}% margin to offset"
            )
            if avg_cash_per_close and avg_cash_per_close > 0:
                closes = proposed_cost / (avg_cash_per_close * gross_margin_pct / 100)
                result["closes_to_offset"] = round(closes, 1)

    return result


def compute_hiring_analysis(
    roles: list[dict],
    monthly_net_income: float,
    current_mrr: float,
    monthly_revenue: float | None,
    monthly_cogs: float | None,
    monthly_opex: float | None,
    avg_contract_value: float | None,
    close_rate_pct: float | None,
    avg_cash_per_close: float | None,
    gross_margin_pct: float | None,
    true_team_cost: float,
    financial_position: dict | None = None,
    growth_rate_pct: float | None = None,
    binding_constraint: str | None = None,
    forward_mrr: dict | None = None,
    cash_position: dict | None = None,
    raises: list[dict] | None = None,
    total_monthly_burn: float | None = None,
) -> dict:
    """Compute hiring affordability for one or more proposed roles.

    Parameters
    ----------
    roles : list of dicts with keys: role, monthly_cost, is_revenue_generating
    financial_position : the dual-basis model from financial_position.py
    growth_rate_pct : latest MoM MRR growth rate for 3-month forecast
    binding_constraint : top deficiency from deficiency_analysis (for context)
    """
    # ── Dual-basis current state (from financial_position) ──
    fp = financial_position or {}
    cash_basis = fp.get("cash_basis")
    recognized_basis = fp.get("recognized_basis")
    headline = fp.get("headline") or {}
    fp_costs = fp.get("costs") or {}

    current = {
        "headline_net": headline.get("monthly_net"),
        "headline_basis": headline.get("basis"),
        "headline_status": headline.get("status"),
        "true_team_cost": round(true_team_cost, 2),
        "current_mrr": round(current_mrr, 2),
        "team_cost_pct_of_mrr": fp_costs.get("team_cost_pct_of_mrr"),
        "team_cost_benchmark": fp_costs.get("team_cost_benchmark"),
    }

    # Add both bases if available
    if cash_basis:
        current["cash_basis"] = {
            "revenue": cash_basis.get("revenue"),
            "monthly_net": cash_basis.get("monthly_net"),
            "status": cash_basis.get("status"),
            "gross_margin_pct": cash_basis.get("gross_margin_pct"),
        }
    if recognized_basis:
        current["recognized_basis"] = {
            "revenue": recognized_basis.get("revenue"),
            "monthly_net": recognized_basis.get("monthly_net"),
            "status": recognized_basis.get("status"),
            "gross_margin_pct": recognized_basis.get("gross_margin_pct"),
        }

    # Use headline net (already consistent, no double-count)
    net_income = headline.get("monthly_net") or monthly_net_income

    # ── Per-role analysis ──
    per_role = []
    total_added_cost = 0.0

    for r in roles:
        cost = float(r.get("monthly_cost", 0))
        role_name = r.get("role", "New hire")
        is_rev = bool(r.get("is_revenue_generating", False))
        total_added_cost += cost

        analysis = compute_single_hire(
            proposed_cost=cost,
            proposed_role=role_name,
            is_revenue_generating=is_rev,
            avg_cash_per_close=avg_cash_per_close,
            close_rate_pct=close_rate_pct,
            gross_margin_pct=gross_margin_pct,
            avg_contract_value=avg_contract_value,
        )
        per_role.append(analysis)

    # ── Raises for existing employees ──
    raise_details = []
    total_raise_cost = 0.0
    if raises:
        for ra in raises:
            added = float(ra.get("monthly_increase", 0))
            total_raise_cost += added
            total_added_cost += added
            raise_details.append({
                "role": ra.get("role", "Existing employee"),
                "current_salary": _safe_round(ra.get("current_salary")),
                "new_salary": _safe_round(ra.get("new_salary")),
                "monthly_increase": round(added, 2),
                "is_spof": bool(ra.get("is_spof", False)),
            })

    # ── Combined impact ──
    new_team_cost = true_team_cost + total_added_cost
    new_monthly_net = net_income - total_added_cost

    cost_as_pct_of_mrr = round(new_team_cost / current_mrr * 100, 1) if current_mrr > 0 else None
    mrr_threshold = round(new_team_cost / 0.40, 2) if new_team_cost > 0 else 0

    combined_closes_to_offset = None
    if avg_cash_per_close and avg_cash_per_close > 0:
        combined_closes_to_offset = round(total_added_cost / avg_cash_per_close, 1)

    combined = {
        "total_added_cost": round(total_added_cost, 2),
        "new_team_cost": round(new_team_cost, 2),
        "monthly_net_before": round(net_income, 2),
        "monthly_net_after": round(new_monthly_net, 2),
        "can_afford": new_monthly_net > 0,
        "status_before": _net_status(net_income),
        "status_after": _net_status(new_monthly_net),
        "cost_as_pct_of_mrr": cost_as_pct_of_mrr,
        "mrr_threshold_for_hires": mrr_threshold,
        "combined_closes_to_offset": combined_closes_to_offset,
        "role_count": len(roles),
    }

    # ── 3-month forecast ──
    forecast = _compute_forecast(
        current_mrr=current_mrr,
        monthly_net=net_income,
        growth_rate_pct=growth_rate_pct,
        total_added_cost=total_added_cost,
        months=3,
    )

    # Determine when the hire becomes affordable (if not now)
    affordable_at_month = None
    if not combined["can_afford"]:
        for f in forecast:
            if f["can_afford_at_this_point"]:
                affordable_at_month = f["month"]
                break

    # ── Constraint context ──
    constraint_context = None
    if binding_constraint:
        constraint_context = {
            "binding_constraint": binding_constraint,
            "note": ("Consider whether this hire addresses the binding constraint. "
                     "Hiring capacity where there's no bottleneck = underutilized cost."),
        }

    # ── Forward MRR sustainability lens ──
    forward_lens = None
    if forward_mrr:
        fwd_months = forward_mrr.get("forward_months") or []
        fwd_current = forward_mrr.get("current_recognized_mrr") or 0
        mtm_floor = forward_mrr.get("mtm_floor") or 0
        avg_per_client = forward_mrr.get("avg_monthly_per_client") or 0
        active_clients = forward_mrr.get("active_clients") or 0
        expiry_schedule = forward_mrr.get("expiry_schedule") or []
        renewal_info = forward_mrr.get("renewal_rate_historical") or {}

        # Total costs: use full-outflow burn if available, else COGS + OpEx
        total_costs = total_monthly_burn or ((monthly_cogs or 0) + (monthly_opex or 0))

        # Cash projection starting point — use cash_in_bank ONLY
        # (total_available double-counts Stripe incoming which arrives over time)
        cp = cash_position or {}
        starting_cash = cp.get("cash_in_bank") or 0
        running_cash = starting_cash

        # Forward net per month with graded sustainability + cash projection
        fwd_forecast = []
        for fm in fwd_months[:6]:  # cap at 6 months
            fwd_rev = fm.get("recognized_mrr") or 0
            fwd_net = fwd_rev - total_costs - total_added_cost
            fwd_net_before = fwd_rev - total_costs
            team_pct = (
                _safe_round(new_team_cost / fwd_rev * 100, 1)
                if fwd_rev > 0 else None
            )

            # Cash projection: starting cash + cumulative net flows
            running_cash += fwd_net
            grade = _graded_sustainability(team_pct, running_cash, fwd_net)

            fwd_forecast.append({
                "month": fm.get("month"),
                "recognized_mrr": _safe_round(fwd_rev),
                "clients": fm.get("clients"),
                "net_before_hire": _safe_round(fwd_net_before),
                "net_after_hire": _safe_round(fwd_net),
                "cash_balance": _safe_round(running_cash),
                "team_cost_pct": team_pct,
                "sustainability": grade,
            })

        # When does the hire become unsustainable (churn cliff)?
        sustainable_until = None
        for ff in fwd_forecast:
            if ff["sustainability"]["grade"] == "unsustainable":
                sustainable_until = ff["month"]
                break

        # Cash runway: when does cash go negative?
        cash_runway_month = None
        for ff in fwd_forecast:
            if ff["cash_balance"] is not None and ff["cash_balance"] < 0:
                cash_runway_month = ff["month"]
                break

        # Count healthy months
        healthy_count = sum(
            1 for ff in fwd_forecast
            if ff["sustainability"]["grade"] == "healthy"
        )
        tight_count = sum(
            1 for ff in fwd_forecast
            if ff["sustainability"]["grade"] == "tight"
        )
        unsustainable_count = sum(
            1 for ff in fwd_forecast
            if ff["sustainability"]["grade"] == "unsustainable"
        )

        # Contribution margin: how many clients fund this hire?
        clients_to_fund = None
        if avg_per_client and avg_per_client > 0 and gross_margin_pct:
            contribution_per_client = avg_per_client * (gross_margin_pct / 100)
            clients_to_fund = _safe_round(total_added_cost / contribution_per_client, 1)
        elif avg_per_client and avg_per_client > 0:
            clients_to_fund = _safe_round(total_added_cost / avg_per_client, 1)

        # New clients needed to replace churn
        new_clients_needed_monthly = None
        if avg_per_client and avg_per_client > 0:
            total_expiring = sum(e.get("contracts_expiring", 0) for e in expiry_schedule[:6])
            avg_monthly_churn = total_expiring / 6 if expiry_schedule else 0
            new_clients_needed_monthly = _safe_round(avg_monthly_churn, 1)

        forward_lens = {
            "current_recognized_mrr": _safe_round(fwd_current),
            "mtm_floor": _safe_round(mtm_floor),
            "avg_monthly_per_client": _safe_round(avg_per_client),
            "active_clients": active_clients,
            "clients_to_fund_hire": clients_to_fund,
            "starting_cash": _safe_round(starting_cash),
            "forward_forecast": fwd_forecast,
            "sustainable_until": sustainable_until,
            "cash_runway_month": cash_runway_month,
            "churn_warning": sustainable_until is not None,
            "summary": {
                "healthy_months": healthy_count,
                "tight_months": tight_count,
                "unsustainable_months": unsustainable_count,
                "total_months": len(fwd_forecast),
            },
            "renewal_rate": renewal_info.get("note"),
            "new_clients_to_replace_churn_monthly": new_clients_needed_monthly,
            "verdict": _forward_verdict(
                fwd_forecast, total_added_cost, sustainable_until,
                clients_to_fund, binding_constraint,
            ),
        }

    result_dict = {
        "current": current,
        "per_role": per_role,
        "combined": combined,
        "forecast_3mo": forecast,
        "forward_sustainability": forward_lens,
        "affordable_at_month": affordable_at_month,
        "constraint_context": constraint_context,
        "note": "Analysis only — the hire decision is yours.",
    }
    if raise_details:
        result_dict["raises"] = raise_details
        result_dict["combined"]["total_raise_cost"] = round(total_raise_cost, 2)

    return json_safe(result_dict)
