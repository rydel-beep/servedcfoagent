# SCOREBOARD_DIAGNOSIS — date binding + contract value (2026-08-10, #140)

## Was the scoreboard windowed?
YES for the four tiles, NO for the delta. `renderHeadline()` reads
`state.board.scoreboard.headline`, and `state.board` is fetched via
`loadBoard(...windowQS())` (range+clock from the card-header control, #133) —
so Closes/Leads/Cash/Spend ALREADY move with the selected window+clock and
carry the clock label. The gap: the "vs prior" delta in `_build_board` was
gated `if not (start or end) and days in (30, 60, 90)` — it **appeared only for
standard 30/60/90 windows, never for custom ranges or Maximum**, and covered
only leads/closes/cash/spend (no contract). There is NO scoreboard-local date
control to remove — it already binds to the one control.

## The card-header control (the binding pattern to extend)
`?range=/?clock=` + the `windowQS()` builder (#133) — the grid, dossier, and
rosters all consume it. The scoreboard rides the same board fetch, so binding
is already correct for the tiles; only the delta needed to follow the window.

## Contract-value column (live tracker)
- **Column**: index 28, header "4 · MONEY (update from Stripe) Contract Value",
  detected by `"contract value"` in `tracker_cols()` → `idx["contract"]`.
- **Format**: lump dollar amounts (e.g. 5900, 6600, 10500 … max 24900), parsed
  by `_money` (strips $/comma); blank cell → `None`.
- **Blank-rate**: **4 / 68 all-time won rows (6%)** have no contract value.
- **Mapping**: same tracker ROW as the close (ID/row-anchored — the contract
  value is a field on the won lead, never name-guessed). All-time won contract
  sum: **$942,147**.

## The one engine already has it
`compute_from_inputs` parses `contract` per lead, sums `b["contract"]` per
creative, carries `sum_contract` in totals, and marks blank-contract deals with
a note. What was missing (added this wave): a `contract_missing` COUNT
(blank ≠ zero — a blank adds 0 to the total AND is counted, never a real $0),
and `contract_total`/`contract_tiers`/`contract_missing` in the scoreboard
headline. Contract value is thus defined ONCE in the engine, windowed by the
same clock as cash; the tile and the close rows READ it (I13 single-source).

## Build plan
1.1 Extend the delta to ANY selected window (custom included; all-time skipped
honestly — no period precedes "all time") and add contract to the deltas.
1.2 Headline exposes contract_total/tiers/missing; the Cash tile renders
"Cash collected $X (reconciled) · Contract $Y (tracker)" side by side — never
swapped, distinct provenance chips, the gap ("$Z outstanding") shown, and a
"N close(s) missing contract value" honest note. Contract value + the missing
note are doors (→ the closes roster; `contract_missing` is a drillable anomaly
metric). 1.3 close-roster rows already carry `person["contract"]` (None when
blank) — the JS renders it beside cash with the "not recorded" state.
