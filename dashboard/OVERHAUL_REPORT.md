# CFO Dashboard — Fable-Class Overhaul Report
2026-06-11 (Sydney) · commits `ceca950` → `aa785f6` (6 stage commits, each independently deployable)

## Stage 0 — Audit findings

**SECURITY (critical, fixed first):** `GET /cfo/snapshot` was publicly reachable
with zero authentication, serving the entire 68KB financial picture — cash
balances, burn, margins, every client's MRR, and the **named team roster with
per-person salaries** (AUD + PHP) plus owner pay. It had been designed open in
the daily-pulse era and never revisited. Locked the same hour it was found:
now requires `X-CFO-KEY` or a dashboard cookie; 3 regression tests pin it;
verified 401 live. All `/dashboard/api/*` routes (incl. chat, which spends the
Anthropic key) were already correctly auth-gated; `/cfo/refresh` already 401'd.

Other Stage 0 findings: snapshot 4 days stale in production (no scheduled
refresh existed — fixed in Stage A); no formal cash engine module (cash was
computed once in snapshot.py — formalized via the metrics engine); all recent
fixes (re-sign slider, PDF, roster, dual deployable cash) confirmed deployed;
127/127 tests passing at baseline.

## Stage A — Accuracy lockdown (full detail: ACCURACY_LOCKDOWN.md)

- **`metrics_engine.py`**: one canonical, labelled entry per headline metric
  (`value`, FLOW/BALANCE `kind`, `window`, `source` field path, plain-English
  `definition`). All surfaces — dashboard, Jarvis, PDF, exports — display
  these; none recompute.
- **Consistency gate**: `assert_consistency()` on every build. Internal
  arithmetic contradictions (burn differing across surfaces, runway not
  recomputing from displayed inputs, cash-card math not closing, NaN/Infinity)
  now **fail the build loudly**; the app keeps serving the last good snapshot.
- **Stripe truth**: collected cash labeled **GROSS** (pre-fee), payouts
  labeled **NET banked**; in-transit cash is an explicit BALANCE with a
  confirmed-date and a >7-day staleness flag. The $87k-vs-$62k mystery solved:
  Stripe's "last 4 weeks" is the payout view ($87,878.74 banked), the
  dashboard's card is gross charges collected ($80,860) — different concepts,
  now both shown with definitions.
- **Upstream bug found**: the Stripe MCP **ignores its `days` parameter**
  (every window returns trailing 30d) — "prior period" revenue had silently
  computed to $0 since forever. The pull now detects the dishonored window and
  refuses to fabricate (None + degraded flag). **Root fix needed in the
  served-stripe-mcp repo.**
- **Scheduled refresh**: daemon thread every 6h ends the stale-snapshot era.
- **Tests**: +20 displayed-output guardrails (150 total, all passing).

## Stage B — Design system

