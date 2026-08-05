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

(Build sections follow: Phase 1 the section, Phase 2 nav + self-model, Phase 3 the
full check.)
