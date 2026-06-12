# Dashboard V2 — Decision Log

## Phase 0: Connection Report
- **GHL and Xero**: env vars only set on Railway, not locally. All development/testing for
  GHL and Xero features will work in production only. Verified locally: Sheets, Stripe MCP.
- **Stripe MCP subscriptions**: Returns 1 active, 1 past_due, 1 cancelled — but MRR is $62k.
  This counts subscription *objects*, not customer subscriptions. Known Stripe MCP limitation.
- **Stripe per-customer data**: Not available. MCP provides aggregate only. Cannot do
  per-client Stripe matching. CLAUDE.md already documents this.

## Phase 1: Client Count Reconciliation
- **Decision**: Active count = 30 (31 Active in sheet - 1 The Advocate confirmed churned)
- **Rationale**: Health tab has 31 "Active" rows. The Advocate is still marked Active in sheet
  but Rydel explicitly confirmed it's churned in prior conversation. All 11 LTC Won deals
  successfully match Health tab clients. No clients are "awaiting Stripe" anymore — all new
  signings are now in the Health tab.
- **The 32 vs 30 gap**: Rydel reported 32; sheet says 31 Active. Possible The Advocate
  was included in Rydel's count, plus The Raama (whose contract ends June 30) may still
  be counted as active despite $0 MRR this month. Our parser correctly includes both
  $0-MRR clients as active with a discrepancy flag.

## Phase 5b: Prepaid Contract Data
- **Finding**: The Health tab (GID 1407663952) now contains Start Date, End Date, Contract
  Value, Service Term, and Monthly Recognized Revenue columns. This is sufficient to build
  the renewal-watch panel without any sheet changes.

## Stage A: Accuracy Lockdown (2026-06-11)
- **Names in snapshot**: Kept roster names in snapshot JSON (the roster editor needs
  them) now that /cfo/snapshot is auth-locked. Agent CLAUDE.md rule amended: real names
  never in UNAUTHENTICATED outputs or history files. History store remains aggregate-only.
- **Consistency gate semantics**: assert_consistency() hard-fails only on internal
  arithmetic contradictions (code bugs). Cross-source disagreements stay degraded[] flags.
  On gate failure during refresh, the app keeps serving the last good snapshot.
- **Stripe MCP days bug**: MCP ignores the days param (always 30d). revenue_previous was
  silently $0 forever; now None + degraded flag. Root fix belongs in served-stripe-mcp repo.
- **$87k vs $62k**: Stripe UI "last 4 weeks" = payouts banked (NET); dashboard card =
  charges collected (GROSS). Both now shown, labeled, with window definitions.
- **Scheduled refresh**: daemon thread every 6h (REFRESH_INTERVAL_HOURS) — snapshot had
  gone 4 days stale with only startup/manual refresh.

## Stage D decisions (2026-06-11)
- **Jarvis streaming deferred**: chat.py calls Anthropic non-streaming via requests; converting
  to SSE is a risky surgery on an auth-gated endpoint under the time cap. Shipped the animated
  typing indicator + smooth autoscroll instead. Streaming is the top Stage-D+1 candidate.
- **Ad-spend slider**: does not exist in the codebase (Stage 0 inventory); the non-regression
  contract lists it but there is nothing to regress. Noted as ABSENT, not broken.
- **Window toggle**: verified purely client-side (precomputed sales.windows[]) — no refetch,
  so toggle latency is render-only (<100ms by construction).

## Voice suite decisions (2026-06-11)
- ELEVENLABS_API_KEY could not be verified locally (railway CLI unlinked). Built with the
  full fallback chain; /api/voice-status reveals configuration post-deploy. If unset, voice
  works on browser TTS until Rydel adds the key.
- TTS playback uses GET /api/tts?text=... so the <audio> element streams progressively
  (instant start) — POST also supported. Auth via the same dashboard cookie.
- Default entrance sting synthesized in-build (pure-Python WAV) = royalty-free by authorship.
  User slot dashboard/static/audio/entrance.mp3 is gitignored; no copyrighted audio bundled.
- TTS caps in-memory (resets on deploy) — acceptable for a cost backstop, documented.
- Stretch items (wake word, conversation mode) deferred per ship-priority.

## EDITH suite decisions (2026-06-12)
- Supersedes voice.js (removed) — edith.js is the single voice client. Internal JS API name
  window.JarvisChat kept (not user-visible) to avoid churn in chat.js consumers.
- No hey_edith_wasm.ppn at build time → interim built-in "Jarvis" keyword, labeled in UI;
  code hot-loads the custom .ppn when present (server flags presence into __EDITH_CFG__).
- PICOVOICE_ACCESS_KEY unverifiable locally (railway CLI unlinked) — wake toggle explains
  itself if absent; click/hold-V unaffected.
- Micro-doubling "detune" implemented as LFO-modulated 14ms delay (chorus ≈8 cents perceived)
  — true pitch-shift needs a worklet; chorus achieves the read at zero latency.
- Greeting is deterministic server composition (engine values + Open-Meteo), not model-written:
  faster, never fabricates, weather skips gracefully.
- Voice audition persists to state/voice_config.json (Railway volume) so a "set" survives
  restarts; empty POST resets to the locked FRIDAY voice.

## Browser-mode wake word (2026-06-12, post-EDITH)
- Picovoice signup now requires approval; Rydel blocked. Added a browser-STT wake fallback:
  continuous SpeechRecognition matching /(hey )?edith|jarvis/ at transcript end. Labeled
  honestly in UI (uses browser speech service, NOT on-device). Auto-prefers Porcupine when
  PICOVOICE_ACCESS_KEY appears. Wake/query listeners share one recognizer — wake pauses
  during active listening and on hidden tabs, resumes after.

## EDITH single-audio-authority rebuild (2026-06-12)
- Phase 0 found: wake double-fire (interim+final transcripts, no idempotency), 7 unowned
  sound sources, no mixer, boot SFX at full scale, mp3 never uploaded to server. Confirmed
  by Rydel before surgery.
- Phases 1-3 are one coherent edith.js rewrite (audioManager + state machine + fx + synth
  can't be split without shipping broken intermediates); committed as one, then P4 server,
  then P5/report — noted as deviation from commit-per-phase.
- Default conversational preset back to Subtle per spec (the earlier 'edith' 52% preset
  removed; System at 45% covers the heavy moments). Rydel can push Subtle's sliders up.
- Re-wake music blast removed per spec (second wake = chime + "Yes, Rydel?" only). Music
  rides the boot; "keep playing after boot" toggle added.
- Default sting deleted: empty slot → synth power-up only (no 404 player errors; client
  checks slot status before attempting playback).
