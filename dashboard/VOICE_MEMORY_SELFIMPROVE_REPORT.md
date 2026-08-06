# Voice Restoration + Memory Maintenance + the Conversation Self-Improvement Loop

## PHASE 0 — THE THREE DIAGNOSES (2026-08-06)

### A · THE VOICE TRACE — root cause exact, Rydel account action required
End-to-end call from the server's own credentials:
```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream
→ 400 {"detail":{"type":"authentication_error","code":"invalid_api_key",
   "message":"API key must start with 'sk_'.","status":"invalid_api_key_prefix"}}
```
The Railway `ELEVENLABS_API_KEY` is a **legacy 64-char key**; ElevenLabs now rejects
any key not starting with `sk_` — every synthesis fails, the browser robot voice
plays silently. Not quota, not outage, not our pipeline (settings/chunker/normalizer
untouched and unregressed). Break timing: provider-side key-format enforcement, not
a deploy of ours.

**RYDEL'S STEPS (the only human action in this build):**
1. elevenlabs.io → Profile → API Keys → create a new key (it starts `sk_`).
2. Railway → project athletic-gratitude → service CFOagent → Variables →
   replace `ELEVENLABS_API_KEY` → redeploy happens automatically.
3. Say anything to EDITH — her real voice returns; the canary flips RUNNING.

### B · THE PILOT-VENUE TRACE — classified: PURE LOOP-RESOLUTION-MISS
- The fact EXISTS and recall works: memory_facts **#169** [decision], active,
  weight 2.5, **inside the top-60 AND inside the char budget**: "The pilot venue
  for the reservations platform is Chiangmai Thai, starting mid-September."
  (2026-08-03; she even answered a quiz on it correctly two minutes after storing.)
- The question came from **open-loop #5** — a reminder Rydel himself created
  (2026-08-03, phrased as the question). The loop engine had NO resolution
  detection: `resolve()` existed but nothing ever called it from conversation;
  only "drop it" could kill a reminder. So the loop re-fired every 3 days forever,
  regardless of what memory knew. **Not memory-loss, not recall-miss.**
- Same class found live: loop #2 "reconnect Xero this week" (Xero is alive —
  the stale action item traced in the triage build IS this loop).

### C · MEMORY-STORE HEALTH (before maintenance)
| metric | value |
|---|---|
| facts total / active | 176 / 175 |
| decay ever run | **NO** (0 facts with weight < 1 — the D3 debt confirmed) |
| top-60 render vs 6,000-char fact budget | **7,034 chars — INVARIANT BROKEN** (9 facts silently trimmed per turn) |
| active facts beyond the top-60 window | 115 |
| near-dup active pairs (sim ≥ 0.55) | 12 (e.g. the two Chloie-salary facts — a real contradiction pair) |
| growth | bursty: 96 facts in one week (2026-06-29) |

## THE BUILD (DECISIONS #124)

### D1 · LOUD FALLBACK + VOICE HEALTH (silent degradation impossible)
- `voice_health.py`: every proxy failure recorded (kv voice:health); status in
  /api/voice-status; daily TTS canary + quota read (warns at 85% BEFORE
  exhaustion); registry row "EDITH voice (ElevenLabs)" (FAILING/RUNNING/UNKNOWN);
  salience: fallback-active re-fires daily while broken (watermarked), quota event.
- Client: the FIRST fallback utterance each session announces itself — "Heads up —
  I'm on the fallback voice; ElevenLabs is failing with [server-recorded reason]" —
  at all 4 fallback paths; the badge reads "FALLBACK VOICE".
- EDITH: "is your voice okay?" answers truthfully either way.

### D3 · MEMORY MAINTENANCE (the debt paid, nightly forever)
`memory_maintenance.py`, nightly kv-stamped tick: consolidation (sim ≥ 0.75 same
category → merge, journaled) · contradiction sweep (review band 0.55–0.75: newer
fact with an explicit transition marker supersedes; otherwise a CONFIRMATION CARD —
never guessed) · importance-weighted retention (stale 45d+ low-weight → archive
tier) · **the budget invariant re-protected at every size** (demote the stalest
tail until the hot block fits with recall headroom). **NEVER DELETES** (grep-tested:
no DELETE in the module); every action journaled (kv memory:maintenance_journal);
`restore memory fact #N` reverses any demotion; archived facts stay retrievable
(topical matches return labelled in recall). EDITH: "memory conflicts" / "memory
card N: keep A/B/both" / "memory journal".

### D2 · THE LOOP FIX (asked-answered becomes impossible, twice over)
- **Belt — the pre-ask recall check:** before ANY question-shaped reminder
  surfaces, `_preask_answer()` searches memory; a strong fact match resolves the
  loop with the answer attached (never asked), and logs the near-miss incident —
  prevention is captured, not silent.
- **Braces — resolution detection:** every recorded user turn runs
  `check_resolution()` — a statement (never a question) sharing the loop's
  distinctive words resolves it with the answer attached. Wired at both chat sites.
- Plain reminders (no question shape) are untouched — "reconnect Xero this week"
  still surfaces until Rydel drops or answers it.
- The class is a PERMANENT regression suite: tests/test_asked_answered.py (seeded
  fact + loop → resolves, never surfaces, re-fire impossible; questions never
  self-resolve; unrelated statements don't resolve).

### UPGRADE · THE SELF-IMPROVEMENT LOOP
`convo_quality.py`: silent incident capture (corrections "I told you / no, I said /
we already discussed", asked-answered + near-misses, register drift, voice
fallbacks) → kv convo:incidents · weekly self-review job (counts by class, trend vs
prior week, worst exchange verbatim, canned-phrase drift scan over the last 300
assistant turns) · PROPOSALS confirmation-gated ("apply proposal N" is the only
apply path; avoid-list phrases then ride the persona) · metrics (incidents/100
turns, asked-answered target ZERO, near-miss saves, fallback count) · EDITH on
herself: "how's your conversation quality been?" (numbers + honest worst moment),
"what did you learn this week?" (only Rydel-confirmed fixes). Incident → test
discipline: the suite grows by demonstrated failures.

## VERIFICATION
- Suite 626 (17 new: voice_health 6, asked_answered 6, maintenance/quality 5) —
  all green; the greeting's correct salience (CPL-class events, watermarks), thread
  state, internal-only loop boundary untouched.
- LIVE (production, post-deploy): filled below.

## LIVE FIRST-RUN
(filled after deploy)
