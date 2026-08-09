# RANGE_SPEED_DIAGNOSIS — where the seconds actually go (2026-08-10)

Instrumented live on prod (railway ssh), fresh never-computed boxes.

## D1 — the cold-path breakdown (measured, ms)

| Stage | ms | Class |
|---|---|---|
| tracker parse (mirror read + clean + parse) | 110 | input |
| contacts sync check + load (Postgres) | 26 + 95 | input |
| **entity map refresh (Meta, on 12h-TTL lapse)** | **4,157** | network on the interactive path |
| **ad-spend daily refresh (Meta level=ad, trailing 7d)** | **7,047** | network on the interactive path — **NO TTL: every compute pays it** |
| lineage refresh (merge, no probes pending) | 109 | input |
| spend_by_ad_in_range (store file re-read + sum) | 405 | store re-read per call |
| **compute_from_inputs (the actual window math)** | **88** | engine |
| canonical anchors (leads 85 · ltc 85 · spend 368) | 538 | independent anchors (spend = store re-read) |
| full compute(), fresh box | 7,279 | — |
| same box, cached | 20 | — |

**Verdict: the cost was never aggregation.** The window math is 88ms; the
1.5–7s is Meta network sitting on the interactive path (the ad-spend trailing
backfill has NO TTL and refires on EVERY compute; the entity map blocks when
its 12h TTL lapses) plus per-call store file re-reads. Variance (1.5s good
days, 7s bad) is Meta API latency — exactly matching what Rydel witnessed.

## D2 — what dims
`body.adx-loading` dims EVERY panel to 55% opacity on EVERY board load —
presets AND custom ranges. Presets resolve in ~110ms so the dim is a blink;
customs sit dimmed for the whole Meta round-trip.

## D3 — race exposure
`reqToken` latest-wins already discards stale responses (response A landing
after B never paints — the guard is server-echo checked). Gaps: no
cancellation of superseded in-flight fetches, and no target-state pending
header (during load the OLD header/rows stay — honest but not the flow asked).

## D4 — day-decomposability + the bucket-layer verdict
The Sydney-day buckets ALREADY EXIST at input grain: `meta_ad_spend_daily`
IS (ad × Sydney-day) spend/impressions; tracker leads ARE day-keyed facts
(input/set/close days); cohort attribution is arrival-day-keyed (confirmed —
a cohort bucket is its arrival day's leads + their downstream facts). Every
grid metric is day-decomposable at INPUT grain. At OUTPUT grain they are NOT
cleanly decomposable: the activity annotations (earlier_closes/sets/shows,
◔ undated) are BOX-RELATIVE (defined against the box start), so output-grain
buckets would re-walk member facts at sum time anyway — a second aggregation
path for zero gain over the 88ms engine. **Chosen architecture: keep the ONE
engine as the only summing path; make its INPUTS bucket-reads** — (a) evict
Meta network from the interactive path (TTL + background refresh; serve the
stamped store), (b) extend the daily stores to FULL history so Maximum and
old boxes are store-served (today: ad-level covers 90d only — an old box
falls to a live Meta call), (c) mtime/stamp-keyed in-process memos for store
loads and parsed inputs. I13 is strengthened: zero new aggregation code.

Fallback plan for non-decomposables: none needed — the engine keeps computing
box-relative annotations from member facts exactly as today.

## Post-build results (deployed e300820, 2026-08-10)

**Perf, measured in prod (worst realistic case = fresh worker process):**

| Interaction | Before | After | Budget |
|---|---|---|---|
| Preset switch (30/60/90) | 103ms–17.5s (first build/process) | **26–113ms** | ≤150ms ✅ |
| Maximum | 117–187ms | **48–155ms** | — ✅ |
| Custom box, first-ever | 1.5–7s (once 79s) | **140–283ms** (2024-era one-time 3.6s, pre-converged — now 130–400ms) | ≤300ms ✅ |
| Custom box, repeat | 22–173ms | **22ms** | — ✅ |
| Same box, other clock | 1.3s | **283ms** | — ✅ |
| Roster under a custom box | 199–317ms | **73–180ms** | <500ms ✅ |

**Where the seconds went (all fixed):** ad-spend trailing refresh with no TTL
(2–7s/compute) → TTL + background · entity-map TTL lapse (4.2s) → background ·
`recover_by_name` historical sweeps (12.8s/serve profiled) → negative-cached +
nightly-only · 33 fresh Postgres connections/serve (0.70s) → per-thread reuse ·
store file re-reads (0.77s) → mtime memos · account+ad spend history lost per
deploy → kv mirrors + full backfill (588 Sydney-day buckets to 2024-11-01,
one-time 24.6s ad-level + 1.1s account; kv-mirror survival proven across a
live deploy).

**Correctness:** 11 boxes × both clocks: 88 serving-vs-forced-recompute total
compares, 0 drift · fresh-Meta per-box spend, 0 mismatches · I17 3,468 cells 0
drift · DST-spanning box (Oct 2026) and single-day box exact · recon green
everywhere · F6 live-proven: epoch bump → the open range view recomputes
(2ms cached → 126ms rebuild, recon green).

**Flow:** dim overlay deleted (grep + structural tests); pending header claims
the TARGET state in the same frame numeric cells skeleton; superseded fetches
aborted (AbortController) atop the token + server-echo guards; failures revert
controls to the last-good board. Sentinel: bucket_drift (nightly closed-day
sample vs fresh Meta, ACTION-promoted) + name_recovery_pass live.
