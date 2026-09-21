# ESTATE SCAN — 2026-09-21

Three scans across nineteen pages, run against production. Findings are
ranked by severity and sorted into the class of failure they belong to:
**BROKEN** (scan 1) · **DISAGREES WITH ITSELF** (scan 2) ·
**DISAGREES WITH REALITY** (scan 3) · **MISLEADING COPY** · **SLOW**.

Deterministic, doctrine-safe findings were fixed in this run, each with a
named regression test. Judgment-shaped findings become owner decision
cards — nothing was decided on Rydel's behalf.

## The runs

| run | commit | scan 1 | scan 2 | scan 3 | findings | runtime |
|---|---|---|---|---|---|---|
| first | `d4d5898` | 19 pages, 8 flags | 13 keys, 0 divergences | 6 checks pass, 3 not comparable | **11** (0 SEV1) | 132s |
| second (after fixes) | `2f62158` | 19 pages clean | 13 keys, 0 divergences, 2 engine checks, 3 EDITH drills | 6 pass, 3 not comparable | **0** | 153s |

## Findings — fixed in this run (each with a regression test)

| # | class | sev | finding | fix | test |
|---|---|---|---|---|---|
| 1 | BROKEN (scan defect) | SEV2 | The scan reported 7 "tiles rendered empty" on brief / cash / unit-econ. They are the **legacy ⓘ icons**, which use `data-metric` for the old tooltip system and carry no value of their own — a false positive. | Only elements that publish `data-value` are treated as metric-carrying tiles. | `test_scan2_metrics_carry_their_identity_in_the_dom` |
| 2 | BROKEN (scan defect) | SEV2 | The system page reported "a panel failed" because the health panel's *informational* empty state ("no scan has ever recorded a result here") uses the boundary style. | Empty states carry `.empty-state`; the scan ignores them. An empty state is not a failure. | covered by the clean second run |
| 3 | BROKEN (scan defect) | SEV3 | All three EDITH drills returned nothing — the scan posted `{message}` while the chat API takes a `history` array. | Corrected the call shape; the drills now answer (347 / 498 / 311 characters, 8 / 8 / 4 numbers). | `test_scan2_compares_by_key_and_against_the_engine` |
| 4 | DISAGREES WITH REALITY | SEV2 | Scan 3 could not check Meta at all: there was **no live re-read path**, so the archive could only be compared with itself. It honestly said "not comparable" rather than passing — but the check was hollow. | Added `meta_spend.fetch_day_live()` — one day, read live, **never writes the archive**. Sampled on three closed days. | `test_scan3_meta_live_reread_is_read_only` |

## Findings — from the defect review that preceded the scan (Part A/B)

| # | class | sev | finding | fix | test |
|---|---|---|---|---|---|
| 5 | MISLEADING COPY | **SEV1** | The show rate read **100%** when only 14 of 22 consults were confirmed attended — the rest were simply unmarked. The month's headline conclusion rested on it. | Confirmed basis is primary; the range is shown; status-only can never read "ahead"; the gap finder runs on both bases and says when the conclusion flips. | `test_a1_*` (3 tests) |
| 6 | MISLEADING COPY | **SEV1** | "Behind on closed" and "8 clients projected against 4 planned" in the same breath. | Outcome and rate are separate statuses; a test forbids contradictory words in one sentence. | `test_a2_outcome_and_rate_are_separate_and_never_contradict` |
| 7 | MISLEADING COPY | SEV2 | Spending **$1,948 over plan** rendered as "ahead". | Cost metrics read over/under plan; gain metrics read ahead/behind. | `test_a3_cost_metrics_never_read_ahead` |
| 8 | MISLEADING COPY | SEV2 | Qualified at n=173 read "too early to tell" — a large sample called uncertain. | Three-way band: outside the interval → ahead/behind; inside and tight → on track; wide → too early. | `test_a4_three_way_status_band` |
| 9 | MISLEADING COPY | SEV2 | Qualified read "planned 49%" though nothing plans a qualified rate. | Unmodelled stages read "usually X%". | `test_a5_*` (2 tests) |
| 10 | DISAGREES WITH ITSELF | **SEV1** | **Two qualification rules** existed — the engine's (CRM form required) and the travelling view's own (tracker answer). Same rows, two answers. | One rule, `attribution_engine.qualify_lead`; a test pins the single call site. | `test_b1_exactly_one_qualification_call_site` |
| 11 | DISAGREES WITH REALITY | **SEV1** | The revenue picklist changed at source on **2026-08-26**; the parser only knew the old spellings, so 75 leads parsed UNKNOWN and the rule read them as *below floor*. | Literal spellings added; unreadable values are UNKNOWN, never "below floor"; a new spelling now raises a loud drift finding. | `test_b1_unrecognised_value_is_unknown_not_below_floor`, `test_b3_picklist_drift_fires_loudly` |
| 12 | BROKEN | SEV2 | Pitched counted **all-time** CRM stages against this window's leads — "at least 102" when only 22 consults had happened. | Scoped to the window's own consults (now "at least 7"). | covered by `test_pitched_*` |

## Decision cards raised (judgment — not decided here)

| card | evidence | the one action |
|---|---|---|
| **The onboarding doc teaches a retired model** | Brief 17's document still teaches creative rotation, retired by DECISIONS #147 (continuous ad sets). | Rewrite it, or add a retirement note pointing at #147. |
| **The show/close evidence ladder has no Xero rung** | Brief 4 shipped T1/T2/T3 in `ads_truth.py`; `grep -c xero ads_truth.py` → 0. Cash evidence exists in `xero_pull.py` but was never wired in as a rung. | Decide whether the Xero rung is still wanted, and at what tier. |
| **The simulator can't solve for a required rate** | `requiredSpend` solves counts → spend; there is no "what close rate do I need". | Decide whether to add rate-solving to the compass. |
| **Consultations nobody marks** | 7 of 23 September consults have no attendance marked either way — the month's biggest-gap ranking sits on them. | Decide who marks attendance, and when. |
| **The tracker has no "pitched" column** | Carried from #156; the recorder now measures it going forward, but the source still can't record it. | Decide whether Piolo adds the column. |

## The honest limits of this scan

- **Scan 2 compares 13 keys across the modern surfaces** (the landing's 11
  tiles and travelling's 10 stages). The legacy area pages don't publish
  `data-value` yet, so their numbers are not yet in the matrix. Extending
  it is follow-up work, and until then scan 2's coverage is partial —
  stated here rather than implied away.
- **Scan 3 marks three Meta checks "not comparable"** in the runs above
  because the live re-read landed after them. From the next run it is a
  real cent-exact comparison on three closed days.
- Runtime 132–153s per full run; the Meta budget is three calls.
