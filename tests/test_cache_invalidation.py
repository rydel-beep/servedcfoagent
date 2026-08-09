"""
tests/test_cache_invalidation.py — F6 (extreme audit): derivation writes must
invalidate the compute cache and the rollup layer IMMEDIATELY. Root cause: no
derivation write (card apply, ruling conversion, supersession, show
verification, spine, reached) touched attribution_engine._cache or the
persisted rollups — after "apply the date card" the affected cells kept OLD
values labelled fresh for up to 30 minutes. A freshness label on stale data
is a lie.

Mechanism under test: kv `derived:epoch` — bumped by every derivation-class
write, folded into the engine cache key and stamped on every rollup record.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attribution_engine as eng
import resolution
from tests.test_ads_dashboard import _client, _fake_result


def _clear_epoch():
    import kv_store
    kv_store.delete("derived:epoch")


# ── the epoch bumps on every derivation-class write ──────────────────────────

def test_record_derived_date_bumps_epoch():
    _clear_epoch()
    e0 = resolution.derived_epoch()
    ok = resolution.record_derived_date("cache test lead", "close_date", "2026-08-01",
                                        "derived:stripe", {"charge_id": "ch_test"})
    assert ok
    assert resolution.derived_epoch() == e0 + 1
    # idempotent re-derivation converts nothing twice AND bumps nothing twice
    resolution.record_derived_date("cache test lead", "close_date", "2026-08-01",
                                   "derived:stripe", {"charge_id": "ch_test"})
    assert resolution.derived_epoch() == e0 + 1


def test_supersede_bumps_epoch():
    resolution.record_derived_date("cache test lead2", "close_date", "2026-08-01",
                                   "derived:stripe", {"charge_id": "ch_test2"})
    e1 = resolution.derived_epoch()
    resolution.supersede_derived("cache test lead2", "close_date", "2026-08-01")
    assert resolution.derived_epoch() == e1 + 1


# ── the engine cache keys on the epoch ───────────────────────────────────────

def test_compute_cache_invalidated_by_epoch_bump(monkeypatch):
    """A cached result must NOT be served after a derivation write."""
    calls = {"n": 0}
    result = _fake_result()

    def fake_inputs(*a, **kw):
        calls["n"] += 1
        return result
    import attribution_join, meta_entities, leads_view
    monkeypatch.setattr(attribution_join, "sync_contacts", lambda: {"at": None, "total": 0})
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    monkeypatch.setattr(meta_entities, "refresh_entity_map",
                        lambda force=False: {"ads": {}, "extras": {}, "degraded": []})
    monkeypatch.setattr(meta_entities, "refresh_ad_spend_daily", lambda: {})
    monkeypatch.setattr(meta_entities, "spend_by_ad_in_range",
                        lambda s, e: {"ads": {}, "source": "test", "degraded": []})
    monkeypatch.setattr(eng, "_tracker_rows_clean", lambda: [])
    monkeypatch.setattr(leads_view, "count_leads", lambda w0, w1: {"count": 0})
    monkeypatch.setattr(eng, "compute_from_inputs", fake_inputs)
    eng._cache.clear()
    eng.compute(days=30)
    assert calls["n"] == 1
    eng.compute(days=30)
    assert calls["n"] == 1                    # warm — served from cache
    resolution.bump_derived_epoch("test write")
    eng.compute(days=30)
    assert calls["n"] == 2                    # the write invalidated the cache
    # cache_fresh reflects the CURRENT epoch key shape (the rollup layer's probe)
    import datetime as dt
    from helpers import today_sydney
    w1 = today_sydney(); w0 = w1 - dt.timedelta(days=29)
    assert eng.cache_fresh(w0, w1, "cohort") is True
    resolution.bump_derived_epoch("test write 2")
    assert eng.cache_fresh(w0, w1, "cohort") is False
    # old-epoch entries were pruned on the next compute write, not left to pile up
    eng.compute(days=30)
    assert all(k[4] == resolution.derived_epoch() for k in eng._cache)


# ── the rollup layer stamps + honours the epoch ──────────────────────────────

def test_rollup_from_before_a_write_serves_stale_labelled(monkeypatch):
    """Apply a card → the stored rollup predates the write → the serve is
    stale-LABELLED with the derivation reason and a refresh kicks. No
    stale-labelled-fresh window remains."""
    import kv_store
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    result = _fake_result()
    result["window"] = {"start": "s", "end": "e", "days": 30}
    monkeypatch.setattr("attribution_engine.compute", lambda **kw: result, raising=True)
    monkeypatch.setattr("dashboard.ads._prefetch_adjacent", lambda d, b: None, raising=True)
    refreshes = []
    monkeypatch.setattr("dashboard.ads._refresh_async",
                        lambda d, b: refreshes.append((d, b)), raising=True)
    eng._cache.clear()                        # engine cold → rollup path
    kv_store.delete("attr:rollup:cohort:30")  # a rollup left by an earlier test
                                              # would flip the first serve stale
    # a fresh serve stores the rollup stamped with the CURRENT epoch
    d = c.get("/ads/api/board?days=30").get_json()
    assert d["stale"] is False
    stored = kv_store.get("attr:rollup:cohort:30")
    assert stored.get("epoch") == resolution.derived_epoch()
    # the derivation write bumps the epoch → the stored rollup is now stale
    resolution.bump_derived_epoch("card applied (test)")
    eng._cache.clear()
    d2 = c.get("/ads/api/board?days=30").get_json()
    assert d2["stale"] is True
    assert "derivation" in (d2.get("stale_reason") or "")
    assert refreshes                          # a refresh was kicked
