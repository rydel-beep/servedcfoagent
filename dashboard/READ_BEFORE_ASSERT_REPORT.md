# READ-BEFORE-ASSERT + IN-CHAT SELF-DIAGNOSIS — build report

**Date:** 2026-07-09 (Sydney)

## Phase 0 — incident verdict: MODEL INFERENCE (not stale mirror)
EDITH claimed "cash collected is blank for Hung's Chinese, Lost Sheep Cafe, Akuna Cafe." Read of the
LIVE sheet (Lead-to-Cash Tracker, col 32 "Cash Collected"):

| Row | Close | Contract | **Cash Collected (live)** |
|---|---|---|---|
| Hung's Chinese | 7/8/2026 | $15,100 | **$8,305.00** |
| Lost Sheep Cafe | 7/7/2026 | $14,500 | **$15,950.00** |
| Akuna Cafe | 6/30/2026 | $18,300 | **$1,650.00** |

All three **FILLED**. **Verdict: model inference.** There was NO deterministic per-row cash read
path — `_won_deals` reads business/close/contract only; the range engine reads cash *in aggregate*
(sums col 32) but never reports per-row. So a "cash for [client]" question read NOTHING and fell to
the model, which inferred "blank" from a cash figure's composition and asserted it as fact. A fresh
mirror wouldn't have helped — no code path read those cells. The gap: deterministic recall never
covered FIELD STATES.

## Phase 1 — read-before-assert (`tracker_read.py`)
`read_client_row(name)` resyncs the tab if stale/recent-row (>10 min → targeted resync), reads the
row, returns every field VERBATIM (offer, close, contract, **cash collected**, outcome) + sync time.
`client_context(text)` injects the verbatim row(s) into the model whenever a client field-state
question is detected — so the model states cell contents ONLY from the read, never infers 'blank'.
A genuinely blank cell is reported blank (truth); a filled cell is reported filled. Client matching
is distinctive-token-only (never "cafe"/"bar"/"the"), so "that's wrong" can't match "That Bakery".

## Phase 2 — self-check loop (`handle_self_check`)
CHALLENGE trigger ("that's wrong / it's not blank / I just checked / are you sure / double-check")
→ resync → re-read the exact rows (from the message or the recent thread) → CORRECT with root cause
("You're right — I asserted that without reading the cells. Resynced <time>: Hung's $8,305, Lost
Sheep $15,950, Akuna $1,650") and recompute the affected total — OR CONFIRM with verbatim cells if
the claim was right (truth, not appeasement). All in-chat.

## Phase 3 — diagnostic commands (Tier 2, deterministic)
- "check the tracker for [client]" → resync + verbatim row + sync time.
- "cash collected for [client]" / "why doesn't cash include [client]" → the exact cell + inclusion
  rule (filled = counted; only a blank cell excludes a row). Distinguishes tracker cash-collected
  (team-logged) from Stripe trailing-30d cash (landed) — never conflated.
- "verify your data" / "diagnose yourself" → per-tab sync state + age + row count + auto-resync if aging.

## Phase 4 — incident log (`incident_log.py`)
When the self-check finds a filled cell that was claimed blank (staleness can't explain it), EDITH
logs a STRUCTURED incident (asked / claimed / truth / trace / suspected code path). "show me the
incident" / "write that up for a fix" → a copy-ready block for Claude Code, stating plainly a
code-level fix is needed and she can't self-patch code.

## Guardrails held
Field states are READ, never inferred; recent-row/stale questions auto-resync before answering;
challenges trigger in-chat resync → re-read → correct/confirm + root cause + recompute; she never
asks Rydel for numbers she can read; truth over appeasement; code bugs get an honest handoff.
Wired into both `/api/chat` and the voice `/api/chat-stream`. Verified live below.
