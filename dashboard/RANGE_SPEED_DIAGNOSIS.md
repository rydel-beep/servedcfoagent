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
