"""tests/test_ads_truth.py — ADS TRUTH regression suite (DECISIONS #126).
Named for the diagnosed cases: A (clock inheritance), B (activity annotations),
C→Gate 2 (reached tier), D (tier partition). Plus I8/I10/I11/I13 adversarials,
the spine provenance mechanism, and the loud-failure sweep rule."""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribution_engine as eng
import pytest
from tests.test_attribution import HDR, RES_A, W0, W1, contact, resolver, row


def _compute(rows, contacts, basis="cohort", w0=W0, w1=W1):
    # compute_from_inputs takes RAW tracker rows (header + data) and parses inside
    return eng.compute_from_inputs([HDR] + rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}),
                                   w0, w1, basis=basis)


# ── CASE A class: clock purity (I11) ─────────────────────────────────────────

def test_case_a_cross_clock_math_refused():
    """Adversarial: combining results from two clocks must RAISE, never blend."""
    rows = [row("A Lead", "a@x.com")]
    r_coh = _compute(rows, [contact("c1", "a@x.com", "A Lead")], basis="cohort")
    r_act = _compute(rows, [contact("c1", "a@x.com", "A Lead")], basis="activity")
    with pytest.raises(ValueError):
        eng.assert_same_basis(r_coh, r_act)
    assert eng.assert_same_basis(r_coh, r_coh) == "cohort"


