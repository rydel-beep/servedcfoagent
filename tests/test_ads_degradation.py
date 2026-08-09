"""
tests/test_ads_degradation.py — F5 (extreme audit): LOUD DEGRADATION on the money
columns. A dead upstream must be UNMISTAKABLE from a true zero — a dead Meta token
rendering "$0 spend / $0 CPL" as real numbers is an ACTIONABLE lie (scale a "free"
ad, kill a "broken" winner). Contract:

  1. The engine folds every upstream degradation signal into result.degraded
     (spend source, entity map, contacts) — nothing carried-but-dropped.
  2. The board / roster / dossier payloads CARRY degraded[] + ok to the client.
  3. The client renders a DEGRADED chip + strip (source + reason) — never $0,
     never a '—' that reads as real-zero (JS/CSS contract tests).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attribution_engine as eng
from tests.test_attribution import HDR, RES_A, contact, resolver, row
from tests.test_ads_dashboard import _client, _fake_result

JS = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "js", "adsapp.js")
CSS = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "css", "adsapp.css")


def _js():
    with open(JS) as f:
        return f.read()


# ── 1 · the engine folds every degradation signal ────────────────────────────

def test_compute_folds_meta_entity_and_contact_degradation(monkeypatch):
    """Meta spend dead + entity map dead + GHL contacts empty → ALL THREE land in
    result.degraded and ok is False. Root cause of F5: signals produced at source
    were carried in payloads but dropped before the UI."""
    import attribution_join, meta_entities, leads_view
    monkeypatch.setattr(attribution_join, "sync_contacts", lambda: {"at": None, "total": 0})
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: [])
    monkeypatch.setattr(meta_entities, "refresh_entity_map",
                        lambda force=False: {"ads": {}, "extras": {},
                                             "degraded": [{"metric": "meta_entities",
                                                           "reason": "token dead (test)"},
                                                          {"metric": "meta_entities",
                                                           "reason": "token dead (test)"}]})
    monkeypatch.setattr(meta_entities, "refresh_ad_spend_daily", lambda: {})
    monkeypatch.setattr(meta_entities, "spend_by_ad_in_range",
                        lambda s, e: {"ads": {}, "source": None,
                                      "degraded": [{"metric": "meta_ad_spend_range",
                                                    "reason": "Meta API 401 (test)"}]})
    monkeypatch.setattr(eng, "_tracker_rows_clean",
                        lambda: [HDR, row("Lead One", "l1@x.com")])
    monkeypatch.setattr(leads_view, "count_leads", lambda w0, w1: {"count": 1})
    import meta_spend
    monkeypatch.setattr(meta_spend, "spend_in_range",
                        lambda s, e: (_ for _ in ()).throw(RuntimeError("Meta dead")))
    r = eng.compute(days=30, force=True)
    metrics = [d.get("metric") for d in r["degraded"]]
    assert "meta_ad_spend_range" in metrics       # dead spend source is IN the payload
    assert "meta_entities" in metrics             # entity-map degradation folded in
    assert metrics.count("meta_entities") == 1    # deduped (stale-store repeats collapse)
    assert "attribution" in metrics               # empty contacts stated
    assert r["ok"] is False                       # ok:true only when degraded[] empty


# ── 2 · payload carriage (board / roster / dossier) ──────────────────────────

def _degraded_result(days=30, basis="cohort"):
    r = _fake_result()
    r["window"] = {"start": "s", "end": "e", "days": days}
    r["basis"] = basis
    r["degraded"] = [{"metric": "meta_ad_spend_range", "reason": "Meta token dead (test)"}]
    r["ok"] = False
    return r


def test_board_payload_carries_degraded_and_ok(monkeypatch):
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    monkeypatch.setattr("attribution_engine.compute",
                        lambda **kw: _degraded_result(kw.get("days", 30),
                                                      kw.get("basis", "cohort")),
                        raising=True)
    monkeypatch.setattr("dashboard.ads._prefetch_adjacent", lambda d, b: None, raising=True)
    d = c.get("/ads/api/board?days=30").get_json()
    assert d["degraded"] and d["degraded"][0]["metric"] == "meta_ad_spend_range"
    assert d["ok"] is False


def test_roster_payload_carries_degraded(monkeypatch):
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    monkeypatch.setattr("attribution_engine.compute",
                        lambda **kw: _degraded_result(), raising=True)
    monkeypatch.setattr("attribution_join.load_contacts", lambda: [], raising=True)
    monkeypatch.setattr("dashboard.ads._ghl_notes_for", lambda ids: {}, raising=True)
    d = c.get("/ads/api/roster?days=30&creative=120000000000000001&stage=leads").get_json()
    assert d["degraded"] and d["degraded"][0]["metric"] == "meta_ad_spend_range"


def test_dossier_payload_carries_degraded(monkeypatch):
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    monkeypatch.setattr("attribution_engine.compute",
                        lambda **kw: _degraded_result(), raising=True)
    monkeypatch.setattr("attribution_engine._tracker_rows_clean", lambda: [HDR], raising=True)
    monkeypatch.setattr("attribution_join.load_contacts", lambda: [], raising=True)
    d = c.get("/ads/api/dossier?days=30&creative=120000000000000001").get_json()
    assert d["degraded"] and d["degraded"][0]["metric"] == "meta_ad_spend_range"


# ── 3 · the render contract (JS/CSS) ─────────────────────────────────────────

def test_js_renders_degraded_chip_never_zero():
    js = _js()
    # the primitives exist
    assert "degradedEntryFor" in js and "degradedChip" in js and "degradedStrip" in js
    assert "adx-degraded" in js
    # every spend-derived column is in the poisoned set
    for col in ("cost_per_lead", "cost_per_qualified", "cost_per_set",
                "cost_per_close", "cost_per_close_loaded", "ltgp_cac"):
        assert col in js[js.index("SPEND_COLS"):js.index("SPEND_COLS") + 300], col
    # grid cells consult degradation BEFORE money() rendering
    assert js.index("degradedEntryFor(c.k)") < js.index("c.money ? money(v) : num(v)")
    # the banner carries the strip on both branches (normal + no-leads)
    assert js.count("degradedStrip(state.board.degraded)") >= 2
    # headline spend tile consults degradation
    assert "degradedEntryFor('spend')" in js
    # dossier money legs + roster head consult degradation
    assert "dmoney('cost_per_lead'" in js and "degradedStrip(d.degraded)" in js


def test_js_hygiene_block_never_silently_vanishes():
    js = _js()
    i = js.index("function renderHygiene")
    block = js[i:i + 900]
    assert "unavailable" in block           # a dead sweep states itself
    assert "display = 'none'; return" not in block


def test_sales_summary_export_states_degradation():
    """F5 family: the exported sales summary is built from the snapshot — if the
    snapshot is degraded the export must say so, not read as clean truth."""
    from dashboard.sales_summary import build_sales_summary
    txt = build_sales_summary({"sales": {}, "degraded": [
        {"metric": "ghl_pull", "reason": "GHL API down (test)"}]}, 30)
    assert "DEGRADED" in txt and "ghl_pull" in txt
    clean = build_sales_summary({"sales": {}}, 30)
    assert "DEGRADED" not in clean


def test_css_degraded_styles_exist():
    with open(CSS) as f:
        css = f.read()
    assert ".adx-degraded" in css and ".adx-degraded-strip" in css
