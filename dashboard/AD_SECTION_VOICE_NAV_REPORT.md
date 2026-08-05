# Ad Section on the Finance Dashboard + Voice-Driven Navigation

## PHASE 0 — FRONT-END MAP + ACTION SCHEMA (2026-08-05)

### The front-end as it exists
- **One long page** (`dashboard.html`), 38 flat `<section id="section-*">` blocks
  re-parented at boot into 4 decision zones by `applyZones()` (`dashboard.js:4263`,
  zone member arrays at `:4247-4262`). Navigation = scroll anchors: the sticky
  section-nav (13 links), vim `g`+key jumps, and the Cmd+K palette (which
  auto-enumerates `.nav-link` — a new nav link is palette-registered for free).
- **Global window bar** `#global-window-bar` (7/14/30/60/90, `currentWindow` state,
  `initGlobalWindowSelector()` at `dashboard.js:1565`) — the natural target for
  "filter to 60 days".
- **The leads page is a separate route** (`/dashboard/leads`, own template) — navigating
  there is a page navigation, not a scroll.
- **SSE contract**: `event: <name>\ndata: <JSON>` (`routes.py:887 sse()`); events
  meta/delta/done/error; generator `chat.py:654 chat_stream`; transport switch
  `routes.py:1029-1055`; deterministic short-circuit `gen_cmd()` at `routes.py:997`.
  Client parser `chat.js:139 sendTextStream` — **unknown event names fall through the
  else-if chain and are silently ignored**, so a new event is backward/forward safe;
  the audio path is fed only from `delta` (a `nav` event cannot break voice, by
  construction). The bridge (`/bridge/chat-stream`) reuses the same
  `chat_stream_response`, so channel-aware behavior lands in one place.
- **Self-model**: there is NO "text and voice only" string in the repo — the false line
  was model-emergent. The persona (`chat.py BASE_PERSONA`) never says she's embedded in
  a dashboard or can navigate it. Fix = (a) deterministic nav interception so display
  asks never reach the model, (b) persona self-knowledge paragraph, (c) per-surface
  capability handler.

### The action schema (v1 — versioned, ignorable, timeline-adoptable)
Emitted as SSE event `nav`, payload:
```json
{"v": 1, "type": "navigate", "target": "ad_tracking",
 "params": {"window": "60d", "creative": "<creative_key>", "verdict": "KILL",
             "q": null, "drill": true}}
{"v": 1, "type": "set_window", "params": {"days": 60}}
{"v": 1, "type": "filter", "target": "ad_tracking", "params": {"verdict": "KILL"}}
```
Rules: unknown `v`/`type`/`target`/params are ignored gracefully client-side (never a
broken page); every nav event is paired with a spoken/text confirmation in the same
reply; nav events are emitted ONLY on the dashboard channel — the timeline channel gets
the honest cross-surface answer until its widget adopts the handler in Part 2 (adoption
= one `else if (ev === 'nav')` + a handler, nothing else).

### The navigable-target registry (CFO surface)
| target | kind | params | existence check |
|---|---|---|---|
| `ad_tracking` | section `#section-ad-tracking` (new) | window, creative, verdict, tier, q, drill | always |
| `brief, cash, forward, mrr, churn, economics, pnl, funnel, clients, team, pipeline, reps, dq` | scroll anchors (the 13 nav links) | — | anchor exists |
| `leads_page` | page `/dashboard/leads` | — | always |
| `targets_page` | page `/dashboard/targets` | — | always |
| `data_sources` | page `/dashboard/data-sources` | — | always |
| `window` | global window bar | days ∈ 7/14/30/60/90 | validated |
| creative entities | drill inside ad_tracking | resolved against the live engine result (entity-gated; ambiguous → ask; nonexistent → refusal, NO navigation) | engine labels |

UI context rides the chat POST (`{ui: {section, window}}`) so relative commands
("just the kills", "now 90 days") compose against the CURRENT view — thread-aware by
transport, no server session state.

## PHASE 1 — THE SECTION (shipped)

`#section-attribution` on the finance dashboard (zone 2, after the funnel; nav link
"Ads"; auto-registered in the Cmd+K palette; `g a` jump). Renderer
`dashboard/static/js/ltcboard.js` — RENDER ONLY off `/cfo/attribution/scoreboard` +
`/rows`: the confirmed columns with verdict badges (DD green / KILL red / WATCH grey
with n), sortable headers, 30/60/90 window selector, honest rows pinned at the bottom
and always rendered, the attribution-rate + qualified-rule + freshness banner, the
constraint line, the creative drill card (click a row → tracker filters to its humans),
search, incremental rendering for the 1,200-row tracker, threshold/unknown/close/tier
highlights, and the basis footer.

