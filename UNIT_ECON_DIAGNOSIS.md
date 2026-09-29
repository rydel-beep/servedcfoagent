# UNIT_ECON_DIAGNOSIS — LTV, CAC, LTGP:CAC (brief of 29 Sep 2026)

Status: **PHASE 0 — CODE HALF COMPLETE · DATA HALF BLOCKED.**
The live read-only probes (`railway ssh` on CFOagent) were refused by the
session's permission layer, so nothing below is measured from production yet.
Every verdict here is proven from the code path that renders the tile. Every
number that needs live data is marked **PENDING-LIVE**. No code changed.

---

## 1 · The renewal measurement: PENDING-LIVE

`csm_baselines.measure_renewal_rate()` (B1) exists and is the method the brief
asks for: a term-length-aware trailing-12-month cohort, a 30-day grace, a floor
share, ID-exact declarations, and ambiguous cases excluded but counted. Running it
needs the live snapshot, which was blocked.

What the code already shows about the number it produces:
- `value` = renewed ÷ (renewed + not-renewed) over clients **still in a dated
  store**. Churned clients with no dates can't be placed in the window, so
  they drop out of the denominator. The function's own `bound_note` says:
  *"treat the point value as an upper estimate"*.
- `lower_bound` puts every undated churned client into the denominator.
- "Renewed" = still Active past term end. The floor-share check is **not
  enforced** because prior-MRR history isn't stored (stated in `method`).
  Downgrades therefore count as renewals unless a downsell declaration exists.
- `confidence_pm` is `None` whenever the rate is exactly 100%. The witnessed
  "100%, lower 22.7%" therefore rendered with **no confidence interval**.

## 2 · D1 verdict: CONFIRMED (from code)

`finance_analysis._ltv_inputs()` line 120:
`renewal = b1["value"]`, which is the upper estimate, used as the point input.
`lower_bound` only goes into the provenance string. **A bound is being used as
the estimate.**

LTV formula as coded (`_ltv_of`, line 138):
`LTV = contract × completion% + contract × renewal%`
That is one renewal at the same contract value, with no horizon, no per-package
renewal term, and no discounting.

