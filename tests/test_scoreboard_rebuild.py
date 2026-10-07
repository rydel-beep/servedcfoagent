"""THE SCOREBOARD (#173) — the rules every number must obey."""
from __future__ import annotations

import datetime as dt
import os
import re
from decimal import Decimal

import pytest

from helpers import SYDNEY_TZ
from scoreboard import build as B
from scoreboard import fetch as F
from scoreboard import rules as R
from scoreboard import store as S

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(HERE, "scoreboard")
NOW = dt.datetime(2026, 10, 7, 18, 0, tzinfo=SYDNEY_TZ)
OCT = R.window("month", NOW.date())
SEP = R.window("custom", NOW.date(), "2026-09-01", "2026-09-30")
CONSULT, PERSONAL, TESTCAL = "calConsult0001", "calPersonal001", "calTest000001"
STAGE_WON, STAGE_OPEN = "stageWon00001", "stageOpen0001"


def syd(y, m, d, h=10, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=SYDNEY_TZ).isoformat()


def contact(cid, first, last, email=None, phone=None, added=None, paid=True, form=None):
    return {"id": cid, "firstNameRaw": first, "lastNameRaw": last, "email": email, "phone": phone,
            "dateAdded": added or syd(2026, 10, 2),
            "attributions": [{"utmSessionSource": "Paid Social", "medium": "facebook", "utmCampaign": "C1"}] if paid else
                            [{"utmSessionSource": "Social media", "medium": "instagram"}],
            "source": "Facebook", "deal_form": form or {}}


def event(eid, cid, start, status="confirmed", cal=CONSULT, user="userKalin0001"):
    return {"id": eid, "contactId": cid, "calendarId": cal, "startTime": start, "appointmentStatus": status,
            "assignedUserId": user, "_calendarName": {CONSULT: "Served - Consultation Calendar",
                                                      PERSONAL: "Kalin Long's Personal Calendar",
                                                      TESTCAL: "Served Consult calendar - TEST"}[cal]}


def charge(cid, amount_cents, created, email, name="Payer", status="succeeded"):
    return {"id": cid, "amount": amount_cents, "status": status, "paid": status == "succeeded",
            "created": int(dt.datetime.fromisoformat(created).timestamp()), "billing_email": email,
            "billing_name": name, "currency": "aud", "description": "Growth Pro"}


