# COMMAND-DRIVEN TARGETS / BENCHMARKS / GOALPOSTS (Category A only)

**Date:** 2026-06-24 (Sydney) · **Scope:** served-cfo-agent only. Lets Rydel set the dashboard's
manual goalposts by voice or text. ONLY values with no live source — no live metric is editable
here, no Sheets write-back. Auth-gated (only authenticated Rydel can write).

## Phase 0 — inventory of settable (no-live-source) values

All confirmed genuinely manual (agency-set goalposts, no API/source):

| Key | Default | Type | Drives |
|---|---|---|---|
| `ltgp_cac_target` | 3.0× | target | LTGP:CAC healthy line + KPI sub + month-perf bench |
| `roas_target` | 3.0× | target | ROAS status |
| `payback_target` | 30 days | target | Payback status + month-perf bench |
| `gross_margin_floor` | 45% | benchmark | Gross-margin floor + KPI sub + month-perf bench |
| `gross_margin_target` | 50% | target | Gross-margin healthy target |
| `op_efficiency_target` | 1.5× | target | Operating-efficiency status |
| `speed_to_lead_target` | 50% | target | Speed-to-lead goalpost |
| `set_to_show_target` / `show_to_close_target` | 70% / 35% | target | Funnel goalposts |
| `runway_goal` / `mrr_goal` / `cac_ceiling` | unset | goalpost | new settable goalposts |
| `growth_assumption` | unset | assumption | forecast assumption |
| `_notes` | — | note | free-form brief notes |

**Out of scope (flagged, untouched):** the MRR projection growth rates are *derived from data*
(finance_sheets_pull) — not manual, so not editable here. Live metrics (active clients, ad spend,
MRR, cash) are explicitly never settable.

## Storage + refresh-merge design

`manual_targets.py` owns a JSON store on the Railway volume (`/data/manual_targets.json`, falls
back to `state/` for local dev) — `{values: {key: {value, set_by, set_at}}, history: [...]}`.
Defaults live in code (`DEFAULTS`). `get_resolved()` returns `{key: value}` (overrides on defaults);
`get_all()` returns the full view (value, default, is_user_set, set_by, set_at, type, unit, label).

**Merge-on-refresh:** the store is SEPARATE from the snapshot. `build_snapshot()` reads it on every
rebuild (`snapshot["targets"] = get_all()`) and passes `get_resolved()` into `compute_hormozi`, so a
rebuild **never wipes a set target** — verified: set → rebuild → rebuild, the target survives both.

## Phase 1 — the update flow (voice + text, confirmation loop)

`manual_targets.handle_turn(text, token)` is called in BOTH `/api/chat` and `/api/chat-stream`
BEFORE the model — a target command short-circuits the LLM (the "local match before model" pattern).
Returns `(reply, handled)`; `handled=False` falls through to EDITH normally.

- **SET:** "set the LTGP:CAC target to 3.5", "move the gross margin benchmark to 50%", "CAC ceiling
  to 4000", "assume 8% monthly growth" → parses field + value (%, ×, $, k-suffix, days, months) →
  **echoes a confirmation** ("Setting LTGP:CAC target from 3.0× to 3.5× — confirm?") and writes ONLY
  on the next affirmative ("yes"/"confirm"/"do it"). A "no" cancels. The parsed value is echoed so a
  misheard number is caught before it's written.
- **AMBIGUITY:** "set the target to 3.5" (which target?) → EDITH asks which one, writes nothing.
- **QUERY:** "what's my LTGP:CAC target?" → reports value + "set by you / default". "what targets
  have I set?" → summary of all user-set goalposts.
- **RESET:** "reset the gross margin benchmark to default" → confirm → restores the documented default.
- **NOTE:** "note: …" / "add a note: …" → confirm → stored with set_by/set_at.

## Phase 2 — display + persistence

- KPI sub-text (`#sub-margin`, `#sub-ltgpcac`) and the Month-Performance benchmark chips read
  `snapshot.targets`, showing the **set value** + a subtle "· set by you" tag (these SHOULD be
  manual — the tag is informative, not a warning).
- **Comparisons reflect the new goalpost:** Hormozi's healthy/watch/critical classification uses the
  resolved target. Before/after example (live): LTGP:CAC value 3.21 with default target 3.0 →
  **healthy**; set the target to 3.5 → same 3.21 value now classifies **watch** (below the new line),
  and the KPI sub reads "benchmark: 3.5× · set by you". Verified the benchmark flows:
  `hormozi.ltgp_cac.benchmark` 3.0 → 3.5; `gross_margin.benchmark` 45 → 48 on set.
- Persists across refreshes (merge-on-refresh, above).

## Phase 3 — audit + management

- Every change is appended to `history[]` (field, old→new, set_by, set_at, action) in the store.
- **API (auth-gated):** `GET /api/targets` → all current values + history; `POST /api/targets/set`
  {key, value} (settings-panel direct set); `POST /api/targets/reset` {key} → default.
- **Settings panel:** `/dashboard/targets` — a self-contained auth-gated page listing every target/
  benchmark/goalpost/assumption with current value (editable, unit-aware) + default + "set by you"
  tag + Save/Reset, plus Notes and the full change-history. Discoverable via the Cmd-K palette
  ("Targets & benchmarks"). Consumes GET/POST `/dashboard/api/targets[/set|/reset]`.
- **Voice/text management:** "what targets have I set?" / "reset the X to default" also work.

## Guardrails honoured
- ONLY manual/no-live-source values; nothing live-sourced is editable (out of scope, untouched).
- Confirmation before every write; ambiguous field/value → ask, never guess.
- Persist across refresh; auth-gated writes; lean (no override/write-back machinery).
- Non-regression: Meta spend, CAC/LTGP:CAC/ROAS, ad-spend single-source, data-accuracy fixes all
  intact. 225 tests pass (+10 manual-targets).
