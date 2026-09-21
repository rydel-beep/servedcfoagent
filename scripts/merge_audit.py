#!/usr/bin/env python3
"""merge_audit.py — assemble the sharded real-seat audit into ONE register.

The audit walks 25 pages and activates every control on a freshly loaded
page, which is slow enough that it runs as parallel shards. This merges
their report.json files into USABILITY_AUDIT.md — the single findings
register that is the build list.
"""
import glob
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEV_ORDER = {"SEV1": 0, "SEV2": 1, "SEV3": 2}
# What each page is FOR. A page serving no named job is a finding, not a fact.
JOBS = {
    "today": "daily · are we winning?", "landing": "daily · the old landing",
    "brief": "daily · the long read", "sales": "daily · the team scoreboard",
    "sales-area": "daily · ads & sales panels", "ads": "daily · creative decisions",
    "leads": "daily · reactivation", "cash": "weekly · cash & capital",
    "receivables": "weekly · who owes", "decisions": "weekly · rulings",
    "system": "weekly · is the estate honest", "travelling": "weekly · plan vs actual",
    "worklog": "weekly · collaboration", "unit-econ": "monthly · unit economics",
    "projection": "monthly · forward MRR", "renewals": "monthly · churn",
    "outflows": "monthly · OpEx & BAS", "team": "monthly · team & hiring",
    "scale": "monthly · the compass", "csm": "monthly · CSM cockpit",
    "bookkeeping": "monthly · the queue", "targets": "monthly · targets",
    "definitions": "none · reference", "data-sources": "none · reference",
    "memory": "none · reference",
}


