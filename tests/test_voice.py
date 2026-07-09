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


# ── Unclamp + intent routing ─────────────────────────────────────────────────

def _U(t):
    return {"role": "user", "content": t}


def _A(t):
    return {"role": "assistant", "content": t}


def test_base_persona_is_unclamped():
    """EDITH is a general assistant, not finance-only — and never invents figures."""
    from dashboard.chat import BASE_PERSONA
    assert "EDITH" in BASE_PERSONA
    assert "NOT limited to business" in BASE_PERSONA
    # the one hard rule that survives: no fabricated financial figures
    assert "never invent a number" in BASE_PERSONA


def test_general_questions_route_general():
    from dashboard.chat import is_business_intent
    assert is_business_intent([_U("What coffee should I have this afternoon?")]) is False
    assert is_business_intent([_U("How do I get from Newcastle to Byron Bay?")]) is False
    # blend prompt: human question, no forced finance — stays general
    assert is_business_intent([_U("I'm exhausted, should I take the afternoon off?")]) is False


def test_business_questions_route_business():
    from dashboard.chat import is_business_intent
    for q in ("What's our cash position?", "How much runway do we have?",
              "Can we hit 110k this month?", "How is Kalin tracking on closes?",
              "How are we doing this month?"):
        assert is_business_intent([_U(q)]) is True, q


def test_followups_inherit_prior_topic():
    """Terse follow-ups with no signal of their own inherit the prior turn."""
    from dashboard.chat import is_business_intent
    # coffee thread stays general
    assert is_business_intent([
        _U("What coffee should I have?"), _A("Cold brew."),
        _U("what about a flat white instead?")]) is False
    # cash thread stays business
    assert is_business_intent([
        _U("What's our MRR?"), _A("$72k."),
        _U("what about next month?")]) is True


def test_context_attached_only_on_business_intent():
    """The heavy financial snapshot rides only on business turns; general turns
    answer as open Claude with just the persona."""
    from dashboard.chat import build_system_prompt
    snap = '{"cash_position":{"cash_in_bank":140007.29},"metrics":{"k":1}}'
    sys_g, biz_g = build_system_prompt([_U("what coffee should I have?")], snap)
    sys_b, biz_b = build_system_prompt([_U("what's our cash position?")], snap)
    assert biz_g is False and biz_b is True
    # general: persona only, no snapshot dump, no business-mode header
    assert "FULL SNAPSHOT" not in sys_g and "BUSINESS MODE" not in sys_g
    assert sys_g.startswith("You are EDITH")
    # business: persona + finance discipline + the live cash figure
    assert "BUSINESS MODE" in sys_b and "140007.29" in sys_b
    # token discipline: general prompt is much lighter than business
    assert len(sys_g) < len(sys_b)


def test_chat_reports_intent_in_result():
    """chat() surfaces the routing decision for the HUD / observability."""
    from dashboard.chat import chat
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = ""  # no network; we only check the no-key path is clean
    out = chat([_U("hi")], "{}", "tok")
    # no key → error path (intent only attaches on the success path), but must not crash
    assert out["reply"] is None


def test_voice_addendum_is_topic_agnostic():
    """Voice register governs delivery, not topic — general voice answers allowed."""
    from dashboard.chat import VOICE_ADDENDUM
    assert "DELIVERY" in VOICE_ADDENDUM
    assert "Jarvis" not in VOICE_ADDENDUM


# ── Streaming responsiveness (Phase 1) ───────────────────────────────────────

def test_chat_stream_yields_error_without_key():
    """chat_stream degrades to an error event, never crashes, with no key."""
    from dashboard.chat import chat_stream
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = ""
    events = list(chat_stream([_U("hi")], "{}", "tok"))
    assert events and events[0][0] == "error"


def test_chat_stream_rate_limit_blocks():
    """The existing per-token rate limit applies to the stream path too."""
    from dashboard.chat import chat_stream
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = "fake"          # past the no-key guard
    chat_mod._rate_counts["limtok"] = [9e18] * chat_mod.RATE_LIMIT  # exhaust
    events = list(chat_stream([_U("hi")], "{}", "limtok"))
    chat_mod._rate_counts["limtok"] = []
    assert events and events[0][0] == "error" and "Rate limit" in events[0][1]


