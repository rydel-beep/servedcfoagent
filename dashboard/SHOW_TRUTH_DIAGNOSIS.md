# SHOW TRUTH — DIAGNOSIS (2026-08-08, counts before code)

## Phase 0 — read state, honest nightly answer, probes
- **Nightly**: the two accuracy rows on file are the 2026-08-07 MANUAL runs (v1 with
  the checker bugs, v2 clean). The scheduled tick had not fired yet at inspection
  (the tick stamp was cleared during verification); it is armed for tonight. The
  event-sweep AUTO backlog is done (35 set + 19 show dates derived); the "remaining"
  count (72) is mostly multi-appointment contacts (PROPOSED, correctly not auto'd)
  and no-appointment contacts that legitimately re-check on cache expiry — NOT
  unfinished AUTO work.
- **CALL RECORDS: READABLE under current scopes.** /conversations/search → 200;
  /conversations/{id}/messages → 200. Call shape (empirical): message `type: 1`,
  `meta.call.duration` (seconds — **sometimes null**), `meta.call.status`
  ("completed"), `dateAdded`. No token changes.
- **XERO: the re-consent has NOT landed.** Invoices → 401, BankTransactions → 401
  (TaxRates/reports still 200). §2.2 is the gap paragraph — zero speculative code.

## D1 — THE INFLATION BOUND
Of the 19 status-derived shows: **1 call-evidenced · 0 outcome-evidenced · 18
(94.7%) rest on status alone — unverifiable as built.** The hole is real and large.
Nuance the cards will carry: several unverified shows have LONG calls near but
BEFORE the scheduled date (ron ling 3,489s · albert hakfoort 1,478s · jingjie
1,486s · matt annenberg 1,070s) — real conversations, but not attendance of THAT
appointment under the strict on/after rule; they render as card context for
Rydel's one-click, never as silent verification.

## D2 — CALL COVERAGE
**19/22 (86%)** of sampled known-real conversations (closes + dated shown sets)
have retrievable call records. Coverage is HIGH → evidence-required shows will not
structurally undercount; the residual 14% is the honest uncertainty band, stated
on the dashboard label.

## D3 — XERO
Scopes not landed (exact codes above). The five no-evidence contacts (Vipin, Dj,
Hiep Nguyen, John Tamayo close, Neri input) remain the bank-transfer blind spot
until the re-consent lands; the probe is re-run nightly-cheap via the existing
debug endpoint when Rydel says it's done.

## Design confirmed by the numbers
Three tiers ship: SHOW·VERIFIED (call ≥ set_call_seconds on/after the scheduled
date, ID-exact — or outcome-evidenced by a downstream close) · SHOW·UNVERIFIED
(kept-status only; counted SEPARATELY, PROPOSED card each) · NOT-A-SHOW
(cancelled/invalid/noshow — set only, unchanged). Tracker-flagged shows stay
AUTHORITY (an explicit human record, not absence-of-flag) and render as their own
provenance. Unit economics consume tracker+verified; unverified is visible beside.

---

## THE BUILD + LIVE RUNS (2026-08-08, commits 9d9ad7b + aee6744 — DECISIONS #129)

### Final live classification (all 19 derived shows — the hand-audit table)
- **17 × show:tracker-authority** — the setter explicitly marked "Showed" on the
  tracker row; questioning the authority's explicit record would invert the
  doctrine. (Run 1 had carded all of these — the refinement retired the noise.)
- **1 × show:call-evidenced** — sami amor: call `l2TRdDhyn6l1dvjxiqY3`, 319s,
  2026-04-24 ≥ scheduled 2026-04-23.
- **1 × unverified** — matt annenberg: appointment scheduled 2026-08-12 (the
  FUTURE); his 1,070s call on 08-05 is the set call, shown as card context. The
  nightly pass auto-upgrades when post-appointment evidence lands.
- Near-miss pattern from run 1 (17 long calls of 10–58 min just before the
  scheduled dates) resolved into the tracker-authority tier — those conversations
  were real and the tracker had already said so.

### Cells + economics
Shows per window UNCHANGED (30d 6 · 60d 11 · 90d 20; 1 in-window unverified,
labelled `Nv·Mu`) — the tiers reclassified evidence, they did not inflate or
deflate honest counts. Show-rate flags now consume VERIFIED only. **Verdicts
moved: NONE** (named check, live).

### PROPOSED queue delta
Attendance cards: 18 (run 1) → **1** (run 2, after the authority refinement) —
matt annenberg, with his near-miss context. Close cards: unchanged (15, Xero
corroboration pending scopes).

### Xero (the gap paragraph)
GET /api.xro/2.0/Invoices → **401** · GET /api.xro/2.0/BankTransactions → **401**
(probed 2026-08-08 via the deployed service; report-read scopes still the only
grants). The rung is NOT built — zero speculative code. When Rydel's re-consent
lands, the probe (existing /debug/xero-probe) flips and the rung follows the
standing convention (payment dates → PROPOSED, corroboration shown on cards).
The five bank-transfer no-evidence contacts remain the honest blind spot.

### Nightly (verbatim schedule)
integrity_sweep (kv-stamped daily in the attribution loop) now runs: invariants →
undated-set census → spine census → quad-check → reached sweep → date-resolution +
supersession → event sweep (40/night) → **show verification (upgrades journaled,
quiet positives in the feed)** → accuracy row with **verified_show_ratio**
(currently 18/19 = 0.947) → self-retiring flag publish → phantom prune.
