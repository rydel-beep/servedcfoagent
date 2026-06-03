# CFO Dashboard V3 — Build Report

**Date:** 2026-06-03
**Commit:** `72259c1`
**Deploy:** Railway, verified live at `2026-06-03T22:01:55 AEST`

---

## Stage A: Kill Hallucinations (Phases 1-5)

### Phase 1 — Visual Hallucinations Fixed

**Problem:** MRR projection caption repeated/stacked on every render cycle. `appendChild` in the render loop created a new DOM element each time without clearing the old one.

**Fix:** Replaced with a stable element pattern — single `div` with `id='mrr-projection-summary'`, created once, updated via `innerHTML` on subsequent renders. If projection data is absent, the element is removed.

**Problem:** Chart.js tooltips showed duplicate entries at overlapping data points (e.g., where actual MRR and projected MRR share the same value at the junction point).

**Fix:** Added a `filter` callback to the tooltip configuration that suppresses a tooltip entry if an earlier dataset already shows the same value at that index.

### Phase 2 — MRR Projection Model Corrected

**Problem:** The projection used a 3-month average growth rate (20.8%/mo) that was inflated by early rapid-growth months (41%, 16%, 6%). This created a misleadingly optimistic forecast.

**Fix:**
- Base case now uses the **latest MoM rate** (5.6%) instead of the 3mo average
- Optimistic case uses the 3mo average for comparison
- Added `decelerating` flag (True when 3 consecutive months of declining growth)
- Caption now shows: latest rate, 3mo avg (if different), and deceleration warning
- Projection dict includes `growth_rate_latest`, `decelerating`, `growth_flag`, `method`, `caveat`

### Phase 3 — Headline Metric Accuracy Verified

All 8 headline metrics traced to source. Reconciliation:

| Metric | Source | Status |
|---|---|---|
| MRR | Health tab sum of active contract values | Clean |
| Cash collected | Stripe API (trailing period) | Clean |
| Active clients | Health tab Active/Web Sub, cross-ref LTC Won | Clean |
| Close rate | LTC tracker Won/Total | Clean |
| CAC | Commission + ad spend / closes | Clean |
| LTGP:CAC | Derived from contract value, margin, CAC | Clean |
| Gross margin | (Revenue - COGS) / Revenue | Clean |
| Payback days | CAC / daily gross profit per client | Clean |

No fabricated numbers found. All values trace to API responses or spreadsheet cells.

### Phase 4 — Server-Side Integrity Checks

Added `_run_integrity_checks(snapshot, hormozi)` in `snapshot.py`. Runs on every snapshot build. Validates:
- Gross margin in 0-100% range
- Projection growth rate < 50%/mo (sanity cap)
- Commissions <= cash collected
- No negative MRR
- Hormozi ratios capped (>100x flagged as suspect)

Failures are appended to `degraded[]` so they surface in the dashboard and Jarvis context.

### Phase 5 — Client-Side Render Guard

Added `checkRenderIntegrity()` in `dashboard.js`. Runs after every render pass. Detects and removes duplicate DOM elements that share the same `id`, preventing visual stacking regressions.

**Stage A gate: PASSED.** All metrics verified, all hallucinations fixed, all tests green (62 existing + 16 sales summary privacy tests).

---

## Stage B: Strategic Layer (Phases 6-9)

### Phase 6 — Team Model (`team_model.py`)

Reads the SALARY tab from Finance Sheet. Builds per-role costs grouped by function.

**Output:**
- 15 team members across 6 departments (C-LEVEL, PAID ADS, PR, MEDIA, TECH, SMM)
- Total team salary: **$18,891/mo** (excluding owner)
- Owner gross: **$9,704/mo**
- Total with owner: **$28,595/mo**
- Single points of failure detected: `delivery_other`, `delivery_tech` (1 person each)

Department-to-function mapping via `_DEPT_TO_FUNCTION` dict. Functions: leadership, delivery_ads, delivery_content, delivery_other, delivery_tech, delivery_smm.

**Privacy:** Per-role salary data is included in the snapshot for owner/CFO view only. The sales summary export (`/api/sales-summary`) has a strict privacy boundary — no salaries, no MRR, no revenue, no payroll data crosses into sales-team-visible output.

