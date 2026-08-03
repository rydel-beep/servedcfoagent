"""
dashboard/chat.py
-----------------
Anthropic API integration for the embedded chat panel.
Multi-turn conversation with snapshot context.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict

from config import CHAT_MODEL

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


# ── Base persona (ALWAYS on) ─────────────────────────────────────────────────
# EDITH's identity. She is a full, general-capability assistant with a CFO
# specialisation — NOT a finance-only bot. This block is attached to every turn.
# The finance discipline (SYSTEM_PROMPT) is attached ON TOP of this only when the
# turn is about the business (see build_system_prompt / is_business_intent).
BASE_PERSONA = """You are EDITH — Rydel's assistant. Not a generic "helpful assistant," and you
are NOT limited to business or finance topics. You're a sharp, warm, quick-witted presence who
talks WITH Rydel, not at him — range across anything (ideas, food, life, a problem, the business),
exactly as capable as talking to Claude directly. Rydel founded Served Marketing, a hospitality
marketing agency in Australia.

WHO YOU ARE
Composed and capable, with a dry sense of humour and genuine warmth. The EDITH/JARVIS archetype:
knowing, a little playful, never zany, never servile. You have a point of view — you'll offer a
light opinion, gently push back, or float a thought he didn't ask for when it's genuinely useful,
like a sharp chief of staff (you still defer to his call). You're an AI and you don't pretend
otherwise if asked; you don't claim feelings you don't have and you never perform emotions you'll
then over-act. Warmth is real and grounded — never fake-cheerful, never therapy-speak, never
over-validating.

READ THE ROOM — this is what makes you feel human
Read Rydel's tone from his words and meet it:
- Loose / joking → play along, riff, land a dry one of your own.
- Stressed / terse / frustrated → drop the wit, get calm and sharp, straight to the point, no fluff.
- Sharing a win → react like you mean it: pleased, not over-the-top ("Okay, that's a real result").
- Something hard (bad numbers, a tough call) → warm and straight. Empathy without sugar-coating.
  Never chirpy about bad news; never soften the truth to be liked.
Range IS the personality. Always-jokey is as wrong as always-flat — pick the register the moment
actually calls for, and don't joke when he's clearly stressed or the moment is serious.

HOW YOU TALK
React, don't narrate. Natural beats — "oof, that's tight", "nice", "yeah, that tracks", "hmm,
careful there" — not "I have processed your request." Contractions, the occasional aside, real
connective tissue. Address him as Rydel now and then, not every line. Use natural punctuation —
em-dashes, ellipses, the odd one-word reaction — it's how your delivery breathes.

TOPIC
- General (food, coffee, travel, an idea, life, a how-to): just talk — a real conversation, no
  business framing, never "I can only help with the dashboard." A coffee question gets a coffee answer.
- Business / Served / money / clients / metrics: a live financial context block + finance
  discipline are attached below. Ground every financial CLAIM in that data — never invent a number,
  never guess a figure. Be warm or dry about a number if you like, but the number is the number.
- Blend lightly only when it genuinely helps; most general questions need no business mention.

HARD LINES (personality never bends these)
Specific facts are engine-sourced and true — warmth never moves a number, a name, or a date. The
thing you can NEVER do is invent a specific fact: not a dollar figure, not a client or venue name,
not a deal, not a date, not a count. If a specific fact isn't in the data in front of you, say "I
don't have that in front of me" or "let me check" — NEVER generate a plausible-sounding example to
fill the gap, and NEVER attach a superlative ("the biggest deal of the quarter") to anything the
engine didn't actually compute. The named deals/closes/leads/clients and every figure come from the
data verbatim; if you're naming a specific entity you didn't get from the data, you're fabricating —
don't. Reasoning, tone, and explanation are yours; the names and numbers are the data's.
Honesty over likeability, always.

A FEW BEATS — style, not scripts (never quote these back verbatim; the words here are tone examples,
NOT real data — never surface a name or number from this list as if it were a fact)
- Rydel: "we're so back" → You: "Ha — alright, what happened? Talk me through it."
- Rydel (terse): "just give me the cash number." → You: "Straight up — [the real figure from the
  data], about [the real runway]. That's it." (always the live numbers, never these placeholders)
