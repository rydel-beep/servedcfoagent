# SERVED CFO AGENT — Claude Project Instructions

## What this project is

The served-cfo-agent is a standalone CFO data engine for Served Marketing. It pulls
financial data from Stripe, GHL, Google Sheets, and Xero, computes Hormozi-style unit
economics, and exposes them via REST endpoints on Railway. Its job is to be the honest
mirror of the business — surfacing what's actually happening without flattering or
distorting.

All work stays inside `served-cfo-agent/`. Never touch sibling repos.

## Core engineering rules

- `today_sydney()` and `now_sydney()` everywhere — the business runs on AEST/AEDT.
- Never fabricate numbers. Source failure: value = null, add entry to `degraded[]`.
- `ok: true` only when `degraded[]` is empty.
- Triple-check validation: row-count sanity + cross-source range band + reconciliation
  against any pre-computed cell.
- Minimum viable diffs. Show diffs before committing.
- Real names allowed in CLAUDE.md and internal docs only. NEVER in snapshot JSON or
  history files (aggregate-only).
- Diagnose first, fix second. Phase gates between investigation and implementation.

## Xero account identification (parser discipline)

Identify a Xero account by its explicit `account_id` and `account_name` from the API
response. Never infer from payee, amount, description, or context. A historical bug
misidentified "Contractors NO GST" entries as "Wages and Salaries" entries by inference;
a regression test in `tests/test_xero_pull.py` now prevents this.

If the categoriser assigns a transaction to an account-named bucket, the transaction's
`account_name` must equal that account's name exactly. No exceptions.

## People at Served Marketing

The agent must never conflate these people. Match by exact name; flag close matches.

| Name | Role | Cost type | Primary source of truth |
|---|---|---|---|
| Rydel Limjoco | Founder/CEO (only official employee) | Recurring gross pay ($2,241/wk, ~$9,704/mo) + occasional bonuses | Wages and Salaries (gross recurring) + Wages Payable (bonus & net clearing) |
| Kalin Long | Closer (sales) | Performance commission | Lead-to-Cash tracker col 40 |
| Coby Goldner | Setter (sales) | Performance commission | Lead-to-Cash tracker col 39 |
| Maran [surname TBC] | Setter (sales) | Performance commission | Lead-to-Cash tracker col 39 |
| Colby Shaw | Videographer / subcontractor | Variable COGS | Xero Contractors NO GST, filtered by payee "Colby Shaw" only |
| Rictor Kniehl Limjoco | Rydel's brother — personal loan repayment | IGNORE in business cost | n/a |

**Critical:** Coby Goldner (setter) ≠ Colby Shaw (videographer). Spellings "Coby" / "Cobi" /
"Colby Goldner" -> Coby the setter. "Colby Shaw" or "Shaw" -> the videographer. Flag any
ambiguous match for Rydel before categorising.

Maran's surname pending confirmation from Lead-to-Cash tracker or Xero contacts.

## How owner pay works (Australian payroll mechanics, lock this in)

Recurring owner pay is a normal payroll journal with three legs:
- **DR Wages and Salaries** (P&L expense) for GROSS amount — this is the business cost
- **CR Wages Payable** (BS liability) for NET amount — clearing account until bank pays out
- **CR PAYG Payable** (BS liability) for tax withheld — later remitted to ATO via BAS

Recurring owner pay legitimately LIVES in Wages and Salaries as gross. It is not a
miscoding. The Wages Payable side is a clearing account, not the home of recurring pay.

Worked example — Rydel's pay, monthly:
- Gross (Wages and Salaries debit, business cost): $2,241/wk x 4.33 = $9,704/mo
- Net (cleared through Wages Payable to bank): $1,700/wk x 4.33 = $7,361/mo
- PAYG withheld: $541/wk x 4.33 = $2,343/mo
- Reconciliation: $7,361 + $2,343 = $9,704 ✓

Business cost = gross = $9,704/mo. This is what `true_team_cost` uses.

**Owner bonuses are different.** Lumpy bonuses should NOT run through Wages and Salaries
as P&L expense. They are balance-sheet-side journals (Wages Payable as the destination).
In April, $57,241 above recurring gross was miscoded into Wages and Salaries (includes
owner bonus and possibly other items — full composition pending April GL from Raymond).
Piolo fixed the coding going forward as of 2026-05-31. Historical April data (~$66k Wages)
still includes the excess and won't be retroactively cleaned. Any trailing-30d window straddling the fix date will produce hybrid
numbers until the window fully clears pre-fix entries (estimated clean from late June 2026).

## True team cost

Recurring monthly cost of running the team. Used in op-efficiency, runway, hiring capacity,
"what does it cost to keep the lights on."

**Includes (monthly):**
- Core team payroll via Wise (coded in Contractors NO GST) — SALARY tab is source of
  truth, $18,891/mo aggregate
- Owner recurring pay GROSS (Wages and Salaries) — $9,704/mo
- Super baseline — $1,076/mo

**Total true team cost: ~$29,671/mo**

**Excludes:**
- Owner lump-sum bonuses (lumpy, balance-sheet-side journal, visible in cashflow not in
  recurring cost)
