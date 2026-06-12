# EDITH Voice — Single-Audio-Authority Rebuild Report
2026-06-12 (Sydney)

## Phase 0 diagnosis (what was actually wrong)

**The double-fire mechanism, found exactly:** `browserWake.onresult` fires for
*interim AND final* transcripts — "Hey Edith" matched the wake regex twice.
`wakeFired()` had no idempotency guard, and `bootedThisSession` was set at boot
*start*, so: trigger #1 → full boot (greeting ~3s later, ElevenLabs voice);
trigger #2 milliseconds later → took the "re-wake" path → `speak('Yes, Rydel?')`
immediately, racing the voice-status fetch → browser speechSynthesis → **default
male voice**. Then the boot's real greeting landed → "doubles up saying hello."
Same disease produced the general overlap: 7 independent sound sources
(`new Audio` ×3, speechSynthesis, 6 oscillators, chime, music), **no mixer, no
single owner, no state machine**. Boot SFX played at master volume 1.0 with no
limiter ("far too loud"). The entrance mp3 never played because **it never
reached the server** — Railway deploys from GitHub and the file is (correctly)
gitignored; the only bridge is the authed upload, which hadn't been used.

## The architecture now

```
            ┌─────────────────────────────────────────────┐
            │                audioManager                 │
            │  ONE AudioContext · ONE mixer               │
            │  master ─┬─ voice (1.0) ── fx graph ── out  │
            │          ├─ sfx   (0.25) ── limiter ── out  │
            │          └─ music (0.5)  ─────────────  out │
            └─────────────────────────────────────────────┘
   speak() / playMusic() / reactor() / chime() — nothing else makes sound.

   STATE MACHINE: IDLE → BOOTING → GREETING → LISTENING → THINKING
                  → SPEAKING → (LISTENING | IDLE)
   Wrong-state triggers are ignored and logged. The greeting can only fire
   from BOOTING→GREETING, once. Wake has a 1.5s debounce on top.
```

**The iron rule:** `speak()` increments an utterance token and hard-stops any
current voice first. Stale playback (an interrupted stream, a cancelled
fallback) checks the token and discards itself. One voice at a time — enforced,
not hoped.

**Fallback gating (kills the male voice):** browser speechSynthesis fires ONLY
on confirmed ElevenLabs failure — HTTP/element error, or no first audio byte
within **4s** (watchdog cleared by the `playing` event). If the ElevenLabs
stream arrives after a fallback started, the late stream is paused and
discarded. When fallback does speak: female en-AU/GB voice by name heuristics
(Karen/Catherine/Moira/Serena), never the default, with a visible
"voice fallback (reason)" badge. Unknown voice-status = await the status, never
guess an engine.

**Queue policy:** new reply while SPEAKING = interrupt (stop current, speak
new). No stacking, structurally.

## Effects (Phase 2)

Every voice playback routes through the graph — dry path connects first
(an exception can't mute the voice), and a bypass is **announced** in a note,
never silent. Presets:

| Preset | wet | band | comb | double | reverb |
|---|---|---|---|---|---|
| Subtle (default replies) | 0.15 | 120–8000 | 0.12 | 0.25 | 0.12 |
| Assistant | 0.28 | 140–7200 | 0.18 | 0.35 | 0.16 |
| System (boot/greeting, auto) | 0.45 | 200–5800 | 0.28 | 0.48 | 0.24 |
| Off | 0 | — | — | — | — |

Audition button speaks the test line through current settings; advanced sliders
live-apply; everything persists in localStorage. The orb waveform reads the
**post-effects** voice channel.

## The arc-reactor sound (Phase 3)

Synthesized in Web Audio per spec — no files, royalty-free by construction:
detuned 55Hz sine pair fading in (0.8s) → sawtooth charge 110→880Hz through a
lowpass opening 400→6kHz with slight stereo spread → bandpass noise riser →
harmonic bloom chord (A/C#/E/A) + a soft 1.3→2.6kHz chime as "EDITH — ONLINE"
lands. Plays on the **sfx channel at 0.25 through a 12:1 limiter** — polite by
construction. Wake/ack chimes are the same family, same channel.
**Ducking automation:** voice start → sfx+music ramp down in 150ms; release
400ms after speech ends. Mixer panel (master/voice/sfx/music) persisted.

## Entrance music (Phase 4) — action for Rydel

Your mp3 stays local and gitignored; it reaches the server one way:

1. Dashboard → `?` panel → **Entrance music** → choose your file → **upload**
   (mp3/m4a, ≤15MB, auth-gated, type-validated).
2. **Railway volume (2-minute setup, do this once):** Railway → your service →
   **Volumes** → *New Volume* → mount path `/data`. The upload then survives
   every redeploy. Without a volume the panel will warn "re-upload after each
   deploy" (the status payload flags it).
3. Boot checks the slot: present → plays on the music channel from the wake
   moment, ducks under the greeting, fades out 2s after (or keeps playing via
   the "keep playing after boot" toggle). Absent → synth power-up only — no
   broken player, no default sting.

`ENTRANCE_AUDIO_PATH` env overrides the location if ever needed.

## Boot v2 (Phase 5)

t=0 reactor synth + music + screen dim + orb ignition → t≈0.6 ring sweep +
wireframe grid pass (one canvas layer) → t≈1.0 card cascade, each flashing a
tiny "● ONLINE" tick → t≈1.9 corner brackets + "EDITH — ONLINE" **types on with
a cursor** → t≈2.6 greeting (System preset), music ducks, ambience settles.
Click-skippable; reduced-motion → 400ms fade. Second wake in-session: ack chime
+ "Yes, Rydel?" → LISTENING — no boot replay. Page load gets the silent card
cascade (toggleable).

## Conversational sharpness (Phase 6)

Endpointing preserved exactly (patience 0.8–3.0s × continuation cues × energy
VAD × countdown ring; hold-V deterministic). Barge-in = `stopVoice()` — token
invalidation makes it effectively instant (<50ms of JS, well under the 300ms
budget). Latencies are instrumented in the console (`[EDITH] latency …`) —
read actuals from DevTools during your live test, they depend on your network
+ Anthropic + ElevenLabs. Voice, greeting, and typed chat share one thread —
the "and how does that compare to last month?" follow-up resolves from the
prior turn because it IS the same conversation history.

## Testing matrix status

- Server suite 32/32 green (auth on tts/greeting/entrance-audio upload; weather
  fallback; voice-config; brief honesty; caps) + full 171-test suite unaffected.
- Live-browser items (double-voice ×5, overlap, barge-in, levels, effects
  audition, music upload, boot timings) are **by-ear items** — the six below.

## Six things to verify by ear

1. **"Hey Edith" cold ×5** — exactly one voice, every time, always hers. Watch
   the console: duplicate triggers print `wake debounced` / `transition BLOCKED`
   instead of speaking.
2. **Two rapid questions** — the second cuts the first off mid-word. Never two
   voices at once.
3. **Boot at default mix** — reactor sits politely under the music; her
   greeting ducks both; release after she finishes.
4. **Audition Off → Subtle → Assistant → System** — audible, tasteful steps;
   conversational replies carry Subtle.
5. **Upload your track → "Hey Edith"** — music from t=0, ducked greeting, 2s
   fade-out (or keeps playing with the toggle).
6. **"What's our cash position?" then "how does that compare to last month?"**
   — the follow-up resolves "that" from context, in her voice, with the caption
   matching the dashboard.
