#!/usr/bin/env python3
"""render_gate.py — THE REAL BROWSER IS THE DEPLOY GATE (dashboard hardening).

Playwright/Chromium against the production URL (Railway has no preview envs on
this plan, so the gate runs IMMEDIATELY POST-DEPLOY; a FAIL means the operator
reverts: `git revert HEAD && git push` — the Railway build gate keeps the old
build serving during the rebuild). "Visible" claims are admissible ONLY with
this gate's artefact.

Owner session via the normal login form (password from env GATE_OWNER_PASSWORD
— never printed, never stored). Passes:
  1 · landing COLD (fresh renderer)          — desktop 1440×900
  2 · landing WARM (reload, cache active)    — desktop
  3 · POST-HERO-REBUILD: the brief area page held through the 10-min
      auto-refresh tick (GATE_HOLD=0 skips — for fast re-runs)
  4 · landing MOBILE (390×844): stacks, no horizontal overflow
  5 · landing JS DISABLED: tiles still read correctly (server-render proof)
  6 · every summary card's href resolves 200 (owner session)

Assertions (any failure = EXIT 1 = NO DEPLOY):
  · exactly 8 executive tiles, each with a non-empty value; a "—" value is
    legal ONLY with a labelled reason beside it (sub/note) — never blank
  · every tile carries a freshness stamp; the verdict line is non-empty
  · zero pageerrors; zero console errors; zero same-origin HTTP ≥ 500
  · load budget: DCL ≤ 6000 ms cold / 3500 ms warm
  · mobile: document.scrollWidth ≤ viewport + 2px
Artefacts → dashboard/evidence/gate-<commit>/ (report.json + screenshots).
"""
import json
import os
import re
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
HOLD = os.environ.get("GATE_HOLD", "1") == "1"
LEGACY_TOKEN = os.environ.get("GATE_LEGACY_TOKEN")   # local drill servers use the token path
ROOT = os.path.join(os.path.dirname(__file__), "..")

FAILS: list[str] = []
REPORT: dict = {"base": BASE, "passes": {}, "fails": FAILS}


def fail(msg):
    FAILS.append(msg)
    print("GATE FAIL:", msg, file=sys.stderr)


def commit_of(base) -> str:
    try:
        with urllib.request.urlopen(base + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "unknown")[:12]
    except Exception:
        return "unknown"


def wire_console(page, log):
    page.on("console", lambda m: log.append({"type": m.type, "text": m.text[:400]})
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: log.append({"type": "pageerror", "text": str(e)[:600]}))
    page.on("response", lambda r: log.append({"type": "http", "url": r.url[:200], "status": r.status})
            if r.status >= 500 and r.url.startswith(BASE) else None)


def login(page):
    if LEGACY_TOKEN:
        page.goto(BASE + "/dashboard/?t=" + LEGACY_TOKEN, wait_until="domcontentloaded")
        return
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PW)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


PROBE_JS = """() => {
  const pulse = Array.from(document.querySelectorAll('.pulse-tile')).map(el => ({
    id: el.id,
    value: (el.querySelector('.pulse-value')?.innerText || '').trim(),
    sub: (el.querySelector('.pulse-sub')?.innerText || '').trim(),
  }));
  const tiles = Array.from(document.querySelectorAll('.exec-tile')).map(el => ({
    id: el.id,
    state: el.dataset.state,
    value: (el.querySelector('.exec-tile-value')?.innerText || '').trim(),
    sub: (el.querySelector('.exec-tile-sub')?.innerText || '').trim(),
    note: (el.querySelector('.exec-tile-note')?.innerText || '').trim(),
    stamp: (el.querySelector('.exec-tile-stamp')?.innerText || '').trim(),
  }));
  const cards = Array.from(document.querySelectorAll('.landing-card')).map(a => ({
    id: a.id, href: a.getAttribute('href'),
    title: (a.querySelector('.landing-card-title')?.innerText || '').trim(),
  }));
  const nav = performance.getEntriesByType('navigation')[0];
  return {
    tiles, cards, pulse,
    verdict: (document.getElementById('exec-verdict')?.innerText || '').trim(),
    height: document.body.scrollHeight,
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    dcl: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
  };
}"""


