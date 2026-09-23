# STATUS — served-cfo-agent session log

## 2026-09-23 — R-PIOLO · EVIDENCE-FIRST CLOSES · MONEY UNDER ANOTHER NAME (#161)

Built + committed; **not deployed yet** — the Railway CLI session expired
mid-session, so the live evidence, Part 2 (Koji specifically) and every
production check are outstanding and are NOT claimed. Suite **1377 passed**,
compileall + import clean.

**THE THREE-LINK VERDICT (read off the code paths, all three broken):**
1. the close event — `_closes_union` builds from the tracker (close columns
   empty since 24 July) plus the gap ledger's AUTO entries;
2. the money — the matcher attaches by name, and `_stripe_hits` (which
   decides AUTO vs PROPOSED) **never read the payer-alias store at all**;
3. the recompute — `rebuild_closes()` is called from exactly ONE place, an
   owner-only button. No loop, no refresh path. "Refreshed and still not
   updated" is literally true.

**Built**: `close_detect.py` (four sources read together, provenance on every
entry, corroboration-pending listed, immediate invalidation on the 5-minute
tick) · `unmatched_payments.py` (TODAY panel + one-click owner confirm that
writes and journals the alias, re-matches, rebuilds) · the gap ledger now
counts a confirmed alias as payment evidence (normaliser mismatch caught by a
test) · the matcher attaches on **identity only** — a distinctive surname or
first-name+amount used to AUTO-ASSIGN and are proposals now · `role_access.py`
(R-PIOLO: central allowlist, deny by default, carve-outs first, single-person
totals suppressed) · EDITH answers "what closed today" from the ledger ·
scan-2 keys for both new panels · registry 212/212, jargon zero.

**Artefacts**: `CLOSE_PIPELINE_DIAGNOSIS.md` · `dashboard/evidence/role-matrix-after.json`
(every route × role, real status codes) · `dashboard/evidence/close-pipeline-drills.json`
(six drills, all passing, including "a surname is never auto-assigned" and
"evidence → blocks rebuilt") · DECISIONS #161.

**Flagged, not slipped in**: Piolo loses EDITH's **voice** (Rydel's ruling)
and EDITH's **memory pages** (my judgement call — owner-scope facts; one line
lifts it).


## 2026-09-22 (2) — SYSTEM PAGE · FRESHNESS AS A CONTRACT · EDITH ON EVERY OWNER PAGE (#160)

