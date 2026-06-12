"""
scripts/capture_hud.py
----------------------
Stark HUD proof harness (Phase 6). Launches the app locally with a capture
token, drives every animated state via the public EDITH surface, and saves
screenshots + a video + DOM assertions + frame-time numbers to
dashboard/verification/hud/.

The HUD layer is event-driven by design, so states are driven through the
same events real usage fires. Where headless lacks real mic/audio, the
public seams (micRMS, analyser, getState) are overridden in-page — that
exercises the actual render paths, which is the deliverable under test.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboard", "verification", "hud")
TOKEN = "hud-capture-token"
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"

os.makedirs(OUT, exist_ok=True)


def start_app() -> subprocess.Popen:
    env = dict(os.environ)
    env["DASHBOARD_TOKEN"] = TOKEN
    env["CFO_REFRESH_KEY"] = "capture"
    env.pop("ANTHROPIC_API_KEY", None)   # chat falls back fast; fine for visuals
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"import os; os.chdir({ROOT!r}); "
         "import dashboard.auth as a; a.DASHBOARD_TOKEN = os.environ['DASHBOARD_TOKEN']; "
         f"from app import app; app.run(host='127.0.0.1', port={PORT}, debug=False)"],
        env=env, cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("app did not start")


FAKE_ANALYSER = """
window.EDITH.analyser = function() {
  return { fftSize: 256, frequencyBinCount: 128,
    getByteFrequencyData: function(buf) {
      var t = performance.now() / 90;
      for (var i = 0; i < buf.length; i++)
        buf[i] = Math.max(0, Math.min(255,
          140 * Math.abs(Math.sin(t + i * 0.4)) + 60 * Math.random()));
    },
    getByteTimeDomainData: function(buf) {
      for (var i = 0; i < buf.length; i++)
        buf[i] = 128 + 50 * Math.sin(performance.now() / 40 + i * 0.3);
    } };
};
"""


def main():
    from playwright.sync_api import sync_playwright

    app = start_app()
    results = {"captures": [], "assertions": {}, "perf": None}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                "--autoplay-policy=no-user-gesture-required",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ])

            # ── screenshot pass ────────────────────────────────────────────
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(f"{BASE}/dashboard/?t={TOKEN}")
            page.wait_for_load_state("networkidle")

            # boot-on-load animation runs immediately — catch it mid-flight
            page.wait_for_timeout(700)
            page.screenshot(path=f"{OUT}/01-load-boot-mid.png", full_page=False)
            results["captures"].append("01-load-boot-mid.png")

            page.wait_for_timeout(3000)
            page.screenshot(path=f"{OUT}/02-idle-stark.png")
            results["captures"].append("02-idle-stark.png")

            # THINKING — drive via the same event a typed send fires
            page.evaluate("window.dispatchEvent(new CustomEvent('edith:chat', {detail: {phase: 'sent'}}))")
            page.wait_for_timeout(500)
            page.screenshot(path=f"{OUT}/03-thinking-0.5s.png")
            results["captures"].append("03-thinking-0.5s.png")
            page.wait_for_timeout(1000)
            page.screenshot(path=f"{OUT}/04-thinking-1.5s.png")
            results["captures"].append("04-thinking-1.5s.png")

            # DOM assertions while THINKING is live
            results["assertions"] = page.evaluate("""(() => {
              const get = (sel) => document.querySelector(sel);
              const vis = (el) => el && parseFloat(getComputedStyle(el).opacity) > 0.05;
              const anim = (el) => el && getComputedStyle(el).animationName !== 'none';
              const reactor = get('#stark-reactor');
              const ringA = get('.sr-a');
              return {
                reactor_exists: !!reactor,
                reactor_visible: vis(reactor),
                reactor_ring_animating: anim(ringA),
                shards_canvas_visible: vis(get('#stark-canvas')),
                ticker_visible: vis(get('#stark-ticker')),
                ticker_text: (get('#stark-ticker') || {}).textContent || '',
                radar_exists: !!get('#stark-radar'),
                radar_blips: document.querySelectorAll('.radar-blip').length,
                brackets_exist: !!get('#edith-brackets'),
                grid_exists: !!get('.stark-grid'),
                body_thinking_class: document.body.classList.contains('stark-thinking'),
                body_stark_class: document.body.classList.contains('stark-mode'),
              };
            })()""")

            # perf sample during the busiest state
            page.wait_for_timeout(1500)
            results["perf"] = page.evaluate("window.__STARK_PERF__ && window.__STARK_PERF__()")

            page.evaluate("window.dispatchEvent(new CustomEvent('edith:chat', {detail: {phase: 'reply'}}))")
            page.wait_for_timeout(400)

            # LISTENING — public seams stand in for the real mic
            page.evaluate("""
              window.EDITH.micRMS = function() { return 0.12; };
              window.EDITH.getState = function() { return 'listening'; };
              window.dispatchEvent(new CustomEvent('edith:state', {detail: {from: 'idle', to: 'listening'}}));
            """)
            page.wait_for_timeout(1200)
            page.screenshot(path=f"{OUT}/05-listening.png")
            results["captures"].append("05-listening.png")
            page.evaluate("""
              window.EDITH.getState = function() { return 'idle'; };
              window.dispatchEvent(new CustomEvent('edith:state', {detail: {from: 'listening', to: 'idle'}}));
            """)

            # SPEAKING — fake analyser feeds the bars
            page.evaluate(FAKE_ANALYSER + """
              window.EDITH.getState = function() { return 'speaking'; };
              window.dispatchEvent(new CustomEvent('edith:state', {detail: {from: 'idle', to: 'speaking'}}));
            """)
            page.wait_for_timeout(900)
            page.screenshot(path=f"{OUT}/06-speaking.png")
            results["captures"].append("06-speaking.png")
            page.evaluate("window.dispatchEvent(new CustomEvent('edith:state', {detail: {from: 'speaking', to: 'idle'}}))")

            # BOOT — the full sequence via the reactor button
            page.click(".reactor")
            page.wait_for_timeout(1400)
            page.screenshot(path=f"{OUT}/07-boot-mid.png")
            results["captures"].append("07-boot-mid.png")
            page.wait_for_timeout(3000)

            # FOCUS mode
            page.evaluate("localStorage.setItem('edith-stark', '0')")
            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)
            page.screenshot(path=f"{OUT}/08-focus-mode.png")
            results["captures"].append("08-focus-mode.png")
            results["assertions"]["focus_strips_radar"] = page.evaluate(
                "getComputedStyle(document.querySelector('#stark-radar')).display === 'none'")
            ctx.close()

            # ── video pass: send → thinking → speaking (~10s) ─────────────
            vctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                       record_video_dir=OUT,
                                       record_video_size={"width": 1440, "height": 900})
            vpage = vctx.new_page()
            vpage.goto(f"{BASE}/dashboard/?t={TOKEN}")
            vpage.wait_for_load_state("networkidle")
            vpage.wait_for_timeout(3200)
            vpage.evaluate("window.dispatchEvent(new CustomEvent('edith:chat', {detail: {phase: 'sent'}}))")
            vpage.wait_for_timeout(3500)
            vpage.evaluate("window.dispatchEvent(new CustomEvent('edith:chat', {detail: {phase: 'reply'}}))")
            vpage.evaluate(FAKE_ANALYSER + """
              window.EDITH.getState = function() { return 'speaking'; };
              window.dispatchEvent(new CustomEvent('edith:state', {detail: {from: 'idle', to: 'speaking'}}));
            """)
            vpage.wait_for_timeout(3000)
            video = vpage.video
            vctx.close()
            if video:
                src = video.path()
                shutil.move(src, f"{OUT}/thinking-sequence.webm")
                results["captures"].append("thinking-sequence.webm")

            browser.close()
    finally:
        app.kill()

    with open(f"{OUT}/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
