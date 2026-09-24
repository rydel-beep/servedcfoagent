"""ATTACH THE MONEY · COUNT THE CALLS (#162).

Pinned here:
  1 the roster's venue names are matcher candidates; auto-match stays
    exact-evidence only; the roster columns are read by header name
  2 the calendar-level appointment source: cancelled excluded, test
    calendars out, Sydney days, windows stated in words, one source
  3 the status-stale standing rule
"""

import datetime as dt
import os
import re

import pytest

import kv_store

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


# ── 1 · THE MATCHER ─────────────────────────────────────────────────────────

_IDX = {"by_email": {}, "contacts": [], "by_business": {}, "surname_map": {}}
_ROSTER = {"active": {"pottery green bakers gordon"},
           "amounts": {"pottery green bakers gordon": 2083.33},
           "venues": {"pottery green bakers gordon": "Pottery Green Bakers Gordon"},
           "terms": {}}


def test_a_roster_venue_is_a_candidate_without_a_tracker_row():
    """The Pottery Green case: the client existed only on the roster, and the
    matcher said 'nothing close enough to guess' about a payer string that
    WAS the client's name — candidates came from the tracker alone."""
    import stripe_reconcile as sr
    kv_store._MEM.clear()
    m = sr._match_payment("Pottery Green Bakers Gordon", "", 1760.0, _IDX, _ROSTER)
    assert m["category"] == "needs_review"
    assert m["suggested"][0]["business"] == "Pottery Green Bakers Gordon"
    assert "venue name (roster)" in m["suggested"][0]["basis"]


def test_even_an_exact_venue_name_payer_is_a_proposal_not_a_match():
    """Ruled auto evidence is an alias, a customer id, an email or a phone.
    An exact venue-name payer proposes at top strength; one confirmation
    writes the alias and it attaches itself from then on."""
    import stripe_reconcile as sr
    kv_store._MEM.clear()
    m = sr._match_payment("Pottery Green Bakers Gordon", "", 1760.0, _IDX, _ROSTER)
    assert "business" not in m
    assert m["suggested"][0]["score"] >= 90
    sr.learn_alias("Pottery Green Bakers Gordon", "Pottery Green Bakers Gordon")
    again = sr._match_payment("Pottery Green Bakers Gordon", "", 1760.0, _IDX, _ROSTER)
    assert again["basis"] == "confirmed alias"


def test_an_unrelated_payer_is_still_unrecognised():
    import stripe_reconcile as sr
    kv_store._MEM.clear()
    m = sr._match_payment("Totally Unrelated Payer", "", 999.0, _IDX, _ROSTER)
    assert m["category"] == "unrecognised"


def test_the_roster_is_read_by_header_name_never_position():
    """Production held {'pottery green bakers gordon': 12022025.0} — the
    START DATE 12-02-2025 with the punctuation stripped, treated as twelve
    million dollars of MRR, because the money column was read as r[7]."""
    src = _read("stripe_reconcile.py")
    fn = src[src.index("def _roster_index"):src.index("def _aliases")]
    assert "monthly recognized" in fn.lower()
    # strip the docstring first — it QUOTES the old r[7] for the record,
    # and a test that greps prose fails on its own documentation
    code = re.sub(r'"""(?:.|\n)*?"""', "", fn)
    code = re.sub(r'"""(?:.|\n)*?"""', "", fn, flags=re.S)
    assert "r[7]" not in code, "column 7 is Start Date, not money"
    import stripe_reconcile as sr

    def fake_rows(*a, **k):
        return [["Client Name", "Status", "Package", "Term", "RS", "RD", "RS2",
                 "Start Date", "End Date", "Contract Value",
                 "Monthly Recognized Revenue"],
                ["Pottery Green Bakers Gordon", "Active", "Scale Engine", "6",
                 "", "", "", "12-02-2025", "06-02-2026", "$12,500.00",
                 "$2,083.33"]]
    import sheet_mirror
    orig = sheet_mirror.read_by_gid
    sheet_mirror.read_by_gid = fake_rows
    try:
        r = sr._roster_index()
    finally:
        sheet_mirror.read_by_gid = orig
    assert r["amounts"]["pottery green bakers gordon"] == 2083.33
    assert r["venues"]["pottery green bakers gordon"] == "Pottery Green Bakers Gordon"
    assert r["terms"]["pottery green bakers gordon"]["end_date"] == "06-02-2026"


