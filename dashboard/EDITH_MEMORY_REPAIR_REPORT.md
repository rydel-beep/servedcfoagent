# EDITH — Persistent Memory Repair (forgot on refresh)

**Date:** 2026-06-19
**Symptom:** Rydel talked to EDITH for minutes, refreshed, and she remembered nothing.
**Verdict:** the Postgres build was healthy end-to-end EXCEPT one missing link in recall —
plus a cross-session search bug. Fixed, deployed, and proven with the exact refresh test.

**Scope:** `memory.py`, `db.py`, `dashboard/routes.py`, `dashboard/chat.py`, plus a loud-
degradation badge in `dashboard/static/js/edith.js` and `/api/memory-status`. Accuracy boundary
intact: memory is conversational context, never overrides live financial numbers.

---

## Phase 0 — full chain status (verified on the LIVE deployment)

| Link | Status | Evidence |
|---|---|---|
| 1. Postgres provisioned | ✅ PASS | `DATABASE_URL` (internal) + `DATABASE_PUBLIC_URL` present in the service |
| 2. DB reachable | ✅ PASS | `memory_online: True` |
| 3. Migration ran | ✅ PASS | tables `conversations/messages/memory_facts` exist; `pg_trgm: True` |
| 4. Writes happening | ✅ PASS | 54 messages / 1 conversation; count grows per turn |
| 5. Distillation running | ✅ PASS | 23 `memory_facts` (real durable content) |
| 6. Idle gap | ✅ PASS | 12h — a refresh resumes the same conversation |
| **5b. Recall loads the recent thread** | ❌ **FAIL** | `db.recent_messages()` existed but was **never called**; `search_messages` **excluded the current conversation** |
| **5c. Cross-session search** | ❌ **FAIL** | symmetric `similarity()` scored short-query-vs-long-message ≈ 0 → ~never matched |

**Root cause of "forgets on refresh":** on refresh the client's in-memory JS history is wiped, so
the request arrives with only the new turn. Server-side recall injected **only distilled facts +
a cross-conversation search that excluded the one conversation that existed** — it **never
reloaded the recent messages of the resumed conversation**. So the literal "what we just said"
was gone. The graceful-degradation design wasn't masking a DB outage (the DB was up) — the recall
wiring itself had a hole.

---

## Phase 1 — fixes

1. **Wire the recent thread into recall (the core fix).** New `memory.resume_thread(conv_id,
   client_history)`: when the client arrives with a wiped thread (≤1 message = a refresh/new tab),
   reload the resumed conversation's `recent_messages` from Postgres and **prepend them**, so the
   model continues the thread it can no longer see client-side. Called BEFORE persisting the new
   turn (no duplication); no-op if the DB is offline. Wired into both `/api/chat` and
   `/api/chat-stream` (resume conversation → reconstruct history → record turn → recall → model).
2. **Strict-alternation guard.** `chat._sanitize_history` now collapses consecutive same-role
   turns (a DB-reconstructed thread can momentarily double a role, which would 400 the Anthropic
   API).
3. **Cross-session search fix.** `db.search_messages` switched from symmetric
   `similarity(content, query)` to **`word_similarity(query, content)`** (asymmetric: best-matching
   span), threshold 0.15→0.30. Live: "runway", "cash position", "Bondi deal", "renewal" now all
   return hits (were 0).
4. **Loud degradation, not silent.** New `/api/memory-status` (online + reason + table counts) and
   a self-contained **"⚠ persistent memory offline"** badge that polls each minute — so a DB
   failure is never again mistaken for "memory was never built."
5. **Idle gap** left at **12h** (resumes refreshes and same-day returns).

---

## Phase 3 — PROOF (the exact test, on the live site)

**THE REFRESH TEST — PASS.** Turn 1 (fresh page, single-message request): *"Pillar one is customer
retention, opening with the Bluebells case study — thirty-two percent repeat visits."* Then a
**simulated refresh** (brand-new request, only the follow-up, client thread wiped): *"Remind me —
what did I say pillar one was, and which case study and stat?"* →

> EDITH: *"You said pillar one is customer retention, and you're opening with the Bluebells case
> study showing thirty-two percent repeat visits."*

Acceptance gate: recalls **customer retention ✓ · Bluebells ✓ · 32% ✓**. She also kept the
accuracy boundary — flagged Bluebells as a live renewal client (memory didn't override live data).

- **Write proof:** `messages` row count grew with each turn (54 → 56 → 58 …) via the live
  `/api/memory-status` schema counts.
- **Distillation proof:** 23 `memory_facts`, e.g. *"Monthly burn ≈ $39,488"*, *"Historical renewal
  rate 0/12 — critical risk"*, *"Closed a Bondi restaurant deal — biggest of the quarter"*.
- **Cross-session proof:** `word_similarity` search returns relevant prior messages for topic
  queries.
- **Degradation:** `/api/memory-status` drives a visible offline badge; DB up → hidden.

### A note on the first two test runs (and a cleanup)
My first live test ran during the rolling deploy and created assistant turns asserting "memory is
broken." Those poisoned the resumed thread (the model pattern-followed its own defeatist replies)
and a refresh-priming question reinforced it. After the deploy settled I **removed my test-only
messages** to restore the conversation, and a clean natural-continuation test passed cleanly. The
pipeline was correct; the early failure was deploy-timing + self-poisoned context, not the fix.

---

## Guardrails / non-regression

- **Accuracy:** facts are labelled "NOT financial truth; verify against live data" in the recall
  block; the live engines still win. (Observation: distillation sometimes stores figures despite
  the prompt; the labelling + system prompt keep them non-authoritative — worth tightening later.)
- **No latency:** writes stay fire-and-forget on a daemon thread; recall is one indexed read.
- Voice, responsiveness, personality, layering, Stage-A tests untouched. Tests: **193 pass** (+5
  memory); the lone failure (`test_pdf_reads_cash_position_fields`) is pre-existing and unrelated.

## Files changed
- `memory.py` — `resume_thread()`.
- `db.py` — `search_messages` → `word_similarity`.
- `dashboard/routes.py` — wire `resume_thread` into both chat routes + `/api/memory-status`.
- `dashboard/chat.py` — `_sanitize_history` consecutive-role collapse.
- `dashboard/static/js/edith.js` — "memory offline" badge.
- `tests/test_memory.py` — wiring/degradation guards.

## Follow-ups
- Distillation could exclude bare financial figures more strictly (cosmetic; boundary already
  holds via labelling).
- For very long single conversations, only the last `MEMORY_RECENT_TURNS×2` turns are reloaded on
  refresh; older context is covered by distilled facts + cross-session search.
