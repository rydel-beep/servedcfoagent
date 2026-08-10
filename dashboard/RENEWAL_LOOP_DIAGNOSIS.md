# RENEWAL & CHURN TRUTH LOOP — DIAGNOSIS (Phase 1, 2026-08-10)

## Phase 0 · Access + existing machinery (gate: PASSED)

**The MRR contract sheet = the Finance Sheet's Health tab** (sheet
`FINANCE_SHEET_CONFIG.sheet_id`, gid 1407663952) — already the one engine's
client/MRR/status source, readable TODAY via the existing paths (Postgres
sheet_mirror first, public gviz/CSV export fallback; live probe 200, 131 raw
rows). No new tokens needed. No Drive OAuth exists → freshness = content hash
+ mirror sync stamp, not Drive modified-time.

**Existing machinery this feature EXTENDS (found, not duplicated):**
- `client_overrides.py` — THE confirmation-gated client write-back (Rydel-
  confirmed 2026-07-03): churn/downgrade declarations as a READ-LAYER over the
  sheet, pending-token confirm loop, undo, audit table, and
  `reconcile_churned()` — the convergence primitive (sheet catches up → the
  override marks reconciled). Missing: RENEWED declarations, a dashboard UI
  (chat-only today), scan/diff/freshness, conflict lanes, queue integration.
- `collab.queue()` — Piolo's queue = action-feed flags (categories
  reconciliation/data_quality) overlaid with resolve/verify state. Pending-
  sheet declarations must become ACTION-FEED items to land here; convergence
  auto-clears because the flag stops generating (A5) and collab marks it
  verified. (Today the pending list is chat-query-only — NOT in the feed.)
- Renewal Watch + Churn Risk: built inside `finance_sheets_pull.
  pull_client_health()` (at_risk ≤60d by End Date; renewal_watch from month 4
  of term) — already applies churn/downgrade overrides. Cards render in
  dashboard.js (`renderChurnRisk`, ~line 1989).
- `mrr_snapshot.take_snapshot()` — daily per-client MRR row read from snapshot
  client_health (post-override) → declarations flow into snapshots via the one
  engine; the declare path must force-refresh today's row.
- Owner gating: `dashboard/auth.is_owner()` exists (rydel=owner, piolo=coo).

## D1 · Real schema (probed live)

Header row 0: `Client Name · Status · Package Type · Service Term · Start
Date · End Date · Contract Value · Monthly Recognized Revenue · <blank> ·
January 2026 · February 2026 · …` (month recognition columns rightward). Dates are
MM-DD-YYYY. 131 raw rows; 57 client rows; footer/TOTAL rows present.
Status vocabulary observed: Active / Finished (+ blanks on spacer rows).

**Human-edit hazards (live examples):** a row with End Date BEFORE Start Date
(phoodle: start 07-21-2026, end 01-21-2026 — the known typo); blank spacer
column H; TOTAL/footer rows; month columns appended over time (layout grows
rightward). ⇒ the scan parses HEADER-ANCHORED with a header checksum; any
missing/renamed anchor column fails LOUD, zero row reads.

## D2 · Linkage (computed live)

Roster (dashboard client set): **40** · Sheet client rows: **57** (40 Active +
17 non-Active history) · Active↔roster match: **40/40 both directions, 100%,
0 duplicate normalized names**. Linkage is NAME-NORMALIZED — the sheet has no
ID column, so sheet-row↔client links are name-anchored by construction; the
scan carries this as an honesty note, quarantines any future duplicate-norm
collision (never assigns), and surfaces unmatched rows in the UNLINKED lane.
Type-ahead selection binds to the EXISTING roster entry (the closest thing to
an ID this surface has) — free text matching nothing = "not a known client".

## D3 · Baseline status derivation + where declarations slot in

Status/MRR truth today: Health tab row (Status/End Date/month columns) →
`pull_client_health()` → overrides applied inline (churn drops row, downgrade
lowers MRR) → snapshot.client_health → EVERY consumer (MRR headline, Renewal
Watch, Churn Risk, voice counts, quarterly, mrr_snapshots). The declaration
layer slots into the SAME override apply-step — a RENEWED declaration
overrides `contract_end` (+optional MRR) before at_risk/renewal_watch
membership is computed. Zero parallel math anywhere; grep confirms the only
status/MRR computation sites are pull_client_health + client_overrides.apply.

## Build plan deltas (vs mission spec)
- Freshness = content-hash (no Drive scope) — allowed fallback.
- "Piolo queue item" = action-feed item in a queue-visible category (the
  existing queue), auto-retiring on convergence.
- RENEWED reuses the client_overrides table: change_type='renewal',
  effective_date carries the NEW contract-end/renewal date, new_mrr optional.
- Scan runs server-side in one request (~1–3s: one CSV + diff); the button is
  async client-side with progress — honest-loading rules apply.

## D1 addendum (build-time proof of the drift guard)
The first live scan TRIPPED the schema guard: the diagnosis probe had truncated
the header to "Monthly Recognized" (display cut at 18 chars); the real column is
"Monthly Recognized Revenue". The guard refused to read a single row until the
anchor was corrected — exactly the failure mode it exists for, demonstrated
against the builder's own wrong assumption on day one.
