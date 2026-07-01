"""
tests/test_manual_targets.py
----------------------------
Rydel-set targets/benchmarks: the NL command flow (set/query/reset/note) with the
confirmation loop, value parsing, persistence, and target-aware Hormozi.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import manual_targets
from hormozi_metrics import m1_ltgp_cac, m4_gross_margin


def _fresh(monkeypatch, tmp_path):
    # Fresh per-test store file → no values and no pending carry over.
    monkeypatch.setattr(manual_targets, "MANUAL_TARGETS_STORE", str(tmp_path / "mt.json"))


def test_set_requires_confirmation_then_persists(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    reply, handled = manual_targets.handle_turn("set the LTGP:CAC target to 3.5", "tok")
    assert handled and "3.5" in reply and "confirm" in reply.lower()
    # Not written until confirmed.
    assert manual_targets.get_resolved()["ltgp_cac_target"] == 3.0
    reply2, handled2 = manual_targets.handle_turn("yes", "tok")
    assert handled2 and "now 3.5" in reply2
    assert manual_targets.get_resolved()["ltgp_cac_target"] == 3.5
    # Persisted across a reload (new process would re-read the file).
    assert manual_targets.get_all()["ltgp_cac_target"]["is_user_set"] is True
    assert manual_targets.get_all()["ltgp_cac_target"]["set_by"] == "Rydel"


def test_deny_cancels(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    manual_targets.handle_turn("set roas target to 4", "tok")
    reply, handled = manual_targets.handle_turn("no", "tok")
    assert handled and "leaving" in reply.lower()
    assert manual_targets.get_resolved()["roas_target"] == 3.0  # unchanged


def test_percent_and_value_parsing(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    reply, _ = manual_targets.handle_turn("move the gross margin benchmark to 50%", "tok")
    assert "50%" in reply
    manual_targets.handle_turn("yes", "tok")
    assert manual_targets.get_resolved()["gross_margin_floor"] == 50.0
    # money k-suffix
    _fresh(monkeypatch, tmp_path)
    r, _ = manual_targets.handle_turn("set the CAC ceiling to 4k", "tok")
    assert "$4,000" in r
    manual_targets.handle_turn("yep", "tok")
    assert manual_targets.get_resolved()["cac_ceiling"] == 4000.0


def test_ambiguous_field_asks(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    reply, handled = manual_targets.handle_turn("set the target to 3.5", "tok")
    assert handled and "which" in reply.lower()
    # nothing pending committed
    assert manual_targets._get_pending("tok") is None


def test_query_and_summary(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    manual_targets.handle_turn("set the payback target to 21 days", "tok")
    manual_targets.handle_turn("yes", "tok")
    q, handled = manual_targets.handle_turn("what's my payback target?", "tok")
    assert handled and "21" in q
    s, _ = manual_targets.handle_turn("what targets have I set?", "tok")
    assert "Payback" in s


def test_reset_to_default(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    manual_targets.handle_turn("set the LTGP:CAC target to 4", "tok"); manual_targets.handle_turn("yes", "tok")
    assert manual_targets.get_resolved()["ltgp_cac_target"] == 4.0
    r, _ = manual_targets.handle_turn("reset the LTGP:CAC target to default", "tok")
    assert "default" in r.lower()
    manual_targets.handle_turn("yes", "tok")
    assert manual_targets.get_resolved()["ltgp_cac_target"] == 3.0


def test_note_flow(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    r, handled = manual_targets.handle_turn("note: push the Q3 campaign next week", "tok")
    assert handled and "Q3 campaign" in r
    manual_targets.handle_turn("yes", "tok")
    assert manual_targets.get_all()["_notes"][0]["text"].startswith("push the Q3")


def test_non_command_falls_through(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    reply, handled = manual_targets.handle_turn("what's our cash position?", "tok")
    assert handled is False and reply is None


def test_hormozi_uses_set_target(monkeypatch, tmp_path):
    # A set target moves the healthy/below-target classification.
    snap = {"sales": {"deep": {"money": {"avg_contract": 16000}}, "funnel": {"closes": 6}},
            "xero": {"gross_margin_pct": 60},
            "ad_spend_resolved": {"value": 6000, "source": "meta_live", "window_days": 30},
            "costs": {}}
    # ltgp = 16000*0.6 = 9600; cac = 6000/6 = 1000; ratio = 9.6
    healthy = m1_ltgp_cac(snap, {"ltgp_cac_target": 3.0})
    assert healthy["status"] == "healthy" and healthy["benchmark"] == 3.0
    # raise target well above the ratio (9.6 < watch band 2/3·20 = 13.3) → critical
    strict = m1_ltgp_cac(snap, {"ltgp_cac_target": 20.0})
    assert strict["benchmark"] == 20.0 and strict["status"] == "critical"
    # a target the ratio clears into the watch band only
    assert m1_ltgp_cac(snap, {"ltgp_cac_target": 12.0})["status"] == "watch"


def test_hormozi_gross_margin_settable(monkeypatch, tmp_path):
    snap = {"xero": {"gross_margin_pct": 47, "revenue": 80000, "gross_profit": 37600}}
    # default floor 45 / target 50 → 47 is "watch"
    assert m4_gross_margin(snap, {})["status"] == "watch"
    # lower the floor to 40 and target to 45 → 47 now healthy
    assert m4_gross_margin(snap, {"gross_margin_floor": 40.0, "gross_margin_target": 45.0})["status"] == "healthy"


def test_pending_is_store_backed_survives_worker_switch(monkeypatch, tmp_path):
    # The confirmation must survive a "yes" landing on a different gunicorn worker —
    # i.e. it lives in the shared store file, not process memory. Simulate by reading
    # pending back fresh (any worker re-_load()s the same file).
    _fresh(monkeypatch, tmp_path)
    manual_targets.handle_turn("set the ROAS target to 4.5", "tok")
    pend = manual_targets._get_pending("tok")
    assert pend and pend["key"] == "roas_target" and pend["new"] == 4.5
    # A different "worker" (no in-memory state) confirms via the same store file.
    reply, handled = manual_targets.handle_turn("yes", "tok")
    assert handled and "now 4.5" in reply
    assert manual_targets._get_pending("tok") is None  # cleared after commit


def test_affordability_questions_do_not_trigger_command(monkeypatch, tmp_path):
    """Genuine financial questions with numbers must NOT hit the targets command menu."""
    import manual_targets as mt
    monkeypatch.setattr(mt, "STORE", str(tmp_path / "t.json"), raising=False)
    for q in ["can we afford to bump standard SMM salary to 35k PHP, then push Gabie to 40k?",
              "what if we raise Gabie to 40k",
              "can we afford a 40k hire",
              "should we change our LTGP:CAC to 3",
              "how much runway do we have"]:
        mt._clear_pending("tok")
        assert mt.handle_turn(q, "tok")[1] is False, q


def test_real_set_commands_still_work(monkeypatch, tmp_path):
    import manual_targets as mt
    monkeypatch.setattr(mt, "STORE", str(tmp_path / "t2.json"), raising=False)
    for q in ["set the LTGP:CAC target to 3.5", "gross margin benchmark to 50%",
              "CAC ceiling to 4000", "move the ROAS target to 5", "set the MRR goal to 100k"]:
        mt._clear_pending("tok")
        assert mt.handle_turn(q, "tok")[1] is True, q
