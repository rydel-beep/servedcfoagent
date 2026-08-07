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
