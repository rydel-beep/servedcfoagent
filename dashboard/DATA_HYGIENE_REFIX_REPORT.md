# Data Hygiene Refix — one clock, honest headline, invariants, speed, EDITH as monitor

## PHASE 0 — FORENSICS (2026-08-06) — AWAITING RYDEL'S BASIS RULING

### A · The mixed-basis proof (I1 violations, named and dated)
Per-column basis as coded (attribution_engine.py): leads/qualified/sets/shows = COHORT
by Input Date in the window (`window_leads`); closes/contract/cash = CLOSE-DATE basis
(`window_closes`). **Two clocks in one row — by design until now.**

Violating rows (closes > leads), with every phantom close named:
- **30d: 3 creative rows + 4 ladder rows.**
  · B008_A03: 1 close / 0 leads — Tesla Zhong (in 4 Jul, closed 8 Jul; entered 4 days
    before the window opened on 8 Jul).
  · B006_A03: Glen Fitzgerald (in 20 Jun, closed 9 Jul).
  · B005_A07: Tony Thai (in 14 Jun, closed 20 Jul).
  · Ladder inherits: name-level B008_A03 shows 0 leads/3 closes; batches B005/B006;
    campaign "NO CAMPAIGN DATA" 0/3.
- **60d: 1 + 2** — B004_A03: Lucas Reid (in 3 Jun, closed 24 Jun; window opened 8 Jun).
- **90d: 0** — the window is wide enough to hold the full lag today.
Not missing data: close-lag crossing window edges under mixed bases.

### B · The headline close audit (three-way, named)
The ENGINE'S top-line is honest — totals.closes == the tracker authority in all three
windows (30d: 5 = attributed 4 + unattributed 1 [Sam King, no ad identity] · 60d: 10 =
8 + 2 [+The Leopard Deli] · 90d: 18 = 15 + 3 [+Dinesh Khenchi]; ambiguous 0 closes).
GHL closed-won in-window: 0 (the dead lane, already flagged); Stripe: 0 missing.

**The understatement lives in TWO DISPLAY READS:**
1. The LEADERS card "Most Closes: **1**" — a single creative's max, positioned like the
   window total. This is the "board says 1" Rydel saw.
2. The ladder ACCOUNT row — attributed-ads-only (4 vs the true 5), label says so but the
   number still reads low at a glance.
FIX (Phase 2): the scorecard headline becomes TOTAL closes (== tracker, I5-tested) with
the tier breakdown beneath; every dropped close clickable with its why.

### C · Performance profile
Engine cold compute: **63.8s per cold window** (tracker CSV fetch + full contact read +
resolution). Warm in-process: 0ms; board assembly on warm engine: 3ms. **A cold window
switch costs ~60s — the entire lag.** Top costs: (1) tracker live CSV per compute,
(2) attr_contacts full read per compute, (3) 90d trailing compute on board calls,
(4) ladder/scorecard rebuild per request, (5) GHL notes live per roster.
Fix plan: persisted rollups keyed (basis, window) refreshed by the loop + on sync,
adjacent-window prefetch, cached==live test-enforced.

### D · The basis options (the gate)
(a) LEAD-COHORT (HYROS convention): a lead's whole future belongs to its entry window —
    true conversion rates; recent windows show fewer closes (lag stated on screen).
(b) ACTIVITY-IN-WINDOW: what happened this month; closes can exceed leads, each such row
    carries an inline explanation.
(c) BOTH as an explicit labelled toggle — one basis at a time, never mixed.
Plus: headline = TOTAL closes with tier breakdown (recommended).

## RYDEL'S RULINGS + THE BUILD (2026-08-06)
BOTH bases as a labelled toggle (LEAD-COHORT default) · headline = TOTAL closes with the
tier breakdown. Implemented per DECISIONS #120:
- ONE CLOCK PER VIEW: basis threaded as a required engine parameter (invalid → raises;
  cache keyed by basis; canonical checks follow the active clock). Cohort = the entry
  window's cohort and everything that later happened to it; Activity = events on their
  own dates with earlier-lead closes annotated inline (↤N on the cell). The #118
  no-input-date closes live on the activity clock; cohort keeps them visible via hygiene.
- THE HONEST HEADLINE: total closes/leads/cash/spend tiles with tier breakdowns
  (attributed · ambiguous · IG-DM · unattributed); "Top Closing Creative" renamed so a
  per-creative max can never masquerade as the window total.
- INVARIANTS AS CODE: I1/I2 runtime per row (violation → the row renders the honest
  error state, never the number, + salience once); I3 tier sums; I5/I6 in the
  reconciliation block; I7 basis stamped on every row/payload. Property-style seeded
  tests prove ordinary variation can't violate.
- SPEED: persisted rollups keyed (basis, window); stale rollups served LABELLED
  ("showing the last rollup — refreshing…") with background refresh + client poll;
  adjacent windows prefetched after any fresh build; roster GHL notes capped to 8
  inline. Cold-path cost isolated to background threads.
- EDITH CUSTODIAN: "what basis am I looking at?" (the two clocks + worked example),
  "are the invariants green?" (live status + reconciliation), the existing integrity/
  accuracy answers; corrections stay confirmation-gated via existing mechanisms only.

## LIVE VERIFICATION (production data)
| basis × window | headline closes | == canonical (I5) | tiers sum (I3) | integrity errors | invariant violations |
|---|---|---|---|---|---|
| cohort 30d | 1 | ✓ (1) | ✓ | 0 | 0 |
| cohort 60d | 8 | ✓ (8) | ✓ | 0 | 0 |
| activity 30d | 5 | ✓ (5) | ✓ | 0 | 0 |
| activity 60d | 10 | ✓ (10) | ✓ | 0 | 0 |
The Phase-0 phantoms cured: B008_A03 / B006_A03 / B005_A07 read 0 leads/0 closes under
cohort (their closes belong to June's cohorts) and 1 close with the ↤1 earlier-lead
annotation under activity. Warm compute 0ms; suite 584 green.
