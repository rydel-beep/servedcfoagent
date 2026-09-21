# USABILITY AUDIT — the real-seat walk

Production `b029c82d8a87` · real Chromium, owner session, desktop 1440×900 and mobile 390×844 · 3755s of walking across parallel shards.

Every page the app serves was loaded, and **every visible control was actually activated** — each one on a freshly reloaded page, so a panel opened by one control can never make the controls beneath it look broken. Controls whose label marks them write-capable are inventoried and reported NOT-EXERCISED: READ-ONLY LAW #148 forbids the click.

**This register is the build list.** Nothing in this wave was built before it existed.

## The shape of it

| pages walked | controls activated | dead or unreachable | errored | not exercised (write-capable) | pages with no metric identity |
|---|---|---|---|---|---|
| 25 desktop + 25 mobile | 1867 | 19 | 22 | 145 | 17 |

**125 findings** · BROKEN 18 · DATA-GAP 1 · DATA-QUALITY 1 · DEAD-CONTROL 14 · DISAGREES-WITH-ITSELF 1 · MISLEADING 2 · NO-JOB 3 · SCAN2-GAP 19 · SLOW 66

### BROKEN — 18

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
| SEV1 | `ads` | control errors: “70” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “150” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “300” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “All” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “Batches” | Cannot read properties of null (reading 'scoreboard') | fix the handler |
| SEV1 | `ads` | control errors: “Campaigns” | Cannot read properties of null (reading 'scoreboard') | fix the handler |

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

### DEAD-CONTROL — 14

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV2 | `landing` | unreachable control: “Ads” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `landing` | unreachable control: “Outflows & BAS
OpEx vs tax/statutory — banded, never blended” | covered by #eh-orbwrap | something is covering it — fix the stacking or remove it |
| SEV2 | `cash` | unreachable control: “Sales” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `sales-area` | unreachable control: “Money” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `renewals` | unreachable control: “Ads” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `scale` | unreachable control: “mrr” | unreachable on a clean page: ElementHandle.select_option: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `scale` | unreachable control: “btn-solve” | covered by #iwant-row | something is covering it — fix the stacking or remove it |
| SEV2 | `bookkeeping` | unreachable control: “Ads” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `csm` | unreachable control: “explain ⓘ” | covered by h3 | something is covering it — fix the stacking or remove it |
| SEV2 | `ads` | unreachable control: “Ads” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |
| SEV2 | `ads` | unreachable control: “” | covered by div .adx-hyg-item | something is covering it — fix the stacking or remove it |
| SEV2 | `ads` | unreachable control: “on” | covered by span .adx-hyg-fix | something is covering it — fix the stacking or remove it |
| SEV2 | `ads` | dead control: “Ads” | button#c108 changed nothing when clicked | wire it or remove it |
| SEV2 | `sales` | unreachable control: “Ads” | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. | something is covering it — fix the stacking or remove it |

### SCAN2-GAP — 19

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV2 | `sales-area` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `projection` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `renewals` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `outflows` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
| SEV2 | `receivables` | page publishes no metric identities | no [data-metric][data-value] anywhere — scan 2 cannot compare it | publish data-metric/window/clock/basis/value on every number |
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
| SEV3 | `unit-econ` | 8 number(s) without an identity | e.g. $85,338, $42,247, $0, 100%, 44 | add the data-metric contract to these |
| SEV3 | `team` | 5 number(s) without an identity | e.g. 18, $31,374, $-3,694, $1,857, 44.5% | add the data-metric contract to these |

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

### SLOW — 66

