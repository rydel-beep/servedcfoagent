"""
scripts/verify_outflow_bands.py — Part A PROD probe (read-only).
Run in the container: python3 -m scripts.verify_outflow_bands
The restated trailing-6-months table (the payoff exhibit) + partition
invariant + accrual leg + the EDITH drill + sentinel first run.
"""
import json
import time

import outflow_bands as OB


def main():
    out = {}
    t0 = time.time()
    d = OB.monthly_bands(6)
    out["build_s"] = round(time.time() - t0, 2)
    out["months"] = [{k: m.get(k) for k in
                      ("month", "blended_total", "opex", "tax_statutory",
                       "personal", "flagged", "partition_ok", "unavailable")}
                     for m in d["months"]]
    out["tax_items"] = [(m["month"], m.get("tax_items"))
                        for m in d["months"] if m.get("tax_items")]
    out["flagged"] = [(m["month"], [i["label"] for i in m.get("flagged_items") or []])
                      for m in d["months"] if m.get("flagged_items")]
    out["accrual"] = d.get("accrual")
    out["degraded"] = d.get("degraded")
    ans, handled = OB.handle_expense_query("what are our real monthly expenses?")
    out["edith_drill"] = {"handled": handled, "answer": ans}
    t0 = time.time()
    out["sentinel_first_run"] = OB.sentinel_watch()
    out["sentinel_s"] = round(time.time() - t0, 2)
    # the burn fix live: current snapshot's burn excludes tax/personal
    try:
        from snapshot import load_persisted
        b = (load_persisted() or {}).get("monthly_burn") or {}
        out["burn_now"] = {k: b.get(k) for k in
                           ("total_recurring_burn", "other_opex",
                            "tax_statutory_excluded", "personal_excluded")}
    except Exception as e:
        out["burn_now"] = {"error": str(e)[:80]}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
