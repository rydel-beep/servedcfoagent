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
# Rydel's established FRIDAY voice — dashboard Jarvis must sound identical to Mac FRIDAY.
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "yj30vwTGJxSHezdAGsv9")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")  # low latency

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
        "voice_id": ELEVENLABS_VOICE_ID,
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


def stream_tts(text: str):
    """Yield MP3 chunks from ElevenLabs for the given text.

    Raises RuntimeError with a human-readable reason on any failure —
    the route turns that into a JSON fallback signal so the client can
    drop to browser speechSynthesis. A TTS failure must never block the answer.
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

    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
        f"?optimize_streaming_latency=3&output_format=mp3_44100_64"
    )
    resp = requests.post(
        url,
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
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
