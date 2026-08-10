"""
voice_health.py
---------------
THE VOICE'S HEALTH LAYER (VOICE_MEMORY_SELFIMPROVE_REPORT D1): silent degradation
is impossible. Every ElevenLabs failure is RECORDED (kv voice:health), the client
announces the fallback out loud + badges it, salience carries it (watermarked),
the automation registry shows a canary row, and quota is watched BEFORE exhaustion.

Root cause on record (2026-08-06): the Railway ELEVENLABS_API_KEY is a legacy
64-char key; ElevenLabs now rejects any key not starting with 'sk_' (400
invalid_api_key_prefix). Fixing the key is a RYDEL ACCOUNT ACTION — this module
makes sure such a failure can never again play a robot voice silently.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KV_HEALTH = "voice:health"     # {last_fail:{ts,reason,cls}, last_ok:{ts}, fails_today, day}
_KV_CANARY = "voice:canary"     # {ts, ok, reason, quota:{used,limit,pct}}
_KV_FEED = "feed:extra:voice"   # the action-feed registry channel (owner-facing)

QUOTA_WARN_PCT = 85


# ── FAILURE CLASSIFICATION (2026-08-10 fix — the second bug's core) ──────────
# Root cause of the silent-by-specificity failure: stream_tts logged the
# ElevenLabs body then DISCARDED it, so every surface said "returned 400"
# instead of "your API key is invalid — rotate it". Every failure now carries
# a CLASS + a human message + the OWNER ACTION where one exists. The credits
# class stays even while credits are fresh — the original failure mode must be
# caught loudly next time too.

FAILURE_CLASSES = ("auth", "voice_id", "model", "rate_limit", "credits",
                   "caps", "delivery", "unknown")

_RYDEL_ACTIONS = {
    "auth": ("Re-set ELEVENLABS_API_KEY on the Railway CFOagent service with a "
             "current API key from the ElevenLabs dashboard (Developers → API "
             "Keys — it starts with 'sk_'), then redeploy."),
    "credits": "Top up / upgrade the ElevenLabs plan — character quota exhausted.",
    "voice_id": "The configured voice no longer exists in the ElevenLabs account "
                "— pick the voice again in the voice panel (or restore it in "
                "ElevenLabs).",
}


def classify_failure(status_code: int | None, body: str | None,
                     context: str | None = None) -> dict:
    """(status, response body, context) → {cls, human, rydel_action}. Built
    from ElevenLabs' documented error codes + the live-captured 2026-08-10
    body. NEVER includes key material."""
    b = (body or "").lower()
    ctx = (context or "").lower()
    cls = "unknown"
    if status_code in (401, 403) or "invalid_api_key" in b or "authentication_error" in b \
            or "api key" in b:
        cls = "auth"
    elif "voice_not_found" in b or ("voice" in b and "not found" in b):
        cls = "voice_id"
    elif "model_not_found" in b or ("model" in b and ("not found" in b or "deprecated" in b)):
        cls = "model"
    elif status_code == 429 or "too_many" in b or "rate" in b:
        cls = "rate_limit"
    elif "quota" in b or "character_limit" in b or "credits" in b:
        cls = "credits"
    elif "cap" in ctx or "rate limit (" in ctx:
        cls = "caps"
    elif ctx.startswith("delivery") or "timeout" in ctx or "connection" in ctx:
        cls = "delivery"
    human = {
        "auth": "the API key is invalid or expired (auth failure)",
        "voice_id": "the configured voice ID no longer exists in the account",
        "model": "the configured TTS model is unavailable/deprecated",
        "rate_limit": "ElevenLabs is rate-limiting requests",
        "credits": "ElevenLabs character credits are exhausted",
        "caps": "the app's own TTS cost cap blocked the request",
        "delivery": "the network/delivery path to ElevenLabs failed",
        "unknown": f"ElevenLabs returned {status_code}" if status_code else "unknown TTS failure",
    }[cls]
    return {"cls": cls, "human": human, "rydel_action": _RYDEL_ACTIONS.get(cls)}


def publish_feed_state() -> None:
    """The action-feed item (owner-facing, via the feed:extra registry) —
    REPLACED wholesale per call: degraded → one specific item naming the class
    + the exact owner step; healthy → empty (self-retiring)."""
    try:
        import kv_store
        s = status()
        if s["degraded"]:
            cls = (s.get("cls") or "unknown")
            action = s.get("rydel_action") or "See dashboard/VOICE_DIAGNOSIS.md."
            kv_store.put(_KV_FEED, [{
                "severity": "S1",
                "category": "voice",
                "title": f"EDITH voice DOWN ({cls}): {s.get('reason') or 'TTS failing'}",
                "action": action,
            }])
        else:
            kv_store.put(_KV_FEED, [])
    except Exception as e:
        logger.info("voice feed publish failed: %s", e)


def record_failure(reason: str, cls: str | None = None,
                   rydel_action: str | None = None) -> None:
    """Called by the TTS proxy on every ElevenLabs failure. Cheap, never raises.
    Now CLASSIFIED (2026-08-10): the class + owner action ride the health state
    and the action-feed item — never a bare status code again."""
    try:
        import kv_store
        from helpers import now_sydney, today_sydney
        h = kv_store.get(_KV_HEALTH) or {}
        day = str(today_sydney())
        if h.get("day") != day:
            h["day"], h["fails_today"] = day, 0
        h["fails_today"] = (h.get("fails_today") or 0) + 1
        # human-spoken reason; never echo env-var names (the status payload has a
        # no-key-material contract, and this line gets read ALOUD by the fallback)
        clean = (reason or "unknown").replace("ELEVENLABS_API_KEY", "the ElevenLabs key")
        h["last_fail"] = {"ts": now_sydney().isoformat(timespec="seconds"),
                          "reason": clean[:160], "cls": cls or "unknown",
                          "rydel_action": rydel_action}
        kv_store.put(_KV_HEALTH, h)
        publish_feed_state()
    except Exception as e:
        logger.info("voice_health record_failure failed: %s", e)


def record_ok() -> None:
    try:
        import kv_store
        from helpers import now_sydney
        h = kv_store.get(_KV_HEALTH) or {}
        h["last_ok"] = {"ts": now_sydney().isoformat(timespec="seconds")}
        kv_store.put(_KV_HEALTH, h)
        publish_feed_state()          # healthy → the feed item self-retires
    except Exception:
        pass


def status() -> dict:
    """{degraded, reason, fails_today, last_ok, canary} — what the widget and
    EDITH ('is your voice okay?') read."""
    import kv_store
    h = kv_store.get(_KV_HEALTH) or {}
    c = kv_store.get(_KV_CANARY) or {}
    lf, lo = h.get("last_fail"), h.get("last_ok")
    degraded = bool(lf and (not lo or lf["ts"] > lo["ts"]))
    return {"degraded": degraded,
            "reason": (lf or {}).get("reason"),
            "cls": (lf or {}).get("cls"),
            "rydel_action": (lf or {}).get("rydel_action"),
            "fails_today": h.get("fails_today") or 0,
            "last_ok": (lo or {}).get("ts"), "last_fail": (lf or {}).get("ts"),
            "canary": c or None}


def run_canary() -> dict:
    """Tiny synthesis + quota read, recorded (the automation registry's row).
    Read-only against ElevenLabs; a few characters of quota when healthy."""
    import kv_store
    from helpers import now_sydney
    out = {"ts": now_sydney().isoformat(timespec="seconds"), "ok": False,
           "reason": None, "quota": None}
    try:
        from dashboard.voice import stream_tts, ELEVENLABS_API_KEY
        gen = stream_tts("ok")
        first = next(gen, b"")
        for _ in gen:
            pass
        out["ok"] = bool(first)
        if out["ok"]:
            record_ok()
        # quota (the API exposes usage) — warn BEFORE exhaustion
        try:
            import requests
            r = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                             headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=10)
            if r.status_code == 200:
                d = r.json()
                used, limit = d.get("character_count"), d.get("character_limit")
                if used is not None and limit:
                    out["quota"] = {"used": used, "limit": limit,
                                    "pct": round(used / limit * 100, 1)}
        except Exception:
            pass
    except Exception as e:
        out["reason"] = str(e)[:160]
        record_failure(out["reason"], cls=getattr(e, "cls", "unknown"),
                       rydel_action=getattr(e, "rydel_action", None))
    kv_store.put(_KV_CANARY, out)
    publish_feed_state()
    return out


def boot_canary() -> None:
    """Deploy-time canary (2026-08-10): the daily tick's first run is boot+6h —
    today's failure sat undetected from deploy till 07:29. A boot-time run
    closes that window; failures raise the loud chain immediately."""
    try:
        if not __import__("dashboard.voice", fromlist=["elevenlabs_configured"]).elevenlabs_configured():
            return
        run_canary()
    except Exception as e:
        logger.info("boot canary failed to run: %s", e)


def automation_row() -> dict:
    """The registry row: FAILING when the canary/live path fails, RUNNING when ok,
    UNKNOWN when the canary has never run."""
    s = status()
    c = s.get("canary")
    if s["degraded"]:
        return {"id": "cfo:voice_tts", "name": "EDITH voice (ElevenLabs)",
                "state": "FAILING", "detail": (s.get("reason") or "TTS failing")[:100]}
    if c and c.get("ok"):
        q = c.get("quota") or {}
        det = f"canary ok {c['ts'][:16]}" + (f" · quota {q['pct']}%" if q.get("pct") is not None else "")
        return {"id": "cfo:voice_tts", "name": "EDITH voice (ElevenLabs)",
                "state": "RUNNING", "detail": det}
    return {"id": "cfo:voice_tts", "name": "EDITH voice (ElevenLabs)",
            "state": "UNKNOWN", "detail": "canary has not run yet"}


def salience_events() -> list[dict]:
    """Fallback-active (day-bucketed → re-fires daily while broken) + quota-approaching.
    Watermarked by salience like every other event."""
    from helpers import today_sydney
    s = status()
    day = str(today_sydney())
    events = []
    if s["degraded"]:
        act = s.get("rydel_action")
        events.append({"id": f"voice_fallback:{day}", "type": "voice_fallback",
                       "salience": 82 if s.get("cls") == "auth" else 78, "ago": 0,
                       "spoken": (f"my ElevenLabs voice is failing — {s.get('reason') or 'unknown'} "
                                  f"— I'm on the fallback voice"
                                  + (f". {act}" if act else " until it's fixed"))})
    q = ((s.get("canary") or {}).get("quota")) or {}
    if q.get("pct") is not None and q["pct"] >= QUOTA_WARN_PCT:
        events.append({"id": f"voice_quota:{day}", "type": "voice_quota",
                       "salience": 66, "ago": 0,
                       "spoken": (f"ElevenLabs quota at {q['pct']}% "
                                  f"({q['used']:,}/{q['limit']:,} chars) — top up before it dies mid-sentence")})
    return events


def daily_tick() -> bool:
    """kv-stamped once-a-day canary (called from the shared background loop)."""
    import kv_store
    from helpers import today_sydney
    if kv_store.get("voice:canary_tick") == str(today_sydney()):
        return False
    try:
        run_canary()
        kv_store.put("voice:canary_tick", str(today_sydney()))
        return True
    except Exception as e:
        logger.warning("voice canary tick failed: %s", e)
        return False


# ── EDITH: "is your voice okay?" ─────────────────────────────────────────────

import re as _re

_VOICE_OK_RE = _re.compile(r"(is|how'?s) your voice( okay| ok| doing)?|voice (health|status|okay|ok)\b|"
                           r"are you (on the )?fallback", _re.I)


def handle_voice_health_command(text: str) -> tuple[str | None, bool]:
    if not text or not _VOICE_OK_RE.search(text):
        return None, False
    s = status()
    if s["degraded"]:
        return (f"No — ElevenLabs is failing ({s.get('reason') or 'unknown reason'}; "
                f"{s['fails_today']} failure(s) today), so you're hearing the fallback voice. "
                f"Fixing the key/account is on your side — I flag it until it's back."), True
    c = s.get("canary") or {}
    q = c.get("quota") or {}
    parts = ["Voice is healthy — ElevenLabs responding" +
             (f", canary last passed {str(c.get('ts'))[:16]}" if c.get("ok") else "")]
    if q.get("pct") is not None:
        parts.append(f"quota {q['pct']}% used ({q['used']:,}/{q['limit']:,} chars)")
    return (". ".join(parts) + "."), True
