# PHASE 0 — THE SYSTEM PAGE, EDITH, AND WHETHER THE DATA IS CURRENT

**2026-09-22 · production `07a3310` · real Chromium, owner session, three
passes: cold · warm · sixteen minutes idle**

Rydel asked for three things. This is what the measurements actually show,
including the two hypotheses the evidence killed.

---

## 1 · "THE SYSTEM TAB IS GLITCHY" — WHAT IT REALLY IS

### What I expected, and what the measurement said

| hypothesis | verdict |
|---|---|
| live checks run on page load | **KILLED** — `/api/health` reads stored kv rows; no scan runs |
| client-filled panels cause layout shift | **KILLED** — **CLS = 0** on all three passes |
| long tasks make it janky | **KILLED** — **0 ms** of long tasks |
| an auto-refresh loop re-fills panels | **CONFIRMED** — at **+600 s**, on the dot |
| an unbounded telemetry stream rendered raw | **CONFIRMED** |

The page is not slow and it does not jump: FCP **640 ms**, DCL **897 ms**,
CLS **0**. The glitchiness is something else, and the idle pass is where it
shows.

### The actual causes

**a · The page never stops talking to the server.** Sitting idle for sixteen
minutes, untouched:

```
+59s   /api/memory-status          +600s  /api/snapshot  ← the 10-min re-render
+120s  /api/memory-status                 /api/voice-status
+180s  /api/memory-status                 /api/memory-status
…every 60 seconds, forever…       +900s  /api/voice-status + /api/memory-status
```

`edith.js` carries `setInterval(poll, 60000)` against `/api/memory-status` —
**sixty requests an hour per open tab**, on a page that never displays
memory status. `/api/voice-status` polls every five minutes. Neither is
anything the System page asked for; both ride along because the page loads
the whole dashboard bundle.

**b · A ten-minute full re-render.** `dashboard.js` ends with:

```js
setInterval(async () => { const snap = await fetchSnapshot(); if (snap) render(snap); }, 600000);
```

`render(snap)` rebuilds **every panel on the page**. The probe caught it at
**+600 s** exactly. On a page you are reading, the whole thing silently
rewrites itself.

**c · It loads a payload it does not need.** Ten API calls on load, including
`/api/snapshot`, `/api/history?n=14` and `/api/forecast` — the System page
needs health and telemetry and nothing else.

**d · The telemetry section rendered a raw stream.** It printed the last
twelve individual client errors. In the real data that is badly misleading:

> **81 errors in 24 hours — and they are ONE distinct problem.**
> `Uncaught TypeError: Cannot set properties of null (setting 'innerHTML')`
> on unit-econ (35), brief (24), ads & sales (22). Last seen 19.1 hours ago.

That is the defect fixed in #158; the count proves the fix landed. But
rendered as a stream it looked like a dozen separate fires.

---

## 2 · "EDITH IN THE MAIN DASHBOARD" — WHAT EXISTS

| surface | state |
|---|---|
| `/dashboard/api/chat` · `/api/chat-stream` | exist, `@require_auth`, SSE streaming |
| `/dashboard/api/tts` | exists — ElevenLabs proxied server-to-server, key never in the browser |
| STT | Web Speech in `edith.js` |
| thread model | **channel-scoped already** — `memory.start_conversation(channel)`; the Timeline bridge runs `channel="timeline"` with shared memory |
| old landing + area pages | have a chat panel and the HUD |
| **TODAY and SALES** | **no EDITH at all** — zero references |

So there is one brain and one voice pipeline, and the extension point for a
new surface is a **new channel** — exactly what the Timeline bridge already
does. Nothing needs to be built twice.

**The gap**: the pages built in the finish-line wave (TODAY, SALES) carry no
EDITH whatsoever, and `/api/chat-stream` hardcoded
`channel = "voice" if voice else "text"`, so a dashboard surface could not
have its own thread.

---

## 3 · "THE DASHBOARDS NEED ACCURATE, UPDATED DATA" — THE CHAIN

Measured end to end, live:

| link | age | budget | verdict |
|---|---|---|---|
| sheet mirror (tracker, health, payout log…) | **1 min** | 3 min | fine — 90-second loop |
| CRM opportunities | **1–4 min** | 20 min | fine — 15-minute loop |
| Stripe (with the snapshot) | 14 min | 20 min | fine |
| Xero bank/P&L | 18.4 h | 24 h | fine — and never force-pulled |
| CRM contacts + notes | **18 h** | — | incremental; flagged |
| **Meta spend, today** | **18.4 h** | 1 h | **STALE** |
| **Engine blocks the tiles read** | **70 min** | 10 min | **STALE** |

### The two broken links

**a · The engine blocks lag two hours behind a ninety-second mirror.**
`exec:cache:*`, `today:cache:*` and `compass:pulse` rebuild only inside
`_scheduled_refresh_loop`, which is `time.sleep(2 hours)` **first**, work
second. So a tracker edit reaches the mirror in ninety seconds and the tile
up to two hours later. Everything the tiles read is downstream of that one
sleep.

**b · Today's Meta spend never refreshes.** The archive is store-first and
`backfill_history` is idempotent — *"days already archived are never
re-fetched"* — which is right for closed days and wrong for today. Today's
row was captured once and has been served ever since; the probe found it
**18.4 hours old**.

### And neither Refresh button refreshed

- `/api/refresh` → `build_snapshot()` only.
- `/api/resync` → mirrors + `build_snapshot()`.

**Neither touches the caches the tiles actually read.** That is precisely why
pressing refresh appeared to do nothing: the snapshot moved, the tiles did
not.

---

## 4 · WHAT THIS MEANS FOR THE BUILD

- The System page is rebuilt to load from **stored results only** — measured
  at **134 ms** to assemble — with no dashboard bundle, so the memory-status
  and voice-status polls and the ten-minute re-render are gone by
  construction rather than by being switched off.
- Its telemetry section becomes **grouped with counts**; a stream of one
  repeated error is not a picture of anything.
- Freshness gets a **stated contract per source**, an **as-of computed from a
  value's inputs** (never render time), and a **five-minute tick** that
  rebuilds the engine blocks when — and only when — their inputs have moved.
- **Refresh now** pulls what is safe, then rebuilds the blocks. Xero is never
  force-pulled; its refresh token is single-use, so the button says when the
  batched pull is instead.
- EDITH gets a **dock**, owner-only, on every owner page — a new **channel**
  on the existing brain and the existing voice pipeline, loaded after first
  paint inside its own boundary, silent until tapped.
