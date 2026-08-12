# AD LIFECYCLE BOARD v2 — build report (2026-08-12, commit 564664f)

Rulings logged: **R-A = DECISIONS #143 · R-B = #144 · R-C = #145** (Rydel's,
logged not derived). Suite: **991 green** (+45 new: test_ads_lifecycle 37,
test_ads_board_routes 8).

## Phase 0 findings

- **Existing kill-candidate logic**: `attribution_flags.flags()` rule
  `spend_no_leads` — window-scoped, $150 default
  (`ad_flag_spend_no_leads`), **no day boundary, no lifetime awareness**.
  RETIRED and replaced by R-A: the one computation now lives in
  `ads_lifecycle.classify_stage`; the dashboard kill cards derive from the
  SAME built block (`kill_candidate_flags(block=...)`) and deep-link to the
  Board. The verdict KILL (min-n 30) is untouched and rides as the second,
  named kill kind.
- **Meta status availability**: the entity map carries `effective_status`
  per ad, which FOLDS PARENT LAYERS (`CAMPAIGN_PAUSED`, `ADSET_PAUSED`
  arrive as ad-level effective statuses under the ads_read token) — parent
  visibility confirmed without extra calls. Delivery truth = the per-ad
  daily spend/impressions archive (`meta_ad_spend_daily`, 800d retention +
  floor backfill). Blocked-enabled states (PENDING_REVIEW / WITH_ISSUES /
  PENDING_BILLING_INFO / IN_PROCESS / PREAPPROVED) map to named amber
  reasons; true learning/budget limitation is NOT visible under ads_read —
  stated honestly as "reason unknown (commonly learning or budget-limited)".
- **Discussion-store extension**: additive `stance` field on comments
  (kill/scale/hold whitelist), stance-only posts allowed, supersession
  journaled on the OLDER comment (`stance_superseded_by` + journal line).
  Existing notes unaffected (no migration needed — absent key = no stance).

## Shipped

- **1.1 Status engine** (`ads_lifecycle.status_for`): DELIVERING (impressions
  within `freshness_days`, default 2, config) · ENABLED-NOT-DELIVERING
  (reason named where knowable) · PAUSED (layer named) · `unknown` DEGRADED
  when Meta unconfigured/entity map empty/archive >26h stale — never a stale
  green. Freshness-stamped ("status as of {time} (delivery data {n}m old)").
  Renders: table "Live" column + board card accents; filter chips
  All/Delivering/Not-delivering/Paused + spend-band toggle (reads R-A
  config) on BOTH views; URL-stated (?view=&status=&band=).
- **1.2 The Board** (?view=board): lanes TESTING (progress "day X · $Y/$200"
  toward the NEARER boundary) · KILL CANDIDATE (basis-chipped rotation|
  verdict) · MARKED TO KILL · WATCH · SCALE CANDIDATE (verdict-only) ·
  MARKED TO SCALE · KILLED/PAUSED archive (collapsed details; undecided
  paused ads labelled "paused (no decision recorded)"). Cards: status accent
  + amber reason · rotation clock (lifetime, labelled) · window funnel line
  (THE scoreboard row — view parity by construction) · spend/CPL (F5
  degradation honoured) · verdict pill w/ provisional label · stance chip ·
  discussion badge · decision chip w/ reason + ageing · disagreement chip ·
  Preview ↗ · click → dossier. Moves: drag onto MARKED-* or move-menu → the
  dialog (states the meaning, REQUIRES the reason, SHOWS the card's
  opinions+stances, friction confirm below min-n) → journal + feed +
  pending chip → convergence on the next status sync.
- **1.3 Opinions on cards**: one store proven — the same comment (with
  stance) renders on the card, in the dossier Notes, the discussion panel,
  the move dialog, and EDITH. Latest-per-user counts once; changing stance
  supersedes (journaled); tombstone removes from the summary.
- **1.4 Consolidations + sentinel**: dashboard kill cards = the board kill
  lane (one block object per serve); sentinel L2 grew `lifecycle_watch`
  (status-freshness · convergence-lag >2d naming the mover · stage-drift on
  unchanged inputs-hash · rules-journal integrity · stance-summary
  integrity).

## Verification highlights (test-pinned)

- **R-A permutations exact**: day4/$150 → boundary by DAYS; day2/$200 → by
  SPEND; each × {0 leads → kill_candidate(rotation), 1 lead → watch}.