| sev | page | finding | detail | the fix |
|---|---|---|---|---|
| SEV3 | `landing` | slow control: “Jump to
⌘K” | 835ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `landing` | slow control: “Ads & sales
3 closes Sep MTD · Meta spend $9,082
open →” | 2481ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `landing` | slow control: “Morning brief (full)
the long-form read · exec summary · ver” | 2558ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `brief` | time-to-interactive 2637ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `cash` | time-to-interactive 3982ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `cash` | slow control: “Ads” | 2419ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `cash` | slow control: “Money” | 1680ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `cash` | slow control: “← Dashboard” | 2469ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales-area` | time-to-interactive 3665ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `sales-area` | slow control: “EDITH” | 2364ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales-area` | slow control: “Ads” | 2648ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales-area` | slow control: “Sales” | 2160ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `unit-econ` | time-to-interactive 2426ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `projection` | time-to-interactive 6217ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `projection` | slow control: “Sales” | 2082ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `renewals` | slow control: “Jump to
⌘K” | 906ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `outflows` | time-to-interactive 3092ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `outflows` | slow control: “Sales” | 2393ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `receivables` | time-to-interactive 3397ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `receivables` | slow control: “Ads” | 2610ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `team` | time-to-interactive 4240ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `team` | slow control: “Ads” | 2546ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `team` | slow control: “Sales” | 2176ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `team` | slow control: “CSM” | 2007ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `team` | slow control: “← Dashboard” | 2331ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | time-to-interactive 2777ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `decisions` | slow control: “Ads” | 2888ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | slow control: “Sales” | 2251ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | slow control: “CSM” | 2198ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | slow control: “Decisions
24” | 1400ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `decisions` | slow control: “← Dashboard” | 2447ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `system` | time-to-interactive 3806ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `scale` | slow control: “Ads” | 2361ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `scale` | slow control: “Plan” | 566ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `scale` | slow control: “Show how we're travelling” | 2289ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `travelling` | time-to-interactive 3530ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `travelling` | slow control: “Decisions
24” | 2163ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `definitions` | time-to-interactive 3369ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `definitions` | slow control: “Sales” | 2496ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `definitions` | slow control: “Money” | 2499ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `worklog` | time-to-interactive 2414ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `worklog` | slow control: “Money” | 2301ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `worklog` | slow control: “Done
Concern
Question
Suggestion” | 1174ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `csm` | time-to-interactive 2192ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `csm` | slow control: “EDITH” | 2411ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `csm` | slow control: “Plan” | 2090ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `leads` | slow control: “Sales” | 2101ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `leads` | slow control: “Look up” | 687ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `data-sources` | slow control: “Plan” | 2041ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `data-sources` | slow control: “← back to dashboard” | 2006ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `memory` | time-to-interactive 2900ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `memory` | slow control: “Money” | 2179ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `memory` | slow control: “Decisions
24” | 2123ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `memory` | slow control: “on” | 903ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `ads` | time-to-interactive 5336ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `ads` | slow control: “EDITH” | 2302ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `ads` | slow control: “CSM” | 2278ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `ads` | slow control: “Decisions
24” | 2222ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `today` | time-to-interactive 3510ms | budget 1500ms | trim the page's first-paint work |
| SEV3 | `today` | slow control: “EDITH” | 1838ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `today` | slow control: “Today” | 1815ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `today` | slow control: “Sales” | 2330ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `today` | slow control: “On course to beat the client plan, 8 projected against 4 pla” | 2052ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales` | time-to-interactive 8251ms | budget 2000ms | trim the page's first-paint work |
| SEV3 | `sales` | slow control: “Sales” | 2367ms (budget 500ms) | make the interaction optimistic |
| SEV3 | `sales` | slow control: “month to date” | 2124ms (budget 500ms) | make the interaction optimistic |

## Every page — status, speed, controls, identity, job

