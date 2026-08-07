# FUNNEL COMPLETION — PHASE 1 DIAGNOSIS (2026-08-08, counts before code)

## Phase 0 deltas vs the brief
- **The close-date convention was NEVER semantically ruled.** #118 rules AUTHORITY
  (tracker, counted by its Close Date) but not cash-received vs signed/verbal.
  → ENCODED DEFAULT (veto-able, DECISIONS #128): **close = the signed/verbal
  deal-won event**; payments are evidence NEAR the close, not the close → the
  Stripe/Xero rungs are PROPOSED, never AUTO. (Consistent with #122's P1 cards.)
- **Xero rung unavailable**: current OAuth scopes are three granular REPORT reads
  (P&L/BankSummary/BalanceSheet) — invoices/payments 401 (probed in the BAS build).
  The rung is reported as a capability gap, not built blind. No tokens minted.
- The resolution engine (#122) exists and is CLOSES-scoped (P1/P2 cards); the truth
  engine's spine sweep (#126) is CLOSE-SPINE-scoped. The brief's suspicion is
  correct: **no sweep ever touched non-closing leads.** This build extends both —
  no parallel resolver.
- GHL appointment reads work under current scopes (probed #126; live sample below).
- Tracker date columns (real header): Input[1] · First Called[11] · Set[18] ·
  Close[27] · Deposit[31] · Last Payment[33] · Refund[36].
- Setter-outcome vocabulary (real, counted): no pick up 358 · set 237 · no set 162 ·
  dq 143 · (blank) 139 · working on 70.

## HYPOTHESIS VERDICT: CONFIRMED, with one nuance — the numbers
**D2 — Sets/Shows zero:**
- 237 set events exist in the tracker; only **115 carry a Set Date; 122 (51%) are
  dateless**. Every dated sample is April–June — **Set Date filling stopped ~June**.
- Shows (180) have NO date column at all (they ride the set call).
- Therefore: 30d **activity** cells read sets=0, shows=0 (Failure 2 exactly — the
  witnessed zeros are the ACTIVITY clock); 30d **cohort** reads sets=22, shows=17
  (cohort needs no event date). The nuance: Failure 2 is clock-specific, and it is
  the dateless class + the sweep gap, as hypothesized.
- GHL appointment sample (12 attributed leads): 2 have appointment objects — BOTH
  are tracker set=True/set_date=None with real created/startTime/status
  ("confirmed") → derivation will date them. Older sets may lack GHL objects
  (calendar adoption is recent) — those stay honestly dateless.

**D1 — Dateless census (24 rail entries):**
- 19 blank Close Dates + 5 blank Input Dates = 24 entries.
- **Duplicate-names verdict: TWO GENUINE DATELESS EVENTS PER CONTACT, not a bug.**
  Neri Roth Herrmann, John Tamayo, Julieta Pablo Tadiaman, Aldrin Dabuan, Jenny Bui
  each have BOTH Close Date and Input Date blank — one rail entry per missing event
  is correct rendering. (Rail upgrade groups them per contact with ×2 chips.)
- Evidence per contact: tracker Deposit Date is blank for ALL 19 (rung 1 yields
  zero). P1 candidates: 6 Stripe first-payment + 9 GHL stage-change; 4 have NO
  candidate anywhere (Vipin, Dj, Hiep Nguyen, John Tamayo).
- Under the encoded convention: **all 15 close-date candidates are PROPOSED**
  (payment/stage = near-evidence), 4 stay dateless with the honest reason.
- The 5 blank INPUT dates gain a real AUTO rung: **GHL contact created date**
  (ID-exact, single, unambiguous — the lead's arrival) → "derived:ghl-contact-created".

**D3 — Reached "—" on Names:** root-caused by inspection: `attribution_verdicts.
_aggregate()` sums a fixed field list that omits `reached` (and the annotation
fields) — the ladder rows never carry the key. Same engine, missing group-by
wiring, not a parallel path. One-line fix + a named regression test.

**D4 — Lane lag, aged per deal (30d window, all UNMOVED):**
Sam King 21d · Lucas Cristofle 22d · Glen Fitzgerald 29d · Tony Thai 18d.

## What the cells SHOULD read after the build
- Activity sets/shows: rows whose sets got derived dates (GHL appointments) land in
  their booked-date windows; the ~120 old dateless sets without GHL objects stay in
  the ◔ annotation + hygiene (honest remainder, listed).
- Cohort cells: unchanged (already correct).
- Reached: identical on every tab (grouped through the one engine).

---

## THE BUILD + LIVE FIRST RUN (2026-08-08, commits 47f9c15 + 60057f4 — DECISIONS #128)

### Dateless disposition: 24 → the honest remainder
| lane | count | detail |
|---|---|---|
| input AUTO-derived | 4 | jenny bui (contact r7efHW52…, 2025-05-23) · john tamayo (HNoKxA5O…, 2025-10-07) · aldrin dabuan (nxQlELS4…, 2025-06-27) · julieta pablo tadiaman (t93MSMuY…, 2025-07-21) — "derived:ghl-contact-created", journaled |
| close PROPOSED (cards standing) | 15 | 6 Stripe first-payment + 9 GHL stage-change — the encoded signed-date convention keeps payments as near-evidence; "apply the date card for X" converts one on Rydel's word (no tracker write; the Piolo item persists) |
| no evidence anywhere | 5 | Vipin, Dj, Hiep Nguyen, John Tamayo (close) + Neri Roth Herrmann (input — no GHL contact match) — honestly dateless, reason stated |
Both-blank won rows now PARSE (excluded ≠ deleted): the parser keeps every won row;
it windows nowhere until a date exists (source or derived) — the recon carries an
explicit derived_placed term (live: leads derived=4, ok=True at all-time).

### Sets/Shows: before → after (activity clock, live)
| window | sets | shows |
|---|---|---|
| 30d | 0 → **9** | 0 → **5** |
| 60d | 1 → **17** | 1 → **10** |
| 90d | 2 → **32** | 2 → **19** |
Recon ok and 0 invariant violations at every window post-derivation. Event sweep:
3 batches, **140 GHL calls**, 35 set dates + 19 show dates derived (appointment IDs
journaled; live status vocabulary observed: confirmed/cancelled/invalid/noshow — a
cancelled/invalid/noshow appointment derives the SET date only, never a show);
17 multi-appointment contacts → PROPOSED with candidates; **24 contacts remaining**
(the nightly sweep clears ~40/night — done in one more night).

### The B008 walkthrough (live)
Cohort 90d: 16 leads → 11 qualified → 7 reached → 5 sets → 5 shows → 1 close
($5,170) — coherent at every stage. Activity 30d: sets=1 shows=1 closes=1 with the
◔1 undated annotation and NO integrity error. A close with 0 bare sets is no longer
renderable (I8 + annotations, test-locked).

### Tab parity (live)
Names-tab reached: B001_A05 9 · B008_A04 7 · B001_A01 7 — the engine's grouped
values; the "—" class is a named regression test.

### Sample audit (derived sets, appointment IDs)
hana 2026-07-08 (53Ncwtqe…) · lynn 2026-07-24 (h2iFmM76…) · ramin 2026-07-06
(LtKkHS8q…) · george 2026-07-16 (IK5aQzKm…) · steffan 2026-07-14 (yad99mHm…) ·
ron ling 2026-07-17 (n5pXUSdk…) · shamsher 2026-05-21 (28RkcCr1…) · tony wai
2026-06-17 (Q960iZKD…) · sami amor 2026-04-23 (YnUuO5Q6…) · dani zeini 2026-06-29
(B8Q5G9YN…) — each date = the appointment's BOOKED date per the encoded convention.

### Lane-lag ageing (live)
Per-deal items generated on the matrix refresh: Sam King 21d · Lucas Cristofle 22d ·
Glen Fitzgerald 29d · Tony Thai 18d — "closed in tracker Nd ago · GHL stage
UNMOVED", drillable, self-clearing on stage move.
