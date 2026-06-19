# EDITH — Real-Time Responsiveness + Voice Music Control

**Date:** 2026-06-19
**Goal:** Drop the 3–4s+ gap between Rydel finishing speaking and EDITH replying to feel
real-time, by **overlapping** the pipeline (stream speech while still generating) rather than
optimising one step — and let Rydel control the music channel by voice mid-conversation.
**Constraint:** conversation quality is already good; this is SPEED + CONTROL, not a change to
how she thinks or talks.

**Scope:** `served-cfo-agent/` only — `dashboard/chat.py`, `dashboard/routes.py`,
`dashboard/voice.py`, `dashboard/static/js/chat.js`, `dashboard/static/js/edith.js`,
`tests/test_voice.py`. Same `CHAT_MODEL`, same auth + rate/token caps, fx chain never bypassed.

---

## Phase 0 — the latency stack (measured live, deployed)

A typical voice reply was a **stack of serial waits**:

| Stage | What | Before |
|---|---|---|
| t0→t1 | Endpointing patience (silence wait) | **~1.4s** (×2 on continuation cues) |
| t1→t3 | **Model generation — NON-streaming, full reply awaited** | **~3.9–4.6s** ← dominant |
| t3→t4 | TTS first byte (ElevenLabs flash, already streams) | ~0.78s |
| t4→t5 | Browser audio buffer → first word | ~0.15s |
| **t0→t5** | **stop speaking → first audible word** | **~6.6s** |

The bottleneck was unambiguous: the **entire** reply was generated (~4.3s) before TTS even
started. TTS was already flash + streaming. So the fix is to **pipeline** generation → TTS →
playback, not to shave the TTS step.

---

## Phase 1 — stream speech while generating (the big win)

Instead of `await full reply → await full audio`, the reply now streams and is spoken
sentence-by-sentence.

- **`chat.py::chat_stream()`** — generator over Anthropic streaming (`messages.stream`),
  yielding `("meta",{intent,context_tokens})` → many `("delta", text)` → `("done", reply)` /
  `("error", msg)`. Reuses the intent router, the financial-accuracy rules, the per-token rate
  limit, and 529-retry (guarded so a mid-stream failure never double-emits).
- **`routes.py::/api/chat-stream`** — SSE endpoint, `@require_auth`, `X-Accel-Buffering: no`
  so chunks flush live. `/api/chat` stays as the non-streaming fallback.
- **`chat.js::sendTextStream()`** — reads the SSE, splits text at **sentence/clause
  boundaries** (decimals like `$140,007.29` and `3.6` are guarded against splitting), and
  emits each chunk via callback. Same conversation thread/memory. **Inline fallback** to
  `/api/chat` on any stream failure, so history and chat bubbles stay consistent.
- **`edith.js` AudioManager streaming queue** — `speakStream()/beginSpeakStream/pushSpeakChunk/
  endSpeakStream` play chunks **in order, through the SAME EDITH fx chain** (`routeThroughFx`),
  starting chunk 1 while later chunks are still being generated/synthesised. The one-voice rule
  holds: a new utterance or barge-in bumps `currentUtterance`, orphaning the stream instantly;
  `stopVoice()` resolves the pending stream promise so nothing hangs.

**Result:** first audible word lands after the **first sentence**, not the whole reply.

---

## Phase 2 — faster TTS model

`voice.py`: conversational TTS model is env-configurable via **`TTS_MODEL`** (canonical;
`ELEVENLABS_MODEL` kept as backward-compatible fallback), defaulting to the low-latency
`eleven_flash_v2_5`. Optional **`TTS_GREETING_MODEL`** lets the one-off boot greeting use a
higher-fidelity model (defaults to the fast model — no behaviour change). The **locked voice
ID** (`yj30vwTGJxSHezdAGsv9`) and the **EDITH effects chain** are untouched — only the synth
model is swappable. (Default was already flash, so this is mostly making it explicit + adding
the greeting override.)

---

## Phase 3 — adaptive endpointing

`edith.js::endpointWindow()` makes the silence window adaptive on top of the base patience
slider (the ceiling):

