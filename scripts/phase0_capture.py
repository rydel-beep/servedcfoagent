#!/usr/bin/env python3
"""PHASE 0 — reproduce the dashboard from Rydel's seat with a REAL browser.

Playwright/Chromium, owner session via the normal login form (password read from
process env GATE_OWNER_PASSWORD — never printed, never stored). Three passes:
cold load, warm load, and post-hero-rebuild (page held open past the 10-min
auto-refresh tick). Captures console errors / pageerrors / failed requests,
headline-tile DOM state, full-page screenshots, and load timing.

Output: JSON report to stdout path arg + screenshots into dashboard/evidence/phase0/.
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
EVD = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence", "phase0")
HOLD_FOR_REBUILD = os.environ.get("GATE_HOLD", "1") == "1"   # pass 3 (10.5 min)

# Headline elements to inspect (id or selector -> label)
PROBES = [
    ("#brief-cash", "hero Cash on hand"),
    ("#brief-mrr", "hero MRR"),
    ("#brief-active", "hero Active clients"),
    ("#brief-ltvcac", "hero LTV:CAC"),
    ("#brief-ltgpcac", "hero LTGP:CAC"),
    ("#morning-brief", "Morning Brief container"),
    ("#section-ratio-tiles", "Zone1 unit-econ panel"),
    ("#section-decision-cards", "Zone1 decision cards"),
    ("#section-csm-card", "Zone1 CSM card"),
    ("#section-cash-position", "Zone1 cash position"),
    ("#section-ar", "Zone1 AR"),
    ("#kpi-strip", "Zone2 KPI strip"),
]

def new_report():
    return {"passes": [], "meta": {"base": BASE, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def probe_dom(page):
    out = {}
    # generic: every element with an id starting section-/brief-/kpi- : presence + text
    js = """() => {
      const grab = sel => { const el = document.querySelector(sel);
        if (!el) return {present:false};
        const t = (el.innerText||'').trim().replace(/\\s+/g,' ');
        const r = el.getBoundingClientRect();
        return {present:true, visible: !!(el.offsetParent!==null||el.tagName==='BODY'),
                empty: t.length===0, text: t.slice(0,220), top: Math.round(r.top+window.scrollY), h: Math.round(r.height)};
      };
      const res = {};
      for (const sel of %s) res[sel] = grab(sel);
      // page metrics
      res.__page = { height: document.body.scrollHeight,
        sections: Array.from(document.querySelectorAll('[id^=section-]')).map(e=>({id:e.id, h:Math.round(e.getBoundingClientRect().height), empty:(e.innerText||'').trim().length===0})),
        scripts: Array.from(document.scripts).map(s=>s.src).filter(Boolean),
        title: document.title };
      try { const nav = performance.getEntriesByType('navigation')[0];
        res.__timing = nav ? {domContentLoaded: Math.round(nav.domContentLoadedEventEnd), load: Math.round(nav.loadEventEnd), transfer: nav.transferSize} : null; } catch(e){}
      return res;
    }""" % json.dumps([p[0] for p in PROBES])
    try:
        out = page.evaluate(js)
    except Exception as e:
        out = {"__probe_error": str(e)[:300]}
    return out

def run_pass(page, name, rep, console_log, shot):
    time.sleep(6)  # let client JS run/settle
    dom = probe_dom(page)
    page.screenshot(path=shot, full_page=True)
    rep["passes"].append({"name": name, "dom": dom, "console": list(console_log), "screenshot": os.path.basename(shot)})
    console_log.clear()

def main():
    if not PW:
        print("GATE_OWNER_PASSWORD not in env", file=sys.stderr); sys.exit(2)
    os.makedirs(EVD, exist_ok=True)
    rep = new_report()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        console_log = []
        def wire(page):
            page.on("console", lambda m: console_log.append({"type": m.type, "text": m.text[:400]}) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: console_log.append({"type": "pageerror", "text": str(e)[:600]}))
            page.on("requestfailed", lambda r: console_log.append({"type": "requestfailed", "url": r.url[:200], "err": (r.failure or "")[:120]}))
            page.on("response", lambda r: console_log.append({"type": "http_error", "url": r.url[:200], "status": r.status}) if r.status >= 400 else None)
        page = ctx.new_page(); wire(page)
        # login (normal form flow — the same thing Rydel does)
        page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PW)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state("domcontentloaded")
        rep["meta"]["post_login_url"] = page.url
        console_log.clear()

        # PASS 1 — cold load (fresh renderer, normal non-busted URL: Rydel's state)
        t0 = time.time()
        page.goto(BASE + "/dashboard/", wait_until="load")
        rep["meta"]["cold_wallclock_s"] = round(time.time() - t0, 2)
        run_pass(page, "cold", rep, console_log, os.path.join(EVD, "pass1-cold.png"))

        # PASS 2 — warm load (reload; cache active)
        t0 = time.time()
        page.reload(wait_until="load")
        rep["meta"]["warm_wallclock_s"] = round(time.time() - t0, 2)
        run_pass(page, "warm", rep, console_log, os.path.join(EVD, "pass2-warm.png"))

        if HOLD_FOR_REBUILD:
            # PASS 3 — hold through the 10-minute auto-refresh tick, capture after
            time.sleep(640)
            run_pass(page, "post-hero-rebuild", rep, console_log, os.path.join(EVD, "pass3-rebuild.png"))

        browser.close()
    out = os.path.join(EVD, "phase0-report.json")
    with open(out, "w") as f:
        json.dump(rep, f, indent=1)
    print(out)

if __name__ == "__main__":
    main()
