# STATUS — served-cfo-agent session log

## 2026-08-17 — CSM INVESTMENT: model + measure + hold to 4x (#146)

The CSM-hire cockpit ships as the repo's FIRST owner-only domain. Suite
**1086** (from 1023; +63 across 5 new test files).

1. **csm_model.py (NEW)** — pure math core. Reproduces the Sequence-to-
   Success v2 printed figures as regression (16 checks green: per-client,
   book, floor/base/upside, loaded ~3.1x beside the source's unloaded 3.5x);
   two ROI clocks (cohort vs steady-state, never blended, test-pinned);
   4x solve = 68.7% renewal on the loaded cohort clock (between base and
   upside; Y1 4x unattainable in every scenario, stated); layer-vs-hire
   lens; funding_paths() is a pure function of owner-config inputs (no
   director constants anywhere — grep-asserted); comp accrual table with
   90-day clawback.
2. **csm_baselines.py (NEW)** — Gate-0 B1–B5 from data with measured/
   placeholder labels: B1 term-length-aware renewal (survivorship-BOUNDED —
   the first run read 100% because churned clients weren't in the stores;
   now the known-churned list bounds the rate and the label says so);
   in-term completion from cash/contract on ended terms; B2 refund split
   (Xero line total + Stripe per-charge evidence; remainder FLAGGED —
   transaction-level Xero is a registered dependency); B3 expansion
   (step-up proxy from repeat won-deals; product lines don't exist yet —
   placeholders retained, declarations measure forward); B4 dated book
   ledger (kv, join/leave events) + owner tiers + second-CSM trigger +
   workload preview; B5 DQS proxy from the bridge (labelled proxy).
3. **Declarations** — DOWNSELL/CONTINUITY + EXPANSION (8 subtypes +
   first-6-month value) join the ONE #135 flow: preview/apply branches,
   convergence semantics (one-off expansion = cash, converges by
   definition), Piolo edit text (unknown kinds now LOUD, never wrong),
   projection additive stream, roster apply, watch clearing (downsell =
   decided outcome), dialog + Mark-continuity inline button.
4. **csm_plan.py (NEW)** — the domain hub: masked-journal owner config
   (director figures kv-only), Gate-0 checklist (auto data ticks with
   evidence + owner human ticks), nine-risk live register, ladder calendar
   from real terms, NRR (starting cohort, mid-window join excluded —
   test), scoreboard K1–K6, comp accrual vs Xero-paid (activates at
   start), actuals overlay (baseline-rate renewals credit $0 — test),
   scenario publish (M8 overlay — the projection panel note, labelled
   what-if), EDITH drill + owner context injector, sentinel watch
   (owner-only lane, never the shared feed).
5. **Surfaces** — /dashboard/csm (7 tabs, watermark + no-screen-share
   banner, keyboard tabs, ?tab=, explain-this → EDITH narrates from the
   engine); Zone-1 owner card (ships hidden, only an owner 200 reveals —
   fail-closed, structural test); DISCREET MODE (session flag, hides card
   + overlay + shows header chip). EDITH registered on BOTH handler lists;
   CSM turns never persist to memory/distillation (either side, any
   channel — tested end-to-end through /api/chat).
6. **csm_docs.py (NEW)** — D4 CSM_ANALYSIS briefing (kv-versioned md +
   PDF, regenerable from chat or page; no director figures by design) +
   D5 candidate comp page (stripped; preflight forbidden-token proof;
   generator REFUSES on a dirty preflight — test). D6 specs in docs/:
   GHL ingestion (+ Tristan-ready task text, not created), health score,
   CSM role scope, Timeline panel outline.
7. **Sentinel** — nightly csm_watch (baseline freshness, ledger, shared-
   memory leak probe) in the owner lane + SENTINEL_QUEUE.md; weekly
   security replay now probes 8 anonymous CSM routes (any 200 = LOUD P1).
8. **SG_RATE = 0.12** — the single super-rate authority lands beside
   SUPER_BASELINE_MONTHLY (which is NOT SG-derived; never multiplied).

**Files:** csm_model.py, csm_baselines.py, csm_plan.py, csm_docs.py (new),
client_overrides.py, renewal_loop.py, forward_projection.py,
finance_sheets_pull.py, mrr_snapshot.py, xero_wages_categoriser.py,
ad_sentinel.py, dashboard/routes.py, dashboard/templates/csm.html (new),
dashboard/templates/dashboard.html, dashboard/static/js/dashboard.js,
DECISIONS.md (#146), dashboard/CSM_DIAGNOSIS.md (new), docs/CSM_*.md (new).
**Tests:** 1086 passed (63 new: test_csm_model / test_csm_declarations /
test_csm_plan / test_csm_confidentiality + existing suites green).


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
