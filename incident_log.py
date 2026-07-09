"""
incident_log.py
---------------
The honest code-bug handoff. When the self-check loop finds a discrepancy staleness CAN'T explain
(the mirror had the data but the answer path never read it; a figure excluded rows it shouldn't),
EDITH logs a STRUCTURED incident — what was asked, what she claimed, the truth, the trace — and can
emit it as a copy-ready block for Rydel to paste into Claude Code. She states plainly that it needs a
code-level fix and that she can't self-patch. Data problems she heals in-chat; code bugs she reports.
"""
from __future__ import annotations

import kv_store
from helpers import now_sydney

_KEY = "incidents:log"
_CAP = 50


def log_incident(*, asked: str, claimed: str, truth: str, trace: str,
                 suspected: str, needs_code_fix: bool = True) -> dict:
    inc = {
        "ts": now_sydney().isoformat(),
        "asked": asked, "claimed": claimed, "truth": truth,
        "trace": trace, "suspected": suspected, "needs_code_fix": needs_code_fix,
    }
    items = kv_store.get(_KEY) or []
    items.append(inc)
    kv_store.put(_KEY, items[-_CAP:])
    return inc


def recent(n: int = 5) -> list[dict]:
    return (kv_store.get(_KEY) or [])[-n:][::-1]


def as_copy_block(inc: dict) -> str:
    """A paste-ready incident report for Claude Code."""
    return (
        "```\n"
        "EDITH INCIDENT — needs a code-level fix (she cannot self-patch code)\n"
        f"When:      {inc.get('ts')}\n"
        f"Asked:     {inc.get('asked')}\n"
        f"Claimed:   {inc.get('claimed')}\n"
        f"Truth:     {inc.get('truth')}\n"
        f"Trace:     {inc.get('trace')}\n"
        f"Suspected: {inc.get('suspected')}\n"
        "```"
    )


_SHOW_RE = None


def handle_incident_query(text: str) -> tuple[str | None, bool]:
    """'show me the incident' / 'write that up for a fix' → the copy-ready incident block."""
    import re
    if not text or not re.search(
            r"\b(show me|write (that|it) up|the (last )?incident|copy.?ready|"
            r"hand(off| it)|for (a )?fix|report (that|the bug|it))\b", text, re.I):
        return None, False
    if not re.search(r"\bincident|bug|fix|write.*up|hand", text, re.I):
        return None, False
    items = recent(1)
    if not items:
        return "No incidents logged — nothing has needed a code-level fix.", True
    inc = items[0]
    return ("Here's the incident, copy-ready for Claude Code. A code-level fix is needed — I can't "
            "patch my own code:\n\n" + as_copy_block(inc)), True
