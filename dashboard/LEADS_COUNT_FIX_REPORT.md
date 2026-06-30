# LEADS COUNT FIX — "4 June leads" was a scorecard aggregate; raw is 88

**Date:** 2026-06-30 (Sydney) · Same class as the setter-comms-$500 and "16 clients" bugs:
a summary tab gave a wrong LOW number while the truth was in the raw rows.

## Phase 0 — where "4" came from vs the raw 88

| | Value | Source |
|---|---|---|
| What EDITH said | **~4** | Team Scorecard cell "Leads in" = 4 (a narrow rolling window: Leads 4 → Sets 1 → Shows 1 → Closes 2), NOT June |
| The truth | **88** | Raw Lead-to-Cash Tracker rows with an Input Date in June 2026 + a Lead Name |

**Root cause (two faults):**
1. "How many leads in June" was NOT handled deterministically — `leads_view.handle_leads_command`
   only catches "latest/recent leads" (display), returning `handled=False` for counts, so the turn
   fell through to the **free-styling model**.
2. The model grabbed the **Team Scorecard aggregate** ("Leads in = 4") from the snapshot — the
   scorecard's current narrow rolling window, not a June total — and reported it as June leads.

So the "4" is the scorecard's rolling-window lead count, never June. Real June = 88 raw rows.

## Phase 1 — deterministic lead counts from raw rows
`leads_view.count_leads(w0,w1)` counts the mirror's RAW rows by **Input Date** (a lead = any row
with an Input Date + Lead Name — Rydel-confirmed). `handle_lead_count_command` parses the range
("in June", "this month", "last week", "between X and Y", "total") via the range parser and returns
the count VERBATIM, labelled "from the raw tracker by Input Date (not a scorecard figure)".
Live cross-check: June **88**, May **109**, all-time **1,028**. The scorecard is never the source.

## Phase 2 — tie to deterministic recall
Count questions route to the deterministic handlers BEFORE the model (both /api/chat + stream):
lead counts (leads_view) and close counts (closes_view: won deals by Close Date — June = 6). The
model never generates a count. Display handlers (latest/recent lead, biggest deal) unaffected —
verified count questions don't collide with them.

275 tests pass (+2). The wrong "4" is gone; "how many leads in June" → 88.
