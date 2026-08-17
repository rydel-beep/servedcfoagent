"""
tests/test_csm_plan.py
----------------------
The CSM domain engine: NRR starting-cohort convention (mid-window join
excluded — test-pinned), comp accrual activation + event mapping, actuals
overlay crediting rules (baseline-rate renewals credit $0), scenario-overlay
labelling + start offset, ladder-calendar dates for 3/6-month terms, gates
(auto vs human ticks), risk register, config validation.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import datetime as dt

import csm_plan
import csm_baselines


def _kv(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


# ── NRR ─────────────────────────────────────────────────────────────────────

def test_nrr_starting_cohort_excludes_mid_window_join(monkeypatch):
    import mrr_snapshot
    from helpers import today_sydney
    today = today_sydney()

    def snap_on(d):
        if d <= today - dt.timedelta(days=80):
            return {"snap_date": str(d), "current_mrr": 10000,
                    "per_client": {"a": 5000, "b": 3000, "c": 2000}}
        # end of window: a expanded, b contracted, c churned, NEWBIE joined
        return {"snap_date": str(d), "current_mrr": 11000,
                "per_client": {"a": 6000, "b": 2000, "newbie": 3000}}
    monkeypatch.setattr(mrr_snapshot, "snapshot_on_date", snap_on)
    out = csm_plan.nrr_rolling(90)
    assert out["available"]
    assert out["start_mrr"] == 10000
    assert out["expansion"] == 1000
    assert out["contraction"] == 1000
    assert out["churn"] == 2000
    # (10000 + 1000 - 1000 - 2000) / 10000 = 80% — NEWBIE's 3000 excluded
    assert out["nrr_pct"] == 80.0
    assert "starting cohort" in out["convention"]


def test_nrr_honest_when_history_missing(monkeypatch):
    import mrr_snapshot
    monkeypatch.setattr(mrr_snapshot, "snapshot_on_date", lambda d: None)
    monkeypatch.setattr(mrr_snapshot, "first_snapshot_date", lambda: "2026-08-10")
    out = csm_plan.nrr_rolling(90)
    assert out["available"] is False and "2026-08-10" in out["reason"]


# ── comp accrual ────────────────────────────────────────────────────────────

def test_comp_accrual_pre_start_activates_at_start(monkeypatch):
    _kv(monkeypatch)
    acc = csm_plan.comp_accrual({**csm_plan.config(), "start_date": "2099-01-01"})
    assert acc["state"] == "activates at start" and acc["total_accrued"] == 0.0


def test_comp_accrual_maps_declarations_to_events(monkeypatch):
    _kv(monkeypatch)
    decls = [
        {"change_type": "renewal", "client_name": "A", "term_months": 6,
         "id": 1, "created_at": "2026-01-05"},
        {"change_type": "renewal", "client_name": "B", "term_months": 12,
         "id": 2, "created_at": "2026-01-06"},                    # + lock12
        {"change_type": "downsell", "client_name": "C", "id": 3,
         "created_at": "2026-01-07"},                             # continuity
        {"change_type": "expansion", "client_name": "D", "subtype": "ordering",
         "first6_value": 1494, "id": 4, "created_at": "2026-01-08"},
        {"change_type": "expansion", "client_name": "E", "subtype": "referral",
         "first6_value": 9000, "id": 5, "created_at": "2026-01-09"},
    ]
    monkeypatch.setattr(csm_plan, "_declarations_since", lambda s: decls)
    acc = csm_plan.comp_accrual({**csm_plan.config(), "start_date": "2026-01-01"})
    # 500 + (500+800) + 150 + 10%*1494 + 5%*9000 = 2549.4
    assert acc["total_accrued"] == 500 + 500 + 800 + 150 + 149.4 + 450
    assert acc["state"] == "live"
    assert "Xero" in acc["xero_note"]          # payroll truth stated


# ── actuals overlay (R5) ────────────────────────────────────────────────────

def _live_cfg():
    return {**csm_plan.config(), "start_date": "2026-01-01"}


def test_baseline_rate_renewals_credit_zero(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(csm_baselines, "all_baselines", lambda fresh=False: {
        "b1_renewal": {"value": 100.0}})       # baseline predicts EVERY renewal
    decls = [{"change_type": "renewal", "client_name": "A", "new_mrr": 3000,
              "term_months": 6, "id": 1, "created_at": "2026-02-01"}]
    monkeypatch.setattr(csm_plan, "_declarations_since", lambda s: decls)
    out = csm_plan.actuals_overlay(_live_cfg())
    assert out["credited_to_date"] == 0.0      # predicted → $0 credited
    assert out["ledger"] == []


def test_above_baseline_renewal_credits_with_evidence(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(csm_baselines, "all_baselines", lambda fresh=False: {
        "b1_renewal": {"value": 0.0}})         # baseline predicts none
    decls = [{"change_type": "renewal", "client_name": "A", "new_mrr": 1000,
              "term_months": 6, "id": 77, "created_at": "2026-02-01"}]
    monkeypatch.setattr(csm_plan, "_declarations_since", lambda s: decls)
    out = csm_plan.actuals_overlay(_live_cfg())
    assert out["credited_to_date"] > 0
    assert out["ledger"][0]["evidence_id"] == 77
    assert "never a verdict" in out["roi_to_date_note"].lower() or \
           "NEVER a verdict" in out["roi_to_date_note"]


def test_expansion_and_continuity_credit_with_evidence(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(csm_baselines, "all_baselines", lambda fresh=False: {
        "b1_renewal": {"value": 100.0}})
    decls = [{"change_type": "expansion", "client_name": "D",
              "subtype": "ordering", "first6_value": 1000, "id": 9,
              "created_at": "2026-02-01"},
             {"change_type": "downsell", "client_name": "C", "new_mrr": 499,
              "id": 10, "created_at": "2026-02-02"}]
    monkeypatch.setattr(csm_plan, "_declarations_since", lambda s: decls)
    out = csm_plan.actuals_overlay(_live_cfg())
    kinds = {l["kind"]: l for l in out["ledger"]}
    assert "expansion (ordering)" in kinds and kinds["expansion (ordering)"]["evidence_id"] == 9
    assert "continuity capture" in kinds and kinds["continuity capture"]["evidence_id"] == 10


# ── scenario overlay (M8) ───────────────────────────────────────────────────

def test_scenario_overlay_labelled_and_start_offset(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(csm_baselines, "all_baselines", lambda fresh=False: {
        "b4_book": {"tiers": {"book_count": 30}}})   # scale 1.0 vs source book
    from helpers import today_sydney
    today = today_sydney()
    start = (today.replace(day=1) + dt.timedelta(days=93)).replace(day=1)
    cfg = csm_plan.config()
    csm_plan.set_config({"user": "rydel"}, {"start_date": str(start)})
    out = csm_plan.scenario_overlay()
    assert "what-if" in out["label"]
    offset = (start.year - today.year) * 12 + (start.month - today.month)
    # months before her start carry zero incremental revenue
    for i in range(offset):
        assert out["monthly_incremental_revenue"][i] == 0.0
    assert out["monthly_incremental_revenue"][offset] > 0
    assert out["book_scale"] == 1.0


# ── ladder calendar ─────────────────────────────────────────────────────────

def test_ladder_calendar_dates_for_3_and_6_month_terms(monkeypatch):
    _kv(monkeypatch)
    import snapshot
    monkeypatch.setattr(snapshot, "load_persisted", lambda: {
        "active_clients": {"active": [
            {"name": "SixMo", "package": "Growth Pro",
             "contract_start": "2026-08-01", "contract_end": "2027-02-01",
             "current_mrr": 3050},
            {"name": "ThreeMo", "package": "Cafe Walk-Ins",
             "close_date": "2026-08-01", "current_mrr": 1500},
            {"name": "NoDates", "package": "Custom", "current_mrr": 900},
        ]}})
    monkeypatch.setattr(csm_baselines, "all_baselines", lambda fresh=False: {
        "b4_book": {"tiers": {"assignments": {"SixMo": 1}}}})
    cal = csm_plan.ladder_calendar()
    by = {c["client"]: c for c in cal["clients"]}
    assert by["SixMo"]["term_months"] == 6
    assert by["SixMo"]["month4_lock_date"] == "2026-11-29"     # start + 120d
    assert by["SixMo"]["renewal_date"] == "2027-01-02"          # end - 30d
    assert by["SixMo"]["tier"] == 1
    assert by["ThreeMo"]["term_months"] == 3                    # package default
    assert "derived" in by["ThreeMo"]["term_basis"]
    assert by["ThreeMo"]["term_end"] == "2026-11-01"
    assert "NoDates" in cal["undated"]                          # honest, not faked


# ── gates + risks + config ──────────────────────────────────────────────────

def test_gates_auto_and_human(monkeypatch):
    _kv(monkeypatch)
    b = {"b1_renewal": {"label": "measured 2026-08-17"},
         "b2_refund_split": {"label": "partial — measured 2026-08-17"},
         "b4_book": {"tiers": {"tier1_count": 0}}}
    g = csm_plan.gates(b)
    auto = {i["id"]: i for i in g["items"] if i["type"] == "data"}
    assert auto["baselines_measured"]["done"] is True
    assert "measured" in auto["baselines_measured"]["evidence"]
    assert auto["book_tiered"]["done"] is False
    out, err = csm_plan.tick_gate({"user": "rydel"}, "miguel_reframe", True)
    assert err is None and out["who"] == "rydel"
    g2 = csm_plan.gates(b)
    assert g2["done"] == 2
    # data items are NOT owner-tickable
    _, err2 = csm_plan.tick_gate({"user": "rydel"}, "baselines_measured", True)
    assert err2


def test_risk_register_live_signals(monkeypatch):
    _kv(monkeypatch)
    b = {"b4_book": {"tiers": {"tier1_count": 0}}}
    r = csm_plan.risks(b)
    reg = {x["id"]: x for x in r["register"]}
    assert len(r["register"]) == 9              # the nine failure modes
    assert reg["book_untiered"]["status"] == "fire"
    out, err = csm_plan.set_risk({"user": "rydel"}, "routing_around", "ok", "fine")
    assert err is None
    reg2 = {x["id"]: x for x in csm_plan.risks(b)["register"]}
    assert reg2["routing_around"]["status"] == "ok"
    _, bad = csm_plan.set_risk({"user": "rydel"}, "nope", "ok")
    assert bad


def test_config_validation(monkeypatch):
    _kv(monkeypatch)
    _, err = csm_plan.set_config({"user": "rydel"}, {"nonsense_key": 1})
    assert "unknown config key" in err
    _, err2 = csm_plan.set_config({"user": "rydel"}, {"sg_rate": 0.9})
    assert "out of bounds" in err2
    _, err3 = csm_plan.set_config({"user": "rydel"}, {"start_date": "soon"})
    assert "ISO date" in err3
    cfg, err4 = csm_plan.set_config({"user": "rydel"},
                                    {"employment_form": "contractor"})
    assert err4 is None and cfg["employment_form"] == "contractor"


def test_summary_card_line_shape(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(csm_baselines, "all_baselines", lambda fresh=False: {
        "b1_renewal": {"label": "measured x"}, "b2_refund_split": {"label": "partial — measured x"},
        "b4_book": {"tiers": {"tier1_count": 0, "book_count": 30}}})
    import mrr_snapshot
    monkeypatch.setattr(mrr_snapshot, "snapshot_on_date", lambda d: None)
    monkeypatch.setattr(mrr_snapshot, "first_snapshot_date", lambda: None)
    s = csm_plan.summary()
    assert s["card_line"].startswith("CSM · ")
    assert "Gate 0" in s["card_line"] and "path to 4x" in s["card_line"]
    assert s["dial_4x"]["y1_honesty"] == "year-1 4x exists in NO scenario"
