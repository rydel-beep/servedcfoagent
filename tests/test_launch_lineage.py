"""
tests/test_launch_lineage.py — LAUNCH LINEAGE (#133).

launched = FIRST-DELIVERY (first day with impressions), never created_time and
never the ad set's reused start_time; days running = ACTIVE DELIVERY DAYS,
never calendar days. Store-censored ads (earliest known day == the 90d spend
store's oldest edge) get a one-time lifetime probe; until it runs they report
"on or before", never a fabricated exact date. Hover, dossier and the launch
sorts all read the ONE engine field — equality is asserted here.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import launch_lineage as LL

TODAY = dt.date(2026, 8, 9)


@pytest.fixture
def iso_store(tmp_path, monkeypatch):
    """Isolated lineage store + a controlled fake per-ad daily spend store."""
    path = str(tmp_path / "lineage.json")
    monkeypatch.setattr(LL, "LINEAGE_STORE", path)
    LL._mem_cache.clear()

    def set_spend_days(days: dict):
        import meta_entities
        monkeypatch.setattr(meta_entities, "_load_json",
                            lambda p: {"days": days} if p == meta_entities.AD_SPEND_STORE
                            else {})
    # kv mirror quiet in tests
    import kv_store
    monkeypatch.setattr(kv_store, "put", lambda *a, **k: None)
    monkeypatch.setattr(kv_store, "get", lambda *a, **k: None)
    return set_spend_days


def _days(spec: dict) -> dict:
    """{date: [ad ids with delivery]} → the spend-store day shape."""
    return {d: {aid: {"name": f"ad {aid}", "spend": 10.0, "impressions": 100}
                for aid in aids}
            for d, aids in spec.items()}


def test_uncensored_ad_first_delivery_from_store(iso_store, monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    iso_store(_days({"2026-05-11": ["111"], "2026-06-01": ["111", "222"],
                     "2026-06-03": ["222"]}))
    out = LL.refresh()
    assert out["ads"] == 2
    # ad 222 was born INSIDE the store → its launch is exact, no probe needed
    lin = LL.lineage_for(["222"], today=TODAY)
    assert lin["launch"] == "2026-06-01" and lin["launch_approx"] is False
    assert lin["active_days"] == 2


def test_censored_ad_reports_on_or_before_until_probed(iso_store, monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    iso_store(_days({"2026-05-11": ["111"], "2026-05-12": ["111"]}))
    out = LL.refresh()
    # not configured → the probe can't run; degradation is STATED, nothing guessed
    assert out["pending_probes"] == 1
    assert any("lifetime launch probe" in d["reason"] for d in out["degraded"])
    lin = LL.lineage_for(["111"], today=TODAY)
    assert lin["launch"] == "2026-05-11"
    assert lin["launch_approx"] is True          # "on or before" — probe pending


def test_lifetime_probe_pins_exact_launch_and_backfills_days(iso_store, monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: True)
    iso_store(_days({"2026-05-11": ["111"], "2026-05-13": ["111"]}))
    calls = {"monthly": 0, "daily": 0}

    def fake_get(path, params):
        calls["monthly"] += 1
        return {"data": [
            {"date_start": "2026-03-01", "date_stop": "2026-03-31", "impressions": "0"},
            {"date_start": "2026-04-01", "date_stop": "2026-04-30", "impressions": "500"},
            {"date_start": "2026-05-01", "date_stop": "2026-05-31", "impressions": "900"},
        ]}, None

    def fake_get_all(path, params):
        calls["daily"] += 1
        tr = json.loads(params["time_range"])
        assert tr["since"] == "2026-04-01"       # first ACTIVE month, not the dead one
        return [{"date_start": "2026-04-10", "impressions": "300", "spend": "5"},
                {"date_start": "2026-04-11", "impressions": "200", "spend": "5"},
                {"date_start": "2026-04-30", "impressions": "0", "spend": "0"}], None
    monkeypatch.setattr(meta_entities, "_get", fake_get)
    monkeypatch.setattr(meta_entities, "_get_all", fake_get_all)
    monkeypatch.setattr(LL, "_token", lambda: "t")
    out = LL.refresh()
    assert out["probed"] == 1 and out["pending_probes"] == 0
    lin = LL.lineage_for(["111"], today=TODAY)
    assert lin["launch"] == "2026-04-10" and lin["launch_approx"] is False
    # active days = probed pre-store days + store days (zero-impression day excluded)
    assert lin["active_days"] == 4               # 04-10, 04-11, 05-11, 05-13
    # idempotent: a second refresh probes NOTHING again
    LL.refresh()
    assert calls["monthly"] == 1 and calls["daily"] == 1


def test_active_days_never_calendar_days_on_a_paused_ad(iso_store, monkeypatch):
    """The mission case: paused-then-resumed must not claim runtime it didn't have."""
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    iso_store(_days({"2026-06-01": ["A"], "2026-06-02": ["A"],
                     "2026-07-30": ["A"], "2026-07-31": ["A"]}))   # 58-day pause
    LL.refresh()
    lin = LL.lineage_for(["A"], today=TODAY)
    assert lin["active_days"] == 4
    assert lin["calendar_days"] == 70            # 06-01 → 08-09 inclusive
    assert lin["active_days"] < lin["calendar_days"]


