# PROMPT LEDGER — the 37 briefs since the August handoff

Status assigned by **verified presence** (a module, a route answering on the
live app, a DECISIONS entry, an artefact), never by a document's claim.
Verified 2026-09-21 against commit `acf0172`.

## NOT RUN / PARTIAL first — what's missing

| # | brief | status | evidence | what's missing |
|---|---|---|---|---|
| 33 | DASHBOARD-UX-OVERHAUL | **NOT RUN** | no TODAY page exists (`grep TODAY dashboard/templates` → 0); no jobs shell; the SALES page at `/dashboard/sales` → **404** (the `sales.html` that exists is the lead-reactivation view at `/dashboard/leads`, from brief 12) | the jobs-to-be-done shell, the TODAY page, the named design system, the SALES page. #152's area pages cover part of the IA intent, not the shell |
| 4 | SHOW-TRUTH-XERO-RUNG | **PARTIAL** | show truth shipped — `ads_truth.py` T1/T2/T3 ladder + DECISIONS #129 "attendance requires evidence"; the verified/unverified split is live and is what Part A1 of this run built on | **the Xero rung is not in the ladder** (`grep -c xero ads_truth.py` → 0). Cash evidence lives in `xero_pull.py` but was never wired as a rung of the show/close evidence ladder |
| 36 | SIMULATOR-V3-BIDIRECTIONAL | **PARTIAL** | `sim_core.requiredSpend()` solves counts → spend for all five goal kinds (leads/calls/clients/cash/MRR), proven by the behaviour gate | **no solve for a required RATE**: you cannot ask "what close rate do I need to hit 8 clients at this spend". Counts go both ways; rates only forward |
| 17 | AD-TRACKING-TEAM-ONBOARDING | **SHIPPED (STALE — flag)** | the document exists and was delivered | it teaches the **retired** creative-rotation model; superseded by #147 (R-A2 continuous ad sets). The doc now teaches something the system no longer does — it needs a rewrite or a retirement note |
| 19 | EDITH-VOICE-FIX | **SUPERSEDED** | by brief 20 / DECISIONS #142 (key rotated, scoped-key class) | nothing — intentionally replaced |
| 16 | FINANCE-DASHBOARD-IA | **SHIPPED, then SUPERSEDED in part** | DECISIONS #139; `/dashboard/worklog` + `/dashboard/bookkeeping` both answer (302 auth) | the landing-page cards it introduced were replaced by #152's server-rendered summary cards — the pages themselves still stand |

## The rest — SHIPPED, with evidence

