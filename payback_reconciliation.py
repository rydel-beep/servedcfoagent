"""
payback_reconciliation.py
-------------------------
TRUE payback period per deal / per offer, by reconciling each closed deal against its
ACTUAL Stripe payment history — not a blended cash-per-close approximation.

For each won deal: match it to a Stripe customer (email → name-search → flagged), read
the real cash-arrival timeline (succeeded charges, refunds subtracted), and find the day
cumulative collected cash crosses the loaded CAC for that close. Roll up by offer.

ACCURACY:
- Confident matches only (email exact / unambiguous name). Low/no match → EXCLUDED from
  the payback and listed for review. NEVER fabricate a match to force a number.
- Loaded CAC (ad + closer + setter per close, from the range engine), not bare ad spend.
- Small-sample / never-recovered / missing-offer are FLAGGED, not silently emitted.
- READ-ONLY Stripe. PII-safe: emails are used for matching server-side only — never logged,
  never returned in output, never stored. Output keys on business name + Stripe customer id.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import statistics

import requests

from config import STRIPE_SECRET_KEY, SHEET_CONFIG, HTTP_TIMEOUT

logger = logging.getLogger(__name__)

_API = "https://api.stripe.com"
# Lead-to-Cash Tracker columns (resolved by header elsewhere; these are the stable layout).
_C_NAME, _C_EMAIL, _C_BUSINESS, _C_OFFER, _C_CLOSE, _C_CONTRACT, _C_OUTCOME = 3, 4, 7, 26, 27, 28, 23
_OFFERS = {"scale engine", "scale engine split", "growth pro"}


def _money(s) -> float | None:
    s = str(s or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(s) -> dt.date | None:
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# ── Stripe (read-only) ───────────────────────────────────────────────────────

def _sget(path: str, params: dict) -> dict:
    backoff = 2.0
    for attempt in range(3):
        try:
            r = requests.get(_API + path, auth=(STRIPE_SECRET_KEY, ""), params=params,
                             timeout=(5, HTTP_TIMEOUT))
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 and attempt < 2:
                import time
                time.sleep(backoff); backoff *= 2; continue
            return {"error": r.status_code, "data": []}
        except requests.RequestException as e:
            if attempt < 2:
                import time
                time.sleep(backoff); backoff *= 2; continue
            return {"error": str(e)[:80], "data": []}
    return {"data": []}


def _find_customer(email: str, business: str) -> tuple[str | None, str | None, str | None]:
    """Return (customer_id, confidence, currency_hint). Email exact → name-search → (None,None,None).
    PII: email is used here only; never returned/logged."""
    if email and "@" in email:
        r = _sget("/v1/customers", {"email": email.strip(), "limit": 1})
        if r.get("data"):
            return r["data"][0]["id"], "email", r["data"][0].get("currency")
    if business:
        token = re.sub(r"[^a-zA-Z0-9 ]", "", business).split()
        token = token[0] if token else ""
        if len(token) >= 3:
            r = _sget("/v1/customers/search", {"query": f"name~'{token}'", "limit": 3})
            data = r.get("data") or []
            if len(data) == 1:  # unambiguous
                return data[0]["id"], "name", data[0].get("currency")
    return None, None, None


def _customer_timeline(cust_id: str) -> tuple[list[tuple[dt.date, float]], list[str]]:
    """Succeeded charges as [(date, net_amount_aud)], refunds subtracted. Charges only
    (subscription/instalment charges appear here too — using invoices as well would double-count).
    Returns (timeline, currency_flags)."""
    r = _sget("/v1/charges", {"customer": cust_id, "limit": 100})
    timeline = []
    flags = []
    for c in r.get("data", []):
        if not (c.get("paid") and c.get("status") == "succeeded"):
            continue
        cur = (c.get("currency") or "aud").upper()
        if cur != "AUD":
            flags.append(cur)
        net = (c.get("amount", 0) - c.get("amount_refunded", 0)) / 100.0
        if net <= 0:
            continue
        timeline.append((dt.date.fromtimestamp(c["created"]), round(net, 2)))
    timeline.sort()
    return timeline, sorted(set(flags))


# ── Tracker (mirror) ─────────────────────────────────────────────────────────

def _won_deals(w0: dt.date, w1: dt.date) -> list[dict]:
    """Won deals (Call Outcome == won) with Close Date in window, from the mirror."""
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name("Lead-to-Cash Tracker")
    except Exception:
        rows = None
    if rows is None:
        from sales_analytics_pull import _fetch_tab
        rows = _fetch_tab("Lead-to-Cash Tracker")
    out = []
    if not rows:
        return out
    for r in rows[1:]:
        if len(r) <= _C_CONTRACT:
            continue
        if (r[_C_OUTCOME].strip().lower() if len(r) > _C_OUTCOME else "") != "won":
            continue
        cd = _date(r[_C_CLOSE])
        if cd is None or not (w0 <= cd <= w1):
            continue
        out.append({
            "name": (r[_C_NAME].strip() if len(r) > _C_NAME else ""),
            "business": (r[_C_BUSINESS].strip() if len(r) > _C_BUSINESS else ""),
            "email": (r[_C_EMAIL].strip() if len(r) > _C_EMAIL else ""),  # PII: not returned
            "offer": (r[_C_OFFER].strip() if len(r) > _C_OFFER else ""),
            "contract": _money(r[_C_CONTRACT]),
            "close_date": cd,
        })
    return out


# ── Payback curve ────────────────────────────────────────────────────────────

def _deal_payback(timeline: list[tuple[dt.date, float]], close_date: dt.date, cac: float) -> dict:
    """Days from close until cumulative collected cash ≥ cac. None/ongoing if never reached."""
    cum = 0.0
    for d, amt in timeline:
        if d < close_date:
            # pre-close payment (deposit) still counts toward recovery from close day 0
            cum += amt
            continue
        cum += amt
        if cum >= cac:
            return {"payback_days": max((d - close_date).days, 0), "recovered": True,
                    "collected": round(cum, 2)}
    # account for pre-close cum already added
    if cum >= cac and timeline:
        return {"payback_days": 0, "recovered": True, "collected": round(cum, 2)}
    last = timeline[-1][0] if timeline else close_date
    return {"payback_days": None, "recovered": False, "collected": round(cum, 2),
            "ongoing_days": max((last - close_date).days, 0)}


def compute_payback(range_start: str | None = None, range_end: str | None = None) -> dict:
    """True payback per deal + per offer for closes in [range_start, range_end] (default last 90d)."""
    from helpers import today_sydney
    today = today_sydney()
    try:
        w1 = dt.date.fromisoformat(range_end) if range_end else today
        w0 = dt.date.fromisoformat(range_start) if range_start else (today - dt.timedelta(days=90))
    except (TypeError, ValueError):
        w1, w0 = today, today - dt.timedelta(days=90)

    degraded = []
    if not STRIPE_SECRET_KEY:
        return {"error": "no_stripe_key",
                "degraded": [{"metric": "payback", "reason": "No STRIPE_SECRET_KEY — cannot reconcile"}]}

    # Per-close loaded CAC for the window (ad + closer + setter ÷ closes) from the range engine.
    per_deal_cac = None
    try:
        import range_unit_economics
        ue = range_unit_economics.unit_economics(str(w0), str(w1))
        per_deal_cac = ue.get("cac_loaded")
    except Exception as e:
        logger.warning("payback: loaded CAC unavailable: %s", e)
    if not per_deal_cac:
        degraded.append({"metric": "payback_cac",
                         "reason": "Loaded CAC unavailable for window — payback can't be computed"})
        return {"error": "no_cac", "window": {"start": str(w0), "end": str(w1)}, "degraded": degraded}

    deals = _won_deals(w0, w1)
    matched, unmatched = [], []
    for d in deals:
        cust_id, conf, _cur = _find_customer(d["email"], d["business"])
        if not cust_id:
            unmatched.append({"business": d["business"] or d["name"], "offer": d["offer"],
                              "close_date": str(d["close_date"]), "contract": d["contract"],
                              "reason": "no confident Stripe match (email/name) — review/log link"})
            continue
        timeline, cur_flags = _customer_timeline(cust_id)
        if not timeline:
            unmatched.append({"business": d["business"] or d["name"], "offer": d["offer"],
                              "close_date": str(d["close_date"]), "customer": cust_id,
                              "reason": "matched a Stripe customer but no succeeded charges yet"})
            continue
        pb = _deal_payback(timeline, d["close_date"], per_deal_cac)
        rec = {
            "business": d["business"] or d["name"],
            "offer": d["offer"],
            "close_date": str(d["close_date"]),
            "contract": d["contract"],
            "customer": cust_id,           # id only — no email/PII
            "match_confidence": conf,
            "cac": per_deal_cac,
            "payback_days": pb["payback_days"],
            "recovered": pb["recovered"],
            "collected_to_date": pb["collected"],
            "ongoing_days": pb.get("ongoing_days"),
        }
        if cur_flags:
            rec["currency_flag"] = cur_flags
        matched.append(rec)

    # Per-offer rollup (recovered deals only; small-sample flagged).
    per_offer = {}
    for offer in sorted({m["offer"] for m in matched if m["offer"]}):
        grp = [m for m in matched if m["offer"] == offer and m["recovered"] and m["payback_days"] is not None]
        ongoing = [m for m in matched if m["offer"] == offer and not m["recovered"]]
        entry = {"deals_recovered": len(grp), "deals_ongoing": len(ongoing)}
        if grp:
            days = [m["payback_days"] for m in grp]
            entry["median_payback_days"] = round(statistics.median(days), 1)
            entry["avg_payback_days"] = round(statistics.mean(days), 1)
        if len(grp) < 3:
            entry["caveat"] = f"small sample ({len(grp)} recovered deal(s)) — directional, not robust"
        per_offer[offer] = entry

    # Blended (all recovered matched deals).
    all_rec = [m["payback_days"] for m in matched if m["recovered"] and m["payback_days"] is not None]
    blended = {"median_payback_days": round(statistics.median(all_rec), 1) if all_rec else None,
               "deals_recovered": len(all_rec),
               "note": "blend across offers — masks per-offer differences; see per_offer"}

    return {
        "window": {"start": str(w0), "end": str(w1)},
        "per_deal_cac": per_deal_cac,
        "cac_basis": "loaded CAC per close (ad + closer + setter), from the range engine",
        "blended": blended,
        "per_offer": per_offer,
        "matched": matched,
        "unmatched": unmatched,
        "summary": {"closes": len(deals), "matched": len(matched), "unmatched": len(unmatched),
                    "match_rate_pct": round(100 * len(matched) / len(deals)) if deals else None},
        "as_of": today.isoformat(),
        "source": "stripe_charges + lead-to-cash mirror",
        "degraded": degraded,
    }


# ── Voice / text command ─────────────────────────────────────────────────────

_PAYBACK_RE = re.compile(r"\bpay[\s-]?back\b", re.I)


def _which_offer(t: str) -> str | None:
    tl = t.lower()
    if "growth pro" in tl:
        return "Growth Pro"
    if "split" in tl:
        return "Scale Engine Split"
    if "scale engine" in tl:
        return "Scale Engine"
    return None


def handle_payback_command(text: str) -> tuple[str | None, bool]:
    """Answer 'payback on Growth Pro', 'payback by offer', etc. — true Stripe-reconciled payback."""
    if not text or not _PAYBACK_RE.search(text):
        return None, False
    res = compute_payback()
    if res.get("error"):
        return (f"I can't compute true payback right now ({res['error'].replace('_', ' ')})."), True
    po = res["per_offer"]
    summ = res["summary"]
    tail = ""
    if summ["unmatched"]:
        tail = (f" ({summ['unmatched']} of {summ['closes']} closes aren't confidently linked to "
                f"Stripe yet — they're on the review list.)")
    offer = _which_offer(text)
    if offer and offer in po:
        e = po[offer]
        if e.get("median_payback_days") is not None:
            cav = f" {e['caveat']}." if e.get("caveat") else ""
            ong = f" {e['deals_ongoing']} still recovering." if e.get("deals_ongoing") else ""
            return (f"{offer} pays back in ~{e['median_payback_days']:.0f} days (median of "
                    f"{e['deals_recovered']} reconciled deal(s), real Stripe cash timing).{cav}{ong}{tail}"), True
        return (f"No {offer} deals have recovered their CAC in the data yet "
                f"({e.get('deals_ongoing', 0)} still collecting).{tail}"), True
    # By-offer summary
    parts = []
    for o, e in po.items():
        if e.get("median_payback_days") is not None:
            parts.append(f"{o} ~{e['median_payback_days']:.0f}d ({e['deals_recovered']} deal(s)"
                         + (", small sample" if e.get("caveat") else "") + ")")
        else:
            parts.append(f"{o} not yet recovered")
    bl = res["blended"].get("median_payback_days")
    head = f"Payback by offer (real Stripe timing): {'; '.join(parts) or 'no reconciled deals yet'}."
    if bl is not None:
        head += f" Blended ~{bl:.0f}d (masks the per-offer spread)."
    return head + tail, True
