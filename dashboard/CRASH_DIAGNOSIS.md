# CRASH DIAGNOSIS — the dashboard from Rydel's seat (Phase 0, 2026-09-18)

Method: **real browser** — Playwright/Chromium (headless), owner session via the
normal login form, production URL `web-production-16b16.up.railway.app/dashboard/`,
1440×900 desktop, commit `38a8c812` live. Three passes: cold load · warm reload ·
page held open through the 10-minute auto-refresh tick. Full console, DOM probes,
full-page screenshots, timing. Artefacts: `dashboard/evidence/phase0/`
(`phase0-report.json`, `pass1-cold.png`, `pass2-warm.png`, `pass3-rebuild.png`).
**No script injection** — this is the load path Rydel's own Chrome runs.

## The verdict in one paragraph

The page is a **16,225 px client-rendered scroll wall**: the server inlines the
full snapshot into `__SNAP__` but writes **zero values into the HTML** — every
one of 43 panels is a skeleton filled by a single 5,600-line `dashboard.js`
pass whose orchestrator (`render()`, line 528) makes **40 sequential unguarded
calls**. Any early throw halts every renderer after it while server tests stay
green — the structural blindness this wave ends. In this capture the chain
happened to survive, and still: **one panel has been dead-crashed in production
for days** (below), a second visibly races to zero-height, two live `TypeError`s
fired on cold load, and the voice layer arms a microphone loop on every page
load.

## The first uncaught exceptions (console, verbatim)

Cold pass — 23 console entries, including two thrown errors:

```
projection load failed: TypeError: Failed to fetch
    at loadProjection (dashboard.js?v=38a8c8123b71:3589:21)
    at renderFor…
```

```
GET /dashboard/api/action-feed → 500
Failed to load resource: the server responded with a status of 500 ()
```

The 500 repeats on **every pass** (cold, warm, post-rebuild). It is a **server
crash, live in production**: `jsonify` (sort_keys) dies with
`TypeError: '<' not supported between instances of 'int' and 'str'` because
`gap_reconcile.py` posted feed items with `severity: 2` (int) into
`feed:extra:tracker_backfill`, which put an int key beside `"S1"/"S2"/"S3"`
in the feed's `counts` dict (prod log traceback captured 2026-09-17 23:47:52).
The client's `renderActionFeed` does `if (!r.ok) return` — so the **"What
needs action" panel has rendered a skeleton forever, silently**. Crashed-silent
is exactly the class the suite + endpoint tests could not see. Fixed both ends
this wave: severity normalised at ingestion (`_norm_severity`) and at the
source (`"S2"`).

The cold-pass `net::ERR_ABORTED` batch (19 requests) is a navigation artifact
of the capture (login redirect → goto re-entry) — but it exposed a real
property: `loadProjection` **throws** on a failed fetch rather than rendering a
failure state; on a flaky connection those panels die exactly like Rydel
described.

## Panel inventory — 43 sections, every one client-filled

DOM probe results (warm pass): headline positions in px from page top.

| Section | Render mode | State in capture |
|---|---|---|
| section-brief (Morning Brief hero) | client-fill (renderMorningBrief; rebuilt every 10 min, innerHTML wipe) | rendered; hero ratio stats present (`11.51× / 4.94×` at y=321 — first screenful) |
| section-exec, section-actions | client-fill | rendered |
| section-kpis (KPI strip) | client-fill | rendered; LTV/LTGP cells are the standing engine's second render path (removed this wave) |
| section-action-feed | client-fill from /api/action-feed | **CRASHED — endpoint 500 on every pass; skeleton forever, silent** |
| section-csm-card | client-fill (owner fetch) | **RACE — h=0 flash on warm pass** before fetch resolves |
| section-decision-cards | client-fill (owner fetch) | rendered — 2,747 px tall, pushes Cash Position to y=4,379 |
| section-cash-position | client-fill | rendered ($187,613, "as of 2026-09-18") — value fresh, but freshness only visible inside this one panel |
| section-ar | client-fill | rendered (y=5,181 — 6 screenfuls down) |
| section-ratio-tiles | client-fill | rendered at y=1,616 (below the fold) |
| remaining 33 sections (capital, stripe-health, forward, trend, revenue, churn, month-perf, waterfall, outflow, commissions, metrics, perf-analysis, speed-to-lead, funnel, setter-deep, health, verdicts, team, deficiency, pipeline, dq-loss, offers, lead-roi, reps, cohort, reconciliation, quality, bas, forecast-cash, forecast-mrr, roas, ops-cards, adlink) | client-fill, one shared orchestrator | rendered in this capture; **zero of them have an error boundary** — all die together on any early throw |

Page height: cold 16,225 px · warm 15,590 px · post-rebuild 16,259 px
(≈18 screenfuls at 1440×900). Load: cold DCL 5.08 s · warm 2.63 s.

## The audio loop's role

`edith.js:2345-2346` — on **every page load**, wake-word and double-clap
detection arm **by default** (`lsGet('edith-wake','1')`, `lsGet('edith-clap','1')`
— default `'1'` unless the user has explicitly unchecked them):
`armClap() → ensureMic() → navigator.mediaDevices.getUserMedia({audio:true})`
plus a continuous AudioContext analyser loop. Headless Chromium denies the mic
silently; **Rydel's real Chrome runs the always-on mic/analysis loop on a
finance dashboard** — the page is permanently busy (this is what made the
prior wave's injected screenshots "intermittent"), and a permission prompt can
sit over the page. No autoplay media fires on load (`loadBootVisuals` is
visual-only; entrance audio needs a reactor click) — the offender is the
**mic loop, not playback**. This wave: both default to `'0'` — voice is opt-in
via the reactor click; owner-exclusivity unchanged.

## Freshness & accuracy notes from the capture

- Cash on hand read "$187,613 · Xero, as of 2026-09-18" — **fresh at capture
  time**; but the stamp exists only inside the Cash Position panel. Most tiles
  carry no as-of/pulled-at at all, so a stale snapshot is indistinguishable
  from a fresh one anywhere else on the page. (Fixed: every exec tile carries
  `source · as-of · pulled-at`, amber past threshold.)
- The bundle is version-busted per commit (`?v=38a8c8123b71`) — the **HTML**
  itself is the un-busted surface; cache headers verified this wave.
- `finance_analysis._windows()` pins `sep_mtd` to `date(2026,9,1)` — correct
  this month, **rots on Oct 1** (flagged, not silently fixed).

## What this diagnosis mandates (the wave's build order)

1. Headline values **server-rendered** into the HTML (JS enhances, never fills).
2. Every panel an **error boundary**; the orchestrator guarded per-panel.
3. Voice/mic **opt-in**; no always-on loop on the data page.
4. The landing page ≤ 8 tiles + verdict + cards; heavy panels → their own pages.
5. A **real-browser gate** (this same Playwright harness + assertions) as the
   deploy gate; client errors → telemetry → sentinel feed.
