# CONVERSATIONAL CONTINUITY, SCENARIOS & ADVISORY MODE — report

**Date:** 2026-07-29 (Sydney). EDITH now follows the thread: strategy questions get analysis,
anaphoric follow-ups resolve against the active metric via a deterministic scenario engine, and a
verbatim repeat to a different question is caught as the routing bug it is.

## Phase 0 — the routing trace (honest)
I replayed the three-turn incident through the live pipeline:
- **T1 "How can we reduce CAC?"** → intent `command`: `_METRIC_RE` matches "CAC" → the deterministic
  unit-econ handler fires → **recites the breakdown, no analysis.** *This is the reproducing failure.*
- **T2 "Have you taken Tony Thai into account?"** → `general` (model): honest not-in-data +
  counterfactual. **Excellent, unchanged.**
- **T3 "So at an extra 3 more closes what does that look like?"** → No deterministic handler matches
  it (`_METRIC_RE`/`_COHORT_RE`/close-count all false — traced), so it **falls through to the model**,
  which — with the CAC thread in history — already resolved "that" → CAC and divided. **But that was
  model-improvised arithmetic, not the canonical one-engine scenario math**; it isn't guaranteed.
- **Repetition:** nothing prevented the same canned output twice.

So the real gaps: **no advisory path** (T1), **no deterministic scenario/thread layer** (T3 relied on
the model's luck), **no repetition guard**.

## Phase 1 — thread state + anaphora (`conversation.py`)
- **Thread state** = the active metric (CAC / ROAS / LTGP:CAC), derived from recent turns. The
  history is already carried across text **and** voice (server-side `memory.resume_thread`), so the
  thread survives both pipelines — verified.
- **Anaphora**: follow-ups resolve to the active metric with no explicit name — "an extra 3 more
  closes", "and over 60 days?", "what if ad spend halves?", "and the ratio?" (switches to LTGP:CAC).
- **Ambiguity rule**: a concrete delta with no active metric ("what about 3 more closes?" cold) → one
  clarifier ("which metric — CAC, ROAS or LTGP:CAC?"). A vague what-if with no delta falls through
  (never hijacks an MRR/runway forecast).
- **"back to actuals" / "what IS X"** → the real number, labelled — scenarios never overwrite actuals.

## Phase 2 — the scenario engine (`scenario_engine.py`, one-engine)
Deterministic what-ifs over the **same canonical formulas** as `range_unit_economics` /
`three_x_model` — no parallel math. Recomputes CAC / ROAS / LTGP:CAC under ± closes / ad spend /
commissions / window. **Second-order awareness**: commissions scale per-close by default *offered*
against the flat-hold primary. Results are spoken as hypothetical ("would be… down ~27% from the
actual…") with the assumption stated. It shares the base with the report's 3x knobs and the
forecasts (all read `unit_economics`) — one engine, three surfaces.

## Phase 3 — advisory mode
"How do we reduce/improve X" → **driver decomposition + ranked levers**, grounded in the figures:
e.g. CAC → *"$2,793 on 8 closes, driven by closer commissions $10,200 (46%), ad $9,593 (43%), setter
$2,550 (11%). Three levers by impact: (1) volume — +3 takes it to ~$2,031 (−27%), no extra spend;
(2) commission structure — [cited principle]; (3) ad efficiency — CPL/close-rate on the $9,593. Want
me to quantify any of these?"* — analysis, not recital; ends with an offer, not a lecture. Principles
are pulled from memory (never invented policy); when memory has none, the lever is stated generically
without attributing a false rule.

## Phase 4 — the repetition guard
Before a deterministic reply is emitted, it's compared to the immediately-prior assistant reply. A
**verbatim-identical repeat in response to a DIFFERENT user message** = a routing failure → suppressed,
logged, and the thread-aware/model path answers instead. The **same** question re-asked is allowed
(answered consistently, phrase-varied). In both chat + chat-stream.

## Verify (live transcript = the acceptance test)
- **T1** → advisory (components ranked, levers, offer to quantify). **No bare recital.**
- **T2** → unchanged (honest not-in-data + counterfactual).
- **T3** → *"loaded CAC would be $2,031 — (ad 9,593 + closer 10,200 + setter 2,550) / 11 closes, down
  ~27% from the actual $2,793 (holding spend/comms flat). If commissions scale per close, it's $2,466."*
  **Deterministic, canonical, labelled.**
- **Stacked**: "what's our CAC" → $2,793 actual; "what if 5 more closes" → $1,719 (−38%); "over 60
  days" → $2,563 actual at 60d; "what IS our CAC" → $2,793 actual. Coherent.
- **Metric switch**: "how's ROAS" → 13.34x; "and with double the ad spend?" → **ROAS** 6.67x (−50%) —
  resolves to the new active thread, not CAC.
- **Cold-open ambiguity** → one clarifier. **Forecast not hijacked**: "what if MRR grows 10%?" →
  forecasting. **Repetition guard**: a re-phrased CAC lookup → the guard suppressed the canned repeat,
  the model answered "same answer — $2,794…". **Musing** → conversation (three-tier intact).

## Non-regression
Additive — `scenario_engine.py`, `conversation.py`, one handler slot at the front of each chain, a
guard in the loop. `today_sydney()`; scenarios wrote nothing (actuals untouched, consistency intact).
Stage-A + 6 new conversation tests. Deterministic handlers, greetings, memory, test-lead exclusion,
three-tier routing all preserved.
