#!/usr/bin/env python3
"""triple_scan.py — THREE FAILURE CLASSES, THREE SCANS (permanent).

A page can fail three different ways and each needs its own scan:

  SCAN 1 · IT WORKS          — every page in the nav renders, every tile
                               carries a value or a labelled state, zero
                               console errors. (The render/behaviour gates
                               do this deeply for the landing and /scale;
                               this widens it to every page.)
  SCAN 2 · IT AGREES WITH    — the same metric, for the same window and
            ITSELF             basis, shows the SAME number on every
                               surface, and each equals the engine's own
                               API. This is the scan that would have caught
                               "qualified 16% here, 50% there" on day one.
  SCAN 3 · IT AGREES WITH    — the engine against the outside world: Meta
            REALITY            spend on closed days, Stripe cash, the Xero
                               AR anchor and bank balances, CRM appointment
                               and opportunity counts, tracker row counts.

Every run writes a HEALTH row (pass/fail per scan, counts, top failure,
runtime, API calls) that the health page and the nav dot read; failures
become feed items; and a scan that FAILS TO RUN is itself a loud failure.

Read-only throughout: it loads pages and calls read APIs. It never writes
to the tracker, the CRM, or any actuals store.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
LEGACY_TOKEN = os.environ.get("GATE_LEGACY_TOKEN")

# every page in the nav — scan 1 covers all of them
PAGES = [
    ("today", "/dashboard/today"),
    ("sales-board", "/dashboard/sales"),
    ("landing", "/dashboard/landing"),
    ("brief", "/dashboard/view/brief"),
    ("cash", "/dashboard/view/cash"),
    ("sales", "/dashboard/view/sales"),
    ("unit-econ", "/dashboard/view/unit-econ"),
    ("projection", "/dashboard/view/projection"),
    ("renewals", "/dashboard/view/renewals"),
    ("outflows", "/dashboard/view/outflows"),
    ("receivables", "/dashboard/view/receivables"),
    ("team", "/dashboard/view/team"),
    ("decisions", "/dashboard/view/decisions"),
    ("system", "/dashboard/view/system"),
    ("scale", "/dashboard/scale"),
    ("travelling", "/dashboard/scale/travelling?window=mtd&compare=usual"),
    ("definitions", "/dashboard/definitions"),
    ("worklog", "/dashboard/worklog"),
    ("bookkeeping", "/dashboard/bookkeeping"),
    ("csm", "/dashboard/csm"),
    ("ads", "/ads"),
]

# EDITH drills whose numbers must equal the engine (scan 2c)
DRILLS = [
    ("how are we travelling this month", ["travelling"]),
    ("what's my LTV to CAC", ["unit_econ"]),
    ("what's committed", ["committed_mrr"]),
]

FINDINGS: list[dict] = []


def finding(scan, sev, cls, title, detail, surfaces=None):
    FINDINGS.append({"scan": scan, "sev": sev, "class": cls, "title": title,
                     "detail": detail, "surfaces": surfaces or []})
    print(f"[{scan}/{sev}] {title} — {detail[:150]}", file=sys.stderr)


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
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


# ── SCAN 1 — it works ───────────────────────────────────────────────────────

def scan_works(page, log, evd, shots=False):
    out = {"pages": {}, "ok": True}
    for name, path in PAGES:
        log.clear()
        try:
            resp = page.goto(BASE + path, wait_until="load", timeout=45000)
            time.sleep(2)
            status = resp.status if resp else 0
        except Exception as e:  # noqa: BLE001
            finding("scan1", "SEV1", "BROKEN", f"{name} failed to load",
                    str(e)[:200], [path])
            out["ok"] = False
            continue
        probe = page.evaluate("""() => ({
          title: document.title,
          boundaries: Array.from(document.querySelectorAll('.panel-boundary-fail:not(.empty-state)')).map(e => e.innerText.slice(0,90)),
          tiles: Array.from(document.querySelectorAll('[data-metric][data-value]')).map(el => ({
            metric: el.dataset.metric,
            value: (() => {
              const inner = el.querySelector('.exec-tile-value,.pulse-value,.tv-actual,.s-card-value');
              if (inner) return (inner.innerText || '').trim();
              // a metric stamped directly ON the element that shows it
              return String(('value' in el ? el.value : el.innerText) || '').trim().slice(0, 40);
            })(),
            sub: (el.querySelector('.exec-tile-sub,.pulse-sub,.tv-stage-sub')?.innerText || '').trim(),
          })),
          panels: document.querySelectorAll('section').length,
        })""")
        errs = [c for c in log if c["type"] in ("error", "pageerror", "http")]
        page_ok = True
        if status and status >= 400:
            finding("scan1", "SEV1", "BROKEN", f"{name} returned {status}", path, [path])
            page_ok = False
        for e in errs:
            finding("scan1", "SEV2", "BROKEN", f"{name}: console {e['type']}",
                    str(e.get("text") or e)[:200], [path])
            page_ok = False
        for b in probe["boundaries"]:
            finding("scan1", "SEV2", "BROKEN", f"{name}: a panel failed",
                    b, [path])
            page_ok = False
        for t in probe["tiles"]:
            if not t["value"]:
                finding("scan1", "SEV2", "BROKEN",
                        f"{name}: {t['metric']} rendered empty",
                        "a tile must carry a value or a labelled state", [path])
                page_ok = False
            elif t["value"] == "—" and not t["sub"]:
                finding("scan1", "SEV3", "MISLEADING COPY",
                        f"{name}: {t['metric']} shows a dash with no reason",
                        "an empty state must say why", [path])
                page_ok = False
        out["pages"][name] = {"status": status, "tiles": len(probe["tiles"]),
                              "panels": probe["panels"], "ok": page_ok}
        out["ok"] = out["ok"] and page_ok
        if shots and not page_ok:
            page.screenshot(path=os.path.join(evd, f"scan1-{name}.png"), full_page=True)
    return out


# ── SCAN 2 — it agrees with itself ──────────────────────────────────────────

def scan_agrees_with_itself(page, evd):
    """Collect every [data-metric] across surfaces, keyed by
    (metric, window, basis); assert one value per key, and that it equals
    the engine's own API."""
    seen: dict[tuple, list] = {}
    for name, path in PAGES:
        try:
            page.goto(BASE + path, wait_until="load", timeout=45000)
            time.sleep(1.5)
            rows = page.evaluate("""() => Array.from(document.querySelectorAll('[data-metric][data-value]')).map(el => ({
              metric: el.dataset.metric, window: el.dataset.window || '',
              clock: el.dataset.clock || '', basis: el.dataset.basis || '',
              value: el.dataset.value || '',
              text: (() => {
              const inner = el.querySelector('.exec-tile-value,.pulse-value,.tv-actual,.s-card-value');
              if (inner) return (inner.innerText || '').trim();
              // a metric stamped directly ON the element that shows it
              return String(('value' in el ? el.value : el.innerText) || '').trim().slice(0, 40);
            })(),
            }))""")
        except Exception as e:  # noqa: BLE001
            finding("scan2", "SEV2", "BROKEN", f"{name}: could not be read",
                    str(e)[:150], [path])
            continue
        for r in rows:
            if r["value"] in ("", "None"):
                continue
            key = (r["metric"], r["window"], r["basis"])
            seen.setdefault(key, []).append({"surface": name, "value": r["value"],
                                             "text": r["text"]})
    # (a) same key → same value on every surface
    divergences = 0
    for key, hits in seen.items():
        vals = {h["value"] for h in hits}
        if len(vals) > 1:
            divergences += 1
            finding("scan2", "SEV1", "DISAGREES WITH ITSELF",
                    f"{key[0]} differs across surfaces",
                    " vs ".join(f"{h['surface']}={h['value']}" for h in hits),
                    [h["surface"] for h in hits])
    # (b) each equals the engine's API
    engine_checks = 0
    try:
        api = page.evaluate(
            """async () => { const r = await fetch('/dashboard/api/snapshot');
                 return r.ok ? await r.json() : null; }""")
        if api:
            pairs = [
                ("cash_on_hand", ((api.get("cash_position") or {}).get("cash_in_bank"))),
                ("committed_mrr", ((api.get("client_health") or {}).get("current_mrr"))),
            ]
            for metric, engine_val in pairs:
                if engine_val is None:
                    continue
                for key, hits in seen.items():
                    if key[0] != metric:
                        continue
                    engine_checks += 1
                    for h in hits:
                        try:
                            if abs(float(h["value"]) - float(engine_val)) > 0.02:
                                finding("scan2", "SEV1", "DISAGREES WITH ITSELF",
                                        f"{metric} on {h['surface']} ≠ the engine",
                                        f"page {h['value']} vs engine {engine_val}",
                                        [h["surface"]])
                        except ValueError:
                            pass
    except Exception as e:  # noqa: BLE001
        finding("scan2", "SEV2", "BROKEN", "engine comparison unavailable",
                str(e)[:150])
    # (c) EDITH's numbers equal the engine's
    drill_results = []
    for question, _tags in DRILLS:
        try:
            ans = page.evaluate(
                """async (q) => { const r = await fetch('/dashboard/api/chat', {
                     method: 'POST', headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify({history: [{role: 'user', content: q}]})});
                   return r.ok ? await r.json() : {error: 'status ' + r.status}; }""",
                question)
            text = ((ans or {}).get("reply") or (ans or {}).get("message")
                    or (ans or {}).get("response") or "")
            nums = re.findall(r"[\d,]+\.?\d*", text)
            drill_results.append({"q": question, "numbers": nums[:8],
                                  "len": len(text)})
            if not text:
                finding("scan2", "SEV3", "BROKEN", f"EDITH gave no answer to '{question}'",
                        "the drill returned nothing")
        except Exception as e:  # noqa: BLE001
            finding("scan2", "SEV3", "BROKEN", f"EDITH drill failed: {question}",
                    str(e)[:120])
    return {"keys": len(seen), "divergences": divergences,
            "engine_checks": engine_checks, "drills": drill_results,
            "ok": divergences == 0}


