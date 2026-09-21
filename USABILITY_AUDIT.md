# USABILITY AUDIT — the real-seat walk

Production `f2e158186f6d` · real Chromium, owner session, desktop 1440×900 and mobile 390×844 · 1320s of walking across parallel shards.

Every page the app serves was loaded, and **every visible control was actually activated** — each one on a freshly reloaded page, so a panel opened by one control can never make the controls beneath it look broken. Controls whose label marks them write-capable are inventoried and reported NOT-EXERCISED: READ-ONLY LAW #148 forbids the click.

**This register is the build list.** Nothing in this wave was built before it existed.

## The shape of it

| pages walked | controls activated | dead or unreachable | errored | not exercised (write-capable) | pages with no metric identity |
|---|---|---|---|---|---|
| 25 desktop + 25 mobile | 1582 | 25 | 19 | 65 | 21 |

**90 findings** · BROKEN 19 · DATA-GAP 1 · DATA-QUALITY 1 · DEAD-CONTROL 17 · DISAGREES-WITH-ITSELF 1 · MISLEADING 2 · NO-JOB 3 · SCAN2-GAP 21 · SLOW 25

### BROKEN — 19

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV1 | `brief` | control errors: “7d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `brief` | control errors: “14d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `brief` | control errors: “30d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `brief` | control errors: “60d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `sales-area` | control errors: “7d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `sales-area` | control errors: “14d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `sales-area` | control errors: “30d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `sales-area` | control errors: “60d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `unit-econ` | control errors: “7d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `unit-econ` | control errors: “14d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `unit-econ` | control errors: “30d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `unit-econ` | control errors: “60d” | Cannot set properties of null (setting 'innerHTML') | fix the handler |
| SEV1 | `ads` | control errors: “150” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “300” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “Campaigns” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV2 | `today` | HTTP 404 (expected 200) | /dashboard/today → 404 | build the page or retire the route |
| SEV2 | `today` | 1 console error(s) | Failed to load resource: the server responded with a status of 404 () | fix or bound the throwing block |
| SEV2 | `sales` | HTTP 404 (expected 200) | /dashboard/sales → 404 | build the page or retire the route |
| SEV2 | `sales` | 1 console error(s) | Failed to load resource: the server responded with a status of 404 () | fix or bound the throwing block |

### DISAGREES-WITH-ITSELF — 1

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV1 | `landing (pulse) vs travelling` | the landing says show rate 100%, travelling says 70% | compass:pulse on production holds show_rate {value: 1.0, n: 29, window: 't30 · verified basis'} and the landing tile is labelled ' | the pulse takes the confirmed basis and its range from the one engine; a scan-2 key ties the two surfaces together so they can never diverge again |

### MISLEADING — 2

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV1 | `landing / today` | “Cash net MTD (bank basis)” is not month-to-date | The tile reads $2,869.53 and its own drawer admits the basis: CommBank 2026-09-15 $185,603.85 → today $188,473.38. The true month- | anchor the month from last_n_days(), not series(); re-anchor when the cached anchor is not the month's earliest available day; regression test |
| SEV2 | `engine (history_store)` | series(field, N) counts ENTRIES, not days | Snapshots append roughly every 2 hours, so series(f, 30) spans about 2.5 days while reading like 30. tile_drawers._bank_anchor() i | callers that mean days use last_n_days(); document the unit on series() |

### DATA-GAP — 1

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV2 | `sales (targets)` | the Closer Payout & KPI target block has no machine-readable labels | The tab reads fine by name (1319 rows; the gid in sales_analytics_pull is stale and 400s). Its KPI block exposes Value/Target pair | show the targets only once Rydel labels the rows; decision card, never a guess |

