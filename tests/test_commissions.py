"""THE COMMISSION RULES — every ruled example, as a test.

Rydel ruled the structure on 2026-09-22. Each worked example he gave is
pinned here, plus the invariant that matters most: the manager's override is
funded OUT of the junior's commission and never adds company cost.
"""

import datetime as dt

import pytest

import comp_rulebook as RB
import commission_engine as CE


def _gp(closer="kalin", setter="maran", cash=3355.0, inclusive=True,
        when="2026-09-25"):
    """A Growth Pro monthly: $18,300 ex-GST over 6 months, first month
    $3,355 inclusive = $3,050 ex-GST."""
    return {"name": f"GP {closer}", "close_date": dt.date.fromisoformat(when),
            "offer": "Growth Pro", "payment_type": "Monthly",
            "contract": 18300.0, "closer": closer, "setter": setter,
            "cash_events": [{"when": when, "amount": cash, "inclusive": inclusive}]}


def _se_pif(closer="kalin", when="2026-09-25", amount=14500.0, inclusive=False):
    return {"name": f"SE PIF {closer}", "close_date": dt.date.fromisoformat(when),
            "offer": "Scale Engine", "payment_type": "PIF",
            "contract": 14500.0, "closer": closer, "setter": "coby",
            "cash_events": [{"when": when, "amount": amount, "inclusive": inclusive}]}


def _se_split(closer="coby", when="2026-09-25", each=6750.0, inclusive=False):
    return {"name": f"SE split {closer}", "close_date": dt.date.fromisoformat(when),
            "offer": "Scale Engine Split", "payment_type": "Split",
            "contract": 13500.0, "closer": closer, "setter": "coby",
            "cash_events": [{"when": when, "amount": each, "inclusive": inclusive},
                            {"when": "2026-10-25", "amount": each, "inclusive": inclusive}]}


def _amt(res, role=None, who=None, kind=None):
    return round(sum(e["amount"] for e in res["events"]
                     if (role is None or e["role"] == role)
                     and (who is None or e["who"] == who)
                     and (kind is None or kind in e["kind"])), 2)


# ── R-GST ───────────────────────────────────────────────────────────────────

def test_ex_gst_conversion():
    assert RB.ex_gst(3355.0) == 3050.0
    assert RB.ex_gst(3300.0) == 3000.0
    assert RB.ex_gst(5000.0) == 4545.45
    assert RB.ex_gst(3050.0, inclusive=False) == 3050.0


def test_a_percentage_is_never_applied_to_gst_inclusive_cash():
    """Rydel's worked example: a $3,355 inc-GST first-month charge pays the
    setter $152.50 — five per cent of $3,050, not of $3,355."""
    res = CE.accrue_close(_gp())
    pct = _amt(res, role="setter", kind="% of initial-month cash")
    assert pct == 152.50, res["events"]
    assert pct != round(3355.0 * 0.05, 2)


# ── R-SET ───────────────────────────────────────────────────────────────────

def test_a_qualified_set_pays_fifty_dollars():
    out = CE.accrue_set("2026-09-25", "maran", qualified=True)
    assert out["amount"] == 50.0
    assert out["events"][0]["role"] == "setter"


def test_the_bounty_is_owed_whether_or_not_it_closes():
    """127 of the 194 payout-log rows are marked Won = No and still carry the
    $50. The bounty is a SET event, not a close event."""
    out = CE.accrue_set("2026-09-25", "coby", qualified=True)
    assert out["amount"] == 50.0
    # …and it is NOT part of what a close accrues
    res = CE.accrue_close(_gp())
    assert not [e for e in res["events"] if e["kind"] == "set bounty"]


def test_a_pif_pays_the_setter_on_the_whole_prepayment():
    res = CE.accrue_close(_se_pif())
    pct = _amt(res, role="setter", kind="% of initial-month cash")
    assert pct == round(14500.0 * 0.05, 2) == 725.0
    note = next(e["basis"] for e in res["events"] if "% of initial" in e["kind"])
    assert "PIF" in note


# ── R-KALIN-CLOSE ───────────────────────────────────────────────────────────

def test_kalin_growth_pro_pays_750():
    res = CE.accrue_close(_gp(closer="kalin"))
    assert _amt(res, role="closer", who="kalin") == 750.0


def test_kalin_scale_engine_pays_1500():
    res = CE.accrue_close(_se_pif(closer="kalin"))
    assert _amt(res, role="closer", who="kalin") == 1500.0


# ── R-COBY + R-KALIN-MGR — the ruled splits ─────────────────────────────────

