"""koji_probe.py — THE EVIDENCE FOR ONE DEAL, IN ONE SHOT.

Read-only. It answers the three questions Part 0 asks about Koji and prints
what it actually found, including the empty answers:

  1 CLOSE EVENT  — a tracker close row? a CRM opportunity in a closed stage,
                   and when did it get there? a recorded transition? what do
                   the contact's custom fields hold (the closed-deal form)?
  2 THE MONEY    — the charge(s) under the payer name, and every payment the
                   matcher currently cannot attach to anybody.
  3 THE MACHINERY— what the gap engine thinks, what the detection ledger
                   holds, and when each last ran.

Run on the box:  railway ssh --service CFOagent "cd /app && PYTHONPATH=/app \
                 /opt/venv/bin/python /tmp/d/koji_probe.py"
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

NAME = os.environ.get("PROBE_CLIENT", "koji")
PAYER = os.environ.get("PROBE_PAYER", "sanatani rombola")


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def head(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def main():
    out = {}

    head("1a · TRACKER — any row mentioning the client")
    try:
        import sheet_mirror
        import attribution_engine as AE
        rows = sheet_mirror.read_tab("ltc_tracker") or []
        cols = AE.tracker_cols(rows[0]) if rows else {}
        hits = [r for r in rows[1:] if NAME in json.dumps(r).lower()]
        print(f"tracker rows: {len(rows)} · rows mentioning {NAME!r}: {len(hits)}")
        for r in hits[:5]:
            print({k: (r[i] if i is not None and i < len(r) else "")
                   for k, i in cols.items() if i is not None})
        dated = [r for r in rows[1:]
                 if cols.get("close_date") is not None
                 and cols["close_date"] < len(r) and str(r[cols["close_date"]]).strip()]
        print(f"rows with ANY close date: {len(dated)}")
        if dated:
            last = max(str(r[cols["close_date"]])[:10] for r in dated)
            print(f"most recent tracker close date: {last}")
        out["tracker_hits"] = len(hits)
    except Exception as e:
        print("tracker unreadable:", e)

    head("1b · CRM — the opportunity, its stage, its owner, when it moved")
    try:
        import ghl_mirror
        opps = ghl_mirror.read_opportunities(open_only=False) or []
        hits = [o for o in opps if NAME in json.dumps(o, default=str).lower()]
        print(f"opportunities: {len(opps)} · matching {NAME!r}: {len(hits)}")
        for o in hits[:5]:
            raw = o.get("raw") if isinstance(o.get("raw"), dict) else {}
            ct = (raw or {}).get("contact") or {}
            print(json.dumps({
                "id": o.get("id"), "name": o.get("name"),
                "stage": o.get("stage_name"), "status": o.get("status"),
                "value": o.get("monetary_value"),
                "created": str(o.get("created_at"))[:16],
                "stage_changed": str(o.get("last_stage_change_at"))[:16],
                "contact": ct.get("name"), "email": ct.get("email"),
                "assigned_to": raw.get("assignedTo"),
            }, indent=1, default=str))
        closed = [o for o in opps
                  if "closed" in str(o.get("stage_name") or "").lower()]
        print(f"opportunities in a closed stage: {len(closed)}")
        recent = sorted(closed, key=lambda o: str(o.get("last_stage_change_at") or ""),
                        reverse=True)[:8]
        for o in recent:
            raw = o.get("raw") if isinstance(o.get("raw"), dict) else {}
            ct = (raw or {}).get("contact") or {}
            print(f"  {str(o.get('last_stage_change_at'))[:16]} · "
                  f"{ct.get('name') or o.get('name')} · {o.get('stage_name')}")
    except Exception as e:
        print("CRM mirror unreadable:", e)

    head("1c · THE STAGE RECORDER — did it see the move?")
    try:
        import stage_history
        import kv_store
        print("watching since:", stage_history.started_at())
        tr = kv_store.get(stage_history.K_TRANSITIONS) or []
        closed = [t for t in tr if "closed" in str(t.get("to") or "").lower()]
        print(f"transitions recorded: {len(tr)} · into a closed stage: {len(closed)}")
        for t in closed[-10:]:
            print("  ", json.dumps(t, default=str))
    except Exception as e:
        print("recorder unreadable:", e)

    head("1d · THE CONTACT'S CUSTOM FIELDS (the closed-deal form)")
    try:
        import ghl_mirror
        contacts = ghl_mirror.read_all_contacts() or {}
        found = [c for c in contacts.values()
                 if NAME in json.dumps(c, default=str).lower()]
        print(f"contacts held: {len(contacts)} · matching: {len(found)}")
        for c in found[:3]:
            raw = c.get("raw") if isinstance(c.get("raw"), dict) else c
            cf = raw.get("customFields") or raw.get("custom_fields") or []
            print("contact:", raw.get("contactName") or raw.get("name"),
                  "| custom fields:", len(cf))
            for f in cf:
                if isinstance(f, dict):
                    print("   ", f.get("id"), "=", str(f.get("value"))[:80])
    except Exception as e:
        print("contacts unreadable:", e)

    head("2 · THE MONEY — the payer, and everything unattached")
    try:
        import cash_truth
        charges = cash_truth._recent_charges(120) or []
        print(f"succeeded charges (120d): {len(charges)}")
        for c in charges:
            if PAYER in _n(c.get("customer_name")):
                print("  PAYER HIT:", json.dumps(
                    {k: str(v) for k, v in c.items() if k != "_email"}, indent=1))
        import unmatched_payments as UP
        res = UP.scan(120)
        print(f"\nunattached payments: {res.get('count')} · "
              f"${res.get('total_unmatched')}")
        for r in res.get("rows") or []:
            print(f"  {r['date']} · {r['payer']} · ${r['amount']} · {r['charge_id']}"
                  f" · guess: {(r.get('suggested') or [{}])[0].get('business', '—')}")
    except Exception as e:
        print("charges unreadable:", e)

    head("3 · THE MACHINERY — what each engine currently holds")
    try:
        import kv_store
        import gap_reconcile as GR
        st = kv_store.get("gap:state") or {}
        print("gap window:", (st.get("gap") or {}).get("start"), "→",
              (st.get("gap") or {}).get("end"), "| detected on:", st.get("detected_on"))
        led = GR.close_ledger()
        print(f"gap ledger: {len(led.get('ledger') or [])} entries · "
              f"auto={led.get('auto')} proposed={led.get('proposed')}")
        for e in (led.get("ledger") or [])[-6:]:
            print(f"   {e.get('close_date')} · {e.get('person')} · {e.get('state')}"
                  f" · {(e.get('missing') or '')[:60]}")
        import close_detect
        det = close_detect.latest()
        print(f"\ndetection ledger: {len(det.get('entries') or [])} entries "
              f"(confirmed {det.get('confirmed')}, detected {det.get('detected')})"
              f" · last scan {det.get('at')}")
        for e in (det.get("entries") or [])[:8]:
            print(f"   {e['close_date']} · {e['person']} · {e['state']} · "
                  f"missing: {', '.join(e.get('missing') or []) or 'nothing'}")
        import freshness
        print("\nlast freshness tick:", (freshness.last_tick() or {}).get("at"))
    except Exception as e:
        print("engines unreadable:", e)

    print("\n" + json.dumps(out))


if __name__ == "__main__":
    main()
