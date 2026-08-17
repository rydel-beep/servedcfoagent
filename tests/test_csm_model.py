"""Regression + ruling tests for csm_model (DECISIONS #146).

The source figures (Sequence-to-Success v2) are the regression target; the
two ROI clocks, the layer/hire lens, funding-path purity, clawback and the
4x solve are the rulings under test.
"""

import csm_model as m


def test_regression_reproduces_source():
    result = m.regression_check()
    assert result["ok"], [c for c in result["checks"] if not c["ok"]]


def test_loaded_cost_matches_quoted():
    assert abs(m.loaded_cost_annual(80_000.0) - 89_600.0) < 1.0


def test_contractor_form_is_flat():
    assert m.loaded_cost_annual(80_000.0, {"employment_form": "contractor"}) == 80_000.0


def test_cohort_and_steady_state_never_blended():
    """Synthetic check: the two clocks are separate keys, computed on
    different windows, and steady-state only exists from month 13."""
    curve = m.monthly_curve("base")
    ss = m.steady_state_roi(curve)
    assert ss["from_month"] == 13
    assert ss["series"][0]["month"] == 13
    base = m.scenario_roi("base")
    # cohort divides lifetime by ONE year of cost; steady-state divides
    # trailing-12 by trailing-12 — at month 13+ the values must differ
    # (tail months carry lower lift than the cohort ratio implies).
    assert base["cohort_roi_loaded"] != ss["series"][-1]["steady_state_roi"]
    # no blended field exists anywhere
    for k in base:
        assert "blend" not in k
    for row in ss["series"]:
        assert "cohort" not in row


def test_y1_4x_unattainable_in_all_scenarios():
    for name in ("floor", "base", "upside"):
        s = m.scenario_roi(name)
        assert s["y1_roi_loaded"] < 4.0
        assert s["y1_roi_unloaded"] < 4.0


def test_4x_solve_between_base_and_upside():
    s = m.solve_renewal_for_cohort_roi(4.0)
    assert s["between_base_and_upside"]
    assert 60.0 <= s["renewal_pct"] <= 72.0
    assert s["clock"] == "cohort"
    assert s["cost_basis"] == "loaded"


def test_monthly_sums_to_annual():
    for name in ("floor", "base", "upside"):
        curve = m.monthly_curve(name)
        a = m.SCENARIO_ANCHORS[name]
        y1 = sum(r["credited_lift"] for r in curve["months"][:12])
        life = sum(r["credited_lift"] for r in curve["months"])
        assert abs(y1 - (a["net_y1"] + a["ote"])) < 1.0
        assert abs(life - (a["net_lifetime"] + a["ote"])) < 1.0


def test_ramp_months_below_steady():
    curve = m.monthly_curve("base")
    ms = curve["months"]
    assert ms[0]["credited_lift"] < ms[2]["credited_lift"]
    assert ms[1]["credited_lift"] < ms[2]["credited_lift"]


def test_layer_vs_hire_differ_by_structural_lift_exactly():
    lv = m.layer_vs_hire("base", structural_split=0.5)
    a = m.SCENARIO_ANCHORS["base"]
    credited = a["net_lifetime"] + a["ote"]
    loaded = m.loaded_cost_annual(a["ote"])
    expect_delta = lv["structural_lift"] / loaded
    assert abs((lv["layer_roi_loaded"] - lv["hire_roi_loaded"]) - expect_delta) < 0.02
    # structural share is small on source numbers
    assert lv["structural_lift"] < 0.06 * credited


def test_layer_vs_hire_default_split_labelled_placeholder():
    lv = m.layer_vs_hire("base")
    assert lv["structural_split_label"] == "placeholder"


def test_funding_path_pure_and_unconfigured_state():
    # unconfigured: no offset numbers invented
    fp = m.funding_paths(89_600.0, None, None)
    assert fp["configured"] is False
    assert fp["offset_funded"] is None
    assert "not set" in fp["note"]
    # configured (synthetic figures — NOT director figures): delta math exact
    fp2 = m.funding_paths(89_600.0, 100_000.0, 20_000.0, sg_rate=0.12)
    assert fp2["configured"] is True
    assert abs(fp2["offset_funded"]["loaded_offset"] - 89_600.0) < 0.01
    assert abs(fp2["offset_funded"]["fixed_cost_delta"] - 0.0) < 0.01
    assert fp2["business_cash_funded"]["director_income"] == "unchanged"
    # the financing-view warning is always present when configured
    assert "NEVER ROI" in fp2["financing_view_warning"]


def test_comp_accrual_matches_table_and_clawback():
    events = [
        {"type": "renewal"},                                    # +500
        {"type": "renewal", "months_to_churn": 2},              # clawed back
        {"type": "lock12"},                                     # +800
        {"type": "stepup", "first6_value": 6_000.0},            # +600
        {"type": "sprint", "first6_value": 3_000.0},            # +300
        {"type": "continuity_save"},                            # +150
        {"type": "referral", "amount": 10_000.0},               # +500
        {"type": "nrr_quarter", "nrr": 1.02},                   # +1500
        {"type": "nrr_quarter", "nrr": 0.97},                   # +0
    ]
    acc = m.accrue_comp(events)
    assert acc["total_accrued"] == 500 + 0 + 800 + 600 + 300 + 150 + 500 + 1500
    clawed = acc["lines"][1]
    assert clawed["accrued"] == 0.0 and "clawed back" in clawed["note"]


def test_clawback_reverses_500_on_60_day_churn():
    acc = m.accrue_comp([{"type": "renewal", "months_to_churn": 2}])
    assert acc["total_accrued"] == 0.0


def test_no_director_figures_in_module():
    """The module must contain no director comp constants — funding inputs
    arrive from owner config at call time."""
    import inspect
    import re
    src = inspect.getsource(m)
    # standalone figures only (not substrings of other numbers like 145_000)
    for pat in (r"(?<![\d_])144[_,]?000", r"(?<![\d_])45[_,]?000(?![\d.])",
                r"(?<![\d_])144k", r"(?<![\d_])45k"):
        assert not re.search(pat, src), pat
    # structural purity: funding inputs default to None (arrive from config)
    sig = inspect.signature(m.funding_paths)
    assert sig.parameters["director_current_annual"].default is inspect.Parameter.empty
    assert sig.parameters["director_proposed_annual"].default is inspect.Parameter.empty


def test_convention_notes_present():
    r = m.regression_check()
    joined = " ".join(r["convention_notes"])
    assert "ONE YEAR of cost" in joined
    assert "55.2%" in joined and "42.9%" in joined
    assert "6.5k" in joined and "9.5k" in joined


def test_ote_interpolation_hits_anchors():
    for a in m.SCENARIO_ANCHORS.values():
        assert abs(m.ote_at(a["renewal_pct"]) - a["ote"]) < 0.01
        assert abs(m.credited_lift_lifetime_at(a["renewal_pct"])
                   - (a["net_lifetime"] + a["ote"])) < 0.01
