# TRIPLE_SWEEP_REPORT — three domains vs ground truth (2026-08-10)

Sweep run live against prod (commit 809820c pre-fix state; fixes shipped in
2b77b03). Every claim below has a live probe behind it; deterministic findings
were FIXED IN-RUN with regression tests; judgment-shaped ones are PROPOSED.

## Scorecard

| Domain | Check class | Result |
|---|---|---|
| **1 · System integrity** | I17 roster-cell equality: 30/60/90/All + 2 custom boxes × both clocks | **13,519 cells · 0 drift** ✅ |
| | I1–I16 invariants across the same 12 box×clock legs | 2 fails, BOTH the known source-data rows (ADS 38 Hannah / ADS 36 Rydel: tracker "Showed" without a set — rendered as honest integrity-error rows; Piolo source fix, PROPOSED) ⚠ known |
| | Reconciliation identities (leads/closes/cash/spend), all legs | **0 failures** ✅ |
| | Rollup ↔ live-engine coherence (15 spot cells, cohort 30d) | **15/15 match**, epoch-stamped ✅ |
| | Evidence journal (post-F2) | mechanism live (31 entries); >2-day-old charge-id check **inconclusive by age** (partition born 08-09). FOUND: the 12 ruling-conversion entries predate the partition and sat only in the 200-cap rolling log → **backfilled to the durable journal in-run** (SEV3 fixed); primary chain (charge-ids in derived:dates evidence) was never at risk — 10/10 present ✅ |
| | Sentinel health | accuracy rows 1/day post-F16 (0 dupe days) · 1 cost row, 0 over budget · kill switch unset (= heals active, documented) ✅ |
| | Degraded rendering | suite-pinned (test_ads_degradation, 8 tests incl. mocked-dead upstream) ✅ |
| **2 · Ad data vs Meta** | Fresh insights vs dashboard, per-ad spend+impressions: Last 7d / Last 30d / custom 12–19 Jul | **24, 55, 14 ads: 0 mismatches, to the cent** (incl. today — no volatility divergence at probe time) ✅ |
| | Launch + active-days re-derived from fresh lifetime daily insights (10 ads) | **10/10 exact** (launch day AND active-day count) ✅ |
| | Hybrid CPL/C-Qual/C-Set/C-Close recomputed by hand (10 creatives × 4 ratios) | **40/40 exact** ✅ |
| | Attribution spot-audit (25 most recent leads re-walked) | 23/25 resolve id-exact to a creative · 0 ambiguous · 2 unresolved (organic/untagged — honest Unattributed) ✅ |
| **3 · Lead truth** | Every close, all-time (58) quad-checked | **58/58 evidenced**: 48 tracker-dated + 10 derived, each derived date matching its charge-id evidence · 3 closes have no GHL contact (tracker-only identity chips render — known, SEV4) ✅ |
| | Every set (19) + show (13) in last-60d activity | **32/32 justified** by tracker cell, derivation, or spine evidence ✅ |
| | 50 random leads across 29 creatives, chips re-justified | 1 flag → check-artifact (duplicate-identity rows, orlando rinaldi ×2 — engine windows each row correctly; register SEV4 note) ✅ |
| | Consult datetimes vs raw GHL (every rendered datetime in sample) | post-deploy leg — see §Consult verification |
| | Dateless queue re-disposition | 5 P1 cards + H1s re-checked: **0 new evidence** since #131; BUT Nirosha's P1 card was proposing a date for her DUPLICATE blank row → **card-layer duplicate-dated guard shipped in-run** (SEV3 fixed, regression-tested) |
| | Derived-10 source-fill re-check | **0 tracker fills yet** → no supersessions due (mechanism verified in-suite) ✅ |

## Discrepancy register

| # | SEV | Finding | Disposition |
|---|---|---|---|
| T1 | **SEV1** | **Appointment-endpoint timestamps are LOCATION-LOCAL, not UTC** — hour-distribution proof (130 appts: raw hours all 07:00–23:00; as-UTC 121/130 land 7pm–6am Sydney; peer session re-probed: 266/266 offset-less). `sydney_day`'s naive=UTC assumption (correct for Z-suffixed contact/message/Postgres stamps — verified per-endpoint) was applied to appointment fields by the F8 migration, moving **22 derived set/show dates +1 day** (the pre-F8 `[:10]` slice was accidentally right for this endpoint). | **FIXED in-run**: source-aware `consult_schedule.appt_day` at every appointment call site (event_sweep, spine candidates, re-derivation machinery) + corrective migration `rederive_appointment_local_days()` (journaled, epoch-bumped) + regression tests pinning both semantics. Peer session amends its F8 register/artifact claims. |
| T2 | SEV3 | Nirosha's P1 close-date card proposed dating her duplicate blank won row — acting on it would double-count an $18,300 deal. The #131 auto-converter had the duplicate-dated guard; the card generator didn't. | **FIXED in-run**: same both-key guard at the card layer; the duplicate now gets an explicit "DELETE the duplicate row — do NOT fill a date" card. Regression test. |
| T3 | SEV3 | The 12 ruling-conversion journal entries predate the F2 durable partition and lived only in the 200-cap rolling log (one flush from ageing out). Charge-ids in derived:dates evidence meant the trust chain itself was never at risk. | **FIXED in-run**: one-time backfill of evidence-class rolling-log entries into resolution:journal (post-deploy migration step, deduped). |
| T4 | SEV4 | test_timeline_adapter week-filter test was calendar-flaky (fixture complaint dated 08-02 + unfrozen "today−7d" → failed every run after 08-09). | **FIXED in-run**: clock frozen to the fixture's week. |
| T5 | SEV4 | Duplicate-identity non-won tracker rows exist (orlando rinaldi ×2, 18 months apart). Engine counts each entry event correctly; roster enrichment prefers one row for tracker-field display on such duplicates. | Registered; no engine change (legitimately two lead events). Piolo may merge if the 2024 row is stale. |
| T6 | SEV4 | 3 all-time closes have no GHL contact (tracker-only identity) — attribution impossible for them, chips state it. | Known class; PROPOSED (Piolo: add emails to tracker or contacts to GHL). |
| T7 | note | 2 all-time-cohort integrity-error rows (shows>sets: Esin Kandas, Tiffany Nguyen) — pre-existing, rendered honestly since the roster wave. | PROPOSED (source fix at tracker). |

