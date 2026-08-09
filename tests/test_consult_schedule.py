"""
tests/test_consult_schedule.py — the consult scheduled-datetime source (#134).

Pins: the EXACT display format (12-hour, full month, midday/midnight edges),
the appointment-endpoint timezone truth (offset-less = SYDNEY-LOCAL, localized
never converted; Z/offset converts), DST-transition rendering, the rebook rule
(cancelled/invalid never render as the consult; earliest upcoming beats latest
past), and every honest non-time state. booked-on vs scheduled-for must never
swap: the field carries a provenance line saying windowing stays on booked-on.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import consult_schedule as CS
from helpers import SYDNEY_TZ

NOW = SYDNEY_TZ.localize(dt.datetime(2026, 8, 9, 12, 0))


def _appt(aid, start, status="confirmed", added="2026-08-01 10:00:00"):
    return {"id": aid, "startTime": start, "appointmentStatus": status,
            "dateAdded": added}


# ── the formatter: exact spec ────────────────────────────────────────────────

def test_format_exact_spec():
    d = SYDNEY_TZ.localize(dt.datetime(2026, 8, 14, 14, 30))
    assert CS.format_consult(d) == "August 14, 2026, 2:30 PM"


def test_format_midday_and_midnight():
    assert CS.format_consult(SYDNEY_TZ.localize(dt.datetime(2026, 8, 14, 12, 0))) == \
        "August 14, 2026, 12:00 PM"
    assert CS.format_consult(SYDNEY_TZ.localize(dt.datetime(2026, 8, 14, 0, 5))) == \
        "August 14, 2026, 12:05 AM"
    assert CS.format_consult(SYDNEY_TZ.localize(dt.datetime(2026, 8, 14, 23, 59))) == \
        "August 14, 2026, 11:59 PM"


def test_format_single_digit_day_no_padding():
    assert CS.format_consult(SYDNEY_TZ.localize(dt.datetime(2026, 9, 3, 9, 5))) == \
        "September 3, 2026, 9:05 AM"


# ── the parser: appointment-endpoint tz truth ────────────────────────────────

def test_offsetless_is_sydney_local_never_utc_shifted():
    """THE tz trap: 130/130 live appointments sit in business hours as-written;
    the UTC reading would put a 5pm consult at 3am. Offset-less = local."""
    d = CS.parse_appt_dt("2026-04-21 17:00:00")
    assert d.hour == 17 and d.tzinfo is not None
    assert CS.format_consult(d) == "April 21, 2026, 5:00 PM"


def test_z_suffixed_converts_from_utc():
    d = CS.parse_appt_dt("2026-07-09T22:30:00Z")
    assert CS.format_consult(d) == "July 10, 2026, 8:30 AM"   # +10h AEST


def test_explicit_offset_converts():
    d = CS.parse_appt_dt("2026-08-14T09:00:00-04:00")          # US East
    assert CS.format_consult(d) == "August 14, 2026, 11:00 PM"  # 13h ahead


def test_dst_transition_days_render_correct_wall_clock():
    # AEDT begins 2026-10-04 (Sydney): wall-clock local times stay wall-clock
    before = CS.parse_appt_dt("2026-10-03 15:00:00")
    after = CS.parse_appt_dt("2026-10-05 15:00:00")
    assert CS.format_consult(before) == "October 3, 2026, 3:00 PM"
    assert CS.format_consult(after) == "October 5, 2026, 3:00 PM"
    assert before.tzname() == "AEST" and after.tzname() == "AEDT"


def test_garbage_parses_to_none_never_a_guess():
    for bad in (None, "", "not a date", "2026-13-40 12:00:00"):
        assert CS.parse_appt_dt(bad) is None


# ── selection: rebook chains, upcoming vs past ───────────────────────────────

def test_cancelled_never_renders_as_the_consult():
    cur, rebooked = CS.pick_current([
        _appt("a1", "2026-08-01 14:00:00", status="cancelled"),
        _appt("a2", "2026-08-05 15:30:00", status="confirmed"),
    ], now=NOW)
    assert cur["id"] == "a2" and rebooked == 1


def test_earliest_upcoming_beats_latest_past():
    cur, _ = CS.pick_current([
        _appt("past", "2026-08-08 10:00:00"),
        _appt("soon", "2026-08-11 10:00:00"),
        _appt("later", "2026-09-01 10:00:00"),
    ], now=NOW)
    assert cur["id"] == "soon"


def test_all_past_picks_latest():
    cur, _ = CS.pick_current([
        _appt("old", "2026-07-01 10:00:00"),
        _appt("newer", "2026-08-05 16:00:00"),
    ], now=NOW)
    assert cur["id"] == "newer"


def test_only_cancelled_yields_none_with_count():
    cur, rebooked = CS.pick_current([
        _appt("a1", "2026-08-01 14:00:00", status="cancelled"),
        _appt("a2", "2026-08-02 14:00:00", status="invalid"),
    ], now=NOW)
    assert cur is None and rebooked == 2


# ── the row field: every state honest ────────────────────────────────────────

def test_field_scheduled_with_rebook_and_upcoming():
    cache = {"c1": {"appts": [
        _appt("a1", "2026-08-01 14:00:00", status="cancelled"),
        _appt("a2", "2026-08-14 14:30:00", status="confirmed")]}}
    f = CS.consult_field("c1", market="au", now=NOW, cache=cache)
    assert f["state"] == "scheduled"
    assert f["formatted"] == "August 14, 2026, 2:30 PM"
    assert f["upcoming"] is True and f["rebooked"] == 1
    assert f["appointment_id"] == "a2"
    assert "booked-on" in f["provenance"]          # the semantic pin rides along
    assert "tz_label" not in f                     # AU leads: no suffix noise


def test_field_us_market_carries_tz_label():
    cache = {"c1": {"appts": [_appt("a2", "2026-08-14 14:30:00")]}}
    f = CS.consult_field("c1", market="us", now=NOW, cache=cache)
    assert f["tz_label"] == "AEST"
    f2 = CS.consult_field("c1", market="us",
                          now=SYDNEY_TZ.localize(dt.datetime(2026, 11, 1, 9, 0)),
                          cache={"c1": {"appts": [_appt("a3", "2026-11-05 10:00:00")]}})
    assert f2["tz_label"] == "AEDT"                # DST-correct suffix


def test_field_tracker_only_no_contact():
    f = CS.consult_field(None, now=NOW, cache={})
    assert f["state"] == "tracker_only"
    assert "no GHL appointment" in f["note"]


def test_field_fetched_but_empty_is_no_appointment():
    f = CS.consult_field("c1", now=NOW, cache={"c1": {"appts": []}})
    assert f["state"] == "no_appointment"
    assert "no GHL appointment" in f["note"]


def test_field_unfetched_is_distinct_from_no_appointment():
    f = CS.consult_field("c1", now=NOW, cache={})
    assert f["state"] == "unfetched"
    assert "not a missing consult" in f["note"]


def test_field_only_cancelled_states_the_chain():
    cache = {"c1": {"appts": [_appt("a1", "2026-08-01 14:00:00", status="cancelled")]}}
    f = CS.consult_field("c1", now=NOW, cache=cache)
    assert f["state"] == "no_appointment" and "cancelled" in f["note"]


# ── warm: bounded, cache-respecting ──────────────────────────────────────────

def test_warm_skips_cached_and_respects_cap(monkeypatch):
    import kv_store
    monkeypatch.setattr(kv_store, "get",
                        lambda k, default=None: {"c1": {"appts": []}}
                        if k == CS._KV_APPT_CACHE else default)
    calls = []
    import ads_truth
    monkeypatch.setattr(ads_truth, "_cached_appointments",
                        lambda cid: calls.append(cid) or [])
    out = CS.warm(["c1", "c2", "c3", "c4"], cap=2)
    assert calls == ["c2", "c3"]                   # cached c1 skipped; cap honoured
    assert out["fetched"] == 2 and out["remaining"] == 1


# ── roster engine integration: the field rides the ONE roster path ───────────

def test_roster_rows_carry_consult_where_set_exists(monkeypatch):
    import attribution_engine as eng
    import roster_engine as RE
    from tests.test_roster_engine import _reset_kv, _rows, _contacts, _compute, _patch_live
    _reset_kv()
    cache = {"c1": {"appts": [_appt("a1", "2026-07-20 14:30:00", status="cancelled"),
                              _appt("a2", "2026-08-14 14:30:00", status="confirmed")]}}
    monkeypatch.setattr(CS, "_cache", lambda: cache)
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    out = RE.build(days=31, basis="cohort", level="creative",
                   key="120000000000000001", metric="sets")
    assert out.get("error") is None
    ann = next(p for p in out["people"] if p["name"] == "Ann Alpha")
    # Ann is id-linked to c1 → scheduled, rebooked ×1, exact format
    assert ann["consult"]["state"] == "scheduled"
    assert ann["consult"]["formatted"] == "August 14, 2026, 2:30 PM"
    assert ann["consult"]["rebooked"] == 1
    assert ann["booked_date"] == "2026-07-11"      # booked-on stays the windowing date
    # a LEADS-cell roster also carries the consult for set-holders (any funnel cell)
    out2 = RE.build(days=31, basis="cohort", level="creative",
                    key="120000000000000001", metric="leads")
    ann2 = next(p for p in out2["people"] if p["name"] == "Ann Alpha")
    assert ann2.get("consult", {}).get("formatted") == "August 14, 2026, 2:30 PM"
    # a NO-SET person carries NO consult field — absence is honest (Cara has
    # setter outcome blank → no set; she sits on the unattributed tier)
    out3 = RE.build(days=31, basis="cohort", level="creative",
                    key="__unattributed__", metric="leads")
    cara = next((p for p in out3["people"] if p["name"] == "Cara Gamma"), None)
    assert cara is not None and "consult" not in cara


def test_roster_unfetched_contact_is_stated_not_blank(monkeypatch):
    import roster_engine as RE
    from tests.test_roster_engine import _reset_kv, _compute, _patch_live
    _reset_kv()
    monkeypatch.setattr(CS, "_cache", lambda: {})   # nothing warmed yet
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    out = RE.build(days=31, basis="cohort", level="creative",
                   key="120000000000000001", metric="sets")
    ann = next(p for p in out["people"] if p["name"] == "Ann Alpha")
    assert ann["consult"]["state"] == "unfetched"


# ── #134 the appointment-local tz fix (the F8-appt regression class) ─────────

def test_appt_day_offsetless_is_local_day_never_utc_shifted():
    """A 5pm local booking must stay on its own day — the naive=UTC path pushed
    every >=14:00 appointment stamp onto the NEXT Sydney day (the 22-entry
    F8 migration regression, corrected by rederive_appointment_local_days)."""
    assert CS.appt_day("2026-04-17 17:25:43") == "2026-04-17"
    from helpers import sydney_day
    assert str(sydney_day("2026-04-17 17:25:43")) == "2026-04-18"   # the trap, pinned
    # Z-suffixed stamps still convert (messages/contacts are genuinely UTC)
    assert CS.appt_day("2026-07-09T22:30:00Z") == "2026-07-10"
    assert CS.appt_day(None) is None


def test_event_sweep_derives_appointment_days_source_aware():
    """Structural: every appointment-field day conversion in ads_truth goes
    through consult_schedule.appt_day — never _date_of/sydney_day (which stay
    correct for the Z-suffixed message + contact stamps)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "ads_truth.py")).read()
    sweep = src.split("def event_sweep")[1].split("def ")[1] if False else \
        src.split("def event_sweep")[1]
    seg = sweep.split("def contact_calls")[0]
    assert "_date_of(a.get(" not in seg               # no appointment field on the UTC path
    assert "appt_day(a.get(" in seg
    # messages stay on the UTC path (verified Z-suffixed live)
    calls_seg = src.split("def contact_calls")[1].split("\ndef ")[0]
    assert '_date_of(m.get("dateAdded")' in calls_seg
    # the re-derivation machinery is source-aware too
    rsrc = open(os.path.join(os.path.dirname(__file__), "..", "resolution.py")).read()
    seg2 = rsrc.split("def rederive_ghl_dates_sydney")[1].split("def rederive_appointment_local_days")[0]
    assert "appt_day(raw)" in seg2
    assert "def rederive_appointment_local_days" in rsrc


def test_upcoming_appointment_cache_expires_daily(monkeypatch):
    """The Matt Annenberg catch (triple sweep): a cancelled-after-caching
    upcoming consult must not render 'upcoming' for a week — upcoming-bearing
    entries expire daily; past-only entries keep the 7d TTL."""
    import ads_truth
    import kv_store
    import datetime as dt
    from helpers import today_sydney
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    t = today_sydney()
    monkeypatch.setattr(ads_truth, "contact_appointments",
                        lambda cid: [{"id": "up1",
                                      "startTime": f"{t + dt.timedelta(days=3)} 11:30:00",
                                      "appointmentStatus": "confirmed"}])
    ads_truth._cached_appointments("cA")
    assert store["ghl:appt_cache"]["cA"]["expires"] == str(t + dt.timedelta(days=1))
    monkeypatch.setattr(ads_truth, "contact_appointments",
                        lambda cid: [{"id": "old1",
                                      "startTime": f"{t - dt.timedelta(days=30)} 14:00:00",
                                      "appointmentStatus": "showed"}])
    ads_truth._cached_appointments("cB")
    assert store["ghl:appt_cache"]["cB"]["expires"] == str(t + dt.timedelta(days=7))
