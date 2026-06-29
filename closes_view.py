"""
closes_view.py
--------------
Deterministic factual recall for CLOSES — the verbatim recent won deals and the biggest
deal, read from the mirrored Lead-to-Cash Tracker. Built after a verify run caught the
model FABRICATING a close ("Bondi Beach Restaurant — biggest deal of the quarter"): factual
recall about real deals must come from the data, never the model's imagination.

A CLOSE = a row with Call Outcome == "won" + a Close Date. Returns name, business, close
date, contract value, offer — VERBATIM. Mirrors the leads_view pattern. Reads by tab NAME.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

logger = logging.getLogger(__name__)

_TAB = "Lead-to-Cash Tracker"


def _money(s) -> float | None:
    s = str(s or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(s) -> dt.date | None:
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _col_map(header: list[str]) -> dict:
    idx, outs = {}, []
    for k, c in enumerate(header):
        cl = (c or "").lower()
        if "close date" in cl and "close" not in idx:
            idx["close"] = k
        elif "contract value" in cl and "contract" not in idx:
            idx["contract"] = k
        elif "lead name" in cl and "name" not in idx:
            idx["name"] = k
        elif "business name" in cl and "business" not in idx:
            idx["business"] = k
        elif "offer sold" in cl and "offer" not in idx:
            idx["offer"] = k
        elif "call outcome" in cl:
            outs.append(k)
    if outs:  # CLOSER outcome = the one at/before Close Date (not the setter's earlier col)
        cd = idx.get("close")
        before = [k for k in outs if cd is None or k < cd]
        idx["outcome"] = max(before) if before else max(outs)
    return idx


def _won_deals() -> list[dict]:
    """All won deals (Call Outcome == won) with a Close Date, newest first. From the mirror."""
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name(_TAB)
    except Exception:
        rows = None
    if rows is None:
        from sales_analytics_pull import _fetch_tab
        rows = _fetch_tab(_TAB)
    if not rows:
        return []
    hi = next((i for i, r in enumerate(rows[:6]) if any("close date" in (c or "").lower() for c in r)), 0)
    cm = _col_map(rows[hi])
    if "close" not in cm or "outcome" not in cm:
        return []
    out = []
    for r in rows[hi + 1:]:
        if cm["outcome"] >= len(r) or r[cm["outcome"]].strip().lower() != "won":
            continue
        cd = _date(r[cm["close"]]) if cm["close"] < len(r) else None
        if cd is None:
            continue
        out.append({
            "name": (r[cm["name"]].strip() if cm.get("name", 99) < len(r) else ""),
            "business": (r[cm["business"]].strip() if cm.get("business", 99) < len(r) else ""),
            "close_date": cd,
            "contract": _money(r[cm["contract"]]) if cm.get("contract", 99) < len(r) else None,
            "offer": (r[cm["offer"]].strip() if cm.get("offer", 99) < len(r) else ""),
        })
    out.sort(key=lambda x: x["close_date"], reverse=True)
    return out


def recent_closes(limit: int = 5) -> dict:
    deals = _won_deals()
    if not deals:
        return {"closes": [], "total": 0, "degraded": [{"metric": "closes", "reason": "tracker unavailable"}]}
    return {"closes": [{**d, "close_date": str(d["close_date"])} for d in deals[:limit]], "total": len(deals)}


def biggest_deal(within_days: int | None = None) -> dict | None:
    """The largest won deal by contract value (optionally within the last N days). Real data only."""
    deals = [d for d in _won_deals() if d.get("contract")]
    if within_days is not None:
        from helpers import today_sydney
        cutoff = today_sydney() - dt.timedelta(days=within_days)
        deals = [d for d in deals if d["close_date"] >= cutoff]
    if not deals:
        return None
    d = max(deals, key=lambda x: x["contract"])
    return {**d, "close_date": str(d["close_date"])}


# ── Voice / text command ─────────────────────────────────────────────────────

_CLOSES_RE = re.compile(
    r"(last|recent|latest)\s+(few\s+)?(closes?|deals?|wins?)|"
    r"\b(closes?|deals?)\s+(this|last)\s+(week|month)|recent(ly)?\s+closed|what.*closed\b", re.I)
_BIGGEST_RE = re.compile(r"\b(biggest|largest|highest)\s+(deal|close|contract|client)\b", re.I)


def _fmt(d: dict) -> str:
    who = d["business"] or d["name"]
    val = f", ${d['contract']:,.0f}" if d.get("contract") else ""
    offer = f", {d['offer']}" if d.get("offer") else ""
    return f"{who} (closed {d['close_date']}{offer}{val})"


def handle_closes_command(text: str) -> tuple[str | None, bool]:
    """Deterministic recent-closes / biggest-deal — verbatim from the mirror, no model embroidery."""
    if not text:
        return None, False
    if _BIGGEST_RE.search(text):
        # "biggest deal" — only answer from real contract values; never invent a superlative.
        within = 90 if re.search(r"\b(quarter|90|recent|lately)\b", text, re.I) else None
        b = biggest_deal(within_days=within)
        if not b:
            return ("I don't have contract values I can rank right now — I'd need to check the "
                    "tracker."), True
        scope = " in the last 90 days" if within else " on record"
        return f"Biggest deal{scope}: {_fmt(b)}.", True
    if _CLOSES_RE.search(text):
        r = recent_closes(limit=5)
        cl = r.get("closes") or []
        if not cl:
            return "I can't see the closed deals in the tracker right now — the data layer may be offline.", True
        return "Last few closes: " + "; ".join(_fmt(d) for d in cl) + ".", True
    return None, False