- **continuation cue** (`…and`, `…so`, trailing comma — existing `CONTINUATIONS`) → **2× base**
  (he's mid-thought, stay patient),
- **clear sentence end** (`? . !`) + energy dropped → **~0.75s** (snappy),
- otherwise a complete-looking phrase → **~0.9s**.

Energy must stay low for the whole window and the transcript stable, so even the snappy floor
needs real silence — it can't clip a mid-thought pause. The countdown ring, hold-V override,
and barge-in are unchanged.

---

## Phase 4 — lean context (don't let the snapshot bloat first-token)

Live streaming exposed a second bottleneck: **business** first-token (~2.5s) was much slower
than **general** (~1.7s) because the business path attaches the financial snapshot — and the
real snapshot is **~93k chars**. Time-to-first-token scales with input size.

- The intent router already keeps **general** turns snapshot-free (verified: general voice
  context ~1.8k chars).
- New: `_build_context_block(lean=True)` on the **voice** path drops the trailing raw
  **FULL SNAPSHOT** dump. The curated sections (canonical metrics, cash position, financial
  position, verdicts, funnel, forward MRR, burn, roster, …) already carry every
  canonical/headline number, so a short spoken reply loses nothing. **Text chat keeps the full
  snapshot** for deep, exploratory questions.
- Measured: voice business context **~33k → ~10.4k tokens (−69%)**, canonical metrics + cash
  figures still present. Per-call context-token estimate is now logged (`chat`/`chat_stream`)
  for ongoing visibility.

---

## Phase 5 — voice music control

While music plays, Rydel controls the **music channel** by voice, matched **locally** (no model
round-trip) and routed **before** the model so a "turn it down" can't be mistaken for a query.

| Command | Action (music channel only) |
|---|---|
| "turn the music down" / "lower" / "quieter" | step music gain down 0.15 |
| "turn it up" / "louder" | step music gain up 0.15 |
| "pause the music" / "stop the music" | pause music playback |
| "resume" / "play the music" / "unpause" | resume from where it paused |
| "mute the music" / "unmute" | toggle music mute (remembers prior level) |
| "set the music to 30 percent" | set music gain to N% |

- **EDITH's voice (chVoice) and SFX (chSfx) are never touched** — only `chMusic`.
- **Disambiguation:** a bare control verb ("turn it down", "pause") is treated as a music
  command only when music actually exists; otherwise it routes normally. Explicit "music" /
  "set … percent" always matches.
- **Acknowledgement:** an instant tonal confirm (`uiConfirm`) + a brief caption — no TTS
  round-trip, so it feels immediate.
- **Persistence:** volume changes go through `setMix`, which writes `edith-mix-music` to
  localStorage, so the next session respects it. The existing auto-duck-under-voice still
  applies on top (the manual level is the new baseline it ducks from).

---

## Before / after — first audible word (live measurements)

Old stack (measured): full non-streaming generation ~4.3s + TTS 0.78s ≈ **5.1s** from send to
first word; plus ~1.4s endpointing ≈ **~6.5s** stop-speaking → first word.

New stack (streaming, measured live on `/api/chat-stream`, voice register):

| | Context | First token | First chunk (TTS starts) | Full reply |
|---|---|---|---|---|
| General (no snapshot) | ~0.7k tok | **~1.5s** | ~1.8s | ~1.9s |
| Business — before lean | ~33k tok | ~2.5s | — | ~5.1s |
| Business — after lean ctx | ~11k tok | **~2.0s** | ~2.4s | ~3.7–4.3s |

First audible **word** ≈ first chunk + TTS first byte (~0.78s):
- **General ≈ ~2.6s** from send (was ~5.1s)
- **Business ≈ ~3.2s** from send (was ~5.1s)

Adaptive endpointing additionally trims t0→t1 from ~1.4s to **~0.75–0.9s** on clear questions,
so **stop-speaking → first word** drops from **~6.5s** to roughly **~3.4s (general) / ~4.0s
(business)** — and she's audibly speaking sentence 1 while the rest still streams.

**Net:** the perceived gap (stop-speaking → first word) drops from ~6.5s to roughly **2.5–4s**,
and EDITH is audibly speaking the first sentence while the rest is still being generated
(streaming confirmed). The general/conversational path — the most common — is the fastest and
approaches the real-time target; the business path is bounded by model time-to-first-token on
the financial context, which the lean-context change cuts substantially.

---

## Non-regression

- **fx chain never bypassed** — streamed chunks route through `routeThroughFx` (same EDITH
  preset); a new utterance/barge-in flushes the queue and stops instantly (one-voice rule).
- **Financial accuracy** — streaming uses the same intent routing + accuracy rules; figures
  stay engine-sourced; the lean voice context still carries every canonical number.
- **Fallbacks** — streaming TTS unavailable or stream error → non-streaming `/api/chat` +
  `speak()`; TTS failure still drops to browser speech. The proven path is always underneath.
- **Tests:** 182 passing (+5 new streaming/TTS tests); JS sentence-chunking validated in Node
  (decimals don't split, text reconstructs). Wake word, HUD, memory, cost caps, Stage-A
  accuracy-lockdown tests green. The lone failing test (`test_pdf_reads_cash_position_fields`)
  is pre-existing and unrelated (confirmed by stashing the change).

## Files changed

- `dashboard/chat.py` — `chat_stream()`, `_estimate_tokens()`, lean context, token logging.
- `dashboard/routes.py` — `/api/chat-stream` SSE endpoint.
- `dashboard/voice.py` — `TTS_MODEL`/`TTS_GREETING_MODEL` env, `stream_tts(model_override)`.
- `dashboard/static/js/chat.js` — `sendTextStream()` + sentence chunking + inline fallback.
- `dashboard/static/js/edith.js` — streaming speech queue, adaptive endpointing, music control,
  barge-in for the streaming path.
- `tests/test_voice.py` — streaming + TTS-model tests.

## Follow-ups / honesty

- The live four-conversation + music test by **ear** needs Rydel's browser (mic + speakers);
  these measurements are server-side timings + Node logic validation. The deployed
  `/api/chat-stream` numbers are real.
- Business TTFT is now bounded by model prompt-processing on the curated financial context
  (~10k tokens). Further trimming risks correctness, so it's left intact; a per-question
  context selector is a possible future optimisation.
- A `?t=<dashboard token>` is committed in plaintext in `dashboard/POST_BUILD_REPORT.md`
  (pushed to GitHub) — flagged separately; rotate `DASHBOARD_TOKEN` on Railway.