def assert_landing(name, probe, console, expect_dcl=None, check_console=True):
    tiles = probe.get("tiles") or []
    if len(tiles) != 8:
        fail(f"{name}: {len(tiles)} executive tiles, expected 8")
    for t in tiles:
        if not t["value"]:
            fail(f"{name}: tile {t['id']} has an EMPTY value")
        if t["value"] == "—" and not (t["sub"] or t["note"]):
            fail(f"{name}: tile {t['id']} shows '—' with NO labelled reason")
        if not t["stamp"]:
            fail(f"{name}: tile {t['id']} has no freshness stamp")
    if not probe.get("verdict"):
        fail(f"{name}: verdict line empty")
    if len(probe.get("cards") or []) < 12:
        fail(f"{name}: only {len(probe.get('cards') or [])} summary cards (expected ≥12 for owner)")
    # SALES PULSE (compass): 3 tiles, each a value or a labelled state
    pulse = probe.get("pulse") or []
    if len(pulse) != 3:
        fail(f"{name}: {len(pulse)} pulse tiles, expected 3")
    for t in pulse:
        if not t["value"]:
            fail(f"{name}: pulse tile {t['id']} EMPTY")
        if t["value"] == "—" and not t["sub"]:
            fail(f"{name}: pulse tile {t['id']} shows '—' with no labelled reason")
    if check_console:
        errs = [c for c in console if c["type"] in ("error", "pageerror", "http")]
        for e in errs:
            fail(f"{name}: console/{e['type']}: {str(e.get('text') or e)[:160]}")
    if expect_dcl and probe.get("dcl") and probe["dcl"] > expect_dcl:
        fail(f"{name}: DCL {probe['dcl']}ms over budget {expect_dcl}ms")


