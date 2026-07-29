# CAPITAL ALLOCATION — the deciding layer (final report)

**Date:** 2026-07-29 (Sydney). EDITH could sense cash but not help deploy it. This adds the deciding
organ: it makes idle cash visible as a **bleeding opportunity cost** (not a safe pile), and forces
every dollar above a fixed survival buffer to have a named job via a ritual that won't commit until
**Unassigned = $0**.

## Files changed
- **`capital_allocation.py`** (new) — the one testable module: schema + `migrate()` (5 tables + 6
  seeded buckets), all compute (`compute_state`), settings/review/line/deployment persistence, and
  `handle_command()` for voice (with a mandatory confirmation loop on writes).
- `app.py` — `capital_allocation.migrate()` on boot (the per-module convention).
- `dashboard/routes.py` — `/api/capital` (state), `/api/capital/settings`, `/api/capital/review`
  (run/assign/commit), `/api/capital/deploy`; voice handler wired into **both** chat chains.
- `dashboard/chat.py` — a `CAPITAL ALLOCATION` context section (real keys, assumption labelled,
  text-chat-only so voice stays fast).
- `salience.py` — one watermarked greeting: idle-cash bleed / review-due (only when genuinely new).
- `dashboard/templates/dashboard.html`, `static/js/dashboard.js`, `static/css/dashboard.css` — the
  section: the bleed hero (red), the sacred greyed Wall, deployable surplus, the bucket panel with a
  live red→green **Unassigned** forcing function, mark-deployed, and review history.

## Migration
Name/pattern: `capital_allocation.migrate()` — module-level `_DDL` with `CREATE TABLE IF NOT EXISTS`
for `capital_settings`, `allocation_buckets`, `allocation_reviews`, `allocation_lines`,
`bucket_deployments`; seeds the singleton settings row and 6 buckets via `ON CONFLICT DO NOTHING`.
**Idempotent — confirmed:** it runs on every boot; buckets stayed at exactly **6** across repeated
deploys and an explicit double-migrate. Money columns are `NUMERIC(14,2)`; money math uses `Decimal`
(exact AUD, no float drift — e.g. $150k idle @ 8% = exactly $12,000/yr, $1,000/mo).

## The three self-improvement iterations
**Iteration 1 —** *Critique:* a non-positive assumed return would model a $0/negative bleed as if
real; stale (last-known) cash computed the bleed with no caveat in the hero; `run_review` could open
an empty draft while below buffer. *Fix:* opportunity cost only computes with a **positive** return;
the hero shows a *"cash is last-known — Xero was unavailable"* caveat when stale; `run_review`
refuses when there's no surplus. *Verified:* return=0 → opportunity cost `None`; below-buffer
`run_review` → refused.

**Iteration 2 —** *Critique:* `_build_context_block` called `compute_state()` on **every** chat turn
(needless DB round-trips on the latency-sensitive path — echoes the prior pool-pressure incident);
negative assignments were possible. *Fix:* the context section is **text-chat-only** (voice answers
capital questions deterministically before the model, so it skips the reads); `set_line` clamps
assignments to ≥ 0. *Verified:* voice intents still answer; assignment math holds.

**Iteration 3 —** *Critique:* migrate idempotency needed explicit proof; the settings endpoint
couldn't *clear* an assumption, so a value I chose during testing would linger as if Rydel's. *Fix:*
proved idempotency (6 buckets, stable); the settings endpoint now accepts an explicit null to clear a
field. *Verified:* reset to a pristine **not_configured** state — Rydel sets his own Wall first.

## Confirmed sourcing behaviour (anti-fabrication)
- **Cash = real** — `snapshot["cash_position"]["cash_in_bank"]` (live Xero BankSummary closing
  balances). If Xero is down it's last-known **and labelled stale** in the tile and the hero — never
  presented as live.
- **Assumed return = labelled an ASSUMPTION** on every surface — the hero tile *"(an assumption, not a
  guarantee)"*, the voice reply, the salience line, and the model context `NOTE`. Opportunity cost is
  always framed as **modelled**, never a fact EDITH "knows".
- **Missing config → prompts, never invents.** With buffer/return unset the state is
  `not_configured`, `config_missing` names exactly what's absent, and the tile/voice ask Rydel to set
  it. No plausible default is ever fabricated.

## The two required answers
- **If cash drops below the wall, what does the user see?** → the **BELOW BUFFER** state: *"cash $X is
  under your $Y wall — rebuild the wall before deploying"*, **no surplus, opportunity cost = $0**.
  (No negative surplus, no fabricated cost.)
- **Can a review commit with money unassigned?** → **No.** Commit is refused server-side (Decimal-exact
  `unassigned == $0.00` check) and the Commit button is disabled until Unassigned hits $0. Proven live:
  commit at partial → *"unassigned is not zero — every dollar needs a job"*; commit at $0 → committed.

## Live proof (Phase 2)
Real cash $196,965.94 → configured → bleed **$646/mo ($7,757/yr)** at 8%; below-buffer → no
surplus/no cost; **commit refused at partial**, committed at $0; deploying $48k **halved the bleed to
$323/mo** (the reward loop). Then reset to pristine.

## Non-regression / notes
Additive — one module + endpoints + one context section + one salience line + one UI panel; nothing
existing rewired. `today_sydney()`/`now_sydney()` throughout (zero `date.today()` in the diff).
Note: my Phase-2 verification left **one test review** in history (a real committed review dated
today, with placeholder allocations) — harmless; ignore it, or say the word and I'll clear it.
