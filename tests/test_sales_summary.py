"""
tests/test_sales_summary.py
----------------------------
Privacy boundary tests for the sales summary export.
Ensures no financial data leaks into the sales-team summary.
"""
import re

import pytest

from dashboard.sales_summary import build_sales_summary


# Minimal snapshot with both sales AND financial data.
# The summary must use ONLY the sales block.
_MOCK_SNAPSHOT = {
    "generated_at": "2026-06-02T18:00:00+10:00",
    "stripe": {"mrr": 62903, "revenue": {"current": {"total_aud": 55000}}},
    "xero": {"revenue": 48000, "gross_profit": 30000, "gross_margin_pct": 62.5, "net_profit": 15000},
    "profit": {"revenue": 48000, "net_profit": 15000, "gross_margin_pct": 62.5},
    "costs": {"closer_commission": 5500, "setter_commission": 2200},
    "revenue_views": {"stripe_cash_trailing_30d": 55000},
    "hormozi": {"M1_LTGP_CAC": {"value": 9.08, "status": "healthy"}},
    "active_clients": {"total_clients": 30, "total_mrr": 62903},
    "sales": {
        "funnel": {
            "leads_in": 45, "sets": 22, "shows": 15, "closes": 6, "dqs": 8,
            "lead_to_set_pct": 48.9, "set_to_show_pct": 68.2,
            "show_to_close_pct": 40.0, "lead_to_close_pct": 13.3,
            "dq_rate_pct": 17.8,
        },
        "velocity": {"days_lead_to_cash_median": 14, "days_lead_to_cash_avg": 18.5},
        "per_setter": [
            {"name": "Coby Goldner", "dials": 120, "sets": 10, "dials_per_set": 12.0,
             "show_pct": 70.0, "speed_to_lead_pct": 45.0},
            {"name": "Maran", "dials": 95, "sets": 12, "dials_per_set": 7.9,
             "show_pct": 66.7, "speed_to_lead_pct": 52.0},
        ],
        "per_closer": [
            {"name": "Kalin Long", "shows": 15, "closes": 6, "close_rate_pct": 40.0,
             "commission_total": 5500},
        ],
        "setter_activity": [],
        "setter_deep_dive": {"dials": 215, "connects": 80, "connect_rate_pct": 37.2,
                             "sets_booked": 22, "showed": 15, "closed": 6,
                             "five_min_rate_pct": 48.0, "calls_within_5_min": 103, "total_dials": 215},
        "payout": {"total_owed": 2200},
        "commission_detail": {"closer": {"total_commission_sheet": 5500}},
        "deep": {
            "leak_flags": ["Set→Show 68.2% vs target 70.0% — show-up leak"],
            "setter_performance": [
                {"name": "Coby Goldner", "speed_to_lead_pct": 45.0, "sets": 10},
                {"name": "Maran", "speed_to_lead_pct": 52.0, "sets": 12},
            ],
            "lead_quality": {
                "by_source": [
                    {"source": "Facebook", "leads": 25, "sets": 14, "closes": 4, "close_rate_pct": 16.0, "dq_rate_pct": 12.0},
                    {"source": "Google", "leads": 12, "sets": 5, "closes": 2, "close_rate_pct": 16.7, "dq_rate_pct": 16.7},
                    {"source": "Referral", "leads": 8, "sets": 3, "closes": 0, "close_rate_pct": 0.0, "dq_rate_pct": 25.0},
                ],
            },
            "loss": {
                "dq_reasons": [{"reason": "Too small", "count": 4, "pct": 50.0}],
                "no_show_pct": 10.0, "no_shows": 2, "total_sets": 22,
                "per_setter_noshow": [],
            },
        },
        "windows": [
            {"window_days": 7, "leads": 10, "sets": 5, "shows": 3, "closes": 1,
             "lead_to_set_pct": 50.0, "set_to_show_pct": 60.0,
             "show_to_close_pct": 33.3, "lead_to_close_pct": 10.0,
             "dq_rate_pct": 20.0, "dqs": 2, "median_days_to_close": 12,
             "per_setter": [{"name": "Coby Goldner", "dials": 30, "sets": 3, "dials_per_set": 10.0}],
             "per_closer": [{"name": "Kalin Long", "shows": 3, "closes": 1, "close_rate_pct": 33.3}]},
            {"window_days": 14, "leads": 20, "sets": 10, "shows": 7, "closes": 3,
             "lead_to_set_pct": 50.0, "set_to_show_pct": 70.0,
             "show_to_close_pct": 42.9, "lead_to_close_pct": 15.0,
             "dq_rate_pct": 15.0, "dqs": 3, "median_days_to_close": 13,
             "per_setter": [{"name": "Coby Goldner", "dials": 55, "sets": 5, "dials_per_set": 11.0}],
             "per_closer": [{"name": "Kalin Long", "shows": 7, "closes": 3, "close_rate_pct": 42.9}]},
            {"window_days": 30, "leads": 45, "sets": 22, "shows": 15, "closes": 6,
             "lead_to_set_pct": 48.9, "set_to_show_pct": 68.2,
             "show_to_close_pct": 40.0, "lead_to_close_pct": 13.3,
             "dq_rate_pct": 17.8, "dqs": 8, "median_days_to_close": 14,
             "per_setter": [], "per_closer": []},
            {"window_days": 60, "leads": 80, "sets": 40, "shows": 28, "closes": 10,
             "lead_to_set_pct": 50.0, "set_to_show_pct": 70.0,
             "show_to_close_pct": 35.7, "lead_to_close_pct": 12.5,
             "dq_rate_pct": 16.0, "dqs": 13, "median_days_to_close": 15,
             "per_setter": [], "per_closer": []},
            {"window_days": 90, "leads": 110, "sets": 55, "shows": 38, "closes": 14,
             "lead_to_set_pct": 50.0, "set_to_show_pct": 69.1,
             "show_to_close_pct": 36.8, "lead_to_close_pct": 12.7,
             "dq_rate_pct": 15.5, "dqs": 17, "median_days_to_close": 15,
             "per_setter": [], "per_closer": []},
        ],
    },
}

