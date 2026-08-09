# SERVED AD TRACKING — the dedicated dashboard

> **SUPERSEDED NOTE (2026-08-09, audit F14):** this report is HISTORY, not current
> truth (ADS_SYSTEM_STATE.md is canonical). In particular: rosters are now served by
> `roster_engine.py` (one cellspec→roster path, I17 roster==cell), NOT the route-side
> mechanism described below, and live GHL notes are capped at the FIRST 8 contacts per
> roster (not ≤30).


## PHASE 0 — DIAGNOSE + PROBE (2026-08-05)

### 1 · The 30/60/90 toggle — root cause (code-walk, `ltcboard.js`)
Three defects, compounding:
1. **Dropped re-query**: `fetchAll()` returns early while `state.loading` is true, but
   `setWindow()` updates `state.days` + the active button FIRST. A slow in-flight window
   (cold 90d) + a quick toggle = the new fetch silently dropped: the button says 90d,
   the data stays 60d. No queue, no retry.
2. **Untagged responses**: fetches don't carry the window they were issued for — a late
   response renders under whatever the CURRENT label is.
3. **No per-block stamps**: nothing rendered records its window, so a stale mix is
   invisible.
FIX (Phase 2): ONE atomic `/ads/api/board?days=` call per window (scoreboard + flags +
rows in one payload, window echoed back), latest-wins request token, render-guard that
discards any response whose echoed window ≠ current state (console.error + test), URL-
persisted `?window=`, loading skeletons. Regression test on the echo/guard.

### 2 · Note sources for the drill (probed live)
| Source | Reachability | Fill | Shape |
|---|---|---|---|
| Tracker `Setter Notes` (col 20) | mirror, 90s fresh | **91%** (1,175/1,291) | short free text ("wanting weekly rate", "NA, VM AND SMS LEFT") |
| Tracker `DQ Reason` (col 17) | mirror | 7% | picklist-ish ("Wrong ICP", "Wrong number") |
| Tracker `Lead Quality` (col 19) | mirror | 10% | graded ("5-Unfit") |
| Tracker `Loss Reason` (col 24) | mirror | **0%** — dead column, shown only if ever filled |
| **GHL contact notes** | **LIVE endpoint works with the sales key** (25/25 HTTP 200 on real contacts) | ~20% of contacts carry notes | HTML body (stripped for display), dateAdded, userId — labelled "GHL · <date>" |
| GHL opportunity | mirror (`ghl_opportunities.stage_name`) | open-pipeline coverage | pipeline stage per person |
Drill policy: tracker notes from the mirror (stamped with sheet sync), GHL notes fetched
LIVE per roster (≤30 contacts, throttled, stamped at fetch), each labelled with its
source; empty = "no notes recorded", never filler.

### 3 · Migration map
OUT of the finance dashboard: `#section-attribution` markup, the zone-2 membership line,
`ltcboard.js` script tag, the "Ads" nav link, the `g a` jump. IN its place: a link card
"Ad Tracking →" (owner-only finance surface keeps one click away). Voice-nav:
`ad_tracking` becomes a PAGE target → `/ads` opened in a NEW TAB with the spoken line;
the false-limitation line stays dead; all other targets untouched.

### 4 · Outlier rules (deterministic; thresholds adjustable via manual-inputs)
| Flag | Rule (per window) | Default | manual_targets key |
|---|---|---|---|
| KILL CANDIDATE | spend ≥ $X and 0 leads | X=$150 | ad_flag_spend_no_leads |
| FUNNEL BREAK | ≥ N leads and 0 sets | N=8 | ad_flag_leads_no_sets |
| SHOW-UP PROBLEM | show rate < Y% at ≥5 sets | Y=40% | ad_flag_show_floor_pct |
| WRONG AUDIENCE | qualified% deviates > Z pts from account avg at ≥8 leads | Z=25 | ad_flag_qual_dev_pts |
| CPL OUTLIER | CPL > M× account avg at ≥5 leads, spend ≥ $100 | M=2.0 | ad_flag_cpl_mult |
| CAPTURE REGRESSION | window attribution rate < trailing-90d − D pts | D=10 | ad_flag_attr_drop_pts |
| DATA INTEGRITY | duplicate-suspect rows > 0; revenue-unknown > U% of window leads | U=20 | ad_flag_unknown_rev_pct |
All min-n respected; each flag card states rule + numbers + the implied question; new
flags feed salience once, watermarked.

### 5 · Defaults
Path `/ads` · name "SERVED AD TRACKING" · access owner + coo (Piolo full-visibility per
the standing rule) + media_buyer (romano; SHIPS DISABLED — enabling = setting
MEDIA_BUYER_PASSWORD; his session is fail-closed allowlisted to /ads only, the sales-role
pattern). ARCHITECTURAL SIMPLIFICATION RECORDED: the planned timeline copy of this
section is CANCELLED — Romano uses /ads directly; the timeline's only remaining debt is
its railway.json build gate.

## THE BUILD + THE FIVE PASSES (2026-08-05, all live on production data)

Shipped: `/ads` (dashboard/ads.py + ads.html + adsapp.js/css — neutral asset names per
the ad-blocker lesson) · finance dashboard migrated to a link card · voice-nav retargeted
(new-tab, URL params) · attribution_flags.py scorecard · roster API · media_buyer role
scoping (ships disabled). Suite **563 green** (17 new).

**PASS 1 — RECONCILIATION**: 3 windows, rows-sum == totals == engine recon ok:
30d leads 80 / closes 6 / cash $41,635 · 60d 165/10/$59,945 · 90d 272/18/$110,140.
Leaders present each window; every leader's figures exist verbatim in the table.
**PASS 1b — ROSTER==COUNT**: 15/15 cells (top 3 creatives × 5 stages), zero mismatches.
**PASS 2 — DRILL TRUTH**: live people carry real bands (tracker-sourced), setter
outcomes, pipeline stages ("Consult Call Booked", "Disqualified"…), tracker+GHL notes
with source labels and fetch stamps, GHL links; closes carry contract+cash (Tesla Zhong
$8,305 = the Stripe-matched figure). Empty notes render "no notes recorded".
**PASS 3 — WINDOW PROOF**: board==direct engine API on all totals + identical top rows,
3/3 windows; browser toggle 30→60 updates URL (?window=60), banner flips to the 60d
figures (90.9%, 150/165), skeleton during the swap, latest-wins + echo guard in code and
under test.
**PASS 4 — ADVERSARIAL** (test-enforced + probes): media_buyer sweep (enabled in test
env): /ads 200; chat/snapshot/greeting/collab/targets/data-sources/leads → 403/bounce;
/cfo/* 401; sales → bounced from /ads; anon → login; nonexistent/ambiguous creatives
refused (nav tests); zero-flag windows render "thresholds all clear"; days capped ≤365;
read-only grep green.
**PASS 5 — COLD END-TO-END** (browser, production data): open /ads?window=30 → banner
86.2% (69/80), 3 leaders, 11 flags (the real zero-lead spenders: B009_A03 $318/0,
G3 July $231/0, …, + the Nirosha duplicate-row account flag), 72 creatives, 80 tracker
rows; toggled 60d (proven above); **clicked the 17 → 17 person cards, "matches the
cell ✓", 34 real labelled notes** (Ross Tancred — "will have a look at our website…"
tracker; George Fatouros — GHL notes with fetch stamps). No body h-overflow.
Screenshots: claude-chrome-screenshots-UO7oRw/screenshot-1785911252735-2.jpg (the
scorecard) + …-1785911372332-3.jpg (the drill).

REMAINING: Rydel's minute — open /ads, click the 17, meet the humans.
