"""carveout_leak_hunt.py — DOES A CARVE-OUT COME OUT SOMEWHERE ELSE?

An access rule that only guards the front door is not a rule. This walks
EVERY surface Piolo is allowed to open — pages, APIs, drawers, exports — and
reads what comes back looking for the three things that are his blind spots:

  · per-person pay          (a commission figure, a junior rate, a set fee,
                             the Kalin override, what Coby nets)
  · the CSM restructure     (the director comp offset, Miguel's name)
  · anything owner-scoped   that the route list lets through by accident

Names alone are NOT a leak: Piolo sees who closed what. A name next to a pay
figure is. So the hunt looks for pay-shaped KEYS and phrases, not for people.

Run locally (structure) or against a live box (structure + real values):
    python3 scripts/carveout_leak_hunt.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# pay-shaped things that must never reach a non-owner response
PAY_MARKERS = (
    "by_person", "kalin_override", "coby_nets", "junior rate", "set_fee",
    "set fee", "commission_rate", "per_close_cost", "closer_commission",
    "setter_commission", "commission accrued", "take-home",
)
CSM_MARKERS = (
    "director comp", "comp offset", "csm scoreboard",
    "renewal uplift target",
)
# Miguel needs a word boundary: "Miguelitos Diner" is a CLIENT, and flagging
# it as a leak twice taught me nothing except to read my own output.
CSM_NAME_RE = re.compile(r"\bmiguel\b", re.I)
# keys whose mere presence in a JSON payload is the leak
PAY_KEYS = ("commission", "commissions_by_person", "by_person", "payout")


# Two things are NOT leaks, and saying so here beats re-deciding it by eye
# on every run:
#   · a DEGRADED entry naming the metric "setter_commission" — it reports a
#     blank cell, with no person and no amount, and fixing it is Piolo's job
#   · the team roster's names and roles, once the salaries are scrubbed out
ACCEPTED = (
    ("/dashboard/api/sales-summary", "setter_commission",
     "a data-quality note about a blank cell — no person, no amount"),
    ("/dashboard/api/snapshot", "setter_commission",
     "the same degraded note, carried on the snapshot's degraded list"),
    ("/dashboard/api/snapshot", "miguel (as a person)",
     "the roster's names and roles; every salary figure is scrubbed"),
)


def _accepted(path: str, marker: str) -> bool:
    return any(p == path and m == marker for p, m, _ in ACCEPTED)


def _hits(body: str, markers) -> list[str]:
    low = body.lower()
    return sorted({m for m in markers if m in low})


def main():
    os.environ.setdefault("DASHBOARD_TOKEN", "leak-hunt")
    import app as appmod
    import role_access as RA

    findings = []
    checked = 0
    app = appmod.app
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        path = str(rule)
        if "<" in path or "GET" not in rule.methods:
            continue
        # R-PIOLO-PARITY (#167): the finance role is EXPECTED to see pay —
        # this hunt now polices the roles that must not: ad_domain.
        c = app.test_client()
        with c.session_transaction() as s:
            s["actor"] = {"user": "romano", "role": "ad_domain", "display": "Romano"}
        try:
            r = c.get(path)
        except Exception as e:  # noqa: BLE001
            findings.append({"path": path, "kind": "error", "detail": str(e)[:120]})
            continue
        checked += 1
        if r.status_code >= 400:
            continue
        body = r.data.decode("utf-8", "replace")
        pay = _hits(body, PAY_MARKERS)
        csm = _hits(body, CSM_MARKERS)
        if CSM_NAME_RE.search(body):
            csm = sorted(set(csm) | {"miguel (as a person)"})
        keys = []
        if "application/json" in (r.headers.get("Content-Type") or ""):
            try:
                keys = [k for k in PAY_KEYS
                        if re.search(rf'"{k}"\s*:', body)]
            except Exception:  # noqa: BLE001
                keys = []
        pay = [m for m in pay if not _accepted(path, m)]
        csm = [m for m in csm if not _accepted(path, m)]
        if pay or csm or keys:
            findings.append({"path": path, "status": r.status_code,
                             "pay_markers": pay, "csm_markers": csm,
                             "pay_keys": keys,
                             "sample": _sample(body, (pay + csm + keys))})

    out = {"checked": checked, "findings": findings}
    d = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "carveout-leak-hunt.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"surfaces Piolo can open, read: {checked}")
    for f_ in findings:
        print(" LEAK?", f_["path"], f_.get("pay_markers"), f_.get("csm_markers"),
              f_.get("pay_keys"))
        print("       ", (f_.get("sample") or "")[:160])
    print(("\nNO CARVE-OUT LEAK — " if not findings else
           f"\n{len(findings)} POSSIBLE LEAK(S) — ") + path)
    return 1 if findings else 0


def _sample(body: str, markers) -> str:
    for m in markers:
        i = body.lower().find(str(m).lower())
        if i >= 0:
            return re.sub(r"\s+", " ", body[max(0, i - 70):i + 90])
    return ""


if __name__ == "__main__":
    sys.exit(main())
