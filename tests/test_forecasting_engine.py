"""
tests/test_forecasting_engine.py
--------------------------------
Forecasting layer: 13-week cash flow, dynamic runway, MRR scenarios + what-ifs, expiry-aware
attrition, accuracy tracking. Deterministic fixtures. Every output is labelled PROJECTION.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kv_store, forecasting_engine as fe

def _snap(cash=170000, burn=32000, mrr=63000, active=38, inflow=69000, closes90=16, churn90=0, expiry_delta=-6000):
    return {
        "cash_position": {"cash_in_bank": cash, "total_monthly_burn": burn, "runway_months": round(cash/burn,1)},
        "client_health": {"current_mrr": mrr, "active_count": active},
        "active_clients": {"active_count": active},
        "stripe": {"revenue": {"current": {"total_aud": inflow}}},
        "forward_mrr": {"renewal_rate_historical": {"rate": 0.0},
                        "forward_months": [{"delta": 0}, {"delta": expiry_delta}, {"delta": expiry_delta}]},
        "_closes90": closes90, "_churn90": churn90,
    }

def _patch(monkeypatch, snap):
    kv_store._MEM.clear()
    import capacity_engine as ce
    monkeypatch.setattr(ce, "net_velocity", lambda s=None: {
        "90d": {"closes": snap["_closes90"], "churn": snap["_churn90"], "net_per_month": 5.3, "noisy": snap["_closes90"]<9}})
    monkeypatch.setattr(fe, "_snap", lambda: snap)

def test_cash_flow_cash_positive(monkeypatch):
    s=_snap(); _patch(monkeypatch, s)
    cf=fe.cash_flow_13wk(s)
    assert cf["is_projection"] is True
    # inflow (69k/mo) >> outflow (32k/mo) → cash-positive, cash grows
    assert cf["cash_positive"] is True and cf["ending_cash"] > cf["starting_cash"]
    assert len(cf["curve"]) == 13

def test_dynamic_vs_static_runway(monkeypatch):
    s=_snap(); _patch(monkeypatch, s)
    dr=fe.dynamic_runway(s)
    assert dr["static_runway_months"] == round(170000/32000,1)   # static assumes no inflow
    assert dr["cash_positive"] is True and "GROWS" in dr["read"]  # dynamic: cash-positive

def test_mrr_forecast_expiry_aware(monkeypatch):
    s=_snap(); _patch(monkeypatch, s)
    mf=fe.mrr_forecast(s)
    # expiry drag applied at 0% renewal → base attrition present; scenarios ordered best>base>worst
    assert mf["scenarios"]["best"]["end_mrr"] >= mf["scenarios"]["base"]["end_mrr"] >= mf["scenarios"]["worst"]["end_mrr"]
    assert mf["renewal_rate_pct"] == 0.0
    assert "PROJECTION" in mf["assumptions_note"]

def test_what_if_churn_doubles_changes_result(monkeypatch):
    s=_snap(); _patch(monkeypatch, s)
    base=fe.mrr_forecast(s)["scenarios"]["base"]["end_mrr"]
    doubled=fe.mrr_forecast(s, churn_mult=2.0)["scenarios"]["base"]["end_mrr"]
    assert doubled < base   # doubling attrition lowers the projected MRR (the earlier bug)

def test_renewal_rate_adjustable(monkeypatch):
    s=_snap(); _patch(monkeypatch, s)
    low=fe.mrr_forecast(s)["scenarios"]["base"]["end_mrr"]     # 0% renewal (historical)
    fe.set_assumption("renewal_rate_pct", 80)
    high=fe.mrr_forecast(s)["scenarios"]["base"]["end_mrr"]    # 80% renewal → less drag → higher
    assert high > low

def test_accuracy_tracking(monkeypatch):
    kv_store._MEM.clear()
    assert fe.accuracy("mrr")["available"] is False
    fe.record_projection("mrr", "6mo", 70000, "2026-08")
    fe.grade_projection("mrr", "2026-08", 65000)
    ac=fe.accuracy("mrr")
    assert ac["available"] and ac["recent_bias_pct"] > 0 and ac["direction"] == "optimistic"  # projected high

def test_handlers_route_and_label_projection(monkeypatch):
    s=_snap(); _patch(monkeypatch, s)
    for q in ["what's our cash flow forecast","are we cash positive","where is mrr going","what if churn doubles"]:
        r,h=fe.handle_forecast_command(q)
        assert h and "PROJECTION" in r
    assert fe.handle_forecast_command("what's the weather")[1] is False
