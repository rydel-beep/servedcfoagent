# EDITH Voice Suite — Build Report
2026-06-12 (Sydney) · supersedes the Jarvis voice suite (upgraded in place)

## Architecture: one brain, full-duplex voice

```
"Hey Edith" ── Porcupine WASM (ON-DEVICE — no audio leaves the browser
   │            before the wake word fires)
   ▼
chime → [first wake: BOOT HUD + greeting] → listening
   │
Web Speech API (en-AU, continuous) + CONVERSATIONAL ENDPOINTING:
   adaptive silence window (patience 0.8–3.0s, default 1.4s)
   × linguistic continuation ("…and", "…but", trailing comma → window ×2)
   × energy VAD (resumed speech instantly cancels the countdown)
   → visual contract: amber progress ring fills while EDITH waits
   ▼
EXISTING /dashboard/api/chat (voice: true) — same memory, same metric
   discipline, same engines. EDITH persona in the spoken register.
   ▼
/dashboard/api/tts → ElevenLabs stream (LOCKED voice yj30vwTGJxSHezdAGsv9)
   ▼
AI VOICE CHARACTER (Web Audio, zero added latency):
   bandpass → metallic comb → micro-doubling (LFO chorus ≈8¢) →
   short plate convolver → wet/dry (~85% clean / 15% effect)
   ▼
speakers · orb pulse + waveform strip read the POST-processed signal
   ▼
conversation mode: auto re-listen ~6s · barge-in (speak >300ms → she stops)
   "thanks Edith / that's all / go to sleep" → "Very good, Rydel." → idle
```

## Identity

- EDITH everywhere: page title, wordmark, chat panel, captions, persona prompt.
- **Voice locked:** `yj30vwTGJxSHezdAGsv9` (Rydel's licensed ElevenLabs voice).
  Register tuning: stability 0.55, similarity 0.75 (exposed in the panel).
- No cloning anywhere — character comes from the licensed voice + effects.
- Test line (audition button): *"Good evening, Rydel. EDITH online. Cash
  position is ninety-one thousand dollars; runway three point six months."*

## Wake word status: INTERIM — action for Rydel

`static/wake/hey_edith_wasm.ppn` was **not present** at build time, so the
toggle currently arms Porcupine's built-in **"Jarvis"** keyword (labeled as
interim in the UI). To get "Hey Edith":

1. console.picovoice.ai → Porcupine → **Create Wake Word**
2. Phrase: **"Hey Edith"** (three syllables — more reliable than bare "Edith";
   optionally train "Edith" too)
3. Platform: **Web (WASM)** · Language: English → train → **download the .ppn**
4. Place it at **`served-cfo-agent/dashboard/static/wake/hey_edith_wasm.ppn`**
   and deploy (or drop onto the Railway volume). The code detects the file on
   page load and hot-switches the keyword — no code change needed.

Also requires **`PICOVOICE_ACCESS_KEY`** in Railway env (free at the same
console — note: Picovoice signups now need approval, which can take time).
**Until the key exists, the toggle arms a BROWSER-MODE wake word instead:**
the browser's own speech recognition listens for "Hey Edith" continuously.
Honest trade-off, stated in the UI: browser mode sends audio to the browser's
speech service while armed (it is NOT on-device); it also hands the mic to the
query listener while you're actively talking and re-arms after. The code
auto-upgrades to on-device Porcupine the moment the key is added — no action
needed beyond the env var. Click/hold-V always work regardless.
Note: the Picovoice key is client-side **by design** (WASM init) but is
injected only into the authed dashboard page, never into public static assets.
Blast radius if leaked: someone could burn your free-tier wake-word quota —
no financial data exposure.

- Consent UX: wake word **OFF by default**; enabling requests the mic and shows
  a pulsing green armed dot on the orb; disabling fully releases the mic
  (browser indicator goes dark). Paused when the tab is hidden.

## Endpointing — how EDITH knows you're not finished

Three cooperating signals (Phase 2): the silence timer only starts when the
transcript stops changing AND mic energy drops; a trailing continuation cue
("and", "but", "so", "because", "which", trailing comma…) doubles the wait;
resumed speech energy resets it instantly. The amber ring around the orb IS
the countdown — when it completes, the utterance sends and the orb flips to
thinking. Hold-V/Space bypasses all of it (release = send) for noisy rooms.
**Barge-in:** speaking over EDITH for >300ms (or Esc / orb click) stops her
mid-word and starts listening.

## AI voice character — presets (the "twang")

