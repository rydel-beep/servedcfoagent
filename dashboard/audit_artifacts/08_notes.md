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

## CORRECTION (same night, post-ship)
The 22 F8 moves above were ERRONEOUS — the GHL appointments endpoint emits
offset-less Sydney-LOCAL stamps (live format probe: 266/266 space-separated,
no Z/offset; hours cluster in Sydney business hours). The +1-day shifts came
from sydney_day()'s naive=UTC assumption applied to local stamps. Stripe (10)
and contact-created (4) classes verified correct and unmoved. Rollback data:
each entry's `rederived.old` + journal lines. Fix + re-derivation: follow-up
session (SEV1), registered in AUDIT_FINDINGS_REGISTER.md F8 correction note.

## RESOLUTION (2026-08-10, #134 — commit 2b77b03)
Corrective migration ran live: 22/22 appointment dates re-derived back (−1 day,
0 crossings), journaled "appt-local-tz (#134)", idempotent (0/72 on re-run),
epoch → 6. Post-migration full I17: 5,052 cells, 0 drift; recon green. Plus the
F2 backfill: +38 evidence-class entries (all 12 pre-partition ruling
conversions now durable in resolution:journal). Detail:
dashboard/TRIPLE_SWEEP_REPORT.md (#134 session).
