"""#170 — the one unit-economics engine, checked by hand."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store
import unit_econ_engine as UE

INP = {"measured": True, "renewal_pct": 22.2, "renewal_ci95": [9.0, 45.2],
       "renewal_n": 18, "completion_pct": 72.7, "completion_n": 18,
       "horizon_months": 36, "measured_on": "2026-09-29", "note": None}


def _e(person, cv, offer=None, term=None):
    return {"person": person, "offer": offer, "term_months": term,
            "contract": {"value": cv, "source": "tracker contract cell"}}


def test_growth_pro_by_hand():
    r = UE.ltv_for(_e("Koji", 18300.0, "Growth Pro"), INP)
    # 6-month term inside a 36-month horizon → 5 renewal terms
    hand = 18300 * 0.727 + sum(18300 * 0.222 ** k for k in range(1, 6))
    assert len(r["renewals"]) == 5
    assert abs(r["expected"] - round(hand, 2)) < 0.05
    assert r["floor"] == 18300.0


def test_horizon_caps_the_series():
    r = UE.ltv_for(_e("X", 10000.0, "Cafe Walk-ins"), INP)   # 3-month term
    assert len(r["renewals"]) == 11                             # (36−3)//3
    old = UE.HORIZON_MONTHS
    UE.HORIZON_MONTHS = 6
    try:
        assert UE.ltv_for(_e("X", 10000.0, "Growth Pro"), INP)["renewals"] == []
    finally:
        UE.HORIZON_MONTHS = old


def test_non_retainer_gets_no_renewal_and_no_inference():
    r = UE.ltv_for(_e("Scott Cho", 4799.0, "Walk in Engine", 3), INP)
    assert r["renewals"] == [] and r["package"] is None
    assert r["expected"] == round(4799 * 0.727, 2)
    assert "no renewal credited" in r["working"]


def test_no_contract_is_pending_not_zero():
    r = UE.ltv_for(_e("Harman singh", None), INP)
    assert r["floor"] is None and r["expected"] is None and "pending" in r["why"]


def test_unmeasured_withholds_expected():
    kv_store.delete(UE.K_MEASURED)
    inp = UE.inputs()
    assert not inp["measured"]
    r = UE.ltv_for(_e("Koji", 18300.0, "Growth Pro"), inp)
    assert r["expected"] is None and r["floor"] == 18300.0


def test_window_ratio_is_reproducible_by_hand(monkeypatch):
    import close_register as CR
    import sales_cost
    entries = [_e("Koji", 18300.0, "Growth Pro"), _e("Scott Cho", 4799.0, "Walk in Engine", 3),
               _e("Harman singh", None)]
    monkeypatch.setattr(CR, "closes", lambda w0, w1, clock="activity": entries)
    monkeypatch.setattr(sales_cost, "build", lambda w0, w1: {
        "true_cac": {"total": 22652.34, "ad_spend": 13120.69, "components": []},
        "commissions": {"pending_deals": 1, "pending_range": None}})
    w = UE.window("2026-09-01", "2026-09-29", "mtd", inp=INP, margin=(65.2, "test"))
    rows = [UE.ltv_for(e, INP) for e in entries]
    known = [r for r in rows if r["floor"] is not None]
    avg_exp = sum(r["expected"] for r in known) / len(known)
    cac = 22652.34 / 3
    assert w["ltv_cac_expected"] == round(round(avg_exp, 2) / round(cac, 2), 2)
    assert w["ltv_cac_floor"] == round(round((18300 + 4799) / 2, 2) / round(cac, 2), 2)
    assert w["ltv_pending"] == ["Harman singh"] and w["ltv_known"] == 2
    s = w["sensitivity"]
    assert s["ltv_cac_low"] < w["ltv_cac_expected"] < s["ltv_cac_high"]


# ── EDITH drills (#170) ──────────────────────────────────────────────────────

_VIEW = {"as_of": "2026-09-29T16:00:00+10:00",
         "inputs": {**INP},
         "headline": {"window": {"start": "2026-07-02", "end": "2026-09-29"},
                      "closes": 11, "ltv_cac_expected": 3.41, "ltv_cac_floor": 3.12,
                      "ltgp_cac_expected": 2.22, "ltgp_cac_floor": 2.03,
                      "cac_loaded": 5359.21, "cac_spend_only": 2973.01,
                      "ltv_pending": ["Harman singh"]},
         "mtd": {"closes": 4, "ltv_cac_expected": 1.62, "ltgp_cac_expected": 1.05,
                 "cac_loaded": 5663.09}}


def test_edith_ltv_to_cac_answers_the_headline_first(monkeypatch):
    import range_unit_economics as R
    monkeypatch.setattr(R, "_engine_view", lambda: _VIEW)
    reply, ok = R.handle_unit_econ_command("what's our LTV to CAC")
    assert ok
    first = reply.split(". ")[0]
    assert "last 90 days" in first and "3.41×" in first and "as of 2026-09-29" in first
    assert "3.12×" in reply and "22.2%" in reply and "18 ended terms" in reply
    assert "Month to date it reads 1.62×" in reply


def test_edith_client_ltv_names_the_missing_number(monkeypatch):
    import close_register as CR
    import range_unit_economics as R
    monkeypatch.setattr(CR, "latest", lambda build_if_empty=False: {"entries": [
        {"person": "Scott Cho", "client": "Amoroso Gelateria", "close_date": "2026-09-26",
         "status": "confirmed", "contract": {"value": None}, "cash": {"amount": 5278.9}}]})
    reply, ok = R.handle_unit_econ_command("what did Amoroso buy?")
    assert ok and "needs your number" in reply and "never read as a package" in reply
    reply, ok = R.handle_unit_econ_command("what's Amoroso's LTV")
    assert ok and "Amoroso Gelateria" in reply
