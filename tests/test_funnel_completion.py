"""tests/test_funnel_completion.py — DECISIONS #128: the date-resolution engine
(derive-never-invent, journal schema, supersession + disagreement), the engine
merge with derived_placed recon terms, tab parity (the Reached "—" regression),
conflicting-candidates → PROPOSED, lane-lag ageing, read-only externals."""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribution_engine as eng
import resolution as RES
from tests.test_attribution import HDR, RES_A, W0, W1, contact, resolver, row


def _reset():
    import kv_store
    for k in ("derived:dates", "ads_truth:flags", "integrity:autofix_log",
              "ads_truth:proposed", "ghl:appt_cache"):
        kv_store.put(k, None)


def _compute(rows, contacts, **kw):
    return eng.compute_from_inputs([HDR] + rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}),
                                   W0, W1, **kw)


# ── the derivation contract (I12) ────────────────────────────────────────────

def test_derivation_without_evidence_is_rejected():
    _reset()
    assert RES.record_derived_date("x y", "close_date", "2026-07-01",
                                   "derived:stripe", {}) is False   # empty evidence
    assert RES.record_derived_date("x y", "badfield", "2026-07-01",
                                   "derived:stripe", {"id": 1}) is False
    assert RES.derived_dates() == {}


def test_derivation_idempotent_no_churn():
    _reset()
    import kv_store
    assert RES.record_derived_date("a b", "set_date", "2026-07-10",
                                   "derived:ghl-appt", {"appointment_id": "ap1"})
    j1 = len(kv_store.get("integrity:autofix_log") or [])
    assert RES.record_derived_date("a b", "set_date", "2026-07-10",
                                   "derived:ghl-appt", {"appointment_id": "ap1"})
    j2 = len(kv_store.get("integrity:autofix_log") or [])
    assert j1 == j2                                    # re-run = zero re-derivation churn
    assert len(RES.derived_dates()["a b"]) == 1


def test_source_fill_supersedes_and_disagreement_surfaces():
    _reset()
    import kv_store
    RES.record_derived_date("a b", "close_date", "2026-07-10",
                            "derived:stripe", {"charge": "ch_1"})
    out = RES.supersede_derived("a b", "close_date", "2026-07-10")
    assert out["agrees"] is True
    assert "a b" not in RES.derived_dates()            # retired, journaled
    # a DISAGREEING source fill surfaces — never silently resolved
    RES.record_derived_date("c d", "close_date", "2026-07-10",
                            "derived:stripe", {"charge": "ch_2"})
    out = RES.supersede_derived("c d", "close_date", "2026-07-14")
    assert out["agrees"] is False
    flags = kv_store.get("ads_truth:flags") or []
    assert any("disagreement" in f["reason"] for f in flags)


# ── the engine merge + recon terms ───────────────────────────────────────────

def test_derived_input_date_windows_the_lead_with_recon_term():
    _reset()
    r_ = row("No Input", "n@x.com", input_date="", closer="won",
             close_date="2026-07-20", contract="9000", cash="4000")
    RES.record_derived_date("no input", "input_date", "2026-07-10",
                            "derived:ghl-contact-created", {"contact_id": "c1"})
    out = _compute([r_], [contact("c1", "n@x.com", "No Input")],
                   canonical={"leads": 0, "closes": 0, "cash": 0.0})
    assert out["totals"]["leads"] == 1                  # windowable NOW, labelled
    lv = next(v for v in out["rows"] if v["name"] == "No Input")
    assert lv["derived_dates"]["input_date"] == "derived:ghl-contact-created"
    ck = out["reconciliation"]["checks"]
    # the canonical (raw authority) sees 0 — the derived term balances it honestly
    assert ck["leads"]["derived_placed"] == 1 and ck["leads"]["ok"]
    assert ck["closes"]["derived_placed"] == 1 and ck["closes"]["ok"]
    assert ck["cash"]["derived_placed_cash"] == 4000.0 and ck["cash"]["ok"]


def test_derived_close_date_windows_on_activity_clock():
    _reset()
    r_ = row("Blank Close", "b@x.com", closer="won", close_date="",
             contract="8000", cash="3000")
    RES.record_derived_date("blank close", "close_date", "2026-07-15",
                            "derived:stripe (Rydel-confirmed)", {"charge": "ch_9"})
    out = _compute([r_], [contact("c1", "b@x.com", "Blank Close")], basis="activity")
    c = next(x for x in out["creatives"] if x["closes"] == 1)
    assert c["deals"][0]["close_date"] == "2026-07-15"
    assert c["deals"][0]["derived"]["close_date"].startswith("derived:stripe")


def test_derived_set_date_populates_activity_sets():
    _reset()
    r_ = row("Dateless Set", "d@x.com", setter="set", show="Showed")
    r_[18] = ""                                        # the 122-strong class
    RES.record_derived_date("dateless set", "set_date", "2026-07-12",
                            "derived:ghl-appt", {"appointment_id": "ap7"})
    out = _compute([r_], [contact("c1", "d@x.com", "Dateless Set")], basis="activity")
    c = next(x for x in out["creatives"] if x["leads"] == 1)
    assert c["sets"] == 1 and c["shows"] == 1          # the Failure-2 zeros, cured
    lv = next(v for v in out["rows"] if v["name"] == "Dateless Set")
    assert lv["derived_dates"]["set_date"] == "derived:ghl-appt"
    # tracker date, when it lands, is never double-counted (one lead, one set)
    assert c["sets"] <= c["leads"]


