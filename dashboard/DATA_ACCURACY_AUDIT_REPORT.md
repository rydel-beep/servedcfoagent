# DATA ACCURACY AUDIT — Phase 0 (Diagnosis only, no changes made)

**Date:** 2026-06-24 (Sydney) · **Scope:** served-cfo-agent only · **Status:** HARD STOP — awaiting Rydel.

All findings below were verified **live** from this environment by running the agent's own pull
functions and probing the live Stripe MCP. No source was changed. No secrets printed.

---

## TL;DR — one root cause behind #1 and #2

The **Finance Google Sheet** (`1n7OcGrO…CTg`, which holds the **Health tab** — the authoritative
client roster) now returns **HTTP 401**. Its public/link sharing was revoked sometime after
2026-06-19 (it worked then: 33 active + 2 web-sub). Every consequence flows from this:

- **Active clients shows 16/17 ("0 active, N awaiting Stripe")** — NOT a Stripe miscount. When the
  Health tab 401s, `active_clients.py` is handed an **empty roster** and falls back to deriving the
  client list purely from the **Lead-to-Cash tracker's "Won" deals** (a *different* sheet, still
  public, still 200). Those won-deals are all tagged `awaiting_stripe`, so the headline becomes
  "N clients (0 active, N awaiting Stripe)" where **N = the number of Won deals in the LTC tracker**.
- **Refresh pill always red** — partly this 401 (now a genuine core failure), but the pill was
  **structurally red even when healthy**: the pill fails on `degraded[] > 0`, and `degraded[]` is
  *never empty* (Xero + GHL are unconfigured, and the Stripe MCP has known permanent limitations).

The agent's source-of-truth design is **already correct** (it points at the Health tab). The bugs
are: (a) the authoritative source is *down* (needs Rydel to re-share — gated), and (b) the
*fallback* and the *pill logic* are wrong and present confidently-wrong/always-red states instead
of labelled-degraded ones (code fixes, in-scope).

---

## 1. ACTIVE CLIENTS — exact trace + root cause

**What computes it:** `metrics_engine.build_canonical_metrics` →
`active_client_count = active_clients.active_count`. The dashboard headline (`#val-clients`) renders
`ac.active_count`; the sub-line (`dashboard.js:2030`) renders
`(confirmed_both_sources + legacy_pre_tracker)` **active** + `pending_health_update` **awaiting Stripe**.

`active_clients.derive_active_clients()` builds the roster from:
- **(a) Health tab** (Finance sheet) — *primary roster*, `source="health_tab"`.
- **(b) LTC tracker Won deals** — cross-reference; Won-but-not-in-Health become
  `source="ltc_tracker"`, `sources_agree=False`, `awaiting_stripe=True` → counted as
  `pending_health_update`.

**Live values measured today:**

| Source | Result |
|---|---|
| Finance sheet / Health tab CSV (`…/export?format=csv&gid=1407663952`) | **HTTP 401** (both gid-export and gviz-by-name) → `pull_client_health()` returns `None` → **0 health clients** |
| LTC tracker (`1BrL-xh…reDY`, gviz CSV) | **HTTP 200**, 384 KB → **17 Won deals** today |
| Stripe MCP `get_stripe_subscriptions` | active **1** (this is the unrelated MCP miscount, see §4) |

**Reproduced end-to-end (live):** `derive_active_clients(health=[], won_deals=17)` →
`active_count=17, confirmed=0, legacy=0, pending_health_update=17` →
dashboard renders **"17 clients (0 active, 17 awaiting Stripe)"**. Rydel saw 16 — identical bug,
one fewer Won deal at that moment. **The headline number tracks the LTC Won-deal count whenever the
Health tab is down.**

**Authoritative roster (per CLAUDE.md source-of-truth rules):** the **Health tab in the Finance
sheet** — Active/Web-Sub status, churned excluded, LTC cross-ref. On 2026-06-19 it yielded
**33 active + 2 web-sub = 35** (derived `active_count` 36 incl. 1 new LTC signing). That is the real
roster. The dashboard's 16/17 is wrong because the authoritative source is 401, not because the code
points at the wrong source.

