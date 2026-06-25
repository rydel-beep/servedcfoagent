# FULLY-LOADED CAC + LTGP:CAC — Phase 0 diagnosis (HARD STOP)

**Date:** 2026-06-25 (Sydney) · **Scope:** served-cfo-agent only · **Status:** HARD STOP — confirm
the comp structures + the LTGP basis before wiring. No changes made.

## 1. How CAC / LTGP:CAC are computed today (live trace)

`hormozi_metrics.m1_ltgp_cac` / `m2_cac_breakdown`:
```
CAC = (ad_spend + setter_payout + closer_comm) / closes
LTGP:CAC = LTGP / CAC,   where LTGP = avg_contract × gross_margin%
```
**It already includes closer + setter comms** — so the premise "CAC counts ad spend only" isn't
quite right. The real gap is that the **setter component is incomplete** and uses a partial source.

Live inputs (window **2026-05-26 … 06-25**, 30d):

| Component | Source | Live value | Verdict |
|---|---|---|---|
| Meta ad spend | `ad_spend_resolved` (Meta live, 30d) | **$8,757.50** | ✓ correct, window-matched |
| Closer commissions | `costs.closer_commission` = sheet "Commission Closer" actuals | **$7,200.00** | ✓ actual-from-sheet, 30d |
| Setter commissions | `sales.payout.total_owed` = **scorecard $50/qualified-set only** | **$500.00** | ✗ INCOMPLETE — missing the 5%-of-cash |
| Closes | `sales.funnel.closes` (Team Scorecard) | **4** | ✓ |
| → CAC | (8,757.50 + 7,200 + 500) / 4 | **$4,114.38** | understated (setter too low) |
| LTGP | avg_contract $16,537.50 × gross_margin 71.1% | **$11,758.16** | basis needs confirming (below) |
| → LTGP:CAC | 11,758.16 / 4,114.38 | **2.86×** (watch) | too high — setter undercounted |

`costs.setter_commission` (sheet "Commission Setter" col) reads **$0** (that column is blank — a
known data-quality flag), and it isn't used in the math anyway. The setter cost is taken from the
scorecard's **$50 × qualified sets** only — so the **5%-of-cash-collected** half of the setter comp
is entirely missing from CAC.

## 2. The real setter comp — read from the SETTER PAYOUT LOG (by name)

The setter payout log records, per deal: cash collected, **set_fee ($50)**, **pct_bonus (5% of
cash)**, total_owed. The agent reads it by **gid 552970662 — which now returns HTTP 400** (the same
400 behind the flaky test), so `payout_log.total_owed` is currently **None**. Reading the tab **by
name "SETTER PAYOUT LOG" returns 200** (1,607 rows). Its column layout differs from the old
gid-parser (business, setter, won, cash, set_fee, pct_bonus, total_owed, status, notes/date).

**Window-matched setter comp (by name, deals in 2026-05-26 … 06-25):**
15 deals · set_fees **$750.00** ($50 × 15) + pct_bonuses **$757.27** (5% of cash) = **$1,507.27**
— vs the **$500** CAC uses today. (Date matched on the log's payment/notes date — see the
window-basis question below.)

## 3. Loaded-CAC preview (correct the setter component)

| | Current | Corrected (setter $500 → $1,507.27) |
|---|---|---|
| ad + closer + setter | 8,757.50 + 7,200 + **500** | 8,757.50 + 7,200 + **1,507.27** |
| total acquisition cost | $16,457.50 | **$17,464.77** |
| ÷ 4 closes = **CAC** | **$4,114.38** | **$4,366.19** |
| **LTGP:CAC** (contract-basis LTGP $11,758) | **2.86×** | **2.69×** |

So CAC rises ~$252 and the ratio tightens 2.86 → **2.69** — a modest correction, *if* LTGP stays
contract-based. The LTGP basis is the far bigger lever ↓.

## 4. The biggest question — the LTGP basis

