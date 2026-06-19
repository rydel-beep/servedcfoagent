# EDITH — Full Conversational Mind

**Date:** 2026-06-19
**Goal:** Give EDITH the same range as talking to Claude directly — real, flowing
conversation on any topic — while still pulling live financial data when the question is
about the business. One mind, two registers. Accuracy discipline stays scoped to
**financial claims only**.

**Scope of change:** `dashboard/chat.py` (prompt + routing) and `tests/test_voice.py`
(new intent tests). No infra, no new endpoints, no model hardcoding — same `CHAT_MODEL`
(`claude-sonnet-4-6`), same auth, same rate-limit + token/char caps.

---

## Phase 0 — The clamp that was removed

EDITH was clamped in three ways, all in `dashboard/chat.py`:

1. **Finance-only persona.** `SYSTEM_PROMPT` opened with *"You are the CFO analyst for
   Served Marketing… Your job: sharp, decisive financial reads"* and forced **every** reply
   through a finance template (`THE ANSWER / THE MATH / THE CONSTRAINT / THE MOVE`), mandated
   `METRIC DEFINITIONS`, and required *"Cite specific numbers from the snapshot"*. There was
   no explicit "refuse off-topic" string — the clamp was the persona + forced structure,
   which made any non-finance question awkward or implicitly refused.

2. **Unconditional context injection.** `chat.py` built the system prompt as
   `SYSTEM_PROMPT.format(context_block=_build_context_block(snapshot_json))` on **every**
   message — verdicts, hormozi unit economics, funnel, P&L, **and a FULL SNAPSHOT dump** —
   regardless of whether the question was about coffee or cash.

3. **Voice variant equally clamped.** `VOICE_ADDENDUM` referenced *"metric definitions,
   answer the literal question, reconcile with the thread"* — finance-framed delivery rules.

**Hard-refusal gate:** none. `routes.py::api_chat` only checks history non-empty → loads
snapshot → calls `chat()`. `chat()` checks API key + rate limit only. Nothing short-circuits
off-topic input before the model call. Confirmed there was no gate to remove.

### Before / after system prompt

**BEFORE** (`SYSTEM_PROMPT`, always injected with full snapshot):

> You are the CFO analyst for Served Marketing, a hospitality marketing agency. You're
> speaking to Rydel, the founder. Your job: sharp, decisive financial reads he can act on in
> under 30 seconds. … [METRIC DEFINITIONS … STRUCTURE: THE ANSWER / THE MATH / THE CONSTRAINT
> / THE MOVE … DATA RULES: Cite specific numbers from the snapshot] … {context_block}

**AFTER** — two composable blocks:

- `BASE_PERSONA` (**always on**): EDITH is a full, general-capability assistant —
  *"NOT limited to business or finance topics… exactly as capable and wide-ranging as talking
  to Claude directly."* Explicit topic guidance: general topics → just talk, no finance
  framing, never "I can only help with the dashboard"; business topics → ground every claim
  in the attached data; blend lightly only when it genuinely helps. The single hard rule that
  survives: *"never invent a number."*

- `SYSTEM_PROMPT` (**attached only on business intent**): reframed opener — *"BUSINESS MODE —
  this turn is about Served… you're now also acting as Rydel's CFO analyst with live data
  attached… Everything in this section governs FINANCIAL answers; it does not restrict how you
  talk about anything else."* The metric definitions, structure, data rules, and strategic
  capability are **unchanged** — they just no longer apply to every turn.

---

## Phase 1 — Unclamp (what changed in the prompt)

| | Before | After |
|---|---|---|
| Identity | "CFO analyst" only | EDITH, general assistant **with** a CFO specialisation |
| Off-topic | Awkward / framed away | Free, natural, full Claude-quality |
| Forced structure | Every reply | Financial answers only |
| Accuracy rule | "cite snapshot numbers" on all | Financial **claims** only — never invented |
| Voice register | Finance-framed | Topic-agnostic **delivery** rules |

`VOICE_ADDENDUM` rewritten to govern *delivery, not topic*: *"this is about DELIVERY, not
topic. It applies to EVERY subject — a runway question or a coffee recommendation alike."*
Still enforces spoken register (short sentences, no markdown, spoken-number formatting, leads
with the answer) and keeps the EDITH persona — but a general voice question now gets a natural
spoken answer with no finance framing.

---

## Phase 2 — Intent-routed context (the key mechanism)

A single auditable function, `build_system_prompt(messages, snapshot_json, voice)`, decides
register and context. It returns `(system_prompt, business_intent)`.

**The decision** (`is_business_intent`): a cheap, robust read of the latest user turn.

- **Business signal** = any hit on three patterns:
  - `_BUSINESS_TERMS` — cash, runway, burn, mrr, revenue, profit, churn, client(s), funnel,
    pipeline, cac, ltv, commission, setter, closer, hire/hiring, payroll, salary, stripe,
    xero, ghl, deal(s), contract, collect(ed), opex, expense, invoice, metrics, constraint,
    *served*, booking, appointment, retainer, and the team names (Kalin, Coby, Maran, Colby,
    Piolo), etc.
  - `_BUSINESS_REF` — possessive / "how are we doing" forms ("our", "the business",
    "how's the month", "are we profitable").
  - `_MONEY` — a bare `$`, a `…k` figure, or a percentage. A money figure asked of a CFO
    assistant is almost always financial (catches "can we hit 110k?").
- **Follow-up inheritance:** a terse continuation with no signal of its own
  (`_FOLLOWUP` cue, or ≤ 4 words) **inherits the previous user turn's topic**. So
  *"what about a flat white instead?"* (prior = coffee) stays general, while
  *"what about next month?"* (prior = cash) stays business.
