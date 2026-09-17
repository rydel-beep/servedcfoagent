"""receivables.py — the AR layer the system never had (#150).

R-CASH stands: cash = Stripe/Xero receipts only. What was MISSING was the
other half of the ledger — what's EXPECTED and not yet received. This
engine renders it per client, never counts a pending cent as cash:

  expected  — the RECOGNIZED grid's per-client month cells (the sheet's own
              statement of what should be billed/recognised), plus renewed
              terms from the renewal ledger where the grid is blank.
  received  — Stripe succeeded receipts matched to the client (email/name/
              alias; the payer-alias store consulted; unmatched receipts
              become PROPOSED alias cards, never auto-assigned).
  outstanding = expected-to-date − received-to-date (floor $0 per month),
              aged from each unpaid month's end.
  status    — paid / pending (current month, not yet due) / overdue /
              failed-charge (a failed Stripe charge in the window).

Reconciliation anchor: the Xero Balance-Sheet "Accounts Receivable" line
(kv xero:ar_anchor, refreshed by the daily BAS pull) — deltas surfaced with
the reason ledger-AR ≠ schedule-AR can differ (invoice timing, GST,
non-client invoices). Invoice-level Xero AR needs a scope the token doesn't
hold (historical 401) — registered dependency, stated on the tile.

READ-ONLY LAW (#148): reads only; corrections are Piolo/owner packages.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_KV_CACHE = "ar:state"
_GRACE_DAYS = 7          # a current-month expected payment isn't "overdue"
                         # until this many days past month start


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _month_labels_between(d0: dt.date, d1: dt.date) -> list[str]:
    out = []
    y, m = d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        out.append(dt.date(y, m, 1).strftime("%B %Y"))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _aliases() -> dict:
    try:
        return {(_norm(k)): _norm(v)
                for k, v in (kv_store.get("stripe:payer_aliases") or {}).items()}
    except Exception:
        return {}


def _charges(days: int = 200) -> list[dict] | None:
    import cash_truth
    return cash_truth._raw_recent_charges(days)


def _match_receipts(clients: list[str], charges: list[dict]) -> tuple[dict, list]:
    """{client_norm: [receipts]} + unmatched succeeded receipts. Match order:
    payer-alias store → email-prefix/venue bridge → full-name containment.
    Surname-only never matches (the Jagjeet class)."""
    from helpers import SYDNEY_TZ
    alias = _aliases()
    by_client = {_norm(c): [] for c in clients}
    keys = sorted(by_client, key=len, reverse=True)
    unmatched = []
    failed_by_client = {}
    for ch in charges or []:
        bd = ch.get("billing_details") or {}
        cust = ch.get("customer") if isinstance(ch.get("customer"), dict) else {}
        payer = (cust.get("name") or bd.get("name") or "").strip()
        email = (bd.get("email") or (cust.get("email") if cust else "") or "").lower()
        pn = _norm(payer)
        pn = alias.get(pn, pn)
        local = _norm(email.split("@")[0]) if "@" in email else ""
        dom = _norm(email.split("@")[1].split(".")[0]) if "@" in email else ""
        hit = None
        for k in keys:
            if len(k) < 5:
                continue
            if pn and (k in pn or pn in k):
                hit = k
                break
            if local and len(local) >= 6 and (k.startswith(local[:10]) or local.startswith(k[:10])):
                hit = k
                break
            if dom and len(dom) >= 6 and (k.startswith(dom[:10]) or dom.startswith(k[:10])):
                hit = k
                break
        rec = {"charge_id": ch.get("id"),
               "amount": round(((ch.get("amount") or 0)
                                - (ch.get("amount_refunded") or 0)) / 100, 2),
               "date": str(dt.datetime.fromtimestamp(ch["created"],
                                                     tz=SYDNEY_TZ).date()),
               "payer": payer, "email": email,
               "status": ch.get("status")}
        ok = bool(ch.get("paid") and ch.get("status") == "succeeded")
        if hit and ok:
            by_client[hit].append(rec)
        elif hit and ch.get("status") == "failed":
            failed_by_client.setdefault(hit, []).append(rec)
        elif ok and rec["amount"] > 0:
            unmatched.append(rec)
    return by_client, unmatched, failed_by_client


def build_ar(fresh: bool = False, window_months: int = 3) -> dict:
    """The AR state: per-client expected/received/outstanding/aging over the
    trailing window_months (incl. the current month)."""
    today = today_sydney()
    cached = kv_store.get(_KV_CACHE)
    if cached and not fresh and cached.get("date") == str(today):
        return cached
    import forward_mrr
    rec = forward_mrr.per_client_recognition()
    sheet_clients = rec.get("clients") or {}
    degraded = list(rec.get("degraded") or [])
    # renewal-ledger extension of expectations where the grid is blank
    ledger = {}
    try:
        import finance_tabs
        ledger = finance_tabs.sheet_renewals_for_projection() or {}
    except Exception:
        pass
    start_month = (today.replace(day=1) - dt.timedelta(days=30 * (window_months - 1))).replace(day=1)
    labels = _month_labels_between(start_month, today)
    charges = _charges()
    if charges is None:
        return {"ok": False, "date": str(today),
                "reason": "Stripe unreachable — AR needs receipts truth "
                          "(never fabricated)"}
    receipts_by, unmatched, failed_by = _match_receipts(list(sheet_clients), charges)

    rows = []
    for name, srow in sorted(sheet_clients.items()):
        nn = _norm(name)
        monthly = srow.get("monthly") or {}
        le = ledger.get(nn)
        expected_rows = []
        for lbl in labels:
            exp = monthly.get(lbl)
            src = "RECOGNIZED grid"
            if not exp and le and le.get("mrr") and not le.get("extension"):
                d0 = dt.datetime.strptime(lbl, "%B %Y").date()
                lf, lu = le.get("from"), le.get("until")
                if lf and lu and lf <= str(d0.replace(day=28)) and lu >= str(d0):
                    exp, src = le["mrr"], le["provenance"]
            if exp:
                expected_rows.append({"month": lbl, "expected": float(exp),
                                      "source": src})
        if not expected_rows:
            continue
        month_bounds = {}
        for e in expected_rows:
            d0 = dt.datetime.strptime(e["month"], "%B %Y").date()
            month_bounds[e["month"]] = d0
        recs = receipts_by.get(nn) or []
        received_total = round(sum(r["amount"] for r in recs
                                   if str(start_month) <= r["date"]), 2)
        expected_total = round(sum(e["expected"] for e in expected_rows), 2)
        outstanding = round(max(expected_total - received_total, 0.0), 2)
        # aging: walk months oldest-first, consume receipts
        remaining = received_total
        oldest_unpaid = None
        for e in expected_rows:
            if remaining >= e["expected"] - 0.01:
                remaining -= e["expected"]
            else:
                oldest_unpaid = month_bounds[e["month"]]
                break
        days_overdue = 0
        status = "paid"
        if outstanding > 0.01:
            if oldest_unpaid:
                days_overdue = max((today - oldest_unpaid).days - _GRACE_DAYS, 0)
            status = "overdue" if days_overdue > 0 else "pending"
        if failed_by.get(nn):
            status = "failed-charge"
        nxt = None
        nxt_lbl = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        if (sheet_clients[name].get("monthly") or {}).get(nxt_lbl.strftime("%B %Y")) \
                or (ledger.get(nn) or {}).get("mrr"):
            nxt = str(nxt_lbl)
        rows.append({
            "client": name, "status": status,
            "expected_window": expected_total,
            "received_window": received_total,
            "outstanding": outstanding,
            "days_overdue": days_overdue,
            "oldest_unpaid_month": (oldest_unpaid.strftime("%B %Y")
                                    if oldest_unpaid else None),
            "next_expected": nxt,
            "expected_rows": expected_rows,
            "receipts": recs[:8],
            "failed_charges": failed_by.get(nn) or [],
        })
    rows.sort(key=lambda r: (-r["outstanding"], r["client"]))
    buckets = {"current": 0.0, "1-7d": 0.0, "8-30d": 0.0, "31+d": 0.0}
    for r in rows:
        if r["outstanding"] <= 0.01:
            continue
        d = r["days_overdue"]
        k = ("current" if d <= 0 else "1-7d" if d <= 7
             else "8-30d" if d <= 30 else "31+d")
        buckets[k] = round(buckets[k] + r["outstanding"], 2)
    total_outstanding = round(sum(b for b in buckets.values()), 2)
    anchor = kv_store.get("xero:ar_anchor")
    anchor_delta = (round(total_outstanding - float(anchor["accounts_receivable"]), 2)
                    if anchor and anchor.get("accounts_receivable") is not None
                    else None)
    # alias proposals for unmatched receipts (PROPOSED, never auto-assigned)
    proposals = []
    for u in unmatched[:12]:
        cand = None
        toks = [t for t in re.split(r"[^a-z0-9]+", (u["payer"] or "").lower())
                if len(t) > 4]
        for name in sheet_clients:
            if any(t in name.lower() for t in toks):
                cand = name
                break
        proposals.append({**u, "proposed_client": cand,
                          "state": "PROPOSED — confirm via the alias flow "
                                   "(never auto-assigned)"})
    out = {
        "ok": True, "date": str(today), "window_months": window_months,
        "rows": rows,
        "aging": buckets,
        "total_outstanding": total_outstanding,
        "xero_ar_anchor": anchor,
        "anchor_delta": anchor_delta,
        "anchor_note": ("schedule-AR vs the Xero Balance-Sheet AR line — a "
                        "delta can be legitimate (invoice timing, GST, "
                        "non-client invoices); invoice-level Xero needs a "
                        "scope the token doesn't hold (registered "
                        "dependency)" if anchor else
                        "Xero AR anchor not yet captured — lands with the "
                        "next daily BAS pull"),
        "unmatched_receipts": proposals,
        "degraded": degraded,
        "law": "pending is NEVER cash — receipts only (R-CASH)",
    }
    kv_store.put(_KV_CACHE, out)
    return out


def expected_month_end() -> dict:
    """The Part-A2 'expected month-end' leg: receipts to date + outstanding
    expected THIS month (labelled projection, never blended into cash)."""
    ar = build_ar()
    if not ar.get("ok"):
        return {"available": False, "reason": ar.get("reason")}
    today = today_sydney()
    lbl = today.strftime("%B %Y")
    due_this_month = 0.0
    for r in ar["rows"]:
        for e in r["expected_rows"]:
            if e["month"] == lbl:
                got = sum(x["amount"] for x in r["receipts"]
                          if x["date"][:7] == str(today)[:7])
                due_this_month += max(e["expected"] - got, 0.0)
    return {"available": True,
            "outstanding_expected_this_month": round(due_this_month, 2),
            "label": "expected by month-end (schedule + AR — a labelled "
                     "projection, not cash)"}


def sentinel_watch() -> dict:
    """Nightly: AR rebuild + anchor drift (loud via queue when the delta
    jumps) + overdue-growth signal for the renewal watch (owner lane)."""
    out = {"at": str(today_sydney())}
    try:
        ar = build_ar(fresh=True)
        out["ok"] = ar.get("ok")
        out["total_outstanding"] = ar.get("total_outstanding")
        out["anchor_delta"] = ar.get("anchor_delta")
        prev = kv_store.get("ar:watch_prev") or {}
        if (ar.get("anchor_delta") is not None
                and prev.get("anchor_delta") is not None
                and abs(ar["anchor_delta"] - prev["anchor_delta"]) > 2000):
            try:
                import ad_sentinel
                ad_sentinel.queue_item(
                    "AR-vs-Xero drift moved",
                    f"schedule-AR delta went {prev['anchor_delta']} → "
                    f"{ar['anchor_delta']}", rank="P2")
            except Exception:
                pass
        kv_store.put("ar:watch_prev", {"anchor_delta": ar.get("anchor_delta"),
                                       "total": ar.get("total_outstanding")})
        out["overdue_31d"] = [r["client"] for r in ar.get("rows", [])
                              if r["days_overdue"] > 31][:10]
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


# ── EDITH drill ─────────────────────────────────────────────────────────────

_WHO_RE = re.compile(r"who ha(s|sn)'?t paid|who owes|outstanding payments|"
                     r"pending payments|receivables|\bAR\b", re.I)


def handle_ar_command(text: str) -> tuple[str | None, bool]:
    if not _WHO_RE.search(text or ""):
        return None, False
    try:
        ar = build_ar()
        if not ar.get("ok"):
            return (f"I can't answer receivables honestly right now — "
                    f"{ar.get('reason')}.", True)
        owing = [r for r in ar["rows"] if r["outstanding"] > 0.01][:8]
        if not owing:
            return ("Nobody owes right now — every expected payment in the "
                    "window is received (schedule vs Stripe receipts).", True)
        bits = [f"{r['client']}: ${r['outstanding']:,.0f} "
                f"({r['status']}{', ' + str(r['days_overdue']) + 'd overdue' if r['days_overdue'] else ''}"
                f"{', oldest unpaid ' + r['oldest_unpaid_month'] if r['oldest_unpaid_month'] else ''})"
                for r in owing]
        return (f"Outstanding (schedule vs receipts, pending is never cash): "
                + " · ".join(bits)
                + f". Total ${ar['total_outstanding']:,.0f} across "
                  f"{len(owing)} client(s); aging buckets on the AR panel.", True)
    except Exception as e:
        logger.info("ar drill failed: %s", e)
        return None, False