### DEAD-CONTROL — 17

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV2 | `landing` | unreachable control: “Outflows & BAS
OpEx vs tax/statutory — banded, never blended” | covered by #eh-rings | something is covering it — fix the stacking or remove it |
| SEV2 | `receivables` | unreachable control: “Chat with EDITH” | covered by #defs-help-btn | something is covering it — fix the stacking or remove it |
| SEV2 | `scale` | unreachable control: “” | covered by #iwant-row | something is covering it — fix the stacking or remove it |
| SEV2 | `scale` | unreachable control: “mrr” | covered by #btn-iwant .scale-btn | something is covering it — fix the stacking or remove it |
| SEV2 | `scale` | unreachable control: “btn-solve” | covered by #iwant-row | something is covering it — fix the stacking or remove it |
| SEV2 | `worklog` | dead control: “Done
Concern
Question
Suggestion” | select#collab-kind changed nothing when clicked | wire it or remove it |
| SEV2 | `csm` | unreachable control: “explain ⓘ” | covered by h3 | something is covering it — fix the stacking or remove it |
| SEV2 | `csm` | dead control: “employee
contractor” | select#c17 changed nothing when clicked | wire it or remove it |
| SEV2 | `leads` | dead control: “Look up” | button#lookup-btn changed nothing when clicked | wire it or remove it |
| SEV2 | `leads` | dead control: “All reactivation
Stale only
Pitched-stalled only” | select#bucket changed nothing when clicked | wire it or remove it |
| SEV2 | `memory` | dead control: “on” | input#show-inactive changed nothing when clicked | wire it or remove it |
| SEV2 | `memory` | dead control: “Deactivate” | button#c11 changed nothing when clicked | wire it or remove it |
| SEV2 | `memory` | dead control: “Forget” | button#c143 changed nothing when clicked | wire it or remove it |
| SEV2 | `memory` | dead control: “Clear ALL memory…” | button#clear-all changed nothing when clicked | wire it or remove it |
| SEV2 | `ads` | unreachable control: “” | covered by button .adx-deal-open | something is covering it — fix the stacking or remove it |
| SEV2 | `ads` | unreachable control: “on” | covered by button .adx-deal-open | something is covering it — fix the stacking or remove it |
| SEV2 | `ads` | dead control: “Ads” | button#c97 changed nothing when clicked | wire it or remove it |

### SCAN2-GAP — 21

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV2 | `brief` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `cash` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `sales-area` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `unit-econ` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `projection` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `renewals` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `outflows` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `receivables` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `team` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `decisions` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `system` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `scale` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `definitions` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `worklog` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `bookkeeping` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `csm` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `leads` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `targets` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `data-sources` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `memory` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `ads` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |

### DATA-QUALITY — 1

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV3 | `sales` | the tracker's Closer column carries non-people values | Column 21 holds Kalin (121) and Coby (25), but also 'Showed' (3), 'Cancelled' (2), 'No show' (1) and '0' (1) — outcome words writt | attribute only roster names; surface the rest as a labelled data-quality row |

### NO-JOB — 3

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV3 | `definitions` | page serves no named job | not daily, weekly or monthly work — a reference surface | keep as reference, or fold into a job page |
| SEV3 | `data-sources` | page serves no named job | not daily, weekly or monthly work — a reference surface | keep as reference, or fold into a job page |
| SEV3 | `memory` | page serves no named job | not daily, weekly or monthly work — a reference surface | keep as reference, or fold into a job page |

