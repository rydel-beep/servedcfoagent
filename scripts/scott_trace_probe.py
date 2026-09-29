"""scott_trace_probe.py — #170 Part 1: where did Scott's payment stop?

STRICTLY READ-ONLY. kv_store.get only; Stripe via a direct GET (the
cash_truth reader writes a partial-pull marker, so it is NOT used); no
register build, no scan, no invalidation.

Run on the box (piped, nothing written to disk):
  railway ssh --service CFOagent "cd /app && echo <b64> | base64 -d | PYTHONPATH=/app /opt/venv/bin/python -"
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import re

import kv_store
from helpers import SYDNEY_TZ, today_sydney

TERMS = ("scott", "amoroso", "gelat")
AMOUNTS = {5278.90, 4799.00}


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def hit(*fields):
    blob = _n(" ".join(str(f or "") for f in fields))
    return any(t in blob for t in TERMS)


def head(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def mask(e):
    e = str(e or "")
    return (e[:2] + "…@" + e.split("@")[-1]) if "@" in e else e


def main():
    head("A · STRIPE — succeeded charges, last 14 days, Scott/Amoroso/amount")
    from payback_reconciliation import _sget
    since = today_sydney() - dt.timedelta(days=14)
    params = {"limit": 100, "created[gte]": calendar.timegm(since.timetuple()),
              "expand[]": ["data.customer"]}
    r = _sget("/v1/charges", params)
    if r.get("error"):
        print("stripe error:", str(r["error"])[:200])
    n_all = 0
    for c in r.get("data") or []:
        n_all += 1
        cust = c.get("customer") if isinstance(c.get("customer"), dict) else {}
        bd = c.get("billing_details") or {}
        amt = (c.get("amount") or 0) / 100.0
        name = cust.get("name") or bd.get("name")
        email = cust.get("email") or bd.get("email") or c.get("receipt_email")
        if hit(name, email, c.get("description"), cust.get("description")) or amt in AMOUNTS:
            d = dt.datetime.fromtimestamp(c["created"], tz=SYDNEY_TZ)
            print(json.dumps({"id": c["id"], "amount_inc_gst": amt,
                              "refunded": (c.get("amount_refunded") or 0) / 100.0,
                              "status": c.get("status"), "paid": c.get("paid"),
                              "date_sydney": d.isoformat(), "payer": name,
                              "email": mask(email), "customer": cust.get("id"),
                              "description": c.get("description")}))
    print(f"(scanned {n_all} charges; has_more={r.get('has_more')})")

    head("B · UNMATCHED-PAYMENTS STATE (payments:unmatched)")
    st = kv_store.get("payments:unmatched") or {}
    print("scan at:", st.get("at"), "| available:", st.get("available"),
          "| unmatched count:", st.get("count"), "| total:", st.get("total_unmatched"))
    for row in st.get("rows") or []:
        if hit(row.get("payer"), row.get("suggested")) or float(row.get("amount") or 0) in AMOUNTS:
            print("UNMATCHED:", json.dumps(row, default=str)[:400])
    for m in st.get("matched") or []:
        if hit(m.get("payer"), m.get("client")) or float(m.get("amount") or 0) in AMOUNTS:
            print("MATCHED:", json.dumps(m, default=str)[:400])

    head("C · PAYER ALIASES (stripe:payer_aliases) + alias journal")
    al = kv_store.get("stripe:payer_aliases") or {}
    print("alias count:", len(al))
    for k, v in al.items():
        if hit(k, v):
            print(f"  {k!r} → {v!r}")
    for j in (kv_store.get("payments:alias_journal") or [])[-40:]:
        if hit(j.get("payer"), j.get("client")):
            print("JOURNAL:", json.dumps(j, default=str))

    head("D · CLOSE REGISTER (persisted)")
    import close_register as CR
    reg = kv_store.get(CR.K_REGISTER) or {}
    ents = reg.get("entries") or []
    print("built:", reg.get("built_at") or reg.get("at"), "| entries:", len(ents),
          "| confirmed:", sum(1 for e in ents if e.get("status") == "confirmed"))
    for e in ents:
        if hit(e.get("person"), e.get("client"), e.get("email")):
            print(json.dumps({k: e.get(k) for k in (
                "id", "person", "client", "close_date", "dated_by", "sources",
                "status", "contract", "cash", "closer", "setter", "clocks",
                "missing", "corroboration_pending", "package", "tier")},
                default=str, indent=1)[:2500])
    sept = [e for e in ents if str(e.get("close_date") or "") >= "2026-09-01"]
    print("\nSeptember register entries:")
    for e in sept:
        print(f"  {e.get('close_date')} · {e.get('person')} · {e.get('client')} · "
              f"{e.get('status')} · contract={(e.get('contract') or {}).get('value')} "
              f"({(e.get('contract') or {}).get('source')}) · "
              f"cash={(e.get('cash') or {}).get('amount')}")

    head("E · CLOSE DETECTION LEDGER (close_detect, persisted)")
    import close_detect as CD
    det = CD.latest() or {}
    print("at:", det.get("at"), "| entries:", len(det.get("entries") or []))
    for e in det.get("entries") or []:
        if hit(e.get("person"), e.get("client")):
            print(json.dumps(e, default=str)[:1200])

    head("F · CACHE / ROLLUP TIMESTAMPS")
    for k in ("exec:cache:unit_econ", "exec:cache:roas", "closes:last_invalidation",
              "freshness:last_tick", "register:last_build", "closes:last_scan"):
        v = kv_store.get(k)
        if not isinstance(v, dict):
            print(k, "→", type(v).__name__)
            continue
        print(k, "→ computed_at/at:", v.get("computed_at") or v.get("at"),
              "| error:", v.get("error"), "| reason:", v.get("reason"))
    ue = ((kv_store.get("exec:cache:unit_econ") or {}).get("data") or {})
    for wn, w in (ue.get("windows") or {}).items():
        print(f"  {wn}: closes={w.get('closes')} avg_ltv={w.get('avg_ltv_per_close')} "
              f"cac_full={w.get('cac_fully_loaded')} cac_spend={w.get('cac_spend_only')} "
              f"ltv:cac={w.get('ltv_to_cac')} ltgp:cac={w.get('ltgp_to_cac')} "
              f"window={w.get('window')}")
    print("  ltv_inputs:", json.dumps(ue.get("ltv_inputs"), default=str)[:600])
    print("  margin:", str(ue.get("margin_provenance"))[:200])


if __name__ == "__main__":
    main()
