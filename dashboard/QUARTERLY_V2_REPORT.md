# QUARTERLY REVIEW v2 — report

**Date:** 2026-07-27 (Sydney). The Q2 2026 PDF had verbatim integrity but a line-by-line audit found
5 defects + 6 gaps. All fixed at root; a report linter now gates this class of defect; the marketing
roadmap and self-improvement loop are built. The regenerated Q2 2026 PDF (8 pages) is the acceptance
artifact.

## The five defects — root causes + fixes
| | Root cause | Fix |
|---|---|---|
| **D1** ratio as "$5" | `_comparison_table` guessed "money" by substring — "CAC" ∈ "LTGP:CAC" | `quarterly_format.py` type registry (currency/ratio/percent/count); LTGP:CAC renders **4.51x** |
| **D2** blank column | targets "This quarter" cell hardcoded `""` | `targets_current` bound from the pack → shows **$253,200 / $759,600**, **16 / 48** |
| **D3** contradiction | volume-path flag computed twice (ratio vs economics) | **one flag engine** — both read the same `fundable_flag` (PLAUSIBLE everywhere) |
| **D4** degenerate churn | `base_mrr×(M−2)` = total MRR at M=3, printed without data | **suppressed** → "Not computable — churn MRR isn't measured for this window" |
| **D5** fragment | `cac_assumption` string started mid-sentence | **"CAC is held constant at $2,718 — …"** (subject restored) |

## The report linter (`quarterly_linter.py`)
Runs after the pack renders, before the PDF finalises. Each defect is a regression rule:
- **Unit consistency (D1)**, **completeness (D2)**, **contradictions (D3)**, **bounds/degeneracy (D4)**
  → hard-fail generation. **Language/fragments (D5)** → warn + log.
- 8 adversarial tests: reintroduce each defect → the linter catches it. *(It earned its keep during the
  build — it caught an over-broad D1 rule and the opex-delta verbatim issue before they could ship.)*
- Verbatim validator still enforced first (numbers are REAL); the linter adds "numbers make SENSE".
- Findings logged to the linter-trend for the self-improvement loop.

## The insight layer + opex bridge
- **G1 — the loss is named and explained.** Exec summary now: *"…closed 16 deals for $253,200… But the
  P&L landed at −$2,112 net (a loss) — a −106% swing QoQ. The tension: unit economics stayed healthy
  at 4.51x LTGP:CAC, yet the quarter ran a loss — because efficiency degraded with scale (ad spend
  +53%, CAC +23%, ROAS −26%) on top of opex growth."*
- **G2 — the opex bridge** answers "where did the profit go" with real Xero per-line QoQ: **Wages and
  Salaries +$58,090, Closer Commission +$21,025, Advertising +$7,568, Superannuation +$6,971** — the
  swing accounted for line by line. (Deltas computed in the review so they stay verbatim-safe.)
- **G4 — per-section takeaways + the lead-lag warning**: closes trail leads ~1–2 months, so month-end
  lead velocity is a leading indicator. The report auto-fires: *"[!] Jun 2026 leads 89 (−18% MoM vs
  May's 109) — foreshadows next-quarter close risk. Refill the top of funnel now."*

## The marketing roadmap (G5) — a plan, not just targets
- **Channel decomposition** (GHL lead-source, ~98% filled): **86.8% Meta/Facebook**, 7.4% landing page, rest misc.
- **The ramp** — required leads as a graduated monthly build (not flat): **253 → 307 → 343** with the
  spend schedule per month at current CPL.
- **CPL-drift band** — CPL is not held flat silently: **+0% / +15% / +30%** scenarios, each with the
  spend, CAC-at-scale, LTGP:CAC consequence and above-floor flag (adjustable knob).
- **Creative cadence** implication (labelled assumption), **weekly checkpoints** with on-track
  thresholds (CPL, ramp line, lead→set, set→show, LTGP:CAC, payroll:MRR), and a **sequenced dated Q3
  action list** (start hires week 1, lift Meta spend to the ramp, instrument churn now).

## Data plumbing (G3, G6)
- **MRR snapshotting started** (`mrr_snapshot.py`) — a durable monthly/quarter-boundary snapshot of
  roster MRR, taken on boot. Full opening→closing bridges become available from the first snapshot
  date (stated in the report). **Churn-MRR derivation** from the client write-back audit is wired into
  the bridge; until events accrue, the churn math honestly reads "not computable" (retiring D4's
  fallback with real data over time).
- **Benchmark provenance (G6)**: the capacity math now prints *"clients-per-hire (12) and hire lead
  time (4wk) set by Rydel 2026-07-27; payroll:MRR gate 40% and LTGP:CAC floor 3.0x are standing
  thresholds."* (Both were unconfirmed assumptions — Rydel confirmed 12 and changed lead time 6→4wk.)
- The 16/16 closes→MRR smart matcher is staged (bridge matches 14/16 by name today; the 3 misses are
  business-vs-contact name mismatches, resolved as the write-back/roster join is smart-matched).

## Self-improvement loop
- `quarterly_model_store.py` **persists each quarter's 3x model** and **grades the prior quarter**
  against actuals (per lever: required vs delivered, achieved %). The grading section renders from the
  next generation onward (Q2's model is now saved; Q3's report will show "Q2's plan vs what happened").
- **Assumption provenance** surfaced; **linter-trend** logged per generation (recurring findings → build items).

## Verify
- Regenerated Q2 2026 PDF (8 pages): all D1-D5 fixed in render; exec names the loss + tension; opex
  bridge accounts for the swing; lead-lag warning present; roadmap complete; provenance shown.
- Linter passes (and catches each reintroduced defect — 8 tests). Verbatim still enforced.
- Non-regression: **386 passed / 1 failed** (the pre-existing `test_capacity_engine` MRR-drift test,
  unrelated). Quarterly v1 pipeline, one-engine, GHL mirror, roles, archive all intact.
