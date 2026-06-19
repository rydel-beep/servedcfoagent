# EDITH — DATA ACCURACY FIX REPORT

Follows `dashboard/DATA_ACCURACY_REPORT.md` (Stage 0). Run 2026-06-19 (Sydney).
**Accuracy-first finding: the premise of several stages changed once production was checked
live. Reported honestly below rather than building on a false premise.**

---

## 0. LIVE-TRUTH CHECK — the headline premise was wrong

Stage 0 read the repo's `snapshot_state.json` (stamped 2026-06-12). An **authenticated live
pull** of production (`/cfo/snapshot` via `railway run`, key never printed) shows:

| | Repo file (06-12) | **LIVE prod (today)** |
|---|---|---|
| generated_at | 2026-06-12 14:35 | **2026-06-19 10:48 (fresh)** |
| funnel | 76/21/15/7 | **48/13/9/6** (matches live sheet) |
| current MRR | $72,896 | **$75,396** |
| active clients | 34 | **36** |
| DQ issues | 10 | **9** |
| Xero | null (down) | **LIVE — P&L: margin 73%, COGS $21,209, net $17,667** |
| GHL | null (down) | **LIVE — conv 39.2%, 89 new opps, full stage breakdown** |

**Conclusions that overturn the plan:**
- **Production refreshes correctly.** The scheduled rebuild runs; the snapshot is today's. The
  "7-day-stale" data Stage 0 saw was **only the repo's committed `snapshot_state.json`**, not
  prod. The repo file is a build artifact and is not what users see.
- **Xero is ALREADY connected in prod** (live P&L; burn now `available:true` off real Xero
  lines, real ad spend $7,342). **Stage 1 (OAuth restore) is MOOT.**
- **GHL is ALREADY reconnected in prod** (live pipeline). The GHL fix is **MOOT.**
- The numbers the brief cited ($75,396 vs Stripe $54,191; 36 vs 35+1 awaiting; 9 DQ; funnel
  48→6) are the **live** values and are reproduced exactly — confirming the live read.

## Refresh path — diagnosed, works

`#btn-refresh` → POST `/dashboard/api/refresh` (→ `build_snapshot()` which **re-pulls every
source, persists to disk, updates the in-memory cache**) → GET `/dashboard/api/snapshot`
(`load_persisted()` from disk) → `render()`. Persist + read are the same file, so the manual
refresh **does** force a real re-pull and reload. No defect found in the refresh path itself.

**What I could NOT prove** (so I did not claim it): that a browser/proxy was serving a *cached*
API response. The snapshot endpoints carried **no `Cache-Control`** header — so as cheap
insurance I added `no-store` (see §1.3). This is hardening, not a proven-defect fix.

---

## 1. FIXES APPLIED (all verified; full suite 171/171 green — was 169/2-fail at baseline)

### 1.1 `forward_mrr.current_month_mrr` phantom None — FIXED
`forward_mrr.py`: the value was only emitted as `current_recognized_mrr`; the documented
`current_month_mrr` key was absent → None for any consumer using the documented name. Added an
alias so both keys carry the same single value ($75,396 live). No new source, no recompute.

### 1.2 "Won-but-unlogged" DQ flag — ADDED (the real sales-accuracy gap)
`sheets_pull.py`: rows flagged **Won** whose **Close Date** or **Cash Collected** is still
blank are now surfaced as `degraded.won_but_unlogged` + counts in `sheets.data_quality`.
- **Verified live: fires on exactly 2 deals** (The Leopard Deli 06-06, Lucas Doan / The D's
  06-18) — the two Stage 0 identified. Message: *"2 deal(s) marked Won but not fully logged
  (2 missing Close Date; 2 missing Cash Collected) — closes/cash/commission EXCLUDE these until
  the Close Date + money columns are filled."*
- **No sales-math repoint.** `latest_close_date` correctly stays 2026-06-05; closes/cash
  legitimately exclude unlogged rows. The fix makes the blind spot **visible**, exactly as the
  Stage 0 verdict (source/process issue) prescribed. **Counts only — no names** (LTC name/notes
  fields contain emails; see §1.4).

### 1.3 `Cache-Control: no-store` on snapshot/refresh endpoints — ADDED (hardening)
`routes.py` (`/dashboard/api/snapshot`, `/dashboard/api/refresh`) and `app.py`
(`/cfo/snapshot`). Guarantees no client/proxy can serve a stale snapshot after a refresh.

### 1.4 PII leak — FIXED (turned 2 pre-existing red tests green)
Baseline had **2 failing tests** (`test_sales_analytics`, `test_flask_app`) — PII-leak guards
tripped because some LTC **Business Name** cells contain **emails** (lead-form junk, e.g.
`sylvia12342009@hotmail.com`) that flowed into `sales.commission_detail…deals[].business` and
the snapshot. Added `_safe_label()` in `sales_analytics_pull.py` to redact email-shaped labels
at the 3 business-extraction sites (closer detail, setter detail, won-businesses reconciliation).
Real business names never look like emails, so only junk is struck. Leak walker now clean; both
tests pass. (Not caused by this work, but in scope per the security rules + "tests stay green.")

