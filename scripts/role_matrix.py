"""role_matrix.py — WHO CAN REACH WHAT, read off the code itself.

Two passes, because either alone can lie:

  STATIC   every @route in the blueprints with the decorators guarding it, so
           the intended rule is visible even for endpoints that need live data.
  LIVE     the app's own test client, one session per role, issuing the real
           request and recording the real status — the rule as ENFORCED.

GET routes are probed live. POST routes are listed but not fired: some of them
are money-truth actions, and a matrix is not worth performing a write to learn.

Usage:  python3 scripts/role_matrix.py [--json out.json]
"""
from __future__ import annotations

import ast
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

BLUEPRINT_FILES = [
    ("dashboard/routes.py", "/dashboard"),
    ("dashboard/ads.py", "/ads"),
    ("dashboard/bridge.py", "/bridge"),
    ("dashboard/memory_routes.py", "/dashboard/memory"),
]

ROLES = [
    ("owner", {"user": "rydel", "role": "owner", "display": "Rydel"}),
    ("coo", {"user": "piolo", "role": "coo", "display": "Piolo"}),
    ("ad_domain", {"user": "romano", "role": "ad_domain", "display": "Romano"}),
    ("sales", {"user": "sales", "role": "sales", "display": "Sales"}),
    ("anon", None),
]

DENY_CODES = {401, 403}


def static_map() -> dict:
    """{rule_suffix: [decorator names]} straight from the source."""
    out = {}
    for rel, prefix in BLUEPRINT_FILES:
        path = os.path.join(ROOT, rel)
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes, guards = [], []
            for d in node.decorator_list:
                name = _dec_name(d)
                if name and name.endswith("route"):
                    if d.args and isinstance(d.args[0], ast.Constant):
                        routes.append(prefix.rstrip("/") + d.args[0].value)
                elif name:
                    guards.append(name)
            for r in routes:
                out[r] = {"view": node.name, "guards": guards, "file": rel}
    return out


def _dec_name(d) -> str | None:
    if isinstance(d, ast.Call):
        d = d.func
    if isinstance(d, ast.Attribute):
        return d.attr
    if isinstance(d, ast.Name):
        return d.id
    return None


def live_probe() -> dict:
    os.environ.setdefault("DASHBOARD_TOKEN", "matrix-probe")
    import app as appmod
    rows = {}
    rules = sorted(appmod.app.url_map.iter_rules(), key=lambda r: str(r))
    for rule in rules:
        path = str(rule)
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        if "<" in path or "GET" not in methods:
            rows[path] = {"methods": methods, "probed": False,
                          "note": "not probed (parameterised or write-only)"}
            continue
        res = {}
        for label, actor in ROLES:
            c = appmod.app.test_client()
            if actor:
                with c.session_transaction() as s:
                    s["actor"] = actor
            try:
                r = c.get(path)
                code = r.status_code
                where = (r.headers.get("Location") or "")
            except Exception as e:  # a view that explodes is still REACHED
                code, where = 500, str(e)[:60]
            res[label] = {"status": code,
                          "verdict": _verdict(code, where),
                          "redirect": where[:60] or None}
        rows[path] = {"methods": methods, "probed": True, "roles": res}
    return rows


def _verdict(code: int, where: str) -> str:
    if code in DENY_CODES:
        return "DENIED"
    if code >= 500:
        # NOT a pass. A guard that raises while refusing reads as "reached"
        # to anything counting 2xx — caught exactly that way on the memory
        # page, where the redirect named an endpoint that does not exist.
        return "ERROR"
    if code in (301, 302, 303, 307, 308):
        w = (where or "").lower()
        if "login" in w:
            return "DENIED (login)"
        return f"REDIRECT"
    return "REACHED"


def main():
    static = static_map()
    live = live_probe()
    report = {"static": static, "live": live}
    out = None
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        with open(out, "w") as f:
            json.dump(report, f, indent=1)
    probed = [p for p, v in live.items() if v.get("probed")]
    print(f"routes: {len(live)} · probed: {len(probed)} · static rules: {len(static)}")
    for path in sorted(probed):
        r = live[path]["roles"]
        print("%-46s %s" % (path[:46], " · ".join(
            f"{k}:{v['verdict'].split()[0]}" for k, v in r.items())))
    if out:
        print("→", out)


if __name__ == "__main__":
    main()
