# Jarvis Voice Suite — Build Report
2026-06-11 (Sydney)

## Architecture: one brain, two mouths

Voice is strictly an I/O layer on the existing Jarvis. Nothing was duplicated:

```
Rydel speaks ──> Web Speech API (browser, free, en-AU)
                      │ final transcript
                      ▼
        EXISTING /dashboard/api/chat  (voice: true)
        — same conversation memory, same metric definitions,
          same answer discipline, same engine-backed snapshot —
                      │ reply text (spoken register)
                      ▼
        /dashboard/api/tts ──> ElevenLabs streaming (server-proxied)
                      │ mp3 stream            │ on any failure
                      ▼                       ▼
            <audio> progressive play   browser speechSynthesis
                                              │ on that failing too
                                              ▼
                                        text-only + note
```

Voice and typed chat share ONE thread (`conversationHistory` in chat.js, exposed
via `window.JarvisChat.ask`). Every spoken reply also renders in the chat panel
as a caption/record.

`voice: true` appends a VOICE ADDENDUM to the existing system prompt: spoken
register, numbers written for the ear, ≤4 sentences, Jarvis persona — with the
explicit rule that persona never softens accuracy.

## Endpoints (all behind dashboard auth — they spend API money)

| Endpoint | What |
|---|---|
| `POST/GET /dashboard/api/tts` | ElevenLabs streaming proxy. GET enables progressive `<audio>` playback (first audible word fast). On failure: `503 {fallback: true, reason}` — client drops to browser TTS. |
| `POST /dashboard/api/brief` | Composes the 45–75s daily brief from the engines (cash/runway/burn, MRR trajectory, movers from history_store, binding constraint, focus, renewal watch). Model-written in the voice register; deterministic template fallback when the model is unavailable — numbers identical either way. |
| `GET /dashboard/api/voice-status` | `elevenlabs_configured`, voice ID, usage vs caps. No key material. |

## Env vars (server-side only; never in client JS — grep verified)

- `ELEVENLABS_API_KEY` — **required for the FRIDAY voice.** If absent the suite
  still works on browser TTS with a one-line "fallback voice" note.
- `ELEVENLABS_VOICE_ID` — default `yj30vwTGJxSHezdAGsv9` (Rydel's FRIDAY voice).
- `ELEVENLABS_MODEL` — default `eleven_flash_v2_5` (low latency).
- `TTS_DAILY_CHAR_CAP` (default 60,000), `TTS_PER_MINUTE_CAP` (default 12),
  `TTS_MAX_CHARS_PER_REQUEST` (default 2,400) — cost guards, logged on each call.

## Controls

- **Click the orb** (bottom-right) to talk; click again to stop. **Hold V** (or
  Space outside inputs) for walkie-talkie push-to-talk. **Esc** interrupts Jarvis
  mid-speech instantly (so does clicking the orb). **B** = daily brief.
  **?** = help overlay with mute/volume (persisted in localStorage) and the
  entrance-invitation toggle.
- Orb states: idle breathing glow → LISTENING (ring driven by live mic level via
  Web Audio analyser) → THINKING (orbital spin) → SPEAKING (pulse). Captions show
  what it heard and what it's saying. Mic-denied, no-speech, TTS-fallback and
  endpoint errors each surface a calm one-liner — never a silent dead orb.
- Feature detection: no SpeechRecognition (Firefox/Safari) → voice-in hidden with
  a note; Jarvis can still *speak* replies typed in chat. Chrome desktop is the
  flagship; Chrome Android works via tap-to-talk.

## The entrance sequence (click-triggered = autoplay-compliant)

Click the **reactor dot** (top-left, next to JARVIS):
1. **Entrance audio** plays from the user slot if present, else the default sting.
2. **Boot animation**: panels ignite in sequence (~2.5s), skippable by click,
   skipped entirely under `prefers-reduced-motion`.
3. Music **ducks**, Jarvis greets: "Good evening, Rydel. Systems online. Cash …,
   runway … Want the full brief?" — saying "yes" (or clicking Brief) runs the brief.

### 🎵 Your entrance-audio slot (read this, Rydel)
- Drop your own legally-obtained track at:
  **`served-cfo-agent/dashboard/static/audio/entrance.mp3`**
- That exact path is **gitignored** (confirmed: `.gitignore` line
  `dashboard/static/audio/entrance.mp3`) — your file stays on the machine/volume
  and never enters the repo. Upload it to Railway via a volume or keep it local.
- When the slot is empty, the shipped **royalty-free default sting** plays
  (`entrance-default.wav` — synthesized power-up sweep, authored in this build,
  no copyright). The build downloads/bundles **no** copyrighted music.
- Note: files under `/dashboard/static/` are served without auth (standard
  static). The slot holds a song, not financial data — acceptable; avoid putting
  anything sensitive there.
- The invitation pulse on page load is **off by default**; enable it in the `?`
  overlay. The sequence itself only ever triggers on click.

## Cost & security posture

- TTS spend is bounded: per-request char clamp → per-minute cap → daily char cap
  (Sydney-midnight reset), all env-tunable, usage visible at `/api/voice-status`.
- Anthropic chat path reuses the existing 30-messages/hour rate limit and now
  retries up to 3× on 529/overloaded with backoff.
- Unauthenticated `tts`/`brief`/`voice-status` → 302 to login (tested).
- Client bundle grep: no `sk-ant`, no `xi-api-key`, no env names. CLEAN.

## Test coverage

`tests/test_voice.py` — 12 tests: auth rejection on all three endpoints; fallback
JSON when ElevenLabs is unconfigured; voice-status reports config without key
material; daily-cap and per-minute-cap blocking; oversize-text bounding; voice
addendum keeps the discipline prompt; voice flag works without crashing when the
model key is absent; template brief is honest ("churn cliff"), speech-clean (no
markdown), engine-exact, and in the 45–75s word band; brief endpoint contract.
Full suite: **162/162 passing.** Sales-export privacy and all Stage-A
displayed-output tests still green; engines untouched.

## Latency

- Architecture targets: ElevenLabs `eleven_flash_v2_5` + `optimize_streaming_latency=3`
  + progressive `<audio>` GET playback — synthesis starts streaming before the
  full clip exists. First audible word is bounded by chat reply time + ~0.5–1s
  synthesis lead. **Measure by ear on Railway** (local has no ElevenLabs key);
  if first-word latency exceeds ~1.5s after reply text, the next lever is
  sentence-chunked TTS (speak sentence 1 while 2 synthesizes).

## Five things to test by ear

1. Click the orb, ask **"what's our cash position?"** — the spoken number must
   match the cash card exactly, first word within ~4s of finishing speaking.
2. Press **B** — a 45–75 second brief that tells the truth about the churn cliff.
3. **Interrupt it** mid-sentence with Esc — it must stop instantly.
4. Click the **reactor** — sting, ignition sweep, ducked music, greeting, brief offer.
5. In the `?` overlay, mute → ask again — captions still carry the full answer.

## Deferred (stretch, intentionally unbuilt)

Wake-word ("Hey Jarvis" via Porcupine — needs a Picovoice key + always-on-mic
consent UX) and auto re-listen conversation mode. Both slot cleanly behind
`startListening()` when wanted.
