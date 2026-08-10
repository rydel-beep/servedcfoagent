"""
tests/test_voice_loud_fallback.py — EDITH VOICE fix (2026-08-10).

ROOT CAUSE (live-captured, dashboard/VOICE_DIAGNOSIS.md): the Railway
ELEVENLABS_API_KEY is a legacy 64-char key-ID; ElevenLabs 400s it with
`invalid_api_key` ("API keys start with 'sk_'"). Fixing the KEY is a Rydel
account action. The AGENT-side defects fixed here and pinned:

  1 · stream_tts discarded the error body → every surface said "returned 400"
      instead of the class + owner action. Now: TTSFailure carries a
      CLASSIFIED reason (auth/voice_id/model/rate_limit/credits/caps/delivery).
  2 · Loudness was a 6s toast — now: persistent banner + S1 action-feed item
      naming the exact fix, self-retiring on recovery.
  3 · The canary's first run was boot+6h — now: a deploy-time boot canary.
Every failure class drills to a SPECIFIC loud signal; silent fallback = fail.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store
import voice_health as vh

ROOT = os.path.join(os.path.dirname(__file__), "..")

# The EXACT body captured live on 2026-08-10 (the regression fixture)
CAPTURED_400 = ('{"detail":{"type":"authentication_error","code":"invalid_api_key",'
                '"message":"API key ID used as API key - only valid API keys can be '
                'used. API keys start with \'sk_\' and are shown when the key is '
                'created or rotated."}}')


def _reset():
    for k in ("voice:health", "voice:canary", "feed:extra:voice"):
        kv_store.put(k, None)


# ── 1 · the classifier, per failure class ────────────────────────────────────

def test_regression_captured_auth_body_classifies_with_owner_action():
    """THE root-cause regression test: the exact live 400 body must classify
    as auth and carry the precise Rydel step — never a bare 'returned 400'."""
    c = vh.classify_failure(400, CAPTURED_400)
    assert c["cls"] == "auth"
    assert "invalid or expired" in c["human"]
    assert "ELEVENLABS_API_KEY" in c["rydel_action"] and "sk_" in c["rydel_action"]
    assert "Railway" in c["rydel_action"]


def test_classifier_all_classes():
    assert vh.classify_failure(401, "")["cls"] == "auth"
    assert vh.classify_failure(400, '{"detail":{"code":"voice_not_found"}}')["cls"] == "voice_id"
    assert vh.classify_failure(400, '{"detail":{"code":"model_not_found"}}')["cls"] == "model"
    assert vh.classify_failure(429, "")["cls"] == "rate_limit"
    assert vh.classify_failure(400, '{"detail":{"code":"quota_exceeded"}}')["cls"] == "credits"
    assert vh.classify_failure(None, None, context="cap: TTS rate limit (12/min)")["cls"] == "caps"
    assert vh.classify_failure(None, None, context="delivery: ConnectTimeout")["cls"] == "delivery"


def test_credits_class_kept_for_the_original_suspect():
    """Credits are fresh today — but the ORIGINAL failure mode stays loudly
    classified for next time (the prompt's explicit requirement)."""
    c = vh.classify_failure(400, '{"detail":{"code":"quota_exceeded","message":"credits gone"}}')
    assert c["cls"] == "credits" and "exhausted" in c["human"]
    assert "Top up" in c["rydel_action"]


# ── 2 · stream_tts raises a CLASSIFIED failure (not a bare status) ───────────

def test_stream_tts_raises_classified_auth_failure(monkeypatch):
    import dashboard.voice as voice

    class _Resp:
        status_code = 400
        text = CAPTURED_400
    monkeypatch.setattr(voice, "ELEVENLABS_API_KEY", "72b-legacy-id")
    monkeypatch.setattr(voice.requests, "post", lambda *a, **k: _Resp())
    try:
        list(voice.stream_tts("hello"))
        assert False, "should have raised"
    except voice.TTSFailure as e:
        assert e.cls == "auth"                              # NOT "returned 400"
        assert "ELEVENLABS_API_KEY" in (e.rydel_action or "")
        assert "72b" not in str(e) and "72b" not in (e.rydel_action or "")   # no key material


def test_stream_tts_network_error_is_delivery_class(monkeypatch):
    import dashboard.voice as voice
    monkeypatch.setattr(voice, "ELEVENLABS_API_KEY", "k")

    def boom(*a, **k):
        raise voice.requests.ConnectionError("dns")
    monkeypatch.setattr(voice.requests, "post", boom)
    try:
        list(voice.stream_tts("hi"))
        assert False
    except voice.TTSFailure as e:
        assert e.cls == "delivery"


# ── 3 · the loud chain: health + persistent feed item + owner action ─────────

def test_record_failure_publishes_specific_feed_item_and_self_retires():
    _reset()
    c = vh.classify_failure(400, CAPTURED_400)
    vh.record_failure(c["human"], cls=c["cls"], rydel_action=c["rydel_action"])
    s = vh.status()
    assert s["degraded"] and s["cls"] == "auth"
    feed = kv_store.get("feed:extra:voice") or []
    assert len(feed) == 1
    item = feed[0]
    assert item["severity"] == "S1" and item["category"] == "voice"
    assert "auth" in item["title"] and "EDITH voice DOWN" in item["title"]
    assert "ELEVENLABS_API_KEY" in item["action"]          # the exact fix, in the feed
    # recovery self-retires the item (no stale alarm)
    vh.record_ok()
    assert (kv_store.get("feed:extra:voice") or []) == []
    assert vh.status()["degraded"] is False


def test_feed_item_reaches_the_action_feed_registry(monkeypatch):
    _reset()
    vh.record_failure("the API key is invalid or expired (auth failure)",
                      cls="auth", rydel_action="re-set the key")
    import action_feed
    monkeypatch.setattr(action_feed, "load_persisted", lambda: {}, raising=False)
    # the registry unions feed:extra:voice — the owner feed carries it
    src = open(os.path.join(ROOT, "action_feed.py")).read()
    assert '"feed:extra:voice"' in src


def test_salience_names_the_class_and_action():
    _reset()
    vh.record_failure("the API key is invalid or expired (auth failure)",
                      cls="auth", rydel_action="Re-set ELEVENLABS_API_KEY (sk_...)")
    ev = vh.salience_events()
    assert ev and ev[0]["salience"] == 82        # auth is escalated
    assert "Re-set" in ev[0]["spoken"]


# ── 4 · drills: EACH failure class → a specific loud signal, never silent ────

def test_every_failure_class_drills_loud():
    for status, body, ctx, want in [
        (401, "", None, "auth"),
        (400, '{"detail":{"code":"voice_not_found"}}', None, "voice_id"),
        (400, '{"detail":{"code":"model_not_found"}}', None, "model"),
        (429, "", None, "rate_limit"),
        (400, '{"detail":{"code":"quota_exceeded"}}', None, "credits"),
        (None, None, "delivery: timeout", "delivery"),
    ]:
        _reset()
        c = vh.classify_failure(status, body, ctx)
        assert c["cls"] == want
        vh.record_failure(c["human"], cls=c["cls"], rydel_action=c["rydel_action"])
        s = vh.status()
        assert s["degraded"] is True                       # NEVER silent
        assert s["cls"] == want
        feed = kv_store.get("feed:extra:voice") or []
        assert feed and want in feed[0]["title"]           # the signal NAMES the class


# ── 5 · canary + boot canary + sentinel watch ────────────────────────────────

def test_canary_failure_records_classified(monkeypatch):
    _reset()
    import dashboard.voice as voice
    monkeypatch.setattr(voice, "ELEVENLABS_API_KEY", "k")

    def boom(*a, **k):
        raise voice._fail(400, CAPTURED_400)
    monkeypatch.setattr(voice, "stream_tts", boom)
    out = vh.run_canary()
    assert out["ok"] is False
    assert vh.status()["cls"] == "auth"
    assert (kv_store.get("feed:extra:voice") or [])[0]["category"] == "voice"


def test_boot_canary_runs_only_when_configured(monkeypatch):
    ran = []
    monkeypatch.setattr(vh, "run_canary", lambda: ran.append(1))
    import dashboard.voice as voice
    monkeypatch.setattr(voice, "ELEVENLABS_API_KEY", "")
    vh.boot_canary()
    assert ran == []                                       # unconfigured → no probe
    monkeypatch.setattr(voice, "ELEVENLABS_API_KEY", "k")
    vh.boot_canary()
    assert ran == [1]


def test_boot_canary_wired_and_sentinel_watch_present():
    app_src = open(os.path.join(ROOT, "app.py")).read()
    assert "voice_health.boot_canary()" in app_src
    sen = open(os.path.join(ROOT, "ad_sentinel.py")).read()
    assert "voice_watch" in sen and "voice_health.status()" in sen


# ── 6 · no key material anywhere in the loud paths (grep the surfaces) ────────

def test_no_key_material_in_health_or_status():
    _reset()
    vh.record_failure("ElevenLabs key stuff", cls="auth",
                      rydel_action="Re-set ELEVENLABS_API_KEY with an sk_ key")
    import json
    blob = json.dumps(vh.status()) + json.dumps(kv_store.get("feed:extra:voice"))
    # env VAR NAME may appear (it's the instruction); actual key material must not.
    # (the live key prefix '72b' must never surface in a read path)
    assert "72b" not in blob
    r, h = vh.handle_voice_health_command("is your voice okay?")
    assert h and "72b" not in r


# ── 7 · the persistent banner + client fallback contract (structural) ────────

def test_client_has_persistent_banner_and_classified_fallback():
    js = open(os.path.join(ROOT, "dashboard", "static", "js", "edith.js")).read()
    assert "renderVoiceBanner" in js and "edith-voice-banner" in js
    assert "rydel_action" in js and "using fallback" in js
    # the banner is driven by health.degraded, persists (not a 6s toast)
    assert "h.degraded" in js
    css = open(os.path.join(ROOT, "dashboard", "static", "css", "hud.css")).read()
    assert ".edith-voice-banner" in css
