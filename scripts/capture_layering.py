"""UI layering proof: open the chat panel OVER each HUD state and capture
before/after screenshots. Also runs DOM/CSS overlap + clickability assertions.

Run with system python3 (which has playwright); the Flask app is started with
the project venv interpreter (which has flask + deps).

  python3 scripts/capture_layering.py before
  python3 scripts/capture_layering.py after
"""
from __future__ import annotations
import json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHASE = sys.argv[1] if len(sys.argv) > 1 else "after"
OUT = os.path.join(ROOT, "dashboard", "verification", "ui-layering")
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
TOKEN = "layering-capture-token"
PORT = 8137
BASE = f"http://127.0.0.1:{PORT}"
os.makedirs(OUT, exist_ok=True)


def start_app():
    env = dict(os.environ)
    env["DASHBOARD_TOKEN"] = TOKEN
    env["CFO_REFRESH_KEY"] = "t"
    proc = subprocess.Popen(
        [VENV_PY, "-c",
         f"import os; os.chdir({ROOT!r}); "
         "import dashboard.auth as a; a.DASHBOARD_TOKEN = os.environ['DASHBOARD_TOKEN']; "
         f"from app import app; app.run(host='127.0.0.1', port={PORT}, debug=False)"],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("app did not start")


# Inject realistic conversation bubbles + a long message so overlap is visible.
SEED_CHAT = """(() => {
  const m = document.getElementById('chat-messages');
  if (!m) return false;
  m.innerHTML = '';
  const add = (t, role) => {
    const d = document.createElement('div');
    d.className = 'chat-msg ' + role;
    d.textContent = t;
    m.appendChild(d);
  };
  add('What is our cash position and runway right now?', 'user');
  add('Cash on hand is $182,400 across Commbank and Amex. At the current '
    + 'burn of about $61k/month that is roughly 3.0 months of runway. The '
    + 'bigger lever is the expiring-client cliff in August — re-signing even '
    + 'half of them adds about six weeks. Want me to model the re-sign curve?',
    'assistant');
  add('Yes, show me 50% re-sign vs the churn cliff.', 'user');
  add('At 50% re-sign, recognized MRR holds near $48k through Q3 instead of '
    + 'dropping to $31k. The gap is entirely retention, not new sales.', 'assistant');
  m.scrollTo({ top: m.scrollHeight });
  return true;
})()"""


def main():
    from playwright.sync_api import sync_playwright
    app = start_app()
    errors = []
    res = {"phase": PHASE, "captures": [], "assertions": {}}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"{BASE}/dashboard/?t={TOKEN}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3500)

            # open chat panel + seed it
            page.click("#btn-chat-toggle")
            page.wait_for_timeout(500)
            page.evaluate(SEED_CHAT)
            page.evaluate("window.EDITH_HUD && window.EDITH_HUD.setCaption("
                          "'Cash on hand is $182,400 — roughly three months of runway at current burn.')")
            page.wait_for_timeout(300)

            for st, wait in (("idle", 700), ("thinking", 1500), ("speaking", 1100)):
                page.evaluate(f"window.EDITH_HUD && window.EDITH_HUD.setState('{st}')")
                page.wait_for_timeout(wait)
                name = f"{PHASE}-chat-open-{st}.png"
                page.screenshot(path=f"{OUT}/{name}")
                res["captures"].append(name)

            # ── overlap + clickability assertions (speaking state) ──
            page.evaluate("window.EDITH_HUD && window.EDITH_HUD.setState('speaking')")
            page.wait_for_timeout(600)
            res["assertions"] = page.evaluate(r"""(() => {
              const R = (el) => el ? el.getBoundingClientRect() : null;
              const vis = (el) => {
                if (!el) return false;
                const s = getComputedStyle(el);
                return s.display !== 'none' && s.visibility !== 'hidden'
                       && parseFloat(s.opacity) > 0.05;
              };
              const overlaps = (a, bx) => {
                if (!a || !bx) return false;
                if (a.width === 0 || a.height === 0 || bx.width === 0 || bx.height === 0) return false;
                return !(a.right <= bx.left || a.left >= bx.right
                       || a.bottom <= bx.top || a.top >= bx.bottom);
              };
              const panel = document.getElementById('chat-panel');
              const pr = R(panel);
              const targets = {
                eh_stage: document.getElementById('eh-stage'),
                eh_wave: document.getElementById('eh-wave'),
                eh_cap: document.getElementById('eh-cap'),
                eh_tick: document.getElementById('eh-tick'),
                jarvis_orb: document.getElementById('jarvis-orb'),
                jarvis_caption: document.getElementById('jarvis-caption'),
              };
              const zi = (el) => el ? getComputedStyle(el).zIndex : null;
              const report = { panel_z: zi(panel), overlaps_panel: {}, visible: {}, z: {} };
              for (const k in targets) {
                const el = targets[k];
                report.visible[k] = vis(el);
                report.z[k] = zi(el);
                // only count as a collision if the element is actually visible
                report.overlaps_panel[k] = vis(el) && overlaps(R(el), pr);
              }
              // clickability: is the chat input + send + close reachable (top element)?
              const hitTop = (el) => {
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                const top = document.elementFromPoint(cx, cy);
                return top && (el === top || el.contains(top) || top.contains(el));
              };
              report.clickable = {
                chat_input: hitTop(document.getElementById('chat-input')),
                chat_send: hitTop(document.getElementById('chat-send')),
                chat_close: hitTop(document.getElementById('chat-close')),
                refresh_btn: hitTop(document.getElementById('btn-refresh')),
              };
              // ambient pointer-events
              const hud = document.getElementById('edith-hud');
              report.ambient_pointer_events = hud ? getComputedStyle(hud).pointerEvents : null;
              report.body_chat_open = document.body.classList.contains('chat-open');
              return report;
            })()""")

            # close chat → ambient should restore (capture for the recording story)
            page.click("#chat-close")
            page.wait_for_timeout(700)
            page.evaluate("window.EDITH_HUD && window.EDITH_HUD.setState('idle')")
            page.wait_for_timeout(500)
            page.screenshot(path=f"{OUT}/{PHASE}-chat-closed-idle.png")
            res["captures"].append(f"{PHASE}-chat-closed-idle.png")

            ctx.close(); b.close()
    finally:
        app.kill()
    res["console_errors"] = errors[:10]
    with open(f"{OUT}/{PHASE}-results.json", "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


main()
