# STRIPE MONEY-STATE ACCURACY — Phase 0 diagnosis (HARD STOP)

**Date:** 2026-06-25 (Sydney) · **Scope:** served-cfo-agent only · **Status:** HARD STOP —
the app has NO Stripe secret key, and the aggregate MCP cannot return the Balance or Payout
objects. A restricted read-only Stripe key is required before the fix. No changes made.

## 1. Every current Stripe figure + its source (all aggregate/manual — none read the real states)

| Dashboard figure | Source | What it really is |
|---|---|---|
| **"Stripe Incoming $18,000" / "+$18k in transit"** | `CASH_STRIPE_INCOMING` env constant (config.py:96, default 18000) | **MANUAL GUESS** — a hardcoded number, not a read of anything. Rendered as the "Stripe Incoming · pending payout" cash card (dashboard.js:1038) and in the cash-position one-liner (dashboard.js:361). |
| **"Stripe Cash (30D) ~$88,134"** | MCP `get_stripe_revenue(days=30)` → `stripe.revenue.current.total_aud` | **Aggregate flow** — GROSS charges collected over the trailing 30 days. A *flow*, not a money-state; it is NOT a balance or "what's in Stripe now". |
| Stripe payouts "$72,477 paid out (30d)" | MCP `get_stripe_payouts(30)` → `{total_paid_out, payout_count, period_days}` | **Aggregate sum only** — no individual payout objects, no `status`, no `arrival_date`. Cannot tell in-transit from settled. |
| Stripe MRR / active subs | MCP `get_stripe_mrr` / `get_stripe_subscriptions` | Aggregate; subs miscounted (1 "active" — known MCP defect). |
| **"Stripe Available"** | — | **Not shown at all** — there is no Balance-object read, so settled-available is absent. |
| **"In transit to CommBank"** | — | **Not computed** — needs per-payout status/arrival_date, which the MCP can't give. |

`cash_position` then builds `stripe_incoming = $18,000` (manual) and
`total_available = cash_in_bank + $18,000` — so the manual guess propagates into the headline cash.

## 2. Stripe access available to the app

- **No Stripe secret key** in the CFOagent Railway env — checked `STRIPE_SECRET_KEY`,
  `STRIPE_API_KEY`, `STRIPE_KEY`, `STRIPE_RESTRICTED_KEY`, `STRIPE_SK`: **all absent.** Only
  `STRIPE_MCP_BASE` (the aggregate MCP) is configured.
- **The MCP is aggregate-only** (re-confirmed live — 6 tools):
  `get_stripe_mrr, get_stripe_revenue, get_stripe_subscriptions, get_stripe_failed_charges,
  get_stripe_customer_count, get_stripe_payouts`. **None returns the `/v1/balance` object or
  individual `/v1/payouts` objects.** `get_stripe_payouts` returns only an aggregate
  `{total_paid_out: 72477.34, payout_count: 16, period_days: 30}` — no status, no arrival_date.
- **Therefore the app cannot read the three money states.** This is the root cause: EDITH estimates
  ($18k constant) because it has no way to read the truth. (The parallel `stripe_reconcile.py`
  hit the same wall — it degrades to `pending_mcp_tool` because the MCP has no per-charge detail.)

## 3. The gap — real vs shown (proves the discrepancy)

| Money state | Rydel's real Stripe (verified screenshots, 25 Jun) | EDITH shows |
|---|---|---|
| In Stripe, **settled** (balance.available) | **A$0.00** | not shown |
| In Stripe, **pending/incoming** (balance.pending) | **A$13,713.24** (payout arriving 26 Jun) | "$18,000 pending" (manual guess — **wrong**) |
| **Left Stripe, in transit to CommBank** (recent paid payouts not yet settled) | **$11,524.95 (25 Jun) + $4,388.55 (24 Jun) + $1,189.13 (23 Jun) + $2,820.88 (22 Jun)** ≈ $19.9k | not shown as its own state |
| Gross collected 30d (a flow, not a state) | — | "$88,134" (aggregate; fine as a flow but not a money-state) |

I **cannot read the live truth** to print exact current values, because there is no key and the
MCP can't return these objects. The figures above are from Rydel's screenshots.

## HARD STOP — what Rydel needs to add (restricted, read-only)

Create a **restricted read-only Stripe API key** and add it to the **CFOagent** Railway service
(athletic-gratitude / production):

1. Stripe Dashboard → **Developers → API keys → Create restricted key**.
2. Permissions — **Read** only on: **Balance**, **Payouts**, **Balance transactions**
   (and **Charges** read if we later want per-charge reconciliation). Everything else **None**.
   **No write permissions anywhere** (we never create/modify payouts).
3. Copy the key (`rk_live_…`).
4. Railway → CFOagent → Variables → add `STRIPE_SECRET_KEY = rk_live_…` (server-side, never committed).
5. Tell me — I then build the direct reader for `/v1/balance` + `/v1/payouts` and fix the three
   states (Phases 1–3).

Until the key is added, the honest interim is to keep the `$18,000` clearly **labelled as a manual
estimate** (it already is, with the "reconfirm" staleness flag) rather than ship another guess.

**Nothing was changed. Awaiting Rydel's key.**
