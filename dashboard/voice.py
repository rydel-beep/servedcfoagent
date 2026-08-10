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

# ── Expressive delivery defaults (the personality multiplier) ────────────────
# Lower stability = more emotional range (tone rises/falls with content); too low = wobble
# and "drag" (warped/over-emoted prosody). 0.40 overshot — some replies dragged. 0.50 is the
# stable-but-alive band: still carries tone, consistent turn-to-turn. ONE fixed profile for all
# conversational replies — personality comes from WORD CHOICE (the prompt), not from yanking
# voice params per message (that churn is what makes consecutive replies feel inconsistent).
# `style` adds dynamic delivery on models that support it; similarity holds identity. All
# overridable live via the voice panel (save_voice_config) and by env.
TTS_STABILITY = float(os.environ.get("TTS_STABILITY", "0.50"))
TTS_SIMILARITY = float(os.environ.get("TTS_SIMILARITY", "0.75"))
TTS_STYLE = float(os.environ.get("TTS_STYLE", "0.30"))
TTS_SPEED = float(os.environ.get("TTS_SPEED", "0.95"))
TTS_SPEAKER_BOOST = os.environ.get("TTS_SPEAKER_BOOST", "1") == "1"

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
    """Persist {voice_id, stability, similarity, style, speed}. Empty/missing keys
    reset to the (expressive) defaults. `style` is the new expressiveness dial."""
    global _voice_config
    import json as _json
    clean = {}
    vid = (cfg.get("voice_id") or "").strip()
    if vid:
        clean["voice_id"] = vid[:64]
    for k, lo, hi in (("stability", 0.0, 1.0), ("similarity", 0.0, 1.0),
                      ("style", 0.0, 1.0), ("speed", 0.7, 1.2)):
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
    # EDITH expressive register: stability 0.50 (stable-but-alive — carries tone yet stays
    # consistent turn-to-turn; 0.40 dragged/wobbled), similarity 0.75 (identity holds),
    # style 0.30 (dynamic but not over-emoted), speed 0.95. ONE fixed profile for all
    # conversational replies — no per-utterance churn. Panel overrides win; env sets defaults.
    # The EDITH effects chain rides on top of this livelier-but-stable raw voice.
    return {
        "stability": _voice_config.get("stability", TTS_STABILITY),
        "similarity_boost": _voice_config.get("similarity", TTS_SIMILARITY),
        "style": _voice_config.get("style", TTS_STYLE),
        "use_speaker_boost": TTS_SPEAKER_BOOST,
        "speed": _voice_config.get("speed", TTS_SPEED),
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


class TTSFailure(RuntimeError):
    """A CLASSIFIED TTS failure (voice fix 2026-08-10). Root cause of the
    silent-by-specificity bug: the ElevenLabs error body was logged then
    DISCARDED, so every surface said 'returned 400' instead of naming the
    failure class + the owner action. Never carries key material."""

    def __init__(self, human: str, cls: str = "unknown",
                 rydel_action: str | None = None):
        super().__init__(human)
        self.cls = cls
        self.rydel_action = rydel_action


def _fail(status_code=None, body=None, context=None) -> TTSFailure:
    import voice_health
    c = voice_health.classify_failure(status_code, body, context)
    return TTSFailure(c["human"], c["cls"], c["rydel_action"])


def stream_tts(text: str, voice_id_override: str | None = None,
               model_override: str | None = None):
    """Yield MP3 chunks from ElevenLabs for the given text.

    Raises TTSFailure (a RuntimeError) with a CLASSIFIED human-readable reason
    on any failure — the route turns that into a JSON fallback signal so the
    client can drop to browser speechSynthesis, and voice_health records the
    class + owner action. A TTS failure must never block the answer.

    model_override lets the boot greeting opt into a higher-fidelity model;
    conversational turns use the fast default for lowest first-audio latency.
    """
    if not ELEVENLABS_API_KEY:
        # a missing key is the SAME owner-action class as a bad one (auth) —
        # classify it so the fallback names the exact env var to set
        raise _fail(401, "invalid_api_key: ELEVENLABS_API_KEY not configured")
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty text")
    if len(text) > TTS_MAX_CHARS_PER_REQUEST:
        text = text[:TTS_MAX_CHARS_PER_REQUEST]

    cap_err = _check_caps(len(text))
    if cap_err:
        raise _fail(context=f"cap: {cap_err}")

    vid = (voice_id_override or active_voice_id()).strip()
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream"
        f"?optimize_streaming_latency=3&output_format=mp3_44100_64"
    )
    try:
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
    except requests.RequestException as e:
        raise _fail(context=f"delivery: {type(e).__name__}")
    if resp.status_code != 200:
        body = resp.text[:300]
        logger.error("ElevenLabs TTS %d: %s", resp.status_code, body)
        raise _fail(resp.status_code, body)

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