def base_raw():
    harman_form = {"package": "Growth Pro", "business_name": "Grappino",
                   "deal_summary": "Package\tGrowth Pro, six-month marketing agreement\nFee\t$3,050 + GST per month\n"
                                   "Exit waived at three months\nSet by: Maran. Closed by: Kalin.",
                   "amount_paid_inc_gst": "3355"}
    rose_form = {"package": "Scale Engine", "business_name": "Rose Borek",
                 "deal_summary": "Package: Six Month Scale Engine, 6 month term.\nPrice: $14,500 + GST, paid as 2 instalments\n"
                                 "Set by: Maran. Closed by: Coby."}
    return {
        "pipeline": {"p1": {"id": "p1", "name": "1 SERVED Client Acquisition",
                            "stages": [{"id": STAGE_WON, "name": "✅ Closed Deal"}, {"id": STAGE_OPEN, "name": "Consult Call Booked"}]}},
        "calendar": {CONSULT: {"id": CONSULT, "name": "Served - Consultation Calendar", "calendarType": "round_robin"},
                     PERSONAL: {"id": PERSONAL, "name": "Kalin Long's Personal Calendar", "calendarType": "personal"},
                     TESTCAL: {"id": TESTCAL, "name": "Served Consult calendar - TEST", "calendarType": "round_robin"}},
        "contact": {
            "cHarman": contact("cHarman", "Harman", "Singh", "harman@x.com", "0470432499", syd(2026, 9, 5), form=harman_form),
            "cRose": contact("cRose", "Ozan", "Ozsoy", "ozan@x.com", None, syd(2026, 9, 28), form=rose_form),
            "cDup1": contact("cDup1", "Ann", "Lee", "ann@x.com", "0400000001", syd(2026, 10, 3)),
            "cDup2": contact("cDup2", "Ann", "Lee", "ANN@x.com", None, syd(2026, 10, 4)),
            "cOrganic": contact("cOrganic", "Org", "Anic", "org@x.com", None, syd(2026, 10, 4), paid=False),
            "cTest": contact("cTest", "Test", "Lead", "t@x.com", None, syd(2026, 10, 4)),
        },
        "event": {
            # a reschedule chain: 3 Oct (never marked) → 5 Oct = ONE call at 5 Oct
            "eA1": event("eA1", "cDup1", syd(2026, 10, 3, 11)),
            "eA2": event("eA2", "cDup1", syd(2026, 10, 5, 11), status="showed"),
            "eCancel": event("eCancel", "cRose", syd(2026, 10, 2, 9), status="cancelled"),
            "eUnmarked": event("eUnmarked", "cRose", syd(2026, 10, 1, 9)),
            "eNoShow": event("eNoShow", "cOrganic", syd(2026, 10, 6, 9), status="noshow"),
            "eFuture": event("eFuture", "cTest", syd(2026, 10, 20, 9)),
            "eTest": event("eTest", "cTest", syd(2026, 10, 2, 9), cal=TESTCAL),
            "ePersonal": event("ePersonal", "cTest", syd(2026, 10, 2, 13), cal=PERSONAL),
        },
        "opportunity": {
            "oHarman": {"id": "oHarman", "contactId": "cHarman", "pipelineStageId": STAGE_WON, "name": "Harman Singh",
                        "lastStageChangeAt": "2026-09-11T02:34:00Z", "assignedTo": "userKalin0001"},
            "oRose": {"id": "oRose", "contactId": "cRose", "pipelineStageId": STAGE_WON, "name": "Ozan Ozsoy",
                      "lastStageChangeAt": "2026-10-02T02:28:00Z", "assignedTo": "userCoby00001"},
            "oOpen": {"id": "oOpen", "contactId": "cDup1", "pipelineStageId": STAGE_OPEN, "name": "Ann Lee",
                      "lastStageChangeAt": "2026-10-03T02:28:00Z"},
        },
        "closed_entered": {},
        "charge": {
            "chHarman": charge("chHarman", 335500, syd(2026, 9, 14), "harman@x.com", "Harman Singh"),
            "chRose": charge("chRose", 830500, syd(2026, 10, 2, 12), "ozan@x.com", "Dursun Ozan Ozsoy"),
            "chFailed": charge("chFailed", 830500, syd(2026, 10, 2, 11), "ozan@x.com", status="failed"),
            "chStranger": charge("chStranger", 22000, syd(2026, 10, 3), "nobody@x.com", "A Stranger"),
        },
        "refund": {"re1": {"id": "re1", "charge": "chRose", "amount": 55000, "status": "succeeded",
                           "created": int(dt.datetime.fromisoformat(syd(2026, 10, 4)).timestamp())}},
        "payout": {"po1": {"id": "po1", "amount": 830500}},
        "account_day": {f"2026-10-0{d}": {"date_start": f"2026-10-0{d}", "spend": "100.37", "impressions": "1000",
                                           "clicks": "10", "actions": [{"action_type": "lead", "value": "2"}],
                                           "_final": d < 7} for d in range(1, 8)},
        "ad_day": {},
        "bank_txn": {
            "xPayout": {"BankTransactionID": "xPayout", "Type": "RECEIVE", "Status": "AUTHORISED",
                        "Contact": {"Name": "Stripe"}, "DateString": "2026-10-03T00:00:00", "Total": 8305, "SubTotal": 8305},
            "xRose": {"BankTransactionID": "xRose", "Type": "RECEIVE", "Status": "AUTHORISED",
                      "Contact": {"Name": "Rose Borek"}, "DateString": "2026-10-05T00:00:00", "Total": 1100, "SubTotal": 1000},
            "xTransfer": {"BankTransactionID": "xTransfer", "Type": "RECEIVE-TRANSFER", "Status": "AUTHORISED",
                          "Contact": {"Name": "Served savings"}, "DateString": "2026-10-05T00:00:00", "Total": 5000},
        },
        "invoice": {}, "pnl_month": {}, "sheet": {},
    }


def built(raw=None, w=OCT, decisions=None):
    return B.build(raw or base_raw(), w, NOW, decisions or {}, {"rulings": {}})


def m(b, key):
    for sec in ("funnel", "cost", "returns"):
        for x in b[sec]:
            if x["key"] == key:
                return x
    return next(x for x in b["estimates"]["metrics"] if x["key"] == key)


# ── the brief's named tests ─────────────────────────────────────────────────

def test_one_lead_per_person():
    b = built()
    leads = m(b, "leads")
    names = [r["name"] for r in leads["rows"]]
    assert names.count("Ann Lee") == 1                       # two contacts, one email → one lead
    ann = next(r for r in leads["rows"] if r["name"] == "Ann Lee")
    assert ann["repeat_submissions"] and ann["repeat_submissions"][0]["contact_id"] == "cDup2"
    assert "Org Anic" not in names                           # organic social is not an ad lead
    assert "Test Lead" not in names                          # a test contact is listed, not counted
    assert leads["value"] == len(leads["rows"])


