# CAPACITY & HIRING INTELLIGENCE — Phase 0 (data inventory + judgment inputs) — HARD STOP

**Date:** 2026-07-09 (Sydney) · **Status:** HARD STOP for Rydel's benchmarks + mapping before build.

## 1. Team / payroll data (SALARY tab — 18 people)
Columns present: LAST, FIRST, ROLE, DEPARTMENT, STATUS, AUD, PHP. **Missing: start-date, last-raise
date** (needed for raise tenure signals — Rydel adds columns OR seeds once via voice/panel).
Departments (headcount): **SMM 6**, **C-LEVEL 5**, **MEDIA 3**, **PAID ADS 2**, **PR 1**, **TECH 1**.
Mis-tags to confirm: "Creative SMM" and "Bookkeeper" sit under C-LEVEL. Sales team (Kalin closer,
Coby/Maran setters) is **commission-only, NOT on SALARY** — so salaried-hiring affordability excludes
them; sales capacity is a separate (optional) scope.

## 2. Client-assignment data — NONE
No column maps clients → team members in the Health roster or the Lead-to-Cash Tracker (checked both
headers). → **Per-person workload is PHASE 2** (needs an assignment column or a future Asana/Timeline
wire). **Department-level load proceeds now** (active clients ÷ dept headcount vs benchmark).

## 3. Velocity + churn — computable per window ✓
Closes (one-engine): **30d = 6, 60d = 14, 90d = 16**. Churn: the Health roster has an **End Date**
column (col 5) → churned-per-window is derivable (End Date in window / Status→Finished), plus chat
`client_overrides`. **Net velocity = closes − churn** is computable per window. Active clients: **38**.

## 4. Existing infrastructure to build ON (not from scratch)
`team_model.build_team_model` (dept→function, headcount, cost) and `hiring_model.compute_hiring_analysis`
(already uses the 40% rule + binding_constraint) exist — I'll extend these, keeping one-engine
consistency (MRR/payroll/velocity from their single engines).

## HARD STOP — judgment inputs needed (the engine's hinge; I won't guess capacity)
Asked via the questions below: SMM delivery capacity, ads-manager capacity, load threshold + hiring
lead time, acceptable churn rate. Confirmations (defaulting unless you change them): 40% payroll:MRR
gate STANDS; payroll basis = the one-engine true_team_cost (~$29.7k/mo incl. owner gross); sales
excluded from salaried hiring; per-person load = phase-2 (no assignment data); last-raise/start-date
to be seeded. All benchmarks stored via the manual-inputs pattern, labelled "set by you", voice-adjustable.

---

## Built — the engine (Rydel's defaults locked 2026-07-09)
**Benchmarks (kv_store, "set by you", voice-tunable):** SMM full-time 7 / part-time 4.5 clients ·
ads 10 accounts/manager · trigger 85% at 5-week lead · churn gate >2/mo · **40% payroll:MRR ceiling**
on `true_team_cost`.

**Formulas (`capacity_engine.py`, all one-engine deterministic):**
- Department load % = active clients ÷ (Σ per-status capacity). SMM cap = FT×7 + PT×4.5.
- Net velocity = closes (unit_economics) − churn (roster End Date + chat overrides), per 30/60/90d.
- Hire trigger fires when projected load at (now + 5wks) ≥ 85% (or already over); shows 30d vs 90d,
  flags small-sample noise.
- Hiring budget = MRR × 40% − payroll. Priced hires: new ratio, budget fit, MRR gap if over, PHP↔AUD.
- Constraint check: churn/mo vs gate; when elevated, LEADS with retention math (the "don't hire, fix
  the leak" output). Ranked levers, priced.
- Raise signals: tenure-since-raise (seeded — not in the sheet), dept load, affordability; priced
  5/10/15%. NEVER a merit verdict — framing states performance is Rydel's call.

**Live values at build:** SMM **110% load** (38 ÷ 34.5) — hire signal; hiring budget **−$6,632/mo**
(payroll:MRR **50.5%** incl. owner gross, 35.1% team-only) — over the 40% ceiling, so the engine
honestly says "no room yet; MRR needs $79.9k". Churn contained (0/90d) → capacity drives the call.

**Conversational (Tier 2, deterministic):** "when do I need to hire", "hiring budget", "can we afford
a new SMM at 35k PHP" (priced, no longer misroutes to targets), "who's closest to capacity", "who's
due for a raise" (+ performance-is-your-call framing), "should I hire or fix churn", "set SMM
capacity to N". Surfaced via `/api/capacity` (owner-only). Salience: a firing hire trigger is a
watermarked greeting event.

## Honest boundaries held
Department-level load only (no client→person data — per-person is **Phase 2**, needs an assignment
column or Asana wire); raises are signals + pricing, never verdicts; morale never claimed as
measured; salaries owner-only — `capacity_engine` never calls `record_turn` or logs salary figures.

## Phase 2 (documented, not faked)
Per-person workload needs a client-assignment source. Ads load uses total active clients as an upper
bound (ads-client count isn't tracked — flagged, settable). Last-raise dates to be seeded once.
