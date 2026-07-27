# GHL LEAD INTELLIGENCE & REACTIVATION ENGINE — report

**Date:** 2026-07-27 (Sydney). EDITH now sees GHL at the ROW level — every lead, its notes, and
where it left off — and produces a ranked, grounded reactivation list the sales team works from.

---

## Phase 0 — access, inventory, decisions

**API access — reused, no new credentials.** The app's existing `GHL_SALES_API_KEY` is a Private
Integration Token (`pit-…`) with **full scope** — probed live, all four surfaces returned 200:
pipelines, opportunities, **contacts**, and **notes**. No mint, no Railway change. Rate limits:
100 req/10s burst, 200k/day (ample). The Booking-Intelligence pattern wasn't needed — this token
already reads everything.

**Inventory** (pipeline `JJQLCr1fl7OHyrpRwSJp`, "1 SERVED Client Acquisition"): 1,342 opportunities
(1,290 open), 16 stages. Unresponsive/Not Interested = 986 open / $2.23M — matches the oracle.

**Rydel's Phase-0 calls:** (a) EXCLUDE Disqualified (86) + Ban Leads DND (22) from reactivation —
still counted in hygiene, never a target (DND = contact risk); (b) PITCHED-STALLED = reached a
consult stage, open, no stage-change 21+ days; (c) DELIVERY = export-first (CSV + brief), no sales
dashboard role for now.

## Phase 1 — the GHL mirror (`ghl_mirror.py`)
The proven sheet-mirror pattern extended to GHL: `ghl_opportunities`, `ghl_contacts`, `ghl_notes`
(+ `ghl_sync_state`) in Postgres — idempotent upserts, change-detection (note `body_hash`),
deletion propagation, per-source freshness, a background opps loop, resync coverage, and a
resumable throttled backfill (bounded to the open-opp reactivation universe).

**Backfill result:** 1,342 opps / 1,290 open / **1,290 contacts / 2,943 notes** mirrored.

**Integrity — provably faithful, two ways:**
- **Full-population reconciliation** (stronger than a sample): every stage's mirror OPEN count
  equals the GHL oracle — Unresponsive **986 / $2,224,500** ✓, Consult Booked 38 ✓, 2nd Consult 15 ✓,
  Disqualified 86 ✓, Stale 13 ✓, Call Back to Set 14 ✓ … all stages match.
- **Row-level spot-diff:** 6/6 sampled leads matched live GHL exactly on value **and** note count.

## Phase 2 — deterministic classification (`reactivation.py`)
Pure queries over the mirror (bulk-loaded — a few queries, not per-lead). Per lead: stage, status,
value, created, last-touch, days-stale, days-since-touch, notes count, bucket, **warmth** (stage
weight × value factor × recency), and a **tracker join** (email → name-token smart match; unmatched
flagged, never forced).

**Result:** **914 reactivation leads worth $2,354,000** — 878 stale + 36 pitched-stalled. 159 leads
correctly EXCLUDED (Disqualified + Ban DND + Won). Every count is cross-checked against GHL's own
stage filters (reconciliation table above).

**Notes-hygiene finding:** **12% of reactivation leads (111 of 914) have zero notes logged** — cold
reactivation, and a team-process gap worth closing. (The notes that exist are rich — call
briefings/transcripts, ~12.5k chars avg.)

## Phase 3 — grounded "where it left off" (`ghl_notes_summary.py`)
For a candidate, the model reads THAT LEAD'S real notes + stage/dates and writes a 2-3 sentence
recap + last interaction + reactivation angle. **Grounding rules enforced:** no-notes →
deterministic "no notes logged — cold reactivation" WITHOUT calling the model (no backstory
possible); with-notes → notes-only, invent nothing, reference note dates. Cached per notes-hash
(regenerated only on note change). PII stays in the auth-gated mirror — never memory_facts, never
logged plaintext.

**Grounding audit (live, pre-ship):**
- With-notes → traceable: *Stephen Snow* — budget sensitivity, capital raise, CloudWaitress interest,
  2nd consult with Kalin (all from his "CLOSER BRIEFING — BRISKETS" note). *Giampiero* — three named
  restaurants + discovery call **dated 2026-01-14** + agency-transparency frustration (all in notes).
- **No-notes adversarial:** *Daniel Cini* (0 notes) → "No notes logged — cold reactivation" —
  **zero backstory invented.** ✓
- **Nonexistent lead:** "Zxqwerty Fakename" → "I don't have an open lead matching" — not invented. ✓
- **Honest degradation:** on a model timeout → "summary unavailable — retry", never a fabrication. ✓

## Phase 4 — the reactivation product (export-first)
- **CSV** (`/api/reactivation/export.csv`) — full fields for GHL smart-list work (name, business,
  email, phone, stage, bucket, value, days-stale, warmth, notes count, tracker status, where-left-off,
  angle).
- **Reactivation Brief PDF** (`/api/reactivation/brief.pdf`) — branded, ranked top-N with the grounded
  summary + suggested angle + contact details; the artifact Kalin's team works top-to-bottom. Sample
  generated for this report.
- Both contain contact PII **by design** (the team must reach the lead) — deliberate, auth-gated,
  and **audit-logged** to the forever archive (`collab.record_action`).
- **EDITH conversational** (both roles, voice + text): "which leads should we reactivate?" → ranked
  914 / $2.35M list; "where did we leave off with [lead]?" → grounded summary (entity-gated —
  offers closest matches, never invents a lead, disambiguates duplicates); "how many stale leads
  over $10k?" → 56 / $700k; "notes hygiene" → the stat.

## Phase 5 — triple-check + usability
- Reconciliation re-run post-build: matches GHL filters (table above).
- Grounding audit: passed (traceable summaries; no-notes = no backstory; nonexistent not invented).
- Join audit: email/name matches sampled; unmatched flagged not forced.
- Usability: the brief was generated on current data and eyeballed — ranked, scannable, each lead a
  self-contained card (who, stage journey, value, where it left off, the angle, contact info).
- Freshness: opps sync on the loop + resync; a note change re-summarizes on next generation
  (body-hash cache).

## PII & discipline
Lead contact data lives ONLY in the auth-gated mirror tables and deliberate exports — verified: no
`memory_facts` writes, no note/email/phone logged plaintext, exports audit-trailed. `today_sydney()`
throughout; GHL read-only; 529/429 backoff.

## Non-regression
Additive — new modules + endpoints + startup/ resync/ freshness hooks; no existing engine changed.
Stage-A: **374/375** (the 1 failure is the pre-existing `test_capacity_engine` MRR-drift test,
untouched by and unrelated to this work).
