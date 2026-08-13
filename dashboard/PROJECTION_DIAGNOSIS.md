# PROJECTION DIAGNOSIS — the dead sliders + the unclearable warnings (2026-08-13)

## The slider: what it was

ONE physical control (`#resign-slider`, dashboard.html:193) on the Forward
Projection panel — a pre-renewal-wave scenario widget. Its model
(`_computeForwardModel`, dashboard.js): take the RECOGNIZED-tab forward
months and add back `resignPct%` of each month-over-month DROP, cumulatively,
into a cash-balance table/chart. The "adjustable (inflow / collection /
renewal)" tags on the Zone-1/Zone-4 forecast cards promise further controls
that DO NOT EXIST anywhere in the DOM — mockup-promises.

## Why dead (evidence)

1. **Wiring is present but brittle**: `initForwardSlider()` attaches an
   `input` listener directly to the node and re-renders only when
   `currentSnap` is set; the handler chain re-enters a 200-line innerHTML
   rebuild + a Chart.js redraw (CDN-loaded — absent Chart kills the chart
   silently). Any runtime error in that chain, or a missing/late snapshot,
   leaves the slider visually inert. The exact runtime failure in Rydel's
   session was not reproducible without his browser console — stated
   honestly, not guessed.
2. **The model cannot show what the slider claims even when it runs**: the
   uplift applies ONLY to month-over-month drops (`drop > 0` gate) — month 0
   never moves, flat stretches never move, and the whole computation is
   display-side widget math (a one-engine violation) that predates
   declarations: it has no concept of committed vs assumed, no per-client
   terms, no declared actuals.
3. The live curve today (Aug $77.2k → Sep $69.7k → … → Jan $0) would have
   shown SOME movement if the handler fired — which corroborates a
   handler/render-level failure in the witnessed session, not a flat-curve
   illusion.

## Verdict: REPLACE

The orphan is unsalvageable as the assumed-layer control: its math is
widget-local, drop-gated, and layerless. The panel body is replaced by the
two-layer engine (`forward_projection.py` — committed from sheet recognition
+ declarations; assumed = the undecided pool × the renewal assumption) with
purpose-built controls: a renewal-assumption slider bound by DOCUMENT-LEVEL
delegation (immune to node moves/replacement), re-rendering engine-computed
curves via the engine's stated formula (`assumed[m] = pool[m] × pct/100`) —
no widget re-derivation. The forecast cards' false "adjustable" tags are
corrected to name where the real controls live.

## The unclearable warnings (the second witnessed bug)

`finance_sheets_pull` already applies a declared renewal to `contract_end`
(so Churn-Risk/at_risk clears), BUT `renewal_watch` membership keys on
months-elapsed-since-the-ORIGINAL-sheet-start (`elapsed >= 4`), which a
renewal declaration never resets — so the warning survives every
declaration. Fix: a live/recent renewal declaration RE-BASES the term (new
start = the declared start date); the client leaves the watch and re-enters
when the NEW term ages past the lead time (the cycle). Churn-declared
clients already leave the active set; both now land in a browsable
`renewal_watch_cleared` archive with their declaration (excluded ≠ deleted).
