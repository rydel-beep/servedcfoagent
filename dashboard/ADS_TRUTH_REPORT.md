# ADS TRUTH REPORT (2026-08-07, commits 4e3e8cc + df58cf0, DECISIONS #126)

Companion to dashboard/ADS_TRUTH_DIAGNOSIS.md (Phase 0/1, evidence). Suite 648.

## 1 · Phase 0 vs the brief (deltas honestly stated)
The brief assumed a pre-#116 world ("after #115"). Reality: #116–#125 already
landed. The clock (#120) and keying (#119) were RULED → Gate 1 skipped per the
brief's own rule (hardening items built without a stop). The integrity run (#122)
really exists (resolution engine, phantom census, join-spine verdict) — this build
EXTENDED it (spine derivations journal through resolution.log_autofix; no parallel
engine built).

## 2 · Root causes, one paragraph each
- **CASE A (1↔1 mismatch):** the original row was cured by #120; the CLASS survived
  in exactly one path — `roster()` dropped the basis param and always computed the
  cohort clock while the board honored the toggle. Five live activity-cell↔drill
  mismatches reproduced (B006_A03 30d: cell 1, drill 0). Fixed at root: the drill
  inherits and STATES the clicked cell's clock; cross-clock math now RAISES (I11).
- **CASE B (close with 0 sets):** not a phantom — Lucas Cristofle carries full
  tracker set+show; the activity clock counted each event on its own date and
  rendered the lag bare. Fixed: sets/shows gained the ↤ earlier-event annotations
  (and ◔ for sets that EXIST but have no Set Date — 18 such closes found; a
  hygiene rollup routes them to Piolo). I8(activity) makes an unexplained
  "0 sets, 1 close" row structurally impossible.
- **CASE C (Fung Kwok):** legitimately qualified under the ruled fit definition
  ('no pick up' ≠ DQ · $20k–50k · form-complete). Ruled Option A: fit stays;
  REACHED added (qualified ∩ contact evidence). He renders qualified ✓ reached ✗.
- **CASE D ($3,355 double count):** two DISTINCT closes (Tony Thai attributed,
  Sam King unattributed) sharing a standard instalment amount — $3,355 also
  appears on Tanny Puth and Lucas Reid, all against $18,300 contracts. Partition
  was clean everywhere; I10 now guards it permanently.

## 3 · The rulings
- **#126 Gate 2 = OPTION A:** qualified stays fit; REACHED tier added (funnel
  lead → qualified → reached → set → show → close); reach-rate flag
  (`qualified_unreachable`, floor 40% config) feeds verdict signals. Thresholds
  config-surfaced (reached_call_seconds 60 · set_call_seconds 120).
- Clock/keying: #120/#119 honored (no new ruling); the four hardening items
  confirmed by Rydel and built.

## 4 · Census: before → after
| class | before | after |
|---|---|---|
| activity cell↔drill mismatches (Case A class) | 5 live | **0** (structurally dead, test-locked) |
| unexplained closes>shows rows (activity) | 13 @90d | **0** (↤/◔ annotated; I8 guards) |
| tier-partition violations | 0 | 0 (now I10-guarded forever) |
| cohort monotonicity violations | 0 | 0 (I8 full-chain guard added) |
| phantom closes (T0) | 0 real (1 false in sweep v1) | **0** (joiner fixed, census clean) |
| bare "mismatch, report this" renders | 1 class | **deleted** — cause+clock+lane messages |

## 5 · Quad-check (production, all 18 closes ≤90d)
18 facts × 4 reads: **18/18 agree on the authority core** (engine == tracker won
row == board). Validator-layer causes surfaced, never absorbed: GHL closed-won
lane dead (KNOWN standing cause, ops rule stands) on 10; no GHL contact match
(join gap, validator unavailable) on 5. **Zero unexplained disagreements.**
Sweep v1's 3 "CRITICAL no tracker won row" + 1 phantom were the checker's OWN
naive name-index (last-write-wins on duplicate names) — fixed (won-preferring
index), regression-tested, and the accuracy table keeps both nights honestly:
26 → 1 disagreements.

## 6 · Derived + Piolo queue
- T2 derivations: 2 fired in sweep v1 (real GHL appointment objects — the live
  status vocabulary is now verified: "confirmed") and were REVERSED with a journal
  entry once the joiner fix showed both closes had tracker evidence all along
  (tracker = T1 authority; no double-count, test-proven). Current derived count: 0.
- Piolo queue: ONE rollup item live — "18 closing deals have a set with NO Set
  Date — fill at source" (self-retiring channel, rebuilt per sweep).
- Reached sweep: first pass checked 30 unreached-qualified contacts, found GHL
  appointment evidence for 5 (journaled); ~364 remain, swept incrementally
  (30/night, rate-capped).

## 7 · PROPOSED, waiting on Rydel
- Nothing in the T3 spine lane (empty — every close is tracker-evidenced).
- The sweep will auto-file regression-test skeletons for any NEW cause class;
  none pending after the v2 clean run.

## 8 · What the nightly sweep does tonight, verbatim
Run invariants I1–I12 across both clocks × 30/60/90 → spine census (T1/T2/T3/T0,
derivations journaled + Piolo items) → quad-check all ≤90d closes (board · engine ·
GHL validator · tracker) → reached sweep (next 30 contacts) → append the accuracy
row → publish findings to its own self-retiring feed channel (close-level/≥$1k →
ACTION lane) → prune stale phantom flags → if the sweep itself fails, flag
`ads_truth_sweep_down` S1. EDITH: "how accurate is the ad data?" answers from the
table.

## 9 · Unproven / honest limits
- 🟡 T2 status vocabulary verified against ONE live appointment ("confirmed");
  other statuses (showed/noshow variants) accepted per the coded set but not yet
  observed live — the raw status is always recorded, unknowns never guessed.
- 🟡 REACHED currently proves via tracker evidence + GHL appointments; connected-
  call-duration and two-way-thread evidence need GHL conversation-API reads not
  yet probed — the definition is honest about its current evidence base (the
  column undercounts, never overcounts).
- 🟡 The K=25 random-cell quad-check leg samples close cells today (closes are
  the material facts); lead-cell sampling rides the same machinery when needed.
- ⬜ Grid <2s / drill <500ms formal budget measurement (spot-checks fine via
  rollups; not instrumented this run).
- Rydel's eyes close the build: /ads → activity basis → any close cell → the
  drill now states its clock and matches; the Reached column; the ◔18 annotation.

Statuses: Cases A–D ✅ proven by inspection/test · invariants I8–I13 ✅ live ·
sweep ✅ two production runs recorded · reached tier ✅ live (evidence base 🟡
growing nightly) · report claims above each carry their evidence line.