## Domain-2 match table (dashboard vs fresh Meta)

| Box | Ads (fresh/dash) | Spend fresh | Spend dash | Per-ad mismatches |
|---|---|---|---|---|
| Last 7d | 24 / 24 | $1,579.99 | $1,579.99 | **0** |
| Last 30d | 55 / 55 | $9,713.89 | $9,713.89 | **0** |
| Custom 12–19 Jul | 14 / 14 | $2,743.33 | $2,743.33 | **0** |

Launch re-derivation sample (10 ads, fresh lifetime daily insights): all exact —
e.g. …970167 launch 2026-03-20/54 active · …660167 2026-07-01/30 · …520167
2026-07-26/11. utmAdId forward-capture (Romano chain): **78% id-exact of
last-30d leads (54/69), 90% of last-14d (27/30), 88% of last-7d** — plus 5
name-ref / 8 no-ref / 2 unmatched in the 30d set; id-exact share of resolved
attribution in the 25-lead walk: 23/25.

## Consult verification + migration (post-deploy legs)

Filled after the 2b77b03 deploy — see the addendum at the bottom of this file.

## Rendered numbers that changed because of this sweep

1. **Derived set/show dates (appointment-sourced, up to 22 entries)**: the
   corrective migration reverts the F8 +1-day shifts — each change journaled
   old → new with reason `appt-local-tz (#134)`. Exact list in the addendum.
2. **Nirosha's card**: P1 date-candidate → duplicate-blank delete-me card
   (queue content, not a metric).
3. Nothing else — Domains 1–2 found zero numeric drift to correct.

## Addendum — post-deploy legs (2b77b03, 2026-08-10)

**Corrective migration (T1)**: dry-run 22 changes — 15 set_date + 7 show_date,
every one −1 day, 0 window crossings; live run applied + journaled
(`appt-local-tz (#134)`), epoch → 6; idempotence re-run 0/72. Changed names:
lynn · ramin (set+show) · george · ron ling (set+show) · shamsher · sami amor
(set+show) · dani zeini · iqbal fauzan · silvia kubes · nguyen nguyen · bilal
siddique · isaac anderson (show) · owen stuchbery (set+show) · renato chilelli
(show) · francesca martina · jingjie yangjacky · michiel de ruyter (set+show).
Post-migration: 5,052 cells 0 I17 drift · recon green · only the 2 known
source-data invariant rows.

**Consult verification (Domain 3 final leg)**: live 60d sets roster — 12
people; states {scheduled 8 · no_appointment 4} (every state honest, no
blanks); all 8 rendered datetimes verified against the raw cached appointment
(pick-current selection, rebook count, exact format spec) — 0 problems. Live
GHL re-fetch of all 8: **1 divergence — Matt Annenberg**, appointment
cancelled in GHL AFTER caching (7d TTL) → rendered "upcoming" wrongly. → T8.

| # | SEV | Finding | Disposition |
|---|---|---|---|
| T8 | SEV3 | Upcoming appointments are the MUTABLE class — a post-caching cancellation could render as "the consult · upcoming" for up to 7 days. | **FIXED in-run**: upcoming-bearing cache entries expire DAILY (past-only keep 7d) + one-time expiry of old-regime entries; regression test. Residual staleness bound: ≤1 day, and the nightly warm refreshes it. |

**Warm convergence**: appt cache 84 → 115 contacts (the full 120d set-lead
population) over 3 computes; roster panel steady state after convergence.

**Perf vs budgets (measured live, in-process)**
- Roster panel with consult datetimes: standard-window path **484ms** (30
  scheduled datetimes), warm re-open **249–270ms** — budget <500ms ✅. First
  open during warm convergence paid 8.1–8.6s (one-time; the class now sits in
  the nightly + background computes).
- Control apply: standard windows (30/60/90/Maximum) **103–117ms** from
  epoch-stamped rollups (stale-labelled when superseded, refresh kicked);
  custom boxes 1.5–2.0s on first compute (the documented F1-class cold cost;
  22ms cached). Perceived <300ms holds via skeleton + labelled arrival.
- Grid at Maximum: **117ms** (rollup-served) ✅.
- Anon probes: board/roster/dossier with ?range/?clock → 401; hostile ?range →
  401 (auth precedes parsing; validation suite-pinned) ✅.

**Queue re-dispositions**: dateless-9 → unchanged except Nirosha's card
replaced by the duplicate-blank delete-me card (T2); 4 H1 no-candidates:
still zero payment-class evidence (re-checked in the #131 nightly rung).
Derived-10: 0 tracker fills; no supersessions due; all 10 charge-ids now in
the durable journal (T3).
