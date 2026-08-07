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
