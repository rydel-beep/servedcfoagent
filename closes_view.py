"""
closes_view.py
--------------
Deterministic factual recall for CLOSES — EDITH's voice/text path. Built
after a verify run caught the model FABRICATING a close; rebuilt for the ONE
CLOSE REGISTER: this module used to be a third private tracker reader (own
column map, no test-lead exclusion, no dedupe), which is why "what have we
closed this month" answered "the 5 most recent won rows ALL-TIME" — the
phrase "this month" was discarded and the population was the tracker's,
where three of September's four closes did not exist.

Now every answer reads `close_register` — the same population as /ads, the
SALES board, travelling, the tiles and compass — and a window in the
question is honoured. `_money`/`_date` stay exported (tracker_read imports
them).
"""
from __future__ import annotations

import datetime as dt
import logging
import re

logger = logging.getLogger(__name__)


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


def _won_deals() -> list[dict]:
    """All CONFIRMED register closes, newest first — the one population."""
    import close_register as CR
    out = []
    for e in CR.latest().get("entries") or []:
        if e.get("status") != "confirmed":
            continue
        try:
            cd = dt.date.fromisoformat(e["close_date"])
        except (ValueError, TypeError):
            continue
        out.append({
            "name": e.get("person") or "",
            "business": e.get("client") or "",
            "close_date": cd,
            "contract": (e.get("contract") or {}).get("value"),
            "cash": (e.get("cash") or {}).get("amount"),
            "offer": e.get("offer") or "",
            "missing": e.get("missing") or [],
            "tier": (e.get("attribution") or {}).get("tier"),
        })
    out.sort(key=lambda x: x["close_date"], reverse=True)
    return out


def recent_closes(limit: int = 5) -> dict:
    deals = _won_deals()
    if not deals:
        return {"closes": [], "total": 0,
                "degraded": [{"metric": "closes",
                              "reason": "close register unavailable"}]}
    return {"closes": [{**d, "close_date": str(d["close_date"])}
                       for d in deals[:limit]], "total": len(deals)}


def biggest_deal(within_days: int | None = None) -> dict | None:
    """The largest close by contract value (optionally within the last N
    days). Register data only — never a superlative from imagination."""
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


_CLOSE_COUNT_RE = re.compile(
    r"(how many|number of|count of)\s+\w*\s*(closes?|deals?|wins?|clients? closed)|"
    r"(closes?|deals?)\s+(count|did we (close|win)|in (june|july|may|april|the))", re.I)


def count_closes(w0: dt.date | None, w1: dt.date | None) -> int:
    """Confirmed register closes with a close date in [w0,w1]
    (None,None = all-time). Activity clock."""
    n = 0
    for d in _won_deals():
        cd = d["close_date"]
        if (w0 is None or cd >= w0) and (w1 is None or cd <= w1):
            n += 1
    return n


def _parse_window(text: str):
    """(w0, w1, label) or None — the same range parser the rest of the
    estate uses, so 'this month' means the same thing everywhere."""
    from helpers import today_sydney
    today = today_sydney()
    try:
        from range_unit_economics import parse_range
        rng = parse_range(text, today)
        if rng:
            return rng
    except Exception:  # noqa: BLE001
        pass
    if re.search(r"\bthis month\b", text, re.I):
        return (today.replace(day=1), today,
                f"{today.strftime('%B')} (month to date)")
    return None


def handle_close_count_command(text: str) -> tuple[str | None, bool]:
    """'How many closes in June / this month' → the register's count."""
    if not text or not _CLOSE_COUNT_RE.search(text):
        return None, False
    from helpers import today_sydney
    today = today_sydney()
    rng = _parse_window(text)
    if not rng:
        if re.search(r"\b(total|all|ever|do we have)\b", text, re.I):
            return (f"{count_closes(None, None)} closes total on the register "
                    f"(confirmed, activity clock)."), True
        rng = (today.replace(day=1), today, f"{today.strftime('%B')} (month to date)")
    import close_register as CR
    t = CR.totals(str(rng[0]), str(rng[1]), "activity")
    extra = (f" Plus {t['proposed']} proposed close(s) still needing evidence "
             f"({', '.join(t['proposed_people'])})." if t.get("proposed") else "")
    return (f"{t['count']} closes in {rng[2]} — the close register, activity "
            f"clock (closed in the window).{extra}"), True


def handle_closes_command(text: str) -> tuple[str | None, bool]:
    """Recent closes / biggest deal / 'what have we closed this month' —
    the register, with the window in the question honoured."""
    if not text:
        return None, False
    if _BIGGEST_RE.search(text):
        within = 90 if re.search(r"\b(quarter|90|recent|lately)\b", text, re.I) else None
        b = biggest_deal(within_days=within)
        if not b:
            return ("I don't have contract values I can rank right now — the "
                    "close register may be empty or rebuilding."), True
        scope = " in the last 90 days" if within else " on record"
        return f"Biggest deal{scope}: {_fmt(b)}.", True
    if _CLOSES_RE.search(text):
        rng = _parse_window(text)
        if rng:
            import close_register as CR
            rows = CR.closes(str(rng[0]), str(rng[1]), "activity")
            t = CR.totals(str(rng[0]), str(rng[1]), "activity")
            if not rows:
                base = f"Nothing on the close register for {rng[2]}."
            else:
                lines = []
                for e in rows:
                    who = e.get("client") or e.get("person")
                    cv = (e.get("contract") or {}).get("value")
                    miss = e.get("missing") or []
                    lines.append(f"{who} ({e['close_date']}"
                                 + (f", ${cv:,.0f}" if cv else "")
                                 + (f" — missing: {', '.join(miss)}" if miss else "")
                                 + ")")
                base = (f"{t['count']} close{'s' if t['count'] != 1 else ''} in "
                        f"{rng[2]} (activity clock): " + "; ".join(lines) + ".")
            if t.get("proposed"):
                base += (f" Plus {t['proposed']} proposed close(s) needing "
                         f"evidence: {', '.join(t['proposed_people'])}.")
            return base, True
        r = recent_closes(limit=5)
        cl = r.get("closes") or []
        if not cl:
            return ("I can't see the close register right now — it may be "
                    "rebuilding."), True
        return "Last few closes: " + "; ".join(_fmt(d) for d in cl) + ".", True
    return None, False
