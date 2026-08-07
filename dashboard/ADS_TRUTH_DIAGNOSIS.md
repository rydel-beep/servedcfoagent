# ADS TRUTH — PHASE 0/1 DIAGNOSIS (2026-08-07, evidence only, no fixes yet)

## Phase 0: what this brief assumed vs what actually exists
The brief was written from a pre-#116 snapshot ("currently after #115"). Since then,
ELEVEN rulings/builds landed (DECISIONS #116–#125). Deltas, honestly stated:
- **The clock IS RULED** — #120 (2026-08-06): BOTH bases as an explicit labelled
  toggle, LEAD-COHORT default, one clock per view, cache/canonical per basis,
  invariants I1–I7 as runtime code. → Gate 1's basis ruling is SKIPPED (honored);
  what remains from Gate 1 is encoding hardening (cross-clock guard, drill clock
  inheritance) — build items, not rulings.
- **The keying policy IS RULED** — #119: HYBRID (ad-id truth, "Name [Campaign]"
  labels, archived marked, __ambiguous__ quarantine). → skipped (honored).
- **The integrity run (#122) actually shipped:** deployed-state gate, phantom
  census (0 on both clocks × 30/60/90), the join-spine verdict (one
  lead_bucket_key join for leads AND closes; I2 structural), resolution doctrine
  (A1–A5 auto-fix + P1/P2 cards + H1/H2 lanes, journaled, no source writes).
  A resolution engine EXISTS (resolution.py) — this build EXTENDS it, no parallel.
- Close authority (#118), Qualified v2 fit definition (#115), triage lanes (#121)
  all stand. today_sydney() everywhere; /ads role gate live.

## Case A — B006_A03 "1↔1 mismatch": ROOT-CAUSED (the class is alive in the DRILL)
The original two-clock row was cured by #120: cohort 30d shows NO B006_A03 row
(Glen Fitzgerald's lead is June's cohort); activity 30d shows closes=1 WITH the
↤1 earlier-lead annotation. Honest on both clocks.
**But the mismatch class survives in one live path:** `dashboard/ads.py roster()`
calls `attribution_engine.compute(days, start, end)` WITHOUT the basis parameter —
it always computes the COHORT clock, while the board honors `?basis=`. Every
activity-basis close cell therefore drills into a cohort-clock roster:
| window | cell (activity) | drill (cohort) |
|---|---|---|
| 30d B008_A04 | 1 | 0 |
| 30d B006_A03 | 1 | 0 (reproduced: cell 1, drill [] — Glen Fitzgerald missing) |
| 30d B005_A07 | 1 | 0 |
| 60d B004_A03 | 1 | 0 |
| 60d Unattributed | 2 | 1 |
**Two computation paths for one cell = the Case-A bug class (I11 violation).**
Fix: roster honors basis; the drill inherits and STATES the clicked cell's clock.

## Case B — B008_A04 "close with 0 sets": NOT A PHANTOM — an annotation gap
Lucas Cristofle (closed 2026-07-16, $5,170) has FULL tracker evidence: set ✓,
show ✓ (dates before the 30d window opened). On the activity clock each event
counts on its own date → "12 leads, 7q, 0 sets, 0 shows, 1 close" is TRUE on that
clock but renders unexplained: closes carry the ↤ earlier-lead annotation, sets
and shows DON'T. Cohort 90d reads the same row sanely (16/11/5/5/1).
**The whole census class is this:** closes>shows on activity = 3 (30d) / 8 (60d) /
13 (90d) rows; cohort = 0 violations at every window. Zero missing spine data.
Fix: activity funnel annotations for sets/shows (the closes treatment, extended) +
the event-spine invariant (I9) as the standing safety net.

## Case C — Fung Kwok: LEGITIMATELY QUALIFIED, UNREACHABLE — the definition works
Engine row: qualified=TRUE via the ruled definition — 'no pick up' ≠ DQ ✓ ·
revenue "$20k-50k" parsed, floor met ✓ · form/finalised ✓. The definition measures
FIT; it says nothing about contact. **Gate 2 counts (computed, all-time):
619 qualified · 229 terminal-unreachable (37%) — no pickup/unresponsive with no
set/show/closer evidence. 30d: 33 qualified · 9 terminal-unreachable.**
Option B (amend the definition) would move all-time 619 → 390, 30d 33 → 24.

## Case D — the $3,355 "double count": TWO DISTINCT CLOSES (case closed)
$3,355 is a standard instalment amount (against $18,300 contracts). It appears on
FOUR distinct deals: Tony Thai (B005_A07) · Sam King (Unattributed) · Tanny Puth
(B001_A01) · Lucas Reid (B004_A03). Partition check across all six basis×window
combos: **0 closes in two tiers; tier sums == headline (closes AND cash)
everywhere.** No violation exists; I10 ships as the permanent guard.

## Full census (baseline for Phase 3)
- Monotonicity: cohort CLEAN at 30/60/90. Activity: the cross-window-lag class
  only (above); sets>leads: 1 row at activity 90d (same class, set before lead's
  window edge); qualified>leads: 0 everywhere.
- Tier partition: CLEAN (see Case D).
- Mismatch-cell class: the 5 roster-basis instances (Case A) — the only live ones.
- 90d close truth table: **18/18 closes have (a) a tracker row, (b) tier-correct
  linkage, (c) tracker set+show evidence.** T1 (tracker) covers 100% today; T0
  (spineless) count: ZERO. The spine build is a safety net, not a backfill.
- GHL appointment API probe: GET /contacts/{id}/appointments → 200 (read-only,
  existing token) — T2 derivation is feasible when T1 ever goes missing.

## What this means for the gates
- GATE 1 (clock + keying): RULED (#120/#119) → skipped per the brief's own rule.
  Remaining Gate-1 items are hardening, built without a stop: basis-aware roster,
  drill clock inheritance + header label, cross-clock arithmetic guard, activity
  funnel annotations, the activity cash strip on the cohort view (labelled,
  computed by the one engine — an encoding of #120, not a new ruling).
- GATE 2 (qualified vs reached): GENUINE STOP — presented with the counts above.
