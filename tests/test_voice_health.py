"""tests/test_voice_health.py — D1: silent degradation impossible. Failure recording,
degraded status, salience watermark ids, the registry row, the EDITH answer."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import voice_health as VH


def _reset():
    import kv_store
    kv_store.put("voice:health", None)
    kv_store.put("voice:canary", None)


def test_failure_then_ok_flips_degraded():
    _reset()
    VH.record_failure("ElevenLabs returned 400")
    s = VH.status()
    assert s["degraded"] and "400" in s["reason"] and s["fails_today"] == 1
    VH.record_ok()
    assert VH.status()["degraded"] is False
    VH.record_failure("x"); VH.record_failure("y")
    assert VH.status()["fails_today"] == 3          # same-day counter accumulates


def test_salience_fires_while_degraded_watermark_daily():
    _reset()
    VH.record_failure("ElevenLabs returned 400")
    ev = VH.salience_events()
    assert len(ev) == 1 and ev[0]["type"] == "voice_fallback"
    assert ev[0]["id"].startswith("voice_fallback:")   # day-bucketed → re-fires daily
    assert "fallback voice" in ev[0]["spoken"]
    VH.record_ok()
    assert VH.salience_events() == []


def test_quota_warning_before_exhaustion():
    _reset()
    import kv_store
    VH.record_ok()
    kv_store.put("voice:canary", {"ts": "2026-08-06T10:00:00", "ok": True,
                                  "quota": {"used": 90000, "limit": 100000, "pct": 90.0}})
    ev = VH.salience_events()
    assert any(e["type"] == "voice_quota" and "90.0%" in e["spoken"] for e in ev)


def test_automation_row_states():
    _reset()
    assert VH.automation_row()["state"] == "UNKNOWN"       # canary never ran
    VH.record_failure("ElevenLabs returned 400")
    assert VH.automation_row()["state"] == "FAILING"
    import kv_store
    VH.record_ok()
    kv_store.put("voice:canary", {"ts": "2026-08-06T10:00:00", "ok": True, "quota": None})
    assert VH.automation_row()["state"] == "RUNNING"


def test_edith_voice_answer_truthful():
    _reset()
    VH.record_failure("ElevenLabs returned 400")
    r, h = VH.handle_voice_health_command("is your voice okay?")
    assert h and "failing" in r and "fallback" in r
    VH.record_ok()
    r, h = VH.handle_voice_health_command("voice status")
    assert h and "healthy" in r
    assert VH.handle_voice_health_command("hello")[1] is False


def test_tts_route_records_failures():
    src = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "routes.py")).read()
    assert "voice_health.record_failure" in src and "voice_health.record_ok" in src
    # the client announces the fallback out loud, once per session
    js = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "static",
                           "js", "edith.js")).read()
    assert "fallbackAnnouncePrefix" in js and js.count("fallbackAnnouncePrefix() + text") == 4
    assert "on the fallback voice" in js
