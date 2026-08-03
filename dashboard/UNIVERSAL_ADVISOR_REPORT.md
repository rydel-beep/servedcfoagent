# EDITH Universal Advisor — Build Report (Phases 1–4, 2026-08-03)

EDITH is now Rydel's voice on the Timeline Dashboard — **owner-exclusive, one brain,
read-only on the delivery world**. This report is the evidence record. Companion doc on the
timeline side: `TIMELINE_EDITH_BRIDGE.md` (auth/token design + Layer-1 specifics).
Decisions: DECISIONS.md #104–107.

## Architecture (as approved in Phase 0)

ONE BRAIN — no forked EDITH. The Timeline ships a thin widget (`web/edith.js`) that talks
only to same-origin proxy routes; those proxy to this service's new `/bridge/*` blueprint,
which delegates to the SAME cores the CFO dashboard uses (`chat_stream_response`,
`tts_response`, `greeting_response`) with `channel="timeline"`. Memory facts, recall,
salience watermarks, registers, three-tier routing: shared. Conversation THREADS are
surface-scoped (`db.get_or_create_active_conversation` — dashboard text+voice share one
rolling thread as always; `timeline` resumes only its own).

Token flow (Option A): the timeline mints a **per-request 60s HMAC token**
(`EDITH_BRIDGE_SECRET`, shared env on both Railway services, never in any browser;
µs-precision expiry so same-second tokens are unique; single-use per worker) → this
service independently re-validates signature/expiry/TTL-sanity/purpose/owner on EVERY
`/bridge/*` request. Fail-closed without the secret. Session cookies never authorize
`/bridge/*` (test-enforced).

## THE GATE — adversarial evidence (produced before Phases 2–4 built on the bridge)

Layer 2 (this service, direct curl):

| Attack | Result |
|---|---|
| No token | **403** |
| Garbage token | **403** |
| Forged signature (wrong secret) | **403** |
| Real-secret token for `miguel` / `piolo` | **403 / 403** |
| Expired real-secret `rydel` token | **403** |
| Wrong purpose (`dashboard`) | **403** |
| Overlong TTL (mint-bug guard) | **403** (unit) |
| Valid `rydel` token | **200** `{"ok":true,"user":"rydel","surface":"timeline"}` |
| Same token replayed | **403** (single-use; 60s expiry is the cross-worker backstop) |
| Owner's dashboard session cookie on /bridge/* | **403** (unit) |

Layer 1 (timeline, live):

| Actor | entitled | chat-stream | tts | greeting |
|---|---|---|---|---|
| Unauthenticated | 401 | 401 | 401 | 401 |
| `admin` (authenticated non-owner) | `{"enabled":false}` | **403** | **403** | **403** |
| `rydel` | `{"enabled":true}` | SSE meta/delta/done ✓ | audio/mpeg (real ElevenLabs bytes) ✓ | full payload ✓ |

First live reply through the bridge: *“Loud and clear, Rydel — EDITH's online on this
surface.”* Widget presence: the button is server-flag-revealed (`/api/edith/entitled`,
same idiom as the SMM tab); the static JS is world-readable but secret-free and inert —
per the approved design, the LAYERS are the security, not client-side hiding.

## Phase 2 — Timeline context, live-verified against the Timeline's own data

- “What is overdue or stalled right now?” → *“32 overdue (worst: Akuna Cafe 5, Hung’s
  Chinese 3, Hono Grill 3); 0 at risk; 145 stale (worst: Noodle Asia 13 …) (Timeline synced
  0.1 h ago.)”* — exact match to `/bridge/data/risk` (total 32, per_client Akuna 5…).
- “Where is Butlers Cucina onboarding at?” → *“established; health 58 (amber); 4 open
  tasks, 4 overdue”* — exact match to the client detail payload.
- “How is Nonexistent Bistro tracking?” → refused, not invented.
- “Any complaints this week?” → *“No complaints this week on the Timeline.”* — ground
  truth 0 in the signals log for the window. Events likewise (0 upcoming → said so).
- Cross-domain: “Full picture on Akuna Cafe” → delivery state (Timeline, freshness-stamped)
  **plus** *“Finance side (CFO snapshot): MRR $3000.0; package Growth Pro; status
  Active.”* — each fact labelled by its source, no new metric math.
- Ambiguous names ask (“A few Timeline clients match…”); pronouns fall through to the
  conversation brain (never substring-matched to a client).

## Phase 3 — Automation health (flag failures AND confirm green)

Registry: 15 Timeline jobs + 4 EDITH loops = **19 automations**, each with expected
cadence and a named evidence source (see `automations.py` header). Live: *“All 19
automations are green…”* and *“Timeline Asana sync (6am): RUNNING — last success 10.6h
ago”* (matches the 6am Sydney run). Failure/stale/unknown paths are unit-verified
(9 tests: stale window, failing with error detail verbatim, bridge-down → UNKNOWN never
green, day-bucketed re-fire, week-bucketed all-green watermark). A live stale-seed was
NOT performed — it would have meant corrupting production `integrationstatus` rows; the
evaluation matrix is covered by tests and the UNKNOWN path fired live during a bridge
outage window. Salience wiring: failures re-fire daily while broken; the weekly
positive-confirmation event makes silence unambiguous.

