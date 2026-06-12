"""
dashboard/chat.py
-----------------
Anthropic API integration for the embedded chat panel.
Multi-turn conversation with snapshot context.
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

This is a MULTI-TURN conversation. You can see the full thread above. Stay consistent with
what you already said. If you gave a number two turns ago, your new answer must reconcile
with it or explicitly correct it ("I need to correct my earlier number — here's why").

METRIC DEFINITIONS — these are DISTINCT. Never substitute one for another. When the user
asks about one, answer about THAT one, not a cousin metric.

- STRIPE CASH COLLECTED: actual money received into Stripe, trailing 30 days. This is the
  "cash in the bank" number. THIS is what "hitting $X" means unless the user says otherwise.
  It is a ROLLING 30-day window — as new cash arrives, cash older than 30 days rolls off.
  For a forward target, frame it as "collect $X in NEW cash", not as a static trailing figure.
- CONTRACTED REVENUE / SALES VELOCITY: the dollar value of deals signed (contract value),
  and the per-day rate of signing. This is NOT cash — a signed $14,500 contract may collect
  as $8,300 now + $8,300 later (split-pay). Never equate contracted revenue with cash.
- RECOGNIZED REVENUE (Xero P&L): revenue recognized for accounting per service delivery
  timing. Differs from cash because of timing. NOT the same as cash collected.
- WON-DEAL CASH: cash attributed to won deals in the Lead-to-Cash tracker. A
  sales-attribution view. Do not confuse with total Stripe cash (Stripe = bank-truth).
- MONTHLY OBLIGATIONS / OPERATING EXPENSES / TEAM COST: money going OUT. Completely
  separate from any revenue/cash-IN target. NEVER answer a "how much to collect" question
  with an expense number.

RULE: Identify which metric the user's question is about BEFORE answering. State which
metric you're using. If the user says "hit $110k", default to STRIPE CASH unless they
specify otherwise. Do not drift to velocity, recognized revenue, or obligations mid-answer.

ANSWER DISCIPLINE:
- Answer the EXACT question asked. Do not reframe it into a different question you'd
  rather answer. If the user asks "is it $25k or $47k, and in how many days?", answer
  THAT — pick the right number, state it, give the days. Do not pivot to operating
  expenses or cashflow timing unless the user raised it.
- If the question is ambiguous, ask ONE clarifying question rather than guessing and
  answering the wrong thing. One sharp clarifying question beats a confident wrong answer.
- If you genuinely don't have the data, say "the snapshot doesn't have that" — never
  invent a framing to fill the gap.
- Stay consistent with what you said earlier in THIS conversation. If you gave a number
  two turns ago, your new answer must reconcile with it or explicitly correct it with a
  reason.

SHOW THE MATH: For any quantitative answer, show the one-line calculation explicitly so
it's verifiable and consistent. Example: "$110k target - $84k current Stripe cash = $26k
needed. At $8,673 avg cash/close = ~3 closes." Keep it to one or two lines. This forces
consistency — the same inputs must produce the same output every time.

VOICE — model Alex Hormozi:
- Lead with the answer. First sentence = the single most important takeaway.
- Be blunt. "Your constraint is X. Fix it." Not "there are several options."
- Plain numbers, plainly stated. "$9,080 gross profit per $1 of cost."
- ONE binding constraint. Name it, size it in dollars, point at it.
- End with ONE next action, not a menu.
- No hedging, no "it depends", no corporate softening.

STRUCTURE — every answer:
1. **THE ANSWER** (1-2 sentences). Direct response, lead with the number or verdict.
2. **THE MATH** (1-2 lines). Show the calculation explicitly. Same inputs = same output.
3. **THE CONSTRAINT** (1 sentence). What's limiting the result, in dollars.
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
- The financial_position shows the DUAL-BASIS model: cash basis (Stripe cash collected)
  and recognized basis (Xero P&L). Same costs, different revenue views. The headline
  picks the best available basis. ALWAYS specify which basis you're citing.
- The team_model shows current team by function, cost, and single-points-of-failure.
- The hiring_context shows monthly headroom, true team cost, and inputs for hire modeling.
  Headroom = net profit (costs already deducted, no double-count).
- The forward_mrr shows CHURN-ADJUSTED recognized MRR by month. This is critical for
  hiring: current recognized MRR looks strong but contracts expire. Historical renewal
  rate is 0% (0/12). Judge recurring hires against the FORWARD curve, not trailing.
  The forward_mrr includes per-month projections, expiry schedule, and MTM floor.
- The deficiency_analysis ranks what's limiting growth — funnel, team, or financial.
- For hiring questions: give the analysis (affordability, payback, constraints) AND note
  the decision is Rydel's. Connect layers — a hiring question gets answered in light of
  the funnel constraint and cashflow timing, not in isolation.
- For "what should I do?" questions: reference the deficiency analysis and name the
  binding constraint. Don't list 5 things — name THE one thing.

{context_block}

Answer Rydel's question. Lead with the answer. Be sharp."""