| page | status | FCP | DCL | TTI | controls | dead | errored | panels | metric keys | the job it serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `/ads` | 200 | 5348ms | 5335ms | 5336ms | 96 | 8 | 6 | 3 | 0 | daily · creative decisions |
| `/dashboard/bookkeeping` | 200 | 548ms | 520ms | 520ms | 11 | 1 | 0 | 1 | 0 | monthly · the queue |
| `/dashboard/view/brief` | 200 | 1592ms | 2637ms | 2637ms | 25 | 0 | 4 | 5 | 2 | daily · the long read |
| `/dashboard/view/cash` | 200 | 3816ms | 3981ms | 3982ms | 22 | 1 | 0 | 4 | 1 | weekly · cash & capital |
| `/dashboard/csm` | 200 | 2208ms | 2192ms | 2192ms | 31 | 2 | 0 | 2 | 0 | monthly · CSM cockpit |
| `/dashboard/data-sources` | 200 | 1928ms | 1913ms | 1913ms | 13 | 0 | 0 | 0 | 0 | none · reference |
| `/dashboard/view/decisions` | 200 | 3776ms | 2776ms | 2777ms | 18 | 0 | 0 | 1 | 0 | weekly · rulings |
| `/dashboard/definitions` | 200 | 3412ms | 3367ms | 3369ms | 11 | 0 | 0 | 0 | 0 | none · reference |
| `/dashboard/landing` | 200 | 948ms | 948ms | 948ms | 38 | 2 | 0 | 2 | 11 | daily · the old landing |
| `/dashboard/leads` | 200 | 920ms | 903ms | 903ms | 1011 | 0 | 0 | 0 | 0 | daily · reactivation |
| `/dashboard/memory/` | 200 | 2916ms | 2900ms | 2900ms | 231 | 0 | 0 | 0 | 0 | none · reference |
| `/dashboard/view/outflows` | 200 | 2920ms | 3091ms | 3092ms | 21 | 0 | 0 | 3 | 0 | monthly · OpEx & BAS |
| `/dashboard/view/projection` | 200 | 6012ms | 6189ms | 6217ms | 39 | 0 | 0 | 6 | 0 | monthly · forward MRR |
| `/dashboard/view/receivables` | 200 | 3212ms | 3397ms | 3397ms | 20 | 0 | 0 | 1 | 0 | weekly · who owes |
| `/dashboard/view/renewals` | 200 | 728ms | 997ms | 998ms | 28 | 1 | 0 | 4 | 0 | monthly · churn |
| `/dashboard/sales` | 200 | 8212ms | 8251ms | 8251ms | 18 | 1 | 0 | 0 | 26 | daily · the team scoreboard |
| `/dashboard/view/sales` | 200 | 1936ms | 3664ms | 3665ms | 24 | 1 | 4 | 10 | 0 | daily · ads & sales panels |
| `/dashboard/scale` | 200 | 824ms | 1683ms | 1683ms | 40 | 2 | 0 | 9 | 0 | monthly · the compass |
| `/dashboard/view/system` | 200 | 2624ms | 3806ms | 3806ms | 18 | 0 | 0 | 3 | 0 | weekly · is the estate honest |
| `/dashboard/targets` | 200 | 1072ms | 1062ms | 1062ms | 36 | 0 | 0 | 2 | 0 | monthly · targets |
| `/dashboard/view/team` | 200 | 2128ms | 4240ms | 4240ms | 26 | 0 | 0 | 2 | 1 | monthly · team & hiring |
| `/dashboard/today` | 200 | 3524ms | 3510ms | 3510ms | 16 | 0 | 0 | 0 | 12 | daily · are we winning? |
| `/dashboard/scale/travelling` | 200 | 3384ms | 3530ms | 3530ms | 30 | 0 | 0 | 12 | 10 | weekly · plan vs actual |
| `/dashboard/view/unit-econ` | 200 | 1292ms | 2425ms | 2426ms | 30 | 0 | 8 | 6 | 1 | monthly · unit economics |
| `/dashboard/worklog` | 200 | 3508ms | 2401ms | 2414ms | 14 | 0 | 0 | 1 | 0 | weekly · collaboration |

## Mobile 390×844 — overflow and paint

| page | status | FCP | overflow |
|---|---|---|---|
| `/ads` | 200 | 1552ms | none |
| `/dashboard/bookkeeping` | 200 | 1068ms | none |
| `/dashboard/view/brief` | 200 | 1240ms | none |
| `/dashboard/view/cash` | 200 | 2396ms | none |
| `/dashboard/csm` | 200 | 888ms | none |
| `/dashboard/data-sources` | 200 | 1952ms | none |
| `/dashboard/view/decisions` | 200 | 2736ms | none |
| `/dashboard/definitions` | 200 | 1236ms | none |
| `/dashboard/landing` | 200 | 856ms | none |
| `/dashboard/leads` | 200 | 828ms | none |
| `/dashboard/memory/` | 200 | 960ms | none |
| `/dashboard/view/outflows` | 200 | 1312ms | none |
| `/dashboard/view/projection` | 200 | 18832ms | none |
| `/dashboard/view/receivables` | 200 | 1576ms | none |
| `/dashboard/view/renewals` | 200 | 980ms | none |
| `/dashboard/sales` | 200 | 1440ms | none |
| `/dashboard/view/sales` | 200 | 572ms | none |
| `/dashboard/scale` | 200 | 3736ms | none |
| `/dashboard/view/system` | 200 | 3332ms | none |
| `/dashboard/targets` | 200 | 1224ms | none |
| `/dashboard/view/team` | 200 | 1344ms | none |
| `/dashboard/today` | 200 | 1080ms | none |
| `/dashboard/scale/travelling` | 200 | 3544ms | none |
| `/dashboard/view/unit-econ` | 200 | 984ms | none |
| `/dashboard/worklog` | 200 | 1484ms | none |