def main():
    dirs = sys.argv[1:] or sorted(glob.glob(
        os.path.join(ROOT, "dashboard", "evidence", "usability-*")))
    pages, findings, access, commit, runtime = [], [], [], "unknown", 0
    seen_finding = set()
    for d in dirs:
        rp = os.path.join(d, "report.json")
        if not os.path.exists(rp):
            continue
        r = json.load(open(rp, encoding="utf-8"))
        commit = r.get("commit") or commit
        runtime += r.get("runtime_s") or 0
        pages += r.get("pages") or []
        access += r.get("access") or []
        for f in r.get("findings") or []:
            key = (f["sev"], f["class"], f["page"], f["title"])
            if key in seen_finding:
                continue
            seen_finding.add(key)
            findings.append(f)

    # Findings a crawler cannot infer — a number that renders perfectly and
    # agrees with itself can still be describing the wrong window. These were
    # verified by hand against production and carry their evidence.
    sem = os.path.join(os.path.dirname(__file__), "audit_semantic_findings.json")
    if os.path.exists(sem):
        for f in json.load(open(sem, encoding="utf-8")):
            key = (f["sev"], f["class"], f["page"], f["title"])
            if key not in seen_finding:
                seen_finding.add(key)
                findings.append(f)

    desktop = [p for p in pages if not p.get("mobile")]
    mobile = [p for p in pages if p.get("mobile")]
    by_class: dict = {}
    for f in sorted(findings, key=lambda x: (SEV_ORDER.get(x["sev"], 9), x["class"])):
        by_class.setdefault(f["class"], []).append(f)

    controls = [c for p in desktop for c in (p.get("controls_tested") or [])]
    dead = [c for c in controls if c.get("verdict") in ("NO-OP", "BLOCKED")]
    errored = [c for c in controls if c.get("verdict") == "ERROR"]
    not_ex = [c for c in controls if c.get("verdict") == "NOT-EXERCISED"]
    no_identity = [p for p in desktop
                   if p.get("status") == 200 and not (p.get("metrics") or [])]

    L = [
        "# USABILITY AUDIT — the real-seat walk",
        "",
        f"Production `{commit}` · real Chromium, owner session, desktop "
        f"1440×900 and mobile 390×844 · {runtime}s of walking across parallel "
        "shards.",
        "",
        "Every page the app serves was loaded, and **every visible control was "
        "actually activated** — each one on a freshly reloaded page, so a panel "
        "opened by one control can never make the controls beneath it look "
        "broken. Controls whose label marks them write-capable are inventoried "
        "and reported NOT-EXERCISED: READ-ONLY LAW #148 forbids the click.",
        "",
        "**This register is the build list.** Nothing in this wave was built "
        "before it existed.",
        "",
        "## The shape of it",
        "",
        f"| pages walked | controls activated | dead or unreachable | errored | "
        f"not exercised (write-capable) | pages with no metric identity |",
        "|---|---|---|---|---|---|",
        f"| {len(desktop)} desktop + {len(mobile)} mobile | {len(controls)} | "
        f"{len(dead)} | {len(errored)} | {len(not_ex)} | {len(no_identity)} |",
        "",
        f"**{len(findings)} findings** · "
        + " · ".join(f"{k} {len(v)}" for k, v in sorted(by_class.items())),
        "",
    ]
    for cls, items in sorted(by_class.items(),
                             key=lambda kv: SEV_ORDER.get(kv[1][0]["sev"], 9)):
        L += [f"### {cls} — {len(items)}", "",
              "| sev | page | finding | detail | the fix |", "|---|---|---|---|---|"]
        for x in items:
            L.append(f"| {x['sev']} | `{x['page']}` | {x['title'].replace('|', '/')} "
                     f"| {x['detail'][:130].replace(chr(10), ' ').replace('|', '/')} "
                     f"| {x['fix']} |")
        L.append("")

    L += ["## Every page — status, speed, controls, identity, job", "",
          "| page | status | FCP | DCL | TTI | controls | dead | errored | "
          "panels | metric keys | the job it serves |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(desktop, key=lambda x: x.get("name") or ""):
        if p.get("error"):
            L.append(f"| `{p['path']}` | **load failed** | | | | | | | | | "
                     f"{JOBS.get(p['name'], '—')} |")
            continue
        t = p.get("controls_tested") or []
        L.append(
            f"| `{p['path']}` | {p['status']} | {p.get('fcp')}ms | "
            f"{p.get('dcl')}ms | {p.get('tti')}ms | {len(t)} | "
            f"{len([c for c in t if c.get('verdict') in ('NO-OP', 'BLOCKED')])} | "
            f"{len([c for c in t if c.get('verdict') == 'ERROR'])} | "
            f"{len(p.get('panels') or [])} | {len(set(p.get('metrics') or []))} | "
            f"{JOBS.get(p['name'], '—')} |")

    if mobile:
        L += ["", "## Mobile 390×844 — overflow and paint", "",
              "| page | status | FCP | overflow |", "|---|---|---|---|"]
        for p in sorted(mobile, key=lambda x: x.get("name") or ""):
            if p.get("error"):
                continue
            ov = ("**yes** — scrollWidth "
                  f"{p.get('scrollWidth')} > {p.get('innerWidth')}"
                  if (p.get("scrollWidth") or 0) > (p.get("innerWidth") or 0) + 2
                  else "none")
            L.append(f"| `{p['path']}` | {p['status']} | {p.get('fcp')}ms | {ov} |")

    if access:
        L += ["", "## Access matrix — who can reach what", "",
              "| who | page | status | landed on |", "|---|---|---|---|"]
        for a in access:
            if a.get("skipped"):
                L.append(f"| {a['who']} | — | skipped | {a['skipped']} |")
                continue
            L.append(f"| {a['who']} | {a.get('page')} | {a.get('status')} | "
                     f"`{a.get('landed', a.get('error', ''))}` |")

    L += ["", "## Dead, unreachable and errored controls — every one", "",
          "| page | control | verdict | detail |", "|---|---|---|---|"]
    for p in desktop:
        for c in (p.get("controls_tested") or []):
            if c.get("verdict") not in ("NO-OP", "BLOCKED", "ERROR"):
                continue
            L.append(f"| {p['name']} | "
                     f"{(c.get('label') or c.get('id') or c['ref'])[:44].replace(chr(10), ' ')} "
                     f"| {c['verdict']} | {(c.get('detail') or '')[:90]} |")

    L += ["", "## Not exercised — write-capable, inventoried not clicked", "",
          "| page | control |", "|---|---|"]
    for p in desktop:
        for c in (p.get("controls_tested") or []):
            if c.get("verdict") != "NOT-EXERCISED":
                continue
            L.append(f"| {p['name']} | "
                     f"{(c.get('label') or c.get('id') or c['ref'])[:60].replace(chr(10), ' ')} |")

    out = os.path.join(ROOT, "USABILITY_AUDIT.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"merged {len(dirs)} shards → {out}")
    print(f"  {len(findings)} findings · {len(desktop)} desktop pages · "
          f"{len(controls)} controls · {len(dead)} dead · {len(errored)} errored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
