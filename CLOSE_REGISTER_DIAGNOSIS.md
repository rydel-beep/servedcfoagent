# WHY /ADS SAYS 1 WHEN FOUR DEALS CLOSED — AND WHY EVERY SURFACE HAS ITS OWN ANSWER

**2026-09-24 · served-cfo-agent · Phase 0 of the ONE CLOSE REGISTER build.
Measured on production (read-only probe `scripts/close_register_phase0.py`,
run on the box 12:39 AEST), not argued from the code.**

---

## THE MATRIX — every surface, asked its own code path, same day

| surface | code path | source it reads | clock | 30d activity | 30d cohort | all-time | Orlando | Harman | William | Koji |
|---|---|---|---|---|---|---|---|---|---|---|
| **/ads headline + grid** | `dashboard/ads.py:113` → `attribution_engine.compute` | tracker rows + sanctioned derived dates — **nothing else** | toggle, **default cohort** | 2 | **1 ← the number Rydel saw** | 61 | ✔ activity only | ✘ **cannot appear** | ✘ **cannot appear** | ✔ |
| **travelling** | `travelling.py:311` → `FA._closes_union` | engine ∪ gap-ledger AUTO | activity, hardcoded | 4 (MTD) | — | — | ✔ | ✔ | ✔ | ✔ |
| **finance/home tiles** | `exec_top.py:73` → `window_report` / `unit_econ_view` → `_closes_union` | engine ∪ gap-ledger AUTO | activity, hardcoded (tiles **labelled** "cohort") | 4 | — | 12 (t90) | ✔ | ✔ | ✔ | ✔ |
| **SALES headline** | `sales_scoreboard.py:110` — its own inline filter | **tracker only** | activity, hardcoded | **1** | — | — | ✘ | ✘ | ✘ | ✔ |
| **SALES cash (same page)** | `sales_scoreboard.py:524` → `_closes_union` | engine ∪ gap-ledger AUTO | activity | 4 deals' cash | — | — | ✔ | ✔ | ✔ | ✔ |
| **ad scoreboard (EDITH "scoreboard")** | `attribution_queries.py:29` → `compute(days=30)` | tracker + derived | **cohort, hardcoded** | — | 1 | — | ✘ | ✘ | ✘ | ✔ |
| **compass actuals** | `compass_engine.py` ×7 → `_closes_union` | engine ∪ gap-ledger AUTO | activity, hardcoded | 4 | — | — | ✔ | ✔ | ✔ | ✔ |
| **EDITH "how many closes this month"** | `closes_view.py:144` — its own sheet reader | **tracker only** (no test-lead exclusion, no dedupe) | activity | **1** (MTD) | — | — | ✘ | ✘ | ✘ | ✔ |
| **EDITH "what have we closed this month"** | `closes_view.py:186` `recent_closes(5)` | tracker only | **none — "this month" is discarded; answers 5 most recent ALL-TIME** | — | — | 5 rows | ✘ | ✘ | ✘ | ✔ |
| **detection ledger (yesterday's #161)** | `close_detect.scan()` | tracker + GHL stage + recorder + payments | activity, 60d | **5** | — | 13 | ✔ | ✔ | ✔ | ✔ |
| **gap ledger** | `gap_reconcile.rebuild_closes` | GHL closed-stage in gap window + Stripe | activity | 3 AUTO + 1 PROPOSED | — | 6 | ✔ AUTO | ✔ AUTO | ✔ AUTO | ✘ (post-window, tracker has him) |

Plus a **seventh independent number nobody asked for**: `metrics_engine.py:147`
reads `funnel.closes` straight from the Team Scorecard sheet cell — outside
all engines (blank on the box today).

## THE CAUSES OF "1" — the brief's four hypotheses, confirmed or killed

**(a) CONFIRMED, and worse than stated.** The ads engine reads the tracker
plus the sanctioned derived-date lane. A derived close date can only land on
an existing tracker LEAD row. Orlando has one, so his gap-reconciled close
reaches /ads (on the activity clock). **Harman and William have no tracker
lead row at all — no clock, no window, no toggle can ever show them on /ads.**
The all-time grid holds 61 deals and still not them.

**(b) CONFIRMED.** The /ads default is the COHORT clock (`dashboard/ads.py:97`),
where a close counts in the window its LEAD arrived. 30d cohort = 1 (Koji,
lead and close both in September). 30d activity = 2. The board even prints a
nag saying 30d cohort is "still landing" — the number Rydel read was the
cohort figure with no total beside it.

**(c) KILLED.** The headline does NOT drop unattributed closes —
`closes_total` is the full engine population with the tier split rendered
beside it. The subset problem is (a): the *population* is a subset, not the
label.

**(d) OVERTAKEN BY EVENTS.** Koji is now visible everywhere — a human typed
his tracker row on 23 Sep (the first tracker close since 24 Jul). Today the
"1" on /ads IS Koji. The three the page still cannot see are Orlando (cohort
default) and Harman + William (structurally invisible, cause (a)).

**The sharpest finding: three surfaces say "1" for three DIFFERENT reasons.**
/ads says 1 because of the cohort clock on a tracker-only engine; SALES says 1
because its headline filter is tracker-only (while its own cash number on the
same page is built from the four-close union); EDITH says 1 because
`closes_view` is a third independent tracker reader. Same wrong number,
three separate mechanisms — the root pattern the brief names.

## WHAT ELSE THE PROBE FOUND

1. **Two candidate closes nobody counts**: Michael Pulvirenti (27 Aug, GHL
   stage only, PROPOSED) and Jay Lunsford (16 Sep, GHL stage only, PROPOSED,
   no money found). Real or not, they are exactly what the register's
   `proposed-needs-evidence` status is for.
2. **Jay Lunsford is in the gap ledger but NOT in the detection ledger** —
   the two four-source readers disagree with each other (to chase in
   Phase 1: stage-name match list vs `LIKE '%closed%'`, or a blank person key).
3. **The tiles are labelled with the wrong clock**: `unit_econ_view` names
   its window `cohort_month`, computes it on `"activity"`
   (`finance_analysis.py:661`), and the tiles render "Sep cohort · N closes"
   (`exec_top.py:299`). The number is right; the label lies.
4. **SALES' headline count and SALES' cash figure are different
   populations** on one page: 1 close, but cash from 4 closes.
5. `closes_view` and `range_unit_economics` bypass `parse_tracker`, so
   test-lead exclusion and won-dedupe do not apply to EDITH's voice answers
   or per-range unit economics.
6. `close_detect` — built precisely to see these closes — is consumed by
   **zero counting surface**: only the TODAY panel, the action feed, and
   EDITH's "what closed today" (which does not match "this month").

## THE POPULATION FORKS TO DELETE (Phase 1 hit list)

| # | fork | fix |
|---|---|---|
| 1 | `sales_scoreboard.py:110` inline `closes_in` | read the register |
| 2 | `closes_view._won_deals` (EDITH voice, quarterly pack) | read the register |
| 3 | `attribution_engine.compute` as /ads' close population | /ads reads the register (attribution stays the engine's job; the POPULATION is the register's) |
| 4 | `finance_analysis._closes_union` | becomes a thin read of the register (its union logic moves in) |
| 5 | `metrics_engine.funnel_closes` scorecard cell | labelled external reference, never a close count |
| 6 | `range_unit_economics` own tracker parse for closes | read the register |
| 7 | `compass_engine.py:130` raw tracker won-filter | read the register |

Baseline: suite locally 1386 passed, 2 pre-existing environmental failures
(`fpdf` missing in local venv; a kv-state-dependent source string in
`test_booked_calls_kept_only_and_windowed`). An unrelated in-flight
uncommitted change set (payer-matcher/roster, `ALIAS_APPOINTMENT_DIAGNOSIS.md`)
is in the tree and left untouched by this build.
