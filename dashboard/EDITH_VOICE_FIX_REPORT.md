# EDITH Voice — Effects Routing Fix + Character Tuning
2026-06-12 (Sydney)

## Root cause found (Phase 1)

**Not the classic orphaned-graph bypass.** The trace showed routing structurally
intact: per-utterance `createMediaElementSource` on the same element that plays
(fresh element each utterance — the once-per-element rule respected), chain →
voice gain → post-FX analyser → master → destination. The AudioContext is
demonstrably running during sessions — the reactor synth and entrance music
play through the *same* context and mixer.

**The actual cause was calibration + a stale-key trap:**
1. The rebuild's conversational default was `subtle` = **12–15% wet over a
   0.925 dry floor** — perceptually indistinguishable from raw.
2. The rebuild dropped the old `edith` preset key; any browser with
   `edith-fx-preset: 'edith'` persisted in localStorage **silently fell back to
   subtle**. Raw-sounding voice, by configuration.
3. The chain lacked the two ingredients the ear actually reads as "AI":
   **compression** (ultra-even dynamics) and the **high-shelf sheen** (crisp
   digital edge).

Unknown preset keys now resolve to the default ('edith'), never silently down.

## The new signal path (Phase 2/3)

```
TTS element (same-origin stream, MediaElementSource — probe-verified)
 → COMPRESSOR  −28dB · 4:1 · 5ms/150ms        [whole signal — the AI evenness]
 → dry tap ──────────────────────────────────────────────┐
 → HP 140Hz → LP 9kHz                                    │
 → high-shelf +2.5dB @ 6.5kHz                 [the sheen]│
 → comb 5ms (0.15) ─┐                                    │
 → micro-double 14ms, LFO ≈10¢ (0.30) ─┤ wet bus (0.28) ─┼→ voice gain
 → shimmer ring-mod 3kHz (0.03, cap 0.10) ─┤             │     ↓
 → bright plate 100ms (0.14) ─┘                          │ post-FX analyser
                                                          │     ↓
 dry (1 − wet/2) ────────────────────────────────────────┘ master → out
```

| Preset | wet | band | shelf | comb | double | shimmer | reverb | comp |
|---|---|---|---|---|---|---|---|---|
| Off (A/B reference) | 0 | — | — | — | — | — | — | off |
| Subtle (old default, kept) | 0.12 | 120–8000 | +1.5 | 0.12 | 0.25 | 0 | 0.12 | on |
| **EDITH (new default)** | **0.28** | **140–9000** | **+2.5** | **0.15** | **0.30** | **0.03** | **0.14** | **on** |
| System (boot/greeting, auto) | 0.45 | 200–5800 | +3.0 | 0.26 | 0.44 | 0.05 | 0.22 | on |

**Layer A:** ElevenLabs stability raised **0.55 → 0.70** (server default) —
more even, controlled delivery before any FX. Similarity 0.75 unchanged.

## Instruments built in (because "is the filter on?" must never be a mystery)

- **FX badge** near the orb on every utterance: `FX: EDITH` / `SYSTEM` / `OFF`
  / `FALLBACK` / `BYPASS!` — permanent visibility of the path taken.
- **Muffle probe button** (panel): plays a line at 100% wet through a 300Hz
  lowpass — if it doesn't sound underwater, routing is broken. The post-FX
  analyser simultaneously checks the spectral balance and prints
  `MUFFLE PROBE PASS/FAIL` with low/high-band energies. The probe is the
  arbiter; run it once after deploy.
- **A/B button**: raw line → 600ms gap → processed line. Back-to-back is how
  the ear judges.
- **Bypass self-detection**: 1.5s into every ElevenLabs utterance, if the
  element is advancing while the post-FX analyser is silent, it badges
  `BYPASS!` and tells you to report it. Console logs `routing verified` with
  the measured peak on the healthy path.
- `ctx.state` is logged at every routing call (`[EDITH] fx route: edith
  wet=0.28 ctx=running`).

## Latency

Web Audio nodes add zero buffering latency; the streaming MediaElementSource
path is unchanged (no fetch-decode-then-play conversion was needed — the probe
verifies the element path, per the spec's "the probe is the arbiter"). First
audible word budget unchanged.

## What stayed untouched (non-regression)

Entrance music, SFX mix/limiter/ducking, audio authority (one-voice token
rule), state machine, wake word, endpointing, captions. Server suite 32/32;
no engine or endpoint changes beyond the stability default.

## 60-second tune-by-ear guide (Rydel)

1. Hard-refresh → `?` panel → **A/B raw vs fx**. You should clearly hear the
   difference; B is composed, crisp, faintly synthetic.
2. Want **more AI**? Advanced → push **Wet** first (0.28 → 0.35), then
   **Double** (0.30 → 0.40). Want **less**? Same two, downward.
3. Shimmer adds the glassy glint — 0.03 is right; past 0.08 it goes Dalek
   (the slider is capped at 0.10 for that reason).
4. Run **muffle probe** once — expect underwater + "PASS". If it ever says
   FAIL, screenshot the note and tell me.
5. Boot/greeting should sound noticeably heavier than replies — that's the
   System preset doing its per-context job.
