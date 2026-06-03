# Hiring V2 Report — Dual-Basis Financials + Comprehensive Hiring Analysis

## Stage A: Fix Financial Contradiction

### Problem
The Team & Hiring Power panel showed contradictory numbers:
- Top strip: "MONTHLY HEADROOM -$12,752/mo" (red, implies burning)
- Current State: "Monthly net: $16,919/mo" + "Self-funding — no burn" (green)

The ~$29,671 gap equals `true_team_cost` exactly. Root cause: `snapshot.py` computed
`monthly_headroom = xero_net_profit - true_team_cost`, but Xero net profit already
includes team cost as an expense. Team cost was subtracted twice.

### Fix: Dual-Basis Financial Model

Created `financial_position.py` as the single source of truth:
- **Cash basis**: Stripe cash collected as revenue, Xero cost structure
- **Recognized basis**: Xero P&L (accounting view, service delivery timing)
- Both bases use the SAME cost figures — only revenue differs
- `headline` picks the best available (prefers cash basis)
- `hiring_context.monthly_headroom` now equals `headline.monthly_net` (no double-count)

### Files Changed (Stage A)
- `financial_position.py` — NEW: dual-basis financial model
- `snapshot.py` — Uses `build_financial_position()`, headroom = headline_net
- `dashboard/static/js/dashboard.js` — Top strip shows Cash Net + Recognized Net side by side
- `dashboard/static/js/dashboard.js` — `_renderHiringResult()` updated for new response format

## Stage B: Comprehensive Hiring Analysis

### Features Added

1. **Dual-basis current state in hiring result** — Shows cash-basis and recognized-basis
   net positions with status labels, team/MRR ratio with benchmark color coding

2. **3-month forward forecast** — Projects MRR growth and net position per month with
   hire costs factored in. Table shows projected MRR, net/mo, cumulative cash impact,
   and affordability check per month

3. **`affordable_at_month` indicator** — If a hire isn't affordable now, identifies the
   month it becomes affordable based on MRR growth trajectory

4. **Multi-role scenario modeling** — Stack multiple hires, see combined impact on net
   position, team cost ratio, MRR threshold needed

5. **Constraint context** — Surfaces the binding constraint from deficiency analysis with
   a warning: "Hiring capacity where there's no bottleneck = underutilized cost"

6. **Jarvis integration** — Chat context now includes `financial_position` (dual-basis model).
   System prompt updated to reference dual-basis and specify which basis to cite.

### Files Changed (Stage B)
- `hiring_model.py` — `compute_hiring_analysis()` accepts `financial_position`,
  `growth_rate_pct`, `binding_constraint`. Added `_compute_forecast()`, per-role analysis,
  combined impact, constraint context
- `dashboard/routes.py` — Passes financial_position, growth rate, binding constraint to
  hiring model
- `dashboard/static/js/dashboard.js` — `_renderHiringResult()` renders forecast table,
  constraint warning, affordable_at_month indicator
- `dashboard/chat.py` — Added financial_position to chat context, updated system prompt

### Privacy Verification
- Sales summary (`sales_summary.py`) accesses ONLY sales/funnel/rep data
- No financials, payroll, commissions, MRR, revenue, or CAC leak to sales export

### Test Results
- 83 tests passing
- Zero-value edge case (0 MRR, 0 revenue) produces valid JSON (no Infinity/NaN)
- Dual-basis model produces consistent numbers across all display surfaces