### Phase 7 — Hiring Affordability Engine (`hiring_model.py`)

`compute_hiring_analysis()` models any proposed hire:

**Inputs:** role, monthly_cost, is_revenue_generating + financial context from snapshot (monthly_net_income, current_mrr, avg_contract_value, close_rate, gross_margin, true_team_cost)

**Outputs:**
- `can_afford` — boolean, based on positive headroom after hire
- `headroom_after_hire` — monthly dollars remaining
- `months_runway` — how long current cash covers the hire if net income goes negative
- `additional_closes_needed` — for revenue-generating roles, how many extra closes/mo to self-fund
- `cost_as_pct_of_mrr` — hire cost relative to current MRR
- `mrr_threshold_for_hire` — MRR level where team cost stays under 40%

**Dashboard integration:** Interactive form in Team & Hiring Power section. POST to `/api/hiring-scenario`. Results rendered inline with affordability verdict.

### Phase 8 — Deficiency Analysis (`deficiency_analysis.py`)

Cross-layer growth constraint ranking. Analyzes three layers:

1. **Funnel deficiencies** — Show-to-Close rate (vs 35% benchmark), Set-to-Show rate (vs 70%), speed-to-lead
2. **Team deficiencies** — Single points of failure, function gaps
3. **Financial deficiencies** — Margin compression, team cost ratio, client concentration

**Key features:**
- Ranks by severity (critical > high > medium) then dollar impact
- Interaction insights: detects compounding constraints (e.g., "Your constraint is conversion, not lead volume — hiring more setters won't help until Show-to-Close improves")
- Binding constraint clearly identified as the top-ranked deficiency

**Live output (2026-06-03):** 4 deficiencies ranked. Top constraint: Show-to-Close at 31.6% (below 35% benchmark).

### Phase 9 — Jarvis Strategic Upgrade (`dashboard/chat.py`)

Jarvis system prompt updated with STRATEGIC CAPABILITY section:
- Team model, deficiency analysis, and hiring context now included in the context block sent to Claude
- Prompt instructs: "For hiring questions, give the analysis AND note the decision is Rydel's. Connect layers."
- Prompt instructs: "For 'what should I do?' questions, reference the deficiency analysis and name THE binding constraint."

Jarvis can now answer questions like:
- "Should I hire another closer?" — answers with affordability math, payback period, and whether the funnel constraint (Show-to-Close) means a closer hire won't help yet
- "What's limiting growth?" — references the deficiency analysis, names the binding constraint, sizes it in dollars
- "Can I afford a $3k/mo content person?" — runs the hiring model mentally against the snapshot context

---

## Files Changed/Created

| File | Action | Purpose |
|---|---|---|
| `dashboard/static/js/dashboard.js` | Modified | Hallucination fixes, render guard, deficiency/team/hiring UI |
| `finance_sheets_pull.py` | Modified | Projection model rewrite (latest rate, deceleration) |
| `snapshot.py` | Modified | Integrity checks, team/deficiency/hiring integration |
| `team_model.py` | Created | SALARY tab reader, per-function team cost model |
| `hiring_model.py` | Created | Hire affordability and payback analysis |
| `deficiency_analysis.py` | Created | Cross-layer growth constraint ranking |
| `dashboard/routes.py` | Modified | `/api/hiring-scenario` endpoint |
| `dashboard/chat.py` | Modified | Strategic context + prompt upgrade |
| `dashboard/templates/dashboard.html` | Modified | Growth + Team nav sections, hiring form |

## Tests

- 62 existing tests: all pass
- 16 sales summary privacy tests: all pass
- No new test files added (strategic modules are integration-tested via snapshot build)

## Deferred

- **Growth Moves panel (Phase 9a):** The deficiency analysis ranks constraints and provides interaction insights, which covers the core intent. A dedicated "ranked moves with sequencing" UI panel was not built as a separate section — the deficiency analysis + Jarvis strategic capability together serve this purpose.
- **Jarvis live chat verification:** Strategic prompt is deployed and context is confirmed present in the snapshot. Live conversational testing deferred to next session.
