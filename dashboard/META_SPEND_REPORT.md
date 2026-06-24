# META AD SPEND — Live spend feeding CAC / LTGP:CAC / ROAS

**Date:** 2026-06-24 (Sydney) · **Scope:** served-cfo-agent only · **Read-only** (ads_read /
Insights GET only). Status: **built + tested (211 pass); awaiting Rydel to set the token, then
live verify.**

## Phase 0 — token reuse + current source (findings)

- **Token to reuse:** the Ad Monitor (`served-marketing/ad-monitor`) uses `META_ACCESS_TOKEN`
  (System User) + `META_AD_ACCOUNT_ID` via the `facebook_business` SDK against the Insights edge
  (`spend, impressions, clicks, actions, purchase_roas`). Ad account: **`act_1071149830652711`**
  (real). The token in its local `.env` is a **placeholder**; the real token lives in the Ad
  Monitor's Railway env. **CFOagent has no `META_*` vars** (confirmed via `railway variables`).
- **GATE (Rydel chose "Set META_* on CFOagent"):** copy `META_ACCESS_TOKEN` +
  `META_AD_ACCOUNT_ID=1071149830652711` (or `act_…`) from the Ad Monitor's Railway Variables into
  the **CFOagent** service (athletic-gratitude/production). Read-only `ads_read` is sufficient — do
  NOT grant `ads_management`/write. Once set, the engine goes live on the next refresh.
- **Scope (Rydel chose "Agency-wide total"):** one ad account → one agency-level spend feeding
  CAC/ROAS. Per-client/campaign split left as a clean future hook (level=campaign).
- **Current spend source being replaced:** CAC/LTGP:CAC/payback read `xero.xero_ad_spend`. Xero has
  **no live OAuth token** (creds set on Railway, `/xero/connect` never completed → `xero=null`), so
  ad spend fell back to a **hardcoded `AD_SPEND_FALLBACK = $8,002`** (`opex_pull.py`). Every ratio
  inherited that stale estimate. Live Meta spend replaces it.

## Phase 1 — spend fetch (`meta_spend.py`, read-only)

- **Insights edge:** `GET /act_<id>/insights?fields=spend,impressions,clicks&level=account&
  time_increment=1&time_range={since,until}` via raw Graph API (`requests`; no SDK dep added to the
  CFO service). One call returns a **daily series** covering the widest window.
- **Windows:** 7d / 30d / 60d / 90d (match the dashboard's Window selector) + current calendar
  month, all summed from the daily store. Windows are trailing-N ending **today_sydney()**.
- **RETROACTIVE REFRESH (accuracy core):** every refresh re-fetches the trailing daily series and
  **OVERWRITES** the stored days — spend is **never frozen**, so Meta's ~72h attribution updates are
  always captured. The trailing `META_BACKFILL_DAYS` (default 7) are flagged **`provisional`** with a
  note ("firms up over ~72h"). Test `test_fetch_overwrites_retroactively` proves a re-fetched day
  goes 100 → 175 (overwrite, not 275 append).
- **Storage:** per-day `{date: {spend, impressions, clicks, last_fetched}}` persisted to
  `state/meta_spend_daily.json` (gitignored) — survives restarts, enables backfill + freshness.
- **Currency:** account `currency` is read; if not AUD, a labelled degraded entry is added (no
  silent FX). Account `timezone_name` is surfaced (Meta buckets days in the account's tz; for an AU
  account this is Sydney — flagged for the live spot-check).
- **Rate limits / transient:** retry with backoff on Meta codes {1,2,4,17,613,80004} and HTTP
  500/502/503/529; auth/permission/validation errors surface immediately (no pointless retries).
- **Failure → last-known:** if the live fetch fails, the last-good store is shown with
  `fetch_ok=false` + a loud degraded entry ("Meta Insights fetch failed … showing last-known"),
  never a silent stale number (test `test_fetch_failure_keeps_last_good`).

## Phase 2 — wired into unit economics (window-consistent)

- **Resolved ad spend** (`snapshot.ad_spend_resolved`, also `hormozi._resolved_ad_spend`):
  **Meta live (primary, 30d) → Xero Advertising (fallback) → None**, one value every consumer
  reads. CAC/LTGP:CAC/payback/LTV:CAC now read this instead of `xero.xero_ad_spend` directly;
  `inputs_used` records `ad_spend_source` + `ad_spend_window_days` so the basis is auditable.
- **CAC (loaded):** `(ad_spend + setter payouts + closer commission) / closes`, ad_spend now live
  Meta (30d) over the same window as `closes` (the 30d scorecard). Window-consistent.
- **LTGP:CAC:** LTGP from its existing source ÷ the new live-spend CAC. **The 3.94× WILL move** once
  live spend replaces the $8,002 fallback — `inputs_used.cac_loaded`/`ad_spend` show the new basis so
  a corrected ratio isn't mistaken for a bug. Exact before/after is printed at live-verify (needs the
  token).
