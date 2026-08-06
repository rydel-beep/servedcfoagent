# BAS & PAYG Prediction — the quarterly tax bill, seen coming

> **THE STANDING LINE (every surface):** estimates for cash planning — your
> accountant/BAS agent lodges the official statement. Never lodgement figures,
> never tax advice. EDITH's job is that the cash is sitting there when they lodge.

## PHASE 0 — CAPABILITY PROBE + TAX-CONFIG DISCOVERY (2026-08-06) — HARD STOP

### 1 · The capability table (probed live, read-only, via /debug/xero-probe)

| Xero read | status | meaning for the build |
|---|---|---|
| Reports/ProfitAndLoss | **200** | QTD revenue/spend for the cross-estimate + projection run-rate |
| Reports/BankSummary | **200** | the BAS #2353 physical set-aside balance |
| Reports/BalanceSheet | **200** | **THE LEDGER PATH**: GST · PAYG Withholdings Payable · Income Tax Payable · BAS/Tax #2353 account balances at any date |
| Organisation (settings) | **200** | GST basis + period read from Xero itself (below) |
| TaxRates | **200** | the org's active GST rate table |
| Invoices / BankTransactions (line-level tax) | 401 | per-transaction 1A/1B decomposition NOT available with current scopes |
| Reports/TrialBalance, Reports list | 401 | not granted |
| Payroll AU API | 401 | no Xero Payroll read — PAYGW comes from the BS account + the known $541/wk withholding (CLAUDE.md) |
| Activity Statement / lodged BAS history | **no public API endpoint exists** | official lodged figures are never readable by ANY scope — the official-report path is structurally closed; ledger-derived is THE path, labelled |

Minimal scope addition available (option, not assumed): `accounting.transactions.read`
would unlock line-level 1A/1B decomposition. NOT required for the build below.

### 2 · Config read FROM XERO (not assumed)
- **SalesTaxBasis: CASH** — GST reports on cash collected/paid.
- **SalesTaxPeriod: QUARTERLY1** — quarterly BAS.
- FY ends 30 June · AUD · PaysTax: true · org name "Served Marketing" (entity: THE 97 GROUP PTY LTD).
- Active GST rates: GST on Income 10% · GST on Expenses 10% · GST Free · BAS Excluded.

### 3 · Current-quarter reality read — BOTH WAYS (the calibration baseline)
BAS quarter Jul–Sep 2026, QTD = Jul 1 → Aug 6:

**(a) Ledger-derived (Balance Sheet GST account movement):**
GST liability $41,138.08 (Jun 30) → $49,956.18 (Aug 6) = **+$8,818.10 net GST accrued QTD**.

**(b) P&L cross-estimate (10% of GST-able flows):**
Revenue $103,192 ex-GST → 1A ≈ $10,319. Input credits from the opex mix ≈ $1.3–2.7k
(Advertising $10,197 → ~$1,020 credit; Contractors NO GST $17,490 → zero by name;
wages/super/international travel → zero; commissions/subscriptions uncertain without
line-level tax). **Net ≈ $7.6–9.0k QTD.**

**The two paths agree** — (a) $8,818 sits inside (b)'s range. Gap driver: line-level
tax coding invisible at current scopes (the honest limit, stated on-surface).

**Naive projection illustration (labelled MODELLED):** $8,818 over 37 days →
~$21.9k net GST for the full quarter at current run-rate, + PAYGW ~$7.0k
($541/wk × 13) → **a ~$29k BAS landing ~late Oct** (due date per lodgement answer below).

### 4 · The history read + ONE ANOMALY (named, not absorbed)
| date | GST acct | PAYGW payable | Income Tax payable | BAS #2353 (set-aside bank) |
|---|---|---|---|---|
| 2025-06-30 | 4,085 | — | 5,250 | 20,005 |
| 2025-09-30 | 9,147 | 1,104 | 5,250 | 43,592 |
| 2025-12-31 | 10,974 | 5,790 | 5,250 | 68,176 |
| 2026-03-31 | 6,013 | 11,833 | 5,250 | 78,635 |
| 2026-06-30 | **41,138** | **0** | **20,949** | 75,655 |
| 2026-08-06 | 49,956 | 2,132 | 20,912 | **100,183** |

