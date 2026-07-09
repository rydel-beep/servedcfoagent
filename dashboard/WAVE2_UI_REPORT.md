# WAVE 2 — DECISION-ZONE UI RE-ARCHITECTURE (build report)

**Date:** 2026-07-09 (Sydney). Read the frontend SKILL.md first. Built on a committed, stable
front-end base (the accumulated layering/stripe-reconcile/null-key-fix WIP was committed first).

## What shipped
1. **Stable base first** — committed the coherent uncommitted front-end WIP (`7f0a0b8`): the z-index
   LAYERING system (ambient HUD / orb / scrim / chat lanes), a **null-key fix** in chat.py (it read
   active_clients keys that don't exist → EDITH had no roster in voice mode — audit Pattern 1),
   Stripe reconciliation, refresh cadence. Screenshot-verified; caught + fixed a **mobile orb overlap**
   (`4fea0fa`) where the orb covered the brief on phones.
2. **4 decision zones** (`applyZones()`, safe DOM relocation — no fragile HTML block moves):
   - ZONE 1 **Am I safe** — cash on hand (no longer buried below brief/exec/actions/kpis), cash
     runway forecast, forward MRR.
   - ZONE 2 **Is the machine working** — MRR, unit economics, funnel, capacity, commissions, cohort…
   - ZONE 3 **What needs action** — the consolidated **Action Feed** + the previously-scattered
     alerts (actions, verdicts, deficiency, dq-loss, churn, stripe-health, reconciliation).
   - ZONE 4 **Where are we going** — the MRR projection (base/best/worst).
   Numbered eyebrows encode the real decision sequence; headers stay quiet, panels stay the focus.
3. **Made the Wave-0/1 backends visible:**
   - **Action Feed panel** (Zone 3) renders `/api/action-feed` — one ranked list (S1>S2>S3) with a
     plain-language action each, replacing scattered warnings.
   - **Cash runway forecast** (Zone 1) + **MRR scenarios** (Zone 4) render `/api/forecast` — every
     figure tagged PROJECTION with its adjustable assumptions (renewal rate shown).
4. **Theme + responsive** — CSS derived from the harbour-navy HUD palette; zone grid collapses to one
   column at <=768px; forecast/action panels legible on 390px.

## Verified live (Playwright, desktop 1440 + mobile 390)
4 zones with correct titles; Action Feed + both forecast panels populated; **0 page errors** desktop
and mobile; mobile single-column; the mobile orb no longer covers content.

## Client updates handled (2026-07-09)
Rydel: Noodle Asia re-signed (~$4.2k+GST, 6mo, OG price) and Bluebells will re-sign. Both are
RENEWALS refuting the historical 0/12 (0%) renewal rate. Set the forecast **renewal-rate assumption
to 25%** (live) — MRR base moved from −$3,782/mo to −$616/mo (near flat). They still need entering in
the Health sheet (source of truth; the write path is churn/downgrade only) to flow into MRR/count.
The Action Feed already flags "3 Active clients with $0 MRR: Bluebells…" and "4 won deals not on
Health tab".

## Follow-ups (not blocking)
- Fine per-section ordering within Zone 2 can iterate.
- The 4 recent closes + the two re-signs need Health-sheet entry (bookkeeping).
- A future refinement: taper cash-forecast recurring inflow with the MRR projection.
