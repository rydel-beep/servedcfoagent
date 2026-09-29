"""tests/test_owner_deal_terms.py — #170: an owner-ruled deal, and a
commission nobody ruled is PENDING, never averaged.

Shaped on Rocky's Italian (Rydel, 29 Sep): Scale Engine, $14,500 ex-GST,
split into three payments; payment 1 $5,500 by bank transfer; 2 and 3 the
remaining balance, equally. Cash counts only with evidence; a personal-
account payment is never business cash.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import close_register as CR
import commission_engine as CE
import comp_rulebook as RB
import kv_store


def _schedule(p1_received=None, account=None, evidence=None):
    # payment 1 $5,500 inc GST → $5,000 ex; balance $10,450 inc → 2 × $5,225
    return [{"n": 1, "amount": 5500.0, "gst": "inc", "due": "2026-09-29",
             "received": p1_received, "channel": "bank transfer",
             "account": account, "evidence_id": evidence},
            {"n": 2, "amount": 5225.0, "gst": "inc", "due": "2026-10-29"},
            {"n": 3, "amount": 5225.0, "gst": "inc", "due": "2026-11-29"}]


def _terms(**kw):
    t = {"key": "max", "person": "Max", "client": "Rocky's Italian",
         "close_date": "2026-09-29", "package": RB.PKG_SCALE_SPLIT,
         "package_words": "Scale Engine", "term_months": 6,
         "payment_type": "split", "contract_ex_gst": 14500.0,
         "schedule": _schedule(), "closer": "kalin", "setter": "maran",
         "words": "Rocky's Italian — contact Max — Scale Engine — signed 29 Sep",
         "by": "rydel", "at": "2026-09-29T15:00:00+10:00"}
    t.update(kw)
    return t


def test_a_ruling_is_the_signed_contract_and_never_cash():
    e = CR._ruling_entry(_terms())
    CR._apply_terms(e, _terms())
    assert e["contract"] == {"value": 14500.0, "signed": True, "gst": "ex",
                             "source": "owner ruling — rydel, 2026-09-29, journaled"}
    assert "contract value" not in e["missing"]
    assert e["cash"]["amount"] is None                       # nothing received yet
    assert [r["n"] for r in e["ruled_cash"]["receivable"]] == [1, 2, 3]


def test_received_without_bank_feed_is_pending_not_cash():
    t = _terms(schedule=_schedule("2026-09-29", "business"))
    e = CR._ruling_entry(t)
    CR._apply_terms(e, t)
    assert e["cash"]["amount"] is None
    assert e["ruled_cash"]["pending_bank_feed"][0]["state"] == "cash pending bank feed"


def test_bank_feed_evidence_makes_it_cash():
    t = _terms(schedule=_schedule("2026-09-30", "business", "xero-txn-123"))
    e = CR._ruling_entry(t)
    CR._apply_terms(e, t)
    assert e["cash"]["amount"] == 5500.0
    assert e["ruled_cash"]["counted"][0]["ex_gst"] == 5000.0


def test_a_personal_account_payment_is_never_business_cash():
    t = _terms(schedule=_schedule("2026-09-29", "personal", "anything"))
    e = CR._ruling_entry(t)
    CR._apply_terms(e, t)
    assert e["cash"]["amount"] is None
    assert "outside business accounts" in e["ruled_cash"]["outside_business_accounts"][0]["state"]


def _deal(closer):
    e = CR._ruling_entry(_terms())
    CR._apply_terms(e, _terms(closer=closer))
    return {"name": "Max", "close_date": dt.date(2026, 9, 29),
            "package": e["package"], "payment_type": "split", "contract": 14500.0,
            "closer": closer, "setter": "maran", "cash_events": e["cash_events"]}


def test_kalin_scale_engine_split_is_1500_across_three_collections():
    acc = CE.accrue_close(_deal("kalin"))
    closer = [x["amount"] for x in acc["events"] if x["role"] == "closer"]
    assert closer == [500.0, 500.0, 500.0]
    setter = [x["amount"] for x in acc["events"] if x["role"] == "setter"]
    assert setter == [250.0]                        # 5% of $5,000 ex-GST


def test_coby_split_totals_1000_with_kalins_3pct_carved_out():
    acc = CE.accrue_close(_deal("coby"))
    mgr = [x["amount"] for x in acc["events"] if x["role"] == "manager"]
    assert mgr == [150.0, 142.5, 142.5]             # 3% of 5,000 / 4,750 / 4,750
    closer_side = sum(x["amount"] for x in acc["events"] if x["role"] in ("closer", "manager"))
    assert abs(closer_side - 1000.0) < 0.02         # never on top


def test_a_ruling_needs_words_and_gst_basis():
    bad = CR.rule_deal_terms("Max", "Rocky's", "2026-09-29", "Scale Engine", 6,
                             14500, _schedule(), words="")
    assert not bad["ok"]
    sched = _schedule()
    sched[0]["gst"] = None
    bad = CR.rule_deal_terms("Max", "Rocky's", "2026-09-29", "Scale Engine", 6,
                             14500, sched, words="x")
    assert not bad["ok"] and "inc or ex" in bad["error"]


def test_a_ruled_uncovered_package_is_pending_not_zero(monkeypatch):
    """Amoroso's 'Walk in Engine' normalises to DWY — no ruled rate."""
    import sales_cost as SC
    monkeypatch.setattr(SC, "_tracker_deals", lambda: [])
    monkeypatch.setattr(SC, "_union_deals", lambda w0, w1: [
        {"person": "Scott Cho", "close_date": "2026-09-26", "contract": 4799.0,
         "cash": 5278.9, "ruled": {"package": RB.normalise_package("Walk in Engine"),
                                   "payment_type": "PIF", "closer": None,
                                   "setter": "maran",
                                   "cash_events": [{"when": "2026-09-26",
                                                    "amount": 5278.9, "inclusive": True}]}},
        {"person": "Harman singh", "close_date": "2026-09-11", "contract": None,
         "cash": 3355.0, "ruled": None}])
    monkeypatch.setattr(SC, "_sets_in_window", lambda w0, w1: {"count": 0, "basis": "t"})
    monkeypatch.setattr(SC, "_sets_from_engine", lambda w0, w1: 0)
    monkeypatch.setattr(SC, "_ad_spend", lambda w0, w1: 1000.0)
    monkeypatch.setattr(CE, "_raise_card", lambda card: None)
    out = SC.build("2026-09-01", "2026-09-29")
    by = {d["name"]: d for d in out["deals"]}
    assert by["Scott Cho"]["pending"] and by["Scott Cho"]["closer_cost"] is None
    assert by["Scott Cho"]["setter_cost"] == 239.95   # 5% of $4,799 ex-GST
    assert by["Harman singh"]["pending"] and by["Harman singh"]["total"] is None
    c = out["commissions"]
    assert c["pending_deals"] == 2
    assert c["pending_range"]["min"] < c["pending_range"]["max"]
    assert "averaged_deals" not in c