---

## 2. NOT DONE — gated, moot, or out of scope (with reasons)

- **Stage 1 — Xero OAuth restore: MOOT.** Already live in prod (P&L flowing). No action.
- **GHL reconnect: MOOT.** Already live in prod. No action.
- **Stage 2 — live cash on hand from Xero: REAL remaining work, GATED.** Xero is connected but
  the agent's `xero_pull` fetches **P&L only — no bank balances** (`xero` has no bank/cash
  keys). Cash is still the manual override ($140,007, confirmed 06-04, now 15d stale). To do
  live cash:
  1. Add a **bank-balance pull** to `xero_pull.py` (Xero Accounts/Bank Summary) via the existing
     connection.
  2. **Pin balance semantics first** (HARD gate): the Stage 0 live CommBank read returned a
     *negative combined* (−$14,190 over a range) = almost certainly **period movement, not a
     closing balance**. Confirm which accounts = "cash on hand" (CommBank Transaction #2352 +
     Saver #4041; **exclude** BAS/Tax #2353 = tax reserve, and the Amex = liability) and that
     the figure read is the **closing balance**.
  3. Keep Stripe in-transit a separate labelled line; recompute burn/runway off the verified
     base; loud fallback if Xero read fails.
  *Not started — correctly gated on Rydel + semantics. Replacing $140k with a live-but-wrong
  negative would be worse than the labelled override.*
- **Stripe MCP subscription miscount: OUT OF SCOPE (separate repo `served-stripe-mcp`).** The
  discipline is "served-cfo-agent/ only." In-repo, the agent already treats the Stripe sub
  count as **non-authoritative** (active clients = Health+LTC = 36 canonical; Stripe MRR shown
  only as a labelled cross-check) and the `stripe_mrr_subs_mismatch` flag surfaces it. No
  in-repo change needed; the MCP service itself must be fixed in its own repo.
- **Client count "36 vs 35+1": already internally consistent, no defect.** `active_count = 36 =
  15 confirmed_both + 20 legacy + 1 pending_health` (The D's bar, `awaiting_stripe`). 36 is the
  single canonical count; "35 active + 1 awaiting" is its decomposition, not a contradiction.
- **Closes "one definition": not collapsed — by design.** The figures (funnel cohort closes = 6;
  Kalin closer-attributed monthly KPI = 5; deal-won variants) measure **different things** and
  are labelled by section. Forcing them to one number would be *less* accurate. The headline
  funnel uses one definition (scorecard cohort). Recommend a one-line glossary note rather than
  a collapse.
- **Per-source real timestamps + row counts: NOT DONE (recommended follow-up).** Current
  `source_freshness` gives a per-source timestamp (None when a source returns nothing) but all
  share the single build time and there are no row counts. A true per-pull timestamp + row count
  is a worthwhile Stage 4 enhancement; deferred to keep this change set minimal and low-risk.
- **Snapshot persistence to `/data`: RECOMMENDED (env step for Rydel).** `SNAPSHOT_FILE` is a
  relative (ephemeral) path. A `/data` volume already exists (Xero tokens + history use it — and
  that volume is *why* Xero stayed connected across deploys). Set `SNAPSHOT_FILE=/data/snapshot_state.json`
  on Railway so the snapshot survives restarts. Outward infra change → Rydel's call.

---

## 3. NEW FINDINGS to surface

- **History contains client names — contradicts CLAUDE.md.** `history_store.append()` writes the
  **full** snapshot (incl. `active_clients[].name` + name-bearing `degraded` reasons) to
  `state/snapshot_history.jsonl`, but CLAUDE.md states "history stays aggregate-only (no real
  names)." Pre-existing; flagged per "the contradiction itself is the finding." Recommend a
  scoped follow-up: strip names/PII before appending to history.
- **LTC Business Name hygiene:** multiple rows carry emails/junk in the Business Name field — a
  source-entry quality issue (now redacted on the way out, but worth cleaning at source).

---

## 4. DEPLOY STATUS

All changes verified **locally** (171/171 tests + live-data checks against the real sheets &
prod snapshot). **Deploy to Railway is an outward, gated action** (per DECISIONS.md) — not done
autonomously. Recommended: review the 5-file diff, deploy, then confirm live that
`won_but_unlogged` shows in the DQ panel and `current_month_mrr` is populated.

**Files changed:** `forward_mrr.py`, `sheets_pull.py`, `sales_analytics_pull.py`,
`dashboard/routes.py`, `app.py` (+70 / −6).
