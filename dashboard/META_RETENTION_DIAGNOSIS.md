# META_RETENTION_DIAGNOSIS — the #3018 boundary bug (2026-08-10)

## Phase 0 — confirmed live (prod)

**The failing request** (dossier all-time spend → `meta_spend.spend_in_range`):
`time_range={"since":"2023-07-01","until":"2026-08-10"}` level=account →
`HTTP 400 code=3018: "The start date of the time range cannot be beyond 37
months from the current date"`. `spend: null`, one coarse `degraded` entry
`{metric: meta_spend_range}`.

**The boundary, pinned empirically** (day-by-day probe, not docs): the edge is
**exactly calendar-37-months-before today_sydney**. Today 2026-08-10 → floor
2023-07-10. `2023-07-09` → #3018; `2023-07-10` → OK. It ROLLS daily (tomorrow
the edge is 2023-07-11). The account's earliest data sits ~Jul 2023, i.e. AT
the boundary now — so every day it rolls, a day of real history becomes
API-unretrievable. This is the archive's whole reason to exist.

**api_floor** = `calendar_37mo(today_sydney) + safety_margin` (default 3 days →
2023-07-13 today); computed fresh per request, never cached across days.

## Call-site inventory (10 — ALL must route through the one builder)

| # | Site | Range it builds | #3018 risk |
|---|---|---|---|
| 1 | `meta_spend.spend_in_range` :272 | arbitrary (all-time → 2023) | **YES — the witnessed trigger** |
| 2 | `meta_spend.backfill_history` :197 | account chunks to `since` | YES if since < floor |
| 3 | `meta_spend.pull_meta_spend` :347 | trailing 90d | no (but routes for uniformity) |
| 4 | `meta_entities.spend_by_ad_in_range` :566 | arbitrary per-ad | **YES — per-ad all-time** |
| 5 | `meta_entities.backfill_history` :493 | per-ad chunks to `since` | YES if since < floor |
| 6 | `meta_entities.refresh_ad_spend_daily` :427 | trailing 7/90d | no (routes) |
| 7 | `meta_entities.recover_by_name` :317 | 3 yearly chunks back | **YES — the oldest year** |
| 8 | `launch_lineage._lifetime_probe` :178 | `date_preset=maximum` | **YES — an ad with >37mo history** |
| 9 | `launch_lineage._lifetime_probe` :195 | first-active-month → store edge | YES if that month < floor |
| 10 | `ads_truth.bucket_drift_check` :848 | sampled closed days (recent) | no (routes) |

Two low-level GET helpers already exist (`meta_spend._graph_get_all`,
`meta_entities._get_all`) — near-identical. The ONE builder (`meta_range.py`)
is pure range logic (clamp/scope/chunk/merge/disclose) and takes the low-level
`fetch` as a parameter, so it's the single call-site WITHOUT merging the two
modules. Grep-asserted: no `/insights` time_range built outside it.

## Degradation propagation — the coarse bug

`spend_in_range` returns `degraded:[{metric:"meta_spend_range", reason}]` with
NO range. The dossier (`ads.py:604`) MERGES `result.degraded + r_all.degraded`
into one `dossier_degraded`; the JS `degradedEntryFor` matches any metric
starting with `"meta"` → **every spend column, both windows, badges DEGRADED**
even when the 60d data is perfectly retrievable. Fix (1.2): degraded entries
carry `(source, range, cause)`; each econ leg (`econ_window`, `econ_all_time`)
consults its OWN degraded list; the JS `dmoney` reads the leg's list, not the
merged one.

## Bucket layer (range-speed wave, as shipped)

`meta_ad_spend_daily` (per-ad × Sydney-day) + `meta_spend_daily` (account ×
day), both kv-mirrored (`meta:ad_spend_daily`, `meta:spend_daily`), reseed on
boot. Current coverage from the range-speed backfill: **2024-11-01 → today**.
Missing: 2023-07-13 → 2024-10-31 (retrievable NOW, rolling off soon → 1.3
backfills it) + the pre-retention sliver 2023-07-01..-09 (never retrievable →
named absence). The buckets are ALREADY the serving layer and idempotent —
1.3 extends the backfill to the floor, adds per-day `captured` stamps, and
makes bucket history authoritative for days the API can no longer serve.

## The three layers (build plan)
1.1 `meta_range.py`: `api_floor()` (rolling), `clamp()` (+ `clamped_from`),
`scope` (per-ad → launch), `chunk` (≤90d), `insights()` (merge, per-chunk
degradation). Route all 10 sites through it.
1.2 range-scoped `degraded[]` + per-leg dossier consult.
1.3 backfill to floor (idempotent, source-stamped), pre-retention honesty,
sentinel retention-heal + archive-completeness watches. F6: bump the derived
epoch after a backfill so rollups refresh.