**Gap:** displayed **16/17** vs authoritative **~35–36**. Cause = Health-tab access revoked
(HTTP 401), triggering the LTC-only fallback.

---

## 2. REFRESH PILL ALWAYS RED — two layers

**Pill logic** (`dashboard.js:558`): `failing = (snap.ok === false) || degraded > 0;` →
red dot when `failing`. **`ok` is computed as `len(degraded) == 0`** (snapshot.py:548).

**Layer A — structural (red even when healthy):** `degraded[]` is *never* empty. On the last
*healthy* snapshot (2026-06-19, Health tab working), there were **12 degraded entries**, almost all
permanent/benign:
- `xero` — "XERO_CLIENT_ID or XERO_CLIENT_SECRET not set" (integration never configured)
- `ghl_pipeline` — "GHL_SALES_API_KEY … not set"
- `customer_count` / `revenue_previous` / `stripe_mrr_subs_mismatch` — known Stripe-MCP limitations
- benign data-quality flags (blank commissions, cash-override stale, funnel cross-check, etc.)

None of these mean "the refresh failed," yet each one alone forces the pill red. **The pill can
essentially never be green** under the current `ok = no-degraded-at-all` rule.

**Layer B — genuine failure (now):** the Health-tab 401 adds a *real core-source* failure
(`client_health`, `payroll_baseline`, `recognized_revenue` all degrade — same sheet). So today the
pill is *legitimately* unhealthy — but the system can't tell Rydel that, because it already looked
red every other day too.

**Live snapshot rebuild status:** the persisted snapshot rebuilds **fully** (it doesn't error
partway — pulls that fail return `None` + a `degraded` entry rather than throwing). So numbers aren't
"half-built"; they're built with the Health-tab-derived metrics **missing/fallback-substituted**.
`generated_at` advances on each refresh. The danger is the *silent fallback*, not a partial build.

---

## 3. CASH / STRIPE RECONCILE

**Cash in bank $140,007.29** — this is the **manual `CASH_ON_HAND_OVERRIDE`** constant, confirmed
**2026-06-04** → **20 days stale** today (flagged `cash_override_stale` in degraded[]). The agent's
own Xero integration is **unconfigured** (`XERO_CLIENT_ID/SECRET` not set) → `xero = null`. So cash is
the stale manual figure; Xero was never restored (Stage-2 from prior sessions still pending).

**Stripe "pending payout $18,000"** — this is the **manual `CASH_STRIPE_INCOMING` constant**, NOT a
live read. Verified: the Stripe MCP exposes only 6 tools —
`get_stripe_mrr, get_stripe_revenue, get_stripe_subscriptions, get_stripe_failed_charges,
get_stripe_customer_count, get_stripe_payouts`. **There is no balance / pending / in-transit tool.**
`get_stripe_payouts` returns *already-banked* net payouts ($73,539 trailing-30d), not pending. So the
live ~$19k Rydel quotes **cannot be read from the current MCP** — the $18k is just the 2026-06-04
manual figure, now ~$1k low. Reconciling to $19k needs either Rydel's updated number or a new MCP
balance tool (external repo — gated).

---

## 4. CONTRADICTIONS & authoritative-source-per-metric

| Metric | Dashboard | Reality / live | Authoritative source | Note |
|---|---|---|---|---|
| Active clients | 16/17 | ~35–36 | **Health tab** (Finance sheet) | Source 401 → LTC-only fallback (the bug) |
| "Current MRR" | Health-tab MRR ($75,396 on 06-19) | unavailable now (Health 401) | **Health tab `current_mrr`** | Down with the sheet |
| Stripe MRR | $57,241 (live) | $57,241 | Stripe (cross-check only) | Billing-MRR basis; **never** equals Health MRR |
| Active subs | 1 | likely many | Stripe MCP (defective) | MCP miscount — $57,241 MRR on "1 sub" is impossible; **MCP service bug, external repo** |
| Stripe pending | $18,000 | ~$19,000 (Rydel) | manual constant | No live balance tool exists |
| Cash in bank | $140,007 | unknown | manual override (Xero unrestored) | 20 days stale |

