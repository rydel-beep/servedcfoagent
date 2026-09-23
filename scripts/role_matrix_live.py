"""role_matrix_live.py — THE ACCESS RULE AS PRODUCTION ENFORCES IT.

The local matrix reads the rule; this one asks the running server. Real
logins, real sessions, real status codes, every GET route in the map, plus
the money-truth actions probed with a POST that the server must refuse.

Run it under `railway run` so the passwords come from the environment and are
never typed:  railway run python3 scripts/role_matrix_live.py
"""
from __future__ import annotations

import json
import os
import sys

import requests

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")

ACCOUNTS = [
    ("owner", "rydel", os.environ.get("RYDEL_PASSWORD")),
    ("coo", "piolo", os.environ.get("PIOLO_PASSWORD")),
    ("anon", None, None),
]

# what Piolo must be able to open
GRANTED = [
    "/dashboard/today", "/dashboard/sales", "/dashboard/scale",
    "/dashboard/scale/travelling", "/dashboard/system", "/dashboard/landing",
    "/dashboard/api/travelling", "/dashboard/api/unit-economics",
    "/dashboard/api/decision-cards", "/dashboard/api/ar",
    "/dashboard/api/outflow-bands", "/dashboard/api/scale/defaults",
    "/dashboard/api/unmatched", "/dashboard/api/closes/pending",
    "/dashboard/api/finance-analysis", "/dashboard/api/ground-truth",
    "/dashboard/api/renewal/clients", "/dashboard/api/snapshot",
]
# what must refuse him
REFUSED_GET = [
    "/dashboard/api/csm/model", "/dashboard/api/comp/rules",
    "/dashboard/api/comp/cost", "/dashboard/api/tts",
    "/dashboard/memory/api/facts", "/dashboard/api/voice-status",
]
REFUSED_POST = [
    "/dashboard/api/unmatched/confirm", "/dashboard/api/closes/confirm",
    "/dashboard/api/renewal/declare", "/dashboard/api/targets/set",
    "/dashboard/api/scale/commit-plan", "/dashboard/api/gap/rebuild",
    "/dashboard/api/refresh-now", "/dashboard/api/comp/rules",
]
# a route nobody has classified
UNKNOWN = "/dashboard/api/not-a-real-route-161"


def session_for(user, pw):
    s = requests.Session()
    if user:
        r = s.post(BASE + "/dashboard/login",
                   data={"username": user, "password": pw}, timeout=30,
                   allow_redirects=False)
        if r.status_code not in (302, 200):
            raise SystemExit(f"login failed for {user}: {r.status_code}")
    return s


def main():
    if not os.environ.get("PIOLO_PASSWORD"):
        print("PIOLO_PASSWORD not in env — run under `railway run`", file=sys.stderr)
        return 2
    out = {"base": BASE, "granted": {}, "refused_get": {}, "refused_post": {},
           "unknown_route": {}, "fails": []}
    sessions = {}
    for label, user, pw in ACCOUNTS:
        sessions[label] = session_for(user, pw)

    coo = sessions["coo"]
    for p in GRANTED:
        code = coo.get(BASE + p, timeout=90, allow_redirects=False).status_code
        out["granted"][p] = code
        if code != 200:
            out["fails"].append(f"piolo cannot open {p} ({code})")
    for p in REFUSED_GET:
        code = coo.get(BASE + p, timeout=60, allow_redirects=False).status_code
        out["refused_get"][p] = code
        if code not in (302, 403):
            out["fails"].append(f"piolo reached {p} ({code})")
    for p in REFUSED_POST:
        code = coo.post(BASE + p, json={}, timeout=60,
                        allow_redirects=False).status_code
        out["refused_post"][p] = code
        if code != 403:
            out["fails"].append(f"piolo could POST {p} ({code})")
    out["unknown_route"] = {
        "GET": coo.get(BASE + UNKNOWN, timeout=30, allow_redirects=False).status_code,
        "POST": coo.post(BASE + UNKNOWN, json={}, timeout=30,
                         allow_redirects=False).status_code}

    anon = sessions["anon"]
    out["anon"] = {p: anon.get(BASE + p, timeout=30,
                               allow_redirects=False).status_code
                   for p in ("/dashboard/today", "/dashboard/api/snapshot")}
    for p, code in out["anon"].items():
        if code not in (302, 401, 403):
            out["fails"].append(f"anonymous reached {p} ({code})")

    owner = sessions["owner"]
    out["owner_still_has_it"] = {
        p: owner.get(BASE + p, timeout=60, allow_redirects=False).status_code
        for p in ("/dashboard/api/comp/rules", "/dashboard/csm",
                  "/dashboard/api/tts?text=hello")}
    for p, code in out["owner_still_has_it"].items():
        if code != 200:
            out["fails"].append(f"OWNER lost {p} ({code})")

    d = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "role-matrix-live.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    print(("\nLIVE MATRIX PASS — " if not out["fails"] else
           f"\nLIVE MATRIX FAIL ({len(out['fails'])}) — ") + path)
    return 1 if out["fails"] else 0


if __name__ == "__main__":
    sys.exit(main())
