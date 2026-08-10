# DECISIONS

## 2026-06-24 — Missing recently-closed clients (Cally Hotel / Lucas) audit + fix

1. **Root cause was a READ bug, not missing data.** Cally Hotel (Lucas Reid) is fully logged
   in the tracker (Won, close 6/24, cash $3,355) and present in the snapshot's `active_clients`.
   EDITH couldn't speak to it because `dashboard/chat.py._build_context_block` built the ACTIVE
   CLIENTS block with keys that don't exist (`total_clients`/`total_mrr`/`avg_mrr` → None) and
   omitted the per-client list. In voice/lean mode (no full-snapshot dump) that left EDITH with
   zero client names. Fixed: real keys (`active_count`, `total_mrr_derived`) + a compact roster
   that ships in both text and voice.

2. **"Lucas" = Lucas Reid (Cally Hotel), per Rydel.** So both reported names are the same
   fully-logged client → the failure was purely read bug + refresh lag, no source gap for the
   named client. (Separately, Lucas *Doan* / The D's bar is a genuine Won-but-unlogged row —
   correctly excluded from cash/close totals and surfaced via the existing `won_but_unlogged`
   flag; needs source entry if signed.)

3. **Brief's canonical gid `544609965` is the WRONG tab** — it's a 30-row instructions banner,
   not data. The real 1,199-row data tab is named "Lead-to-Cash Tracker", which the code already
   reads by name (full sheet, no row cutoff). Flagged, did NOT repoint sources (gated change).

4. **Refresh tightened** (stale 4h→90min, interval 6h→2h, both env-overridable) so a same-day
   close auto-surfaces within ≤2h; manual `POST /cfo/refresh` still forces an unconditional rebuild.

5. **Stripe↔tracker reconciliation: consumer built, gated on an MCP tool that doesn't exist yet.**
   The Stripe MCP is aggregate-only (no per-charge data — confirmed live). Built
   `stripe_reconcile.py` (matches charges→tracker by email→name, PII-safe output) and wired it
   into the snapshot, but it degrades to `pending_mcp_tool` with a clear flag rather than
   fabricate. Chose NOT to edit the separate `served-stripe-mcp` repo (out of this repo's scope);
   documented the exact tool to add (`get_stripe_recent_charges`). Activates automatically once shipped.

6. **`fpdf` test failure is pre-existing/environmental** (missing local dep in `briefing_pdf.py`,
   untouched), not a regression. 225/226 pass.

## 2026-06-16 — Chat 404 fix (Issue A)

1. **Replacement model = `claude-sonnet-4-6`.** The dead string `claude-sonnet-4-20250514`
   was the dated ID for Sonnet 4, retired 2026-06-15. `claude-sonnet-4-6` is the documented
   drop-in for retired Sonnet 4 — same tier, keeps `temperature` support so the existing
   `temperature=0.5` call is unaffected. Chose the like-for-like Sonnet tier over jumping to
   Opus to keep cost/latency unchanged; Opus is one env-var flip away (`CHAT_MODEL`).

2. **Config-sourced, not hardcoded.** Added `CHAT_MODEL` to `config.py` (the documented home
   for all env vars) with a valid in-code default, read via `from config import CHAT_MODEL`.
   Rationale: the original bug was only possible because the string was hardcoded with no env
   override — centralising prevents recurrence and lets the model be bumped without a code
   deploy.

3. **No live "ping" test against candidate model strings.** The model catalog is authoritative
   and the retirement date (2026-06-15) matches the 404 symptom exactly, so a probe was
   unnecessary. Also avoided making a live API call so as not to touch the (masked) API key.

4. **Did NOT set the Railway `CHAT_MODEL` env var yet, and did NOT push/deploy.** The in-code
   default already fixes the 404 on deploy, so the env var is optional hardening. Pushing to
   production + setting prod env vars is an outward, hard-to-reverse action; per the project
   rule "show diffs before committing" and production-safety norms, this is gated on Rydel's
   explicit go rather than done autonomously. Diff shown; awaiting greenlight.

5. **Scope held to Issue A.** Hard-stopped before Issue B (Sheets freshness) per the work
   order's phase gate.

## 2026-06-16 — Sheets freshness audit (Issue B, Phase 1 — diagnosis only)

6. **No fetch logic changed.** Hard stop at the data map per the work order. Findings only.

7. **Will NOT fix the payout-log 400 by switching gviz-by-gid.** Probed and proved gviz
   *ignores* the `gid` param (gid 1862317163 and gid 239343371 returned byte-identical output
   — a 27-row guardrail tab). Swapping `/export?gid=` → `gviz?gid=` would turn a loud 400 into
   a silent wrong-tab read. Correct fix is fetch-by-NAME via gviz (needs the exact tab name)
   or publishing the LTC book for `/export`. Deferred to Rydel.

8. **Will NOT silently repoint `forward_mrr`.** gid 1407663952 is the **Health** tab, but
   `forward_mrr` treats it as RECOGNIZED. Per CLAUDE.md ("do not silently repoint an engine")
   this needs Rydel to confirm intent before any change.

9. **Probes were read-only and public.** Sheets CSV/gviz exports need no credentials, so no
   secret was touched. The one model-API ping ran via `railway run` so the Anthropic key was
   injected into a subprocess, never read into context. No Railway variable was dumped (only
   the single `CHAT_MODEL` / `SNAPSHOT_FILE` keys were parsed out).

## 2026-06-19 — Data-accuracy build (see dashboard/DATA_ACCURACY_FIX_REPORT.md)

10. **Production refreshes correctly — the "stale data" was the repo's committed
    `snapshot_state.json` (06-12), NOT prod.** Authenticated live pull showed prod stamped today
    (10:48), funnel 48/13/9/6, MRR $75,396, 36 clients. The repo file is a build artifact. The
    refresh path (POST rebuild→persist→GET→render) is sound; no refresh-path defect found.

11. **Stage 1 (Xero OAuth restore) and the GHL reconnect are MOOT** — both already LIVE in prod
    (Xero P&L margin 73%, burn off real lines; GHL conv 39.2%, 89 opps). The `/data` volume is
    why Xero survived deploys. No action taken.

12. **Stage 2 (live cash from Xero) is the real remaining work and stays GATED.** `xero_pull`
    fetches P&L only — no bank balances — so cash is still the labelled manual override. Needs
    (a) a bank-balance pull in `xero_pull.py` and (b) balance semantics pinned: the live
    CommBank read returned a NEGATIVE combined over a range = period movement, not a closing
    balance. Will NOT repoint $140k to a live-but-wrong negative. Awaiting Rydel.

13. **Stripe MCP sub miscount NOT fixed in-repo** — separate `served-stripe-mcp` repo;
    "served-cfo-agent/ only" applies. The agent already treats the count as non-authoritative
    and flags the mismatch.

14. **Closes NOT collapsed to one number** — funnel-cohort (6), closer monthly KPI (5), and
    deal-won variants measure different things and are labelled by section; collapsing would
    reduce accuracy. Headline uses one definition (scorecard cohort).

15. **Applied (171/171 green; deploy gated):** `current_month_mrr` alias on `forward_mrr`;
    `won_but_unlogged` DQ flag (fires on the 2 unlogged wins); `Cache-Control: no-store` on
    snapshot/refresh endpoints; `_safe_label` redaction of email-shaped Business Name labels
    (also fixed 2 pre-existing PII-leak test failures).

16. **New finding: history is NOT aggregate-only.** `history_store.append()` writes the full
    snapshot incl. client names to `snapshot_history.jsonl`, contradicting CLAUDE.md. Flagged
    for a scoped follow-up; not fixed here.

## 2026-06-19 — Stage 2 live cash: STOPPED at Stage 1 gate (see dashboard/LIVE_CASH_REPORT.md)

17. **Agent's Railway Xero OAuth is LIVE but scope-blocked for bank balances.** A deployed-context
    read (`/debug/xero-raw`) returned a 200 P&L. But the scope is `accounting.reports.profit
    andloss.read` (P&L ONLY). Bank closing balances need `accounting.reports.read` (Balance
    Sheet / Bank Summary). → Re-consent at a broader scope required (Rydel's browser action via
    /xero/connect). Will NOT bypass auth or use the chat MCP for prod.

18. **Tenant identity must be confirmed before any cash repoint.** The agent's P&L header reads
    "THE 97 GROUP PTY LTD", while the claude.ai MCP labelled the org "Served Marketing". Strong
    evidence it's the same entity (P&L shows Served's exact cost lines: Advertising $7,342,
    Contractors NO GST $15,789), but will NOT repoint cash on an assumption. Rydel to confirm
    THE 97 GROUP PTY LTD is the Xero org holding CommBank #2352 + #4041.

19. **Nothing built/changed this step.** Stage 2A/2B/3 queued behind the re-consent gate. Cash
    stays on the labelled $140,007 override — not faked. I CAN do the scope code change + deploy
    on Rydel's go (not a credential action); only the browser re-consent is his.

## 2026-06-19 — EDITH full conversational mind (see dashboard/EDITH_CONVERSATION_REPORT.md)

20. **Unclamped EDITH from finance-only to general assistant + CFO specialisation.** The clamp
    was the persona + forced finance template in `SYSTEM_PROMPT`, plus unconditional injection
    of the full snapshot on every turn (no hard-refusal gate existed). Split into `BASE_PERSONA`
    (always on, general Claude-range) + `SYSTEM_PROMPT` (business register, attached only on
    business intent) + a topic-agnostic `VOICE_ADDENDUM` (delivery, not topic).

21. **Intent-routed context.** New `is_business_intent()` (keyword/topic/$-figure heuristic with
    terse-follow-up inheritance) + `build_system_prompt()` — the one auditable place register +
    context are decided. Business turns attach the live snapshot + accuracy rules; general turns
    answer as open Claude (and skip the heavy snapshot payload). Bias on ambiguity = attach.

22. **Accuracy guard scoped to financial CLAIMS only.** The single surviving hard rule: never
    invent a financial figure; missing data is stated plainly. Everything non-financial is free
    conversation. Auth + rate-limit + TTS caps unchanged; model still `CHAT_MODEL` (not hardcoded).

23. **Voice/text parity is automatic** — both converge on `chat()` → `build_system_prompt`.
    `chat()` now returns `intent` for observability (HUD ticker left untouched to protect the
    HUD non-regression guarantee). Tests: 177 passed (+7 new intent tests); the lone failure
    (`test_pdf_reads_cash_position_fields`) is pre-existing and unrelated. Live four-type
    conversation test must run on the deployed dashboard (no local API key by design).

## 2026-06-19 — EDITH real-time responsiveness + voice music control (see dashboard/EDITH_RESPONSIVENESS_REPORT.md)

24. **Latency was a serial stack; fixed by overlapping, not micro-optimising.** Phase 0 (live):
    endpointing ~1.4s + NON-streaming model gen ~4.3s + TTS first-byte ~0.78s ≈ 6.6s to first
    word. The model-gen wait (whole reply before TTS) was dominant.

25. **Streaming pipeline (Phase 1).** chat_stream() generator + /api/chat-stream SSE; chat.js
    reads the stream and splits at sentence/clause boundaries (decimals guarded); edith.js plays
    chunks through the SAME fx chain via a queue, one-voice/barge-in preserved, stopVoice resolves
    the stream promise. Non-streaming /api/chat is the fallback (used inline on any stream error).

26. **Fast TTS env (Phase 2)** TTS_MODEL (default flash) + optional TTS_GREETING_MODEL; locked
    voice ID + fx unchanged. **Adaptive endpointing (Phase 3):** ~0.75–0.9s on a clear sentence
    end, 2× base on a continuation cue; ring/hold-V/barge-in intact.

27. **Lean voice context (Phase 4) — second bottleneck.** Live streaming showed business TTFT
    ~2.5s vs general ~1.7s because the ~93k-char snapshot inflates time-to-first-token. Voice path
    now drops the redundant FULL SNAPSHOT dump (curated sections already carry every canonical
    number): ~33k → ~11k context tokens (−69%), business TTFT ~2.5s → ~2.0s. Text chat keeps the
    full snapshot. General turns already snapshot-free.

28. **Voice music control (Phase 5).** Local intent match (down/up/pause/resume/mute/set %) acts
    on the MUSIC channel only, routed before the model, instant tonal ack, volume persisted via
    setMix→localStorage. EDITH's voice + SFX never touched.

29. **Net:** stop-speaking → first word ~6.5s → ~3.4s (general) / ~4.0s (business); she speaks
    sentence 1 while the rest streams. Tests 182 pass (+5). Ear-test (mic/speakers) is Rydel's to
    run; server-side streaming timings are live-measured. Excluded unrelated pre-existing
    Postgres-memory WIP (db.py/config.py/requirements.txt) from these commits.

## 2026-06-19 — Persistent memory (Postgres) — engine + UI DEPLOYED (see dashboard/EDITH_MEMORY_REPORT.md)

- Built in NEW modules only (db.py, memory.py, dashboard/memory_routes.py + memory.html +
  memory.js) — ZERO edits to the chat path (streaming session owns chat.py/routes.py/chat.js,
  commits 6243f40/f7bac63). Chat integration = documented ~3-line hook (report §8), deferred.
- psycopg3 + raw SQL (no ORM); config.DATABASE_URL prefers internal (postgres.railway.internal),
  falls back to public. Schema: conversations/messages/memory_facts + pg_trgm trigram recall.
- Memory != financial truth (hard boundary): recall labelled "NOT financial truth", never
  overrides a live engine number, facts timestamped, secrets guarded out of distillation.
