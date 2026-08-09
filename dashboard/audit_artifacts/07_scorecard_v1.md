# GATE-CLOSE ARTIFACT 07 — SCORECARD v0 → v1 (artifact-00 definitions, exactly)

Measured 2026-08-09. Sources: live kv probe via `railway ssh` (data-state
metrics — the wave doesn't change the data, only its handling), the merged-tree
suite (artifact 06), and sandbox perf measurement. Rows marked **[POST-DEPLOY]**
re-measure live after the wave deploys + migrations run (artifact 08) — the
scorecard is the ONLY permitted statement of improvement; no percentages.

| Metric (artifact-00 definition) | v0 (2026-08-08) | v1 (2026-08-09) |
|---|---|---|
| Reconciliation (leads/closes/cash/spend × cohort/activity × 30/90) | all-ok (8/8) | all-ok — unchanged by wave; suite re-proves the recon terms; **[POST-DEPLOY]** live re-check |
| Invariants I1–I17 (both clocks × 30/60/90) | all-ok live; I17 full sweep 18,744 cells 0 drift | suite-enforced incl. NEW rollup-path I17 (F1 isolation); sandbox full sweep 0 drift; **[POST-DEPLOY]** live full I17 via `ad_sentinel.full_i17_sweep()` |
| Accuracy history | 4 rows, DOUBLED dates (08-07 ×2, 08-08 ×2), disagreements 26→1→1→1 | 5 rows live (08-09: 18 agree / 1 disagree / 0 invariant viol); doubles collapse via journaled `dedupe_accuracy_history()` **[POST-DEPLOY]**; one row/date structural thereafter (F16) |
| Date coverage | sets 156/245 (63.7%) · closes 58/67 (86.6%) · inputs 1113/1114 | same data-state (the wave adds no derivations); F8 re-derivation moves ~dates, not counts **[POST-DEPLOY]** exact old→new list |
| Roster link rate (identity) | exact-id ~ as artifact 05; contact→tracker hop rates stated on board | unchanged data-state **[POST-DEPLOY]** re-read from the live board |
| Derived-vs-source agreement (supersessions) | 4 total / 4 DISAGREED (n small, watch) | unchanged (no new supersessions); now under the sentinel's L2 drift watch |
| Verified-show ratio | 0.857 and FALLING — **nobody watching** (F15) | 0.857 live — now a TRACKED L1 metric (decline >0.03 alerts) + L2 night-over-night drift diff |
| Grid latency (board serve) | rollup-backed, <2s warm; stale-labelled serves | unchanged mechanism + epoch-honest staleness (F6); warm check FIXED (dead 3-tuple probe → cache_fresh) |
| Drill/roster latency COLD | **5.7–15.8s** (engine build on the serve path) vs 500ms budget | **~0.25s projected** (rollup slice: 0.3ms sandbox max + ~33ms kv read + ~0.2s enrichment); engine build structurally OFF the serve path (test-enforced by a 6s-mocked build under a 500ms timer) **[POST-DEPLOY]** live confirm |
| Drill/roster latency WARM | 0.223s | 0.223s (path unchanged) |
| Nightly runtime + calls | ~76s observed; API calls uncounted; ran TWICE on race days | self-timed + counted per run — SENTINEL COST block in every accuracy row vs L2 budget (240s / 130 calls); single-flight (F16) **[POST-DEPLOY]** first live cost row |
| PROPOSED depth | 5 P1 + 4 H1 + 1 P2 · 37 set-multi · 3 attendance · integrity_pending 38 | same queues live (judgment work — sentinel-queued, never auto-fixed); integrity_pending 38 → expected ~23 after the first F3 retire pass **[POST-DEPLOY]** |
| Hygiene open (flags) | 3 | 2 live |
| Journal / evidence horizon | 200-cap, oldest entry 1 day old — evidence aging out | rolling 200 unchanged + durable `resolution:journal` (cap 1000) holding ALL evidence-class entries (F2); live count starts at 0 and backfills as passes run |
| Security | /debug gated (F4 hotfix); F12 open | F12 CLOSED (whitelist + esc + taint tests); weekly L3 security replay (/debug 401 + taint 400) standing |
| Suite | 686+2 at gate | **800 passed** merged tree (artifact 06) |

New standing capabilities (not in v0's vocabulary): derived-epoch cache
invalidation (F6) · loud degradation end-to-end (F5) · refund reporting lane
(R1/#132) · Sydney-day derivation boundary + DST tests (F8) · the sentinel
L0–L3 with budgets, targeted escalation, bounded self-heal, kill switch
(Phase H).
