"""
tests/test_sydney_day.py — F8 (extreme audit): derived dates must use the SYDNEY
day, never the UTC slice. Root cause: `_date_of()` sliced GHL ISO timestamps
(`str(v)[:10]`) — a booking before ~10–11am Sydney derived onto the PREVIOUS
day (drill B9). This violates the today_sydney doctrine at the derivation
boundary; the fix lives in the shared helper (`helpers.sydney_day`), not at
call sites, so it cannot be violated one caller at a time.

Includes the Oct 2026 DST transition (AEST +10 → AEDT +11 on 2026-10-04) so
the conversion can't regress across the changeover, and the journaled F8
re-derivation pass over pre-fix derivations.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers import sydney_day
import kv_store
import resolution


# ── the helper (the source fix) ──────────────────────────────────────────────

def test_drill_b9_case_morning_sydney_booking_is_the_next_day():
    # 2026-07-09T22:30Z is 08:30 AEST on the 10th — the OLD slice said 07-09
    assert sydney_day("2026-07-09T22:30:00.000Z") == dt.date(2026, 7, 10)


def test_afternoon_sydney_booking_keeps_its_day():
    # 2026-07-10T04:00Z is 14:00 AEST on the 10th — same day both ways
    assert sydney_day("2026-07-10T04:00:00.000Z") == dt.date(2026, 7, 10)


def test_dst_transition_oct_2026():
    """AEST (+10) → AEDT (+11) at 2026-10-04 02:00. The helper must apply the
    RIGHT offset on each side of the changeover."""
    # night before the changeover: +10 still applies → 14:30Z = 00:30 on 10-04
    assert sydney_day("2026-10-03T14:30:00Z") == dt.date(2026, 10, 4)
    # after the changeover: +11 applies → 13:30Z = 00:30 on 10-05
    assert sydney_day("2026-10-04T13:30:00Z") == dt.date(2026, 10, 5)
    # boundary check: 12:59Z on 10-04 = 23:59 AEDT on 10-04, NOT 10-05
    assert sydney_day("2026-10-04T12:59:00Z") == dt.date(2026, 10, 4)


def test_accepts_datetimes_dates_offsets_and_bare_dates():
    # naive datetime = wire-format UTC
    assert sydney_day(dt.datetime(2026, 7, 9, 22, 30)) == dt.date(2026, 7, 10)
    # aware datetime in another zone converts correctly
    aware = pytz.utc.localize(dt.datetime(2026, 7, 9, 22, 30))
    assert sydney_day(aware) == dt.date(2026, 7, 10)
    # explicit-offset ISO string
    assert sydney_day("2026-07-10T08:30:00+10:00") == dt.date(2026, 7, 10)
    # a bare date has no clock — passes through
    assert sydney_day("2026-07-09") == dt.date(2026, 7, 9)
    assert sydney_day(dt.date(2026, 7, 9)) == dt.date(2026, 7, 9)
    assert sydney_day(None) is None and sydney_day("") is None
    assert sydney_day("garbage") is None


def test_ads_truth_date_of_uses_sydney_day():
    import ads_truth
    assert ads_truth._date_of("2026-07-09T22:30:00.000Z") == "2026-07-10"
    assert ads_truth._date_of(None) is None


# ── the journaled re-derivation of pre-fix derivations ───────────────────────

def _seed_prefix_derivation():
    """A pre-F8 derivation: appointment booked 2026-07-09T22:30Z (= Sydney
    07-10) but stored with the UTC slice 07-09."""
    kv_store.put("derived:dates", {
        "f8 test lead": {
            "set_date": {"date": "2026-07-09", "provenance": "derived:ghl-appt",
                         "evidence": {"appointment_id": "appt_F8", "contact_id": "cF8",
                                      "raw_status": "confirmed"}, "ts": "2026-08-01"},
            "show_date": {"date": "2026-07-09", "provenance": "derived:ghl-appt",
                          "evidence": {"appointment_id": "appt_F8", "contact_id": "cF8",
                                       "raw_status": "confirmed"}, "ts": "2026-08-01"}}})
    kv_store.put("ghl:appt_cache", {
        "cF8": {"expires": "2099-01-01",
                "appts": [{"id": "appt_F8", "dateAdded": "2026-07-09T22:30:00.000Z",
                           "startTime": "2026-07-09T23:00:00.000Z",
                           "appointmentStatus": "confirmed"}]}})
    kv_store.put("integrity:autofix_log", [])
    kv_store.put("resolution:journal", [])


def test_rederivation_moves_the_date_and_journals_old_new(monkeypatch):
    _seed_prefix_derivation()
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    e0 = resolution.derived_epoch()
    out = resolution.rederive_ghl_dates_sydney()
    changed = {(c["name"], c["field"]): c for c in out["changed"]}
    assert changed[("f8 test lead", "set_date")]["old"] == "2026-07-09"
    assert changed[("f8 test lead", "set_date")]["new"] == "2026-07-10"
    assert changed[("f8 test lead", "set_date")]["evidence_id"] == "appt_F8"
    store = resolution.derived_dates()
    assert store["f8 test lead"]["set_date"]["date"] == "2026-07-10"
    assert store["f8 test lead"]["set_date"]["rederived"]["reason"] == "F8-sydney-day"
    # journaled with old→new + evidence + reason, in the DURABLE stream (F2)
    ej = resolution.evidence_journal()
    assert any("F8-sydney-day" in e["detail"] and "2026-07-09 → 2026-07-10" in e["detail"]
               for e in ej)
    # caches invalidated exactly once (F6)
    assert resolution.derived_epoch() == e0 + 1


def test_rederivation_is_idempotent(monkeypatch):
    _seed_prefix_derivation()
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    resolution.rederive_ghl_dates_sydney()
    e1 = resolution.derived_epoch()
    out2 = resolution.rederive_ghl_dates_sydney()
    assert out2["changed"] == []              # converts nothing twice
    assert resolution.derived_epoch() == e1   # no epoch churn either


def test_rederivation_dry_run_touches_nothing(monkeypatch):
    _seed_prefix_derivation()
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    out = resolution.rederive_ghl_dates_sydney(dry_run=True)
    assert out["changed"] and out["dry_run"] is True
    assert resolution.derived_dates()["f8 test lead"]["set_date"]["date"] == "2026-07-09"


def test_rederivation_flags_window_boundary_crossings(monkeypatch):
    """A date moving across a 30/60/90d window edge changes what those windows
    count — the pass must call it out, not silently shuffle."""
    from helpers import today_sydney
    edge_old = str(today_sydney() - dt.timedelta(days=30))   # just OUTSIDE 30d
    # appointment whose Sydney day is one later — just INSIDE the 30d window
    booked_utc = f"{edge_old}T22:30:00.000Z"
    kv_store.put("derived:dates", {
        "f8 edge lead": {"set_date": {"date": edge_old,
                                      "provenance": "derived:ghl-appt",
                                      "evidence": {"appointment_id": "appt_E",
                                                   "contact_id": "cE",
                                                   "raw_status": "confirmed"},
                                      "ts": "2026-08-01"}}})
    kv_store.put("ghl:appt_cache", {
        "cE": {"expires": "2099-01-01",
               "appts": [{"id": "appt_E", "dateAdded": booked_utc,
                          "startTime": booked_utc, "appointmentStatus": "confirmed"}]}})
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    out = resolution.rederive_ghl_dates_sydney()
    assert out["crossed_window"] and 30 in out["crossed_window"][0]["crossed_window"]
