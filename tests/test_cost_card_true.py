"""THE COST CARD, MADE TRUE — the verification battery.

One mix drives both cards (invariant) · commissions rulebook-only, mix-
weighted per package and per closer · PIF share weighted, never boolean ·
bounties on QUALIFIED sets · Coby's bonuses when he is in the mix · capacity
cost that rises as volume scales · fixed-vs-variable labels · no 6.3% as a
source anywhere · ratios named with their margin source · show-the-math
prints the real arithmetic.
"""

import copy
import json
import os

import pytest

import kv_store
import compass_engine as CE
import sales_cost as SC
import comp_rulebook as RB

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


PKG = {
    "growth pro": {"mrr": 3050.0, "term": 6, "contract": 18300.0,
                   "cash_schedule": [0.3, 0.14, 0.14, 0.14, 0.14, 0.14],
                   "gross_margin_pct": 42.9, "delivery_cost_monthly": 1741.6,
                   "m0_share_measured_n": 9, "mrr_provenance": "test"},
    "scale engine": {"mrr": 3500.0, "term": 6, "contract": 21000.0,
                     "cash_schedule": [0.3, 0.14, 0.14, 0.14, 0.14, 0.14],
                     "gross_margin_pct": 42.9, "delivery_cost_monthly": 1998.5,
                     "m0_share_measured_n": 9, "mrr_provenance": "test"},
}


@pytest.fixture()
def stub(monkeypatch):
    team = CE._team_snapshot()
    team.update({"setters": 2, "closers": 1})
    fake = {"computed_at": "2026-09-24T10:00:00+10:00", "items": {
        "cpl": CE._item(55.0, 300, "90d", "t"),
        "monthly_spend_baseline": CE._item(22500.0, 3, "90d", "t"),
        "set_rate": CE._item(0.18, 300, "90d", "t"),
        "show_rate": CE._item(0.9, 45, "90d", "t"),
        "close_rate": CE._item(0.28, 40, "90d", "t"),
        "deal_mix": CE._item({"growth pro": 0.6, "scale engine": 0.4},
                             20, "180d", "t"),
        "closer_mix": CE._item({"kalin": 1.0}, 20, "180d", "t"),
        "setter_mix": CE._item({"coby": 0.6, "maran": 0.4}, 20, "180d", "t"),
        "pif_share": CE._item(0.5, 4, "180d", "t"),
        "qualified_rate": CE._item(1.0, 60, "90d", "t"),
        "packages": CE._item(copy.deepcopy(PKG), None, "", "t"),
        "lag_curve": CE._item([1.0, 0.0, 0.0], 20, "180d", "t"),
        "renewal_rate": CE._item(0.5, 10, "12mo", "t"),
        "cpl_epsilon": CE._item(0.2, 9, "", "t", assumption=True),
        "commission_pct_of_cash": CE._item(0.063, None, "", "t"),
        "opex_monthly_ex_tax": CE._item(30000.0, 3, "", "t"),
        "sales_tooling_monthly": CE._item(2132.0, None, "", "t"),
        "sales_tooling_per_seat": CE._item(0.0, None, "", "t", assumption=True),
        "seasonality": CE._item({}, None, "", "t", assumption=True),
        "team": CE._item(team, None, "", "t"),
        "lanes": CE._item({"au": 250, "us": 50}, 300, "90d", "t"),
    }}
    kv_store.put(CE.K_DEFAULTS, fake)
    monkeypatch.setattr(CE, "book_state",
                        lambda H, m0, r, pins=None: {"mrr": [0.0] * H,
                                                     "cash": [0.0] * H,
                                                     "note": "stub"})
    monkeypatch.setattr(CE, "cash_position_base",
                        lambda: {"cash_ex_setaside": 150000.0, "cash": 150000.0,
                                 "tax_set_aside": 0})
    return fake


# ── PART 1: one mix drives BOTH cards ───────────────────────────────────────

