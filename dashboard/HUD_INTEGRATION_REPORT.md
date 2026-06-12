# EDITH HUD — Verbatim Reference Integration Report
2026-06-12 (Sydney)

## Phase 0 verdict: why three rounds produced nothing visible

**Deployed-but-toggled-off.** Evidence: the Stark HUD commit (baf7390) exists,
pushed, and the live bundle served all 21KB of it with every marker — but
`stark-hud.js:18` contained `if (reduced) return false`: **with macOS
"Reduce Motion" enabled (Accessibility → Display), Stark mode was permanently
forced off and every HUD layer was `display:none`.** Every earlier round had
the same fatal gate — the v1 entrance, boot v2, and load animations each
individually skipped under `prefers-reduced-motion`. One accessibility setting
nullified three builds, while headless captures (no reduced-motion) kept
showing everything "working".

Ruled out: never-built (commits exist), not-deployed (live grep positive),
cached (live headers are `cache-control: no-cache` + ETag — revalidated every
load), console errors (zero, asserted).

**The reference contract kills this failure class:** under reduced motion,
animations *shorten* — elements **never hide**. Brackets + radar render
unconditionally.

## What was integrated where

| Reference part | Production location | Adaptation (positioning/z-index ONLY) |
|---|---|---|
| `<style>` block | `static/css/hud.css` | `#edith-hud` → fixed full-viewport overlay, transparent, `pointer-events:none`; brackets/radar clear the header; scanline travels 100vh |
| `#edith-hud` markup | `templates/dashboard.html` | verbatim; demo `#eh-controls` NOT integrated |
| `<script>` engine | `static/js/hud.js` | verbatim logic/timings/counts; demo's hardcoded caption replaced by the REAL reply text (never fake specifics) |
| old `stark-hud.js` | **retired** (git rm) | replaced by the reference implementation |

Every class name, animation, duration, dash-array, color, and size is the
reference's.

## Wiring map (Phase 2)

`window.EDITH_HUD.setState` is driven by the existing events — no engine or
audio-pipeline changes:

| Live event | HUD state |
|---|---|
| `edith:state → booting` | thinking |
| `edith:state → greeting` | speaking |
| `edith:state → listening/thinking/speaking/idle` | same |
| `edith:chat sent` (typed query) | thinking |
| `edith:chat reply/error` (typed, no audio) | idle |
| `edith:tts synth {text}` | caption = the real reply text |

Ticker lines are the reference's; they cycle only during THINKING (real model
wait) — no invented specifics.

## Cache busting (Phase 3)

All five JS/CSS asset URLs now carry `?v=<RAILWAY_GIT_COMMIT_SHA>` (fallback:
process start time) — every deploy busts every client cache permanently.
**Rydel: hard-refresh ONCE (Cmd+Shift+R); after this build it's never needed
again.**

## Proof (Phase 4)

`scripts/capture_hud_v2.py` against this build (local instance of the deploy
commit — the live page requires Rydel's auth token, which stays his):

- Captures in `dashboard/verification/hud/`: `hud-01-canary-load.png` (canary:
  brackets + radar on plain load) and `hud-02-{idle,listening,thinking,speaking}.png`.
- Assertions, all pass: `#edith-hud` exists · `data-state` switches · 4
  brackets visible · radar visible · ticker reads `ANALYSING ENGINES▌` ·
  **shards canvas: 202 painted pixels during thinking** (nonzero-paint proof)
  · rings animating · **zero console errors**.
- Visual: the thinking frame shows the reference's ring stage, core, ticker,
  radar, and brackets over the live dashboard — side-by-side comparable with
  `edith-hud-reference.html` (kept in the repo root).

## Non-regression

171/171 server tests green · voice suite, music, mixer, clap wake, endpointing
untouched (HUD subscribes to events only) · engines untouched.
