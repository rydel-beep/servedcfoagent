# WAVE 1 — FORECASTING LAYER (build report)

**Date:** 2026-07-09 (Sydney) · `forecasting_engine.py` — projections with visible, adjustable
assumptions. Deterministic base (one engine); never presented as actuals.

## What shipped
1. **13-week cash-flow forecast** — weekly inflow (Stripe trailing-30d cash run-rate + expected
   new-deal cash = velocity × avg × collection rate) − outflow (engine burn + optional tax
   set-aside). Returns the week-by-week curve, the minimum week, and the drivers.
2. **MRR forecast + scenarios** — BASE (trailing velocity) / BEST (velocity +50%, attrition −50%) /
   WORST (velocity −50%, attrition ×2), 6 months. Live what-ifs ("what if churn doubles", "what if we
   close 3 more"). **Expiry-aware:** attrition = mid-contract churn + contract-expiry drag from
   `forward_mrr`, scaled by an adjustable **renewal rate** (default = historical, currently **0%**).
3. **Dynamic runway** — from the cash-flow forecast (incorporating inflows) alongside the conservative
   static runway. Surfaces the key insight: the business is **cash-positive**, so static runway
   (cash÷burn) badly understates the position.
4. **Honesty architecture** — every output labelled PROJECTION; assumptions (inflow, collection rate,
   closes/mo, churn/mo, avg MRR, renewal rate, tax set-aside) adjustable by voice ("set renewal rate
   to 50"); confidence from small-sample flags; separate from actuals.
5. **Forecast accuracy tracking** — `record_projection` / `grade_projection` / `accuracy` (kv_store):
   projected-vs-actual + running bias ("my last N MRR forecasts ran +X% optimistic").

## The honest picture it surfaces (live)
- **Cash:** cash-positive ~+$55k/mo — cash GROWS $172k → ~$336k over 13 weeks; no tight week. Static
  runway (5.3mo) assumes zero inflow and understates reality.
- **MRR:** at the **historical 0% renewal**, contract expiries (~$12.7k/mo drag) OUTPACE new-deal MRR
  (~$8.9k/mo) → BASE MRR DECLINES ($63k → ~$41k in 6mo). This reconciles with the binding-constraint
  finding: retention/renewals are existential. Set a higher renewal rate to model fixing it (BEST
  case with renewals + more sales grows MRR).
- The two reconcile: cash is fine *now* (actual collections), but if the projected MRR decline lands,
  inflow tapers — flagged as a caveat on the cash forecast.

## Conversational (Tier 2, deterministic) + `/api/forecast` (owner-only)
"cash flow forecast" / "tight week" · "dynamic runway" / "are we cash positive" · "where's MRR going"
/ "best/worst case" · "what if churn doubles" / "what if we close N more" · "how accurate are your
forecasts" · "set renewal rate / collection rate / closes per month / forecast inflow to N".

## Data readiness notes (honest limits)
- No precise offer instalment schedule exists → new-deal cash modeled from velocity × avg × an
  adjustable collection rate (not exact instalments).
- Stripe subscription timing is unreliable (MCP) → recurring inflow uses the trailing-30d gross cash
  run-rate as the proxy.
- Cash forecast holds recurring inflow flat (doesn't yet taper with the MRR decline) — cross-
  referenced as a caveat; a future refinement can couple them.
