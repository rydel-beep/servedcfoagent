# ADS_SYSTEM_STATE — the canonical ad-tracking system doc

**Read this FIRST in any ads session.** AS-SHIPPED at the audit GATE CLOSE
(2026-08-09): the fix wave (F1–F16 per AUDIT_FINDINGS_REGISTER.md), ruling R1
(DECISIONS #132), and the Phase H sentinel are in the tree. Nothing below is
inherited unre-proven — every claim traces to a wave test or a gate-close
artifact (`dashboard/audit_artifacts/06+`). Old *_REPORT.md files are history,
not truth — where they conflict with this doc, this doc wins.

## Architecture (one engine per metric AND per roster)

```
tracker (Sheets, AUTHORITY) ─┐
GHL contacts/appts/calls ────┤→ attribution_engine.compute()  ← THE engine
Meta spend/entities ─────────┤   (per-creative rows + person rows + members
Stripe charges (read-only) ──┘    + invariants + reconciliation)
        ↓ consumers (zero new math anywhere)
  scoreboard_view · attribution_verdicts.ladder/ladder_groups · roster_engine
  · dashboard/ads.py routes · ads_truth sweeps · resolution derivations
  · ad_sentinel (Phase H — the standing watcher)
```

- `attribution_engine.py` — parse_tracker → dedupe_won → derived-date merge →
  tier bucketing → per-metric counters WITH member lists (I17) → invariants →
  reconciliation. In-process cache 30-min TTL keyed
  **(w0, w1, basis, market, derived_epoch)** — the F6 epoch means a derivation
  write invalidates every cached result at once; consumers probe warmth ONLY
  via `cache_fresh()` (never a hand-built tuple — the old 3-tuple probe was a
  dead warm path). degraded[] folds spend + entity-map + contact signals,
  deduped (F5).
- **Rollup layer** (`dashboard/ads.py`): `attr:rollup:<basis>:<days>` records
  are `{at, epoch, board, engine}` — `engine` is the F1 slice (creatives WITH
  members + trimmed rows) that serves COLD rosters/dossiers via
  `roster_engine.load_result()` in <500ms, stale-LABELLED with age + reason;
  an epoch-mismatched rollup states "superseded by a derivation write" and
  auto-refreshes. Board payloads carry `degraded[]` + `ok` (F5).
- `roster_engine.py` — THE cellspec→roster path; payload states served_from /
  stale / stale_reason; I17 len(people)==cell checked at build.
- `resolution.py` — derive-never-invent engine. JOURNAL-FIRST writes (F10);
  every derivation-class write bumps `derived:epoch` (F6); evidence-class
  journal entries persist in durable `resolution:journal` cap 1000 (F2) while
  sweep noise rolls in the 200-cap log; `rederive_ghl_dates_sydney()` is the
  journaled F8 migration (idempotent, dry-run, boundary-crossing callouts).
- `helpers.sydney_day()` — THE derivation-boundary day conversion (F8): every
  GHL/Postgres timestamp converts to the Sydney calendar day (DST-correct);
  UTC slicing at a derivation boundary is a doctrine violation.
- `cash_truth.py` — charge pulls mark PARTIAL failures loudly
  (`stripe:partial_pull`, F9): the cash view degrades core, the #131 ruling
  pass skips the run, the card builder keeps existing cards.
  `refund_report()` (R1/DECISIONS #132): refunds are post-close economics —
  they report here (incl. fully-refunded charges), never erase closes.
- `ads_truth.py` — spine census, reached sweep (now prunes merged-away ids —
  F7), event sweep, show verification, quad-check, nightly `integrity_sweep`
  (self-timing, SENTINEL COST block in its accuracy row; F3 self-retiring
  invariant alerts; F11 orphan-derivation census; ONE accuracy row per date).
  `nightly_tick` is SINGLE-FLIGHT via an atomic day claim (F16;
  `kv_store.put_if_absent`), claim released on failure so the day retries.
- `dashboard/ads.py` + `adsapp.js` — render + drill only (I16). DEGRADED
  chips/strips on every spend-derived surface (F5); ?roster= deep links
  whitelist level/metric + esc() before render (F12).

## Conventions (DECISIONS refs)

- #111 first-touch · #118/#120 tracker authority + one clock per view ·
  #126 ads-truth loop · #127 market filter I15 · #128 date conventions ·
  #129 show tiers · #131 payment-class close-date auto-derivation ·
  **#132 refund semantics (R1): a refund is post-close economics — close
  dates/funnel counts untouched; the refund reports in
  `cash_truth.refund_report` (it moves, it doesn't vanish).**

## Integrations + scopes

| Source | State |
|---|---|
| GHL | contacts/appointments/conversations readable; payments/invoices 401 (no rung) |
| Stripe | read-only rk_ key; partial pulls marked LOUD (F9) |
| Meta | entities + spend live; a dead token renders DEGRADED, never $0 (F5). ALL insights calls route through the ONE `meta_range` builder — clamped to the rolling 37-month API floor (#3018 impossible), per-ad-scoped, chunked, clamp-disclosed (#138). |
| Meta spend ARCHIVE | the daily buckets (`meta_ad_spend_daily`/`meta_spend_daily`, kv-mirrored) are AUTHORITATIVE for days the API can no longer serve — a day captured while in-window (source-stamped `captured`) is summed forever as Meta's 37-month window rolls off the back. Days before the earliest capture render "pre-API-retention" (named absence, never $0). Nightly retention-heal grows the archive to the floor; archive-completeness watches the front (#138). |
| Xero | report scopes only; Invoices 401 — re-consent pending on Rydel (queued) |
| Postgres | kv_store + mirrors + attr_contacts; Railway-internal (probe via `railway ssh`) |

## Invariants

I1/I2/I8 funnel coherence · I10 tier partition · I11 clock purity · I13 single
computation path · I14 no orphan badges · I15 market partition · I16 view
purity · **I17 roster-cell equality** — enforced at increment; sampled n=5
hourly (L1), n=20 nightly (L2), FULL weekly (L3) + suite sweeps.

## Jobs + cadences

- `attribution_engine.start_loop()` — every 6h: compute refresh + module ticks
  + `ads_truth.nightly_tick()` (**single-flight day claim BEFORE the sweep —
  F16**; boot does not tick immediately).
- `ad_sentinel.start_loop()` — hourly heartbeat: **L1** every hour (recon ·
  I10 · I17 n=5 · delta-anomaly band incl. verified-show-ratio decline, F15);
  **L2 extras** once the nightly sweep stamps (drift diff vs previous accuracy
  row + the heal pass); **L3** weekly (full I17 · full 90d quad-check ·
  5-claim re-proof · security replay [/debug 401 + roster taint 400] · perf
  regression vs budgets). All single-flight via kv claims — safe across both
  workers.

## The sentinel (Phase H — SHIPPED)

- **Escalation**: an L0/L1 signal buys a TARGETED deep pass on its domain only
  (i17 → full I17 now; recon/partition → quad-check now; metric anomaly →
  drift diff; security → probe replay). Spend follows signal.
- **Budgets** (per run): L1 15s/0 calls · L2 240s/130 calls · L3 600s/20
  calls. Breach = LOUD action-feed alert; every run appends an auditable cost
  row (kv `sentinel:cost`); the nightly accuracy row carries the L2 cost
  block (runtime + API calls vs budget).
- **Self-heal boundary (HARD)**: deterministic data-layer ONLY — rebuild
  stale/epoch-superseded rollup · clear invalidated engine cache · re-sync
  stale contact table · re-derive on new evidence / process supersessions ·
  regenerate failing-test skeletons. Each heal journaled (durable evidence
  stream) + ONE quiet feed line. The sentinel NEVER edits code, definitions,
  conventions, or thresholds, and never invents data. Judgment-/code-shaped
  findings → `SENTINEL_QUEUE.md` (ranked) + an action-feed item.
- **KILL SWITCH**: env `AD_SENTINEL_PAUSE_HEALS` (any truthy value) pauses all
  heals; detection keeps running and states the pause in the feed. Proven:
  `tests/test_sentinel.py::test_kill_switch_halts_heals_detection_continues`.

## Launch lineage + date control (#133, 2026-08-09)

- `launch_lineage.py` — THE launch/active-days source: launched = FIRST-DELIVERY
  day from insights (never created_time — secondary; never ad-set start_time —
  reused), days running = ACTIVE delivery days. Durable store (state file + kv
  mirror `launch:lineage`); store-censored ads get a one-time lifetime probe
  (2–3 GETs, 15/15 succeeded at build); unprobed = "on or before", degraded ≠
  zero. Attached ONCE in compute() + ladder _aggregate — hover card, dossier
  lineage section (three dates + exact delivery timeline), and launch/active-
  days sorts read the same field (equality test-enforced).
- Date control: ?range=YYYY-MM-DD..YYYY-MM-DD + ?clock=activity|cohort — a
  window PARAMETER over the one engine (no second path). Strict validation
  (F12-immune), future end clamped to today_sydney + noted; presets default
  ACTIVITY, standard windows keep ruled cohort; every label carries the active
  clock; drills/rosters/dossier inherit box+clock via one JS windowQS()
  builder; I17 pinned on custom ranges both clocks. Sourcing: META/HYB header
  chips on all Meta-sourced/hybrid columns (hybrids degrade if either side
  degrades) — grep-enforced. Nightly sweep watches: launch_freshness +
  clock_label (ACTION-promoted).

## Known open findings

- **F17 (register)**: normalization split — `resolution._norm` strips '@'/'.'
  while the engine's `_norm` keeps them; derived keys for such names never
  match engine name_norms, so the derived-date merge silently skips them.
  Queued P1 (SENTINEL_QUEUE) — needs a keyed-migration session; do NOT
  hot-patch either normalizer. Census mislabel already fixed (dual-norm).

## Security posture

All /ads + /cfo surfaces auth-walled; sales fail-closed; media_buyer
shipped-disabled; /debug/* X-CFO-KEY-gated (`45670b7`, sweep test). F12
reflected-XSS via ?roster= CLOSED (whitelist + esc at the boundary, taint
tests, weekly sentinel replay). No open security findings.

## Data state (post-migration items — run at deploy, artifact 08)

- F8: `rederive_ghl_dates_sydney()` — journaled old→new over every ghl-appt /
  contact-created derivation; reconciliation re-checked green after.
- F16: `dedupe_accuracy_history()` — the doubled 08-07/08-08 rows collapsed
  (journaled), one row per date thereafter by construction.
- Standing judgment queue (never auto-fixed): see SENTINEL_QUEUE.md seed —
  4 stage-only P1 · 37 set-multi · 3 attendance · 1 P2 link · 4 H1 blanks ·
  Xero re-consent.