def test_reschedule_chain_counted_once_at_final_time():
    b = built()
    booked = m(b, "calls_booked")["rows"]
    ids = [r["appointment_id"] for r in booked]
    assert "eA2" in ids and "eA1" not in ids
    assert any(r["appointment_id"] == "eA1" for r in b["detail"]["calls_rescheduled_removed"])


def test_cancelled_never_counts_as_booked():
    b = built()
    assert "eCancel" not in [r["appointment_id"] for r in m(b, "calls_booked")["rows"]]
    assert [r["appointment_id"] for r in b["detail"]["calls_cancelled"]] == ["eCancel"]


def test_unmarked_never_assumed():
    b = built(w=R.window("custom", NOW.date(), "2026-10-01", "2026-10-31"))
    rows = {r["appointment_id"]: r["outcome"] for r in m(b, "calls_booked")["rows"]}
    assert rows["eUnmarked"] == "unmarked"
    assert rows["eFuture"] == "still to come"
    assert m(b, "calls_held")["value"] == 1                  # only the one marked 'showed'
    assert m(b, "calls_held")["parts"]["unmarked"] == 1
    assert any(n["kind"] == "Unmarked consult" for n in b["needs_a_human"])


def test_test_and_personal_calendars_not_counted():
    b = built()
    ids = [r["appointment_id"] for r in m(b, "calls_booked")["rows"]]
    assert "eTest" not in ids and "ePersonal" not in ids
    assert any(n["kind"] == "Booking on a personal calendar" for n in b["needs_a_human"])


def test_gst_conversion():
    assert R.ex_gst(Decimal("3355")) == Decimal("3050.00")
    assert R.ex_gst(Decimal("8305")) == Decimal("7550.00")
    assert R.ex_gst(Decimal("1677.50")) == Decimal("1525.00")


def test_refund_netting():
    b = built()
    cash = m(b, "new_client_cash")
    # Rose: $8,305 inc → $7,550 ex, less a $550 inc refund → $500 ex
    assert cash["value"] == pytest.approx(7550.00 - 500.00 + 0)  # + the Xero line is not linked to her deal
    assert any(r["source"] == "Stripe refund" for r in cash["rows"])


def test_failed_charges_and_stripe_payouts_are_not_receipts():
    b = built()
    ids = [r["id"] for r in m(b, "new_client_cash")["rows"]]
    assert "chFailed" not in ids
    nr = {r["id"]: r["why"] for r in b["detail"]["not_receipts"]}
    assert "Stripe payout" in nr["xPayout"] and "transfer" in nr["xTransfer"]


def test_each_payment_counted_once():
    raw = base_raw()
    pays, refunds, _ = B.payments(raw)
    ids = [p["id"] for p in pays]
    assert len(ids) == len(set(ids))
    assert "xPayout" not in ids                              # the Stripe payout is the same money as chRose


def test_xero_receipt_uses_xeros_own_ex_gst():
    pays, _, _ = B.payments(base_raw())
    x = next(p for p in pays if p["id"] == "xRose")
    assert x["amount_ex"] == Decimal("1000.00")


def test_meta_cent_exact():
    b = built()
    spend = m(b, "ad_spend")
    assert spend["value"] == 702.59                          # 7 × $100.37, no float drift
    assert sum(Decimal(str(r["spend"])) for r in spend["rows"]) == Decimal("702.59")


def test_missing_meta_day_is_not_zero():
    raw = base_raw()
    del raw["account_day"]["2026-10-03"]
    b = built(raw)
    assert m(b, "ad_spend")["value"] is None
    assert m(b, "cac_ads")["value"] is None
    assert "not yet read" in m(b, "ad_spend")["note"]


def test_sydney_window_boundaries():
    w = R.window("last_month", dt.date(2026, 10, 7))
    assert (w["start"], w["end"]) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    # 30 Sep 14:30 UTC = 1 Oct 00:30 Sydney → October, not September
    assert R.syd_date("2026-09-30T14:30:00Z") == dt.date(2026, 10, 1)
    assert R.syd_date("2026-09-30T13:30:00Z") == dt.date(2026, 9, 30)
    # Harman entered Closed Won 11 Sep 02:34 UTC = 11 Sep 12:34 Sydney
    b = built(w=SEP)
    assert [d["person"] for d in m(b, "closes")["rows"]] == ["Harman Singh"]
    for k in ("month", "last_month", "last7", "last30", "last90"):
        assert R.window(k, dt.date(2026, 10, 7))["label"]


