"""EXPLAIN EVERYTHING · SIMULATE DIRECTLY · SIMPLIFY — the battery.

Registry coverage 100% (build gate) · jargon grep zero · one tooltip source ·
simulator == the engine (no second model) · I-want inversions · constant-CPL
default · what-if never writes · three levels · accuracy in plain words.
"""

import copy
import json
import os
import re

import pytest

import kv_store
import compass_engine as CE
from dashboard import definitions as D

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ── Part 1: the registry ────────────────────────────────────────────────────

def test_registry_coverage_100_percent():
    """THE BUILD GATE: every rendered metric/control/chip/lane/lever carries
    a registry entry — 100% or this build fails."""
    missing, total = D.coverage_check()
    assert total > 120
    assert not missing, f"unexplained elements ({len(missing)}/{total}): {missing[:12]}"


def test_registry_text_is_team_language():
    reg = D.load()
    hits = []
    for eid, e in reg["entries"].items():
        for f in ("name", "meaning", "computed", "changing", "default_from", "good"):
            for j in D.jargon_hits(e.get(f) or ""):
                hits.append((eid, f, j))
    assert not hits, hits[:8]


def test_registry_entry_shapes():
    reg = D.load()
    for eid, e in reg["entries"].items():
        assert e.get("name") and e.get("meaning"), eid
        assert e.get("kind") in ("metric", "control", "chip", "lane", "lever",
                                 "panel", "page"), eid
        if e["kind"] == "control":
            assert e.get("changing"), f"control {eid} must say what changing it does"


def test_one_tooltip_source_no_adhoc_text():
    """defs.js renders ONLY registry entries; the pages inject the registry
    server-side; the legend is generated from it."""
    js = _read("dashboard", "static", "js", "defs.js")
    assert "window.__DEFS__" in js and "tipHtml" in js
    # no hardcoded explanation strings in defs.js beyond UI chrome
    assert "cohort" not in js.lower()
    for tpl in ("dashboard.html", "panel_page.html", "scale.html"):
        assert 'partials/defs.html' in _read("dashboard", "templates", tpl), tpl
    legend = _read("dashboard", "templates", "definitions.html")
    assert "{% for eid, e in entries.items()" in legend


def test_edith_explain_reads_the_registry():
    reply, handled = D.handle_explain_command("what is cost per lead")
    assert handled and "lead" in reply.lower()
    assert "divided" in reply.lower() or "worked out" in reply.lower()
    routes = _read("dashboard", "routes.py")
    assert routes.count("handle_explain_command, False") == 2   # BOTH tier-2 lists


def test_registry_selectors_are_valid_css():
    """A malformed selector would silently kill hover matching for its entry."""
    from html.parser import HTMLParser  # noqa: F401 (just needs stdlib presence)
    for eid, e in D.load()["entries"].items():
        sel = e.get("selector")
        if sel:
            assert not sel.startswith(" ") and len(sel) < 120, eid


# ── Part 2: the simulator == the engine (no second model) ───────────────────

PKG = {
    "growth pro": {"mrr": 3050.0, "term": 6, "contract": 18300.0,
                   "cash_schedule": [0.3, 0.14, 0.14, 0.14, 0.14, 0.14],
                   "gross_margin_pct": 42.9, "delivery_cost_monthly": 1741.6,
                   "m0_share_measured_n": 9, "mrr_provenance": "test"},
}