def _time_of_day(hour: int) -> str:
    return "morning" if hour < 12 else ("afternoon" if hour < 18 else "evening")


def _compose_greeting(tod: str, loc: dict, weather: dict | None,
                      events: list[dict], avoid: list[str]) -> str | None:
    """Model-composed greeting from DETERMINISTIC facts. Figures/names verbatim; 1-3 sentences;
    fresh structure each time. Returns None on any failure (caller uses the safe fallback)."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    facts = [f"Time of day: {tod} (use as the opener register, optional)."]
    if loc:
        facts.append(f"Rydel is in: {loc.get('place')} (how known: {loc.get('source')}).")
    if weather and weather.get("temp_c") is not None:
        hi = f", high {round(weather['high_c'])}" if weather.get("high_c") is not None else ""
        facts.append(f"Weather there: {round(weather['temp_c'])} degrees, {weather['condition']}{hi} "
                     f"(mention ONLY if notable/useful, not every time).")
    if events:
        facts.append("NEW since you last greeted him — surface the top 1-2, numbers/names VERBATIM:")
        for e in events:
            facts.append(f"  - {e['spoken']}")
    else:
        facts.append("NOTHING new since last time. Give a light human hello with NO stats/numbers.")
    avoid_line = (" Do NOT open like these recent greetings: " + " | ".join(avoid[:5])) if avoid else ""
    try:
        from dashboard.chat import BASE_PERSONA
    except Exception:
        BASE_PERSONA = "You are EDITH, Rydel's sharp chief of staff."
    from config import CHAT_MODEL
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        for attempt in range(3):
            try:
                r = client.messages.create(
                    model=CHAT_MODEL, max_tokens=160,
                    system=BASE_PERSONA + "\n\nYou are composing EDITH's SPOKEN boot greeting.",
                    messages=[{"role": "user", "content":
                        "Compose a fresh 1-3 sentence spoken greeting from the facts below. Hard rules: "
                        "every number and name VERBATIM from the facts (invent NOTHING, no rounding drift); "
                        "vary the structure and opener each time (you may lead with the news, the hello, "
                        "or a question); no fixed skeleton; end naturally (not always 'What do you need?')."
                        + avoid_line + "\n\nFACTS:\n" + "\n".join(facts)}])
                txt = "".join(getattr(b, "text", "") for b in r.content).strip()
                return txt or None
            except Exception as e:  # noqa: BLE001
                if "529" in str(e) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
    except Exception as e:  # noqa: BLE001
        logger.info("greeting composer failed — using deterministic fallback: %s", e)
        return None


def _remember_shape(text: str) -> None:
    """Keep the last few greeting openers so the composer can avoid repeating them."""
    try:
        import kv_store
        shapes = kv_store.get("greeting:recent_shapes") or []
        opener = " ".join(text.split()[:8])
        shapes = ([opener] + [s for s in shapes if s != opener])[:6]
        kv_store.put("greeting:recent_shapes", shapes)
    except Exception:
        pass


def build_greeting(snap: dict, mark: bool = True) -> dict:
    """EDITH's boot greeting: resolved location + salient NEW events, composed fresh each time.
    Figures come verbatim from the deterministic salience feed / one engine; the model varies only
    the framing. Falls back to a safe deterministic hello if the composer is unavailable."""
    import location
    import salience
    import kv_store

    loc = location.resolve()
    weather = location.weather_and_localtime(loc)
    hour = (weather or {}).get("local_hour")
    if hour is None:
        hour = now_sydney().hour
    tod = _time_of_day(hour)

    events = salience.top(snap, 3)
    avoid = kv_store.get("greeting:recent_shapes") or []

    text = _compose_greeting(tod, loc, weather, events, avoid)
    if not text:
        # Safe deterministic fallback — hello + top event verbatim, never invented, never a crash.
        bits = [f"Good {tod}, Rydel."]
        bits.append(salience.summary_line(events) if events else "Quiet since we last spoke — nothing new.")
        text = " ".join(bits)

    if mark:
        salience.mark_told(events)
        salience.note_greeted(snap)
        _remember_shape(text)

    return {"text": text, "weather": weather, "location": loc,
            "events": [e["spoken"] for e in events]}
