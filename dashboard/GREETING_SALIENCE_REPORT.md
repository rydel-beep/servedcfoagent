# HUMAN GREETINGS, DYNAMIC LOCATION & SALIENCE — build report

**Date:** 2026-07-07/08 (Sydney)

## Before
`build_greeting` emitted a FIXED skeleton every boot — *"Good {tod}, Rydel… It's {t} in **Newcastle**…
You're at X appointments and Y deals closed… Cash collected: $Z. What do you need?"* — the same metric
litany regardless of events, **hardcoded** Newcastle coords, Sydney time-of-day, no watermark, no
session awareness. It read like a playbook rule, not a person.

## Phase 1 — dynamic location (`location.py`)
Resolution chain: **manual override** ("I'm in <place>", persisted) → **browser geolocation**
(`/api/geolocation`, reverse-geocoded, cached) → **last-known** → **Newcastle default** (stated
neutrally). Weather + time-of-day come from Open-Meteo for the RESOLVED lat/lon with `timezone=auto`,
so time-of-day is LOCAL. Geocoding via Open-Meteo, reverse via BigDataCloud (both free, no key); every
call degrades silently. "I'm back home" clears the override; "where do you think I am?" answers
honestly (place + how she knows). Newcastle is no longer hardcoded.

## Phase 2 — salience engine (`salience.py`)
Deterministic EVENTS since the watermark, each from a real source with a timestamp — never invented:
failed charge / past-due (Stripe, 100/95) ≥ deal closed (mirror, 80) ≥ payout landed (Stripe, 60) ≥
runway threshold crossing (engine, 55) ≥ new lead(s) (mirror, 40, batched if several). Ranked by
importance × recency; greeting surfaces the top 1-3. **Watermark + dedup** (`kv_store`, durable): every
surfaced event is marked told and never re-announced. Nothing new → the feed says so → a light hello
with NO stats. Queryable mid-session: "what's new?" returns the same feed.

## Phase 3 — composed greetings (`_compose_greeting`)
The model composes each boot from the persona + time-of-day + location/weather (used only when
notable) + the top events WITH their exact figures. Hard rules: numbers/names VERBATIM (no invention,
no rounding), 1-3 spoken sentences, no fixed skeleton, vary opener/structure, avoid the last ~6
greeting openers (anti-repetition via `kv_store`). Composer failure → a safe deterministic fallback
(hello + top event verbatim) — never a crash, never invented content.

## Phase 4 — session flow
`/api/greeting` is session-gated: a refresh/resume within a 25-min idle gap returns the SAME greeting
(no re-greet, no re-watermark); a new session composes fresh and advances the feed. Location + "what's
new" are TIER-1 handlers (run before the ramble gate), so they never misroute — and they compose
around deterministic data, so they don't fight the three-tier conversational-flow fix.

## Guardrails held
Greeting figures stay verbatim from the one engine / deterministic feed (the one-engine `_sales_headline`
repoint is untouched; consistency suite green); salience events are deterministic from real sources;
watermark prevents repeated news; nothing-notable = light hello; 1-3 sentences; location falls back
gracefully with override winning; composer failure falls back safely. 311 tests pass (+8).