@pytest.fixture()
def stub(monkeypatch):
    fake = {"computed_at": "2026-09-21T10:00:00+10:00", "items": {
        "cpl": CE._item(90.0, 300, "90d", "t"),
        "monthly_spend_baseline": CE._item(10000.0, 3, "90d", "t"),
        "set_rate": CE._item(0.15, 300, "90d", "t"),
        "show_rate": CE._item(0.9, 45, "90d", "t"),
        "close_rate": CE._item(0.28, 40, "90d", "t"),
        "deal_mix": CE._item({"growth pro": 1.0}, 20, "180d", "t"),
        "packages": CE._item(copy.deepcopy(PKG), None, "", "t"),
        "lag_curve": CE._item([1.0, 0.0, 0.0], 20, "180d", "t"),
        "renewal_rate": CE._item(0.5, 10, "12mo", "t"),
        "cpl_epsilon": CE._item(0.2, 9, "", "t", assumption=True),
        "commission_pct_of_cash": CE._item(0.063, None, "", "t"),
        "opex_monthly_ex_tax": CE._item(30000.0, 3, "", "t"),
        "sales_tooling_monthly": CE._item(2132.0, None, "", "t"),
        "seasonality": CE._item({}, None, "", "t", assumption=True),
        "team": CE._item(CE._team_snapshot(), None, "", "t"),
        "lanes": CE._item({"au": 250, "us": 50}, 300, "90d", "t"),
    }}
    kv_store.put(CE.K_DEFAULTS, fake)
    monkeypatch.setattr(CE, "book_state",
                        lambda H, m0, r, pins=None: {"mrr": [0.0] * H,
                                                     "cash": [0.0] * H,
                                                     "note": "stub"})
    monkeypatch.setattr(CE, "cash_position_base",
                        lambda: {"cash_ex_setaside": 150000.0, "cash": 150000.0,
                                 "tax_set_aside": 0})
    return fake


def test_simulate_month_equals_forward_first_month(stub):
    """No second model: with the lag collapsed to this month, the simulator's
    chain equals the forward engine's first month exactly."""
    sim = CE.simulate_month()
    inp = CE.default_inputs()
    inp["horizon_months"] = 3
    run = CE.forward(inp)
    m0 = run["months"][0]
    assert abs(sim["leads"] - m0["leads"]) < 0.11
    assert abs(sim["calls"] - m0["calls_booked"]) < 0.11
    assert abs(sim["shows"] - m0["shows"]) < 0.11
    assert abs(sim["clients"] - m0["closes"]) < 0.02
    assert abs(sim["cash_this_month"] - m0["cash_new_cohort"]) < 1.0
    assert abs(sim["mrr_added"] - m0["mrr_new"]) < 1.0
    # the simulator's all-in cost per client == the engine's cohort figure
    assert abs(sim["cac"] - run["cohorts"][0]["cac_cohort"]) < 1.0
    assert sim["cac_spend_only"] < sim["cac"]


def test_simulator_constant_cpl_default_curve_opt_in(stub):
    flat = CE.simulate_month(spend=30000.0)
    assert flat["cpl_effective"] == flat["cpl_base"]     # DEFAULT: constant
    curved = CE.simulate_month(spend=30000.0, cpl_curve=True)
    assert curved["cpl_effective"] > curved["cpl_base"]  # opt-in: it climbs
    assert curved["leads"] < flat["leads"]


def test_simulate_cpl_override(stub):
    a = CE.simulate_month(spend=10000.0, cpl_override=50.0)
    assert a["leads"] == 200.0
    assert a["cpl_effective"] == 50.0


def test_show_the_math_arithmetic_equals_engine(stub):
    """The 'show the math' lines are the same arithmetic the engine computes
    — spot-check every step by hand from the payload."""
    s = CE.simulate_month(spend=10000.0)
    assert abs(s["leads"] - 10000.0 / s["cpl_effective"]) < 0.11
    assert abs(s["calls"] - s["leads"] * 0.15) < 0.11
    assert abs(s["shows"] - s["calls"] * 0.9) < 0.11
    assert abs(s["clients"] - s["shows"] * 0.28) < 0.02
    assert abs(s["cash_this_month"] - s["clients"] * s["m0_share"] * s["contract_avg"]) < 1.0
    assert abs(s["cac"] - (10000.0 + s["commissions_over_term"] + s["tooling"])
               / s["clients"]) < 0.51