def test_coby_growth_pro_splits_550_into_9150_and_45850():
    res = CE.accrue_close(_gp(closer="coby"))
    assert _amt(res, role="manager", who="kalin") == 91.50
    assert _amt(res, role="closer", who="coby") == 458.50
    # the company paid the junior rate, not a penny more
    assert _amt(res, role="closer") + _amt(res, role="manager") == 550.0


def test_coby_scale_engine_pif_splits_1000_into_435_and_565():
    res = CE.accrue_close(_se_pif(closer="coby"))
    assert _amt(res, role="manager", who="kalin") == 435.0
    assert _amt(res, role="closer", who="coby") == 565.0
    assert _amt(res, role="closer") + _amt(res, role="manager") == 1000.0


def test_coby_scale_engine_split_pays_500_per_collection():
    res = CE.accrue_close(_se_split(closer="coby"))
    mgr = [e for e in res["events"] if e["role"] == "manager"]
    jr = [e for e in res["events"] if e["role"] == "closer"]
    assert len(mgr) == 2 and len(jr) == 2, "one event per collection"
    assert all(e["amount"] == 202.50 for e in mgr), mgr
    assert all(e["amount"] == 297.50 for e in jr), jr
    assert _amt(res, role="manager", who="kalin") == 405.0
    assert _amt(res, role="closer", who="coby") == 595.0
    assert _amt(res, role="closer") + _amt(res, role="manager") == 1000.0


# ── THE INVARIANT ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("deal", [
    _gp(closer="coby"), _se_pif(closer="coby"), _se_split(closer="coby"),
])
def test_the_override_never_adds_company_cost(deal):
    """The company's total on ANY junior-closed deal equals the junior rate.
    Kalin's 3% moves money from Coby to Kalin; it is not an extra cost."""
    res = CE.accrue_close(deal)
    v = RB.current_version()
    pkg = res["package"]
    junior_rate = v["junior_closer_flat"][pkg]
    closer_side = round(_amt(res, role="closer") + _amt(res, role="manager"), 2)
    assert closer_side == junior_rate, (closer_side, junior_rate, res["events"])


def test_the_manager_share_is_labelled_as_funded_by_the_junior():
    res = CE.accrue_close(_gp(closer="coby"))
    mgr = next(e for e in res["events"] if e["role"] == "manager")
    assert mgr["funded_by"] == "coby"


def test_a_deduction_larger_than_the_commission_is_capped_never_negative():
    """An unusual package where 3% of the cash exceeds the junior's
    commission: cap at the commission and raise a card."""
    deal = {"name": "huge cash, small rate", "close_date": dt.date(2026, 9, 25),
            "offer": "Growth Pro", "payment_type": "PIF", "contract": 18300.0,
            "closer": "coby", "setter": "maran",
            "cash_events": [{"when": "2026-09-25", "amount": 100000.0,
                             "inclusive": False}]}
    res = CE.accrue_close(deal)
    jr = _amt(res, role="closer", who="coby")
    mgr = _amt(res, role="manager", who="kalin")
    assert jr >= 0, "the junior's commission must never go negative"
    assert mgr == 550.0 and jr == 0.0
    assert _amt(res, role="closer") + _amt(res, role="manager") == 550.0
    assert any("CAPPED" in e["basis"] for e in res["events"] if e["role"] == "manager")


# ── EFFECTIVE DATING — history is never silently restated ───────────────────

def test_a_past_deal_is_costed_at_the_rules_of_its_own_day():
    """Growth Pro paid $900 in June and July; $750 is today's rule. A June
    deal must not be restated at today's number."""
    june = _gp(closer="kalin", when="2026-06-04")
    today = _gp(closer="kalin", when="2026-09-25")
    assert _amt(CE.accrue_close(june), role="closer") == 900.0
    assert _amt(CE.accrue_close(today), role="closer") == 750.0


def test_the_junior_structure_did_not_exist_before_it_was_ruled():
    """Coby's recorded closes were paid at the full rate. The junior rate
    starts on 2026-09-22, not before."""
    old = CE.accrue_close(_gp(closer="coby", when="2026-07-17"))
    assert _amt(old, role="manager") == 0.0
    assert _amt(old, role="closer", who="coby") == 900.0
    new = CE.accrue_close(_gp(closer="coby", when="2026-09-25"))
    assert _amt(new, role="manager") == 91.50


def test_a_date_older_than_any_evidence_is_labelled_an_estimate():
    v = RB.version_for("2024-01-01")
    assert "estimated" in (v.get("confidence") or "")


