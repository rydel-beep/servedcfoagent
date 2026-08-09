"""
tests/test_sentinel_watches_133.py — the two #133 sentinel watches riding the
nightly integrity sweep (L2): launch-field freshness and range-view clock-label
integrity. Both append typed disagreements (the feed-lane promotion and the
auto-test-skeleton mechanism consume the kind); clock_label is ACTION-promoted.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ads_truth
import launch_lineage as LL


def _out():
    return {"date": "2026-08-09", "disagreements": []}


def _fake_stores(monkeypatch, lineage_ads, spend_days):
    import meta_entities
    monkeypatch.setattr(LL, "_load", lambda: {"ads": lineage_ads})
    monkeypatch.setattr(meta_entities, "_load_json",
                        lambda p: {"days": spend_days}
                        if p == meta_entities.AD_SPEND_STORE else {})
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    return store


def test_launch_freshness_clean_store_no_flags(monkeypatch):
    out = _out()
    _fake_stores(monkeypatch,
                 {"A": {"delivery_days": ["2026-08-01"], "lifetime_probed": True}},
                 {"2026-08-01": {"A": {"spend": 5, "impressions": 10}}})
    ads_truth.launch_freshness_check(out)
    assert out["launch_lineage"]["missing_day_entries"] == 0
    assert out["disagreements"] == []


def test_launch_freshness_lagging_store_flags(monkeypatch):
    out = _out()
    _fake_stores(monkeypatch,
                 {"A": {"delivery_days": ["2026-08-01"], "lifetime_probed": True}},
                 {"2026-08-01": {"A": {"spend": 5, "impressions": 10}},
                  "2026-08-02": {"A": {"spend": 7, "impressions": 20},
                                 "B": {"spend": 3, "impressions": 9}}})
    ads_truth.launch_freshness_check(out)
    assert out["launch_lineage"]["missing_day_entries"] == 2   # A's 08-02 + all of B
    kinds = [d["kind"] for d in out["disagreements"]]
    assert kinds == ["launch_freshness"]
    assert "not keeping up" in out["disagreements"][0]["cause"]


def test_launch_probe_pending_across_nights_flags(monkeypatch):
    lineage = {"A": {"delivery_days": ["2026-08-01"], "censored": True,
                     "lifetime_probed": False}}
    spend = {"2026-08-01": {"A": {"spend": 5, "impressions": 10}}}
    out1 = _out()
    kv = _fake_stores(monkeypatch, lineage, spend)
    ads_truth.launch_freshness_check(out1)
    # first night: pending recorded, no persistence flag yet
    assert not any(d["kind"] == "launch_freshness" and "pending" in d["cause"]
                   for d in out1["disagreements"])
    assert kv["launch:pending_prev"]["count"] == 1
    # second night, still pending → the persistence flag fires
    out2 = {"date": "2026-08-10", "disagreements": []}
    ads_truth.launch_freshness_check(out2)
    assert any(d["kind"] == "launch_freshness" and "still pending" in d["cause"]
               for d in out2["disagreements"])


def test_clock_label_ok_when_engine_honours_the_clock(monkeypatch):
    import attribution_engine as eng

    def fake_compute(start=None, end=None, basis="cohort", **kw):
        return {"basis": basis, "basis_label": f"{basis} label",
                "window": {"start": start, "end": end}}
    monkeypatch.setattr(eng, "compute", fake_compute)
    out = _out()
    ads_truth.clock_label_check(out)
    assert out["clock_label"]["ok"] is True
    assert out["disagreements"] == []


def test_clock_label_drift_is_loud_and_action_promoted(monkeypatch):
    import attribution_engine as eng

    def broken_compute(start=None, end=None, basis="cohort", **kw):
        # the engine IGNORES the clock param — the exact wiring failure the
        # watch exists for (both legs come back cohort, unlabelled)
        return {"basis": "cohort", "basis_label": None,
                "window": {"start": start, "end": end}}
    monkeypatch.setattr(eng, "compute", broken_compute)
    out = _out()
    ads_truth.clock_label_check(out)
    assert out["clock_label"]["ok"] is False
    kinds = {d["kind"] for d in out["disagreements"]}
    assert kinds == {"clock_label"}
    causes = " | ".join(d["cause"] for d in out["disagreements"])
    assert "engine echoed" in causes            # activity leg came back cohort
    assert "basis_label missing" in causes
    assert "I11 guard FAILED" in causes         # same-basis mix no longer raises
    # clock_label is in the ACTION-promoted kind set (feed-lane contract)
    src = open(os.path.join(os.path.dirname(__file__), "..", "ads_truth.py")).read()
    promo = src.split('dgg["kind"] in (')[1].split(")")[0]
    assert "clock_label" in promo
