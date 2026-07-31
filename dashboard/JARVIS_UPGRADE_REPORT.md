# THE JARVIS UPGRADE — report (in progress: Phase 0 + Pillar 1 landed)

**Date:** 2026-07-31 (Sydney). A five-pillar upgrade. This is a genuine multi-session build; per the
work order it lands **pillar by pillar with a regression suite at each boundary** ("each pillar
leaves the system shippable"). **Phase 0 (map + gate) and Pillar 1 (Initiative) are landed and
verified.** Pillars 2–5 are the next increments.

## The hard boundary — EDITH is internal-only (verified)
Grep-verified across the whole codebase: **no outbound client-contact path exists** — no email/SMS/
message send, no smtp/sendgrid/twilio; the GHL module is **read-only** (`requests.get` only). Nothing
can message a client, and this build adds nothing that could. Open-loop tracking is scoped to
internal/system matters only; **no client-deal loops or follow-ups** are ever created (adversarially
unit-tested).

## Phase 0 — five-pillar current-state map
| Pillar | Exists now | Gaps |
|---|---|---|
| 1 Initiative | `salience.py` (10 watermarked event types) → greeting | **[BUILT]** open-loop store + anomaly watch; push channel (deferred) |
| 2 Drift-proofing | `DECISIONS.md` (prose, 110 entries); `memory_facts`; watermarks; thread state | structured/versioned **Decisions Registry**; advisory citation; memory supersession; consistency audit |
| 3 Doctrine | doctrine in `CLAUDE.md`; `handle_advisory` grounds in figures + `_principle_for` | canonical **`SERVED_DOCTRINE.md`**; systematic doctrine-binding; doctrine-aware proactiveness |
| 4 Craft | `edith.js` already has substantial **barge-in** machinery; register rules; thread state | measure barge-in latency; **repair** handler; register mirroring; **multi-intent** completeness; conversation-wide variety |
| 5 Self-knowledge | `/health` (server/db/freshness/degraded); `incident_log`; `source_freshness` | **conversational** self-state ("what's degraded / how fresh / what can you do / what did you get wrong") |

**Push-channel gate (Rydel's call):** **dashboard-only** — initiative surfaces in the greeting +
salience + dashboard; no Lark push (flagged as the initiative limitation; a clean seam remains to
add a `LARK_WEBHOOK_URL` later).

## Pillar 1 — the Initiative engine (landed)
**A. Open-loop tracking (`open_loops.py`), internal/system only.**
- **Reminders** — "remind me to X [when]" creates a loop; it resurfaces in the greeting with manners,
  at most every `FOLLOWUP_DAYS` (watermarked); **"drop it" kills it permanently**. A reminder that
  reads like EDITH-chasing-a-client ("remind me to email the client") is **refused, citing the
  internal-only boundary** — she'll remind *you* to do it, never do it herself.
- **System loops** (derived, cheap, non-recursive): Xero re-auth needed, capital buffer unset, Stripe
  read-only key unset — technical gates awaiting a Rydel action. (Deliberately NOT the collab queue /
  test-lead scan — those cycle through `action_feed→salience` or are heavy; they surface on their own
  panels.)
- **No client-deal loops, ever** — the boundary is enforced in code and unit-tested.

**B. Anomaly watch (`anomaly_watch.py`).** Each cycle, a deterministic deviation check vs the trailing
trend — lead velocity, cash movement, failed charges, and loaded CPL (current 7d vs trailing 28d via
the one canonical engine). A deviation beyond the (adjustable) threshold becomes a watermarked
salience event with the deviation **quantified** ("CPL $81 → $126, +55% vs the trailing 4-week"). No
urgency is manufactured; every figure is engine-verbatim.

**C. Push channel:** dashboard-only (per the gate). Initiative rides the existing salience→greeting
path; the etiquette (watermarks, no-nag cadence, "drop it") is in place.

### Verification (live)
- **Reminder** — "remind me to reconnect Xero this week" → `command`: *"Got it — I'll remind you…"*
  Next fresh greeting: *"you asked me to remind you about reconnecting Xero this week… still sitting
  open."* → **"drop it"** → *"Dropped — I won't bring that up again."* ✓
- **Boundary (adversarial)** — "remind me to email the client about their invoice" → **refused**,
  cites the internal-only rule; grep confirms no outbound path; a client-deal question creates **no
  loop**. ✓
- **Anomaly** module runs deterministically inside salience (watermarked). ✓
- **Router regression** — imperative commands ("remind me", "drop it", "set…") no longer misclassified
  as conversational rambles; genuine musings still route to conversation. Advisory/scenario (T1/T3)
  intact.

### A bug I introduced and fixed (honest)
Wiring loops into `salience.collect`, I created an **infinite recursion**: `salience.collect →
open_loops.system_loops → collab.queue → action_feed.build_action_feed → salience.collect`. It hung
the greeting *and* the dashboard action feed. Root-caused from the logs, fixed by removing the
recursive/heavy calls from `system_loops` (now cheap, non-recursive). Verified: greeting responds in
~5s, action feed returns 13 items.

## Status & next increments
**Landed & shippable:** Phase 0 + Pillar 1 (Initiative). **Next (in order, each with its own
regression boundary):** Pillar 2 (Decisions Registry + supersession + consistency audit), Pillar 3
(`SERVED_DOCTRINE.md` + advisory binding), Pillar 4 (barge-in latency + repair + multi-intent
completeness + register mirroring), Pillar 5 (conversational self-knowledge). The two canon documents
(registry + doctrine) will be seeded for Rydel's sign-off before they bind.
