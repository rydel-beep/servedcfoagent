# CASH ON HAND — Xero connection verification + live wiring

**Date:** 2026-06-29 (Sydney) · **Scope:** served-cfo-agent · **Xero:** READ-ONLY

## Phase 0 — connection verification (all checks run against the live token)

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | Token present & valid | ✅ PASS | access + refresh present; **refresh succeeded** (token live, not expired) |
| 2 | Right org (Trap 2) | ✅ PASS | **1 tenant only** — "Served Marketing" (legal: THE 97 GROUP PTY LTD), id `243931e2-…`; saved `tenant_id` matches. Same org (trading vs legal name), not a different company |
| 3 | offline_access / scopes | ✅ PASS | granted: `offline_access`, `reports.banksummary.read`, `reports.balancesheet.read`, `reports.profitandloss.read`, `settings.read`. `transactions.read` absent **by design** (granular scopes only) — **not needed**; cash uses the Bank Summary report |
| 4 | Live read works | ✅ PASS | Organisations read OK — Served Marketing, AU, AUD |
| 5 | Target accounts resolve | ✅ PASS | **#2352** Business Transaction (`d93b6904`), **#4041** Bus Online Saver (`e7dc87e2`), **BAS #2353** (`50a4af6a`); **Amex** identified for exclusion. ⚠ a 6th account "**notn in use**" shares #2352's *number* → matched by **name marker**, not number |
| 6 | Closing balance (Trap 1) | ✅ PASS | positive point-in-time **closing** balances (not movements); reconciles to the ~$172k target under the include-BAS decision |

**Closing balances (as of 2026-06-26, point-in-time):**
```
Business Transaction #2352 .....  $43,680.26   include
Bus Online Saver #4041 .........  $56,593.51   include
BAS / Tax #2353 ................  $71,574.03   include (Rydel: include-BAS)
                       cash on hand =  $171,847.80  ≈ $172k ✓
Amex (liability) .............. −$18,152.80   EXCLUDED
"notn in use" (dup #2352 num) .   $2,458.82   EXCLUDED (no marker)
```

**Cash-definition decision (Rydel, 2026-06-29):** the brief said "exclude BAS" yet expected ~$172k —
which only reconciles **with** BAS. Surfaced the contradiction (HARD STOP); Rydel chose **$172k flat,
include BAS** (no reserve carve-out). Cash on hand = #2352 + #4041 + BAS #2353; Amex excluded.

## Phase 1 — wiring (live, with loud fallback)

- `xero_pull.pull_xero()` now also reads the **Bank Summary** with the same refreshed token (Xero
  refresh tokens are single-use — must not refresh twice) and returns `cash_on_hand` = closing-balance
  sum of the three accounts (matched by **name marker** `#2352/#4041/#2353`, so the "notn in use"
  number-duplicate is excluded).
- `snapshot.py` cash-on-hand is now **live Xero**, not the hardcoded override. **Loud fallback**: if
  the live read fails it shows `⚠ Xero unavailable — last-known $X` (a degraded entry; never a silent
  stale number). The stale `CASH_ON_HAND_OVERRIDE $140,007 / "confirmed 2026-06-04 ⚠ reconfirm"` figure
  and its staleness machinery are **removed**; config keeps only a labelled `CASH_ON_HAND_LAST_KNOWN`
  fallback.
- **Before → after:** `$140,007 (stale 06-04 manual)` → **`$171,847.80` (live Xero closing balances)**.
  The $32k delta is the old manual figure being stale + having excluded BAS. Dashboard label is now
  "Cash on hand · Xero, as of <date>" (the "confirmed … reconfirm" label is gone).

Tests: 258 pass (+4 cash extraction: sum, Amex/notn-in-use exclusion, closing-not-opening, missing-flag).
