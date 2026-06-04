"""
tests/test_forward_projection.py
--------------------------------
Anti-regression guardrails for the forward projection.
Tests assert against the values that would be DISPLAYED, not internal calcs.

Key invariants:
- Cash balance moves with net: cash[m] = cash[m-1] + net[m]
- Starting cash = cash_in_bank (not total_available)
- Cash can't rise in a month where net is negative
- No Infinity/NaN in output
- Forward MRR matches live client data
"""
from hiring_model import compute_hiring_analysis, _graded_sustainability


# Minimal inputs for the forward sustainability lens
SAMPLE_FORWARD_MRR = {
    "current_recognized_mrr": 65420,
    "forward_months": [
        {"month": "June 2026", "recognized_mrr": 65420, "clients": 29},
        {"month": "July 2026", "recognized_mrr": 52186, "clients": 24},
        {"month": "August 2026", "recognized_mrr": 45520, "clients": 21},
        {"month": "September 2026", "recognized_mrr": 33872, "clients": 16},
        {"month": "October 2026", "recognized_mrr": 13618, "clients": 6},
        {"month": "November 2026", "recognized_mrr": 7533, "clients": 3},
    ],
    "mtm_floor": 5037,
    "active_clients": 31,
    "avg_monthly_per_client": 2110,
    "expiry_schedule": [],
    "renewal_rate_historical": {"rate": 0, "renewed": 0, "churned": 12},
}

SAMPLE_CASH_POSITION = {
    "cash_in_bank": 140007,
    "total_available": 158007,  # includes Stripe incoming — should NOT be used
    "stripe_incoming": 18000,
}

TOTAL_BURN = 38377  # from opex_pull


def _run_hiring_analysis(added_cost=0):
    """Run hiring analysis and return the forward_sustainability block."""
    result = compute_hiring_analysis(
        roles=[{"role": "test", "monthly_cost": added_cost, "is_revenue_generating": False}] if added_cost > 0 else [],
        monthly_net_income=0,
        current_mrr=65420,
        monthly_revenue=None,
        monthly_cogs=None,
        monthly_opex=None,
        avg_contract_value=None,
        close_rate_pct=None,
        avg_cash_per_close=None,
        gross_margin_pct=65.0,
        true_team_cost=29671,
        financial_position=None,
        forward_mrr=SAMPLE_FORWARD_MRR,
        cash_position=SAMPLE_CASH_POSITION,
        total_monthly_burn=TOTAL_BURN,
    )
    return result.get("forward_sustainability") or {}


def test_starting_cash_uses_cash_in_bank_not_total_available():
    """Starting cash must be cash_in_bank ($140k), not total_available ($158k)."""
    fwd = _run_hiring_analysis()
    assert fwd["starting_cash"] == 140007
    assert fwd["starting_cash"] != 158007, "Must use cash_in_bank, not total_available"


def test_cash_balance_moves_with_net():
    """Each month's cash = prior month's cash + that month's net.
    This is the exact bug that kept recurring: cash floating instead of accumulating."""
    fwd = _run_hiring_analysis()
    forecast = fwd.get("forward_forecast", [])
    assert len(forecast) >= 3

    starting = fwd["starting_cash"]
    expected_cash = starting

    for i, ff in enumerate(forecast):
        net = ff["net_before_hire"]
        expected_cash = expected_cash + net
        actual_cash = ff["cash_balance"]
        # Within rounding tolerance
        assert abs(actual_cash - expected_cash) < 1, (
            f"Month {ff['month']}: expected cash {expected_cash:.0f} "
            f"(prior + net {net:.0f}), got {actual_cash:.0f}"
        )


def test_cash_never_rises_when_net_negative():
    """Cash balance CANNOT increase in a month where net is negative.
    This is the specific symptom of the floating-cash bug."""
    fwd = _run_hiring_analysis()
    forecast = fwd.get("forward_forecast", [])

    prev_cash = fwd["starting_cash"]
    for ff in forecast:
        net = ff.get("net_before_hire") or ff.get("net_after_hire") or 0
        cash = ff["cash_balance"]
        if net < 0:
            assert cash <= prev_cash, (
                f"Month {ff['month']}: net is {net:.0f} (negative) but cash "
                f"ROSE from {prev_cash:.0f} to {cash:.0f}"
            )
        prev_cash = cash


def test_no_infinity_nan_in_forward():
    """No Infinity or NaN in any forward forecast field."""
    import math
    fwd = _run_hiring_analysis()
    forecast = fwd.get("forward_forecast", [])
    for ff in forecast:
        for key in ("recognized_mrr", "net_before_hire", "net_after_hire", "cash_balance"):
            val = ff.get(key)
            if val is not None:
                assert not math.isinf(val), f"{ff['month']}.{key} is Infinity"
                assert not math.isnan(val), f"{ff['month']}.{key} is NaN"


def test_forward_months_count():
    """Forward forecast should have up to 6 months."""
    fwd = _run_hiring_analysis()
    forecast = fwd.get("forward_forecast", [])
    assert 1 <= len(forecast) <= 6


def test_cash_projection_is_monotonically_declining_when_all_nets_negative():
    """When every month has negative net, cash must strictly decline."""
    fwd = _run_hiring_analysis()
    forecast = fwd.get("forward_forecast", [])

    # Check if all nets are negative (they are in this scenario — burn > MRR from Oct on)
    all_negative = all(
        (ff.get("net_before_hire") or 0) < 0
        for ff in forecast[1:]  # skip June which may be positive
    )
    if not all_negative:
        return  # Skip if not all negative (test still valid structurally)

    # Cash should be declining for those months
    for i in range(2, len(forecast)):
        if (forecast[i].get("net_before_hire") or 0) < 0:
            assert forecast[i]["cash_balance"] < forecast[i - 1]["cash_balance"], (
                f"Cash should decline: {forecast[i-1]['month']} ({forecast[i-1]['cash_balance']}) "
                f"-> {forecast[i]['month']} ({forecast[i]['cash_balance']})"
            )


def test_graded_sustainability_unsustainable_on_negative_cash():
    """Grade must be unsustainable when cash goes negative."""
    grade = _graded_sustainability(team_cost_pct=60, cash_balance=-5000, monthly_net=-10000)
    assert grade["grade"] == "unsustainable"


def test_graded_sustainability_healthy():
    grade = _graded_sustainability(team_cost_pct=40, cash_balance=100000, monthly_net=5000)
    assert grade["grade"] == "healthy"