Navy-anchored token system on the brand palette (#2E6EA6 / #1A3A5C / #EEF4FA /
#7A9ABF); status green/amber/red are semantic only. Fraunces display over
Archivo UI; **tabular numerals on every figure**; currency 0dp with thousands
separators; explicit-sign deltas. One card anatomy across all stat tiles.
One Chart.js chrome (grid/tooltip/legend) — and the forward cash chart now
**overlays the 0% churn-cliff baseline against the selected re-sign %** with a
red zero-line, making the retention value visible rather than numeric.
Contrast-checked text tiers, no pure white, focus-visible states,
reduced-motion support.

## Stage C — UX & intuitiveness

- **Morning Brief** at the top: cash + runway + burn in display type, MRR with
  trajectory arrow and next-month figure, top-3 movers since yesterday, the
  binding constraint named in one sentence, and a single recommended focus.
  The 60-second read; everything below is detail on demand.
- **IA reordered by decision priority**: Brief → Cash → Forward → MRR → Churn
  → Economics → P&L → Funnel → Clients → Team → Pipeline → Reps → DQ.
- **ⓘ definition tooltips** on headline metrics, fed by the metrics engine's
  canonical definitions including FLOW vs BALANCE — the Stripe-cash vs
  recognized conflation that once confused Jarvis is now taught to the human.
- **Windowed vs LIVE badges** on every panel; window badges track the toggle.
- **States**: skeleton loaders, global error banner with retry, cash
  confirmed-date staleness surfaced on the card itself.
- **Progressive disclosure**: per-deal commissions and the cohort matrix
  collapse to `<details>`; roster modeling shows "⚠ N changes from actual —
  reset" whenever scratch edits are live.
- **Responsive pass**: brief stacks, cash grids go single-column, tables
  scroll horizontally — checkable from a phone.

## Stage D — Fluidity & performance

- **Instant paint**: the last snapshot is inlined into the page
  (`window.__SNAP__`) — first render requires **zero** API round-trips,
  then a background refresh runs with an "Updating…" indicator.
- **Toggles**: window switching confirmed purely client-side from precomputed
  `sales.windows[]` (no refetch — latency is render-only). Re-sign slider
  recomputes display-side from precomputed forward months.
- **Zero layout shift**: reserved min-heights for hero/KPI/cash/forward;
  fixed chart frames.
- **Lazy render**: offer-mix chart + cohort matrix defer via
  IntersectionObserver until scrolled near.
- **Jarvis feel**: animated typing indicator + smooth autoscroll.
  *Deferred:* token streaming (the chat path is non-streaming `requests`;
  converting to SSE was judged too risky under the cap — top follow-up).
- **Page weight** (uncompressed): CSS 45.3→61.7KB, JS 156.8→170.2KB,
  HTML 21.1→23.3KB — the cost of the design system and new features, offset
  by one fewer blocking request before first contentful paint.

## Stage E — Intelligence & delight

14-day sparklines + signed 1-day deltas on headline KPIs; >15% day-over-day
movers get a pulsing anomaly dot in the Brief; context-aware Jarvis question
chips ("What's our real runway?", re-sign scenario when churn risk exists,
hire affordability when headroom exists); **Cmd+K command palette** (sections,
refresh, PDF, exports, ask-Jarvis) with `g c` / `g f` / `g b` / `g t` / `g m`
shortcuts and `/` for chat; 500ms eased count-up on first load only.

## Non-regression checklist

- ✅ Auth: dashboard + all APIs reject unauthenticated; `/cfo/snapshot` locked (verified 401 live)
- ✅ Engines untouched in B–E (cash, financial_position, forward MRR, hiring, metrics_engine)
- ✅ Date-window reactivity, re-sign slider (now charted), roster scratch editing + reset
- ✅ Briefing PDF endpoint live (auth-gated 302), sales export privacy tests green (16/16)
- ✅ Jarvis memory + canonical-metrics discipline (context now leads with the metrics block)
- ✅ No secrets in client assets (grep clean: sk-ant, X-CFO-KEY, tokens)
- ✅ 150/150 tests passing (the one observed failure was a local DNS outage mid-run, not code; re-verify with: `python3 -m pytest tests/ test_snapshot.py`)
- ⚠ Ad-spend slider: listed in the contract but **does not exist in the codebase** (confirmed absent at Stage 0) — nothing regressed; flagging so it can be commissioned deliberately if wanted.

## Needs-Rydel (cannot be fixed from this repo)

1. **Reconfirm cash figures** (bank balance + Stripe in-transit) and set
   `CASH_CONFIRMED_DATE` on Railway — the override is from 2026-06-04 and the
   dashboard now shows an amber "reconfirm" flag.
2. **Fix the Stripe MCP service** (separate repo) to honor the `days` param.
3. **Sheet hygiene**: blank closer commission (1 deal), blank setter
   commissions (8 deals), Pottery Green Bakers Gordon active at $0 MRR,
   scorecard-vs-raw funnel mismatch.
4. **If the Lark pulse fetches `/cfo/snapshot`**, add the `X-CFO-KEY` header —
   the endpoint no longer serves anonymous requests.

## Five things to eyeball yourself (design/feel are human judgments)

1. **The Morning Brief on your phone** — is the cash figure the first thing
   your eye lands on, and does the one-sentence constraint ring true?
2. **Drag the re-sign slider** — the gap between the dashed churn-cliff line
   and the solid line is the dollar value of retention; does it read instantly?
3. **Hover an ⓘ icon** — do the FLOW/BALANCE definitions match how you think
   about the numbers?
4. **Hit Cmd+K and type "cash"** — does the palette feel fast and obvious?
5. **The Fraunces/Archivo pairing and navy depth** — premium financial
   product, or too moody? Type and atmosphere are taste calls; everything
   else I can defend with data.
