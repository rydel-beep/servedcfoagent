"""
financial_position.py
---------------------
Single coherent financial model for the business, presented on two bases:
  - CASH basis: Stripe cash collected (real money in the bank)
  - RECOGNIZED basis: Xero P&L (accounting view, service delivery timing)

Both bases use the SAME cost figures — only revenue differs.
This is the ONE source of truth for all financial position displays.
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


def _net_status(monthly_net) -> dict:
    """Return a status dict for a monthly net figure."""
    if monthly_net is None:
        return {"status": "unknown", "label": "Data unavailable"}
    if monthly_net > 0:
        return {"status": "surplus", "label": f"Surplus ${monthly_net:,.0f}/mo"}
    if monthly_net == 0:
        return {"status": "breakeven", "label": "Breakeven"}
    return {"status": "burn", "label": f"Burning ${abs(monthly_net):,.0f}/mo"}


def build_financial_position(
    # Cash basis inputs
    stripe_cash_30d: float | None = None,
    # Recognized basis inputs (from Xero P&L)
    xero_revenue: float | None = None,
    xero_cogs: float | None = None,
    xero_gross_profit: float | None = None,
    xero_gross_margin_pct: float | None = None,
    xero_opex: float | None = None,
    xero_net_profit: float | None = None,
    # Cost inputs (same for both bases)
    true_team_cost: float = 0.0,
    ad_spend: float | None = None,
    # MRR for ratio calculations
    current_mrr: float = 0.0,
) -> dict:
    """Build the dual-basis financial position model.

    Returns a dict with 'cash_basis', 'recognized_basis', 'costs', and 'ratios'.
    """
    # ── Shared cost structure ──
    costs = {
        "true_team_cost": round(true_team_cost, 2),
        "ad_spend": _safe_round(ad_spend),
        "team_cost_pct_of_mrr": (
            round(true_team_cost / current_mrr * 100, 1)
            if current_mrr > 0 else None
        ),
        "team_cost_benchmark": "healthy" if (
            current_mrr > 0 and true_team_cost / current_mrr < 0.45
        ) else "elevated" if (
            current_mrr > 0 and true_team_cost / current_mrr < 0.55
        ) else "high" if current_mrr > 0 else "unknown",
    }

    # ── Cash basis ──
    # Stripe cash is total cash in, team cost is total fixed cost out.
    # Cash net = stripe_cash - true_team_cost - ad_spend - other opex
    # For a simple view: cash net = stripe_cash - all costs
    # But we don't have full cash-basis costs broken out, so we estimate:
    # If Xero net profit is available, cash-basis net ≈ stripe_cash - xero_revenue + xero_net
    # Simpler: show stripe cash as revenue line, and use Xero cost structure
    cash_basis = None
    if stripe_cash_30d is not None:
        # Use Xero's cost structure but with Stripe cash as revenue
        cash_costs = (
            (xero_cogs or 0) + (xero_opex or 0)
        ) if xero_cogs is not None or xero_opex is not None else None

        if cash_costs is not None:
            cash_net = stripe_cash_30d - cash_costs
            cash_gp = stripe_cash_30d - (xero_cogs or 0)
            cash_gm = round(cash_gp / stripe_cash_30d * 100, 1) if stripe_cash_30d > 0 else None
        else:
            cash_net = None
            cash_gp = None
            cash_gm = None

        cash_basis = {
            "label": "Cash Basis (Stripe)",
            "revenue": round(stripe_cash_30d, 2),
            "cogs": _safe_round(xero_cogs),
            "gross_profit": _safe_round(cash_gp),
            "gross_margin_pct": cash_gm,
            "opex": _safe_round(xero_opex),
            "monthly_net": _safe_round(cash_net),
            "status": _net_status(cash_net),
            "hiring_headroom": _safe_round(cash_net),
        }

    # ── Recognized basis ──
    recognized_basis = None
    if xero_net_profit is not None:
        recognized_basis = {
            "label": "Recognized Basis (Xero P&L)",
            "revenue": _safe_round(xero_revenue),
            "cogs": _safe_round(xero_cogs),
            "gross_profit": _safe_round(xero_gross_profit),
            "gross_margin_pct": _safe_round(xero_gross_margin_pct, 1),
            "opex": _safe_round(xero_opex),
            "monthly_net": round(xero_net_profit, 2),
            "status": _net_status(xero_net_profit),
            "hiring_headroom": round(xero_net_profit, 2),
        }

    # ── Pick the best available for the headline ──
    # Prefer cash basis (real money), fall back to recognized
    headline_net = None
    headline_basis = None
    if cash_basis and cash_basis["monthly_net"] is not None:
        headline_net = cash_basis["monthly_net"]
        headline_basis = "cash"
    elif recognized_basis and recognized_basis["monthly_net"] is not None:
        headline_net = recognized_basis["monthly_net"]
        headline_basis = "recognized"

    return json_safe({
        "cash_basis": cash_basis,
        "recognized_basis": recognized_basis,
        "costs": costs,
        "headline": {
            "monthly_net": headline_net,
            "basis": headline_basis,
            "status": _net_status(headline_net),
            "hiring_headroom": headline_net,
        },
        "current_mrr": round(current_mrr, 2),
    })