## Access matrix — who can reach what

| who | page | status | landed on |
|---|---|---|---|
| anon | TODAY | 200 | `/dashboard/login` |
| anon | SALES | 200 | `/dashboard/login` |
| anon | MONEY | 200 | `/dashboard/login` |
| anon | PLAN | 200 | `/dashboard/login` |
| anon | ADS | 200 | `/dashboard/login` |
| ad_domain | TODAY | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |
| ad_domain | SALES | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |
| ad_domain | MONEY | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |
| ad_domain | PLAN | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |
| ad_domain | ADS | 200 | `/ads/?window=30&clock=cohort&market=all&sort=spend.desc&rows=70` |

## Dead, unreachable and errored controls — every one

| page | control | verdict | detail |
|---|---|---|---|
| landing | Ads | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |
| landing | Outflows & BAS OpEx vs tax/statutory — bande | BLOCKED | covered by #eh-orbwrap |
| brief | 7d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| brief | 14d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| brief | 30d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| brief | 60d | ERROR | Cannot set properties of null (setting 'innerHTML') |
| cash | Sales | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |
| sales-area | Money | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |
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
| renewals | Ads | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |
| scale | mrr | BLOCKED | unreachable on a clean page: ElementHandle.select_option: Timeout 2500ms exceeded. |
| scale | btn-solve | BLOCKED | covered by #iwant-row |
| bookkeeping | Ads | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |
| csm | explain ⓘ | BLOCKED | covered by h3 |
| csm | explain ⓘ | BLOCKED | covered by h3 |
| ads | Ads | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |
| ads | c20 | BLOCKED | covered by div .adx-hyg-item |
| ads | c21 | BLOCKED | covered by div .adx-hyg-item |
| ads | c22 | BLOCKED | covered by div .adx-hyg-item |
| ads | on | BLOCKED | covered by span .adx-hyg-fix |
| ads | on | BLOCKED | covered by span .adx-hyg-fix |
| ads | on | BLOCKED | covered by span .adx-hyg-fix |
| ads | 70 | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | 150 | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | 300 | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | All | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | Ads | NO-OP |  |
| ads | Batches | ERROR | Cannot read properties of null (reading 'scoreboard') |
| ads | Campaigns | ERROR | Cannot read properties of null (reading 'scoreboard') |
| sales | Ads | BLOCKED | unreachable on a clean page: ElementHandle.click: Timeout 2500ms exceeded. |

## Not exercised — write-capable, inventoried not clicked