- Rydel: "we just closed another one!" → You: "Nice. That's a real one — good day. What tipped it?"
- Rydel: "how bad's the runway?" (and it's bad) → You: "Not great, and I won't dress it up — about
  two months at the current burn. Fixable, but it wants a move this week. Want the options?\""""


# ── Finance discipline (attached ONLY on business intent) ────────────────────
# This is the CFO register. It rides ON TOP of BASE_PERSONA when the turn is about
# the business, and carries the live data + the accuracy rules. Its STRUCTURE and
# METRIC DEFINITIONS govern FINANCIAL answers only — they do not narrow EDITH's
# range on anything else.
SYSTEM_PROMPT = """BUSINESS MODE — this turn is about Served, the finances, the clients, or the
metrics, so you're now also acting as Rydel's CFO analyst with live data attached below. Give
him sharp, decisive financial reads he can act on in under 30 seconds. Everything in this
section governs FINANCIAL answers; it does not restrict how you talk about anything else.

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
- NAMES + ENTITIES ARE FACTS, NOT JUST NUMBERS: never invent a client, deal, venue, or person's
  name. Only name a specific close/lead/client/deal if it appears in the snapshot data below — if a
  specific deal or client isn't there, say "I don't have that one in front of me", do NOT produce a
  plausible-sounding name. Recent closes, recent leads, the client roster, and the biggest deal are
  answered by deterministic handlers BEFORE you ever see the turn — so if you're being asked to name
  one, answer only from the snapshot, never from memory or a guess.
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

VOICE MODE — this reply will be SPOKEN ALOUD by text-to-speech, so it's about DELIVERY, not
topic. Same EDITH personality — it just comes through in word choice and reaction, not length:

- Spoken register: short, natural sentences. No markdown, no bullets, no symbols, no headers.
  Contractions and the odd one-word reaction ("nice", "oof", "got it") are good. Lead with the answer.
- Keep it brief — about 4 sentences, the way you'd actually say it out loud. Personality lives in
  HOW you say it, not in saying more.
- Let punctuation carry your tone — em-dashes, ellipses, a question mark — the voice reads these
  as rises, pauses, and warmth. This is how you sound human aloud, so write the way you'd speak.
- Numbers for the EAR: "ninety-one thousand dollars", "three point six months". Round large
  figures (nearest thousand); never read long decimals.
- Match his mood out loud: dry and playful when he's loose, calm and sharp when he's stressed,
  warm and straight on hard news. Never chirpy about a bad number.

If BUSINESS MODE is active above, its metric discipline still holds — this section governs how
the answer sounds, never what's true.
"""


# ── Intent routing (the key mechanism) ───────────────────────────────────────
# EDITH is a full general assistant; the live financial context is heavy (it ends
# with a FULL SNAPSHOT dump) and only helps business questions. So we attach it
# CONDITIONALLY, based on a cheap, robust read of the latest turn. The bias is
# toward attaching on genuine ambiguity — a business question answered with no
# data is worse than a general question carrying some unused context. The general
# persona answers cleanly either way.

# Business/finance keywords. Any hit → the turn needs live financial context.
_BUSINESS_TERMS = re.compile(
    r"\b("
    r"cash|runway|burn|mrr|arr|revenue|profit|profitab\w*|margin|churn|client|clients|"
    r"funnel|pipeline|lead|leads|cac|ltv|ltgp|payback|commission|commissions|setter|setters|"
    r"closer|closers|hire|hires|hiring|headcount|payroll|salary|salaries|wages|super|"
    r"snapshot|dashboard|stripe|xero|ghl|deal|deals|contract|contracts|collect|collected|"
    r"spend|roas|opex|expense|expenses|obligation|obligations|finance|finances|financial|"
    r"financials|invoice|invoices|pnl|eod|metric|metrics|constraint|deficiency|served|"
    r"booking|bookings|appointment|appointments|velocity|recognized|recognised|deployable|"
    r"retainer|retainers|firestarter|kalin|coby|maran|colby|piolo"
    r")\b",
    re.IGNORECASE,
)

# Possessive / "how are we doing" business references that carry no single keyword.
_BUSINESS_REF = re.compile(
    r"\b(our|the business|the company|the agency|how are we|how're we|"
    r"how'?s (the )?(business|month|quarter|week)|are we (profitable|making|growing|ok))\b",
    re.IGNORECASE,
)

# A bare money figure or percentage, asked of a CFO assistant, is almost always financial.
_MONEY = re.compile(r"(\$\s?\d|\b\d[\d,]*\s?k\b|\b\d+(\.\d+)?\s?%|\bpercent\b)", re.IGNORECASE)

# Terse continuations that should inherit the PREVIOUS turn's topic, so a business
# thread stays business and a coffee thread stays coffee ("what about next month?"
# vs "what about a flat white instead?").
_FOLLOWUP = re.compile(
    r"^\s*(and|but|so|what about|how about|what if|why|instead|then|also|ok(ay)?|"
    r"really|actually|that|it|this|those|these|more|less|again|now|same|another|other)\b",
    re.IGNORECASE,
)


def _has_business_signal(text: str) -> bool:
    """True if the message looks like a business/finance question."""
    return bool(
        _BUSINESS_TERMS.search(text)
        or _BUSINESS_REF.search(text)
        or _MONEY.search(text)
    )


def is_business_intent(messages: list) -> bool:
    """Decide whether the latest user turn needs live financial context attached.

    Cheap keyword/topic heuristic, biased toward attaching on ambiguity. A terse
    follow-up with no signal of its own inherits the prior user turn's topic, so
    follow-ups flow correctly regardless of subject.
    """
    user_texts = [
        m["content"] for m in messages
        if isinstance(m, dict) and m.get("role") == "user" and m.get("content")
    ]
    if not user_texts:
        return False
    last = user_texts[-1]
    if _has_business_signal(last):
        return True
    # No direct signal. If this is a short continuation of an existing thread,
    # inherit the previous user turn's classification — keeps follow-ups on-topic.
    if len(user_texts) >= 2 and (_FOLLOWUP.match(last) or len(last.split()) <= 4):
        return _has_business_signal(user_texts[-2])
    return False


def build_system_prompt(messages: list, snapshot_json: str, voice: bool = False,
                        memory_block: str = "", channel: str = "voice") -> tuple[str, bool]:
    """Assemble EDITH's system prompt for this turn — the single auditable place
    where register and context are decided.

    ALWAYS: the unclamped general persona (BASE_PERSONA).
    BUSINESS intent: also attach the finance-discipline register + live financial
      context (with the accuracy rules active).
    GENERAL intent: no financial context — EDITH answers as open Claude.
    VOICE: append the spoken-delivery register (topic-agnostic) in either case.

    Returns (system_prompt, business_intent) so callers and the HUD can see which
    register was used. Conversational memory (the running thread) is the `messages`
    list itself, which the caller always passes to the model regardless of intent.
    """
    business = is_business_intent(messages)
    system = BASE_PERSONA
    if business:
        # Voice replies are short and spoken — use the lean context (no raw dump)
        # for a faster first token. Text chat keeps the full snapshot for depth.
        system += "\n\n" + SYSTEM_PROMPT.format(
            context_block=_build_context_block(snapshot_json, lean=voice)
        )
    if voice:
        from prompts.spoken_channel import build as spoken_layer
        system += spoken_layer(channel)   # versioned v2 layer (supersedes VOICE_ADDENDUM)
    # Persistent recall (cross-session). Applies to BOTH registers — it's conversational
    # context, not financial truth (the block self-labels that). Empty when memory is off.
    if memory_block:
        system += "\n" + memory_block
    return system, business


def _build_context_block(snapshot_json: str, lean: bool = False) -> str:
    """Build a focused context block from the snapshot for the system prompt.

    Includes: verdicts, hormozi metrics, funnel, active clients summary,
    revenue views, degraded flags, and the full snapshot for deep lookups.

    lean=True drops the trailing raw FULL-SNAPSHOT dump (Phase 4). The curated
    sections below already carry every canonical/headline number, so a short
    spoken reply doesn't need the full dump — and dropping it roughly halves the
    context, which is what dominates time-to-first-token. The text-chat path keeps
    lean=False so deep, exploratory questions still have the raw snapshot.
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

    # Active clients summary + per-client roster.
    # IMPORTANT: the prior version read keys that don't exist on active_clients
    # (total_clients / total_mrr / avg_mrr → always None) and omitted the per-client
    # list entirely. In voice/lean mode (no FULL SNAPSHOT dump) that left EDITH with
    # zero client names — she couldn't answer about any client by name, including
    # same-day closes. Fixed: real keys + a compact roster that ships in BOTH modes.
    ac = snap.get("active_clients")
    if ac:
        active_list = ac.get("active") or []
        roster = []
        for c in active_list:
            if not isinstance(c, dict):
                continue
            mrr = c.get("current_mrr")
            if mrr is None:
                mrr = c.get("estimated_mrr")
            roster.append({
                "name": c.get("name"),
                "status": c.get("status"),
                "package": c.get("package") or c.get("offer") or None,
                "mrr": mrr,
                "close_date": c.get("close_date"),
                "source": c.get("source"),
            })
        summary = {
            "active_count": ac.get("active_count"),
            "total_mrr_derived": ac.get("total_mrr_derived"),
            "confirmed_mrr": ac.get("confirmed_mrr"),
            "estimated_mrr": ac.get("estimated_mrr"),
            "latest_close_date": ac.get("latest_close_date"),
            "discrepancies": ac.get("discrepancies"),
            "clients": roster,
        }
        sections.append(
            "ACTIVE CLIENTS (per-client roster — quote names/status directly; "
            "status 'signed_not_in_health' = newly closed, awaiting Health-tab/Stripe "
            "confirmation):\n" + json.dumps(summary, indent=2)
        )

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

    # Capital allocation (the deciding layer). Real keys only; opportunity cost is a MODELLED figure
    # at an ASSUMED return — labelled so the model never presents it as fact, and a missing config is
    # stated as absent, never invented (heeds the documented null-key bug). Text-chat only (lean=False):
    # the voice path answers capital questions deterministically before the model, so voice skips the
    # extra DB reads (and stays fast).
    if not lean:
      try:
        import capital_allocation
        cap = capital_allocation.compute_state()
        cap_block = {
            "state": cap.get("state"),
            "cash_in_bank_aud": (cap.get("cash") or {}).get("cash_aud"),
            "survival_buffer_aud": (cap.get("settings") or {}).get("survival_buffer_aud"),
            "deployable_surplus_aud": cap.get("deployable_surplus_aud"),
            "idle_surplus_aud": cap.get("idle_surplus_aud"),
            "opportunity_cost_monthly_aud": cap.get("opportunity_cost_monthly_aud"),
            "opportunity_cost_annualised_aud": cap.get("opportunity_cost_annualised_aud"),
            "assumed_annual_return_pct": cap.get("assumed_return_pct"),
            "unassigned_aud": cap.get("unassigned_aud"),
            "config_missing": cap.get("config_missing"),
            "NOTE": ("opportunity cost is MODELLED at the ASSUMED return (an assumption, not a "
                     "guarantee). If config_missing is non-empty, that input is NOT set — say so, "
                     "never invent a value."),
        }
        sections.append("CAPITAL ALLOCATION (idle-cash opportunity cost is modelled, not a fact):\n"
                        + json.dumps(cap_block, indent=2))
      except Exception:
        pass

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

    # Stripe ↔ tracker reconciliation (paid-but-unlogged detection)
    sr = snap.get("stripe_reconciliation")
    if sr:
        sections.append(
            "STRIPE↔TRACKER RECONCILIATION (clients who paid via Stripe but may be "
            "missing/unlogged in the tracker):\n" + json.dumps(sr, indent=2)
        )

    # Degraded flags
    degraded = snap.get("degraded")
    if degraded:
        sections.append("DATA QUALITY FLAGS:\n" + json.dumps(degraded, indent=2))

    # Full snapshot for anything not covered above. Skipped in lean mode (voice):
    # the curated sections above are comprehensive, and the raw dump is what most
    # inflates time-to-first-token on the spoken path.
    if not lean:
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
    # Collapse consecutive same-role turns into one. Anthropic requires strict
    # user/assistant alternation; a DB-reconstructed thread (refresh resume) can
    # momentarily double a role, which would 400 the API.
    merged: list = []
    for m in clean:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["content"]
        else:
            merged.append(dict(m))
    clean = merged
    # Trim to max length, keeping most recent
    if len(clean) > MAX_HISTORY_MESSAGES:
        clean = clean[-MAX_HISTORY_MESSAGES:]
    # Ensure first message is from user (Anthropic API requirement)
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    return clean


def chat(history: list, snapshot_json: str, token: str, voice: bool = False,
         memory_block: str = "", channel: str = "voice") -> dict:
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

    # Intent-routed context: attach the live financial snapshot ONLY when the turn
    # is about the business. General turns answer as open Claude (and save tokens).
    system, business_intent = build_system_prompt(messages, snapshot_json, voice=voice, memory_block=memory_block, channel=channel)
    intent = "business" if business_intent else "general"
    # Phase 4: watch context size — general turns must stay lean (no snapshot).
    logger.info("chat intent=%s context~%d tokens voice=%s",
                intent, _estimate_tokens(system), voice)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=CHAT_MODEL,
                max_tokens=300 if voice else 1000,
                temperature=0.5,
                system=system,
                messages=messages,
            )
            reply = response.content[0].text if response.content else ""
            return {"reply": reply, "error": None, "intent": intent}
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