def test_the_panel_total_never_swallows_cents(monkeypatch):
    """'{:,.0f}' rounded $19,552.50 to $19,552 on the panel whose whole job
    is that no money goes quietly anywhere."""
    import unmatched_payments as UP
    monkeypatch.setattr(UP, "latest", lambda: {"count": 7,
                                               "total_unmatched": 19552.50,
                                               "rows": [], "available": True,
                                               "at": "now"})
    assert UP.panel()["total_text"] == "$19,552.50"
    monkeypatch.setattr(UP, "latest", lambda: {"count": 2,
                                               "total_unmatched": 3520.0,
                                               "rows": [], "available": True,
                                               "at": "now"})
    assert UP.panel()["total_text"] == "$3,520"


# ── 2 · THE APPOINTMENT SOURCE ──────────────────────────────────────────────

def _seed_events(events):
    import appointments as AP
    kv_store.put(AP.K_EVENTS, {"ok": True, "at": "2026-09-24T10:00:00+10:00",
                               "window": {}, "calendars": [], "events": events,
                               "errors": []})


def _ev(day, hour, title, status="confirmed", kind="consult", cid="c1"):
    return {"id": f"{day}{hour}{title[:4]}", "when": f"{day}T{hour:02d}:00:00+10:00",
            "day": day, "title": title, "status": status,
            "cancelled": status in ("cancelled", "invalid"),
            "calendar": "Consultation", "calendar_kind": kind,
            "contact_id": cid, "assigned_user_id": "u1", "owner": "Kalin",
            "booked_at": "2026-09-20T09:00:00.000Z",
            "follow_up": bool(re.search(r"follow", title, re.I))}


def test_cancelled_never_sits_inside_the_booked_count():
    import appointments as AP
    kv_store._MEM.clear()
    _seed_events([_ev("2026-09-24", 11, "Scott — Free Consultation"),
                  _ev("2026-09-24", 16, "Simon — Free Consultation", "cancelled")])
    r = AP.booked_between(dt.date(2026, 9, 24), dt.date(2026, 10, 1))
    assert r["count"] == 1 and r["cancelled_count"] == 1


def test_test_calendars_and_onboarding_never_count_as_consults():
    import appointments as AP
    kv_store._MEM.clear()
    _seed_events([_ev("2026-09-24", 8, "Jeff 24hrs Tesing", kind="test"),
                  _ev("2026-09-25", 14, "Koji — Onboarding", kind="onboarding"),
                  _ev("2026-09-25", 11, "Byrdi — Free Consultation")])
    r = AP.booked_between(dt.date(2026, 9, 24), dt.date(2026, 10, 1))
    assert r["count"] == 1 and len(r["excluded"]) == 2


def test_a_near_midnight_booking_stays_on_its_sydney_day():
    """13:30 UTC on the 24th IS 11:30 PM Sydney on the 24th; 15:00 UTC is
    1:00 AM Sydney on the 25th. A UTC day boundary would misplace both."""
    import appointments as AP
    kv_store._MEM.clear()
    d1 = AP.parse_when("2026-09-24T13:30:00Z")
    d2 = AP.parse_when("2026-09-24T15:00:00Z")
    assert str(d1.date()) == "2026-09-24" and d1.hour == 23
    assert str(d2.date()) == "2026-09-25" and d2.hour == 1


def test_every_window_is_stated_in_words():
    import appointments as AP
    kv_store._MEM.clear()
    _seed_events([_ev("2026-09-28", 8, "Dan — Follow Up")])
    from helpers import today_sydney
    r = AP.booked_between(today_sydney(), dt.date(2026, 10, 1))
    assert r["window_words"].startswith("today →")
    assert r["follow_ups"] == 1