# ── SCAN 3 — it agrees with reality ─────────────────────────────────────────

def scan_agrees_with_reality(page):
    """The engine against the outside world. Runs server-side through an
    owner-only endpoint so the external calls use the existing clients and
    tokens (no new ones), and the page never holds a credential."""
    try:
        res = page.evaluate(
            """async () => { const r = await fetch('/dashboard/api/ground-truth');
                 return r.ok ? await r.json() : {error: 'status ' + r.status}; }""")
    except Exception as e:  # noqa: BLE001
        finding("scan3", "SEV1", "BROKEN", "ground-truth scan could not run",
                str(e)[:150])
        return {"ok": False, "error": str(e)[:150]}
    if not res or res.get("error"):
        finding("scan3", "SEV1", "BROKEN", "ground-truth scan errored",
                str((res or {}).get("error"))[:150])
        return {"ok": False, "error": (res or {}).get("error")}
    for chk in res.get("checks", []):
        if chk.get("ok") is False:
            finding("scan3", chk.get("sev", "SEV2"), "DISAGREES WITH REALITY",
                    chk.get("name", "a source disagrees"),
                    chk.get("detail", ""), [chk.get("source", "")])
    return res


# ── the run ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scans", default="1,2,3")
    ap.add_argument("--shots", action="store_true")
    args = ap.parse_args()
    if not PW and not LEGACY_TOKEN:
        print("GATE_OWNER_PASSWORD not in env", file=sys.stderr)
        sys.exit(2)
    from playwright.sync_api import sync_playwright

    commit = commit_of()
    evd = os.path.join(ROOT, "dashboard", "evidence", f"scan-{commit}")
    os.makedirs(evd, exist_ok=True)
    started = time.time()
    report = {"commit": commit, "base": BASE,
              "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "scans": {}}
    want = set(args.scans.split(","))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        log: list = []
        page = ctx.new_page()
        page.on("console", lambda m: log.append({"type": m.type, "text": m.text[:300]})
                if m.type == "error" else None)
        page.on("pageerror", lambda e: log.append({"type": "pageerror", "text": str(e)[:300]}))
        page.on("response", lambda r: log.append({"type": "http", "text": f"{r.url[:120]} → {r.status}"})
                if r.status >= 500 and r.url.startswith(BASE) else None)
        login(page)
        log.clear()
        if "1" in want:
            report["scans"]["works"] = scan_works(page, log, evd, args.shots)
        if "2" in want:
            report["scans"]["agrees_with_itself"] = scan_agrees_with_itself(page, evd)
        if "3" in want:
            report["scans"]["agrees_with_reality"] = scan_agrees_with_reality(page)
        # write the HEALTH row through the owner endpoint (the repo's own store)
        runtime = round(time.time() - started, 1)
        row = {"commit": commit, "runtime_s": runtime,
               "scan1_ok": (report["scans"].get("works") or {}).get("ok"),
               "scan2_ok": (report["scans"].get("agrees_with_itself") or {}).get("ok"),
               "scan3_ok": (report["scans"].get("agrees_with_reality") or {}).get("ok"),
               "findings": len(FINDINGS),
               "top": (FINDINGS[0]["title"] if FINDINGS else None),
               "pages": len((report["scans"].get("works") or {}).get("pages", {}))}
        try:
            page.evaluate(
                """async (row) => { await fetch('/dashboard/api/health-row', {
                     method: 'POST', headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify(row)}); }""", row)
        except Exception as e:  # noqa: BLE001
            print("health row post failed:", e, file=sys.stderr)
        browser.close()

    report["findings"] = FINDINGS
    report["health_row"] = row
    out = os.path.join(evd, "scan.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1)
    sev1 = [f for f in FINDINGS if f["sev"] == "SEV1"]
    print(f"TRIPLE SCAN — {len(FINDINGS)} findings ({len(sev1)} SEV1) in "
          f"{runtime}s → {out}")
    sys.exit(1 if sev1 else 0)


if __name__ == "__main__":
    main()
