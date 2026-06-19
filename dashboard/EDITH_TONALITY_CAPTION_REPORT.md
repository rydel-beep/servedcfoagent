# EDITH — Tonality Consistency + Caption/Voice Sync

**Date:** 2026-06-19
**Two issues after the personality/expression + streaming work:**
1. **Caption desync** — the on-screen subtitle didn't match what EDITH was saying (a generic/
   stale "entry" line).
2. **Tonality inconsistency** — improved but sometimes "dragged"/wobbly — the low-stability
   expressive setting overshooting.

**Scope:** `dashboard/static/js/hud.js`, `dashboard/static/js/edith.js`, `dashboard/voice.py`,
`tests/test_voice.py`. No regressions to personality, streaming responsiveness, one-voice rule,
accuracy, memory, layering, Stage-A tests.

---

## Phase 0 — both root causes

### Caption desync (the real bug)
Two caption surfaces exist: the prominent HUD `#eh-cap` and a small `.jarvis-caption`. In the
**streaming** path:
- **HUD `#eh-cap`** typed out `capLine`, but `capLine` was **snapshotted once** at the moment
  `setState('speaking')` fired (`var line = capLine;` in `hud.js`). That fires on the *first
  chunk transition* — **before any chunk text exists** — so it typed whatever was stale (the
  greeting / previous reply = the "entry subtitle"), and **never advanced** as chunks streamed
  (`setCaption` only stored the string; the typing loop had already captured the old one).
- **`.jarvis-caption`** was set to `''` in `beginSpeakStream()` and **never repopulated** per
  chunk → blank during streamed replies.

So the caption was sourced from a **stale snapshot**, not the live streamed chunk text.

### Tonality
`active_voice_settings()` returns **one fixed profile** — it does **not** vary per utterance/mood,
so there was no backend param churn (that hypothesis didn't apply). The "drag/wobble" was
**stability 0.40 overshooting**: too low → warped/over-emoted prosody on some replies, and
inconsistency turn-to-turn. Conversational units are already sentence/clause-chunked (tight), so
long-sentence drag was limited to the non-streamed single-shot path (brief/greeting).

---

## Phase 1 — caption/voice sync (single source of truth, per-chunk reveal)

The caption now renders the **exact streamed text sent to TTS**, advancing with playback:

- **Single source:** in `_pumpStream`, the chunk `text` that builds the `/api/tts` URL is the
  same `text` dispatched to the caption — they cannot diverge.
- **Per-chunk reveal, synced to playback:** the caption is dispatched on each chunk's **`playing`**
  event (not at synthesis/creation), so the words appear as that chunk becomes **audible**. New
  event `edith:caption {text}`; the HUD types it out (replace + typewriter). When the next chunk
  plays, the caption advances to it.
- **No more snapshot / entry subtitle:** `hud.js` caption is now a live typewriter over a target
  string (`capSet`/`capClear`) driven by `edith:caption` — the stale `capLine` snapshot is gone.
  `setState('speaking')` no longer types anything; every other state clears the caption.
- **Single-shot replies** (greeting / brief / audition via `speak()`): dispatch `edith:caption`
  with the full line on `playing`, so those captions match too.
- **Barge-in / flush:** `stopVoice()` clears the local caption and dispatches `edith:caption {''}`
  → HUD clears — no orphaned text from a flushed reply.
- **Chat bubble unchanged:** the complete reply still lands in the chat thread (the record); the
  caption is the live overlay. They agree because both come from the same streamed text.

**Validated (Node, DOM-free):** simulating the per-chunk pipeline, each shown caption equals the
spoken chunk, and a barge clears the caption.

---

## Phase 2 — tonality (stable but still alive)

| Setting | Before | After | Why |
|---|---|---|---|
| stability | 0.40 | **0.50** (`TTS_STABILITY`) | stable-but-alive band — carries tone yet consistent turn-to-turn; 0.40 dragged/wobbled |
| style | 0.35 | **0.30** (`TTS_STYLE`) | a touch tamer so it doesn't over-emote at the higher stability |
| similarity / speed / boost | — | 0.75 / 0.95 / on | unchanged |

- **No per-utterance churn:** confirmed the profile is **one fixed set** for all conversational
  replies (a regression test asserts `active_voice_settings()` is identical call-to-call).
  Personality comes from **word choice** (the prompt) + the expressive model, **not** from
  swinging voice params per message.
- **Chunking tames drag:** the streaming path already synthesises sentence/clause-sized units,
  so pacing stays tight.
- **EDITH effects chain** unchanged — the effect rides the livelier-but-stable raw voice (re-check
  the wet mix by ear; adjustable in the panel).
- **Panel A/B:** "A/B composed vs expressive" now plays the same line at **0.40 vs 0.50** so Rydel
  locks the consistent value by ear; the Expression/Style sliders persist the choice.

---

## Guardrails / non-regression

- **Personality/warmth** untouched (it lives in word choice, not voice params).
- **Streaming responsiveness** unchanged — the caption rides existing playback events, no extra
  calls or latency.
- **One-voice rule / barge-in** intact — caption clears with the audio.
- **Accuracy, memory, layering** untouched. Tests: **188 pass** (+1 new one-fixed-profile test);
  the lone failure (`test_pdf_reads_cash_position_fields`) is pre-existing and unrelated.

## Live verification (deployed)

- **Voice settings live:** `stability 0.50, style 0.30, similarity 0.75, speaker_boost on,
  speed 0.95` — confirmed via `/api/voice-status`.
- **Caption source = TTS source:** the streamed reply (e.g. "You've got a hundred and forty
  thousand in the bank, plus eighteen thousand in transit from Stripe — so about a hundred and
  fifty-eight thousand all up…") is the exact text the frontend uses to build each `/api/tts`
  chunk **and** to dispatch `edith:caption` — one variable, both paths, so they can't diverge.
  Accuracy intact ($140k + $18k = $158k; burn ~$39.5k).


## Follow-ups

- The **eye test** (does the on-screen caption visibly track the spoken words; does 0.50 sound
  consistent yet alive) is Rydel's in the browser — the caption is client-rendered. The
  single-source wiring is structurally guaranteed (same `text` → TTS and caption) and validated
  in Node; the deployed voice settings are verified below.
- Lock the stability by ear with the panel **A/B (0.40 vs 0.50)** and the Expression slider if you
  want a different point in the band.
