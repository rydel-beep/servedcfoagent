# ADS_SYSTEM_STATE — the canonical ad-tracking system doc

**Read this FIRST in any ads session.** Everything below is AS-VERIFIED on
2026-08-08 (extreme audit; artifacts in `dashboard/audit_artifacts/`). Nothing
is inherited from old reports unre-proven. Old *_REPORT.md files are history,
not truth — where they conflict with this doc, this doc wins.
Status: audit discovery complete; fix wave AT THE GATE (see
AUDIT_FINDINGS_REGISTER.md — F-numbers below refer to it).

## Architecture (one engine per metric AND per roster)

```
tracker (Sheets, AUTHORITY) ─┐
GHL contacts/appts/calls ────┤→ attribution_engine.compute()  ← THE engine
Meta spend/entities ─────────┤   (per-creative rows + person rows + members
Stripe charges (read-only) ──┘    + invariants + reconciliation)
        ↓ consumers (zero new math anywhere)
  scoreboard_view · attribution_verdicts.ladder/ladder_groups · roster_engine
  · dashboard/ads.py routes · ads_truth sweeps · resolution derivations
```

- `attribution_engine.py` — parse_tracker → dedupe_won → derived-date merge →
  tier bucketing (ad / __ig_dm__ / __unattributed__ / __ambiguous__) →
  per-metric counters WITH member lists recorded at the increment (I17) →
  invariants I1/I2/I8/I10/I17 → reconciliation vs canonical anchors.
  In-process cache: 30-min TTL, keyed (w0,w1,basis,market), PER WORKER (×2
  gunicorn) — the root of F1/F6 staleness findings.
- `roster_engine.py` — THE cellspec→roster path (level×key×metric×window×clock
  ×market). Every people-list surface consumes it. I17: len(people)==cell.
- `attribution_verdicts.py` — verdicts + `ladder_groups()` = the ONE grouping
  path for Names/Batches/Campaigns/Account (rosters + ladder share it).
- `resolution.py` — derive-never-invent date engine: journaled
  `record_derived_date` / `supersede_derived` (source wins, disagreement
  surfaces) / P1-P2 cards / `apply_payment_class_ruling` (#131).
- `ads_truth.py` — spine census, reached sweep, event sweep, show verification,
  quad-check, nightly `integrity_sweep` (+I17 20-cell sampling), Edith accuracy.
- `dashboard/ads.py` + `adsapp.js` — render + drill only (I16 view purity).

## Conventions (DECISIONS refs — all re-verified live)

- #111 first-touch attribution; last-touch counted, never blended (drill B3:
  the FT creative owns rows AND closes; LT gets no row).
- #118/#120 tracker authority · one clock per view (I11).
- #126 ads-truth loop · #127 market filter I15 + interaction layer ·
  #128 date conventions (set=booked, show=scheduled+evidence, input=created,
  close=signed) · #129 show tiers (verified/unverified) ·
  #131 payment-class close-date auto-derivation (Stripe email-exact AUTO; GHL
  stage PROPOSED forever; 10 live conversions, $30,983, charge ids journaled;
  duplicate-dated guard `9db5b7d`).

## Integrations + scopes (live-probed 2026-08-08)

| Source | State |
|---|---|
| GHL | contacts/appointments/conversations readable; **payments/orders, payments/transactions, invoices → 401** (no payment rung exists) |
| Stripe | read-only rk_ key on Railway; charges readable (pagination partial-failure = F9) |
| Meta | entities + spend live; degradation currently invisible on /ads (F5) |
| Xero | report scopes only; Invoices 401 — **re-consent still pending on Rydel** |
| Postgres | kv_store + mirrors + attr_contacts; Railway-internal (local runs CANNOT reach it — probe via `railway ssh`, `/opt/venv/bin/python`) |

## Invariants

I1/I2/I8 funnel coherence · I10 tier partition · I11 clock purity · I13 single
computation path · I14 no orphan badges · I15 market partition · I16 view
purity · **I17 roster-cell equality** (members at increment; suite sweep +
build check + nightly 20-cell sample; live full sweep 2026-08-08: 18,744 cells,
0 drift).

## Jobs + cadences (verified wiring)

- `attribution_engine.start_loop()` (app.py:834): every 6h — compute refresh +
  close_integrity/bas/voice/memory/convo ticks + `ads_truth.nightly_tick()`
  (kv-stamped daily; **stamp written after the 76s sweep → double-run race =
  F16**). Boot does NOT tick immediately (first tick = boot+6h).
- Rollup layer: `attr:rollup:<basis>:<days>` persisted boards; stale-labelled
  serves + background refresh + adjacent-window prefetch (incl. All).
- Nightly sweep duties: invariants both clocks × 3 windows · spine census ·
  quad-check 90d closes · reached sweep (≤30) · date resolution + #131 rung ·
  event sweep (≤40) · show verification (≤40) · I17 sample (20) · accuracy row.

## Known limits (honest, current)

- F1: roster/drill cold path 5.7–15.8s (cache TTL/worker split) — wave fix.
- F5: `degraded[]` not rendered on /ads → $0-spend illusion under Meta failure.
- F6: derivation writes don't invalidate caches → ≤30min stale-as-fresh after
  a card apply.
- F2: autofix journal horizon ≈2 days (200 cap) — evidence retention at risk.
- F8: GHL-derived set/show dates use the UTC day (morning-Sydney bookings derive
  a day early).
- Date coverage: sets 156/245 dated (63.7%) · closes 58/67 (86.6%) · inputs
  1113/1114. Queue: 4 stage-only P1 + 4 H1 + 1 P2 + 37 set-multi + 3 attendance.
- verified_show_ratio 0.857 and falling as status-only shows derive — needs the
  sentinel trend watch (F15).
- All 4 supersessions to date DISAGREED with the source (n small; watch).
- Cross-service note (NOT touched): the timeline repo consumes some of the same
  GHL data — any ID-semantics change must be coordinated, own session.

## Security posture

All /ads + /cfo surfaces auth-walled (matrix in artifact 05); sales fail-closed
allowlist; media_buyer shipped-disabled (live env probe); **/debug/* fully
X-CFO-KEY-gated as of `45670b7`** (F4 hotfix — anon MRR exposure closed,
permanent sweep test). Open: F12 reflected-XSS via ?roster= (wave).

## Sentinel (designed, NOT yet built — post-gate Phase H)

L0 inline guards → L1 hourly (recon identities + I17 n=5 + delta-anomaly) →
L2 nightly (existing sweep + drift diff + cost row) → L3 weekly (full I17 +
claims sample + security replay + perf regression). Self-heal boundary:
deterministic data-layer only, journaled; kill switch env
`AD_SENTINEL_PAUSE_HEALS`; escalations + judgment items → SENTINEL-QUEUE.md.
