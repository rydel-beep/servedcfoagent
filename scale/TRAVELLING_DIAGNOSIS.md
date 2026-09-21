# TRAVELLING DIAGNOSIS — what the data can actually support (2026-09-21)

Read from production before any code. Every stage below is built only to the
level its evidence supports; anything thinner renders as a labelled state.

## What already shipped (and what gets consolidated)

| wave | state |
|---|---|
| Simulator v3 (lock-free, parity, behaviour gate) | **shipped** (#155) — this view reuses its engine + core |
| North-star block (actual · plan · required levers) on /scale | **shipped** (#155) — **CONSOLIDATED**: it becomes this view's compact summary + link; the full levers table moves here. One plan-vs-actual surface, never two |
| Compass roadmap + plan-of-record | **shipped** (#153) — supplies the "committed plan" comparator (none committed yet) |
| Hardening (server-render, boundaries, render gate) | **shipped** (#152) |
| Dashboard overhaul / TODAY page | **never ran** — no TODAY page exists. The landing's **verdict line** is the equivalent surface and gets the link |

## Stage-by-stage evidence

| # | stage | source | verdict |
|---|---|---|---|
| 1 | Ad spend | `meta_spend` daily archive + today | **full** — today labelled provisional; daily run-rate from yesterday's delivering spend |
| 2 | Leads | tracker `input_date`, ID-exact (174 MTD) | **full** |
| 3 | Qualified / unqualified / **unknown** | tracker DQ reason + revenue band (`$50k-$100k`, `$20k-$50k`, `Under $20k`) + GHL form completeness | **full** — DQ reasons present (Other 18, Wrong number 13, Budget too low 6, Tyre kicker 5…). Rows without tracker context → **UNKNOWN**, its own bucket |
| 4 | Consults booked | **GHL appointments only** | **full, GHL-led** — the tracker's Set Date column is **empty: 0 of 446 rows in 120 days** (the `set` flag exists on 116 and is used as the cross-check, not the count) |
| 5 | Consults due / upcoming | appointment `startTime` vs now | **full** — 257 appointments cached across 167 contacts |
| 6 | Showed | appointment status (confirmed 182 · noshow 14 · cancelled 58 · invalid 3) + call records + tracker outcome | **full, tiered** — verified (call ≥60s or outcome) · unverified (status only) · evidenced-by-close |
| 7 | **Pitched** | tracker closer outcome = won/lost/follow-up/pending/no-show — **no "pitched" value exists**. GHL stages DO: "Pitched and Drifted" (61) + "✅ Closed Deal" (56) | **EVIDENCED LOWER BOUND, labelled.** ghl_mirror stores the **current** stage + `last_stage_change_at` — **no stage history**, so a lead pitched and later moved to "Unresponsive/Not Interested" no longer reads as pitched. Rendered as "at least N (lower bound)" with the reason, **never inferred from shows**. A Piolo package line proposes a tracker Pitched column (a package — never a write) |
| 8 | Closed | tracker authority; **R-GAP window is STILL OPEN** (2026-07-24 → today; scope = close/contract/cash columns, lead INPUT rows continued) | **full** — the union engine's GHL-primary-inside-the-window rule applies; gap items labelled |
| 9 | Contract value signed | tracker RECOGNIZED contract cell | **full** — derived values chipped |
| 10 | Cash from new clients | **Stripe receipts only**, by receipt date, from this window's closes | **full** — R-CASH holds; all-client receipts shown only as secondary context |
| — | **Setter dials / conversations** | `ads_truth.contact_calls` (GHL conversations → messages, type 1 `meta.call`), cached 7 days, **~86% coverage of known-real conversations** (measured in that module) | **partial, cache-only.** The request path reads the CACHE and never fetches (a month's roster would be hundreds of API calls). Coverage % renders on the panel; speed-to-first-contact only where a call record exists |

## Rulings this diagnosis forces

1. **Consults booked count comes from GHL**, stated on the row — because the
   tracker column that would cross-check it has been empty since April.
2. **Pitched renders as an evidenced lower bound** (current-stage snapshot),
   never inferred from "showed". Showed-but-not-pitched is split into
   *disqualified on the call* vs *pitched-not-closed* only for the portion
   evidence supports; the rest is "not recorded".
3. **Unknown is its own bucket** and never joins unqualified.
4. **The north-star levers move here**; /scale keeps a three-line summary
   that links to this view — one plan-vs-actual surface.
5. Closes/cash inside the still-open gap window carry their labels.
