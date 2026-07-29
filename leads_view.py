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
    outs = []
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
        elif "show status" in cl and "show" not in idx:
            idx["show"] = k
        elif "call outcome" in cl:
            outs.append(k)
    if outs:
        idx["setter_outcome"] = min(outs)  # the SETTER's "SET/DQ" outcome (the earlier column)
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
    rows = rows or []
    # Repoint to the clean view: test leads voided from all metrics (one classification engine).
    try:
        import test_leads
        return test_leads.clean_tracker_rows(rows)
    except Exception:
        return rows


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


def count_leads(w0: dt.date | None, w1: dt.date | None) -> dict:
    """Count ENTERED leads (a row with an Input Date + Lead Name) in [w0,w1]. None,None = all-time.
    Counts the mirror's RAW rows directly — never a scorecard aggregate."""
    rows = _rows()
    if not rows:
        return {"count": None, "degraded": [{"metric": "lead_count", "reason": "tracker unavailable"}]}
    hi = next((i for i, r in enumerate(rows[:6]) if any("lead name" in (c or "").lower() for c in r)), 0)
    cm = _col_map(rows[hi])
    if "date" not in cm or "name" not in cm:
        return {"count": None, "degraded": [{"metric": "lead_count", "reason": "lead columns not found"}]}
    n = 0
    for r in rows[hi + 1:]:
        name = (r[cm["name"]].strip() if cm.get("name", 99) < len(r) else "")
        if not name:
            continue
        d = _date(r[cm["date"]]) if cm["date"] < len(r) else None
        if d is None:
            continue
        if (w0 is None or d >= w0) and (w1 is None or d <= w1):
            n += 1
    return {"count": n}


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


# Lead COUNTS for a period — deterministic from raw rows, NEVER the scorecard or model.
_LEAD_COUNT_RE = re.compile(
    r"(how many|number of|count of|how much)\s+\w*\s*leads?|"
    r"leads?\s+(count|did we get|came in|in (june|july|may|april|the))", re.I)
_ALLTIME_RE = re.compile(r"\b(total|all|altogether|in (the )?(system|tracker|pipeline)|do we have|ever)\b", re.I)


def handle_lead_count_command(text: str) -> tuple[str | None, bool]:
    """'How many leads in June / this month / between X and Y' → raw count by Input Date."""
    if not text or not _LEAD_COUNT_RE.search(text):
        return None, False
    from helpers import today_sydney
    today = today_sydney()
    rng = None
    try:
        from range_unit_economics import parse_range
        rng = parse_range(text, today)
    except Exception:
        rng = None
    if not rng and _ALLTIME_RE.search(text):
        r = count_leads(None, None)
        if r.get("count") is None:
            return "I can't read the tracker rows right now to count leads.", True
        return f"{r['count']} leads total in the tracker (every entered lead, by Input Date).", True
    if not rng:
        rng = (today.replace(day=1), today, f"{today.strftime('%B')} (month to date)")
    r = count_leads(rng[0], rng[1])
    if r.get("count") is None:
        return "I can't read the tracker rows right now to count leads.", True
    return (f"{r['count']} leads in {rng[2]} — counted from the raw tracker by Input Date "
            f"(entered leads, not a scorecard figure)."), True


def _count_substage(stage: str, w0: dt.date | None, w1: dt.date | None) -> int | None:
    """Cohort count of a funnel sub-stage among leads whose Input Date is in [w0,w1].
    stage='set' → setter Call Outcome == SET; stage='show' → Show Status == Showed. Raw rows."""
    rows = _rows()
    if not rows:
        return None
    hi = next((i for i, r in enumerate(rows[:6]) if any("lead name" in (c or "").lower() for c in r)), 0)
    cm = _col_map(rows[hi])
    if "date" not in cm:
        return None
    col = cm.get("setter_outcome") if stage == "set" else cm.get("show")
    if col is None:
        return None
    want = "set" if stage == "set" else "showed"
    n = 0
    for r in rows[hi + 1:]:
        d = _date(r[cm["date"]]) if cm["date"] < len(r) else None
        if d is None or (w0 and d < w0) or (w1 and d > w1):
            continue
        if col < len(r) and r[col].strip().lower() == want:
            n += 1
    return n


_SUBSTAGE_RE = re.compile(
    r"(how many|number of|count of)\s+\w*\s*(sets?|shows?|appointments?|appts?|booked)\b|"
    r"(sets?|shows?)\s+(count|in (june|july|may|april|the))", re.I)


def handle_substage_count_command(text: str) -> tuple[str | None, bool]:
    """'How many sets/shows in <period>' → cohort count from raw rows (by lead Input Date)."""
    if not text or not _SUBSTAGE_RE.search(text):
        return None, False
    tl = text.lower()
    stage = "show" if ("show" in tl) else ("set" if re.search(r"\b(set|sets|appointment|appt|booked)\b", tl) else None)
    if stage is None:
        return None, False
    from helpers import today_sydney
    today = today_sydney()
    try:
        from range_unit_economics import parse_range
        rng = parse_range(text, today)
    except Exception:
        rng = None
    if not rng:
        rng = (today.replace(day=1), today, f"{today.strftime('%B')} (month to date)")
    n = _count_substage(stage, rng[0], rng[1])
    if n is None:
        return f"I can't read the tracker rows to count {stage}s right now.", True
    label = "sets booked" if stage == "set" else "shows"
    return (f"{n} {label} in {rng[2]} — counted from the raw tracker (of leads that came in that "
            f"window, by Input Date), not a scorecard figure."), True


def handle_client_count_command(text: str) -> tuple[str | None, bool]:
    """'How many (active) clients' → the canonical derived active-client count from the snapshot."""
    if not text or not re.search(r"(how many|number of|count of)\s+\w*\s*(active\s+)?clients?", text, re.I):
        return None, False
    try:
        from snapshot import load_persisted
        ac = (load_persisted() or {}).get("active_clients") or {}
        n = ac.get("active_count")
    except Exception:
        n = None
    if n is None:
        return "I can't read the active-client roster right now.", True
    return (f"{n} active clients (derived roster — Health tab reconciled with recent won deals, "
            f"churned excluded)."), True
