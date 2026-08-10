# EDITH VOICE — DIAGNOSIS (2026-08-10, evidence captured BEFORE any fix)

## The ladder

**L1 · CREDENTIAL — ROOT CAUSE CONFIRMED (live probe, prod runtime):**
- `ELEVENLABS_API_KEY` on the CFO service: PRESENT, 64 chars, prefix `72b…`,
  no whitespace/quote corruption — a **legacy API-key-ID, not an `sk_` API key**.
- Authenticated probe `GET /v1/user` with the loaded key → **HTTP 400**:
  `{"detail":{"type":"authentication_error","code":"invalid_api_key",
  "message":"API key ID used as API key - only valid API keys can be used.
  API keys start with 'sk_' and are shown when the key is created or rotated."}}`
- Same 400 on `/v1/voices`.
- This matches the **2026-08-06 finding already on record** in voice_health.py's
  header — the key rotation it prescribed WAS NEVER DONE. Credits being fresh is
  consistent: the account is fine; the app can't authenticate to it.

**L2 · VOICE ID / MODEL — BLOCKED BEHIND L1** (voices list 400s with the same
auth error). The configured `yj30vwTGJxSHezdAGsv9` + `eleven_flash_v2_5` cannot
be confirmed until a valid key exists; the first canary run after the key is
re-set verifies both implicitly (it synthesizes with exactly these values) and
the new classifier names voice/model failures specifically if they surface.

**L3 · REQUEST CONTRACT — NOT IMPLICATED.** The TTS request shape
(`POST /v1/text-to-speech/{vid}/stream`, xi-api-key header, model_id +
voice_settings body) produces a well-formed auth error, not a contract error.
No endpoint/param drift observed. One REAL defect found here: `stream_tts`
logs the response body but **throws it away** — the raised reason is the
generic "ElevenLabs returned 400", discarding `invalid_api_key`. That's why
every downstream surface said "400" instead of "your key needs rotating."

**L4 · DELIVERY PATH — INTACT.** Server-side proxy (`/dashboard/api/tts`,
key never leaves the server), eager first-chunk pull so failures surface as
JSON 503 not mid-stream, `new Audio(url)` against the same-origin authed
route. No regression.

**L5 · FALLBACK TRIGGER — mapped.** Server: any RuntimeError → 503
`{fallback, reason}` + `voice_health.record_failure`. Client: not-configured /
first-byte timeout / stream error / play-failed each badge + speak a one-time
"Heads up — I'm on the fallback voice" announce. Canary: kv shows it RAN and
FAILED (07:29 today, reason "ElevenLabs returned 400"); health kv shows
fails_today=2, no last_ok ever. **Nothing swallows the error silently** —
the catch classes are correct.

## Why Rydel still discovered it BY EAR (the second bug, precisely)

The 2026-08-06 loudness layer fired for four days, but failed the doctrine on
specificity + persistence + routing:
1. **Unclassified reason** — every surface carried "ElevenLabs returned 400";
   the body that names `invalid_api_key` (an OWNER-ACTION failure) was
   discarded at the throw site. A loud signal that doesn't name the failure
   class or the fix isn't actionably loud.
2. **No persistent indicator** — a 6-second toast + auto-hiding FX badge +
   a once-per-session spoken prefix; between sessions the UI looks healthy.
3. **Not in the action feed** — the one queue Rydel works from never carried
   "EDITH voice down: re-set ELEVENLABS_API_KEY (needs an sk_ key)". It lived
   only in salience greeting lines and the automation registry (pull surfaces).

## Verdict

- ROOT CAUSE (single, confirmed): **stale legacy API-key-ID in
  `ELEVENLABS_API_KEY` on Railway — ElevenLabs requires `sk_`-prefixed keys.**
- **RYDEL ACTION REQUIRED (hard stop honored — no key minted):** in the
  ElevenLabs dashboard → Developers → API Keys → create/rotate a key (starts
  `sk_`) → set it as `ELEVENLABS_API_KEY` on the Railway **CFOagent** service →
  redeploy/restart. The boot canary will then confirm within seconds.
- Agent-side fixes (Phase 2/3, each implicated above): classify failures from
  the response body (auth / voice-id / model / rate-limit / credits / caps /
  delivery) · persistent UI banner while degraded · action-feed item naming
  the exact owner step · boot-time canary (today's first canary ran at 07:29 —
  a deploy-time one closes the gap) · sentinel watch on canary state.
