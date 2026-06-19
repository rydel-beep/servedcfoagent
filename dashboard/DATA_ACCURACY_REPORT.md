# EDITH — DATA ACCURACY REPORT

## STAGE 0 — ACCURACY DIAGNOSIS (read-only; no sources changed)

**Run date:** 2026-06-19 (Sydney) · **Diagnosis only — HARD STOP for Rydel before any source change.**

> **Scope caveat (read first):** the "displayed value" column below is read from the
> repo's `snapshot_state.json`, whose `generated_at` is **2026-06-12T14:35:50+10:00 — 7
> days old**. The LTC tracker and Xero figures were read **live today** via MCP. So several
> mismatches between "displayed" and "live" are *snapshot staleness*, which is itself the
> headline finding (see §A and Stage 4). Confirming the LIVE Railway snapshot's age needs an
> authenticated pull of `/dashboard/api/snapshot` (deferred to Stage 4).

---

### §A — HEADLINE FINDING: the snapshot is stale, so the whole dashboard is 7 days behind

- `snapshot_state.json.generated_at = 2026-06-12`; today = 2026-06-19. Every computed
  metric (funnel, MRR, cash, sales, clients) is a 7-day-old read.
- Mechanism (`app.py`): a daemon thread rebuilds every `REFRESH_INTERVAL_HOURS` (default 6h);
  startup rebuilds if persisted snapshot >4h old. Served by gunicorn `--workers 2`.
- Proof the live sources moved on: the LTC tracker `modifiedTime = 2026-06-19T00:37Z` (edited
  **today**); leads logged today; the **live** Team Scorecard reads **48 / 13 / 9 / 6**
  (leads/sets/shows/closes) vs the dashboard's stale **76 / 21 / 15 / 7**.
- This is the dominant cause of "data doesn't seem accurate." It is a **refresh-integrity
  defect (Stage 4)**, not a per-metric bug. Likely failure modes to verify live: scheduled
  thread died/never started in the serving worker; multi-worker + single persisted file; or
  the persisted file not surviving deploys (no `/data` volume → `SNAPSHOT_FILE` ephemeral).

---

### §1 — SOURCE MAP (every headline metric)

| Metric (displayed) | Source system | Sheet/tab/range or API | Freshness it carries | Value shown (snapshot 06-12) |
|---|---|---|---|---|
| Cash on hand | **Manual override** (NOT Xero) | `config.CASH_ON_HAND_OVERRIDE` env | confirmed 2026-06-04 | **$140,007.29** |
| Cash in transit | Manual | `config.CASH_STRIPE_INCOMING` | 2026-06-04 | $18,000 |
| Tax reserved | Manual | `config.CASH_TAX_RESERVED` | 2026-06-04 | $20,000 |
| Total monthly burn | **Hardcoded fallback** (Xero down) | `monthly_burn` salary tab + hardcoded | n/a (`available:false`) | $39,211 |
| Runway | Derived | cash_override ÷ burn_fallback | — | 3.6 mo |
| Current MRR | Google Sheet (Health tab) | Finance Sheet `Health` | 06-12 | $72,896.18 |
| MRR (Stripe cross-check) | Stripe MCP | `served-stripe-mcp` | 06-12 | $53,971 (miscount) |
| Forward MRR next mo | Sheet (Health next_mrr) | Finance Sheet | 06-12 | $58,236.18 |
| Active clients | Derived (Health + LTC) | `active_clients.active_count` | 06-12 | **34** |
| Funnel (leads→closes) | Google Sheet | LTC `Team Scorecard` computed cells | 06-12 | 76/21/15/7 *(live now 48/13/9/6)* |
| Cash collected 30d | Stripe MCP | revenue.current | 06-12 | $82,398.90 (gross) |
| Stripe payouts 30d | Stripe MCP | payouts | 06-12 | $78,957.80 (net) |
| Wasted-leads / speed-to-lead | Google Sheet | LTC raw rows | 06-12 | STL 5–7% |
| GHL pipeline counts | GHL API | unconfigured | **null** | — |
| Failed charges | Stripe MCP | subscriptions/charges | 06-12 | 12 |
| Closer commission 30d | Google Sheet | LTC cols | 06-12 | $9,300 (1 blank) |
| Setter commission 30d | Google Sheet | LTC cols | 06-12 | $0 (8 blank) |
| True team cost | Google Sheet | Finance `SALARY` tab | 06-12 | $30,504/mo |
| Gross margin | Xero P&L | unconfigured | **null** | — |

