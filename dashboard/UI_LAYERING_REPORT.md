# EDITH — UI Layering & Fluidity Fix

**Date:** 2026-06-19
**Scope:** `served-cfo-agent/dashboard/` only — CSS/layout architecture. No changes to
animation behaviour, voice, memory, engines, or data. Brand palette unchanged.
**Bug:** HUD animations (orb glow, speaking waveform, ambient ticker text, radar) rendered
ON TOP OF the chat panel — captions and waveform z-fought with the conversation bubbles.

> **Rydel — the overlap is gone; the conversation is clean over the HUD.**
> Before/after proof: `dashboard/verification/ui-layering/before-chat-open-speaking.png`
> vs `after-chat-open-speaking.png` (the speaking-state acceptance shot).

---

## Phase 0 — The real stacking picture (read from the live CSS/DOM, not guessed)

Every positioned layer, its z-index, and its stacking-context owner **before** the fix:

| Element | Pos | z-index (before) | Lane | Notes |
|---|---|---|---|---|
| `body.edith-session::before` (grid) | fixed | 1 | ambient | OK — already behind content |
| `.global-window-bar` | sticky | 85 | chrome | |
| `.section-nav` | sticky | 90 | chrome | |
| `.header` | sticky | 100 | chrome | |
| `.stark-header-stream` | fixed | 101 | (inert) | no `stark-hud.js` exists |
| **`.chat-overlay`** | fixed | **190** | chat scrim | below the HUD — the flaw |
| **`.chat-panel`** | fixed | **200** | chat | **below the HUD — the flaw** |
| `.stark-edge` | fixed | 200 | (inert) | |
| **`#edith-hud`** (root: shards, scan, radar, brackets **+ `#eh-stage`**) | fixed | **230** | overlay | **above the chat panel** |
| `.edith-brackets i` | fixed | 240 | overlay | duplicate corner brackets (edith.js) |
| `.edith-hud-ring` | fixed | 248 | orb | |
| `.edith-wave` / `.edith-fx-badge` | fixed | 249 | orb | |
| **`.jarvis-orb`** | fixed | **250** | orb | **above the chat panel** |
| **`.jarvis-caption`** / `.jarvis-note` | fixed | **250** | orb | **above the chat panel** |
| `.jarvis-help` | fixed | 260 | orb | |
| `.calib-panel` | fixed | 270 | orb | |
| `.error-banner` / `.stark-beam` / `.stark-radial` | fixed | 300 | toast | |
| `.edith-boot-hud` | fixed | 350 | boot | |
| `.edith-power-prompt` | fixed | 360 | boot | |
| `.cmdk-overlay` | fixed | 400 | modal | |
| `.metric-tip` | fixed | 500 | tooltip | |
| `.modal-overlay` / `.export-modal` | fixed | 999 / 1000 | modal | |

`#eh-stage` (the orb rings, the `#eh-tick` ambient ticker, the `#eh-wave` speaking
waveform, and the `#eh-cap` caption) had **no z-index of its own** — it inherited
`#edith-hud`'s **z-230** and sat in that root's stacking context.

### Root cause (proved empirically, not asserted)

The chat panel docks to the **right** edge (`width:420px`, full height). **Every** EDITH
voice/HUD element docks to the **bottom-right corner** at a z-index **above** the panel:

- `#eh-stage` → effective **z-230** (via `#edith-hud`) — right:24px, bottom:150px
- `.jarvis-orb` / `.jarvis-caption` → **z-250** — right:24px

So whenever chat opened, the orb, the ticker text, the waveform, and the caption painted
**over** the panel's exact region. Two text layers (floating caption + message bubbles)
landed on the same pixels — the "text spazzing out." The full-viewport `#eh-shards` canvas
and `#eh-scan` scanline (also z-230) painted over the panel too.

The Phase-0 harness (`scripts/capture_layering.py before`) measured it directly with the
chat panel open over the speaking state:

```
panel_z = 200
overlaps_panel: { eh_stage:true, eh_wave:true, eh_cap:true, eh_tick:true, jarvis_orb:true }
```

Five HUD elements geometrically intersecting the panel **and** painting above it. That is
the bug, reproduced and quantified. Screenshot: `before-chat-open-speaking.png`.

