# EDITH — Audio Integrity Fix

**Date:** 2026-06-19
**Three audio bugs, mostly introduced/worsened by the streaming + adaptive-endpointing work:**
1. **Crackle / "poor signal" that worsens over time** — progressive degradation.
2. **Cuts itself off mid-sentence.**
3. **Prematurely finishes listening** while Rydel is still talking.

**Scope:** `dashboard/static/js/edith.js` only. Locked voice ID + EDITH effects chain intact.

---

## Phase 0 — all three root causes

**1. Crackle = audio NODE LEAK.** `routeThroughFx` built a **full node graph per chunk and per
utterance** — compressor, 3 biquad filters, 2 delays, a convolver (fresh impulse buffer),
comb/double/shimmer/reverb gains, **and oscillators (`lfo`, `shimOsc`) that call `.start()`** —
and **nothing was ever disconnected or stopped**. Each `<audio>` element's `MediaElementSource`
stayed wired into `chVoice` forever. Over a session, **dozens–hundreds of running oscillators +
nodes accumulated** → CPU climbs → the audio thread underruns → crackle that compounds the longer
the session runs. The `AudioContext` itself was already a single persistent one (good); the leak
was per-utterance nodes never released.

**2. Self-cutoff = no-lookahead chunk scheduling.** `_pumpStream` created chunk N+1's `<audio>`
(a fresh `/api/tts` fetch + synthesis) **only on chunk N's `ended` event** → a TTS-first-byte
**gap (~0.5–0.8s) at every seam**, and on `error` it **silently skipped** a sentence. **Stop-
trigger audit:** every `stopVoice`/`stopAll` caller is user-initiated (orb click, Esc, sustained
barge-in >600ms) or post-completion (`afterReply` runs after `await stream.promise`) — **no
spurious mid-playback stop**. The cutoff was the seam gap, not a rogue stop.

**3. Premature endpointing = window too eager + VAD gate too high.** Interim ASR rarely emits
punctuation, so almost every utterance hit the `Math.min(base, 900)` "complete-looking" branch →
fired at **900ms** of silence (too short for a mid-thought pause). The energy-VAD reset worked but
its threshold (`micRMS() > 0.055`) was **too high** — soft/resumed speech didn't exceed it, so the
silence timer wasn't reset and it fired mid-thought.

---

## Phase 1 — audio lifecycle (kill the progressive crackle)

- **Per-utterance teardown:** `routeThroughFx` now tracks **every** node (`N()`) and oscillator
  (`O()`) it creates and attaches `el._fxTeardown`. On a chunk/utterance finishing (`ended`,
  `error`, or any stop), teardown **declick-ramps the mix gains** to silence (~8ms), then (after
  the ramp) **stops the oscillators and disconnects every node**, so the element + graph are GC'd.
  Wired into the streaming queue (`_tearDownEl` on chunk end/stop), `_finishStream`, `stopVoice`,
  and single-shot `speak()`'s `done`.
- **Output peak limiter:** a `DynamicsCompressor` limiter (threshold −3 dB, ratio 20:1) built
  **once** on the voice bus (`chVoice → voiceLimiter → analyser → master`), so the wet chain
  (dry+comb+double+shimmer+reverb summed) can never clip-crackle regardless of preset.
- **One persistent `AudioContext`** — unchanged; never per-utterance.
- **Proof (Node sim):** 200 chunks through the track/teardown pattern → **0 live nodes, 0 running
  oscillators** afterwards (vs. ~3,600 leaked nodes + ~400 running oscillators before). A 30-min
  session now sounds like minute one.

---

## Phase 2 — gapless chunk playback (stop the self-cutoff)

