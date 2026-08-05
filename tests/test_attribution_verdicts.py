"""
Phase 3 verdict layer + Phase 4 CFO-side prep — adversarial tests.

Verdict rails (Rydel's rules): KILL requires 30 attributed leads (closes alone never
kill); DOUBLE DOWN needs the floor WITH margin at ≥3 closes; borderline holds; zero-close
sufficient-lead creatives kill only when the funnel shows the failure is the creative's
own output; channel rows carry no verdict; the constraint check can conclude the tool
isn't the bottleneck. media_buyer bridge role: ships DISABLED, reaches ONLY /bridge/attribution.
"""
from __future__ import annotations

import attribution_verdicts as AV

FLOOR = 3.0


def row(label="Creative X", tier="ad", leads=0, qualified=0, sets=0, shows=0,
        closes_cohort=0, closes=0, spend=0.0, ltgp_cac=None, ltgp=None,
        loaded=None, cost_per_close=None):
    return {"creative_key": label.lower(), "label": label, "tier": tier,
            "leads": leads, "qualified": qualified, "sets": sets, "shows": shows,
            "closes_cohort": closes_cohort, "closes": closes, "spend": spend,
            "ltgp_cac": ltgp_cac, "ltgp": ltgp, "cost_per_close_loaded": loaded,
            "cost_per_close": cost_per_close,
            "gates": {"n_leads": leads, "n_closes": closes,
                      "sufficient_for_scale": closes >= 3,
                      "sufficient_for_kill": leads >= 30}}


def base_from(*rows):
    return AV.baselines(list(rows))


def test_double_down_needs_margin_and_three_closes():
    r = row(leads=40, qualified=30, sets=12, shows=8, closes_cohort=4, closes=4,
            spend=4000, ltgp_cac=4.2, ltgp=48000, loaded=2800)
    v = AV.verdict_for_row(r, FLOOR, base_from(r))
    assert v["verdict"] == AV.DOUBLE_DOWN
    assert "every $1 here returns $4.20" in v["driver"]


def test_above_floor_but_two_closes_watches():
    r = row(leads=35, qualified=25, sets=10, shows=6, closes_cohort=2, closes=2,
            spend=2000, ltgp_cac=5.0, ltgp=24000, loaded=2400)
    v = AV.verdict_for_row(r, FLOOR, base_from(r))
    assert v["verdict"] == AV.WATCH and "scale requires 3" in v["driver"]


def test_kill_below_floor_at_thirty_leads():
    r = row(leads=41, qualified=30, sets=10, shows=5, closes_cohort=2, closes=2,
            spend=9000, ltgp_cac=1.2, ltgp=10000, loaded=5000)
    v = AV.verdict_for_row(r, FLOOR, base_from(r))
    assert v["verdict"] == AV.KILL
    assert "n=41" in v["driver"] and "1.2x < 3.0x" in v["driver"]


def test_below_floor_without_thirty_leads_never_kills():
    r = row(leads=12, qualified=9, sets=5, shows=4, closes_cohort=3, closes=3,
            spend=6000, ltgp_cac=0.8, ltgp=6000, loaded=2500)
    v = AV.verdict_for_row(r, FLOOR, base_from(r))
    assert v["verdict"] == AV.WATCH and "KILL requires 30" in v["driver"]


def test_borderline_band_holds():
    r = row(leads=50, qualified=40, sets=15, shows=10, closes_cohort=4, closes=4,
            spend=5000, ltgp_cac=2.9, ltgp=30000, loaded=2600)
    v = AV.verdict_for_row(r, FLOOR, base_from(r))
    assert v["verdict"] == AV.WATCH and "borderline" in v["driver"]


def test_zero_close_thirty_leads_sets_below_baseline_kills():
    healthy = row("Healthy", leads=40, qualified=32, sets=16, shows=10,
                  closes_cohort=4, closes=4, spend=3000, ltgp_cac=4.0)
    dud = row("Dud", leads=35, qualified=6, sets=1, shows=0, spend=4000)
    base = base_from(healthy, dud)
    v = AV.verdict_for_row(dud, FLOOR, base)
    assert v["verdict"] == AV.KILL
    assert "lead quality is the creative's output" in v["driver"]


