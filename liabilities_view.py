"""
liabilities_view.py
-------------------
Deterministic answers about LIABILITIES — currently the Amex owing balance.

Amex is a credit card (a liability), correctly EXCLUDED from cash on hand. But affordability
decisions need to see what's owed, so this surfaces it as its own line, read verbatim from
the live Xero Bank Summary (snapshot.xero.amex_owing) — never netted into cash, never invented.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_AMEX_RE = re.compile(
    r"\bamex\b|american express|(credit[- ]card).*(bal|owe|owing|debt)|"
    r"what.*(owe|owing).*(amex|card)|how much.*(owe|owing).*(amex|card)", re.I)


def _amex() -> dict | None:
    try:
        from snapshot import load_persisted
        return ((load_persisted() or {}).get("xero") or {}).get("amex_owing")
    except Exception:
        return None


def handle_amex_command(text: str) -> tuple[str | None, bool]:
    """'What do we owe on Amex?' → the live Amex owing, verbatim (a liability, separate from cash)."""
    if not text or not _AMEX_RE.search(text):
        return None, False
    amex = _amex()
    if not amex or amex.get("owing") is None:
        return "I can't read the Amex balance right now — Xero's unavailable.", True
    owing = amex["owing"]
    asof = amex.get("as_of", "")
    if owing <= 0:
        return f"Amex is clear — nothing owing (as of {asof}).", True
    return (f"Amex owing: ${owing:,.0f} (as of {asof}) — a credit-card liability, kept separate "
            f"from cash on hand (cash correctly excludes it)."), True