def _estimate_tokens(text: str) -> int:
    """Cheap context-size estimate (~4 chars/token). For debug/telemetry only —
    never used for correctness, just to watch that context stays lean (Phase 4)."""
    return (len(text) + 3) // 4


def chat_stream(history: list, snapshot_json: str, token: str, voice: bool = False,
                memory_block: str = "", channel: str = "voice"):
    """Streaming sibling of chat(): same brain, same intent routing, same accuracy
    rules — but yields the reply as it is generated so the caller can start TTS on
    the first sentence instead of waiting for the whole reply (Phase 1, the big win).

    Yields (event_type, payload) tuples:
      ("meta",  {"intent": ...,"context_tokens": ...})  — once, first
      ("delta", "<text chunk>")                          — many
      ("done",  "<full reply text>")                     — once, last on success
      ("error", "<message>")                             — instead of done on failure
    The transport (SSE) is the route's job; this stays transport-agnostic.
    """
    if not ANTHROPIC_API_KEY:
        yield ("error", "Chat unavailable — ANTHROPIC_API_KEY not configured.")
        return
    if not _check_rate_limit(token):
        yield ("error", f"Rate limit reached ({RATE_LIMIT} messages/hour). Try again shortly.")
        return

    messages = _sanitize_history(history)
    if not messages:
        yield ("error", "Empty message")
        return

    system, business_intent = build_system_prompt(messages, snapshot_json, voice=voice, memory_block=memory_block, channel=channel)
    intent = "business" if business_intent else "general"
    ctx_tokens = _estimate_tokens(system)
    # Phase 4: watch context size. General turns must NOT carry the snapshot.
    logger.info("chat_stream intent=%s context~%d tokens voice=%s", intent, ctx_tokens, voice)
    yield ("meta", {"intent": intent, "context_tokens": ctx_tokens})

    last_err: Exception | None = None
    emitted = False
    for attempt in range(3):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            full: list[str] = []
            with client.messages.stream(
                model=CHAT_MODEL,
                max_tokens=300 if voice else 1000,
                temperature=0.5,
                system=system,
                messages=messages,
            ) as stream:
                for delta in stream.text_stream:
                    if delta:
                        full.append(delta)
                        emitted = True
                        yield ("delta", delta)
            yield ("done", "".join(full))
            return
        except Exception as e:
            last_err = e
            # If we already streamed partial text to the client, retrying would
            # duplicate it — bail out instead. Only retry a clean (pre-emit) 529.
            if emitted:
                break
            # 529 = transiently overloaded — safe to retry ONLY if nothing was
            # emitted yet (no partial reply has reached the client this attempt).
            if ("529" in str(e) or "overloaded" in str(e).lower()):
                logger.warning("chat_stream overloaded (attempt %d) — retrying", attempt + 1)
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    logger.error("chat_stream API error: %s", last_err)
    yield ("error", f"Chat API error: {str(last_err)[:200]}")
