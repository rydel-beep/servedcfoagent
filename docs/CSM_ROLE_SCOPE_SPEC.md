# CSM — Dashboard Role Scope (Phase 5 · DESIGNED, NOT ENABLED)

Status: **spec only**. No `csm` role exists in the auth layer today and none
is created by this build. When enabled (post-hire, Rydel's word, separate
session), the role is provisioned like the existing role users — named
identity, no shared credentials with other roles.

## What the CSM role SEES

- **Her scoreboard** — K1 NRR on her book, K2 continuity, K3 expansion,
  K4 onboarding, K5 health visibility, K6 systemisation milestones — the
  same numbers the owner sees for these tiles, because she is paid on them
  and every variable line must be calculable by her.
- **Ladder calendar** — her book's term dates, month-4 lock dates, renewal
  dates, rung due this week/month, tier.
- **Her comp accrual** — itemised by event (renewal / lock / step-up /
  sprint / continuity save / referral / NRR bonus), clawback-aware, beside
  the note "payroll truth = what's paid".
- **Her book** — client list with tier, term, health score (Phase-5),
  offer log readback.

## What the CSM role NEVER sees

- Company finance: P&L, cash, runway, MRR beyond her book's own numbers,
  refunds ledger, any owner tile.
- The CSM investment MODEL: ROI clocks, scenarios, funding paths, the 4×
  solve, baselines beyond her own targets.
- The director comp offset — not as a number, not as a concept surface.
- Any other identity's queues, feeds, or EDITH channels.

## Mechanics (when built)

- Fail-closed: the role starts with ZERO routes and each surface above is
  explicitly granted; anything unlisted 403s.
- Her surfaces are read-only except: nothing. All writes stay in GHL
  (her system of work) and the owner declaration flow (money truth).
- The confidentiality matrix in the weekly security replay gains a `csm`
  row the day the role is enabled: /csm and every owner CSM surface → 403.
- EDITH for the CSM role (if ever enabled) answers only from her granted
  surfaces; owner-scope facts stay invisible (the existing scope mechanism).

## Timeline-native CSM panel (outline, for the Timeline session)

- RAG health board (worst-first) · today's rungs (ladder calendar slice) ·
  overdue-deliverable translator ("what to tell the client, what's on
  Miguel") · complaint queue with response SLA · renewal runway (next 60
  days of term ends) · her comp accrual readback.
- Data: Timeline-native + the GHL ingestion spec fields; NO finance-
  dashboard calls beyond her granted read endpoints.
