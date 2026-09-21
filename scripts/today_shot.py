#!/usr/bin/env python3
"""today_shot.py — the ten-second screenshot.

TODAY's whole claim is that Rydel can answer "are we winning?" in ten
seconds. This captures what he actually sees, desktop and mobile, and
prints the text above the fold so the claim can be judged rather than
asserted.
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")


def login(page):
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PW)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


def main():
    commit = os.environ.get("GATE_COMMIT", "latest")
    evd = os.path.join(ROOT, "dashboard", "evidence", f"today-{commit}")
    os.makedirs(evd, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch()
        for name, vp, mobile in (("desktop", {"width": 1440, "height": 900}, False),
                                 ("mobile", {"width": 390, "height": 844}, True)):
            ctx = br.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)[:200]))
            page.on("console", lambda m: errs.append(m.text[:200])
                    if m.type == "error" else None)
            login(page)
            t0 = time.time()
            page.goto(BASE + "/dashboard/today", wait_until="load")
            page.wait_for_timeout(1800)
            ms = int((time.time() - t0) * 1000)
            shot = os.path.join(evd, f"today-{name}.png")
            page.screenshot(path=shot)                     # ABOVE THE FOLD only
            page.screenshot(path=os.path.join(evd, f"today-{name}-full.png"),
                            full_page=True)
            probe = page.evaluate("""() => {
              const fold = innerHeight;
              const vis = (el) => {
                const r = el.getBoundingClientRect();
                return r.top < fold && r.bottom > 0;
              };
              const cards = Array.from(document.querySelectorAll('.s-card'))
                .filter(vis).map(c => ({
                  label: (c.querySelector('.s-card-label')?.innerText || '').trim(),
                  value: (c.querySelector('.s-card-value')?.innerText || '').trim(),
                  delta: (c.querySelector('.s-delta')?.innerText || '').trim(),
                  trend: !!c.querySelector('svg.s-trend path'),
                }));
              const v = document.querySelector('.s-verdict');
              return {
                cards_above_fold: cards,
                verdict_above_fold: v && vis(v) ? (v.innerText || '').trim() : null,
                nav: Array.from(document.querySelectorAll('.s-nav-link'))
                       .map(a => (a.innerText || '').trim()).filter(Boolean),
                overflow: document.documentElement.scrollWidth > innerWidth + 2,
              };
            }""")
            out[name] = {"ms": ms, "errors": errs, **probe}
            print(f"\n── {name.upper()}  ({ms}ms, {len(errs)} console errors, "
                  f"overflow={probe['overflow']})")
            print("   nav:", " · ".join(probe["nav"]))
            for c in probe["cards_above_fold"]:
                print(f"   {c['label'][:34]:36s} {c['value'][:18]:20s} "
                      f"{c['delta'][:44]}" + ("  [trend]" if c["trend"] else ""))
            if probe["verdict_above_fold"]:
                print("   VERDICT:", probe["verdict_above_fold"].replace("\n", " ")[:150])
            ctx.close()
        br.close()
    print(f"\nscreenshots → {evd}")
    return 0


if __name__ == "__main__":
    if not PW:
        print("GATE_OWNER_PASSWORD not set", file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