**THE ANOMALY:** at 30 Jun 2026 (EOFY) the GST account jumped $6k → $41k, PAYGW
cleared to zero, and Income Tax Payable jumped $5.3k → $20.9k — the signature of
accountant EOFY journals (true-ups/provisions), not organic accrual. AND the GST
account has NOT dropped since 30 Jun — consistent with the **Apr–Jun BAS not yet
paid** (standard due date 28 Jul has passed; a BAS-agent extension would make it
~25-26 Aug). This is a question, not a conclusion.

**The set-aside picture TODAY:** ATO-related book liabilities ≈ **$73.0k**
(GST $49,956 + PAYGW $2,132 + Income Tax $20,912) vs the physical BAS #2353
account at **$100,183** — covered, ~$27k buffer.

### 5 · What only Rydel knows (the hard-stop questions)
1. Who lodges + due dates: BAS/tax agent (extended dates ~25th of the following
   second month) or self-lodged (28 Oct / 28 Feb / 28 Apr / 28 Jul)?
2. Is the $20,912 Income Tax Payable a PAYG INSTALMENT arrangement (method/amount)
   or the accountant's year-end provision only?
3. Payroll reality: PAYGW = Rydel's own wage only ($541/wk withheld), PH team =
   international contractors (no PAYGW) — confirm.
4. The estimates-not-advice framing + the Apr–Jun BAS status (lodged/paid? with
   the agent?).

## RYDEL'S RULINGS (2026-08-06)
1. **BAS agent lodges** — extended due dates (Jul–Sep → 25 Nov · Oct–Dec → 28 Feb ·
   Jan–Mar → 26 May · Apr–Jun → 25 Aug).
2. **On PAYG instalments** — amount pending his ATO notice; the line ships
   amount-pending ("set PAYG instalment to $X" records it, provenance stamped);
   NEVER invented into totals until set.
3. **PAYGW = his own wage only** ($541/wk withheld); PH team = international
   contractors, no withholding.
4. **Framing confirmed** — estimates for planning, the accountant lodges; the
   Apr–Jun BAS (~$41.1k on the ledger) is WITH THE AGENT (due ~25 Aug).

## THE BUILD (DECISIONS #123)
- **bas_engine.py — THE one engine.** refresh() (daily kv-stamped tick + boot tick,
  staggered across workers for the single-use Xero refresh token) pulls READ-ONLY:
  Balance Sheet tax lines at quarter-open & today, QTD P&L, the BAS #2353 bank
  balance — ONE token refresh per pull (xero_pull.pull_bas_inputs). Everything
  persists to kv `bas:estimate`; NO surface touches Xero on a request path.
- **The estimate:** GST QTD = ledger movement, with the PAYMENT-DROP assumption
  (account falls ≥50% below opening = prior BAS paid) applied openly — adjusted,
  flagged, salience-announced, never silent. A missing line on a present report
  reads 0 (probe-verified: Xero omits zero-balance accounts), a missing report
  reads unknown. Cross-check: P&L 10%-of-flows band (credit rules deterministic:
  "NO GST"/wages/super/international never carry credits; advertising/named-GST
  lines always; unknown lines only in the high bound). Ledger outside the band +
  tolerance → drift_flag → hygiene/salience, never absorbed.
- **PAYGW:** ledger balance when readable, $541/wk model as the labelled fallback.
  **Instalment:** active per Rydel, amount-pending until set (excluded from totals,
  the pending state rendered). **Prior obligation:** the quarter-close GST+PAYGW
  balance while unpaid, dated to the agent deadline; disappears when the payment
  drop is detected.
- **THE SET-ASIDE:** spoken-for = GST + PAYGW + Income Tax Payable book balances
  TODAY vs the physical BAS #2353 account (covered/short + buffer), and the split
  ("Cash $X · spoken for $Y → yours $Z") on the cash card + the BAS card via
  free_cash_view(). The forecast books each obligation in its DUE WEEK
  (tax_obligations_in_horizon; auto-disabled if a manual weekly_tax_setaside is
  set — no double count).
