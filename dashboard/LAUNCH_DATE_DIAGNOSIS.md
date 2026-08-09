# LAUNCH_DATE_DIAGNOSIS — Phase 1 of the launch-lineage + date-control build (2026-08-09)

Probes: `scripts/launch_date_probe.py` (read-only Graph GETs, run under `railway run`;
artifact `dashboard/audit_artifacts/launch_probe.json`, 25 ads, 0 errors) + local
per-ad daily store analysis (`state/meta_ad_spend_daily.json`, 90-day retention,
2026-05-11 → 2026-08-08, 161 ads with delivery).

## D1 — the three launch dates, measured on OUR data

| Candidate | What it is | Verdict on this account |
|---|---|---|
| `created_time` (ad object) | when the ad was made | **24/25 sampled ads: identical to first-delivery; 1/25 off by exactly 1 day** (ADS 36 Rydel AD B: created 3-19, delivered 3-20). Drafts do not sit on this account — ads deliver the day they're made. |
| adset `start_time` (scheduled) | the AD SET's schedule | **Useless as an ad launch signal — ad sets are REUSED.** Sampled ads created 2026-05-05 sit in ad sets with start_time 2025-05-16 / 2025-07-03 / 2026-01-22 (up to ~1 year before the ad existed). Never show as "launched"; context-label only. |
| first-impression day (insights) | delivery actually began | **THE launch definition** (DECISIONS #133). Retrievable per ad via lifetime `time_increment=monthly` sweep → daily zoom in the first active month (2 GETs/ad, both confirmed working, 0 errors). |

**The real Trap-1 on this data is not created-vs-delivery — it's the 90-day store
horizon.** 15/25 sampled ads (all the store-censored ones) would misstate launch by
**5–52 days** if "first day in the daily store" were shipped as "launched" (worst:
ADS 36 Rydel AD B, true first delivery 2026-03-20 vs store-first 2026-05-11).
The lifetime probe is REQUIRED for any ad whose first store day == the store's
oldest day; the store alone is only trustworthy for ads born inside it.

**Active days ≠ calendar days is real:** within the 90-day store alone,
B008_A04 "Brash — Objection-First / Ashley Hook" ran **30 active delivery days
across a 36-calendar-day span** (a 6-day pause). Store-censored ads diverge more
once lifetime is counted (ADS 36 Rydel AD B: 3 active months spanning ~5 calendar
months). Days-running MUST be the count of days with delivery, never `today −
launch`.

**Granularity capability (honest bound):** daily rows are retrievable for any
window (paginated, ≤500/page). The build computes: launch (exact day, lifetime),
active-day count (exact: store days + one lifetime daily backfill per ad, cached
durably — a launch date never changes once observed), and a delivery timeline.
Timeline resolution: exact daily inside the rolling 90-day store; for the pre-store
past the cached backfill preserves the daily list at probe time. No curve is ever
interpolated — where daily data was never fetched, the dossier omits the spark
(never fakes it).

## D2 — range-clock semantics (the label spec; box = [A, B] inclusive, Sydney days)

| Metric | ACTIVITY (events inside the box) | COHORT (the box's arrivals own everything) |
|---|---|---|
| leads | Input Date ∈ box | same (arrival IS the cohort event) — clock-stable |
| qualified / reached | attribute of the box's leads — clock-stable | same |
| sets | Set Date ∈ box, whoever's lead, whenever it arrived | sets belonging to leads that ARRIVED in box, whenever booked |
| shows | show tied to a set dated ∈ box | shows of box-arrival leads |
| closes | Close Date ∈ box (earlier-lead closes annotated ↤) | closes of box-arrival leads, whenever they landed |
| cash / contract | follows closes on the active clock | follows closes on the active clock |
| spend / impressions / clicks | delivery inside the box — **inherently activity** (Meta daily) | no cohort reading exists; the same box-delivery number is shown, labelled "spend is delivery-clock by nature" |
| CPL / C-Qual | box spend ÷ box leads — clock-stable (leads are stable) | same |
| C/Set, C/Close, ROAS | numerator/denominator follow the active clock → **differ across clocks** | differ |

"closes, last 7d" — activity: deals whose Close Date fell in those 7 days.
Cohort: deals from leads that arrived in those 7 days (usually ~0 — young cohort;
the maturity note exists for exactly this).

## D3 — source map under an arbitrary range

| Class | Columns | Failure behaviour |
|---|---|---|
| **Engine-authoritative** (tracker/GHL, cross-checked) | leads, qualified, reached, sets, shows, closes, contract, cash | live even when Meta is down |
| **Meta-sourced** (insights; NOT engine-recomputable) | spend, impressions, clicks, launch lineage (first-delivery, active days, status) | `source: Meta` chip; token/API degraded → **DEGRADED** cell, never a plausible 0 |
| **Hybrid** (Meta numerator ÷ engine count, or engine value ÷ Meta-containing cost) | CPL, C/Qual, C/Set, C/Close, C/Close-loaded, ROAS (both), LTGP:CAC | hybrid chip; degrades if EITHER side degrades |

## Phase-0 deltas (vs the mission premise)

1. **The audit fix wave is still AT THE GATE** (F1/F5/F6/F8/F12 open) and the
   sentinel is designed-not-built (Phase H, gated). This build carries its own
   hardening for its own surfaces (Sydney boundaries via `today_sydney()`, strict
   param validation, escaped rendering) and adds its watch-checks to the NIGHTLY
   integrity sweep (the sentinel's L2 rung) — sentinel L0–L3 proper remains gated.
2. **`refresh_entity_map` requests `created_time` but drops it** when building the
   store — the dossier's "created" line could never render (silent None). Fixed in
   this build (entity store now keeps `created_time`).
3. The window/clock engine params already exist (`start`/`end` + `basis`) — the
   date control is a UI + validation + labelling layer over the ONE path, exactly
   as required. No parallel aggregation was needed or built.
4. F8 (GHL-derived set/show dates sliced on the UTC day) remains open in the gated
   wave; the range control itself never converts timestamps (tracker dates + Sydney
   `today_sydney()` boundaries), so the new surface does not inherit the defect.
