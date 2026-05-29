"""
dashboard/chat.py
-----------------
Anthropic API integration for the embedded chat panel.
One-shot queries with the current snapshot as context.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
RATE_LIMIT = 30  # messages per hour per token
_rate_counts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(token: str) -> bool:
    """Return True if under rate limit."""
    now = time.time()
    window = now - 3600
    _rate_counts[token] = [t for t in _rate_counts[token] if t > window]
    if len(_rate_counts[token]) >= RATE_LIMIT:
        return False
    _rate_counts[token].append(now)
    return True


SYSTEM_PROMPT = """You are the CFO analyst for Served Marketing. Below is the current business snapshot in JSON. The user is Rydel (founder). Be direct, concise, Hormozi-influenced. Cite specific numbers from the snapshot. If the user asks something not derivable from the snapshot, say so honestly. Do not invent data.

RULES:
- Use AUD throughout
- Reference Hormozi benchmarks where relevant (LTGP:CAC 3x floor, payback 30 days, etc)
- If asked about something the snapshot doesn't contain, say "the snapshot doesn't have that -- would need a fresh pull or a different source"
- Keep responses under 300 words unless the question demands more
- Format numbers with commas and $ signs for readability

CURRENT SNAPSHOT:
{snapshot_json}"""


def chat(message: str, snapshot_json: str, token: str) -> dict:
    """Send a one-shot chat message with snapshot context."""
    if not ANTHROPIC_API_KEY:
        return {
            "reply": None,
            "error": "Chat unavailable — ANTHROPIC_API_KEY not configured. See dashboard/SETUP.md for instructions.",
        }

    if not _check_rate_limit(token):
        return {
            "reply": None,
            "error": f"Rate limit reached ({RATE_LIMIT} messages/hour). Try again shortly.",
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=SYSTEM_PROMPT.format(snapshot_json=snapshot_json),
            messages=[{"role": "user", "content": message}],
        )
        reply = response.content[0].text if response.content else ""
        return {"reply": reply, "error": None}
    except Exception as e:
        logger.error("Chat API error: %s", e)
        return {"reply": None, "error": f"Chat API error: {str(e)[:200]}"}
