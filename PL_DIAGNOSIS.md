# WHERE THE 6.9% CAME FROM, AND WHAT AUGUST ACTUALLY LOOKED LIKE

**2026-09-24 · served-cfo-agent · diagnose first, evidence from production**

---

## THE AUGUST THREE-WAY RECONCILIATION (the headline)

Three ways of asking "what was August's revenue", three answers, every delta
explained:

| basis | figure (ex-GST) | what it is |
|---|---|---|
| **Xero recognised** | **$81,106.81** | Sales $81,060.67 + Interest $46.14, calendar August, pulled via `pull_pl_range` |
| **Stripe receipts** | **$61,197.82** | 28 succeeded charges, $67,317.60 gross ÷ 1.1 |
| **Contract-based** | **≈ $72,888 + one-offs** | committed MRR per client-month (current roster's figure; the engine computes August's own roster) |

**The Xero − Stripe delta ($19,862.99), decomposed with invoice evidence**
(10 August ACCREC invoices, read-only):

- **Invoiced revenue ≈ $20,550 ex-GST** ($22,605 incl-GST across 9 live
  invoices; one $8,305 invoice VOIDED and excluded). Of that, **$15,378 was
  still unpaid at month end** — The Leopard Deli $5,500, Kin Fun Keng Wong
  $4,708, Bar Elvina $5,170: this is the AR, recognised in August, cash in
  September or never.
- **The remaining ≈ $60,511 of the Sales line is NOT invoices.** It matches
  Stripe's August receipts ($61,198 ex-GST) to within ~$690 — payout-lag
  boundary noise.

**THE STRIPE-IN-XERO VERDICT**: Stripe sales ARE recognised in Xero — as
**bank deposits coded directly to the Sales account** when payouts are
reconciled, not as invoices. So the P&L's Sales line is a **hybrid basis**:
cash-on-payout for Stripe clients + accrual-on-invoice for bank-transfer
clients. Recognition of a Stripe charge trails the charge by the payout lag
(days); recognition of an invoice can precede cash by weeks. Neither is the
contract-based run-rate. This is precisely why three labelled bases exist
after this wave, with a bridge between them.

**Why recognised ($81.1k) sits ABOVE contracted MRR (~$72.9k)**: one-off
invoices (Tanny Puth $3,050 ex, Steph Wicks $2,200 ex, weekly Warners
invoices), plus AR raised for work whose cash never arrived in August.

---

## F1 · HOW THE 6.9% WAS PRODUCED

The snapshot carries a `profit` block from Xero. On the day of the failure it
held:

```
revenue: 49395.86 · net_profit: 3399.53
period: {"label": "trailing 30 days", "start": "2026-08-25", "end": "2026-09-24"}
cogs: null → gross_margin_pct: 100.0
```

That block is injected verbatim into EDITH's context as "PROFIT & LOSS".
**Net profit margin is not a metric any engine computes** — confirmed: the
registry has no entry (only `cash_net_mtd`, `operating_net_mtd`, `burn_net`);
no module computes a margin percentage. EDITH divided the two context numbers
herself: 3,399.53 ÷ 49,395.86 = **6.88% → "6.9% — $3,400 ÷ $49,396"**.
Nothing could stop her, because nothing owned the number.

Note what the rolling window did to the story: calendar August's net was
**+$20,518.70 on $81,107** (25.3%!), but the mid-month-to-mid-month slice
caught a light patch and read 6.9%. Same business, same books — the window
was the lie.

## F2 · THE LTGP MARGIN, CONFIRMED DOUBLE-COUNTED

`finance_analysis.unit_econ_view()`: margin = Xero `gross_margin_pct`, which
is **always 100%** (no COGS section in the chart of accounts — every cost
sits under Operating Expenses), so the ≥95% implausibility guard fires **every
time** and the value is always the fallback: **"FY26 contribution margin
42.9%"**. Contribution already subtracts advertising and commissions — the
acquisition costs that are CAC — so LTGP:CAC divided by CAC twice.

Correct Hormozi basis: delivery cost only. FY26: contractors no-GST $205,074
+ contractors with-GST $9,766 + client reporting tools $37,910 = **$252,750 =
36.2% of $698,599 → gross margin ≈ 63.8%**, LTGP:CAC ≈ **4.4×** (was 2.95×).
The simulator's "profit-vs-cost" uses the same contribution figure — same
defect, same fix.

## F3 · THE WINDOW AND THE LATE STRIPE BADGE

- The only P&L read was `_fetch_profit_and_loss` = today − 30 days: a rolling
  mid-month window, never a calendar period. `pull_pl_range` (explicit
  calendar windows) already exists — the quarterly review uses it — so the
  recognised basis is buildable today. The rolling read is retired as a
  citable source.
- **"STRIPE RECEIPTS IS LATE" — the cause is structural, not a broken job**:
  the freshness stamp for `stripe` is `snapshot.generated_at` ("arrives with
  the snapshot"), and the snapshot refreshes every ~90–120 minutes — against
  a **20-minute budget**. The contract is breached by design most of every
  cycle. Not the token, not rate limits, not pagination: a 2-hour job
  stamping a 20-minute promise. Fix: a lightweight receipts pull with its own
  stamp riding the 5-minute freshness tick.

## WHAT XERO GIVES US TO BUILD ON

Account-level lines per calendar window (13 opex accounts in August, named),
report scopes only (`profitandloss / banksummary / balancesheet .read` — no
transactions scope; invoice-level detail in this diagnosis came through the
separately-authorised Xero MCP, read-only). August's 13 accounts map onto the
ladder cleanly; `Contractors NO GST` is the one mixed account (delivery
subcontractors + team payroll via Wise) — split by config with the FY26
review's basis as the draft, flagged for the owner's confirmation.