- **ROAS (new, `m8_roas`):** `(closes × avg_contract) / ad_spend` over the same window = new
  contracted revenue per $1 of ad spend. **Labelled Meta-based**; `read` explicitly says "Google not
  yet included." `window_consistent` flag asserts spend window == funnel window.
- **Per-platform honesty:** everything is Meta-only; no faked blended numbers. Google Ads is a clean
  future hook (add a `google_spend` source + sum into `ad_spend_resolved`).

## Phase 3 — display + freshness + reconcile

- **Economics section** gains two rows: **Ad Spend** (resolved value + a source/freshness tag —
  "(Meta live, 3m ago)" / "(Xero line — Meta unavailable)" / "(unavailable)") and **ROAS (Meta)**.
  Lead-Source ROI cost/close now uses the resolved spend too. The Xero P&L card keeps showing the
  Xero advertising line (it's a P&L view).
- **Per-source freshness:** `source_freshness.meta_spend` added. Meta degraded entries
  (`meta_spend`, `meta_spend_currency`) are tagged **`severity: optional`** and added to
  `OPTIONAL_DEGRADED_METRICS`, so a Meta problem shows in the Data Quality panel and as a degraded
  source **without turning the pill red** (distinct from a core refresh failure) — verified: a
  no-token build is still `refresh_health: green` with `meta_spend` in `optional_degraded`.
- **Reconcile (at live-verify):** live Meta 30d spend vs the old $8,002 fallback will be printed
  with the delta, plus a spot-check of one window against Ads Manager (within attribution
  tolerance).

## Verification status

- Built + unit/integration tested: **211 tests pass** (7 new in `test_meta_spend.py`), incl. the
  retroactive-overwrite and fetch-failure-fallback cases. Full `build_snapshot()` runs clean with no
  token (meta_spend=None, ad_spend_resolved=None, ROAS unknown, pill green, consistency gate passes).
- **No token in code/commits** (grep clean; only env reads). Read-only confirmed (Insights GET only;
  no write scopes).
- **PENDING (needs Rydel):** set `META_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID` on CFOagent. Then I:
  verify `ads_read` works live, spot-check one window vs Ads Manager, confirm currency=AUD, print
  CAC/LTGP:CAC/ROAS **before/after**, and confirm a recent day firms up across refreshes.

## Config knobs (config.py)
`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`, `META_API_VERSION` (v21.0), `META_BACKFILL_DAYS` (7),
`META_SPEND_WINDOWS` ([7,30,60,90]), `META_PRIMARY_WINDOW` (30), `META_SPEND_STORE`
(state/meta_spend_daily.json).

## Future hook — Google Ads
`ad_spend_resolved` is the single resolution point. Adding Google = a `google_spend` engine + summing
into the resolved value and re-labelling ratios "blended." No ratio code changes. Not faked today.
