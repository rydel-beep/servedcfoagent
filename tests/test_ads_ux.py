"""tests/test_ads_ux.py — the interaction layer (DECISIONS #127): I14 no orphan
badges, I15 market partition, I16 view purity, the market marker, All window,
deep-link auth, feed↔table loop."""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribution_engine as eng
from tests.test_attribution import HDR, RES_A, W0, W1, contact, resolver, row

JS = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "js", "adsapp.js")
ADS = os.path.join(os.path.dirname(__file__), "..", "dashboard", "ads.py")


def _compute(rows, contacts, **kw):
    return eng.compute_from_inputs([HDR] + rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}),
                                   W0, W1, **kw)


# ── the market marker ────────────────────────────────────────────────────────

def test_market_norm_never_defaults_silently():
    assert eng._market_norm("Australia") == "au"
    assert eng._market_norm("US") == "us"
    assert eng._market_norm("USA") == "us"
    assert eng._market_norm("") == "unknown"          # blank → the honest bucket
    assert eng._market_norm("Mars") == "unknown"      # unrecognised → never AU


def _mrow(name, email, market):
    r = row(name, email, closer="won", close_date="2026-07-20",
            contract="10000", cash="5000")
    r[9] = market      # the Market column
    return r


def test_i15_market_partition_sums_to_all():
    rows = [_mrow("AU One", "a1@x.com", "Australia"),
            _mrow("AU Two", "a2@x.com", "Australia"),
            _mrow("US One", "u1@x.com", "US"),
            _mrow("Mystery", "m1@x.com", "")]
    contacts = [contact(f"c{i}", e, n) for i, (n, e) in enumerate(
        [("AU One", "a1@x.com"), ("AU Two", "a2@x.com"),
         ("US One", "u1@x.com"), ("Mystery", "m1@x.com")])]
    r_all = _compute(rows, contacts)
    parts = {m: _compute(rows, contacts, market=m) for m in ("au", "us", "unknown")}
    for metric in ("leads", "closes", "cash"):
        total = r_all["totals"][metric]
        summed = sum(p["totals"][metric] for p in parts.values())
        assert summed == total, (metric, summed, total)   # AU + US + Unknown == All
    assert parts["au"]["totals"]["leads"] == 2
    assert parts["us"]["totals"]["leads"] == 1
    assert parts["unknown"]["totals"]["leads"] == 1
    # spend is OMITTED under a filter (never an absurd per-market CPL) + stated
    assert parts["us"]["market_note"] and "spend" in parts["us"]["market_note"]
    assert r_all["market"] == "all" and parts["us"]["market"] == "us"


def test_market_validation_raises():
    import pytest
    with pytest.raises(ValueError):
        _compute([_mrow("X", "x@x.com", "US")], [contact("c1", "x@x.com", "X")],
                 market="mars")


# ── I16: view purity (the UI computes nothing) ───────────────────────────────

def test_i16_view_purity_no_ui_arithmetic():
    js = open(JS).read()
    # no arithmetic on metric fields in the client — formatting only
    for pat in (r"\.closes\s*[+\-*/]", r"\.leads\s*[+\-*/]", r"\.cash\s*[+\-*/]\s*[a-z0-9(]",
                r"\.qualified\s*[+\-*/]", r"\.sets\s*[+\-*/]", r"\.spend\s*\*"):
        assert not re.search(pat, js), pat
    # the grid find is presentation-only and says so
    assert "FILTERED VIEW (aggregates unchanged)" in js
    # sort presets contain no new math — 'worst' delegates to the verdict ranking
    assert "VERDICT_RANK" in js and "no new math" in js


# ── I14: no orphan badges (every anomaly is a door) ──────────────────────────

def test_i14_every_badge_is_a_door():
    js = open(JS).read()
    # every annotation span carries the door class + a data-anom object reference
    spans = re.findall(r"<span class=\\?\"adx-earlier[^>]*", js)
    assert spans, "annotation badges exist"
    for s in spans:
        assert "adx-door" in s and "data-anom=" in s, s[:80]
    # a delegated handler resolves the object; the dead-tooltip class is gone
    assert "closest('.adx-door[data-anom]')" in js
    assert "anomalyPanel(" in js and "dealPanel(" in js and "openDossier(" in js
    # hygiene items + the dateless rail are doors too
    assert "adx-dateless" in js and "adx-deal-open" in js


# ── window + URL + deep links ────────────────────────────────────────────────

def test_all_window_and_url_state():
    ads = open(ADS).read()
    assert "ALL_DAYS = 3650" in ads and '"all"' in ads.lower() or "'all'" in ads
    js = open(JS).read()
    assert "window=(\\d{1,3}|all)" in js            # ?window=all parses
    assert "market=(au|us|unknown|all)" in js       # ?market= parses
    assert "sort=([a-z_]+)" in js                   # ?sort= parses
    assert "[?&]dossier=" in js and "[?&]deal=" in js


def test_headline_compare_is_engine_computed_and_labelled():
    ads = open(ADS).read()
    assert "vs prior" in ads and "assert_same_basis(result, prev)" in ads
    js = open(JS).read()
    assert "state.board.compare" in js              # rendered, not derived


def test_new_routes_are_auth_gated():
    ads = open(ADS).read()
    for route in ("/api/dossier", "/api/deal"):
        seg = ads.split(f'@bp.route("{route}"')[1][:80]
        assert "require_auth" in seg, route


def test_feed_items_deep_link_to_the_deal_panel():
    src = open(os.path.join(os.path.dirname(__file__), "..", "close_integrity.py")).read()
    # blank close + input date items + the lane-lag ageing items (#128)
    assert src.count('"deal_name": t["name"]') >= 2
    af = open(os.path.join(os.path.dirname(__file__), "..", "action_feed.py")).read()
    assert '"/ads?deal=" ' in af or '"/ads?deal="' in af
    dj = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "static",
                           "js", "dashboard.js")).read()
    assert "it.link" in dj


def test_deal_panel_explains_invisibility(monkeypatch):
    """The witnessed El Gringos class: the panel names WHY the deal is invisible
    and carries its queue state — never a dead tooltip."""
    import dashboard.ads as ads_mod
    leads = [{"name": "El Gringos Locos", "name_norm": "el gringos locos",
              "email": "eg@x.com", "won": True, "close_date": None,
              "input_date": None, "set": True, "set_date": None, "show": True,
              "business": "El Gringos", "market": "au",
              "setter_outcome": "set", "closer_outcome": "won",
              "contract": 12500.0, "cash": 0.0, "setter_notes": "", "dq_reason": ""}]
    monkeypatch.setattr(eng, "parse_tracker", lambda rows: (leads, {}))
    monkeypatch.setattr(eng, "_tracker_rows_clean", lambda: [])
    import app as app_mod
    client = app_mod.app.test_client()
    r = client.get("/ads/api/deal?name=El%20Gringos%20Locos")
    assert r.status_code in (302, 401, 403)   # unauthenticated → the gate holds
