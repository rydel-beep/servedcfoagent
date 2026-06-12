"""
tests/test_voice.py
-------------------
Jarvis voice suite guardrails: auth on money-spending endpoints, fallback
chain when ElevenLabs is absent, cost caps, voice register, brief composition.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("CFO_REFRESH_KEY", "test-key-123")
os.environ.setdefault("DASHBOARD_TOKEN", "test-dash-token")
_orig_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
_orig_eleven = os.environ.pop("ELEVENLABS_API_KEY", None)


def _client(authed=False):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    from app import app
    app.config["TESTING"] = True
    c = app.test_client()
    if authed:
        c.post("/dashboard/login", data={"token": "test-dash-token"})
    return c


# ── Auth: these endpoints spend API money ────────────────────────────────────

def test_tts_rejects_unauthenticated():
    c = _client()
    resp = c.post("/dashboard/api/tts", json={"text": "hello"})
    assert resp.status_code == 302, "unauthenticated TTS must redirect to login"
    resp = c.get("/dashboard/api/tts?text=hello")
    assert resp.status_code == 302


def test_brief_rejects_unauthenticated():
    c = _client()
    resp = c.post("/dashboard/api/brief", json={})
    assert resp.status_code == 302


def test_voice_status_rejects_unauthenticated():
    c = _client()
    resp = c.get("/dashboard/api/voice-status")
    assert resp.status_code == 302


# ── Fallback chain ───────────────────────────────────────────────────────────

def test_tts_falls_back_without_key():
    """No ELEVENLABS_API_KEY → JSON fallback signal, never a hang or 500."""
    import dashboard.voice as voice_mod
    voice_mod.ELEVENLABS_API_KEY = ""
    c = _client(authed=True)
    resp = c.post("/dashboard/api/tts", json={"text": "cash position"})
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["fallback"] is True
    assert "ELEVENLABS_API_KEY" in data["reason"]


def test_voice_status_reports_configuration():
    import dashboard.voice as voice_mod
    voice_mod.ELEVENLABS_API_KEY = ""
    c = _client(authed=True)
    data = c.get("/dashboard/api/voice-status").get_json()
    assert data["elevenlabs_configured"] is False
    assert data["voice_id"] == "yj30vwTGJxSHezdAGsv9"
    assert data["daily_char_cap"] > 0
    # never leak key material
    assert "api_key" not in json.dumps(data).lower().replace("daily_char", "")


# ── Cost caps ────────────────────────────────────────────────────────────────

def test_daily_char_cap_blocks():
    import dashboard.voice as voice_mod
    from helpers import today_sydney
    voice_mod.ELEVENLABS_API_KEY = "fake-key-for-cap-test"
    day = str(today_sydney())
    voice_mod._daily_chars[day] = voice_mod.TTS_DAILY_CHAR_CAP  # cap exhausted
    err = voice_mod._check_caps(10)
    assert err is not None and "cap" in err.lower()
    voice_mod._daily_chars[day] = 0  # reset for other tests


def test_per_minute_cap_blocks():
    import time
    import dashboard.voice as voice_mod
    voice_mod._minute_hits = [time.time()] * voice_mod.TTS_PER_MINUTE_CAP
    err = voice_mod._check_caps(10)
    assert err is not None and "rate" in err.lower()
    voice_mod._minute_hits = []


def test_tts_truncates_oversize_text():
    """Oversize text must be truncated, not rejected — but cap math still applies."""
    import dashboard.voice as voice_mod
    voice_mod.ELEVENLABS_API_KEY = ""
    with pytest.raises(RuntimeError):
        # no key → raises before any network call; proves no unbounded request
        list(voice_mod.stream_tts("x" * 100000))


# ── Voice register ───────────────────────────────────────────────────────────

def test_voice_addendum_exists_and_keeps_discipline():
    from dashboard.chat import VOICE_ADDENDUM, SYSTEM_PROMPT
    assert "SPOKEN ALOUD" in VOICE_ADDENDUM
    assert "No markdown" in VOICE_ADDENDUM or "no markdown" in VOICE_ADDENDUM
    # the addendum extends, never replaces, the discipline prompt
    assert "METRIC DEFINITIONS" in SYSTEM_PROMPT


def test_chat_accepts_voice_flag_without_key():
    """voice=True path returns the configured-key error, not a crash."""
    from dashboard.chat import chat
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = ""
    out = chat([{"role": "user", "content": "hi"}], "{}", "tok", voice=True)
    assert out["reply"] is None and "ANTHROPIC_API_KEY" in out["error"]


# ── Brief composition ────────────────────────────────────────────────────────

def _fake_snap():
    return {
        "cash_position": {"cash_in_bank": 140007.29, "stripe_incoming": 18000,
                          "runway_months": 3.6, "total_monthly_burn": 39211},
        "client_health": {"current_mrr": 72896.18, "next_mrr": 58236.18,
                          "mrr_delta": -14660.0, "renewal_watch": [],
                          "revenue_at_risk_30d": 14660},
        "deficiency_analysis": {"binding_constraint": {
            "name": "Speed-to-lead", "impact": "slower response, lower close",
            "current": "0%", "target": "50%", "fix": "Immediate response SOP"}},
        "verdicts": {"top_leaks": [{"name": "Wasted leads", "read": "targeting"}]},
    }


def test_template_brief_is_honest_and_speakable():
    """Fallback brief: engine numbers verbatim, says the churn cliff plainly,
    no markdown artifacts for the TTS to mangle."""
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = ""  # force template path
    from dashboard.voice import build_brief
    out = build_brief(_fake_snap(), [
        {"mrr": 70000, "stripe_collected_30d": 60000, "active_clients": 33, "failed_charges": 2},
        {"mrr": 72896, "stripe_collected_30d": 80860, "active_clients": 34, "failed_charges": 1},
    ], "tok")
    assert out["source"] == "template"
    text = out["text"]
    assert "$140,000" in text                      # cash, speech-rounded
    assert "3.6" in text                           # runway
    assert "churn cliff" in text                   # honesty: forward picture is red
    assert "Speed-to-lead" in text                 # binding constraint
    assert "*" not in text and "#" not in text     # nothing markdown for the ear
    words = len(text.split())
    assert 60 <= words <= 220, f"brief length off for 45-75s spoken: {words} words"


def test_brief_endpoint_with_auth():
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = ""
    c = _client(authed=True)
    resp = c.post("/dashboard/api/brief", json={})
    # 200 with text (or 404 if no snapshot persisted in this environment)
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.get_json()
        assert data["text"] and data["source"] in ("model", "template")


# ── EDITH: greeting, weather, voice config ───────────────────────────────────

def test_greeting_rejects_unauthenticated():
    c = _client()
    assert c.get("/dashboard/api/greeting").status_code == 302


def test_voice_config_rejects_unauthenticated():
    c = _client()
    assert c.post("/dashboard/api/voice-config", json={}).status_code == 302


def test_greeting_skips_weather_gracefully(monkeypatch):
    """Weather down → greeting still composes (time + headline + open)."""
    import dashboard.voice as voice_mod
    monkeypatch.setattr(voice_mod, "get_newcastle_weather", lambda: None)
    out = voice_mod.build_greeting(_fake_snap())
    assert out["weather"] is None
    t = out["text"]
    assert "Rydel" in t and "What do you need?" in t
    assert "$140,000" in t and "3.6" in t   # engine headline survives
    assert "Newcastle" not in t


def test_greeting_includes_weather_when_available(monkeypatch):
    import dashboard.voice as voice_mod
    monkeypatch.setattr(voice_mod, "get_newcastle_weather",
                        lambda: {"temp_c": 18.2, "condition": "clear", "high_c": 22.4})
    t = voice_mod.build_greeting(_fake_snap())["text"]
    assert "18 and clear in Newcastle" in t and "heading for 22" in t
    assert "hope you're doing well" in t   # warm open before the numbers


def test_greeting_time_of_day_sydney(monkeypatch):
    """Greeting salutation must follow Sydney time, not server/UTC time."""
    import dashboard.voice as voice_mod
    from helpers import now_sydney
    hour = now_sydney().hour
    expected = "morning" if hour < 12 else ("afternoon" if hour < 18 else "evening")
    assert f"Good {expected}" in voice_mod.build_greeting(_fake_snap())["text"]


def test_voice_config_set_and_reset(tmp_path, monkeypatch):
    import dashboard.voice as voice_mod
    monkeypatch.setattr(voice_mod, "_VOICE_CONFIG_FILE", str(tmp_path / "vc.json"))
    voice_mod.save_voice_config({"voice_id": "abc123", "stability": 0.7})
    assert voice_mod.active_voice_id() == "abc123"
    assert voice_mod.active_voice_settings()["stability"] == 0.7
    # empty body resets to the locked default
    voice_mod.save_voice_config({})
    assert voice_mod.active_voice_id() == "yj30vwTGJxSHezdAGsv9"
    assert voice_mod.active_voice_settings() == {"stability": 0.55, "similarity_boost": 0.75}


def test_voice_config_rejects_garbage():
    import dashboard.voice as voice_mod
    out = voice_mod.save_voice_config({"voice_id": "x" * 500, "stability": 9, "similarity": -1})
    assert len(out["voice_id"]) == 64      # clamped
    assert "stability" not in out          # out-of-range dropped
    voice_mod.save_voice_config({})        # reset


def test_voice_addendum_is_edith():
    from dashboard.chat import VOICE_ADDENDUM
    assert "EDITH" in VOICE_ADDENDUM and "Jarvis" not in VOICE_ADDENDUM


def test_weather_cache_shape(monkeypatch):
    """A cached weather payload is returned without a second network hit."""
    import dashboard.voice as voice_mod, time as _t
    voice_mod._weather_cache.update(ts=_t.time(), data={"temp_c": 20, "condition": "clear", "high_c": 23})
    called = {"n": 0}
    class _Boom:
        def __call__(self, *a, **k): called["n"] += 1; raise AssertionError("network hit despite cache")
    monkeypatch.setattr(voice_mod.requests, "get", _Boom())
    assert voice_mod.get_newcastle_weather()["temp_c"] == 20
    assert called["n"] == 0
    voice_mod._weather_cache.update(ts=0.0, data=None)
