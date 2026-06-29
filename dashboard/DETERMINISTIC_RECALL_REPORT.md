# DETERMINISTIC FACTUAL RECALL — stop the model embroidering data

**Date:** 2026-06-29 (Sydney) · Trigger: a verify run caught the model fabricating
"Bondi Beach Restaurant — biggest deal of the quarter" on a "last few closes" question.

## Phase 0 — routing map + fabrication root cause

**Deterministic (exact, pre-model) before this build:** resync, data-sources, manual targets,
unit-economics (LTGP:CAC/ROAS/LTV/CAC), payback, latest/recent leads.
**Still hitting the free-styling model:** "last few closes", "recent deals", "biggest deal",
client roster — i.e. open-ended FACTUAL recall.

**Root cause of "Bondi Beach Restaurant" (two compounding faults):**
1. The persona's own style examples contained `Rydel: "closed the Bondi deal!"` — so "Bondi" was
   primed in-context as a deal name. Asked to name closes, the model echoed its own example as if
   it were real data.
2. The HARD LINE read *"the ONLY thing you can never do is invent financial figures"* — which
   **implicitly licensed inventing entities** (names/deals/venues). The rule guarded numbers, not names.
The closes list wasn't answered deterministically, so the open question reached the model, which
filled the gap with a plausible-sounding venue + a superlative the engine never computed.

## Phase 1 — deterministic handlers (`closes_view.py`)
- "Last few / recent closes / recent deals" → real won deals from the mirror (Call Outcome == won,
  newest by Close Date) returned VERBATIM: business, date, offer, contract value. No model.
- "Biggest deal" → the max real contract value (optionally last 90d); if no rankable contract data,
  it DEFERS ("I'd need to check") — never invents a superlative.
- Wired into the chat router before the model (both text + stream), after the leads handler.

## Phase 2 — anti-fabrication guardrail (persona, `chat.py`)
- Rewrote the HARD LINE: the thing you can NEVER do is invent **a specific fact — not a figure, not
  a client/venue name, not a deal, not a date, not a count.** Missing fact → "I don't have that in
  front of me", never a plausible example, never a superlative the engine didn't compute.
- Removed the "Bondi deal" example (replaced with a venue-free beat) + labelled the style beats
  "tone examples, NOT real data — never surface a name/number from this list as a fact".
- Reinforced in business-mode DATA RULES: names + entities are facts, not just numbers; only name a
  close/lead/client/deal that's in the snapshot; the deterministic handlers answer these before the
  model sees them.

## Verify
"Last few closes" → real won deals verbatim, no Bondi, no fabricated dates. "Biggest deal" → real
max contract or honest defer. Adversarial (a nonexistent deal) → model defers, doesn't invent.
Reasoning ("how are closes trending") still conversational, grounded in exact data. 273 tests (+4).
