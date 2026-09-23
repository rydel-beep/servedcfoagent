# WHY A DEAL CLOSED TODAY ISN'T IN THE NUMBERS — AND WHO CAN SEE WHAT

**2026-09-23 · served-cfo-agent · diagnose first**

---

## THE THREE-LINK VERDICT

Rydel closed Koji today, the money arrived under the payer name "Sanatani
Rombola", he pressed refresh, and nothing moved. There are three links
between "a deal closed" and "the ratios changed". **All three are broken, and
each one on its own is enough to produce exactly what he saw.**

| link | state | what breaks it |
|---|---|---|
| **1 · the close event** | **BROKEN** | the tracker's close columns have been empty since **24 July** (R-GAP). The engine's own close list is built from them, so a close today produces no row. |
| **2 · the money** | **BROKEN** | the matcher attaches a payment to a client by name. The payer name is not the client's name, there is no alias for it, and no path exists to attach the two — so the money counts as cash and belongs to nobody. |
| **3 · the recompute** | **BROKEN** | the one job that reads closes out of the CRM instead of the tracker (`gap_reconcile.rebuild_closes`) is called from **exactly one place: the owner-only `/api/gap/rebuild` button.** No loop runs it. Neither Refresh button touches it. |

### Link 1 — where a close comes from

`finance_analysis._closes_union()` is the single place the estate agrees on
what closed in a window. It unions:

1. `attribution_engine.compute()` — deals from the **tracker**, and
2. `gap_reconcile.close_ledger()` — but **only entries in state `AUTO`**.

The tracker half has produced nothing since 24 July, which is the whole
reason R-GAP exists. So every close since then depends entirely on the ledger
— and on that ledger having been rebuilt, and on those entries being `AUTO`.

### Link 2 — why the money doesn't find the client

Two separate matchers, neither of which can see through a different payer
name:

- `stripe_reconcile._match_payment()` scores a payment against the tracker's
  identity index. Before this change it would auto-attach on a **distinctive
  surname** or a **first name plus a plausible amount** — a real risk of the
  opposite failure (money attached to the wrong venue with nobody seeing the
  decision).
- `gap_reconcile._stripe_hits()` — the one that decides `AUTO` vs `PROPOSED`
  — matches **email-exact or full-name containment only**, and **never
  consults the payer-alias store at all.** So even a confirmed alias would
  not have made Koji's close `AUTO`.

A payment under a name that belongs to neither the contact nor the venue
therefore leaves the close **PROPOSED**, and `_closes_union` ignores
`PROPOSED`. The cash still counts (R-CASH reads Stripe totals), which is why
the bank figure looks right while the client is invisible — the most
misleading shape this failure can take.

### Link 3 — nothing recomputes

- `gap_reconcile.rebuild_closes(apply=True)` — called **only** by
  `POST /dashboard/api/gap/rebuild` (owner-only).
- the nightly `gap_reconcile.sentinel_watch()` calls `refresh_convergence()`,
  which rebuilds the ledger — but that is a once-a-day rung, not a pipeline.
- `/api/refresh`, `/api/resync` and the new `/api/refresh-now` (#160) pull
  sources and rebuild the engine BLOCKS. **None of them runs close
  detection.** So "refreshed and still not updated" is the literal truth: he
  refreshed everything except the step that would have found the close.

**None of these three failures is a crash.** Every one of them is a pipeline
waiting on a human: fill a cell, press a button, name a payer.

---

## WHAT WAS BUILT IN RESPONSE

| link | the fix |
|---|---|
| 1 | `close_detect.py` — a close is visible as soon as **any** source shows it: the tracker, the CRM stage (not limited to the gap window), the stage recorder's own transitions, or a payment matched to a client with no close on file. Provenance on every entry; the others listed as corroboration-pending; what is still missing named. |
| 2 | `unmatched_payments.py` — the money that landed without a name becomes a panel on the home dashboard with a one-click owner confirmation that writes the alias, journals who said so and which charge proved it, and applies it to future charges. The matcher now attaches on **identity only** (alias, exact email, exact name); a resemblance is a proposal. |
| 3 | the five-minute freshness tick runs the detection, and a new close or a confirmed alias **invalidates immediately** — the derivation epoch is bumped and the engine blocks rebuild, so the next page load is already right. |

---

## PIOLO'S ACCESS, AS IT WAS

Measured with `scripts/role_matrix.py` (every route, one session per role,
the real status codes — not a reading of the decorators).

**The shape before this change:** Piolo could reach 97 of the 127 probed GET
routes, and the ones he could NOT reach were, for the most part, exactly the
ones Rydel now wants him to have:

| denied to Piolo before | after R-PIOLO |
|---|---|
| `/dashboard/sales`, `/dashboard/scale`, `/dashboard/scale/travelling` | **granted** (read) |
| `/api/travelling`, `/api/travelling/history`, `/api/travelling/remodel` | **granted** |
| `/api/scale/*` reads (backtest, defaults, calibration, plan-vs-actual, scenarios, north-star, scenario-pdf) | **granted** |
| `/api/decision-cards`, `/api/finance-analysis(.pdf)`, `/api/ground-truth`, `/api/renewal/clients`, `/api/telemetry` | **granted** |
| `/api/csm/*`, `/dashboard/csm` | **still owner-only** (carve-out) |
| `/api/comp/rules`, `/api/comp/cost` | **still owner-only** (carve-out) |

And two things he COULD reach that he no longer can, both flagged to Rydel
rather than slipped in:

- **EDITH's voice** (`/api/tts`, `/api/voice-status`, `/api/entrance-audio`,
  `/audio/entrance`) — the ruling says the voice stays owner-exclusive.
- **EDITH's memory pages** (`/dashboard/memory/*`) — the fact store and the
  conversation transcripts carry owner-scope context. This one is a
  judgement call, not something Rydel asked for; one line lifts it.

The old model had no allowlist for the coo role at all: `require_auth` let
him straight through to anything not individually marked `@require_owner`.
That is why a NEW route was granted to him by default — the opposite of the
rule Rydel asked for.

---

## LIVE EVIDENCE — NOT YET COLLECTED

The Railway CLI session expired mid-session (`railway login` needs a human),
so the parts of Part 0 that need production data are **not done and are not
claimed**:

- the Koji opportunity's actual stage, owner and stage-change time,
- whether the stage recorder captured the transition,
- Kalin's Closed Deal Form entry (package, term, contract value),
- the charge id, amount and date under "Sanatani Rombola",
- the full list of currently unmatched payments.

Everything above this line is read off the code paths and the route map,
which is where all three broken links live. The live pull confirms **which
link fired first for this particular deal** and supplies the figures for the
before/after table — it cannot change the fact that all three are broken.
