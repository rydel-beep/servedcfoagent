# RESPONSIVE LAYOUT OVERHAUL — report

**Date:** 2026-07-21 (Sydney). Structure only — the harbour-navy HUD palette + type are unchanged.
Acceptance authority = the rendered width sweep + live resize (screenshots in
`dashboard/verification/responsive-layout/`), not test counts.

## Phase 0 — the rigid layout (evidence)
**Before width sweep — horizontal overflow at 9 of 10 widths** (`documentElement.scrollWidth` vs
viewport):

| width | scrollWidth | overflow |
|---|---|---|
| 1920 | 2275 | ⚠ +355 |
| 1440 | 2035 | ⚠ +595 |
| 1280 | 1935 | ⚠ +655 |
| 1024 | 1679 | ⚠ +655 |
| 900 | 1555 | ⚠ +655 |
| 390 | 671 | ⚠ +281 |

The page bled sideways at almost every width (Rydel's exact complaint). Rigidity inventory:
- **`.kpi-strip`** — `display:flex` with `.kpi{flex:1}` but **no `min-width:0`**, so tiles couldn't
  shrink below their content and the strip ballooned to ~2275px, overflowing every viewport (top
  offender at all wide widths).
- **`.grid-2`** — `grid-template-columns: 1fr 1fr` fixed 2-column, **no collapse** to 1-col.
- **`.zone-grid`** — 2-col collapsing at a **single** 768px breakpoint → narrow cards clip content
  between 768–1320.
- **`body{overflow-x:hidden}`** — *masked* overflow by CLIPPING content rather than reflowing.
- Two conflicting `.main` max-widths (1280 / 1320); fixed-pixel inner content (a 480px canvas,
  `white-space:nowrap` labels, tables without responsive containers).
- **Why resize didn't react:** the layout had fixed columns and no fluid tracks, so dragging the
  browser never re-flowed anything.

## Phase 1 — the fluid grid system
Appended a source-order-last overhaul block (wins the cascade for equal-specificity overrides):
- **KPI strip → fluid grid** `repeat(auto-fit, minmax(min(148px,100%), 1fr))` with a 1px gap for
  separators — reflows into rows, never overflows.
- **`.grid-2` + `.zone-grid` → `auto-fit minmax(min(Npx,100%), 1fr)`** — cards collapse 2→1 smoothly
  at EVERY width, not one hard breakpoint. `min(Npx,100%)` keeps the min-track ≤ the container so a
  single card never overflows at 390.
- **`min-width:0` + `max-width:100%`** on every layout container so children shrink instead of
  forcing the page wider than the viewport.
- **Tables** get `display:block; overflow-x:auto` → scroll WITHIN their card, never the page.
- **clamp()** on KPI values so numbers stay readable at every size.
- Charts were already responsive (Chart.js `responsive:true` + SVG `viewBox`), so live resize
  reflows via pure CSS + Chart.js — no stale-pixel JS.

## Phase 2 — decision zones (established Wave 2, now fluid)
The four zones (Am I safe / Is the machine working / What needs action / Where are we going) were
built in Wave 2 (`applyZones()` relocates sections into zone grids; the consolidated action feed is
Zone 3). This overhaul makes those zone grids fluid so they stack in priority order on narrow
screens — Zone 1 stays first at every width.

## Phase 4 — visual proof (all green)
- **After width sweep — ZERO horizontal overflow at every width** (`scrollWidth === viewport` at
  1920/1728/1536/1440/1280/1152/1024/900/768/390). Full-page shots in `after/`.
- **Live resize (1920 → 390, nine intermediate widths)** — no overflow at any point; the fold
  visibly reflows 3-col → 2-col → 1-col. Frames in `resize-sequence/`.
- **Chat-open at desktop (1440) + mobile (390)** — no page overflow (layering regression clean).
- **Piolo's view (1024)** — responsive + correctly scoped ("signed in as Piolo"), no overflow.

## Non-regression
CSS-only change — no Python touched, so the engine/data behaviour and the Stage-A/backend test
suite (375 passing) are unaffected. The chat-overlap / HUD-yield layering fixes were re-verified at
desktop + mobile widths with the new grid.