def test_version_boundaries_are_exact():
    assert RB.version_for("2026-09-21")["version"] == 3
    assert RB.version_for("2026-09-22")["version"] == 4
    assert RB.version_for("2026-04-30")["version"] == 2
    assert RB.version_for("2026-05-01")["version"] == 3


# ── BLANK IS NEVER ZERO ─────────────────────────────────────────────────────

def test_a_blank_tracker_cell_is_never_read_as_zero():
    """The defect that cost September every dollar of commission."""
    deal = _gp(closer="kalin")
    deal["recorded_closer_commission"] = None
    deal["recorded_setter_commission"] = None
    c = CE.counted_for(deal)
    assert c["closer"] == 750.0 and c["closer_source"] == "accrued"
    assert c["setter"] == 152.50 and c["setter_source"] == "accrued"
    assert c["chip"] == "worked out from your rules"
    assert c["total"] > 0


def test_a_recorded_value_wins_over_the_accrual():
    deal = _gp(closer="kalin")
    deal["recorded_closer_commission"] = 900.0
    c = CE.counted_for(deal)
    assert c["closer"] == 900.0 and c["closer_source"] == "recorded"


# ── UNCOVERED PACKAGES ──────────────────────────────────────────────────────

def test_an_unruled_package_says_needs_your_number_and_never_guesses():
    deal = _gp()
    deal["offer"] = "Content Scale"
    res = CE.accrue_close(deal)
    assert res["needs_your_number"], res
    assert _amt(res, role="closer") == 0.0
    assert "needs your number" in res["needs_your_number"][0]


def test_an_unrecognised_offer_is_not_silently_packaged():
    assert RB.normalise_package("") is None
    assert RB.normalise_package("Something New") is None
    assert RB.normalise_package("Growth Pro") == RB.PKG_GROWTH_PRO
    assert RB.normalise_package("Scale Engine Split") == RB.PKG_SCALE_SPLIT


# ── THE MANAGER RETAINER ────────────────────────────────────────────────────

def test_the_retainer_is_a_monthly_cost_not_a_per_deal_one():
    r = CE.manager_retainer("2026-10")
    assert r["amount"] == 500.0 and r["who"] == "kalin"
    # September is part-served: the rule started on the 22nd, and that is
    # said rather than silently pro-rated
    sep = CE.manager_retainer("2026-09")
    assert sep["partial_month"] is True and "part-served" in sep["basis"]
    res = CE.accrue_close(_gp(closer="coby"))
    assert not [e for e in res["events"] if "retainer" in e["kind"]]


# ── THE COBY POLICY FLAG ────────────────────────────────────────────────────

def test_the_coby_policy_flag_states_the_pif_effect():
    f = RB.coby_policy_flag()
    assert f["owner_only"] is True
    assert f["growth_pro"]["he_nets"] == 458.50
    assert f["scale_engine_pif"]["deduction"] == 435.0
    assert f["scale_engine_pif"]["he_nets"] == 565.0
    # the deduction bites far harder on a PIF: ~17% of a Growth Pro
    # commission, ~43% of a Scale Engine PIF commission
    assert f["growth_pro"]["deduction_share_pct"] == pytest.approx(16.6, abs=0.6)
    assert f["scale_engine_pif"]["deduction_share_pct"] == pytest.approx(43.5, abs=0.6)
    assert (f["scale_engine_pif"]["deduction_share_pct"]
            > f["growth_pro"]["deduction_share_pct"])


def test_open_items_name_what_is_not_known():
    ids = {i["id"] for i in RB.open_items()}
    assert "set_fee_basis" in ids
    assert "gp_900_vs_750" in ids
    assert any(i.startswith("rate_") for i in ids)


# ── CONFIDENTIALITY — per-person comp is owner-only ─────────────────────────

@pytest.fixture()
def app_client():
    import os
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-comm")
    import app as appmod
    return appmod


def test_comp_rules_are_owner_only(app_client):
    """R-PIOLO-PARITY (#167): the finance role reads the rulebook at parity;
    ad_domain, sales and anonymous stay refused — structurally."""
    coo = app_client.app.test_client()
    with coo.session_transaction() as s:
        s["actor"] = {"user": "piolo", "role": "coo", "display": "Piolo"}
    assert coo.get("/dashboard/api/comp/rules").status_code == 200
    for role, user in (("ad_domain", "romano"), ("sales", "kalin")):
        c = app_client.app.test_client()
        with c.session_transaction() as s:
            s["actor"] = {"user": user, "role": role, "display": user}
        for path in ("/dashboard/api/comp/rules", "/dashboard/api/comp/cost"):
            r = c.get(path)
            assert r.status_code in (302, 401, 403), (role, path, r.status_code)
            if r.status_code == 200:
                raise AssertionError(f"{role} could read {path}")
    anon = app_client.app.test_client()
    assert anon.get("/dashboard/api/comp/rules").status_code in (302, 401, 403)


