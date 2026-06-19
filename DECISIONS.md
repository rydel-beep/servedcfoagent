# DECISIONS

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
