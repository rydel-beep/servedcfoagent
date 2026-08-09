# GATE-CLOSE ARTIFACT 07 — SCORECARD v0 → v1 (artifact-00 definitions, exactly)

Measured 2026-08-09. Sources: live kv probe via `railway ssh` (data-state
metrics — the wave doesn't change the data, only its handling), the merged-tree
suite (artifact 06), and sandbox perf measurement. LIVE values measured post-deploy
(527794d) — see artifact 08 for raw outputs. The scorecard is the ONLY
permitted statement of improvement; no percentages.

| Metric (artifact-00 definition) | v0 (2026-08-08) | v1 (2026-08-09) |
|---|---|---|
| Reconciliation (leads/closes/cash/spend × cohort/activity × 30/90) | all-ok (8/8) | all-ok LIVE post-migration (recon: true, degraded: []) — artifact 08 |
| Invariants I1–I17 (both clocks × 30/60/90) | all-ok live; I17 full sweep 18,744 cells 0 drift | LIVE full I17 post-deploy: **4,344 cells, 0 drift** (36.2s) + peer's custom-range sweep 2,970 cells 0 drift |
| Accuracy history | 4 rows, DOUBLED dates (08-07 ×2, 08-08 ×2), disagreements 26→1→1→1 | doubles COLLAPSED live (5→3 rows, journaled, idempotent); one row/date structural; 08-09 row: 18 agree / 1 standing disagree / 0 invariant viol + the FIRST sentinel cost block |
| Date coverage | sets 156/245 (63.7%) · closes 58/67 (86.6%) · inputs 1113/1114 | counts unchanged; F8 moved **22 dates +1 day** (15 set, 7 show; 0 window crossings; 10 stripe close dates verified unmoved) — full old→new list in artifact 08 |
| Roster link rate (identity) | exact-id ~ as artifact 05; contact→tracker hop rates stated on board | unchanged data-state (board identity block live) |
| Derived-vs-source agreement (supersessions) | 4 total / 4 DISAGREED (n small, watch) | unchanged (no new supersessions); now under the sentinel's L2 drift watch |
| Verified-show ratio | 0.857 and FALLING — **nobody watching** (F15) | 0.857 live — now a TRACKED L1 metric (decline >0.03 alerts) + L2 night-over-night drift diff |
| Grid latency (board serve) | rollup-backed, <2s warm; stale-labelled serves | unchanged mechanism + epoch-honest staleness (F6); warm check FIXED (dead 3-tuple probe → cache_fresh) |
| Drill/roster latency COLD | **5.7–15.8s** (engine build on the serve path) vs 500ms budget | **0.172s MEASURED LIVE** from the rollup slice (stale-labelled; warm second read 0.064s); engine build structurally OFF the serve path |
| Drill/roster latency WARM | 0.223s | 0.223s (path unchanged) |
| Nightly runtime + calls | ~76s observed; API calls uncounted; ran TWICE on race days | MEASURED LIVE: first cost row **95.21s / 73 API calls** vs budget 240s/130 — within budget; single-flight (F16) |
| PROPOSED depth | 5 P1 + 4 H1 + 1 P2 · 37 set-multi · 3 attendance · integrity_pending 38 | same judgment queues (sentinel-queued); integrity_pending **38 → 25 live** (15 stale invariant alerts self-retired, F3) |
| Hygiene open (flags) | 3 | 2 live |
| Journal / evidence horizon | 200-cap, oldest entry 1 day old — evidence aging out | rolling 200 unchanged + durable `resolution:journal` LIVE with 31 entries after the migrations (F8 re-derivations + sweep derivations) — cap 1000 (F2) |
| Security | /debug gated (F4 hotfix); F12 open | F12 CLOSED; LIVE external probes post-deploy: /debug/* 401, crafted ?roster= 401-walled zero-echo; weekly L3 replay standing |
| Suite | 686+2 at gate | **800 passed** merged tree (artifact 06) |

New standing capabilities (not in v0's vocabulary): derived-epoch cache
invalidation (F6) · loud degradation end-to-end (F5) · refund reporting lane
(R1/#132) · Sydney-day derivation boundary + DST tests (F8) · the sentinel
L0–L3 with budgets, targeted escalation, bounded self-heal, kill switch
(Phase H).
