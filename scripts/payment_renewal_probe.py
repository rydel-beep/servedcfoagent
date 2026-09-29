"""payment_renewal_probe.py — #170: B1 renewal + completion from payment
history, LIVE, READ-ONLY. Stripe via direct GETs (no partial marker write),
the one matcher (pure scoring), tracker won rows. Nothing persisted."""
import calendar
import datetime as dt
import json
import re

from helpers import SYDNEY_TZ, today_sydney


def _n(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def main():
    from payback_reconciliation import _sget
    today = today_sydney()
    data_start = today - dt.timedelta(days=550)
    params = {"limit": 100, "created[gte]": calendar.timegm(data_start.timetuple()),
              "expand[]": ["data.customer"]}
    raw, after, pages = [], None, 0
    while pages < 30:
        p = dict(params)
        if after:
            p["starting_after"] = after
        r = _sget("/v1/charges", p)
        if r.get("error"):
            print("STRIPE ERROR page", pages, str(r["error"])[:160]); break
        raw.extend(r.get("data") or []); pages += 1
        if not r.get("has_more"):
            break
        after = raw[-1]["id"]
    print(f"charges fetched: {len(raw)} over {pages} page(s); has_more at stop: {r.get('has_more')}")
    first = min((c["created"] for c in raw), default=None)
    if first:
        data_start = dt.datetime.fromtimestamp(first, tz=SYDNEY_TZ).date()
    print("data starts:", data_start)

    import stripe_reconcile as SR
    import unmatched_payments as UP
    idx, roster = UP._index()
    by_client, unmatched = {}, 0
    for c in raw:
        if not (c.get("paid") and c.get("status") == "succeeded"):
            continue
        amt = ((c.get("amount") or 0) - (c.get("amount_refunded") or 0)) / 100.0
        if amt <= 0:
            continue
        cust = c.get("customer") if isinstance(c.get("customer"), dict) else {}
        bd = c.get("billing_details") or {}
        name = cust.get("name") or bd.get("name") or ""
        email = (cust.get("email") or bd.get("email") or c.get("receipt_email") or "").lower()
        m = SR._match_payment(name, email, amt, idx, roster)
        if not m.get("business"):
            unmatched += 1
            continue
        d = dt.datetime.fromtimestamp(c["created"], tz=SYDNEY_TZ).date()
        by_client.setdefault(m["business"], []).append((d, amt))
    print(f"matched clients: {len(by_client)} · unmatched charges: {unmatched}")

    import attribution_engine as AE
    leads, _ = AE.parse_tracker(AE._tracker_rows_clean())
    leads, _f = AE.dedupe_won(leads)
    won = {}
    for l in leads:
        if not l.get("won"):
            continue
        for k in (l.get("business"), l.get("name")):
            if _n(k):
                won.setdefault(_n(k), l)
    deals, nodeal = {}, []
    for client in by_client:
        l = won.get(_n(client))
        if l is None:
            nodeal.append(client); continue
        cd = l.get("close_date")
        deals[client] = {"offer": l.get("offer"),
                         "close_date": (dt.date.fromisoformat(str(cd)[:10]) if cd else None),
                         "contract": l.get("contract")}
    print(f"clients with a tracker won row: {len(deals)} · without: {len(nodeal)}")

    import csm_baselines as B
    out = B.measure_from_payments(by_client, deals, today, data_start)
    ren, com = out["renewal"], out["completion"]
    print("\nRENEWAL:", json.dumps({k: ren[k] for k in ("value", "n", "renewed", "ci95", "n_excluded")}))
    for r_ in ren["rows"]:
        print("  ", json.dumps(r_))
    print("excluded:")
    for e in ren["excluded"]:
        print("  ", json.dumps(e)[:200])
    print("no tracker won row (excluded, counted):", nodeal)
    print("\nCOMPLETION:", json.dumps({k: com[k] for k in ("value", "n")}))
    for r_ in com["rows"]:
        print("  ", json.dumps(r_))


main()
