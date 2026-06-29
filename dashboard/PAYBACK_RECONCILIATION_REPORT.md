# TRUE PAYBACK via Stripe payment reconciliation

**Date:** 2026-06-29 (Sydney) · READ-ONLY Stripe · PII-safe (emails server-side only, never output/logged)

## Phase 0 — access / matching / offer assessment

| Prerequisite | Status | Detail |
|---|---|---|
| Stripe per-payment access | ✅ | Existing `rk_live` restricted key reads charges / payment_intents / invoices / subscriptions / customers + Search API (all 200). No new key needed. |
| Offer type captured | ✅ | "Offer Sold" col 26 populated: Scale Engine ×4, Scale Engine Split ×3, Growth Pro ×3 (10 closes since Apr 1). |
| Deal → Stripe matching | ⚠️ | email-exact 4/10 + Stripe name-search 1 = **5/10 (50%)**. Chain proven (Deepa→$8,305 close-day; Lucas→$3,355 close-day). Tracker contact email often ≠ Stripe billing email; some closes not in Stripe. |

**Decision (Rydel):** build now + emit the unmatched list as the action list (engine correct; per-offer
firms up as the deal↔Stripe link improves).

## The engine (`payback_reconciliation.py`)
- **Stripe timeline:** per matched customer, succeeded **charges** only (subscription/instalment
  charges appear here too — adding invoices would double-count), refunds subtracted → `[(date, $AUD)]`.
  Non-AUD flagged.
- **Matching (confident or flagged):** email exact (high) → unambiguous Stripe name-search (medium) →
  else **unmatched/excluded + listed**. Never fabricated. PII: email used only here, never returned.
- **Per-deal payback:** cumulative collected cash from close until it crosses the **loaded CAC per close**
  (ad + closer + setter ÷ closes, from the range engine — not bare ad spend). Pre-close deposits count.
  Never reaches CAC → **"ongoing (>N days)"**, not a false finite number.
- **Per offer:** median/avg payback over recovered deals, **small-sample flagged (<3)**; ongoing counted
  separately. **Blended** shown alongside (labelled — it masks the per-offer spread).
- **Range-aware:** any close window (default last 90d), CAC window-consistent with the range engine.

## Surfaced
- `GET /dashboard/api/payback?days=N` (or start/end) — full per-deal + per-offer + unmatched.
- Voice/text: "payback on Growth Pro", "payback by offer", "how long until a Scale Engine deal pays
  back" → per-offer median with real-Stripe-timing label + small-sample caveat + unmatched count.
- Freshness: reads live Stripe + the mirror; "as_of"; Stripe failure surfaces loudly (degraded).

## What Rydel still needs (to lift match rate ~50% → ~100%)
The unmatched list is the action list. Best fix: capture the **Stripe customer id** (or align the
tracker email to the billing email) at close — then every close reconciles and per-offer payback
becomes robust. 265 tests pass (+7).
