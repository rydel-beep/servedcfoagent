"""contract_loss_probe.py — #170: why did three September closes lose their
contract values (and Orlando his confirmation) in the 11:50 register build?

STRICTLY READ-ONLY: kv_store.get + the tracker mirror read (in-memory memo
only). No build, no scan, no compute that persists.
"""
from __future__ import annotations

import json
import re

import kv_store

PEOPLE = ("orlando", "harman", "william cooney", "koji", "scott cho", "amoroso",
          "grappino", "phoenix", "food corp", "pompoko")


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def hit(*f):
    b = _n(" ".join(str(x or "") for x in f))
    return any(p in b for p in PEOPLE)


def head(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def main():
    head("G · GAP LEDGER (gap:close_ledger) + gap:state")
    gl = kv_store.get("gap:close_ledger")
    print("type:", type(gl).__name__, "| keys:",
          list(gl.keys())[:10] if isinstance(gl, dict) else None)
    if isinstance(gl, dict):
        print("at:", gl.get("at") or gl.get("built_at") or gl.get("generated"),
              "| entries:", len(gl.get("ledger") or []))
        for e in gl.get("ledger") or []:
            if hit(e.get("person"), (e.get("health_row") or {}).get("name")):
                print(json.dumps({k: e.get(k) for k in (
                    "person", "close_date", "contract_value", "contract_provenance",
                    "package", "mrr", "health_row", "stripe", "evidence", "state")},
                    default=str)[:900])
    gs = kv_store.get("gap:state") or {}
    print("gap:state at:", gs.get("at") or gs.get("computed_at") or gs.get("date"),
          "| keys:", list(gs.keys())[:12])

    head("H · TRACKER LEAD ROWS (engine-parsed, deduped)")
    import attribution_engine as AE
    rows = AE._tracker_rows_clean()
    print("mirror rows:", None if rows is None else len(rows))
    leads, _ = AE.parse_tracker(rows)
    leads, _f = AE.dedupe_won(leads)
    for l in leads:
        if hit(l.get("name"), l.get("business")):
            print(json.dumps({k: l.get(k) for k in (
                "name", "business", "status", "close_date", "contract", "cash",
                "offer", "package", "term", "closer", "setter", "input_date")},
                default=str))

    head("I · REGISTER JOURNAL (last 15) + reconciliation")
    for j in (kv_store.get("register:journal") or [])[-15:]:
        print(json.dumps(j, default=str)[:400])
    rc = kv_store.get("register:reconciliation") or {}
    print("recon at:", rc.get("at"), "| findings:",
          json.dumps(rc.get("findings"), default=str)[:1200])

    head("J · REGISTER — the 4 remaining Sept closes, full records")
    reg = kv_store.get("register:closes") or {}
    for e in reg.get("entries") or []:
        if str(e.get("close_date") or "") >= "2026-09-01" and "scott" not in _n(e.get("person")):
            print(json.dumps({k: e.get(k) for k in (
                "person", "client", "status", "sources", "contract", "cash",
                "missing", "closer", "setter", "clocks")}, default=str)[:1500])
    print("register degraded:", json.dumps(reg.get("degraded"), default=str)[:600])

    head("K · UNIT-ECON CACHE — cohort_month + trailing_90d full")
    ue = ((kv_store.get("exec:cache:unit_econ") or {}).get("data") or {})
    for wn in ("cohort_month", "trailing_90d"):
        w = (ue.get("windows") or {}).get(wn) or {}
        print(wn, json.dumps({k: w.get(k) for k in (
            "closes", "cac_note", "true_cac", "by_package", "avg_ltv_per_close")},
            default=str)[:2500])


if __name__ == "__main__":
    main()
