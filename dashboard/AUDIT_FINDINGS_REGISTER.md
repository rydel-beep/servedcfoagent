# ADS EXTREME AUDIT — FINDINGS REGISTER (2026-08-08)

Status: **AT THE GATE** — discovery complete, awaiting Rydel's word on the fix
wave. Artifacts in `dashboard/audit_artifacts/` (00 scorecard · 01 suite ·
02 claims · 03 drills run · 04 XSS scan · 05 security+perf ·
drills_phase_b.py = 13 sandbox drills, all passing with observed behavior pinned).

## SEV1 — fixed immediately (harm-prevention exception)

**F4 · Anonymous financial-data exposure + anon-triggerable credential burner.**
`GET /debug/stripe-ping` returned the live MRR ($59,316 AUD) + the internal MCP
base URL to any anonymous internet caller (live-curled, artifact 05);
`GET /debug/sources` let an anonymous caller trigger four full upstream pulls
including the single-use Xero refresh chain (credential-DoS shape). Both now
X-CFO-KEY-gated — **hotfixed `45670b7`, live-verified 401**, permanent sweep
test (`tests/test_debug_route_auth.py`: any ungated /debug route fails the suite).

## SEV2 — correctness/staleness at risk (proposed wave, in order)

**F1 · Drill/roster cold-path latency breaks the <500ms budget in the common
case.** Engine cache = 30-min TTL, per-worker (×2), per-(basis, days, market)
key; measured cold path 5.7–15.8s (artifact 00/05). The <500ms claim held only
on the warm minority path (claims C22 DISPROVEN as stated). *Fix:* persist
`creatives[].members` into the existing rollup payloads and serve rosters from
the rollup layer (same staleness labeling the grid already has); rollup size
+~50–120KB. Effort M. Blast radius: rollup shape, roster route.

**F5 · Degradation is invisible on /ads.** The board payload carries
`degraded[]`/`ok:false` but adsapp.js never renders it — a dead Meta token
renders **$0 spend and $0 CPL as if real** with no flag (code refs: adsapp.js
has zero `degraded` reads; `money(0)` renders "$0"). *Fix:* degradation strip in
the banner + spend/cost columns render "—" with a chip when the spend source is
degraded. Effort S. Blast radius: banner + column rendering.

**F6 · Post-action staleness shown as fresh.** No derivation write (card apply,
ruling conversion, nightly fills) invalidates the engine cache or rollups —
after "apply the date card", the affected cells keep OLD values labelled fresh
for up to 30min (+rollup age). resolution.py provably never touches
`attribution_engine._cache` (grep artifact). *Fix:* a `derived:epoch` kv bump on
every derivation write, folded into the compute cache key; background rollup
refresh kicked on bump. Effort S/M. Blast radius: compute cache keying.

**F2 · The trust journal truncates in ~2 days.** `integrity:autofix_log` caps at
200 and the event sweep floods it — oldest surviving entry was one day old at
audit (artifact 00: journal_total=200, oldest 2026-08-07). Ruling-conversion
evidence (charge ids) will age out. *Fix:* split streams — conversions/
supersessions into a `resolution:journal` capped 1000; sweep noise stays in the
200 cap. Effort S.

## SEV3 — robustness/security hardening (proposed wave)

**F3 · Stale invariant entries never retire from `integrity:pending`** (15 live
from past transient states while current invariants are all-ok — the A5
self-retiring doctrine is violated for this class; crying-wolf risk). *Fix:*
prune invariant-class pendings whose row currently passes, mirroring the
phantom prune. Effort S.

**F8 · Derived dates use the UTC day, not the Sydney day.** `_date_of()` slices
GHL ISO timestamps — a booking before ~10–11am Sydney derives the PREVIOUS day
(drill B9 pins it: `2026-07-09T22:30Z` = 08:30 AEST on the 10th → derives
07-09). Violates the today_sydney doctrine at the derivation boundary; affects
set/show derivation dates (close dates via Stripe use epoch→local date and are
correct). *Fix:* Sydney-convert before slicing; one-off re-derivation pass over
the 58 ghl-appt derivations (journaled supersedes). Effort M.

