"""
tests/test_rollup_rosters.py — F1 (extreme audit): rollup-backed rosters.
Root cause: the roster/drill path required a live engine result; the engine
cache is 30-min TTL, PER WORKER (×2), per-(window,basis,market) key — so the
COMMON case (other worker, expired TTL, untouched window) was a 5.7–15.8s
engine build against a <500ms drill budget.

Fix under test: the board layer persists an "engine slice" (creatives WITH
their I17 member lists + trimmed view rows) beside every rollup;
roster_engine.load_result serves rosters/dossiers from that slice when the
engine is cold — stale-LABELLED like the grid, background warm kicked.

ISOLATION RULE (the wave prompt): this touches the rollup shape, so grid
consumers are re-run (test_ads_dashboard/test_ads_ux) and I17 is re-swept in
FULL after this fix — see test_i17_full_sweep_on_rollup_path here plus the
suite-wide sweeps.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attribution_engine as eng
import kv_store
import roster_engine
from tests.test_ads_dashboard import _fake_result

MEMBER_METRICS = ("leads", "qualified", "reached", "sets", "shows", "closes")


def _slice_of(result):
    from dashboard.ads import _engine_slice
    return _engine_slice(result)


def _store_rollup(result, basis="cohort", days=30, epoch=None):
    import resolution
    kv_store.put(f"attr:rollup:{basis}:{days}",
                 {"at": time.time(), "epoch": epoch if epoch is not None
                  else resolution.derived_epoch(),
                  "board": {"window": result.get("window")},
                  "engine": _slice_of(result)})


def _fast_enrichment(monkeypatch):
    monkeypatch.setattr(eng, "_tracker_rows_clean", lambda: [])
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])


def test_cold_roster_serves_from_rollup_under_budget(monkeypatch):
    """Engine cold + rollup present → the roster is served from the slice,
    STALE-LABELLED, inside the 500ms budget — the 6s engine build is NOT on
    the serve path (it would blow the timer)."""
    result = _fake_result()
    result["window"] = {"start": "s", "end": "e", "days": 30}
    _store_rollup(result)
    eng._cache.clear()

    def slow_compute(**kw):
        time.sleep(6)          # the old cold path — must never run synchronously
        return result
    monkeypatch.setattr(eng, "compute", slow_compute)
    warm_calls = []
    monkeypatch.setattr(roster_engine, "_warm_async",
                        lambda d, b: warm_calls.append((d, b)))
    _fast_enrichment(monkeypatch)
    t0 = time.perf_counter()
    d = roster_engine.build(days=30, basis="cohort", level="creative",
                            key="120000000000000001", metric="leads")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"cold roster took {elapsed:.2f}s — budget is 500ms"
    assert d["served_from"] == "rollup" and d["stale"] is True
    assert "cold" in d["stale_reason"]
    assert warm_calls == [(30, "cohort")]          # the fresh build was kicked
    assert d["count"] == len(d["people"])          # I17 holds on the rollup path


def test_warm_engine_serves_fresh_never_the_rollup(monkeypatch):
    result = _fake_result()
    result["window"] = {"start": "s", "end": "e", "days": 30}
    _store_rollup(result)
    monkeypatch.setattr(eng, "compute", lambda **kw: result)
    _fast_enrichment(monkeypatch)
    import datetime as dt
    from helpers import today_sydney
    import resolution
    w1 = today_sydney(); w0 = w1 - dt.timedelta(days=29)
    eng._cache[eng.cache_key(w0, w1, "cohort")] = (time.time(), result)
    d = roster_engine.build(days=30, basis="cohort", level="creative",
                            key="120000000000000001", metric="leads")
    assert d["served_from"] == "engine" and d["stale"] is False


def test_epoch_mismatch_states_the_derivation_reason(monkeypatch):
    import resolution
    result = _fake_result()
    result["window"] = {"start": "s", "end": "e", "days": 30}
    _store_rollup(result, epoch=resolution.derived_epoch())
    resolution.bump_derived_epoch("test write")
    eng._cache.clear()
    monkeypatch.setattr(roster_engine, "_warm_async", lambda d, b: None)
    _fast_enrichment(monkeypatch)
    monkeypatch.setattr(eng, "compute",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("cold path ran")))
    d = roster_engine.build(days=30, basis="cohort", level="creative",
                            key="120000000000000001", metric="leads")
    assert d["stale"] is True and "derivation" in d["stale_reason"]


def test_custom_and_market_windows_never_use_the_rollup(monkeypatch):
    """A custom range or market filter has no rollup — those compute directly."""
    result = _fake_result()
    calls = []

    def compute(**kw):
        calls.append(kw)
        return result
    monkeypatch.setattr(eng, "compute", compute)
    r1, m1 = roster_engine.load_result(30, "2026-07-01", "2026-07-31", "cohort", None)
    r2, m2 = roster_engine.load_result(30, None, None, "cohort", "au")
    assert len(calls) == 2
    assert m1["served_from"] == "engine" and m2["served_from"] == "engine"


def test_engine_slice_keeps_members_and_roster_fields():
    result = _fake_result()
    sl = _slice_of(result)
    for c in sl["creatives"]:
        assert "members" in c                       # I17 lists survive the slice
    for v in sl["rows"]:
        for k in ("name", "name_norm", "qualified", "reached", "revenue"):
            assert k in v
        assert "input_date" not in v                # trimmed — size discipline
    assert sl["basis"] == result["basis"]


def test_i17_full_sweep_on_rollup_path(monkeypatch):
    """FULL I17 over the rollup-served result: EVERY metric of EVERY creative row
    — the roster (member list) equals the cell, zero drift. The one thing an F1
    rollup-shape change could break is exactly this equality."""
    result = _fake_result()
    result["window"] = {"start": "s", "end": "e", "days": 30}
    _store_rollup(result)
    eng._cache.clear()
    monkeypatch.setattr(roster_engine, "_warm_async", lambda d, b: None)
    monkeypatch.setattr(eng, "compute",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("cold path ran")))
    _fast_enrichment(monkeypatch)
    checked = drifted = 0
    sl = kv_store.get("attr:rollup:cohort:30")["engine"]
    for row in sl["creatives"]:
        for m in MEMBER_METRICS:
            checked += 1
            n_members = len((row.get("members") or {}).get(m) or [])
            if n_members != (row.get(m) or 0):
                drifted += 1
            d = roster_engine.build(days=30, basis="cohort", level="creative",
                                    key=row["creative_key"], metric=m)
            assert d["count"] == len(d["people"]) == n_members, \
                (row["creative_key"], m)
    assert drifted == 0 and checked >= 24