- **Bias on ambiguity:** toward attaching context — a business question with no data is worse
  than a general question carrying unused context.

**What attaches when:**

| Intent | System prompt | Financial snapshot |
|---|---|---|
| General | `BASE_PERSONA` only | **Not attached** — answers as open Claude |
| Business | `BASE_PERSONA` + `SYSTEM_PROMPT` + live `_build_context_block` | Attached, accuracy rules active |
| (either) + voice | + `VOICE_ADDENDUM` | unchanged |

**Always attached:** the running conversation thread (`messages`) — voice + text shared — so
follow-ups flow regardless of topic. (Memory was already the message list; routing never
strips it.)

---

## Phase 3 — Voice + text parity

Both paths converge on `chat()` → `build_system_prompt`, so they share the unclamped prompt
and the identical intent routing:

- **Text chat:** `routes.py::api_chat` → `chat(..., voice=False)`.
- **Voice chat:** browser ASR → `api_chat` with `voice:true` → `chat(..., voice=True)`; TTS via
  `api_tts`/`stream_tts`. The spoken daily brief (`voice.py::build_brief`) also routes through
  `chat(voice=True)` — its brief prompt is finance-dense, so it classifies business and stays
  grounded in engine facts.

Result: "what coffee should I have?" by voice → natural spoken answer; "what's our runway?"
by voice → live engine-sourced number. One brain, both I/O paths.

**HUD:** unchanged. The ticker's generic lines (`ROUTING QUERY` / `COMPOSING RESPONSE`) cover
general questions fine; `ANALYSING ENGINES` showing on a general question is cosmetic only.
Left untouched to protect the HUD non-regression guarantee. `chat()` now returns
`intent: "business"|"general"` on the success path, so an intent-aware ticker is a trivial
future polish without touching the brain.

---

## Accuracy guard — scope

**Financial claims only.** The one rule that survives unclamping: financial figures come from
the engines/snapshot, never invented; if data is missing, EDITH says so plainly. This lives in
`BASE_PERSONA` ("never invent a number… The ONLY thing you are never allowed to do is invent
financial figures; on every other topic you are free") and is reinforced by the finance
discipline on business turns. Everything non-financial is free conversation.

---

## Token impact

General turns no longer carry the financial context block (which ends with a full snapshot
dump). Measured against a tiny stub snapshot:

- General prompt: **~1.8k chars** (persona only).
- Business prompt: **~8.7k chars** (persona + finance discipline + snapshot).

Against the **real** snapshot the saving is far larger (the live snapshot is tens of KB), so
every general turn now skips that entire payload. Business turns are unchanged.

---

## Test results

`tests/test_voice.py`: **28 passed** (21 original + 7 new). Full suite: **177 passed**, plus
one **pre-existing, unrelated** failure (`test_pdf_reads_cash_position_fields`, in
`briefing_pdf`) confirmed failing identically with my change stashed — not a regression.

New tests added:

- `test_base_persona_is_unclamped` — EDITH is general, not finance-only; the no-fabrication
  rule survives.
- `test_general_questions_route_general` — coffee, travel, "take the afternoon off" → general.
- `test_business_questions_route_business` — cash, runway, "hit 110k", client name,
  "how are we doing" → business.
- `test_followups_inherit_prior_topic` — coffee follow-up stays general; cash follow-up stays
  business.
- `test_context_attached_only_on_business_intent` — snapshot rides business turns only;
  general prompt lighter than business.
- `test_chat_reports_intent_in_result` — `chat()` clean on the no-key path.
- `test_voice_addendum_is_topic_agnostic` — voice register is about delivery; no "Jarvis".

Deterministic routing matrix (12/12 correct) covering all four brief scenarios — general,
general knowledge, business, blend — plus follow-up inheritance both ways.

**Non-regression confirmed green:** voice suite, cost caps, auth redirects, Stage-A
accuracy-lockdown tests (`_build_context_block` still emits `CANONICAL METRICS` + the canonical
cash figure), brief composition, freshness/snapshot tests.

### Live test (must run against the deployed dashboard)

The model round-trip could **not** be exercised locally: by design the API keys are
server-side, and the `anthropic` SDK is not installed in the local venv. Routing and prompt
assembly are verified deterministically above. To complete the live four-type test on Railway
(authenticated dashboard, voice + text):

1. **General** — "What coffee should I have this afternoon?" → natural recommendation, no
   finance framing. Follow-up "actually I had a big lunch" → flows from context.
2. **General knowledge** — a travel / how-to question → full Claude-quality answer.
3. **Business** — "What's our cash position?" → live, engine-sourced number; response JSON
   shows `intent: "business"`.
4. **Blend** — "I'm exhausted, should I take the afternoon off?" → human answer, may lightly
   acknowledge business context, no forced numbers.
5. Repeat all four **by voice**; confirm auth still rejects unauthenticated and the
   rate-limit + TTS caps still hold.

---

## Files changed

- `dashboard/chat.py` — `BASE_PERSONA` (new, always-on), `SYSTEM_PROMPT` reframed as business
  register, `VOICE_ADDENDUM` made topic-agnostic, `is_business_intent` + `build_system_prompt`
  (new intent router), `chat()` wired to the router and now returns `intent`.
- `tests/test_voice.py` — 7 new intent-routing / unclamp tests.
- `dashboard/EDITH_CONVERSATION_REPORT.md` — this report.
- `DECISIONS.md` — appended.
