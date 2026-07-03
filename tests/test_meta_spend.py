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

    monkeypatch.setattr(meta_spend, "_graph_get",
                        lambda p, q: ({"currency": "AUD", "timezone_name": "Australia/Sydney"}, None))
    calls = {"n": 0}
    def fake_insights(path, params):
        calls["n"] += 1
        spend = "100.00" if calls["n"] == 1 else "175.00"  # attribution firms up
        return [{"date_start": d0, "date_stop": d0, "spend": spend,
                 "impressions": "10", "clicks": "2"}], None
    monkeypatch.setattr(meta_spend, "_graph_get_all", fake_insights)

    r1 = meta_spend.pull_meta_spend()
    assert r1["meta_spend"]["windows"]["7d"]["spend"] == 100.0
    r2 = meta_spend.pull_meta_spend()
    # Re-fetched day OVERWRITES (not appends/freezes): 175, not 275.
    assert r2["meta_spend"]["windows"]["7d"]["spend"] == 175.0
    assert r2["meta_spend"]["currency"] == "AUD"
    assert any(d["provisional"] for d in r2["meta_spend"]["daily"])


def test_fetch_failure_keeps_last_good(monkeypatch, tmp_path):
    store_file = tmp_path / "m.json"
    monkeypatch.setattr(meta_spend, "META_SPEND_STORE", str(store_file))
    monkeypatch.setattr(meta_spend, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(meta_spend, "META_AD_ACCOUNT_ID", "123")
    today = meta_spend.today_sydney()
    import json
    store_file.write_text(json.dumps({str(today): {"spend": 90.0, "impressions": 5, "clicks": 1}}))
    monkeypatch.setattr(meta_spend, "_graph_get", lambda p, q: (None, "acct err"))
    monkeypatch.setattr(meta_spend, "_graph_get_all", lambda p, q: (None, "HTTP 500 code=2: transient"))
    r = meta_spend.pull_meta_spend()
    assert r["meta_spend"] is not None  # last-good shown
    assert r["meta_spend"]["fetch_ok"] is False
    assert r["meta_spend"]["windows"]["7d"]["spend"] == 90.0
    assert any("failed" in d["reason"].lower() for d in r["degraded"])


def test_pagination_follows_cursor(monkeypatch):
    # _graph_get_all MUST follow paging.next — a single page silently truncates the
    # range (the live bug: page 1 = oldest 25 days, recent windows read $0).
    pages = [
        ({"data": [{"date_start": "2026-03-01", "spend": "10"}],
          "paging": {"next": "https://graph.facebook.com/PAGE2"}}, None),
        ({"data": [{"date_start": "2026-06-20", "spend": "20"}],
          "paging": {"next": "https://graph.facebook.com/PAGE3"}}, None),
        ({"data": [{"date_start": "2026-06-24", "spend": "30"}]}, None),  # no next → done
    ]
    seq = {"i": 0}
    def fake_req(url, params):
        out = pages[seq["i"]]; seq["i"] += 1; return out
    monkeypatch.setattr(meta_spend, "_graph_request", fake_req)
    rows, err = meta_spend._graph_get_all("act_1/insights", {"access_token": "t"})
    assert err is None
    assert len(rows) == 3
    assert {r["date_start"] for r in rows} == {"2026-03-01", "2026-06-20", "2026-06-24"}


def test_pagination_partial_on_error(monkeypatch):
    # If a later page fails, return what we have + a loud error (no silent truncation).
    pages = [
        ({"data": [{"date_start": "2026-03-01", "spend": "10"}],
          "paging": {"next": "https://graph.facebook.com/PAGE2"}}, None),
        (None, "HTTP 500 code=2"),
    ]
    seq = {"i": 0}
    def fake_req(url, params):
        out = pages[seq["i"]]; seq["i"] += 1; return out
    monkeypatch.setattr(meta_spend, "_graph_request", fake_req)
    rows, err = meta_spend._graph_get_all("act_1/insights", {"access_token": "t"})
    assert len(rows) == 1 and err is not None and "pagination" in err


def test_roas_meta_primary_window_consistent():
    # ROAS delegates to the one engine — CONTRACTED revenue ÷ Meta spend (Rydel-locked).
    contracted = 6 * 16300
    eng = {"roas": round(contracted / 6000, 2), "caveats": [],
           "components": {"contract_value_total": contracted, "ad_spend": 6000.0,
                          "closes": 6, "window": {"days": 30}}}
    r = m8_roas({}, {}, eng)
    assert r["value"] == round(contracted / 6000, 2)
    assert r["inputs_used"]["contracted_revenue"] == contracted
    assert "contracted" in r["read"].lower()


def test_resolver_prefers_meta_then_xero():
    meta_snap = {"ad_spend_resolved": {"value": 6000.0, "source": "meta_live", "window_days": 30}}
    assert _resolved_ad_spend(meta_snap) == (6000.0, "meta_live", 30)
    xero_snap = {"xero": {"xero_ad_spend": 8002.0}}
    assert _resolved_ad_spend(xero_snap) == (8002.0, "xero_advertising", 30)
    empty = {}
    assert _resolved_ad_spend(empty) == (None, None, 30)
