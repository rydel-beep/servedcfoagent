# PROMPT LEDGER — the 37 briefs since the August handoff

Status assigned by **verified presence** (a module, a route answering on the
live app, a DECISIONS entry, an artefact), never by a document's claim.
Verified 2026-09-21 against commit `acf0172`; **five rows re-verified against
`1b8e7a8` after the finish-line wave** (#158) — their deltas are below.

## NOT RUN / PARTIAL first — what's missing

| # | brief | status | evidence | what's missing |
|---|---|---|---|---|
| 33 | DASHBOARD-UX-OVERHAUL | **SHIPPED** (was NOT RUN) | `/dashboard/today` and `/dashboard/sales` both answer 200 on the live app; `dashboard/shell.py` + `partials/shell_nav.html` put a persistent nav on **every** page (test: `test_every_page_carries_the_nav`); `dashboard/static/css/served.css` is the named component library; DECISIONS #158 | nothing of the brief. The legacy area pages now carry the shell and the component library but their interiors still run on the older panel CSS — stated, not implied away |
| 4 | SHOW-TRUTH-XERO-RUNG | **PARTIAL — and now BLOCKED, with the exact unblock** | show truth shipped (T1/T2/T3 + #129). The scope was **probed** on 2026-09-21: the token holds `accounting.reports.profitandloss.read`, `...banksummary.read`, `...balancesheet.read` only — `Invoices` **401**, `BankTransactions` **401** | invoice/payment reads are NOT granted, so the rung cannot be built without guessing. **The unblock, exactly:** add `accounting.transactions.read` to `XERO_SCOPES` (`app.py`) and Rydel re-approves at `/xero/connect`. Registered, not blind-built (#158) |
| 36 | SIMULATOR-V3-BIDIRECTIONAL | **SHIPPED** (was PARTIAL) | `sim_core.requiredRate()` + `chainWithRate()`: typing a count into a stage solves that stage's rate with everything upstream HELD, reads "required X%, measured Y%, N points above", and flags above-100% as not achievable. Behaviour-gate steps `run_required_rate` type it into the live page and check upstream did not move, downstream became the ask, and the impossible flag fired | nothing. Rates now solve both ways, like counts |
| 17 | AD-TRACKING-TEAM-ONBOARDING | **SHIPPED (STILL STALE — could not be regenerated)** | the document exists and was delivered | it still teaches the **retired** creative-rotation model (#147). Regenerating it needed the ship-notes skill, which **does not exist on this machine** (row 23) — so the doc was not rewritten and is not claimed to be. It needs a rewrite or a retirement note pointing at #147 |
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
| 23 | SHIP-NOTES-SKILL | **RESOLVED: NOT PRESENT.** Searched on 2026-09-21 — `.claude/skills/served-ship-notes/SKILL.md` does not exist in the repo, in `~/.claude/skills/`, or anywhere under `~/Documents/CLAUDE` (the only skills directory found belongs to `youtube-engine`). It is not available to run, so brief 17's document could not be regenerated. No longer "unverifiable" — verified absent |
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

**Totals before the finish line: 30 SHIPPED · 3 PARTIAL · 1 NOT RUN ·
1 SUPERSEDED · 1 SHIPPED-but-stale · 1 unverifiable-from-repo.**

**Totals after (`1b8e7a8`): 32 SHIPPED · 1 PARTIAL (brief 4, blocked on a
Xero scope only Rydel can grant) · 0 NOT RUN · 1 SUPERSEDED · 1
SHIPPED-but-stale (brief 17, blocked on the missing skill) · 0
unverifiable — row 23 is now verified ABSENT rather than unknown.**
