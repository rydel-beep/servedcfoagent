# Action Zone Triage — from flood to decision surface

## PHASE 0 — THE FLOOD, AUDITED (2026-08-06) — AWAITING RYDEL'S CONFIRMATION

### A · Inventory
**72 items** in the "What needs action" zone right now. Generators ranked:

| generator | items | what it emits |
|---|---|---|
| data_quality | 25 | blank Close Dates (19), MRR/sub artifact, Health-tab gaps, $0-MRR actives, blank commissions, Nirosha dup, GHL dead lane |
| attr_flag | 22 | per-creative ad-board flags ($200-ish spend / 0 leads each) |
| data_integrity | 21 | **the SAME 19 blank Close Dates again** + 2 recon lines, prefixed "Data integrity:" |
| loop | 3 | open reminders/loops Rydel himself set |
| anomaly | 1 | CPL $117 → $201 (+71% vs trailing 4-week) |

**Root cause of the flood, named:** (1) DUPLICATION — `data_quality` and
`data_integrity` both emit the blank-Close-Date census, so 19 facts render as ~40
lines; (2) NO ROUTING — hygiene facts and per-creative flags land in the decision
zone instead of the hygiene panel / ads scorecard they already live on; (3) NO
COLLAPSE — 22 creative flags each get their own line instead of one scorecard rollup.

### B · The four tests applied — five-lane classification (proposal)

**ACTION (Rydel's decisions — 2 items today, not 72):**
- CPL $117 → $201 (**+71%** vs trailing 4-week) — why-line carries the number; a
  budget/creative decision.
- Open loop: "which venue did I pick as the pilot for the reservations platform" —
  his own reminder; surfaces until answered.
- (Borderline, default-visible until ruled: "Stripe read-only key looks unset" —
  likely a STALE premise; the rk_ key is live on Railway. Proposed: verify once, then
  suppress as stale with reason logged.)

**DELEGATED (one collapsed line, not 40):**
- "23 tracker date fixes with Piolo — 19 blank Close Dates + 5 blank Input Dates
  (~$219k contract value invisible to windowed figures until fixed)". One line,
  expandable; self-retires as Piolo fills dates.

**HYGIENE (→ hygiene panel, off the decision zone — full named list):**
1. MRR $59,316 with only 1 active sub — Stripe MCP subscription-count artifact
2. 2 won deals not on Health tab: Butlers Cucina, Il Ritrovo (~$2,250 MRR understated)
3. 4 Active clients with $0 MRR: Masala Factory, At Thai, Walkway to Ceylon, Pottery Green Bakery
4. GHL closed-won lane dead (5-6 tracker closes in 30d, 0 GHL stage moves) — ops rule already printed
5. 6 won deals with blank setter commission
6. Duplicate won row: Nirosha Dushani Jayasekara ($18,300) — already in Piolo's queue
7-25. The 19 blank Close Dates individually (Vipin, Ella Ponce, Phoebe Pham, Dj,
   Tong Ou, Terry Yu, El Gringos Locos, Hiep Nguyen, Tommy Lê, Harjinder Singh,
   Johnny Ibra, Christie-Lee Gulley, Jintamani M Thoms, Nirosha Dushani Jayasekara,
   Neri Roth Herrmann, John Tamayo, Julieta Pablo Tadiaman, Aldrin Dabuan, Jenny Bui)
   — the detail behind the DELEGATED line, listed once (dedup kills the 21
   "Data integrity:" copies).

**WATCH (visible but quiet):**
- The 22 attr_flag creative lines collapse to ONE line: "22 creative flags on the ad
  board — top: G3 Graphic News $231/0 leads" linking the /ads scorecard where they
  already render with full context. Below-threshold singles stay here.

**NOISE (suppressed, reason stated, auditable):**
- Zero items today from these generators. Standing rule for when they appear:
  close/payout/lead EVENTS are information (greeting/salience), not decisions —
  suppressed from the action zone with reason "informational event", recoverable via
  "show me what you suppressed".

### C · Materiality distribution
20 of 72 items carry dollars. Top: $59,316 (artifact) · $18,300 (dup row) · $2,250 ·
$318 · then $231/$225/$224/$216/$206… median **$199** (the ad-flag cluster — each one
~$200 spend/0 leads, individually small, collectively a creative-batch question that
belongs on the ads scorecard, not as 22 separate action lines).

### D · Proposed caps and thresholds (the gate)
1. **ACTION cap: 7** ranked by dollars-at-stake; overflow visible under "more".
2. **Every ACTION item carries a number-bearing why-line** (no number → not ACTION).
3. **Dollar floor for auto-ACTION: $500**; below that → WATCH unless a rule promotes
   it (e.g. trend anomalies like the CPL spike are promoted regardless of size).
4. **Window: 90 days** for event-derived items; ACTION items NEVER age out — they
   leave only by decision, delegation, or explicit dismiss/snooze.
5. **Dedup rule:** one fact = one line; the data_quality/data_integrity double-emit
   is merged at the feed builder.
6. **Suppression is auditable:** every suppressed/routed item logs {item, lane,
   reason, ts}; "show me what you suppressed" prints it.

**Net effect if confirmed: 72 lines → ~4 (2 ACTION + 1 DELEGATED + 1 WATCH rollup),
with hygiene detail on the hygiene panel where it already belongs. Nothing deleted,
everything auditable.**

## RYDEL'S RULINGS + THE BUILD (2026-08-06)
All four confirmed: the routing as proposed · cap 7 / number-bearing why-lines /
$500 floor / 90d / never-age-out · (plus the integrity doctrine, see
FULL_STACK_INTEGRITY_REPORT). Implemented per DECISIONS #121:
- **triage.py** — `fact_key()` strips the "Data integrity:" prefix before hashing
  (one fact = one line; the double-emit dies at the source); `route()` applies the
  confirmed lane rules, the $500 floor (promoted categories exempt: anomaly, failed,
  past_due, verdict crossings, hire/threshold; Rydel's own loops always ACTION), the
  dollars-at-stake ranking, and the rollup collapses (Piolo date-fix line, team
  logging line, ad-board scorecard line). Every routing away from ACTION is written
  to kv `triage:log` with its reason — nothing is silent, nothing is deleted.
- **State** — kv `triage:state`: dismissed (logged, recoverable), snoozed (returns
  after N days), delegated (moves to the delegated lane), restore. The ONLY ways an
  ACTION item leaves besides deciding it. POST /dashboard/api/triage (owner-only);
  hover controls on the zone; EDITH takes "dismiss/snooze/delegate/restore <item>".
- **The zone UI** — decision list capped at 7 (overflow visible under "more"),
  delegated/watch rollups expandable in place, hygiene stays on the hygiene panel,
  a footer line points at the audit trail.
- **EDITH the triage partner** — "show me what you suppressed" (the full routing
  log, grouped by lane with reasons), "why is this here" (the four tests per item),
  the action verbs above; wired at both chat dispatch sites.

## LIVE VERIFICATION (production data, 2026-08-06)
72 raw items → **4 ACTION** (CPL +72% anomaly · pilot-venue reminder · Xero
reconnect reminder · the Stripe-key loop [likely stale — Rydel can `dismiss` it])
+ **1 DELEGATED** rollup (31 tracker date fixes with Piolo, detail expandable)
+ **1 WATCH** rollup (22 creative flags → /ads scorecard). 60 routings logged;
suppressed-list command answers with the full audit. Suite 597 green.
