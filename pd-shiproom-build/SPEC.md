# SPEC — "Pitched & Drifted" section for the Shiproom (timeline dashboard)

Target repo: **timeline dashboard**. This spec + assets live with the task
in the cfo agent repo; the timeline dashboard repo must be present in the
workspace before the run.

## Context (2 lines)

Leads who were pitched, said yes, then stalled get dragged into the
"Pitched and Drifted" GHL stage and receive a 4-week win-back email cycle
(6 proof emails → 🎁 offer → bump). Copy is drafted by the `served-winback`
Claude skill and reviewed in Notion before anything is loaded into GHL.
This section makes the whole system visible in one place.

## Rule zero — discovery before code

Read the timeline dashboard repo first. Match its existing stack, design
tokens, routing, and section patterns exactly. Introduce NO new framework,
no new styling system. The PD section must look native next to the
existing Shiproom sections. Do not modify or delete any existing section.

## The section: "Pitched & Drifted" — three blocks

### Block 1 — Email Queue (live from Notion)

Source: Notion data source `f38d3581-8844-4249-aea2-8e041be37e41`
(PD Email Review DB, under the "Pitched & Drifted — Win-Back Hub" page).

- Show the latest cohort (highest `pd-YYYY-MM` value in the Cohort select).
- Group by **Week** (Week 1–4), sort by **Scheduled** ascending.
- Per row: Email Name, Scheduled date, Subject, Status badge, link to the
  Notion page (row URL).
- Status badge colours: Draft grey · Rydel Review yellow ·
  Approved — ready for GHL green · Loaded in GHL blue · Sent purple.
- The offer entry (Email select = "E7 — Offer") renders visually
  distinguished — 🎁 marker + accent border, matching how the Notion entry
  is distinguished.
- Data access: server-side only via `NOTION_TOKEN` env var (Notion
  internal integration; Rydel shares the Win-Back Hub with it once). The
  token must NEVER reach client code. If the site is static, fetch at
  build/deploy time; follow whatever data pattern the repo already uses.
  Every render carries a "Data as of <timestamp>" stamp.

### Block 2 — Cohort Funnel (manual data v1, honest about freshness)

GHL stats are NOT automated yet (poller is a later build). v1 reads a
committed file `data/pd-stats.json`:

```json
{
  "lastUpdated": "2026-08-25",
  "cohort": "pd-2026-08",
  "funnel": { "inStage": 0, "opened": 0, "clicked": 0, "replied": 0, "booked": 0 },
  "perEmail": [
    { "email": "E1", "sends": 0, "openRate": null, "clickRate": null, "replies": 0 }
  ]
}
```

- Render funnel left→right with counts; per-email open/click table below.
- `null` renders as "—", never as 0. Always show `lastUpdated` prominently
  ("GHL stats last updated <date> — manual weekly export"). Never imply
  live data.
- Seed the file with the empty August structure above.

### Block 3 — Winback Engine (skill mirror page)

- Commit `served-winback-SKILL.md` (provided alongside this spec) into the
  repo and render it on a subpage titled "Winback Engine — skill mirror".
- Banner at top, verbatim: "Mirror for reference. The installed Claude
  skill is the executable source of truth. When the skill changes, this
  file is re-exported — never edited here."

### Link rail (all three blocks share it)

- Notion: Win-Back Hub (`app.notion.com/p/3b18984c04748107b3fef38ccb5b7bc3`),
  PD Email Review (`app.notion.com/p/ae913f24cf3c48a8934b2e96e0ea7c95`),
  PD Monthly Offers (`app.notion.com/p/adb62e8546e74999a6c108f1198f2c0a`)
- Asana build task:
  `app.asana.com/1/1206296132789863/project/1207106039441848/task/1217105130859893`

## Acceptance criteria

1. PD section reachable from the Shiproom's existing nav, styled native.
2. Email Queue renders the real August cohort (8 entries, grouped Week
   1–4) from Notion server-side; row links open the Notion pages; 🎁 offer
   entry visually distinguished.
3. Funnel block renders from `data/pd-stats.json` with the freshness stamp
   and em-dashes for nulls.
4. Skill mirror page renders with the banner.
5. `NOTION_TOKEN` referenced from env only — grep confirms it never
   appears in client bundles.
6. No existing section, route, or file removed or visually changed.
7. Mobile-safe at ~380px.

## Guardrails (inherit Edith's standing rules)

Git checkpoint before starting and after each block. No file deletion.
Plain-English summary of everything changed in MORNING-REPORT.md,
including any assumption made where this spec was silent.
