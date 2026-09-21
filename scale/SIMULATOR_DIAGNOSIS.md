# SIMULATOR DIAGNOSIS — reproduced from Rydel's seat (2026-09-21)

Method: Playwright/Chromium, owner login, production `/dashboard/scale`
(build `a42c58a`), Rydel's exact sequence. Artefacts:
`dashboard/evidence/simulator-phase0/` (phase0.json + step screenshots).

## The verdict: failure (b) — LOCK SEMANTICS, with a silent-revert aggravator

The step-by-step DOM record:

| step | spend field | CPL field | leads field | the sentence |
|---|---|---|---|---|
| 0 initial | 10,150 | 88.26 **(locked 🔒 by default)** | 115 | "…$88.26 per lead → 115 leads" |
| 1 typed spend **15000** | 15,000 | 88.26 | **170 ✓ moved** | "…$88.26 → 170 leads" |
| 2 typed CPL **120** | 15,000 | **shows "120"** | **170 ✗ DID NOT MOVE** | **still "…$88.26 per lead"** |
| 3 typed spend 20000 | 20,000 | **REVERTED to 88.26** | 227 | "…$88.26 → 227 leads" |

- Zero console errors, zero page errors on every step — **not (c)**.
- Spend edits recomputed leads and the chain instantly — **not (a)**.
- The chart tracked the fields (it renders from the same state) — **not (d)**.
- Elasticity was OFF (default) — **not (e)**.
- **The cause:** CPL shipped **locked by default**, and the input handler
  ignored edits to the locked field
  (`if (id === 'sim-cpl' && simState.lock !== 'cpl') …` — his keystrokes
  hit a field that LOOKED editable but was semantically pinned). Worse,
  the next recompute **overwrote his typed 120 with the derived 88.26** —
  a silent revert. The "lock any field" triad made behaviour depend on
  which field was pinned; nothing on screen said his edit was being
  discarded. Exactly his words: *"I changed the cost per lead … and it
  didn't change the amount of leads."*
- The target box worked correctly ("$23,886/mo … 40 calls") — the
  complaint is the triad, not the solver.

## The fix (this wave)

Locks are RETIRED. **Two inputs, one output**: SPEND and CPL are always
editable inputs; LEADS is always the derived output (leads = spend ÷ CPL).
Elasticity mode makes CPL explicitly read-only-derived ("effective CPL at
this spend"), visually disabled — never an editable-looking field that
drops input. Target mode is a separate labelled toggle where SPEND becomes
the output. One formula core shared by page and engine; a BEHAVIOUR gate
(not just a render gate) types into the fields on production and asserts
leads move on BOTH inputs before any deploy stands.
