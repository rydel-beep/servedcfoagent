"""
scripts/verify_forward_projection.py — forward-MRR wave PROD probe (read-only).
Run in the container: python3 -m scripts.verify_forward_projection
No writes: project() reads; preview_declaration() stages nothing.
"""
import json
import time

import forward_projection as FP


def main():
    out = {}
    t0 = time.time()
    p = FP.project()
    out["project_s"] = round(time.time() - t0, 3)
    out["config"] = FP.config()
    out["months_n"] = len(p.get("months") or [])
    out["months_head"] = (p.get("months") or [])[:3]
    out["committed"] = p.get("committed")
    out["assumed_pool"] = p.get("assumed_pool")
    out["oneoff_cash_nonzero"] = [(p["months"][i], v)
                                  for i, v in enumerate(p.get("oneoff_cash") or [])
                                  if v]
    out["formula"] = p.get("assumption_formula")
    out["reconciliation"] = p.get("reconciliation")
    out["degraded"] = p.get("degraded")
    pc = p.get("per_client") or {}
    out["clients_n"] = len(pc)
    out["clients_sample"] = {k: v for k, v in list(pc.items())[:4]}

    # the watch state live (open + cleared archive)
    try:
        import finance_sheets_pull as FSP
        ch = (FSP.pull_client_health() or {}).get("client_health") or {}
        out["renewal_watch"] = [{k: w.get(k) for k in
                                 ("name", "months_elapsed", "total_months",
                                  "days_until_renewal", "status")}
                                for w in ch.get("renewal_watch") or []]
        out["watch_cleared"] = ch.get("renewal_watch_cleared")
        out["at_risk_n"] = len(ch.get("at_risk") or [])
    except Exception as e:
        out["watch_error"] = str(e)[:120]

    # sentinel first run
    t0 = time.time()
    w = FP.sentinel_watch()
    out["sentinel_first_run"] = w
    out["sentinel_s"] = round(time.time() - t0, 2)

    # a REAL-roster preview drill (pure — stages nothing): annual normalisation
    try:
        import client_overrides as CO
        roster = CO._roster()
        if roster:
            nm = roster[0].get("name")
            prev, err = CO.preview_declaration(nm, "renewal", amount=30000,
                                               term_months=12, cadence="annual")
            out["preview_drill"] = {"client": nm, "err": err,
                                    "preview": (prev or {}).get("preview"),
                                    "normalised": ((prev or {}).get("payload")
                                                   or {}).get("new_mrr")}
    except Exception as e:
        out["preview_drill"] = {"error": str(e)[:120]}

    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
