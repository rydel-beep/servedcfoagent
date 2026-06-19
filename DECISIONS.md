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
