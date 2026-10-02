"""tests/test_truth_tables.py — #172 Part A: raw rows counted directly, by id.

Pinned: cancelled never counts; one consult per appointment id; a same-
calendar rescheduled chain within 14 days counts once at its final time and
is listed; test/onboarding/personal calendars are excluded and listed;
shows are never assumed (unmarked stays unmarked); closes come from the
Closed Deal stage by opportunity id plus rulings; cash is counted once by id
ex-GST and Stripe payouts are never receipts; the page renders for owner and
finance and the gate cannot act on it.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import truth_tables as TT  # noqa: E402

TODAY = dt.date(2026, 10, 2)


def _ev(eid, cid, start, status, cal="c1", resched=False, user="U1"):
    return {"id": eid, "contactId": cid, "startTime": start, "appointmentStatus": status,
            "_calendarId": cal, "_calendarName": {"c1": "Served - Consultation Calendar", "c2": "Served Onboarding Calendar",
                                                   "c3": "Served Consult calendar - TEST", "c4": "Kalin Long's Personal Calendar"}[cal],
            "assignedUserId": user, "rescheduledAt": "x" if resched else None, "createdBy": {"userId": user}, "title": ""}


def _raw(events, opps=(), stripe=(), xero=(), rulings=()):
    return {
        "calendars": [{"id": "c1", "name": "Served - Consultation Calendar", "calendarType": "round_robin"},
                      {"id": "c2", "name": "Served Onboarding Calendar", "calendarType": "round_robin"},
                      {"id": "c3", "name": "Served Consult calendar - TEST", "calendarType": "round_robin"},
                      {"id": "c4", "name": "Kalin Long's Personal Calendar", "calendarType": "personal"}],
        "events": list(events),
        "contacts_by_id": {"A": {"firstName": "Illawong", "lastName": "Chinese", "timezone": "Australia/Sydney"},
                           "B": {"firstName": "Dan", "lastName": "Cohen", "timezone": "Australia/Sydney"},
                           "J": {"firstName": "Josgen", "lastName": "Jose", "timezone": "America/New_York"}},
        "opportunities": list(opps), "stages": {"closed": "✅ Closed Deal", "lead": "Served New Leads"},
        "pipelines": [], "contacts": [], "other_pipelines": {}, "stage_transitions": [],
        "stripe_matched": list(stripe), "xero_receipts": list(xero), "xero_not_receipts": [],
        "rulings": list(rulings), "tracker_lead_dates": ["2026-09-03", "2026-09-20"],
    }


def test_cancelled_never_counts_and_each_id_counts_once():
    raw = _raw([_ev("e1", "A", "2026-09-17T16:00:00+10:00", "confirmed"),
                _ev("e2", "A", "2026-09-24T16:00:00+10:00", "cancelled"),
                _ev("e3", "B", "2026-09-23T08:00:00+10:00", "confirmed"),
                _ev("e3", "B", "2026-09-23T08:00:00+10:00", "confirmed")])   # the same id twice
    a = TT.appointments(raw, dt.date(2026, 9, 1), TODAY)
    assert a["count"] == 2
    assert [r["why"] for r in a["excluded"]] == ["cancelled — never counts"]
    assert a["rows"][1]["contact_name"] == "Dan Cohen"            # from GHL, never "Dan Cohen Cohen"


def test_a_rescheduled_chain_counts_once_at_its_final_time_and_is_listed():
    raw = _raw([_ev("e1", "A", "2026-09-17T16:00:00+10:00", "confirmed"),
                _ev("e2", "A", "2026-09-21T13:00:00+10:00", "confirmed"),
                _ev("e3", "A", "2026-09-24T16:00:00+10:00", "cancelled")])
    a = TT.appointments(raw, dt.date(2026, 9, 1), TODAY)
    assert a["count"] == 1 and a["rows"][0]["appointment_id"] == "e2"
    assert a["removed_duplicates"][0]["appointment_id"] == "e1"
    assert "counted once at Mon 21 Sep 2026 13:00" in a["removed_duplicates"][0]["why"]
    assert any(f["kind"] == "rescheduled chain (confirm)" for f in a["flags"])


def test_two_consults_far_apart_or_on_different_calendars_both_count():
    raw = _raw([_ev("e1", "A", "2026-09-01T16:00:00+10:00", "confirmed"),
                _ev("e2", "A", "2026-09-30T13:00:00+10:00", "confirmed"),     # > 14 days
                _ev("e3", "B", "2026-09-10T11:00:00+10:00", "confirmed"),
                _ev("e4", "B", "2026-09-12T11:00:00+10:00", "confirmed", cal="c2")])  # onboarding
    a = TT.appointments(raw, dt.date(2026, 9, 1), TODAY)
    assert a["count"] == 3 and not a["removed_duplicates"]
    assert [r["why"] for r in a["excluded"]] == ["onboarding calendar — not a consult"]


def test_test_and_personal_calendars_are_excluded_and_listed():
    raw = _raw([_ev("e1", "A", "2026-09-05T10:00:00+10:00", "confirmed", cal="c3"),
                _ev("e2", "A", "2026-09-06T10:00:00+10:00", "confirmed", cal="c4")])
    a = TT.appointments(raw, dt.date(2026, 9, 1), TODAY)
    assert a["count"] == 0 and {r["why"] for r in a["excluded"]} == {"test calendar — not a consult",
                                                                       "personal calendar — not a consult"}


def test_shows_are_never_assumed():
    raw = _raw([_ev("e1", "A", "2026-09-17T16:00:00+10:00", "confirmed"),
                _ev("e2", "B", "2026-09-18T16:00:00+10:00", "noshow"),
                _ev("e3", "J", "2026-10-20T16:00:00+10:00", "confirmed")])
    a = TT.appointments(raw, dt.date(2026, 9, 1), dt.date(2026, 10, 31))
    assert a["shows"] == {"showed": 0, "no-show": 1, "unmarked": 1, "upcoming": 1}


def test_us_time_consults_are_flagged_with_both_zones():
    raw = _raw([_ev("e1", "J", "2026-09-03T06:30:00+10:00", "confirmed")])
    a = TT.appointments(raw, dt.date(2026, 9, 1), TODAY)
    f = [x for x in a["flags"] if x["kind"] == "outside 7am–9pm Sydney"][0]
    assert "06:30 Sydney" in f["detail"] and "America/New_York" in f["detail"]
    assert a["rows"][0]["start_local"].endswith("16:30")


def test_closes_come_from_the_closed_stage_by_id_plus_rulings():
    opps = [{"id": "o1", "contactId": "A", "pipelineStageId": "closed", "lastStageChangeAt": "2026-09-23T06:03:00.000Z",
             "assignedTo": "6S3Qmfoh1X1geMDKFfVN", "monetaryValue": 2000, "name": "Illawong: x", "customFields": []},
            {"id": "o2", "contactId": "B", "pipelineStageId": "lead", "lastStageChangeAt": "2026-09-23T06:03:00.000Z"},
            {"id": "o3", "contactId": "B", "pipelineStageId": "closed", "lastStageChangeAt": "2026-07-01T00:00:00.000Z"}]
    rulings = [{"person": "Rose Borek", "client": "", "close_date": "2026-10-02", "package": "Scale Engine",
                "contract_ex_gst": 15000.0, "note": "ruling"}]
    c = TT.closes(_raw([], opps=opps, rulings=rulings), dt.date(2026, 9, 1), TODAY)
    assert [r["contact_name"] for r in c["rows"]] == ["Illawong Chinese", "Rose Borek"]
    assert c["rows"][0]["dated_by"] == "GHL last stage change" and c["rows"][0]["day_sydney"] == "2026-09-23"
    assert c["rows"][0]["closer"].startswith("Kalin Long")
    assert c["rows"][1]["source"] == "owner ruling" and c["rows"][1]["stage"] == "owner ruling — not yet in GHL"


def test_cash_counts_each_id_once_ex_gst_from_both_sources():
    stripe = [{"id": "ch_1", "date": "2026-09-23", "payer": "Sanatani Rombola", "amount_inc": 1650.0, "client": "Pompoko Ramen", "basis": "alias"},
              {"id": "ch_1", "date": "2026-09-23", "payer": "Sanatani Rombola", "amount_inc": 1650.0, "client": "Pompoko Ramen", "basis": "alias"},
              {"id": "ch_2", "date": "2026-08-30", "payer": "Old", "amount_inc": 1100.0, "client": "Old Co", "basis": "alias"}]
    xero = [{"id": "x1", "date": "2026-09-29", "payer": "Rockys Italian", "amount_inc": 5500.0, "client": "Rocky's Italian", "basis": "bank line", "unconfirmed": True}]
    m = TT.cash(_raw([], stripe=stripe, xero=xero), dt.date(2026, 9, 1), TODAY)
    assert m["count"] == 2 and m["total_inc"] == 7150.0 and m["total_ex"] == 6500.0
    assert m["by_client"][0]["client"] == "Rocky's Italian" and m["by_client"][0]["ex"] == 5000.0
    assert m["rows"][1]["unconfirmed"] is True


def test_leads_count_opportunities_created_with_the_tracker_beside():
    opps = [{"id": "o1", "contactId": "A", "createdAt": "2026-09-03T01:00:00.000Z", "source": "Facebook", "pipelineStageId": "lead"},
            {"id": "o2", "contactId": "B", "createdAt": "2026-08-20T01:00:00.000Z", "source": "Facebook", "pipelineStageId": "lead"}]
    l = TT.leads(_raw([], opps=opps), dt.date(2026, 9, 1), TODAY)
    assert l["count"] == 1 and l["tracker_rows"] == 2 and l["difference"] == -1
    assert l["by_source"] == {"Facebook": 1}


def test_default_window_is_this_month_and_no_21_day_window_exists():
    w0, w1, label = TT.window("month", TODAY)
    assert (w0, w1) == (dt.date(2026, 10, 1), TODAY) and "This month" in label
    assert TT.window("last7", TODAY)[0] == dt.date(2026, 9, 26)
    assert TT.window("last30", TODAY)[0] == dt.date(2026, 9, 3)
    src = open(os.path.join(os.path.dirname(__file__), "..", "truth_tables.py"), encoding="utf-8").read()
    assert "21 days" not in src.lower() and "last21" not in src and "d21" not in src


def test_the_saved_tables_exist_and_are_unconfirmed():
    t = TT.latest()
    assert t and t["confirmation"]["status"] == "unconfirmed"
    assert set(t["windows"]) >= {"month", "sep", "since_sep", "last7", "last30"}
    assert t["windows"]["sep"]["headline"]["showed"] == 0        # nobody has marked a show in GHL


@pytest.fixture()
def app_client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-172")
    import app as appmod
    return appmod.app


def _as(app, role, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": user, "role": role, "display": user}
    return c


def test_the_truth_page_renders_for_owner_finance_and_gate(app_client):
    for role, user in (("owner", "rydel"), ("coo", "piolo"), ("gate", "gate")):
        r = _as(app_client, role, user).get("/dashboard/truth?window=sep")
        assert r.status_code == 200, role
        html = r.get_data(as_text=True)
        assert "Truth tables" in html and "unconfirmed" in html and 'data-metric="truth_appointments"' in html
    assert _as(app_client, "sales", "sales").get("/dashboard/truth").status_code in (302, 403)