- **One-ahead lookahead/prefetch:** the **next** chunk's `<audio>` is created + FX-routed and
  starts **buffering while the current chunk is still speaking** — warmed the moment it arrives
  (`_maybePrefetch` on `pushSpeakChunk`) or as soon as the current starts (inline). On the seam,
  the prefetched, already-buffered chunk plays immediately → no TTS-first-byte gap. (Verified in a
  Node state-machine sim: each chunk is prefetched before it's played; play order preserved.)
- **Clean hold, never abandon:** if generation lags (queue empty, stream still open), `_pumpStream`
  simply **waits** — `streamPlaying` goes false and the next `pushSpeakChunk` resumes it. The
  sentence is never ended early.
- **Retry-not-skip:** a transient chunk error now **retries once** (fresh `/api/tts`) before
  giving up, instead of silently dropping the sentence.
- **Tightened stop logic:** audited every stop call — all are real interrupts (orb click, Esc,
  sustained barge-in) or post-completion. A routine state/UI change does not kill active speech.
  Barge-in still flushes + stops instantly (and tears down the prefetched chunk too).

---

## Phase 3 — endpointing recalibration (stop cutting Rydel off)

Biased back toward patience without losing snappiness on a clear end:

| Case | Before | After |
|---|---|---|
| base patience (default) | 1.4s | **1.5s** |
| continuation cue (`…and`, filler, comma) | 2× base | **1.8× base** (~2.7s) |
| confident clear end (`? . !`, no continuation) | min(base, 0.75s) | **~1.0s** |
| un-punctuated stop ("looks complete") | min(base, **0.9s**) ← too eager | **full base (~1.5s)** |
| energy-VAD reset threshold | `micRMS > 0.055` | **`> 0.035`** (soft/resumed speech resets the timer) |

- Fast-fire (~1.0s) only on a **punctuated** end, since interim ASR rarely punctuates — an
  un-punctuated stop is treated as possibly-mid-thought and gets the full window.
- **Continuation list expanded** with fillers (`um/uh/er/ah/hmm`), conjunctions, articles,
  prepositions, and mid-thought verbs/pronouns (`is/are/we/i/want/need/going/think/about/…`) +
  trailing comma/dash — so a breath after these holds, doesn't fire.
- **Energy-VAD** lowered so resumed/soft speech reliably **resets** the silence timer (the prime
  cause of premature send).
- **Countdown ring** and **hold-V** unchanged (hold-V bypasses endpointing entirely — the
  guaranteed "don't cut me off" mode).
- **Sim:** "our runway is" → 2700ms (patient), "what's our cash position" → 1500ms (full),
  "...position?" → 1000ms (snappy), continuations → 2700ms.

---

## Guardrails / non-regression

- **Responsiveness:** prefetch keeps the first word fast (it doesn't delay chunk 1; it warms
  chunk 2). Personality, caption sync (per-chunk reveal), one-voice/barge-in — all preserved.
- **Accuracy, memory, layering, Stage-A tests:** untouched. **188 tests pass**; the lone failure
  (`test_pdf_reads_cash_position_fields`) is pre-existing and unrelated.
- Validations: teardown flat-node-count sim, prefetch order sim, endpointing window sim — all green.

## Live verification (deployed)

- Health `200`; the deployed `dashboard/static/js/edith.js` carries all three fixes (teardown,
  prefetch/`streamNextEl`/`_maybePrefetch`, `voiceLimiter`, `VAD_RESUME_RMS` all present — 20
  marker hits). Asset is cache-busted per commit, so browsers load the new build.
- Logic validations (Node, DOM-free): teardown → 0 leaked nodes/oscillators over 200 chunks;
  prefetch → each chunk buffered before played, order preserved; endpointing window → patient on
  mid-thought, ~1.0s on a punctuated end.


## Follow-ups

- The **ear test** (long session stays clean; multi-sentence replies play gaplessly; mid-thought
  pause doesn't send early) is Rydel's in the browser — these are client-side audio behaviours.
  The lifecycle/scheduling/endpointing logic is validated in Node and the asset is deployed.
- Further gold-standard for seams would be AudioContext-timeline scheduling via decoded
  `AudioBufferSourceNode`s (sample-accurate, crossfaded); prefetch + teardown resolves the
  reported symptoms at far lower regression risk and is the right first move.
