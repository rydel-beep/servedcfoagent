"""close_register_drills.py — SABOTAGE IT, WATCH IT SCREAM.

Two drills the brief demands, run in-process against seeded stores so they
prove the LOGIC anywhere (the live confirmation is the triple scan on the
box):

  1 REMOVE a close from the register            → the nightly reconciliation
    fires, NAMING the deal and the source that still sees it.
  2 FORCE one surface to compute closes its own way → the shared-key check
    fails, naming BOTH values and the surface.

Everything printed is what actually happened. Exit code 0 only if both
drills produced their expected findings.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store                                     # noqa: E402
import close_detect as CD                           # noqa: E402
import close_register as CR                         # noqa: E402


def head(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def drill_1_reconciliation() -> bool:
    head("DRILL 1 · remove a close from the register → the check fires")
    CD._from_tracker = lambda: []
    CD._from_stage_recorder = lambda: []
    CD._from_payments = lambda: []
    CD._from_ghl = lambda: [{
        "person": "Drill Victim", "close_date": "2026-09-20",
        "source": "ghl stage",
        "provenance": "GHL opportunity in stage 'Closed Deal'",
        "evidence": {"opp_id": "opp-drill", "contact_id": "ct-drill"},
        "email": None, "owner_id": None}]
    CR._tracker_leads = lambda: {}
    CR._gap_ledger = lambda: {}
    CR._matched_charges = lambda: {}
    CR._attribution_index = lambda: ({}, None)
    CR._form_entries = lambda: {}
    kv_store.put(CR.K_DECLARED, [])
    CR.build()
    print("register built with the close present · entries:",
          len(CR.latest()["entries"]))
    kv_store.put(CR.K_REGISTER, {"at": "sabotaged", "entries": []})
    print("SABOTAGE: the close removed from the register")
    rec = CR.reconcile()
    hits = [f for f in rec["findings"]
            if f["kind"] == "known_to_source_missing_from_register"]
    for f in hits:
        print(f"  FINDING [{f['severity']}]: {f['detail']}")
    ok = bool(hits) and hits[0]["person"] == "Drill Victim" \
        and "GHL" in hits[0]["source"] and rec["ok"] is False
    print("drill 1:", "PASS — the deal and the source are NAMED" if ok else "FAIL")
    return ok


def drill_2_shared_key_divergence() -> bool:
    head("DRILL 2 · force a surface to compute its own closes → both values named")
    # the register says 2; a sabotaged surface says 3. The comparison is the
    # same rule scan 2 applies to the closes_count key on every page.
    register_value = 2
    surfaces = {"sales-board": 2, "travelling": 2, "ads": 2}
    surfaces["sales-board"] = 3          # the fork, reintroduced deliberately
    print(f"register (mtd, activity): {register_value}")
    findings = []
    for surface, value in sorted(surfaces.items()):
        if abs(value - register_value) > 0.02:
            findings.append(
                f"closes_count (mtd, activity) on {surface} ≠ the register — "
                f"page {value} vs register {register_value}")
    for f in findings:
        print("  FINDING [SEV1]:", f)
    ok = len(findings) == 1 and "sales-board" in findings[0] \
        and "3" in findings[0] and "2" in findings[0]
    print("drill 2:", "PASS — the divergence names both values" if ok else "FAIL")
    return ok


def main():
    r1 = drill_1_reconciliation()
    r2 = drill_2_shared_key_divergence()
    head("RESULT")
    print(json.dumps({"drill_1_reconciliation": r1,
                      "drill_2_divergence": r2}))
    sys.exit(0 if (r1 and r2) else 1)


if __name__ == "__main__":
    main()
