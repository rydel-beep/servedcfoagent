"""unmatched_history_probe.py — #170 ruling 3: every unmatched Stripe charge
in the measurement window, with the one matcher's own PROPOSAL (never
applied). STRICTLY READ-ONLY: Stripe GETs, pure scoring, no kv writes."""
import calendar, datetime as dt, json
from helpers import SYDNEY_TZ, today_sydney
from payback_reconciliation import _sget
import stripe_reconcile as SR
import unmatched_payments as UP

since = today_sydney() - dt.timedelta(days=550)
params = {"limit": 100, "created[gte]": calendar.timegm(since.timetuple()),
          "expand[]": ["data.customer"]}
raw, after = [], None
for _ in range(30):
    p = dict(params)
    if after:
        p["starting_after"] = after
    r = _sget("/v1/charges", p)
    raw.extend(r.get("data") or [])
    if not r.get("has_more"):
        break
    after = raw[-1]["id"]
idx, roster = UP._index()
groups = {}
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
    if m.get("business"):
        continue
    d = dt.datetime.fromtimestamp(c["created"], tz=SYDNEY_TZ).date()
    key = (name or "(unnamed)").strip().lower()
    g = groups.setdefault(key, {"payer": name or "(unnamed)",
                                "email_domain": email.split("@")[-1] if "@" in email else None,
                                "charges": 0, "total": 0.0, "first": str(d), "last": str(d),
                                "description": c.get("description"),
                                "suggested": m.get("suggested") or [],
                                "category": m.get("category"), "why": m.get("why")})
    g["charges"] += 1; g["total"] = round(g["total"] + amt, 2)
    g["first"] = min(g["first"], str(d)); g["last"] = max(g["last"], str(d))
rows = sorted(groups.values(), key=lambda g: -g["total"])
print(f"unmatched charges: {sum(g['charges'] for g in rows)} · payers: {len(rows)} · "
      f"total ${sum(g['total'] for g in rows):,.2f}")
for g in rows:
    print(json.dumps(g, default=str)[:420])
