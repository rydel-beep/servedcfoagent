"""llm_compat.py — keep EDITH talking across Anthropic SDK generations.

WHY THIS EXISTS (found 2026-09-22, in production, by the dock gate):

`requirements.txt` asks for `anthropic>=0.52.0`. A Railway rebuild resolved
that to **1.7.0**, whose `messages.create()` and `messages.stream()` no longer
accept `temperature`. Every business question EDITH was asked came back as:

    Chat API error: Messages.stream() got an unexpected keyword argument 'temperature'

— a silent brain outage that only showed up because a gate asked her for a
number instead of a definition (a glossary answer never reaches the model).

So: ask the installed SDK what it accepts, once, and pass `temperature` only
where it is still a parameter. An SDK that has dropped it runs at its own
default rather than refusing to answer at all — an answer with a different
temperature beats no answer.
"""
from __future__ import annotations

import inspect
import logging

logger = logging.getLogger(__name__)

_SUPPORTED: dict[str, bool] = {}


def _supports(method) -> bool:
    key = getattr(method, "__qualname__", str(method))
    if key not in _SUPPORTED:
        try:
            ok = "temperature" in inspect.signature(method).parameters
        except (TypeError, ValueError):  # pragma: no cover - exotic callables
            ok = False
        _SUPPORTED[key] = ok
        if not ok:
            logger.info("anthropic SDK does not accept temperature on %s — "
                        "calling without it", key)
    return _SUPPORTED[key]


def temp(method, value: float) -> dict:
    """`**temp(client.messages.create, 0.5)` — the kwarg, or nothing."""
    return {"temperature": value} if _supports(method) else {}
