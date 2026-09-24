"""client_status_watch.py — A CLIENT WHO PAYS IS NOT EXPIRED (#162).

Pottery Green Bakers Gordon: the roster shows a term that ended in June and
zero monthly revenue — and the same client paid $1,760 in August and $1,760
in September. The books said "gone"; the bank said "here". Nobody was lying;
the roster was stale, and nothing was comparing it against the money.

THE STANDING RULE: any client with matched payments in the last 60 days
whose roster row says non-active, term-expired, or zero/blank MRR is a
STATUS-STALE finding — surfaced with its payment evidence and an exact
Piolo package line to fix the roster/renewal ledger AT SOURCE. The sheet is
never written; the finding retires itself when the next scan sees the row
corrected.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_FINDINGS = "status_stale:findings"
K_FEED = "feed:extra:status_stale"      # one publisher, replaced wholesale
WINDOW_DAYS = 60


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _term_expired(end_date: str) -> bool:
    """Health-tab dates arrive MM-DD-YYYY."""
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", str(end_date or "").strip())
    if not m:
        return False
    try:
        return dt.date(int(m.group(3)), int(m.group(1)),
                       int(m.group(2))) < today_sydney()
    except ValueError:
        return False


def scan() -> dict:
    """Compare the money against the roster. Reads the matched-payment set
    the unmatched-payments scan already produced — no new external call."""
    import stripe_reconcile as SR
    import unmatched_payments as UP

    cutoff = str(today_sydney() - dt.timedelta(days=WINDOW_DAYS))
    matched = (UP.latest() or {}).get("matched") or []
    paid: dict[str, list] = {}
    for m in matched:
        if str(m.get("date") or "") >= cutoff:
            paid.setdefault(_norm(m.get("client")), []).append(m)

    terms = (SR._roster_index() or {}).get("terms") or {}
    findings = []
    for key, payments in paid.items():
        t = terms.get(key)
        if t is None:
            continue                    # not on the roster — the sweep's job
        problems = []
        if (t.get("status") or "").lower() != "active":
            problems.append(f"status is '{t.get('status') or 'blank'}'")
        if _term_expired(t.get("end_date")):
            problems.append(f"term ended {t.get('end_date')}")
        if not t.get("mrr"):
            problems.append("monthly revenue is zero or blank")
        if not problems:
            continue
        total = round(sum(float(p.get("amount") or 0) for p in payments), 2)
        findings.append({
            "client": payments[0].get("client"),
            "paid_last_60d": total,
            "payments": [{"date": p.get("date"), "amount": p.get("amount"),
                          "charge_id": p.get("charge_id"),
                          "basis": p.get("basis")} for p in payments],
            "roster": t,
            "problems": problems,
        })

    findings.sort(key=lambda f: -f["paid_last_60d"])
    out = {"at": now_sydney().isoformat(), "window_days": WINDOW_DAYS,
           "findings": findings, "count": len(findings)}
    kv_store.put(K_FINDINGS, out)

    items = []
    for f in findings[:10]:
        pays = " + ".join(f"${p['amount']:,.0f} on {p['date']}"
                          for p in f["payments"][:3])
        items.append({
            "severity": "S2", "category": "data_quality",
            "title": f"paying client marked stale — {f['client']}",
            "detail": (f"paid {pays} ({', '.join(p['charge_id'] for p in f['payments'][:2])}) "
                       f"while the roster says {'; '.join(f['problems'])}")[:200],
            "action": ("fix the Health-tab row / renewal ledger at source "
                       "(READ-ONLY law: the agent never writes the sheet) — "
                       "this item retires when the next scan sees it corrected"),
        })
    kv_store.put(K_FEED, items)
    return out


def latest() -> dict:
    return kv_store.get(K_FINDINGS) or {"findings": [], "count": 0}
