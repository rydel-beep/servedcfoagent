"""
tests/test_range_flow.py — RANGE SPEED + FLOW (2026-08-10).

Backend: Meta network is evicted from the interactive compute path — the
ad-spend daily refresh is TTL-guarded (stale-but-present serves the stamped
store and refreshes in the BACKGROUND; only an empty store blocks), the entity
map does the same on TTL lapse, and history backfill makes Maximum/old boxes
store-served. Frontend (structural pins): the dim overlay is dead; loading is
per-cell and honest (the header claims the TARGET state in the same frame the
numeric cells skeleton — old numbers never sit under a new-range label);
superseded fetches are aborted; failures revert controls to the last-good
board.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import meta_entities as ME

_REPO = os.path.join(os.path.dirname(__file__), "..")
_JS = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
_CSS = open(os.path.join(_REPO, "dashboard", "static", "css", "adsapp.css")).read()


# ── backend: the TTL guard (D1's 7s eviction) ────────────────────────────────

def _spend_store(monkeypatch, tmp_path, refreshed_at):
    import json
    p = tmp_path / "spend.json"
    p.write_text(json.dumps({"days": {"2026-08-01": {"A": {"spend": 5.0,
                                                           "impressions": 10,
                                                           "clicks": 1}}},
                             "refreshed_at": refreshed_at}))
    monkeypatch.setattr(ME, "AD_SPEND_STORE", str(p))
    ME._json_memo.clear()
    return p


def test_fresh_store_serves_without_any_network(monkeypatch, tmp_path):
    _spend_store(monkeypatch, tmp_path, time.time() - 60)
    monkeypatch.setattr(ME, "configured", lambda: True)
    def boom(*a, **k):
        raise AssertionError("network on the interactive path")
    monkeypatch.setattr(ME, "_get_all", boom)
    monkeypatch.setattr(ME, "_kick_bg", boom)
    out = ME.refresh_ad_spend_daily()
    assert out["days"]["2026-08-01"]["A"]["spend"] == 5.0


def test_stale_store_serves_now_and_refreshes_in_background(monkeypatch, tmp_path):
    _spend_store(monkeypatch, tmp_path, time.time() - ME._AD_SPEND_TTL_S - 10)
    monkeypatch.setattr(ME, "configured", lambda: True)
    kicked = []
    monkeypatch.setattr(ME, "_kick_bg", lambda key, fn: kicked.append(key))
    def boom(*a, **k):
        raise AssertionError("stale-but-present must NOT fetch inline")
    monkeypatch.setattr(ME, "_get_all", boom)
    out = ME.refresh_ad_spend_daily()
    assert out["days"]                        # served immediately, stamped
    assert kicked == ["ad_spend"]             # freshness restored off-path


def test_empty_store_still_blocks_first_boot(monkeypatch, tmp_path):
    import json
    p = tmp_path / "spend.json"
    p.write_text(json.dumps({"days": {}}))
    monkeypatch.setattr(ME, "AD_SPEND_STORE", str(p))
    ME._json_memo.clear()
    monkeypatch.setattr(ME, "configured", lambda: True)
    calls = []
    monkeypatch.setattr(ME, "_get_all", lambda path, params: (calls.append(path) or [], None))
    ME.refresh_ad_spend_daily()
    assert calls                              # first boot fetches inline


def test_entity_map_ttl_lapse_serves_stale_and_kicks_bg(monkeypatch, tmp_path):
    import json
    p = tmp_path / "ents.json"
    p.write_text(json.dumps({"fetched_at": time.time() - ME._ENTITY_TTL_S - 5,
                             "ads": {"1": {"name": "x"}}}))
    monkeypatch.setattr(ME, "ENTITY_STORE", str(p))
    ME._json_memo.clear()
    kicked = []
    monkeypatch.setattr(ME, "_kick_bg", lambda key, fn: kicked.append(key))
    out = ME.refresh_entity_map()
    assert out["ads"]["1"]["name"] == "x"     # stamped stale map, served now
    assert kicked == ["entity_map"]


def test_backfill_history_idempotent_once_covered(monkeypatch, tmp_path):
    import json
    p = tmp_path / "spend.json"
    p.write_text(json.dumps({"days": {"2026-06-01": {}},
                             "history_since": "2026-01-01"}))
    monkeypatch.setattr(ME, "AD_SPEND_STORE", str(p))
    ME._json_memo.clear()
    monkeypatch.setattr(ME, "configured", lambda: True)
    def boom(*a, **k):
        raise AssertionError("covered history must not refetch")
    monkeypatch.setattr(ME, "_get_all", boom)
    # #138: history_since 2026-01-01 already reaches past the API floor, so a
    # backfill to 2026-01-01 (or the default floor) fetches nothing — idempotent.
    out = ME.backfill_history("2026-01-01")
    assert out["fetched_days"] == 0 and "already covered" in out["note"]


# ── frontend: the dim is dead; loading is per-cell and honest ────────────────

def test_dim_overlay_provably_gone():
    assert "classList.add('adx-loading')" not in _JS
    assert 'classList.add("adx-loading")' not in _JS
    # the blanket dim RULE is deleted (the adxPulse skeleton keyframe is not a dim)
    assert "body.adx-loading .adx-panel" not in _CSS
    # the replacement exists: per-cell skeletons only
    assert ".adx-pending tbody td:not(.adx-name)" in _CSS
    assert "adx-shimmer" in _CSS


def test_header_claims_target_in_the_same_frame_numbers_hide():
    """The one sin: old numbers under a new-range label. enterPending() sets
    the TARGET header AND the skeleton classes together, is called BEFORE the
    fetch, and renderAll() clears pending only when matching data arrived
    (echo-guarded upstream)."""
    body = _JS.split("function enterPending()")[1].split("function clearPending()")[0]
    assert "pendingHeaderLine()" in body and "loading…" in body
    assert "adx-pending" in body and "adx-pending-head" in body
    lb = _JS.split("function loadBoard(")[1].split("function echoMatches")[0]
    assert lb.index("enterPending()") < lb.index("fetch('/ads/api/board?'")
    ra = _JS.split("function renderAll()")[1].split("function ")[1] if False else \
        _JS.split("function renderAll()")[1][:400]
    assert "clearPending()" in ra
    # the pending header derives from CONTROL state, never the old board
    ph = _JS.split("function pendingHeaderLine()")[1].split("function ")[1] if False else \
        _JS.split("function pendingHeaderLine()")[1][:400]
    assert "state.range" in ph and "state.windowLabel" in ph
    assert "state.board" not in ph


def test_race_guard_aborts_superseded_and_keeps_token_gate():
    lb = _JS.split("function loadBoard(")[1].split("function echoMatches")[0]
    assert "inflight.abort()" in lb
    assert "AbortController" in lb
    assert "signal: inflight && inflight.signal" in lb
    assert "AbortError" in lb                 # aborted fetches never touch the UI
    assert "token !== state.reqToken" in lb   # the paint gate stays
    assert "echoMatches(data)" in lb          # and the server-echo guard stays


def test_failure_reverts_to_last_good_state():
    body = _JS.split("function exitPendingToLastGood")[1].split("\n  }")[0]
    assert "clearPending()" in body
    assert "syncPresetSelect()" in body and "renderAll()" in body
    lb = _JS.split("function loadBoard(")[1].split("function echoMatches")[0]
    assert "exitPendingToLastGood" in lb


def test_controls_never_locked():
    """pointer-events:none may exist ONLY on the hover card (which must not
    intercept clicks) — never on panels, controls, or the pending state."""
    for chunk in _CSS.split("}"):
        if "pointer-events: none" in chunk:
            assert ".adx-hover" in chunk, f"pointer lock outside the hover card: {chunk[:120]}"
    assert ".adx-pending" in _CSS and "pointer-events" not in \
        _CSS.split(".adx-pending tbody")[1].split("@keyframes")[0]


def test_recover_by_name_negative_caches_misses(monkeypatch):
    """RANGE SPEED (profiled 12.8s/serve): an unresolvable name-ref re-swept up
    to 3 YEARLY insights chunks on EVERY fresh compute. Misses negative-cache
    for 7 days; a cached miss makes ZERO network calls; hits still learn."""
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(ME, "configured", lambda: True)
    calls = []
    monkeypatch.setattr(ME, "_get_all", lambda p, prm: (calls.append(p) or [], None))
    assert ME.recover_by_name("Ghost Ad That Never Existed") is None
    assert calls                                   # first miss swept
    n = len(calls)
    assert ME.recover_by_name("Ghost Ad That Never Existed") is None
    assert len(calls) == n                         # cached miss: zero network
    assert "ghost ad that never existed" in store[ME._NAME_MISS_KEY]
    # expiry re-opens the sweep
    store[ME._NAME_MISS_KEY]["ghost ad that never existed"] = \
        time.time() - ME._NAME_MISS_TTL_S - 5
    ME.recover_by_name("Ghost Ad That Never Existed")
    assert len(calls) > n


def test_interactive_compute_never_runs_name_recovery():
    """The historical-name insights sweep is nightly-only: compute()'s resolver
    passes allow_recovery=False (a first-ever old box paid 79s of first-time
    name sweeps inline before this)."""
    src = open(os.path.join(_REPO, "attribution_engine.py")).read()
    seg = src.split("def resolve_fn(ref, kind):")[1].split("def ")[0]
    assert "allow_recovery=False" in seg
    ats = open(os.path.join(_REPO, "ads_truth.py")).read()
    assert "def name_recovery_pass" in ats
    assert 'out["name_recovery"] = name_recovery_pass()' in ats


def test_name_recovery_pass_learns_and_caches(monkeypatch):
    import ads_truth
    import attribution_join
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(ME, "configured", lambda: True)
    monkeypatch.setattr(ME, "refresh_entity_map",
                        lambda force=False: {"ads": {}, "extras": {}})
    monkeypatch.setattr(ME, "candidates_by_name", lambda name, store=None: [])
    recovered = []
    monkeypatch.setattr(ME, "recover_by_name",
                        lambda name: recovered.append(name) or (
                            {"ad_id": "1"} if "Known" in name else None))
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [
        {"tier": "ad", "ft_ref_kind": "name", "ft_ad_ref": "Known Old Ad"},
        {"tier": "ad", "ft_ref_kind": "name", "ft_ad_ref": "Ghost Ad"},
        {"tier": "ad", "ft_ref_kind": "id", "ft_ad_ref": "123"},   # ids skipped
    ])
    out = ads_truth.name_recovery_pass(max_names=10)
    assert out["checked"] == 2 and out["learned"] == 1 and out["cached_miss"] == 1
    assert recovered == ["Known Old Ad", "Ghost Ad"]
