"""
hiring_model.py
---------------
Hiring affordability analysis. For any proposed hire (or stack of hires),
computes affordability, financial impact, payback, and additional sales needed.

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


def _runway_status(monthly_net: float) -> dict:
    """Compute runway status from monthly net income/burn.

    Returns dict with months (float|None) and status label.
    """
    if monthly_net > 0:
        return {"months": None, "status": "cashflow_positive",
                "label": "Self-funding — no burn"}
    if monthly_net == 0:
        return {"months": None, "status": "breakeven",
                "label": "Breakeven — no surplus, no burn"}
    # Burning: runway not meaningful without a cash balance,
    # but we report the burn rate
    return {"months": None, "status": "burning",
            "label": f"Burning {abs(round(monthly_net, 2))}/mo"}


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

    # Revenue-generating: closes needed to self-fund
    if is_revenue_generating and avg_cash_per_close and avg_cash_per_close > 0:
        closes_to_cover = proposed_cost / avg_cash_per_close
        result["closes_to_self_fund"] = round(closes_to_cover, 1)
        result["self_funding_note"] = (
            f"Needs {round(closes_to_cover, 1)} closes/mo "
            f"at ${round(avg_cash_per_close):,.0f} avg cash/close to cover cost"
        )
    else:
        # Non-revenue: additional MRR needed at current margin
        if gross_margin_pct and gross_margin_pct > 0:
            mrr_needed = proposed_cost / (gross_margin_pct / 100)
            result["additional_mrr_needed"] = round(mrr_needed, 2)
            result["offset_note"] = (
                f"Needs ${round(mrr_needed):,.0f}/mo additional MRR "
                f"at {round(gross_margin_pct, 1)}% margin to offset"
            )
            # Closes to offset
            if avg_cash_per_close and avg_cash_per_close > 0:
                closes = proposed_cost / (avg_cash_per_close * gross_margin_pct / 100) if gross_margin_pct > 0 else None
                if closes is not None:
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
) -> dict:
    """Compute hiring affordability for one or more proposed roles.

    Parameters
    ----------
    roles : list of dicts with keys: role, monthly_cost, is_revenue_generating
    """
    # ── Current financial picture ──
    current = {
        "monthly_revenue": _safe_round(monthly_revenue),
        "monthly_cogs": _safe_round(monthly_cogs),
        "gross_margin_pct": _safe_round(gross_margin_pct, 1),
        "monthly_opex": _safe_round(monthly_opex),
        "true_team_cost": round(true_team_cost, 2),
        "monthly_net": round(monthly_net_income, 2),
        "current_mrr": round(current_mrr, 2),
    }
    current["runway"] = _runway_status(monthly_net_income)

    # ── Per-role analysis ──
    per_role = []
    total_added_cost = 0.0
    total_revenue_generating_cost = 0.0
    total_closes_to_self_fund = 0.0

    for r in roles:
        cost = float(r.get("monthly_cost", 0))
        role_name = r.get("role", "New hire")
        is_rev = bool(r.get("is_revenue_generating", False))
        total_added_cost += cost
        if is_rev:
            total_revenue_generating_cost += cost

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
        if is_rev and analysis.get("closes_to_self_fund"):
            total_closes_to_self_fund += analysis["closes_to_self_fund"]

    # ── Combined impact ──
    new_team_cost = true_team_cost + total_added_cost
    new_monthly_net = monthly_net_income - total_added_cost
    headroom_before = monthly_net_income
    headroom_after = new_monthly_net

    # Team cost as % of MRR
    cost_as_pct_of_mrr = round(new_team_cost / current_mrr * 100, 1) if current_mrr > 0 else None
    mrr_threshold = round(new_team_cost / 0.40, 2) if new_team_cost > 0 else 0

    # Closes needed to offset ALL added cost (combined)
    combined_closes_to_offset = None
    if avg_cash_per_close and avg_cash_per_close > 0:
        combined_closes_to_offset = round(total_added_cost / avg_cash_per_close, 1)

    combined = {
        "total_added_cost": round(total_added_cost, 2),
        "new_team_cost": round(new_team_cost, 2),
        "headroom_before": round(headroom_before, 2),
        "headroom_after": round(headroom_after, 2),
        "can_afford": headroom_after > 0,
        "monthly_net_before": round(monthly_net_income, 2),
        "monthly_net_after": round(new_monthly_net, 2),
        "runway_after": _runway_status(new_monthly_net),
        "cost_as_pct_of_mrr": cost_as_pct_of_mrr,
        "mrr_threshold_for_hires": mrr_threshold,
        "combined_closes_to_offset": combined_closes_to_offset,
        "role_count": len(roles),
    }

    return json_safe({
        "current": current,
        "per_role": per_role,
        "combined": combined,
        "note": "Analysis only — the hire decision is yours.",
    })


def _safe_round(val, decimals=2):
    """Round if not None, return None otherwise."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isinf(val) or math.isnan(val)):
        return None
    return round(val, decimals)