def test_group_lineage_is_member_union(iso_store, monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    iso_store(_days({"2026-06-01": ["A"], "2026-06-02": ["A", "B"],
                     "2026-06-05": ["B"]}))
    LL.refresh()
    agg = LL.aggregate_rows([{"ad_ids": ["A"]}, {"ad_ids": ["B"]}], today=TODAY)
    assert agg["launch"] == "2026-06-01"         # earliest member
    assert agg["active_days"] == 3               # UNION of days, not a sum (4)


def test_unknown_ad_is_degraded_never_zero(iso_store, monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    iso_store({})
    LL.refresh()
    lin = LL.lineage_for(["999"], today=TODAY)
    assert lin["launch"] is None and lin["active_days"] is None
    assert "unknown" in lin["degraded"]


def test_delivery_days_match_lineage_scalars(iso_store, monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    iso_store(_days({"2026-06-01": ["A"], "2026-06-03": ["A"]}))
    LL.refresh()
    dd = LL.delivery_days(["A"], today=TODAY)
    lin = LL.lineage_for(["A"], today=TODAY)
    assert len(dd) == lin["active_days"]
    assert dd[0] == lin["launch"]


# ── ONE SOURCE: hover (scoreboard row) == dossier == sort key ────────────────

def test_lineage_identical_across_board_row_and_dossier(monkeypatch):
    import attribution_engine as eng
    from tests.test_ads_dashboard import _client, _fake_result
    result = _fake_result()
    LIN = {"launch": "2026-06-05", "launch_approx": False, "active_days": 12,
           "calendar_days": 30, "status": "ACTIVE", "created_time": "2026-06-04",
           "scheduled_start": "2025-05-16", "source": "meta:insights", "degraded": None}
    for c in result["creatives"]:
        c["lineage"] = LIN if c["tier"] == "ad" else None
    result["window"] = {"start": "x", "end": "y", "days": 30}
    monkeypatch.setattr("attribution_engine.compute", lambda **kw: result, raising=True)
    # pin the F1 rollup fast path to the same result — an earlier test's persisted
    # rollup slice must not leak into this equality check
    monkeypatch.setattr("roster_engine.load_result",
                        lambda *a, **kw: (result, {"served_from": "engine", "stale": False,
                                                   "stale_age_s": None, "stale_reason": None}),
                        raising=True)
    monkeypatch.setattr("roster_engine.build", lambda **kw: {"people": [], "i17": {"ok": True}},
                        raising=True)
    # a rollup left in kv by an earlier test would serve a stale board without
    # the faked lineage — clear it and quiet the background prefetch
    import kv_store
    kv_store.delete("attr:rollup:cohort:30")
    monkeypatch.setattr("dashboard.ads._prefetch_adjacent", lambda d, b: None, raising=True)
    eng._cache.clear()
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    board = c.get("/ads/api/board?days=30").get_json()
    row = [r for r in board["scoreboard"]["rows"] if r["tier"] == "ad"][0]
    assert row["lineage"] == LIN                 # the hover card's read
    dossier = c.get(f"/ads/api/dossier?days=30&creative={row['creative_key']}").get_json()
    assert dossier["lineage"] == LIN             # the dossier's read — same field
    # tier rows carry None — no ad identity exists for them (never a fake launch)
    tier = [r for r in board["scoreboard"]["rows"] if r["tier"] != "ad"][0]
    assert tier["lineage"] is None
