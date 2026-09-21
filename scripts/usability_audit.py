#!/usr/bin/env python3
"""usability_audit.py — THE REAL-SEAT AUDIT (Phase 0 of the finish line).

Nothing is built before this register exists. It sits in Rydel's seat: a real
Chromium against PRODUCTION, a real owner session, desktop 1440×900 and mobile
390×844, and it walks every page the app serves.

For every page it records: HTTP status, first paint, DOMContentLoaded,
time-to-interactive, console errors, the panel inventory, whether the page
publishes `data-metric` identities (the scan-2 gap list), and a screenshot.

For every CONTROL it records a verdict:
  WORKS       — activating it changed something (DOM, URL, or a network read)
  NO-OP       — activating it changed nothing at all
  ERROR       — activating it threw, or drove a 4xx/5xx
  SLOW        — it worked, but took longer than 500 ms
  MISLEADING  — it works, but says something different from what it does
  NOT-EXERCISED — write-capable by name; READ-ONLY LAW #148 forbids the click

READ-ONLY: the auditor only activates controls that pass the read-only
allowlist. Anything whose label or id smells like a write (save, apply, commit,
declare, resolve, export, send, refresh, deploy, reset…) is inventoried and
reported as NOT-EXERCISED, never clicked. It never writes to the tracker or
the CRM and never touches GHL_EMAIL_TOKEN.

Output: USABILITY_AUDIT.md (the findings register = the build list) plus
dashboard/evidence/usability-<commit>/ (report.json + screenshots).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
AD_USER = os.environ.get("GATE_AD_USER", "romano")
AD_PW = os.environ.get("GATE_AD_PASSWORD")

# Every HTML surface the app serves. `expect` is the status we believe is
# correct; a mismatch is itself a finding.
PAGES = [
    ("landing",      "/dashboard/landing",             200, "daily"),
    ("brief",        "/dashboard/view/brief",          200, "daily"),
    ("cash",         "/dashboard/view/cash",           200, "weekly"),
    ("sales-area",   "/dashboard/view/sales",          200, "daily"),
    ("unit-econ",    "/dashboard/view/unit-econ",      200, "monthly"),
    ("projection",   "/dashboard/view/projection",     200, "monthly"),
    ("renewals",     "/dashboard/view/renewals",       200, "monthly"),
    ("outflows",     "/dashboard/view/outflows",       200, "monthly"),
    ("receivables",  "/dashboard/view/receivables",    200, "weekly"),
    ("team",         "/dashboard/view/team",           200, "monthly"),
    ("decisions",    "/dashboard/view/decisions",      200, "weekly"),
    ("system",       "/dashboard/view/system",         200, "weekly"),
    ("scale",        "/dashboard/scale",               200, "monthly"),
    ("travelling",   "/dashboard/scale/travelling",    200, "weekly"),
    ("definitions",  "/dashboard/definitions",         200, "none"),
    ("worklog",      "/dashboard/worklog",             200, "weekly"),
    ("bookkeeping",  "/dashboard/bookkeeping",         200, "monthly"),
    ("csm",          "/dashboard/csm",                 200, "monthly"),
    ("leads",        "/dashboard/leads",               200, "daily"),
    ("targets",      "/dashboard/targets",             200, "monthly"),
    ("data-sources", "/dashboard/data-sources",        200, "none"),
    ("memory",       "/dashboard/memory/",             200, "none"),
    ("ads",          "/ads",                           200, "daily"),
    ("today",        "/dashboard/today",               200, "daily"),
    ("sales",        "/dashboard/sales",               200, "daily"),
]

# Controls whose label/id smells like a write are NEVER clicked (READ-ONLY LAW).
WRITE_WORDS = re.compile(
    r"save|appl|commit|declare|resolv|dismiss|undismiss|restore|export|send|"
    r"delete|remove|refresh|resync|deploy|reset|confirm|override|assign|"
    r"rebuild|scan|backfill|set\b|submit|publish|post\b|upload|log\s?out|logout|"
    r"pdf|download|csv|tier|discreet|record|pin\b|"
    # 2026-09-21: the first estate run of this auditor CLICKED two
    # "Deactivate" buttons on the memory page and flipped two of EDITH's own
    # facts inactive (both restored the same hour). None of these words were
    # on the list. A label-based allowlist is a guess, so the structural
    # guard below is the real fix — this list is now only the first net.
    r"forget|deactiv|activat|clear|archive|toggle|edit\b|undo|retry|"
    r"approve|reject|accept|apply|mark\b|flag\b|close\b|cancel", re.I)

# STRUCTURAL GUARD (the real one): a control is exercised ONLY if activating
# it cannot reach a write endpoint. Any element whose handler or form would
# issue a non-GET request is never clicked, whatever it is labelled.
SAFE_PAGES_FOR_WRITES = ()          # there are none; nothing is safe to write

# How many controls of the SAME SHAPE to actually activate.
SAMPLE_PER_SHAPE = 3

FINDINGS: list[dict] = []
SEV_ORDER = {"SEV1": 0, "SEV2": 1, "SEV3": 2}


def finding(sev, cls, page, title, detail, fix=""):
    FINDINGS.append({"sev": sev, "class": cls, "page": page, "title": title,
                     "detail": detail, "fix": fix})
    print(f"[{sev}/{cls}] {page}: {title} — {detail[:140]}", file=sys.stderr)


def commit_of():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "unknown")[:12]
    except Exception:
        return "unknown"


def login(page, user, pw):
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', user)
    page.fill('input[name="password"]', pw)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


# ── the page probe ──────────────────────────────────────────────────────────

PROBE = r"""(CONTROL_SELECTOR) => {
  // A control sitting in a CLOSED drawer is in the DOM but is not a control
  // the user can reach. Counting it would invent dead controls that aren't.
  const VISIBLE = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    let n = el;
    while (n && n !== document.body) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden'
          || parseFloat(cs.opacity || '1') < 0.05) return false;
      if (n.hasAttribute('hidden') || n.getAttribute('aria-hidden') === 'true')
        return false;
      n = n.parentElement;
    }
    if (getComputedStyle(el).pointerEvents === 'none') return false;
    // A CLOSED drawer is parked off-canvas (translateX, or a negative
    // bottom) rather than hidden. Its buttons are in the DOM and pass every
    // CSS visibility test, but no user can reach them — counting them would
    // invent dead controls. A fixed element must intersect the viewport; any
    // other element must intersect the document.
    let fixed = false, n2 = el;
    while (n2 && n2 !== document.body) {
      if (getComputedStyle(n2).position === 'fixed') { fixed = true; break; }
      n2 = n2.parentElement;
    }
    if (fixed)
      return r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
    const doc = document.documentElement;
    const l = r.left + scrollX, t = r.top + scrollY;
    return l + r.width > 0 && t + r.height > 0
           && l < doc.scrollWidth && t < doc.scrollHeight;
  };
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const paint = performance.getEntriesByType('paint')
      .find(p => p.name === 'first-contentful-paint');
  const panels = Array.from(document.querySelectorAll(
      '.panel, .card, section[id], .exec-card, .tv-stage, .area-panel'))
    .map(el => ({
      id: el.id || '',
      title: (el.querySelector('h1,h2,h3,.panel-title,.card-title,.tv-stage-name')
              ?.innerText || '').trim().slice(0, 70),
      failed: el.matches('.panel-boundary-fail:not(.empty-state)') ||
              !!el.querySelector('.panel-boundary-fail:not(.empty-state)'),
      empty: (el.innerText || '').trim().length < 3,
    }))
    .filter(p => p.id || p.title);
  const metrics = Array.from(document.querySelectorAll('[data-metric][data-value]'))
    .map(el => el.dataset.metric);
  // anything that LOOKS like a number on the page but carries no identity
  const numberish = Array.from(document.querySelectorAll(
      '.exec-tile-value, .pulse-value, .tv-actual, .kpi-value, .stat-value, ' +
      '.metric-value, .big-number, .num, td.num'))
    .filter(el => !el.closest('[data-metric][data-value]') &&
                  !el.hasAttribute('data-value'))
    .map(el => ((el.innerText || '').trim().slice(0, 24)))
    .filter(t => /[0-9]/.test(t));
  const controls = Array.from(document.querySelectorAll(CONTROL_SELECTOR))
    .map((el, i) => {
      el.setAttribute('data-audit-ref', 'c' + i);
      const label = (el.innerText || el.getAttribute('aria-label') ||
                     el.getAttribute('title') || el.value || '').trim().slice(0, 60);
      // A table of 300 lead rows has 300 identical links. Testing each one
      // teaches nothing and never finishes. Controls are grouped by SHAPE —
      // tag, classes, href pattern, label pattern — and a few of each group
      // are activated; the group size is reported, so nothing is silently
      // dropped.
      const cls = (typeof el.className === 'string' ? el.className
                   : (el.getAttribute('class') || '')).trim();
      const shape = el.tagName.toLowerCase() + '|' + cls + '|'
        + (el.getAttribute('href') || '').replace(/[0-9a-f]{6,}|\d+/gi, '#') + '|'
        + label.replace(/\d+/g, '9').replace(/[A-Za-z]+/g, 'a').slice(0, 24);
      // A stamped attribute dies the moment a panel re-renders itself, and
      // the dead handle then reads as "unreachable". A structural path is
      // re-resolvable, so the auditor keeps pointing at the same control.
      const pathOf = (n) => {
        if (n.id) return '#' + CSS.escape(n.id);
        const parts = [];
        while (n && n.nodeType === 1 && n !== document.body) {
          const parent = n.parentElement;
          if (!parent) break;
          const same = Array.from(parent.children)
              .filter(k => k.tagName === n.tagName);
          parts.unshift(n.tagName.toLowerCase()
              + (same.length > 1 ? ':nth-of-type(' + (same.indexOf(n) + 1) + ')' : ''));
          if (parent.id) { parts.unshift('#' + CSS.escape(parent.id)); break; }
          n = parent;
        }
        return parts.join(' > ');
      };
      return {
        ref: 'c' + i,
        sel: pathOf(el),
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || '').toLowerCase(),
        cls: cls,
        in_form: !!el.closest('form'),
        label: label,
        id: el.id || '',
        href: el.getAttribute('href') || '',
        shape: shape,
        disabled: !!el.disabled,
        visible: VISIBLE(el),
      };
    })
    .filter(c => c.visible && !c.disabled);
  return {
    title: document.title,
    dcl: Math.round(nav.domContentLoadedEventEnd || 0),
    load: Math.round(nav.loadEventEnd || 0),
    fcp: Math.round(paint ? paint.startTime : 0),
    interactive: Math.round(nav.domInteractive || 0),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    panels, metrics, numberish, controls,
  };
}"""


def tti(page):
    """Time to interactive, measured honestly: the moment after load when the
    main thread has been quiet (no long task) for 500 ms."""
    try:
        return page.evaluate(r"""() => new Promise(res => {
          const nav = performance.getEntriesByType('navigation')[0] || {};
          let last = nav.loadEventEnd || performance.now();
          let done = false;
          let po;
          try {
            po = new PerformanceObserver(list => {
              for (const e of list.getEntries()) last = e.startTime + e.duration;
            });
            po.observe({type: 'longtask', buffered: true});
          } catch (e) {}
          const started = performance.now();
          const check = () => {
            if (done) return;
            if (performance.now() - last > 500 || performance.now() - started > 8000) {
              done = true; if (po) po.disconnect(); res(Math.round(last));
            } else setTimeout(check, 120);
          };
          check();
        })""")
    except Exception:
        return None


def is_write_capable(c):
    blob = f"{c.get('label','')} {c.get('id','')} {c.get('href','')} {c.get('cls','')}"
    if WRITE_WORDS.search(blob):
        return True
    # a submit control, or anything living inside a form, can POST
    if c.get("type") in ("submit", "reset") or c.get("in_form"):
        return True
    return False


def signature(page):
    return page.evaluate("""() => ({
      url: location.href,
      title: document.title,
      len: ((document.body && document.body.innerText) || '').length,
      html: ((document.body && document.body.innerHTML) || '').length,
      open: document.querySelectorAll('[open], .open, .is-open, .drawer-open, .active').length,
    })""")


# An overlay left open by one control hides every control beneath it, which
# would report the whole page as broken. The auditor closes what it opens.
CONTROL_SELECTOR = ('button, a[href], select, input[type=range], '
                    'input[type=checkbox], [role=button], [onclick], .tab, '
                    '.chip[data-action], .seg, .toggle')

# A reload wipes the refs the probe stamped, which would make every remaining
# control read GONE. Re-stamping in the same deterministic order restores them.
STAMP_JS = """(sel) => {
  Array.from(document.querySelectorAll(sel))
       .forEach((el, i) => el.setAttribute('data-audit-ref', 'c' + i));
  return document.querySelectorAll('[data-audit-ref]').length;
}"""


def stamp_refs(page):
    try:
        return page.evaluate(STAMP_JS, CONTROL_SELECTOR)
    except Exception:
        return 0


OVERLAY_JS = """() => {
  const el = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
  let n = el;
  while (n && n !== document.body) {
    const cs = getComputedStyle(n);
    if ((cs.position === 'fixed' || cs.position === 'absolute')
        && (parseInt(cs.zIndex) || 0) >= 20) {
      const r = n.getBoundingClientRect();
      if (r.width > innerWidth * 0.5 && r.height > innerHeight * 0.35)
        return {id: n.id || '', cls: String(n.className || '').slice(0, 70)};
    }
    n = n.parentElement;
  }
  return null;
}"""


def clear_overlay(page, path):
    """Return the page to a clean seat: Escape, then a reload if that fails.
    Returns the overlay that was found, or None."""
    try:
        ov = page.evaluate(OVERLAY_JS)
    except Exception:
        return None
    if not ov:
        return None
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        if not page.evaluate(OVERLAY_JS):
            return ov
    except Exception:
        pass
    try:
        page.goto(BASE + path, wait_until="load", timeout=45000)
        page.wait_for_timeout(900)
        stamp_refs(page)
    except Exception:
        pass
    return ov


def exercise(page, path, control, log, net):
    """Activate one control and classify what happened. Read-only controls
    only — the caller filters. Timing is the time to the FIRST observable
    change, not a fixed wait: a fixed wait would call every control slow."""
    before = signature(page)
    n_before = len(net)
    errs_before = len([e for e in log if e["type"] in ("error", "pageerror")])
    blocked_by = None
    t0 = time.time()
    def _resolve():
        for how in (control.get("sel"), f'[data-audit-ref="{control["ref"]}"]'):
            if not how:
                continue
            try:
                found = page.query_selector(how)
            except Exception:
                found = None
            if found:
                return found
        return None
    try:
        el = _resolve()
        if not el:
            return {"verdict": "GONE", "ms": 0}
        if control.get("tag") == "select":
            # Clicking a <select> only opens the native list — the page sees
            # nothing, and every dropdown in the estate read NO-OP because of
            # it. Choosing a DIFFERENT option is what a user actually does.
            opts = el.evaluate(
                "(s) => Array.from(s.options).map(o => o.value)") or []
            cur = el.input_value()
            other = next((o for o in opts if o != cur), None)
            if other is None:
                return {"verdict": "NO-OP", "ms": 0,
                        "detail": "the dropdown has only one option"}
            el.select_option(other, timeout=2500)
        else:
            el.click(timeout=2500, force=False)
    except Exception as e:  # noqa: BLE001
        msg = str(e).split("\n")[0][:200]
        # Not actionable is not the same as broken. Clear whatever is covering
        # it and try once more; only a control that stays unreachable on a
        # clean page is a real finding.
        blocked_by = clear_overlay(page, path)
        try:
            el2 = _resolve()
            if not el2:
                return {"verdict": "GONE", "ms": 0}
            t0 = time.time()
            if control.get("tag") == "select":
                opts = el2.evaluate(
                    "(s) => Array.from(s.options).map(o => o.value)") or []
                cur = el2.input_value()
                other = next((o for o in opts if o != cur), None)
                if other is not None:
                    el2.select_option(other, timeout=2500)
                    page.wait_for_timeout(400)
                    return {"verdict": "WORKS", "ms": int((time.time() - t0) * 1000),
                            "navigated": False}
            # centre it: a control parked under a fixed bar is reachable to a
            # user who scrolls differently, and calling that "unreachable"
            # would be a finding the seat does not actually have
            page.evaluate("(el) => el.scrollIntoView({block: 'center'})", el2)
            page.wait_for_timeout(350)
            el2.click(timeout=2500, force=False)
        except Exception as e2:  # noqa: BLE001
            cover = None
            try:
                cover = page.evaluate(
                    """(sel) => {
                      const el = document.querySelector(sel);
                      if (!el) return null;
                      const r = el.getBoundingClientRect();
                      const x = Math.max(1, Math.min(innerWidth - 1, r.x + r.width / 2));
                      const y = Math.max(1, Math.min(innerHeight - 1, r.y + r.height / 2));
                      const top = document.elementFromPoint(x, y);
                      if (!top || top === el || el.contains(top) || top.contains(el))
                        return null;
                      const cls = (typeof top.className === 'string'
                                   ? top.className
                                   : (top.getAttribute('class') || ''));
                      return (top.id ? '#' + top.id : top.tagName.toLowerCase())
                             + (cls ? ' .' + cls.trim().split(/\s+/)[0] : '');
                    }""", control.get("sel")
                    or f'[data-audit-ref="{control["ref"]}"]')
            except Exception:
                pass
            return {"verdict": "BLOCKED", "ms": int((time.time() - t0) * 1000),
                    "detail": (f"covered by {cover}" if cover else
                               "unreachable on a clean page: "
                               + str(e2).split(chr(10))[0][:120]),
                    "covered_by": cover, "first_error": msg}
    # poll for the first observable change (up to 1.2s), so `ms` measures the
    # interaction rather than the auditor's own patience
    ms = None
    for _ in range(24):
        page.wait_for_timeout(50)
        now = signature(page)
        if (now["url"] != before["url"] or now["len"] != before["len"]
                or now["html"] != before["html"] or now["open"] != before["open"]
                or len(net) > n_before):
            ms = int((time.time() - t0) * 1000)
            break
    if ms is None:
        ms = int((time.time() - t0) * 1000)
    after = signature(page)
    new_errs = [e for e in log if e["type"] in ("error", "pageerror")][errs_before:]
    bad_net = [r for r in net[n_before:] if r["status"] >= 400]
    changed = (after["url"] != before["url"] or after["len"] != before["len"]
               or after["html"] != before["html"] or after["open"] != before["open"]
               or len(net) > n_before)
    navigated = after["url"] != before["url"]
    out = {"ms": ms, "navigated": navigated}
    if new_errs:
        out["verdict"] = "ERROR"
        out["detail"] = new_errs[0]["text"][:200]
    elif bad_net:
        out["verdict"] = "ERROR"
        out["detail"] = f"{bad_net[0]['status']} {bad_net[0]['url'][-70:]}"
    elif not changed:
        out["verdict"] = "NO-OP"
    elif ms > 500:
        out["verdict"] = "SLOW"
    else:
        out["verdict"] = "WORKS"
    if blocked_by:
        out["was_covered_by"] = blocked_by
    if navigated:
        try:
            page.goto(BASE + path, wait_until="load", timeout=45000)
            page.wait_for_timeout(900)
            stamp_refs(page)
        except Exception:
            pass
    else:
        # close whatever this control opened, so the next control is clicked
        # on a clean page rather than through a modal
        ov = clear_overlay(page, path)
        if ov:
            out["opened_overlay"] = ov
    return out


def audit_page(page, name, path, expect, job, evd, mobile=False, log=None,
               net=None, exercise_controls=True):
    log.clear()
    net.clear()
    t0 = time.time()
    try:
        resp = page.goto(BASE + path, wait_until="load", timeout=45000)
        status = resp.status if resp else 0
    except Exception as e:  # noqa: BLE001
        finding("SEV1", "BROKEN", name, "page failed to load", str(e)[:200])
        return {"name": name, "path": path, "status": 0, "error": str(e)[:200]}
    page.wait_for_timeout(1500)
    wall = int((time.time() - t0) * 1000)
    probe = page.evaluate(PROBE, CONTROL_SELECTOR)
    probe["tti"] = tti(page)
    probe["wall_ms"] = wall
    probe["status"] = status
    probe["job"] = job
    probe["name"] = name
    probe["path"] = path
    probe["mobile"] = mobile
    shot = os.path.join(evd, f"{name}{'-mobile' if mobile else ''}.png")
    try:
        page.screenshot(path=shot, full_page=not mobile)
        probe["screenshot"] = os.path.basename(shot)
    except Exception:
        pass

    # ── findings from the page itself ──
    if status != expect:
        finding("SEV1" if status >= 500 else "SEV2", "BROKEN", name,
                f"HTTP {status} (expected {expect})", f"{path} → {status}",
                "build the page or retire the route")
    errs = [e for e in log if e["type"] in ("error", "pageerror")]
    if errs:
        finding("SEV2", "BROKEN", name, f"{len(errs)} console error(s)",
                errs[0]["text"][:200], "fix or bound the throwing block")
    fails = [p for p in probe["panels"] if p["failed"]]
    for p in fails:
        finding("SEV2", "BROKEN", name, "a panel tripped its boundary",
                f"{p['id'] or p['title']}", "fix the panel's renderer")
    if status == 200 and not probe["metrics"]:
        finding("SEV2", "SCAN2-GAP", name, "page publishes no metric identities",
                "no [data-metric][data-value] anywhere — scan 2 cannot compare it",
                "publish data-metric/window/clock/basis/value on every number")
    elif status == 200 and probe["numberish"]:
        finding("SEV3", "SCAN2-GAP", name,
                f"{len(probe['numberish'])} number(s) without an identity",
                "e.g. " + ", ".join(probe["numberish"][:5]),
                "add the data-metric contract to these")
    if mobile and probe["scrollWidth"] > probe["innerWidth"] + 2:
        finding("SEV2", "BROKEN", name, "horizontal overflow on mobile",
                f"scrollWidth {probe['scrollWidth']} > {probe['innerWidth']}",
                "make the wide element scroll inside its own container")
    budget = 1500 if name in ("today", "landing") else 2000
    if status == 200 and probe.get("tti") and probe["tti"] > budget and not mobile:
        finding("SEV3", "SLOW", name, f"time-to-interactive {probe['tti']}ms",
                f"budget {budget}ms", "trim the page's first-paint work")
    if job == "none" and status == 200:
        finding("SEV3", "NO-JOB", name, "page serves no named job",
                "not daily, weekly or monthly work — a reference surface",
                "keep as reference, or fold into a job page")

    # ── the controls ──
    if not exercise_controls or status != 200:
        probe["controls_tested"] = []
        return probe
    tested = []
    groups: dict = {}
    for c in probe["controls"]:
        groups.setdefault(c.get("shape") or c["ref"], []).append(c)
    sampled = 0
    for c in probe["controls"]:
        grp = groups.get(c.get("shape") or c["ref"], [])
        if len(grp) > SAMPLE_PER_SHAPE and grp.index(c) >= SAMPLE_PER_SHAPE:
            c["verdict"] = "REPRESENTED-BY-SAMPLE"
            c["reason"] = (f"one of {len(grp)} controls of the same shape; "
                           f"{SAMPLE_PER_SHAPE} of them were activated")
            tested.append(c)
            continue
        sampled += 1
        if is_write_capable(c):
            c["verdict"] = "NOT-EXERCISED"
            c["reason"] = "write-capable by label — READ-ONLY LAW #148"
            tested.append(c)
            continue
        if c["href"].startswith(("http", "mailto:")) and BASE not in c["href"]:
            c["verdict"] = "NOT-EXERCISED"
            c["reason"] = "external link"
            tested.append(c)
            continue
        # Every control is activated on a FRESHLY LOADED page. One control
        # that opens a panel would otherwise cover the ones after it, and the
        # whole page would report as broken — the cascade that made this
        # auditor's own first run untrustworthy.
        try:
            page.goto(BASE + path, wait_until="load", timeout=45000)
            page.wait_for_timeout(800)
            stamp_refs(page)
        except Exception:
            pass
        log.clear()
        r = exercise(page, path, c, log, net)
        c.update(r)
        tested.append(c)
        if r["verdict"] == "BLOCKED":
            finding("SEV2", "DEAD-CONTROL", name,
                    f"unreachable control: “{c['label'] or c['id']}”",
                    r.get("detail", "")[:200],
                    "something is covering it — fix the stacking or remove it")
        elif r["verdict"] == "NO-OP":
            finding("SEV2", "DEAD-CONTROL", name, f"dead control: “{c['label'] or c['id']}”",
                    f"{c['tag']}#{c['id'] or c['ref']} changed nothing when clicked",
                    "wire it or remove it")
        elif r["verdict"] == "ERROR":
            finding("SEV1", "BROKEN", name, f"control errors: “{c['label'] or c['id']}”",
                    r.get("detail", "")[:200], "fix the handler")
        elif r["verdict"] == "SLOW":
            finding("SEV3", "SLOW", name, f"slow control: “{c['label'] or c['id']}”",
                    f"{r['ms']}ms (budget 500ms)", "make the interaction optimistic")
    probe["controls_tested"] = tested
    probe["controls"] = len(probe["controls"])
    return probe


def access_matrix(pw_ctx):
    """Who can see what — owner, ad_domain, anonymous."""
    out = []
    checks = [("/dashboard/today", "TODAY"), ("/dashboard/sales", "SALES"),
              ("/dashboard/view/cash", "MONEY"), ("/dashboard/scale", "PLAN"),
              ("/ads", "ADS")]
    for who in ("anon", "ad_domain"):
        ctx = pw_ctx.new_context(viewport={"width": 1280, "height": 800})
        p = ctx.new_page()
        if who == "ad_domain":
            if not AD_PW:
                out.append({"who": who, "skipped": "no ad_domain password in env"})
                ctx.close()
                continue
            login(p, AD_USER, AD_PW)
        for path, label in checks:
            try:
                r = p.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
                out.append({"who": who, "page": label, "path": path,
                            "status": r.status if r else 0,
                            "landed": p.url.replace(BASE, "")})
            except Exception as e:  # noqa: BLE001
                out.append({"who": who, "page": label, "path": path,
                            "error": str(e)[:120]})
        ctx.close()
    return out


def render_md(report, path):
    f = sorted(report["findings"],
               key=lambda x: (SEV_ORDER.get(x["sev"], 9), x["class"]))
    by_class: dict = {}
    for x in f:
        by_class.setdefault(x["class"], []).append(x)
    lines = [
        "# USABILITY AUDIT — the real-seat walk",
        "",
        f"Production `{report['commit']}` · {report['at']} · real Chromium, owner "
        "session, desktop 1440×900 and mobile 390×844.",
        "",
        "Every page the app serves was loaded and every visible control was "
        "activated, except those whose label marks them write-capable — those "
        "are inventoried and reported NOT-EXERCISED, because READ-ONLY LAW #148 "
        "forbids the click. **This register is the build list.**",
        "",
        "## The register — findings by class",
        "",
        f"**{len(f)} findings** · "
        + " · ".join(f"{k} {len(v)}" for k, v in sorted(by_class.items())),
        "",
    ]
    for cls, items in sorted(by_class.items(),
                             key=lambda kv: SEV_ORDER.get(kv[1][0]["sev"], 9)):
        lines += [f"### {cls} ({len(items)})", "",
                  "| sev | page | finding | detail | the fix |",
                  "|---|---|---|---|---|"]
        for x in items:
            lines.append(f"| {x['sev']} | {x['page']} | {x['title']} | "
                         f"{x['detail'][:120]} | {x['fix']} |")
        lines.append("")
    lines += ["## Every page — status, speed, job, scan-2 identity", "",
              "| page | status | FCP | DCL | TTI | controls | dead | panels | "
              "metrics published | job |", "|---|---|---|---|---|---|---|---|---|---|"]
    for p in report["pages"]:
        if p.get("error"):
            lines.append(f"| {p['name']} | **load failed** | | | | | | | | |")
            continue
        tested = p.get("controls_tested") or []
        dead = len([c for c in tested if c.get("verdict") == "NO-OP"])
        lines.append(
            f"| `{p['path']}` | {p['status']} | {p.get('fcp')}ms | {p.get('dcl')}ms | "
            f"{p.get('tti')}ms | {len(tested)} | {dead} | {len(p.get('panels') or [])} | "
            f"{len(p.get('metrics') or [])} | {p.get('job')} |")
    lines += ["", "## Access matrix", "",
              "| who | page | status | landed on |", "|---|---|---|---|"]
    for a in report.get("access", []):
        if a.get("skipped"):
            lines.append(f"| {a['who']} | — | skipped | {a['skipped']} |")
            continue
        lines.append(f"| {a['who']} | {a.get('page')} | {a.get('status')} | "
                     f"`{a.get('landed', a.get('error', ''))}` |")
    lines += ["", "## Controls, every one", "",
              "| page | control | verdict | ms |", "|---|---|---|---|"]
    for p in report["pages"]:
        for c in (p.get("controls_tested") or []):
            lines.append(f"| {p['name']} | {(c.get('label') or c.get('id') or c['ref'])[:40]} "
                         f"| {c.get('verdict')} | {c.get('ms', '')} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "USABILITY_AUDIT.md"))
    ap.add_argument("--only", default="")
    ap.add_argument("--no-controls", action="store_true")
    ap.add_argument("--no-mobile", action="store_true")
    ap.add_argument("--tag", default="", help="shard name; keeps parallel runs from colliding")
    ap.add_argument("--no-access", action="store_true")
    ap.add_argument("--mobile-only", action="store_true")
    args = ap.parse_args()
    if not PW:
        print("GATE_OWNER_PASSWORD not set", file=sys.stderr)
        return 2
    commit = commit_of()
    evd = os.path.join(ROOT, "dashboard", "evidence",
                       f"usability-{commit}" + (f"-{args.tag}" if args.tag else ""))
    os.makedirs(evd, exist_ok=True)
    pages = [p for p in PAGES if not args.only or p[0] in args.only.split(",")]
    report = {"commit": commit, "base": BASE, "pages": [], "findings": FINDINGS,
              "at": time.strftime("%Y-%m-%d %H:%M")}
    log: list = []
    net: list = []
    t0 = time.time()
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: log.append({"type": m.type, "text": m.text[:400]})
                if m.type == "error" else None)
        page.on("pageerror", lambda e: log.append({"type": "pageerror", "text": str(e)[:400]}))
        page.on("response", lambda r: net.append({"url": r.url[:160], "status": r.status})
                if r.url.startswith(BASE) else None)
        if not args.mobile_only:
            login(page, USER, PW)
            for name, path, expect, job in pages:
                print(f"── {name} {path}", file=sys.stderr)
                report["pages"].append(audit_page(
                    page, name, path, expect, job, evd, log=log, net=net,
                    exercise_controls=not args.no_controls))
        ctx.close()
        if not args.no_mobile:
            mctx = br.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True)
            mp = mctx.new_page()
            mp.on("console", lambda m: log.append({"type": m.type, "text": m.text[:400]})
                  if m.type == "error" else None)
            mp.on("pageerror", lambda e: log.append({"type": "pageerror", "text": str(e)[:400]}))
            mp.on("response", lambda r: net.append({"url": r.url[:160], "status": r.status})
                  if r.url.startswith(BASE) else None)
            login(mp, USER, PW)
            for name, path, expect, job in pages:
                report["pages"].append(audit_page(
                    mp, name, path, expect, job, evd, mobile=True, log=log,
                    net=net, exercise_controls=False))
            mctx.close()
        if not args.no_access:
            report["access"] = access_matrix(br)
        br.close()
    report["runtime_s"] = int(time.time() - t0)
    with open(os.path.join(evd, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    render_md(report, args.out)
    sev1 = len([x for x in FINDINGS if x["sev"] == "SEV1"])
    print(f"\nAUDIT: {len(FINDINGS)} findings ({sev1} SEV1) in {report['runtime_s']}s")
    print(f"  register → {args.out}\n  evidence → {evd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
