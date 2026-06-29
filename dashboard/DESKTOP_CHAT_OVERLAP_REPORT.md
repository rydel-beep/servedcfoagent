# DESKTOP CHAT OVERLAP — fixed (with rendered proof, not just assertions)

**Date:** 2026-06-29 (Sydney) · Acceptance = full-page screenshots at real desktop widths, chat OPEN.

## Why this was real and prior "passes" weren't
Playwright is now runnable in this environment (chromium installed), so for the first time the fix
was verified against the ACTUAL RENDERED VIEW — which is what exposed the truth.

## Phase 0 — reproduced overlap (live, committed code) at 1024/1280/1440/1536/1920
Measured: `.chat-panel` z=**200**, but `#edith-hud` z=**230**, `.jarvis-orb`/`.jarvis-caption` z=**250**,
`.edith-wave` z=**249** — every HUD layer sits ABOVE the chat, pinned to the same right-side region
the chat docks into. The rendered screenshot showed the "EDITH — STANDBY" orb + radar **inside the
chat panel, over the message area**, at every width.

**Root cause (why prior fixes "passed" but Rydel still saw overlap):** the whole "ambient yields to
the conversation" mechanism — both the JS that sets `body.chat-open` AND the CSS that responds to it —
lives only in an **uncommitted** working tree; **neither is deployed.** On the live committed site
`body.chat-open` is NEVER set (verified: `body.classList.contains('chat-open') === false` after
opening chat), and there are **zero** `chat-open` rules in the committed CSS (grep = 0). Prior fixes
also updated the `--z-chat`/`--z-orb` *variables*, but `.chat-panel` and the HUD use **hardcoded**
z-indexes (200 vs 230–250) that ignore the scale. So the live HUD had nothing telling it to yield.

## Phase 1 — the fix (CSS-only, keyed off the COMMITTED open class)
Since `body.chat-open` isn't set live, the fix keys off `.chat-panel.open` (which IS applied live) via
`:has()`: when the chat is open, the ambient HUD (`#edith-hud`, `.jarvis-orb`, `.jarvis-caption`,
`.jarvis-help`, `.edith-wave`, `.edith-caption`, ambient ticker) yields entirely
(`visibility:hidden + opacity:0 + pointer-events:none`), and the chat panel/overlay are raised to
z 400/390 — above any ambient layer. It's scoped to the open state, so the HUD is untouched when the
chat is closed (the lab look intact). No dependency on the parallel `body.chat-open` JS.

## Phase 2 — rendered proof (the gate)
Injected the exact fix into the live page and re-measured + screenshotted at **1024/1280/1440/1536/
1920**, chat OPEN: chat z=**400**, **zero** HUD elements intersecting the chat box at every width, and
the screenshot shows the conversation area clean (orb/radar/waveform gone). Before/after PNGs in
`dashboard/verification/desktop-chat-overlap/`.
