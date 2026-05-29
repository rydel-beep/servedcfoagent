# Jarvis Dashboard v1 — Post-Build Report

**Status:** BUILT
**Build date:** 2026-05-29
**Deploy:** Pushed to main, Railway auto-deployed, health check passing

## Live URL

```
https://web-production-16b16.up.railway.app/dashboard
```

## Setup Required (2 minutes)

The dashboard is deployed and running but needs two Railway env vars set:

### 1. Dashboard Token (for login)

In Railway dashboard → CFO agent service → Variables, add:

```
DASHBOARD_TOKEN=McLwu-uvFSaxm49HPGxRdfggOBlgTSEVfztUPqvJPkM
```

Then visit:
```
https://web-production-16b16.up.railway.app/dashboard?t=McLwu-uvFSaxm49HPGxRdfggOBlgTSEVfztUPqvJPkM
```

The token sets a 30-day cookie on first visit. Bookmark the URL — subsequent visits
don't need the query param.

### 2. Anthropic API Key (for chat panel)

In Railway dashboard → CFO agent service → Variables, add:

```
ANTHROPIC_API_KEY=<your-key>
```

**IMPORTANT:** The API key Rydel pasted in the build prompt was used for testing but is
exposed in conversation history. **Rotate the key** at https://console.anthropic.com
and use the new one in Railway. The old key was NOT committed to any file.

Without this key, the dashboard works fully (numbers, charts, refresh) — only the chat
panel shows "Chat unavailable" until the key is set.

## What Works

- Token-protected login (cookie-based, 30-day expiry)
- Query param first-visit auth (?t=TOKEN)
- Money section: MRR, cash collected, gross margin, op efficiency (all with status colours)
- Secondary row: revenue, net profit, payback days, LTGP:CAC
- Verdicts: ranked leak cards with $/mo impact, wins as chips
- Sales funnel: bar visualization with conversion rates
- Per-setter table: dials, sets, dials/set, speed-to-lead, show%, close%
- Per-closer table: shows, closes, rate, commission
- Charts: funnel bar chart + offer mix doughnut (Chart.js, CDN)
- Data quality section (collapsible): degraded sources, last refresh timestamp
- Refresh button: triggers server-side refresh with 10s cooldown
- Auto-refresh: polls snapshot every 10 minutes
- Chat panel: slide-in from right, Anthropic API with full snapshot context
- Chat rate limit: 30 messages/hour
- Graceful chat fallback when API key missing
- Responsive: 2-col on tablet, 1-col on mobile
- Dark glass Jarvis aesthetic

## What's Deferred

- Chat history persistence (currently one-shot per message — v2 feature)
- Revenue trend sparkline (needs 7+ days of history_store data to be meaningful)
- LTGP:CAC trend sparkline (same — history accumulating)
- MTD vs trailing-30d toggle on funnel section
- "View snapshot data" link in chat panel (raw JSON modal)

## Test Results

- Dashboard tests: 8/8 passed
- Categoriser tests: 12/12 passed
- Integration tests: 6/6 passed

## Files Added/Modified

**New (14 files):**
- dashboard/__init__.py
- dashboard/auth.py — Token middleware
- dashboard/chat.py — Anthropic API integration
- dashboard/routes.py — Flask blueprint (6 routes)
- dashboard/templates/dashboard.html — Single-page dashboard
- dashboard/templates/login.html — Token entry
- dashboard/static/css/dashboard.css — Dark glass theme
- dashboard/static/js/dashboard.js — Data fetching + rendering
- dashboard/static/js/chat.js — Chat panel logic
- dashboard/SETUP.md — Chat setup instructions
- dashboard/POST_BUILD_REPORT.md — This file
- tests/test_dashboard.py — 8 tests

**Modified (3 files):**
- app.py — Added blueprint registration + secret_key
- requirements.txt — Added anthropic>=0.52.0
- .gitignore — Added .dashboard_token and .env*

## Smoke Test Commands

```bash
# Health check
curl -s https://web-production-16b16.up.railway.app/health

# Login page renders
curl -s -o /dev/null -w "%{http_code}" https://web-production-16b16.up.railway.app/dashboard/login

# Dashboard redirects to login (no auth)
curl -s -o /dev/null -w "%{http_code}" -L https://web-production-16b16.up.railway.app/dashboard/

# First visit with token (after setting DASHBOARD_TOKEN env var)
# Open in browser:
# https://web-production-16b16.up.railway.app/dashboard?t=McLwu-uvFSaxm49HPGxRdfggOBlgTSEVfztUPqvJPkM
```

## Permissions Note

Phase 0 permissions update was NOT needed — the existing settings.local.json already
had sufficiently permissive allow entries. No changes were made to the permissions config.
No revert needed.

---

Ready for Rydel's first login. Set the two Railway env vars (DASHBOARD_TOKEN + ANTHROPIC_API_KEY),
then bookmark the URL with the token query param on first visit; the cookie carries it from then on.
