#!/usr/bin/env python3
"""system_probe.py — REPRODUCE THE SYSTEM PAGE FROM THE SEAT (Phase 0).

"The System tab is glitchy" is a symptom. This measures what actually
happens: every network request with its timing, every console error, the
cumulative layout shift, every long task, and — because the page carries a
ten-minute auto-refresh — what happens after sitting idle.

Three passes: COLD (fresh renderer) · WARM (reload) · IDLE (sit for
`--idle` minutes and watch). Read-only: it loads pages and watches.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
# GATE_* explicitly, or run it under `railway run`, which injects the live
# credential envs — so the value is never typed or written down.
PW = os.environ.get("GATE_OWNER_PASSWORD") or os.environ.get("RYDEL_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")

WATCH_JS = """() => {
  window.__M__ = {cls: 0, shifts: [], longtasks: [], errors: []};
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) {
        if (!e.hadRecentInput) {
          window.__M__.cls += e.value;
          window.__M__.shifts.push({v: +e.value.toFixed(4),
                                    t: Math.round(e.startTime)});
        }
      }
    }).observe({type: 'layout-shift', buffered: true});
  } catch (e) {}
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries())
        window.__M__.longtasks.push({dur: Math.round(e.duration),
                                     t: Math.round(e.startTime)});
    }).observe({type: 'longtask', buffered: true});
  } catch (e) {}
  window.addEventListener('error', e =>
    window.__M__.errors.push(String(e.message).slice(0, 200)));
}"""


def commit_of():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "unknown")[:12]
    except Exception:
        return "unknown"


def login(page):
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PW)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


def snapshot_metrics(page):
    try:
        return page.evaluate("() => window.__M__ || {}")
    except Exception:
        return {}


def run(path: str, idle_minutes: float, out_dir: str):
    report = {"base": BASE, "path": path, "commit": commit_of(), "passes": {}}
    net: list = []
    console: list = []

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(WATCH_JS)
        page = ctx.new_page()

        page.on("console", lambda m: console.append(
            {"type": m.type, "text": m.text[:300], "at": time.time()})
            if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: console.append(
            {"type": "pageerror", "text": str(e)[:300], "at": time.time()}))
        page.on("request", lambda r: net.append(
            {"phase": "req", "url": r.url[:200], "method": r.method,
             "at": time.time()}) if r.url.startswith(BASE) else None)
        page.on("response", lambda r: net.append(
            {"phase": "res", "url": r.url[:200], "status": r.status,
             "at": time.time()}) if r.url.startswith(BASE) else None)

        login(page)

        for name, wait_s in (("cold", 8), ("warm", 8)):
            net.clear()
            console.clear()
            t0 = time.time()
            page.goto(BASE + path, wait_until="load", timeout=60000)
            page.wait_for_timeout(wait_s * 1000)
            m = snapshot_metrics(page)
            reqs = [r for r in net if r["phase"] == "req"]
            res = [r for r in net if r["phase"] == "res"]
            report["passes"][name] = {
                "wall_ms": int((time.time() - t0) * 1000),
                "requests": len(reqs),
                "api_requests": [r["url"].replace(BASE, "") for r in reqs
                                 if "/api/" in r["url"]],
                "failures": [{"url": r["url"].replace(BASE, ""), "status": r["status"]}
                             for r in res if r["status"] >= 400],
                "console_errors": [c for c in console if c["type"] in ("error", "pageerror")],
                "console_warnings": len([c for c in console if c["type"] == "warning"]),
                "cls": round(m.get("cls", 0), 4),
                "shifts": (m.get("shifts") or [])[:12],
                "longtasks": (m.get("longtasks") or [])[:12],
                "longtask_total_ms": sum(t["dur"] for t in (m.get("longtasks") or [])),
                "timing": page.evaluate(
                    """() => { const n = performance.getEntriesByType('navigation')[0] || {};
                       const p = performance.getEntriesByType('paint')
                                   .find(x => x.name === 'first-contentful-paint');
                       return {fcp: Math.round(p ? p.startTime : 0),
                               dcl: Math.round(n.domContentLoadedEventEnd || 0),
                               load: Math.round(n.loadEventEnd || 0)}; }"""),
            }
            page.screenshot(path=os.path.join(out_dir, f"system-{name}.png"),
                            full_page=True)

        # ── IDLE: sit and watch. The page carries a ten-minute auto-refresh;
        # this is the only way to see what it does to a page nobody touched.
        if idle_minutes > 0:
            net.clear()
            console.clear()
            base_m = snapshot_metrics(page)
            start = time.time()
            end = start + idle_minutes * 60
            timeline = []
            while time.time() < end:
                time.sleep(20)
                cur = snapshot_metrics(page)
                new_reqs = [r for r in net if r["phase"] == "req"
                            and "/api/" in r["url"]]
                if new_reqs or (cur.get("cls", 0) - base_m.get("cls", 0)) > 0.001:
                    timeline.append({
                        "at_s": int(time.time() - start),
                        "api_requests": [r["url"].replace(BASE, "") for r in new_reqs],
                        "cls_delta": round(cur.get("cls", 0) - base_m.get("cls", 0), 4),
                    })
                    net.clear()
                    base_m = cur
            m = snapshot_metrics(page)
            report["passes"]["idle"] = {
                "minutes": idle_minutes,
                "timeline": timeline,
                "total_api_requests": len([r for r in net if r["phase"] == "req"
                                           and "/api/" in r["url"]]),
                "console_errors": [c for c in console
                                   if c["type"] in ("error", "pageerror")],
                "cls_at_end": round(m.get("cls", 0), 4),
                "longtask_total_ms": sum(t["dur"] for t in (m.get("longtasks") or [])),
            }
            page.screenshot(path=os.path.join(out_dir, "system-idle.png"),
                            full_page=True)
        br.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="/dashboard/view/system")
    ap.add_argument("--idle", type=float, default=16.0,
                    help="minutes to sit idle (the auto-refresh tick is 10)")
    ap.add_argument("--tag", default="system")
    args = ap.parse_args()
    if not PW:
        print("GATE_OWNER_PASSWORD not set", file=sys.stderr)
        return 2
    out_dir = os.path.join(ROOT, "dashboard", "evidence",
                           f"phase0-{args.tag}-{commit_of()}")
    os.makedirs(out_dir, exist_ok=True)
    rep = run(args.path, args.idle, out_dir)
    with open(os.path.join(out_dir, "probe.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)

    for name in ("cold", "warm", "idle"):
        p = rep["passes"].get(name)
        if not p:
            continue
        print(f"\n── {name.upper()}")
        if name == "idle":
            print(f"   sat {p['minutes']} min · {p['total_api_requests']} API calls "
                  f"· CLS {p['cls_at_end']} · long tasks {p['longtask_total_ms']}ms")
            for t in p["timeline"]:
                print(f"     +{t['at_s']}s  {len(t['api_requests'])} calls "
                      f"{t['api_requests'][:4]}  CLS+{t['cls_delta']}")
            for e in p["console_errors"][:5]:
                print("     ERROR:", e["text"][:120])
            continue
        print(f"   FCP {p['timing']['fcp']}ms · DCL {p['timing']['dcl']}ms "
              f"· {p['requests']} requests · CLS {p['cls']} "
              f"· long tasks {p['longtask_total_ms']}ms")
        print(f"   API on load: {p['api_requests']}")
        if p["failures"]:
            print(f"   FAILURES: {p['failures']}")
        for e in p["console_errors"][:5]:
            print("   ERROR:", e["text"][:140])
        if p["shifts"]:
            print(f"   shifts: {p['shifts'][:6]}")
    print(f"\nevidence → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