| page | control |
|---|---|
| landing | System the last estate scan passed all three |
| landing | Reload the page (values are server-rendered at request time) |
| landing | Download CFO Briefing PDF |
| landing | Chat with EDITH |
| landing | Forward projection month-0 committed $74,971 open → |
| landing | Bookkeeping queue flag → resolve → verify open → |
| brief | System the last estate scan passed all three |
| brief | Refresh data |
| brief | Download CFO Briefing PDF |
| brief | Chat with EDITH |
| cash | System the last estate scan passed all three |
| cash | Refresh data |
| cash | Download CFO Briefing PDF |
| cash | Chat with EDITH |
| cash | Save |
| sales-area | System the last estate scan passed all three |
| sales-area | Refresh data |
| sales-area | Download CFO Briefing PDF |
| sales-area | Chat with EDITH |
| unit-econ | System the last estate scan passed all three |
| unit-econ | Refresh data |
| unit-econ | Download CFO Briefing PDF |
| unit-econ | Chat with EDITH |
| projection | System the last estate scan passed all three |
| projection | Refresh data |
| projection | Download CFO Briefing PDF |
| projection | Chat with EDITH |
| projection | on |
| projection | Declare… |
| projection | on |
| projection | Declare… |
| projection | on |
| projection | Declare… |
| renewals | System the last estate scan passed all three |
| renewals | Refresh data |
| renewals | Download CFO Briefing PDF |
| renewals | Chat with EDITH |
| renewals | Scan sheet |
| renewals | Declare… |
| renewals | Mark resigned |
| renewals | Mark churned |
| renewals | Mark continuity |
| renewals | Scan sheet |
| renewals | Mark resigned |
| renewals | Mark churned |
| outflows | System the last estate scan passed all three |
| outflows | Refresh data |
| outflows | Download CFO Briefing PDF |
| outflows | Chat with EDITH |
| receivables | System the last estate scan passed all three |
| receivables | Refresh data |
| receivables | Download CFO Briefing PDF |
| receivables | Chat with EDITH |
| team | System the last estate scan passed all three |
| team | Refresh data |
| team | Download CFO Briefing PDF |
| team | Chat with EDITH |
| team | Reset |
| team | × |
| team | Analyze |
| decisions | System the last estate scan passed all three |
| decisions | Refresh data |
| decisions | Download CFO Briefing PDF |
| decisions | Chat with EDITH |
| system | System the last estate scan passed all three |
| system | Refresh data |
| system | Download CFO Briefing PDF |
| system | Chat with EDITH |
| scale | System the last estate scan passed all three |
| scale | What if: close rate to 35% |
| scale | RESET |
| scale | RESET |
| scale | reset |
| scale | reset |
| scale | reset |
| scale | Current run-rate (measured) |
| scale | +50% spend |
| scale | Your 35% close rate |
| scale | reset every control to its measured default |
| scale | c36 |
| scale | c37 |
| travelling | System the last estate scan passed all three |
| travelling | Month to date Last 21 days Custom range |
| travelling | The scenario on screen The committed plan Last month Your us |
| travelling | Save this check |
| definitions | System the last estate scan passed all three |
| worklog | System the last estate scan passed all three |
| worklog | Post |
| worklog | ▸ Show completed (54) |
| bookkeeping | System the last estate scan passed all three |
| csm | System the last estate scan passed all three |
| csm | on |
| csm | Save config |
| csm | on |
| leads | System the last estate scan passed all three |
| leads | Log out |
| leads | All reactivation Stale only Pitched-stalled only |
| leads | Refresh |
| leads | Export CSV |
| leads | Download Brief (PDF) |
| targets | System the last estate scan passed all three |
| targets | ↻ Refresh |
| targets | Save |
| targets | Save |
| targets | Save |
| data-sources | System the last estate scan passed all three |
| data-sources | ↻ Resync now |
| data-sources | Refresh panel |
| memory | System the last estate scan passed all three |
| memory | ↻ Refresh |
| memory | on |
| memory | Edit |
| memory | Deactivate |
| memory | Delete |
| memory | Edit |
| memory | Deactivate |
| memory | Delete |
| memory | Edit |
| memory | Deactivate |
| memory | Delete |
| memory | Forget |
| memory | Forget |
| memory | Forget |
| memory | Clear ALL memory… |
| ads | System the last estate scan passed all three |
| ads | log out |
| ads | Vipin · close |
| ads | Dj · close |
| ads | Hiep Nguyen · close |
| ads | Tommy Lê · close |
| ads | Christie-Lee Gulley · close |
| ads | Jintamani M Thoms · close |
| ads | Nirosha Dushani Jayasekara · close |
| ads | Neri Roth Herrmann ×2 · close · input |
| ads | John Tamayo ×2 · close · input |
| ads | Julieta Pablo Tadiaman ×2 · close · input |
| ads | Jenny Bui ×2 · close · input |
| ads | Today Yesterday Last 7 days Last 14 days Last 30 days Last 6 |
| ads | sort presets… Most leads Most qualified Most reached Most cl |
| today | System the last estate scan passed all three |
| today | PROPOSED close — Kristeen Hammond (2026-07-31) |
| today | PROPOSED close — Michael Pulvirenti (2026-08-27) |
| today | PROPOSED close — Jay Lunsford (2026-09-16) |
| sales | System the last estate scan passed all three |
| sales | unassigned |
