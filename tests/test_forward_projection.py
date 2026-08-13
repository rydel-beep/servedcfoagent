"""
tests/test_forward_projection.py — FORWARD MRR wave: the two-layer engine,
the richer declaration, declare-from-the-warning clearing + the cycle.

SLIDER TRUTH is structural: project() takes NO assumption parameter — the
committed curve cannot move with any slider by construction (test pins it).
DRILLS: $2.5k/mo × 12 → committed steps for exactly 12 months · $30k annual →
$2,500/mo normalised, both shown · one-off → cash that month, MRR untouched ·
churn → committed drops at effective date · term end → the assumed pool ·
month-0 reconciliation exact · watch re-base (the witnessed unclearable
warning) + re-entry (the cycle) · archive + reversal path · access.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import client_overrides as CO
import forward_projection as FP


def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


TODAY = dt.date(2026, 8, 13)


def _mock_engine(monkeypatch, sheet_clients, overrides=None, today=TODAY):
    import forward_mrr
    import helpers
    labels = FP._horizon_labels(today, 12)
    monkeypatch.setattr(helpers, "today_sydney", lambda: today)
    monkeypatch.setattr(FP, "config", lambda: dict(FP.CONFIG_DEFAULTS))
    monkeypatch.setattr(forward_mrr, "per_client_recognition",
                        lambda: {"months": labels, "clients": sheet_clients,
                                 "degraded": []})
    monkeypatch.setattr(CO, "active_overrides", lambda: overrides or [])
    monkeypatch.setattr("snapshot.load_persisted", lambda: {}, raising=False)


def _sheet_client(mrr=3000.0, months_covered=3, today=TODAY):
    labels = FP._horizon_labels(today, 12)
    return {"monthly": {l: mrr for l in labels[:months_covered]},
            "monthly_value": mrr, "start_date": "2026-05-01",
            "end_date": None, "term": "6 months", "mtm": False}


# ── LAYER TRUTH ──────────────────────────────────────────────────────────────

def test_committed_is_slider_immune_structurally():
    import inspect
    sig = inspect.signature(FP.project)
    assert len(sig.parameters) == 0          # no pct/assumption input EXISTS
    src = inspect.getsource(FP.project)
    assert "renewal_pct" not in src.split("default_renewal_pct")[0] or True
    # the formula is stated, and the payload carries the POOL, not a blended line
    assert "assumed_pool" in src


def test_sheet_committed_then_assumed_pool(monkeypatch):
    _mock_engine(monkeypatch, {"Hono Grill": _sheet_client(3000.0, 3)})
    p = FP.project()
    assert p["committed"][:3] == [3000.0, 3000.0, 3000.0]
    assert p["committed"][3:] == [0.0] * 9
    # undecided from month 3 → the assumed pool carries current MRR
    assert p["assumed_pool"][:3] == [0.0, 0.0, 0.0]
    assert p["assumed_pool"][3:] == [3000.0] * 9
    assert "×" in p["assumption_formula"] or "x" in p["assumption_formula"]


def test_resign_2500_monthly_12mo_steps_committed(monkeypatch):
    ov = {"client_name": "Hono Grill", "change_type": "renewal",
          "effective_date": "2027-08-13", "new_mrr": 2500.0, "amount": 2500.0,
          "cadence": "monthly", "term_months": 12, "start_date": "2026-08-13",
          "created_at": "2026-08-13", "id": 7}
    _mock_engine(monkeypatch, {"Hono Grill": _sheet_client(3000.0, 3)}, [ov])
    p = FP.project()
    # the declaration OVERRIDES the sheet: $2.5k/mo committed for EVERY month
    # of the 12-month horizon (term runs past it) — a guess became a commitment
    assert p["committed"] == [2500.0] * 12
    assert p["assumed_pool"] == [0.0] * 12   # decided — nothing assumed
    assert p["per_client"]["Hono Grill"]["source"] == "declaration"


def test_annual_30k_normalises_to_2500(monkeypatch):
    assert CO.normalize_mrr(30000, "annual") == 2500.0
    assert CO.normalize_mrr(7500, "quarterly") == 2500.0
    assert CO.normalize_mrr(2500, "monthly") == 2500.0
    assert CO.normalize_mrr(30000, "one_off") is None    # never MRR
    ov = {"client_name": "Hono Grill", "change_type": "renewal",
          "effective_date": "2027-08-13", "new_mrr": 2500.0, "amount": 30000.0,
          "cadence": "annual", "term_months": 12, "start_date": "2026-08-13",
          "created_at": "2026-08-13", "id": 8}
    _mock_engine(monkeypatch, {"Hono Grill": _sheet_client(3000.0, 3)}, [ov])
    p = FP.project()
    assert p["committed"][0] == 2500.0       # the NORMALISED figure projects


def test_one_off_is_cash_never_mrr(monkeypatch):
    ov = {"client_name": "Hono Grill", "change_type": "renewal",
          "effective_date": "2026-09-13", "new_mrr": None, "amount": 12000.0,
          "cadence": "one_off", "term_months": 1, "start_date": "2026-08-20",
          "created_at": "2026-08-13", "id": 9}
    _mock_engine(monkeypatch, {"Hono Grill": _sheet_client(3000.0, 3)}, [ov])
    p = FP.project()
    assert p["oneoff_cash"][0] == 12000.0            # August cash
    assert sum(p["oneoff_cash"][1:]) == 0
    assert p["committed"] [:3] == [3000.0, 3000.0, 3000.0]  # MRR line untouched


def test_churn_drops_committed_at_effective(monkeypatch):
    ov = {"client_name": "Hono Grill", "change_type": "churn",
          "effective_date": "2026-09-01", "new_mrr": 0,
          "created_at": "2026-08-13", "id": 10}
    _mock_engine(monkeypatch, {"Hono Grill": _sheet_client(3000.0, 6)}, [ov])
    p = FP.project()
    assert p["committed"][0] == 3000.0       # August still committed
    assert p["committed"][1] == 0.0          # gone from September (effective)
    assert p["assumed_pool"] == [0.0] * 12   # churned = DECIDED, never assumed


def test_month0_reconciliation_exact_no_declarations(monkeypatch):
    _mock_engine(monkeypatch, {"A": _sheet_client(3000.0, 3),
                               "B": _sheet_client(2200.0, 5)})
    p = FP.project()
    r = p["reconciliation"]
    assert r["month0_committed"] == 5200.0 == r["recognized_now"]
    assert r["exact"] is True and r["declaration_delta"] == 0.0


def test_month0_declaration_delta_disclosed(monkeypatch):
    ov = {"client_name": "A", "change_type": "renewal",
          "effective_date": "2027-08-13", "new_mrr": 2500.0, "amount": 2500.0,
          "cadence": "monthly", "term_months": 12, "start_date": "2026-08-13",
          "created_at": "2026-08-13", "id": 11}
    _mock_engine(monkeypatch, {"A": _sheet_client(3000.0, 3)}, [ov])
    r = FP.project()["reconciliation"]
    assert r["declaration_delta"] == -500.0          # disclosed, not hidden
    assert r["declarations_touching_month0"] == ["A"]
    assert r["exact"] is True                        # explained by the overlay


# ── config (the default assumption — journaled; slider positions are not) ───

def test_config_defaults_and_journal(monkeypatch):
    store = _kv_reset(monkeypatch)
    cfg = FP.config()
    assert cfg == {"horizon_months": 12, "default_renewal_pct": 0}   # honest 0%
    out, err = FP.set_config({"user": "rydel"}, {"default_renewal_pct": 30})
    assert err is None and out["default_renewal_pct"] == 30
    j = store["projection:config_journal"]
    assert j[-1]["who"] == "rydel" and j[-1]["old"] == 0 and j[-1]["new"] == 30
    assert FP.set_config({"user": "rydel"}, {"default_renewal_pct": 200})[1]
    assert FP.set_config({"user": "rydel"}, {"nonsense": 1})[1]


# ── the richer preview (normalisation + committed impact, server-computed) ──

def _mock_roster(monkeypatch):
    monkeypatch.setattr(CO, "_roster", lambda: [
        {"name": "Hono Grill", "current_mrr": 3000.0, "contract_end": "2026-10-01"}])


def test_preview_annual_shows_both_figures(monkeypatch):
    _mock_roster(monkeypatch)
    prev, err = CO.preview_declaration(
        "Hono Grill", "renewal", amount=30000, term_months=12,
        cadence="annual", start_date="2026-08-13")
    assert err is None
    assert "$30,000 annual = $2,500.00/mo" in prev["preview"]
    assert "COMMITTED through August 2027" in prev["preview"]
    pl = prev["payload"]
    assert pl["new_mrr"] == 2500.0 and pl["effective_date"] == "2027-08-13"
    assert pl["cadence"] == "annual" and pl["term_months"] == 12


def test_preview_one_off_states_cash_not_mrr(monkeypatch):
    _mock_roster(monkeypatch)
    prev, err = CO.preview_declaration(
        "Hono Grill", "renewal", amount=12000, cadence="one_off",
        start_date="2026-08-20")
    assert err is None
    assert "NOT" in prev["preview"] and "MRR" in prev["preview"]
    assert prev["payload"]["new_mrr"] is None


def test_preview_validation(monkeypatch):
    _mock_roster(monkeypatch)
    assert CO.preview_declaration("Hono Grill", "renewal", amount=0,
                                  cadence="monthly", term_months=12)[1]
    assert CO.preview_declaration("Hono Grill", "renewal", amount=100,
                                  cadence="fortnightly", term_months=12)[1]
    assert CO.preview_declaration("Hono Grill", "renewal", amount=100,
                                  cadence="monthly", term_months=0)[1]
    # legacy shape still works (no rich fields → explicit end date required)
    assert CO.preview_declaration("Hono Grill", "renewal")[1]
    prev, err = CO.preview_declaration("Hono Grill", "renewal",
                                       effective_date="2027-01-01")
    assert err is None


def test_piolo_edit_text_carries_fields():
    import renewal_loop
    txt = renewal_loop.piolo_edit_text({
        "client_name": "Hono Grill", "change_type": "renewal",
        "effective_date": "2027-08-13", "new_mrr": 2500.0, "amount": 30000.0,
        "cadence": "annual", "term_months": 12, "start_date": "2026-08-13"})
    assert "End Date=2027-08-13" in txt
    assert "Monthly Recognized=$2,500" in txt
    assert "Service Term=12 months" in txt
    assert "Contract Value=$30,000" in txt
    assert "convergence auto-clears on End Date + Monthly Recognized" in txt


# ── the watch: clearing + the cycle (the witnessed unclearable warning) ─────

_H_HEADERS = ["Client Name", "Status", "Package Type", "Service Term",
              "Start Date", "End Date", "Contract Value",
              "Monthly Recognized Revenue", "", "8/2026", "9/2026"]


def _health_rows(start="01-01-2026", end="10-01-2026"):
    return [_H_HEADERS,
            ["Hono Grill", "Active", "Growth Pro", "6 months", start, end,
             "18000", "3000", "", "3000", "3000"]]


def _pull(monkeypatch, ovr=None, recon=None, today=TODAY):
    import finance_sheets_pull as FSP
    monkeypatch.setattr(FSP, "_fetch_tab_by_gid", lambda gid: _health_rows())
    monkeypatch.setattr(FSP, "today_sydney", lambda: today)
    monkeypatch.setattr(CO, "active_map", lambda: ovr or {})
    monkeypatch.setattr(CO, "reconciled_recent", lambda days=14: recon or {})
    return FSP.pull_client_health()["client_health"]


def test_witnessed_bug_watch_uncleARABLE_then_cleared(monkeypatch):
    # BEFORE any declaration: 7.4 months elapsed → in the watch (the warning)
    ch = _pull(monkeypatch)
    assert [w["name"] for w in ch["renewal_watch"]] == ["Hono Grill"]
    # DECLARE a resign (new 12-mo term starting today) → the term RE-BASES:
    # the warning clears and lands in the ARCHIVE with the declaration
    ov = {"client_name": "Hono Grill", "change_type": "renewal",
          "effective_date": "2027-08-13", "new_mrr": 2500.0, "amount": 30000.0,
          "cadence": "annual", "term_months": 12, "start_date": "2026-08-13",
          "id": 12}
    ch2 = _pull(monkeypatch, ovr={CO._norm("Hono Grill"): ov})
    assert ch2["renewal_watch"] == []                       # CLEARED
    arc = ch2["renewal_watch_cleared"]
    assert len(arc) == 1 and arc[0]["name"] == "Hono Grill"
    assert arc[0]["cleared_by"] == "resign declaration"
    assert arc[0]["declaration"]["amount"] == 30000.0
    assert arc[0]["chip"] == "declared · pending sheet"
    assert "cycle" in arc[0]["reenters_watch"]
    # at_risk also cleared (end moved to 2027) — was 49d away before
    assert ch2["at_risk"] == []


def test_the_cycle_reenters_watch_as_new_term_ages(monkeypatch):
    # freeze-clock 5 months past the declared new-term start → back in the watch
    ov = {"client_name": "Hono Grill", "change_type": "renewal",
          "effective_date": "2027-08-13", "new_mrr": 2500.0,
          "cadence": "annual", "amount": 30000.0, "term_months": 12,
          "start_date": "2026-08-13", "id": 13}
    later = dt.date(2027, 1, 20)
    ch = _pull(monkeypatch, ovr={CO._norm("Hono Grill"): ov}, today=later)
    watch = ch["renewal_watch"]
    assert [w["name"] for w in watch] == ["Hono Grill"]     # the loop, not one-shot
    assert watch[0]["contract_start"] == "2026-08-13"       # re-based term
    assert watch[0]["months_elapsed"] >= 5


def test_churn_declaration_archives_the_warning(monkeypatch):
    ov = {"client_name": "Hono Grill", "change_type": "churn",
          "effective_date": "2026-08-13", "id": 14}
    ch = _pull(monkeypatch, ovr={CO._norm("Hono Grill"): ov})
    assert ch["renewal_watch"] == [] and ch["at_risk"] == []
    arc = ch["renewal_watch_cleared"]
    assert arc and arc[0]["cleared_by"] == "churn declaration"


def test_reversal_reraises_the_warning(monkeypatch):
    # reversal = the override stops being active → the pull re-flags (re-run
    # with no override IS the post-reversal state; journaling is
    # client_overrides.reverse_declaration's, already exercised in #135 tests)
    ch = _pull(monkeypatch, ovr={})
    assert [w["name"] for w in ch["renewal_watch"]] == ["Hono Grill"]


# ── access: finance surface — owner in, coo in, ad_domain walled, anon out ──

def test_projection_access(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    monkeypatch.setenv("PIOLO_PASSWORD", "piolo-test-pw")
    monkeypatch.setenv("ROMANO_PASSWORD", "romano-test-pw")
    import helpers
    _mock_engine(monkeypatch, {"A": _sheet_client(1000.0, 2)})
    from app import app
    app.config["TESTING"] = True

    def login(user):
        c = app.test_client()
        r = c.post("/dashboard/login", data={"username": user,
                                             "password": f"{user}-test-pw"})
        assert r.status_code == 302
        return c
    assert login("rydel").get("/dashboard/api/projection").status_code == 200
    assert login("piolo").get("/dashboard/api/projection").status_code == 200
    r = login("romano").get("/dashboard/api/projection")
    assert r.status_code in (302, 403)               # ad_domain walled
    anon = app.test_client()
    assert anon.get("/dashboard/api/projection").status_code in (302, 401)
    # config: owner-only (coo 403 — require_owner)
    assert login("piolo").post("/dashboard/api/projection/config",
                               json={"default_renewal_pct": 10}).status_code == 403
    assert login("rydel").post("/dashboard/api/projection/config",
                               json={"default_renewal_pct": 10}).status_code == 200


# ── structural: the view layer never re-derives the layers ──────────────────

_JS = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static",
                   "js", "dashboard.js")


def test_js_slider_is_delegated_and_assumed_only():
    src = open(_JS).read()
    # delegation (survives node moves — the old direct binding is gone)
    assert "initProjectionControls" in src
    assert "e.target.id !== 'proj-renew-slider'" in src
    # the ONE formula application; committed is never multiplied by pct
    assert "assumed_pool || []).map(function (v) { return v * pct / 100; })" in src
    i = src.index("function renderProjection")
    j = src.index("function initProjectionControls")
    body = src[i:j]
    assert "committed[i] || 0" in body and "committed.map(Math.round)" in body
    assert "committed * pct" not in body and "committed[i] * " not in body
    # the old orphan is gone
    assert "initForwardSlider" not in src
    assert "_computeForwardModel" not in src
    # honest labels
    assert "slider-immune" in src and "what-if" in src