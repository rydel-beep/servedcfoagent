#!/usr/bin/env python3
"""behaviour_gate.py — THE BEHAVIOUR GATE (render gate ≠ behaviour gate).

Playwright INTERACTION tests on the production /scale simulator, owner
session: set spend → leads must move to spend÷CPL · change CPL → leads must
move · drag the chart → spend+leads follow · target mode ("40 calls") →
spend becomes the solved answer, sentence inverts · elasticity toggle →
effective CPL shown, leads bend · reset → measured defaults restored ·
zero console errors throughout. FAIL = NO DEPLOY. Three passes
(cold / warm / post-rebuild-tick optional). On PASS it posts to
/api/scale/behaviour-verified so the "LOGIC VERIFIED" badge updates.
Artefacts → dashboard/evidence/behaviour-<commit>/.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
LEGACY_TOKEN = os.environ.get("GATE_LEGACY_TOKEN")
PASSES = int(os.environ.get("BEHAVIOUR_PASSES", "3"))
ROOT = os.path.join(os.path.dirname(__file__), "..")

FAILS: list[str] = []
REPORT: dict = {"base": BASE, "passes": [], "fails": FAILS}


def fail(msg):
    FAILS.append(msg)
    print("BEHAVIOUR FAIL:", msg, file=sys.stderr)


def commit_of():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "unknown")[:12]
    except Exception:
        return "unknown"


def login(page):
    if LEGACY_TOKEN:
        page.goto(BASE + "/dashboard/?t=" + LEGACY_TOKEN, wait_until="domcontentloaded")
        return
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PW)
    page.click('button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


def state(page):
    return page.evaluate("""() => ({
      spend: +(document.getElementById('sim-spend')?.value || 0),
      cpl: +(document.getElementById('sim-cpl')?.value || 0),
      leads: +((document.getElementById('sim-leads')?.innerText || '0').replace(/,/g, '')),
      sentence: (document.getElementById('sim-sentence')?.innerText || ''),
      chart_point: +(document.getElementById('sim-chart')?.dataset.point || -1),
      cpl_disabled: !!document.getElementById('sim-cpl')?.disabled,
      spend_disabled: !!document.getElementById('sim-spend')?.disabled,
      cpl_note: (document.getElementById('sim-cpl-note')?.innerText || ''),
      calls: (document.getElementById('chain-calls-v')?.innerText || ''),
    })""")


def type_into(page, sel, value):
    page.fill(sel, str(value))
    page.dispatch_event(sel, "input")
    time.sleep(0.35)


def run_pass(page, name, evd, shots):
    steps = {}
    page.goto(BASE + "/dashboard/scale", wait_until="load")
    time.sleep(3)
    page.evaluate("document.querySelector('#defs-tour [data-t=skip]')?.click()")
    time.sleep(0.3)
    s0 = state(page)
    steps["initial"] = s0
    if not s0["leads"]:
        fail(f"{name}: leads output empty at load")
        return steps

    # 1 · SET SPEND → leads == spend ÷ CPL, chain moves
    type_into(page, "#sim-spend", 15000)
    s1 = state(page)
    steps["after_spend_15000"] = s1
    expect = 15000 / s1["cpl"]
    if abs(s1["leads"] - expect) > 2:
        fail(f"{name}: spend edit — leads {s1['leads']} ≠ 15000÷{s1['cpl']}={expect:.0f}")
    if s1["calls"] == s0["calls"]:
        fail(f"{name}: spend edit — the chain did not move")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-1-spend.png"))

    # 2 · CHANGE CPL → leads move (RYDEL'S EXACT COMPLAINT)
    type_into(page, "#sim-cpl", 120)
    s2 = state(page)
    steps["after_cpl_120"] = s2
    if abs(s2["cpl"] - 120) > 0.01:
        fail(f"{name}: CPL edit was not kept (field reads {s2['cpl']})")
    if abs(s2["leads"] - 15000 / 120) > 2:
        fail(f"{name}: CPL edit — leads {s2['leads']} ≠ 15000÷120=125")
    if "$120" not in s2["sentence"] and "120.00" not in s2["sentence"]:
        fail(f"{name}: sentence still shows the old CPL: {s2['sentence'][:80]}")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-2-cpl.png"))

    # 3 · chart point == fields (a view, not a second calculation)
    if s2["chart_point"] >= 0 and abs(s2["chart_point"] - s2["leads"]) > 2:
        fail(f"{name}: chart point {s2['chart_point']} ≠ leads {s2['leads']}")

    # 4 · DRAG the chart → spend + leads follow
    box = page.evaluate("""() => { const r = document.getElementById('sim-chart').getBoundingClientRect();
                                   return {x: r.left, y: r.top, w: r.width, h: r.height}; }""")
    page.mouse.move(box["x"] + box["w"] * 0.8, box["y"] + box["h"] * 0.5)
    page.mouse.down()
    page.mouse.move(box["x"] + box["w"] * 0.85, box["y"] + box["h"] * 0.5)
    page.mouse.up()
    time.sleep(0.4)
    s4 = state(page)
    steps["after_drag"] = s4
    if abs(s4["spend"] - s2["spend"]) < 500:
        fail(f"{name}: chart drag did not move spend ({s2['spend']} → {s4['spend']})")
    if abs(s4["leads"] - s4["spend"] / s4["cpl"]) > 3:
        fail(f"{name}: after drag leads {s4['leads']} ≠ spend÷CPL")

    # 5 · TARGET MODE: I want 40 calls → spend becomes the answer
    page.select_option("#iwant-kind", "calls")
    page.fill("#iwant-value", "40")
    page.click("#btn-iwant")
    time.sleep(0.6)
    s5 = state(page)
    steps["after_target_40calls"] = s5
    if not s5["spend_disabled"]:
        fail(f"{name}: target mode — spend field should be visibly the answer (disabled)")
    if "you need $" not in s5["sentence"] and "To get 40" not in s5["sentence"]:
        fail(f"{name}: target sentence did not invert: {s5['sentence'][:90]}")
    # calls must read ~40
    try:
        if abs(float(s5["calls"]) - 40) > 1:
            fail(f"{name}: target 40 calls — chain reads {s5['calls']}")
    except ValueError:
        fail(f"{name}: calls not numeric in target mode: {s5['calls']!r}")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-5-target.png"))

    # 6 · back to FORWARD; ELASTICITY toggle → effective CPL shown, leads bend
    page.check("#mode-forward")
    time.sleep(0.3)
    type_into(page, "#sim-spend", 30000)
    before = state(page)
    page.check("#sim-cpl-mode")
    time.sleep(0.4)
    s6 = state(page)
    steps["after_elasticity_on"] = s6
    if not s6["cpl_disabled"]:
        fail(f"{name}: elasticity ON — the CPL field must be read-only-derived")
    if "effective CPL" not in s6["cpl_note"]:
        fail(f"{name}: elasticity ON — no effective-CPL explanation shown")
    if not (s6["leads"] < before["leads"]):
        fail(f"{name}: elasticity ON at high spend must bend leads down "
             f"({before['leads']} → {s6['leads']})")
    page.uncheck("#sim-cpl-mode")
    time.sleep(0.3)
    s6b = state(page)
    if s6b["cpl_disabled"]:
        fail(f"{name}: elasticity OFF — CPL must be editable again")

    # 7 · RESET to measured
    page.click(".sim-preset[data-preset='measured']")
    time.sleep(0.4)
    s7 = state(page)
    steps["after_reset"] = s7
    if abs(s7["spend"] - steps["initial"]["spend"]) > max(steps["initial"]["spend"] * 0.02, 100):
        fail(f"{name}: reset did not restore measured spend "
             f"({steps['initial']['spend']} vs {s7['spend']})")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-7-reset.png"))
    return steps


def main():
    if not PW and not LEGACY_TOKEN:
        print("GATE_OWNER_PASSWORD not in env", file=sys.stderr)
        sys.exit(2)
    commit = commit_of()
    evd = os.path.join(ROOT, "dashboard", "evidence", f"behaviour-{commit}")
    os.makedirs(evd, exist_ok=True)
    REPORT["commit"] = commit
    REPORT["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        console_errors = []
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)[:200]))
        page.on("console", lambda m: console_errors.append("console: " + m.text[:200])
                if m.type == "error" else None)
        login(page)
        names = ["cold", "warm", "third"][:PASSES]
        for i, name in enumerate(names):
            steps = run_pass(page, name, evd, shots=(i == 0))
            REPORT["passes"].append({"name": name, "steps": steps})
        REPORT["console_errors"] = console_errors
        for e in console_errors:
            fail("console: " + e)

        ok = not FAILS
        # post the result so the badge updates (owner session held)
        try:
            page.evaluate(
                """async (body) => { await fetch('/dashboard/api/scale/behaviour-verified', {
                     method: 'POST', headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify(body)}); }""",
                {"ok": ok, "commit": commit, "passes": len(names),
                 "reason": "; ".join(FAILS[:3])})
        except Exception as e:  # noqa: BLE001
            print("badge post failed:", e, file=sys.stderr)
        browser.close()
    REPORT["ok"] = not FAILS
    out = os.path.join(evd, "report.json")
    with open(out, "w") as f:
        json.dump(REPORT, f, indent=1)
    print(("BEHAVIOUR PASS — " if not FAILS else "BEHAVIOUR FAIL — ") + out)
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
