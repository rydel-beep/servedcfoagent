# Stage A — Accuracy Lockdown Report
2026-06-11 (Sydney)

## What this stage guarantees

Every headline number now has exactly ONE computation site, every displayed
surface reads that site, and the snapshot build **fails loudly** (refuses to
ship) if any two surfaces would show different values for the same metric.

## Architecture

- **`metrics_engine.py`** — canonical layer. `snapshot.metrics` carries one
  entry per headline metric with `value`, `kind` (FLOW per-period vs BALANCE
  point-in-time), `window`, `source` (the snapshot field path it mirrors), and
  a plain-English `definition`. Dashboard, Jarvis, PDF, and exports display
  these; none recompute.
- **`assert_consistency()`** runs on every snapshot build. It checks internal
  arithmetic invariants (burn identical on every surface, runway recomputes
  from its displayed inputs, cash-card math closes, costs equal the sheet
  totals they cite, hormozi margin IS the Xero margin, revenue views mirror
  sources verbatim, zero NaN/Infinity anywhere). A violation raises
  `ConsistencyError`: the refresh keeps the last good snapshot and logs the
  contradiction instead of shipping it.
- **Source-data disagreements** (sheet vs Stripe, scorecard vs raw rows) are
  NOT consistency failures — they surface in `degraded[]` as before. The gate
  only hard-fails on contradictions code could create.

## Stripe truth (A2) — findings & fixes

### a) In-transit cash
`cash_position` now explicitly separates:
- `cash_in_bank` — **BALANCE**, landed (owner-confirmed override)
- `stripe_incoming` — **BALANCE**, in transit: Stripe balance + pending payout,
  collected but not yet banked
- `total_available` — true near-term cash = bank + in-transit (balance + balance;
  a test asserts no FLOW is ever summed in)

The Stripe MCP exposes **no balance tool** (verified against its /tools
inventory), so in-transit remains a manual figure. The override now carries
`confirmed_date` + `confirmed_age_days`, and a degraded flag fires when the
confirmation is >7 days old. **Confirmed 2026-06-04 — already stale at
build time; Rydel should reconfirm bank + Stripe balance and set
`CASH_CONFIRMED_DATE`.**

### b) Gross vs net of fees
- `stripe.revenue.current` is now labeled **GROSS — charges collected before
  Stripe fees** (verified: the MCP returns raw charge totals; no fee data
  exists anywhere in the pipeline).
- `stripe.payouts` is now labeled **NET — banked after fees, lags collection**.
- No estimated fee deduction was added (no fee feed exists; estimating would
  violate the never-fabricate rule). The two labeled figures bracket reality.

### c) The ~$87k (Stripe UI) vs ~$62k (dashboard) gap — SOLVED
Live reconciliation on 2026-06-11:
- `get_stripe_revenue(30d)` → **$80,860 gross collected** (25 transactions)
- `get_stripe_payouts(30d)` → **$87,878.74 banked**

Stripe's "last 4 weeks" headline matches the **payout (banked, net) view**;
the dashboard card shows **gross charges collected** for its trailing-30d
window. Different concepts, offset by payout timing — not a bug in either
number, but an unlabeled comparison. Both now appear with explicit window
definitions so a cross-check against Stripe always has a matching view.

### d) CRITICAL upstream bug — Stripe MCP ignores `days`
Verified live: `get_stripe_revenue(days=7|28|60|90)` all return
`period_days: 30` with identical totals. Consequences and fixes:
- "Previous period" revenue (60d − 30d) silently computed to **$0** for as
  long as this has been broken. Now: the pull detects the dishonored window
  and sets `revenue_previous = None` + degraded flag instead of fabricating 0.
- **Needs-Rydel:** the fix at source lives in the `served-stripe-mcp` service
  (separate repo) — its handlers must honor the `days` argument.

## Reconciliation of headline numbers (fresh build, 2026-06-11)

| Metric | Value | Kind | Source | Verdict |
|---|---|---|---|---|
| Cash in bank | $140,007.29 | BALANCE | owner override (2026-06-04) | ⚠ stale — reconfirm |
| In-transit (Stripe) | $18,000 | BALANCE | manual config | ⚠ stale — reconfirm |
| True near-term cash | $158,007.29 | BALANCE | bank + in-transit | ✓ arithmetic verified |
| Monthly burn | $39,211* | FLOW | opex engine | ✓ identical on all surfaces (*local build lacks Xero ad-spend lines; Railway value will differ) |
| Runway | 3.6 mo* | BALANCE | cash / burn | ✓ recomputes exactly |
| Current MRR | $72,896 | FLOW | Health tab | ✓ matches sheet |
| Next-month MRR | $58,236 | FLOW | RECOGNIZED tab | ✓ churn cliff is real — $14.7k expiring |
| Stripe MRR | $53,971 | FLOW | Stripe MCP | ⚠ cross-check only; MCP sub-count broken (1 active sub) |
| Active clients | 34 | BALANCE | derived (Health+LTC) | ✓ single count everywhere |
| Stripe collected 30d | $80,860 | FLOW | MCP, GROSS | ✓ reconciles (see c) |
| Stripe banked 30d | $87,878.74 | FLOW | MCP payouts, NET | ✓ matches Stripe UI |
| Closer commission | $9,300 | FLOW | sheet col 20 | ⚠ 1 won deal blank — verify sheet |
| Setter commission | $0 | FLOW | sheet col 19 | ⚠ 8 won deals blank — verify sheet |
| Funnel closes | 7 | FLOW | Team Scorecard | ⚠ scorecard vs raw-row mismatch (79 vs 111 leads) — sheet hygiene, flagged |

## Needs-Rydel (data quality, cannot be fixed in code)

1. **Reconfirm cash figures** (bank + Stripe in-transit), set `CASH_CONFIRMED_DATE`.
2. **Fix the Stripe MCP service** to honor the `days` parameter (separate repo).
3. **Sheet hygiene:** blank closer commission (1 deal), blank setter commissions
   (8 deals), Pottery Green Bakers Gordon active at $0 MRR (churned?), scorecard
   vs raw-row funnel mismatch.
4. **Lark pulse (if it exists outside this repo)** must send `X-CFO-KEY` since the
   snapshot lock.

## Operational fix

The snapshot was observed 4 days stale in production (no scheduled refresh
existed). A daemon thread now refreshes every `REFRESH_INTERVAL_HOURS`
(default 6) with the staleness guard, in addition to startup refresh.

## Test coverage

`tests/test_accuracy_lockdown.py` — 20 displayed-output guardrails asserting:
consistency gate clean on a real build; canonical values literally equal their
cited source fields; burn/starting-cash/client-count identical across surfaces
(including the hiring forward lens); JSON-safety (no NaN/Inf); GROSS/NET labels
present; no fabricated prior-period revenue; no FLOW summed into balance cards;
freshness block present; window-tagged vs point-in-time separation; chat and
PDF read the same cash_position the dashboard shows; and the gate itself
raises on a planted contradiction. Full suite: **150/150 passing.**
