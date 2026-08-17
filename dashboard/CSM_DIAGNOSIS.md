# CSM INVESTMENT — Phase-0 diagnosis (2026-08-17)

No comp figures in this document (director figures live in owner config only;
CSM comp defaults are the published PDF table, parametric).

## Sources located

- **Workbook (`Served_Retention_CSM_Model_v2.xlsx`): NOT located** — not in
  `data/csm/` (absent), not attached to the Notion Client Success Layer page.
- **PDF tables: used** — the brief's printed regression figures (per-client,
  book, scenario table, comp table, placeholders) fully specify the targets;
  `csm_model.py` reproduces them (16 regression checks green).
- **Notion "Client Success Layer — Aussie CSM Hire" page (LOCK IN HQ)**:
  ingested as the LIVING PLAN overlay. It has evolved past the v1 model:
  TTM Aug-25→Jul-26 economics (sales $771k, refunds $41k = 5.4%), an updated
  comp band, the Monday 17-Aug run-sheet, the offer/upsell ladder v1 with
  trigger moments, the keep/kill criteria, and the margin-adjusted break-even
  (~$9.5k retained-or-added MRR at ~68% CM vs the $6.5k cost-only figure) —
  the engine surfaces both conventions.

## Sequencing state (consumed engines — all landed)

- Declaration engine (#135 wave, 08-13): `client_overrides` + `renewal_loop`
  + declare-from-the-warning UI. Kinds today: churn / downgrade / renewal.
  THIS build adds `downsell` (continuity → Served OS floor) and `expansion`
  (subtypes: stepup / sprint / ordering / reservations / photo_day /
  market_intel / second_venue / referral, with amount + first-6-month value)
  to the ONE flow. 18 enumerated touch points (preview/apply branches,
  `_sheet_reflects`, `piolo_edit_text`, `forward_projection.project()`
  branches, `finance_sheets_pull` roster apply, routes field whitelist,
  dialog JS, `mrr_snapshot` churn filter).
- Two-layer forward projection (08-13): `project()` is zero-arg by test —
  the CSM scenario is an OVERLAY module consuming its output, never a fork.
- Outflow/refunds classifier (08-14): `outflow_bands` account-first doctrine;
  "Refunds and Rebates Expense" → OPEX band. Xero per-transaction API is NOT
  wired (P&L line totals only) — B2's split uses the Xero line as the total,
  Stripe `cash_truth.refund_report` + tracker cols 35/37 for cause evidence,
  remainder flagged "unattributed — needs transaction-level Xero read"
  (registered dependency, not faked).
- Scenario engine: **no publish contract exists** — `scenario_engine.py` is
  chat what-ifs over CAC/ROAS/LTGP only. M8's "publish into the main
  projection" is BUILT here as a labelled owner-only overlay on the
  projection panel (kv-config + journal pattern), not consumed.

## Auth + confidentiality architecture (the law)

- Roles: rydel/owner · piolo/coo (FULL visibility by #113-era ruling —
  **the CSM domain is the ruled exception**, logged in DECISIONS #146) ·
  sales · ad_domain (romano/isaiah/inna, allowlist fail-closed) · legacy
  token → owner · anon. `require_owner` = the gate for every /api/csm/*;
  the /csm page uses require_auth + explicit `is_owner()` + redirect
  (require_owner would return raw JSON on a page).
- Traps encoded: `is_owner()` fails OPEN outside auth-wrapped handlers
  (never call it bare) · `/ads` substring allowlist (no "ads" in csm paths) ·
  nav_registry pages are announced to all roles (csm NOT registered) ·
  streaming handler list is separate (drill registered in BOTH).
- EDITH memory has NO scope concept. Mechanism built here: CSM answers are
  deterministic tier-2 drills (owner-gated, fall through silently for
  non-owners) + owner-only grounded context; CSM turns are excluded from
  memory persistence AND distillation (the `_cmd_sensitive` idiom, extended);
  CSM facts live in an owner-scoped kv store, never `memory_facts`.
- Non-owner output paths audited (25 enumerated): action feed, triage lanes,
  collab worklog/digest/journal (the announce-to-Piolo path — CSM never
  writes there; export audit goes to the owner-only csm journal instead),
  greeting/brief/salience, snapshot + chat context dump, briefing/quarterly
  PDFs, bridge attribution (media_buyer-reachable), memory admin UI,
  maintenance journal echo. CSM writes to NONE of them.
- Timeline bridge: `EDITH_BRIDGE_OWNERS=rydel` is the boundary (tested);
  the widget's CSM answers carry a deep link to /dashboard/csm in the reply
  text (no timeline-repo change).
- served-ship-notes: captures as ad_domain → structurally excluded from
  /csm by the allowlist; pinned by test.
- Discreet mode: none existed anywhere — built here (owner session flag,
  card + every dashboard CSM mention hidden; indicator chip while active).

## Xero payroll finding (described, not quantified)

Director comp sits INSIDE the P&L "Wages and Salaries" line as recurring
gross (the three-leg payroll journal: DR Wages gross · CR Wages Payable net ·
CR PAYG withheld) — so the offset's P&L mechanics are a reduction of the
Wages and Salaries expense line plus proportional super. April 2026 carries
a known miscoded excess (pre-Piolo-fix); windows straddling it are flagged.
**No SG percentage constant existed in the codebase** — super was modelled
only as a flat monthly baseline. This build introduces the single SG-rate
authority (`SG_RATE`, default 0.12, config-verifiable) beside
`SUPER_BASELINE_MONTHLY` in `xero_wages_categoriser.py`.

## Existing models (extended, not duplicated)

- `hiring_model` / `capacity_engine.price_hire`: affordability/cost side —
  the CSM model's NEW piece is retention-lift ROI; cost basis cross-checked.
- `forecasting_engine`: owns runway/13wk-cash; `renewal_rate_pct` assumption
  is the knob the CSM scenario moves when published (labelled what-if).
- `three_x_model`: churn-math precedent; its `_flag` discipline reused
  conceptually (stated assumptions, held constant).
- `mrr_snapshot.per_client` (forced on every declaration) = the NRR windows.
  KNOWN TRAP: `churn_mrr_in_window` reads a field `audit_log` never selects
  (reports 0.0 with events present) — bypassed, not trusted.

## Bridge fields available for the DQS proxy (K5/B5)

overview: per-client `health_score, overdue, real_breaches, open_tasks` ·
risk: `overdue / at_risk / stale` buckets · client detail: `complaints[]`
(kind, severity, created_at), onboarding_status · signals/events. NO
last-touch field exists → proxy uses the stale bucket + complaint recency;
">14 days without substantive contact" renders as "not exposed — Phase-5
item" (never faked).
