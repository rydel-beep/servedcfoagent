# DATA SCRUTINY — Phase-0 diagnosis (2026-09-17, #150)

## The two shipped-or-not checks
- **OUTFLOW-TRUTH: SHIPPED** (08-14) — account-code-first bands, I-OUTFLOW
  invariant nightly. BUT two consumers never adopted it (the finding).
- **FORWARD-MRR two-layer: SHIPPED** (08-13) — the "committed" label's
  origin. Committed = contracted RECOGNITION (revenue). The tile said
  " committed" bare → Rydel read "$72,887.52" as a monthly COST.

## The two headline tiles' actual formulas
- **"$72,887.52"** = `client_health.current_mrr` — Σ active clients'
  current-month MRR (Health-gid tab, filtered, declarations applied).
  REVENUE. Now labelled "Committed MRR (revenue)" with a full drawer.
- **"$1.6k net"** = the Zone-1 forecast tile `Net $X/mo`
  (`forecasting_engine.cash_flow_13wk().net_weekly × 52/12` — an
  ASSUMPTION-DRIVEN PROJECTION, inflow + new-client cash − burn − tax
  set-aside), or its sibling the projection table's month-0 `Net`
  (committed+assumed − recurring burn). Neither was an actual; neither said
  so. Now: "Forecast net (projection)" + drawer reconciling against the
  THREE actual nets.

## Live plausible-lie bugs found (fixed this wave)
1. `financial_position` nets consumed BLENDED opex — tax/statutory +
   personal counted as operating cost (snapshot.py passed
   `operating_expenses`, not the banded figure). FIXED: banded OpEx +
   `opex_basis` note.
2. The waterfall banded the OpEx rows then re-blended tax inside its own
   "Net Profit" line. FIXED: both nets rendered, labelled.
3. `range_unit_economics` gated LTV:CAC behind the gross-margin read
   (Xero down → LTV:CAC null for no reason). FIXED: un-gated.
4. Two "cash collected" tiles from different sources, unlabelled
   (tracker cells vs Stripe). FIXED: both qualified.
5. `range_unit_economics` docstring said ROAS = cash; the code (Rydel-
   locked) computes CONTRACTED. Relabelled contract ROAS everywhere.

## The workbook tab map (runtime-enumerated; new tab = surfaced finding)
LTC book (7): README · Lead-to-Cash Tracker (1,517 rows) · Setter Payout
Log · Sheet1 (stub) · Team Scorecard · Setter Deep-Dive · Closer Payout &
KPI (not yet mirrored).
FINANCE book (8): MRR PROJECTION TO 2026 (manual model — never a source) ·
**Sheet5 (renewal ledger AUX)** · ACTUAL (cash grid, 60 rows) ·
**RECOGNIZED (revenue grid + THE RENEWAL LEDGER in cols E–K — never read
before this wave)** · SALARY · FIXED COSTS (unread tooling register) ·
Sheet6 (stub) · ACTUAL BACKUP (never a source).

## The renewal ledger the system never ingested
8 Renewed + 1 Pending-URGENT in RECOGNIZED's renewal columns: Noodle Asia
(08-18 → 02-18-27, $8,560), Bluebells (07-09 → MONTH-MONTH extension),
Cycho's, At Thai, Panini CO, Walkway to Ceylon, The Raama, Pottery Green
("URGENT: CONTACT NOW", term ended 06-02) + Pizzicotto (Pending, URGENT).
Sheet5 conflicts (At Thai Pending-vs-Renewed) surfaced, never merged.

## Cross-tab MRR truths (the recon table's inputs)
engine roster $72,887.52/38 · ACTUAL tab $107,196.01/45 · RECOGNIZED
$92,796.01/39 · RECOGNIZED footer $67,337.52 (≠ its own rows $76,437.52).
One truth = the engine roster (ruled derivation); every delta caused +
owned in `finance_tabs.cross_tab_recon()`.

## AR capability map
Stripe: charges (paginated, partial-marked) + subscriptions counts (the
past-due `data[]` was being discarded) + no invoices endpoint. Xero:
report scopes only — Invoices 401 (standing); the Balance-Sheet AR line IS
reachable and now rides the daily BAS pull as the anchor (`xero:ar_anchor`).
Expected-payments leg = the RECOGNIZED per-client grid (forward_mrr) +
renewal ledger. Invoice-level Xero AR = registered dependency (Rydel:
enable accounting.transactions.read + re-consent when wanted).
