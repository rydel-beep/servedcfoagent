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

    return json_safe({
        "current": current,
        "per_role": per_role,
        "combined": combined,
        "forecast_3mo": forecast,
        "affordable_at_month": affordable_at_month,
        "constraint_context": constraint_context,
        "note": "Analysis only — the hire decision is yours.",
    })