def test_a_rescheduled_consult_counts_once():
    """A reschedule is a cancelled event plus a live one — the live one
    counts, the cancelled one sits beside."""
    import appointments as AP
    kv_store._MEM.clear()
    _seed_events([_ev("2026-09-24", 6, "Lilian — Free Consultation",
                      "cancelled", cid="lil"),
                  _ev("2026-09-25", 9, "Lilian — Free Consultation", cid="lil")])
    r = AP.booked_between(dt.date(2026, 9, 24), dt.date(2026, 10, 1))
    assert r["count"] == 1 and r["cancelled_count"] == 1


def test_every_booked_calls_surface_reads_the_one_source():
    """Scan-2's structural half: pulse, SALES and travelling all read
    appointments.py when the store is filled; the per-contact cache is only
    the labelled fallback before the first sync."""
    for mod, marker in (("compass_engine.py", "appointments.upcoming(7)"),
                        ("sales_scoreboard.py", "appointments.upcoming(7)"),
                        ("travelling.py", "AP.store()")):
        src = _read(mod)
        assert "import appointments" in src, mod
        assert marker in src, mod


def test_the_tile_states_its_window_in_words():
    src = _read("dashboard", "exec_top.py")
    assert 'f"Booked consults · {window}"' in src
    assert "window_words" in src


def test_the_sync_rides_the_crm_loop_and_refresh_now():
    assert "appointments.sync()" in _read("ghl_mirror.py")
    fresh = _read("freshness.py")
    assert "ghl_appointments" in fresh
    assert '_step("CRM calendars", _appts)' in fresh


# ── 3 · THE STANDING RULE ───────────────────────────────────────────────────

def test_a_paying_client_marked_expired_is_a_finding(monkeypatch):
    import client_status_watch as CSW
    kv_store._MEM.clear()
    monkeypatch.setattr("unmatched_payments.latest", lambda: {"matched": [
        {"client": "Pottery Green Bakers Gordon", "payer": "Pottery Green Bakers Gordon",
         "amount": 1760.0, "date": "2026-09-20", "charge_id": "ch_a", "basis": "confirmed alias"},
        {"client": "Pottery Green Bakers Gordon", "payer": "Pottery Green Bakers Gordon",
         "amount": 1760.0, "date": "2026-08-20", "charge_id": "ch_b", "basis": "confirmed alias"},
        {"client": "Healthy Venue", "payer": "Someone", "amount": 3050.0,
         "date": "2026-09-01", "charge_id": "ch_c", "basis": "email"}]})
    monkeypatch.setattr("stripe_reconcile._roster_index", lambda: {
        "terms": {"pottery green bakers gordon":
                  {"status": "Active", "end_date": "06-02-2026", "mrr": 2083.33},
                  "healthy venue":
                  {"status": "Active", "end_date": "01-30-2027", "mrr": 3050.0}},
        "active": set(), "amounts": {}, "venues": {}})
    res = CSW.scan()
    assert res["count"] == 1
    f = res["findings"][0]
    assert f["client"] == "Pottery Green Bakers Gordon"
    assert f["paid_last_60d"] == 3520.0
    assert any("term ended" in p for p in f["problems"])
    items = kv_store.get(CSW.K_FEED)
    assert items and "ch_a" in items[0]["detail"]
    assert "never writes the sheet" in items[0]["action"]


def test_a_healthy_paying_client_is_not_a_finding(monkeypatch):
    import client_status_watch as CSW
    kv_store._MEM.clear()
    monkeypatch.setattr("unmatched_payments.latest", lambda: {"matched": [
        {"client": "Healthy Venue", "payer": "Someone", "amount": 3050.0,
         "date": "2026-09-01", "charge_id": "ch_c", "basis": "email"}]})
    monkeypatch.setattr("stripe_reconcile._roster_index", lambda: {
        "terms": {"healthy venue": {"status": "Active", "end_date": "01-30-2027",
                                    "mrr": 3050.0}},
        "active": set(), "amounts": {}, "venues": {}})
    assert CSW.scan()["count"] == 0
