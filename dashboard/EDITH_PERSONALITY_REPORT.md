# EDITH — Personality & Human-Like Delivery

**Date:** 2026-06-19
**Goal:** EDITH conversated well but read like an AI delivering answers. Give her real
personality — tonality, emotional intelligence, humour that riffs when Rydel jokes, warmth,
adaptability — an assistant that talks *with* him. Two layers: the **system prompt** (her
character — the biggest lever) and the **ElevenLabs delivery settings** (the voice expressing
range). **Accuracy never bends** — financial claims stay engine-sourced and true; she can deliver
hard news with empathy, but the number doesn't move.

**Honest framing:** an LLM doesn't literally feel. This builds emotional *intelligence +
expression* — reading Rydel's tone and responding genuinely and appropriately — which is what
makes conversation feel human. Warm and real, never performative or saccharine.

**Scope:** `dashboard/chat.py` (persona), `dashboard/voice.py` (delivery), `dashboard/static/js/
edith.js` (voice panel), `tests/test_voice.py`. Same `CHAT_MODEL`, locked voice ID, EDITH fx
chain, conversational-mind router, persistent memory.

---

## Phase 0 — current character (what was making her flat)

- **`BASE_PERSONA`** said only: *"warm, composed, quick, with a dry wit. You speak plainly and
  never pad."* True but thin — **no mood-reading, no humour instruction, no examples**. The
  model had nothing concrete to act on, so it defaulted to competent-but-neutral.
- **`VOICE_ADDENDUM`** was pure delivery mechanics (concise, spoken numbers) — no personality,
  no prosody guidance.
- **ElevenLabs**: `stability 0.70`, `similarity 0.75`, `speed 0.92`, **no `style`**. 0.70 is a
  *composed/even* setting — it deliberately flattens tonal movement, so even a livelier script
  came out level.

The flatness was **under-specified character + over-stable voice**. Both fixed.

---

## Phase 1 — the character (system prompt, the biggest lever)

`BASE_PERSONA` rewritten from a one-line descriptor into **specific behavioural instruction**:

- **Who she is:** EDITH/JARVIS archetype — knowing, a little playful, never zany, never servile;
  has a point of view; offers a light opinion or gently pushes back like a **sharp chief of
  staff** (still defers to his call). AI, honest about it, no fabricated feelings.
- **READ THE ROOM** (the core of feeling human) — match his tone:
  - loose/joking → play along, riff, land a dry one;
  - stressed/terse → drop the wit, calm and sharp, straight to the point;
  - a win → react like she means it, not over-the-top;
  - hard news → warm and straight, empathy without sugar, never chirpy about bad numbers.
- **React, don't narrate:** "oof, that's tight", "nice", "yeah, that tracks" — not "I have
  processed your request." Contractions, asides, natural punctuation.
- **Range IS the personality** — always-jokey is as wrong as always-flat; pick the register the
  moment calls for; no jokes when he's stressed.
- **Four few-shot beats** SHOW the character (a joke, a terse-Rydel ask, a win, hard-news
  delivery) — labelled *style, not scripts*, so the model never parrots them.
- **Hard lines that survive personality:** financial figures engine-sourced and true (warmth
  never moves a number); honesty over likeability; no fabricated feelings to over-emote.

`VOICE_ADDENDUM` now carries personality through **word choice + prosody** — punctuation
(em-dashes, ellipses, a question mark) as vocal rise/pause/warmth cues, "match his mood out
loud," personality in *how* she says it not *how much* — while staying concise (≈4 sentences).

### Before → after (persona core)

> **Before:** "PERSONA: warm, composed, quick, with a dry wit. You speak plainly and never pad."

> **After:** a full character with WHO YOU ARE, READ THE ROOM (4 registers), HOW YOU TALK,
> HARD LINES, and 4 few-shot beats — see `chat.py::BASE_PERSONA`.

---

## Phase 2 — expressive delivery (ElevenLabs)

`voice.py::active_voice_settings()` moved into the **expressive band**, all env-configurable and
live-tunable in the panel:

| Setting | Before | After | Why |
|---|---|---|---|
| stability | 0.70 | **0.40** (`TTS_STABILITY`) | tone now rises/falls with content; still clearly EDITH. Lower = more range but risks wobble — 0.40 is the band |
| style | — | **0.35** (`TTS_STYLE`) | dynamic delivery on models that support it (ignored harmlessly otherwise) |
| similarity | 0.75 | 0.75 (`TTS_SIMILARITY`) | identity holds |
| speaker boost | — | on (`TTS_SPEAKER_BOOST`) | presence on the livelier raw voice |
| speed | 0.92 | 0.95 (`TTS_SPEED`) | natural pace |