**THE AD-BLOCKER TRAP (found live, fixed):** the file was first named `adtrack.js` and
the section `section-ad-tracking` — uBlock-class filter lists silently blocked the
script (`*adtrack*` matches EasyPrivacy patterns) while every other asset loaded. This
would have hit Rydel's browser too. Everything renamed neutral: `ltcboard.js`,
`section-attribution`, `ltcb-`/`ltcv-` CSS prefixes. Recorded so nobody reintroduces
ad-ish names on ad-related UI.

## PHASE 2 — VOICE NAV + SELF-MODEL (shipped)

- `nav_registry.py` (targets/schema/capability text) + `nav_router.py` (deterministic
  intents, FIRST in the chain — a display ask can never reach the model). SSE `nav`
  events emitted on the deterministic path; `edithnav.js` executes them (smooth scroll
  with settle-re-assert, window bar, ad-board filters, page navs) with a flash ack;
  unknown actions ignored. Typed chat now uses the same streaming path as voice —
  identical behavior, one pipeline. UI context (`{ui: {section, window}}`) rides every
  chat POST so relative commands compose against the current view.
- Persona: the "WHERE YOU ARE" block (embedded in the dashboard, can navigate/display,
  per-surface honesty); the emergent "text and voice only" line is structurally dead —
  nav asks are intercepted before the model, and the persona bans the claim for any
  that slip through. Timeline channel: honest cross-surface answer, zero actions.

## PHASE 3 — THE FULL CHECK (all live on the local production-data instance)

ACCURACY: 25 scoreboard cells (5 creatives × leads/qualified/closes/cash/spend) MATCH
the API to the cent; 5 tracker rows MATCH /rows (dates, revenue band/unknown states);
the /rows data was already 15-row hand-verified against the sheet + live Graph in the
scoreboard PASS 1; verdict badges render the engine's verdicts with n; banner figures
are the API's own (86.2% / 69/80 at 30d; 90.9% / 150/165 at 60d).

THE SCRIPTED DRIVE (typed chat = the same stream as voice; transcript excerpts):
1. "show me the ad dashboard" → nav event → page scrolls onto the board (top 76px),
   reply: "Pulling up the ad tracking board — 86.2% of the window's leads are
   ad-attributed; top spender is B008_A04… 17 leads, 1 closes." ✓
2. "filter to 60 days" → board window flips to 60d, banner reads the 60d API numbers ✓
3. "show me Ad B" → drill opens on "Served 2026 Q2/Q1… Rydel AD B", reply carries the
   badge + closes + cash figures ✓
4. "just the ones to kill" → KILL filter applied; zero ad rows (correct — nothing is at
   KILL); honest rows still rendered ✓
5. "open the leads page" → full page navigation to /dashboard/leads; back; "back to the
   ad board" → returns + scrolls (settle-re-assert fix proven on a cold reload, top=0) ✓
6. "show me the Zebulon VSL ad" → honest refusal, wire-verified ZERO nav events ✓
7. timeline channel "show me the ad dashboard" → no nav event, honest "finance
   dashboard" answer, the false line absent ✓
8. "what can you show me?" → the real registry list (board, funnel, cash, pages…) ✓
Width: no body horizontal overflow at narrow width (tables scroll in their wraps);
full multi-device sweep rides Rydel's own drive + the Part-2 timeline session.

REGRESSION: suite green (see session note for the final count); voice pipeline
untouched by construction (nav events never feed the audio chunker — delta-only);
owner gate: /cfo/* 401 unauthenticated (unchanged), dashboard pages behind
require_auth; zero timeline-repo changes (the repo isn't even reachable from this
session); no new writes anywhere.

## PART-2 ADOPTION NOTE (timeline widget)
One `else if (ev === 'nav')` branch + an EdithNav-equivalent handler in the widget;
the server already channels correctly (timeline gets text-only today). The bridge
already serves /bridge/attribution* for the section's data when it lands there.

REMAINING: Rydel's voice drive on his machine — "show me the ad dashboard" — closes
the build.