def test_revenue_mix_equals_commission_mix(stub):
    """THE INVARIANT: the deal mix pricing the revenue card is the mix the
    commission engine costs — mapped onto the rulebook's package keys."""
    s = CE.simulate_month()
    assert s["mix"] == {"growth pro": 0.6, "scale engine": 0.4}
    assert s["commission_mix"] == {RB.PKG_GROWTH_PRO: 0.6,
                                   RB.PKG_SCALE_ENGINE: 0.4}
    assert s["mix_warning"] is None
    # and the per-close figure is mix-weighted from the rulebook, not $902
    # for everything: 0.6×(750 + 5%×3050) + 0.4×(1500 + 5%×(0.5×14500 + 0.5×7250))
    gp = 750.0 + 0.05 * 3050.0
    se = 1500.0 + 0.05 * (0.5 * 14500.0 + 0.5 * 14500.0 / 2.0)
    assert abs(s["commission_per_close"] - (0.6 * gp + 0.4 * se)) < 0.51


def test_explicit_package_mix_override_raises_the_warning(stub):
    """An override is allowed — but never silent. The card says the two
    sides no longer describe the same business."""
    s = CE.simulate_month({"package_mix": {RB.PKG_GROWTH_PRO: 1.0}})
    assert s["mix_warning"] and "deal mix" in s["mix_warning"]
    sm = CE.simulate_month()
    assert sm["mix_warning"] is None


def test_revenue_moves_with_the_mix_and_so_do_commissions(stub):
    """Shifting the deal mix toward Scale Engine moves the revenue card AND
    the commission line — together, from the same input."""
    gp_only = CE.simulate_month({"deal_mix": {"growth pro": 1.0}})
    se_only = CE.simulate_month({"deal_mix": {"scale engine": 1.0}})
    assert se_only["cash_over_term"] > gp_only["cash_over_term"]
    assert se_only["commission_per_close"] > gp_only["commission_per_close"]


# ── PART 2: commissions from the rulebook only ──────────────────────────────

def test_kalin_growth_pro_is_902_50(stub):
    s = CE.simulate_month({"deal_mix": {"growth pro": 1.0},
                           "closer_mix": {"kalin": 1.0}})
    assert s["commission_per_close"] == 902.50    # 750 + 5% × 3,050


def test_50_50_kalin_coby_blends_with_cobys_company_total(stub):
    """Coby's $550 is the COMPANY total (Kalin's 3% inside, never on top);
    his one-time $1,000 fast-win rides as $100 across the ten closes that
    earn it, weighted by his share of the mix."""
    s = CE.simulate_month({"deal_mix": {"growth pro": 1.0},
                           "closer_mix": {"kalin": 0.5, "coby": 0.5}})
    closer_blend = 0.5 * 750.0 + 0.5 * 550.0        # 650
    setter = 0.05 * 3050.0                           # 152.50
    fastwin = 1000.0 / 10 * 0.5                      # 50
    assert abs(s["commission_per_close"] - (closer_blend + setter + fastwin)) < 0.01
    # and it is CHEAPER than Kalin-only — the junior rate is the point
    kalin = CE.simulate_month({"deal_mix": {"growth pro": 1.0},
                               "closer_mix": {"kalin": 1.0}})
    assert s["cac"] < kalin["cac"]


def test_pif_share_is_weighted_never_boolean():
    """pif_share 0.5 costs half the Scale Engine closes on the full
    prepayment and half on the first collection — it was read as a boolean
    (any non-zero → 100% PIF) before the diagnosis."""
    full = SC.modelled_commission({"package_mix": {RB.PKG_SCALE_ENGINE: 1.0},
                                   "closer_mix": {"kalin": 1.0},
                                   "pif_share": 1.0})
    none = SC.modelled_commission({"package_mix": {RB.PKG_SCALE_ENGINE: 1.0},
                                   "closer_mix": {"kalin": 1.0},
                                   "pif_share": 0.0})
    half = SC.modelled_commission({"package_mix": {RB.PKG_SCALE_ENGINE: 1.0},
                                   "closer_mix": {"kalin": 1.0},
                                   "pif_share": 0.5})
    assert full["setter_pct_per_close"] == round(0.05 * 14500.0, 2)
    assert none["setter_pct_per_close"] == round(0.05 * 7250.0, 2)
    assert half["setter_pct_per_close"] == round(
        (full["setter_pct_per_close"] + none["setter_pct_per_close"]) / 2, 2)


def test_coby_in_the_mix_adds_his_kpi_bonus(stub):
    """The $350 monthly bonus (gated) appears when the closer mix includes
    him — and never when it doesn't."""
    without = CE.simulate_month({"closer_mix": {"kalin": 1.0}})
    with_c = CE.simulate_month({"closer_mix": {"kalin": 0.7, "coby": 0.3}})
    assert without["monthly_fixed"] == 500.0
    assert with_c["monthly_fixed"] == 850.0
    assert with_c["monthly_fixed_detail"]["junior_kpi_bonus"] == 350.0