LTGP today = **avg CONTRACT value × gross margin** = $16,537.50 × 71.1% = **$11,758** (lifetime
gross profit on the full contract). The work order says "LTGP from **cash collected** / gross
profit." These differ hugely:

| LTGP basis | LTGP | LTGP:CAC (on corrected CAC $4,366) |
|---|---|---|
| **Contract value × margin** (current; "lifetime") | $11,758 | **2.69×** |
| **Cash collected × margin** (avg_cash $5,509 × 71.1%) | $3,917 | **0.90×** |

This single choice moves the ratio from 2.69× to 0.90×. "LTGP = **Lifetime** Gross Profit" argues for
the full contract value (a 6-month deal's lifetime value is its contract, not the first payment) —
but I won't change it without Rydel's call.

## HARD STOP — confirm before wiring
1. **Setter comp = $50 per set + 5% of cash collected**, read actual from the SETTER PAYOUT LOG
   (by name, since the gid 400s)? (→ ~$1,507 window-matched, not $500.)
2. **Closer comp = the sheet "Commission Closer" actuals ($7,200)** — correct source?
3. **LTGP basis = contract value × margin (current, "lifetime") or cash collected × margin?** ← the
   decisive one (2.69× vs 0.90×).
4. **Window/date basis for the setter log** — match deals by set/close date or payment date? (affects
   exactly which deals fall in the 30d window).

ROAS stays ad-spend-only (revenue ÷ ad spend) — a distinct metric, will NOT be changed. Nothing
wired yet.

---

## Phases 1–3 — built (Rydel confirmed: contract-basis LTGP · setter $50+5% from log · close/set date)

**Setter window-date reality:** the by-name SETTER PAYOUT LOG has NO set/close-date column, and
joining its lead names to the main tracker's close dates matched only **7 of 164 deals** —
unreliable (157 dropped). So I window by the log's **payout date** (the only complete, reliable
signal), **clearly labelled**. The close-date figure ($1,296) was just incomplete; payout-date
($1,507.27) is the true window total.

**`loaded_cac.py` (new):** reads the SETTER PAYOUT LOG by name (gid 552970662 → 400; by name → 200),
parses per-deal `$50 set_fee + 5% pct_bonus`, window-matched. Live: **15 deals · $750 set fees +
$757.27 bonuses = $1,507.27**. Degrades to None (caller falls back to the scorecard figure) on
failure. `hormozi._resolved_setter_comm` uses it (actual-from-log) → scorecard fallback (labelled).

**Before → after (live, 30d):**

| | Before | After |
|---|---|---|
| Setter comm in CAC | $500 (scorecard $50/set only) | **$1,507.27** (log: $50/set + 5% cash) |
| CAC = (ad 8,757.50 + closer 7,200 + setter) ÷ 4 | **$4,114.38** | **$4,366.19** |
| **LTGP:CAC** (contract-basis LTGP $11,758) | **2.86×** | **2.69×** (watch, below 3×) |
| **ROAS** (revenue ÷ ad spend) | 7.55× | **7.55× (unchanged)** — ad-spend-only, comms excluded |

**Window per component (all ~30d):** ad spend = Meta trailing-30d; closer = sheet "Commission
Closer" actuals (won deals, 30d); setter = payout log (payout-date-windowed to the sales window);
closes = Team Scorecard. Each labelled; not perfectly identical bases (heterogeneous sources) but
all 30d — flagged.

**Transparency:** the CAC `read` now carries the loaded breakdown — "ad $X (Meta) + closer $Y
(sheet) + setter $Z (log) = $total ÷ N closes" — with the setter source (log vs scorecard) labelled.
Attribution is **Meta-only** (Google not yet integrated); the hook stays at `ad_spend_resolved`.

**Non-regression:** ROAS unchanged (m8 untouched, ad-spend-only); LTGP unchanged (contract basis,
Rydel-confirmed); 238 tests pass (+4).
