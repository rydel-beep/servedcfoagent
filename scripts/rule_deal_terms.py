"""rule_deal_terms.py — encode an owner deal-terms ruling (#170), journaled.

A PRODUCTION WRITE (the register's ruling store + its journal) — run only on
Rydel's explicit instruction, with his words verbatim. Every field is an
argument; nothing is defaulted from an amount.

  railway ssh --service CFOagent "cd /app && PYTHONPATH=/app /opt/venv/bin/python \
    scripts/rule_deal_terms.py --person Max --client \"Rocky's Italian\" \
    --close-date 2026-09-29 --package 'Scale Engine' --payment-type split \
    --term-months 6 --contract-ex-gst 14500 \
    --payment '1|5500|inc|2026-09-29|2026-09-29|bank transfer|business|' \
    --payment '2|5225|inc|2026-10-29||bank transfer||' \
    --payment '3|5225|inc|2026-11-29||bank transfer||' \
    --closer kalin --setter maran --words '<Rydel's ruling, verbatim>'"

--payment fields: n|amount|inc/ex|due|received|channel|account|evidence_id
(received/account/evidence_id blank until true).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _payment(s: str) -> dict:
    n, amount, gst, due, received, channel, account, evidence = (s.split("|") + [""] * 8)[:8]
    return {"n": int(n), "amount": float(amount), "gst": gst or None,
            "due": due or None, "received": received or None,
            "channel": channel or None, "account": account or None,
            "evidence_id": evidence or None}


def main():
    ap = argparse.ArgumentParser()
    for a in ("--person", "--client", "--close-date", "--package", "--words"):
        ap.add_argument(a, required=True)
    ap.add_argument("--term-months", type=int, required=True)
    ap.add_argument("--contract-ex-gst", type=float, required=True)
    ap.add_argument("--payment", action="append", required=True)
    ap.add_argument("--payment-type")
    ap.add_argument("--closer")
    ap.add_argument("--setter")
    ap.add_argument("--contact")
    a = ap.parse_args()
    import close_register as CR
    res = CR.rule_deal_terms(
        a.person, a.client, a.close_date, a.package, a.term_months,
        a.contract_ex_gst, [_payment(p) for p in a.payment], a.words,
        actor="rydel", closer=a.closer, setter=a.setter,
        payment_type=a.payment_type, contact=a.contact)
    print(json.dumps(res, default=str, indent=1))
    if res.get("ok"):
        e = CR.record(CR._norm(a.person))
        print(json.dumps({k: (e or {}).get(k) for k in (
            "status", "contract", "cash", "ruled_cash", "closer", "setter",
            "package", "term_months")}, default=str, indent=1))


if __name__ == "__main__":
    main()