- Graceful degradation if DB down (verified). DEPLOYED + verified live (commit 4d93249): prod
  connects via internal URL (status online:true), migrate-on-boot ran, /dashboard/memory live +
  auth-gated, 183/183 tests green. NOT YET LIVE: the chat-path hook (EDITH won't persist real
  conversations until those ~3 lines land — streaming path is now stable so it's unblocked).

## 2026-06-19 — Memory chat-path hook APPLIED + verified end-to-end (commit e6ba6b8)

- Wired persist + selective recall into BOTH /api/chat and /api/chat-stream (streaming session
  had landed, so editing chat.py/routes.py was safe). build_system_prompt/chat/chat_stream gained
  an optional memory_block (default "" = unchanged). Recall injected for BOTH registers (labelled
  NOT financial truth). User+assistant turns persisted async; distillation fired async on done.
- VERIFIED LIVE in prod: stated a codename in conversation A → archived A → in a SEPARATE
  conversation B, EDITH correctly recalled "Bluefin Tuna Launch, March 2027" from Postgres, with
  provenance (result.recalled). clear-all privacy control verified. 183/183 tests green.
- EDITH now remembers across sessions/devices end-to-end. Memory subsystem COMPLETE.

## 2026-06-19 — EDITH personality + expressive voice (see dashboard/EDITH_PERSONALITY_REPORT.md)

30. **Flatness was under-specified character + over-stable voice.** Persona said only "warm,
    composed, dry wit" (no mood-reading/humour/examples); ElevenLabs stability 0.70 flattened
    tone. Both fixed.

31. **Character rewrite (Phase 1, biggest lever).** BASE_PERSONA now gives SPECIFIC behaviour:
    EDITH/JARVIS archetype with chief-of-staff initiative; READ THE ROOM (loose→playful,
    stressed→sharp, win→pleased, hard-news→warm+straight); react-don't-narrate; "Range IS the
    personality"; 4 few-shot beats (style not scripts). VOICE_ADDENDUM carries personality via
    word choice + prosody (em-dash/ellipsis as voice cues), stays concise. Hard lines survive:
    financial figures engine-sourced/true, honesty over likeability, no fabricated feelings.

32. **Expressive delivery (Phase 2).** stability 0.70→0.40, new style 0.35, speaker_boost on,
    speed 0.95 — all env (TTS_STABILITY/STYLE/SIMILARITY/SPEED/SPEAKER_BOOST) + live panel sliders
    (Expression, Style) + "A/B composed vs expressive" button. Locked voice ID + fx chain
    unchanged (effect rides the livelier raw voice). save_voice_config persists style.

33. **Adaptability + memory (Phase 3).** Personality in the always-on persona (no added latency),
    applies to general + business; memory_block recall carries warmth across sessions.

34. **Live-verified (deployed, text+voice).** Joke→playful riff; terse→sharp accurate number;
    win→genuine + flags missing deal value (no invention); hard-news→warm+straight with every
    figure engine-sourced (3.5mo runway, churn cliff, 0/12 renewals); range→shifts register +
    mood callback; voice joke→"Ha — how many have you had?". Accuracy held throughout. Tests 187
    pass (+ persona/style); voice-config reset test updated to expressive defaults. Excluded
    parallel WIP (chat.js chat-open, dashboard.css, capture_layering.py) from my commits.

## 2026-06-19 — EDITH UI layering & fluidity fix (see dashboard/UI_LAYERING_REPORT.md)

- **Root cause (measured, not guessed):** chat panel docked right at z-200; every EDITH
  voice/HUD element docked bottom-right at z≥230 (`#eh-stage` via `#edith-hud`=230,
  `.jarvis-orb`/`.jarvis-caption`=250). So orb/waveform/ticker/caption painted OVER the panel.
  Phase-0 harness proved it: `overlaps_panel` true for eh_stage/eh_wave/eh_cap/eh_tick/jarvis_orb.
- **Fix = one z-index token scale** (`--z-ambient…--z-tooltip` in `:root`) applied system-wide;
  no raw z-index left on a live positioned element. Lanes: ambient(1) < content(10) <
  chrome(85–100) < orb(150) < scrim(300) < chat(310) < boot(700) < modal(1000) < toast(1100)
  < tooltip(1200).
- **Structural move:** lifted `#eh-stage` OUT of `#edith-hud` so ambient (grid/scan/radar/
  brackets/shards → z-ambient, behind content) and the orb (z-orb, above content) live in
  separate lanes. `hud.js` now mirrors `data-state` onto `#eh-stage` so the `[data-state]`-keyed
  ring/core animations survive the move (verified rings+core still animate).
- **DEVIATION from the brief's literal layer order (documented):** brief listed orb (#4) ABOVE
  chat (#3). I put the **chat scrim+panel ABOVE the orb** (scrim 300 / panel 310 > orb 150).
  Rationale: belt-and-suspenders — the panel then wins on z-order ALONE, so the acceptance gate
  (no overlap) cannot be defeated by a geometry edge case. The orb still visibly "yields": on
  `body.chat-open` it slides clear of the panel (`translateX(-(chat-w+32))`), ambient dims to
  0.10, and all floating TEXT (eh-cap/eh-tick/jarvis-caption/note) is muted (reply lives in the
  bubble). Net effect matches the brief's intent (orb steps aside, conversation has priority)
  with a stronger guarantee.
- **Did NOT delete any animation.** Orb rings + `#eh-wave` waveform still play in their lane,
  stepped aside. The inert `.stark-*` CSS (no `stark-hud.js`, never injected) was left intact
  with a comment rather than ripped out.
- **Panel open/close switched from animated `right:` to `translateX`** (GPU, no layout shift);
  reduced-motion respected.
- **Proof:** before/after Playwright captures + JSON assertions in
  `dashboard/verification/ui-layering/` (after: all `overlaps_panel` false, panel z 310, chat
  controls clickable, 0 console errors). Verified at 1440/820/390px. HUD canary green.
- **Non-regression:** 187/187 relevant tests pass; the 1 failure is a pre-existing
  `ModuleNotFoundError: fpdf` (missing local optional dep), no Python touched.
- **NOT pushed/deployed** — frontend diff shown, gated on Rydel's go per project norms.

## 2026-06-19 — EDITH caption/voice sync + tonality consistency (see dashboard/EDITH_TONALITY_CAPTION_REPORT.md)

35. **Caption desync root cause (the real bug).** HUD #eh-cap typed `capLine` snapshotted ONCE at
    speaking-start (before any streamed chunk arrived) and never advanced — so it showed a stale/
    entry line; .jarvis-caption was left blank in the streaming path. Fix: caption is driven by the
    SAME streamed chunk text, revealed per chunk at PLAYBACK START via a new edith:caption event
    (single source of truth: the same `text` builds the /api/tts URL and the caption). hud.js
    caption is now a live typewriter (capSet/capClear); no snapshot. stopVoice clears it (barge →
    no orphaned text). Chat bubble still holds the full reply.

36. **Tonality: stability 0.40→0.50 (stable-but-alive).** 0.40 overshot — some replies dragged/
    wobbled. 0.50 carries tone yet is consistent turn-to-turn; style 0.35→0.30. Confirmed ONE
    fixed profile for all conversational replies (regression test: settings identical call-to-
    call) — personality comes from word choice, not per-utterance param swings. Panel A/B now
    compares 0.40 vs 0.50 to lock by ear.

37. **Live-verified + guardrails.** Deployed settings stability 0.50/style 0.30 confirmed; caption
    source == TTS source structurally guaranteed + Node-validated (caption==spoken chunk; barge
    clears). Personality/warmth, streaming responsiveness, one-voice rule, accuracy all intact.
    Tests 188 pass (+1). Eye test (caption visibly tracks speech; 0.50 by ear) is Rydel's in-
    browser. hud.js carried a 1-line `var stage` from in-flight parallel layering work (not mine);
    excluded the rest of the parallel UI WIP (css/html/chat.js/capture_layering.py) from my commit.

## 2026-06-19 — EDITH audio integrity (see dashboard/EDITH_AUDIO_INTEGRITY_REPORT.md)

38. **Progressive crackle = audio node leak.** routeThroughFx built a full fx graph (incl. lfo/
    shim oscillators that .start()) per chunk/utterance and never disconnected/stopped them →
    hundreds of running oscillators + nodes accumulate → CPU climbs → audio underruns/crackle.
    Fix: track every node/oscillator per utterance; el._fxTeardown declick-ramps then stops
    oscillators + disconnects all nodes on ended/stop. Built-once output peak limiter on the
    voice bus prevents hot-chain clip-crackle. Node sim: 0 leaked over 200 chunks (was ~3600
    nodes + 400 oscillators).

39. **Self-cutoff = no-lookahead scheduling.** Next chunk was only fetched on current's `ended`
    → ~0.5-0.8s gap per seam; `error` skipped a sentence. Fix: one-ahead PREFETCH (next chunk
    buffers while current plays, warmed on arrival via _maybePrefetch); clean HOLD if generation
    lags (never abandons sentence); retry-once on transient error. Stop-trigger audit: all stops
    are real interrupts or post-completion — no spurious mid-playback stop.

40. **Premature endpointing.** Un-punctuated stops fired at 900ms (interim ASR rarely punctuates)
    and VAD gate 0.055 was too high to reset on soft/resumed speech. Fix: full window (~1.5s,
    default 1.4→1.5) for un-punctuated stops, fast ~1.0s ONLY on punctuated end, 1.8x for expanded
    continuation cues; VAD reset 0.055→0.035. Ring + hold-V unchanged. Sim confirms patient on
    mid-thought, snappy on punctuated end.

41. **All edith.js only; guardrails intact.** Responsiveness (prefetch doesn't delay first word),
    personality, caption sync, one-voice/barge-in preserved. Tests 188 pass. Ear test (long
    session clean; gapless multi-sentence; no early send) is Rydel's in-browser. Excluded parallel
    UI-layering WIP (css/html/chat.js/UI_LAYERING_REPORT.md/capture_layering.py) from this commit.

## 2026-06-19 — EDITH persistent-memory repair: forgot on refresh (see dashboard/EDITH_MEMORY_REPAIR_REPORT.md)

42. **The DB chain was healthy; recall had a hole.** Verified live: Postgres provisioned
    (internal+public DATABASE_URL), reachable, migrated (tables+pg_trgm), writes landing (54 msgs),
    distillation running (23 facts), idle gap 12h. The bug: db.recent_messages() existed but was
    NEVER called, and build_recall_context's search EXCLUDES the current conversation. On refresh
    (client JS history wiped) the model got only facts + a cross-conv search of the only conv that
    exists (empty) → forgot the recent thread.

43. **Fix.** memory.resume_thread(): on a wiped client thread (≤1 msg) reload recent_messages of
    the resumed conversation from Postgres and prepend, so refresh RESUMES. Wired into /api/chat +
    /api/chat-stream (resume → reconstruct → record → recall → model). _sanitize_history collapses
    consecutive same-role turns (Anthropic alternation). search_messages: symmetric similarity() →
    word_similarity() (short-query-in-long-text), 0.15→0.30 — cross-session recall now fires.

44. **Loud degradation.** /api/memory-status + a self-contained "persistent memory offline" badge
    (polls/min) so a DB failure is never again a silent forget.

45. **PROVEN live.** Talk ("pillar one = customer retention, Bluebells case study, 32% repeat") →
    simulated refresh (empty client history) → EDITH recalled all three; accuracy boundary held
    (flagged Bluebells as a live renewal client). Writes grow per turn; 23 distilled facts; cross-
    session search returns hits. NOTE: first test ran mid-rollout and self-poisoned the thread with
    "memory is broken" assistant turns; removed those test-only messages (restored conv #1 to 54),
    clean test passed. Tests 193 pass (+5). Excluded parallel UI-layering WIP from my commits.

## 2026-06-24 — Data accuracy audit (wrong client count + always-red pill + cash/Stripe)

46. **Root cause (Phase 0, verified live).** The Finance Google Sheet (`1n7OcGr…CTg`, holds the
    Health tab = authoritative client roster) returns **HTTP 401** — its public/link sharing was
    revoked after 2026-06-19. `pull_client_health()` → None → `derive_active_clients()` falls back
    to the LTC tracker's Won deals (a *different*, still-public sheet) → headline becomes
    "N clients (0 active, N awaiting Stripe)" where N = LTC Won-deal count (16, now 17). NOT a
    Stripe miscount. Reproduced live: health=[] + 17 won → active_count 17, all pending.

47. **Refresh pill always red = structural.** Pill fails on `ok===false || degraded>0`, and
    `ok = len(degraded)==0`. `degraded[]` is never empty (Xero+GHL unconfigured, Stripe-MCP
    limitations, benign data-quality flags) → pill could never be green even on a healthy day.

48. **Rydel's decisions (gate after Phase 0):** (a) he re-shares the Finance sheet (no code change
    needed to restore the roster); (b) approved BOTH code fixes — gate the active-clients fallback
    so a down roster is labelled-stale not confidently-wrong, and fix the pill to distinguish core
    failure (red) from optional/known-degraded (not red); (c) restore Xero live cash (gated — prove
    closing-balance semantics via read-only Xero MCP first, then print agent-side OAuth restore
    steps + HARD STOP).

49. **Stripe pending $18k / cash $140,007 are manual constants**, not live reads. Stripe MCP has no
    balance/pending tool (6 tools, none for balance). Cash override 20 days stale; agent-side Xero
    unconfigured. Live Stripe MRR $57,241 on "1 active sub" = stripe-mcp service defect (external
    repo), already flagged degraded; does not feed the client headline.

## 2026-06-24b — Canonical-source reconciliation (contradiction surfaced)

50. **gid 182553893 is the SALARY tab, not the client roster.** Rydel's follow-up work order named
    Finance tab gid `182553893` as the authoritative active-clients roster and instructed a repoint.
    Read live: it is the **SALARY tab** (header LAST/FIRST NAME, ROLE, DEPT, STATUS, SALARY AUD/PHP;
    18 staff; TOTAL SALARY AUD $21,174). It has zero clients. The agent ALREADY reads it for burn
    (`pull_salary_baseline` → $21,174). **Did NOT repoint active-clients to it** — that would count
    staff. The real roster is the **Health tab gid 1407663952** (Client Name/Status/Package/…;
    36 Active), which the code already uses. Per CLAUDE.md "the contradiction itself is the finding."
    The "16" was the Health-tab 401 fallback (fixed last session, committed ed0cf11), NOT Stripe.
    HARD STOP: confirm active-clients stays on the Health tab; no salary-tab repoint.

## 2026-06-24c — Live Meta ad spend → CAC/LTGP:CAC/ROAS

51. **Live Meta spend feeds unit economics (read-only).** Built `meta_spend.py` (Insights edge,
    raw Graph API, no SDK dep) reusing the Ad Monitor's `META_ACCESS_TOKEN`/`META_AD_ACCOUNT_ID`
    (act_1071149830652711). RETROACTIVE: every refresh re-fetches a daily series and OVERWRITES
    stored days (never freeze; Meta attribution firms over ~72h); trailing 7d flagged provisional;
    persisted to state/meta_spend_daily.json. Windows 7/30/60/90 + month. Resolved ad spend
    (snapshot.ad_spend_resolved + hormozi._resolved_ad_spend): Meta live (primary, 30d) → Xero
    Advertising (fallback) → None — replaces the stale $8,002 AD_SPEND_FALLBACK. CAC/LTGP:CAC/
    payback/LTV:CAC repointed; NEW m8_roas = (closes×avg_contract)/spend, window-consistent,
    Meta-labelled (Google = future hook at the single resolution point). meta_spend degraded =
    severity:optional → pill stays GREEN (Meta absence ≠ refresh failure); failure shows last-known
    + loud flag, never silent stale. Currency≠AUD flags (no silent FX). 211 tests pass (+7).
    Rydel chose: set META_* on CFOagent (gated — token not in CFO env yet); agency-wide scope.
    HARD STOP: set the two env vars on CFOagent, then live-verify (spot-check vs Ads Manager +
    print CAC/LTGP:CAC/ROAS before/after). Report: dashboard/META_SPEND_REPORT.md.

52. **Pagination bug caught at live-verify.** First deploy showed Meta 7/30/60d = $0 but 90d =
    $5,068 over only 25 days. Cause: Meta Insights paginates (~25 days/page, OLDEST first); the
    single GET grabbed page 1 only → recent days dropped → recent windows silently $0 (the exact
    "silently-wrong" failure mode). Fix: `_graph_get_all` follows `paging.next` to the end (cap 12
    pages); a mid-pagination failure returns partial rows + a loud degraded flag, never silent
    truncation. Live re-verify: fetched_days 25→90; 7d $2,652 / 30d $9,038.89 / 60d $17,358 /
    90d $23,628 (AUD, acct tz Australia/Sydney). 213 tests pass (+2 pagination).

## 2026-06-24d — Repoint ALL ad-spend consumers to the single live-Meta source

53. **One ad-spend source dashboard-wide.** The Meta build wired CAC/LTGP:CAC/ROAS to
    ad_spend_resolved but left Profit Waterfall, cash burn, financial_position, verdicts, and the
    briefing PDF on the stale Xero advertising line ($7,384; was the $8,002 hardcode pre-Xero) — a
    live contradiction (economics $9,041 vs waterfall $7,384). Fix: `snapshot._resolve_ad_spend`
    computed BEFORE get_monthly_burn and passed in as ad_spend_override; burn/financial_position/
    hormozi/waterfall/verdicts/PDF all read the identical resolved value (Meta live 30d, window-
    matched). Burn keeps the Xero line as ad_spend_xero_ref cross-ref. Waterfall P&L headline stays
    Xero-reconciled; only the OpEx breakdown shows live ad spend (Other OpEx absorbs the variance).
    KILLED AD_SPEND_FALLBACK ($8,002) — no Meta+no Xero → ad spend 0 + loud note, never a hardcode.
    Cross-section verified: all consumers = $9,041.62 for 30d. 215 tests pass (+3). Report:
    dashboard/AD_SPEND_CONSUMER_FIX_REPORT.md.

## 2026-06-24e — Command-driven manual targets/benchmarks/goalposts (Category A)

54. **Rydel sets manual goalposts by voice/text.** New manual_targets.py: JSON store on /data
    (survives redeploy), DEFAULTS registry, get_resolved/get_all/history/set/reset. handle_turn()
    parses set/query/reset/note from NL with a CONFIRMATION loop (echo parsed value → write only on
    "yes"; ambiguous field → ask) — wired into /api/chat + /api/chat-stream BEFORE the model
    (local-match short-circuit, music-control pattern). compute_hormozi takes targets=get_resolved()
    so LTGP:CAC/ROAS/payback/gross-margin/op-eff healthy-line reflects Rydel's goalposts; snapshot
    exposes snapshot["targets"] (value/default/is_user_set/set_by/set_at). Frontend KPI subs +
    month-perf chips show the set value + "set by you" tag. API: GET /api/targets (+history),
    POST /api/targets/set + /reset (auth-gated). MERGE-ON-REFRESH: store is separate; a rebuild
    reads + layers it, never wipes a set target (verified set→rebuild→rebuild survives). ONLY
    no-live-source values; live metrics never editable (out of scope). 225 tests pass (+10).
    Report: dashboard/TARGETS_BENCHMARKS_REPORT.md.

55. **Targets settings panel.** Added the graphical panel (the follow-up from DECISIONS 54) as a
    self-contained auth-gated page at /dashboard/targets (memory-page pattern — avoids the
    UI-layering-entangled dashboard.html). Groups targets/benchmarks/goalposts/assumptions, each
    row: current value (editable, unit-aware) + default + "set by you" tag + Save/Reset; plus Notes
    and full change-history. Consumes the existing GET/set/reset API. Discoverable via the Cmd-K
    palette ("Targets & benchmarks"). +3 dashboard tests (page renders, API get/set/reset, unauth
    blocked). Report: dashboard/TARGETS_BENCHMARKS_REPORT.md.

## 2026-06-25 — Stripe money-state accuracy (read real balance/payout objects)

56. **Real Stripe money states via a read-only key.** Phase 0: every Stripe money figure was an
    aggregate/manual guess — "$18,000 incoming" = the CASH_STRIPE_INCOMING constant; "$88k cash" =
    MCP gross-charges flow; payouts = aggregate sum (no per-payout status). No secret key in env; MCP
    aggregate-only (6 tools, no Balance/Payout objects). HARD STOP → Rydel adds a restricted
    read-only key. Built stripe_balance.py (read-only GET /v1/balance + /v1/payouts) computing THREE
    states: available (balance.available, settled), pending_incoming (balance.pending, settling),
    in_transit_to_bank (recent payouts pending/in_transit/paid-not-yet-arrived; failed dropped;
    paid-arrival-passed → recently_paid_settling, not double-counted). Wired into cash_position
    (replaces the $18k card with 3 distinct labelled state cards + true total_available, no
    double-count) + snapshot["stripe_money"] + source_freshness; metrics_engine canonical entries +
    stripe_money_states tagged optional (no key → graceful, pill not red on its own). AUD-only,
    non-AUD flagged. Degrades to the labelled manual $18k when no key. 233 tests pass (+4). Report:
    dashboard/STRIPE_MONEY_STATE_REPORT.md. NOTE: snapshot.py also carries a PARALLEL session's
    uncommitted stripe_reconcile WIP — committed only my hunks (checkout-reapply).

57. **Hotfix — total_available consistency for 3 states.** First Stripe-states deploy 500'd
    /cfo/refresh once the key went live: cash_position.total_available = bank + available + incoming
    + in-transit, but check_consistency still asserted bank + incoming (2-term). No-key tests passed
    (extra terms 0). Fixed the invariant to the 4-term sum + regression test (19e94a2). Live-verified:
    available -$107 (~$0), incoming $13,713.24 (exact match to Rydel's Stripe), in-transit $11,524.95;
    $18k guess gone; pill green.

## 2026-06-25 — Fully-loaded CAC (real setter comm from the log)

58. **CAC setter component completed.** CAC already included closer ($7,200 actual) + setter, but
    the setter half used the scorecard $50/qualified-set figure only ($500), missing 5%-of-cash.
    The real per-deal $50+5% lives in the SETTER PAYOUT LOG, which reads by gid 552970662 → HTTP 400
    but by NAME "SETTER PAYOUT LOG" → 200 (different column layout). New loaded_cac.py reads it by
    name, window-matched → $1,507.27 (15 deals: $750 fees + $757.27 bonuses). hormozi
    _resolved_setter_comm uses it (actual-from-log) with scorecard fallback (labelled). Rydel
    confirmed: LTGP stays CONTRACT-basis (×margin = $11,758, not cash collected); setter = $50/set +
    5% from the log; window by close/set date — BUT the log has no close/set-date column and the
    tracker name-join matched only 7/164, so windowed by PAYOUT date (labelled). Before→after: CAC
    $4,114 → $4,366; LTGP:CAC 2.86 → 2.69×; ROAS unchanged (ad-spend-only, m8 untouched). Breakdown
    surfaced in the CAC read. 238 tests pass (+4). Report: dashboard/LOADED_CAC_REPORT.md.

## 2026-06-25 — Postgres sheet-mirror (live-backed cache)

59. **Live-backed cache (sheets → sync → Postgres mirror → EDITH).** EDITH read a slow periodic
    snapshot, so recent sheet edits (e.g. last closes) were invisible. Built sheet_mirror.py: a
    faithful jsonb mirror (sheet_mirror + sheet_sync_state) on the existing memory Postgres; sync_tab
    atomic + content-hash change detection (skip unchanged; replace-on-change incl. removals; loud
    failure keeps last-good). Focused scope (Rydel): Lead-to-Cash Tracker, Team Scorecard, SETTER
    PAYOUT LOG (by name) + Health (BY GID 1407663952 — the tab named "Health" is an MRR-projection
    view; gid is the real roster). Reads re-sourced: _fetch_tab/_fetch_tab_by_gid/loaded_cac read the
    mirror first, live fallback if stale/absent/DB-down. Background sync 90s + voice/text "resync"
    (sync_all + snapshot rebuild → names latest close) + /dashboard/api/resync. Transparency:
    /dashboard/data-sources panel + "what's plugged in/is your data current" voice query (last-checked
    vs last-changed, status, errors — loud on failure). Read-only; graceful Postgres-down. 246 tests
    pass (+8). Report: dashboard/SHEET_MIRROR_REPORT.md.

## 2026-06-25 — Range-aware unit economics + mirror to all 7 tabs

60. **Mirror expanded to all 7 tabs** (Setter Deep-Dive, RECOGNIZED, SALARY added). finance_sheets_pull
    ._fetch_tab + forward_mrr read the mirror first now too.
61. **Range-aware unit economics** (range_unit_economics.py): LTGP:CAC / ROAS / LTV:CAC for ANY range,
    window-consistent BY CONSTRUCTION (one range drives every input). Rydel-confirmed: attribution =
    SPEND-IN-WINDOW; ROAS revenue = CASH COLLECTED (was contracted); LTV = full contract value (no
    margin, current). Closes/contract/cash/closer windowed by Close Date (LTC Tracker, by header);
    setter by payout date (log); ad spend by spend date (meta_spend.spend_in_range, store-or-live).
    NL range parsing (in May / last 3 weeks / between X&Y / this-vs-last-month / Q1 / YTD) wired into
    the chat router AFTER targets. Driver decomposition in every reply + comparisons attribute the Δ.
    GET /dashboard/api/unit-economics (dashboard + voice share one engine → no drift). Zero/small
    windows flagged, no div-by-zero. 252 tests pass (+6). Report: dashboard/RANGE_UNIT_ECONOMICS_REPORT.md.

62. **Closes methodology reconciled + dashboard wired through the range engine.** The range engine
    counted closes loosely (contract>0 → 8/30d) while the dashboard used the Scorecard's opaque
    `closes` cell (4) — divergent CACs. Reconciled to ONE definition: a close = Call Outcome == "won"
    + Close Date in window (the canonical per-deal, range-flexible definition the velocity calc uses).
    Dashboard CAC/LTGP:CAC/LTV:CAC/ROAS tiles now route through GET /api/unit-economics for the
    selected window (applyRangeEconomics, dashboard.js only) → tiles == EDITH's spoken answer, no
    drift; breakdown on hover. Scorecard cell kept for the legacy funnel display only. 252 tests pass.

63. **Scorecard "Closes = 4" diagnosed (no code change).** The Team Scorecard's closes (4) is a
    7-DAY COHORT metric counted by lead Input Date (2026-05-26→06-01: "of this week's 27 new leads,
    4 converted") — proven: Leads-in=27 = exactly the Input-Date-in-that-week count (30d=98), and
    every Scorecard ratio ties to one 27→9→8→4 cohort (Lead→Close 14.8% = 4/27). The engine's 8 is
    deals CLOSED in trailing-30d by Close Date — the money/CAC denominator (window-consistent with
    spend/comms/cash). Different windows + different bases; both correct. The Scorecard's 4 is a
    weekly funnel-conversion KPI, NOT the CAC denominator. Reconciled engine (close-date-in-window)
    confirmed correct.

64. **Dashboard economics fixed + cohort-conversion view added.** (a) The month-perf card/KPI strip
    read snap.hormozi (no element IDs) so the tile override missed them → cached the engine result
    (rangeEcon) and route the card's LTGP:CAC/CAC/LTV:CAC through it; all economics displays now match
    EDITH's voice for the selected window. (b) Added cohort_funnel(w0,w1) — leads-in→set→showed→closed
    + lead→close % by lead INPUT DATE (reproduces the Scorecard's 14.8%=4/27 exactly). Surfaced in
    unit_economics()["cohort"], /api/unit-economics, a voice command ("how's lead flow converting"),
    and a labelled line in the month-perf card, alongside (and explicitly distinct from) the close-date
    money view. 254 tests pass.

65. **Funnel section wired to the cohort engine.** renderFunnel now prefers the range engine's
    cohort_funnel (rangeEcon.cohort) for the selected window — same leads→set→showed→closed numbers
    as the month-perf cohort line and EDITH's "lead flow" answer — labelled "cohort (by lead Input
    Date)" with a note it's the window's NEW leads (≠ deals closed in-window). Falls back to the
    snapshot funnel until the engine resolves; applyRangeEconomics re-renders it on window change.
    Added lead_to_set_pct to cohort_funnel. 254 tests pass.

## 2026-06-29 — Cash on hand wired LIVE from Xero (+ connection verification)

66. **Xero connection verified + cash on hand wired live.** Phase 0 (6 checks) all PASS: token
    valid (refresh works), ONE tenant "Served Marketing" (legal THE 97 GROUP PTY LTD, AU/AUD) matching
    saved tenant_id, offline_access + banksummary/balancesheet/profitandloss granular scopes
    (transactions.read absent by design, not needed), live read OK, target accounts resolve (#2352
    d93b6904, #4041 e7dc87e2, BAS #2353 50a4af6a; Amex excluded; "notn in use" shares #2352's NUMBER
    so matched by NAME marker), positive CLOSING balances (Trap 1 cleared). Cash-definition
    contradiction surfaced (brief said exclude-BAS but expected ~$172k, which needs BAS) → Rydel chose
    **$172k flat include-BAS**. Cash on hand = closing bal #2352 $43,680 + #4041 $56,594 + BAS #2353
    $71,574 = $171,847.80. Wired in xero_pull.pull_xero (Bank Summary, same single-use refresh token)
    → snapshot cash_in_bank, with LOUD last-known fallback. Removed stale $140,007/"confirmed 06-04"
    override. 258 tests pass (+4). Report: dashboard/CASH_ON_HAND_REPORT.md.

67. **True payback via Stripe reconciliation (payback_reconciliation.py).** Phase 0: existing rk_live
    key reads all per-payment endpoints (no new key); Offer Sold col 26 populated; deal→Stripe match
    ~50% (email-exact 4/10 + name-search 1; tracker email ≠ billing email). Rydel: build now + unmatched
    list. Engine: per-customer Stripe charge timeline (refunds subtracted, charges-only to avoid
    invoice double-count) → per-deal payback = cumulative cash crosses loaded CAC per close (range
    engine, not bare ad spend); never-recovered = ongoing (not false-finite); per-offer median
    small-sample-flagged (<3); blended shown alongside (labelled). Confident matches only (unmatched
    excluded+listed, never fabricated). PII-safe (emails server-side only). GET /api/payback + voice
    ("payback on Growth Pro"). Range-aware. 265 tests (+7). Report: dashboard/PAYBACK_RECONCILIATION_REPORT.md.

68. **Leads visibility (leads_view.py).** Live test: EDITH named closes but not the latest LEAD. Phase 0
    verified gid 1923956551 = the SAME Lead-to-Cash Tracker already mirrored (full LEAD INTAKE→close
    pipeline; lead = Input Date+Lead Name row, close = Call Outcome won). Mirror already had the data —
    gap was surfacing. leads_view.recent_leads/latest_lead read the mirror, newest by Input Date+Time;
    voice ("who's the latest lead?"/"recent leads"), resync confirmation now names latest lead + latest
    close, GET /api/leads. PII-safe (email/phone never returned). 269 tests (+4). Read by tab NAME.

69. **Deterministic factual recall + anti-fabrication guardrail.** Verify run caught the model
    fabricating "Bondi Beach Restaurant — biggest deal of the quarter" on "last few closes". Root
    cause: (a) persona style example literally said 'closed the Bondi deal!' (primed the name); (b)
    HARD LINE only forbade inventing NUMBERS, implicitly licensing invented ENTITIES. Fix: closes_view.py
    deterministic handlers ("last few closes"/"recent deals" → real won deals verbatim; "biggest deal"
    → real max contract or honest defer) wired before the model. Persona rewritten: never invent a
    specific fact (figure/name/deal/date/count); removed the Bondi example + labelled beats as non-data;
    business-mode DATA RULES reinforce names-are-facts. 273 tests (+4). chat.py persona region is
    parallel-clean (parallel only touches _build_context_block 369+) → checkout-reapply.
    Report: dashboard/DETERMINISTIC_RECALL_REPORT.md.

70. **Desktop chat-overlap fixed (with rendered proof).** Playwright became runnable (chromium
    installed) → verified against the ACTUAL rendered view for the first time. Root cause: the
    "ambient yields" mechanism (body.chat-open JS + CSS) lives only in the parallel session's
    UNCOMMITTED tree — never deployed; live, body.chat-open is never set and there are 0 chat-open CSS
    rules, so the HUD (#edith-hud z230, .jarvis-orb/.jarvis-caption z250, .edith-wave z249) renders
    over the chat-panel (z200) in the shared right-side zone. Prior fixes updated z-scale VARIABLES but
    the elements use hardcoded z. Fix (CSS-only, dashboard.css): key off the live .chat-panel.open via
    :has() — yield the ambient HUD entirely (visibility/opacity/pointer-events) + raise chat to z400/390
    when open; untouched when closed. Verified live-injected at 1024/1280/1440/1536/1920: chat z=400,
    ZERO overlaps, screenshot clean. Report: dashboard/DESKTOP_CHAT_OVERLAP_REPORT.md; PNGs in
    dashboard/verification/desktop-chat-overlap/. chat.css via checkout-reapply (parallel WIP preserved).

71. **Leads-count fix (scorecard 4 → raw 88).** "How many leads in June" said ~4 (Team Scorecard
    "Leads in" cell, a narrow rolling window) while the raw tracker has 88 June rows. Root cause:
    counts weren't deterministic — handle_leads_command only does display ("latest/recent"), so
    "how many" fell to the model, which grabbed the scorecard aggregate. Fix: leads_view.count_leads
    + handle_lead_count_command (raw rows by Input Date; lead = Input Date + Lead Name, Rydel-confirmed
    = 88 June / 109 May / 1028 all-time) and closes_view.count_closes + handle_close_count_command (won
    deals by Close Date), wired BEFORE the model in both chat endpoints. Scorecard never sources a count.
    275 tests (+2). Report: dashboard/LEADS_COUNT_FIX_REPORT.md.

72. **Count sweep — sets/shows/clients locked to raw rows.** Extended the deterministic-count pattern
    so no "how many" reaches the model: sets (setter Call Outcome==SET, cohort by Input Date = 26 June),
    shows (Show Status==Showed = 13), clients (snapshot active_clients.active_count = 37, derived roster).
    leads_view.handle_substage_count_command + handle_client_count_command, wired before the model. Sub-
    stages labelled "cohort by Input Date" (not conflated with the scorecard's own set/show formula).
    June funnel from raw: 88→26→13→6. 277 tests (+4).

73. **Command misrouting fixed + Amex owing surfaced.** (a) "Can we afford to bump SMM to 35k, push Gabie
    to 40k" hit the targets menu: the SET-trigger fired on set-verb(incl bump/raise) + "to" + digit, with
    no metric requirement and no question-guard. Tightened: fires only if NOT a question (_QUESTION_RE) AND
    a number AND (target-noun OR set-verb+known-metric); cost verbs dropped; ambiguous explicit commands
    still ask "which target?"; stale pending no longer nags. (b) Amex owing (credit-card liability, Bank
    Summary negative balance $18,153) read via xero_pull._extract_amex_owing → snapshot.xero.amex_owing;
    dashboard liability line + liabilities_view.handle_amex_command ("what do we owe on Amex"). Separate
    from cash, never netted. Phase 2 affordability routes to analysis but per-person salaries not yet in
    context (follow-up). 283 tests (+8). Report: dashboard/COMMAND_ROUTING_AND_AMEX_REPORT.md.

74. **Deterministic salary lookup (grounds affordability math).** salary_view.py reads per-person
    AUD+PHP verbatim from the SALARY tab (col5/col6, values-as-of date, implied FX from tab totals).
    Pure lookups ("what do we pay Gabie" → $831/₱35,000; "total payroll" → $21,174/₱910,000 @ ₱43/A$1)
    answered before the model. Affordability/change questions guarded OUT of the lookup (_CHANGE_Q) but
    the verified roster is injected into the model context (salary_context) so cost/FX math uses real
    figures, not memory. 287 tests (+4). Wired in both chat endpoints. Report update in
    COMMAND_ROUTING_AND_AMEX_REPORT.md.

75. **Client churn/downgrade WRITE-BACK — dashboard override (no Google write).** Rydel chose: EDITH
    does NOT write the sheet; she records churn/downgrade in Postgres (client_overrides), the dashboard
    applies it (count+MRR+churn via pull_client_health's existing churn-skip hook), and a "For Piolo"
    queue lists the manual Health-sheet edits. Brief's write target gid 182553893 was the SALARY tab
    (would corrupt payroll) → roster is Health gid 1407663952. Confirmation loop (echo exact row, yes/no,
    ambiguous→ask), one-direction (confirm→resync→dashboard), churn auto-reconciles once the sheet
    catches up, one-command undo + audit log, auth-gated. No permission escalation. 293 tests (+6).
    Report: dashboard/CLIENT_WRITEBACK_REPORT.md.

76. **ONE engine per metric (killed the four-way contradiction).** A session gave 4 answers for one
    metric: two engines (hormozi snapshot = contracted ROAS/scorecard closes; range engine = cash
    ROAS/tracker closes) plus the greeting (scorecard 0/2, Stripe $70k). Rydel locked: ROAS=contracted,
    "cash collected"=new-deal tracker cash, closes/appts=tracker Call-Outcome-won, CAC=loaded, LTGP:CAC
    & LTV:CAC as-is. Consolidated: range engine ROAS→contracted; hormozi m1/m2/m7/m8 DELEGATE to
    unit_economics(30d) (one call, shared) — duplicate formulas deleted; greeting reads
    hormozi._sales_headline (engine); tiles/chat already the engine. Consistency suite asserts
    hormozi==engine + greeting==engine + ROAS-contracted + no-duplicate-ROAS-formula (grep). 297 tests
    (+4). Report: dashboard/ONE_ENGINE_REPORT.md.

77. **Three-tier intent routing (stop data non-sequiturs on musings).** A rambling voice musing
    returned a random payroll row: salary_view._PAY_RE's `(what|how much).*(…|on)` greedily bridged
    "what we do" → "more on". Fix: intent_router.py — TIER 1 commands (strict, first), TIER 2 data
    (GATED), TIER 3 conversation (DEFAULT). is_conversational_ramble() skips TIER 2 for long
    declarative no-data-structure turns → model. entity_relevant() suppresses an entity-scoped lookup
    (salary) naming a person absent from the utterance (aggregates/superlatives exempt). Tightened
    _PAY_RE (no cross-ramble bridge). Asymmetry: unsure → conversation. Gated both /api/chat and the
    voice /api/chat-stream. 303 tests (+6). Report: dashboard/CONVERSATIONAL_FLOW_REPORT.md.

78. **Human greetings + dynamic location + salience.** Replaced the fixed greeting template (same stat
    litany + hardcoded Newcastle) with: location.py (override → browser-geo → last-known → Newcastle
    default; Open-Meteo weather/local-time for resolved lat/lon), salience.py (deterministic events
    since a durable watermark — failed/past-due/close/payout/runway/leads, ranked importance×recency,
    dedup so known news never repeats, "what's new?" queryable), and a model-composed greeting
    (persona + facts, figures VERBATIM, 1-3 sentences, anti-repetition, safe deterministic fallback).
    /api/greeting session-gated (25-min idle → same greeting, no re-greet). kv_store.py = durable
    Postgres KV for watermark/override/shapes. One-engine repoint + consistency suite untouched. 311
    tests (+8). Report: dashboard/GREETING_SALIENCE_REPORT.md.

79. **Dashboard outage (2026-07-09): em-dash crash → restore + harden.** build_snapshot threw
    ValueError on float('—') in _pull_deep_dive (a scorecard placeholder cell) → /cfo/refresh 500 →
    no snapshot → dashboard had no data. Total outage because the local snapshot file was wiped on the
    last deploy AND sources weren't isolated. Restore: _parse_float() safe-parse (eb31338). Harden:
    _safe_result() fail-softs each of the 11 snapshot sources — one crash degrades itself, build
    survives (ec59bdb); /health upgraded to subsystem triage (server/DB/snapshot-freshness/degraded
    sources) (323f4e9). Error banner already surfaced null-snapshot. 315 tests (+3). Parallel WIP
    (stripe_reconcile, refresh-cadence) preserved via checkout-reapply. Report: dashboard/OUTAGE_FIX_REPORT.md.

80. **Read-before-assert + in-chat self-diagnosis.** EDITH claimed 3 clients' cash-collected cells
    were blank; they were filled ($8,305/$15,950/$1,650). Verdict: MODEL INFERENCE — no per-row cash
    read path existed, so the answer read nothing and the model inferred 'blank' from a cash figure.
    Fix (tracker_read.py): read_client_row() resyncs recent/stale tabs + reads every field VERBATIM;
    client_context() injects verbatim rows so the model can't infer a field state; handle_self_check()
    is the challenge loop (resync → re-read → correct with root cause / confirm — truth not
    appeasement) + recompute; diagnostic commands "check the tracker for X" / "cash collected for X" /
    "verify your data"; distinctive-token client matching (no 'cafe'/'that' false hits). incident_log.py
    logs a structured code-bug handoff ("show me the incident" → copy-ready block; she states she can't
    self-patch code). Wired into /api/chat + /api/chat-stream. 321 tests (+6). Report:
    dashboard/READ_BEFORE_ASSERT_REPORT.md.

81. **Capacity & hiring intelligence engine.** capacity_engine.py — the who/when/what-can-we-afford
    source of truth. Rydel's locked benchmarks (kv_store, voice-tunable): SMM 7 FT / 4.5 PT clients,
    ads 10/manager, trigger 85% at 5wk lead, churn gate >2/mo, 40% payroll:MRR ceiling on
    true_team_cost. Department load (SMM cap = FT×7+PT×4.5; live 110%), net velocity (closes−churn
    30/60/90d), hire trigger (projected load at now+lead ≥ threshold, volatility-flagged), hiring
    budget (MRR×40%−payroll; live −$6,632 = 50.5% ratio, over ceiling → honest "no room yet, MRR needs
    $79.9k"), priced hires (PHP↔AUD), constraint check (churn elevated → LEADS with retention math,
    "don't hire fix the leak"), raise signals (tenure+load+affordability, priced 5/10/15%, NEVER
    verdicts). Conversational Tier 2 (afford question no longer misroutes to targets); /api/capacity
    owner-only; salience tie-in for firing triggers. BOUNDARIES: dept-level only (per-person = phase-2,
    no assignment data); salaries never to memory (record_turn skipped for capacity replies) or logs;
    morale never claimed. 331 tests (+10). Report: dashboard/CAPACITY_HIRING_REPORT.md.

82. **System audit (Wave 0) + S1 quick-wins.** Full audit (3 parallel sweeps + live verification):
    the recent hardening builds LANDED (one-engine consistency green, ad-spend migration complete,
    outage /health+fail-soft, deterministic-recall/read-before-assert gate all paths). Material
    findings + fixes shipped this run: F1 (S1) — dashboard funnel/exec/verdicts read Scorecard cells
    showing 0/0/0/0 while the tracker held 85 leads/24 sets/6 closes; repointed sales.funnel to raw
    tracker 30d in pull_sales_analytics (closes by Close Date = canonical 6). F2 (S2) — greeting blasted
    "26 charges failed" daily from the unreliable Stripe MCP (1 sub/$67k MRR); gated failed+past_due
    salience on the stripe_mrr_subs_mismatch flag. F4 (S2) — capacity_engine.churn_in_window swallowed
    errors silently (0 churn = data-missing); added logging. Deferred: F3/F5 (roster reconciliation,
    bookkeeping), F6-F8 (labels/time-bombs). Wave 1 (forecasting) + Wave 2 (decision-zone UI) specs in
    the report. 331 tests. Report: dashboard/SYSTEM_AUDIT_REPORT.md.

83. **Wave 1 — forecasting layer.** forecasting_engine.py: 13-week cash flow (Stripe cash run-rate +
    velocity×avg×collection − burn → curve + min week), MRR forecast + BASE/BEST/WORST scenarios +
    live what-ifs, dynamic runway vs static, forecast-accuracy tracking (kv_store projected-vs-actual
    bias). EXPIRY-AWARE: attrition = mid-contract churn + forward_mrr expiry drag scaled by an
    adjustable renewal rate (default = historical 0%). Honesty architecture: all labelled PROJECTION,
    every assumption voice-adjustable (inflow/collection/closes/churn/renewal/tax), confidence flags,
    separate from actuals. Surfaces two truths: business is cash-positive (~+$55k/mo, static runway
    understates) BUT at 0% historical renewal MRR declines (expiries $12.7k/mo > new deals $8.9k/mo) —
    retention is existential. Tier-2 conversational + /api/forecast owner-only. 338 tests (+7).
    Report: dashboard/FORECASTING_REPORT.md. Wave 2 (UI) remains.

84. **Wave 2 — decision-zone UI + stable-base commit.** Committed the accumulated front-end WIP as a
    stable base (7f0a0b8: layering z-index system, a chat.py null-key fix [Pattern 1], stripe
    reconciliation, cadence); fixed a live mobile orb overlap (4fea0fa). Re-architected the flat
    ~30-section dashboard into 4 decision zones via safe JS DOM relocation (applyZones): Am I safe /
    Is the machine working / What needs action / Where are we going. Rendered the previously-invisible
    backends: the consolidated Action Feed (/api/action-feed) in Zone 3, and cash-runway + MRR-scenario
    forecasts (/api/forecast) in Zones 1 & 4, all tagged PROJECTION. Set forecast renewal_rate to 25%
    for the Noodle Asia + Bluebells re-signs (MRR base −$3,782→−$616/mo). Screenshot-verified desktop +
    mobile, 0 page errors. Report: dashboard/WAVE2_UI_REPORT.md.

85. **Cash truth — Stripe-aware cash + the "WA: blank" fix.** The incident ("last cash collected" →
    "WA: cash-collected cell is genuinely blank") was NOT a column mismapping (col 32 verified correct
    across all 4 locators, live-sampled): a junk enquiry-paragraph row token-matched "what", then
    2-char substring matching landed on an unrelated junk row named "WA". Fixed tracker_read matching
    (names ≤40 chars, conversational stopwords, ≥4-char substring floor). SOURCE HIERARCHY built:
    tracker = deal truth, Stripe = cash truth — cash_truth.py joins succeeded charges (per-charge
    money-state via balance_transaction) to tracker rows (email > unambiguous name > unambiguous
    amount+date; Won-row preference for duplicate rows; ambiguity FLAGGED never guessed; PII asserted).
    "Last cash collected" now answers from ACTUAL payment events with tracker-logging status, both
    truths on disagreement. GATE FINDING: the read-only rk_ key was ALREADY on Railway (Round 7/12) —
    nothing was blocked; stripe_reconcile.py was dormant only on a never-built MCP tool → repointed to
    direct API reads, paid-but-unlogged LIVE. Needs-logging list: action feed (persistent S2) +
    salience (watermarked, greeting-worthy) + "what needs logging?" query; EDITH nudges, team logs —
    cash cells never auto-written. Logging lag quantified (21d: 10 covered / 9 under-logged / 4
    unmatched) + observed-lag watermarks in kv_store. Basis names: Stripe-actual vs tracker-logged
    cash, no repoint (headline-basis choice OPEN for Rydel). Fixed a PRE-EXISTING order-dependent
    full-suite failure with a root conftest.py (test auth env). 359 tests (+21). Report:
    dashboard/CASH_TRUTH_REPORT.md. Branch feat/cash-truth, not merged (Rydel's gate).

85. **Smarter Stripe↔client payment matching.** The old matcher (exact email OR exact normalized
    name, tracker-only) false-flagged 4 payments ($9,952.50): existing clients paying again
    (Jeni/Nirosha/Jagjeet) + payer≠business (Fiona Fitzgerald = Glen's venue). Rebuilt _match_payment
    as MULTI-SIGNAL + roster-inclusive + confidence-scored: email(100) · contact-name tokens(80) ·
    first-name(50) · business tokens(68) · distinctive surname(60)/common(26) · amount corroboration
    (+20). Bands: ≥60 unambiguous → auto-match (existing_client_repeat vs matched_known); 26-59 →
    needs_review (suggested); none → unrecognised. Never forces a match on ties. Re-reconciled: Fiona→
    62Thirty, Nirosha→her record, Jeni→Gone Burger auto; Jagjeet→unrecognised (common surname, correct
    to ask). Renamed flag stripe_paid_not_in_tracker→stripe_unrecognised_payment (severity hygiene, no
    core-red). Alias learning ("Jagjeet is <client>" → kv_store, auto-matches forever). Handlers +
    action-feed updated; PII guard retained. 4 false positives → 1 verify → 0 after one confirm. 368
    tests (+7). Report: dashboard/PAYMENT_MATCHING_REPORT.md.

86. **Three-way collaboration layer + per-user auth.** Rydel's call: Piolo (bookkeeper/acting COO)
    gets FULL visibility + authority = same as Rydel, but every Piolo action is FLAGGED to Rydel;
    roles differ by identity, not access. dashboard/auth.py rewritten: two env accounts (rydel=owner,
    piolo=coo), Flask session {user,role}, current_actor(), audit_login, /logout, require_owner
    reserved. SAFE MIGRATION: setting RYDEL_PASSWORD+PIOLO_PASSWORD enables per-user AND retires the
    shared token atomically; inert until then (no lockout). collab.py: work log (done/concern/question/
    suggestion, threads, 15-min edit then append-only corrections, archive-hide, NO deletes), queue
    (live flags → resolve-with-note → EDITH re-derives from fresh data → ✓verified/⚠partial; clears
    only on data change, stated factually), digest (watermarked), salience surfacing, archive (date
    browse, month summary, substring search, unified journal over audit trails, dated JSON/CSV export
    off-DB). Attribution hook in client_overrides. Injection-safe (entries are data). Endpoints
    /api/collab/*, /whoami, /logout; chat handlers actor-aware. 375 tests (+7). LIVE per-role verify
    pending railway login. Report: dashboard/COLLABORATION_LAYER_REPORT.md.

87. **Piolo's front-end panels.** Zone-3 dashboard panels for the collaboration layer: Bookkeeping
    queue (live flags → resolve-with-note inline → EDITH verification annotation, status pills) and
    Work log (composer + colour-coded entries + "signed in as" from /api/whoami). Consumes
    /api/collab/*; wired into loadAll + the zone map; HUD-theme CSS; responsive. Local Playwright:
    panels render, composer works, 0 page errors. Live-data + per-role deployed verification pending
    railway login. Commit 141533c.

88. **Responsive layout overhaul (fluid grid).** The layout was rigid — horizontal overflow at 9/10
    widths (scrollWidth 2275px at a 1920 viewport; the page bled sideways = Rydel's complaint). Root:
    .kpi-strip was display:flex with no min-width:0 → ballooned to ~2275px; .grid-2/.zone-grid were
    fixed/single-breakpoint 2-col; body overflow-x:hidden clipped content. Fix (CSS-only, palette
    unchanged): KPI strip → grid repeat(auto-fit, minmax(min(148px,100%),1fr)); .grid-2/.zone-grid →
    auto-fit minmax(min(Npx,100%),1fr) so cards collapse smoothly at every width; min-width:0/max-
    width:100% on all containers; tables scroll within cards; clamp() on values. Charts already
    responsive (Chart.js + SVG viewBox). VERIFIED: after-sweep zero overflow at all 10 widths
    (scrollWidth===viewport); live-resize 1920→390 no overflow + visible 3→2→1 col reflow; chat-open
    layering clean desktop+mobile; Piolo view responsive+scoped. Zones (Wave 2) now fluid. No Python
    changed (375 tests unaffected). Report: dashboard/RESPONSIVE_LAYOUT_REPORT.md.

88b. **Responsive v2 — corrected the over-correction.** Rydel: "way too stretched, nothing in the
    middle, messy." v1 (88) forced .main to max-width:100% (killed the centered 1320px column →
    edge-to-edge sprawl) and used auto-fit grids (cards stretched to arbitrary widths). Fix: .main
    restored to max-width:1320 + margin auto (centered); .grid-2/.zone-grid → repeat(2, minmax(0,1fr))
    — clean equal two-column that still shrinks safely, stacking to 1-col at 900px. Kept the real
    overflow fix (KPI strip flex→grid). VERIFIED deployed (1a712af): 1920 → .main 1320px centered
    (300px margins each side), 1440 → 1320 centered, ≤1024 fills width, all overflow=0; screenshots
    confirm centered/tidy at 1920/1440/700/390. dashboard/verification/responsive-layout/v2/.

89. **Quarterly Review PDF — Phase 0 gate (Rydel's calls, 2026-07-21).** (a) QUARTER CONVENTION =
    CALENDAR quarters (Q2 2026 = Apr–Jun is the default last-completed review; Q3 = current). For
    this period AU-FY and calendar resolve to identical windows anyway. (b) 3X METRIC = EVERYTHING:
    3x cash collected + contracted revenue + new MRR together — model 3x of overall QoQ company
    growth, not a single lever. (c) ACCESS = Rydel + Piolo both (full-visibility mandate) → gate is
    require_auth, NOT require_owner; Piolo's generation is flagged to Rydel via collab. VERIFIED
    live numbers (Q2 2026 Apr–Jun): 16 closes, $253,200 contracted, $98,255 new-deal cash, CAC
    $2,688, LTGP:CAC 4.8, ROAS 10.38; current MRR $85,996; 42 active clients. DATA AVAILABILITY
    (probed live): Meta ad-spend history is DEEP (meta_live_range back to Q1 2025 — corrects the
    stale "Meta only since 6/24" premise); tracker closes cap YoY (Q3 2025 = 2 closes, Q2 2025 = 0)
    → QoQ (vs Jan–Mar 2026) fully honest; YoY computable for Xero REVENUE only, unit-econ/sales YoY
    NOT (stated plainly in PDF). PDF engine = reuse fpdf2 (already deployed, branded BriefingPDF),
    no weasyprint/Railway change.

90. **Quarterly Review PDF — built & verified (Phases 1-4).** One button (both roles) generates a
    branded fpdf2 PDF from the canonical engines: the quarter + QoQ/honest-YoY + a constraint-first
    3x model, dated into the forever archive, each generation flagged to Rydel (record_action).
    Modules: quarterly_pack (window-consistent, one-engine), quarterly_compare (nascent-tracker YoY
    guard: suppress tracker-dependent fields when prior quarter <3 closes → Q2-2025 sales/unit-econ
    reads "not computable", only Xero + Meta compare), three_x_model (fundability-aware — leads/spend
    plausible because LTGP:CAC stays above floor, binding constraint = Delivery hires operational
    wall), quarterly_review (orchestrator + chat handler), dashboard/quarterly_pdf (render +
    validate_verbatim: every $-figure must trace to the pack, generation fails loudly otherwise).
    Added xero_pull.pull_pl_range (per-quarter P&L; Xero history verified live to 2025). VERIFIED
    LIVE: same-moment pack==dashboard exact (LTGP:CAC 4.74/CAC 2718.13/closes 16/contracted 253200/
    cash 98255/adspend 24382.88); adversarial $9,999,999 caught; Rydel+Piolo both generate 200+valid
    PDF, both archived+flagged; chat "compare to last year"/"3x next quarter"/"generate" all work;
    375 Stage-A tests green. Report: dashboard/QUARTERLY_REVIEW_REPORT.md.

91. **Piolo work-log silent-failure — fixed (2026-07-22).** Reported: Piolo submits entries/queue
    answers, nothing records, no error. TRACED VERDICT (Phase 0, evidence): NOT the suspected 403
    over-gate — collab endpoints use require_auth (require_owner is applied to NOTHING; no owner-only
    403 gates exist by Rydel's full-authority decision). Backend writes succeed for Piolo (4 types →
    200, rows land ids 17-20; resolve → 200 + verification loop) and the browser round-trip works
    (POST fires, renders back, no console errors). REAL DEFECT: front-end _postLog/_resolveFlag/
    renderWorkLog/renderCollabQueue ignored r.ok, swallowed errors (catch{}), and cleared the field +
    re-rendered regardless — so a 401 (expired session) or transient 500 looked identical to success
    and wiped the text. add_entry returning None also surfaced as a silent 200 {ok:false}. FIX: check
    status + visible outcome (Saving→Posted✓/clear error), keep text on failure, map 401/403/server/
    network; renders surface 401; server returns 400 (empty)/500 (write fail) with loud logger.error
    (user+role+endpoint). VERIFIED live both roles: Piolo browser success shows Posted✓ + renders;
    forced expired-session shows the session error with TEXT PRESERVED; role sweep 200/200/401 (no
    gate loosened — zero authz change); Rydel digest sees Piolo. Collab tests 7/7; Stage-A 374/375
    (the 1 failure = pre-existing capacity_engine MRR-drift test, untouched by this work). Report:
    dashboard/PIOLO_INPUT_FIX_REPORT.md.

92. **GHL Lead Intelligence — Phase 0 gate (2026-07-27).** ACCESS: existing GHL_SALES_API_KEY is a
    Private Integration Token (pit-) with FULL scope — probed live, pipelines/opportunities/contacts/
    NOTES all 200. No new credentials, no Railway change. Rate limits 100/10s burst, 200k/day (ample).
    INVENTORY (pipeline JJQLCr1fl7OHyrpRwSJp "1 SERVED Client Acquisition"): 1342 opps (open 1290/won
    20/lost 31). Unresponsive/Not Interested = 986 open / $2,226,500 (matches the ~986/$2.2M oracle);
    reactivatable cold-stage open ≈1030 (matches oracle). Notes: ~48% of leads have >=1 note (~52%
    none = hygiene finding), notes long (~12.5k chars avg). Contact carries email/phone/name/tags;
    opp carries contactId/name/monetaryValue/lastStageChangeAt. RYDEL'S CALLS: (a) EXCLUDE both
    Disqualified (86) + Ban Leads DND (22) from reactivation — still counted in hygiene, never a
    target (DND = contact risk). (b) PITCHED-STALLED = reached Consult Call Booked/2nd Consult, open,
    no stage-change 21+ days. (c) DELIVERY = export-first (CSV + formatted reactivation brief), no
    sales dashboard role for now. STALE = open, created 90d+, in a reactivatable cold stage (excl.
    Disqualified/Ban/Won). WARMTH = stage-reached (weighted) × value × last-touch recency. JOIN to
    tracker: email best → name-token fallback (smart matcher); unmatched flagged not forced.

93. **GHL Lead Intelligence — built & verified (Phases 1-5, 2026-07-27).** Row-level GHL mirror
    (ghl_mirror: opportunities/contacts/notes → Postgres, sheet-mirror pattern, resumable throttled
    backfill, freshness, resync, opps loop) reusing the existing full-scope pit- token. Backfill:
    1342 opps/1290 open/1290 contacts/2943 notes. MIRROR FAITHFUL — full-population reconciliation
    matches GHL oracle exactly (Unresponsive 986/$2,224,500, etc.) + 6/6 row-level spot-diff on
    value+note-count. reactivation.py: deterministic stale/pitched-stalled classification (bulk
    reads), warmth rank, tracker join (email→name), reconciliation, hygiene. Result: 914
    reactivation leads/$2.35M (878 stale + 36 pitched-stalled); 159 excluded (Disqualified/Ban/Won).
    NOTES HYGIENE: 12% of reactivation leads have zero notes. ghl_notes_summary.py: grounded
    where-it-left-off (notes-only, no-notes→no backstory, cached per body-hash, 529 retry). GROUNDING
    AUDIT passed: summaries trace to real notes+dates (Stephen Snow/Giampiero), no-notes→no backstory
    (Daniel Cini), nonexistent not invented, honest degradation on timeout. Product (export-first):
    CSV + branded reactivation brief PDF (audit-logged PII exports) + EDITH handlers (which-leads/
    where-left-off/how-many-over-$X/hygiene, entity-gated). PII: no memory_facts, no plaintext logs.
    Bug fixed mid-build: short single-letter contact names spuriously matched via substring → scored
    matcher + contact dedup + bulk readers (also fixed N+1 queries). Stage-A 374/375 (1 pre-existing
    capacity drift, unrelated). Report: dashboard/GHL_LEAD_INTELLIGENCE_REPORT.md.

94. **Scoped sales dashboard role (2026-07-27).** Built the "(b) later" option: a sales-team login
    (Kalin/setters) confined to lead reactivation, no financials. SECURITY = FAIL-CLOSED: auth.py
    adds a 'sales' account (SALES_PASSWORD env, role=sales) + sales_permitted() allowlist enforced
    centrally in require_auth — a sales session reaches ONLY /leads, /api/reactivation*,
    /api/lead-lookup, /api/whoami, /logout; EVERY other authed route 403s (API) or redirects (pages),
    and UNKNOWN/future paths are denied by default (no financial surface leaks by omission). Chat is
    intentionally denied to sales (it carries the financial snapshot as context). New self-contained
    sales.html (reactivation list/filters/search/export, brand palette, no financial chrome) — 914
    cards, zero overflow. /api/lead-lookup (scoped where-left-off) + reactivation.lookup_lead +
    display_name on list items. Owner dashboard gets a Leads link. VERIFIED: scoping unit test 4/4
    (allowlist denies all financial+unknown paths); owner reaches /leads + lead-lookup (grounded) +
    still all financial endpoints; unauth 401. ACTIVATION PENDING: Rydel must set SALES_PASSWORD on
    Railway (like RYDEL_/PIOLO_PASSWORD) — until then no sales account exists (safe, no lockout);
    then run the live sales round-trip (login → leads only → 403 on snapshot/quarterly/chat).

95. **Quarterly Review v2 — Phase 0 (2026-07-27).** Audit found 5 defects + 6 gaps in the Q2 PDF.
    ROOT CAUSES: D1 LTGP:CAC shown as "$5" — _comparison_table detects money by substring ("CAC" in
    "LTGP:CAC"); fix = type-aware format registry. D2 targets "This quarter" column hardcoded "" —
    never bound. D3 volume-path flag computed twice (_flag ratio→out-of-trend in prose vs fundable
    flag→plausible in table); fix = one flag engine per lever. D4 tolerable-churn = base_mrr×(M−2) =
    total MRR when M=3, degenerate + prints without churn data; fix = bounds/availability guard →
    "not computable". D5 "held constant at $2,718 --" fragment (cac_assumption string has no subject).
    DATA FINDINGS: GHL lead-source fills 98/100, ~87% Facebook/Paid-Social → channel decomposition
    real; Meta campaign-level CPL not yet wired (aggregate only) → add campaign breakdown. 3 unmatched
    closes = name-normalization misses, surfaced in G3 smart-matcher wiring. BENCHMARK PROVENANCE:
    clients_per_delivery_hire=12 + hire_lead_time were hardcoded assumptions. RYDEL CONFIRMED:
    clients/hire = 12 (now set-by-Rydel), hire lead time = 4 WEEKS (was assumed 6). Both become
    provenance "set by Rydel 2026-07-27".

96. **Quarterly Review v2 — built & verified (2026-07-27).** Fixed all 5 defects at root + built the
    linter + 6 gaps + self-improvement infra; regenerated Q2 2026 PDF (8 pages). D1: type-aware
    quarterly_format registry (ratio renders "4.51x" not "$5"). D2: targets_current bound (shows
    $253,200/$759,600, 16/48). D3: one flag engine (volume-path == lever flag, both PLAUSIBLE). D4:
    churn "not computable — needs churn data" (degenerate figure retired). D5: "CAC is held constant
    at $2,718" (subject restored). LINTER (quarterly_linter): D1-D4 hard-fail, D5 warn; 8 adversarial
    tests; gates generation after verbatim. Caught real issues mid-build (over-broad D1 rule; opex
    delta verbatim). G1: exec summary names -$2,112 loss + -106% swing, reconciles 4.51x-yet-loss
    (ad +53%/CAC +23%/ROAS -26%). G2: opex bridge — real Xero per-line QoQ (Wages +$58,090, Closer
    Comm +$21,025, Advertising +$7,568 explain the swing); deltas computed in review (verbatim-safe).
    G4: lead-lag warning auto-fires (Jun leads 89, -18% MoM → Q3 close-risk). G5: marketing roadmap —
    channel mix (86.8% Meta), graduated ramp (253→307→343), CPL-drift band (0/+15/+30%), creative
    cadence, weekly checkpoints, sequenced Q3 actions. G6: benchmark provenance (clients/hire 12 +
    lead-time 4wk set by Rydel). G3: mrr_snapshot durable job started on boot + churn derivation from
    write-back audit wired into bridge (opening/churn legs); full bridges from first-snapshot date.
    Self-improvement: quarterly_model_store persists each model + grades prior quarter (renders from
    next gen) + linter trend. Stage-A 386/1 (pre-existing capacity drift). Report:
    dashboard/QUARTERLY_V2_REPORT.md.

97. **Test-lead exclusion — Phase 0 confirmed (2026-07-29).** Scan of both mirrors found 19 strong
    test candidates, 0 borderline. Tracker: 17 of 1291 leads (Jaspher/Test-Jas variants, Carl Test
    Account, Try [test@ email], Curry Delights [rydel in email]). GHL: 2 (rydel@ contact + Curry
    Delights). RYDEL CONFIRMED: void all 19; Curry Delights = test (void); tokens = rydel, jaspher,
    test (staff tokens match anywhere; 'test' only in test-shaped positions, else borderline→review).
    IMPACT: all-time tracker 1291→1274 (−17); Q2 2026 UNAFFECTED (test entries are 2025 + one
    2026-07-27, none in Apr–Jun); trailing-30d −1 (the 2026-07-27 Jaspher Test driving the salience
    'new lead' contamination). Confirmed list == rule output, so rules need no special-casing. NOTE:
    Team-Scorecard funnel (sales_analytics_pull) is a pre-aggregated sheet cell — can't row-filter;
    row-level cohort_funnel IS cleaned. Design: ONE classification engine (test_leads.classify) + one
    clean view per source (clean_tracker_rows + ghl read_opportunities(exclude_test)); consumers
    repoint; excluded≠deleted (audit view); overrides remembered + resync-proof.

98. **Test-lead exclusion — built & verified (2026-07-29).** ONE classification engine
    (test_leads.classify: staff tokens rydel/jaspher match anywhere; 'test' strong only in
    test-shaped positions [whole-word/test-email/GHL tag], substring-in-plausible-name → borderline
    KEEP) + ONE clean view per source (clean_tracker_rows + read_opportunities(exclude_test)).
    Repointed ALL lead consumers: leads_view._rows, range_unit_economics cohort_funnel/_ltc_in_window,
    reactivation (5 reads + tracker join), quarterly_roadmap channel_mix, payback_reconciliation,
    salience (via recent_leads). Grep-proof: raw lead reads remain ONLY in the classifier + clean
    wrappers + audit scan. Overrides (mark test/real, owner+Piolo) persisted in kv_store, outrank
    rules, resync-proof. Audit view (/api/test-lead-scan) + EDITH ('what's excluded'/'mark X
    test|real'/'add token'→confirm) + data-cleaning journal note. VERIFIED live: confirm persisted;
    reactivation clean (Curry Delights GONE, no test names, pool 914→913); recent-leads clean (no
    test/jaspher → salience won't fire 'new lead'); audit shows all 19 excluded (non-destructive).
    Fixed an N+1 (classify read rules+overrides per row → pool-exhaustion 500) by loading ctx once.
    Impact: tracker 1291→1274 (−17); Q2 2026 unaffected (test entries pre-Apr-2026 + one 2026-07-27);
    trailing-30d −1. Stage-A 386/1 (pre-existing capacity drift); +5 classification tests. Report:
    dashboard/TEST_LEAD_EXCLUSION_REPORT.md.

99. **Conversational continuity, scenarios & advisory — built & verified (2026-07-29).** Phase-0
    trace (honest): T1 "how can we reduce CAC" DID recite (unit-econ handler intercepts strategy Qs);
    T3 "3 more closes" reached the MODEL (no handler matches) which improvised the math — not the
    canonical scenario engine; no repetition guard. BUILT: scenario_engine.py (deterministic what-ifs
    over the SAME unit_economics formulas — CAC/ROAS/LTGP:CAC, ±closes/spend/comms/window, per-close
    comm-scaling variant; labelled, actuals untouched). conversation.py (active-metric thread state
    from history [carried across text+voice via resume_thread]; ADVISORY = decomposition + ranked
    levers + memory-cited principle; ANAPHORA = follow-ups → scenario engine; clarifier only on
    concrete-delta-without-metric; 'what IS X'/'back to actuals' → actual). routes: conversation.handle
    runs FIRST in both chains (before forecast/recital so '5 more closes' isn't hijacked) +
    _repetition_failure guard (verbatim repeat to a different Q → suppress+log → model gives varied
    answer). VERIFIED LIVE: T1→advisory; T2 unchanged; T3→"$2,031 ÷11, −27%, per-close variant $2,466";
    stacked scenarios coherent; ROAS metric-switch resolves correctly; forecast not hijacked; guard
    suppresses canned repeat; musing→conversation. Stage-A 397/1 (pre-existing capacity drift) + 6
    conversation tests. Report: dashboard/CONVERSATIONAL_ANALYSIS_REPORT.md.

100. **Capital Allocation layer — built & verified (2026-07-29).** The deciding organ. capital_allocation.py:
     5 NUMERIC(14,2) tables (settings/buckets/reviews/lines/deployments) + migrate() on boot (idempotent,
     6 buckets seeded via ON CONFLICT); Decimal money math (exact AUD). compute_state derives cash (real
     Xero cash_in_bank via snapshot; stale labelled) − wall = deployable surplus; idle = surplus − deployed;
     opportunity_cost = idle × assumed_return/12 (MODELLED, return labelled an ASSUMPTION everywhere).
     Ritual: run_review → assign → commit REFUSED until Unassigned==$0 (Decimal-exact, server-authoritative).
     Edge cases: cash<wall → BELOW BUFFER (no surplus, $0 cost); config unset → not_configured + config_missing
     (prompts, never invents); return<=0 → no bleed. UI: bleed hero (red, reads as loss), sacred greyed Wall,
     deployable tile, live red→green Unassigned forcing function, mark-deployed (bleed drops), history
     (assigned vs deployed). Voice: deploy/opportunity-cost/review/unassigned/set-buffer|return (confirm loop).
     Context section (text-only, real keys, assumption-labelled). Salience: idle-bleed + review-due (watermarked).
     3 self-improvement iterations logged (return>0 guard + stale caveat + no-empty-review; lean-gate context +
     clamp negative assigns; idempotency proof + null-clear settings). VERIFIED LIVE: cash $196,965.94 → bleed
     $646/mo@8%; below-buffer→no cost; commit refused@partial/committed@$0; deploy $48k→bleed halved $323/mo;
     reset to pristine. Zero date.today(). Report: dashboard/CAPITAL_ALLOCATION_REPORT.md.

101. **Capital Allocation — unresponsive-page fix (2026-07-29).** Rydel: couldn't type on the capital
     section + page went unresponsive. Playwright (clean single load) couldn't reproduce (typing +
     thread fine, no overlay, no console errors) → environmental to real usage. ROOT CAUSE: compute_state
     opened ~6 separate DB connections per call + review_history more; under the dashboard's ~10
     concurrent on-load fetches this pressured the Postgres connection pool (the SAME failure mode as
     the test-lead N+1 incident) → requests hang → page feels unresponsive / inputs lag. FIX: compute_state
     + review_history now use ONE connection each (inlined queries) — /api/capital dropped to ~0.4s.
     Plus renderCapital skips re-render while an input is focused (no mid-typing wipe). Added discard-draft
     + owner-only reset (start-over) endpoints; used reset to clear all Phase-2 test reviews/deployments →
     pristine not_configured slate (history 0, buckets preserved). VERIFIED live: real-keystroke flow
     (type buffer/return → Save → bleed hero → run review → type $50k in bucket → Unassigned updates live
     $46,966) with thread responsive, zero pageerrors.

102. **Jarvis Upgrade — Phase 0 map + push decision (2026-07-31).** HARD BOUNDARY: EDITH internal-only —
     no outbound client-contact path exists (grep-verified: no email/SMS/message send, GHL read-only);
     no client-deal loops/follow-ups (client-deal matters surface passively only). Push channel: Rydel
     chose DASHBOARD-ONLY (no Lark; flagged as the initiative limitation). Current state: P1 salience
     (10 watermarked events) exists, no open-loop store / no anomaly watch. P2 DECISIONS.md prose (109
     entries) + memory_facts exist, no structured registry / no supersession / no consistency audit. P3
     doctrine in CLAUDE.md, no SERVED_DOCTRINE.md / no systematic advisory-doctrine binding. P4 edith.js
     has substantial barge-in machinery already; no repair/register-mirror/multi-intent-completeness. P5
     /health + incident_log + freshness exist, no conversational self-state handlers. Build extends
     existing organs; land 1→5 with regression between each.

103. **Jarvis Upgrade — Pillar 1 Initiative engine LANDED (2026-07-31).** Two new modules wired into
     the existing salience→greeting path. (A) `open_loops.py` — INTERNAL/SYSTEM-ONLY open-loop store
     (kv_store-backed): "remind me to X [when]" creates a watermarked reminder that resurfaces in the
     greeting with manners at most every FOLLOWUP_DAYS(3); "drop it" kills it permanently; a reminder
     that reads like EDITH-chasing-a-client (`_OUTBOUND_CLIENT` regex) is REFUSED citing the internal-only
     boundary. Plus derived SYSTEM loops (Xero re-auth / capital buffer unset / Stripe key unset) — cheap,
     non-recursive, verbatim from real state. NO client-deal loops ever (unit-tested). (B) `anomaly_watch.py`
     — deterministic deviation vs trailing trend (lead velocity, cash movement, failed charges, loaded CPL
     7d-vs-28d via the one canonical unit_economics engine); a breach becomes a watermarked salience event
     with the deviation quantified. Reminder default importance 78 so it clears the greeting top-3.
     Router: `intent_router._COMMAND` regex so imperatives ("remind me", "drop it", "set…") are never
     misclassified as conversational rambles. BUG I introduced + fixed: salience.collect → open_loops.system_loops
     → collab.queue → action_feed.build_action_feed → salience.collect INFINITE RECURSION (hung greeting +
     action feed); fixed by making system_loops cheap/non-recursive (dropped collab.queue + test_leads.scan).
     VERIFIED live: reminder create→greeting-resurface(5.3s)→drop; "email the client" refused; action feed 13
     items; anomaly runs deterministically. Regression: tests/test_salience_location.py updated to isolate
     close/leads salience from the new loop/anomaly events (they fire legitimately on an unconfigured capital
     buffer). Push: dashboard-only (per #102). Report: dashboard/JARVIS_UPGRADE_REPORT.md. Pillars 2–5 next.

104. **Universal Advisor P1 — owner-exclusive Timeline voice bridge, ONE BRAIN (2026-08-03).** EDITH
     is now reachable from the Timeline Dashboard as a voice widget for RYDEL ONLY, double-gated:
     Layer 1 (timeline) — session cookie + user ∈ EDITH_BRIDGE_USERS ("rydel"; admin fallback
     deliberately excluded) on same-origin proxy routes; Layer 2 (this repo, dashboard/bridge.py) —
     every /bridge/* request independently validates a per-request 60s HMAC token (EDITH_BRIDGE_SECRET,
     server-to-server only, µs-precision expiry, single-use per worker, fail-closed without the
     secret; session cookies NEVER authorize /bridge/*). NO forked EDITH: the bridge delegates to the
     same extracted cores (chat_stream_response / tts_response / greeting_response) with
     channel="timeline". Conversations are now SURFACE-SCOPED (db.get_or_create_active_conversation:
     dashboard text+voice share one thread; timeline gets its own) while memory facts, recall and
     salience watermarks stay shared — proven live both directions (fact told on Timeline recalled on
     the CFO dashboard and vice versa). Rate/state buckets now key on the authenticated user (the
     "anon" shared bucket is retired). Adversarial evidence in dashboard/UNIVERSAL_ADVISOR_REPORT.md.

105. **Universal Advisor P2 — Timeline context adapter, verbatim + entity-gated (2026-08-03).**
     timeline_adapter.py reads the Timeline's token-gated /bridge/data/* API (overview, client
     detail, risk drills, signals, events, automation-status) — READ-ONLY (test-enforced no non-GET),
     figures verbatim with the Timeline's OWN freshness clock, fail-honest when unreachable ("I won't
     guess at delivery state"). Entity gates extended to timeline clients: ambiguous → ask, unknown →
     refused, pronouns → fall through to the conversation brain. Cross-domain joins compose existing
     engines only ("full picture on X" = delivery state from the Timeline + MRR/cash/package from the
     CFO snapshot, each labelled by source; NO new metric math). Fixed in passing: the pre-tier-2
     stripe alias-confirm regex was swallowing any capitalized question ("What is overdue?" → payer
     "What") — question openers now fall through (regression-tested both ways).

106. **Universal Advisor P3 — automation-health registry with POSITIVE confirmation (2026-08-03).**
     automations.py: declarative registry — 15 Timeline scheduled jobs (evidence = the APScheduler
     listener's job:* rows in integrationstatus, read over the bridge) + 4 EDITH loops (snapshot age,
     sheet_sync_state, ghl_sync_state, mrr_snapshots). States RUNNING/STALE/FAILING/UNKNOWN; an
     unreachable evidence source is UNKNOWN and NEVER counted green. Salience: failures re-fire daily
     while broken (day-bucketed watermarks); when everything is green a weekly watermarked event says
     so ("All 19 automations green") — silence is never ambiguous in either direction. Conversational
     registry truth verified live ("Are the automations healthy?" → all-19-green; "Did the sync run
     today?" → "last success 10.6h ago" matching the 6am run).

107. **Universal Advisor P4 — content review is READ-ONLY and copy-only for now (2026-08-03).**
     notion_content.py reads the Email Library / Lead Magnets / Content Pieces / Email Command Centre
     via a DEDICATED read-only Notion integration (NOTION_TOKEN on this service; GET + query/search
     only — a write POST is refused by construction, test-enforced). Review mode injects the piece's
     VERBATIM copy into the advisory context with a quote-only-this-text contract; never paraphrased
     into something it doesn't say. GHL email stats: probed 3 Aug with the existing sales-location
     key → 401 on every email/campaign endpoint → performance stats are cleanly SKIPPED and the
     review says so (copy-only). STATUS AT SHIP: NOTION_TOKEN was NOT yet present on CFOagent —
     every content path fail-honests ("integration isn't connected — I won't invent content",
     verified live) and lights up the moment the token lands. No outbound/send/publish path exists
     in either adapter (grep- and test-verified).

108. **Content review verified LIVE + a starved-recall bug fixed (2026-08-03, close-out).** With
     NOTION_TOKEN provisioned: Email Library (37 rows) / Lead Magnets (1) / Content Pieces (17) all
     REACHABLE; the "Email Command Centre" is a PAGE ("Email Marketing — Command Centre",
     3498984c-0474-81b6-b0a3-c8c5be0dc6b4) — wired in as the Newsletter-SOP RULES reference for
     critique, not a listable library. Anti-fabrication gate PASSED: 8/8 quoted strings across 3
     real pieces matched the raw Notion blocks exactly; a genuinely-empty page, empty windows and a
     nonexistent title all fail-honested; GHL stats remain 401 → copy-only reviews (accepted
     constraint). Boundary re-grepped (no write verbs, no outbound), owner gate re-confirmed.
     FOUND+FIXED pre-existing: 60 distilled facts alone blew the 8000-char memory budget, tail-
     truncating the trigram-recall section on every turn — cross-conversation recall was silently
     dead (only distilled facts crossed surfaces). Facts now cap at budget−2000; regression-locked;
     recall of the timeline review verified live on the CFO dashboard. Known gap left as-is:
     db.decay_facts still unscheduled (fact store only grows). Report:
     dashboard/CONTENT_REVIEW_VERIFICATION.md. Suites 424 green.

109. **Timeline voice overhaul — the mouth/memory/brain decomposition (2026-08-03).** Rydel's
     live verdict (hallucinates, drags, creepy, contextless) root-caused via a parity table: the
     bridge had ported the transport but dropped tuned pieces. Fixes: (MOUTH) speech_normalize.py
     runs in the ONE shared tts core so BOTH surfaces speak ear-clean (currency→words, ratios,
     acronym lexicon env-extensible via SPEECH_LEXICON, dates, eye-formatting stripped; captions
     keep eye-format); widget v2 = verbatim CFO chunker + GAPLESS WebAudio scheduled playback
     (0ms seams by construction, prefetch, generation tokens, node cleanup); measured first-audio
     0.48–0.70s. (MEMORY) timeline-channel Tier-3 turns carry a delivery-world grounding block
     (roster+risk+freshness+entity rule) — conversational delivery talk grounded, adversarial set
     green on-channel; STT confidence gate (<0.5 → "didn't catch that", no model call), self-echo
     guard, adaptive endpointing, raw transcripts logged. (BRAIN) prompts/spoken_channel.py —
     VERSIONED v2 spoken layer, parameterized per channel, supersedes inline VOICE_ADDENDUM;
     channel threaded through the chat stack. One source for voice settings confirmed (no drift
     possible). Gate + CFO voice loop regression-checked; suite 432 green. ACCEPTANCE: Rydel's
     ears (pending his click-test). Report: dashboard/TIMELINE_VOICE_OVERHAUL.md.

110. **EMAIL ENGINE — the boundary amendment + Phase A live (2026-08-04).** The standing "EDITH
     never sends" rule is AMENDED in exactly one controlled way: owner-executed sends via the
     confirmed chain (draft → Rydel approval → GHL draft read-back → recipient list displayed →
     his explicit press → count-echo confirm → execute → read-back → audit). Autonomous contact
     remains forbidden forever: v1 has no schedulers touching sends; ghl_email.send_email refuses
     without an owner chain token that cannot exist until Phase C is built (verify_chain_token
     always False) — structurally impossible, test-enforced. GHL access: dedicated GHL_EMAIL_TOKEN
     (Rydel-created; sales key untouched, reads only); location PINNED to Served Marketing
     8nmZRSNCIslNgLwJSt3h (API-verified name) with LocationViolation raised on any other location
     in any parameter — client sub-accounts structurally unreachable. Phase A shipped + live:
     email_drafts store (append-only events), grounded generation (SOP + Email Library voice +
     both Wins DBs — Google Wins now shared), THE THREE GATES (proof/link/relation) blocking
     READY_FOR_REVIEW, bridge endpoints, salience announce, pipeline-memory queries. LIVE PROOF:
     draft #1 (weekly) generated grounded and gate-passed; winback generation REFUSED (no doctrine
     documented + empty P&D cohort — never invented). OPEN: newsletter segment undefined (staging
     blocked until named); winback doctrine; timeline EMAIL board UI; Phases B/C after triple-pass.

111. **AD ATTRIBUTION ENGINE — Phases 1-2 design (2026-08-04).** Rydel confirmed at the Phase-0
     hard stop: FIRST-TOUCH default (last-touch stored + shown, labelled, never blended);
     QUALIFIED = tracker setter Call Outcome ≠ DQ (deterministic core) plus a flag-only
     validation sweep (GHL stages/notes/tracker comments disagreements FLAG for review — a
     number only changes after human review, never silently); MIN-N = 30 attributed leads or
     3 closes, KILL verdicts require the 30-lead bar, scale verdicts may fire on 3 closes;
     IG DM = a CHANNEL-LEVEL tier (lead denominator = DM contacts that entered the tracker;
     influencer/photographer/vendor DMs = explicit "IG non-lead inquiries" bucket, excluded
     from lead math, visible; borderline flagged). Tiers: ad-level / IG-DM channel / non-lead
     inquiries / unattributed. Build decisions: (a) LEAD UNIVERSE = clean tracker rows (the
     leads_view one-engine definition) — reconciliation to canonical totals is structural, not
     aspirational; (b) per-CREATIVE key = normalized ad NAME (creative identity survives the
     114-duplicate-name reality; member ad_ids listed; adset/campaign rollups from id-resolved
     members, coverage labelled) — id-first resolution order utmAdId → id-style utm_content →
     unique name → learned alias (insights name→id recovery, kv `attr:ad_aliases`, learned like
     payment aliases); (c) closes/cash per creative on the CLOSE-DATE basis (parity with
     unit_economics); cohort lead→set→show rates shown for diagnostics, labelled; (d) DEDUPE
     RULE for duplicate won rows: same email (name fallback) + same close date or same contract
     value → one deal (keep most money-complete row), duplicates surfaced as data-quality flags
     for fix-at-source, and the reconciliation identity carries the duplicates term explicitly
     so canonical totals still balance; (e) per-ad daily spend store (level=ad insights,
     meta_ad_spend_daily.json) with meta_spend's retroactive-backfill discipline, reconciled to
     the account-level engine total — test-enforced; (f) new auth surface: NONE — /cfo/attribution
     reuses _snapshot_request_authorized; media_buyer role comes in Phase 4 and ships disabled;
     (g) ads_read only, structurally: no Meta POST anywhere in the new modules (grep-tested).

## #112 — 2026-08-04 — Email engine: the four held decisions land (Rydel, verbatim)
1) Segment ladder = the S0–S5 doctrine model, encoded in segments.py (nowhere else);
   staging/sending resolve recipients ONLY through it. S4 is the sole sendable segment
   (HOT/WARM/COLD tier rules), governor 3/contact/week + 1 convert-ask/week list-wide,
   global discount lock (bonuses only — staging refuses discount language).
   Named approximation: HOT "engaged ≤30d" proxies via lastActivity/dateUpdated until
   campaign stats wire in (contacts API exposes no per-contact open/click recency).
2) Proof gate: explicitly-hypothetical math allowed (same-sentence triggers: if/say/
   imagine/suppose/roughly/for example/works out to, or per-unit build-up ×/=);
   achieved-result phrasing still holds; ambiguity holds. Hypothetical framing does
   NOT launder client names. Allowances are reported on the gate result, not silent.
3) Winback SOP: probe each run; refuse honestly while invisible. (Probed 2026-08-04:
   NOW VISIBLE, 2500 chars — winback un-gates automatically via relation_gate; still
   correctly refuses on the empty P&D cohort.)
4) Board eyeball is Rydel's; engine only guarantees it renders the live store
   (verified: 14 ready / 9 held / #1 approved).

111. **Email system COMPLETED to the send chain (2026-08-04, one-shot).** Winback verdict executed
     (skill-written → PD DB → ingest; EDITH generates weekly ONLY, GENERATABLE enforced + live-
     refusal-verified). Cadence Mon 09:00 Sydney drafts-only daemon. PD ingest with history mapping
     + cohort-block. Phase B staging live-proven (pinned location, inert draft, id-before-read-back,
     orphan adoption, honest metadata-only read-back). Phase C owner send chain shipped: live
     recipient resolution with CODE-level exclusions, count-echo confirm, single-use bound chain
     tokens, one send call site verifying its own token, full audit. Adversarially verified live to
     the empty-list boundary; a real test-segment send waits only on one tagged internal contact.
     Incidents (hotfixed, recorded): bridge-escape boot break, dropped status UPDATE, falsy-zero
     count parse. State doc updated as-built: dashboard/EMAIL_SYSTEM_STATE.md.

112. **INCIDENT + THE DEPLOY GATE (2026-08-04, ~17:20 AEST).** (Numbering note: two #111
     entries exist — the attribution design and the email completion, written by parallel
     sessions; both stand; numbering continues from here.) WHAT SHIPPED BROKEN: deploy
     750666c2 (the Phase C send-chain increment) carried a SyntaxError in
     dashboard/bridge.py:229 — double-escaped quotes (JSON-style \" inside a double-quoted
     Python string). app.py imports the bridge at module level → the whole service failed
     boot. WHY THE GATE DIDN'T RUN: a syntax error fails pytest COLLECTION, so the suite
     cannot have been green against that tree — the mid-build increment was deployed
     without it. FAIL-CLOSED HELD: no sends were possible while down, Postgres separate
     and healthy, no data lost. DOWNTIME: ~4-6 minutes (crash ~17:20 → hotfix 6b76314
     committed 17:24, live minutes later, by the same session). THE PATTERN, NOT BLAME:
     mid-build increments were deployable with zero structural check. CLOSED STRUCTURALLY:
     (a) the Railway build now runs `python -m compileall -q .` + `python -c "import app"`
     — a boot-breaking error fails the BUILD and the previous deployment keeps serving;
     (b) healthcheck instructions handed to Rydel (deploy-replacement requires a passing
     /health); (c) boot banner + enriched /health + uncaught-exception logging so a bad
     boot's last lines always name the failing module. THE RULE: no deploy without
     compileall clean + import smoke + full suite green — the build enforces the first
     two; the suite is the agent's non-negotiable pre-push step, INCLUDING mid-build
     increments. Incremental deploys are still deploys.

113. **ATTRIBUTION PHASE 3 (verdict layer) + PHASE 4 CFO-SIDE PREP (2026-08-05).** Phase 4
     (Timeline AD TRACKING section) HELD by Rydel until the timeline repo is released.
     VERDICTS (attribution_verdicts.py, pure + test-enforced): ranking metric = LTGP:CAC vs
     the registry floor (manual_targets ltgp_cac_target, default 3.0x). DOUBLE DOWN = ≥
     floor×1.1 at ≥3 closes ("every $1 here returns $X LTGP", figures in every driver).
     KILL = < floor×0.9 at ≥30 attributed leads — closes alone NEVER kill (Rydel's rule);
     zero-close sufficient-lead creatives kill only when their leads also SET below the
     account rate (lead quality IS the creative's output); if they set fine, the verdict
     names the SALES HANDOFF instead. Borderline (×0.9–×1.1) holds. Stage diagnostics per
     creative vs account baselines (denominators <3 shown, never judged) name where it
     wins/loses. CONSTRAINT CHECK: all sufficient-n creatives clear the floor → "creative
     selection isn't the constraint; volume/capacity is" + the capacity engine's worst-dept
     load; no sufficient rows → says so honestly. Nothing auto-pauses; ads_read only.
     SALIENCE: a creative NEWLY crossing to DOUBLE DOWN/KILL at sufficient n announces once
     (kv attr:verdict_crossings → salience #12, watermarked).
     PIOLO'S QUEUE (Rydel's ask): the engine publishes duplicate-won-row flags to kv
     (attr:data_quality_flags) → action_feed data_quality items → collab.queue — the
     Nirosha item appears there and SELF-RETIRES when the tracker row is fixed at source
     (each compute overwrites the list; clean source = empty; the explicit-duplicates
     reconciliation term then reads 0).
     MEDIA_BUYER ROLE (ships DISABLED): EDITH_BRIDGE_MEDIA_BUYERS env (default empty).
     A media_buyer token validates only for routes wearing require_bridge_any_role —
     today exactly ONE: GET /bridge/attribution. Every owner route 403s the role
     server-side (test-enforced: ping/email list/send all 403 romano even when enabled).
     Flip-on = setting the env var; nothing else changes.

114. **UTM TEMPLATE WAIVED; PHASE 5 ACCEPTANCE ADAPTED (2026-08-05).** Rydel: "No need on
     Romano's UTMs — proceed." Consequences, recorded so nothing nags later: (a) site-click
     ads keep carrying no UTM params → website-path leads REMAIN in the explicit
     Unattributed bucket by choice — the attribution-rate banner keeps that visible, never
     hidden; (b) the FORWARD-CAPTURE mechanism of record is the FB lead-form integration,
     which stamps utmAdId + utmCampaignId on every lead-form contact TODAY (Phase 0/2
     proven, 212 of the recent-90d ad-attributed leads) — no manual step required to keep
     it; (c) Phase 5's forward proof therefore uses a live trace of the newest real
     lead-form lead (dateAdded → utmAdId → resolved creative → tracker → engine tier)
     instead of a synthetic form submission — no test submission is made (also honours the
     no-form-POST safety rule); (d) the triple-scan runs CFO-side now; the UI-dependent
     checks (width sweep, drill-ins, EDITH's five queries, salience-once demo on screen)
     execute when Phase 4 ships. IG click-to-DM remains the largest honest gap (~43% of
     recent leads, channel-tier by design).

115. **LTC SCOREBOARD PART 1 + QUALIFIED v2 (2026-08-05).** Rydel's Phase-0 confirmations:
     (a) QUALIFIED v2 = setter Call Outcome ≠ DQ (the post-call FINAL authority) AND
     revenue band lower bound ≥ the floor (manual_targets qualified_revenue_floor,
     default $20,000/mo — "anything above 20k") AND FORM-COMPLETE (the GHL form's three
     core answers present: revenue xaOeqdkAxtwj6W8hsVgV, readiness 2WLa5ylwPluInylD1l5X,
     timeline Xu5oqFj1ulLcS83CVRBE). Revenue source precedence: the tracker "Revenue
     Range" cell wins (setter-verified); the GHL form answer fills gaps — measured:
     unknown collapses 64.1% → 4.1% of lead rows. Unknown is a visible excluded state
     (never 0, never guessed); a novel picklist value parses unknown + raises a
     data-quality flag. Setter notes stay FLAG-ONLY (the disagreement sweep keys on
     FINALISED, not the stricter qualified). IMPACT (journaled, all-time preview):
     qualified 968 → 604 (−364: 313 under-$20k, 42 revenue-unknown, 56 form-incomplete,
     overlaps possible) — the QoQ-visible change is this decision, like the test-lead
     cleaning was. (b) SCOREBOARD COLUMNS as proposed (Contracted/ROAS live in drill-in).
     (c) ROMANO'S media_buyer VIEW = FULL ROW-LEVEL (names, businesses, revenue bands) —
     reversing the aggregates-only default; the role itself still SHIPS DISABLED.
     BUILD: revenue_bands.py (exact band map); attr_contacts captures the 3 form fields;
     the engine computes qualified v2 post-join, emits per-row view rows + qualified_rule
     impact; scoreboard_view() is a RESHAPE (test: scoreboard sums == engine totals — a
     disagreement is a failing test); /cfo/attribution/{scoreboard,rows} (owner) +
     /bridge/attribution/{scoreboard,rows} (owner + media_buyer); EDITH deterministic
     queries (scoreboard / which-creative-brought-X / qualified-per-creative), entity-
     gated, refusals on unknown names. Part 2 (Timeline section) remains gated on the
     timeline repo (not reachable from this session).

116. **AD SECTION ON THE FINANCE DASHBOARD + VOICE NAVIGATION + THE SELF-MODEL FIX
     (2026-08-05).** The incident: EDITH announced the Ad B double-down, Rydel said "show
     me the ad dashboard", she claimed "text and voice only" — a false self-model (she IS
     the dashboard). Fixes, all CFO-repo (timeline untouched — not even reachable):
     (a) AD TRACKING section (#section-attribution, zone 2, nav link "Ads", g-a jump) —
     RENDER-ONLY off /cfo/attribution/{scoreboard,rows}; zero client math; confirmed
     columns, verdict badges w/ n, 30/60/90 selector, honest rows always, banner +
     constraint line, drill→row-filter, search, incremental rows. (b) VOICE NAV: SSE
     `nav` events (schema v1, nav_registry) on the deterministic path only; nav_router
     FIRST in the chain so display asks never reach the model; entity-gated drills
     (ambiguous asks, nonexistent refuses, both without action); thread-aware relative
     commands via {ui} on every chat POST; typed chat switched to the SAME stream as
     voice; timeline channel = honest cross-surface answer, zero actions (Part-2
     adoption = one else-if + a handler). (c) SELF-MODEL: persona "WHERE YOU ARE" block;
     the false line banned + structurally unreachable for nav intents; "what can you
     show me" reads the registry per surface. LESSONS THE DRIVE CAUGHT: `adtrack.js` /
     `section-ad-tracking` names were silently killed by ad-blocker filter lists —
     renamed neutral (ltcboard.js/section-attribution/ltcb-); never name ad-UI assets
     with "ad" substrings. Scoreboard sort comparator was inverted (caught on the first
     screenshot). Cold-reload smooth-scroll gets eaten by late layout inflation —
     scrollToSection re-asserts until the layout settles. Suite green; the scripted
     8-step drive passed end-to-end on production data; Rydel's voice drive is the
     acceptance.

117. **SERVED AD TRACKING — THE DEDICATED DASHBOARD at /ads (2026-08-05).** Four upgrades
     (AD_DASHBOARD_REPORT): (1) the ad section moved OUT of the finance dashboard to its
     own role-gated surface (/ads, own identity, link card left behind; voice-nav
     "show me the ad dashboard" now opens /ads in a NEW TAB with URL params carrying
     window/verdict/creative). ARCHITECTURAL SIMPLIFICATION RECORDED: the planned
     timeline copy of the section is CANCELLED — Romano uses /ads directly; the
     timeline's only remaining debt is its railway.json build gate. (2) THE TOGGLE BUG
     root-caused (fetchAll dropped re-queries while loading; untagged responses; no
     window stamps) and fixed structurally: ONE atomic /ads/api/board call per window,
     latest-wins token, response echoes its window, client guard discards mismatches
     (test-enforced), URL-persisted ?window=. Proven per window live (30d 86.2% 69/80 ·
     60d 90.9% 150/165 · 90d 272 leads — board==direct engine API on all totals + top
     rows). (3) DRILL-DOWNS: every count opens its humans — roster == count structurally
     (same engine cohort) AND live-proven 15/15 cells; person cards carry revenue band
     (unknown amber), setter outcome, pipeline stage (ghl mirror), notes LABELLED by
     source (tracker Setter Notes 91% fill / DQ Reason; GHL contact notes fetched LIVE —
     probe: 25/25 HTTP 200 — with fetch stamps), GHL contact links; "no notes recorded",
     never filler. (4) INTELLIGENCE SCORECARD: leaders row + deterministic flags
     (attribution_flags.py; 7 manual_targets thresholds, voice-adjustable; min-n inside
     each rule; severity-sorted cards with rule+numbers+question; new sev1/2 flags feed
     salience once, watermarked; EDITH: "what's flagged on the ad board?" verbatim).
     ISOLATION: media_buyer account exists ONLY when MEDIA_BUYER_PASSWORD is set (ships
     disabled); auth.py fail-closed allowlist scopes the role to /ads — the printed
     sweep 403s/bounces chat, snapshot, greeting, collab, targets, data-sources, leads;
     /cfo/* never honors sessions (401). Sales cannot reach /ads. Suite 563 green
     (17 new tests). Five-pass evidence in the report; Rydel's minute is the gate.

118. **CLOSE-COUNT INTEGRITY + THE INSUFFICIENT-DATA FIX (2026-08-05).** Phase-0 three-way
     matrix (tracker vs GHL vs Stripe, name by name) ruled on by Rydel: the SIX 30d closes
     are COMPLETE (Sam King, James Xu, Tesla Zhong, Lucas Cristofle, Glen Fitzgerald, Tony
     Thai) — the engine had been counting the tracker faithfully; AUTHORITY = the sales
     tracker counted by its Close Date (GHL stage + Stripe cash VALIDATE, flags only,
     never silently reconciled); all four classifications confirmed. FINDINGS: GHL's
     closed-won lane DEAD ~90d (ops habit — the printed rule: move the stage the same day
     the tracker records the close); 19/67 won rows have BLANK Close Dates (historical
     hygiene debt, listed for humans); 5 won rows also missing Input Date were PARSER-
     INVISIBLE (a real engine gap — FIXED: a won row with a Close Date counts as a close
     without an Input Date; non-won rows still need one); "Allan Thai" Stripe payments
     ($2,805+$550) sum exactly to Tony Thai's $3,355 recorded cash → payer alias, learned
     via the existing matcher. BUILT: close_integrity.py — the STANDING daily three-way
     matrix (kv-stamped tick in the attribution loop; tracker mirror + ghl_opportunities
     mirror + the Stripe reconcile), classified disagreements → the /ads DATA HYGIENE
     panel + the action feed (Piolo's queue, self-retiring) + salience (new sev1/2
     disagreement announces once) + EDITH "do the systems agree on closes?" verbatim.
     INSUFFICIENT-DATA FIX (gates UNTOUCHED — 30 leads/3 closes, now imported from the
     engine so they cannot fork): PROVISIONAL signal below min-n (TRENDING STRONG/WEAK/
     EARLY, dashed badges, why + "N more leads or M more closes" progress — never phrased
     or styled as a decision; adversarially tested: a 2-lead creative can never render
     DOUBLE DOWN); the AGGREGATION LADDER (batch B###_ prefix → campaign → account, same
     engine sums — roll-up == component sums test-enforced — same thresholds, so a level
     that clears n earns a REAL verdict; scorecard defaults to the highest confirmed
     level); always-valid account reads; honest empty state; 30d window guidance ("closes
     trail leads — 60/90d is the honest read"); the DEFINITIONS panel (every number's
     basis one click away).

119. **CREATIVE IDENTITY — THE HYBRID RE-KEY + JOIN CONTRACT (2026-08-05).** Phase-0
     forensics: 199 duplicated ad names across 504 member ads (full entity map incl.
     archived); SEVEN current 30d rows were silent cross-campaign merges (worst:
     B001_A05 with 7 members across 4 campaigns; 'vid 5' hiding 63 contacts + 1 close in
     one of three members); the census showed 94% of window leads already resolve by
     EXACT ad id — the distortion was the GROUPING (name-keyed rows merging exact-id
     attributions across campaigns), plus 379 all-time name-resolved contacts silently
     merged on duplicated names. RYDEL'S RULINGS: HYBRID keying (AD ID = the base key
     and the truth; name/batch/campaign = deliberate ladder levels); labels
     "Name [Campaign]"; archived/deleted members SHOWN, marked. THE IDENTITY DOCTRINE
     encoded: ids are truth, names are labels; a non-unique name match is QUARANTINED in
     the first-class __ambiguous__ row (candidates listed in the drill) — never assigned,
     never merged into certainty. BUILT: resolve_ref re-keyed (id-first keys, campaign-
     disambiguated labels, history marks); the quarantine bucket + candidates in view
     rows; the ladder gains the NAME level (the deliberate cross-campaign view; split↔
     group reconciles exactly — live-proven on B008_A04: TOF 15 leads/$1,505/1 close
     TRENDING STRONG vs Retargeting 2/$234 EARLY, name level 17/$1,739); identity_health
     (census, per-hop measured rates, exact-id degradation flag → salience) on the /ads
     hygiene strip; JOIN_CONTRACT.md (the four hops, keys, fallbacks, ambiguity rules,
     measured rates); EDITH: "how accurate is our ad tracking?" / "which ads share the
     name X?" (fabricated names refused). JOURNALED RE-STATEMENT: attributed now means
     CERTAIN — 30d attributed 69→67 with 2 moved to the ambiguous quarantine (attribution
     rate reads 83.8% vs 86.2%; the difference is honesty, not loss). Suite 579 green.

120. **DATA HYGIENE REFIX — ONE CLOCK PER VIEW + THE HONEST HEADLINE + INVARIANTS + SPEED
     (2026-08-06).** Phase-0 forensics NAMED both defects: (1) mixed bases — leads/sets on
     the Input-Date clock, closes/cash on the Close-Date clock IN THE SAME ROW → 3 creative
     + 4 ladder rows at 30d showed closes with zero leads (Tesla Zhong, Glen Fitzgerald,
     Tony Thai; Lucas Reid at 60d) — close-lag crossing window edges, inherited by every
     ladder level; (2) the "board says 1" headline was the LEADERS CARD (a single
     creative's max positioned like a window total) + the attributed-only account row —
     the engine's totals were honest all along. RYDEL RULED: BOTH bases as an explicit
     labelled toggle (LEAD-COHORT default — a lead's whole future belongs to its entry
     window; ACTIVITY — events on their own dates, earlier-lead closes annotated inline);
     headline = TOTAL closes with the tier breakdown. BUILT: basis threaded as a required
     parameter through the engine (invalid basis raises; cache keyed by basis; canonical
     cross-checks follow the active clock — activity vs the close-date authority, cohort
     vs entry-dated won rows of the same authority); the #118 no-input-date rule lives on
     the ACTIVITY clock (a cohort needs an entry date; such rows stay visible via
     hygiene); INVARIANTS AS CODE — I1 (closes≤leads per clock, activity scoped via the
     earlier-closes annotation), I2 (every close traces to a deal), I3 (tier sums == the
     headline), I5/I6 (authority + spend reconciliation), I7 (basis stamped everywhere) —
     violations mark the row integrity_error (the UI renders the honest error state,
     NEVER the contradictory number) and feed salience once; property-style seeded tests.
     HEADLINE tiles (closes/leads/cash/spend with tier breakdowns) + "Top Closing
     Creative" renamed so a per-creative max can never read as the window total. SPEED:
     the ~64s cold-window cost solved by persisted rollups keyed (basis, window) —
     stale rollups served LABELLED with a background refresh + client poll (never
     silently fresh), adjacent windows prefetched, roster GHL-notes capped to 8 inline.
     EDITH the custodian: "what basis am I looking at?" / "are the invariants green?" —
     deterministic, sourced; corrections remain confirmation-gated through existing
     mechanisms only. LIVE: I5 green on all four (basis × window) checks; the three
     phantom rows cured on both clocks; suite 584.

121. **ACTION ZONE TRIAGE — FIVE LANES, DECISIONS NOT FACTS (2026-08-06).** Phase-0
     audit: 72 items in the zone, ZERO genuine Rydel decisions among them. The flood's
     causes NAMED: (1) the same 19 blank-Close-Date facts emitted TWICE (data_quality +
     "Data integrity:"-prefixed data_integrity — the title-prefix defeated the old
     title[:60] dedup); (2) hygiene facts sitting on the decision surface; (3) 22
     per-creative ad flags each holding a line. RYDEL CONFIRMED all four rulings: the
     five-lane routing (ACTION = his decisions, ranked by dollars-at-stake, every item
     carrying a number-bearing why-line; DELEGATED = collapsed team rollups — the Piolo
     date-fix line; HYGIENE = artifacts to the hygiene panel; WATCH = quiet, ad flags
     collapse to ONE line linking the /ads scorecard; NOISE = informational events
     suppressed WITH a stated reason, auditable); cap 7 with visible overflow; $500
     auto-ACTION floor (trend anomalies promote regardless); 90d event window; ACTION
     NEVER ages out — leaves only by decision, delegation, or explicit dismiss/snooze.
     BUILT: triage.py (fact_key strips prefixes — one fact = one line; route() lanes +
     rollups + the $-ranked cap; kv triage:state for dismiss/snooze/delegate/restore —
     explicit, logged, reversible; kv triage:log = the full routing audit), the zone UI
     renders lanes with hover dismiss/snooze + expandable rollups, POST /api/triage
     (owner-only), EDITH: "show me what you suppressed" / "why is this here" /
     "dismiss|snooze|delegate|restore <item>" wired at both dispatch sites. LIVE: 72 →
     4 ACTION + 1 DELEGATED + 1 WATCH rollup; 60 routings logged, nothing deleted.

122. **FULL-STACK INTEGRITY — THE RESOLUTION DOCTRINE (2026-08-06).** Deployed-state
     check FIRST (the don't-fix-twice gate): every recent fix (#118/#119/#120) code-
     present AND live (commit cfd1822) — the brief's symptoms described the pre-refix
     board, named as already-fixed. Phantom census: ZERO on both clocks × 30/60/90d;
     the join-asymmetry suspected in the brief DOES NOT EXIST (leads and closes
     attribute through the same lead_bucket_key join; I2 makes closes ⊆ cohort
     structural). RYDEL CONFIRMED the doctrine: AUTO-FIX derives never invents (A1
     normalization · A2 exact-id re-key · A3 confirmed-alias reuse, new aliases still
     ask · A4 ↤N clock annotations · A5 self-retiring flags) with EVERY application
     logged (kv integrity:autofix_log — alias learns + reuses now log themselves);
     PROPOSED-FIX cards show evidence and wait for a human (P1 blank Close Date with a
     GHL stage-move/Stripe first-payment candidate; P2 exact-unique name link where the
     email join failed); HUMAN-FIX routed (H1 no-candidate blanks → Piolo; H2 ambiguous
     identities stay quarantined). THE HARD LINE: nothing here ever WRITES to the
     tracker, GHL, or Stripe — cards only propose what a human types; the tracker stays
     the single write-point. BUILT: resolution.py riding close_integrity's daily
     refresh; EDITH: "any proposed fixes?" / "what did you auto-fix?". LIVE: 15 of 19
     blank Close Dates got derived candidates with named sources; 1 P2 link (Fausto
     Falchi); 4 genuinely human-only. Suite 597.

123. **BAS & PAYG PREDICTION — THE QUARTERLY TAX BILL, SEEN COMING (2026-08-06).**
     Phase-0 probe (read-only, via the deployed service — Xero refresh tokens are
     SINGLE-USE; local refreshes are forbidden, they'd break production's chain):
     Activity Statement has NO public API endpoint under any scope — the LEDGER path
     is the path; line-level tax needs accounting.transactions.read (not granted,
     named as the optional addition, never assumed). Readable today: P&L, BankSummary,
     BalanceSheet (GST / PAYG Withholdings / Income Tax Payable / the physical
     BAS #2353 set-aside account), Organisation settings (GST basis CASH, period
     QUARTERLY — read from Xero, not assumed), TaxRates. Two-way QTD agreement:
     ledger +$8,818 net GST inside the P&L 10%-band $7.6–9.0k. EOFY anomaly NAMED
     (GST 6k→41k, PAYGW→0, income-tax provision 5.3k→20.9k at 30 Jun = accountant
     journals; the caveat rides every Jul-quarter decomposition). RYDEL RULED: agent
     lodgement (extended dates); ON instalments (amount pending his notice — rendered
     amount-pending, excluded from totals until "set PAYG instalment to $X", provenance
     stamped); PAYGW = his wage only ($541/wk); framing confirmed (ESTIMATES FOR
     PLANNING — the accountant lodges; never tax advice); Apr–Jun BAS (~$41.1k) is
     with the agent, due ~25 Aug. BUILT: bas_engine.py — the ONE engine (kv
     bas:estimate; daily + staggered boot tick; request paths never touch Xero);
     payment-drop assumption applied openly (adjusted+flagged+announced); zero-balance
     lines read 0 on present reports (probe-verified Xero omission), unknown on absent
     reports; drift beyond tolerance flags, never absorbs; the SET-ASIDE (spoken-for =
     GST+PAYGW+income-tax balances vs the BAS #2353 account + the cash split on the
     cash card); forecast books obligations in their DUE WEEKS (no double-count with
     manual weekly set-aside); salience T-14/T-3 (tightest band wins) + anomalies,
     watermarked, bas_due → S1 + triage-PROMOTED; EDITH full-picture/due/set-aside/
     why-moved/set-instalment/refresh at both dispatch sites, disclaimer test-enforced
     in every answer. Suite 609 (12 new).

124. **VOICE RESTORATION + MEMORY MAINTENANCE + THE SELF-IMPROVEMENT LOOP (2026-08-06).**
     THREE DEFECTS, THREE ROOT CAUSES, NAMED: D1 the ElevenLabs key on Railway is a
     legacy 64-char key — the API now rejects non-'sk_' keys (400
     invalid_api_key_prefix, traced end-to-end) → RYDEL ACCOUNT ACTION (new key into
     ELEVENLABS_API_KEY); code side ships the LOUD FALLBACK (first fallback utterance
     announces itself with the recorded reason; persistent badge; salience daily while
     broken; daily canary in the automation registry; quota warns at 85%). D2 the
     pilot-venue question was a PURE LOOP-RESOLUTION-MISS — fact #169 was stored,
     recalled, in-budget; the reminder loop had no resolution path but "drop it", so it
     re-fired every 3 days (same class live: the stale "reconnect Xero" loop #2). Fixed
     twice over: the PRE-ASK RECALL CHECK (a question-shaped reminder whose answer
     exists in memory resolves with the answer attached — never asked; the near-miss
     logged) + RESOLUTION DETECTION on every recorded user turn (a statement sharing
     the loop's distinctive words resolves it). The asked-answered class is a permanent
     regression suite. D3 decay had NEVER run; the budget invariant was broken AGAIN
     (top-60 = 7,034 chars vs 6,000) → memory_maintenance.py nightly: merge (≥0.75) /
     supersede (transition-marked) / CONFIRMATION CARDS (uncertain — never guessed) /
     demote stale low-weight to the archive tier / budget re-protected at every size.
     NEVER DELETES (grep-tested), fully journaled, 'restore memory fact #N' reverses,
     archived facts stay retrievable in recall. UPGRADE: convo_quality.py — silent
     incident capture (corrections/asked-answered/near-misses/drift/fallbacks), weekly
     self-review with trend + worst-exchange, proposals CONFIRMATION-GATED (the
     avoid-list is the only behaviour change and only on "apply proposal N"), metrics
     (incidents/100 turns; asked-answered target ZERO), EDITH honest about her own
     track record. Suite 626 (17 new).

125. BAS CALIBRATION AGAINST THE OFFICIAL EXPORT (2026-08-06). The lodged Activity
     Statement (THE 97 GROUP, Apr–Jun 2026, cash basis) is GROUND TRUTH: total $41,519 =
     net GST $19,788 + PAYGW $20,281 + PAYG instalment $1,450 — proving "amount owed" is
     the FULL obligation, never net GST alone. New kv `bas:lodged` stores official lines
     per lodged quarter (provenance journaled); lodged figures DISPLAY over any ledger
     proxy; the ledger's quarter-close figure ($41,138.08, −0.92%) is kept only as the
     calibration comparison, its $380.92 residual ITEMISED on-screen (splitting further
     needs accounting.transactions.read — not granted — or the accountant's journal;
     multi-date BS trace proved the clearing balance is a composite: EOFY sweep moved
     $29,950 PAYGW incl. $11,833 pre-April carry into GST clearing). Config updated from
     EVIDENCE: instalment_amount=$1,450 "per lodged BAS Apr–Jun 2026 (T7)"; the $541/wk
     PAYGW model is kept for recurring (ledger QTD confirms) with the lodged actual
     ($20,281, −65% model error: April's one-off $13,789 run) shown as the band. "WHAT WE
     OWE THE ATO" = THE POSITION: (a) lodged-but-unpaid (Apr–Jun UNPAID per ledger — GST
     clearing ROSE 41,138→49,956, no payment drop; due 25 Aug agent) + (b) QTD accrued +
     (c) projected remainder (labelled). Card leads with it; set-aside spoken-for =
     (a)+(b)+income-tax provision; outstanding lodged = STANDING salience 92 that never
     ages out, auto-resolves on the clearing-drop payment signal (or "mark the BAS as
     paid"). Honesty score public per quarter (estimator vs official, per component);
     divergence beyond 2× median observed error (floor 5%) flags with the component
     named. Ingest flow: scripts/ingest_bas_export.py (--seed = this export) — drop a
     new export → ingest → recalibrate. Suite 612 green (8 new BAS tests).

126. **ADS TRUTH ENGINE — REACHED TIER + CLOCK HARDENING + THE SPINE + THE NIGHTLY
     TRUTH LOOP (2026-08-07).** Phase-0 honesty: the brief assumed a pre-#116 world;
     the clock (#120) and keying (#119) were ALREADY RULED → Gate 1 skipped per its own
     rule. Diagnosis (ADS_TRUTH_DIAGNOSIS.md): CASE A's row was cured by #120 but the
     CLASS lived on in ONE path — roster() ignored the basis param (always cohort) while
     the board honored it → 5 live activity-cell↔drill mismatches, reproduced. CASE B was
     NOT a phantom — 18/18 closes ≤90d carry tracker set+show; "0 sets, 1 close" was the
     activity clock rendering cross-window lag WITHOUT the ↤ annotation closes already
     had (13 rows at 90d; cohort clean everywhere). CASE C: Fung Kwok legitimately
     qualified (fit ≠ contact) — counts: 619 all-time qualified, 229 (37%) terminal-
     unreachable. CASE D: NOT a double count — $3,355 is a standard instalment on FOUR
     distinct deals; partition clean across all six basis×window combos. RYDEL RULED:
     Option A — KEEP qualified as fit, ADD the REACHED tier (deterministic contact
     evidence: tracker set/show/close or GHL evidence ≥ thresholds, config-surfaced);
     plus all four clock fixes. BUILT: basis-aware roster + drill states its clock (the
     Case-A class killed at root, regression-locked); assert_same_basis (I11 — cross-
     clock math RAISES); activity ↤ annotations for sets/shows + deal evidence in drills
     (Case B); the activity cash strip on the cohort view (labelled, one engine); REACHED
     column (qualified ∩ contact-evidence; Fung renders qualified ✓ reached ✗; reach-rate
     flag "qualified_unreachable" at <40% config floor; sweep-backed GHL evidence cache —
     engine reads kv only); THE SPINE (I9/I12): T1 tracker → T2 GHL-appointment auto-
     derivation (journaled via the resolution engine, Piolo-queue item per derivation —
     fix at source, never patch silently) → T3 PROPOSED → T0 PHANTOM (S1-loud);
     provenance splits rendered ("2 tracker · 1 derived"), tracker never double-counts
     with derived; I8 funnel monotonicity (cohort full-chain; activity unexplained-gap
     rule) + I10 tier partition as runtime invariants; I13 single-computation-path as a
     structural test; human-legible mismatch messages (cause + clock + lane — the bare
     "report this" class deleted). THE NIGHTLY TRUTH SWEEP (ads_truth.integrity_sweep):
     invariants both clocks × 3 windows + spine census + quad-check (board rollup ·
     engine recompute · GHL validator [dead won-lane = KNOWN standing cause, surfaced
     not absorbed] · tracker authority) + reached sweep (incremental, rate-capped) →
     accuracy row (kv ads_truth:accuracy); close-level/≥$1k findings → ACTION-promoted
     feed lane; NEW cause classes auto-file a PROPOSED regression-test skeleton; a sweep
     failure is itself LOUD (kv flag → feed). EDITH: "how accurate is the ad data?"
     answers from the table with real numbers, never vibes. Suite 646 (13 new,
     case-named).

127. **ADS UX — THE INTERACTION LAYER: EVERY NUMBER IS A DOOR (2026-08-07).** Phase-0:
     I1–I13 green (sweep row 2026-08-07: 0 invariant violations) → UI work allowed. The
     clock is the RULED TOGGLE (#120) — window labels carry the ACTIVE clock, not a
     single ruled basis. Census: 20 element classes; 10 gaps built, 6 deliberate-statics
     with reasons (ADS_UX_CENSUS.md). THE MARKET MARKER RULED DETERMINISTIC — the
     tracker Market column: 100.0% coverage (1,278 Australia · 13 US · 0 blank),
     corroborated by the "Served 2026 USA Campaign" naming and phone country codes →
     the conditional gate did NOT fire. BUILT: market as an ENGINE parameter (leads-side
     filter; blank/unrecognised → the honest Unknown bucket, never a silent AU default;
     SPEND OMITTED under a filter with the reason stated — Meta spend is per-creative,
     not market-splittable; canonical re-scoped to the filtered authority; I15 partition
     AU+US+Unknown == All, test-enforced) · window All (?window=all) + HEADLINE DELTAS
     vs the prior equal-length window (same engine, second invocation, labelled, I11-
     guarded) · CLICKABLE ANOMALIES (the witnessed Sets "0 ◔1" dead-end): every ↤/◔
     badge is a door → anomaly panel (plain-English cause, the deals, tracker evidence,
     GHL link, queue state, resolution lane); the DATELESS RAIL as a first-class bucket
     (excluded ≠ deleted, self-clearing when Piolo fills dates); /ads/api/deal powers
     badge panels AND the feed↔table loop (El Gringos-class feed items now deep-link
     /ads?deal=) · THE CREATIVE DOSSIER (/ads/api/dossier, name-click + ?dossier= deep
     link): identity & delivery (Meta status + created date, LABELLED as created-not-
     first-delivery; sparkline omitted rather than faked) · unit economics window +
     all-time (one engine, min-n intact) · the lead ledger (funnel chips w/ provenance,
     GHL/tracker links, honest empty states) · SORTING: presets incl. "Lowest
     performing" (the VERDICT ENGINE's ranking, no new math), URL ?sort=, stable
     secondary spend-desc, tier rows pinned · grid FIND (presentation-only, "FILTERED
     VIEW" noted) · sticky header + frozen Creative column + a persisted column picker.
     INVARIANTS: I14 (no orphan badges — every annotation carries the door class + an
     object ref, structurally tested) · I15 (market partition) · I16 (view purity — no
     UI arithmetic on metrics, grep-enforced). Auth regression-checked on every new
     route/param. Suite 658 (10 new).

128. **ADS FUNNEL COMPLETION + DATE RESOLUTION (2026-08-08).** DIAGNOSIS FIRST
     (FUNNEL_COMPLETION_DIAGNOSIS.md): the hypothesis CONFIRMED with numbers — 237 set
     events exist, only 115 dated (122/51% dateless; Set Date filling stopped ~June);
     shows (180) have no date column; the witnessed zeros are the ACTIVITY clock
     (cohort populates); no sweep ever touched non-closing leads. Duplicate rail names
     = TWO GENUINE dateless events per contact (close AND input blank), not a bug.
     Reached "—" on Names = _aggregate()'s field list omitted reached (missing group-by
     wiring, one path). Deposit Date blank on all 19 dateless closes; Xero
     invoices/payments = CAPABILITY GAP (report scopes only, probed — reported, not
     built). TWO ENCODED CONVENTIONS (defaults, veto-able): close = the SIGNED/VERBAL
     deal-won event (#118 ruled authority, not semantics) → payment/stage dates are
     near-evidence → Stripe/GHL-stage rungs PROPOSED, never AUTO; set = the appointment
     BOOKED date (setter action); show = the appointment SCHEDULED date requiring
     kept-status evidence; input = GHL contact created date (ID-exact) → AUTO. BUILT
     (extends resolution.py + ads_truth — no parallel resolver): record_derived_date
     (journal schema REJECTS missing evidence; idempotent), supersede_derived (source
     wins; disagreement SURFACES in hygiene, never silently resolved), resolve_dates
     (input AUTO from contact-created; close stays the P1 PROPOSED lane — "apply the
     date card for X" converts a card to a journaled derivation on Rydel's word, no
     tracker write, the Piolo item persists); event_sweep (batched/cached/incremental
     GHL appointments for the 122 dateless sets — single unambiguous appointment →
     AUTO set+show dates; multiple → PROPOSED with candidates; calls counted); ENGINE
     MERGE: derived dates make events windowable NOW with provenance chips (tracker
     always wins; derived_placed terms keep the recon honest — engine == raw canonical
     + derived term, test-enforced); ladder tab parity (reached + annotations in the
     ONE aggregation — the "—" class is a named regression test); lane-lag ageing
     (per-deal "closed Nd ago · GHL stage UNMOVED", drillable, self-clearing); rail
     upgrade (grouped by contact ×N chips; "Derived (awaiting source)" collapsed
     section — visible, excluded ≠ deleted); nightly sweep gains date-resolution +
     event-sweep + supersession passes. Suite 671 (13 new).

129. **PD CONDUCTOR AUTONOMY — AMENDMENT TO #110 (2026-08-07).** The "autonomous
     contact structurally impossible" boundary is amended by the Master Spec v1.1
     two-gate model: copy requires Rydel's Approved flip AND the cohort requires
     Rydel's Launch click. Post-Launch, the pd-conductor executes the approved,
     hash-locked sequence for up to 28 days unattended. This is SANCTIONED EXECUTION
     of pre-approved contact, not autonomous contact. Any deviation from the approved
     copy or schedule voids the sanction and requires re-approval. #110's owner-only
     send chain remains binding for everything outside the PD machine.

130. **LADDER AMENDMENT TO #112 — PD_ACTIVE + PD_QUIET (2026-08-07).** Per the
     approved pd-automation-master-spec.md v1.1: contacts tagged `pd-active` (the
     "Pitched and Drifted" stage) classify PD_ACTIVE — suppressed from ALL marketing
     except campaigns registered in segments.PD_MACHINE_CAMPAIGNS; PD_ACTIVE takes
     precedence over S2's blanket freeze (S2 as first encoded suppressed the PD
     machine's own sends — the reconciliation this entry exists for). S0/S1 still
     precede it. Cycle completion (`pd-completed-YYYY-MM`, `pd-active` removed) →
     PD_QUIET: 14 days TOTAL email silence (quiet blocks even pd-machine sends),
     then S4-WARM with the tier capped WARM while the completion is recent.
     NAMED APPROXIMATION: the completed tag is month-granular, so quiet holds
     through day 21 of the following month and the WARM cap ~90 days — replaced by
     exact dates when the conductor's enrolment ledger lands. Discount lock now
     also catches "voucher" (a discount instrument in costume — Rydel's ruling).

129. **SHOW TRUTH — ATTENDANCE REQUIRES EVIDENCE (2026-08-08).** DIAGNOSIS
     (SHOW_TRUTH_DIAGNOSIS.md): live GHL vocabulary has NO completed/showed status
     (confirmed/cancelled/invalid/noshow only) — a kept-status "show" is the absence of
     a noshow flag, and setter flagging died ~June. D1 INFLATION BOUND: 18/19 derived
     shows (94.7%) rested on status alone; 1 call-evidenced; 0 outcome. D2: call
     records READABLE under current scopes (conversations/search + messages; type=1,
     meta.call.duration — sometimes null) and cover 86% of known-real conversations →
     evidence-required shows won't structurally undercount. BUILT: three tiers —
     SHOW·VERIFIED (call ≥ set_call_seconds ON/AFTER the scheduled date, ID-exact; or
     OUTCOME-EVIDENCED by a downstream close; or Rydel's word via "confirm attendance
     for <name>") · SHOW·UNVERIFIED (status-only — counted SEPARATELY everywhere:
     row/scoreboard/ladder carry shows_unverified; the show-rate flag consumes VERIFIED
     only; a PROPOSED card per unverified with the near-miss call as context — long
     calls BEFORE the scheduled date NEVER silently verify) · NOT-A-SHOW
     (cancelled/invalid/noshow → set only, unchanged). Tracker "Showed" stays AUTHORITY
     (an explicit human record). Nightly: show_verification_pass in integrity_sweep
     (later call records upgrade UNVERIFIED→VERIFIED automatically — journaled, a quiet
     positive in the feed); accuracy row gains verified_show_ratio; the hygiene rail
     gains the "Unverified shows (N)" chip (every-number-is-a-door). Call reads batched
     + cached 7d, never a location crawl. XERO RUNG: the re-consent has NOT landed
     (Invoices/BankTransactions 401 at probe) — the gap is reported, zero speculative
     code; the five bank-transfer no-evidence contacts remain the honest blind spot
     until the scopes land. Suite 683 (7 new).

131. **DATELESS-CLOSE AUTO-DERIVATION — THE PAYMENT-CLASS RULING (2026-08-08).**
     Rydel's ruling (stated twice; this entry is the encode — veto window open):
     for closes whose tracker Close Date is BLANK, ID-EXACT PAYMENT-CLASS evidence
     AUTO-derives the close date. The rungs: Stripe first payment matched by EMAIL
     (the email is the ID) → AUTO now, journaled "ruling-conversion DECISIONS #131"
     with the charge id as evidence; GHL payment/transaction objects → probed
     2026-08-08 under the current token: /payments/orders, /payments/transactions,
     /invoices all 401 "not authorized for this scope" — NO rung built (zero
     speculative code; if the scope ever lands, the rung joins this ruling); Xero
     invoice/payment → scopes still not landed (Invoices 401) — same. GHL STAGE
     timestamps remain PROPOSED FOREVER: the lane demonstrably lags — a stage move
     is when someone dragged a card, not when the deal closed. Stripe matched by
     NAME ONLY is a label match, not an ID → stays PROPOSED. Filled tracker dates
     always win (the pass runs over blanks only); supersession + surfaced-
     disagreement rules unchanged (#128); the Piolo source-fill queue item persists
     until the tracker cell is filled. Conversions are NEVER silent: each is
     journaled per deal, the batch posts ONE action-feed notice ("N close dates
     applied under DECISIONS #131 — $X placed on the clocks", 7-day retention
     through sweep rebuilds), and derived closes land on the clocks immediately
     with their derived:stripe chip (derived_placed recon terms keep reconciliation
     green). Idempotent: re-running converts nothing twice. The nightly
     resolve_dates pass carries the rung forward for future dateless closes.
     Live at encode: 15 P1 cards → 11 Stripe-backed eligible, 4 stage-only stay
     (Tommy Lê, Neri Roth Herrmann, Julieta Pablo Tadiaman, Jenny Bui).

132. **REFUND SEMANTICS — RULING R1 (2026-08-09, Rydel, audit gate close).**
     A fully-refunded Stripe charge STILL auto-derives / retains the close date
     (option (a) of drill B6 — keep as-is, zero derivation code changed).
     Rationale (encoded verbatim from the ruling): the payment cleared and the
     deal closed; a later refund is POST-CLOSE ECONOMICS — it belongs in
     churn/refund reporting, not grounds to erase a real close from the funnel.
     Cash remains tracker-authority throughout (no dollar was ever at risk in
     this lane — the Stripe rung supplies DATE evidence only). What shipped with
     the ruling: `cash_truth.refund_report()` — the lane the refund MOVES TO
     (charge id, date, amounts, fully_refunded flag; INCLUDES fully-refunded
     charges the cash view rightly drops at $0) — riding `unified_cash_view` as
     `refunds`; regression test `tests/test_refund_ruling.py` proves (1) the
     derived close date survives a full refund, (2) the refund is visible in the
     report — it moves to the right place, it does not vanish.

133. **LAUNCH LINEAGE + META-STYLE DATE CONTROL (2026-08-09).** ENCODED
     CONVENTION — **RYDEL-APPROVED 2026-08-10, no veto; the convention is now
     RULED**: "launched" = the FIRST-DELIVERY date — the first
     day Meta insights records impressions for the ad — never created_time
     (the object's birthday; secondary display only when it differs) and never
     the ad-set start_time (probe: ad sets are reused, start_times up to ~1yr
     before the ad existed). "Days running" = ACTIVE DELIVERY DAYS (days with
     delivery), never calendar days (probe: B008_A04 ran 30 active/36
     calendar; ADS 36 Rydel B 54 active/143 calendar). D1 on live data:
     created≈first-delivery on this account (24/25 identical, max 1d) — the
     REAL trap was the 90d spend-store horizon (15/25 sampled ads would
     misstate launch by 5–52d) → launch_lineage.py keeps a durable store
     (state file + kv mirror "launch:lineage"): store-censored ads get a
     ONE-TIME lifetime probe (monthly maximum sweep → daily zoom → daily
     backfill; 15/15 probed live, 0 errors); unprobed = "on or before", never
     guessed. Lineage computed ONCE in the engine (compute() attach + ladder
     _aggregate union) — hover card, dossier, and launch/active-days sorts
     read the same field (equality test-enforced); tier rows carry None.
     DATE CONTROL: ?range=YYYY-MM-DD..YYYY-MM-DD + ?clock=activity|cohort
     (basis alias kept) — a window PARAMETER over the one engine; strict
     validation (F12-immune), future end clamped to today_sydney + noted,
     start>end/future-start refused friendly; presets (Today/24h/7d/14d/30d/
     this-month/last-month/Maximum) default to the ACTIVITY clock
     (Meta-native), standard windows keep the ruled cohort default, explicit
     clock picks always win; the active clock is in every label; drills/
     rosters/dossier inherit the exact box+clock (I17 pinned on custom ranges
     both clocks); box-before-launch renders "not yet launched in this range"
     honesty notes. Sourcing: META chips on Meta-sourced columns, HYB chips on
     Meta÷engine hybrids (degrade if either side degrades) — grep-asserted no
     unlabelled Meta metric. D1/D2/D3 in dashboard/LAUNCH_DATE_DIAGNOSIS.md.

134. **CONSULT SCHEDULED-DATETIME — THE DISPLAY CONVENTION + THE APPOINTMENT-TZ
     TRUTH (2026-08-09).** ENCODED — **RYDEL-APPROVED 2026-08-10, no veto; the
     convention is now RULED**: two dates exist per set and BOTH
     stay with distinct jobs — BOOKED-ON (setter action; appointment dateAdded /
     tracker Set Date) remains the WINDOWING clock for Sets (#128, unchanged);
     SCHEDULED-FOR (appointment startTime — when the consult happens) is the
     DISPLAY beside the tracker link: "August 14, 2026, 2:30 PM", Sydney local,
     one shared formatter (consult_schedule.format_consult), provenance chip
     attached, US-market rows carry the AEST/AEDT suffix. Never swapped; never
     windowed on scheduled; never booked shown where "consult:" is labelled.
     Rebook chains: cancelled/invalid NEVER render as the consult; earliest
     upcoming beats latest past; "rebooked ×N" marks the chain. Tracker-only
     sets state "set (tracker) · no GHL appointment" — no fabricated time;
     unfetched-cache is a distinct stated state the warm passes converge to
     zero (compute() cap-20 warm + nightly). TZ TRUTH (probed, peer-confirmed
     266/266): the GHL /contacts/{id}/appointments endpoint returns OFFSET-LESS
     LOCATION-LOCAL timestamps (raw hours all business-time; the UTC reading
     put 121/130 consults 7pm–6am — absurd) — parsed as Sydney-LOCAL in
     consult_schedule.parse_appt_dt. This is the OPPOSITE of sydney_day's
     naive=UTC default (correct for Z/offset wire stamps and Postgres); the
     F8 migration's 22 appointment-sourced set/show re-derivations were
     +1-day regressions and are corrected under the triple-sweep register
     (source-aware parse + journaled re-derivation; artifact 08 carries the
     changed list; the peer session amends its own F8 claims).

135. **RENEWAL & CHURN TRUTH LOOP — THE NO-WRITE BOUNDARY (2026-08-10).**
     ENCODED RULING: **EDITH never writes the MRR contract sheet** (the Finance
     Sheet's Health tab). One writer per surface: the OWNER declares on the
     dashboard (churned / renewed / downgraded — owner-only, confirmation-
     gated, journaled, reversible); PIOLO maintains the sheet; the system's
     job is CONVERGENCE WITH RECEIPTS. The boundary is architectural — two
     writers on one document turns every disagreement into a clobber-war —
     and holds even if a Sheets write capability exists or later appears.
     Shipped: renewal_loop.py (scan engine — fresh pull, content-hash
     freshness [no Drive metadata scope exists — stated, not faked], per-
     client diffs, header-checksum SCHEMA-DRIFT guard that fails LOUD, verdict
     lanes CONVERGED / SHEET-ORIGINATED [source:sheet chip] / CONFLICT [loud,
     both values + provenance, Rydel resolves — never silently merged] /
     UNLINKED); the declare flow EXTENDS client_overrides (the 2026-07-03
     write-back — same tables, same pending-confirm contract) with the
     RENEWAL kind (new term end + optional MRR change, old_end recorded for
     conflict detection); pending declarations ride the action feed as
     data_quality items (→ collab.queue, Piolo's queue) carrying the EXACT
     sheet edit, self-retiring on convergence; declarations flow through the
     ONE engine (pull_client_health override apply) into MRR headline,
     Renewal Watch, Churn Risk, voice counts, and mrr_snapshots (forced
     same-day row on declare); chips "declared · pending sheet" → "declared ✓
     sheet". Sentinel (L2 nightly extras): nightly scan + watches (scan
     staleness >7d · pending ageing >5d · conflicts → ACTION · schema-drift
     trip). Linkage is NAME-anchored (the sheet has no ID column — D2: 40/40
     matched at build); free text matching no roster client = "not a known
     client", NO phantom clients. Extending declare rights to the piolo role
     is a FUTURE ruling — noted, not built. Tests:
     tests/test_renewal_loop.py (19, incl. the no-sheet-write grep).

136. **AD-DOMAIN TEAM ACCESS + DISCUSSION + PREVIEW LINKS (2026-08-10).**
     ACCESS — Rydel's word (the #113/#117 "until his word" condition) is GIVEN:
     the shipped-disabled media_buyer role turns ON as **ad_domain** — ONE
     role, config-driven assignees (AD_DOMAIN_USERS, default romano,isaiah,
     inna; each enabled by {USER}_PASSWORD env; MEDIA_BUYER_PASSWORD honoured
     as Romano's legacy env). Scope: every /ads surface incl. discussion
     read/write and range/clock controls; fail-closed allowlist denies ALL
     finance surfaces, card applies/PROPOSED confirms (owner-side money-truth
     actions), EDITH voice/bridge, /debug — a new endpoint cannot leak to the
     role by omission. Credentials are Rydel-issued env secrets — the agent
     never mints them (enable steps in the session report). Veto-able.
     DISCUSSION — the FIRST non-owner write surface: anchored comments (board
     | creative), author = SESSION identity only (no author parameter exists),
     CONTEXT STAMP captured server-side from the one engine for the view the
     client names (window+clock+live metrics — the observation stays
     interpretable after numbers move), one-level replies, journaled edits,
     tombstoned deletes ("comment removed by X" — excluded ≠ deleted), resolve
     collapses-not-removes, 10/user/10min rate limit, bodies escaped at every
     render, EDITH reads (never posts) via handle_discussion_recall +
     edith_context. Store: kv ads:discussion; owner feed via the
     feed:extra:ads_discussion registry channel.
     PREVIEW LINKS — preview_shareable_link rides the entity map (refreshed
     each cycle; rot self-heals to the honest "ad deleted · no preview" chip);
     shareability verified live: resolves publicly, viewing requires any
     Facebook login (Meta's design), NOT token-holder-restricted. Sentinel:
     discussion_volume + preview_rot watches in the nightly sweep.

137. **PIOLO QUEUE — MARK-DONE THAT STICKS + RELEVANCE GATING (2026-08-10).**
     Diagnosed (evidence in dashboard/PIOLO_QUEUE_DIAGNOSIS.md): the done-bug
     was (B) RESURRECTION, not a dead handler — item identity was
     slug(category+title) WITH live numbers, so metric drift re-opened
     resolved items (prod: mrr-72,275 resolved → mrr-59,316 open; "1 won
     deal…Butlers" resolved → "2 won deal…Butlers, Il Ritrovo" open) and
     resolved rows never left the render ("Resolved — verifying" nags).
     FIX — EVIDENCE-SIGNATURE DISMISSALS: signature = sha1(category +
     normalized(title) + normalized(action)) with volatile tokens (numbers,
     money, ages) DROPPED — routine drift keeps a dismissal; a genuinely new
     state (name-set/fix-path change) re-arms as a new item. Done = "I handled
     THIS state", never "hide this subject". The generator SUPPRESSES matched
     dismissals into a reversible Done view (un-dismiss restores, owner-side);
     dismissals whose flag stops reproducing auto-verify ("resolved at
     source"). RELEVANCE LANES: ACTIVE (the only counted lane — badges, EDITH,
     queue_count) · AGED (demoted, reason-stamped, collapsed, one-click
     restore): churned-subject per the lifecycle engines (#135 declarations +
     sheet non-Active + known-churned) or >90d unactioned AND immaterial ·
     DONE. MATERIALITY GUARD: money-bearing/close-level items NEVER age out
     (floor kv queue:materiality_floor). first_seen now PERSISTS per signature
     (collab_item_state) — real ages, journaled lane transitions (once, not
     per build). Excluded ≠ deleted throughout: every row retrievable, every
     transition in the collab archive. Sentinel: queue lane watch + aged-
     growth alert in L2. Tests: tests/test_piolo_queue.py (13, incl. the
     witnessed failure re-run and both re-arm directions).
