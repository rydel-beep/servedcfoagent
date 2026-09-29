"""rockys_probe.py — #170: Rocky's Italian (contact Max), Scale Engine, 29 Sep.
STRICTLY READ-ONLY: SELECTs on the GHL mirror, kv_store.get, the tracker
mirror read. No build, no scan, no writes."""
from __future__ import annotations

import json
import re

import db
import kv_store

TERMS = ("rocky", "rockys")


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def hit(*f):
    b = _n(" ".join(str(x or "") for x in f))
    return any(t in b for t in TERMS)


def main():
    print("== GHL opportunities (mirror) ==")
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, contact_id, name, monetary_value, status, stage_name, "
            "assigned_to, last_stage_change_at, created_at, raw "
            "FROM ghl_opportunities WHERE deleted=FALSE AND "
            "(lower(name) LIKE '%%rocky%%' OR lower(raw::text) LIKE '%%rocky%%')"
        ).fetchall()
    for r in rows:
        raw = r["raw"] if isinstance(r["raw"], dict) else json.loads(r["raw"] or "{}")
        ct = raw.get("contact") or {}
        print(json.dumps({"opp_id": r["id"], "contact_id": r["contact_id"],
                          "name": r["name"], "value": r["monetary_value"],
                          "status": r["status"], "stage": r["stage_name"],
                          "assigned_to": r["assigned_to"],
                          "stage_changed": str(r["last_stage_change_at"]),
                          "created": str(r["created_at"]),
                          "contact_name": ct.get("name"),
                          "custom_fields": raw.get("customFields")}, default=str)[:1500])
    try:
        import comp_rulebook as CRB
        owners = getattr(CRB, "GHL_OWNER_NAMES", None)
        print("owner map:", owners)
    except Exception as e:
        print("owner map n/a:", e)

    print("\n== register + detection ==")
    for key in ("register:closes", "closes:detected"):
        for e in (kv_store.get(key) or {}).get("entries") or []:
            if hit(e.get("person"), e.get("client")):
                print(key, json.dumps({k: e.get(k) for k in (
                    "person", "client", "close_date", "status", "sources",
                    "contract", "cash", "closer", "closer_ghl_owner_id", "setter",
                    "missing")}, default=str)[:1200])

    print("\n== tracker rows ==")
    import attribution_engine as AE
    rows = AE._tracker_rows_clean()
    leads, _ = AE.parse_tracker(rows)
    for l in leads:
        if hit(l.get("name"), l.get("business")):
            print(json.dumps({k: l.get(k) for k in (
                "name", "business", "close_date", "contract", "cash", "offer",
                "closer", "setter", "input_date", "qualified")}, default=str))

    print("\n== unmatched payments ==")
    st = kv_store.get("payments:unmatched") or {}
    for r in (st.get("rows") or []) + (st.get("matched") or []):
        if hit(r.get("payer"), r.get("client")) or float(r.get("amount") or 0) in (5500.0, 5000.0):
            print(json.dumps(r, default=str)[:400])


if __name__ == "__main__":
    main()
