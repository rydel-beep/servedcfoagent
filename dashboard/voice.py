"""
dashboard/voice.py
------------------
Voice I/O layer: ElevenLabs streaming TTS proxy + the spoken daily brief.

One brain, two mouths: speech-to-text happens in the browser (Web Speech API);
replies come from the EXISTING chat brain (dashboard/chat.py with voice=True);
this module only converts reply text to audio and composes the brief text.

Cost guards: per-minute request cap + daily character cap (env-configurable).
The API key never leaves the server.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict

import requests

from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# LOCKED: Rydel's licensed ElevenLabs voice (the FRIDAY voice). EDITH ships with this.
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "yj30vwTGJxSHezdAGsv9")
# Conversational TTS model — low-latency by default so first-audio is fast (Phase 2).
# Canonical env is TTS_MODEL; ELEVENLABS_MODEL kept as a backward-compatible fallback.
# The locked voice ID and the EDITH effects chain are unchanged — only the synth model.
ELEVENLABS_MODEL = os.environ.get(
    "TTS_MODEL", os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5"))
# Optional higher-fidelity model for the one-off boot greeting, where a touch more
# warmth matters and latency doesn't. Defaults to the fast model (no behaviour change).
ELEVENLABS_GREETING_MODEL = os.environ.get("TTS_GREETING_MODEL", ELEVENLABS_MODEL)

# Runtime voice config — lets the audition tool swap voice/tuning without a
# redeploy. Persisted to the state dir so it survives restarts.
_VOICE_CONFIG_FILE = os.path.join(
    "/data" if os.path.isdir("/data") else "state", "voice_config.json")
_voice_config: dict = {}


def _load_voice_config() -> dict:
    global _voice_config
    try:
        import json as _json
        with open(_VOICE_CONFIG_FILE) as f:
            _voice_config = _json.load(f)
    except (OSError, ValueError):
        _voice_config = {}
    return _voice_config


def save_voice_config(cfg: dict) -> dict:
    """Persist {voice_id, stability, similarity}. Empty/missing keys reset to defaults."""
    global _voice_config
    import json as _json
    clean = {}
    vid = (cfg.get("voice_id") or "").strip()
    if vid:
        clean["voice_id"] = vid[:64]
    for k, lo, hi in (("stability", 0.0, 1.0), ("similarity", 0.0, 1.0), ("speed", 0.7, 1.2)):
        v = cfg.get(k)
        if isinstance(v, (int, float)) and lo <= v <= hi:
            clean[k] = float(v)
    _voice_config = clean
    try:
        os.makedirs(os.path.dirname(_VOICE_CONFIG_FILE), exist_ok=True)
        with open(_VOICE_CONFIG_FILE, "w") as f:
            _json.dump(clean, f)
    except OSError as e:
        logger.warning("voice config not persisted: %s", e)
    return clean


def active_voice_id() -> str:
    return _voice_config.get("voice_id") or ELEVENLABS_VOICE_ID


def active_voice_settings() -> dict:
    # EDITH register: stability 0.70 (even, controlled — reads composed/synthetic
    # before any FX), similarity 0.75, speed 0.92 (measured pace — "a little too
    # fast" feedback 2026-06-12). All overridable via the panel's voice config.
    return {
        "stability": _voice_config.get("stability", 0.70),
        "similarity_boost": _voice_config.get("similarity", 0.75),
        "speed": _voice_config.get("speed", 0.92),
    }


_load_voice_config()

TTS_DAILY_CHAR_CAP = int(os.environ.get("TTS_DAILY_CHAR_CAP", "60000"))
TTS_PER_MINUTE_CAP = int(os.environ.get("TTS_PER_MINUTE_CAP", "12"))
TTS_MAX_CHARS_PER_REQUEST = int(os.environ.get("TTS_MAX_CHARS_PER_REQUEST", "2400"))

# In-memory counters (single-process app; resets on deploy, which is acceptable
# for a cost guard — the cap is a backstop, not an invoice).
_daily_chars: dict[str, int] = defaultdict(int)
_minute_hits: list[float] = []


def elevenlabs_configured() -> bool:
    return bool(ELEVENLABS_API_KEY)


def tts_usage() -> dict:
    day = str(today_sydney())
    return {
        "elevenlabs_configured": elevenlabs_configured(),
        "voice_id": active_voice_id(),
        "default_voice_id": ELEVENLABS_VOICE_ID,
        "voice_settings": active_voice_settings(),
        "model": ELEVENLABS_MODEL,
        "daily_chars_used": _daily_chars[day],
        "daily_char_cap": TTS_DAILY_CHAR_CAP,
        "per_minute_cap": TTS_PER_MINUTE_CAP,
    }


def _check_caps(text_len: int) -> str | None:
    """Return an error string if a cap blocks this request, else None."""
    now = time.time()
    global _minute_hits
    _minute_hits = [t for t in _minute_hits if t > now - 60]
    if len(_minute_hits) >= TTS_PER_MINUTE_CAP:
        return f"TTS rate limit ({TTS_PER_MINUTE_CAP}/min) — try again in a moment"
    day = str(today_sydney())
    if _daily_chars[day] + text_len > TTS_DAILY_CHAR_CAP:
        return f"Daily TTS character cap reached ({TTS_DAILY_CHAR_CAP}) — resets at midnight Sydney"
    return None


def stream_tts(text: str, voice_id_override: str | None = None,
               model_override: str | None = None):
    """Yield MP3 chunks from ElevenLabs for the given text.

    Raises RuntimeError with a human-readable reason on any failure —
    the route turns that into a JSON fallback signal so the client can
    drop to browser speechSynthesis. A TTS failure must never block the answer.

    model_override lets the boot greeting opt into a higher-fidelity model;
    conversational turns use the fast default for lowest first-audio latency.
    """
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty text")
    if len(text) > TTS_MAX_CHARS_PER_REQUEST:
        text = text[:TTS_MAX_CHARS_PER_REQUEST]

    cap_err = _check_caps(len(text))
    if cap_err:
        raise RuntimeError(cap_err)

    vid = (voice_id_override or active_voice_id()).strip()
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream"
        f"?optimize_streaming_latency=3&output_format=mp3_44100_64"
    )
    resp = requests.post(
        url,
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": model_override or ELEVENLABS_MODEL,
            "voice_settings": active_voice_settings(),
        },
        stream=True,
        timeout=(5, 30),
    )
    if resp.status_code != 200:
        body = resp.text[:200]
        logger.error("ElevenLabs TTS %d: %s", resp.status_code, body)
        raise RuntimeError(f"ElevenLabs returned {resp.status_code}")

    _minute_hits.append(time.time())
    _daily_chars[str(today_sydney())] += len(text)
    logger.info("TTS streaming %d chars (daily total %d/%d)",
                len(text), _daily_chars[str(today_sydney())], TTS_DAILY_CHAR_CAP)

    for chunk in resp.iter_content(chunk_size=4096):
        if chunk:
            yield chunk


# ── The spoken daily brief ───────────────────────────────────────────────────

def _fmt_aud_speech(v) -> str:
    """Speech-friendly currency: $91,234 -> "$91,000" (TTS reads it naturally)."""
    if v is None:
        return "unknown"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "unknown"
    if abs(n) >= 10000:
        return f"${round(n / 1000) * 1000:,.0f}"
    return f"${n:,.0f}"


def _brief_facts(snap: dict, history: list[dict]) -> dict:
    """Engine values only — no new math beyond same-field deltas."""
    cp = snap.get("cash_position") or {}
    ch = snap.get("client_health") or {}
    def_a = snap.get("deficiency_analysis") or {}
    verdicts = snap.get("verdicts") or {}

    movers = []
    if history and len(history) >= 2:
        prev, curr = history[-2], history[-1]
        for label, field in (("MRR", "mrr"), ("cash collected over thirty days", "stripe_collected_30d"),
                             ("active clients", "active_clients"), ("failed charges", "failed_charges")):
            a, b = prev.get(field), curr.get(field)
            if a is not None and b is not None and a != b:
                movers.append({"label": label, "from": a, "to": b, "delta": b - a,
                               "rel": abs((b - a) / a) if a else 1.0})
        movers.sort(key=lambda m: m["rel"], reverse=True)
        movers = movers[:3]

    renewal_watch = ch.get("renewal_watch") or []
    at_risk = ch.get("revenue_at_risk_30d")

    return {
        "cash_in_bank": cp.get("cash_in_bank"),
        "in_transit": cp.get("stripe_incoming"),
        "runway_months": cp.get("runway_months"),
        "burn": cp.get("total_monthly_burn"),
        "current_mrr": ch.get("current_mrr"),
        "next_mrr": ch.get("next_mrr"),
        "mrr_delta": ch.get("mrr_delta"),
        "movers": movers,
        "binding_constraint": def_a.get("binding_constraint"),
        "top_leak": (verdicts.get("top_leaks") or [{}])[0],
        "renewal_watch_count": len(renewal_watch),
        "revenue_at_risk_30d": at_risk,
    }


def _template_brief(facts: dict) -> str:
    """Deterministic fallback brief — engine numbers, honest, no model needed."""
    now = now_sydney()
    greeting = "Good morning" if now.hour < 12 else ("Good afternoon" if now.hour < 18 else "Good evening")
    parts = [f"{greeting}, Rydel. Here's where the business stands."]

    cash = _fmt_aud_speech(facts["cash_in_bank"])
    runway = facts["runway_months"]
    burn = _fmt_aud_speech(facts["burn"])
    parts.append(
        f"Cash on hand is {cash}, which is {runway if runway is not None else 'an unknown number of'} "
        f"months of runway at {burn} a month of burn."
    )

    mrr = _fmt_aud_speech(facts["current_mrr"])
    nxt = _fmt_aud_speech(facts["next_mrr"])
    delta = facts["mrr_delta"]
    if delta is not None and delta < -500:
        parts.append(f"MRR is {mrr}, but next month drops to {nxt} on current contracts — the churn cliff is real.")
    elif delta is not None and delta > 500:
        parts.append(f"MRR is {mrr}, rising to {nxt} next month.")
    else:
        parts.append(f"MRR is {mrr}, holding roughly flat into next month.")

    for m in facts["movers"][:2]:
        direction = "up" if m["delta"] > 0 else "down"
        parts.append(f"Since yesterday, {m['label']} moved {direction} to {_fmt_aud_speech(m['to']) if abs(m['to']) > 999 else m['to']}.")

    bc = facts["binding_constraint"] or {}
    if bc.get("name"):
        parts.append(f"Your binding constraint is still {bc['name']}.")
        if bc.get("fix"):
            parts.append(f"Today's focus: {bc['fix']}.")

    if facts["revenue_at_risk_30d"]:
        parts.append(f"Renewal watch: {_fmt_aud_speech(facts['revenue_at_risk_30d'])} of MRR is at risk in the next thirty days.")

    parts.append("That's the read. Ask me anything.")
    return " ".join(parts)


def build_brief(snap: dict, history: list[dict], token: str) -> dict:
    """Compose the 45–75 second spoken brief. Model-written in the voice
    register when the chat brain is available; deterministic template otherwise.
    Engine values only — no new math."""
    import json
    facts = _brief_facts(snap, history or [])

    from dashboard.chat import chat as run_chat
    prompt = (
        "Give me my spoken daily brief. Use ONLY these engine facts (do not invent "
        "or recompute anything):\n" + json.dumps(facts, default=str) + "\n\n"
        "Structure: greeting with today's vibe in one clause; cash on hand and runway; "
        "MRR and trajectory; the top movers since yesterday; the binding constraint in "
        "one sentence; today's single recommended focus; renewal watch if revenue is at "
        "risk. 45 to 75 seconds when spoken — roughly 110 to 180 words. Honest: if the "
        "forward picture is red, say so plainly."
    )
    result = run_chat([{"role": "user", "content": prompt}], json.dumps(snap), token, voice=True)
    if result.get("reply"):
        return {"text": result["reply"], "source": "model"}

    logger.warning("Brief falling back to template: %s", result.get("error"))
    return {"text": _template_brief(facts), "source": "template"}


# ── Live weather (Open-Meteo, free, no key) — Newcastle AU ───────────────────

_NEWCASTLE = {"lat": -32.9283, "lon": 151.7817}
_weather_cache: dict = {"ts": 0.0, "data": None}
WEATHER_CACHE_SECONDS = 15 * 60

# WMO weather codes → spoken description
_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "drizzling", 53: "drizzling", 55: "drizzling",
    61: "raining lightly", 63: "raining", 65: "raining heavily",
    66: "raining", 67: "raining", 71: "snowing", 73: "snowing", 75: "snowing",
    80: "showery", 81: "showery", 82: "showery",
    95: "stormy", 96: "stormy", 99: "stormy",
}


def get_newcastle_weather() -> dict | None:
    """Current temp + condition + today's high. 15-min cache. None on any failure
    — the greeting simply skips weather; never blocks."""
    now = time.time()
    if _weather_cache["data"] is not None and now - _weather_cache["ts"] < WEATHER_CACHE_SECONDS:
        return _weather_cache["data"]
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": _NEWCASTLE["lat"], "longitude": _NEWCASTLE["lon"],
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max",
                "timezone": "Australia/Sydney", "forecast_days": 1,
            },
            timeout=(4, 8),
        )
        if resp.status_code != 200:
            return None
        d = resp.json()
        cur = d.get("current") or {}
        daily = d.get("daily") or {}
        data = {
            "temp_c": cur.get("temperature_2m"),
            "condition": _WMO.get(cur.get("weather_code"), "fine"),
            "high_c": (daily.get("temperature_2m_max") or [None])[0],
        }
        if data["temp_c"] is None:
            return None
        _weather_cache.update(ts=now, data=data)
        return data
    except requests.RequestException as e:
        logger.warning("weather fetch failed (greeting will skip it): %s", e)
        return None


def build_greeting(snap: dict) -> dict:
    """The wake-sequence greeting: time-of-day + live weather + ONE business
    headline from the engines + the open. Deterministic — no model, no wait."""
    now = now_sydney()
    tod = "morning" if now.hour < 12 else ("afternoon" if now.hour < 18 else "evening")
    parts = [f"Good {tod}, Rydel. I hope you're doing well."]

    weather = get_newcastle_weather()
    if weather:
        t = round(weather["temp_c"])
        line = f"It's {t} and {weather['condition']} in Newcastle"
        if weather.get("high_c") is not None and round(weather["high_c"]) != t:
            line += f", heading for {round(weather['high_c'])}"
        parts.append(line + ".")

    # Instagram-story safe: sales MOTION (appointments, closes, close rate,
    # cash collected over 30d), never balance-sheet exposure (cash position,
    # runway, burn stay out of the greeting — ask EDITH directly for those).
    funnel = ((snap or {}).get("sales") or {}).get("funnel") or {}
    sets_n, closes_n = funnel.get("sets"), funnel.get("closes")
    close_rate = funnel.get("show_to_close_pct")
    collected = ((((snap or {}).get("stripe") or {}).get("revenue") or {})
                 .get("current") or {}).get("total_aud")

    sales_bits = []
    if sets_n is not None:
        sales_bits.append(f"{sets_n} appointments booked")
    if closes_n is not None:
        sales_bits.append(f"{closes_n} deals closed")
    if sales_bits:
        line = "You're at " + " and ".join(sales_bits)
        if close_rate is not None:
            line += f", closing at {round(close_rate)} percent"
        parts.append(line + ".")
    if collected is not None:
        parts.append(f"Cash collected in the last thirty days: {_fmt_aud_speech(collected)}.")

    parts.append("What do you need?")
    return {"text": " ".join(parts), "weather": weather}
