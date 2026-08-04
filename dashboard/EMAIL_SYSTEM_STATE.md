# EMAIL_SYSTEM_STATE.md — THE single source of truth for the Served email system. Future sessions read THIS FIRST; it supersedes the memory of all prior chats/sessions. (Audit: 2026-08-04, by inspection — every claim carries evidence.)

## The architecture AS IT IS TODAY

```
served-newsletter SKILL ──writes──▶ Notion EMAIL LIBRARY (status "Draft Ready")
                                          │
                                          ▼ INGEST (live, gates applied)  [email_pipeline.ingest_from_library]
EDITH generates: weekly ✓ (winback: SEE THE OPEN CONTRADICTION)          │
   [email_pipeline.generate_draft + three gates] ─────────────┐          │
                                                              ▼          ▼
                                    ONE PIPELINE STORE (Postgres email_drafts, append-only events)
                                                              │
                              ONE REVIEW BOARD (timeline ✉ Email, owner-only) + voice-approve
                                                              │ APPROVE
                                            Phase B GHL STAGING — NOT BUILT (stubs exist)
                                                              │
                                            Phase C SEND CHAIN — NOT BUILT (send refuses always)

PARALLEL LANE (skill-built, pre-dates reconciliation):
served-winback SKILL ──writes──▶ Notion PD EMAIL REVIEW DB (f38d3581…, 8 emails, cohort pd-2026-08,
  statuses Draft→Rydel Review→Approved—ready for GHL→Loaded in GHL→Sent)
  ──read-only──▶ timeline #shiproom/pd board (queue + funnel + skill mirror)
```

## Phase-1 inventory (EXISTS/PARTIAL/ABSENT + evidence)

