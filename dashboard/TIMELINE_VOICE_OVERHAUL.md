# Timeline Voice Overhaul — the mouth, the memory, the brain (2026-08-03)

Rydel's verdict on v1: hallucinates, drags, sounds creepy, lacks context. Root-caused as
three layers; each fixed and measured. cfo `b14b214→7768d16`, timeline widget v2 (`960dc1d`,
in deployed lineage). Suites 432 green. DECISIONS #109.

## Phase 0 — the parity table (what the port had dropped)

| # | Component | CFO tuned path | Timeline path v1 | Now |
|---|---|---|---|---|
| 1 | Persona/system prompt | full stack | same (shared core) | MATCHED (was already) |
| 2 | Router + gates | 3-tier + entity/repetition guards | same (shared core) | MATCHED (was already) |
| 3 | History/thread | rolling client history + channel resume | same | MATCHED (4-turn proof below) |
| 4 | Context blocks | finance + recall + injections | **no timeline data on Tier-3 → free-styled delivery talk (the hallucination source)** | **FIXED** — timeline grounding block |
| 5 | TTS voice settings | tuned, `voice.stream_tts` | same single source | MATCHED (no drift possible) |
| 6 | Chunker | decimal-safe + opening clause-break | re-written variant | **FIXED** — ported verbatim |
| 7 | Playback | prefetch + seam-killing pump | **sequential `new Audio()` → gap at every seam (the dragging)** | **FIXED** — gapless WebAudio schedule |
| 8 | STT | continuous, adaptive endpointing, echo guard | reduced, **no confidence gate (garbled → confident answer)** | **FIXED** — full port + confidence gate |
| 9 | Pronunciation | none (both surfaces read "$3,050", "LTGP:CAC", markdown aloud — **the creepy**) | none | **NEW** — server normalizer, both surfaces |

**Bad-turn trace (reproduced live):** voice question → reply `"The actual LTGP:CAC is 3.75x
(last 30 days) — that's the real number, not a scenario."` → v1 fed that raw to ElevenLabs.

## Layer 1 — THE MOUTH

- **One source for voice settings:** both TTS routes were already the single
  `voice.stream_tts` core — now it also runs `speech_normalize.normalize_for_speech`
  on every input, so drift between surfaces is structurally impossible.
- **Normalizer** (`speech_normalize.py`, 8 tests): currency→words, k/m expansion,
  `A:B`→"A to B", `4.51x`→"four point five one times", acronym lexicon
  (MRR/CAC/LTGP letters, ROAS "row-ass", Xero "Zero"; env-extensible `SPEECH_LEXICON`),
  percents, ISO dates→"July twenty-seventh", all markdown/bullets/emoji/ID-parentheticals
  stripped, short parentheticals become spoken asides. Captions keep eye-format —
  ONLY the TTS input is rewritten. Never raises (returns original on any failure).
  Pre/post pairs for the 5-utterance set are in the session log; the bad-turn specimen →
  *"The actual L T G P to C A C is three point seven five times, last 30 days, that's the
  real number, not a scenario."*
- **Gapless playback (widget v2):** decode-ahead scheduled queue on the WebAudio clock —
  each chunk `start()`s at the previous chunk's exact end (`cursor`), so inter-chunk gap
  is **0ms by construction**; fetch+decode begins at enqueue (prefetch covers the ~0.5s
  synthesis pipeline while the prior chunk plays); per-utterance generation tokens (no
  double-play, clean barge-in), `onended` node disconnect (no accumulation across a
  session). speechSynthesis fallback per chunk on TTS 503.
- **Chunker:** the CFO `sentenceEnd`/`clauseBreak` ported verbatim — decimal guard intact,
  clause-break on the opening chunk only (fast first word).
- **Measured (live, through the full timeline-proxy chain):** first-audio latency
  U1 0.70s · U2 0.57s · U3 0.48s · U4 0.48s · U5-long 0.59s (bytes 28–95KB). The
  worst-case seam equals fetch latency only if a chunk's synthesis outlasts the entire
  previous chunk's playback — not observed.

## Layer 2 — THE MEMORY

- **Thread proof (4 turns, live):** T1 data ("31 overdue, worst Akuna 5…") → T2 pronoun
  *"who's the worst of them?"* → "Akuna Cafe — 5 overdue, health 69, still onboarding"
  (grounded, correct) → T3 musing stayed conversational (no handler misfire) → T4 *"what
  was the first thing I asked?"* → answered exactly.
- **Timeline grounding for Tier-3:** timeline-channel conversational turns now carry
  `timeline_adapter.conversation_context()` — the real roster (names + health), headline
  risk, freshness, and the in-band entity rule ("a name not on this list is NOT a client…
  offer to pull detail rather than guessing"). Tier-2 handlers unchanged and still first.
- **STT honesty (widget v2):** final-result confidence averaged; <0.5 → *"Didn't catch
  that — say it again?"* (spoken + captioned, NO model call); self-echo guard drops her
  own words picked up by the mic; adaptive endpointing (1.5s patience, 3s on
  continuation words) stops half-sentence sends. Raw transcripts logged server-side per
  turn (`timeline transcript (voice=…): …`) so future mishear reports are diagnosable.
- **Adversarial set ON this channel (live):** nonexistent client → refused, not invented ·
  field-state question → verbatim from the injected tracker row (Growth Pro, closed 30
  June 2026, $1,650 first cash) · unknown (Google Ads spend) → *"Not in front of me — the
  data I have covers Meta spend only… want me to flag that?"* · repair ("no, I meant
  praise") → acknowledged and answered honestly (the ramble gate routed it conversational
  — by design, never a misfire).

## Layer 3 — THE BRAIN

`prompts/spoken_channel.py` — **versioned** (`v2-2026-08-03`), supersedes the inline
VOICE_ADDENDUM; `channel` now threads through `chat()/chat_stream()/build_system_prompt`.
Sections: REGISTER (1–3 sentences, answer first, no markdown, long content offered to
screen) · SPEECH-SHAPED (short clauses; rounding aloud allowed ONLY with the exact figure
in the same breath; money always exact) · THE THREAD (pronoun/follow-up resolution,
acknowledge-and-answer repairs) · HONESTY REGISTER (unknown = brief and unashamed; never
answer what wasn't clearly heard) · PERSONALITY (composed, dry, sharp; never chirpy about
a bad number) · CHANNEL NOTES (timeline = delivery-world fluent; figures engine-verbatim).
Full text: `prompts/spoken_channel.py` (kept as the single tuning surface). The CFO
surface gets the same core layer — an upgrade, not a divergence.

## Regression

- Owner gate re-verified live: admin `{"enabled":false}` + 403 chat/tts; unauth 401;
  EDITH `/bridge` direct 403.
- CFO dashboard's own voice loop: login → `/dashboard/api/tts` → 200 `audio/mpeg` (84KB)
  of the normalized money sentence — intact and improved (it gains the normalizer + the
  v2 layer; its tuned settings untouched).
- Timeline team features: ping ok/1650 tasks, overview 33 clients, assistant available.
- EDITH suite **432 passed, 0 failed** (8 normalizer tests + updated voice-register test).

## The human gate

Rydel — click ◈ EDITH and have a real conversation. The dragging (gapless scheduling),
the creepiness (normalizer + tuned chunking) and the context loss (thread + grounding +
spoken layer) should all be gone. Your ears close or reopen this build. If a specific
name still gets mangled, say the word — it's one line in `SPEECH_LEXICON`.