### SLOW — 25

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV3 | `landing` | slow control: “Chat with EDITH” | 560ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `brief` | slow control: “← Dashboard” | 2364ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `cash` | time-to-interactive 2332ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `cash` | slow control: “← Dashboard” | 1075ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales-area` | slow control: “← Dashboard” | 1330ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales-area` | slow control: “Open SERVED AD TRACKING →” | 999ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `projection` | time-to-interactive 6255ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `projection` | slow control: “← Dashboard” | 1129ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `projection` | slow control: “ⓘ” | 512ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `renewals` | slow control: “Chat with EDITH” | 598ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `outflows` | time-to-interactive 2685ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `outflows` | slow control: “← Dashboard” | 1588ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `receivables` | slow control: “← Dashboard” | 1275ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `team` | time-to-interactive 3172ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `team` | slow control: “Chat with EDITH” | 1089ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `team` | slow control: “← Dashboard” | 2056ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | time-to-interactive 2691ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `decisions` | slow control: “Chat with EDITH” | 1941ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | slow control: “← Dashboard” | 1526ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `scale` | slow control: “← Dashboard” | 1485ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `travelling` | time-to-interactive 4025ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `travelling` | slow control: “← Back to the compass” | 832ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `worklog` | slow control: “← Dashboard” | 1803ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `bookkeeping` | slow control: “← Dashboard” | 744ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `csm` | time-to-interactive 2105ms | budget 2000ms | trim the page's first-paint work |

## Every page — status, speed, controls, identity, job

| page | status | FCP | DCL | TTI | controls | dead | errored | panels | metric keys | the job it serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `/ads` | 200 | 1180ms | 1205ms | 1205ms | 85 | 6 | 3 | 3 | 0 | daily · creative decisions |
| `/dashboard/bookkeeping` | 200 | 1512ms | 1493ms | 1493ms | 1 | 0 | 0 | 1 | 0 | monthly · the queue |
| `/dashboard/view/brief` | 200 | 660ms | 647ms | 648ms | 14 | 0 | 4 | 5 | 0 | daily · the long read |
| `/dashboard/view/cash` | 200 | 2368ms | 2332ms | 2332ms | 10 | 0 | 0 | 4 | 0 | weekly · cash & capital |
| `/dashboard/csm` | 200 | 2128ms | 2105ms | 2105ms | 20 | 4 | 0 | 2 | 0 | monthly · CSM cockpit |
| `/dashboard/data-sources` | 200 | 236ms | 229ms | 230ms | 3 | 0 | 0 | 0 | 0 | none · reference |
| `/dashboard/view/decisions` | 200 | 2488ms | 2691ms | 2691ms | 7 | 0 | 0 | 1 | 0 | weekly · rulings |
| `/dashboard/definitions` | 200 | 1888ms | 1611ms | 1860ms | 1 | 0 | 0 | 0 | 0 | none · reference |
| `/dashboard/` | 200 | 976ms | 953ms | 953ms | 28 | 1 | 0 | 2 | 11 | daily · the old landing |
| `/dashboard/leads` | 200 | 320ms | 291ms | 293ms | 1001 | 2 | 0 | 0 | 0 | daily · reactivation |
| `/dashboard/memory/` | 200 | 240ms | 452ms | 452ms | 224 | 6 | 0 | 0 | 0 | none · reference |
| `/dashboard/view/outflows` | 200 | 2096ms | 2683ms | 2685ms | 9 | 0 | 0 | 3 | 0 | monthly · OpEx & BAS |
| `/dashboard/view/projection` | 200 | 6212ms | 6225ms | 6255ms | 27 | 0 | 0 | 6 | 0 | monthly · forward MRR |
| `/dashboard/view/receivables` | 200 | 1768ms | 1778ms | 1779ms | 8 | 1 | 0 | 1 | 0 | weekly · who owes |
| `/dashboard/view/renewals` | 200 | 1352ms | 1746ms | 1746ms | 16 | 0 | 0 | 4 | 0 | monthly · churn |
| `/dashboard/sales` | 404 | 872ms | 860ms | 860ms | 0 | 0 | 0 | 0 | 0 | daily · the team scoreboard |
| `/dashboard/view/sales` | 200 | 1472ms | 1452ms | 1452ms | 13 | 0 | 4 | 10 | 0 | daily · ads & sales panels |
| `/dashboard/scale` | 200 | 1476ms | 1488ms | 1489ms | 28 | 4 | 0 | 9 | 0 | monthly · the compass |
| `/dashboard/view/system` | 200 | 860ms | 1577ms | 1577ms | 7 | 0 | 0 | 3 | 0 | weekly · is the estate honest |
| `/dashboard/targets` | 200 | 252ms | 235ms | 235ms | 26 | 0 | 0 | 2 | 0 | monthly · targets |
| `/dashboard/view/team` | 200 | 3000ms | 3172ms | 3172ms | 14 | 0 | 0 | 2 | 0 | monthly · team & hiring |
| `/dashboard/today` | 404 | 1124ms | 1114ms | 1115ms | 0 | 0 | 0 | 0 | 0 | daily · are we winning? |
| `/dashboard/scale/travelling` | 200 | 2756ms | 4024ms | 4025ms | 18 | 0 | 0 | 12 | 10 | weekly · plan vs actual |
| `/dashboard/view/unit-econ` | 200 | 1444ms | 1430ms | 1431ms | 18 | 0 | 8 | 6 | 0 | monthly · unit economics |
| `/dashboard/worklog` | 200 | 1912ms | 1886ms | 1894ms | 4 | 1 | 0 | 1 | 0 | weekly · collaboration |

