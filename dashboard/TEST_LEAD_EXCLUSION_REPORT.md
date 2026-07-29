# TEST-LEAD EXCLUSION & CLEAN SALES DATA — report

**Date:** 2026-07-29 (Sydney). Test entries (leads the team created while testing forms/funnels)
were contaminating sales metrics. They're now VOIDED from every metric via one classification layer
and one clean view — excluded, never deleted, fully auditable.

## Phase 0 — consumer inventory + confirmed exclusion list
**Consumers** (repoint checklist): lead counts/velocity + funnel (`leads_view`,
`range_unit_economics.cohort_funnel`/`_ltc_in_window`), reactivation + `/dashboard/leads`
(`ghl_mirror.read_opportunities`), roadmap channel-mix/CPL, salience new-lead/latest-lead, EDITH
lead answers, quarterly pack, payback. *(Forecasts read no lead data. The Team-Scorecard funnel is a
pre-aggregated sheet cell — can't row-filter; the row-level `cohort_funnel` used by the quarterly
pack IS cleaned. Stated, not faked.)*

**Scan → confirmed list: 19 strong, 0 borderline.** Tracker 17 of 1,291 (Jaspher/Test-Jas variants,
Carl Test Account, `Try` [test@ email], Curry Delights [rydel in email]); GHL 2 (rydel@ contact +
Curry Delights). **Rydel confirmed:** void all 19; Curry Delights = test; tokens rydel/jaspher/test.
No "Testaccio"-type false positives existed in the data.

## Phase 1 — the one classification layer
`test_leads.classify()` — the single engine:
- **STRONG (auto-void):** staff tokens (rydel/jaspher) anywhere in email/name; explicit GHL test tag;
  test-shaped email localpart (`test@`, `x+test@`); whole-word/leading "test" in the name.
- **BORDERLINE (default KEEP → review):** substring "test" inside a plausible token (Testaccio,
  attestation@) — never auto-voided.
- **OVERRIDES** (`mark test`/`mark real`, owner + Piolo): persisted in kv_store, **outrank the rules
  forever, and survive re-syncs**. Token rules are persisted + editable ("add X to test tokens" →
  confirmation loop, never auto-applied).

## Phase 2 — repoint every consumer (grep-proven)
One clean view per source, all consumers repointed:
- **Tracker:** `test_leads.clean_tracker_rows()` — used by `leads_view._rows`,
  `range_unit_economics._read_ltc_clean` (funnel + won-deal money), `reactivation._tracker_index`,
  `payback_reconciliation`.
- **GHL:** `ghl_mirror.read_opportunities(exclude_test=True)` — used by `reactivation` (5 reads) and
  `quarterly_roadmap._channel_mix`.
- **Grep-proof:** raw lead-table reads remain ONLY in the classifier, the clean wrappers, and the
  audit scan. No metric path bypasses the clean view.
- **Audit view** (`/api/test-lead-scan`, owner + Piolo): the voided list with rule provenance and a
  one-click mark-real. **EDITH:** "what's excluded as test?", "mark [lead] as test/real", "add [token]".

## Phase 3 — impact + consistency
- **Impact:** tracker 1,291 → 1,274 (−17); GHL reactivation pool 914 → 913 (Curry Delights removed);
  **Q2 2026 unaffected** (the test entries are 2025 + one 2026-07-27, none in Apr–Jun); trailing-30d
  −1 (the 2026-07-27 Jaspher Test that was firing the salience "new lead!" noise).
- A one-time **data-cleaning note** is written to the forever archive on confirmation (so future-you
  knows why counts changed).

## Phase 4 — self-improvement
- Auto-classification runs on every read via the clean views (rules + remembered overrides).
- **Borderline queue** = the audit view's borderline section (currently 0) — weak matches flow there,
  never auto-voided.
- Corrections feed back: overrides remembered; "add token" suggests rule additions (Rydel confirms).

## Phase 5 — triple-pass (evidence)
- **PASS 1 (data):** applied list == confirmed 19; classification unit tests (5) prove strong-void,
  borderline-keep (Testaccio kept), and **override outranks rules**; `clean_tracker_rows` drops the
  test row and keeps the borderline venue.
- **PASS 2 (functional):** reactivation clean live (**Curry Delights gone, no test names**);
  recent-leads clean (**no test/jaspher → salience won't fire**); audit view shows all 19
  (non-destructive); grep-proof shows zero metric bypass.
- **PASS 3 (consistency/regression):** Stage-A **386 passed / 1** (the pre-existing capacity-drift
  test, unrelated) + 5 new classification tests; the diff touches lead-metric paths only (isolation).

## Note
Fixed a real bug during the build: `classify()` read the rules + overrides from Postgres on *every
row*, so cleaning 1,291 tracker rows exhausted the DB pool (→ 500). Now the rule context is loaded
once per call and passed through — additive, isolated, and fast.