def test_rows_behind_every_number_sum_to_it():
    for w in (OCT, SEP):
        b = built(w=w)
        for sec in ("funnel", "cost", "returns"):
            for x in b[sec]:
                if x["value"] is None or (not x["rows"] and x["unit"] != "count"):
                    continue
                if x["unit"] == "count":
                    assert x["value"] == len(x["rows"]), x["key"]
                elif x["sum_field"] and x["key"] != "cash30_per_client" and x["key"] != "cac_loaded":
                    assert round(sum(r[x["sum_field"]] or 0 for r in x["rows"]), 2) == x["value"], x["key"]
        loaded = m(b, "cac_loaded")
        if loaded["value"] is not None:
            assert round(sum(r["amount"] for r in loaded["rows"]), 2) == loaded["parts"]["total"]
        c30 = m(b, "cash30_per_client")
        if c30["rows"]:
            assert round(sum(r["cash_30d_ex"] for r in c30["rows"]) / len(c30["rows"]), 2) == c30["value"]


# ── closes, deal form, linking ──────────────────────────────────────────────

def test_closes_are_the_closed_won_stage_by_opportunity():
    b = built()
    rows = m(b, "closes")["rows"]
    assert [r["opp_id"] for r in rows] == ["oRose"]
    assert rows[0]["contract_ex"] == 14500.0 and rows[0]["closer"] == "Coby" and rows[0]["setter"] == "Maran"


def test_deal_form_states_only_what_it_states():
    total, _ = R.stated_total_ex_gst("Price: $1,500 + GST every two weeks")
    assert total is None                                     # a fee, not a contract total
    assert R.stated_total_ex_gst("$15,000 + GST in total")[0] == Decimal("15000.00")
    assert R.stated_term_months("Term\tSix month marketing agreement\nExit waived at three months")[0] == 6
    assert R.stated_closer_setter("Set and closed by Coby") == {"setter": "Coby", "closer": "Coby"}
    b = built(w=SEP)
    harman = m(b, "closes")["rows"][0]
    assert harman["contract_ex"] is None                     # the form never states a total …
    props = [p for p in harman["proposals"] if p["what"] == "contract value ex-GST"]
    assert props and props[0]["value"] == "18300.00"         # … so ×6 is a PROPOSAL, not a number


def test_a_confirmed_proposal_counts_and_is_attributed():
    dec = {"deal:oHarman:contract_ex": {"actor": "Rydel", "at": "2026-10-07T10:00:00", "action": "confirm",
                                        "data": {"value": "18300.00"}}}
    b = built(w=SEP, decisions=dec)
    assert m(b, "contract_value")["value"] == 18300.0
    assert "confirmed by Rydel" in m(b, "closes")["rows"][0]["contract_basis"]


def test_payments_link_by_exact_email_only():
    b = built()
    nah = [n for n in b["needs_a_human"] if n["kind"] == "Payment not linked to a client"]
    assert any("A Stranger" in n["what"] for n in nah)
    rose_cash = [r for r in m(b, "new_client_cash")["rows"] if r["id"] == "chRose"]
    assert rose_cash and rose_cash[0]["link"]["how"] == "same email as the GHL contact"


def test_alias_to_a_differently_named_deal_is_a_proposal_not_a_link():
    raw = base_raw()
    raw["contact"]["cHarman"]["deal_form"]["business_name"] = "Pompoko Ramen"
    raw["charge"]["chAlias"] = charge("chAlias", 165000, syd(2026, 9, 23), "sanatani@x.com", "Sanatani Rombola")
    b = built(raw, w=SEP)
    pay = next(n for n in b["needs_a_human"] if "Sanatani" in n["what"])
    assert pay["proposal"] and pay["proposal"]["opp_id"] == "oHarman"
    assert "chAlias" not in [r["id"] for r in m(b, "new_client_cash")["rows"]]


def test_commission_from_the_rulebook():
    b = built()
    rose = m(b, "closes")["rows"][0]
    cm = rose["commission"]
    assert cm["closer_amount"] == 1000.0                    # Coby, junior rate, Scale Engine (rulebook v4)
    assert cm["setter_amount"] == pytest.approx(0.05 * (7550 - 500))


def test_estimates_are_labelled_with_n():
    b = built()
    for x in b["estimates"]["metrics"]:
        assert x["kind"] == "estimate" and "based on" in x["based_on"]
    assert any("Capped at 36 months" in a for a in b["estimates"]["assumptions"])


# ── the read-only law and the contact allowlist ─────────────────────────────

