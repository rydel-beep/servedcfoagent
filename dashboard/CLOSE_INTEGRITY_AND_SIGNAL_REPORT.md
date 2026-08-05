# Close-Count Integrity + the Insufficient-Data Fix

## PHASE 0 — THE THREE-WAY RECONCILIATION (2026-08-05) — AWAITING RYDEL'S RULINGS

Read-only. Sources: tracker mirror (clean view), GHL won opportunities (live, pipeline
JJQLCr1fl7OHyrpRwSJp, date = lastStatusChangeAt), Stripe via the existing matcher.

### The three counts

| Window | TRACKER (won + Close Date) | GHL (status=won in window) | STRIPE (new-deal cash unmatched to tracker) |
|---|---|---|---|
| 30d | **6** | **0** | **0 missing** (29 charges, 27 recognised, 2 review) |
| 60d | 10 | 0 | — |
| 90d | 18 | 0 | — |

**The 30d six, name by name:** Sam King (17 Jul, $18,300 / $3,355 cash) · James Xu
(7 Jul, $14,500 / $15,950) · Tesla Zhong (8 Jul, $15,100 / $8,305) · Lucas Cristofle
(16 Jul, $14,500 / $5,170) · Glen Fitzgerald (9 Jul, $14,500 / $5,500) · Tony Thai
(20 Jul, $18,300 / $3,355).

### The disagreements, classified

1. **GHL's closed-won lane is DEAD (ops habit, not data)**: 20 won opportunities exist
   all-time, but ZERO have a won-status change inside 90 days — the sales team stopped
   moving deals to closed-won around May. GHL currently validates nothing. This is the
   Phase-3 ops rule ("move the stage the same day the tracker records the close").
2. **19 of 67 won rows have a BLANK Close Date** (28%!) — invisible to every windowed
   count and to windowed LTGP/cash. Dated by their Input Dates they are HISTORICAL
   (Aug 2025 – Apr 2026 intakes; Deposit/Last-Payment columns blank throughout — those
   columns are barely used). They are NOT hiding recent closes; they are hygiene debt
   distorting the all-time and long-window pictures. Full list in the fix list (Vipin,
   Ella Ponce, Phoebe Pham, Dj, Tong Ou, Terry Yu, El Gringos Locos, Hiep Nguyen, Tommy
   Lê, Harjinder Singh, Johnny Ibra, Christie-Lee Gulley, Jintamani M Thoms, Nirosha
   Dushani Jayasekara, Neri Roth Herrmann, John Tamayo, Julieta Pablo Tadiaman, Aldrin
   Dabuan, Jenny Bui).
3. **5 won rows ALSO lack an Input Date** (Neri Roth Herrmann, John Tamayo $24k, Julieta
   Pablo Tadiaman, Aldrin Dabuan, Jenny Bui) — the ad engine's parser DROPS such rows
   entirely (an ENGINE BASIS GAP to fix in Phase 1: closes should count off the won row
   + Close Date alone, input date not required — parity with the unit-economics reader).
4. **"Allan Thai" (Stripe needs-review, $2,805 + $550)**: the two payments sum to
   EXACTLY Tony Thai's recorded cash ($3,355) — the payer is an alias for the Tony Thai
   deal, not a missing close. Proposed: confirm → the matcher learns the alias.
5. **Dedupe**: 1 duplicate won row (Nirosha) counted once — already flagged to Piolo.
6. **Stripe**: 0 paid-but-missing-from-tracker in 30d — no cash from any untracked deal.

### The engine's basis (stated) vs the mental model
Engine close = clean tracker row · closer outcome "won" · Close Date within the window ·
dedupe · test-lead exclusion (0 won rows affected). NOT counted: deals whose CASH arrived
in-window but closed earlier (cash-basis ≠ close-basis); blank-close-date rows; won rows
missing Input Date (the parser gap above). The engine's 6 = the tracker's 6 exactly.

### Verdict starvation (Problem 2 quantified)
30d: five creatives sit at EXACTLY 1 close each (B008_A04, B008_A03, B004_A04, B006_A03,
B005_A07) — each needs 2 more closes (or 30 leads) for a verdict. No plausible correction
of the above errors adds 2 closes to any single creative inside 30d — so Problem 2 is
REAL min-n behavior at 30d, not starvation from Problem 1; the Phase-4 usefulness layer
(provisional signal, aggregation ladder, always-valid account reads) is the fix.

### HARD STOP — Rydel rules on:
(a) AUTHORITY: the tracker (GHL + Stripe validate, flags only) — confirm.
(b) DATE CONVENTION: tracker Close Date (not payment date, not stage-move date) — confirm.
(c) The classifications above — and critically: NAME any deal you know closed in the
    last 30 days that is NOT among the six listed. That names the gap directly.

## RYDEL'S RULINGS (the hard-stop gate, 2026-08-05)
The six are COMPLETE · authority = tracker Close Date · all four classifications
confirmed (blank dates + missing inputs = source errors; GHL lane = ops habit; Allan
Thai = Tony Thai's payer alias, learned).

## THE BUILD (Phases 1-5)
- COUNTING FIX: a won row with a Close Date now counts WITHOUT an Input Date (5 real
  deals incl. John Tamayo $24k were parser-invisible; impact today: 0 windowed-count
  change — all 5 also lack Close Dates — but the gap is closed for the moment humans
  fill them). Alias learned. Impact table in the live-verify output below.
- STANDING CHECK: close_integrity.py — daily three-way matrix (kv tick in the
  attribution loop), classified disagreements → the /ads DATA HYGIENE panel, the action
  feed → Piolo's queue (self-retiring), salience once per new sev1/2 item, EDITH
  "do the systems agree on closes?".
- HUMAN FIX LIST (routed): 19 blank Close Dates + 5 blank Input Dates → per-row items
  in the hygiene panel/queue with the exact field + owner; THE OPS RULE for the team:
  "closed deals move to the GHL closed-won stage the SAME DAY the tracker records the
  close."
- USEFUL BEFORE CERTAINTY: provisional TRENDING badges (dashed, labelled, never
  decisions) + progress-to-verdict; the aggregation ladder (batch → campaign → account,
  same sums, same thresholds, real verdicts where n clears; default = highest confirmed
  level); always-valid account row; honest empty state; 30d close-lag guidance.
- DEFINITIONS PANEL: close / qualified / attribution / verdicts+min-n / windows / cost
  bases — one click, plain language.
