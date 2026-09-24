"""close_register_evidence.py — THE FOUR, PROVED, AND EVERY SURFACE ASKED AGAIN.

Phase 4 acceptance evidence: rebuilds the register on the box, prints the
full evidence table for each of the four September closes (GHL opportunity
id + stage + date · Stripe charge ids/amounts · tracker row or "missing" ·
closed-deal form · contract + source · closer · lead + creative + tier +
why), then re-runs the Phase-0 surface probes so BEFORE → AFTER is one
diff. Read-only against the tracker/GHL/Xero; the register store is kv.

Run on the box:
  railway ssh "cd /app && PYTHONPATH=/app /opt/venv/bin/python /tmp/d/close_register_evidence.py"
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FOUR = ["orlando rinaldi", "harman singh", "william cooney", "koji"]


def head(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main():
    from helpers import today_sydney
    import close_register as CR
    t = today_sydney()
    w0 = str(t - dt.timedelta(days=29))
    w1 = str(t)

    head("REGISTER REBUILD")
    out = CR.build()
    print(f"entries={len(out['entries'])} confirmed={out['confirmed']} "
          f"proposed={out['proposed']} degraded={out['degraded']}")

    head("THE FOUR — full evidence tables")
    for key in FOUR:
        e = CR.record(key)
        if not e:
            e = next((x for x in out["entries"] if key in x["key"]), None)
        if not e:
            print(f"\n!! {key}: NOT ON THE REGISTER")
            continue
        print(f"\n── {e['person']} · {e['client'] or '(no venue on file)'} ──")
        print(json.dumps({
            "close_date": e["close_date"], "dated_by": e["dated_by"],
            "status": e["status"],
            "ghl": {"opp_id": e.get("opp_id"), "contact_id": e.get("contact_id"),
                    "stage": (e.get("evidence") or {}).get("stage"),
                    "stage_changed": (e.get("evidence") or {}).get("stage_changed")},
            "stripe": {"cash_to_date": e["cash"]["amount"],
                       "charge_ids": e["cash"]["charge_ids"],
                       "source": e["cash"]["source"],
                       "tracker_cash_cell": e["cash"]["tracker_cell"]},
            "tracker_row": ("present with close date" if e["chips"]["tracker_row"]
                            else "MISSING"),
            "closed_deal_form": ("present" if e["chips"]["form"]
                                 else "missing (not mirrored — #161)"),
            "contract": e["contract"],
            "closer": e.get("closer") or e.get("closer_ghl_owner_id"),
            "setter": e.get("setter"),
            "lead": e.get("lead"),
            "attribution": e["attribution"],
            "clocks": e["clocks"],
            "sources": [s["source"] for s in e["sources"]],
            "missing": e["missing"],
        }, indent=1, default=str))

    head("TOTALS — 30d, both clocks (the headline's numbers)")
    for clock in ("activity", "cohort"):
        print(clock, json.dumps(CR.totals(w0, w1, clock), default=str))

    head("SURFACES, ASKED AGAIN (Phase-0 shape)")
    R = {}
    import finance_analysis as FA
    cu = FA._closes_union(w0, w1, "activity")
    print(f"_closes_union 30d activity: {len(cu)}")
    R["closes_union"] = len(cu)
    try:
        import sales_scoreboard as SS
        board = SS.build(window="30d")
        tot = (board or {}).get("totals") or {}
        print(f"SALES 30d: closes={tot.get('closes')} "
              f"proposed={tot.get('closes_proposed')} "
              f"cash={board.get('cash', {}).get('total')}")
        R["sales"] = {"closes": tot.get("closes"),
                      "cash": (board.get("cash") or {}).get("total")}
    except Exception as e:  # noqa: BLE001
        print("SALES failed:", e)
    try:
        from dashboard import ads as ADS
        import attribution_engine as AE
        for basis in ("cohort", "activity"):
            res = AE.compute(days=30, basis=basis)
            sb = ADS._overlay_register(AE.scoreboard_view(res), res, basis)
            h = sb["headline"]
            print(f"/ads 30d {basis}: closes_total={h['closes_total']} "
                  f"(engine said {h.get('closes_engine_total')}) "
                  f"tiers={h['closes_tiers']} cash={h['cash_total']}")
            R[f"ads_{basis}"] = {"closes": h["closes_total"],
                                 "tiers": h["closes_tiers"],
                                 "cash": h["cash_total"]}
        reg_block = ADS._register_block(AE.compute(days=30, basis="cohort"), "cohort")
        print("register block (headline source):",
              json.dumps({k: {"count": v.get("count"), "cash": v.get("cash")}
                          for k, v in reg_block.items()
                          if isinstance(v, dict) and "count" in v}, default=str))
    except Exception as e:  # noqa: BLE001
        print("/ads overlay failed:", e)
    try:
        import closes_view as CV
        reply, handled = CV.handle_closes_command("what have we closed this month")
        print("EDITH 'what have we closed this month':", (reply or "")[:400])
        R["edith"] = reply
    except Exception as e:  # noqa: BLE001
        print("EDITH drill failed:", e)
    try:
        import travelling as TR
        cl = TR._closes(t.replace(day=1), t)
        print(f"travelling MTD: count={cl['count']} contract={cl['contract']}")
        R["travelling_mtd"] = cl["count"]
    except Exception as e:  # noqa: BLE001
        print("travelling failed:", e)
    try:
        ue = FA.unit_econ_view()
        print("tiles:", {w: (b or {}).get("closes")
                         for w, b in (ue.get("windows") or {}).items()})
    except Exception as e:  # noqa: BLE001
        print("tiles failed:", e)

    head("RECONCILIATION — first run")
    rec = CR.reconcile()
    print(json.dumps({"ok": rec["ok"],
                      "findings": [(f["severity"], f["detail"]) for f in
                                   rec["findings"]]}, indent=1, default=str))

    head("MACHINE-READABLE")
    print(json.dumps(R, default=str))


if __name__ == "__main__":
    main()
