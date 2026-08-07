"""tests/test_show_truth.py — DECISIONS #129: attendance-evidenced show tiers.
Verified/unverified never merged silently; pre-schedule calls never verify;
cancelled+long-call = set only; outcome-evidenced exception; confirm command;
show-rate consumes verified."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribution_engine as eng
import resolution as RES
from tests.test_attribution import HDR, RES_A, W0, W1, contact, resolver, row


def _reset():
    import kv_store
    for k in ("derived:dates", "ads_truth:proposed", "ads_truth:flags",
              "ghl:call_cache", "integrity:autofix_log"):
        kv_store.put(k, None)


def _compute(rows, contacts, **kw):
    return eng.compute_from_inputs([HDR] + rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}),
                                   W0, W1, **kw)


def _seed_show(nm, state, date="2026-07-12"):
    import kv_store
    store = RES.derived_dates()
    store.setdefault(nm, {})["set_date"] = {
        "date": date, "provenance": "derived:ghl-appt",
        "evidence": {"appointment_id": "ap1", "contact_id": "c1"}}
    store[nm]["show_date"] = {
        "date": date, "provenance": "derived:ghl-appt",
        "evidence": {"appointment_id": "ap1", "contact_id": "c1"},
        "verification": {"state": state, "via": "test"}}
    kv_store.put("derived:dates", store)


def test_unverified_shows_counted_separately_never_merged():
    _reset()
    r_ = row("Status Only", "s@x.com", setter="set", show="")   # NO tracker show flag
    r_[18] = ""
    _seed_show("status only", "unverified")
    out = _compute([r_], [contact("c1", "s@x.com", "Status Only")], basis="activity")
    c = next(x for x in out["creatives"] if x["leads"] == 1 or x["sets"] == 1)
    assert c["shows"] == 1 and c["shows_unverified"] == 1     # split, visible
    sb = eng.scoreboard_view(out)
    srow = next(x for x in sb["rows"] if x["sets"] == 1)
    assert srow["shows_unverified"] == 1                       # rides to the grid


def test_verified_show_counts_clean():
    _reset()
    r_ = row("Verified One", "v@x.com", setter="set", show="")
    r_[18] = ""
    _seed_show("verified one", "verified")
    out = _compute([r_], [contact("c1", "v@x.com", "Verified One")], basis="activity")
    c = next(x for x in out["creatives"] if x["sets"] == 1)
    assert c["shows"] == 1 and c.get("shows_unverified", 0) == 0


def test_tracker_show_flag_stays_authority():
    _reset()
    r_ = row("Tracker Show", "t@x.com", setter="set", show="Showed")
    out = _compute([r_], [contact("c1", "t@x.com", "Tracker Show")])
    c = next(x for x in out["creatives"] if x["sets"] == 1)
    assert c["shows"] == 1 and c.get("shows_unverified", 0) == 0   # authority, not status


def test_show_rate_flag_consumes_verified_only():
    import attribution_flags as AF
    result = {"totals": {"leads": 20}, "window": {"days": 30},
              "creatives": [{"label": "Unverified Heavy", "creative_key": "k1",
                             "tier": "ad", "leads": 10, "qualified": 5, "reached": 5,
                             "sets": 6, "shows": 6, "shows_unverified": 5,
                             "closes": 0, "cash": 0, "spend": 50,
                             "revenue_unknown": 0, "cost_per_lead": 5.0}]}
    out = AF.flags(result)
    hit = next(f for f in out if f["kind"] == "sets_no_shows")
    assert "17%" in hit["headline"]        # 1 verified / 6 sets — not 100%


def test_verification_pass_tiers(monkeypatch):
    """Outcome-evidenced beats everything; a pre-schedule call NEVER verifies; a
    post-schedule ≥threshold call does; else unverified + a PROPOSED card with the
    near-miss shown."""
    _reset()
    import ads_truth
    import kv_store
    for nm in ("closed guy", "early call", "good call", "no call"):
        _seed_show(nm, None)
        store = RES.derived_dates()
        del store[nm]["show_date"]["verification"]
        kv_store.put("derived:dates", store)
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: {
        "creatives": [{"deals": [{"name": "Closed Guy"}]}]})
    calls = {
        "c1": [],   # default
    }
    def fake_calls(cid):
        return calls.get(cid, [])
    # distinct contact ids per name
    store = RES.derived_dates()
    store["early call"]["show_date"]["evidence"]["contact_id"] = "c_early"
    store["good call"]["show_date"]["evidence"]["contact_id"] = "c_good"
    store["no call"]["show_date"]["evidence"]["contact_id"] = "c_none"
    kv_store.put("derived:dates", store)
    calls["c_early"] = [{"id": "call1", "duration": 999, "date": "2026-07-01"}]   # BEFORE 07-12
    calls["c_good"] = [{"id": "call2", "duration": 300, "date": "2026-07-12"}]    # on schedule
    calls["c_none"] = []
    monkeypatch.setattr(ads_truth, "contact_calls", fake_calls)
    out = ads_truth.show_verification_pass()
    store = RES.derived_dates()
    assert store["closed guy"]["show_date"]["verification"]["via"] == "show:outcome-evidenced"
    assert store["good call"]["show_date"]["verification"]["state"] == "verified"
    assert store["early call"]["show_date"]["verification"]["state"] == "unverified"
    assert store["no call"]["show_date"]["verification"]["state"] == "unverified"
    # the near-miss call rides the PROPOSED card as context — never silent verification
    prop = kv_store.get("ads_truth:proposed") or []
    early = next(p for p in prop if p["id"] == "attendance:early call")
    assert "999s call" in early["ask"] and "before the scheduled date" in early["ask"]
    # idempotent re-run: verified entries skipped, no duplicate cards
    out2 = ads_truth.show_verification_pass()
    prop2 = kv_store.get("ads_truth:proposed") or []
    assert len([p for p in prop2 if p["kind"] == "attendance"]) == \
           len([p for p in prop if p["kind"] == "attendance"])


def test_cancelled_appointment_never_derives_show():
    """The NOT-A-SHOW tier is enforced at derivation (event_sweep): kept statuses
    only. Structural: the sweep's show derivation is gated on _APPT_KEPT."""
    import ads_truth
    src = open(os.path.join(os.path.dirname(__file__), "..", "ads_truth.py")).read()
    seg = src.split("def event_sweep")[1].split("def ")[0]
    assert "status in _APPT_KEPT" in seg
    assert "cancelled" not in ads_truth._APPT_KEPT and "noshow" not in ads_truth._APPT_KEPT


def test_confirm_attendance_command():
    _reset()
    _seed_show("maybe guy", "unverified")
    import ads_truth
    import kv_store
    kv_store.put("ads_truth:proposed", [{"id": "attendance:maybe guy",
                                         "kind": "attendance", "close": "maybe guy"}])
    r, h = ads_truth.handle_confirm_attendance("confirm attendance for maybe")
    assert h and "VERIFIED" in r
    store = RES.derived_dates()
    assert store["maybe guy"]["show_date"]["verification"]["via"] == "show:rydel-confirmed"
    assert not any(p["id"] == "attendance:maybe guy"
                   for p in kv_store.get("ads_truth:proposed") or [])
    assert ads_truth.handle_confirm_attendance("hello")[1] is False
