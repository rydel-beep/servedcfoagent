# GROUND-TRUTH SWEEP 2 — status clarity + live sort + Meta-vs-system (2026-08-12)

Deploys: `0e19731` (triad + sort) → `3b9dcfa5` (all-tiers door). Suite **997**.
Probe: `scripts/ground_truth_sweep2.py` (read-only, run in the prod container).

## 1 · The witnessed red-dash rows, decoded (Rydel's question)

Two classes produced the pre-fix render:

- **The G-series / Q326 graphic rows** (the screenshot sample): swept live —
  **24 of 25 are `PAUSED` at the ad's own layer** (effective_status `PAUSED`,
  zero recent impressions — deliberate parks), **1 is
  `NOT DELIVERING · has issues`** (`WITH_ISSUES`). Full ID table in the probe
  output (e.g. `120249238179520167` "C G3 Q326 Served Graphics July 2026 2nd
  Batc" → PAUSED). They now render those words, not a glyph.
- **The bare red dash** was the no-card branch: a table row whose creative key
  had no lifecycle record yet (fresh-deploy stores / a stale lifetime rollup
  missing newly-keyed ads). Today's sweep: **0 window rows without a card** —
  the population is empty; the branch itself now renders
  `NO STATUS · no lifecycle record` with a hover explanation. **No unexplained
  glyph survives** (structurally test-pinned).

Triad reclassification shipped with this wave (the ruling): parent-paused is
now **AMBER** — `NOT DELIVERING · campaign paused` / `· ad set paused` — the
enabled-but-dead middle state; **PAUSED (grey)** = the ad's own layer only.
Live fresh counts: **14 delivering · 74 not-delivering · 566 paused** (the
amber count grew from 3 → 74 precisely because parent-paused relics were
hiding in grey).

## 2 · Live sort — root cause + fix

- **Diagnosis**: the header WAS wired, but `sortRows` fell through to the
  generic branch reading `r['status']` — a field that does not exist on
  engine rows. Every comparison was `null == null`, so the order never
  changed (not a string-sort bug — a missing-key bug).
- **Fix**: `k === 'status'` now sorts on the classifier's ordinal
  (`status.rank`: LIVE 3 → NOT DELIVERING 2 → PAUSED 1 → unknown 0),
  spend-desc tiebreak, both arrow directions meaningful, URL-preserved
  (`?sort=status.desc`), tier rows pinned, filters respected. Structural pin:
  no string-keyed status sort path exists.
- The **Delivering filter chip** is confirmed as the one-click "show me the
  live ads" tool and is now named in the definitions legend.

## 3 · Meta account vs system (cent-exact standard)

| Box | Window | Fresh Meta total | System total | Per-ad mismatches |
|---|---|---|---|---|
| Last 7d (closed) | 07-05..08-11 ends y'day | **$997.38** | **$997.38** | **0** (spend + impressions) |
| Last 30d (closed) | 07-13..08-11 | **$9,508.01** | **$9,508.01** | **0** |
| TODAY (intraday) | 08-12 | $128.18 | $128.18 | 0 at compare time (2 impression-count deltas in a later re-pull — the intraday volatility the label now covers) |

- **Status**: forced fresh entity refresh (6.7s) then re-classified all 648
  creatives → **zero drift** vs the rendered states.
- **Archive reconciliation**: Σ per-ad vs account-level — **0.0% drift** on
  both boxes (`ok: true`).
- **Contract tile**: cohort 30d tile **$18,300 / 2 closes** — found the tile's
  door (account closes) opening on **0 people**: the #140 money tiles total
  ACROSS tiers but the door drilled the ad-ladder cell, and this window's
  closes are channel-tier. **Fixed**: new all-tiers cellspec
  `account/__account_all__`; live re-proof: door = 2 people, contract sum
  **$18,300 — exact**. Cross-clock re-proof: activity 30d = 4 closes /
  **$51,100** = the raw tracker's 3 dated closes (Sam King $18,300 · Lucas
  Cristofle $14,500 · Tony Thai $18,300) + 1 derived-dated close (Arthur
  Gruselle, contract not recorded → the `contract_missing: 1` flag, never $0).
  The apparent 2-vs-3 "mismatch" in the first probe pass was the probe
  comparing a cohort tile to an activity hand-sum — both clocks reconcile
  exactly with source.

## 4 · Real-time path

- **Stamps truthful**: "delivery data {n}m old" claim vs actual
  `refreshed_at`: 30m == 30m, and 3m == 3m on the re-run — the stamp ages
  with the data (>26h stale → the classifier refuses to classify at all).
- Forced-stale + Meta-dead drills (test-pinned): stale archive → `STATUS
  UNKNOWN` with the age named; Meta-dead with fresh-looking delivery data →
  DEGRADED, no green survives. Cadence: TTL loaders (~15–30min) + nightly;
  refresh is background, never blocking.
- **Intraday honesty shipped**: any window including today now carries the
  server-computed note ("⏳ spend includes today — intraday, not final") in
  the banner + the definitions legend (was missing — the today-as-final class
  is closed).

## 5 · Functionality smoke (since the extreme audit)

range control + clock toggle ✓ (suite: test_date_control/test_range_flow) ·
scoreboard binding + contract value ✓ (re-proved live above) · roster drills
+ consult datetimes ✓ (suite + I17 live ok) · discussion post/stance ✓ (12
route tests) · board lanes + reasoned move ✓ (staging-role drills green) ·
preview links ✓ (728/728 ads carry https links; 5 sampled) · filter chips +
spend bands ✓ (band flag engine-side) · rows control / find box ✓ (suite
structural) · Piolo queue + dashboard IA ✓ (test_finance_ia, test_piolo_queue
green in the 997) · EDITH lifecycle drills ✓ (live answers). Broken found: 1
(the money-tile door, fixed above) · registered: 0.

## 6 · Sentinel

Nightly **status-mismatch sampling** joined `lifecycle_watch`: 8 random
id-keyed rendered ads/night → fresh per-ad `effective_status` (≤8 GETs,
inside the L2 call budget) re-classified vs the rendered state — any drift is
a LOUD feed item. Joins the existing freshness / convergence-lag /
stage-drift / rules-journal / stance-integrity watches.
