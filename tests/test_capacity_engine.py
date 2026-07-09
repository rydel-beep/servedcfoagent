"""
tests/test_capacity_engine.py
-----------------------------
Capacity & hiring engine: department load math, hiring budget (40% gate), pricing, constraint check,
net velocity, and conversational routing. Deterministic — team + snapshot are fixtures; benchmarks
are the Rydel-locked defaults.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kv_store, capacity_engine as ce

# 3 full-time + 3 part-time SMM, 2 ads. (owner/others omitted from capacity, present for payroll.)
_TEAM = (
    [{"name": f"smm_ft_{i}", "role": "SMM Full time", "dept": "SMM", "status": "Full Time",
      "aud": 700, "php": 30000} for i in range(3)] +
    [{"name": f"smm_pt_{i}", "role": "SMM Part Time", "dept": "SMM", "status": "Part Time",
      "aud": 570, "php": 24000} for i in range(3)] +
    [{"name": f"ads_{i}", "role": "FB ads", "dept": "PAID ADS", "status": "Full Time",
      "aud": 1050, "php": 46000} for i in range(2)]
)

def _snap(mrr=63302.85, payroll=31953.53, active=38, owner=9704.0, closes=None):
    return {
        "active_clients": {"active_count": active},
        "client_health": {"current_mrr": mrr},
        "hormozi": {"op_efficiency": {"inputs_used": {"true_team_cost": payroll}}},
        "team_model": {"owner_gross_monthly": owner, "total_with_owner": payroll},
    }

def _patch(monkeypatch, churn=0):
    kv_store._MEM.clear()
    monkeypatch.setattr(ce, "_team", lambda: _TEAM)
    monkeypatch.setattr(ce, "churn_in_window", lambda days, snap=None: churn)
    import range_unit_economics as rue
    monkeypatch.setattr(rue, "unit_economics",
                        lambda a, b: {"components": {"closes": 6 if (b and a) else 6}})


def test_department_load_smm_math(monkeypatch):
    _patch(monkeypatch)
    depts = {d["dept"]: d for d in ce.department_load(_snap())}
    smm = depts["SMM (delivery)"]
    # capacity = 3*7 + 3*4.5 = 34.5 ; load = 38/34.5 = 110.1%
    assert smm["capacity"] == 34.5 and smm["load_pct"] == round(38 / 34.5 * 100, 1)
    assert smm["full_time"] == 3 and smm["part_time"] == 3


def test_hiring_budget_over_ceiling(monkeypatch):
    _patch(monkeypatch)
    hb = ce.hiring_budget(_snap())
    # 63302.85*0.40 - 31953.53 = -6632.39 ; ratio 50.5% ; team-only excludes owner
    assert hb["budget_monthly"] == round(63302.85 * 0.40 - 31953.53, 2)
    assert hb["over_ceiling"] is True and hb["payroll_ratio_pct"] == 50.5
    assert hb["team_only_ratio_pct"] == round((31953.53 - 9704.0) / 63302.85 * 100, 1)  # ~35.1%


def test_budget_is_one_engine_consistent(monkeypatch):
    _patch(monkeypatch)
    snap = _snap()
    hb = ce.hiring_budget(snap)
    assert hb["mrr"] == snap["client_health"]["current_mrr"]        # same MRR as the dashboard
    assert hb["payroll"] == snap["hormozi"]["op_efficiency"]["inputs_used"]["true_team_cost"]


def test_price_hire_over_budget_quantifies_gap(monkeypatch):
    _patch(monkeypatch)
    pr = ce.price_hire("new SMM", 814, _snap())        # ~35k PHP
    assert pr["fits_budget"] is False and pr["mrr_gap_to_afford"] > 0
    assert pr["new_ratio_pct"] > 40


def test_constraint_check_elevated_leads_retention(monkeypatch):
    _patch(monkeypatch, churn=9)   # 9 over 90d = 3/mo > gate 2
    cc = ce.constraint_check(_snap())
    assert cc["elevated"] is True and cc["levers"][0]["lever"] == "fix retention"
    assert cc["mrr_lost_per_month"] > 0


def test_constraint_check_contained(monkeypatch):
    _patch(monkeypatch, churn=0)
    cc = ce.constraint_check(_snap())
    assert cc["elevated"] is False and "contained" in cc["levers"][0]["read"]


def test_handlers_route(monkeypatch):
    _patch(monkeypatch)
    assert ce.handle_capacity_command("what's our hiring budget?")[1] is True
    assert ce.handle_capacity_command("can we afford a new SMM at 35k PHP?")[1] is True
    assert ce.handle_capacity_command("who's closest to capacity?")[1] is True
    assert ce.handle_capacity_command("when do I need to hire next?")[1] is True
    assert ce.handle_capacity_command("should I hire or fix churn?")[1] is True
    # a non-capacity question is not grabbed
    assert ce.handle_capacity_command("what's the weather?")[1] is False


def test_set_benchmark_by_voice(monkeypatch):
    _patch(monkeypatch)
    reply, handled = ce.handle_capacity_command("set SMM capacity to 6")
    assert handled and ce.benchmarks()["smm_full_time"] == 6.0


def test_afford_over_budget_shows_mrr_gap_not_targets(monkeypatch):
    _patch(monkeypatch)
    reply, _ = ce.handle_capacity_command("can we afford a new SMM at 35k PHP?")
    assert "MRR" in reply and "ceiling" in reply and "₱35,000" in reply   # priced, not a targets menu


def test_raise_signals_never_verdicts(monkeypatch):
    _patch(monkeypatch)
    rs = ce.raise_signals(_snap())
    assert "performance is your call" in rs["framing"] and "deserve" in rs["framing"]
    for s in rs["signals"]:
        assert "5%" in s["raise_options_aud_month"] and "10%" in s["raise_options_aud_month"]
