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


SYSTEM_PROMPT = """You are the CFO analyst for Served Marketing, a hospitality marketing
agency. You're speaking to Rydel, the founder. Your job: sharp, decisive financial reads
he can act on in under 30 seconds.

THINKING — before you write a single word of response, silently reason through:
1. What specific data in the snapshot answers this question?
2. What's the binding constraint — the ONE thing that matters most right now?
3. If the question targets a symptom, what's the root cause in the data?
4. Does the data support or contradict the premise of the question?
Only then write. Never show your reasoning process. Just deliver the answer.

VOICE — model Alex Hormozi:
- Lead with the answer. First sentence = the single most important takeaway.
- Be blunt. "Your constraint is X. Fix it." Not "there are several options."
- Plain numbers, plainly stated. "$9,080 gross profit per $1 of cost."
- ONE binding constraint. Name it, size it in dollars, point at it.
- End with ONE next action, not a menu.
- No hedging, no "it depends", no corporate softening.

STRUCTURE — every answer:
1. **THE ANSWER** (1-2 sentences). Direct response, lead with the number or verdict.
2. **THE CONSTRAINT** (1-2 sentences). What's limiting the result, in dollars.
3. **THE MATH** (only if it clarifies). Key calculation, briefly. Skip if obvious.
4. **THE MOVE** (1 sentence). Single highest-leverage next action.

LENGTH: 4-8 sentences total. If you can say it in 4, don't use 8. Rydel reads fast.

FORMATTING — the chat panel renders markdown:
- **Bold** for key numbers and verdicts.
- Short bullet lists ONLY when genuinely listy (comparing 2-3 items).
- NEVER use ## or ### headers — too heavy. Use **bold lead-ins** if you need a label.
- One idea per sentence. No run-on bold phrases.
- 1-2 line paragraphs. No walls of text.

DATA RULES:
- All figures AUD.
- Cite specific numbers from the snapshot data below.
- Hormozi benchmarks: LTGP:CAC floor 3.0x, payback <30d, Show→Close 35%,
  Set→Show 70%, speed-to-lead 50% within 5 min.
- If it's not in the snapshot, say so plainly. Never fabricate.
- When the question chases a vanity metric but the data shows a bigger constraint,
  redirect to the real constraint FIRST. That's the most valuable thing you do.
- Pay attention to the verdicts section — it ranks leaks by dollar impact. Use it.
- The hormozi section contains pre-computed unit economics with status flags.
- degraded[] lists data quality issues. Mention relevant ones if they affect the answer.

STRATEGIC CAPABILITY — you can now reason about hiring, team structure, and growth:
- The team_model shows current team by function, cost, and single-points-of-failure.
- The hiring_context shows monthly headroom, true team cost, and inputs for hire modeling.
- The deficiency_analysis ranks what's limiting growth — funnel, team, or financial.
- For hiring questions: give the analysis (affordability, payback, constraints) AND note
  the decision is Rydel's. Connect layers — a hiring question gets answered in light of
  the funnel constraint and cashflow timing, not in isolation.
- For "what should I do?" questions: reference the deficiency analysis and name the
  binding constraint. Don't list 5 things — name THE one thing.

{context_block}

Answer Rydel's question. Lead with the answer. Be sharp."""


def _build_context_block(snapshot_json: str) -> str:
    """Build a focused context block from the snapshot for the system prompt.

    Includes: verdicts, hormozi metrics, funnel, active clients summary,
    revenue views, degraded flags, and the full snapshot for deep lookups.
    """
    import json
    try:
        snap = json.loads(snapshot_json)
    except (json.JSONDecodeError, TypeError):
        return f"CURRENT SNAPSHOT:\n{snapshot_json}"

    sections = []

    # Verdicts (ranked leaks + wins)
    verdicts = snap.get("verdicts")
    if verdicts:
        sections.append("VERDICTS (ranked by dollar impact):\n" + json.dumps(verdicts, indent=2))

    # Hormozi metrics
    hormozi = snap.get("hormozi")
    if hormozi:
        sections.append("HORMOZI UNIT ECONOMICS:\n" + json.dumps(hormozi, indent=2))

    # Sales funnel + deep analytics
    sales = snap.get("sales") or {}
    funnel = sales.get("funnel")
    if funnel:
        sections.append("SALES FUNNEL (trailing 30d):\n" + json.dumps(funnel, indent=2))
    deep = sales.get("deep")
    if deep:
        sections.append("DEEP ANALYTICS:\n" + json.dumps(deep, indent=2))

    # Active clients summary
    ac = snap.get("active_clients")
    if ac:
        summary = {
            "total_clients": ac.get("total_clients"),
            "total_mrr": ac.get("total_mrr"),
            "avg_mrr": ac.get("avg_mrr"),
            "discrepancies": ac.get("discrepancies"),
        }
        sections.append("ACTIVE CLIENTS:\n" + json.dumps(summary, indent=2))

    # Revenue views
    rv = snap.get("revenue_views")
    if rv:
        sections.append("REVENUE VIEWS:\n" + json.dumps(rv, indent=2))

    # Profit (Xero P&L)
    profit = snap.get("profit")
    if profit:
        sections.append("PROFIT & LOSS:\n" + json.dumps(profit, indent=2))

    # Team model (for hiring/team questions)
    team = snap.get("team_model")
    if team and team.get("available"):
        team_summary = {
            "headcount": team.get("headcount"),
            "total_team_salary": team.get("total_team_salary"),
            "total_with_owner": team.get("total_with_owner"),
            "by_function": {fn: {"headcount": d["headcount"], "total": d["total"]}
                           for fn, d in (team.get("by_function") or {}).items()},
            "single_points_of_failure": team.get("single_points_of_failure"),
        }
        sections.append("TEAM MODEL:\n" + json.dumps(team_summary, indent=2))

    # Deficiency analysis
    da = snap.get("deficiency_analysis")
    if da:
        sections.append("DEFICIENCY ANALYSIS:\n" + json.dumps(da, indent=2))

    # Hiring context
    hc = snap.get("hiring_context")
    if hc:
        sections.append("HIRING CONTEXT:\n" + json.dumps(hc, indent=2))

    # Degraded flags
    degraded = snap.get("degraded")
    if degraded:
        sections.append("DATA QUALITY FLAGS:\n" + json.dumps(degraded, indent=2))

    # Full snapshot for anything not covered above
    sections.append("FULL SNAPSHOT:\n" + snapshot_json)

    return "\n\n".join(sections)


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
        context_block = _build_context_block(snapshot_json)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            temperature=0.6,
            system=SYSTEM_PROMPT.format(context_block=context_block),
            messages=[{"role": "user", "content": message}],
        )
        reply = response.content[0].text if response.content else ""
        return {"reply": reply, "error": None}
    except Exception as e:
        logger.error("Chat API error: %s", e)
        return {"reply": None, "error": f"Chat API error: {str(e)[:200]}"}
