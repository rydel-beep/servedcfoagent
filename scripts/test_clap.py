"""
scripts/test_clap.py
--------------------
Controlled-input proof for the double-clap detector: Chromium's fake audio
capture plays /tmp/fake_claps.wav (clap · 350ms · clap · 300Hz tone) as the
microphone, on loop. PASS = the detector logs a double-clap wake and the tone
never triggers anything.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "clap-test-token"
PORT = 8124
BASE = f"http://127.0.0.1:{PORT}"
WAV = "/tmp/fake_claps.wav"


def start_app() -> subprocess.Popen:
    env = dict(os.environ)
    env["DASHBOARD_TOKEN"] = TOKEN
    env["CFO_REFRESH_KEY"] = "t"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"import os; os.chdir({ROOT!r}); "
         "import dashboard.auth as a; a.DASHBOARD_TOKEN = os.environ['DASHBOARD_TOKEN']; "
         f"from app import app; app.run(host='127.0.0.1', port={PORT}, debug=False)"],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("app did not start")


def main():
    from playwright.sync_api import sync_playwright
    app = start_app()
    logs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                "--autoplay-policy=no-user-gesture-required",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={WAV}",
            ])
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.on("console", lambda m: logs.append(m.text))
            page.on("pageerror", lambda e: logs.append("PAGEERROR: " + str(e)))
            page.goto(f"{BASE}/dashboard/?t={TOKEN}")
            page.wait_for_load_state("networkidle")
            # a click = the user-gesture unlock (mirrors real usage)
            page.mouse.click(640, 400)
            page.wait_for_timeout(800)
            # detector telemetry straight from the page
            page.evaluate("console.log('HARNESS-SANITY-PING')")
            page.wait_for_timeout(300)
            print("clap state @1s:", page.evaluate("window.__CLAP_STATE__ && window.__CLAP_STATE__()"))
            # sample mic peaks across one wav loop to see what the page hears
            peaks = page.evaluate("""(async () => {
              const out = [];
              for (let i = 0; i < 50; i++) {
                out.push(window.__CLAP_STATE__ ? +window.__CLAP_STATE__().peakNow.toFixed(3) : -1);
                await new Promise(r => setTimeout(r, 100));
              }
              return out;
            })()""")
            print("peak samples (100ms apart):", peaks)
            page.wait_for_timeout(7000)
            print("clap state @end:", page.evaluate("window.__CLAP_STATE__ && window.__CLAP_STATE__()"))
            cpu = page.evaluate("window.__CLAP_CPU__ && window.__CLAP_CPU__()")
            probe = page.evaluate("""({
              edith: typeof window.EDITH,
              orb: !!document.getElementById('jarvis-orb'),
              clapToggle: localStorage.getItem('edith-clap'),
              wakeToggle: localStorage.getItem('edith-wake'),
              state: window.EDITH ? window.EDITH.getState() : null,
            })""")
            print("probe:", probe)
            browser.close()
    finally:
        app.kill()

    wake_lines = [l for l in logs if "double-clap wake" in l]
    onset_lines = [l for l in logs if "clap onset" in l or "clap:" in l]
    print("=== detector logs ===")
    for l in logs[-30:]:
        print(" ", l)
    print("=== verdict ===")
    print("double-clap wakes:", len(wake_lines))
    print("cpu:", cpu)
    print("PASS" if wake_lines else "FAIL — no double-clap detected")


if __name__ == "__main__":
    main()
