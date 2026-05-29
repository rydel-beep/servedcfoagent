"""
tests/test_xero_wages_categoriser.py
------------------------------------
Tests for the wages categoriser and true_team_cost computation.
Includes regression test for the May 2026 parser bug.
"""
from __future__ import annotations

import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xero_wages_categoriser import (
    identify_account_bucket,
    compute_true_team_cost,
    compute_owner_pay_breakdown,
    categorise_contractors_account,
    flag_window_straddle,
    OWNER_RECURRING_GROSS_MONTHLY,
)


def test_contractor_no_gst_entry_not_misidentified_as_wages():
    """Regression test for May 2026 parser bug.

    A Contractors NO GST entry with a payee that happens to be a sales team
    member must not be categorised as Wages and Salaries. Account
    identification is by account_name explicitly, never by payee inference.
    """
    fixture = {
        "account_name": "Contractors NO GST",
        "account_id": "abc123",
        "payee": "Kalin Long",
        "amount": 1700,
    }
    result = identify_account_bucket(fixture)
    assert result == "Contractors NO GST"
    assert result != "Wages and Salaries"


def test_wages_entry_identified_correctly():
    """Wages and Salaries entry returns its account name."""
    fixture = {
        "account_name": "Wages and Salaries",
        "payee": "Rydel Limjoco",
        "amount": 2241,
    }
    result = identify_account_bucket(fixture)
    assert result == "Wages and Salaries"


def test_unknown_account_name():
    """Missing account_name returns UNKNOWN."""
    assert identify_account_bucket({}) == "UNKNOWN"
    assert identify_account_bucket({"payee": "Someone"}) == "UNKNOWN"


def test_true_team_cost_with_baseline():
    """True team cost = SALARY tab + owner gross + super baseline."""
    result = compute_true_team_cost(salary_tab_baseline=18891.0)
    total = result["true_team_cost_monthly"]
    # $18,891 + $9,704.13 + $1,076 = $29,671.13
    assert 29600 < total < 29750, f"Expected ~$29,671, got {total}"
    assert result["confidence"] == "high"
    assert len(result["components"]) == 3


def test_true_team_cost_uses_gross_not_net():
    """Owner pay component must use gross ($9,704), not net ($6,800)."""
    result = compute_true_team_cost(salary_tab_baseline=18891.0)
    owner_comp = [c for c in result["components"] if c["name"] == "owner_recurring_gross"][0]
    assert owner_comp["value"] > 9000, "Owner pay should be gross (~$9,704), not net (~$6,800)"
    assert owner_comp["value"] < 10000


def test_true_team_cost_missing_baseline():
    """Missing SALARY tab baseline → medium confidence with flag."""
    result = compute_true_team_cost(salary_tab_baseline=None)
    assert result["confidence"] == "medium"
    assert result["flags"] is not None


def test_owner_pay_breakdown_clean_month():
    """May 2026: $6,723 = 3 weeks × $2,241 → zero excess."""
    result = compute_owner_pay_breakdown(6723.0, window_start=date(2026, 5, 1))
    assert result["weeks_detected"] == 3
    assert result["recurring_gross"] == 3 * 2241
    assert result["excess"] == 0


def test_owner_pay_breakdown_april_bonus():
    """April 2026: $66,205 = 4 × $2,241 + $57,241 excess."""
    result = compute_owner_pay_breakdown(66205.0, window_start=date(2026, 4, 1))
    assert result["weeks_detected"] == 4
    assert result["recurring_gross"] == 4 * 2241
    assert result["excess"] == 66205 - (4 * 2241)
    assert "excess_flag" in result


def test_window_straddle_pre_fix():
    """Window starting before 2026-05-31 triggers straddle warning."""
    result = flag_window_straddle(date(2026, 5, 1))
    assert result["window_straddle"] is True


def test_window_straddle_post_fix():
    """Window starting on or after 2026-05-31 → no straddle."""
    result = flag_window_straddle(date(2026, 6, 1))
    assert result["window_straddle"] is False


def test_categorise_contractors():
    """Contractors split: SALARY tab as team payroll, remainder as COGS."""
    result = categorise_contractors_account(
        contractors_total=25000.0,
        salary_tab_baseline=18891.0,
    )
    assert result["team_payroll_via_wise"] == 18891.0
    assert result["subcontractor_cogs"] == 25000.0 - 18891.0


def test_owner_recurring_gross_monthly_value():
    """Verify the computed constant matches $2,241 × 4.33."""
    expected = round(2241 * 4.33, 2)
    assert OWNER_RECURRING_GROSS_MONTHLY == expected


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
