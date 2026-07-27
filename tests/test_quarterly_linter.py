"""Adversarial: each audited defect (D1-D5) reintroduced must trip the linter."""
import pytest
from quarterly_format import fmt_metric, fmt_delta, type_of
from quarterly_linter import lint, LintError


def _clean_review():
    return {
        "quarter": {"label": "Q2 2026"},
        "current": {"unit_economics": {"ltgp_cac": 4.51, "roas": 10.38,
                                       "components": {"cac_loaded": 2718.0, "closes": 16}}},
        "three_x": {
            "targets": {"contracted_revenue": 696000, "new_deal_cash_collected": 294765, "closes": 48},
            "targets_current": {"contracted_revenue": 232000, "new_deal_cash_collected": 98255, "closes": 16},
            "funnel": {"volume_path": {"flag": "plausible"}},
            "requirements_table": [{"lever": "Lead volume (volume path)", "flag": "plausible"}],
            "churn": {"available": False},
        }}


def test_format_types():
    assert fmt_metric("LTGP:CAC", 4.51) == "4.51x"          # D1: ratio, not "$5"
    assert fmt_metric("Contracted revenue", 253200) == "$253,200"
    assert fmt_metric("Lead->close %", 6.0) == "6.0%"
    assert fmt_metric("Closes", 16) == "16"
    assert type_of("LTGP:CAC") == "ratio"


def test_clean_passes():
    assert lint(["LTGP:CAC 4.51x 4.72x -0.21x", "Contracted revenue $232,000 $200,000 +$32,000"],
                _clean_review())["ok"]


def test_d1_ratio_as_dollars_caught():
    with pytest.raises(LintError):
        lint(["LTGP:CAC $5 $6 -$1"], _clean_review())


def test_d2_blank_current_caught():
    r = _clean_review(); r["three_x"]["targets_current"] = {"contracted_revenue": None,
        "new_deal_cash_collected": None, "closes": None}
    with pytest.raises(LintError):
        lint([], r)


def test_d3_flag_contradiction_caught():
    r = _clean_review(); r["three_x"]["funnel"]["volume_path"]["flag"] = "out-of-trend"  # table says plausible
    with pytest.raises(LintError):
        lint([], r)


def test_d4_degenerate_churn_caught():
    r = _clean_review(); r["three_x"]["churn"] = {"current_closing_mrr": 85996, "current_churn_mrr": 85996}
    with pytest.raises(LintError):
        lint([], r)


def test_d4_target_smaller_than_current_caught():
    r = _clean_review(); r["three_x"]["targets"]["closes"] = 10  # < current 16
    with pytest.raises(LintError):
        lint([], r)


def test_d5_fragment_is_warning_not_fatal():
    res = lint(["At the current CPL. held constant at $2,718 -- CAC drift"], _clean_review())
    assert res["ok"] and any("D5" in w for w in res["warnings"])