| Surface | State | Evidence |
|---|---|---|
| Pipeline store | EXISTS — 24 drafts live: #1 weekly APPROVED, 14 READY_FOR_REVIEW, 9 DRAFTING (proof-gate holds) | /bridge/email/list 2026-08-04 |
| EDITH generation: weekly | EXISTS, gated, live-proven (draft #1) | email_pipeline.generate_draft |
| EDITH generation: content-linked | **STILL POSSIBLE — reconciliation NOT implemented** | TYPES line 40 includes it; generate accepts it |
| EDITH generation: winback | Gated off honestly (no SOP readable + cohort 0) | relation_gate winback branch |
| INGEST path | EXISTS + live-proven: 23 Library rows ingested, gates applied (14 pass / 9 held) | ingest_from_library; event log |
| Three gates on every path | EXISTS — generation ✓ ingest ✓ (run_gates both) | email_pipeline lines; 8 adversarial tests |
| Cadence job (Mon 09:00) | **ABSENT — never wired** | grep app.py/email_pipeline: no scheduler |
| ghl_email module | Pinned location (verified "Served Marketing"), token healthy; draft-create/read functions written, **UNTESTED against GHL** (Phase B) | ghl_email.py; probe 200s |
| Send path | ABSENT by construction — send_email refuses (chain tokens can't exist until Phase C); repo-wide grep: no other sender | grep A4 |
| Timeline EMAIL board | EXISTS, deployed, owner-gated (columns/preview/gates/actions) | web/email.js, deploy 6a5886e |
| Voice-approve loop | EXISTS, live-proven (draft #1 approved by echo→yes) | routes tier-1 wiring |
| PD board (#shiproom/pd) | EXISTS, deployed, read-only (queue 8 emails Weeks 1–4 + live funnel + skill mirror) | deploy c4a5ce1 |
| Route/table collisions | NONE at code level (Postgres store vs Notion PD DB; distinct routes) — the collision is ARCHITECTURAL (below) | greps |
| Notion: Winback SOP | **ABSENT** — Command Centre children are only the 2 Newsletter pages; "Winback SOP" search hits the Newsletter SOP (false positive) | C1 probe |
| Notion: Email Library | 37+ rows; newest 8 all "Draft Ready" (4 new on 8/4 — the skill IS writing); ingest trigger status = **"Draft Ready"** (locked) | C2 |
| Notion: Two Faucets package | **NOT in the Library**; its Content Piece status = "Editing" (not shipped) | C2/C3 |
| Notion: shipped-status string | **"Live"** (3 shipped pieces carry it) — locked | C3 |
| Notion: Lead Magnets | "Website to download" = bookingsplaybook.servedmarketing.com.au/download (real); Resource PDF EMPTY; page body still empty | C4 |
| GHL: newsletter tag | **ABSENT** (83 tags; nearest are lead-temp tags "cold lead"/"served - hot lead") | D1 |
| GHL: S0–S5 ladder | **NO implementation anywhere** — no tags, no custom fields | D1/D2 |
| GHL: P&D cohort | 0 contacts (winback sending idle regardless) | D3 |
| GHL: exclusions | "banned" tag + "Ban Leads (DND)" stage exist | D4 |

## Anomaly map (severity-ranked)

- **S1 — TWO WRITERS FOR WINBACK (the contradiction — HARD-STOPPED for Rydel).** Standing
  decision: "EDITH writes weekly + winback." Evidence: the served-winback SKILL already wrote 8
  winback emails (cohort pd-2026-08) into the PD Email Review DB with its own status ladder
  including "Loaded in GHL"/"Sent", reviewed on the read-only PD board — a second winback
  pipeline outside EDITH's board/staging/send chain. RECOMMENDATION: mirror the content-linked
  pattern — skill writes → PD DB is the winback source → EDITH INGESTS PD rows onto the one
  board for staging + the one send chain; dead-code EDITH's winback generation. One writer per
  type, one send path. AWAITING RYDEL.
- **S1 — content-linked generation still in EDITH's scope** (reconciliation half-implemented:
  ingest built, generation never removed). Fix: drop from TYPES; /generate refuses with pointer
  to ingest. (Fix pass, post-verdict.)
- **S2 — no cadence job**: Monday 09:00 confirmed but never wired. Fix: scheduler leg = weekly
  generation + Library-ingest watcher (content-linked); winback leg per the verdict.
- **S2 — Winback SOP still absent** despite being reported added (2×) — winback content rules
  cannot be read. Rydel item.
- **S2 — newsletter list undefined** (no tag; no ladder implementation). Verdict below.
- **S3 — Two Faucets package un-pushed** (skill session) + its episode still "Editing".
- **S3 — Lead Magnets Resource PDF field empty + page body empty** (known, standing).
- **S3 — proof-gate policy question** (illustrative math held 9 skill drafts in DRAFTING) —
  Rydel's call, standing from the last session.

## The verdicts (evidence-based)

1. **WRITER SPLIT — PARTIALLY TRUE, fix directed:** ingest exists + gates-on-ingest proven;
   content-linked generation must be dead-coded (fix pass). Winback ownership is the hard-stop
   question above.
2. **LIST VERDICT: flat `newsletter` tag is V1.** No S0–S5 implementation exists anywhere
   (tags/fields/lists inspected). The ladder stays the documented target, layered later.
   → Tristan's task (paste-ready): *"In GHL (Served Marketing sub-account): create tag
   `newsletter`. Apply it to contacts who consented to marketing email (existing clients +
   engaged leads), excluding: tag `banned`, stage 'Ban Leads (DND)', unsubscribed. This tag IS
   the send list for the weekly — nothing without it gets emailed."*
3. **TRIGGER VERDICT: content-linked = ingest-based.** Locked strings: Email Library status
   **"Draft Ready"** = ingest trigger (already implemented, case-insensitive); Content Pieces
   **"Live"** = shipped-episode status (relation gate + cadence references).

## Standing rules (unchanged, absolute)
Owner-executed sends only (boundary amendment, DECISIONS #110); pinned Served location
8nmZRSNCIslNgLwJSt3h with LocationViolation; three gates on every path incl. ingest; Notion
read-only; test-segment-only sends during build; one brain; append-only pipeline history.

## SUPERSEDED planning section (kept for history)
Fix pass (dead-code content-linked generation; cadence job; winback per Rydel's call) → Phase B
staging (needs the newsletter tag; builds against a temp internal test tag) → winback-ready
idle state → Phase C send chain → triple-pass ×3 + five-scan → EMAIL_ENGINE_REPORT.md.


# AS-BUILT UPDATE — 2026-08-04 (completion session; this section is the current truth)

VERDICT EXECUTED: winback follows the content-linked pattern. Final architecture LIVE:
  served-newsletter skill → Email Library ("Draft Ready") ─┐
  served-winback skill → PD Email Review DB (≥Rydel Review) ─┤→ EDITH INGEST (3 gates)
  EDITH weekly generation (THE only generative lane) ───────┘        │
        ONE pipeline store → ONE board (✉ Email) → APPROVE (click/voice)
        → Phase B STAGE: inert GHL draft in the PINNED Served location, id recorded
          pre-read-back, orphan adoption, read-back = existence+name verbatim (GHL's
          builder API exposes metadata only — surfaced honestly, never hidden)
        → Phase C SEND CHAIN: live recipient view (exclusions in code: DND/banned/
          no-email; winback = exactly the live P&D cohort minus banned/active clients;
          unresolvable list BLOCKS) → count-echo confirm → single-use 5-min chain token
          bound to draft+count → fresh re-resolution + count re-check → the ONE send
          call (verifies its own execution token; grep: single call site, no scheduler
          path) → SENT + audit (pressed_by/executed_by/count/definition).

- Generation: GENERATABLE=("weekly",) — content-linked + winback generation refuse with
  a pointer here (live-verified refusals).
- Cadence: Mon 09:00–09:30 Sydney daemon (kv-stamped once/day): weekly generation +
  Library sweep + PD sweep. DRAFTS ONLY — structurally cannot stage or send.
- PD reconciliation finding: all 8 pd-2026-08 rows were "Rydel Review"; Loaded/Sent
  ladder options historically UNUSED; no non-chain send path exists in code (grep both
  repos). The 8 are ingested as winback drafts, blocked DRAFTING with reason (cohort 0).
- Live verification: staging proven on draft #1 (STAGED_IN_GHL, GHL 6a71919a…, no
  duplicate); chain refusals proven live (forged token, wrong count, empty list, non-
  staged draft); recipient view resolves live and blocks honestly.
- Send testing status: the full chain is code-complete and adversarially verified to
  the empty-list boundary. An actual test-segment SEND awaits one human step: tag ONE
  internal contact `edith-test-internal` in GHL — then the board's Recipients & Send
  walks the whole chain against real internal addresses. The first REAL-list send
  remains Rydel's own act after the newsletter tag exists.
- Incidents during the build (honest record): one boot-breaking syntax error deployed
  and hotfixed within minutes (bridge echo escape); one dropped status-UPDATE caught by
  re-verification; a falsy-zero count parse bug caught by the adversarial battery. All
  fixed + regression-covered where testable.

RYDEL'S LIST (shrunken):
1. Tristan: create the `newsletter` tag (task text above) — swaps the send list from
   TEST to real by config.
2. Tag one internal contact `edith-test-internal` → then run one test-segment send from
   the board (your press, end to end).
3. Paste the Winback SOP into the Command Centre (doctrine reference — no longer a
   build blocker).
4. Push Two Faucets from the skill session when the episode ships.
5. Populate P&D when sales is ready — winback ingests are waiting, blocked honestly.