- Sales commissions to Kalin / Coby / Maran (variable, in CAC math, not team cost). In
  dedicated "Closer Commission" and "Setter Commission" P&L accounts per Piolo's
  2026-05-30 recode
- Subcontractor payments for client delivery e.g. Colby Shaw (variable COGS in Contractors
  NO GST, filtered by payee)
- Catch-up super payments (lumpy quarterly true-ups — exclude from run-rate projections)
- Personal/family loan repayments (Rictor — not business cost)
- Inter-account transfers (GST reserve mirror entries — not expenses)
- PAYG withholding (a flow inside gross pay, not additional cost)

## Xero account structure

- **Wages and Salaries (P&L expense)** — Recurring gross pay for Rydel. Should NOT contain
  sales commissions (moved to Closer/Setter Commission accounts), should NOT contain
  bonuses (now go to Wages Payable). Pre-Piolo-fix historical periods may contain miscoded
  bonus; do not retroactively reclean.
  April 2026 historical example: $66,205 = 4 weeks x $2,241 recurring gross ($8,964) +
  $57,241 excess (includes miscoded bonus; full composition unknown without April GL detail
  still pending Raymond — the $38k in bank feeds was two specific payments of which only
  $20k fell in April, so additional items exist in the $57,241).
- **Wages Payable (BS liability)** — Net pay clearing account for recurring payroll;
  destination for owner bonuses post-2026-05-31 fix.
- **Closer Commission (P&L OpEx)** — Kalin's commission, retroactively recoded back to at
  least March 2026.
- **Setter Commission (P&L OpEx)** — Coby and Maran's commissions, retroactively recoded
  back to at least March 2026.
- **Contractors NO GST (P&L)** — Mixed account. Contains both (a) core team payroll via
  Wise [belongs in true_team_cost] and (b) actual subcontractors for client delivery e.g.
  Colby Shaw [belongs in COGS]. Split by payee using the People table. Unknown payees flag
  for Rydel to classify.
- **Superannuation** — Recurring contributions ~$1,076/mo. Catch-up spikes (e.g. April 2026
  $7,945, May Superchoice $6,869) excluded from forward run-rate projections.
- **PAYG Payable (BS liability)** — Tax withheld pending remittance to ATO via BAS.

## GST reserve mirror entries

Many Xero transactions appear identically in both a transaction account and the BAS
account. These are inter-account transfers for GST reserve — not duplicates, not bank rule
artifacts, not expenses. Net them out of any expense calculation.

## Source-of-truth precedence

When sources conflict, the primary source wins. Secondary sources are cross-references.

| Concept | Primary | Secondary / cross-ref |
|---|---|---|
| Fixed team payroll | SALARY tab | Xero Contractors NO GST (Wise to team) |
| Owner recurring pay | Xero Wages and Salaries (gross) | Xero Wages Payable (net leg) |
| Owner bonus | Xero Wages Payable (post-fix) | — |
| Sales commission | Lead-to-Cash tracker cols 39, 40 | Xero Closer/Setter Commission accounts |
| Subcontractor COGS | Xero Contractors NO GST, filtered by payee | — |
| Total cash outflow | Xero (bank truth) | — |
| Ad spend | Ad Monitor (Meta + Google APIs) when live | Xero Advertising line (fallback) |
| Revenue (cash) | Stripe | — |
| Revenue (P&L recognized) | Xero | — |

**Stripe revenue and Xero revenue are NEVER summed.** Same money, different views. Show
separately, labelled.

## Trailing-window honesty

When reporting trailing-30d (or 90d) totals, the window may straddle structural fixes in
the books. Specifically: any window before late June 2026 that includes April 2026 will
contain the pre-fix $57k excess (bonus + unidentified items) in Wages. The agent should
flag this in `inputs_used` when
producing wages-derived metrics, so reads aren't misinterpreted as ongoing run-rate.

## Client list derivation (never hardcode)

The active-client list is DERIVED on every snapshot from source systems, never hardcoded.
An active client requires presence in the Health tab (Finance Sheet) with Active/Web Sub
status and non-churned status. LTC tracker Won deals are cross-referenced to add contract
values, cash collected, and to catch new signings not yet in the Health tab.

Stripe MCP provides aggregate MRR only (no per-customer data), so it serves as a validation
cross-check, not a per-client source.

Disagreements between sources are surfaced in `active_clients.discrepancies`, never silently
resolved. Known-churned clients (Advocate, Vietnamese Mint, Gloria Jean's, 1st Edition Bar,
Johnnies Fitzroy, Hanmades, Nonnas, Asian Streat, Riverloop, V Noodle, Bunni Beez) are
excluded even if a lingering payment or old Won record appears — flag if a churned client
shows new activity.

Never reintroduce a hardcoded client list; it is the known cause of staleness. The module
`active_clients.py` owns this logic. Legacy Health tab clients (predating the LTC tracker)
are treated as active with `sources_agree: "legacy"`.

## Why this matters

A confidently wrong number is worse than no number. The agent's job is to be the honest
mirror — applying these rules to compute clean figures, surfacing categorisation issues as
data-quality flags so the bookkeeper can fix at source.

This document is authoritative. If a future build or investigation appears to contradict
something here, the contradiction itself is the finding — pause and resolve, don't paper
over.
