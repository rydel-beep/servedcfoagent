# STRATEGY MIGRATION AUDIT — every ghost of the 4d/$200 rotation (2026-08-24)

R-A (DECISIONS #143, the 4-day/$200 rotation) is SUPERSEDED by R-A2 (four
standing ad sets, 7–8-day review cycles, peer-relative pull candidates).
Inventory of every live artifact of the old strategy, with disposition.
Historical journals/reports keep their old-world labels (excluded ≠ deleted)
— exempt from the ghost grep, labelled below.

## Live code — REPLACE

| Ghost | Where | Disposition |
|---|---|---|
| `RULE_DEFAULTS test_days=4 / test_spend=200` + `rules()/set_rules()` (kv `ads:rotation_rules`) | ads_lifecycle.py | **Replace** → `strategy()` config (kv `ads:strategy_rules`): review_cycle_days 7 (due through 8), pull thresholds (CPL ×1.5, starved <5% ×2 cycles, zero-leads-at-≥median-share), budget-drift pct. Old kv keys orphaned (history browsable), never read. |
| `classify_stage` rotation branch (boundary_hit, `day X · $Y/$200` label, TESTING lane, kill_candidate basis=rotation) | ads_lifecycle.py | **Replace** → review-cycle classifier: RUNNING · DUE FOR REVIEW · (verdict path WATCH/SCALE unchanged) · archive. The rotation dict on cards → the review dict {cycle_day, due, injected, set_role, pull_flags}. |
| `kill_candidate_flags` (dashboard kill cards, "why is this still running?") | ads_lifecycle.py + dashboard/ads.py `_attach_lifecycle` | **Replace** → `review_flags`: "due for review: N · pull candidates: M" doors into the Session. |
| `rotation.above_test_spend` spend-band flag | ads_lifecycle.py | **Retire** (the band concept dies with the absolute threshold). |
| `/ads/api/rotation-rules` GET/POST | dashboard/ads.py | **Replace** → `/ads/api/strategy` GET/POST (+ set-mapping endpoints). |
| Move target `kill` → `marked_to_kill` | ads_lifecycle.py DECISION_STATES | **Relabel** → `pull` → `marked_to_pull` (mechanics unchanged: mandatory reason, convergence on Meta-paused, ageing; legacy `kill` accepted as an API alias, stored as pull). Historical decisions keep `marked_to_kill` labels + a "pre-R-A2" note at render. |
| Below-min-n friction copy "a rotation call, not a verdict" | ads_lifecycle.py + adsapp.js | **Relabel** → "a review-cycle call, not a verdict". |
| Sentinel `rules` watch (rotation-rules journal integrity) | ads_lifecycle.sentinel_watch | **Replace** → strategy-config journal integrity + review-overdue + budget-drift + set-partition watches. |
| attribution_flags comments citing the rotation boundary | attribution_flags.py | **Relabel** (comments only; the spend_no_leads rule was already retired). |

## Rendered copy — REPLACE

| Ghost | Where | Disposition |
|---|---|---|
| "Rotation rules ▾" panel (4d/$200 inputs) | ads.html + adsapp.js loadRulesPanel | **Replace** → Strategy panel: review cycle + pull thresholds + THE SET MAPPING (live adset ids/names from the entity store → four roles; owner/coo assigns; unmapped surfaced). |
| Spend-band chips (`≥$200 / <$200`, `?band=`) | ads.html #adx-band-toggle + adsapp.js bandMatches/renderStatusBar/URL | **Replace** → SET chips (All · Broad · Targeted · Graphics · Retarget · Unmapped), `?set=`. |
| Board TESTING/KILL CANDIDATE lanes + "day X · $Y/$200" card clocks + lane descriptions citing R-A | adsapp.js lanes/laneDesc/rotationLine | **Replace** → RUNNING/DUE-FOR-REVIEW lanes, review clock "cycle day X · review due day 7", set chips on cards. |
| Definitions legend "min(4 active days, $200)" | adsapp.js renderDefs (via laneDesc) + legend entries | **Rewrite** for review cycles / due / pull candidate / delivery share / set roles. |
| "rotation clock: per-ad lifetime…" hover notes | adsapp.js | **Replace** with the review-clock note. |

## Levels/tabs — ADD

Sets becomes a first-class grouping (tab beside Ads·Names·Batches·Campaigns·
Account) fed by `/ads/api/sets`: budget-vs-actual (intended ranges config;
graphics $60–70/d, retargeting $40/d, broad/targeted unset until Rydel
enters them — drift only checks configured ranges), per-set funnel,
within-set peer table, status rollup, injected count.

## Docs/DECISIONS — SUPERSEDE (never erase)

- DECISIONS #143 (R-A): **annotated superseded by #147 (R-A2)**, dated. #144
  (R-B reasons/moves) and #145 (R-C stances) carry over unchanged.
- ADS_SYSTEM_STATE.md: Board-v2 section updated to R-A2 as-shipped.
- Historical artifacts (AD_LIFECYCLE_BOARD_REPORT, GROUND_TRUTH_SWEEP_2,
  session notes, journal entries with old lane labels): **history — exempt**,
  render with "pre-R-A2" context where surfaced.
- served-ship-notes (team PDF) references the rotation → **regenerate after
  this wave** (flagged in the report; not regenerated in-session).

## Data availability (confirmed)

- Ad-set membership: `adset_id`/`adset_name` per ad in the entity map (ids
  are truth; name-parsing never used for membership). The engine already
  collects `adset_ids` per creative.
- Per-adset spend: derivable by rollup — archive is per-ad per-day; ad→adset
  via the entity map. Partition check: Σ set spend == archive account total.
- Review clock anchor: launch_lineage first-delivery; resets stored in kv
  `ads:review_clock`; sessions in `ads:review_sessions`.
