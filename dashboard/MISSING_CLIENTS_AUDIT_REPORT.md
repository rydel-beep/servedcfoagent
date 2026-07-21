# MISSING RECENTLY-CLOSED CLIENTS — AUDIT (Phase 0)

**Date:** 2026-06-24 (Sydney) · **Scope:** served-cfo-agent/ · **Status:** Phase 0 complete — HARD STOP for Rydel confirmation before any change.

Question: why does EDITH have "no info" on **Cally Hotel** and **Lucas** when both closed recently (Lucas reportedly paid via Stripe today)?

---

## TL;DR

The deals are **in the tracker** and (as of the latest refresh) **in EDITH's snapshot**. The reason EDITH couldn't speak to them by name is a combination of a **read bug in the chat context builder** (client names get dropped before they reach EDITH) and a **refresh-lag window** (deals closed today aren't visible until a refresh runs). One of the two names (Lucas Doan / The D's) is additionally a genuine **source gap** — marked Won but money fields left blank.

The Stripe↔tracker reconciliation the brief asks for **cannot be built as specified** — the Stripe MCP exposes aggregate numbers only, no per-customer/per-charge data. Honest blocker, detailed below.

---

## CANONICAL SOURCE NOTE (important correction)

The brief lists the tracker as **gid `544609965`**. Fetched live, that gid is **NOT the data tab** — it's a 30-row instructions/guardrail banner ("SERVED — LEAD-TO-CASH TRACKER (Team)", the "DO NOT REINTRODUCE QUERY()" warning). The actual 1,199-row deal data lives in the tab **named** `"Lead-to-Cash Tracker"`, which is exactly what the code already reads (`SHEET_CONFIG["tab_name"]`, fetched by name via gviz). So the code reads the right data; the gid in the brief points at the wrong tab. No repoint needed — flagging the discrepancy rather than acting on it.

- Code fetch (sheets_pull.py, sales_analytics_pull.py): `gviz/tq?...&sheet=Lead-to-Cash Tracker` → full sheet, **no row cutoff** (gviz returns all rows). Live fetch = 1,199 data rows, 53 columns.

---

## PER-NAME TRAIL THROUGH EVERY LAYER

### 1) "Cally Hotel" = **Lucas Reid**, *The Cally Hotel* (tracker data row 60 / sheet row 62)

| Layer | Finding |
|---|---|
| **Raw tracker** | PRESENT & FULLY LOGGED. Closer Call Outcome (col 23) = **Won**; Offer Sold = Growth Pro; **Close Date = 6/24/2026 (today)**; Contract = $18,300; **Cash Collected = $3,355.00**; Closer comm = $900; Setter comm = blank. |
| **EDITH ingest range** | WITHIN range (full sheet read, no cutoff). Passes the `outcome == "won"` filter and the 30-day window (close 6/24 ≥ cutoff 5/25). Verified by re-running the pull on the live sheet: Cally's $3,355 **is** in `deals_won_in_window=10`, `cash_collected=52,050`. |
| **Client list (active_clients)** | PRESENT. `active[0]` = "The Cally Hotel", status Active, **source=`health_tab`**, MRR $3,050, contract $18,300, close 2026-06-24, `sources_agree=true`. |
| **Snapshot** | PRESENT — "cally" appears 7× in the live snapshot. `generated_at` = 2026-06-24T18:52 (today). |
| **Stripe** | Cannot confirm a per-customer payment — MCP is aggregate-only (see §3). Aggregate revenue is non-zero (26 charges, trailing 30d). |
| **What EDITH actually receives** | **DROPPED in voice/lean mode; buried in text mode** — see read bug below. This is why she "has no info." |