def test_form_contract_is_read_by_name_never_by_shape():
    assert CR._form_contract({"Upfront payment": "$4,799", "Contract Value": "$14,500"}) \
        == (14500.0, None)
    v, why = CR._form_contract({"Upfront payment": "$4,799", "Package": "Scale Engine"})
    assert v is None and "no named" in why
    v, why = CR._form_contract({"Contract Value": "14500", "contract_value": "9000"})
    assert v is None and "ambiguous" in why


def test_tiles_say_how_many_proposed_closes_they_left_out(monkeypatch):
    def _e(person, status, day):
        return {"key": person, "person": person, "status": status,
                "close_date": day, "clocks": {"activity": day, "cohort": None},
                "attribution": {"tier": "ad"}, "cash": {"amount": None},
                "contract": {"value": None}}
    monkeypatch.setattr(CR, "latest", lambda build_if_empty=False: {"entries": [
        _e("Orlando Rinaldi", "proposed-needs-evidence", "2026-09-09"),
        _e("Koji", "confirmed", "2026-09-23"),
        _e("Old", "proposed-needs-evidence", "2026-06-01")]})
    n = CR.proposed_note("2026-09-01", "2026-09-29", "mtd")
    assert n == {"n": 1, "label": "+1 proposed, not counted",
                 "href": "/dashboard/closes?window=mtd"}
    assert CR.proposed_note("2026-09-20", "2026-09-29", "mtd") is None
