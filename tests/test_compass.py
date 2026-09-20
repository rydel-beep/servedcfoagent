"""THE SCALING COMPASS — the verification battery.

Engine identities · solver round-trip · constraint naming · scenario law
(toggles never write declarations; plans never actuals) · burn ex-tax ·
cohort≠period CAC under lag · bands widen with small n · read-only law.
"""

import copy
import os
import re

import pytest

import kv_store
import compass_engine as CE

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


PKG = {
    "growth pro": {"mrr": 3050.0, "term": 6, "contract": 18300.0,
                   "cash_schedule": [0.3, 0.14, 0.14, 0.14, 0.14, 0.14],
                   "gross_margin_pct": 42.9, "delivery_cost_monthly": 1741.6,
                   "m0_share_measured_n": 9, "mrr_provenance": "test"},
}


@pytest.fixture()
def stub_defaults(monkeypatch):
    fake = {"computed_at": "2026-09-20T10:00:00+10:00", "items": {
        "cpl": CE._item(90.0, 300, "90d", "t"),
        "monthly_spend_baseline": CE._item(10000.0, 3, "90d", "t"),
        "set_rate": CE._item(0.15, 300, "90d", "t"),
        "show_rate": CE._item(0.9, 45, "90d", "t"),
        "close_rate": CE._item(0.28, 40, "90d", "t"),
        "deal_mix": CE._item({"growth pro": 1.0}, 20, "180d", "t"),
        "packages": CE._item(copy.deepcopy(PKG), None, "", "t"),
        "lag_curve": CE._item([0.5, 0.3, 0.2], 20, "180d", "t"),
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
    # stub book: flat $70k MRR
    monkeypatch.setattr(CE, "book_state",
                        lambda H, m0, r, pins=None: {"mrr": [70000.0] * H,
                                                     "cash": [70000.0] * H,
                                                     "note": "stub"})
    monkeypatch.setattr(CE, "cash_position_base",
                        lambda: {"cash_ex_setaside": 150000.0, "cash": 170000.0,
                                 "tax_set_aside": 20000.0})
    return fake


def _base_inputs(stub_defaults):
    inp = CE.default_inputs()
    inp["horizon_months"] = 14
    return inp


# ── identities ──────────────────────────────────────────────────────────────

def test_cash_schedule_sums_to_contract(stub_defaults):
    for pkg in (CE.measured_defaults()["items"]["packages"]["value"] or {}).values():
        assert abs(sum(pkg["cash_schedule"]) - 1.0) < 1e-6
        # schedule × contract == contract
        assert abs(sum(s * pkg["contract"] for s in pkg["cash_schedule"])
                   - pkg["contract"]) < 0.01


def test_measured_package_schedule_sums_exactly():
    out = CE._package_economics([{"cash": 5000, "contract": 18300}])
    for pkg in out.values():
        assert abs(sum(pkg["cash_schedule"]) - 1.0) < 1e-6


def test_lag_curve_normalised_in_forward(stub_defaults):
    inp = _base_inputs(stub_defaults)
    inp["lag_curve"] = [2.0, 1.0, 1.0]      # un-normalised on purpose
    run = CE.forward(inp)
    ev = sum(c["closes_eventual"] for c in run["cohorts"])
    realised_all = sum(m["closes"] for m in run["months"])
    # realised can trail eventual only by the lag tail beyond the horizon
    assert realised_all <= ev + 1e-6
    assert realised_all >= ev * 0.8


def test_month0_book_identity(monkeypatch):
    """book_state month-0 must equal the present truth: the assumed pool is
    PAYING today — attrition starts month 1 (k=0 factor is 1.0)."""
    fake_proj = {"months": ["October 2026", "November 2026", "December 2026"],
                 "committed": [50000.0, 40000.0, 30000.0],
                 "assumed_pool": [20000.0, 30000.0, 40000.0],
                 "oneoff_cash": [0.0, 0.0, 0.0],
                 "per_client": {}}
    import forward_projection
    monkeypatch.setattr(forward_projection, "project", lambda: fake_proj)
    b = CE.book_state(3, "2026-10", resign_rate=0.5, resign_pins={})
    assert b["mrr"][0] == 70000.0            # committed + FULL assumed at k=0
    assert b["mrr"][1] == 40000.0 + 30000.0 * 0.5


def test_toggle_moves_cliff_by_exactly_its_mrr(monkeypatch):
    """A scenario pin lifts exactly that client's MRR from the slider lane to
    continuation after its committed_until — and writes NOTHING."""
    fake_proj = {"months": ["October 2026", "November 2026", "December 2026"],
                 "committed": [50000.0, 40000.0, 40000.0],
                 "assumed_pool": [10000.0, 13000.0, 13000.0],
                 "oneoff_cash": [0.0, 0.0, 0.0],
                 "per_client": {"Bluebells Takeaway": {
                     "mrr_now": 3000.0, "committed_until": "October 2026"}}}
    import forward_projection
    monkeypatch.setattr(forward_projection, "project", lambda: fake_proj)
    import client_overrides
    before = len(client_overrides.active_overrides() or [])
    b_off = CE.book_state(3, "2026-10", 0.0, {})
    b_on = CE.book_state(3, "2026-10", 0.0, {"Bluebells Takeaway": True})
    # month 0: identical (still committed). months 1..: +exactly its MRR
    assert b_on["mrr"][0] == b_off["mrr"][0]
    assert round(b_on["mrr"][1] - b_off["mrr"][1], 2) == 3000.0
    assert round(b_on["mrr"][2] - b_off["mrr"][2], 2) == 3000.0
    after = len(client_overrides.active_overrides() or [])
    assert before == after                    # ZERO declarations created


def test_burn_excludes_tax(stub_defaults):
    """A BAS accrual month leaves OpEx unchanged — no tax term exists in the
    cost stack; the tax note rides BESIDE."""
    inp = _base_inputs(stub_defaults)
    run = CE.forward(inp)
    m = run["months"][3]
    expected_costs = (m["spend"] + m["commissions"] + m["opex_ex_tax"])
    assert abs(m["costs_total"] - expected_costs) < 0.01
    assert "tax" in (run["tax_beside"]["note"] or "").lower()
    src = _read("compass_engine.py")
    assert "costs = row[\"spend\"] + commissions + opex + hire_cost + delivery_var" in src


def test_capital_dip_is_min_of_path(stub_defaults):
    inp = _base_inputs(stub_defaults)
    run = CE.forward(inp)
    assert run["capital_dip"] == min(m["position"] for m in run["months"])


def test_cohort_and_period_cac_differ_under_lag(stub_defaults):
    inp = _base_inputs(stub_defaults)
    inp["spend_path"] = {"shape": "ramp", "start": 10000.0, "ramp_pct": 25.0}
    run = CE.forward(inp)
    coh = {c["lead_month"]: c["cac_cohort"] for c in run["cohorts"]}
    diffs = [abs(m["cac_period"] - coh[m["month"]])
             for m in run["months"][2:8]
             if m.get("cac_period") and coh.get(m["month"])]
    assert diffs and max(diffs) > 1.0         # they genuinely differ


def test_client_financed_check_from_m0_share(stub_defaults):
    inp = _base_inputs(stub_defaults)
    run = CE.forward(inp)
    m = next(m for m in run["months"] if m.get("cac_period"))
    cash30 = 0.3 * 18300.0                    # m0 share × contract
    assert abs(m["client_financed_check"] - round(cash30 / m["cac_period"], 2)) < 0.011


# ── solver ──────────────────────────────────────────────────────────────────

def test_solver_round_trip_hits_target(stub_defaults):
    inp = _base_inputs(stub_defaults)
    month = CE._month_add(inp["start_month"], 11)
    sol = CE.solve({"kind": "mrr", "month": month, "value": 95000.0}, inp)
    assert sol["feasible"] is True
    assert sol["achieved"] >= 95000.0
    assert sol["achieved"] <= 95000.0 * 1.10   # bisection tolerance
    assert "SCENARIO" in sol["label"]


def test_solver_infeasible_names_the_break(stub_defaults):
    inp = _base_inputs(stub_defaults)
    month = CE._month_add(inp["start_month"], 6)
    sol = CE.solve({"kind": "mrr", "month": month, "value": 10 ** 9}, inp)
    assert sol["feasible"] is False
    assert (sol["breaks_first"] or {}).get("name")
    assert sol["nearest"]["outcome"] > 0


# ── constraints: each fires alone, named with its number ────────────────────

def _run_with(stub, **over):
    inp = _base_inputs(stub)
    inp.update(over)
    return CE.forward(inp)


def test_constraint_cash_fires(stub_defaults, monkeypatch):
    monkeypatch.setattr(CE, "cash_position_base",
                        lambda: {"cash_ex_setaside": 5000.0, "cash": 5000.0,
                                 "tax_set_aside": 0})
    run = _run_with(stub_defaults, opex_monthly_ex_tax=120000.0)
    names = [m["binding_constraint"]["name"] for m in run["months"]]
    assert "CASH" in names
    why = next(m["binding_constraint"]["why"] for m in run["months"]
               if m["binding_constraint"]["name"] == "CASH")
    assert "$" in why                          # the number that made it binding


def test_constraint_leads_cpl_threshold(stub_defaults):
    run = _run_with(stub_defaults,
                    spend_path={"shape": "ramp", "start": 10000.0,
                                "ramp_pct": 60.0},
                    epsilon=0.9)
    names = [m["binding_constraint"]["name"] for m in run["months"]]
    assert "LEADS" in names
    why = next(m["binding_constraint"]["why"] for m in run["months"]
               if m["binding_constraint"]["name"] == "LEADS")
    assert "CPL" in why


def test_constraint_sales_capacity(stub_defaults):
    team = CE._team_snapshot()
    team["closers"] = 1
    team["throughput"] = dict(team["throughput"], calls_per_closer_month=5)
    run = _run_with(stub_defaults, team=team)
    assert any(m["binding_constraint"]["name"] == "SALES CAPACITY"
               for m in run["months"])


def test_constraint_delivery_capacity(stub_defaults):
    team = CE._team_snapshot()
    team["delivery"] = 1
    team["throughput"] = dict(team["throughput"], clients_per_delivery=2)
    # huge hire lead time so auto-hires can't relieve it inside the horizon
    run = _run_with(stub_defaults, team=team, hire_lead_weeks=200)
    assert any(m["binding_constraint"]["name"] == "DELIVERY CAPACITY"
               for m in run["months"])


def test_constraint_retention_book_shrinks(stub_defaults, monkeypatch):
    monkeypatch.setattr(CE, "book_state",
                        lambda H, m0, r, pins=None: {
                            "mrr": [70000.0 - 8000.0 * k for k in range(H)],
                            "cash": [70000.0 - 8000.0 * k for k in range(H)],
                            "note": "stub"})
    run = _run_with(stub_defaults,
                    spend_path={"shape": "flat", "start": 300.0})
    assert any(m["binding_constraint"]["name"] == "RETENTION"
               for m in run["months"])


# ── team: hires ─────────────────────────────────────────────────────────────

def test_hire_card_dated_by_lead_time_and_costs_flow(stub_defaults):
    team = CE._team_snapshot()
    team["closers"] = 1
    team["throughput"] = dict(team["throughput"], calls_per_closer_month=8)
    inp = _base_inputs(stub_defaults)
    inp["team"] = team
    run = CE.forward(inp)
    assert run["auto_hires"], "capacity cross must raise a hire card"
    card = run["auto_hires"][0]
    lead_m = -CE._months_between(card["month"], card["order_by"])
    import math
    assert lead_m == math.ceil(inp["hire_lead_weeks"] / 4.33)
    # cost flows into OpEx from the start month
    start_i = next(i for i, m in enumerate(run["months"])
                   if m["month"] == card["month"])
    inp2 = copy.deepcopy(inp)
    inp2["team"]["throughput"]["calls_per_closer_month"] = 10 ** 6  # no hires
    run2 = CE.forward(inp2)
    assert run["months"][start_i]["opex_ex_tax"] > run2["months"][start_i]["opex_ex_tax"]


def test_planned_hire_cost_from_start_month(stub_defaults):
    inp = _base_inputs(stub_defaults)
    # abundant capacity in BOTH runs so no auto-hire interferes with the diff
    team = CE._team_snapshot()
    team["throughput"] = {"leads_per_setter_month": 10 ** 6,
                          "calls_per_closer_month": 10 ** 6,
                          "clients_per_delivery": 10 ** 6}
    inp["team"] = team
    m3 = CE._month_add(inp["start_month"], 3)
    base = CE.forward(copy.deepcopy(inp))
    inp["hires"] = [{"role": "csm", "role_key": "delivery", "month": m3,
                     "cost_monthly": 2000.0, "ramp_weeks": 8}]
    run = CE.forward(inp)
    assert run["months"][2]["opex_ex_tax"] == base["months"][2]["opex_ex_tax"]
    assert run["months"][3]["opex_ex_tax"] == base["months"][3]["opex_ex_tax"] + 2000.0
    assert run["months"][6]["opex_ex_tax"] == base["months"][6]["opex_ex_tax"] + 2000.0


# ── uncertainty ─────────────────────────────────────────────────────────────

def test_bands_widen_with_small_n(stub_defaults):
    inp = _base_inputs(stub_defaults)
    inp["horizon_months"] = 8
    wide = CE.bands(inp, runs=60)
    d = kv_store.get(CE.K_DEFAULTS)
    for k in ("set_rate", "show_rate", "close_rate"):
        d["items"][k]["n"] = 2000
    kv_store.put(CE.K_DEFAULTS, d)
    narrow = CE.bands(inp, runs=60)
    i = 6
    w_wide = wide["mrr"]["p75"][i] - wide["mrr"]["p25"][i]
    w_narrow = narrow["mrr"]["p75"][i] - narrow["mrr"]["p25"][i]
    assert w_wide > w_narrow


# ── scenarios + plan of record ──────────────────────────────────────────────

def test_scenarios_save_list_commit_never_actuals(stub_defaults):
    kv_store.put(CE.K_SCENARIOS, {})
    kv_store.put(CE.K_PLAN, None)
    inp = _base_inputs(stub_defaults)
    assert CE.save_scenario("Test 2027", inp)["ok"]
    assert any(s["name"] == "Test 2027"
               for s in CE.list_scenarios()["scenarios"])
    assert "error" in CE.commit_plan("nope", "rydel")
    out = CE.commit_plan("Test 2027", "rydel")
    assert out["ok"] and out["version"] == 1
    plan = kv_store.get(CE.K_PLAN)
    assert "never actuals" in plan["label"]
    # committing again bumps the version (versioned plan-of-record)
    assert CE.commit_plan("Test 2027", "rydel")["version"] == 2


# ── pulse ───────────────────────────────────────────────────────────────────

def test_booked_calls_kept_only_and_windowed(monkeypatch):
    import consult_schedule as CS
    from helpers import now_sydney
    import datetime as dt
    now = now_sydney()
    def iso(days):
        return (now + dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cache = {
        "c1": {"appts": [{"startTime": iso(2), "appointmentStatus": "confirmed"}]},
        "c2": {"appts": [{"startTime": iso(3), "appointmentStatus": "cancelled"}]},   # never counts
        "c3": {"appts": [{"startTime": iso(12), "appointmentStatus": "confirmed"}]},  # outside 7d
        "c4": {"appts": [{"startTime": iso(-1), "appointmentStatus": "confirmed"}]},  # past
    }
    monkeypatch.setattr(CS, "_cache", lambda: cache)
    out = CE.booked_calls_next_7d()
    assert out["count"] == 1
    assert "read-only" in out["source"]


def test_landing_renders_pulse_strip_server_side():
    html = _read("dashboard", "templates", "dashboard.html")
    assert "pulse-strip" in html and "{% for t in exec.pulse %}" in html
    from dashboard import exec_top
    pulse = exec_top.build_pulse()
    assert len(pulse) == 3
    for t in pulse:
        assert t["value"], t
        if t["value"] == "—":
            assert t["sub"]                    # labelled, never blank


# ── access + read-only law ──────────────────────────────────────────────────

def test_scale_is_owner_only_and_anon_refused():
    routes = _read("dashboard", "routes.py")
    i = routes.index('def scale_page')
    assert "@require_owner" in routes[i - 200:i]
    for ep in ("api_scale_run", "api_scale_solve", "api_scale_commit_plan",
               "api_scale_scenarios", "api_scale_defaults"):
        j = routes.index(f"def {ep}")
        assert "@require_owner" in routes[j - 250:j], ep
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-compass")
    import app as appmod
    c = appmod.app.test_client()
    r = c.get("/dashboard/scale")
    assert r.status_code in (302, 401, 403)


def test_read_only_law_no_mutations_in_compass():
    src = _read("compass_engine.py")
    assert "GHL_EMAIL_TOKEN" not in src
    assert not re.search(r"batchUpdate|values:append|values:update|"
                         r"requests\.(post|put|patch|delete)\(", src)
    # the toggle path can never reach a declaration writer
    assert "set_override" not in src and "declare(" not in src
    assert "SCENARIO" in src and "never actuals" in src.lower() or "never touches actuals" in src.lower() or "journal" in src.lower()


def test_commit_plan_requires_explicit_confirm():
    routes = _read("dashboard", "routes.py")
    assert 'body.get("confirm")' in routes


def test_gate_asserts_compass_headlines():
    gate = _read("scripts", "render_gate.py")
    assert "pulse tiles, expected 3" in gate
    assert "/dashboard/scale" in gate
    assert "first paint must be server-rendered" in gate
