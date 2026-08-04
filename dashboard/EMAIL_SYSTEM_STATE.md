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

## What happens next (post-verdict)
Fix pass (dead-code content-linked generation; cadence job; winback per Rydel's call) → Phase B
staging (needs the newsletter tag; builds against a temp internal test tag) → winback-ready
idle state → Phase C send chain → triple-pass ×3 + five-scan → EMAIL_ENGINE_REPORT.md.
