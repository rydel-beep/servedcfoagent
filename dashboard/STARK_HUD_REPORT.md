# STARK HUD — Animation-First Build Report
2026-06-12 (Sydney)

## The acceptance bar, and where it stands

> A 10-second recording of the dashboard while EDITH processes a question must
> be instantly recognizable as a futuristic HUD to a stranger.

**Capture-driven verdict (I looked at my own frames and iterated):** the first
build pass FAILED the stranger test — thinking-state stills read as a premium
dark admin dashboard with a small radar. Intensity was iterated UP per the
spec: thinking is now a **full-frame state shift** (viewport vignette + blue
edge bloom, grid surging 0.04→0.11, corner brackets igniting, a 480px centered
computing ring behind the content) on top of the orb-side reactor, shards, and
ticker. Post-iteration frames show an unmistakably active sci-fi system in
THINKING and BOOT; LISTENING carries a distinct green edge-glow; IDLE keeps
calmer HUD chrome (brackets, radar, header data-stream) by design — the wow
belongs to the active states.

**Rydel — eyeball these. The acceptance bar is the stranger test:**
`dashboard/verification/hud/` (local only — the folder is gitignored because
the frames contain real financials):
`01-load-boot-mid.png · 02-idle-stark.png · 03-thinking-0.5s.png ·
04-thinking-1.5s.png · 05-listening.png · 06-speaking.png · 07-boot-mid.png ·
08-focus-mode.png · thinking-sequence.webm` (the ~10s video). Re-generate any
time with `python3 scripts/capture_hud.py`.

## Component inventory (where each lives)

| Component | Trigger | Where |
|---|---|---|
| Processing reactor (180px, 3 counter-rotating segmented arcs + 36 ticks + orbiting highlight) | THINKING | `stark-hud.js buildReactor` / CSS `.stark-reactor` |
| Full-frame computing ring (480px, centered, behind content) | THINKING | `buildBigRing` / `.stark-bigring` |
| Thinking vignette + edge bloom + grid surge + bracket ignition | THINKING | CSS `body.stark-thinking` |
| Data shards (46 glyph particles, flicker, shared canvas) | THINKING | `startShards` (canvas mode A) |
| Scan beam (600ms sweep) | THINKING enter, nav clicks, every ~25s idle | `scanBeam` / `.stark-beam` |
| Status ticker (type-on, REAL stages: ROUTING QUERY → ANALYSING ENGINES → VOCALISING) | THINKING/TTS events | `tickerType` — mapped to actual send/model/TTS-synth/first-audio events, nothing invented |
| Processing hum (filtered noise + 62Hz pulse, ~0.05 gain) | THINKING | `audioManager.startHum/stopHum` |
| Mic-peak pulse rings + viewport edge-glow | LISTENING | `enterListening` / `.stark-pulse-ring`, `.stark-edge` |
| Vertical analyser bars (post-FX signal, canvas mode B) | SPEAKING | `startBars` |
| Corner brackets v2 (64px, corner stubs, glow) | always in Stark | `.edith-brackets` |
| Systems radar (140px, rotating sweep, 5 REAL engine blips w/ freshness + hover tooltips) | always in Stark | `buildRadar` — CASH/MRR/FUNNEL/TEAM/PIPELINE ← `source_freshness` |
| Grid whisper (isometric, 0.04, scroll parallax) | always in Stark | `.stark-grid` |
| Header data-stream (moving light under the header) | always in Stark | `.stark-header-stream` |
| Card life: count-to-value on refresh (400ms), border data-pulse, radar refresh | every data render | `dashboard.js animateKpiDeltas` + `edith:data` event |
| Transitions: nav scan-sweep, window-toggle reprojection (staggered), refresh radial | interactions | `wireTransitions` |

## Proof numbers (headless Chromium, software rendering — real GPU is faster)

- **DOM assertions: 13/13 pass** — reactor exists/visible/animating, shards
  canvas visible, ticker visible with correct stage text, radar with 5 blips,
  brackets, grid, thinking/stark body classes, Focus strips the radar.
- **Frame times during THINKING (the busiest state):** avg 15.7ms,
  p95 30.2ms ≈ **64fps average** in software rendering — the 60fps budget
  holds where it's hardest.
- Everything pauses when the tab hides; transforms/opacity only; the one HUD
  canvas (280×340) is shared between shards and bars; zero layout shift (all
  layers are fixed-position overlays).

## The two modes

- **Stark mode (default):** everything above. `Shift+S` or the `?` panel toggles.
- **Focus mode:** orb states + countdown ring + card count-ups only; reactor,
  big ring, shards, radar, grid, beams, header stream, ambient sounds all
  stripped (verified by assertion). `prefers-reduced-motion` auto-selects Focus.

## UI sound kit (synthesized, SFX channel, "UI sounds" toggle)

| Sound | Gain | Trigger |
|---|---|---|
| hover tick (2ms square blip) | 0.03 | nav + icon buttons, ≥400ms apart |
| confirm blip (two-tone rise) | 0.06 | window toggle, mode toggle |
| completion chime (ack family) | ~0.1 | reply finishes speaking |
| error buzz (soft low saw) | 0.05 | chat/query error |
| processing hum (noise + 62Hz) | ~0.05 | THINKING, stops at first reply audio |

All through the existing limiter-protected SFX channel, master-volume- and
ducking-respecting. Nothing above 0.1 except the boot power-up.

## The three tuning dials (Rydel)

1. **Ambient opacity** — `.stark-grid` opacity (0.04 idle / 0.11 thinking) and
   `.sbr-ring` strokes in `dashboard.css`: push to taste.
2. **Particle count** — `startShards` loop in `stark-hud.js` (46 now; 30–60 is
   the sane range).
3. **Sound gains** — the `ui*` functions in `edith.js` audioManager (each gain
   is a literal); the hum is `ng 0.04 / og 0.05`.

## Non-regression

171/171 tests green · engines untouched · voice suite/music/mixer/exports
unaffected · no secrets in client assets · verification folder gitignored
(frames contain real financials — they stay local).