- **Salience:** T-14/T-3 due-date events (tightest band wins) with the
  covered/not-covered tail; payment-detected + drift anomalies — watermarked;
  `bas_due` → S1 in the feed and PROMOTED to ACTION in triage.
- **EDITH:** "what's our BAS looking like" (full picture) / "when's it due" (all
  obligations, agent dates) / "how much should I set aside" (spoken-for vs the
  BAS account) / "why is it higher" (the decomposition, caveats stated) / "set
  PAYG instalment to $X" / "refresh the BAS estimate" — wired at BOTH dispatch
  sites; the disclaimer in every answer (test-enforced).
- **Decomposition:** delta vs the prior quarter's ledger close; revenue-side
  projection shown; the residual named ("spend mix + timing"), the EOFY-journal
  caveat fires for Jul-start quarters; line-level 1A/1B split named as needing
  `accounting.transactions.read` (the optional scope, still not assumed).

## THE FIVE PASSES
- **P1 SOURCE TRUTH:** line-level hand-check is scope-blocked (named above) — the
  equivalent under current scopes: the two-way agreement (ledger $8,818 QTD inside
  the P&L band $7.6–9.0k, stored per-quarter in bas:calibration) + every balance
  traceable to a named Balance Sheet account. Calibration self-scores each quarter
  close from here on.
- **P2 PROJECTION HONESTY:** "MODELLED" tag on the card, "projected/modelled" in
  every payload + spoken answer; accrued_so_far ≠ amount test-enforced; the
  disclaimer greps green on card, split, salience line, and all EDITH answers.
- **P3 INTEGRATION:** set-aside to the cent (test); the forecast drops the exact
  amount in the due week (test, incl. the no-double-count guard); BAS quarter
  labels exact incl. the Oct–Dec year rollover (test).
- **P4 CONFIG FIDELITY:** adversarial tests — instalments off ⇒ zero instalment
  involvement; amount unset ⇒ excluded from totals; report-present-line-absent ⇒
  ledger 0, report-absent ⇒ labelled model; agent vs standard dates both exact.
- **P5 REGRESSION + E2E:** suite 609 green (12 new); read-only Xero grepped
  (no POST/PUT/DELETE in bas_engine); one-engine grepped (routes + forecast read
  bas_engine, no second BAS math); salience watermark ids stable.

## LIVE VERIFICATION (production, 2026-08-06, commit b485893)
- **The estimate (real books):** Jul–Sep 2026, day 37/92, cash-basis GST · QTD
  $8,818.10 net GST (ledger) inside the P&L band $7,289–$9,169 (two-way agreement
  GREEN, no drift flag) · projected $21,926 GST + $7,033 PAYGW → **~$28,959 due
  25 Nov (agent date)** · instalment renders amount-pending, excluded from totals.
- **The prior obligation:** Apr–Jun 2026 BAS **$41,138 due 25 Aug** — "with the
  agent — not yet paid per the ledger". Salience correctly silent today (19 days
  out); T-14 fires ~11 Aug, T-3 ~22 Aug, with the covered/not-covered tail.
- **THE SET-ASIDE:** spoken for **$72,999.86** (GST $49,956.18 + PAYGW $2,132.00 +
  income tax $20,911.68) vs the BAS #2353 account **$100,182.62** → covered,
  buffer $27,182.76. free_cash_view splits to the cent.
- **Forecast:** the $41,138 obligation lands in week 3 and the curve drops exactly
  ($193,393 + $10,772 net − $41,138 = $163,027 ✓); labelled with confidence.
- **EDITH (spoken, live kv):** full picture / due dates (both obligations, agent
  dates) / set-aside / why-moved (decomposition + the EOFY caveat + the scope
  limit named) — the disclaimer in every answer.
- Cold walkthrough verified via the API payloads + live handlers (dashboard-auth
  screenshots not capturable from this sandbox — stated, not skipped silently).

**RYDEL'S CHECK:** the ~$29k Jul–Sep projection + the $41.1k Apr–Jun bill against
your accountant's expectation — close, or the gap explained by the decomposition
(and remember the EOFY-journal caveat on the $41k figure).