**Root cause for Cally Hotel: (D) + (C).** Data is correct and current; the failure is freshness lag (if asked before today's refresh) and the chat-context read bug that strips client names.

### 2) "Lucas" = **Lucas Doan**, *The D's bar and dining* (tracker data row 39 / sheet row 41)

> Most likely the "Lucas" in the brief, since it's listed as a *separate* client from Cally Hotel. (If you meant Lucas **Reid**, that's the Cally Hotel row above — they're the same person/venue.)

| Layer | Finding |
|---|---|
| **Raw tracker** | PRESENT but **WON-BUT-UNLOGGED**. Closer Call Outcome = **Won**; **Offer Sold, Close Date, Contract Value, Cash Collected, both commissions = ALL BLANK**. Input Date = 2026-06-11. |
| **EDITH ingest range** | Within range. Passes `won` filter; enters window via input-date fallback (6/11). But cash/contract/close are blank → **correctly excluded** from cash/close/commission totals, and **flagged** as `won_but_unlogged` (count=1). |
| **Client list (active_clients)** | PRESENT as "The D's bar and dining", status **`signed_not_in_health`**, source=`ltc_tracker`, all financials null, `awaiting_stripe=true`. |
| **Snapshot** | The business name is in `active_clients`. The **person name "Lucas"/"Doan" appears 0× anywhere in the snapshot** (lead names are intentionally stripped — they contain emails/PII). |
| **Stripe** | "Paid via Stripe today" cannot be confirmed (aggregate-only MCP). If true, the tracker is behind reality — cash not entered at source. |
| **What EDITH receives** | The `won_but_unlogged` **count** reaches her (degraded flags are in chat context) — so she can say "1 won deal isn't fully logged" but **cannot name it**, and has no money for it. |

**Root cause for Lucas Doan: (B) at the money level + (A) if he's paid.** In tracker, flagged Won, but key fields blank → correctly excluded. If he paid via Stripe, the cash/close entry is missing at source — that's a Rydel/team entry, EDITH can't invent it.

### 3) "Lucas Lucas" (row 499) — old Jan-2026 lead, not Won, irrelevant. Noted to avoid confusion.

---

## ROOT-CAUSE VERDICT (per the A/B/C/D scheme)

| Name | In Stripe? | In tracker? | Key fields? | In EDITH range? | In snapshot? | Verdict |
|---|---|---|---|---|---|---|
| **Cally Hotel (Lucas Reid)** | unverifiable¹ | ✅ | ✅ populated | ✅ | ✅ | **C + D** — read bug + refresh lag |
| **Lucas Doan (The D's)** | unverifiable¹ | ✅ | ❌ blank (Won-unlogged) | ✅ (flagged) | business only, no money | **B + A** — source gap |

¹ Stripe MCP cannot return per-customer data — see below.

---

## THE READ BUG (C) — chat context drops client names

`dashboard/chat.py` → `_build_context_block()` builds EDITH's "ACTIVE CLIENTS" section like this:

```python
summary = {
    "total_clients": ac.get("total_clients"),   # ← key does not exist → None
    "total_mrr":     ac.get("total_mrr"),        # ← key does not exist → None
    "avg_mrr":       ac.get("avg_mrr"),          # ← key does not exist → None
    "discrepancies": ac.get("discrepancies"),
}
```

Two defects:
1. **Wrong keys.** The real keys are `active_count` (=38) and `total_mrr_derived` (=$78,446); there is no `avg_mrr`. So the headline client count and MRR EDITH sees are **null**.
2. **No per-client list.** The curated summary never includes `active[]` (the actual client names). 
   - **Text chat (lean=False):** saved only because the *entire* raw snapshot is appended as "FULL SNAPSHOT" — so names exist, but buried in a large JSON blob (and still no headline count).
   - **Voice/lean (lean=True):** the FULL SNAPSHOT dump is **deliberately dropped** for speed. Result: EDITH has **zero client names** — she literally cannot answer "tell me about Cally Hotel" by voice, for *any* client, new or old.

This is the dominant, durable reason EDITH "has no info on Cally Hotel."

A related, by-design limitation: **person/first names never reach the snapshot** (lead-name column is PII-stripped; `active_clients` uses business names). So a query for "Lucas" can't be matched even when "The D's bar and dining" is present.

## THE FRESHNESS WINDOW (D)

- Snapshot refresh: scheduled daemon every **6h** (`REFRESH_INTERVAL_HOURS`), and only if older than the **4h** stale threshold. Manual `POST /cfo/refresh` forces an unconditional rebuild.
- Effect: a deal closed/entered today can be invisible for up to several hours until the next tick. Verified that a **same-day manual refresh DOES pick up today's closes** (live recompute matches the snapshot). So freshness is "fine once refreshed," with a multi-hour blind spot in between.

## THE STRIPE RECONCILIATION BLOCKER

The brief's durable fix — "flag Stripe payments with no matching tracker entry" — **cannot be built as specified.** The Stripe MCP (`served-stripe-mcp-production`) exposes only 6 **aggregate** tools (`get_stripe_mrr`, `get_stripe_revenue`, `get_stripe_subscriptions`, `get_stripe_customer_count`, `get_stripe_failed_charges`, `get_stripe_payouts`). **None return per-customer name/email/amount.** CLAUDE.md already records this ("Stripe MCP provides aggregate MRR only").

To match Lucas's Stripe payment to a tracker row by name/email/amount, one of these is required (a real decision for Rydel):
- **(i)** Extend the Stripe MCP with a `list_recent_charges` / `list_payment_intents` tool returning customer + amount + date (server-side, read-only); then EDITH can reconcile. — *Most robust.*
- **(ii)** Lean on the tracker's existing manual **"Verify from Stripe"** column (col 41) as the reconciliation signal — no Stripe API, but depends on the team filling it.
- **(iii)** Drop the automated reconciliation; rely on the `won_but_unlogged` flag (already live) to surface incomplete Won rows.

I will **not** fabricate a reconciliation that can't actually run against the current MCP.

---

## RECOMMENDED FIXES (pending Rydel's go — HARD STOP here)

**Read-side (autonomous once approved):**
1. Fix `_build_context_block` ACTIVE CLIENTS: use real keys (`active_count`, `total_mrr_derived`) **and include a compact per-client list** (business name, status, package, MRR, close_date, source) — capped/curated so it's affordable in **both** text and voice/lean mode. This is the core fix that lets EDITH answer about any client, including same-day closes, by voice.
2. Optionally tighten the refresh blind spot (e.g. lower stale threshold, or ensure the EOD/voice path can trigger a forced re-pull) so a deal closed today is reflected sooner.

**Source-side (needs you):**
3. **Lucas Doan / The D's bar** is marked **Won** but Offer Sold + Close Date + Cash Collected + commissions are **blank** in the tracker (data row 39 / sheet row 41). If he's signed/paid, fill those at source; EDITH will pick it up on the next refresh. Until then it's correctly held out of cash/close totals and surfaced via the `won_but_unlogged` flag.

**Decision needed from Rydel:**
- Which "Lucas" did you mean — Lucas **Reid** (Cally Hotel, fully logged) or Lucas **Doan** (The D's, unlogged)?
- Stripe reconciliation: pursue option (i) extend the MCP, (ii) use the manual "Verify from Stripe" column, or (iii) rely on the existing unlogged flag?

---

---

## UPDATE — FIXES APPLIED (post-confirmation)

Rydel's decisions: **fix read-side + tighten refresh**; **"Lucas" = Lucas Reid (Cally Hotel)** (so both reported names are the *same* fully-logged client → the failure was purely read bug + lag, not a source gap); **extend the Stripe MCP** for reconciliation.

### 1. Read bug fixed — `dashboard/chat.py` `_build_context_block`
- Replaced the dead keys (`total_clients`/`total_mrr`/`avg_mrr` → always None) with the real ones (`active_count`, `total_mrr_derived`, `confirmed_mrr`, `estimated_mrr`, `latest_close_date`).
- Added a **compact per-client roster** (name, status, package, mrr, close_date, source) that now ships in **both text and voice/lean mode**. EDITH can name any client — including same-day closes — by voice.
- **Verified (lean/voice path):** "The Cally Hotel" present, `active_count: 38`, "The D's bar and dining" present (escaped), `signed_not_in_health` statuses present, 38-client roster rendered.

### 2. Refresh tightened — `app.py`
- Stale threshold 4h → **90min** (`STALE_THRESHOLD_SECONDS`, env-overridable).
- Scheduled interval default 6h → **2h** (`REFRESH_INTERVAL_HOURS`).
- Manual `POST /cfo/refresh` still forces an unconditional rebuild. A deal closed today now surfaces within ≤2h automatically (or instantly on manual refresh).

### 3. Stripe↔tracker reconciliation — consumer built (`stripe_reconcile.py`), wired into `snapshot.py`
- New `reconcile_stripe_tracker()` runs server-side (where tracker emails are available), matches Stripe charges to tracker rows by **email exact → normalized name/business exact**, and flags **"paid in Stripe, no matching tracker entry."** Output is PII-safe (names/amounts/dates only; an assertion blocks any email from leaking).
- Surfaced in EDITH's chat context as a STRIPE↔TRACKER RECONCILIATION section.
- **Honest gating:** the deployed Stripe MCP has no per-charge tool (confirmed live: `get_stripe_recent_charges` → 400 "Unknown tool"). The consumer therefore degrades to `status: pending_mcp_tool` with a clear degraded flag — **no fabricated matches.** It activates automatically once the MCP ships the tool.
- **MCP work required (separate `served-stripe-mcp` repo — out of this repo's scope):** add tool
  `get_stripe_recent_charges(days)` → `{charges:[{id,amount,currency,created,status,customer_name,customer_email}]}` (succeeded charges, AUD major units).

### Before / After — what EDITH knows

| | Before | After |
|---|---|---|
| Cally Hotel by name (voice) | ❌ no client names in lean context | ✅ in roster, status Active, MRR $3,050 |
| Cally Hotel by name (text) | ⚠️ only buried in raw JSON dump | ✅ explicit curated roster entry |
| Headline client count/MRR | ❌ null (dead keys) | ✅ 38 clients, $78,446 derived MRR |
| Newly-closed (signed_not_in_health) | ❌ invisible by name | ✅ listed + labelled "awaiting confirmation" |
| Same-day close visibility | up to ~6h lag | ≤2h auto / instant on manual refresh |
| Paid-but-unlogged detection | none | flag live (pending MCP per-charge tool) |
| Won-but-unlogged (e.g. Lucas Doan) | flag count only | unchanged — still flagged (correct) |

### Verification
- `python -m pytest -q` → **225 passed, 1 failed.** The single failure (`test_pdf_reads_cash_position_fields`) is `ModuleNotFoundError: No module named 'fpdf'` in `briefing_pdf.py` — a missing local dependency, **pre-existing and unrelated** to these changes (that file was not touched).
- Live `build_snapshot()` end-to-end: `stripe_reconciliation` present, Cally + The D's in `active_clients`, `active_count=38`, `won_but_unlogged` firing, `latest_close_date=2026-06-24`.
- Non-regression intact: Meta spend, CAC/ROAS, data-accuracy, voice, memory, layering, Stage-A all green.

---

## NON-REGRESSION (to honour on any fix)

Meta spend, CAC/ROAS, data-accuracy fixes, voice, memory, layering, Stage-A tests must stay green. No silent source repoint. Tracker must keep reading the full live sheet (no row cutoff). Names must never leak to unauthenticated outputs/history (the chat context is auth-gated, so curated names there are acceptable per CLAUDE.md).
