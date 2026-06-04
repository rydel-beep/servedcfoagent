"""
tests/test_opex_pull.py
-----------------------
Tests for the categorised monthly burn breakdown.
"""
from opex_pull import get_monthly_burn


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


def test_commissions_excluded_from_burn():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["commissions"] == 4200 + 3221
    # Commissions should NOT be in total_recurring_burn
    assert result["total_recurring_burn"] == result["total_with_commissions"] - result["commissions"]


def test_travel_excluded_as_one_off():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    assert result["one_off_excluded"] >= 2998 + 51


def test_consulting_split_recurring_vs_one_off():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    # Only $179 recurring, rest is one-off
    one_off_consulting = 1174 - 179
    assert result["one_off_excluded"] >= one_off_consulting
    # other_opex should include only $179 from consulting
    assert result["other_opex"] >= 179


def test_contractors_with_gst_is_cogs():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    # Contractors WITH GST ($1,336) should be in cogs_delivery
    assert result["cogs_delivery"] >= 1336


def test_contractors_no_gst_split():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    # Contractors NO GST ($20,127) split: $18,891 team + $1,236 subcontractor
    sub_portion = 20127 - SALARY_BASELINE
    assert result["cogs_delivery"] >= sub_portion


def test_no_double_count_team():
    """Wages + Super + team portion of Contractors NO GST should NOT inflate burn."""
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    # Total burn should be team_cost + non-team items, NOT team_cost + all Xero expenses
    xero_total = sum(l["amount"] for l in SAMPLE_XERO["opex_line_items"]) + sum(l["amount"] for l in SAMPLE_XERO["cogs_line_items"])
    assert result["total_recurring_burn"] < xero_total


def test_cogs_ratio():
    result = get_monthly_burn(SAMPLE_XERO, TEAM_COST, SALARY_BASELINE)
    expected = round(27895 / 79708 * 100, 1)
    assert result["cogs_ratio_pct"] == expected


def test_no_xero_data_fallback():
    result = get_monthly_burn(None, TEAM_COST, SALARY_BASELINE)
    assert not result["available"]
    assert result["total_recurring_burn"] == TEAM_COST
