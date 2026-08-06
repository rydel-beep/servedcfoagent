# BAS CALIBRATION REPORT — the official export vs the estimator (2026-08-06)

The lodged Activity Statement (THE 97 GROUP PTY LTD, period ending 30 Jun 2026,
**cash basis**, source: `~/Documents/Personal/BANK/THE 97 GROUP PTY LTD - Activity
Statement.pdf`) is **ground truth**. Everything below is calibrated against it.

## 1. The parsed export (Apr–Jun 2026)

| Line | Component | Official |
|---|---|---|
| G1 | Total sales (incl. GST) | $263,391 |
| 1A | GST on sales | $23,937 (audit detail 23,937.69) |
| 1B | GST on purchases | $4,149 (4,149.47) |
| — | **Net GST** | **$19,788** |
| W1 / W5 | Wages / **PAYGW withheld** | $84,133 / **$20,281** |
| T7 / 5A | **PAYG instalment** | **$1,450** |
| 8A / 8B | Owed / credit | $45,668 / $4,149 |
| **9** | **Payment** | **$41,519** — Rydel's "~$41k" confirmed |

## 2. Side-by-side vs the dashboard (pre-fix), every delta classified

| Item | Official | Dashboard was | Delta | Cause |
|---|---|---|---|---|
| Apr–Jun total | 41,519 | prior_obligation **41,138.08** | **−380.92 (−0.92%)** | source-path: ledger clearing-balance proxy (see §3) |
| Apr–Jun record | lodged lines | raw ledger balances in `bas:history` | components absent | S2 — official now the stored record |
| PAYGW /qtr | 20,281 actual | 7,033 modelled ($541/wk) | **−65%** | S2 — model blind to one-off runs (April run withheld $13,789) |
| Instalment | 1,450/qtr | "amount pending", excluded | −1,450 | S2 — config now set from evidence |
| Headline | — | Jul–Sep projection led the card; Apr–Jun a quiet row | — | S1 — hierarchy/labelling, not data absence |
| GST basis | Cash | Cash | — | ✓ no issue |

## 3. The residual, itemised as far as report-level evidence reaches

Multi-date balance-sheet trace (read-only Xero):

| Date | GST clearing | PAYGW Payable | Income Tax Payable |
|---|---|---|---|
| 31 Mar | 6,013.27 | 11,833.00 | 5,250.00 |
| 30 Apr | 13,617.22 | 27,786.00 (+541×4 + **13,789** one-off) | 5,250.00 |
| 31 May | −4,446.44 (Jan–Mar BAS paid 12 May: −28,082.25 incl. 5,250.25 instalment) | 29,950.00 | −0.25 |
| 30 Jun | **41,138.08** | **absent = 0** (EOFY sweep → GST clearing, incl. the 11,833 pre-April carry) | 20,753.50 (EOFY provision) |
| 6 Aug | **49,956.18** (= 41,138.08 + 8,818.10 Jul-QTD) | 2,132.00 (541×~4 ✓) | 20,716.50 |

The 30 Jun clearing balance is a **composite** (accrual GST + PAYGW sweep incl. prior
carry ± instalment postings) that landed within $381 of the official cash-basis total
partly by offsetting errors. Conclusion encoded in the engine: for lodged periods the
**official figures display**; the ledger figure survives only as the calibration
comparison; the −$380.92 residual is itemised on the card with its limit stated
(splitting further needs `accounting.transactions.read` — not granted — or the
accountant's journal).

## 4. Payment state (the cash-urgent finding)

**Apr–Jun $41,519 is UNPAID** as of 2026-08-06: the GST clearing account ROSE
41,138.08 → 49,956.18 (pure Jul-QTD accrual, no payment drop — contrast Jan–Mar's
visible −28,082.25 on 12 May). Due **25 Aug 2026** (agent program), 19 days out.
BAS #2353 set-aside account holds **$100,182.62 → covered** (buffer ≈ $26.8k after
the full spoken-for).

## 5. Fixes shipped

- **`bas:lodged`** — official lodged lines per quarter, provenance journaled
  (`scripts/ingest_bas_export.py --seed` = this export). Lodged figures display
  to the dollar; estimator figures kept alongside, never shown as the truth.
- **Config from evidence**: `instalment_amount = 1450` ("per lodged BAS Apr–Jun 2026
  (T7)"). PAYGW keeps the $541/wk recurring model (Jul-QTD ledger 2,132 = 541×~4
  confirms it) with the lodged actual shown as the band + calibration flag.
- **THE ATO POSITION** (the sharpened "owed"): owed_now = (a) lodged-but-unpaid +
  (b) QTD accrued; (c) projected remainder rides separately, labelled PROJECTION.
  Card leads with it; quarter named explicitly ("Jul–Sep QTD + projection"); last
  quarter + payment state one line beneath.
- **Set-aside** spoken-for = (a)+(b) + income-tax provision (labelled); free-cash
  split everywhere reflects it; forecast books (a) at 25 Aug and (b)+(c) at 25 Nov.
- **Salience**: outstanding lodged = standing item (92, never ages out, says OVERDUE
  past due); payment detection (clearing-drop signal) or "mark the Apr–Jun BAS as
  paid" auto-resolves it with the note.
- **Honesty score** (public, per quarter): total −0.92%; PAYGW −65% (component named
  in the hygiene flag). Tolerance = 2× median observed |error|, floor 5% — set from
  observation, not assumption. EDITH answers "how accurate are your BAS estimates?"
  with it verbatim.

## 6. Verification

Suite: **612 passed** (8 new BAS calibration tests: lodged precedence, residual
itemisation, position math to the cent, payment auto-resolve, standing salience,
honesty score + flags, EDITH answers). Live verification after deploy recorded in
the session note. Estimates-not-advice disclaimer unchanged on every surface;
read-only Xero (grep-tested); one engine (render paths still read `bas_engine` only).
