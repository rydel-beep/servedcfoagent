# CASH TRUTH REPORT — Stripe-aware cash + the "WA: blank" incident (2026-07-09/10)

## The incident, reproduced exactly

Rydel asked: *"what's our last cash collected and who was the last deal we closed"* and EDITH
replied a cash-collected cell was "genuinely blank" for **"WA"**. Reproduced verbatim against the
live tracker:

> "Here's what the tracker actually holds — WA: cash-collected cell is genuinely blank (synced …)."

## The WA verdict — NOT a column mismapping

The cash-collected **column mapping is CORRECT** everywhere. Verified against the live sheet
headers: col 7 `Business Name`, col 32 `Cash Collected` (siblings col 30 `Deposit Amount`,
col 38 `Net Cash`, col 9 `Market` all distinct); `find("cash","collect")` → 32; sampled recent
Won rows read the right cells (Hung's $8,305 / Lost Sheep $15,950 / Akuna $1,650 — all filled).

The failure was a three-stage **row-selection + routing** bug:

1. **No handler existed for aggregate "last cash collected"** — the per-client
   `handle_cash_for` fired because the text contains "cash"+"collect".
2. **Junk-row token hijack:** tracker row 263's Business Name holds an entire pasted lead
   enquiry ("Hey guys, I want to grow my business… strong idea of **what** I need to do…").
   Its "distinctive" token `what` matched "**what**'s our last cash collected".
3. **Loose substring row-match:** `read_client_row` then matched normalized "wa" ⊂
   "i**wa**ntto grow…" → landed on row 57, an UNRELATED junk row whose Business Name is
   literally **"WA"** (a state code typed into the wrong column). Its cash cell is blank →
   "WA: cash-collected cell is genuinely blank."

**Fixes (tracker_read.py):** junk names >40 chars excluded from the match roster;
conversational stopwords (`what/want/need/help/…`) can't be "distinctive" tokens; substring
row-matching requires ≥4 chars per side (2-char "WA" can never hijack again). All prior
read-before-assert tests still green.

## Column-locator map (consumer sweep)

Four INDEPENDENT locators resolve the cash column (all currently agree on col 32):
- **L1** `sheets_pull._col_index` — exact header string from config → `sheets.cash_collected`
  (THE snapshot aggregate).
- **L2** `range_unit_economics._ltc_col_map` — substring → `new_deal_cash` (greeting headline).
- **L3** `tracker_read._cols` — keyword-AND → verbatim per-cell answers.
- **L4** `sales_analytics_pull` — **hardcoded index 32** (3 call sites) → `avg_cash`,
  commission-% of cash.

**No scorecard/aggregate contamination:** every tracker-cash figure traces to raw Won-row
reads. Watch-items (not changed this round): `hormozi.m3_payback_days` mixes L1's total with
L4's average; L4 breaks silently if a column is ever inserted before 32; `active_clients`
won-deal `cash_collected` is wired to a field the upstream never populates (always None).

## Logging lag, quantified (21-day window, live Stripe vs live tracker)

23 succeeded charges: **10 covered** by their deal's cash cell, **9 under-logged** (Stripe
cumulative ahead of the cell), **4 unmatched**. Live examples at build time: Il Ritrovo
$2,500 behind, Gone Burger $1,500 behind, Cally Hotel's $3,355 (paid 6/24) on a row with a
blank cell. The pattern Rydel is feeling is real: cash lands days-to-weeks before cells
update — and the tracker's cash cell is CUMULATIVE with no payment dates, so it can never
answer "when did cash last land". Ongoing lag is now measured (observed watermarks in
kv_store: first-seen vs first-seen-logged per charge; avg + oldest-outstanding visible in
`snapshot.cash_truth.lag`), labelled "observed since 2026-07-09" — sheet edit history doesn't
exist, so it's prospective.

## The Stripe access gate — ALREADY OPEN (brief's premise was stale)

