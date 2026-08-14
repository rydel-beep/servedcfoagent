# OUTFLOW DIAGNOSIS — where BAS/tax lands in "expenses" (2026-08-13)

## Where the figures come from

- The waterfall's OpEx headline = Xero P&L `Total Operating Expenses`
  (xero_pull → snap.xero.operating_expenses).
- The monthly-burn breakdown (tiles/PDF/EDITH) = opex_pull.get_monthly_burn
  over the SAME P&L line items — classification is by account LABEL with
  **default → other_opex** for any unmapped account.
- The BAS layer (bas_engine) reads BALANCE-SHEET tax lines (GST / PAYG
  Withholdings Payable / Income Tax Payable) — correct and untouched.

## Where tax lands today (the skew, quantified from the books)

- **`Income Tax Expense` is a P&L OPERATING-EXPENSE account in this org's
  chart** — June 2026 carries **$26,553.75** on that line (live Xero P&L,
  1–30 Jun). June "Total Operating Expenses" reads **$95,861.08**; without
  the tax line it is **$69,307.33** — the blended figure overstates June
  OpEx by **38.3%**. July's line is $0.00 → the month-over-month "expense"
  comparison (June $95.9k → July $62.0k) is mostly a tax artifact.
- `opex_pull` has NO mapping for "income tax expense" → the $26.5k fell
  into **other_opex inside recurring burn** for any trailing window
  covering June. Same hole: **"Personal Expense"** ($129.48, July) is a
  P&L account that lands in other_opex — a personal lane exists in the
  bank feeds but not in the P&L classifier.
- The bank side corroborates: the CommBank **BAS/Tax #2353** account shows
  the remittance lumps (e.g. **2026-07-21 $13,513.35** — the Q4 settlement
  window; 2026-02-02 ATO $329) — GST/PAYG settlements that never touch the
  P&L (balance-sheet), i.e. the CASH-view tax events.
- **The last 2 tax events for the exhibit**: June's P&L instalment
  ($26,553.75, inflating June OpEx) and the 21-Jul BAS-account remittance
  ($13,513.35, the cash lump). Feb–May P&Ls carry no tax lines (verified).

## The real account names in play (this org's chart — enumerated, not assumed)

P&L expense accounts (trailing 6 months, live): Advertising · Bank Fees ·
Client Reporting Tools · Closer Commission · Consulting & Accounting ·
Contractors NO GST · Contractors WITH GST REMITTLY · Depreciation ·
**Income Tax Expense (TAX)** · Insurance · Motor Vehicle Expenses · Office
Expenses · **Personal Expense (PERSONAL)** · Refunds and Rebates Expense ·
Setter Commission · Stripe Fees · Subscriptions · Superannuation ·
Telephone & Internet · Travel - International · Travel - National · Wages
and Salaries · General Expenses. Balance-sheet tax accounts (bas_engine's
existing source): GST · PAYG Withholdings Payable · Income Tax Payable.

## The fix (classification, never hiding)

One classifier (`outflow_bands.py`) over the LEDGER'S OWN ACCOUNTS (the
account name from the chart is the primary signal — never transaction
descriptions/payee keywords): OPEX · TAX/STATUTORY · PERSONAL · FLAGGED
(unknown accounts — surfaced, owner-assignable, journaled) — bank-lane
TRANSFER stays where it lives (the bank feeds). Superannuation: the books
code it as an operating expense (employer super = a real payroll cost) →
**OPEX** — noted for Rydel's veto. Partition invariant: sum(bands) ==
Total Operating Expenses, per month, tested + nightly.
