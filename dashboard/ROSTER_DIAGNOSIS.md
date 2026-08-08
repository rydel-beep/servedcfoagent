# ROSTER DIAGNOSIS — roster engine · auto date ruling · row control (2026-08-08)

Phase-0/1 findings BEFORE any code. Live probes ran server-side (`railway ssh`,
read-only) — the local machine cannot reach the Railway-internal Postgres, so kv
state was read on the box. GHL probes used the live token, read-only.

## Phase 0 — live state deltas vs the brief

| Brief said | Live state found |
|---|---|
| 15 close cards: 6 Stripe-backed convert, 9 stage-only stay | **15 P1 cards live: 11 Stripe-backed, 4 stage-only** (Tommy Lê, Neri Roth Herrmann, Julieta Pablo Tadiaman, Jenny Bui). Acting on live state: 11 convert, 4 stay PROPOSED. |
| 17 set cards | 38 `setdate:multi` ids in `ads_truth:proposed` (incl. one duplicate id `setdate:multi:lucas reid` — append-across-runs artifact, dedup on write needed) |
| show-truth run | **Shipped** (DECISIONS #129 second entry, commits `aee6744`→`873204a`): verified/unverified show tiers live; 2 attendance cards open (matt annenberg, michiel de ruyter) |
| Xero scopes | **Not landed.** Server-side probe: Invoices 401. The Xero rung stays unbuilt — zero speculative code (same verdict as SHOW_TRUTH_DIAGNOSIS). |
| H1 no-candidate closes | Vipin, Dj, Hiep Nguyen, John Tamayo (4) — unchanged. P2: Fausto Falchi. |
| derived:dates store | 45 contacts with derivations (set/show/input); **0 derived close_dates yet** — the ruling converts the first ones. |

DECISIONS numbering: the log contains **two #129 entries** (PD conductor amendment
+ show truth) and a #130. The ruling entry takes **#131** to stay unambiguous.

## D1 — cell-drill census (what opens on click today)

| Surface | Leads/Qual/Reached/Sets/Shows/Closes | Today |
|---|---|---|
| Ads tab (level=creative), tier=ad, non-zero cell | drill → `/ads/api/roster` person list | ✅ opens people (but row shape has no identity/provenance chips, no tracker link, no event-date framing) |
| Ads tab, **zero cell** | nothing (`data-stage` only set when value truthy) | ❌ dead click |
| Ads tab, **tier rows** (IG DM / Unattributed / Ambiguous) | nothing (`DRILLABLE` requires `tier==='ad'`) | ❌ dead |
| **Names / Batches / Campaigns / Account tabs** | nothing (drill gated on `state.level==='creative'`) | ❌ dead — no cell on any ladder tab opens anything |
| Anomaly badges (↤ ◔ v·u) | `anomalyPanel()` — **client-side filter over `board.rows`** | ⚠ opens, but it is a PARALLEL person-list computed in JS (the doctrine violation this build deletes) |
| Creative name | dossier — server-side ledger built in `/api/dossier` | ⚠ opens, but the ledger is a SECOND parallel list (own contact join, own filter) |
| Hygiene rail chips | deal panel per person | ✅ (single-person door, not a roster) |
| Headline tiles | nothing | out of scope (aggregate tiles, not cells) |

Known pre-existing I17-class defect found in the census: on the **activity clock**
the sets/shows drill filters cohort view-rows (`_STAGES` predicates over
`result.rows`) while the cell counts leads by `set_date`-in-window — the drill can
disagree with the cell. The engine-side member lists (below) kill this class
structurally.

## D2 — identity linkage baseline (all 1,114 tracker rows, live)

- **1,001 (89.9%)** ID-linked tracker↔GHL by email (exact).
- **82 (7.4%)** name-only unique match (unlinked — "name-match" chip).
- **6 (0.5%)** name matches multiple contacts (ambiguous — quarantine chip).
- **25 (2.2%)** tracker-only (no GHL contact at all — "tracker-only" chip).
- Sum of matched = 97.3% — **the hygiene header's 97.3% contact→tracker claim
  verifies exactly.** The 2.7% remainder = the 6+25 above → flagged-chip rows.
