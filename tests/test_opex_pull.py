"""
tests/test_opex_pull.py
-----------------------
Tests for the categorised monthly burn breakdown.
"""
from opex_pull import get_monthly_burn, SUBSCRIPTIONS_OVERRIDE, OWNER_TAKEHOME_MONTHLY, AD_SPEND_FALLBACK, OTHER_OPEX_FALLBACK


SAMPLE_XERO = {
    "revenue": 79708,
    "cogs": 27895,
    "gross_margin_pct": 65.0,
    "opex_line_items": [
        {"label": "Advertising", "amount": 8002},
        {"label": "Bank Fees", "amount": 605},
        {"label": "Closer Commission", "amount": 4200},
        {"label": "Consulting & Accounting", "amount": 1174},
        {"label": "Contractors WITH GST REMITTLY", "amount": 1336},
        {"label": "Office Expenses", "amount": 33},
        {"label": "Setter Commission", "amount": 3221},
        {"label": "Subscriptions", "amount": 228},
        {"label": "Superannuation", "amount": 1076},
        {"label": "Telephone & Internet", "amount": 154},
        {"label": "Travel - International", "amount": 2998},
        {"label": "Travel - National", "amount": 51},
        {"label": "Wages and Salaries", "amount": 8964},
    ],
    "cogs_line_items": [
        {"label": "Client Reporting Tools", "amount": 7769},
        {"label": "Contractors NO GST", "amount": 20127},
    ],
}

TEAM_COST = 29671.0
SALARY_BASELINE = 18891.0


def test_total_burn_exceeds_team_cost():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["available"]
    assert result["total_recurring_burn"] > TEAM_COST


def test_ad_spend_extracted():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["ad_spend"] == 8002


def test_subscriptions_uses_hardcoded_override():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["subscriptions"] == SUBSCRIPTIONS_OVERRIDE
    assert result["subscriptions"] == 3867.0


def test_commissions_excluded_from_burn():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["commissions"] == 4200 + 3221
    # Commissions not in total_recurring_burn
    assert result["total_recurring_burn"] < result["total_with_commissions"]


def test_travel_excluded_as_one_off():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["one_off_excluded"] >= 2998 + 51


def test_consulting_split_recurring_vs_one_off():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    one_off_consulting = 1174 - 179
    assert result["one_off_excluded"] >= one_off_consulting
    assert result["other_opex"] >= 179


def test_contractors_with_gst_is_variable_cogs():
    """Videog/photog is variable COGS, not fixed burn."""
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["variable_cogs"] >= 1336


def test_colby_shaw_subcontractor_is_variable():
    """Subcontractor portion of Contractors NO GST is variable, not fixed."""
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    sub_portion = 20127 - SALARY_BASELINE
    assert result["variable_cogs"] >= sub_portion


def test_no_double_count_team():
    """Team cost items from Xero should NOT inflate the burn total."""
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    # Fixed burn = team_wise + owner_pay + ad + subs + other_opex
    expected = SALARY_BASELINE + OWNER_TAKEHOME_MONTHLY + 8002 + SUBSCRIPTIONS_OVERRIDE + result["other_opex"]
    assert abs(result["total_recurring_burn"] - expected) < 0.01


def test_team_is_salary_baseline_not_true_team_cost():
    """Team in burn should be SALARY tab ($18,891), not true_team_cost ($29,671)."""
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["team"] == SALARY_BASELINE
    assert result["owner_pay"] == OWNER_TAKEHOME_MONTHLY


def test_variable_cogs_excluded_from_fixed_burn():
    """Variable COGS (videog, subcontractors) not in total_recurring_burn."""
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["variable_cogs"] > 0
    assert result["total_with_variable"] == result["total_recurring_burn"] + result["variable_cogs"]


def test_cogs_ratio():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    expected = round(27895 / 79708 * 100, 1)
    assert result["cogs_ratio_pct"] == expected


def test_no_xero_data_fallback():
    """When Xero is down, burn includes hardcoded fallbacks for all components."""
    result = get_monthly_burn(None, TEAM_COST, SALARY_BASELINE)
    assert not result["available"]
    assert result["team"] == SALARY_BASELINE
    assert result["owner_pay"] == OWNER_TAKEHOME_MONTHLY
    assert result["ad_spend"] == AD_SPEND_FALLBACK
    assert result["subscriptions"] == SUBSCRIPTIONS_OVERRIDE
    assert result["other_opex"] == OTHER_OPEX_FALLBACK
    expected_total = SALARY_BASELINE + OWNER_TAKEHOME_MONTHLY + AD_SPEND_FALLBACK + SUBSCRIPTIONS_OVERRIDE + OTHER_OPEX_FALLBACK
    assert result["total_recurring_burn"] == expected_total