def test_zero_close_but_sets_at_baseline_names_the_handoff_not_the_creative():
    healthy = row("Healthy", leads=40, qualified=30, sets=10, shows=6,
                  closes_cohort=3, closes=3, spend=3000, ltgp_cac=4.0)
    setter = row("SetsFine", leads=32, qualified=28, sets=12, shows=8, spend=3500)
    base = base_from(healthy, setter)
    v = AV.verdict_for_row(setter, FLOOR, base)
    assert v["verdict"] == AV.WATCH
    assert "sales handoff" in v["driver"] and "not the creative" in v["driver"]


def test_insufficient_n_is_watch_with_the_numbers():
    r = row(leads=5, closes=1, spend=500, ltgp_cac=0.5)
    v = AV.verdict_for_row(r, FLOOR, base_from(r))
    assert v["verdict"] == AV.WATCH and "n=5 leads, 1 closes" in v["driver"]


def test_channel_rows_carry_no_verdict():
    r = row("Unattributed", tier="unattributed", leads=20)
    assert AV.verdict_for_row(r, FLOOR, base_from(r))["verdict"] is None


def test_stage_diagnostics_name_the_worst_stage():
    healthy = row("Healthy", leads=40, qualified=36, sets=18, shows=12,
                  closes_cohort=4, closes=4, spend=1000, ltgp_cac=4.0)
    leaky = row("Leaky", leads=30, qualified=27, sets=2, shows=1, spend=1000)
    base = base_from(healthy, leaky)
    d = AV.stage_diagnostics(leaky, base)
    assert d["worst_stage"] == "qualified_to_set"
    assert "qualified→set" in (d["read"] or "")


def test_constraint_check_all_clear_names_capacity():
    a = row("A", leads=40, qualified=30, sets=12, shows=8, closes_cohort=4, closes=4,
            spend=3000, ltgp_cac=4.5, ltgp=40000, loaded=2000)
    b = row("B", leads=33, qualified=26, sets=11, shows=7, closes_cohort=3, closes=3,
            spend=2500, ltgp_cac=3.6, ltgp=30000, loaded=2300)
    res = {"creatives": [a, b]}
    AV.apply(res, FLOOR, capacity_note="Paid Ads at 190% load")
    cc = res["verdict_layer"]["constraint_check"]
    assert cc["creatives_are_constraint"] is False
    assert "volume/capacity" in cc["read"] and "190%" in cc["read"]


def test_constraint_check_kill_present_flags_leak():
    a = row("A", leads=40, closes=4, closes_cohort=4, qualified=30, sets=12, shows=8,
            spend=3000, ltgp_cac=4.5)
    k = row("K", leads=45, closes=1, closes_cohort=1, qualified=30, sets=9, shows=4,
            spend=9000, ltgp_cac=0.9, ltgp=9000, loaded=8000)
    res = {"creatives": [a, k]}
    AV.apply(res, FLOOR)
    cc = res["verdict_layer"]["constraint_check"]
    assert cc["creatives_are_constraint"] is True and "K" in cc["kills"]


def test_constraint_check_no_sufficient_rows_is_honest():
    tiny = row("Tiny", leads=4, spend=200)
    res = {"creatives": [tiny]}
    AV.apply(res, FLOOR)
    cc = res["verdict_layer"]["constraint_check"]
    assert cc["creatives_are_constraint"] is None and "insufficient data" in cc["read"]


def test_apply_stamps_rules_and_bands():
    res = {"creatives": [row(leads=40, closes=3, closes_cohort=3, qualified=30,
                             sets=10, shows=6, spend=1000, ltgp_cac=5.0, ltgp=30000,
                             loaded=2000)]}
    AV.apply(res, FLOOR)
    vl = res["verdict_layer"]
    assert vl["bands"] == {"double_down_at": 3.3, "kill_below": 2.7}
    assert "nothing auto-pauses" in vl["rules"]
    assert res["creatives"][0]["verdict"] == AV.DOUBLE_DOWN


def test_constraint_check_indeterminate_when_ltgp_cac_unavailable():
    # sufficient-n rows whose LTGP:CAC can't be computed (margin missing) must never
    # read as "clears the floor" — the exact distortion caught in the Phase-5 scan
    r3 = row("NoMargin", leads=40, qualified=30, sets=12, shows=8, closes_cohort=3,
             closes=3, spend=3000)  # ltgp_cac None
    res = {"creatives": [r3]}
    AV.apply(res, FLOOR)
    cc = res["verdict_layer"]["constraint_check"]
    assert cc["creatives_are_constraint"] is None
    assert "can't be called" in cc["read"] and "unavailable" in cc["read"]