- **Below-min-n never renders SCALE CANDIDATE** (swept 0–29 leads × spends).
- **Parent layer proven**: ad on + campaign off → effective CAMPAIGN_PAUSED
  → grey "paused at the campaign layer". Meta-dead + fresh-looking delivery
  data → `unknown` DEGRADED (stale-green path closed).
- **Decision loop**: blank reason → 400 · journaled {who,when,from→to,
  reason} · feed item carries the reason + "does not control Meta" · 409
  friction below min-n · owner-only reversal (reason required) · kill
  converges on Meta-paused (journal closes, feed self-retires) · scale
  converges on a new ad id · a 3d-old unexecuted mark ages naming Romano
  (feed S2 + sentinel convergence-lag) · decision pins the lane +
  disagreement chip ("engine: scale-candidate") renders.
- **Stances**: 3 kill stances move NOTHING (lane unchanged, decision store
  empty — the auto-move path does not exist, structurally pinned: no
  `stance` token in classify/move/convergence source) · supersession counts
  once · stance whitelist 400s hostile input · hostile bodies never reach
  feed titles · EDITH drills answer with mover+reason and stances+quotes.
- **Consolidation**: `kill_candidate_flags` output == the block's
  kill-lane keys, bases named, board deep-links; decided cards leave the rail.

## PROD verification (deploy 2b22809c, probe scripts/verify_lifecycle_board.py)

- **Stores live**: 728 entities · 682 archived delivery days · refreshed 58m
  ago. (First probe on the fresh deploy caught a real seam — the lifecycle
  loaders read raw state files that Railway wipes per deploy → everything
  DEGRADED-honest but blind; fixed to the kv-seeding loaders, re-verified.)
- **STATUS TRUTH, 10 sampled ads — 10/10 exact** vs raw effective_status +
  delivery buckets: PAUSED→grey "ad layer" · ARCHIVED→"ad (archived)" ·
  **CAMPAIGN_PAUSED→"paused at the campaign layer"** (the parent-layer case,
  live) · zero recent impressions in every grey case. Freshness stamp
  carried. Account-wide: **8 delivering · 3 enabled-not-delivering · 637
  paused** — the triad separates the graveyard from the live set at a glance.
- **LANES live**: archive 637 (collapsed) · kill_candidate 4 · watch 1 ·
  testing 6. Real testing cards: "day 3 · $87/$200", "day 3 · $42/$200".
  Real rotation kills: "day 11 · $595/$200 · 0 lifetime leads", "day 6 ·
  $157/$200 · 0 lifetime leads".
- **Consolidation live: `consolidation_ok: true`** — kill cards ==
  kill-lane keys, exactly, from the same block object.
- **EDITH live**: "why did we kill Retargeting NEW VSL" → "No human decision
  is recorded… The engine's read: archive — paused at the ad (archived)
  layer" (honest, no fabricated mover). Team-think drill → honest empty.
- **Sentinel first run**: status_freshness ok (1.0h) · convergence_lag [] ·
  **stage_drift []** (zero, render vs recompute) · rules ok · stance
  integrity 0/0 · runtime 0.12s (well inside L2 budget).
- **Perf**: all-time leg 0.084s (rollup-served) · lifecycle block build
  0.030s · sentinel watch 0.12s — the board attach adds ~0.11s to a serve,
  inside the grid budget; status refresh rides the existing TTL/background
  loaders (non-blocking).
- View parity is structural: board cards render THE scoreboard rows
  verbatim (no transform path exists in adsapp.js — grep-checkable), so
  card numbers == table numbers for any window/clock by construction.

## Accepted limitations (stated, not hidden)

- Scale-mark convergence: budget raises are invisible under ads_read —
  auto-converges only on duplication (new ad id); otherwise a human
  "confirm executed" (journaled). The dialog states this.
- True "learning phase / budget-limited" amber sub-reasons are not exposed
  by the Graph API at this scope — rendered as an honest "reason unknown".
- Board lanes use LIFETIME evidence (ALL_DAYS engine leg); with the table on
  a narrow window a card can show 0 window-leads while sitting in WATCH on
  lifetime leads — both clocks are labelled on the card by design.

## Also fixed in passing

- `tests/test_meta_retention.py::test_spend_in_range_sums_archive_past_the_floor`
  had an unpinned rolling-floor clock (failed on any run after 2026-08-10);
  the floor's TODAY is now pinned like the rest of the test.