def main():
    if not PW and not LEGACY_TOKEN:
        print("GATE_OWNER_PASSWORD not in env", file=sys.stderr)
        sys.exit(2)
    commit = commit_of(BASE)
    evd = os.path.join(ROOT, "dashboard", "evidence", f"gate-{commit}")
    os.makedirs(evd, exist_ok=True)
    REPORT["commit"] = commit
    REPORT["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── desktop session ──
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        log: list = []
        page = ctx.new_page()
        wire_console(page, log)
        login(page)
        log.clear()

        # PASS 1 — cold
        page.goto(BASE + "/dashboard/landing", wait_until="load")
        time.sleep(3)
        probe = page.evaluate(PROBE_JS)
        page.screenshot(path=os.path.join(evd, "landing-cold.png"), full_page=True)
        REPORT["passes"]["cold"] = {"probe": probe, "console": list(log)}
        assert_landing("cold", probe, log, expect_dcl=6000)
        log.clear()

        # PASS 2 — warm
        page.reload(wait_until="load")
        time.sleep(2)
        probe2 = page.evaluate(PROBE_JS)
        page.screenshot(path=os.path.join(evd, "landing-warm.png"), full_page=True)
        REPORT["passes"]["warm"] = {"probe": probe2, "console": list(log)}
        assert_landing("warm", probe2, log, expect_dcl=3500)
        log.clear()

        # PASS 6 — every card link resolves 200 (fetch in-session)
        hrefs = [c["href"] for c in (probe2.get("cards") or []) if c.get("href")]
        results = page.evaluate(
            """async (hrefs) => {
                 const out = {};
                 for (const h of hrefs) {
                   try { const r = await fetch(h, {redirect: 'follow'}); out[h] = r.status; }
                   catch (e) { out[h] = 'ERR ' + e; }
                 }
                 return out;
               }""", hrefs)
        REPORT["passes"]["card_links"] = results
        for h, st in results.items():
            if st != 200:
                fail(f"card link {h} → {st}")
        log.clear()

        # TOOLTIP sample on the LANDING (registry-driven, keyboard-accessible)
        page.goto(BASE + "/dashboard/landing", wait_until="load")
        time.sleep(2)
        tip_hits = page.evaluate(
            """async () => {
                 const targets = ['#tile-cash_on_hand', '#tile-ltv_cac',
                                  '#tile-pulse_booked_calls', '#card-scale',
                                  '#exec-verdict'];
                 let ok = 0;
                 for (const sel of targets) {
                   const el = document.querySelector(sel);
                   if (!el) continue;
                   el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                   await new Promise(r => setTimeout(r, 450));
                   const t = document.getElementById('defs-tip');
                   if (t && t.style.display === 'block' && t.innerText.length > 20) ok++;
                   el.dispatchEvent(new MouseEvent('mouseout', {bubbles: true}));
                   await new Promise(r => setTimeout(r, 60));
                 }
                 return ok;
               }""")
        REPORT["passes"]["tooltips_landing"] = {"rendered": tip_hits, "of": 5}
        if tip_hits < 5:
            fail(f"landing: only {tip_hits}/5 sampled tooltips rendered from the registry")
        if not page.evaluate("() => !!document.getElementById('defs-help-btn')"):
            fail("landing: the '?' help button is missing")
        log.clear()

        # PASS 7 — area-page RENDER smoke (fetch-200 isn't render-proof):
        # load a representative sample in the real browser; any pageerror,
        # console error or visible boundary-failure block fails the gate.
        # PASS 8 — the /scale tab (compass): server-rendered first paint,
        # zero console errors, no tripped boundaries
        log.clear()
        page.goto(BASE + "/dashboard/scale", wait_until="load")
        # The inputs panel is fetched, so WAIT FOR IT rather than sleeping a
        # fixed 4s and hoping. Under load the fetch took longer than the
        # sleep and the gate reported a panel that renders perfectly well as
        # "did not render controls" — the same fixed-sleep flaw the
        # behaviour gate had on the travelling actions.
        try:
            page.wait_for_selector("#inputs-body .scale-ctl", timeout=20000)
        except Exception:
            pass
        time.sleep(2)
        sprobe = page.evaluate(
            """() => ({
                 hero: (document.getElementById('scale-hero')?.innerText || '').trim().slice(0, 200),
                 inputs: !!document.querySelector('#inputs-body .scale-ctl'),
                 roadmap_or_state: (document.getElementById('roadmap-wrap')?.innerText || '').trim().length > 0
                   || (document.querySelector('#scale-hero .panel-boundary-fail')?.innerText || '').length > 0,
                 boundaries: Array.from(document.querySelectorAll('.panel-boundary-fail')).map(e => e.innerText.slice(0, 100)),
                 sim_triad: !!document.getElementById('sim-triad'),
                 sim_spend: +(document.getElementById('sim-spend')?.value || 0),
                 sim_leads: +((document.getElementById('sim-leads')?.innerText || document.getElementById('sim-leads')?.value || '0').replace(/,/g, '')),
                 chain_clients: (() => {   // an input since the required-rate solve
                   const el = document.getElementById('chain-clients-v');
                   if (!el) return '';
                   return String(('value' in el ? el.value : el.innerText) || '').trim();
                 })(),
                 accuracy: (document.getElementById('accuracy-sentence')?.innerText || '').trim().slice(0, 120),
                 advanced_closed: !document.getElementById('level-advanced')?.open,
                 plan_closed: !document.getElementById('level-plan')?.open,
               })""")
        # SIMULATOR MATH PARITY: the page's rendered chain must equal the
        # server's simulate endpoint for the same inputs (math shown ==
        # math computed — the trust mechanism)
        if sprobe.get("sim_triad") and sprobe.get("sim_spend"):
            server = page.evaluate(
                """async (spend) => {
                     const r = await fetch('/dashboard/api/scale/simulate', {
                       method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: JSON.stringify({spend: spend})});
                     return r.ok ? await r.json() : null;
                   }""", sprobe["sim_spend"])
            REPORT["passes"]["sim_parity"] = {"page": sprobe, "server": server}
            if server:
                if abs(server["leads"] - sprobe["sim_leads"]) > 1.5:
                    fail(f"scale: page leads {sprobe['sim_leads']} ≠ server {server['leads']} (math parity)")
                try:
                    page_clients = float(sprobe["chain_clients"])
                    if abs(server["clients"] - page_clients) > 0.15:
                        fail(f"scale: page clients {page_clients} ≠ server {server['clients']} (math parity)")
                except ValueError:
                    fail(f"scale: chain clients not numeric: {sprobe['chain_clients']!r}")
        else:
            fail("scale: simulator triad missing or unbaked (server-render law)")
        if not sprobe.get("accuracy"):
            fail("scale: accuracy sentence missing from the top of the simulator")
        if not (sprobe.get("advanced_closed") and sprobe.get("plan_closed")):
            fail("scale: Advanced/Plan must ship collapsed (Simple is the default)")
        # TOOLTIPS: hover the first exec-tile-equivalent (a chain card) and a
        # registry-tagged element → the defs tip must render
        page.hover("#chain-clients")
        time.sleep(0.6)
        tip_vis = page.evaluate(
            "() => { const t = document.getElementById('defs-tip');"
            " return t && t.style.display === 'block' && t.innerText.length > 20; }")
        if not tip_vis:
            fail("scale: hover tooltip did not render from the registry")
        page.screenshot(path=os.path.join(evd, "scale.png"), full_page=True)
        REPORT["passes"]["scale"] = {"probe": sprobe, "console": list(log)}
        if not sprobe.get("hero"):
            fail("scale: hero section empty (first paint must be server-rendered)")
        if not sprobe.get("inputs"):
            fail("scale: inputs panel did not render controls")
        for e in [c for c in log if c["type"] in ("error", "pageerror", "http")]:
            fail(f"scale console/{e['type']}: {str(e.get('text') or e)[:160]}")
        log.clear()

        for area in ("unit-econ", "sales", "receivables", "system", "projection"):
            log.clear()
            page.goto(BASE + "/dashboard/view/" + area, wait_until="load")
            time.sleep(4)
            bprobe = page.evaluate(
                """() => ({
                     boundaries: Array.from(document.querySelectorAll('.panel-boundary-fail')).map(e => e.innerText.slice(0, 120)),
                     sections: document.querySelectorAll('section.panel, section.kpi-strip').length,
                   })""")
            REPORT["passes"]["area_" + area] = {"probe": bprobe, "console": list(log)}
            errs = [c for c in log if c["type"] in ("error", "pageerror", "http")]
            for e in errs:
                fail(f"area {area}: console/{e['type']}: {str(e.get('text') or e)[:160]}")
            for b in bprobe.get("boundaries") or []:
                fail(f"area {area}: panel boundary tripped: {b}")
            if not bprobe.get("sections"):
                fail(f"area {area}: no panels rendered")
        log.clear()

        # PASS 3 — post-hero-rebuild on the brief area page (10-min tick)
        if HOLD:
            page.goto(BASE + "/dashboard/view/brief", wait_until="load")
            time.sleep(8)
            log.clear()                       # only errors DURING/AFTER the tick count
            time.sleep(635)
            brief_probe = page.evaluate(
                """() => ({
                     hero: (document.getElementById('brief-body')?.innerText || '').trim().slice(0, 300),
                     ltv: (document.getElementById('brief-ltvcac')?.innerText || '').trim(),
                     boundaries: Array.from(document.querySelectorAll('.panel-boundary-fail')).map(e => e.innerText.slice(0, 120)),
                   })""")
            page.screenshot(path=os.path.join(evd, "brief-post-rebuild.png"), full_page=True)
            REPORT["passes"]["post_rebuild"] = {"probe": brief_probe, "console": list(log)}
            if not brief_probe.get("hero"):
                fail("post-rebuild: brief hero empty after the 10-min tick")
            errs = [c for c in log if c["type"] in ("error", "pageerror", "http")]
            for e in errs:
                fail(f"post-rebuild console/{e['type']}: {str(e.get('text') or e)[:160]}")
        ctx.close()

        # PASS 4 — mobile
        mctx = browser.new_context(viewport={"width": 390, "height": 844})
        mlog: list = []
        mpage = mctx.new_page()
        wire_console(mpage, mlog)
        login(mpage)
        mlog.clear()
        mpage.goto(BASE + "/dashboard/landing", wait_until="load")
        time.sleep(3)
        mprobe = mpage.evaluate(PROBE_JS)
        mpage.screenshot(path=os.path.join(evd, "landing-mobile.png"), full_page=True)
        REPORT["passes"]["mobile"] = {"probe": mprobe, "console": list(mlog)}
        assert_landing("mobile", mprobe, mlog)
        if mprobe.get("scrollW", 0) > mprobe.get("innerW", 390) + 2:
            fail(f"mobile: horizontal overflow (scrollWidth {mprobe['scrollW']} > {mprobe['innerW']})")
        mctx.close()

        # PASS 5 — JS DISABLED (server-render proof)
        nctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                   java_script_enabled=False)
        npage = nctx.new_page()
        # need an authed cookie: reuse login via a JS-enabled throwaway, then
        # copy cookies into the no-JS context (Playwright shares per-context
        # cookies, so log in with a temp ctx and inject)
        tctx = browser.new_context()
        tpage = tctx.new_page()
        login(tpage)
        cookies = tctx.cookies()
        tctx.close()
        nctx.add_cookies(cookies)
        npage.goto(BASE + "/dashboard/landing", wait_until="domcontentloaded")
        html = npage.content()
        tile_count = len(re.findall(r'class="exec-tile state-', html))
        REPORT["passes"]["nojs"] = {"tile_count": tile_count,
                                    "verdict_present": 'id="exec-verdict"' in html}
        npage.screenshot(path=os.path.join(evd, "landing-nojs.png"), full_page=True)
        if tile_count != 8:
            fail(f"JS-disabled: {tile_count} tiles in raw HTML, expected 8 — headline values are NOT server-rendered")
        nctx.close()
        browser.close()

    REPORT["ok"] = not FAILS
    out = os.path.join(evd, "report.json")
    with open(out, "w") as f:
        json.dump(REPORT, f, indent=1)
    print(("GATE PASS — " if not FAILS else "GATE FAIL — ") + out)
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