def test_edith_refuses_commission_figures_to_a_non_owner(app_client):
    import sales_cost as SC
    with app_client.app.test_request_context("/dashboard/api/chat"):
        from flask import session
        session["actor"] = {"user": "romano", "role": "ad_domain", "display": "Romano"}
        reply, handled = SC.handle_commission_query(
            "what do commissions cost us per client")
        assert handled is True
        assert "limited to the owner and the finance role" in reply
        for name in ("kalin", "coby", "maran"):
            assert name not in reply.lower()
        assert "$" not in reply


# ── PASS 3 — the failures the brief told me to hunt for ─────────────────────

def test_no_surviving_second_commission_path():
    """Every computing path collapses into commission_engine. A rate applied
    to cash may survive ONLY as a labelled fallback."""
    import os
    root = os.path.join(os.path.dirname(__file__), "..")

    def _read(f):
        with open(os.path.join(root, f), encoding="utf-8") as fh:
            return fh.read()

    ce = _read("compass_engine.py")
    # the three places that used to multiply a rate by cash
    assert "comm_rate * cash_new" not in ce
    assert "comm_rate * cash_term" not in ce
    assert "comm_est = comm_rate *" not in ce
    assert "_modelled_comm(" in ce

    fa = _read("finance_analysis.py")
    assert "import sales_cost" in fa, "the CAC tiles must read the one engine"

    js = _read(os.path.join("dashboard", "static", "js", "sim_core.js"))
    assert "comm_per_close" in js, "the client must use the rulebook cost too"


def test_a_percentage_is_never_applied_to_inclusive_cash_anywhere():
    """Pass-3 hunt: a % of GST-inclusive cash. Every rate in the engine goes
    through ex_gst first."""
    import os
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "commission_engine.py"), encoding="utf-8") as fh:
        src = fh.read()
    # every multiplication by a rate uses an _ex value
    assert "initial_ex * pct" in src
    assert "ev_cash_ex * mpct" in src
    assert "_cash_ex_gst(" in src


def test_bounties_are_counted_per_set_never_per_close():
    """Pass-3 hunt. The bounty is a SET event; counting it per close would
    make it vanish for every set that never closed — 127 of 194 rows.
    Since the cost-card fix it rides on QUALIFIED sets (rulebook R-SET) —
    still a set event, never a close event."""
    import os
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "compass_engine.py"), encoding="utf-8") as fh:
        ce = fh.read()
    # modelled bounties ride on QUALIFIED SETS, not closes
    assert 'bounty_per_set"] * qualified_sets' in ce
    assert 'bounty_per_set"] * row["calls_booked"] * q_rate' in ce
    assert 'bounty_per_set"] * clients' not in ce
    res = CE.accrue_close(_gp())
    assert not [e for e in res["events"] if e["kind"] == "set bounty"]


def test_commissions_are_never_merged_into_opex_unlabelled():
    import outflow_bands as OB
    r = OB.band_line_items([{"label": "Closer Commission", "amount": 8485.0},
                            {"label": "Setter Commission", "amount": 4870.0},
                            {"label": "Rent", "amount": 2000.0}])
    sub = r["sublines"]["sales_commissions"]
    assert sub["amount"] == 13355.0
    assert sub["label"] == "Sales commissions"
    # the partition invariant still holds
    assert r["partition"]["ok"] is True


def test_current_rules_are_never_silently_applied_to_past_deals():
    """Pass-3 hunt. A deal outside every reconstructed era is LABELLED."""
    v_old = RB.version_for("2020-01-01")
    assert "estimated" in v_old["confidence"]
    v_known = RB.version_for("2026-06-04")
    assert v_known["confidence"] == "reconstructed"
    assert RB.current_version()["confidence"] == "ruled"


def test_no_rate_is_invented_for_an_unruled_package():
    """Pass-3 hunt: 'Content Scale' must not fall through to Scale Engine."""
    assert RB.normalise_package("Content Scale") == RB.PKG_CONTENT_SCALE
    v = RB.current_version()
    assert RB.PKG_CONTENT_SCALE not in v["closer_flat"]
    deal = _gp()
    deal["offer"] = "Content Scale"
    assert CE.accrue_close(deal)["needs_your_number"]
