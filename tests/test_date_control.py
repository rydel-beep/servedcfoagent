"""
tests/test_date_control.py — THE META-STYLE DATE CONTROL (#133), clock-honest.

The range picker is a WINDOW PARAMETER over the one engine — never a second
aggregation path. Under test:
- ?range validation: strict shape, friendly refusals (start>end, future start),
  future-end CLAMP to today_sydney with the note, single-day ranges.
- ?clock declares the question (activity ⇄ cohort; ?basis stays as the alias);
  the payload always echoes the active clock.
- CLOCK DIFFERENCE IS REAL: for the same box the two clocks answer different
  questions and produce different numbers, each matching its D2 definition —
  if they were identical the param isn't wired.
- Date math: Sydney-day boundaries inclusive, a range spanning the Oct 2026
  AEST→AEDT transition, boundary rows, I17 on custom ranges × both clocks.
- Launch honesty: a box entirely before an ad's launch reads "not yet
  launched", never a real-looking zero row.
- The F12 taint class: a hostile ?range= value is REFUSED (fixed message,
  input never echoed into any payload).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attribution_engine as eng
from tests.test_attribution import HDR, RES_A, contact, resolver, row
from tests.test_ads_dashboard import _client

TODAY = None  # resolved live via today_sydney in route tests


def _mini_world(w0, w1, basis):
    """One creative; one lead that ARRIVED before the box and CLOSED inside it;
    one lead that ARRIVED inside the box and CLOSED after it. The clocks MUST
    disagree on this world (D2)."""
    rows = [HDR,
            row("Early Arrival", "ea@x.com", input_date="2026-06-01",
                closer="won", close_date="2026-07-10", contract="9000", cash="4000"),
            row("Late Closer", "lc@x.com", input_date="2026-07-08",
                closer="won", close_date="2026-09-15", contract="7000", cash="2000")]
    contacts = [contact("c1", "ea@x.com", "Early Arrival"),
                contact("c2", "lc@x.com", "Late Closer")]
    return eng.compute_from_inputs(rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}),
                                   w0, w1, basis=basis)


# ── the clock-difference proof (D2 wired end to end) ─────────────────────────

def test_same_box_different_clocks_different_numbers():
    w0, w1 = dt.date(2026, 7, 5), dt.date(2026, 7, 11)     # a 7-day box
    act = _mini_world(w0, w1, "activity")
    coh = _mini_world(w0, w1, "cohort")
    a = next(c for c in act["creatives"] if c["creative_key"] == "120000000000000001")
    c = next(x for x in coh["creatives"] if x["creative_key"] == "120000000000000001")
    # ACTIVITY: the close that HAPPENED in the box counts (lead arrived earlier,
    # annotated ↤); the box's arrival hasn't closed IN the box → 1 close.
    assert a["closes"] == 1 and a["earlier_closes"] == 1
    assert a["cash"] == 4000.0
    # COHORT: the box's arrival owns everything that later happened to it → the
    # September close counts; the earlier arrival is not in this cohort → 1 close
    # but a DIFFERENT deal and different cash.
    assert c["closes"] == 1
    assert c["cash"] == 2000.0
    # leads are clock-stable (arrival IS the cohort event)
    assert a["leads"] == c["leads"] == 1
    # the two clocks disagree where D2 says they must
    assert a["cash"] != c["cash"]
    assert {d["name"] for d in a["deals"]} == {"Early Arrival"}
    assert {d["name"] for d in c["deals"]} == {"Late Closer"}


def test_single_day_range_counts_that_day_only():
    d = dt.date(2026, 7, 8)
    r = _mini_world(d, d, "cohort")
    assert r["window"]["days"] == 1
    c = next(x for x in r["creatives"] if x["creative_key"] == "120000000000000001")
    assert c["leads"] == 1                       # Late Closer arrived exactly 07-08
    assert c["closes"] == 1                      # cohort: its later close belongs to it


def test_range_spanning_oct_2026_sydney_dst_transition():
    """AEDT begins 2026-10-04 in Sydney. Boundaries are calendar days — a lead on
    every day of the box counts exactly once; the box width is unaffected."""
    w0, w1 = dt.date(2026, 10, 2), dt.date(2026, 10, 6)
    rows = [HDR] + [row(f"P{i}", f"p{i}@x.com", input_date=f"2026-10-0{i}")
                    for i in range(2, 7)]
    contacts = [contact(f"c{i}", f"p{i}@x.com", f"P{i}") for i in range(2, 7)]
    r = eng.compute_from_inputs(rows, contacts, {},
                                resolver({"120000000000000001": RES_A}), w0, w1)
    assert r["window"]["days"] == 5
    c = next(x for x in r["creatives"] if x["creative_key"] == "120000000000000001")
    assert c["leads"] == 5                       # incl. BOTH boundary days
    # boundary exclusivity: a day outside either edge does not leak in
    r2 = eng.compute_from_inputs(rows, contacts, {},
                                 resolver({"120000000000000001": RES_A}),
                                 dt.date(2026, 10, 3), dt.date(2026, 10, 5))
    c2 = next(x for x in r2["creatives"] if x["creative_key"] == "120000000000000001")
    assert c2["leads"] == 3


def test_i17_holds_on_custom_ranges_both_clocks():
    for w0, w1 in ((dt.date(2026, 7, 5), dt.date(2026, 7, 11)),
                   (dt.date(2026, 7, 8), dt.date(2026, 7, 8)),
                   (dt.date(2026, 6, 1), dt.date(2026, 9, 30))):
        for basis in ("cohort", "activity"):
            r = _mini_world(w0, w1, basis)
            for c in r["creatives"]:
                for m in ("leads", "qualified", "reached", "sets", "shows", "closes",
                          "earlier_closes", "earlier_sets", "undated_sets"):
                    assert len((c.get("members") or {}).get(m) or []) == (c.get(m) or 0), \
                        f"{w0}..{w1} {basis} {c['creative_key']} {m}"


# ── route-level: validation, clamps, refusals, echo ──────────────────────────

def _mock_board(monkeypatch, capture):
    def fake_serve(days, start, end, basis, force, market=None):
        capture.update({"days": days, "start": start, "end": end, "basis": basis})
        return {"window": {"start": start, "end": end,
                           "days": days if not start else None},
                "basis": basis, "scoreboard": {"rows": []}, "stale": False}
    monkeypatch.setattr("dashboard.ads._serve_board", fake_serve, raising=True)


def test_range_param_reaches_engine_and_clock_echoes(monkeypatch):
    cap = {}
    _mock_board(monkeypatch, cap)
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    r = c.get("/ads/api/board?range=2026-07-01..2026-07-07&clock=activity")
    assert r.status_code == 200
    assert cap["start"] == "2026-07-01" and cap["end"] == "2026-07-07"
    assert cap["basis"] == "activity"
    assert r.get_json()["clock"] == "activity"   # the active clock, never implicit


def test_range_refusals_are_friendly_and_never_echo_input(monkeypatch):
    cap = {}
    _mock_board(monkeypatch, cap)
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    # F12 taint class: hostile values are refused with the FIXED message
    for bad in ("<script>alert(1)</script>", "2026-07-01..<img src=x>",
                "1;DROP TABLE", "2026-13-45..2026-07-01"):
        r = c.get("/ads/api/board", query_string={"range": bad})
        assert r.status_code == 400, bad
        body = r.get_data(as_text=True)
        assert "<script>" not in body and "img src" not in body and "DROP" not in body
    # start > end → refused with the reason
    r = c.get("/ads/api/board?range=2026-07-09..2026-07-01")
    assert r.status_code == 400 and "swap" in r.get_json()["error"]
    # entirely-future range → refused honestly
    from helpers import today_sydney
    fut = str(today_sydney() + dt.timedelta(days=5))
    r = c.get(f"/ads/api/board?range={fut}..{fut}")
    assert r.status_code == 400 and "future" in r.get_json()["error"]


def test_future_end_clamped_to_sydney_today(monkeypatch):
    cap = {}
    _mock_board(monkeypatch, cap)
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    from helpers import today_sydney
    today = today_sydney()
    r = c.get(f"/ads/api/board?range={today - dt.timedelta(days=3)}.."
              f"{today + dt.timedelta(days=4)}")
    assert r.status_code == 200
    assert cap["end"] == str(today)              # clamped, not refused
    assert "clamped to today" in (r.get_json().get("range_note") or "")


def test_single_day_url_form(monkeypatch):
    cap = {}
    _mock_board(monkeypatch, cap)
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    r = c.get("/ads/api/board?range=2026-07-08")
    assert r.status_code == 200
    assert cap["start"] == "2026-07-08" and cap["end"] == "2026-07-08"


def test_roster_route_inherits_range_and_clock(monkeypatch):
    cap = {}

    def fake_build(**kw):
        cap.update(kw)
        return {"people": [], "count": 0, "i17": {"ok": True}, "basis": kw.get("basis")}
    monkeypatch.setattr("roster_engine.build", fake_build, raising=True)
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    r = c.get("/ads/api/roster?range=2026-07-01..2026-07-07&clock=activity"
              "&level=creative&key=k1&metric=closes")
    assert r.status_code == 200
    assert cap["start"] == "2026-07-01" and cap["end"] == "2026-07-07"
    assert cap["basis"] == "activity"
    assert r.get_json()["clock"] == "activity"


def test_range_routes_are_auth_locked(monkeypatch):
    c = _client(monkeypatch)                     # no login
    for path in ("/ads/api/board?range=2026-07-01..2026-07-07",
                 "/ads/api/roster?range=2026-07-01..2026-07-07&key=k&metric=leads",
                 "/ads/api/dossier?range=2026-07-01..2026-07-07&creative=k"):
        assert c.get(path).status_code in (302, 401), path


# ── launch honesty under a range (dossier notes) ─────────────────────────────

def test_dossier_before_launch_is_honest_not_zero(monkeypatch):
    from tests.test_ads_dashboard import _fake_result
    result = _fake_result()
    LIN = {"launch": "2026-07-20", "launch_approx": False, "active_days": 5,
           "calendar_days": 21, "status": "ACTIVE", "created_time": None,
           "scheduled_start": None, "source": "meta:insights", "degraded": None}
    for cr in result["creatives"]:
        cr["lineage"] = LIN if cr["tier"] == "ad" else None
    key = next(cr["creative_key"] for cr in result["creatives"] if cr["tier"] == "ad")

    def fake_load(days=30, start=None, end=None, basis="cohort", market=None):
        r = dict(result)
        r["window"] = {"start": start or "2026-07-01", "end": end or "2026-07-31",
                       "days": 31}
        return r, {"served_from": "engine", "stale": False,
                   "stale_age_s": None, "stale_reason": None}
    monkeypatch.setattr("roster_engine.load_result", fake_load, raising=True)
    monkeypatch.setattr("roster_engine.build",
                        lambda **kw: {"people": [], "i17": {"ok": True}}, raising=True)
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    # box entirely BEFORE launch → "not yet launched", never a real-looking 0
    d = c.get(f"/ads/api/dossier?range=2026-07-01..2026-07-10&creative={key}").get_json()
    assert "not yet launched" in (d.get("lineage_window_note") or "")
    # box straddling the launch → the pre-launch portion is stated
    d2 = c.get(f"/ads/api/dossier?range=2026-07-15..2026-07-25&creative={key}").get_json()
    assert "pre-date launch" in (d2.get("lineage_window_note") or "")
    # box after launch → no note needed
    d3 = c.get(f"/ads/api/dossier?range=2026-07-21..2026-07-28&creative={key}").get_json()
    assert d3.get("lineage_window_note") is None


# ── §2.4: Meta dead under a CUSTOM RANGE — sourced cells degrade, funnel lives ─

def test_meta_dead_under_custom_range_funnel_stays_live(monkeypatch):
    """Mock insights dead for an arbitrary box: the engine still counts the
    tracker funnel (leads/closes live), the payload carries the Meta degradation
    (sourced/hybrid cells render DEGRADED client-side, F5 machinery), and ok is
    False — never a plausible $0."""
    import attribution_join, meta_entities, leads_view, meta_spend
    monkeypatch.setattr(attribution_join, "sync_contacts", lambda: {"at": None, "total": 0})
    monkeypatch.setattr(attribution_join, "load_contacts",
                        lambda: [contact("c1", "ea@x.com", "Early Arrival")])
    monkeypatch.setattr(attribution_join, "resolve_ref",
                        lambda ref, kind, **kw: RES_A)
    monkeypatch.setattr(meta_entities, "refresh_entity_map",
                        lambda force=False: {"ads": {}, "extras": {}, "degraded": []})
    monkeypatch.setattr(meta_entities, "refresh_ad_spend_daily", lambda: {})
    monkeypatch.setattr(meta_entities, "spend_by_ad_in_range",
                        lambda s, e: {"ads": {}, "source": None,
                                      "degraded": [{"metric": "meta_ad_spend_range",
                                                    "reason": "Meta API 401 (test)"}]})
    monkeypatch.setattr(meta_spend, "spend_in_range",
                        lambda s, e: (_ for _ in ()).throw(RuntimeError("Meta dead")))
    monkeypatch.setattr(eng, "_tracker_rows_clean",
                        lambda: [HDR, row("Early Arrival", "ea@x.com",
                                          input_date="2026-07-06", closer="won",
                                          close_date="2026-07-10", contract="9000",
                                          cash="4000")])
    monkeypatch.setattr(leads_view, "count_leads", lambda w0, w1: {"count": 1})
    r = eng.compute(start="2026-07-05", end="2026-07-11", basis="activity", force=True)
    metrics = [d.get("metric") for d in r["degraded"]]
    assert "meta_ad_spend_range" in metrics       # the range's spend source is dead — stated
    assert r["ok"] is False
    c = next(x for x in r["creatives"] if x["creative_key"] == "120000000000000001")
    assert c["leads"] == 1 and c["closes"] == 1   # engine funnel LIVE despite dead Meta
    assert c["cash"] == 4000.0
    assert c["spend"] == 0.0                      # no invented spend — the DEGRADED chip
                                                  # (not this 0) is what the UI renders,
                                                  # test_js_renders_degraded_chip_never_zero