def test_unruled_package_reads_needs_your_number_never_a_guess():
    out = SC.modelled_commission({"package_mix": {RB.PKG_CONTENT_SCALE: 1.0},
                                  "closer_mix": {"kalin": 1.0}})
    assert out["needs_your_number"]
    assert out["closer_per_close"] == 0.0


def test_fy26_rate_is_reference_only_never_the_source(stub):
    """The 6.3% anchor appears ONLY as a labelled sanity reference."""
    s = CE.simulate_month()
    assert "never the source" in s["fy26_reference"]["use"]
    assert "never the source" in s["comm_rate_use"]
    # the registry's cost-card copy no longer sources commissions from it
    reg = json.loads(_read("dashboard", "definitions.json"))
    cc = reg["entries"]["chain_cost"]
    assert "reference" in cc["default_from"]
    assert "use last year's actual" not in cc["default_from"]
    # the retired % control is gone from the inputs panel
    js = _read("dashboard", "static", "js", "scale.js")
    assert "commissions (% of new cash)" not in js
    # the measured-defaults item says what it is now
    items = (kv_store.get(CE.K_DEFAULTS) or {}).get("items") or {}
    # (stubbed here — the live provenance strings are asserted on the module)
    src = _read("compass_engine.py")
    assert src.count("REFERENCE ONLY") >= 2


# ── PART 3: qualified sets are the bounty basis ─────────────────────────────

def test_bounties_ride_on_qualified_sets(stub):
    s = CE.simulate_month(spend=22500.0)
    # exact from the unrounded chain: spend ÷ CPL × set rate × qualified rate
    q_exact = 22500.0 / 55.0 * 0.18 * s["qualified_rate"]
    assert abs(s["bounties"] - s["bounty_per_set"] * q_exact) < 0.51
    assert abs(s["qualified_sets"] - q_exact) < 0.11


def test_changing_the_qualified_rate_moves_bounties(stub):
    full = CE.simulate_month({"qualified_rate": 1.0})
    part = CE.simulate_month({"qualified_rate": 0.8})
    assert abs(part["bounties"] - full["bounties"] * 0.8) < 1.0
    assert part["cac"] < full["cac"]


# ── PART 4: capacity — cost that rises as you scale ─────────────────────────

def test_at_witnessed_volume_headcount_cost_enters_cac(stub):
    """Spend $22,500 at CPL $55 → 409 leads, ~74 calls. Throughput says 3
    setters and 2 closers; the team has 2 and 1 — the gap is costed and CAC
    carries it."""
    s = CE.simulate_month(spend=22500.0)
    cap = s["capacity"]
    assert cap["setters_extra"] == 1 and cap["closers_extra"] == 1
    assert cap["cost_monthly"] == 1400.0 + 2500.0
    line = [c for c in s["cost_card"] if "headcount" in c["label"]][0]
    assert line["amount"] == cap["cost_monthly"]
    assert "+2" in line["label"] and "from 20" in line["label"]
    # the card sums to the all-in cost, and CAC is that ÷ the (unrounded)
    # clients from the same chain
    total = sum(c["amount"] for c in s["cost_card"])
    clients_exact = 22500.0 / 55.0 * 0.18 * 0.9 * 0.28
    assert abs(total / clients_exact - s["cac"]) < 0.51


def test_at_small_volume_no_headcount_cost(stub):
    s = CE.simulate_month(spend=5000.0)
    assert s["capacity"]["extra_total"] == 0
    line = [c for c in s["cost_card"] if "headcount" in c["label"]][0]
    assert line["amount"] == 0.0
    assert "covers this volume" in line["label"]


def test_cac_rises_when_volume_outgrows_the_team(stub):
    """The flat-CAC defect: headcount cost used to be $0 at every volume.
    Now the same volume costed WITH the real team is dearer than costed
    with a team that never runs out — by exactly the hires ÷ clients."""
    s = CE.simulate_month(spend=22500.0)
    roomy = CE._team_snapshot()
    roomy.update({"setters": 2, "closers": 1})
    roomy["throughput"] = {"leads_per_setter_month": 10 ** 6,
                           "calls_per_closer_month": 10 ** 6,
                           "clients_per_delivery": 7}
    flat = CE.simulate_month({"team": roomy}, spend=22500.0)
    assert flat["capacity"]["extra_total"] == 0
    clients_exact = 22500.0 / 55.0 * 0.18 * 0.9 * 0.28
    assert abs((s["cac"] - flat["cac"])
               - s["capacity"]["cost_monthly"] / clients_exact) < 0.51


