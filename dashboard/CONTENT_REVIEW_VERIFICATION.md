# Content Review — Live Verification (2026-08-03, post-provisioning)

NOTION_TOKEN landed; this is the verification record closing out the universal-advisor
build. Companion: UNIVERSAL_ADVISOR_REPORT.md (updated to LIVE). DECISIONS #108.

## Phase 0 — token + per-DB reachability

TOKEN: **PASS** — present on CFOagent (50 chars, masked), client initializes.

| Source | Status | Detail |
|---|---|---|
| Email Library `3118984c-…cbfd361` | **REACHABLE** | data_source query ok — 37 rows visible |
| Lead Magnets `a4be22d4-…a6659d` | **REACHABLE** | data_source query ok — 1 row |
| Content Pieces `927ea6f5-…eccc0` | **REACHABLE** | data_source query ok — 17 rows |
| Email Command Centre | **RESOLVED AS PAGE** — `3498984c-0474-81b6-b0a3-c8c5be0dc6b4` "Email Marketing — Command Centre" | Not a row database: a knowledge page holding the Newsletter SOP + offer-strategy child pages (readable, 43 blocks). Wired in as the RULES reference — newsletter critique now grounds against the actual SOP text (`_rules_copy`). |

No unshared DB remains — **nothing left for Rydel to connect.**

## Phase 1 — real reviews + the verbatim proof (the anti-fabrication gate)

Live review through the owner bridge: *"Review the slowest weeknight email with me…"* →
full advisory critique (hook ranking, structure vs the Hormozi shape, a weak line called
out, Newsletter-SOP checklist including the stale "Fri 29 May 2026" send date, the
`{{CTA_URL}}` placeholder check).

**Verbatim validation — every quoted string grep'd against the raw Notion blocks:**

| Piece | Quoted strings checked | Result |
|---|---|---|
| Email "Your slowest weeknight is an ad targeting goldmine" | "The Tuesday problem nobody fixes" · "Look at your POS, not your ads" · "That's not the algorithm. That's deliberate spend timing." · "Fri 29 May 2026" · "{{CTA_URL}}" | **5/5 exact** |
| Email "The frequency cap most restaurants miss on Meta" | subject "How often is too often?" · body opening "If the same person sees your venue's ad 11 times in a week, you're not advertising. You're harassing them." | **2/2 exact** |
| Content Piece "Low Season Hits and You Pause Marketing" | "Low season hits. Bookings slow down." (asked for the email copy's opening — she correctly skipped the editor-note preamble) | **1/1 exact** |

Zero mismatches, zero paraphrase-drift, zero invented lines.

**Fail-honest paths, all on REAL data:**
- Lead magnet "Restaurant Owner's Guide to Profitable Ads": the Notion page genuinely has
  **0 body blocks** → *"the body of that page didn't come through … the content is blank
  on my end"* — refused to review, suggested checking the page. (For Rydel: the guide's
  copy isn't in the Notion page body — if you want her reviewing it, paste the copy into
  the page.)
- Empty windows: *"Nothing edited in the Lead Magnets in the last 30 days"* (true — the
  row predates the window); email list honours asked windows (fortnight/month) after a fix.
- Nonexistent piece ("Midnight Taco Blitz October Mega Sale") → *"That one's not in the
  library"* — refused, asked what he actually meant.
- GHL stats: still 401 with existing access → reviews are copy-only and the context block
  says so (accepted constraint).

## Phase 2 — boundaries + integration re-verify

- **Grep proof (both repos):** no `requests.put/patch/delete` and no Notion
  create/update/append/archive in `notion_content.py` / `timeline_adapter.py`; non-query
  POST refused by construction (test-enforced); repo-wide outbound sweep (smtp/sendgrid/
  twilio/slack/telegram/send/publish/schedule_send) — zero matches; all 8 timeline
  `/bridge/data/*` routes are GETs. The internal-only refusal untouched.
- **Owner gate re-checked live:** admin session → `{"enabled":false}` + 403 on chat;
  EDITH `/bridge/ping` direct → 403 no-token, 403 bad-token.
- **Cross-surface:** review done on the Timeline recalled on the CFO dashboard —
  **after fixing a real pre-existing bug this check exposed** (below).
- **Suites: 424 passed, 0 failed** (8 new content/memory tests included).

## Found & fixed: recall was silently starved (pre-existing)

The cross-surface check initially failed. Persistence was fine (all 60 timeline messages
in conv 19) and trigram search returned the review at sim 0.46 — but the recall block
was 8044 chars against an 8000 budget: the 60 accumulated distilled facts alone consumed
it, and the "Relevant earlier discussion" section appended after them was tail-truncated
on EVERY turn. Cross-conversation message recall had been dead-on-arrival whenever the
fact store was full; only distilled facts (e.g. the Chiangmai pilot decision) crossed
surfaces. Fix: facts cap at budget−2000 with an explicit "older facts trimmed" marker;
regression test locks the recall section surviving a bloated store. Re-verified live:
the CFO dashboard now recalls the timeline review (title + main flag, verbatim).
Related known gap (pre-existing, unchanged): `db.decay_facts` is never scheduled — the
fact store only grows; worth wiring into a loop in a future session.

## Close-out — what remains

- **Rydel:** nothing blocking. Optional: paste the lead-magnet guide's copy into its
  Notion page body if it should be reviewable; the GHL email-stats limitation stands as
  an accepted constraint (copy-only reviews) unless a location with email access is
  provided; the widget mic/speech UX click-test in Chrome is still his to do.
- **Recommended next build:** the **Timeline security hardening pass** (prompt spec in
  UNIVERSAL_ADVISOR_REPORT.md §Follow-up — ungated /internal/sync + /internal/event-alerts
  and the unauthenticated /api data routes are the standing exposure).
- **Outstanding truth-check:** the system audit (registry-driven verification of every
  automation's evidence chain) remains the right deeper follow-up after hardening.
