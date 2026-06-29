"""
leads_view.py
-------------
Surface LEADS (not just closes) from the mirrored Lead-to-Cash Tracker, so EDITH can answer
"who's the latest lead?" — the gap a live test exposed (she could name recent closes but not
the latest lead entered).

The tracker (mirror tab "Lead-to-Cash Tracker", gid 1923956551) is the full pipeline: the
LEAD INTAKE columns (Input Date/Time, Lead Name, Lead Source, Business) front the same rows
that later carry Close Date / Call Outcome. A LEAD = a row with an Input Date + Lead Name;
a CLOSE = Call Outcome == "won". Reads from the mirror (DB-speed); live fallback.

PII-safe: Email/Phone columns exist but are NEVER returned or logged — only Lead Name,
Business, Source, and the intake timestamp (auth-locked chat surface).
"""
from __future__ import annotations

import datetime as dt
import logging
import re

logger = logging.getLogger(__name__)

_TAB = "Lead-to-Cash Tracker"


def _col_map(header: list[str]) -> dict:
    idx = {}
    for k, c in enumerate(header):
        cl = (c or "").lower()
        if "input date" in cl and "date" not in idx:
            idx["date"] = k
        elif "input time" in cl and "time" not in idx:
            idx["time"] = k
        elif "lead name" in cl and "name" not in idx:
            idx["name"] = k
        elif "lead source" in cl and "source" not in idx:
            idx["source"] = k
        elif "business name" in cl and "business" not in idx:
            idx["business"] = k
    return idx


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


def _time_minutes(s) -> int:
    """Parse '6:37 AM' → minutes since midnight (for same-day ordering). 0 if unparseable."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", str(s or ""))
    if not m:
        return 0
    h = int(m.group(1)) % 12
    if m.group(3) and m.group(3).lower() == "pm":
        h += 12
    return h * 60 + int(m.group(2))


def _rows():
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name(_TAB)
    except Exception:
        rows = None
    if rows is None:
        from sales_analytics_pull import _fetch_tab
        rows = _fetch_tab(_TAB)
    return rows or []


def recent_leads(limit: int = 5) -> dict:
    """The most recently ENTERED leads (by Input Date + Time), newest first. PII-safe."""
    rows = _rows()
    if not rows:
        return {"leads": [], "total": 0, "degraded": [{"metric": "leads", "reason": "tracker unavailable"}]}
    hi = next((i for i, r in enumerate(rows[:6]) if any("lead name" in (c or "").lower() for c in r)), 0)
    cm = _col_map(rows[hi])
    if "date" not in cm or "name" not in cm:
        return {"leads": [], "total": 0, "degraded": [{"metric": "leads", "reason": "lead columns not found"}]}
    leads = []
    for r in rows[hi + 1:]:
        d = _date(r[cm["date"]]) if cm["date"] < len(r) else None
        name = (r[cm["name"]].strip() if cm.get("name", 99) < len(r) else "")
        if d is None or not name:
            continue
        leads.append({
            "name": name,
            "business": (r[cm["business"]].strip() if cm.get("business", 99) < len(r) else ""),
            "source": (r[cm["source"]].strip() if cm.get("source", 99) < len(r) else ""),
            "date": str(d),
            "time": (r[cm["time"]].strip() if cm.get("time", 99) < len(r) else ""),
            "_sortkey": (d.toordinal(), _time_minutes(r[cm["time"]]) if cm.get("time", 99) < len(r) else 0),
        })
    leads.sort(key=lambda x: x["_sortkey"], reverse=True)
    for x in leads:
        x.pop("_sortkey", None)
    return {"leads": leads[:limit], "total": len(leads), "as_of": None}


def latest_lead() -> dict | None:
    r = recent_leads(limit=1)
    return r["leads"][0] if r.get("leads") else None


# ── Voice / text command ─────────────────────────────────────────────────────

_LEADS_RE = re.compile(
    r"(latest|most recent|newest|last|recent)\s+lead|lead.*(just )?(came in|entered)|"
    r"who('?s| is| was)?\s+(the\s+)?(latest|newest|last|most recent)\s+lead|new leads?\b", re.I)


def handle_leads_command(text: str) -> tuple[str | None, bool]:
    if not text or not _LEADS_RE.search(text):
        return None, False
    # "latest/who" → single; "recent/last few/new leads" → a short list
    single = bool(re.search(r"(latest|newest|most recent|who('?s| is| was))", text, re.I)) \
        and not re.search(r"(few|recent leads|last \d|new leads)", text, re.I)
    r = recent_leads(limit=1 if single else 5)
    leads = r.get("leads") or []
    if not leads:
        return "I can't see any leads in the tracker right now — the data layer may be offline.", True
    def fmt(L):
        biz = f" ({L['business']})" if L.get("business") and L["business"] != L["name"] else ""
        src = f" via {L['source']}" if L.get("source") else ""
        when = f"{L['date']}" + (f" {L['time']}" if L.get("time") else "")
        return f"{L['name']}{biz}{src} — {when}"
    if single:
        return f"Latest lead: {fmt(leads[0])}.", True
    return "Most recent leads: " + "; ".join(fmt(L) for L in leads) + ".", True