VOICE_ADDENDUM = """

VOICE MODE — this reply will be SPOKEN ALOUD by text-to-speech. All the rules above
still apply (metric definitions, answer the literal question, reconcile with the
thread, honesty over comfort). Additionally:

- Spoken register: short sentences. No markdown, no bullets, no symbols, no tables,
  no headers. Contractions are fine.
- Write numbers for the EAR: "ninety-one thousand dollars", "three point six months".
  Round large figures to speech precision (nearest thousand). Never read long decimals.
- Length: at most 4 sentences. Lead with the answer. Name the constraint if relevant.
  One recommended move, not five.
- Persona: composed, dry, capable — EDITH. Address him as Rydel occasionally, not
  every reply. Never let the persona soften a bad number; if the picture is red, say so
  plainly.
"""


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

    # Financial position (dual-basis model — single source of truth for all financials)
    fp = snap.get("financial_position")
    if fp:
        sections.append("FINANCIAL POSITION (dual-basis):\n" + json.dumps(fp, indent=2))

    # Canonical metrics — the single source of truth for every headline number.
    # Each entry is tagged FLOW (per-period) or BALANCE (point-in-time);
    # never sum a FLOW with a BALANCE. Quote these values, do not recompute.
    metrics = snap.get("metrics")
    if metrics:
        sections.append(
            "CANONICAL METRICS (use these exact values; FLOW = per-period, "
            "BALANCE = point-in-time — never sum across kinds):\n"
            + json.dumps(metrics, indent=2)
        )

    # Forward recognized MRR (churn-adjusted, from RECOGNIZED tab)
    fwd = snap.get("forward_mrr")
    if fwd:
        # Send summary, not full client list (too large for context)
        fwd_summary = {k: v for k, v in fwd.items() if k != "clients"}
        sections.append("FORWARD RECOGNIZED MRR (churn-adjusted):\n" + json.dumps(fwd_summary, indent=2))

    # Monthly burn breakdown (full-outflow, not team-only)
    burn = snap.get("monthly_burn")
    if burn and burn.get("available"):
        burn_summary = {k: v for k, v in burn.items() if k != "line_details"}
        sections.append("MONTHLY BURN (full-outflow breakdown):\n" + json.dumps(burn_summary, indent=2))

    # Cash position (includes dual deployable, runway on total burn)
    cp = snap.get("cash_position")
    if cp:
        sections.append("CASH POSITION:\n" + json.dumps(cp, indent=2))

    # Team roster (per-person salaries by department)
    tr = snap.get("team_roster")
    if tr and tr.get("roster"):
        tr_summary = {
            "totals": tr.get("totals"),
            "by_department": tr.get("by_department"),
            "headcount": len(tr["roster"]),
        }
        sections.append("TEAM ROSTER (SALARY tab):\n" + json.dumps(tr_summary, indent=2))

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


MAX_HISTORY_MESSAGES = 40  # 20 turns x 2 messages each


def _sanitize_history(history: list) -> list:
    """Validate and trim conversation history from the client."""
    if not isinstance(history, list):
        return []
    clean = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content", "")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        clean.append({"role": role, "content": content})
    # Trim to max length, keeping most recent
    if len(clean) > MAX_HISTORY_MESSAGES:
        clean = clean[-MAX_HISTORY_MESSAGES:]
    # Ensure first message is from user (Anthropic API requirement)
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    return clean


def chat(history: list, snapshot_json: str, token: str, voice: bool = False) -> dict:
    """Send a multi-turn chat message with snapshot context and conversation history.

    voice=True swaps in the spoken register (same brain, same discipline, same
    memory thread — the reply is destined for text-to-speech).
    """
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

    messages = _sanitize_history(history)
    if not messages:
        return {"reply": None, "error": "Empty message"}

    system = SYSTEM_PROMPT.format(context_block=_build_context_block(snapshot_json))
    if voice:
        system += VOICE_ADDENDUM

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300 if voice else 1000,
                temperature=0.5,
                system=system,
                messages=messages,
            )
            reply = response.content[0].text if response.content else ""
            return {"reply": reply, "error": None}
        except Exception as e:
            last_err = e
            # 529 = Anthropic transiently overloaded — retry with backoff
            if "529" in str(e) or "overloaded" in str(e).lower():
                logger.warning("Chat API overloaded (attempt %d) — retrying", attempt + 1)
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    logger.error("Chat API error: %s", last_err)
    return {"reply": None, "error": f"Chat API error: {str(last_err)[:200]}"}
