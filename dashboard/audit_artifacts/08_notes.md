# GATE-CLOSE ARTIFACT 08 — live migrations + prod measures (2026-08-09, deploy 527794d)

## F8 re-derivation (08_live_migrations.json)
72 derivations checked (58 ghl-appt + 4 contact-created + 10 stripe-charge):
**22 changed** (15 set_date + 7 show_date — every one +1 day, the UTC→Sydney
class), 50 unchanged (incl. all 10 stripe close dates — no drift found there),
0 evidence gaps, **0 window-boundary crossings**. Journaled per date with
evidence id + reason F8-sydney-day (now 22+ entries in the durable
resolution:journal). IDEMPOTENT: second run changed 0. Reconciliation green
after apply (recon: true, degraded: []).

## F16 accuracy de-dupe
5 rows → 3 (the two doubled dates collapsed, last-wins). Idempotent: 0 on rerun.

## Live measures (08b_prod_sweep_and_perf.json)
- FULL I17: 4,344 cells (2 clocks × 30/60/90 × all rows × 6 metrics), 0 drift, 36.2s.
- COLD roster (engine cache cleared, rollup slice populated): **0.172s served
  from the rollup, stale-labelled** — budget 500ms; pre-fix 5.7–15.8s. Warm
  second read 0.064s.
- First prod integrity sweep post-deploy: 18/18 agreements on close facts,
  0 invariant violations, spine 18 T1 / 0 T0, I17 sample 20/20 clean,
  **15 stale invariant alerts self-retired (F3)** → integrity_pending 38 → 25,
  orphan census 0.
- FIRST SENTINEL COST ROW: L2 runtime 95.21s · 73 API calls vs budget
  240s/130 — within budget, recorded in the accuracy row + kv sentinel:cost.
- #133 watches (peer's): launch_lineage 155 ads / 0 pending probes / 0 missing
  days; clock_label ok on the sampled range.
- External security probes on the live domain: /debug/stripe-ping 401 ·
  /debug/sources 401 · crafted ?roster= metric → 401 at the auth wall, zero
  payload echo (behind auth: whitelist + esc + server 400, test-proven).