def test_forward_period_cac_carries_sales_headcount(stub):
    inp = CE.default_inputs()
    inp["horizon_months"] = 3
    inp["spend_path"] = {"shape": "flat", "start": 22500.0}
    run = CE.forward(inp)
    m0 = run["months"][0]
    assert m0["sales_headcount_extra"] == 2
    assert m0["sales_headcount_cost"] == 3900.0
    # identity with the simulator (lag [1,0,0] in the stub)
    sim = CE.simulate_month(spend=22500.0)
    assert abs(sim["cac"] - run["cohorts"][0]["cac_cohort"]) < 1.0


# ── PART 5: tooling — fixed base + per-seat, labelled ───────────────────────

def test_tooling_scales_with_seats_only_when_a_per_seat_price_is_given(stub):
    flat = CE.simulate_month(spend=22500.0)
    assert flat["tooling_total"] == 2132.0          # base only — books can't split
    seat = CE.simulate_month({"sales_tooling_per_seat": 100.0}, spend=22500.0)
    # 2 setters + 1 closer + 2 extra = 5 seats
    assert seat["tooling_total"] == 2132.0 + 100.0 * 5
    line = [c for c in seat["cost_card"] if c["label"] == "sales tooling"][0]
    assert line["kind"] == "fixed base + per-seat"


# ── PART 6: named ratios + fixed-vs-variable labels ─────────────────────────

def test_every_cost_line_is_labelled_fixed_or_variable(stub):
    s = CE.simulate_month()
    kinds = {c["label"]: c["kind"] for c in s["cost_card"]}
    assert kinds["ad spend"] == "variable"
    assert kinds["commissions on closes"] == "variable"
    assert kinds["set bounties (qualified sets)"] == "variable"
    assert kinds["manager retainer + bonuses"] == "fixed"
    assert any(k == "steps with volume" for k in kinds.values())


def test_ratios_are_named_and_margin_sourced(stub):
    s = CE.simulate_month()
    assert s["ltv_cac"] == round(s["contract_avg"] / s["cac"], 2)
    assert s["ltgp_cac"] == round(s["contract_avg"] * s["margin_avg"] / s["cac"], 2)
    assert "42.9" in s["margin_source"] or "last year" in s["margin_source"]
    assert s["payback_months"] is not None
    html = _read("dashboard", "templates", "scale.html")
    assert "LTV:CAC" in html and "LTGP:CAC" in html
    assert "margin" in html
    # scan keys: the card's CAC and ratios carry metric identities
    for m in ("sim_cac", "sim_ltv_cac", "sim_ltgp_cac"):
        assert f'data-metric="{m}"' in html


def test_show_the_math_prints_every_cost_line(stub):
    js = _read("dashboard", "static", "js", "scale.js")
    for needle in ("qualified sets (the $50 bounty basis)", "commissions: ",
                   "bounties: ", "fixed: ", "sales tools: ",
                   "headcount", "LTV:CAC", "LTGP:CAC", "payback"):
        assert needle in js, needle
    # the client core computes the same card the engine does (agg-driven)
    core = _read("dashboard", "static", "js", "sim_core.js")
    for needle in ("qualified", "capacity", "tooling_per_seat", "cash_curve",
                   "ltv_cac", "payback"):
        assert needle in core, needle


def test_defaults_carry_the_new_measured_inputs(stub):
    inp = CE.default_inputs()
    for k in ("closer_mix", "setter_mix", "pif_share", "qualified_rate",
              "sales_tooling_per_seat"):
        assert k in inp, k
    assert inp["closer_mix"] == {"kalin": 1.0}
    assert inp["qualified_rate"] == 1.0


def test_whatif_with_new_inputs_still_never_writes(stub):
    kv_store.put(CE.K_SCENARIOS, {"keep": {"inputs": {}}})
    CE.simulate_month({"closer_mix": {"coby": 1.0}, "qualified_rate": 0.5},
                      spend=50000.0)
    assert kv_store.get(CE.K_SCENARIOS) == {"keep": {"inputs": {}}}