def _pkg_source():
    out = {}
    for root, _, files in os.walk(PKG):
        for f in files:
            if f.endswith(".py"):
                out[f] = open(os.path.join(root, f), encoding="utf-8").read()
    return out


def test_no_writes_to_any_source():
    for f, src in _pkg_source().items():
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        assert not re.search(r"requests\.(post|put|patch|delete)\b", code), f
        assert not re.search(r"\.(post|put|patch|delete)\(\s*['\"]https?://", code), f
    assert "requests.get(" in _pkg_source()["fetch.py"]


def test_never_uses_ghl_email_token():
    for f, src in _pkg_source().items():
        assert "GHL_EMAIL_TOKEN" not in src, f


def test_does_not_call_the_old_engines():
    banned = ("close_register", "gap_reconcile", "unit_econ_engine", "sales_cost", "cash_truth",
              "close_detect", "close_integrity", "ground_truth", "metrics_engine", "hormozi_metrics")
    for f, src in _pkg_source().items():
        for b in banned:
            assert not re.search(rf"\bimport {b}\b|\bfrom {b}\b", src), (f, b)


def test_contacts_are_cut_down_before_storage():
    raw = {"id": "c1", "firstName": "a", "email": "a@x.com", "address1": "1 Street",
           "customFields": [{"id": "mRyGnKerOZtM9qAF8WGM", "value": "Growth Pro"},
                            {"id": "J5hG7tf7nukcjezrDQlE", "value": "Wix / owner@x.com / Password: hunter2"}]}
    safe = F.safe_contact(raw)
    assert safe["deal_form"] == {"package": "Growth Pro"}
    assert "customFields" not in safe and "address1" not in safe
    assert "hunter2" not in repr(safe)


# ── store + routes ──────────────────────────────────────────────────────────

def test_store_one_row_per_source_id_and_first_sighting_kept(monkeypatch):
    monkeypatch.setattr(S, "use_db", lambda: False)
    S.reset_memory()
    S.upsert("stripe", "charge", {"ch1": {"amount": 1}})
    S.upsert("stripe", "charge", {"ch1": {"amount": 2}})
    assert S.read("stripe", "charge") == {"ch1": {"amount": 2}}
    assert S.insert_if_absent("ghl", "closed_entered", "o1", {"entered_at": "A"})
    assert not S.insert_if_absent("ghl", "closed_entered", "o1", {"entered_at": "B"})
    assert S.read("ghl", "closed_entered")["o1"]["entered_at"] == "A"
    assert S.claim("ghl", 60) and not S.claim("ghl", 60)
    S.journal_add("Rydel", "confirm", "user:abc", {"name": "Kalin"})
    S.journal_add("Rydel", "undo", "user:abc", {})
    assert "user:abc" not in S.decisions()
    S.reset_memory()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(S, "use_db", lambda: False)
    S.reset_memory()
    import app as appmod
    appmod.app.config["TESTING"] = True
    monkeypatch.setattr(B, "load_raw", lambda: base_raw())
    B.invalidate()
    with appmod.app.test_client() as c:
        yield c
    S.reset_memory()
    B.invalidate()


def _login(c, role):
    with c.session_transaction() as s:
        s["actor"] = {"user": role, "role": role, "display": role.capitalize()}


def test_page_needs_a_login(client):
    r = client.get("/scoreboard/api")
    assert r.status_code in (302, 401)


def test_owner_and_finance_see_it_sales_does_not(client):
    for role, ok in (("owner", True), ("coo", True), ("sales", False), ("ad_domain", False)):
        _login(client, role)
        r = client.get("/scoreboard/api")
        assert (r.status_code == 200) == ok, role


def test_page_renders(client):
    _login(client, "owner")
    r = client.get("/scoreboard?window=last_month")
    assert r.status_code == 200 and b"The Scoreboard" in r.data and b"Needs a human" in r.data


def test_confirm_is_journaled_and_gate_cannot_act(client):
    _login(client, "gate")
    r = client.post("/scoreboard/api/confirm", json={"key": "user:userKalin0001", "data": {"name": "Kalin Long"}})
    assert r.get_json().get("refused") == "gate" and not S.journal()
    _login(client, "owner")
    r = client.post("/scoreboard/api/confirm", json={"key": "user:userKalin0001", "data": {"name": "Kalin Long"}})
    assert r.get_json()["ok"]
    j = S.journal()
    assert j[-1]["key"] == "user:userKalin0001" and j[-1]["data"]["name"] == "Kalin Long" and j[-1]["actor"] == "Owner"
    r = client.post("/scoreboard/api/confirm", json={"key": "drop table", "data": {"x": 1}})
    assert r.status_code == 400