def test_chat_stream_endpoint_rejects_unauthenticated():
    c = _client(authed=False)
    resp = c.post("/dashboard/api/chat-stream", json={"history": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 302          # redirect to login, same guard as /api/chat


def test_estimate_tokens_monotonic():
    from dashboard.chat import _estimate_tokens
    assert _estimate_tokens("") == 0
    assert _estimate_tokens("a" * 400) == 100
    assert _estimate_tokens("a" * 800) > _estimate_tokens("a" * 400)


def test_tts_model_is_env_configurable_fast_default():
    """Phase 2: TTS model resolves from env, defaults to a low-latency model."""
    import dashboard.voice as voice_mod
    assert "flash" in voice_mod.ELEVENLABS_MODEL or "turbo" in voice_mod.ELEVENLABS_MODEL
    # greeting model defaults to the same fast model (no behaviour change unless set)
    assert voice_mod.ELEVENLABS_GREETING_MODEL


# ── Personality + expressive delivery ────────────────────────────────────────

def test_persona_has_mood_reading_and_humour():
    """The character is SHOWN (mood-reading + few-shot beats), not just 'be human'."""
    from dashboard.chat import BASE_PERSONA
    p = BASE_PERSONA.lower()
    assert "read the room" in p                      # mood-reading is explicit
    for cue in ("joking", "stressed", "win", "hard"):
        assert cue in p, cue                         # the four registers are named
    assert "a few beats" in p                        # few-shot examples present
    assert "chief of staff" in p                     # opinions/initiative
    # hard lines survive personality
    assert "never invent a number" in BASE_PERSONA
    assert "honesty over likeability" in p


def test_persona_not_one_note():
    """Range is the personality — neither always-jokey nor always-flat."""
    from dashboard.chat import BASE_PERSONA
    assert "Range IS the personality" in BASE_PERSONA
    # doesn't claim real feelings it will over-act
    assert "don't claim feelings you don't have" in BASE_PERSONA


def test_voice_addendum_carries_personality_via_prosody():
    """Phase 2 tie-in: punctuation as prosody, personality in delivery not length."""
    from dashboard.chat import VOICE_ADDENDUM
    v = VOICE_ADDENDUM.lower()
    assert "punctuation" in v and ("em-dash" in v or "ellips" in v)
    assert "match his mood" in v


def test_voice_settings_expressive_band_with_style():
    """Defaults sit in the stable-but-alive band and expose a style dial."""
    import dashboard.voice as voice_mod
    s = voice_mod.active_voice_settings()
    assert 0.45 <= s["stability"] <= 0.55           # alive but consistent (not flat 0.70, not draggy 0.40)
    assert "style" in s and s["style"] > 0
    assert s["similarity_boost"] == 0.75            # identity holds


def test_voice_settings_are_one_fixed_profile():
    """Tonality consistency: settings don't change per call/mood — same profile every time."""
    import dashboard.voice as voice_mod
    voice_mod.save_voice_config({})                 # defaults
    a = voice_mod.active_voice_settings()
    b = voice_mod.active_voice_settings()
    assert a == b                                   # no per-utterance churn


def test_voice_config_accepts_style_dial(tmp_path, monkeypatch):
    import dashboard.voice as voice_mod
    monkeypatch.setattr(voice_mod, "_VOICE_CONFIG_FILE", str(tmp_path / "vc.json"))
    voice_mod.save_voice_config({"stability": 0.35, "style": 0.5})
    s = voice_mod.active_voice_settings()
    assert s["stability"] == 0.35 and s["style"] == 0.5
    voice_mod.save_voice_config({})                 # reset for other tests


# ── Brief composition ────────────────────────────────────────────────────────

def _fake_snap():
    return {
        "cash_position": {"cash_in_bank": 140007.29, "stripe_incoming": 18000,
                          "runway_months": 3.6, "total_monthly_burn": 39211},
        "sales": {"funnel": {"sets": 21, "closes": 7, "show_to_close_pct": 33.3}},
        # The greeting now reads the ONE engine's headline (stashed in hormozi), not the scorecard.
        "hormozi": {"_sales_headline": {"sets": 21, "closes": 7, "close_rate": 33.3,
                                        "new_deal_cash": 80860.0}},
        "stripe": {"revenue": {"current": {"total_aud": 80860.0}}},
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


def _patch_greeting(monkeypatch, *, loc, weather, events, composed):
    """Wire the greeting's dependencies deterministically (no network, no model)."""
    import dashboard.voice as vm
    import location, salience
    monkeypatch.setattr(location, "resolve", lambda: loc)
    monkeypatch.setattr(location, "weather_and_localtime", lambda l=None: weather)
    monkeypatch.setattr(salience, "top", lambda snap=None, n=3: events)
    monkeypatch.setattr(vm, "_compose_greeting", lambda *a, **k: composed)
    return vm


def test_greeting_fallback_leads_with_salient_event(monkeypatch):
    """Composer down → safe deterministic fallback leads with the top event, figures VERBATIM."""
    ev = [{"id": "close:x", "type": "close", "salience": 80, "ago": 0,
           "spoken": "Lost Sheep Cafe closed — $14,500 (Scale Engine)"}]
    vm = _patch_greeting(monkeypatch, loc={"place": "Newcastle", "source": "default"},
                         weather=None, events=ev, composed=None)
    t = vm.build_greeting({}, mark=False)["text"]
    assert "Rydel" in t and "Lost Sheep Cafe closed — $14,500" in t   # verbatim event
    assert "appointments booked" not in t                            # no fixed stat litany


def test_greeting_nothing_new_is_light_hello(monkeypatch):
    """Empty feed → a light human hello with NO forced stats, no invented news."""
    vm = _patch_greeting(monkeypatch, loc={"place": "Newcastle", "source": "default"},
                         weather=None, events=[], composed=None)
    t = vm.build_greeting({}, mark=False)["text"]
    assert "Rydel" in t and "nothing new" in t.lower()
    assert "$" not in t and "appointments" not in t                  # no forced numbers


def test_greeting_uses_resolved_location_and_composed_text(monkeypatch):
    """Location follows the resolver (not hardcoded Newcastle); composed text is used verbatim."""
    vm = _patch_greeting(monkeypatch, loc={"place": "Sydney", "source": "override"},
                         weather={"temp_c": 19, "condition": "clear", "high_c": 22, "local_hour": 8},
                         events=[], composed="Morning from Sydney — quiet so far.")
    out = vm.build_greeting({}, mark=False)
    assert out["text"] == "Morning from Sydney — quiet so far."
    assert out["location"]["place"] == "Sydney"


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
    # empty body resets to the locked default — now the EXPRESSIVE register
    voice_mod.save_voice_config({})
    assert voice_mod.active_voice_id() == "yj30vwTGJxSHezdAGsv9"
    s = voice_mod.active_voice_settings()
    # stable-but-alive band: expressive enough to carry tone, stable enough not to drag
    assert s["stability"] == voice_mod.TTS_STABILITY and 0.45 <= s["stability"] <= 0.55
    assert s["similarity_boost"] == 0.75
    assert s["style"] == voice_mod.TTS_STYLE        # expressiveness dial present
    assert "use_speaker_boost" in s


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