## Mobile 390×844 — overflow and paint

| page | status | FCP | overflow |
|---|---|---|---|
| `/ads` | 200 | 3792ms | none |
| `/dashboard/bookkeeping` | 200 | 3184ms | none |
| `/dashboard/view/brief` | 200 | 1032ms | none |
| `/dashboard/view/cash` | 200 | 1916ms | none |
| `/dashboard/csm` | 200 | 4008ms | none |
| `/dashboard/data-sources` | 200 | 2284ms | none |
| `/dashboard/view/decisions` | 200 | 2660ms | none |
| `/dashboard/definitions` | 200 | 2276ms | none |
| `/dashboard/` | 200 | 2652ms | none |
| `/dashboard/leads` | 200 | 512ms | none |
| `/dashboard/memory/` | 200 | 880ms | none |
| `/dashboard/view/outflows` | 200 | 2172ms | none |
| `/dashboard/view/projection` | 200 | 5320ms | none |
| `/dashboard/view/receivables` | 200 | 3256ms | none |
| `/dashboard/view/renewals` | 200 | 2244ms | none |
| `/dashboard/sales` | 404 | 3008ms | none |
| `/dashboard/view/sales` | 200 | 2012ms | none |
| `/dashboard/scale` | 200 | 1108ms | none |
| `/dashboard/view/system` | 200 | 2416ms | none |
| `/dashboard/targets` | 200 | 2900ms | none |
| `/dashboard/view/team` | 200 | 2348ms | none |
| `/dashboard/today` | 404 | 1752ms | none |
| `/dashboard/scale/travelling` | 200 | 3124ms | none |
| `/dashboard/view/unit-econ` | 200 | 2128ms | none |
| `/dashboard/worklog` | 200 | 3132ms | none |

## Access matrix — who can reach what

| who | page | status | landed on |
|---|---|---|---|
| anon | TODAY | 404 | `/dashboard/today` |
| anon | SALES | 404 | `/dashboard/sales` |
| anon | MONEY | 200 | `/dashboard/login` |
| anon | PLAN | 200 | `/dashboard/login` |
| anon | ADS | 200 | `/dashboard/login` |
| ad_domain | TODAY | 404 | `/dashboard/today` |
| ad_domain | SALES | 404 | `/dashboard/sales` |
| ad_domain | MONEY | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |
| ad_domain | PLAN | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |
| ad_domain | ADS | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |

## Dead, unreachable and errored controls — every one