def test_tracker_date_beats_derived():
    _reset()
    RES.record_derived_date("has date", "set_date", "2026-07-01",
                            "derived:ghl-appt", {"appointment_id": "ap8"})
    r_ = row("Has Date", "h@x.com", setter="set", show="Showed")   # set_date 2026-07-11
    out = _compute([r_], [contact("c1", "h@x.com", "Has Date")], basis="activity")
    lv = next(v for v in out["rows"] if v["name"] == "Has Date")
    assert lv["set_date"] == "2026-07-11"              # authority wins
    assert not (lv.get("derived_dates") or {}).get("set_date")


# ── tab parity: the Reached "—" regression, forever ──────────────────────────

def test_reached_on_names_tab_equals_engine_grouped_value():
    _reset()
    rows = [row("Fung Kwok", "f@x.com", setter="no pick up", show=""),
            row("Reached One", "r@x.com", setter="set", show="Showed")]
    r = _compute(rows, [contact("c1", "f@x.com", "Fung Kwok"),
                        contact("c2", "r@x.com", "Reached One")])
    import attribution_verdicts as AV
    lad = AV.ladder(r, 3.0)
    name_rows = lad.get("name") or []
    assert name_rows, "ladder name level exists"
    assert sum(a.get("reached") or 0 for a in name_rows) == \
           sum(c.get("reached") or 0 for c in r["creatives"])
    for a in name_rows:
        assert "reached" in a                           # never "—" without a reason


# ── conflicting candidates → PROPOSED, never AUTO ────────────────────────────

def test_multiple_appointments_land_proposed(monkeypatch):
    _reset()
    import ads_truth
    import kv_store
    monkeypatch.setattr(ads_truth, "_cached_appointments", lambda cid: [
        {"id": "ap1", "dateAdded": "2026-07-01T10:00:00", "startTime": "2026-07-03T11:00:00",
         "appointmentStatus": "confirmed"},
        {"id": "ap2", "dateAdded": "2026-07-05T10:00:00", "startTime": "2026-07-08T11:00:00",
         "appointmentStatus": "confirmed"}])
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: {
        "rows": [{"name": "Multi Appt", "set": True, "set_date": None}]})
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts",
                        lambda: [{"id": "cm1", "name": "Multi Appt"}])
    out = ads_truth.event_sweep()
    assert out["derived_set_dates"] == 0 and out["proposed_multi"] == 1
    prop = kv_store.get("ads_truth:proposed") or []
    assert any(p["kind"] == "set_date_candidates" and len(p["candidates"]) == 2
               for p in prop)
    assert RES.derived_dates() == {}                    # nothing AUTO'd


def test_single_appointment_derives_booked_date(monkeypatch):
    _reset()
    import ads_truth
    monkeypatch.setattr(ads_truth, "_cached_appointments", lambda cid: [
        {"id": "ap1", "dateAdded": "2026-07-02T09:00:00", "startTime": "2026-07-04T11:00:00",
         "appointmentStatus": "confirmed"}])
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: {
        "rows": [{"name": "Solo Appt", "set": True, "set_date": None}]})
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts",
                        lambda: [{"id": "cs1", "name": "Solo Appt"}])
    out = ads_truth.event_sweep()
    assert out["derived_set_dates"] == 1
    d = RES.derived_dates()["solo appt"]
    assert d["set_date"]["date"] == "2026-07-02"        # BOOKED date (the convention)
    assert d["show_date"]["date"] == "2026-07-04"       # SCHEDULED date + kept status


def test_apply_date_card_handler(monkeypatch):
    _reset()
    import kv_store
    kv_store.put("integrity:proposed_fixes", {"as_of": "2026-08-08", "cards": [
        {"kind": "P1_close_date_candidate", "name": "Ella Ponce",
         "candidates": [{"date": "2026-02-18", "source": "Stripe first payment"}],
         "id": "pfix:close_date:ella ponce"}]})
    r, h = RES.handle_apply_date_card("apply the date card for ella")
    assert h and "2026-02-18" in r and "Piolo item stays" in r
    assert RES.derived_dates()["ella ponce"]["close_date"]["provenance"].startswith("derived:stripe")


def test_lane_lag_ageing_items(monkeypatch):
    import close_integrity as CI
    monkeypatch.setattr(CI, "_tracker_won_rows", lambda: [
        {"name": "Aged Deal", "email": "", "close_date": dt.date(2026, 7, 20),
         "close_raw": "20/7", "input_date": dt.date(2026, 7, 1),
         "contract": 9000.0, "cash": 3000.0}])
    monkeypatch.setattr(CI, "_ghl_won_in_window", lambda w0, w1: (0, 5))
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    import stripe_reconcile
    monkeypatch.setattr(stripe_reconcile, "reconcile_stripe_tracker",
                        lambda: {"stripe_reconciliation": {}})
    import helpers
    monkeypatch.setattr(helpers, "today_sydney", lambda: dt.date(2026, 8, 8))
    m = CI.run_matrix(30)
    aged = [d for d in m["disagreements"] if d["kind"] == "ghl_stage_lag_deal"]
    assert len(aged) == 1 and "19 day(s) ago" in aged[0]["detail"]
    assert aged[0]["deal_name"] == "Aged Deal"          # drillable (feed deep-link)


def test_read_only_externals():
    for mod in ("resolution.py", "ads_truth.py"):
        src = open(os.path.join(os.path.dirname(__file__), "..", mod)).read()
        for verb in ("requests.post", "requests.put", "requests.delete", "requests.patch"):
            assert verb not in src, (mod, verb)
