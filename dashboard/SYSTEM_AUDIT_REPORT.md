# EDITH — FULL SYSTEM AUDIT (Wave 0) — findings, plan, quick-wins

**Date:** 2026-07-09 (Sydney) · Read-only audit + surgical S1 quick-wins. Waves 1 (forecasting) & 2
(UI) are separate approved runs; ready-to-run specs at the end.

## Method
Three parallel codebase sweeps (null-key, scorecard/migration, stale/silent/fabrication) + live
runtime verification against the deployed dashboard + the consistency suite. Evidence = grep/diff/
live output, not assertion.

═══════════════════════════════════════════════════════════════
## WAVE 0A — DATA-INTEGRITY FINDINGS (ranked)
═══════════════════════════════════════════════════════════════

| # | Sev | Finding | Evidence | Regression? | Effort |
|---|-----|---------|----------|-------------|--------|
| F1 | **S1** | **Funnel display + exec summary show SCORECARD 0/0/0/0** while the tracker truth is 89 leads / 26 sets / 6 closes (30d). The exec line renders "0 leads → 0 closes". | `dashboard.js:632,676,678` read `sales.funnel.*`; live `sales.funnel = {leads_in:0,sets:0,closes:0}` vs tracker 89/6. `verdicts.py:57,61` too. | **YES** — the leads-count fix repaired the *handlers*, not the *display/verdicts*. | LOW |
| F2 | **S2** | **Greeting leads with "26 charges failed"** sourced from the Stripe MCP, which is internally inconsistent (1 active sub but $67k MRR) — likely a false alarm shown daily as the top alert. | live greeting: "26 charges failed today…"; `salience.py:84-89` salience=100; snapshot `stripe.subscriptions={active:1}` + `stripe_mrr_subs_mismatch` degraded flag. | new | LOW |
| F3 | S2 | **4 recent closes not on Health roster** (Lost Sheep, Hung's, Akuna, Bu…) → headline MRR ($63.3k) excludes them while active-count (38) includes them: a count/MRR window mismatch. | snapshot degraded `client_reconciliation`; MRR 63,302 (roster) vs 38 active. | known/flagged | MED (data-entry + surfacing) |
| F4 | S2 | **Silent churn swallow** — `capacity_engine.churn_in_window` `except: pass` returns 0 with no log/degraded, so "no churn" is indistinguishable from "data missing"; feeds hiring recs. | `capacity_engine.py` two `except: pass` in churn_in_window; `_team()` returns [] silently. | new | LOW |
| F5 | S2 | 3 Active clients with $0 MRR (Bluebells, Raama, …) — possible churn/data gap. | snapshot degraded `zero_mrr_active_clients`. | known/flagged | LOW |
| F6 | S2 | `CASH_TAX_RESERVED=$20k` and the `CASH_ON_HAND_LAST_KNOWN` env fallback lack an "as of"/staleness label if the env var is unset while Xero is down. | `config.py`; `snapshot.py` cash fallback path. | partial | LOW |
| F7 | S3 | `roster_stale_since` / `roster_source_reason` read in `metrics_engine.py:112,114` but only SET when health is down — silent None on the happy path (safe via `or` fallback). | agent sweep; `active_clients.py` conditional set. | no | TRIVIAL |
| F8 | S3 | Closer-commission May override is a dormant time-bomb (`CLOSER_MAY_OVERRIDE_ACTIVE=False` now — correct, but reverts silently if a future override isn't flipped back). | `config.py:79-80`. | no | TRIVIAL |

### Truth-check — what LANDED and holds in production (verified live)
- **One engine per metric (Pattern 4):** consistency suite GREEN (4/4); no duplicate ROAS/CAC formula survives grep. ROAS/LTGP:CAC/CAC/MRR identical snapshot==engine. ✓
- **Ad-spend migration (Pattern 3):** COMPLETE — burn, financial_position, hormozi, verdicts, metrics all read `ad_spend_resolved`; range engine correctly uses window-matched Meta spend. The prior incomplete migration is fixed. ✓
- **Outage hardening (Pattern 7):** `/health` reports subsystems; `_safe_result` fail-softs every snapshot source (logged + degraded); error banner surfaces null-snapshot. ✓
- **Fabrication paths (Pattern 8):** deterministic-recall + read-before-assert + strong HARD-LINES prompt + deterministic fallbacks gate greeting, chat, voice, salience, brief. No free-compose-a-number path found. ✓
- **Prior builds live:** greeting/salience, read-before-assert (Hung's $8,305 verbatim), capacity (190%), three-tier intent router (musing → no data dump) all confirmed on the deployed dashboard. ✓
- **MRR dual-source:** handled correctly — recognized $63.3k is the headline, Stripe $67k shown separately/labelled (not masquerading). ✓

**Verdict:** the recent hardening builds genuinely landed. The one material correctness regression is **F1 (funnel display on scorecard)**; the one active-misleading item is **F2 (failed-charges false alarm)**.

═══════════════════════════════════════════════════════════════
## WAVE 0B — UI/UX AUDIT + DECISION-ZONE PROPOSAL (design only; Wave 2)
═══════════════════════════════════════════════════════════════
**Current layout:** ~30 sections in a FLAT list, ordered roughly by data source, not by decision:
brief → exec → actions → kpis → cash-position → stripe-health → forward → trend → revenue → churn →
month-perf → waterfall → commissions → metrics → perf-analysis → speed-to-lead → funnel → setter-deep
→ health → verdicts → team → deficiency → pipeline → dq-loss → offers → lead-roi → reps → cohort →
reconciliation.

**Problems:** (a) "Am I safe" cash/runway is buried below brief/exec/actions/kpis; (b) redundancy
(exec summary repeats brief + kpis; funnel appears in exec AND its own section); (c) warnings
scattered (actions, dq-loss, verdicts, deficiency, stripe-health all carry alerts) rather than one
action feed; (d) the funnel section shows the F1 scorecard zeros; (e) no consistent per-figure
"window / as-of / basis / expand" standard; (f) mobile/390px not audited here (needs the Wave-2 pass;
the SKILL.md was not present in this environment and MUST be read before Wave 2 implementation).

**Proposed decision-zone architecture (Wave 2):**
- ZONE 1 "AM I SAFE" (top): cash on hand + states, static + dynamic runway, burn, 13-week cash curve (Wave 1).
- ZONE 2 "IS THE MACHINE WORKING": MRR + movement, unit economics (loaded CAC / LTGP:CAC / ROAS), funnel velocity (leads→sets→closes, TRACKER-sourced), capacity load.
- ZONE 3 "WHAT NEEDS ACTION": one consolidated action feed (failed/past-due, DQ flags, paid-but-unlogged, hire triggers, raise signals) — replacing the scattered warnings.
- ZONE 4 "WHERE ARE WE GOING": forecasts + scenarios (Wave 1), growth trajectory.
- Per-figure standard everywhere: window shown · as-of shown · basis labelled · breakdown on expand · one pill system (degraded ≠ failed).

═══════════════════════════════════════════════════════════════
## WAVE 0C — FORECASTING AUDIT + DESIGN (design only; Wave 1)
═══════════════════════════════════════════════════════════════
**Exists today:** static runway (cash ÷ burn = 5.3mo); `forward_mrr` (RECOGNIZED-tab month-to-month
floor projection); `hiring_model._compute_forecast` (3-month, growth-rate based). **Limits:** static
runway ignores projected inflows; no week-level cash timing; no scenarios/what-ifs; no accuracy tracking.

**Design (Wave 1):**
1. **13-week cash-flow forecast** — week-by-week: known inflows (contracted instalments per offer
   payment schedule from the Stripe-reconciliation/`payback` data; subscription charge timing;
   expected collections from recent closes) − known outflows (payroll incl. PHP FX, subs, ad
   run-rate, BAS/tax set-asides). Output: the curve, the minimum week, the drivers.
2. **MRR forecast + scenarios** — current MRR + net velocity (closes×avg − churn) over 3-6mo under
   BASE/BEST/WORST (Rydel-adjustable deltas); conversational what-ifs ("what if churn doubles?").
3. **Dynamic runway** — from the cash-flow forecast, shown alongside the conservative static runway.
4. **Honesty architecture** — every projection labelled PROJECTION, assumptions visible + adjustable
   (manual-inputs), confidence bands from input volatility, small-sample flags, never presented as
   actuals.
5. **Accuracy tracking** — store each projection; when actuals land, show projected-vs-actual + a
   running bias ("my last 3 MRR forecasts ran +4% optimistic").

**Data readiness:** cash-forecast inflows need the offer payment schedules — the `payback`/Stripe-
reconcile module has the instalment/close data (Stripe per-payment key present as
`STRIPE_SECRET_KEY`). Outflows (payroll/FX/subs/ad run-rate) all available. MRR base + velocity
available (one engine). Accuracy tracking needs a new `kv_store`-backed projection log. **Buildable.**

═══════════════════════════════════════════════════════════════
## THE WAVE PLAN
═══════════════════════════════════════════════════════════════
- **QUICK WINS (this run):** F1 (funnel/exec/verdicts → tracker, one-engine) · F2 (gate the failed-
  charges false alarm) · F4 (log/degrade the silent churn swallow). All S1/high-visibility, surgical.
- **WAVE 1 (own run):** the forecasting layer per 0C (spec above is prompt-ready).
- **WAVE 2 (own run):** the decision-zone UI re-architecture per 0B + the 390px responsive pass
  (read SKILL.md first).
- Deferred/data-entry: F3, F5 (roster reconciliation — surface louder; largely a bookkeeping action).
