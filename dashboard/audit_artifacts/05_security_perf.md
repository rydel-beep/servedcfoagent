# Phase C+D artifacts — security matrix + measured performance (2026-08-08)

## C1 · Auth matrix (evidence: tests/test_ads_dashboard.py 17 tests fresh-green,
## tests/test_debug_route_auth.py 2 new tests, live anon curls)

| Route | anon | sales | media_buyer | owner/coo | Evidence |
|---|---|---|---|---|---|
| /ads/ + /ads/api/board | 401/302 | 403 | role absent (env unset, live-proven) | 200 | test_anon_sees_nothing · test_sales_role_cannot_reach_ads · env-names probe |
| /ads/api/roster (+level/key/metric params) | 401 | 403 | absent | 200 | test added this session (roster cellspec params asserted) |
| /ads/api/deal · /api/dossier | 401 | 403 | absent | 200 | same allowlist wall (fail-closed fragments) |
| /cfo/attribution, /scoreboard, /rows | 401 (live-curled) | n/a | n/a | key/cookie | live curl 401 artifact |
| /cfo/snapshot · /cfo/refresh | 401 / key-gated | — | — | key/cookie | code + prior tests |
| /debug/stripe-ping · /debug/sources | **WAS 200 ANON** → 401 (hotfixed `45670b7`, live-verified) | — | — | X-CFO-KEY | F4; curl before/after |
| /debug/xero-* · /debug/bas-refresh | 401 | — | — | X-CFO-KEY | test_debug_route_auth sweep (any ungated /debug route now fails the suite) |

State-changing GETs: none user-facing. `/debug/bas-refresh` + `/debug/sources`
refresh caches on GET — key-gated, internal-only; noted, accepted. Card
apply / attendance confirm / PROPOSED interactions all flow through the
authenticated chat/bridge POST path; no mutation route accepts GET.

## C2 · XSS

- Stored-XSS surfaces (Meta creative names, tracker notes, GHL notes): taint
  scan of every innerHTML interpolation in adsapp.js (artifact 04, 64 suspects
  triaged) — all human/Meta-origin strings pass esc(); dashboard.js feed lanes
  sampled: esc() on titles/why/owner. NO stored-XSS path found.
- **ONE reflected-XSS vector found (F12)**: `?roster=<level>~<key>~<metric>`
  deep link — `metric` (and `level`) from the URL render into the drill-title
  innerHTML UNESCAPED before any server validation can reject them. Requires a
  crafted link opened by an authenticated user. → fix wave.
- Secrets in logs: token-adjacent log lines reviewed — statuses and error
  bodies (`resp.text[:300]`) logged, never token values. Clean with note.

## D · Measured performance (artifact 00 latencies + prior-session measurements)

| Metric | Measured | Budget | Verdict |
|---|---|---|---|
| Grid serve (rollup path) | kv get 33ms + render; payloads 239KB (30d) / ~600KB (90d) | <2s | ✅ |
| compute() cold (per key, per worker) | 5.7–7.4s | — | the root of every miss below |
| Roster open, warm engine cache | 210–230ms | <500ms | ✅ |
| Roster open, cold cache (30-min TTL × 2 workers × per-(basis,days,market) key) | 5.7–15.8s | <500ms | ❌ **F1** — the budget holds only in the minority path |
| Dossier (two computes: window + all-time) | rollup-warmed after `47f9c15` prefetch; cold worker = 2× compute | <2s | ⚠ same F1 class |
| Nightly sweep | 76s runtime; API calls bounded: ≤40 appt + ≤30 reached + ≤40 call reads + spine | — | ✅ within budgets; cost now needs a meter (sentinel) |
| Rows control render | client-side slice; worst real dataset 1,113 rows; default window 70 | <2s at All | ✅ by construction (windowed render; not browser-measured — declared) |

NOT RUN (declared): live concurrent worst-case load test (rule B — no prod
load-testing); Postgres EXPLAIN top-5 (queries are single-key kv gets +
one ANY() join on a small table — sampled by inspection, no N+1 found in the
roster/dossier paths: notes capped [:8], one opportunities query per roster);
browser-side render timing + mobile stacking (needs a browser session).
