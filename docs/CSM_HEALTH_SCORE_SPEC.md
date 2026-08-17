# CSM — Client Health-Score Spec (Phase 5 · DESIGNED, NOT BUILT)

Status: **spec only** — for the Timeline-repo session, post-hire. Until this
exists, the finance dashboard renders the DQS **proxy** (bridge fields:
overdue deliverables, complaint recency, stale accounts) with the explicit
"proxy — formal DQS is Miguel's COO scorecard" label. No comp or ROI
content here.

## Inputs (per client)

| Input | Source | Notes |
|---|---|---|
| `days_since_substantive_contact` | GHL `cs_cadence_last_touch` (Phase-5 pipeline) / Timeline activity | "substantive" = call, meeting, or a reply-bearing thread — not a broadcast |
| `delivery_overdue_count` | Timeline (existing bridge field) | overdue deliverables vs Welcome Kit timeline |
| `complaint_recency_days` | Timeline complaints signal | days since last complaint; ∞ if none |
| `results_trend` | client reporting data (bookings/orders/covers, 30d vs prior 30d) | −1 / 0 / +1 banded |
| `payment_status` | Stripe/Xero | current / late / failed-charge present |
| `engagement` | meeting attendance + email response rate (90d) | the Nonna's lesson: never attended = silent churn risk |

## Score

Weighted sum → 0–100. Weights are CONFIG (owner-tunable, journaled), not
code. Suggested starting weights: contact 25 · overdue 20 · complaints 20 ·
results 15 · payment 10 · engagement 10.

RAG thresholds (config): GREEN ≥ 70 · AMBER 40–69 · RED < 40.
Any single hard signal forces a floor: failed charge → max AMBER;
complaint within 7 days → max AMBER; no substantive contact > 30 days → RED.

## Rules

- Score is computed, never hand-set. The CSM's own `cs-at-risk` tag renders
  BESIDE the computed score — disagreement is signal, not error.
- Every score renders with its inputs (no unexplained number).
- Missing input → that component excluded and the score labelled degraded
  (never fabricated).
- History kept (weekly snapshots) so "at-risk recoveries run" is measurable
  (K5) and recoveries are evidence-linked.

## Consumers

- Timeline-native CSM panel (her operating view — RAG board, sorted worst-first).
- Finance dashboard /csm K5 tile: % of book with a health score, >14-day
  no-contact list (owner-only), at-risk recoveries.
- EDITH: "which clients are at risk and why" — inputs, not vibes.