def test_case_a_roster_inherits_the_cell_clock():
    """The drill computes the clicked cell's basis — the exact live bug (5 cells
    at diagnosis) can never come back silently."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "ads.py")).read()
    # the route hands the clicked cell's clock AND market to THE roster engine
    roster_src = src.split("def roster()")[1][:1600]
    assert "basis=_basis_arg(), market=_market_arg()" in roster_src
    # the engine inherits the clock (I11) and states it in the payload
    eng_src = open(os.path.join(os.path.dirname(__file__), "..", "roster_engine.py")).read()
    assert "AE.assert_same_basis(result)" in eng_src
    assert '"clock_note"' in eng_src
    js = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "static",
                           "js", "adsapp.js")).read()
    assert "'&basis=' + encodeURIComponent(state.basis)" in js
    # the bare "mismatch, report this" message class is DEAD — legible cause or nothing
    assert "mismatch, report this" not in js
    assert "I17 DRIFT" in js and "render/engine skew" in js


# ── CASE B class: activity funnel-lag annotations + I8 ───────────────────────

def test_case_b_earlier_set_annotation_not_bare_zero():
    """A close landing in a window whose set happened earlier carries ↤ context
    (earlier_sets/earlier_shows), and I8(activity) stays green."""
    r_ = row("Lucas C", "l@x.com", input_date="2026-06-20", setter="set",
             show="Showed", closer="won", close_date="2026-07-16",
             contract="15000", cash="5170")
    r_[18] = "2026-06-21"     # Set Date BEFORE the July window
    r = _compute([r_], [contact("c1", "l@x.com", "Lucas C")], basis="activity")
    c = next(x for x in r["creatives"] if x["closes"] == 1)
    assert c["sets"] == 0 and c["shows"] == 0          # true on the activity clock
    assert c["earlier_sets"] == 1 and c["earlier_shows"] == 1   # …and explained
    assert c["earlier_closes"] == 1
    assert not c.get("integrity_error")
    # the deal carries its evidence for the drill
    assert c["deals"][0]["set_date"] == "2026-06-21" and c["deals"][0]["show"] is True


def test_case_b_unexplained_zero_sets_close_fails_i8():
    """Adversarial: a close with no in-window events and NO annotation must fail
    I8(activity) loudly — never a bare '0 sets, 1 close' row."""
    r_ = row("Ghost Close", "g@x.com", input_date="2026-07-10", setter="",
             show="", closer="won", close_date="2026-07-16",
             contract="9000", cash="3000")
    r_[18] = ""               # no set, no set date, lead IN window → unexplained
    r = _compute([r_], [contact("c1", "g@x.com", "Ghost Close")], basis="activity")
    c = next(x for x in r["creatives"] if x["closes"] == 1)
    assert "I8(activity)" in (c.get("integrity_error") or "")


def test_case_b_undated_set_annotated_not_red():
    """A set with NO date can't be placed on the activity clock — the row carries
    the ◔ annotation + a hygiene rollup, never an integrity error."""
    r_ = row("Undated Set", "u@x.com", input_date="2026-07-10", setter="set",
             show="Showed", closer="won", close_date="2026-07-16",
             contract="9000", cash="3000")
    r_[18] = ""               # set exists, Set Date blank
    r = _compute([r_], [contact("c1", "u@x.com", "Undated Set")], basis="activity")
    c = next(x for x in r["creatives"] if x["closes"] == 1)
    assert c["undated_sets"] == 1
    assert not c.get("integrity_error")


def test_leads_index_prefers_won_row():
    """The first live sweep's false CRITICALs: duplicate names must never read as
    'no tracker won row' — the index prefers the won row."""
    import ads_truth
    leads = [{"name_norm": "lucas reid", "won": True},
             {"name_norm": "lucas reid", "won": False}]
    assert ads_truth._leads_index(leads)["lucas reid"]["won"] is True
    assert ads_truth._leads_index(list(reversed(leads)))["lucas reid"]["won"] is True


# ── GATE 2 (Case C): the reached tier ────────────────────────────────────────

def test_reached_counts_qualified_with_contact_evidence_only():
    """Fung Kwok's shape: qualified ✓ (fit) reached ✗ (no contact evidence).
    A set/show/won lead is reached; reached ≤ qualified (I8)."""
    rows = [
        row("Fung Kwok", "f@x.com", setter="no pick up", show=""),      # qualified, unreached
        row("Reached One", "r@x.com", setter="set", show="Showed"),     # qualified + set
    ]
    r = _compute(rows, [contact("c1", "f@x.com", "Fung Kwok"),
                        contact("c2", "r@x.com", "Reached One")])
    c = next(x for x in r["creatives"] if x["leads"] == 2)
    assert c["qualified"] == 2 and c["reached"] == 1
    fung = next(v for v in r["rows"] if v["name"] == "Fung Kwok")
    assert fung["qualified"] is True and fung["reached"] is False
    # the scoreboard renders the column
    sb = eng.scoreboard_view(r)
    assert "reached" in sb["columns"]
    assert next(x for x in sb["rows"] if x["leads"] == 2)["reached"] == 1


def test_reached_evidence_cache_marks_lead(monkeypatch):
    """GHL evidence in kv reached:evidence flips an otherwise-unreached qualified
    lead — the sweep populates, the engine only reads."""
    import kv_store
    kv_store.put("reached:evidence", {"c1": {"kind": "ghl-appointment"}})
    try:
        rows = [row("Fung Kwok", "f@x.com", setter="no pick up", show="")]
        r = _compute(rows, [contact("c1", "f@x.com", "Fung Kwok")])
        assert next(v for v in r["rows"] if v["name"] == "Fung Kwok")["reached"] is True
    finally:
        kv_store.put("reached:evidence", {})


# ── CASE D class: tier partition (I10) ───────────────────────────────────────

def test_case_d_two_tier_close_fails_partition():
    crafted = [
        {"creative_key": "A", "deals": [{"name": "Tony Thai", "close_date": "2026-07-20"}]},
        {"creative_key": "B", "deals": [{"name": "Tony Thai", "close_date": "2026-07-20"}]},
    ]
    v = eng.partition_violations(crafted)
    assert len(v) == 1 and v[0]["rows"] == ["A", "B"]
    # same NAME on different dates = two distinct closes (the $3,355 lesson:
    # identical amounts are NOT identity)
    crafted[1]["deals"][0]["close_date"] = "2026-07-21"
    assert eng.partition_violations(crafted) == []


# ── THE SPINE (I9/I12): derived events carry provenance, never merge bare ────

def test_spine_derived_set_counts_with_provenance(monkeypatch):
    import kv_store
    kv_store.put("spine:events", [{"name_norm": "no set lead", "kind": "set",
                                   "provenance": "derived:ghl-appointment",
                                   "evidence": {"appointment_id": "ap1"}}])
    try:
        rows = [row("No Set Lead", "n@x.com", setter="no pick up", show="")]
        r = _compute(rows, [contact("c1", "n@x.com", "No Set Lead")])
        c = next(x for x in r["creatives"] if x["leads"] == 1)
        assert c["sets"] == 1
        assert c["sets_src"] == {"tracker": 0, "derived": 1}   # provenance visible
    finally:
        kv_store.put("spine:events", [])


def test_tracker_set_never_double_counts_with_derived(monkeypatch):
    import kv_store
    kv_store.put("spine:events", [{"name_norm": "has set", "kind": "set",
                                   "provenance": "derived:ghl-appointment"}])
    try:
        rows = [row("Has Set", "h@x.com", setter="set", show="Showed")]
        r = _compute(rows, [contact("c1", "h@x.com", "Has Set")])
        c = next(x for x in r["creatives"] if x["leads"] == 1)
        assert c["sets"] == 1 and c["sets_src"] is None        # tracker wins, no double
    finally:
        kv_store.put("spine:events", [])


# ── I13: one engine per metric (structural) ──────────────────────────────────

def test_i13_single_computation_path():
    src_eng = open(os.path.join(os.path.dirname(__file__), "..",
                                "attribution_engine.py")).read()
    assert src_eng.count("def compute(") == 1
    assert src_eng.count("def compute_from_inputs(") == 1
    ads = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "ads.py")).read()
    # the board layer READS the engine; it never re-derives a metric
    import re as _re
    assert not _re.search(r"\[(['\"])(closes|leads|sets|shows|cash)\1\]\s*[+\-*]\s*", ads)
    # roster counts moved INTO the engine (I17): the payload count is the cell
    # value and len(people) is checked against it — never a second computation
    reng = open(os.path.join(os.path.dirname(__file__), "..", "roster_engine.py")).read()
    assert '"count": cell_value' in reng
    assert 'len(people) == cell_value' in reng


# ── THE SWEEP: loud failure + EDITH accuracy ─────────────────────────────────

def test_sweep_failure_is_loud(monkeypatch):
    import ads_truth
    import kv_store
    kv_store.put("ads_truth:sweep_tick", None)
    kv_store.put("attr:data_quality_flags", [])
    monkeypatch.setattr(ads_truth, "integrity_sweep",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ads_truth.nightly_tick() is False
    assert kv_store.get("ads_truth:sweep_error")["error"] == "boom"
    flags = kv_store.get("attr:data_quality_flags")
    assert any(f["metric"] == "ads_truth_sweep_down" for f in flags)
    # …and EDITH answers honestly while it's down
    r, h = ads_truth.handle_accuracy_command("how accurate is the ad data?")
    assert h and "sweep itself failed" in r
    kv_store.put("ads_truth:sweep_error", None)


def test_edith_accuracy_answers_from_the_table():
    import ads_truth
    import kv_store
    kv_store.put("ads_truth:sweep_error", None)
    kv_store.put("ads_truth:accuracy", [
        {"date": "2026-08-06", "facts_checked": 24, "agreements": 24,
         "disagreements": 1, "invariant_violations": 0,
         "spine": {"T1": 18, "T2": 0, "T3": 0, "T0": 0}},
        {"date": "2026-08-07", "facts_checked": 24, "agreements": 24,
         "disagreements": 0, "invariant_violations": 0,
         "spine": {"T1": 18, "T2": 0, "T3": 0, "T0": 0}}])
    r, h = ads_truth.handle_accuracy_command("can I trust the ad numbers?")
    assert h and "24" in r and "18 tracker" in r and "1 → 0" in r
    assert ads_truth.handle_accuracy_command("hello")[1] is False


def test_reach_rate_flag_fires():
    import attribution_flags as AF
    result = {"totals": {"leads": 20},
              "window": {"days": 30},
              "creatives": [{"label": "Unreachable Ad", "creative_key": "k1",
                             "tier": "ad", "leads": 10, "qualified": 8, "reached": 1,
                             "sets": 0, "shows": 0, "closes": 0, "cash": 0,
                             "spend": 50, "revenue_unknown": 0,
                             "cost_per_lead": 5.0}]}
    out = AF.flags(result)
    assert any(f["kind"] == "qualified_unreachable" for f in out)
