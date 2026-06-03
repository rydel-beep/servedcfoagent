"""
hiring_model.py
---------------
Hiring affordability analysis. For any proposed hire (role + monthly cost),
computes affordability, payback, and the additional sales needed to fund it.

All analysis, no decisions — the hire decision is Rydel's.
"""
from __future__ import annotations


def compute_hiring_analysis(
    proposed_cost: float,
    proposed_role: str,
    is_revenue_generating: bool,
    monthly_net_income: float,
    current_mrr: float,
    avg_contract_value: float | None,
    close_rate_pct: float | None,
    avg_cash_per_close: float | None,
    gross_margin_pct: float | None,
    true_team_cost: float,
) -> dict:
    """Compute hiring affordability for a proposed role.

    Returns analysis dict with affordability, payback, and required sales.
    """
    # Monthly headroom = net income after all costs
    headroom = monthly_net_income
    headroom_after_hire = headroom - proposed_cost
    can_afford = headroom_after_hire > 0

    # Months of runway at current headroom (before going cash-negative)
    months_runway = None
    if proposed_cost > 0 and headroom > 0:
        if headroom_after_hire > 0:
            months_runway = float("inf")  # indefinite
        else:
            months_runway = round(headroom / proposed_cost, 1)

    # Payback analysis for revenue-generating hires
    payback_months = None
    additional_closes_needed = None
    additional_mrr_needed = None

    if is_revenue_generating and avg_cash_per_close and avg_cash_per_close > 0:
        # How many closes/month does this hire need to cover their cost?
        closes_to_cover = proposed_cost / avg_cash_per_close
        additional_closes_needed = round(closes_to_cover, 1)

        # At current close rate, how many additional leads needed?
        if close_rate_pct and close_rate_pct > 0:
            additional_leads = closes_to_cover / (close_rate_pct / 100)
        else:
            additional_leads = None

        payback_months = 1.0  # self-funding from month 1 if they hit targets
    else:
        # Non-revenue hire: how many additional clients needed at current margin?
        if gross_margin_pct and avg_contract_value and avg_contract_value > 0:
            monthly_rev_per_client = avg_contract_value / 6  # typical 6-month contract
            gp_per_client = monthly_rev_per_client * (gross_margin_pct / 100)
            clients_to_cover = proposed_cost / gp_per_client if gp_per_client > 0 else None
            additional_mrr_needed = round(proposed_cost / (gross_margin_pct / 100), 2) if gross_margin_pct > 0 else None
        else:
            clients_to_cover = None

    # Impact on team cost ratio
    new_team_cost = true_team_cost + proposed_cost
    cost_as_pct_of_mrr = round(new_team_cost / current_mrr * 100, 1) if current_mrr > 0 else None

    # MRR threshold: at what MRR does this hire become comfortably affordable?
    # Rule: team cost should be <40% of MRR for a healthy agency
    mrr_threshold = round(new_team_cost / 0.40, 2)

    return {
        "proposed_role": proposed_role,
        "proposed_cost": proposed_cost,
        "is_revenue_generating": is_revenue_generating,
        "current_headroom": round(headroom, 2),
        "headroom_after_hire": round(headroom_after_hire, 2),
        "can_afford": can_afford,
        "months_runway": months_runway,
        "payback_months": payback_months,
        "additional_closes_needed": additional_closes_needed,
        "additional_mrr_needed": additional_mrr_needed,
        "new_team_cost": round(new_team_cost, 2),
        "cost_as_pct_of_mrr": cost_as_pct_of_mrr,
        "mrr_threshold_for_hire": mrr_threshold,
        "note": "Analysis only — the hire decision is yours.",
    }