| Preset | wet | HP/LP | comb | double | reverb | use |
|---|---|---|---|---|---|---|
| Subtle (default) | 0.10 | 110/9000 | 0.08 | 0.18 | 0.08 | conversation |
| Assistant | 0.15 | 120/8000 | 0.12 | 0.25 | 0.12 | conversation, more presence |
| System | 0.28 | 160/6500 | 0.20 | 0.34 | 0.20 | boot + greeting lines (auto) |
| Off | 0 | — | — | — | — | pure ElevenLabs voice |

Per-context rule is automatic: boot/greeting speak through **System**;
replies through your selected preset. A ~80ms bit-crush flicker rides only the
first word of the boot greeting. Master "AI processing" toggle = bypass.
Advanced sliders (HP, LP, resonance, double, reverb, wet) apply to the next
line live and persist in localStorage. **Tune by ear:** open the panel (?),
hit *audition* while flipping presets — Off → Subtle → Assistant → System
should read as a tasteful progression, never "cheap robot." Browser-TTS
fallback bypasses effects (it can't route through Web Audio).

## Voice audition / swap (no redeploy)

Panel → paste any ElevenLabs voice ID → **audition** (test line through
current effects) → **set** (persists server-side in `state/voice_config.json`,
survives restarts) → **reset to default** restores the locked FRIDAY voice.

## Greeting & boot

- `/dashboard/api/greeting` (auth): Sydney time-of-day + **live Newcastle
  weather** (Open-Meteo, free, 15-min server cache, graceful skip on failure)
  + one engine headline (cash + runway) + "What do you need?" — deterministic
  composition, engine values only, honest when red.
- First wake (or the reactor power button): boot HUD — radial ring sweep,
  scanline shimmer, "EDITH — ONLINE", card cascade (60–90ms stagger), orb
  ignition — 2.5–3.5s, click-skippable, `prefers-reduced-motion` → simple fade.
  Optional entrance audio: user slot `static/audio/entrance.mp3` (gitignored),
  royalty-free default sting otherwise; music ducks under the greeting; mic
  auto-opens after.
- Subsequent wakes: chime + "Yes, Rydel?" → listening. Boot is once per session.

## Env vars

| Var | Purpose | Status |
|---|---|---|
| `ELEVENLABS_API_KEY` | TTS (server-side only) | unverifiable from this machine — **verify by ear**; fallback voice = key missing |
| `ELEVENLABS_VOICE_ID` | locked default `yj30vwTGJxSHezdAGsv9` | set |
| `PICOVOICE_ACCESS_KEY` | wake word (client WASM, authed page only) | **add it** (free) |
| `TTS_DAILY_CHAR_CAP` / `TTS_PER_MINUTE_CAP` | cost guards | 60k / 12, intact |

## Fallback chains (all tested)

ElevenLabs → browser speechSynthesis (effects bypassed, noted once) →
text-only. Weather down → greeting skips it. No .ppn → built-in "Jarvis"
interim. No Picovoice key / SDK load failure → click & hold-V. No
SpeechRecognition (Firefox/Safari) → voice-in hidden, speech-out still works.
Anthropic 529 → 3 retries with backoff.

## Tests & non-regression

`tests/test_voice.py` grew to **21 tests** (+9 EDITH: greeting auth, weather
skip/include, Sydney time-of-day, voice-config set/reset/garbage-clamping,
EDITH persona, weather cache). Full suite **171/171 passing**. Engines
untouched; text chat, sliders, roster, exports, PDF, sales-export privacy all
green. Client bundle secrets grep clean.

## Latency

Endpointing adds the patience window by design (default 1.4s of silence — it's
the feature, not lag). TTS path unchanged from v1 (flash model, streaming
GET, progressive playback); the effects graph is real-time Web Audio — zero
added latency. Measure first-word-after-silence on Railway; if >~4s total,
the lever is sentence-chunked TTS.

## Six things to test by ear

1. **"Hey Edith" cold** (after adding the key + .ppn; interim: "Jarvis") —
   boot HUD → greeting with real weather + real cash/runway in the System
   preset → mic opens.
2. **"Show me the funnel and…"** + 2s pause — the ring must reset and WAIT;
   then finish the sentence and watch it send ~1.4s after you stop.
3. **Talk over her** mid-reply — she stops within a beat and listens.
4. **Follow-up with no click** inside the 6s window; then "thanks Edith" →
   "Very good, Rydel."
5. **Audition the presets** Off → Subtle → Assistant → System — progression,
   not robot. Then "AI processing" off = the raw locked voice.
6. **Second wake in-session** — chime + "Yes, Rydel?", no boot replay.