# Financial terms that must NEVER appear in the sales summary
_FORBIDDEN_TERMS = [
    "MRR", "mrr", "margin", "profit", "payroll", "CAC", "LTGP",
    "runway", "commission", "revenue", "salary", "wages",
    "owner pay", "team cost", "net profit", "gross margin",
]


def _check_no_financials(md: str, window_days: int):
    """Assert no forbidden financial terms appear in the markdown."""
    for term in _FORBIDDEN_TERMS:
        assert term not in md, (
            f"PRIVACY VIOLATION at {window_days}d: found '{term}' in sales summary"
        )
    # Also check no raw dollar amounts leak (financial figures)
    # Allow "$" only if not followed by large numbers (commission/revenue scale)
    dollar_matches = re.findall(r'\$[\d,]+', md)
    for m in dollar_matches:
        val = float(m.replace("$", "").replace(",", ""))
        assert val == 0, (
            f"PRIVACY VIOLATION at {window_days}d: found dollar amount '{m}' in sales summary"
        )


@pytest.mark.parametrize("window_days", [7, 14, 30, 60, 90])
def test_privacy_no_financials(window_days):
    """No financial data should appear at any window."""
    md = build_sales_summary(_MOCK_SNAPSHOT, window_days)
    _check_no_financials(md, window_days)


@pytest.mark.parametrize("window_days", [7, 14, 30, 60, 90])
def test_contains_funnel_data(window_days):
    """Summary must contain funnel counts."""
    md = build_sales_summary(_MOCK_SNAPSHOT, window_days)
    assert "Leads:" in md
    assert "Sets:" in md
    assert "Shows:" in md
    assert "Closes:" in md


def test_window_7d_uses_window_data():
    """7d window should use the 7-day window data, not 30d."""
    md = build_sales_summary(_MOCK_SNAPSHOT, 7)
    assert "Trailing 7 days" in md
    assert "Leads: **10**" in md  # 7d has 10 leads, not 45


def test_window_30d_uses_funnel():
    """30d window should use the primary funnel data."""
    md = build_sales_summary(_MOCK_SNAPSHOT, 30)
    assert "Trailing 30 days" in md
    assert "Leads: **45**" in md


def test_window_90d_uses_window_data():
    """90d window should use 90-day window data."""
    md = build_sales_summary(_MOCK_SNAPSHOT, 90)
    assert "Trailing 90 days" in md
    assert "Leads: **110**" in md


def test_contains_rep_performance():
    """Rep names and performance metrics should appear."""
    md = build_sales_summary(_MOCK_SNAPSHOT, 30)
    assert "Coby Goldner" in md
    assert "Kalin Long" in md
    assert "close rate" in md.lower() or "close_rate" in md.lower()


def test_contains_lead_quality():
    """Lead quality by source should be present."""
    md = build_sales_summary(_MOCK_SNAPSHOT, 30)
    assert "Facebook" in md
    assert "Google" in md


def test_contains_speed_to_lead():
    """Speed-to-lead section should be present."""
    md = build_sales_summary(_MOCK_SNAPSHOT, 30)
    assert "Speed-to-Lead" in md
