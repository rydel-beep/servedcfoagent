# ONE ENGINE PER METRIC — Phase 0 (computation-site map) — HARD STOP

**Date:** 2026-07-03 (Sydney) · **Status:** HARD STOP — Rydel locks canonical definitions before
consolidation. Nothing consolidated yet.

## The four-way contradiction, traced to source (live values)

| Metric | GREETING (voice.build_greeting) | CHAT range-engine | SNAPSHOT hormozi | DASHBOARD tiles |
|---|---|---|---|---|
| **ROAS** | — | **2.95×** = cash ÷ spend (range_unit_economics:305) | **contracted** ÷ spend (hormozi m8:561 — "new contracted revenue"; the 4.08/9.02 era) | range engine via `applyRangeEconomics` |
| **LTGP:CAC** | — | contract×margin ÷ loaded CAC (range) | m1 (the 1.47 the model cited) | range engine (4.8 seen) |
| **CAC** | — | **$2,434** (÷ **6** tracker Call-Outcome-won closes) | **$3,815** (÷ scorecard closes) | range engine |
| **LTV:CAC** | — | avg contract ÷ CAC (range) | **4.53** (hormozi m7) | 7× seen (range) |
| **Cash collected 30d** | **$70k** = Stripe total (`stripe.revenue.current`, $69,818) | **$24,965** = new-deal tracker cash (won deals, close-date) | — | — |
| **Appointments** | **0** (`sales.funnel.sets` = scorecard) | 26 (tracker, `leads_view`) | — | — |
| **Deals closed** | **2** (`sales.funnel.closes` = scorecard) | 6 (tracker Call-Outcome-won) | — | — |

## Root causes (definitional drift + duplicate engines)
1. **ROAS = two metrics, one name.** hormozi m8 = CONTRACTED revenue ÷ spend; range engine = CASH
   collected ÷ spend. The model quoted both in one session (4.08 then 2.95).
2. **CAC = two denominators.** hormozi divides by the Team Scorecard `closes` (a narrow rolling
   window, currently 2); the range engine divides by tracker **Call-Outcome-won** closes (6, the
   reconciled definition). → $3,815 vs $2,434.
3. **"Cash collected" = three things.** Stripe TOTAL cash ($70k, all money in) vs new-deal TRACKER
   cash ($24,965, won-deal close-date) vs `sheets.cash_collected` ($32,420). All wear one label.
4. **Greeting reads the SCORECARD** for appointments/closes (0 / 2) — the same narrow-window
   scorecard bug fixed for counts, still live in the greeting and hormozi; the tracker says 26 / 6.
5. **Two engines feed the model:** the snapshot `hormozi` block AND the range engine — so the chat
   drifts between them depending on which it hits.

## HARD STOP — Rydel locks these, then I consolidate to ONE engine (the range engine), repoint every
consumer (greeting, chat context, tiles, brief), delete the hormozi duplicates, and add a
consistency test that fails if any two sites disagree.

---

## Locked definitions (Rydel, 2026-07-03)
- **ROAS = CONTRACTED revenue ÷ Meta spend** (the cash version is retired; one name, one definition).
- **"Cash collected" = new-deal tracker cash** (won deals, close-date); Stripe total renamed elsewhere.
- **Closes/appointments = tracker Call-Outcome-won / tracker SETs** (scorecard killed as a source).
- **CAC = loaded** (ad + closer + setter) ÷ tracker-won closes. **LTGP:CAC** = avg contract × margin ÷
  loaded CAC. **LTV:CAC** = avg contract ÷ loaded CAC. All over the same window.

## Consolidated — ONE engine, all consumers
The single source of truth is `range_unit_economics.unit_economics(window)`. Consolidation:
- **range engine:** ROAS flipped to contracted (`contract_total ÷ ad_spend`); the new-deal cash kept
  under its own name (`new_deal_cash`).
- **hormozi (snapshot):** m1/m2/m7/m8 now **DELEGATE** to the engine (computed ONCE per snapshot,
  shared) — the duplicate scorecard-closes / cash-vs-contracted formulas are DELETED. Grep-proven:
  no `roas = …/ad_spend` formula survives outside the engine (`test_no_duplicate_roas_formula`).
- **greeting:** reads `hormozi._sales_headline` (same engine) — appointments = tracker SETs, closes =
  tracker-won, cash = new-deal cash. No more scorecard 0/2 or Stripe-$70k.
- **dashboard tiles + chat/voice:** already the engine (via `/api/unit-economics` and the range
  handler). So greeting == chat == tiles == snapshot, by construction.

## Traceability
Every engine metric carries its breakdown (formula + $ inputs + window + basis) in `components` and in
each hormozi metric's `read`/`inputs_used` — EDITH can answer "how did you get that?" for any number.

## Consistency tests (`tests/test_metric_consistency.py`)
Assert hormozi == engine for every metric (incl. the KPI alias), the greeting headline == engine, ROAS
is contracted (not cash), and NO duplicate ROAS formula exists. Any future divergence fails CI. 297
tests pass.
