# EDITH VOICE — RESTORE VERIFICATION (2026-08-10, new key)

## Phase 1 — the new key is LIVE and authenticates
- Env var the code reads: **`ELEVENLABS_API_KEY`** (dashboard/voice.py).
- Running service holds the NEW value: **yes** — length 51, prefix `sk_…`,
  no whitespace, not quote-wrapped. The service **restarted cleanly** on the
  paste (the boot canary re-ran with the new key and flipped health to OK on
  its own — `degraded` was already false before this run's manual canary).
- Probe `GET /v1/user` → **401 `missing_permissions` (user_read)**. This is
  NOT an auth failure — it's a SCOPED key: it authenticates, but the account-
  user endpoint needs `user_read`, which this key intentionally omits. The
  probe endpoint was too privileged; the key itself is valid.

## Phase 2 — the rest of the chain, end to end
- **voices** `GET /v1/voices` → **200**, 22 voices, the locked voice
  **`yj30vwTGJxSHezdAGsv9` PRESENT** ✓ (voices_read scope granted).
- **TTS synthesis** `POST /v1/text-to-speech/yj30vwTGJxSHezdAGsv9/stream`
  with `model_id=eleven_flash_v2_5` + the EDITH voice settings → **200,
  7,777 bytes of valid MP3** (ID3/frame header confirmed) ✓ — real ElevenLabs
  audio in her voice. text_to_speech scope granted.
- **request shape** — unchanged, matches current spec (200 first try).
- **delivery proxy** — intact: `/dashboard/api/tts` streams server-side (key
  never leaves the server), eager first-chunk so failures are JSON 503 not
  mid-stream; the browser fetches same-origin authed audio.
- **live canary** (17:42): `ok=true`, fresh synthesis, health healthy,
  registry `RUNNING`, action-feed item cleared.

**Nothing else was broken behind the key.** No voice_id/model/request/proxy
fix was needed — only the key rotation Rydel performed.

## Finding fixed this run — the SCOPED-KEY class
The 401 `missing_permissions` exposed a classifier gap: the pre-existing code
would have called a permission-scoped 401 an "auth" failure and told Rydel to
ROTATE the key — wrong action for a valid-but-under-scoped key. Added a
**`permission`** class: a `missing_permissions` body classifies as permission
(fix = grant Text-to-Speech / Voices scope, NOT rotate). This matters now that
Rydel uses scoped keys: if a future key omits `text_to_speech`, synthesis dies
with this exact signature and the loud signal now names the right fix.

## Known, accepted limitation (not a bug)
The quota pre-warning (`/v1/user/subscription`) needs `user_read`, which the
scoped key omits — so the "quota at 85%" heads-up won't fire for this key. It
degrades gracefully (swallowed, no false alarm); credit exhaustion is still
caught LOUDLY at synthesis time (a quota/credits body on the TTS call →
`credits` class). To restore the pre-warning, grant the key `user_read` too.

## Voice restored: YES — demonstrated
voice_id **yj30vwTGJxSHezdAGsv9** · played-sample: 7,777-byte MP3 synthesized
live + the 17:42 canary. Rydel's ear is the final close.