Deploys → 0b1687e7, 21715fe2, 1991a8f0, d6357e02, 6eddb77a, 16af00b9,
2df40867, bb4e0fac SUCCESS. Suite **1351**. Zero writes
to the tracker, GHL or Xero (the #148 law re-proven); no token minted.

**The System page was not slow — it never stopped talking.** Phase 0's three
passes killed my two obvious hypotheses (CLS **0**, long tasks **0 ms**). The
sixteen-minute idle pass found `/api/memory-status` every 60 s forever, a
`/api/voice-status` every 5 min and a **full panel re-render at +600 s**, all
riding along on the dashboard bundle. Rebuilt from stored results only
(**134 ms** to assemble): requests 23 → **6**, API calls on load 10 → **0**,
idle → exactly one `/api/system` a minute, no re-render, CLS still 0, zero
console errors. Telemetry is now grouped — 81 browser errors that are ONE
bug (the #158 null-innerHTML defect, last seen 19.1 h ago) read as a dozen
fires when streamed raw.

**Freshness was a chain problem.** Every source was inside budget, but the
engine blocks the tiles read were **70 min** old (they rebuilt only on a loop
that sleeps two hours first), today's Meta spend could not refresh at all
(**18.4 h** — store-first archive, idempotent backfill), and NEITHER refresh
button touched what the tiles read. `freshness.py` now owns a stated contract
per source, an as-of computed from a value's INPUTS, a five-minute tick that
rebuilds only when inputs move, and a real Refresh now (owner, rate-limited,
journaled, **Xero never force-pulled** — single-use token). Live after:
blocks 1.6 h → *just now* · Meta 18.4 h → *just now* · **zero stale sources**.

**The dock is a new CHANNEL, not a second EDITH** — same brain, same chat
route, same server-side voice proxy, `channel="dashboard"` beside the
Timeline bridge's `"timeline"`. Owner-only, `EDITH_DOCK=off` kill switch,
loads after first paint in its own boundary, silent until tapped.

**What the gates found that I had not:**
1. **EDITH's brain was DOWN in production.** `anthropic 1.7.0` (resolved from
   a floating `>=0.52.0`) dropped `temperature` from messages.create/stream;
   every business answer failed while glossary answers still worked, so
   nothing showed it. `llm_compat.temp()` fixes it and EDITH's pulse is now a
   System-page row — the brain was the one thing nothing watched.
2. A tile named its OLDEST input, not the LATE one (tracker aged 6 h, tile
   calmly cited Xero's 19 h inside a 24 h budget). Ranked by budget breach now.
3. TODAY's tiles carried **no as-of at all** — `as_of()` existed, nothing used
   it. All eight carry one now, amber + named source when an input is late.
4. The freshness tick ran **inside the test process**, bumping the derivation
   epoch mid-suite and failing an unrelated cache test. Guarded + pinned.
5. "What's our cash on hand" returned the **glossary** — the possessive read
   as "what is…". Split: *what IS x* explains, *what's OUR x* answers.

Gate artefacts: `dock-1991a8f03e00/report.json` (8 steps, fails []) ·
`stale-drill.json` (pause a sync → the right tiles go amber and name it) ·
`one-brain.json` (said on `dashboard` conv 28, recalled on `text` conv 29) ·
`phase0-system-*` before/after. 26 registry entries for the new UI, coverage
gate extended, jargon grep zero. DECISIONS #160.


## 2026-09-17 (3) — VISIBILITY FIX (#151): ratios on screen, AR internal-only, three paid closes

Deploys → a4a17bca SUCCESS. Suite **1106**. The shipped-≠-visible class
named and closed: the ratios Rydel asked for now lead the MORNING-BRIEF
first screenful (LTV:CAC 11.94× · LTGP:CAC 5.12×, doors + labelled
fallback margin, owner screenshot on the live deploy) + a Zone-1 panel
(window selector, 3:1 benchmark line, always rendered). Root cause: the
old KPI cells read the standing engine's nulls below the fold; the honest
engine had no tile. R-PAID: Grappino=Harman resolved (tracker row 112
email-exact + RECOGNIZED row 2 contract $18,300 sheet-recorded); aliases
+ expiring paid-current overrides journaled with charge ids; AR diff =
exactly three rows → current ($77,698.83→$70,248.83). Contract evidence
ladder upgraded (RECOGNIZED cell > derived): all three contracts SIGNED
$54,600, contract ROAS 7.52×. R-AR-INTERNAL grep-pinned (never chases).
New drill: "what's my LTV to CAC". DECISIONS #151.


## 2026-09-17 (2) — DATA SCRUTINY: headline forensics, tab map, AR, unit economics (#150)

Same-day follow-on to the currency wave. Deploys → c5394f1e SUCCESS. Suite
**1103+** (+19 new: test_scrutiny + test_finance_tabs). Zero tracker/GHL
writes (the #148 law re-proven by the same guards).

1. **THE LAW**: every headline tile shows its work (drawer: definition ·
   formula · components w/ source+ids · clock · reconciliation delta) and
   no bare ambiguous label survives (test-pinned grep). "$72,887.52" is now
   "Committed MRR (revenue)" with all 38 rows + cross-tab recon in its
   drawer; the "$1.6k net" (the Zone-1 forecast projection tile) is now
   "Forecast net (projection)" reconciled against THREE actual nets —
   prod: cash net MTD (bank) +$2,009.09 · operating net MTD −$5,327.67
   (tax banded BESIDE) · expected month-end +$34,277.82.
2. **Plausible-lie bugs fixed**: financial_position nets ate BLENDED opex
   (tax+personal as operating cost) → banded; the waterfall re-blended tax
   in its own net line → dual net; LTV:CAC un-gated from the margin read;
   two unlabelled "cash collected" tiles qualified; 100%-margin Xero reads
   fall to the labelled FY26 42.9%.
3. **finance_tabs.py (NEW)** — runtime tab enumeration of BOTH workbooks
   (15 tabs; new/unmapped = surfaced; XML-entity fix prod-caught) + THE
   SHEET RENEWAL LEDGER (RECOGNIZED cols E–K + Sheet5): 8 renewals the
   system never saw (Noodle Asia $8,560 08-18→02-18-27 · Bluebells
   month-to-month extension · Cycho's · At Thai · Panini CO · Walkway ·
   Raama · Pottery Green) now re-base the renewal watch + extend committed
   (labelled lane; month-0 exact with ledger disclosure — prod $74,970.85 =
   recognized + At Thai's ledger MRR). Conflicts surfaced (At Thai,
   Monty's). EXTENSION joined the declaration kinds. Cross-tab recon:
   roster $72,887.52/38 vs ACTUAL $107,196.01/45 vs RECOGNIZED
   $92,796.01/39 vs footer $67,337.52 — 9 deltas caused + owned; 2
   zero-MRR actives EXPLAINED by ledger renewals (At Thai, Pottery Green).
4. **receivables.py (NEW)** — expected (grid+ledger) vs received (Stripe,
   alias-aware) → prod: **$77,698.83 outstanding / 28 clients**; aging
   sums; Bar Elvina $2,350/9d · Leopard Deli $2,500/9d · Walkway $6,100/40d
   + the ones nobody named (Panini CO $6,258/71d, Raama $6,200/71d);
   12 unmatched payments → PROPOSED alias cards; Xero BS AR-line anchor
   rides the daily BAS pull (invoice-level = registered dependency).
5. **Unit economics**: fully-loaded CAC (spend+commissions+tooling config,
   $0 fixed sales labour stated) BESIDE spend-only; LTV per package
   (config PACKAGE_TERMS authority); LTV:CAC + LTGP:CAC per cohort/T90 w/
   provenance + 3:1 "benchmark, not target"; union-close fallback for the
   gap-window CAC (prod-caught). ROAS panel: COHORT cash 1.01× headline,
   receipts 3.29× demoted "not attributable", contract 5.04× with
   signed-vs-derived split + ⚑ chips; briefing v3 regenerated.
6. **decision_cards.py (NEW, owner-only)**: 27 cards live (3 PROPOSED
   closes · Harman's venue · 6 alias proposals · footer · 2 zero-MRR
   resolutions · tab conflicts · URGENT renewals (Pizzicotto, Pottery
   Green, Naan Sense, Firefly) · ad-set mapping · first review session ·
   GHL 56 open-closed flag).
7. Sentinel: tabs watch (change detection) + AR watch (anchor drift) ride
   nightly; all drills live on both EDITH lists (three nets · committed ·
   who-hasn't-paid · did-X-resign · roas).

**Files:** finance_tabs.py, receivables.py, tile_drawers.py,
decision_cards.py (new); finance_analysis.py, range_unit_economics.py,
snapshot.py, forward_projection.py, finance_sheets_pull.py,
client_overrides.py, renewal_loop.py, xero_pull.py, bas_engine.py,
ad_sentinel.py, config.py, dashboard/routes.py, dashboard.js,
dashboard.html, DECISIONS.md (#150), dashboard/SCRUTINY_DIAGNOSIS.md.


## 2026-09-17 — FINANCE CURRENCY + GAP RECONCILIATION + MONTHLY ANALYSIS (#148/#149)

Deploys → 74bbe0ff SUCCESS. Suite **1084** (+13 tests/test_gap_reconcile).
Zero writes to the tracker or GHL (grep + token-usage test-pinned).

1. **Currency audit** (dashboard/CURRENCY_AUDIT_2026-09-17.md): the machine
   ran all month, the humans stopped (no logins since 08-13). SEV1s fixed:
   MRR snapshots were boot-only (32/45 days missing, unrecoverable — now
   daily + null-guarded + today healed $72,887.52/38); GHL contacts mirror
   dead since 07-27 (manual-resync-only — now daily); the sentinel had NO
   watchdog (now: mutual loop-watching, registry rows, LOUD self-retiring
   feed items — dead-nightly drill proven: 3 items fire).
2. **Gap detected + journaled** (#149): tracker close/contract/cash columns
   silent from **2026-07-24** (last close row 07-23) while GHL closed-stage
   activity continued — HUMAN gap (mirror healthy); lead INPUT rows never
   stopped. 08-06→08-12 both-series-zero = the known upstream lead-flow
   outage, excluded.
3. **gap_reconcile.py (NEW)** — GHL-primary window ledger: 3 AUTO closes
   (Orlando Rinaldi 09-09/Food Corp · William Cooney 09-11/Phoenix Hotel ·
   Harman Singh 09-11) derived through the sanctioned lane with opp/contact/
   charge ids; 3 PROPOSED (Kristeen Hammond, Michael Pulvirenti, Jay
   Lunsford US) with missing-evidence named; person→venue bridge via the
   payment email; dedupe + conflict-surfacing test-pinned; **11-row Piolo
   backfill package** live as self-retiring queue items + gap sentinel rung.
4. **finance_analysis.py (NEW)** — three ROAS labelled never blended;
   Sept MTD: spend $7,183.13 · 145 leads · 3 closes · CASH 3.3× receipts /
   1.01× cohort · **CONTRACT 5.05× (floor — Harman CV unknown)** · LTV
   9.35× (inputs provenance-labelled) · **payback ≈ 1 month** (cohort cash
   crossed spend on Harman's 09-14 payment). Verdict engine cites its
   deciding figures. Owner briefing v2 (kv-versioned md+PDF, owner-only
   routes); dashboard ROAS panel (Zone 4); EDITH drills on both lists
   (roas · which-three-closed · what-did-I-miss · what's-stale).
5. **Drift sweep** (dashboard/DRIFT_SWEEP_2026-09-17.md): renewal scan
   clean · projection month-0 EXACT (drift 0.0) · sets partition green but
   62% of 7d spend UNMAPPED (graphics/retargeting candidates exist + 2 new
   US sets — Rydel maps) · ZERO R-A2 review sessions since 08-24 · footer
   mismatch + 6 won-not-on-Health + 6 zero-MRR actives + 7 cash-needs-
   logging + 4 unmatched payments → Piolo/Rydel register · 56 GHL closed-
   stage opps still status open (flagged to GHL owner, never re-staged).

**Files:** gap_reconcile.py, finance_analysis.py, scripts/currency_probe.py
(new); app.py, automations.py, action_feed.py, ad_sentinel.py,
mrr_snapshot.py, ghl_mirror.py, dashboard/routes.py, dashboard.js,
dashboard.html, DECISIONS.md (#148/#149), test fixes (footer/BAS/consult
date-rot), tests/test_gap_reconcile.py (new).


## 2026-08-17 — CSM INVESTMENT: model + measure + hold to 4x (#146)

The CSM-hire cockpit ships as the repo's FIRST owner-only domain. Suite
**1086** (from 1023; +63 across 5 new test files).

1. **csm_model.py (NEW)** — pure math core. Reproduces the Sequence-to-
   Success v2 printed figures as regression (16 checks green: per-client,
   book, floor/base/upside, loaded ~3.1x beside the source's unloaded 3.5x);
   two ROI clocks (cohort vs steady-state, never blended, test-pinned);
   4x solve = 68.7% renewal on the loaded cohort clock (between base and
   upside; Y1 4x unattainable in every scenario, stated); layer-vs-hire
   lens; funding_paths() is a pure function of owner-config inputs (no
   director constants anywhere — grep-asserted); comp accrual table with
   90-day clawback.
2. **csm_baselines.py (NEW)** — Gate-0 B1–B5 from data with measured/
   placeholder labels: B1 term-length-aware renewal (survivorship-BOUNDED —
   the first run read 100% because churned clients weren't in the stores;
   now the known-churned list bounds the rate and the label says so);
   in-term completion from cash/contract on ended terms; B2 refund split
   (Xero line total + Stripe per-charge evidence; remainder FLAGGED —
   transaction-level Xero is a registered dependency); B3 expansion
   (step-up proxy from repeat won-deals; product lines don't exist yet —
   placeholders retained, declarations measure forward); B4 dated book
   ledger (kv, join/leave events) + owner tiers + second-CSM trigger +
   workload preview; B5 DQS proxy from the bridge (labelled proxy).
3. **Declarations** — DOWNSELL/CONTINUITY + EXPANSION (8 subtypes +
   first-6-month value) join the ONE #135 flow: preview/apply branches,
   convergence semantics (one-off expansion = cash, converges by
   definition), Piolo edit text (unknown kinds now LOUD, never wrong),
   projection additive stream, roster apply, watch clearing (downsell =
   decided outcome), dialog + Mark-continuity inline button.
4. **csm_plan.py (NEW)** — the domain hub: masked-journal owner config
   (director figures kv-only), Gate-0 checklist (auto data ticks with
   evidence + owner human ticks), nine-risk live register, ladder calendar
   from real terms, NRR (starting cohort, mid-window join excluded —
   test), scoreboard K1–K6, comp accrual vs Xero-paid (activates at
   start), actuals overlay (baseline-rate renewals credit $0 — test),
   scenario publish (M8 overlay — the projection panel note, labelled
   what-if), EDITH drill + owner context injector, sentinel watch
   (owner-only lane, never the shared feed).
5. **Surfaces** — /dashboard/csm (7 tabs, watermark + no-screen-share
   banner, keyboard tabs, ?tab=, explain-this → EDITH narrates from the
   engine); Zone-1 owner card (ships hidden, only an owner 200 reveals —
   fail-closed, structural test); DISCREET MODE (session flag, hides card
   + overlay + shows header chip). EDITH registered on BOTH handler lists;
   CSM turns never persist to memory/distillation (either side, any
   channel — tested end-to-end through /api/chat).
6. **csm_docs.py (NEW)** — D4 CSM_ANALYSIS briefing (kv-versioned md +
   PDF, regenerable from chat or page; no director figures by design) +
   D5 candidate comp page (stripped; preflight forbidden-token proof;
   generator REFUSES on a dirty preflight — test). D6 specs in docs/:
   GHL ingestion (+ Tristan-ready task text, not created), health score,
   CSM role scope, Timeline panel outline.
7. **Sentinel** — nightly csm_watch (baseline freshness, ledger, shared-
   memory leak probe) in the owner lane + SENTINEL_QUEUE.md; weekly
   security replay now probes 8 anonymous CSM routes (any 200 = LOUD P1).
8. **SG_RATE = 0.12** — the single super-rate authority lands beside
   SUPER_BASELINE_MONTHLY (which is NOT SG-derived; never multiplied).

**Files:** csm_model.py, csm_baselines.py, csm_plan.py, csm_docs.py (new),
client_overrides.py, renewal_loop.py, forward_projection.py,
finance_sheets_pull.py, mrr_snapshot.py, xero_wages_categoriser.py,
ad_sentinel.py, dashboard/routes.py, dashboard/templates/csm.html (new),
dashboard/templates/dashboard.html, dashboard/static/js/dashboard.js,
DECISIONS.md (#146), dashboard/CSM_DIAGNOSIS.md (new), docs/CSM_*.md (new).
**Tests:** 1086 passed (63 new: test_csm_model / test_csm_declarations /
test_csm_plan / test_csm_confidentiality + existing suites green).


## 2026-08-08 — Roster engine + payment-class ruling (#131) + row control

1. **roster_engine.py (NEW)** — the ONE cellspec→roster path. attribution_engine
   records members at every counter increment (I17: len(roster) == cell, both
   clocks, every metric incl. anomaly classes). Consumers refactored to it:
   /ads/api/roster (all tabs + tier rows + zero cells + anomaly metrics), the
   dossier lead ledger, the JS anomaly panel — parallel person-list code deleted.
   Rosters carry identity chips (id-linked / name-match / ambiguous / tracker-only),
   name-discrepancy, event-with-provenance, funnel chips, GHL + tracker links;
   ?roster= deep links; panel sorts (event/state/cash). I17 in the compute
   invariant sweep + suite + nightly 20-cell sampling (drift = ACTION-lane loud).
2. **DECISIONS #131** — dateless-close payment-class auto-derivation: Stripe
   first-payment matched by EMAIL auto-derives blank Close Dates (journaled
   "ruling-conversion DECISIONS #131" w/ charge id; one feed notice, 7d retention;
   idempotent; nightly rung in resolve_dates). GHL stage stays PROPOSED forever;
   GHL payments + Xero rungs NOT built (both 401 at probe — zero speculative code).
   P1 cards stop generating for derived closes.
3. **Row control** — 70/150/300/All on grid + tracker tables; full-dataset
   sort/find before the slice; tier rows pinned; localStorage + ?rows= state.
   D4 finding: no hard cap existed — ~70 was the natural 30d rollup shape.

**Files:** attribution_engine.py, attribution_verdicts.py (ladder_groups extraction),
roster_engine.py (new), resolution.py, ads_truth.py, dashboard/ads.py, adsapp.js,
ads.html, adsapp.css, DECISIONS.md, dashboard/ROSTER_DIAGNOSIS.md (new).
**Tests:** 683 passed (21 new in tests/test_roster_engine.py).

## 2026-08-07 — PD engine fixes (Master Spec v1.1 reconciliation)

**What changed (4 surgical items; send path untouched):**
1. `segments.py`: new **PD_ACTIVE** state — `pd-active` contacts suppressed from all
   marketing except campaigns registered in `PD_MACHINE_CAMPAIGNS`; precedence over
   S2 (S0/S1 still win). Post-cycle **PD_QUIET** (14-day total silence, blocks even
   pd-machine sends) then S4-WARM with a recent-completion WARM cap. Named
   approximation: month-granular `pd-completed-YYYY-MM` → quiet through day 21 of
   the following month; conductor ledger replaces this later.
2. `segments.py`: discount lock now catches **voucher** (word-boundary, both numbers).
3. `DECISIONS.md`: #129 (conductor autonomy amendment to #110 — two-gate sanctioned
   execution) + #130 (ladder amendment to #112 — PD_ACTIVE/PD_QUIET as implemented).
4. Preflight inventory note (below). The conductor itself is NOT built.

**Preflight "not in any other active Served sequence" — inventory sources (for the
conductor build):** (a) GHL per-contact active-workflow list via API, (b) the
conductor's own enrolment ledger, (c) fallback: any `seq-*` / `*-active` tag.

**Files touched:** segments.py, tests/test_email_gate_hypothetical.py, DECISIONS.md,
STATUS.md (new — this file).
**Tests:** suite BEFORE: 671 passed. Target file: 17 passed (5 new PD tests + voucher).
Suite AFTER: 676 passed (671 baseline + 5 new), 0 failures.

---

## 2026-09-18 — DASHBOARD HARDENING (#152): server-rendered truth · crash isolation · real-browser gate

**Phase 0 named the failure** (dashboard/CRASH_DIAGNOSIS.md): 16,225px scroll
wall, every headline client-filled by a 40-call unguarded orchestrator;
/api/action-feed had been 500ing on EVERY prod load for days (int severity →
jsonify sort_keys crash) with the panel silently skeleton'd; edith armed a
getUserMedia mic loop on every load; Phase-0 artefacts in
dashboard/evidence/phase0/.

**What shipped:**
- dashboard/exec_top.py — server-rendered EXECUTIVE TOP: 8 tiles + verdict +
  summary cards baked into the landing HTML (kv-cached engine blocks, refresh
  rides the 2h loop + boot warm; request path read-only; freshness stamp per
  tile; undefined = labelled state). Landing = tiles + verdict + cards, ≤ 8
  tiles, nothing below the cards. Cache-Control: no-store.
- IA split: /dashboard/view/<area> pages (brief · cash · sales · unit-econ ·
  projection · renewals · outflows · team · receivables · decisions
  [owner-only] · system) from partials/area_*.html; card count == page count
  (test-pinned); CSM card server-gated owner+discreet (#146 honored).
- dashboard.js: boundary() orchestrator — per-panel try/catch, absent
  sections skip, failures render "Panel unavailable — {reason} · retry" +
  telemetry; applyZones skipped on area pages; old LTV/LTGP KPI cells
  REMOVED (one rendering path).
- Voice OPT-IN: edith-wake/edith-clap default OFF (no mic loop on load).
- Telemetry: partials/telemetry.html (FIRST script) → POST /api/client-error
  (auth-gated, rate-limited) → kv ring + hourly buckets; render_health.py
  watches (self-check S1 · error-rate spike · tile freshness) →
  feed:extra:render_health.
- scripts/render_gate.py — THE deploy gate (Playwright, owner session, prod
  URL): 8-tile assertion, labelled-state law, card links 200, area render
  smoke, zero console errors, mobile no-overflow, JS-DISABLED server-render
  proof, post-rebuild hold. Artefacts → dashboard/evidence/gate-<commit>/.
  Drilled: broken build BLOCKED (exit 1) · forced client error reached
  telemetry · injected throwing panel isolated (siblings rendered, zero
  uncaught).
- action_feed._norm_severity + gap_reconcile severity "S2" — the prod 500
  fixed at both ends.

---

## 2026-09-20 — THE SCALING COMPASS (#153): /scale tab · sales pulse · expiring terms

- compass_engine.py: measured defaults (CPL $88.5 n=345 · set 14.8% · show
  90.2% · close 28.3% n=46 · lag [0.73,0.27,0] n=22 · renewal B1 midpoint
  61% [22.7–100] · commissions FY26 6.3% (28.8% in-window read surfaced as
  distorted) · OpEx ex-tax ex-acquisition $45.3k/mo · ε default 0.2 with
  the confounded 1.19 fit surfaced) + the monthly equation forward run +
  bisection target solver + Monte Carlo bands + 3-month backtest +
  scenario/plan-of-record store. Scenario lane only — never actuals.
- /dashboard/scale (owner-only): server-rendered Base hero; inputs with
  provenance chips + reset-to-measured; roadmap table to Dec 2027 with the
  BINDING CONSTRAINT named per month; money view (cohort vs period CAC);
  team view + hire cards; scenarios compare/commit; calibration table;
  briefing PDF.
- Landing: SALES PULSE strip (show rate · close rate · booked calls 7d
  from GHL appointment cache, read-only) under the 8 exec tiles.
- Projection page: EXPIRING TERMS panel (30/60/90; scenario-pin toggles →
  preview API, journal NOTHING; Declare… adjacent) + BURN box (ex-tax,
  tax beside, runway).
- Watches → feed:extra:compass: monthly backtest drift · Plan-2027
  variance · capacity threshold inside hire lead time.
- Gate: pulse-strip assertion + /scale first-paint pass + projection area
  smoke. Suite: [filled at deploy]. DECISIONS #153.

---

## 2026-09-21 — EXPLAIN · SIMULATE · SIMPLIFY (#154)

- dashboard/definitions.json (142 plain-English entries) + definitions.py
  (coverage inventory from code, jargon grep, EDITH explain drill) +
  defs.js (hover 300ms / keyboard focus / long-press tap sheet / "?" mode
  / first-run tours) + /dashboard/definitions legend (auto-generated) —
  100% coverage is a build gate + a render_health watch.
- compass_engine.simulate_month (the simulator's server truth; identity ==
  forward month-1), confidence_word, accuracy_sentence (plain words).
- /scale reshaped: SIMPLE (server-rendered triad + question-headed chain +
  show-the-math + I-want + presets) / ADVANCED (collapsed) / PLAN
  (collapsed). Gate now asserts math parity (page == server), tooltip
  render (5/5 landing sample + scale), collapsed defaults, accuracy line.
- Suite: [at deploy]. DECISIONS #154.

---

## 2026-09-21 (2) — SIMULATOR FIXED FOR GOOD (#155)

- Phase-0 reproduced Rydel's failure exactly: failure (b) lock semantics
  (CPL locked by default; typed CPL ignored + silently reverted; zero
  console errors). scale/SIMULATOR_DIAGNOSIS.md + step artefacts.
- Locks retired: spend+CPL always inputs (number+slider), leads always the
  output; Target mode = spend is the answer; elasticity = CPL visibly
  read-only-derived. sim_core.js = ONE formula file (browser + node);
  200-set parity vs engine = zero mismatches; engine wins on settle.
- scripts/behaviour_gate.py (interaction deploy gate, 3 passes, artefacts,
  posts the LOGIC VERIFIED badge). North-star block (actual·plan·required
  + levers + constraint + what-ifs + pinned inputs), calibration log
  (monthly predictions scored in public), drift alerts. Registry 153
  entries, coverage 100%. Suite: [at deploy]. DECISIONS #155.

---

## 2026-09-21 (3) — HOW WE'RE TRAVELLING (#156)

- scale/TRAVELLING_DIAGNOSIS.md first: what each stage can be evidenced to.
  Key verdicts — consults booked come from the calendar (the tracker's
  set-date column is 0 of 446 rows); PITCHED is an evidenced lower bound
  from the CRM's current stage (no history exists), scoped to this
  window's consults, plus a Piolo package line proposing the column;
  setter activity is cache-only call records (no direction recorded).
- travelling.py: 10 stages with rosters (I17), three-way lead split with
  UNKNOWN as its own bucket, plan-to-date markers on flow stages only,
  pipeline-aware month-end projections, status words with bands and
  confidence intervals (small samples read "too early to tell"), the gap
  finder in clients and cash, cross-checks across calendar/tracker/Stripe,
  EDITH's read with template-filled numbers, saved checks + Monday auto-save.
- /dashboard/scale/travelling — server-rendered from URL state, the
  dual-track funnel as the hero, rosters on demand, "Re-model from
  actuals" and "Save this check". CONSOLIDATION: the north-star levers
  table left /scale; one plan-vs-actual surface.
- FOUND AND FIXED AT SOURCE: revenue_bands didn't know the tracker's
  current picklist spellings ("$50k - $100k"), so those leads parsed as
  UNKNOWN and the qualified rule read them as below-floor — the qualified
  metric was wrong everywhere it is used. Literal spellings added.
- Behaviour gate extended with the travelling contract. DECISIONS #156.

---

## 2026-09-21 (4) — ESTATE TRIPLE SCAN + TRAVELLING DEFECTS + LEDGER (#157)

- A: six travelling defects fixed — confirmed-basis show rate with its
  range and a two-basis gap finder (says when the conclusion flips);
  outcome vs rate as separate statuses; cost/gain polarity; three-way
  status bands; "usually" vs "planned"; identities + named denominators.
- B: ONE qualification rule (attribution_engine.qualify_lead) — there were
  two. Picklist changed at source 2026-08-26; 75 leads had been parsing
  UNKNOWN and reading as below-floor. September qualified restated
  24% → 51%; journalled at restatements:qualified_picklist_2026_09.
  A new spelling now raises a loud drift finding.
- C/D: scripts/triple_scan.py (works / agrees with itself / agrees with
  reality) + ground_truth.py + HEALTH rows + watchdog. First run: 11
  findings, all scan defects, fixed. Second run: 0 findings across 19
  pages, 13 metric keys, 6 real external checks. ESTATE_SCAN_2026-09-21.md.
- E: PROMPT_LEDGER.md — 37 briefs by verified presence. 30 shipped,
  3 partial, 1 not run (DASHBOARD-UX-OVERHAUL), 1 superseded, 1 stale doc.
- F: stage_history.py — the recorder remembers what the CRM forgets, in
  this repo's store, on the existing poll. Pitched is measured from today.