Reproducing the tile arithmetic:
- 6.87 × $4,911 = **$33,738.57 average LTV per close**
- ÷ (0.85 + 1.00) = **$18,237 average contract** across the 4 MTD closes
  (PENDING-LIVE: tie this to the register's contract values)
- The same four closes under the coded formula:
  - at the 22.7% lower bound: $18,237 × 1.077 = $19,641, which is **4.00×**
  - at 40% (the old placeholder): $18,237 × 1.25 = $22,796, which is **4.64×**

  The brief's $25.8k / $20.1k illustration uses an iterated-renewal model. The
  numbers above use the formula as it is actually coded.
- LTGP:CAC 4.48 ÷ 6.87 = **65.2% implied gross margin**, consistent with
  `pl_engine.gross_margin_for_ltgp()` on June→August. That ratio inherits
  D1 in full.

## 3 · D2 verdict: CONFIRMED-PROBABLE (label says placeholder; live confirm pending)

`measure_in_term_completion()` returns a value only for **currently active**
clients whose term has already ended, with `contract_value` and
`cash_collected` both present. Otherwise `_ltv_inputs` falls back to
`85.0` and labels it "placeholder 85% (source model)". The witnessed 85% is
that fallback.

There is also a design defect even when a value is measured: the cohort is
drawn from the **active** roster only. A client who churned mid-term (the
exact case completion exists to capture) is never in it. Completion is
survivorship-biased upward by construction.

## 4 · D3 verdict: CONFIRMED (from code)

`dashboard/exec_top.py:287–317`: the Today LTV:CAC and LTGP:CAC tiles read
`windows.cohort_month` from `unit_econ_view()`, which is **1st of the month →
today** on the activity clock. `trailing_90d` is computed in the same call
and never rendered on the tile. With n=4, one close moves CAC by about 25%
(4→5: ×0.8), and September spend is divided by closes whose leads came from
July and August.

## 5 · D4 verdict: PARTLY REFUTED, PARTLY CONFIRMED

- REFUTED as stated: LTV **is** per-close. `_ltv_of(c["contract"])` uses each
  close's own contract value, so a non-Growth-Pro close does move the average.
- CONFIRMED, the real defects:
  1. The package lookup (`by_pkg`) is **display only**. The package's term
     and renewal-term value never enter the maths. The renewal term is
     valued at the *signed* contract, so an upfront deal (e.g. Amoroso's
     $4,799) "renews" at $4,799 whatever the package actually renews at.
  2. `avg_ltv = ltv_total ÷ n` where `n` includes closes with **no contract
     value** (they add $0 to the numerator). Missing contracts silently
     dilute LTV rather than being named.
  3. There is no floor (signed-only) figure anywhere.
  4. There is no horizon cap. It isn't needed today because the series is one
     term, but it is needed as soon as renewal is iterated.

## 6 · D5: PENDING-LIVE

Needs Stripe (the $5,278.90 charge and its payer), the GHL opportunity and
Closed Deal Form, the tracker row, and the close register state for Amoroso
and Koji. All of these are behind the blocked read.

## 7 · CAC as rendered

`unit_econ_view()` → `sales_cost.build(w0, w1)` → `true_cac.per_close`:
ad spend (Meta, `meta_spend.spend_in_range`) + rulebook commissions (blank
tracker cell = ACCRUED) + set bounties + manager retainer + sales tooling
($2,132/mo pro-rata by `days/30.44`), ÷ register closes (activity clock).
Spend-only = Meta ÷ closes.
Witnessed: loaded $4,911, spend-only $2,636, so 4 × $2,636 = **$10,544 Meta
MTD** and 4 × ($4,911 − $2,636) = **$9,100 non-spend acquisition cost**.
(PENDING-LIVE: component split, and Meta cent-exact on closed days.)

## 8 · Cross-surface: FIVE unit-economics maths exist (violates "one engine")

| # | Engine | Formula | Closes from | CAC basis | Consumers |
|---|---|---|---|---|---|
| E1 | `finance_analysis.unit_econ_view` | contract×(completion+renewal) ÷ true CAC | close register | sales_cost TRUE CAC | Today LTV:CAC / LTGP:CAC tiles, unit-econ card, drawers |
| E2 | `range_unit_economics.unit_economics` | **avg contract** ÷ CAC (no completion, no renewal) | tracker won-marks (`_ltc_in_window`) | ad + tracker commission cells (empty since 20 Jul) | `hormozi_metrics` (30d) → snapshot, briefing PDF, quarterly PDF/pack, three_x_model, scenario_engine, EDITH range answers, anomaly_watch, payback_reconciliation, capacity_engine, attribution_engine |
| E3 | `sales_cost._ratios` | avg contract ÷ true CAC | register | TRUE CAC | SALES cost view |
| E4 | `compass_engine` ~L884 | mix × contract × package margin ÷ period CAC | modelled | modelled incl. headcount | Scale compass months |
| E5 | `compass_engine` ~L1600 | contract_mix ÷ cac | modelled | Plan cost card | Plan cost card |

So for the **same window** the estate shows at least three different LTV
definitions (1.85× contract, 1.0× contract, and mix×contract), two CAC
bases (tracker cells vs rulebook), and two close populations (tracker
won-marks vs register). E2 also runs on a **30-day** window while E1's tile is
**MTD**. Divergence is structural, not incidental.
(PENDING-LIVE: the per-surface rendered values for the table.)

## 9 · Register completeness (trailing 90d): PENDING-LIVE

`scripts/close_register_phase0.py` already does the four-source trace for the
first four September closes. It needs extending with Amoroso and a 90-day
sweep, then running on the box.

---

## Plan once live reads are permitted (the phase gate)

1. Run the B1 renewal + completion measurements on the box and record the
   point, n, CI, the ledger rows and the edge cases.
2. Run the register/Stripe/GHL/tracker trace for the five September closes
   plus the 90-day sweep.
3. Then build Parts 1–5:
   - one `unit_econ_engine` (expected + floor, horizon cap, per-package
     renewal term, measured point estimate with the band carried)
   - E2–E5 re-pointed to it, with a single-call-site guard test
   - tiles headlined on trailing 90d
   - register rows for Amoroso and Koji
   - EDITH drills and Scan 2 keys