**Stripe sub miscount** pollutes: (i) the `customer_count` proxy (uses active-subs=1), and (ii) the
MRR-per-sub cross-check. It does **not** feed the active-client headline (that's the Health/LTC path).
Fixing it properly means fixing the **served-stripe-mcp** service (separate repo) — out of
served-cfo-agent scope; the agent already flags it correctly as degraded.

---

## Root-cause summary

1. **Finance sheet (Health tab) → HTTP 401** = the single trigger for the wrong client count AND a
   real refresh failure. Access was revoked after 2026-06-19. **Needs Rydel to re-share** (gated) —
   or the agent moves to authenticated Sheets (service-account) access.
2. **Silent LTC-only fallback** in `active_clients.py` presents a confident wrong headline (16/17)
   when the roster source is down. **Code fix (in-scope):** refuse/label instead of confidently
   render.
3. **Pill logic conflates "any degraded entry" with "refresh failed."** **Code fix (in-scope):**
   GREEN when core sources healthy; AMBER for optional/known-degraded (Xero/GHL/Stripe-MCP limits +
   data-quality flags); RED only on genuine core-source failure.
4. **Cash + Stripe-pending are stale manual constants** (Xero unrestored; no Stripe balance tool).
   **Gated** — needs Rydel's numbers or OAuth consent / external MCP work.

---

## HARD STOP — what I need from Rydel before Phase 1+

See the questions posted alongside this report. Nothing will be changed until you confirm.

---

# PHASES 1–3 — Outcomes (post-gate)

Rydel's gate decisions: (1) he re-shares the Finance sheet; (2) approved both code fixes;
(3) restore Xero live cash.

## Phase 1 — Active clients (FIXED + verified live)

- **Root cause cleared by Rydel:** the Finance sheet now returns **HTTP 200** (re-shared). Health
  tab loads **33 active + 2 web-sub = 35**, current MRR $75,396.
- **Code hardening (shipped to working tree, deploy gated):** `derive_active_clients()` now takes
  `health_source_ok`; when the Health tab is unavailable it sets `roster_source_down` (+ confidence
  `low`) instead of presenting the LTC-Won-only count. `snapshot.py` substitutes the **last-good
  roster, labelled stale** (`roster_stale`, `roster_stale_since`, `active_count_live_unavailable`)
  and adds a loud `client_roster_source` core-degraded entry. `metrics_engine` tags
  `active_client_count` with `stale`. `dashboard.js` renders "⚠ roster source down — last confirmed
  …" instead of "0 active, N awaiting Stripe".
- **Before/after (live build):**
  - Before (Health 401): **16/17 clients — "0 active, 16 awaiting Stripe"** (LTC-Won count).
  - After (Health 200): **37 clients — "35 active, 2 awaiting Stripe"** from the authoritative
    Health-tab roster. Source named: `active_clients.active_count` ← Health tab + LTC cross-ref.
  - If the sheet ever 401s again: headline holds the **last-good 37, labelled "stale — roster
    source down"** (never a confident wrong number).

## Phase 2 — Refresh pill (FIXED + verified)

- **`metrics_engine.classify_refresh_health(degraded)`** splits degraded[] into **core failures**
  (genuine refresh failure → RED) vs **optional/known degradations** (Xero/GHL unconfigured,
  Stripe-MCP limits, bookkeeping data-quality flags → not red). Snapshot now carries
  `refresh_health = {status, core_failures, optional_degraded}`. `dashboard.js` pill reads it:
  RED only on a core failure, GREEN when core sources are healthy (optional shown muted as
  "· N minor"); >24h still stale-reds on age. Falls back to the old rule for pre-classifier
  snapshots.
- **Before/after:**
  - Before: pill RED on `len(degraded) > 0` — and degraded is **never** empty → **always red**.
  - After (live healthy snapshot, 12 optional degradations, 0 core): **pill GREEN**.
  - Health-tab 401 → core failures `[client_health, payroll_baseline, recognized_revenue,
    client_roster_source]` → **RED** (a genuine failure, now distinguishable). Stripe-MCP down →
    RED. Clean → GREEN.
- Manual refresh (`POST /api/refresh`) forces a real `build_snapshot()`; `generated_at` advances;
  pill reflects the true `refresh_health`.

## Phase 3 — Cash / Stripe (HARD STOP — cannot ship live cash)

**Stripe pending ($18,000):** confirmed it is the **manual `CASH_STRIPE_INCOMING` constant**, not a
live read. The Stripe MCP exposes 6 tools, **none for balance/pending/in-transit**
(`get_stripe_payouts` = already-banked net, $73,539 trailing-30d). The live ~$19k cannot be read
without a new MCP balance tool. → **stays the labelled manual figure** until either Rydel provides
the current number or a `get_stripe_balance` tool is added to the (external) stripe-mcp service.

**Cash in bank ($140,007, manual, 20d stale):** I attempted to prove closing-balance semantics via
the **read-only Xero MCP** before any repoint. The available balance tool returns **net
movement / signed transaction sums, NOT closing balances** — proven unreliable:
- `get_commbank_balance(transaction, 2026-06-01..06-24)` → **–$22,356.93** (a movement, impossible
  as a balance).
- `get_commbank_balance(all, 2020-01-01..2026-06-24)` → Transaction **$18,782**, **Saver –$75,731**
  (negative — impossible), BAS $58,826, COMBINED **$1,878** (vs manual $140,007).
- `get_commbank_report` / `get_bank_report` are transaction *classifiers*, not balance reports.

**Semantics are DISPROVEN, not proven.** Per the guardrail ("do NOT ship a wrong live cash number;
closing-balance semantics must be proven"), cash **stays on the labelled-stale manual $140,007**
with the loud `cash_override_stale` flag.

### To actually restore live cash — exact steps (needs Rydel; HARD STOP)

Two independent blockers, both required:
1. **Agent-side Xero OAuth is unconfigured.** The deployed agent reads cash from its OWN Xero
   integration (`XERO_CLIENT_ID` / `XERO_CLIENT_SECRET` / token file), not from this session's MCP.
   To restore: set `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI` on Railway
   (web-production-16b16), then complete the OAuth consent at `/xero/connect` (Rydel signs in to
   Xero and authorises — outward, can't be done for him). Token persists to the `/data` volume.
2. **A PROVEN closing-balance source.** The current Xero balance tooling returns movement, not
   balances. The restore must read the **point-in-time closing balance** of CommBank Transaction
   **#2352** + Online Saver **#4041** (exclude BAS #2353 + Amex) — via Xero's Bank Summary /
   Balance Sheet report (or the Accounts API balance field), and reconcile it against a
   Rydel-confirmed figure on day one before it goes live.

Until BOTH are done, cash remains the owner-confirmed manual override, loudly labelled stale.
**No live cash number was shipped.**

## Remaining gated items
- **Deploy** the code hardening (active_clients/snapshot/metrics_engine/dashboard.js) to
  web-production-16b16 — gated on Rydel's go. The live PILL stays red until this deploys (the
  re-share already fixed the count). Commit must EXCLUDE the parallel UI-layering WIP (css, hud.css,
  chat.js, dashboard.html, capture_layering.py, UI_LAYERING_REPORT.md).
- **Stripe sub miscount** ("1 active sub" vs $57,241 MRR) — defect in the external `served-stripe-mcp`
  service; already flagged degraded; fix is out of `served-cfo-agent` scope.
- **Stripe pending** live read — needs a new MCP balance tool or Rydel's number.
- **Xero live cash** — the two-blocker restore above.
