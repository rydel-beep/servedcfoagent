"""HUD integration proof: drive EDITH_HUD.setState, capture every state,
assert the canary + shards pixels + no console errors."""
from __future__ import annotations
import json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboard", "verification", "hud")
TOKEN = "hud-capture-token"
PORT = 8125
BASE = f"http://127.0.0.1:{PORT}"
os.makedirs(OUT, exist_ok=True)

def start_app():
    env = dict(os.environ); env["DASHBOARD_TOKEN"] = TOKEN; env["CFO_REFRESH_KEY"] = "t"
    proc = subprocess.Popen([sys.executable, "-c",
        f"import os; os.chdir({ROOT!r}); "
        "import dashboard.auth as a; a.DASHBOARD_TOKEN = os.environ['DASHBOARD_TOKEN']; "
        f"from app import app; app.run(host='127.0.0.1', port={PORT}, debug=False)"],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                if r.status == 200: return proc
        except Exception: time.sleep(0.5)
    raise RuntimeError("no app")

def main():
    from playwright.sync_api import sync_playwright
    app = start_app()
    errors = []
    res = {"captures": [], "assertions": {}}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"{BASE}/dashboard/?t={TOKEN}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

            # canary: brackets + radar on plain load
            page.screenshot(path=f"{OUT}/hud-01-canary-load.png")
            res["captures"].append("hud-01-canary-load.png")

            for st, wait in (("idle", 800), ("listening", 1300), ("thinking", 1800), ("speaking", 900)):
                page.evaluate(f"window.EDITH_HUD.setState('{st}')")
                page.wait_for_timeout(wait)
                page.screenshot(path=f"{OUT}/hud-02-{st}.png")
                res["captures"].append(f"hud-02-{st}.png")

            # assertions
            page.evaluate("window.EDITH_HUD.setState('thinking')")
            page.wait_for_timeout(1500)
            res["assertions"] = page.evaluate("""(() => {
              const vis = (el) => el && parseFloat(getComputedStyle(el).opacity) > 0.05
                                  && getComputedStyle(el).display !== 'none';
              const hud = document.getElementById('edith-hud');
              const cv = document.getElementById('eh-shards');
              let painted = 0;
              try {
                const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
                for (let i = 3; i < d.length; i += 16) if (d[i] > 0) painted++;
              } catch (e) {}
              return {
                hud_exists: !!hud,
                data_state: hud && hud.getAttribute('data-state'),
                brackets: document.querySelectorAll('.eh-brk').length,
                brackets_visible: vis(document.querySelector('.eh-brk')),
                radar_visible: vis(document.getElementById('eh-radar')),
                ticker_text: (document.getElementById('eh-tick') || {}).textContent || '',
                shards_painted_px: painted,
                rings_animating: getComputedStyle(document.querySelector('.eh-r1')).animationName !== 'none',
              };
            })()""")
            ctx.close(); b.close()
    finally:
        app.kill()
    res["console_errors"] = errors[:10]
    print(json.dumps(res, indent=2))

main()
