# EDITH — Chat 404 + Google Sheets Freshness Diagnosis

_Generated 2026-06-16 (Sydney). Scope: chat model config + Sheets read/freshness path only.
HUD, voice pipeline, and engine math untouched._

---

## ISSUE A — Chat API 404 (BLOCKING) — ROOT CAUSE FOUND & FIXED IN CODE

### Symptom
```
Chat API error: Error code: 404 - {'type':'error','error':{'type':'not_found_error',
 'message':'model: claude-sonnet-4-20250514'}}
```

### Root cause
A **retired model identifier, hardcoded** in the chat handler.

- The only Anthropic call site in the entire codebase is `dashboard/chat.py`
  (`client.messages.create`). The greeting / brief / voice paths are template-driven
  and never call a model, so chat was the *only* — and a totally — broken LLM surface.
- The model was a **hardcoded string literal** at `dashboard/chat.py:348`
  (`model="claude-sonnet-4-20250514"`). There was **no** `CHAT_MODEL` / `ANTHROPIC_MODEL`
  env var and **no** entry in `config.py`, so the string could only be changed by editing
  code — that is the drift that allowed this to rot.
- `claude-sonnet-4-20250514` is the **dated full ID for the original Claude Sonnet 4**,
  whose **retirement date is 2026-06-15**. As of **2026-06-16** the Anthropic API returns
  `404 not_found_error` for it. Not a key problem, not a Sheets problem — the model string
  simply no longer resolves.

### The fix
- **New single source of truth** in `config.py`: `CHAT_MODEL = os.getenv("CHAT_MODEL", "claude-sonnet-4-6")`.
  Every Claude-calling endpoint (currently just chat) reads this, so the string can never
  drift across endpoints again.
- **`dashboard/chat.py`** now does `from config import CHAT_MODEL` and passes `model=CHAT_MODEL`.
- **Default model: `claude-sonnet-4-6`** (Claude Sonnet 4.6) — the documented drop-in
  replacement for retired Sonnet 4. Same Sonnet tier, 1M context. `temperature=0.5` at the
  call site remains valid on Sonnet 4.6 (sampling params are only removed on the Opus 4.7/4.8
  and Fable tiers), so no other change was needed.
- Because the **in-code default is already a valid model**, the 404 is fixed on the next
  deploy *regardless of whether the Railway env var is set*. The `CHAT_MODEL` env var is the
  future-proof override (e.g. to bump to `claude-opus-4-8` later) — not a requirement.

### Verification
- `claude-sonnet-4-20250514` removed from all executable code (one reference remains, in a
  config.py comment, as deliberate history).
- `config.py` + `dashboard/chat.py` parse clean; `from dashboard import chat` imports OK and
  resolves `CHAT_MODEL = claude-sonnet-4-6`; env override confirmed working.
- `tests/test_voice.py` + `tests/test_dashboard.py`: **32 passed**, no regression.
- **LIVE ping on the dashboard: PENDING DEPLOY** — requires pushing to Railway. Gated on
  Rydel's go (see below). Until deployed, production still serves the old code and still 404s.

### Model string now in use
`claude-sonnet-4-6` (via `config.CHAT_MODEL`, override env var `CHAT_MODEL`).

---

## ISSUE B — Google Sheets freshness — NOT YET STARTED

Hard stop after Phase 0 per the work order. Phase 1 (enumerate every Sheets read; map
id/gid/range→metric; cache TTL & last-fetch; auth validity; staleness probe; resolve what
`gid=239343371` is) has not been run yet.

**Early signal already observed:** the chat/dashboard test run emitted
`Sheet GID 1862317163 fetch failed (status 400)` (the Lead-to-Cash commission tab from
`CLAUDE.md`). That is a live Sheets read failing — a strong lead for Phase 1's auth /
fetch-path investigation. To be confirmed, not yet diagnosed.

_This section will be completed in Phase 1._
