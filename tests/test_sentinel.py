"""
tests/test_sentinel.py — PHASE H proof pack. The build ships only with:

  · every layer runs ≥ once (L1 / L2-extras / L3 — logs in the test output),
  · a FORCED ESCALATION: a planted L1 signal triggers the TARGETED deep pass
    on that domain only,
  · a FORCED HEAL in sandbox: a stale (epoch-superseded) rollup → auto-rebuild
    kicked → journaled + one quiet feed line,
  · the KILL SWITCH (AD_SENTINEL_PAUSE_HEALS) demonstrably halts heals while
    detection keeps running,
  · budget breaches alert LOUD; cost rows are auditable data,
  · F15: the verified-show-ratio decline is a tracked L1 metric that alerts.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ad_sentinel
import kv_store
import resolution
from tests.test_ads_dashboard import _fake_result


def _fresh(monkeypatch, result=None):
    import attribution_engine as AE
    result = result or _fake_result()
    monkeypatch.setattr(AE, "compute", lambda **kw: result)
    kv_store.put("sentinel:metrics", [])
    kv_store.put("sentinel:cost", [])
    kv_store.put("sentinel:escalations", [])
    kv_store.put("ads_truth:flags", [])
    kv_store.delete("stripe:partial_pull")
    monkeypatch.delenv("AD_SENTINEL_PAUSE_HEALS", raising=False)
    return result


# ── L1 runs + cost rows ──────────────────────────────────────────────────────

def test_l1_runs_records_metrics_and_cost(monkeypatch):
    _fresh(monkeypatch)
    out = ad_sentinel.hourly_tick(force=True)
    assert out["layer"] == "L1"
    assert out["cost"]["layer"] == "L1" and out["cost"]["over_budget"] is False
    hist = kv_store.get("sentinel:metrics")
    assert hist and set(hist[-1]["metrics"]) >= {"leads", "closes", "cash", "spend",
                                                 "verified_show_ratio"}
    assert (kv_store.get("sentinel:state") or {}).get("L1")


def test_l1_single_flight_per_hour(monkeypatch):
    _fresh(monkeypatch)
    from helpers import now_sydney
    kv_store.delete(f"sentinel:L1:{now_sydney().strftime('%Y-%m-%dT%H')}")
    assert ad_sentinel.hourly_tick() is not None
    assert ad_sentinel.hourly_tick() is None          # same hour → loser walks


# ── forced escalation: planted signal → targeted pass only ───────────────────

def test_forced_escalation_targeted_pass(monkeypatch):
    result = _fake_result()
    result["reconciliation"] = {"ok": False, "checks": {}}   # planted L1 signal
    _fresh(monkeypatch, result)
    targeted = []
    import ads_truth
    monkeypatch.setattr(ads_truth, "quad_check",
                        lambda days=90: (targeted.append(days) or
                                         {"facts": 5, "hard_disagreements": 0,
                                          "agreements": 5, "table": [], "days": days}))
    out = ad_sentinel.hourly_tick(force=True)
    assert any(s["domain"] == "recon" for s in out["signals"])
    assert targeted == [90]                            # the TARGETED deep pass ran
    esc = kv_store.get("sentinel:escalations")
    assert esc and esc[-1]["domain"] == "recon" and esc[-1]["source"] == "L1"
    # spend follows signal — no full-I17/L3 blanket pass was involved
    flags = " ".join(f["reason"] for f in kv_store.get("ads_truth:flags"))
    assert "ESCALATION [L1→recon]" in flags


# ── F15: verified-show-ratio decline alerts ──────────────────────────────────

def test_vsr_decline_is_watched_and_alerts(monkeypatch):
    _fresh(monkeypatch)
    kv_store.put("sentinel:metrics",
                 [{"at": "2026-08-09T10:00", "metrics": {"verified_show_ratio": 0.90}}])
    kv_store.put("derived:dates", {
        f"vsr lead {i}": {"show_date": {"date": "2026-08-01", "provenance": "derived:ghl-appt",
                                        "evidence": {"appointment_id": "a"},
                                        "verification": {"state": "verified" if i < 8
                                                         else "unverified"}}}
        for i in range(10)})            # vsr now 0.8 — a 0.10 decline
    out = ad_sentinel.hourly_tick(force=True)
    assert any(s["domain"] == "metric:verified_show_ratio" for s in out["signals"])
    flags = " ".join(f["reason"] for f in kv_store.get("ads_truth:flags"))
    assert "verified-show ratio DECLINED" in flags


# ── forced heal: stale rollup → rebuilt → journaled + quiet line ─────────────

def test_forced_heal_stale_rollup_rebuilt_and_journaled(monkeypatch):
    _fresh(monkeypatch)
    kv_store.put("integrity:autofix_log", [])
    kv_store.put("resolution:journal", [])
    kv_store.put("attr:rollup:cohort:30",
                 {"at": time.time(), "epoch": resolution.derived_epoch() - 1 or -1,
                  "board": {}, "engine": None})
    for basis in ("cohort", "activity"):
        for days in (60, 90, 3650):
            kv_store.delete(f"attr:rollup:{basis}:{days}")
    kv_store.delete("attr:rollup:activity:30")
    rebuilds = []
    import dashboard.ads as ads_mod
    monkeypatch.setattr(ads_mod, "_refresh_async", lambda d, b: rebuilds.append((b, d)))
    monkeypatch.setattr(resolution, "resolve_dates", lambda: {})
    out = ad_sentinel.heal_pass()
    assert out["paused"] is False
    assert {"kind": "rollup_rebuild", "target": "cohort:30"} in out["heals"]
    assert rebuilds == [("cohort", 30)]               # rebuild kicked
    # journaled into the DURABLE evidence stream (heal: prefix, F2)
    assert any(e["rule"].startswith("heal:rollup_rebuild")
               for e in resolution.evidence_journal())
    # one QUIET feed line (hygiene lane, not ACTION)
    quiet = [f for f in kv_store.get("ads_truth:flags")
             if f["metric"] == "ads_truth" and "heal: stale rollup" in f["reason"]]
    assert len(quiet) == 1


# ── the kill switch: heals halt, detection continues ─────────────────────────

def test_kill_switch_halts_heals_detection_continues(monkeypatch):
    _fresh(monkeypatch)
    monkeypatch.setenv("AD_SENTINEL_PAUSE_HEALS", "1")
    kv_store.put("attr:rollup:cohort:30",
                 {"at": time.time(), "epoch": resolution.derived_epoch() - 1 or -1,
                  "board": {}, "engine": None})
    rebuilds = []
    import dashboard.ads as ads_mod
    monkeypatch.setattr(ads_mod, "_refresh_async", lambda d, b: rebuilds.append((b, d)))
    out = ad_sentinel.heal_pass()
    assert out["paused"] is True and out["heals"] == []
    assert rebuilds == []                             # NOTHING healed
    flags = " ".join(f["reason"] for f in kv_store.get("ads_truth:flags"))
    assert "heals PAUSED" in flags and "detection continues" in flags
    # detection: L1 still runs and still signals under the paused switch
    result = _fake_result()
    result["reconciliation"] = {"ok": False, "checks": {}}
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: result)
    import ads_truth
    monkeypatch.setattr(ads_truth, "quad_check",
                        lambda days=90: {"facts": 0, "hard_disagreements": 0,
                                         "agreements": 0, "table": [], "days": days})
    out2 = ad_sentinel.hourly_tick(force=True)
    assert any(s["domain"] == "recon" for s in out2["signals"])


# ── L2 extras + drift diff ───────────────────────────────────────────────────

def test_l2_extras_run_after_the_sweep_stamp(monkeypatch):
    _fresh(monkeypatch)
    from helpers import today_sydney
    today = str(today_sydney())
    kv_store.put("ads_truth:sweep_tick", today)
    kv_store.delete(f"sentinel:L2:{today}")
    kv_store.put("ads_truth:accuracy", [
        {"date": "2026-08-08", "disagreements": 1, "invariant_violations": 0,
         "verified_show_ratio": 0.9},
        {"date": today, "disagreements": 4, "invariant_violations": 0,
         "verified_show_ratio": 0.85}])
    monkeypatch.setattr(resolution, "resolve_dates", lambda: {})
    out = ad_sentinel.nightly_extras()
    assert out and out["layer"] == "L2"
    assert out["drift"]["disagreements"]["worse"] is True
    flags = " ".join(f["reason"] for f in kv_store.get("ads_truth:flags"))
    assert "L2 drift" in flags
    assert ad_sentinel.nightly_extras() is None       # single-flight per day


def test_l2_extras_wait_for_the_sweep(monkeypatch):
    _fresh(monkeypatch)
    kv_store.put("ads_truth:sweep_tick", "2020-01-01")
    assert ad_sentinel.nightly_extras() is None


# ── L3 weekly: full I17 + quad + claims + security replay + perf ─────────────

def test_l3_weekly_all_legs(monkeypatch):
    _fresh(monkeypatch)
    import ads_truth
    monkeypatch.setattr(ads_truth, "quad_check",
                        lambda days=90: {"facts": 10, "hard_disagreements": 0,
                                         "agreements": 10, "table": [], "days": days})
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    from helpers import today_sydney
    kv_store.delete(f"sentinel:L3:{today_sydney().strftime('%G-W%V')}")
    out = ad_sentinel.weekly_tick(force=True)
    assert out["full_i17"]["cells"] > 0 and out["full_i17"]["drift"] == 0
    assert out["quad_check_90d"]["hard_disagreements"] == 0
    assert out["claims_reproof"]["ok"] is True
    sec = out["security_replay"]
    assert sec["debug_stripe_ping"] == 401 and sec["debug_sources"] == 401
    assert sec["roster_taint_echoed"] is False and sec["ok"] is True
    assert out["perf"]["ok"] is True
    assert out["cost"]["layer"] == "L3"


# ── budget breach is LOUD ────────────────────────────────────────────────────

def test_budget_breach_alerts_loud(monkeypatch):
    _fresh(monkeypatch)
    monkeypatch.setitem(ad_sentinel.BUDGETS, "L1", {"runtime_s": 0.0, "api_calls": 0})
    out = ad_sentinel.hourly_tick(force=True)
    assert out["cost"]["over_budget"] is True
    flags = [f for f in kv_store.get("ads_truth:flags")
             if f["metric"] == "ads_truth_action" and "BUDGET BREACH" in f["reason"]]
    assert flags


# ── the queue: judgment-shaped work files, never guesses ─────────────────────

def test_queue_item_writes_file_and_feed(monkeypatch, tmp_path):
    _fresh(monkeypatch)
    qp = tmp_path / "SENTINEL_QUEUE.md"
    monkeypatch.setattr(ad_sentinel, "QUEUE_PATH", str(qp))
    ad_sentinel.queue_item("test judgment item", "repro: evidence here", rank="P2")
    assert "test judgment item" in qp.read_text()
    flags = " ".join(f["reason"] for f in kv_store.get("ads_truth:flags"))
    assert "queued (P2): test judgment item" in flags