- **60 of the 1,001 email-linked** rows have tracker name ≠ GHL name → the
  "name discrepancy" chip class (both names shown).
- GHL-only (contact with no tracker row) is not a roster row today by
  construction (rosters are tracker/lead-universe scoped); the chip exists for
  future consumers, rendered when a surface supplies such a person.

## D3 — GHL payment-class probe (live token, exact endpoints)

| Endpoint | Status |
|---|---|
| `GET /payments/orders?altId=<loc>&altType=location` | **401** `The token is not authorized for this scope.` |
| `GET /payments/transactions?...` | **401** same body |
| `GET /invoices/?...` | **401** same body |

Verdict: GHL payment/transaction objects are **scope-locked under the current
token** — the payment-class rung via GHL cannot be probed per contact (the
location-level 401 gates everything below it). The 4 stage-only cards therefore
**stay PROPOSED**, per contact: Tommy Lê, Neri Roth Herrmann, Julieta Pablo
Tadiaman, Jenny Bui — each has only a GHL closed-won stage-move candidate, and
stage timestamps remain PROPOSED forever under the ruling. No GHL-payment code is
built (same zero-speculative-code rule as the Xero rung).

## D4 — row-cap origin

**There is no hard cap anywhere.** The "~70" is the natural rollup shape of the
default window: live 30d cohort = 70 creative rows (67 renderable ad rows) and 70
tracker view-rows. The scoreboard tbody renders ALL rows unpaginated (90d already
renders 184); the Live-tracker table paginates client-side at `PAGE = 150` with a
"show more" button. Live shapes:

| Window | creative rows | renderable ad rows | people rows |
|---|---|---|---|
| 30d | 70 | 67 | 70 |
| 90d | 184 | 181 | 263 |
| All (3650) | 183 | 180 | 1,113 |

Payloads already ship complete datasets (board carries all rows; sort/find already
operate pre-slice). Worst case is ~1.1k table rows — comfortably a **windowed
client-side render** (slice after sort), no server pagination or virtualization
needed. Decision: the row control is a render-window selector (70/150/300/All)
applied AFTER full-dataset sort/filter, tier rows appended pinned outside the
slice. Perf measured in Phase 3 against the <2s grid budget.

## Build plan consequences

1. **Members are recorded where counters increment** (attribution_engine): every
   bucket metric (leads/qualified/reached/sets/shows/closes + annotation classes)
   appends the lead's name_norm at the same line the counter moves. I17
   (len(roster) == cell) becomes near-structural; a suite sweep + nightly sampling
   (20 random cells) guard the rest.
2. **roster_engine.py** is the ONE cellspec→roster path. Ladder tabs resolve group
   membership through `_aggregate`'s existing `member_keys` (sums == concat of
   member rosters because tiers partition leads). Consumers refactored: /api/roster
   (all levels + tiers + anomaly classes), the dossier ledger, the JS anomaly
   panel. The JS `board.rows` filter and the dossier's private join are deleted.
3. **Ruling (#131)**: Stripe first-payment at ID-exact (email) AUTO-derives blank
   close dates via the existing `record_derived_date` journal; name-only Stripe
   matches and all GHL-stage candidates stay PROPOSED. Conversion pass is
   idempotent; each conversion journals card id → derived date → charge id as
   "ruling-conversion DECISIONS #131"; one action-feed item totals the cash placed.
   P1 cards for derived closes stop being generated (queue shows only what needs a
   human); the Piolo source-fill item persists via close_integrity as before.
4. **Row control**: client-side selector 70/150/300/All, persisted per user
   (localStorage), URL `?rows=`, slice after sort/filter, tier rows pinned,
   applied to both the grid and the tracker table.