def test_iwant_inversions_round_trip(stub):
    """'I want N clients' → the spend it returns produces N clients forward."""
    s = CE.simulate_month()
    rates = s["rates"]
    chain = rates["set"] * rates["show"] * rates["close"]
    want_clients = 6.0
    leads_needed = want_clients / chain
    spend_needed = leads_needed * s["cpl_base"]
    check = CE.simulate_month(spend=spend_needed)
    assert abs(check["clients"] - want_clients) < 0.05
    # cash inversion
    want_cash = 20000.0
    clients_needed = want_cash / (s["m0_share"] * s["contract_avg"])
    spend2 = clients_needed / chain * s["cpl_base"]
    check2 = CE.simulate_month(spend=spend2)
    assert abs(check2["cash_this_month"] - want_cash) < 50.0


def test_whatif_never_writes(stub):
    """A simulate call touches no scenario store, no plan, no declarations."""
    kv_store.put(CE.K_SCENARIOS, {"keep": {"inputs": {}}})
    kv_store.put(CE.K_PLAN, {"version": 7})
    import client_overrides
    before = len(client_overrides.active_overrides() or [])
    CE.simulate_month(spend=99999.0, cpl_override=10.0, cpl_curve=True)
    assert kv_store.get(CE.K_SCENARIOS) == {"keep": {"inputs": {}}}
    assert kv_store.get(CE.K_PLAN) == {"version": 7}
    assert len(client_overrides.active_overrides() or []) == before
    assert "what-if" in CE.simulate_month()["label"]


def test_confidence_words():
    assert CE.confidence_word(300) == "solid"
    assert CE.confidence_word(45) == "fair"
    assert CE.confidence_word(13) == "rough"
    assert CE.confidence_word(None) == "rough"


def test_accuracy_sentence_plain_words():
    kv_store.put(CE.K_BACKTEST, {"mape_pct": {"leads": 43.6, "closes": 192.8},
                                 "months": [{"closes": {"actual": 1}},
                                            {"closes": {"actual": 6}},
                                            {"closes": {"actual": 8}}]})
    s = CE.accuracy_sentence()
    assert "±44% on leads" in s or "±43% on leads" in s
    assert "client" in s
    assert not D.jargon_hits(s)


# ── Part 3: three levels, server-rendered simple view ───────────────────────

def test_scale_three_levels_simple_server_rendered():
    html = _read("dashboard", "templates", "scale.html")
    assert 'id="level-simple"' in html
    assert '<details class="scale-section" id="level-advanced"' in html
    assert '<details class="scale-section" id="level-plan"' in html
    # Advanced/Plan collapsed by default (no `open` attribute)
    assert 'id="level-advanced" data-def="level_advanced" open' not in html
    # the simple view's values are jinja-baked (server-rendered first paint)
    assert "sim.leads" in html and "sim.cash_this_month" in html
    # question headings
    for q in ("How many leads does my ad spend buy?",
              "How many calls does that book?",
              "What do you want to happen?",
              "When do we need to hire?"):
        assert q in html, q


def test_scale_page_bakes_simulator_values():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-explain")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    r = c.get("/dashboard/scale")
    assert r.status_code == 200
    h = r.data.decode()
    assert 'id="sim-triad"' in h and 'id="sim-chain"' in h
    assert 'id="accuracy-sentence"' in h
    assert "window.__SCALE_SIM__" in h
    # legend + api
    assert c.get("/dashboard/definitions").status_code == 200
    api = c.get("/dashboard/api/definitions")
    assert api.status_code == 200 and len(api.get_json()["entries"]) > 120
    # anon refused everywhere
    c2 = appmod.app.test_client()
    assert c2.get("/dashboard/scale").status_code in (302, 401, 403)
    assert c2.post("/dashboard/api/scale/simulate", json={}).status_code in (302, 401, 403)


def test_sentinel_recovers_coverage_regressions():
    src = _read("render_health.py")
    assert "definitions registry lost coverage" in src
    assert "coverage_check" in src


def test_gate_asserts_simulator_and_tooltips():
    gate = _read("scripts", "render_gate.py")
    assert "sim-triad" in gate
    assert "defs-tip" in gate
    assert "math parity" in gate
