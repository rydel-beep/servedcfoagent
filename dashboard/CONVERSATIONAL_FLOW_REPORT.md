# CONVERSATIONAL FLOW & INTENT ROUTING FIX — stop data non-sequiturs on musings

**Date:** 2026-07-03 (Sydney)

## Phase 0 — the misfire chain (replayed the exact utterance)
Utterance (voice musing): *"…what we do for Served, complete marketing system, the influencers…
the angle is more on: they know exactly, dollar in dollar out…"*

Replayed through every handler → **`salary_view.handle_salary_command` FIRED.** Why:
`_PAY_RE = (what|how much).*(pay|salary|…|on)\b` — the greedy `.*` **bridged "what"** (in "what we
do") **to "on"** (in "the angle is more on"). ANY utterance containing "what" + "on" (or a bare
"salary"/"pay"/"payroll" anywhere) matched. It then reached a payroll row (in the live incident, a
mis-transcribed fragment resolved to the FB-ads dept → Romano's row).

**Old taxonomy/fallback:** a flat CHAIN of handler regexes — first match wins, short-circuiting the
model. **No confidence gate, no default-to-conversation, no entity check.** Long rambling voice
transcripts were force-fit into an intent; a mid-ramble fragment could independently trip a lookup.

## Phase 1–3 — the fix
**Three tiers (`intent_router.py`):**
- **TIER 1 commands** (set target, mark churned, resync) — strict phrasing, run FIRST (unchanged).
- **TIER 2 data** (counts, salary, unit-econ, payback, leads/closes) — **GATED**.
- **TIER 3 conversation** — the DEFAULT.

**The ramble gate (`is_conversational_ramble`):** a turn with NO data-request structure — no explicit
data phrase ("how many", "what's our", "what do we pay"), no "?", and > 6 words — is a musing and
**SKIPS all TIER 2 handlers**, falling through to the model. Explicit data phrases fire TIER 2 at any
length; terse asks (≤ 6 words) still reach the handlers. **Asymmetry rule:** unsure → conversation.

**Entity-relevance gate (`entity_relevant`, the "Romano rule"):** before an ENTITY-SCOPED lookup
(a person's salary) is returned, a named person in the reply must appear in the utterance/thread —
else it's a non-sequitur and is **suppressed** (falls to conversation). Aggregate/team replies and
superlative/recency lookups (biggest deal, latest lead) are exempt — they surface entities by design.

**Tightened `_PAY_RE`:** the pay verb must sit within a few words of the interrogative — no
cross-ramble bridging. "what we do… more on" no longer matches; real pay questions still do.

**TIER 3 engagement:** musings route to the model WITH recent turns (thread), recalled memory, and
the persona — verified on both `/api/chat` and the voice `/api/chat-stream` path. Figures woven into
conversation stay engine-sourced.

## Verify
`tests/test_intent_router.py` (6): the incident is a ramble; 6 musings all route to conversation; 6
data questions are NOT rambles; `_PAY_RE` no longer matches the ramble; the salary handler is silent
on it; the entity gate suppresses the unmentioned person yet passes named/aggregate replies. 303
tests pass. Live replay below.
