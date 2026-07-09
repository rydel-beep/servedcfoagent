# DASHBOARD OUTAGE — diagnose, restore, harden (2026-07-09)

## Triage verdict
- **Down-type:** NOT server-down (health 200, `/dashboard` HTML rendered). A **DATA-PATH failure** —
  `build_snapshot()` threw → `/cfo/refresh` returned **500** → no snapshot persisted → `/cfo/snapshot`
  **404** → dashboard loaded but had **no data**.
- **Failing component:** `sales_analytics_pull.py:_pull_deep_dive` — `float(_cell(row,3))` on a
  scorecard cell holding **"—"** (a human placeholder) → `ValueError: could not convert string to
  float: '—'`. The `.strip()` guard passed the non-empty em-dash straight to `float()`.
- **Suspect change:** not a recent feature commit — a **new sheet value** tripped a long-fragile parse.
  It became a TOTAL outage because (a) the snapshot lives in a **local file** (`snapshot_state.json`)
  wiped on the last deploy, so there was no stale snapshot to fall back on, and (b) `build_snapshot`
  called every source's `.result()` **unguarded**, so one source raising aborted the whole build.

## Phase 1 — restore service
Added `_parse_float()` (handles blanks + placeholders `— – - N/A TBC` → None, never raises) and used
it at the crash site — the only unguarded `float()` in the file. **`build_snapshot()` verified green**
(35 keys, active_clients 38). Deployed `eb31338`. **Live: `/cfo/refresh` 200, `/cfo/snapshot` 200
(fresh data), `/dashboard` renders — OUTAGE OVER.**

## Phase 2 — refresh isolation (fail-soft)
`_safe_result(future, name)` wraps each of the 11 source futures: a source that RAISES degrades
ITSELF (labelled in `degraded[]`) instead of aborting the build. Verified: a simulated
`sales_analytics` crash still builds the snapshot (active_clients intact, sales labelled degraded,
`ok=false`). A single dependency down never again equals the dashboard down. Deployed `ec59bdb`.

## Phase 3 — harden
- **Boot resilience:** startup/scheduled refresh already wrap `build_snapshot` in try/except; combined
  with fail-soft, a bad source degrades loudly instead of crash-looping.
- **`/health` triage:** upgraded from `{status:ok}` to crash-proof subsystem reporting — server, DB
  reachability, snapshot presence + age + stale flag + **named degraded sources**, overall
  ok/degraded. Live: `{status:ok, db:ok, snapshot:{present, age 3.2m, 7 degraded sources named}}`.
  Deployed `323f4e9`.
- **Error surfacing (already present, confirmed):** `loadAll()` shows `#error-banner`
  ("Couldn't load the dashboard data." + Retry) when the snapshot is null — an explicit error state,
  not a blank screen or infinite spinner.

## Root cause (one line)
A human typed "—" in a numeric scorecard cell; a fragile `float()` (no safe-parse) crashed the whole
snapshot because sources weren't isolated and the local snapshot file had just been wiped on deploy.

## Regression guards
`tests/test_snapshot_resilience.py` — `_parse_float` tolerates the exact crash input + placeholders;
`_safe_result` degrades a crashing source and passes success through. 315 tests pass.

## Nothing reverted
Service was restored by a targeted fix (not a revert); all prior features intact. The parallel
session's uncommitted WIP (stripe_reconcile in snapshot.py; refresh-cadence in app.py) was preserved
via checkout-reapply — not committed, not lost.
