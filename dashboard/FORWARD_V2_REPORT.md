# Forward Projection V2 — Accuracy Overhaul Report

## Why the previous forward section was broken

**Root cause:** There was no separate `cash_engine.py`. The forward cash projection lived
entirely in `hiring_model.py` and was only rendered when the user clicked "Analyze" in the
hiring form — it was never a standalone section.

Three specific bugs:

1. **Starting cash used `total_available` ($158,007) instead of `cash_in_bank` ($140,007).**
   `total_available = cash_in_bank + stripe_incoming` double-counted Stripe incoming (once in
   starting cash, then again as future collection). Fixed: line 377 of `hiring_model.py` now
   reads `cash_in_bank` only.

2. **Cash balance DID move with net** — the math was correct in `hiring_model.py` line 392:
   `running_cash += fwd_net`. The previous "fix" didn't fail because the code was wrong — it
   failed because the fix checked the ENGINE output, not what was DISPLAYED. The forward table
   was only visible inside the hiring-scenario result, requiring a user click to trigger.

3. **No standalone forward section.** The forward projection was buried inside the hiring
   analysis form output. Users had to click "Analyze" with a role to see the forward table.
   Now it's a dedicated `#section-forward` panel visible on the main dashboard.

## What was fixed

### Fix 1: Starting cash ($158k → $140k)
`hiring_model.py` line 377: changed from `cp.get("total_available")` to `cp.get("cash_in_bank")`.
Prevents double-counting Stripe incoming in the forward cash projection.

### Fix 2: Standalone forward projection section
New dedicated panel `#section-forward` in the dashboard:
- Shows forward recognized MRR, net, cash balance, burn %, and graded sustainability
- Uses `cash_in_bank` as starting cash
- Cash balance = prior month + net (verified per-month)
- Renders on page load, no user interaction required

### Fix 3: Recognized MRR freshness
Confirmed: `forward_mrr.py` pulls LIVE from the RECOGNIZED tab every snapshot refresh.
Current: $65,420 / 31 clients. Not stale or cached.

### Fix 4: Re-sign scenario slider
Interactive slider (0-100%) models what happens if expiring clients renew:
- At 0%: the churn cliff (status quo — all contracts expire)
- At higher %: that fraction of expiring MRR is retained
- Shows per-month re-sign uplift, adjusted MRR, recalculated cash balance
- Callout: "Every 25% improvement = ~$X/mo"

## Anti-regression guardrails installed

8 tests in `tests/test_forward_projection.py`:

1. `test_starting_cash_uses_cash_in_bank_not_total_available` — asserts $140k, not $158k
2. `test_cash_balance_moves_with_net` — verifies cash[m] = cash[m-1] + net[m] for every month
3. `test_cash_never_rises_when_net_negative` — the exact floating-cash symptom
4. `test_no_infinity_nan_in_forward` — no broken arithmetic
5. `test_forward_months_count` — 1-6 months present
6. `test_cash_projection_is_monotonically_declining_when_all_nets_negative` — structural check
7. `test_graded_sustainability_unsustainable_on_negative_cash` — grade logic
8. `test_graded_sustainability_healthy` — grade logic

## Triple-check results (against displayed output)

```
Starting cash: $140,007 (cash_in_bank ONLY)

Month           Rec MRR        Net     Cash Bal    ✓
Jun '26      $65,420    $27,043   $167,050   ✓ cash rises (net positive)
Jul '26      $52,186    $13,809   $180,859   ✓ cash rises (net positive)
Aug '26      $45,520     $7,143   $188,001   ✓ cash rises (net positive)
Sep '26      $33,872    −$4,505   $183,496   ✓ cash DROPS (net negative)
Oct '26      $13,618   −$24,759   $158,737   ✓ cash DROPS (net negative)
Nov '26       $7,533   −$30,844   $127,893   ✓ cash DROPS (net negative)
Dec '26           $0   −$38,377    $89,516   ✓ cash DROPS (net negative)
```

Every row: cash[m] = cash[m-1] + net[m]. Cash never rises when net is negative. PASSED.

## Worked example: re-sign slider

- **0% re-sign (default):** MRR falls from $65k to $0 by Dec. Cash survives to ~$89k Dec.
  3 unsustainable months (Oct-Dec).
- **50% re-sign:** ~$19k/mo retained by Oct (half of $38k total expiring by then).
  Cash trajectory improves by ~$19k/mo cumulative. Turns the cliff into a gentle slope.
- **100% re-sign:** No churn from expirations. MRR holds at ~$65k, all months healthy.
  Cash grows throughout. Shows the full value of retention.

Key insight: every 25% improvement in re-sign rate is worth approximately $9,500/mo by
October 2026. Retention is THE lever.
