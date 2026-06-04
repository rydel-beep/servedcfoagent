"""
tests/test_hiring_v4.py
-----------------------
V4 hiring model tests: graded sustainability, cash projection, raise modeling.
"""
from hiring_model import _graded_sustainability, compute_hiring_analysis, json_safe


class TestGradedSustainability:
    """402% team ratio must grade UNSUSTAINABLE, not healthy."""

    def test_402_pct_is_unsustainable(self):
        result = _graded_sustainability(402.0, 100000, 5000)
        assert result["grade"] == "unsustainable"
        assert result["color"] == "red"

    def test_85_pct_is_unsustainable(self):
        result = _graded_sustainability(85.0, 100000, 5000)
        assert result["grade"] == "unsustainable"

    def test_60_pct_is_tight(self):
        result = _graded_sustainability(60.0, 100000, 5000)
        assert result["grade"] == "tight"
        assert result["color"] == "amber"

    def test_30_pct_is_healthy(self):
        result = _graded_sustainability(30.0, 100000, 5000)
        assert result["grade"] == "healthy"
        assert result["color"] == "green"

    def test_negative_cash_is_unsustainable(self):
        result = _graded_sustainability(30.0, -5000, 5000)
        assert result["grade"] == "unsustainable"

    def test_deep_negative_net_is_unsustainable(self):
        result = _graded_sustainability(30.0, 50000, -10000)
        assert result["grade"] == "unsustainable"

    def test_slight_negative_net_is_tight(self):
        result = _graded_sustainability(30.0, 50000, -2000)
        assert result["grade"] == "tight"

    def test_none_values_default_healthy(self):
        result = _graded_sustainability(None, None, None)
        assert result["grade"] == "healthy"


class TestCashProjection:
    """Cash projection must go negative when costs exceed revenue."""

    def _make_forward_mrr(self, monthly_values):
        return {
            "forward_months": [
                {"month": f"2026-{7+i:02d}", "recognized_mrr": v, "clients": 5}
                for i, v in enumerate(monthly_values)
            ],
            "current_recognized_mrr": monthly_values[0] if monthly_values else 0,
            "mtm_floor": 5000,
            "avg_monthly_per_client": 3000,
            "active_clients": 5,
            "expiry_schedule": [],
            "renewal_rate_historical": {"note": "0/12 (0%)"},
        }

    def test_cash_goes_negative_with_high_costs(self):
        # Starting with 10k cash, losing 5k/mo => negative by month 3
        result = compute_hiring_analysis(
            roles=[{"role": "Test", "monthly_cost": 5000, "is_revenue_generating": False}],
            monthly_net_income=0,
            current_mrr=20000,
            monthly_revenue=20000,
            monthly_cogs=10000,
            monthly_opex=10000,
            avg_contract_value=5000,
            close_rate_pct=30,
            avg_cash_per_close=5000,
            gross_margin_pct=50,
            true_team_cost=15000,
            forward_mrr=self._make_forward_mrr([20000, 18000, 15000, 10000, 8000, 5000]),
            cash_position={"total_available": 10000, "cash_in_bank": 10000},
        )
        fwd = result["forward_sustainability"]
        assert fwd is not None
        assert fwd["cash_runway_month"] is not None
        # At least one month should have negative cash
        negative = [f for f in fwd["forward_forecast"] if (f["cash_balance"] or 0) < 0]
        assert len(negative) > 0

    def test_cash_stays_positive_with_surplus(self):
        # Starting with 100k cash, MRR > costs => stays positive
        result = compute_hiring_analysis(
            roles=[{"role": "Test", "monthly_cost": 1000, "is_revenue_generating": False}],
            monthly_net_income=10000,
            current_mrr=50000,
            monthly_revenue=50000,
            monthly_cogs=10000,
            monthly_opex=10000,
            avg_contract_value=5000,
            close_rate_pct=30,
            avg_cash_per_close=5000,
            gross_margin_pct=50,
            true_team_cost=15000,
            forward_mrr=self._make_forward_mrr([50000, 50000, 50000, 50000, 50000, 50000]),
            cash_position={"total_available": 100000, "cash_in_bank": 100000},
        )
        fwd = result["forward_sustainability"]
        assert fwd["cash_runway_month"] is None
        negative = [f for f in fwd["forward_forecast"] if (f["cash_balance"] or 0) < 0]
        assert len(negative) == 0


class TestRaiseModeling:
    """Raise modeling must compute correctly and add to total cost."""

    def test_raise_increases_total_cost(self):
        result = compute_hiring_analysis(
            roles=[{"role": "New Dev", "monthly_cost": 3000, "is_revenue_generating": False}],
            monthly_net_income=20000,
            current_mrr=50000,
            monthly_revenue=50000,
            monthly_cogs=10000,
            monthly_opex=10000,
            avg_contract_value=5000,
            close_rate_pct=30,
            avg_cash_per_close=5000,
            gross_margin_pct=50,
            true_team_cost=15000,
            raises=[
                {"role": "Designer", "current_salary": 4000, "new_salary": 5000, "monthly_increase": 1000},
                {"role": "Editor", "current_salary": 3000, "new_salary": 3500, "monthly_increase": 500},
            ],
        )
        # Total added = 3000 (hire) + 1000 + 500 (raises) = 4500
        assert result["combined"]["total_added_cost"] == 4500
        assert result["combined"]["total_raise_cost"] == 1500
        assert len(result["raises"]) == 2

    def test_raise_details_preserved(self):
        result = compute_hiring_analysis(
            roles=[],
            monthly_net_income=20000,
            current_mrr=50000,
            monthly_revenue=50000,
            monthly_cogs=None,
            monthly_opex=None,
            avg_contract_value=None,
            close_rate_pct=None,
            avg_cash_per_close=None,
            gross_margin_pct=None,
            true_team_cost=15000,
            raises=[
                {"role": "Lead", "current_salary": 5000, "new_salary": 6000,
                 "monthly_increase": 1000, "is_spof": True},
            ],
        )
        r = result["raises"][0]
        assert r["role"] == "Lead"
        assert r["current_salary"] == 5000
        assert r["new_salary"] == 6000
        assert r["monthly_increase"] == 1000
        assert r["is_spof"] is True

    def test_no_raises_no_key(self):
        result = compute_hiring_analysis(
            roles=[{"role": "Test", "monthly_cost": 1000, "is_revenue_generating": False}],
            monthly_net_income=20000,
            current_mrr=50000,
            monthly_revenue=50000,
            monthly_cogs=None,
            monthly_opex=None,
            avg_contract_value=None,
            close_rate_pct=None,
            avg_cash_per_close=None,
            gross_margin_pct=None,
            true_team_cost=15000,
        )
        assert "raises" not in result


class TestJsonSafe:
    """JSON safety for Infinity/NaN."""

    def test_infinity_becomes_none(self):
        assert json_safe(float("inf")) is None
        assert json_safe(float("-inf")) is None

    def test_nan_becomes_none(self):
        assert json_safe(float("nan")) is None

    def test_nested(self):
        data = {"a": float("inf"), "b": [float("nan"), 1.0]}
        result = json_safe(data)
        assert result == {"a": None, "b": [None, 1.0]}