| # | brief | evidence (verified presence) |
|---|---|---|
| 1 | ADS-TRUTH-ENGINE | `ads_truth.py` (T1/T2/T3 spine, `ads_truth:flags`, `ads_truth:proposed`); DECISIONS #126 |
| 2 | ADS-UX-DRILL-DEPTH | DECISIONS #127 "every number is a door"; `/ads` answers (308→auth); `adsapp.js` |
| 3 | ADS-FUNNEL-COMPLETION | DECISIONS #128; `attribution_engine` date-resolution + sets/shows in the funnel |
| 5 | ROSTER-ENGINE | I17 enforced — `test_travelling.py::test_i17_count_equals_roster_on_every_stage`; rosters on every travelling stage and in `/ads` |
| 6 | ADS-EXTREME-AUDIT-SENTINEL | `ad_sentinel.py` (L0–L3, `security_replay`); `SENTINEL_QUEUE.md` is the judgment-work register |
| 7 | AUDIT-GATE-CLOSE | DECISIONS #131/#132 (F1–F16, the resolution doctrine); kill switch `AD_SENTINEL_PAUSE_HEALS` |
| 8 | LAUNCH-LINEAGE-DATE-CONTROL | `launch_lineage.py`; DECISIONS #133 |
| 9 | CONSULT-DATETIME-RANGE-SWEEP | `consult_schedule.py` (offset-less Sydney parse, rebook chain); DECISIONS #134 |
| 10 | RANGE-SPEED-FLOW | DECISIONS #120 (one clock per view, invariants, speed); daily-grain buckets in the ads queries |
| 11 | RENEWAL-CHURN-LOOP | DECISIONS #135; the declare/scan flow on the projection page; `client_overrides` |
| 12 | ADS-ACCESS-DISCUSSION-PREVIEWS | DECISIONS #136; `ads_discussion.py`; ad_domain scoping in `dashboard/auth.py` |
| 13 | TIMELINE-HARDENING | **verified by the one allowed external check**: anonymous `GET https://timelinedashboard-production.up.railway.app/api/overview` → **401** |
| 14 | PIOLO-QUEUE-FIX | DECISIONS #137 (evidence-signature dismissals, relevance gating) |
| 15 | META-RETENTION-FIX | DECISIONS #138; `meta_spend` permanent archive + clamp/chunk |
| 18 | SCOREBOARD-CONTRACT-VALUE | DECISIONS #140 (date-range binding + contract value) |
| 20 | EDITH-VOICE-RESTORE | DECISIONS #142; `voice_health.py` boot canary; voice is opt-in since #152 |
| 21 | AD-LIFECYCLE-BOARD | `ads_lifecycle.py`; DECISIONS #144 (move rights) + #145 (stances are opinions) — reworked by brief 27's R-A2, the board survives |
| 22 | STATUS-SORT-TRUTH-SWEEP | labelled status handling in `ads_lifecycle.py` (65 status references); ground-truth sweep in `ads_truth` |
| 23 | SHIP-NOTES-SKILL | the skill was delivered as a capability, not repo code — **flagged as unverifiable from the repo**; treated as delivered, not as shipped code |
| 24 | FORWARD-MRR-PROJECTION | `forward_projection.py` (committed/assumed, slider-immune committed); the projection page |
| 25 | OUTFLOW-TRUTH-STRIPE-HEALTH | `outflow_bands.py`, `stripe_health.py` (`feed:extra:stripe` canary) |
| 26 | CSM-INVESTMENT v2 | DECISIONS #146; `csm_model.py`, `csm_baselines.py`, `csm_plan.py`, `csm_docs.py`; `/dashboard/csm` answers |
| 27 | STRATEGY-MIGRATION-AD-SETS | DECISIONS #147 (R-A2 continuous ad sets) |
| 28 | FINANCE-CURRENCY-GAP-ANALYSIS | DECISIONS #148 (READ-ONLY LAW) + #149; `gap_reconcile.py`; the gap window is still open and labelled |
| 29 | DATA-SCRUTINY-UNIT-ECONOMICS | DECISIONS #150; `tile_drawers.py`, `receivables.py`, `finance_tabs.py` |
| 30 | VISIBILITY-FIX-LTV-CAC | DECISIONS #151; the ratios are exec tiles; AR internal-only grep test |
| 31 | DASHBOARD-HARDENING | DECISIONS #152; `dashboard/exec_top.py`, `render_health.py`, `scripts/render_gate.py`, evidence folders |
| 32 | SCALING-COMPASS | DECISIONS #153; `compass_engine.py`; `/dashboard/scale` answers |
| 34 | EXPLAIN-SIMULATE-SIMPLIFY | DECISIONS #154; `dashboard/definitions.json` (184 entries, 100% coverage), `defs.js`, `/dashboard/definitions` |
| 35 | SIMULATOR-FIX-NORTH-STAR | DECISIONS #155; `sim_core.js`, `scripts/behaviour_gate.py`, the LOGIC VERIFIED badge |
| 37 | TRAVELLING-VS-TARGET | DECISIONS #156; `travelling.py`, `/dashboard/scale/travelling` answers |

**Totals: 30 SHIPPED · 3 PARTIAL · 1 NOT RUN · 1 SUPERSEDED · 1 SHIPPED-but-stale · 1 unverifiable-from-repo.**