- **Locked voice ID** (`yj30vwTGJxSHezdAGsv9`) and the **EDITH effects chain** unchanged — the
  effect rides on the livelier raw voice (re-check the wet mix by ear; adjustable in the panel).
- **Voice panel:** new **Expression** (stability, "lower = livelier") and **Style** sliders, plus
  an **"A/B composed vs expressive"** button that speaks the same line at the old flat setting
  then the new lively one and leaves the voice on expressive. `save_voice_config` persists
  `style`; one shared poster sends the full dial-set so sliders don't wipe each other.
- **Prosody tie-in:** because ElevenLabs reads punctuation as prosody, Phase 1's word-choice
  guidance directly shapes vocal delivery — the two layers compound.

---

## Phase 3 — adaptability across context + memory

- Personality + mood-reading live in the **always-on** `BASE_PERSONA`, so they apply to **both**
  general and business turns — warm/witty about coffee, focused (or gently, if bad) on a runway
  figure — with accuracy intact on the numbers. **No added latency:** character is in the prompt,
  not extra calls; streaming responsiveness preserved.
- **Memory:** the existing `memory_block` recall (cross-session) is attached for both registers,
  so she can call back shared context naturally — a big part of feeling like she knows him. Same
  EDITH across sessions (stable persona + memory).

---

## Guardrails (must survive personality)

- **Financial accuracy:** unchanged — figures engine-sourced, never invented; missing data is
  stated plainly. Warmth never moves a number.
- **Honesty over likeability**, no fabricated-feelings over-emoting, spoken replies stay concise,
  voice/text parity, one-voice rule, streaming responsiveness — all preserved.

---

## Tests

`tests/test_voice.py`: **38 passing** including new persona/voice tests (mood-reading + few-shots
present; range/not-one-note; prosody in the addendum; expressive settings band + style dial;
config persists style). Full suite **187 passing**; the voice-config reset test was updated to the
new expressive defaults (intentional change). The lone failure
(`test_pdf_reads_cash_position_fields`) is pre-existing and unrelated.

## Live results (deployed dashboard, text + voice)

The five conversation types, run live against `web-production-16b16` — character lands and
**accuracy holds throughout**:

| Test | Rydel | EDITH (live) | Verdict |
|---|---|---|---|
| **Joke** | "we are SO back baby, feeling unstoppable" | "Ha — love the energy. What happened? Talk me through it." | playful, riffs, matches energy ✓ |
| **Stress** (terse) | "just give me the cash number. no fluff." | "**$140,007** in the bank. **$158,007** including $18k Stripe in transit." | drops the wit, sharp, accurate ✓ |
| **Win** | "closed the Bondi deal, biggest this quarter!!" | "Nice — what's the contract value? I don't have it in the system yet…" | genuine + **flags missing data, doesn't invent** ✓✓ |
| **Hard news** | "how bad is our runway? give it straight" | "3.5 months — not catastrophic, but not comfortable… [engine math] …the churn cliff is the number that should keep you up at night. 0/12 renewals." | warm + brutally honest + **every figure engine-sourced** ✓✓✓ |
| **Range** | (after the hard topic) "what's a negroni, should I try one?" | "…sounds simple then punches you in the face — in a good way… a full stop at the end of a bad sentence." | shifts register, witty, **callbacks the mood** ✓ |
| **Voice joke** | "the new espresso machine is a beast, im wired" | "Ha — how many have you had?" | concise spoken register, dry, lands it ✓ |

**Voice settings live (verified):** `stability 0.40, style 0.35, similarity 0.75, speaker_boost
on, speed 0.95`, model `eleven_flash_v2_5`. The A/B button in the panel speaks composed-vs-
expressive on the same line for ear-tuning.



## Follow-ups

- The by-**ear** judgement (does she make him smile; does the voice carry the tone; does the fx
  still sit right on the livelier voice) needs Rydel + the A/B button in the panel. The character
  (text) is live-tested below; the voice settings are deployed and A/B-able.
- `stability 0.40` is the starting band; tune the Expression/Style sliders to taste — the dial is
  there precisely because the sweet spot is an ear call.