**F9 · Stripe pagination partial-failure absorbed silently** (drill B13):
error-with-partial-data falls through and breaks the loop — a first-payment
date can derive from an incomplete charge list with no degradation mark. *Fix:*
partial pull ⇒ degraded flag ⇒ ruling pass skips that run. Effort S.

**F16 · Nightly double-run race.** The kv day-stamp is written AFTER the 76s
sweep; two workers hit their 6h timers near-simultaneously (same boot) — both
pass the gate. Evidence: two accuracy rows per day on 08-07 and 08-08 (artifact
00). Cost duplication + duplicate rows, no wrongness. *Fix:* claim the stamp
before sweeping (set-if-absent), pid-stagger like the BAS tick. Effort S.

**F12 · Reflected XSS via the `?roster=` deep link.** `level`/`metric` parsed
from the URL render into the drill-title innerHTML unescaped, before server
validation can reject (artifact 04 triage; only real vector of 64 suspects —
all stored-XSS surfaces esc() clean). Requires a crafted link + authenticated
victim. *Fix:* client-side whitelist of level/metric + esc() in the title.
Effort S.

**F7 · Contact merge silently droops `reached`** until the next incremental
sweep re-checks the new id (drill B1: transient, self-healing, bounded by the
40/night cap). *Fix (optional):* sweep prunes cache ids absent from contacts.
Effort S.

## SEV4 — polish

**F10** · Crash between derived-store write and journal write leaves a
permanently unjournaled derivation (drill B14). Journal-first ordering. Effort S.
**F11** · Orphan derivations for deleted tracker rows are inert but immortal +
invisible (drill B15). Nightly orphan census → visible bucket. Effort S.
**F14** · Doc drift: ads.py claims "≤30 contacts" notes cap (code: 8); old
report docs describe the pre-engine roster mechanism as current. Correct the
records. Effort XS.
**F15** · verified_show_ratio fell 0.9 → 0.857 with no trend watch — not a bug
(new status-only shows derive faster than verification), but nobody is looking.
Folds into the sentinel's L1 delta-anomaly layer.

## RULING NEEDED — R1 · Refund semantics (drill B6)

A **fully-refunded** succeeded charge currently still AUTO-derives the close
date (cash stays tracker-authority, so money is safe — this is only about the
DATE evidence). Options:
- **(a) Keep as-is (recommended):** the payment happened → the close happened;
  a refund is post-close economics, not evidence the deal never closed. Zero code.
- **(b)** Refunded-first-charge downgrades to PROPOSED (human confirms).
- **(c)** A full refund retires the derivation (supersede-style, journaled).

## PROVEN-GOOD (fresh evidence, no finding)

First-touch close ownership incl. re-inquiry (B3) · two-deals-one-identity I17
(B2) · Nirosha dedupe class (B2b) · rename-mid-window hybrid keying (B4) ·
window boundaries inclusive + compare-window contiguity (B8) · cancel-rebook →
PROPOSED never auto (B12) · USD/partial payments don't disturb the date rung
(B7) · supersession disagreement surfacing (live-fired: Nirosha flag) · auth
walls on every ads/cfo surface (matrix, artifact 05) · media_buyer still
shipped-disabled (live env probe) · sweep-failure loudness (suite) · claims
C1–C16 re-proven (artifact 02; C17/C20/C22 disproven → F14/F3/F1).

## FIX-WAVE PLAN (awaiting approval)

Order: F5 → F6 → F2 (correctness cluster, ~1 session) · F1 (rollup-backed
rosters) · F8 (Sydney-day + re-derivation pass) · F3/F9/F12/F16 (hardening
batch) · F7/F10/F11/F14 (polish batch) · then Phase H sentinel (L0–L3 layers,
budgets, `AD_SENTINEL_PAUSE_HEALS` kill switch, SENTINEL-QUEUE.md) + scorecard
v1 re-measured with artifact-00 definitions. Disturbance risk: F1 touches the
rollup shape (grid consumers re-tested); F8 rewrites ~58 derivation dates
(journaled, reversible); everything else is additive.
