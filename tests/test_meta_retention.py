"""
tests/test_meta_retention.py — the #3018 boundary fix (DECISIONS #138).

The clamp/chunk/scope builder makes #3018 structurally impossible; degradation
is per-(source×range) so a failed all-time pull leaves 60d cells live; the
buckets are the permanent archive (a captured day survives Meta's window
rolling off). The F5 loudness for GENUINE failures must survive untouched.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import meta_range

TODAY = dt.date(2026, 8, 10)


# ── the rolling floor + clamp ────────────────────────────────────────────────

def test_floor_is_calendar_37_months_plus_margin_and_rolls():
    # empirically pinned: the edge is calendar-37-months; margin sits inside it
    f = meta_range.api_floor(TODAY)
    assert f == dt.date(2023, 7, 13)                      # 2023-07-10 + 3-day margin
    # it ROLLS: tomorrow's floor is one day later (never cached across days)
    assert meta_range.api_floor(TODAY + dt.timedelta(days=1)) == f + dt.timedelta(days=1)


def test_clamp_truncates_below_floor_and_discloses():
    c = meta_range.clamp("2016-01-01", str(TODAY), today=TODAY)
    assert c["start"] == "2023-07-13"                     # clamped up to the floor
    assert c["clamped_from"] == "2016-01-01"              # the original is disclosed
    assert c["empty"] is False


def test_clamp_noop_for_in_window_range():
    c = meta_range.clamp("2026-06-01", "2026-06-30", today=TODAY)
    assert c["start"] == "2026-06-01" and c["clamped_from"] is None


def test_clamp_scopes_per_ad_to_launch():
    # an ad born 2026-07-01 never references 2023 even on an all-time request
    c = meta_range.clamp("2016-01-01", str(TODAY), ad_launch="2026-07-01", today=TODAY)
    assert c["start"] == "2026-07-01"


def test_clamp_future_end_and_empty_range():
    c = meta_range.clamp("2026-06-01", "2027-01-01", today=TODAY)
    assert c["end"] == str(TODAY)                         # future end clamped to today
    e = meta_range.clamp("2019-01-01", "2020-01-01", today=TODAY)
    assert e["empty"] is True                             # entirely pre-floor → honest empty


def test_chunks_split_and_cover_inclusive_no_gaps_no_overlap():
    cs = meta_range.chunks("2026-01-01", "2026-06-30", max_days=90)
    assert cs[0][0] == "2026-01-01" and cs[-1][1] == "2026-06-30"
    # contiguous: each chunk starts the day after the previous ends
    for (a_s, a_e), (b_s, b_e) in zip(cs, cs[1:]):
        assert dt.date.fromisoformat(b_s) == dt.date.fromisoformat(a_e) + dt.timedelta(days=1)
    # single-day range → one chunk
    assert meta_range.chunks("2026-03-05", "2026-03-05") == [("2026-03-05", "2026-03-05")]


def test_chunks_span_dst_transition_by_calendar_days():
    # AEDT begins 2026-10-04 — chunks are calendar-day strings, immune to the shift
    cs = meta_range.chunks("2026-09-20", "2026-10-20", max_days=90)
    assert cs == [("2026-09-20", "2026-10-20")]           # one chunk, exact edges


# ── the builder: #3018 impossible, per-chunk isolation ───────────────────────

def _fake_fetch(script):
    """script: {(since,until): rows|Exception}. Returns a fetch_all(path,params)."""
    import json as _j
    calls = []

    def fetch(path, params):
        tr = _j.loads(params["time_range"])
        calls.append((tr["since"], tr["until"]))
        v = script.get((tr["since"], tr["until"]), [])
        if isinstance(v, Exception):
            return None, str(v)
        return v, None
    fetch.calls = calls
    return fetch


def test_builder_never_requests_before_the_floor():
    fetch = _fake_fetch({})
    meta_range.insights("acct/insights", {}, "2016-01-01", str(TODAY), fetch,
                        source="test", today=TODAY)
    # every chunk's `since` is >= the floor — #3018 cannot occur
    for since, _until in fetch.calls:
        assert since >= "2023-07-13", since


def test_builder_one_chunk_failure_degrades_only_its_days():
    # 2 chunks; fail the first, succeed the second → only the first's range degrades
    fetch = _fake_fetch({
        ("2026-01-01", "2026-03-31"): RuntimeError("500 transient"),
        ("2026-04-01", "2026-06-29"): [{"date_start": "2026-05-01", "spend": "9"}],
    })
    r = meta_range.insights("acct/insights", {}, "2026-01-01", "2026-06-29", fetch,
                            source="meta_spend_account", today=TODAY)
    assert len(r["degraded"]) == 1
    assert r["degraded"][0]["range"] == "2026-01-01..2026-03-31"
    assert r["degraded"][0]["source"] == "meta_spend_account"
    assert r["rows"] == [{"date_start": "2026-05-01", "spend": "9"}]   # healthy chunk survives


# ── degradation scoping: all-time fails, window lives (the witnessed bug) ─────

def test_dossier_scopes_degradation_per_leg(monkeypatch):
    import attribution_engine as eng
    from tests.test_ads_dashboard import _client, _fake_result
    win = _fake_result(); win["window"] = {"start": "2026-06-11", "end": "2026-08-10", "days": 60}
    win["degraded"] = []                                  # 60d data healthy
    alltime = _fake_result(); alltime["window"] = {"start": "2016-08-11", "end": "2026-08-10", "days": 3650}
    alltime["degraded"] = [{"metric": "meta_spend_range", "source": "meta_spend_account",
                            "range": "2016..2023", "reason": "clamped/failed"}]
    alltime["spend_clamp_note"] = "Meta spend via API from 2023-07-13; earlier from archive"

    def fake_compute(days=30, start=None, end=None, basis="cohort", market=None, **kw):
        return alltime if (days and int(days) >= 3650) else win
    monkeypatch.setattr(eng, "compute", fake_compute, raising=True)
    monkeypatch.setattr("roster_engine.load_result",
                        lambda days=30, start=None, end=None, **k: (
                            fake_compute(days=days, start=start, end=end),
                            {"served_from": "engine", "stale": False,
                             "stale_age_s": None, "stale_reason": None}),
                        raising=True)
    monkeypatch.setattr("roster_engine.build",
                        lambda **kw: {"people": [], "i17": {"ok": True}}, raising=True)
    key = next(c["creative_key"] for c in win["creatives"] if c["tier"] == "ad")
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    d = c.get(f"/ads/api/dossier?days=60&creative={key}").get_json()
    # the WINDOW leg carries no spend degradation; the ALL-TIME leg does
    assert (d["econ_window"].get("degraded") or []) == []
    assert any(x.get("metric") == "meta_spend_range" for x in d["econ_all_time"]["degraded"])
    assert "from 2023-07-13" in (d["econ_all_time"].get("clamp_note") or "")


def test_js_dossier_reads_the_legs_own_degraded_not_the_merged_list():
    js = open(os.path.join(os.path.dirname(__file__), "..",
                           "dashboard", "static", "js", "adsapp.js")).read()
    seg = js.split("function econRow(label, e)")[1].split("function ")[0]
    assert "e.degraded" in seg                            # the leg's own list
    assert "dmoney('spend', e.spend, ld)" in seg          # scoped, not d.degraded
    assert "e.clamp_note" in seg                          # the named limit renders


# ── F5 regression: a GENUINE unnameable failure still badges DEGRADED ─────────

def test_f5_genuine_failure_still_loud():
    # a chunk that fails with a NON-#3018 error still surfaces as degraded (loud)
    fetch = _fake_fetch({("2026-07-01", "2026-07-31"): RuntimeError("HTTP 500 upstream")})
    r = meta_range.insights("acct/insights", {}, "2026-07-01", "2026-07-31", fetch,
                            source="meta_spend_account", today=TODAY)
    assert r["degraded"] and "500" in r["degraded"][0]["cause"]
    assert r["rows"] == []                                # no fabricated $0 — loud absence


# ── archive semantics: authoritative + idempotent ───────────────────────────

def test_spend_in_range_sums_archive_past_the_floor(monkeypatch):
    import meta_spend
    # the store holds a day BEFORE today's floor (captured earlier when in-window)
    monkeypatch.setattr(meta_spend, "_load_store",
                        lambda: {"2023-05-01": {"spend": 42.0}, "2026-08-01": {"spend": 8.0}})
    monkeypatch.setattr(meta_spend, "today_sydney", lambda: TODAY)
    # PIN THE FLOOR'S CLOCK TOO: spend_in_range computes the floor via
    # meta_range.api_floor() → the REAL today_sydney — unpinned, the expected
    # floor date rolls daily and this test rots on the calendar (it failed
    # 2026-08-12 expecting the 2026-08-10 floor). Same TODAY everywhere.
    import meta_range as MR
    monkeypatch.setattr(MR, "api_floor",
                        lambda today=None: MR._cal_minus_months(TODAY, MR._RETENTION_MONTHS)
                        + __import__("datetime").timedelta(days=MR._SAFETY_MARGIN_DAYS))
    monkeypatch.setattr(meta_spend, "META_ACCESS_TOKEN", "")   # no live fetch
    monkeypatch.setattr(meta_spend, "META_AD_ACCOUNT_ID", "")
    r = meta_spend.spend_in_range("2023-01-01", "2026-08-10")
    # 2023-05-01 is past the API floor but WE archived it → it counts
    assert r["spend"] == 50.0
    assert r["clamped_from"] == "2023-01-01"                  # request reached before floor → disclosed
    assert "from 2023-07-13" in (r["clamp_note"] or "")
