"""close_register_phase0.py — THE MATRIX, MEASURED, NOT ARGUED.

Phase 0 of the ONE CLOSE REGISTER brief: for every surface that shows a
close count, ask ITS OWN code path for the number, on three windows
(30d activity · 30d cohort · all-time), and trace the four September
closes through each population to see who can see whom and why.

Read-only throughout: it calls the same read functions the pages call.
It never writes the tracker, GHL or Xero; the only kv writes are the ones
those functions already perform on every page load / scheduled tick.

Run on the box:
  railway ssh "cd /app && PYTHONPATH=/app /opt/venv/bin/python /tmp/d/close_register_phase0.py"
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

THE_FOUR = [
    ("orlando rinaldi", "food corp"),
    ("harman singh", "grappino"),
    ("william cooney", "phoenix hotel"),
    ("koji", "pompoko"),
]


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _hit(name_frag, biz_frag, *fields):
    blob = _n(" ".join(str(f or "") for f in fields))
    return name_frag in blob or biz_frag in blob


def head(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def four_in(rows, fields):
    """Which of the four appear in `rows`, matching on the given field names."""
    out = {}
    for name_frag, biz_frag in THE_FOUR:
        hits = [r for r in rows
                if _hit(name_frag, biz_frag, *[r.get(f) for f in fields])]
        out[name_frag] = ({"present": True,
                           "close_date": str((hits[0].get("close_date")
                                              or hits[0].get("date") or ""))[:10]}
                          if hits else {"present": False})
    return out


def main():
    from helpers import today_sydney
    today = today_sydney()
    w1 = str(today)
    w0_30 = str(today - dt.timedelta(days=29))
    R = {"at": w1}

    # ── A · /ads — attribution_engine.compute, both clocks ────────────────
    head("A · /ads (engine A: attribution_engine.compute → scoreboard_view)")
    import attribution_engine as AE
    for basis in ("cohort", "activity"):
        try:
            res = AE.compute(start=w0_30, end=w1, basis=basis)
            sv = AE.scoreboard_view(res)
            h = {k: sv.get(k) for k in ("closes_total", "closes_tiers", "basis")}
            deals = [d for c in res.get("creatives", []) for d in (c.get("deals") or [])
                     if w0_30 <= str(d.get("close_date") or "") <= w1]
            print(f"30d {basis}: headline={h} · deals-in-window={len(deals)}")
            R[f"ads_30d_{basis}"] = {"headline": h, "deal_rows": len(deals),
                                     "four": four_in(deals, ["name", "close_date"])}
        except Exception as e:
            print(f"30d {basis} FAILED: {e}")
            R[f"ads_30d_{basis}"] = {"error": str(e)[:200]}
    try:
        res_all = AE.compute(days=3650, basis="activity")
        deals_all = [d for c in res_all.get("creatives", [])
                     for d in (c.get("deals") or []) if d.get("close_date")]
        print(f"all-time activity deals: {len(deals_all)}")
        R["ads_alltime"] = {"deal_rows": len(deals_all),
                           "four": four_in(deals_all, ["name", "close_date"])}
    except Exception as e:
        R["ads_alltime"] = {"error": str(e)[:200]}

    # ── B · _closes_union (travelling / tiles / compass / sales-cash) ─────
    head("B · finance_analysis._closes_union (engine B) — 30d activity")
    import finance_analysis as FA
    try:
        cu = FA._closes_union(w0_30, w1, "activity")
        print(f"rows: {len(cu)}")
        for r in cu:
            print(f"  {r['close_date']} · {r['person']} · contract={r.get('contract')}"
                  f" · cash={r.get('cash')} · source={r.get('source')}")
        R["closes_union_30d_activity"] = {
            "count": len(cu), "four": four_in(cu, ["person", "client_row"])}
    except Exception as e:
        print("FAILED:", e)
        R["closes_union_30d_activity"] = {"error": str(e)[:200]}

    # ── C · travelling MTD ────────────────────────────────────────────────
    head("C · travelling (MTD, activity hardcoded)")
    try:
        import travelling as TR
        w0_mtd = str(today.replace(day=1))
        cl = TR._closes(dt.date.fromisoformat(w0_mtd), today)
        print(json.dumps({k: cl.get(k) for k in ("count", "cash", "contract")}
                         if isinstance(cl, dict) else {"rows": len(cl)}, default=str))
        rows = cl.get("rows") if isinstance(cl, dict) else cl
        R["travelling_mtd"] = ({"raw_keys": sorted(cl.keys())} if isinstance(cl, dict)
                               else {"count": len(cl)})
        if isinstance(rows, list):
            R["travelling_mtd"]["four"] = four_in(rows, ["person", "client_row"])
    except Exception as e:
        print("FAILED:", e)
        R["travelling_mtd"] = {"error": str(e)[:200]}

    # ── D · finance/home tiles ────────────────────────────────────────────
    head("D · tiles: unit_econ_view windows + window_report(sep_mtd)")
    try:
        ue = FA.unit_econ_view()
        for wname, blk in (ue.get("windows") or {}).items():
            print(f"  {wname}: closes={blk.get('closes')}")
        R["unit_econ_view"] = {w: (b or {}).get("closes")
                              for w, b in (ue.get("windows") or {}).items()}
    except Exception as e:
        print("unit_econ_view FAILED:", e)
        R["unit_econ_view"] = {"error": str(e)[:200]}
    try:
        wr = FA.window_report("sep_mtd")
        print(f"  window_report(sep_mtd): closes={len(wr.get('closes') or [])}")
        R["window_report_sep_mtd"] = {
            "count": len(wr.get("closes") or []),
            "four": four_in(wr.get("closes") or [], ["person", "client_row"])}
    except Exception as e:
        print("window_report FAILED:", e)
        R["window_report_sep_mtd"] = {"error": str(e)[:200]}

    # ── E · SALES page ────────────────────────────────────────────────────
    head("E · SALES (sales_scoreboard.build, 30d window)")
    try:
        import sales_scoreboard as SS
        board = SS.build(window="30d")
        tot = (board or {}).get("totals") or {}
        print(f"  totals.closes={tot.get('closes')} · cash keys="
              f"{[k for k in tot if 'cash' in k]}")
        R["sales_30d"] = {"closes": tot.get("closes"),
                          "cash": {k: tot[k] for k in tot if "cash" in k}}
    except Exception as e:
        print("FAILED:", e)
        R["sales_30d"] = {"error": str(e)[:200]}

    # ── F · compass actuals (MTD) ─────────────────────────────────────────
    head("F · compass actuals")
    try:
        import compass_engine as CE
        pva = CE.plan_vs_actual() if hasattr(CE, "plan_vs_actual") else None
        months = (pva or {}).get("months") or []
        cur = next((m for m in months if str(m.get("month", "")).startswith(w1[:7])), None)
        print(f"  this month actual clients: "
              f"{(cur or {}).get('actual', {}).get('clients') if cur else 'n/a'}")
        R["compass_mtd"] = {"actual_clients":
                            (cur or {}).get("actual", {}).get("clients") if cur else None}
    except Exception as e:
        print("FAILED:", e)
        R["compass_mtd"] = {"error": str(e)[:200]}

    # ── G · EDITH's three deterministic paths ─────────────────────────────
    head("G · EDITH paths")
    import closes_view as CV
    try:
        mtd = CV.count_closes(today.replace(day=1), today)
        last30 = CV.count_closes(today - dt.timedelta(days=29), today)
        rec = CV.recent_closes(limit=8)
        print(f"  closes_view.count_closes MTD={mtd} · 30d={last30} · "
              f"recent={[c['business'] or c['name'] for c in rec.get('closes') or []]}")
        R["closes_view"] = {"mtd": mtd, "last30": last30,
                            "four": four_in(rec.get("closes") or [],
                                            ["name", "business"])}
    except Exception as e:
        print("closes_view FAILED:", e)
        R["closes_view"] = {"error": str(e)[:200]}
    try:
        import close_detect as CD
        det = CD.latest()
        ent = det.get("entries") or []
        in30 = [e for e in ent if e.get("close_date", "") >= w0_30]
        print(f"  close_detect ledger: {len(ent)} entries · {len(in30)} in 30d · "
              f"last scan {det.get('at')}")
        for e in in30:
            print(f"    {e['close_date']} · {e['person']} · {e['state']} · "
                  f"sources={[s['source'] for s in e.get('sources') or []]}")
        R["close_detect_30d"] = {"count": len(in30),
                                 "four": four_in(in30, ["person", "client"])}
    except Exception as e:
        print("close_detect FAILED:", e)
        R["close_detect_30d"] = {"error": str(e)[:200]}

    # ── H · snapshot funnel closes (Team Scorecard cell) ─────────────────
    head("H · snapshot funnel.closes (the Google-Sheet Scorecard cell)")
    try:
        import kv_store
        snap = kv_store.get("snapshot:latest") or {}
        fn = ((snap.get("sales") or {}).get("funnel") or snap.get("funnel") or {})
        print(f"  funnel closes: {fn.get('closes')}")
        R["scorecard_cell"] = {"closes": fn.get("closes")}
    except Exception as e:
        R["scorecard_cell"] = {"error": str(e)[:200]}

    # ── I · gap ledger states for the four ────────────────────────────────
    head("I · gap ledger (AUTO vs PROPOSED)")
    try:
        import gap_reconcile as GR
        led = (GR.close_ledger() or {}).get("ledger") or []
        print(f"  ledger rows: {len(led)}")
        for e in led:
            print(f"    {e.get('close_date')} · {e.get('person')} · {e.get('state')}")
        R["gap_ledger"] = {"count": len(led),
                           "four": four_in(led, ["person"]),
                           "states": {e.get("person"): e.get("state") for e in led}}
    except Exception as e:
        print("FAILED:", e)
        R["gap_ledger"] = {"error": str(e)[:200]}

    head("MACHINE-READABLE")
    print(json.dumps(R, default=str))


if __name__ == "__main__":
    main()
