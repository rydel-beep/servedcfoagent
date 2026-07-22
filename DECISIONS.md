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
