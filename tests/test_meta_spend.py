"""
tests/test_meta_spend.py
------------------------
Live Meta ad spend engine: graceful degradation, retroactive daily store →
windowed totals, ROAS wiring, and the Meta-primary/Xero-fallback resolver.
"""
from __future__ import annotations

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import meta_spend
from hormozi_metrics import m8_roas, _resolved_ad_spend
from metrics_engine import classify_refresh_health, OPTIONAL_DEGRADED_METRICS


def test_no_token_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(meta_spend, "META_ACCESS_TOKEN", "")
    monkeypatch.setattr(meta_spend, "META_AD_ACCOUNT_ID", "")
    r = meta_spend.pull_meta_spend()
    assert r["meta_spend"] is None
    assert r["degraded"] and r["degraded"][0]["metric"] == "meta_spend"
    assert r["degraded"][0]["severity"] == "optional"


def test_meta_absence_is_optional_not_core():
    # Pill must NOT go red just because Meta isn't configured.
    rh = classify_refresh_health([{"metric": "meta_spend", "severity": "optional"}])
    assert rh["status"] == "green"
    assert "meta_spend" in OPTIONAL_DEGRADED_METRICS


def test_window_sum_trailing(monkeypatch):
    today = date(2026, 6, 24)
    store = {str(today - timedelta(days=i)): {"spend": 100.0, "impressions": 10, "clicks": 1}
             for i in range(40)}
    w7 = meta_spend._window_sum(store, today, 7)
    w30 = meta_spend._window_sum(store, today, 30)
    assert w7["spend"] == 700.0 and w7["days_covered"] == 7
    assert w30["spend"] == 3000.0 and w30["days_covered"] == 30
    assert w7["window_end"] == "2026-06-24"


def test_fetch_overwrites_retroactively(monkeypatch, tmp_path):
    # Simulate two refreshes: the second re-fetches recent days with UPDATED spend.
    store_file = tmp_path / "meta_daily.json"
    monkeypatch.setattr(meta_spend, "META_SPEND_STORE", str(store_file))
    monkeypatch.setattr(meta_spend, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(meta_spend, "META_AD_ACCOUNT_ID", "123")
    today = meta_spend.today_sydney()
    d0 = str(today)

    calls = {"n": 0}
    def fake_graph(path, params):
        if path.endswith("/insights"):
            calls["n"] += 1
            spend = "100.00" if calls["n"] == 1 else "175.00"  # attribution firms up
            return {"data": [{"date_start": d0, "date_stop": d0,
                              "spend": spend, "impressions": "10", "clicks": "2"}]}, None
        return {"currency": "AUD", "timezone_name": "Australia/Sydney", "name": "Served"}, None
    monkeypatch.setattr(meta_spend, "_graph_get", fake_graph)

    r1 = meta_spend.pull_meta_spend()
    assert r1["meta_spend"]["windows"]["7d"]["spend"] == 100.0
    r2 = meta_spend.pull_meta_spend()
    # Re-fetched day OVERWRITES (not appends/freezes): 175, not 275.
    assert r2["meta_spend"]["windows"]["7d"]["spend"] == 175.0
    assert r2["meta_spend"]["currency"] == "AUD"
    # The recent day is flagged provisional.
    assert any(d["provisional"] for d in r2["meta_spend"]["daily"])


def test_fetch_failure_keeps_last_good(monkeypatch, tmp_path):
    store_file = tmp_path / "m.json"
    monkeypatch.setattr(meta_spend, "META_SPEND_STORE", str(store_file))
    monkeypatch.setattr(meta_spend, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(meta_spend, "META_AD_ACCOUNT_ID", "123")
    today = meta_spend.today_sydney()
    # Seed a good store, then a failing fetch.
    import json
    store_file.write_text(json.dumps({str(today): {"spend": 90.0, "impressions": 5, "clicks": 1}}))
    monkeypatch.setattr(meta_spend, "_graph_get", lambda p, q: (None, "HTTP 500 code=2: transient"))
    r = meta_spend.pull_meta_spend()
    assert r["meta_spend"] is not None  # last-good shown
    assert r["meta_spend"]["fetch_ok"] is False
    assert r["meta_spend"]["windows"]["7d"]["spend"] == 90.0
    assert any("failed" in d["reason"].lower() for d in r["degraded"])


def test_roas_meta_primary_window_consistent():
    snap = {"ad_spend_resolved": {"value": 6000.0, "source": "meta_live", "window_days": 30},
            "sales": {"funnel": {"closes": 6}, "deep": {"money": {"avg_contract": 16300}},
                      "window_days": 30}}
    r = m8_roas(snap)
    assert r["value"] == round(6 * 16300 / 6000, 2)
    assert r["inputs_used"]["window_consistent"] is True
    assert r["inputs_used"]["platform"] == "meta"


def test_resolver_prefers_meta_then_xero():
    meta_snap = {"ad_spend_resolved": {"value": 6000.0, "source": "meta_live", "window_days": 30}}
    assert _resolved_ad_spend(meta_snap) == (6000.0, "meta_live", 30)
    xero_snap = {"xero": {"xero_ad_spend": 8002.0}}
    assert _resolved_ad_spend(xero_snap) == (8002.0, "xero_advertising", 30)
    empty = {}
    assert _resolved_ad_spend(empty) == (None, None, 30)
