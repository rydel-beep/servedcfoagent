# STATUS — served-cfo-agent session log

## 2026-08-08 — Roster engine + payment-class ruling (#131) + row control

1. **roster_engine.py (NEW)** — the ONE cellspec→roster path. attribution_engine
   records members at every counter increment (I17: len(roster) == cell, both
   clocks, every metric incl. anomaly classes). Consumers refactored to it:
   /ads/api/roster (all tabs + tier rows + zero cells + anomaly metrics), the
   dossier lead ledger, the JS anomaly panel — parallel person-list code deleted.
   Rosters carry identity chips (id-linked / name-match / ambiguous / tracker-only),
   name-discrepancy, event-with-provenance, funnel chips, GHL + tracker links;
   ?roster= deep links; panel sorts (event/state/cash). I17 in the compute
   invariant sweep + suite + nightly 20-cell sampling (drift = ACTION-lane loud).
2. **DECISIONS #131** — dateless-close payment-class auto-derivation: Stripe
   first-payment matched by EMAIL auto-derives blank Close Dates (journaled
   "ruling-conversion DECISIONS #131" w/ charge id; one feed notice, 7d retention;
   idempotent; nightly rung in resolve_dates). GHL stage stays PROPOSED forever;
   GHL payments + Xero rungs NOT built (both 401 at probe — zero speculative code).
   P1 cards stop generating for derived closes.
3. **Row control** — 70/150/300/All on grid + tracker tables; full-dataset
   sort/find before the slice; tier rows pinned; localStorage + ?rows= state.
   D4 finding: no hard cap existed — ~70 was the natural 30d rollup shape.

**Files:** attribution_engine.py, attribution_verdicts.py (ladder_groups extraction),
roster_engine.py (new), resolution.py, ads_truth.py, dashboard/ads.py, adsapp.js,
ads.html, adsapp.css, DECISIONS.md, dashboard/ROSTER_DIAGNOSIS.md (new).
**Tests:** 683 passed (21 new in tests/test_roster_engine.py).

## 2026-08-07 — PD engine fixes (Master Spec v1.1 reconciliation)

**What changed (4 surgical items; send path untouched):**
1. `segments.py`: new **PD_ACTIVE** state — `pd-active` contacts suppressed from all
   marketing except campaigns registered in `PD_MACHINE_CAMPAIGNS`; precedence over
   S2 (S0/S1 still win). Post-cycle **PD_QUIET** (14-day total silence, blocks even
   pd-machine sends) then S4-WARM with a recent-completion WARM cap. Named
   approximation: month-granular `pd-completed-YYYY-MM` → quiet through day 21 of
   the following month; conductor ledger replaces this later.
2. `segments.py`: discount lock now catches **voucher** (word-boundary, both numbers).
3. `DECISIONS.md`: #129 (conductor autonomy amendment to #110 — two-gate sanctioned
   execution) + #130 (ladder amendment to #112 — PD_ACTIVE/PD_QUIET as implemented).
4. Preflight inventory note (below). The conductor itself is NOT built.

**Preflight "not in any other active Served sequence" — inventory sources (for the
conductor build):** (a) GHL per-contact active-workflow list via API, (b) the
conductor's own enrolment ledger, (c) fallback: any `seq-*` / `*-active` tag.

**Files touched:** segments.py, tests/test_email_gate_hypothetical.py, DECISIONS.md,
STATUS.md (new — this file).
**Tests:** suite BEFORE: 671 passed. Target file: 17 passed (5 new PD tests + voucher).
Suite AFTER: 676 passed (671 baseline + 5 new), 0 failures.