**Two secondary findings**
- The `.stark-*` layer (≈40 rules, z 0–300) is **inert**: no `stark-hud.js` exists and the
  template never injects `.stark-*` nodes, so none of those rules match a live element. Left
  in place (don't delete the animation work) with a comment; not a source of the live bug.
- `pointer-events:none` was already correct on `#edith-hud`, so ambient layers were not
  stealing clicks. The collision was paint-order only.

---

## Phase 1 — One documented z-index scale (the core fix)

A single token scale now lives in `:root` (dashboard.css) and is applied system-wide. No
fixed/absolute element sets a raw z-index any more.

```css
--z-ambient:  1;     /* grid, scanline, radar, brackets, shards — BEHIND all content */
--z-content:  10;    /* dashboard cards/sections (normal flow)                        */
--z-window:   85;    /* sticky window bar                                             */
--z-nav:      90;    /* sticky section nav                                            */
--z-header:   100;   /* sticky header                                                 */
--z-orb:      150;   /* EDITH orb + voice visuals — ABOVE content, reserved zone      */
--z-scrim:    300;   /* full-page dim that quiets everything below when chat is open  */
--z-chat:     310;   /* the conversation surface — always wins over orb + ambient     */
--z-boot:     700;   /* entrance / power-up overlays (transient)                      */
--z-modal:    1000;  /* export modal, command palette, autoplay gate                  */
--z-toast:    1100;  /* error banner                                                  */
--z-tooltip:  1200;  /* metric tips (must clear modals)                               */
--chat-w:     420px; /* panel width — the orb zone shifts clear of this when open     */
```

**The structural change that makes it work:** `#eh-stage` was lifted **out of** `#edith-hud`
in the template so the two can live in different lanes:

- `#edith-hud` (grid/scanline/radar/brackets/shards) → **`--z-ambient`**, behind all content,
  `pointer-events:none`. Decorative; it now lives in the page gutters and never touches text.
- `#eh-stage` (orb + ticker + waveform + caption) → its own body-level element at **`--z-orb`**,
  above content but below the chat scrim.

Because the state-driven ring/core animations key off `[data-state]` on the stage's ancestor,
`hud.js` now **mirrors** `data-state` onto `#eh-stage` (one line) so those animations keep
working after the move. Verified: `rings_anim:true, core_anim:true, stage_state:"thinking"`.

---

## Phase 2 — Containment & the "ambient yields to the conversation" rule

**The chat panel is a self-contained surface.** Opaque `--bg-card` background, fixed bounds,
`-18px 0 48px` left shadow for elevation, a real stacking context (`transform`), and content
clipped to it (`messages { flex:1; overflow-y:auto }`). Nothing behind it bleeds through.

**When chat is OPEN (`body.chat-open`, toggled in `chat.js`):**
1. The scrim (`.chat-overlay`, now `--z-scrim` 300) sits **above** the orb (150) and ambient
   (1) lanes — opening chat dims the whole page; only the panel (310) stays lit.
2. The ambient HUD quiets further: `body.chat-open #edith-hud { opacity:0.10 }`.
3. The orb + voice cluster **steps aside** — it slides clear of the right-docked panel:
   `transform: translateX(calc(-1 * (var(--chat-w) + 32px)))`, so it reads as "EDITH stepped
   aside," not "EDITH got covered." It stays visible and animating in its own lane.
4. All floating **text** (`.jarvis-caption`, `.jarvis-note`, `#eh-cap`, `#eh-tick`) is
   silenced — the reply now lives in a bubble, so no caption competes with the conversation.
   The orb rings + `#eh-wave` waveform remain as the speaking indicator.
5. On phones (≤960px) the panel is full-width, so the whole orb cluster hides until chat
   closes (there is no clear zone to step into).

When chat closes, everything eases back — the HUD returns to "lab" mode.

**Where the waveform + caption now live:** the `#eh-wave` waveform and the orb stay in the
orb's reserved zone, which translates to the left gutter when chat opens — **never over the
message list.** The spoken-reply text is shown in the chat bubble (its proper home); the
free-floating caption is suppressed during chat instead of duplicating it over the panel.

---

## Phase 3 — Fluidity & polish

- **Transforms/opacity only, 60fps, no layout shift.** Panel open/close is now a
  `translateX` (was an animated `right:` offset = layout thrash). Orb step-aside and ambient
  dim are eased `transform`/`opacity` (`cubic-bezier(.4,0,.2,1)`, 0.32s).
- **Text breathing room:** message line-height 1.5, max-width 85%, the panel scrolls long
  messages within itself (`overflow-y:auto`) — verified with a 4-message seeded thread.
- **Responsive:** holds at 1440 (desktop), 820 (narrow), and 390 (mobile). At ≤960 the panel
  is full-width and the orb cluster hides — captured proof, zero overlap at every size.
- **`prefers-reduced-motion`** collapses the panel/orb/ambient transitions to ~0s.
- EDITH aesthetic (palette, orb, HUD geometry) is unchanged — this was about order and
  readability, not stripping style.

---

## Phase 4 — Visual proof (the bug was visual)

Captured with Playwright against the dashboard served locally from the **same templates +
static assets** as production, authed, chat panel **open** over each HUD state.
(Local rather than the Railway URL for a reproducible, data-independent capture of a pure
CSS/layout change — the rendered DOM/CSS is byte-identical to prod.)

**Saved to `dashboard/verification/ui-layering/`:**

| File | What it proves |
|---|---|
| `before-chat-open-speaking.png` | **The bug** — orb/waveform/ticker/caption over the bubbles |
| `before-results.json` | `overlaps_panel` all **true** (5 elements) |
| `after-chat-open-idle.png` | Clean idle, chat open |
| `after-chat-open-thinking.png` | Clean thinking, chat open |
| `after-chat-open-speaking.png` | **Acceptance shot** — waveform/caption no longer overlap |
| `after-chat-closed-idle.png` | Lab restored — orb floats bottom-right, ambient back |
| `after-narrow-820-chat-open-speaking.png` | Full-width panel, orb hidden, clean |
| `after-mobile-390-chat-open-speaking.png` | Mobile, clean |
| `after-results.json` | `overlaps_panel` all **false**; `body_chat_open:true` |

**DOM/CSS assertions (after):**
```
panel_z = 310
overlaps_panel: { eh_stage:false, eh_wave:false, eh_cap:false, eh_tick:false, jarvis_orb:false }
z: { eh_stage:150, jarvis_orb:150 }     ambient #edith-hud z = 1, pointer-events:none
clickable: { chat_input:true, chat_send:true, chat_close:true }
console_errors: []
```
- No two text-bearing layers share a region (all `overlaps_panel` false; floating text muted).
- Chat panel holds the highest content z (310, above orb 150 and ambient 1).
- Ambient layers are below content and `pointer-events:none`.
- The speaking waveform is inside its reserved zone, stepped aside — not over the message list.

**Clickability:** chat input, send, and close are the top element at their centre (all
`true`). The header refresh button is intentionally *not* clickable while chat is open — the
scrim covers it so a click outside the panel closes chat (standard modal behaviour); it is
fully clickable again the moment chat closes.

**Non-regression**
- HUD canary green after the DOM move: rings + core still animate (`[data-state]` mirrored to
  `#eh-stage`), brackets=4, radar visible, ticker cycling, shards painting (211px), no console
  errors.
- Test suite: **187 passed, 1 failed**. The single failure is
  `test_pdf_reads_cash_position_fields` → `ModuleNotFoundError: No module named 'fpdf'` — a
  missing optional dependency in the local venv, **pre-existing and unrelated** to this
  frontend change (no Python files were touched).

---

## Files changed

| File | Change |
|---|---|
| `dashboard/static/css/dashboard.css` | z-index token scale in `:root`; remapped every live positioned layer to it; chat panel raised + elevated + `translateX` open/close; "ambient yields" block (dim + step-aside + mute floating text + responsive + reduced-motion); inert-`stark` note |
| `dashboard/static/css/hud.css` | `#edith-hud` → `--z-ambient`; `#eh-stage` → `--z-orb`, `position:fixed`, eased transform |
| `dashboard/templates/dashboard.html` | lifted `#eh-stage` out of `#edith-hud`; documented both lanes |
| `dashboard/static/js/hud.js` | mirror `data-state` onto `#eh-stage` so ring/core state animations survive the move |
| `dashboard/static/js/chat.js` | toggle `body.chat-open` on open/close |
| `scripts/capture_layering.py` | new — before/after proof harness + overlap/clickability assertions |
