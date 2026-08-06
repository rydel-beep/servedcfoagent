# Full-Stack Data Integrity — deployed-state, phantom census, resolution doctrine

## PHASE 0 (2026-08-06) — AWAITING RYDEL'S AUTO-FIX RULE CONFIRMATION

### 1 · Deployed-state check FIRST (the "don't fix twice" gate)
Local HEAD `cfd1822` == LIVE /health commit `cfd1822362d1`, status ok. Every recent
fix is code-present AND running in production:

| fix | code | live |
|---|---|---|
| one-clock basis toggle (#120) | PRESENT | YES |
| runtime invariants I1-I7 (#120) | PRESENT | YES |
| identity re-key + ambiguous quarantine (#119) | PRESENT | YES |
| close authority = tracker Close Date (#118) | PRESENT | YES |
| honest TOTAL-closes headline (#120) | PRESENT | YES |

**Verdict: the symptoms in this brief describe the PRE-dc451d7 board. They are named
as already-fixed — nothing here is re-fixed twice.**

### 2 · Phantom-close census (deployed engine, both clocks, 30/60/90d)
integrity_error rows: **0** in all six basis×window combinations. Unannotated
closes>leads rows: **0**. Census total current phantoms: **0**. Cause histogram is
empty — the historical causes (mixed clocks; the three named phantoms Tesla Zhong /
Glen Fitzgerald / Tony Thai) were cured by #120 and verified again today.

### 3 · Identity spine
The brief's suspected asymmetry (closes joining deal→contact→ad while leads join
cohort→ad) **does not exist in the shipped engine**: leads AND closes attribute
through the same memoized `lead_bucket_key` (tracker row → contact → ad id). Under
cohort, closes are structurally ⊆ the cohort (invariant I2); under activity,
earlier-lead closes carry the ↤N annotation. A close can only render under a
creative with its lead — the hard rule already holds, test-enforced.

### 4 · Standing data debt (visible, owned, not phantom):
- 19 blank Close Dates + 5 blank Input Dates (Piolo's queue, self-retiring)
- GHL closed-won lane dead 90d+ (sales-team same-day stage rule printed)
- Nirosha duplicate won row (source fix in Piolo's queue)

### 5 · PROPOSED RESOLUTION DOCTRINE (the gate — confirm before any of it runs)

**AUTO-FIX (derives, never invents — applies silently, logs every application):**
- A1 Normalization: trim/case/whitespace on names & ids before matching (no meaning change).
- A2 Exact-id re-key: renamed creative with the same ad id stays one row (already live, #119).
- A3 Confirmed-alias reuse: an alias Rydel has ALREADY confirmed once (e.g. Allan
  Thai → 'phoodle Vietnamese eatery') auto-applies on recurrence. New aliases still ask.
- A4 Basis annotation: earlier-lead closes annotated ↤N on the activity clock (already live).
- A5 Self-retiring flags: a hygiene item whose underlying fact is fixed at source
  clears itself on next sync.

**PROPOSED-FIX (card with evidence, one-tap confirm, nothing applied until tapped):**
- P1 Blank Close Date where GHL stage-move or Stripe first-payment carries a
  candidate date → card shows the candidate + source; tracker stays authority, the
  card only PROPOSES what a human types into it.
- P2 Near-miss name match (fuzzy ≥ high confidence) between tracker and GHL contact
  → propose the link, never auto-join.

**HUMAN-FIX (routed, named owner, no candidate exists anywhere):**
- H1 Blank dates with no cross-system candidate → Piolo queue (already routed).
- H2 Ambiguous identity (non-unique name, no id) → stays quarantined in
  `__ambiguous__`, listed with candidates, never assigned.

**Hard line: no rule ever writes to the tracker, GHL, or Stripe. Auto-fixes change
only how the engine reads/labels; all source corrections remain human-applied.**

## RYDEL'S RULINGS + THE BUILD (2026-08-06)
A1-A5 confirmed · P1/P2 + H1/H2 confirmed. Implemented per DECISIONS #122:
- **resolution.py** — `propose_fixes()` rides close_integrity's daily refresh
  (read-only). P1: each blank-Close-Date won row is matched (A1-normalized, email
  first then name) against GHL closed-won stage-move dates (mirror, zero API) and
  Stripe first-payment dates (read-only key, 365d lookback); a hit becomes a card
  {candidate date, source, instruction} — the instruction says what to TYPE into the
  tracker; the engine never writes it. P2: a won row whose email matched no GHL
  contact but whose name matches exactly ONE contact → a link proposal, confirmed in
  chat, sources untouched. No candidate → the card says so and the row stays in
  Piolo's queue (H1). Cards live in kv `integrity:proposed_fixes`, rebuilt per
  refresh — a blank filled at source stops generating its card (A5 self-retire).
- **The application log** — kv `integrity:autofix_log` (capped 200): alias LEARNS
  (the self-improvement loop: a confirmed fix becomes a standing rule) and alias
  REUSES (A3, once per reconcile run, payers named) now log themselves. EDITH:
  "what did you auto-fix?" reads it; "any proposed fixes?" reads the cards.
- **Test-enforced hard line** — test_no_write_paths_exist greps resolution.py for
  write primitives (update_cell/batch_update/append_row/requests.post/…): none may
  ever appear.

## LIVE VERIFICATION (production data, 2026-08-06)
**15 of 19** blank Close Dates got derived candidates with named sources
(9 GHL stage-move · 6 Stripe first-payment — e.g. Terry Yu → 2025-09-25 from GHL,
Ella Ponce → 2026-02-18 from Stripe); **1 P2** name link (Fausto Falchi, exact
unique match); **4 H1** rows have no candidate anywhere (Vipin, Dj, Hiep Nguyen,
John Tamayo) and stay with Piolo. Census re-confirmed clean post-build. Suite 597.