The restricted read-only key (rk_…, masked, server-side on Railway CFOagent) **is present and
reads /v1/charges, /v1/customers, /v1/payouts, /v1/balance** — verified live this build. It
was added at Round 7 and proven for per-payment reads at Round 12 (payback reconciliation runs
on it). Nothing was blocked; `stripe_reconcile.py` was dormant only because it waited on an
MCP tool that never materialised.

## The source hierarchy (built: cash_truth.py)

- **Tracker = deal truth** (who closed, offer, contract, close date) — unchanged.
- **Stripe = cash truth** (payment events; in-transit counts as collected-but-not-banked).

`unified_cash_view()` joins succeeded charges (balance_transaction expanded for per-charge
money-state) to tracker rows: **email exact > unambiguous normalized name > unambiguous
amount+date** — confidence recorded, ambiguity FLAGGED never guessed (two same-amount
same-window closes refuse to match; tested adversarially). Duplicate tracker rows per client
are resolved by preferring the Won row with the newest close date. Cumulative Stripe-per-deal
vs the cell (with 7-day pre-close grace for deposits) drives the needs-logging gap. PII: emails
never leave the module (asserted).

## Answer design (live-verified replay)

*"what's our last cash collected and who was the last deal we closed"* now returns, deterministically:

> Last cash collected: $5,500.00 from Fiona FITZGERALD (62Thirty Cafe & Bar) on 2026-07-09 —
> collected — settling into Stripe (available 2026-07-12). Tracker: logged. (matched by
> amount+date) Last deal closed: 62Thirty Cafe & Bar on 2026-07-09 — Scale Engine, $14,500.

Both truths, money-state labelled, no dead-end. When the cell trails Stripe: "Tracker: NOT yet
logged — flagged for the team." Without a key it defers honestly ("I won't guess"). Handler
runs before `handle_cash_for` in both chat endpoints (text + voice).

## Reconciliation activated + needs-logging surface

- **stripe_reconcile.py LIVE**: repointed from the never-built MCP tool to direct read-only
  API charges (shared reader). `paid_missing_from_tracker` (no row at all) now real;
  distinct from `needs_logging` (row exists, cell trails). Both flow to the snapshot.
- **Action feed**: needs-logging items persist as S2 until the team logs them (nudge wording —
  EDITH NEVER auto-writes cash cells; write-back scope stays churn/downgrade only).
- **Salience**: a new paid-but-unlogged gap is greeting-worthy once (watermarked per
  business+gap; a growing gap re-surfaces).
- **Queryable**: "what needs logging?" → the list + unmatched payments.

## Basis labels (one-engine discipline)

Figures from this build are named **Stripe-actual cash**; the existing aggregate stays
**tracker-logged cash** (`sheets.cash_collected`); `stripe_cash_collected_30d` (metrics
engine) remains its own labelled Stripe-revenue window. No metric was repointed. **OPEN
CHOICE FOR RYDEL:** should the headline "cash collected" figure move to Stripe-actual? If
yes, I'll repoint with before/after. Default kept: tracker basis, labelled.

## Verification

- Column mapping proven (live headers + row sample), WA explained + fixed, incident replay
  passes as the acceptance test (test_incident_replay_latest_cash_and_last_deal + live run).
- Blank-tracker/landed-Stripe reports both truths + lands on needs-logging (test + live Cally).
- In-transit/settling money labelled per the money-state model, never double-counted.
- Adversarial ambiguity (same amounts / same names) FLAGGED, never force-matched (tests).
- **359 tests pass, 0 failed** (338 prior + 21 new incl. conftest fix). Also fixed a
  PRE-EXISTING full-suite-only failure (2 tests): test env auth was order-dependent; root
  conftest.py now sets it deterministically.

## Status

Committed on branch `feat/cash-truth` — NOT merged/deployed (Rydel's gate). Parallel UI WIP
(dashboard.js / dashboard.html) untouched and excluded.
