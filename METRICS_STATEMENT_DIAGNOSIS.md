# METRICS STATEMENT — Phase 0 + Scott's payment, traced in code (29 Sep 2026)

Status: **CODE HALF DONE · LIVE HALF BLOCKED.** Read-only production probes
(`railway ssh` on CFOagent) are refused by the session's permission layer. No
production values appear below. None are invented. The signed
`METRICS_STATEMENT_2026-09-29.md` needs live values, so it is **not written**
(writing it without them would be fabrication).

## Phase 0 — which unit-economics builds are live (from DECISIONS / PROMPT_LEDGER / STATUS)

| Build | State | Evidence |
|---|---|---|
| COMMISSIONS → TRUE CAC (rulebook) | SHIPPED | DECISIONS #159; `sales_cost.py`, `comp_rulebook.py` |
| COST-CARD | SHIPPED | DECISIONS #163 |
| CLOSE-REGISTER | SHIPPED | DECISIONS #164; ledger row 46; `close_register.py` |
| NET-PROFIT (P&L engine) | SHIPPED | DECISIONS #165/#166; `pl_engine.py` |
| UNIT-ECONOMICS-ACCURACY | **NOT SHIPPED** | Stopped at Phase 0 (`UNIT_ECON_DIAGNOSIS.md`). Renewal is still the B1 upper bound, completion is still the 85% placeholder, the headline is still MTD, there is no floor, and there are still five unit-econ maths |

So today's LTGP:CAC tile is: **MTD window**, register closes (confirmed only),
`LTV = contract × (completion + renewal)`, gross margin from `pl_engine`, and
TRUE CAC from `sales_cost`.

## The identity, as coded

Tile = `avg_ltv ÷ cac_fully_loaded` = `(Σ LTV ÷ n) ÷ (Σ acq ÷ n_sc)`.
When `n` (register closes) = `n_sc` (sales_cost closes), n cancels and the tile
equals **Σ LTV ÷ Σ acquisition cost** exactly. Both counts read the same
register window, so the identity holds by construction. A hand check needs only
the live close list and cost lines.

**Correction to the brief's premise:** the tile is **month-to-date**, not
trailing 90 days. Witnessed Σ acq MTD = 4 × $4,911 = **$19,644**, not about $60k.
On MTD, one extra close is not imperceptible:

- If Amoroso lands **with** a $4,799 contract, the coded formula gives
  LTV = $8,878 and LTGP = $5,789 at 65.2%. LTV:CAC becomes
  $143,832 ÷ ($19,644 + commissions). That is 7.32× with no commission,
  6.97× with $1,000, and 6.81× with $1,500. Visible at 2 d.p. unless the
  commission happens to land near $1,300.
- If Amoroso lands **without** a contract value, it adds $0 LTV but adds
  commissions. The ratio **falls** (about −0.3× on $1k of commissions).
  Also visible.

**So "LTGP:CAC didn't move" rules out (a) imperceptible.** It points to (b) no
confirmed close in the MTD window, or (d) stale. (c) would have *moved* the
tile, downward.

## Scott's payment — every link, as the code handles it

1. **Stripe → client.** `unmatched_payments.scan()` (2-hour loop) runs the one
   matcher: alias → exact email → exact name. A payer named "Scott …" can never
   match "Amoroso Gelateria" on a name. It matches only via an email on the
   tracker row or a confirmed alias. Otherwise it sits on the unmatched panel,
   and **stop (b0)** applies: no client, no close. PENDING-LIVE:
   `payments:unmatched` state and `stripe:payer_aliases`.
2. **Client → close.** A new client's matched payment becomes a
   `close_detect._from_payments` candidate with a single source ("payment").
   Register status needs the tracker (the authority) **or** two sources, so
   payment alone makes it `proposed-needs-evidence`. `close_register.closes()`
   drops proposed entries, so **stop (b)** applies: the tile is unchanged by
   design, and nothing tells you why. PENDING-LIVE: Amoroso's register entry,
   its sources and its status.
3. **A payment matched to a client already in the register.** This is
   **DEFECT F1, FIXED.** The scheduled scan never invalidated. `close_detect.tick`
   invalidates only on a *new close key*, and the register rebuilds only on
   invalidation. So a charge that corroborated an existing GHL-stage-only
   entry (the step that should flip proposed → confirmed) never reached
   the register or the tiles until some unrelated event rebuilt it. That is
   **stop (d)**.
   Fix: `unmatched_payments.scan()` now invalidates when a charge ID is newly
   matched (idempotent; no churn on re-scan).
   Test: `tests/test_payment_match_invalidation.py` (3 tests).
4. **Close → contract.** The contract comes from the tracker cell, then the
   Closed Deal Form, then the gap ledger. **DEFECT F2 (open):** the form rung
   takes the *first money-like value of any form field*
   (`close_register.py:281`). That is not a package inference, but it can pick
   up a payment amount typed into the form as the "contract". It needs the
   form's field names to fix (PENDING-LIVE).
5. **Contract → LTV/LTGP.** This runs under the not-yet-fixed formula
   (renewal at the upper bound, one renewal priced at the signed amount). An
   upfront $4,799 deal gets full renewal credit at $4,799. This is
   `UNIT_ECON_DIAGNOSIS.md` D1/D4.
6. **Commissions.** **DEFECT F3 (open):** `sales_cost` costs a deal whose package
   or closer is unrecorded "at the blended average". That is a guessed
   commission, and it breaks "rulebook or needs your number". It needs changing
   in the unit-econ build.
7. **Cache → tile.** `exec_top.refresh_cache()` runs on the 2-hour loop and
   inside `invalidate_now`. There is no other path. With F1 fixed, latency is
   one scan cycle (≤ 2 hours, since the scan is on the slow loop), then
   immediate. Getting to minutes needs the scan on the 5-minute tick, which
   is an external Stripe call on every tick. That is a decision for Rydel.

## What's needed to finish (all read-only)

- `payments:unmatched` + `stripe:payer_aliases` → which charge is Scott's, and
  what it matched to
- `close_register.latest()` entry for Amoroso → sources, status, contract,
  close date
- `closes:last_invalidation` + the `exec:cache:unit_econ` timestamp →
  staleness
- The live Σ LTV / Σ acq lines for the MTD window → the hand identity check

## Changed in this session

- `unmatched_payments.py` — F1 fix (invalidate on newly matched charge)
- `tests/test_payment_match_invalidation.py` — 3 regression tests
- Suite: 1515 passed, 1 failed. The failure is **pre-existing** and unrelated:
  `test_alias_appointments.py::test_every_window_is_stated_in_words` seeds a
  2026-09-28 event into a window that starts today. It fails identically with
  the change stashed.
- NOT deployed: the deploy rule needs a fully green suite, and nothing can be
  verified live.