## Phase 4 — Content review (read-only, copy-only)

`notion_content.py` — dedicated read-only integration; GET + query/search only (write
POSTs refused by construction, test-enforced); review turns inject the piece's VERBATIM
copy with a quote-only-this-text contract. GHL email stats: **probed with the existing
sales-location key → 401 on every email/campaign endpoint → stats cleanly skipped**, and
the review context says so (copy-only).

**⚠ BLOCKED AT SHIP: `NOTION_TOKEN` is not present on the CFOagent Railway service** (the
provisioning was reported done but the variable isn't there — possibly saved on another
service or not saved). Until it lands, every content path fail-honests (verified live:
*“The read-only Notion integration isn't connected on my side yet … I won't invent
content.”*). To light it up: Railway → athletic-gratitude → CFOagent → Variables →
`NOTION_TOKEN` = the “EDITH Read-Only” integration secret, and share the four DBs with
that integration. The Email Command Centre id is discovered via search once readable
(or set `NOTION_COMMAND_CENTRE_ID`).

## Cross-surface continuity (live)

Told on the Timeline widget: *“the pilot venue for the reservations platform will be
Chiangmai Thai, starting mid-September.”* Asked on the CFO dashboard: *“Chiangmai Thai —
starting mid-September.”* Asked back on the Timeline: recalled again. Conversation rows
confirm the scoping: the timeline turn lives in its own `channel='timeline'` conversation;
memory is shared. Greeting watermarks are shared by design (news announced once,
whichever window opens first).

## Boundaries (grep- and test-verified)

No outbound path exists: the two new adapters are GET/query-only (non-GET verbs absent,
enforced by tests); repo-wide there is still no send/publish/SMS/webhook-post capability.
EDITH never contacts clients — the existing in-code refusal is untouched. Read-only on
Timeline data and Notion in this build. All figures verbatim from their sources.

## Non-regression

- EDITH: full suite **416 passed, 0 failed** (394 pre-existing incl. 13 new bridge tests
  at P1; +22 adapter/automation/content tests; salience tests updated to isolate the new
  P3 events — same pattern as Pillar 1).
- Timeline (team-facing, smoke as a non-owner user): ping ok / 1650 cached tasks,
  overview 33 clients, 17 scheduled jobs, login + whoami + assistant status intact,
  signals intact, index serves versioned assets. `/health` reports `ok:false` solely from
  the pre-existing `reconciliation: drift on 1 project(s)` (2 Aug, data drift by design —
  not this build).

## Fixed in passing (pre-existing bugs surfaced by this build)

1. `stripe_reconcile.handle_alias_confirm` swallowed any capitalized question containing
   “is” (payer="What"/"Where") in the pre-tier-2 block — starving data handlers on BOTH
   surfaces. Question openers now fall through; real aliases still learn.
2. Chat rate/state buckets keyed on a retired cookie → all users shared one "anon"
   bucket; now keyed per authenticated user.
3. Same-second HMAC tokens were byte-identical → legitimate back-to-back requests tripped
   the replay guard; µs-precision expiry fixed it.

## Env added (names only)

CFOagent: `EDITH_BRIDGE_SECRET`, `EDITH_BRIDGE_OWNERS`, `TIMELINE_BRIDGE_URL`,
(`NOTION_TOKEN` — pending), optional `NOTION_*_ID` overrides.
timelinedashboard: `EDITH_BRIDGE_SECRET`, `EDITH_BRIDGE_USERS`, `EDITH_BRIDGE_URL`.

## Follow-up queued: Timeline hardening pass (Rydel-approved, next session)

Prompt spec — run against `served-timeline-dashboard`:

> **TIMELINE HARDENING PASS.** Read TIMELINE_EDITH_BRIDGE.md §pre-existing-exposure first.
> 1) Gate the two ungated trigger routes: `POST /internal/sync`, `POST /internal/event-alerts`
> (auth.current_user minimum). 2) Decide + implement auth for the unauthenticated data GETs
> (`/api/overview`, `/api/clients`, `/api/client/{key}`, `/api/timeline`, `/api/complaints`,
> `/api/team`, `/api/stale`, `/api/drill/*`, `/api/day14`, `/api/departments`,
> `/api/department/*`, `/health`) — recommend: require login for everything except `/api/ping`
> and a slimmed `/health`; verify the SPA still boots logged-out to the login screen and no
> team workflow breaks. 3) `/internal/*` routes claim admin-gating but use current_user —
> either rename expectations or add a real admin dependency; make it consistent. 4) Set
> `secure=True` on the session cookie. 5) Rename Railway var DASHBOARD_USER → DASHBOARD_USERS
> (code reads both). 6) Non-regress: per-user logins, Asana sync, signals, nudges, Lark
> alerts, EOW/MVP/SMM tabs, the EDITH bridge (rydel loop + admin 403s re-run). Hard-stop
> with a route-by-route before/after table before deploying.
