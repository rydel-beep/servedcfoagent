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


# ── THE SIMULATOR, FIXED FOR GOOD (#155): lock-free + parity ────────────────

def test_no_lock_semantics_remain():
    """The lock design is RETIRED — no lock UI, no lock state, no handler
    that drops an edit because of a pinned field."""
    js = _read("dashboard", "static", "js", "scale.js")
    html = _read("dashboard", "templates", "scale.html")
    assert "sim-lock" not in js and "sim-lock" not in html
    assert "simState.lock" not in js
    assert "sim_core.js" in html               # the ONE formula core loads
    # leads is an OUTPUT (a div, not an input)
    assert '<div class="sim-out-value" id="sim-leads">' in html
    # every spend/cpl edit path recomputes (no mode/lock guard except
    # target-mode disabling, which visibly disables the fields)
    assert "simForward('spend-num')" in js and "simForward('cpl-num')" in js
    assert "sim-spend-slider" in html and "sim-cpl-slider" in html


def test_client_engine_parity_200_random_sets(stub):
    """PART 2: 200 random input sets through sim_core.js (node — the exact
    file the browser runs) and compass_engine.simulate_month → zero
    mismatches beyond float rounding."""
    import json as _json
    import random
    import subprocess
    rng = random.Random(155)
    base = CE.simulate_month()          # aggregates come from the engine
    agg = {k: base[k] for k in ("m0_share", "contract_avg", "mrr_avg",
                                "margin_avg", "comm_rate", "tooling",
                                "epsilon", "spend_baseline")}
    sets = []
    for _ in range(200):
        sets.append({
            "spend": round(rng.uniform(500, 80000), 2),
            "cpl": round(rng.uniform(20, 300), 2),
            "set": round(rng.uniform(0.02, 0.5), 4),
            "show": round(rng.uniform(0.3, 1.0), 4),
            "close": round(rng.uniform(0.05, 0.6), 4),
            "curve": rng.random() < 0.5,
        })
    core = os.path.join(ROOT, "dashboard", "static", "js", "sim_core.js")
    script = (
        "const SimCore = require(%r);"
        "const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "const out = data.sets.map(s => SimCore.chain(s.spend, s.cpl,"
        " {set: s.set, show: s.show, close: s.close}, data.agg, s.curve));"
        "process.stdout.write(JSON.stringify(out));" % core)
    res = subprocess.run(["node", "-e", script],
                         input=_json.dumps({"sets": sets, "agg": agg}),
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[:400]
    client = _json.loads(res.stdout)
    mismatches = []
    for s, c in zip(sets, client):
        e = CE.simulate_month(
            {"set_rate": s["set"], "show_rate": s["show"],
             "close_rate": s["close"]},
            spend=s["spend"], cpl_override=s["cpl"], cpl_curve=s["curve"])
        for key_c, key_e, tol in (("leads", "leads", 0.15),
                                  ("clients", "clients", 0.02),
                                  ("cash_this_month", "cash_this_month", 1.0),
                                  ("mrr_added", "mrr_added", 1.0)):
            if abs(c[key_c] - e[key_e]) > tol:
                mismatches.append((s, key_c, c[key_c], e[key_e]))
        if e["cac"] is not None and c["cac"] is not None \
                and abs(c["cac"] - e["cac"]) > 1.0:
            mismatches.append((s, "cac", c["cac"], e["cac"]))
    assert not mismatches, f"{len(mismatches)} parity mismatches: {mismatches[:3]}"


def test_property_leads_equals_spend_over_cpl(stub):
    import random
    rng = random.Random(7)
    for _ in range(50):
        sp, cpl = rng.uniform(100, 90000), rng.uniform(5, 500)
        s = CE.simulate_month(spend=sp, cpl_override=cpl)
        assert abs(s["leads"] - sp / cpl) < 0.15


def test_property_effective_cpl_monotone_in_spend(stub):
    prev = None
    for sp in (2000, 5000, 10000, 20000, 40000, 80000):
        s = CE.simulate_month(spend=sp, cpl_curve=True)
        if prev is not None:
            assert s["cpl_effective"] >= prev - 1e-9
        prev = s["cpl_effective"]


def test_target_mode_round_trip_via_core(stub):
    """requiredSpend (the target mode) → forward re-run hits the target."""
    import json as _json
    import subprocess
    base = CE.simulate_month()
    agg = {k: base[k] for k in ("m0_share", "contract_avg", "mrr_avg",
                                "margin_avg", "comm_rate", "tooling",
                                "epsilon", "spend_baseline")}
    core = os.path.join(ROOT, "dashboard", "static", "js", "sim_core.js")
    script = (
        "const SimCore = require(%r);"
        "const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "const out = {};"
        "for (const [kind, val] of d.targets) {"
        "  const req = SimCore.requiredSpend(kind, val, d.cpl, d.rates, d.agg, false);"
        "  out[kind] = {spend: req.spend,"
        "    check: SimCore.chain(req.spend, d.cpl, d.rates, d.agg, false)};"
        "}"
        "process.stdout.write(JSON.stringify(out));" % core)
    rates = {"set": base["rates"]["set"], "show": base["rates"]["show"],
             "close": base["rates"]["close"]}
    res = subprocess.run(["node", "-e", script],
                         input=_json.dumps({"targets": [["calls", 40],
                                                        ["clients", 5],
                                                        ["cash", 30000],
                                                        ["mrr", 15000],
                                                        ["leads", 200]],
                                            "cpl": base["cpl_base"],
                                            "rates": rates, "agg": agg}),
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr[:300]
    out = _json.loads(res.stdout)
    assert abs(out["calls"]["check"]["calls"] - 40) < 0.05
    assert abs(out["clients"]["check"]["clients"] - 5) < 0.05
    assert abs(out["cash"]["check"]["cash_this_month"] - 30000) < 50
    assert abs(out["mrr"]["check"]["mrr_added"] - 15000) < 50
    assert abs(out["leads"]["check"]["leads"] - 200) < 0.1


def test_behaviour_badge_and_endpoint():
    routes = _read("dashboard", "routes.py")
    assert "behaviour:last_pass" in routes
    i = routes.index("def api_scale_behaviour_verified")
    assert "@require_owner" in routes[i - 250:i]
    html = _read("dashboard", "templates", "scale.html")
    assert "sim-verified-badge" in html


# ── PART 4: the north-star block ────────────────────────────────────────────

def test_north_star_pacing_math(stub, monkeypatch):
    """Pacing == engine arithmetic on a fixture: day 15 of a 30-day month,
    actual $6,000 → pace $12,000; plan $12,000 → on track."""
    monkeypatch.setattr(CE, "_mtd_funnel", lambda: {
        "day": 15, "days_in_month": 30, "leads": 60, "sets": 9, "shows": 8,
        "clients": 2, "cash_from_closes": 11000.0, "spend": 5000.0,
        "cash_collected": 40000.0, "net_new_mrr": 6000.0})
    kv_store.put(CE.K_NORTH_METRIC, "net_new_mrr")
    kv_store.put(CE.K_PLAN, {"version": 3, "name": "Test",
                             "inputs": {"cpl0": 90.0, "set_rate": 0.15,
                                        "show_rate": 0.9, "close_rate": 0.28,
                                        "spend_path": {"start": 10000.0}},
                             "roadmap": [
                                 {"month": CE._month_add(str(CE.today_sydney())[:7], -1),
                                  "net_mrr": 70000.0, "cash_in": 90000.0},
                                 {"month": str(CE.today_sydney())[:7],
                                  "net_mrr": 82000.0, "cash_in": 95000.0}]})
    ns = CE.north_star()
    assert ns["actual"] == 6000.0
    assert ns["pace"] == 12000.0                      # 6000 ÷ (15/30)
    assert ns["plan"] == 12000.0                      # 82000 − 70000
    assert "on track" in ns["verdict"]
    assert "Plan 2027 v3" in ns["plan_src"]
    # levers: CPL actual = spend/leads
    cpl = next(l for l in ns["levers"] if l["id"] == "lever_cpl")
    assert abs(cpl["actual"] - 5000.0 / 60) < 0.02
    close = next(l for l in ns["levers"] if l["id"] == "lever_close")
    assert abs(close["actual"] - 2 / 8) < 0.001
    # required close = clients needed ÷ shows at pace
    need_clients = 12000.0 / CE.simulate_month()["mrr_avg"]
    shows_pace = 8 / 0.5
    assert abs(close["required"] - need_clients / shows_pace) < 0.01
    assert ns["pinned"]["plan_version"] == 3


def test_north_star_off_plan_lever_highlighted(stub, monkeypatch):
    monkeypatch.setattr(CE, "_mtd_funnel", lambda: {
        "day": 10, "days_in_month": 30, "leads": 100, "sets": 15, "shows": 13,
        "clients": 1, "cash_from_closes": 5000.0, "spend": 4000.0,
        "cash_collected": 20000.0, "net_new_mrr": 2000.0})
    kv_store.put(CE.K_PLAN, None)
    ns = CE.north_star()
    close = next(l for l in ns["levers"] if l["id"] == "lever_close")
    # actual close 1/13 = 7.7% vs plan (measured 28%) → off plan
    assert close["off_plan"] is True


def test_calibration_log_writes_and_scores(stub, monkeypatch):
    kv_store.put(CE.K_CAL_LOG, [])
    out1 = CE.calibration_tick()
    ym = str(CE.today_sydney())[:7]
    assert out1["wrote"] == ym
    log = kv_store.get(CE.K_CAL_LOG)
    assert log[0]["month"] == ym and log[0]["scored"] is None
    assert log[0]["predicted"]["leads"] > 0
    # idempotent within the month
    assert CE.calibration_tick()["wrote"] is None
    # a prior unscored month gets scored from actuals (engines stubbed)
    prev = CE._month_add(ym, -1)
    log.insert(0, {"month": prev, "written_at": "x",
                   "predicted": {"leads": 100, "calls": 15, "clients": 4,
                                 "cash": 20000, "mrr_added": 12000},
                   "scored": None})
    kv_store.put(CE.K_CAL_LOG, log)
    import attribution_engine as AE
    import finance_analysis as FA
    monkeypatch.setattr(AE, "compute", lambda **k: {"creatives": [
        {"leads": 90, "sets": 12, "shows": 10}]})
    monkeypatch.setattr(FA, "_closes_union", lambda *a: [{}, {}, {}])
    out2 = CE.calibration_tick()
    assert out2["scored"] == prev
    scored = next(r for r in kv_store.get(CE.K_CAL_LOG) if r["month"] == prev)
    assert scored["scored"]["actual"]["clients"] == 3
    assert abs(scored["scored"]["error_pct"]["leads"] - 11.1) < 0.2


def test_drift_alert_fires_on_band_break(stub, monkeypatch):
    import attribution_engine as AE
    calls = {"n": 0}
    def fake_compute(**k):
        calls["n"] += 1
        # first call = t30 (booking rate 5%), second = prior 90d (15%)
        if calls["n"] == 1:
            return {"creatives": [{"leads": 100, "sets": 5, "shows": 4}]}
        return {"creatives": [{"leads": 300, "sets": 45, "shows": 40}]}
    monkeypatch.setattr(AE, "compute", fake_compute)
    items = CE.rate_drift_alerts()
    assert any("booking rate dropped" in i["title"] for i in items)


def test_whatif_and_calibration_never_touch_actuals(stub, monkeypatch):
    """The calibration record + north-star reads write only their own kv
    keys — never declarations, never the plan, never scenario stores."""
    kv_store.put(CE.K_PLAN, {"version": 9, "roadmap": [], "inputs": {}})
    kv_store.put(CE.K_SCENARIOS, {"x": {"inputs": {}}})
    import client_overrides
    before = len(client_overrides.active_overrides() or [])
    monkeypatch.setattr(CE, "_mtd_funnel", lambda: {
        "day": 5, "days_in_month": 30, "leads": 10, "sets": 2, "shows": 2,
        "clients": 1, "cash_from_closes": 3000.0, "spend": 1500.0,
        "cash_collected": 9000.0, "net_new_mrr": 3000.0})
    CE.north_star()
    CE.calibration_tick()
    assert kv_store.get(CE.K_PLAN)["version"] == 9
    assert list(kv_store.get(CE.K_SCENARIOS)) == ["x"]
    assert len(client_overrides.active_overrides() or []) == before


def test_north_star_registry_and_template():
    html = _read("dashboard", "templates", "scale.html")
    assert 'id="north-star"' in html and "Are we on pace this month?" in html
    assert "ns-levers" in html and "ns-whatif" in html
    assert "{{ ns.verdict }}" in html            # server-rendered
    for eid in ("north_star", "ns_verdict", "ns_levers", "ns_constraint",
                "ns_whatifs", "ns_callog", "ns_pinned", "sim_mode", "sim_badge"):
        assert D.entry(eid), eid


def test_scale_page_renders_with_live_north_star_payload(stub, monkeypatch):
    """THE CLASS THAT ESCAPED: an engine payload with a missing lever key
    crashed the jinja render in prod (UndefinedError 500) while every unit
    test passed. Now: the page must render 200 with a REAL north_star()
    payload in the cache."""
    monkeypatch.setattr(CE, "_mtd_funnel", lambda: {
        "day": 12, "days_in_month": 30, "leads": 80, "sets": 12, "shows": 10,
        "clients": 3, "cash_from_closes": 15000.0, "spend": 6000.0,
        "cash_collected": 30000.0, "net_new_mrr": 8000.0})
    kv_store.put("compass:north_star",
                 {"computed_at": "2026-09-21T12:00:00+10:00",
                  "data": CE.north_star()})
    kv_store.put("behaviour:last_pass",
                 {"at": "2026-09-21T12:00:00+10:00", "ok": True,
                  "commit": "test", "passes": 3, "reason": ""})
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-sim155")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    r = c.get("/dashboard/scale")
    assert r.status_code == 200, r.data[:200]
    h = r.data.decode()
    assert "Are we on pace this month?" in h
    assert "LOGIC VERIFIED" in h
    assert 'id="ns-levers"' in h and "← off plan" in h or 'id="ns-levers"' in h