| page | control | verdict | detail |
|---|---|---|---|
| landing | Outflows & BAS OpEx vs tax/statutory — bande | BLOCKED | covered by #eh-rings |
| brief | 7d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| brief | 14d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| brief | 30d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| brief | 60d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| sales-area | 7d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| sales-area | 14d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| sales-area | 30d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| sales-area | 60d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 7d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 14d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 30d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 60d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 7d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 14d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 30d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| unit-econ | 60d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| receivables | Chat with EDITH | BLOCKED | covered by #defs-help-btn |
| scale | c21 | BLOCKED | covered by #iwant-row |
| scale | c22 | BLOCKED | covered by #iwant-row |
| scale | mrr | BLOCKED | covered by #btn-iwant .scale-btn |
| scale | btn-solve | BLOCKED | covered by #iwant-row |
| worklog | Done Concern Question Suggestion | NO-OP |  |
| csm | explain ⓘ | BLOCKED | covered by h3 |
| csm | explain ⓘ | BLOCKED | covered by h3 |
| csm | explain ⓘ | BLOCKED | covered by h3 |
| csm | employee contractor | NO-OP |  |
| leads | Look up | NO-OP |  |
| leads | All reactivation Stale only Pitched-stalled  | NO-OP |  |
| memory | on | NO-OP |  |
| memory | Deactivate | NO-OP |  |
| memory | Forget | NO-OP |  |
| memory | Forget | NO-OP |  |
| memory | Forget | NO-OP |  |
| memory | Clear ALL memory… | NO-OP |  |
| ads | c10 | BLOCKED | covered by button .adx-deal-open |
| ads | c11 | BLOCKED | covered by button .adx-deal-open |
| ads | on | BLOCKED | covered by button .adx-deal-open |
| ads | on | BLOCKED | covered by button .adx-deal-open |
| ads | on | BLOCKED | covered by button .adx-deal-open |
| ads | 150 | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | 300 | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | Ads | NO-OP |  |
| ads | Campaigns | ERROR | Cannot read properties of null (reading 'scoreboard') |

## Not exercised — write-capable, inventoried not clicked

| page | control |
|---|---|
| landing | Reload the page (values are server-rendered at request time) |
| landing | Download CFO Briefing PDF |
| landing | Forward projection month-0 committed $74,971 open → |
| landing | Bookkeeping queue flag → resolve → verify open → |
| brief | Refresh data |
| brief | Download CFO Briefing PDF |
| cash | Refresh data |
| cash | Download CFO Briefing PDF |
| cash | Save |
| sales-area | Refresh data |
| sales-area | Download CFO Briefing PDF |
| unit-econ | Refresh data |
| unit-econ | Download CFO Briefing PDF |
| projection | Refresh data |
| projection | Download CFO Briefing PDF |
| projection | Declare… |
| projection | Declare… |
| projection | Declare… |
| renewals | Refresh data |
| renewals | Download CFO Briefing PDF |
| renewals | Scan sheet |
| renewals | Declare… |
| renewals | Scan sheet |
| outflows | Refresh data |
| outflows | Download CFO Briefing PDF |
| receivables | Refresh data |
| receivables | Download CFO Briefing PDF |
| team | Refresh data |
| team | Download CFO Briefing PDF |
| team | Reset |
| team | Analyze |
| decisions | Refresh data |
| decisions | Download CFO Briefing PDF |
| system | Refresh data |
| system | Download CFO Briefing PDF |
| scale | RESET |
| scale | RESET |
| scale | reset |
| scale | reset |
| scale | reset |
| scale | reset every control to its measured default |
| travelling | The scenario on screen The committed plan Last month Your us |
| travelling | Save this check |
| worklog | Post |
| csm | on |
| csm | Save config |
| csm | on |
| leads | Log out |
| leads | Refresh |
| leads | Export CSV |
| leads | Download Brief (PDF) |
| targets | ↻ Refresh |
| targets | Save |
| targets | Save |
| targets | Save |
| data-sources | ↻ Resync now |
| data-sources | Refresh panel |
| memory | ↻ Refresh |
| memory | Delete |
| memory | Delete |
| memory | Delete |
| ads | log out |
| ads | Vipin · close |
| ads | Today Yesterday Last 7 days Last 14 days Last 30 days Last 6 |
| ads | sort presets… Most leads Most qualified Most reached Most cl |