**One source per metric holds.** Cash & burn are on *manual/hardcoded* sources because the
agent's own Xero pipe is down — not Xero-live.

---

### §2 — STALE-VS-MISREAD VERDICT for the LTC tracker → **(a) source/process, NOT an EDITH bug** (with a precise twist)

EDITH reports `latest_close_date = 2026-06-05`. I read the live tracker. Verdict:

- **EDITH is reading the sheet correctly.** The most recent row with a populated **Close Date**
  is **Milad Alizadeh / Texas Charcoal Chicken — Close Date 2026-06-05**, Growth Pro, $18,300,
  cash $3,300. The sheet's own computed Closer per-deal list also ends at Milad 06-05. EDITH's
  `latest_close_date` faithfully mirrors the structured data. **This is not misread (b).**
- **The sheet is NOT idle, either.** It was edited today; leads/sets are being logged daily.
- **The real issue is INCOMPLETE ENTRY (a process/source gap):** there are **2 deals flagged
  "Won" in the closer-outcome column *after* 06-05 whose Close Date / Offer Sold / Contract
  Value / Cash Collected are all BLANK** —
  - **The Leopard Deli (Melissa)** — input 06-06, Kalin, Showed, **Won**, money columns empty.
  - **Lucas Doan (The D's bar and dining)** — set 06-18, Kalin, Showed, **Won**, money empty.
  Because Close Date and Cash are blank, every close/cash/commission metric *correctly*
  excludes them — so the data legitimately "stops" at 06-05.

**Conclusion:** Do **not** repoint or "fix" sales numbers in code. The fix is (i) a **process
flag at source** — finish logging Won rows (Close Date + Offer + money) — and (ii) an **EDITH
visibility upgrade**: surface a DQ flag "N deals marked Won but missing Close Date/money"
(currently EDITH shows *nothing* for these — a blind spot, not a wrong number). Plus the
staleness banner already present (it correctly computed "14 days since last close" against
real today, even though the underlying snapshot is 7 days stale — the banner conflates two
different ages; worth clarifying in Stage 3/4).

---

### §3 — CROSS-SOURCE CONTRADICTIONS

| # | Metric | Source A | Source B | Authoritative (per CLAUDE.md) | Dashboard showing the right one? |
|---|---|---|---|---|---|
| 1 | MRR | Health tab $72,896 | Stripe MCP $53,971 | **Health tab** (Stripe = validation only, and miscounting) | ✅ headline uses Health; show Stripe labelled as cross-check |
| 2 | Active clients | `active_count` **34** | Stripe active subs **1** | **`active_clients.active_count`** (Stripe gives aggregate only) | ✅ 34 is the only count to display; Stripe sub# is not a client count |
| 3 | Closes (30d) | scorecard 6 (live) / 7 (stale) | sheets.deals_won 8; Kalin KPI 5; computed 6 | depends on definition; **funnel headline = scorecard cohort** | ⚠ multiple close counts surfaced; need one labelled definition |
| 4 | Cash on hand | manual override $140,007 | Xero/CommBank live (see §5) | **Xero bank truth** (but pipe down → using override) | ⚠ labelled "owner-confirmed override," not Xero-live |
| 5 | Tax reserve | config $20,000 | Xero BAS/Tax acct $48,977 | Xero | ⚠ override figure ≠ live BAS balance |
| 6 | GHL pipeline | dashboard null | (task cites ~1254 opps) | GHL when live | ❌ GHL down — cannot reconcile |

> Task referenced "36 vs 35 active + 1 awaiting Stripe" and "$75,396 vs $54,191." This snapshot
> shows 34 active / 0 awaiting and $72,896 / $53,971 — the differences are **snapshot
> staleness**; the live figures will match the task once refreshed. The *rule* (show
> `active_count`; never sum Stripe & sheet MRR) is correctly enforced in code.

---

### §4 — THE DATA-QUALITY ISSUES (the `degraded[]` array the DQ panel renders — 10 here; "9" was a prior/live count)

Grouped by root cause:

- **Stripe MCP defects (3):** `revenue_previous` (MCP ignores `days` param → no prior period);
  `customer_count` ("unknown" → proxy); `stripe_mrr_subs_mismatch` (MRR $53,971 with **1**
  active sub → miscount).
- **Integrations down (2):** `ghl_pipeline` (`GHL_SALES_API_KEY`/`LOCATION_ID` not set);
  `xero` (`XERO_CLIENT_ID`/`SECRET` not set).
- **Source-entry gaps (3):** `closer_commission` (1 Won deal blank); `setter_commission` (8
  Won deals blank); `zero_mrr_active_clients` (Pottery Green Bakers Gordon = Active but $0 MRR).
- **Reconciliation surface (1):** `funnel_cross_check` (scorecard 76/21/15/7 vs EDITH-recomputed
  111/34/20/6 — different counting method + window; *working as intended*, surfaces disagreement).
- **Staleness/process (1):** `cash_override_stale` (override last confirmed 06-04).

The DQ count on the dashboard = `snap.degraded.length` computed client-side. Note: separate
"deficiency_analysis" panel (3 items: speed-to-lead, 2 single-point-of-failure roles) is a
*business* analysis, not data-quality — don't conflate.

---

### §5 — INTEGRATION HEALTH

| Integration | Configured (in agent)? | Live now? | Detail |
|---|---|---|---|
| **Xero (agent's own pipe)** | ❌ `XERO_CLIENT_ID/SECRET` not set | ❌ | snapshot `xero=null`; OAuth never configured / token absent. Drives `ok:false`, null margin, hardcoded burn. |
| **Xero (claude.ai MCP)** | ✅ (separate path) | ✅ **LIVE** | `check_xero_connection` → Org "Served Marketing", READ-ONLY. Default card "Amex Platinum Business". CommBank accounts present: Transaction #2352, Saver #4041, BAS #2353. **A working Xero connection EXISTS via MCP** — relevant to Stage 1. |
| **GHL** | ❌ keys not set | ❌ | `ghl=null`. Needs `GHL_SALES_API_KEY` + `GHL_SALES_LOCATION_ID`. |
| **Stripe MCP** | ✅ base URL set | ⚠ up but defective | Returns data but: ignores `days` param, `customer_count`="unknown", **miscounts active subs (1)**. MRR value usable; counts not. |
| **Google Sheets** | ✅ | ✅ | LTC + Finance sheets read fine; LTC edited today. |

**`forward_mrr.current_month_mrr` = None — RESOLVED as a phantom key, not an empty source.**
The function's *docstring* (forward_mrr.py:124) promises `current_month_mrr`, but the code
returns the value under **`current_recognized_mrr` = $72,896.18** (forward_mrr.py:278). No
consumer reads `current_month_mrr` by that name. Fix = alias the key (or correct the
docstring); the MRR value is present and correct. Not a parse bug, not empty.

---

### CommBank live read (caveat — DO NOT treat as cash-on-hand yet)

`get_commbank_balance(all)` for 2026-03-21→2026-06-19 returned: Transaction #2352 **−$63,124.59**,
Saver #4041 −$42.02, BAS/Tax #2353 +$48,977.04, **Combined −$14,189.57**. A *negative combined*
is implausible as a closing balance against a $140k cash position → this almost certainly
returns **net movement over the date range, not a point-in-time balance**. **Before any Stage 2
cash repoint, the correct balance semantics and which accounts = "cash on hand" (CommBank
txn+saver, excluding BAS reserve and the Amex liability) must be pinned down.** Accuracy first.

---

## DECISIONS NEEDED FROM RYDEL (gates before Stage 1+)

1. **Refresh integrity (Stage 4) is the real accuracy bug.** Approve prioritising it — confirm
   the LIVE snapshot age, fix the rebuild path, add per-source freshness. (Recommended first.)
2. **LTC sales numbers:** confirmed **stale-source/process (a)**, not a code defect. Approve:
   (i) you/team finish logging the 2 Won rows (Leopard Deli, Lucas Doan); (ii) EDITH adds a
   "Won but unlogged" DQ flag + keeps the staleness banner. No sales-number code repoint.
3. **Xero:** the agent's own pipe is down, but a **live Xero MCP connection exists**. Decide
   Stage 1 path: (a) restore the agent's own OAuth on Railway (needs your browser consent —
   exact steps to follow), or (b) route the agent's cash/margin through the existing MCP. Until
   then, cash stays on the labelled manual override (not faked).
4. **Stripe MCP miscount, GHL down, forward_mrr key** — approve the Stage 3 fixes as scoped above.

**No sources have been changed. Awaiting your go before Stage 1.**
