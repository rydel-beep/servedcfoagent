"""appointments.py — EVERY CALENDAR, EVERY USER, ONE SOURCE OF TRUTH (#162).

Rydel counted ten booked consults between today and 1 October. The dashboard
showed three on two surfaces and zero on a third — all reading the same
per-contact appointment cache, which is warmed ONLY for contacts that already
have a tracker lead row. Consults booked for anyone else were never fetched,
because appointments were only ever reached *through* a tracker lead. The
same failure shape as the payment matcher, one layer up: the candidate set,
not the data.

This module reads the CALENDARS themselves:

  GET /calendars/                 every calendar in the location
  GET /calendars/events           every event per calendar, in a window

and stores the classified result in kv. Facts that matter:

  · these events carry real UTC offsets ("2026-09-24T06:00:00+10:00") —
    unlike the per-contact endpoint, which is offset-less location-local
    (the #134 lesson). Parsed as given, compared in Sydney time.
  · BOOKED = scheduled and not cancelled. Cancelled is its own list, shown
    beside the count, never inside it.
  · TEST calendars (name contains "test") and the ONBOARDING calendar are
    classified out of the consult count and reported separately.
  · a calendar named "<Someone>'s Personal Calendar" names its events'
    owner — that is evidence, not a guess. Anything else resolves through
    GHL_USER_MAP (env JSON, {userId: name}) or shows the short id honestly.

READ-ONLY: GET requests only. The sync rides the CRM mirror loop; nothing
here runs on a page load.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re

import kv_store
from helpers import now_sydney, today_sydney, SYDNEY_TZ

logger = logging.getLogger(__name__)

K_EVENTS = "appts:calendar_events"
_TEST_RE = re.compile(r"\btest\b", re.I)
_PERSONAL_RE = re.compile(r"^(.+?)'s personal calendar$", re.I)
_FOLLOW_UP_RE = re.compile(r"\bfollow[\s-]*up\b", re.I)


def _calendar_kind(cal: dict) -> str:
    name = str(cal.get("name") or "")
    if _TEST_RE.search(name):
        return "test"
    if "onboarding" in name.lower():
        return "onboarding"
    if str(cal.get("calendarType") or "") == "personal":
        return "personal"
    return "consult"


def _user_map() -> dict:
    try:
        return json.loads(os.environ.get("GHL_USER_MAP", "") or "{}")
    except Exception:  # noqa: BLE001
        return {}


def parse_when(v) -> dt.datetime | None:
    """Offset-carrying ISO → a Sydney-local datetime. Never a UTC day
    boundary: the offset is honoured, then the moment is expressed in
    Sydney, so a 11:30 PM booking stays on its Sydney day."""
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=SYDNEY_TZ)      # defensive; events carry offsets
        return d.astimezone(SYDNEY_TZ)
    except Exception:  # noqa: BLE001
        return None


def sync(days_back: int = 7, days_fwd: int = 35) -> dict:
    """Pull every calendar's events for the window and store the classified
    result. GET only."""
    import ads_truth as AT
    from config import GHL_LOCATION_ID as LOC
    start = now_sydney().replace(hour=0, minute=0, second=0, microsecond=0) \
        - dt.timedelta(days=days_back)
    end = start + dt.timedelta(days=days_back + days_fwd)
    ms = lambda d: int(d.timestamp() * 1000)  # noqa: E731

    r = AT._ghl_get("/calendars/", {"locationId": LOC})
    if r.status_code != 200:
        out = {"ok": False, "error": f"calendar list {r.status_code}",
               "at": now_sydney().isoformat()}
        logger.warning("appointments sync failed: %s", out["error"])
        return out
    cals = (r.json() or {}).get("calendars") or []

    events, cal_meta, errors = [], [], []
    for cal in cals:
        kind = _calendar_kind(cal)
        owner_from_cal = None
        m = _PERSONAL_RE.match(str(cal.get("name") or ""))
        if m:
            owner_from_cal = m.group(1).strip()
        cal_meta.append({"id": cal.get("id"), "name": cal.get("name"),
                         "kind": kind})
        er = AT._ghl_get("/calendars/events",
                         {"locationId": LOC, "calendarId": cal.get("id"),
                          "startTime": ms(start), "endTime": ms(end)})
        if er.status_code != 200:
            errors.append({"calendar": cal.get("name"),
                           "status": er.status_code})
            continue
        for e in (er.json() or {}).get("events") or []:
            when = parse_when(e.get("startTime"))
            status = str(e.get("appointmentStatus") or "").lower() or "unknown"
            uid = str(e.get("assignedUserId") or "")
            owner = (owner_from_cal or _user_map().get(uid)
                     or (uid[:8] + "…" if uid else "unassigned"))
            events.append({
                "id": e.get("id"),
                "when": when.isoformat() if when else None,
                "day": str(when.date()) if when else None,
                "title": (e.get("title") or "").strip(),
                "status": status,
                "cancelled": status in ("cancelled", "invalid"),
                "calendar": cal.get("name"),
                "calendar_kind": kind,
                "contact_id": e.get("contactId"),
                "assigned_user_id": uid,
                "owner": owner,
                "booked_at": e.get("dateAdded"),
                "follow_up": bool(_FOLLOW_UP_RE.search(e.get("title") or "")),
            })
    events.sort(key=lambda x: x["when"] or "")
    out = {"ok": True, "at": now_sydney().isoformat(),
           "window": {"start": str(start.date()), "end": str(end.date())},
           "calendars": cal_meta, "events": events, "errors": errors}
    kv_store.put(K_EVENTS, out)
    logger.info("appointments sync: %d events across %d calendars",
                len(events), len(cal_meta))
    return out


def store() -> dict:
    return kv_store.get(K_EVENTS) or {}


def booked_between(w0: dt.date, w1: dt.date) -> dict:
    """Consults with a start time on a Sydney day in [w0, w1], classified.

    BOOKED = consult-kind or personal-calendar events, not cancelled. Test
    calendars and onboarding are counted separately and never inside the
    booked figure. Follow-ups are IN the count and flagged, so the list can
    say what it is counting instead of hiding the judgement."""
    st = store()
    booked, cancelled, excluded = [], [], []
    for e in st.get("events") or []:
        if not e.get("day") or not (str(w0) <= e["day"] <= str(w1)):
            continue
        if e.get("calendar_kind") in ("test", "onboarding"):
            excluded.append(e)
        elif e.get("cancelled"):
            cancelled.append(e)
        else:
            booked.append(e)
    return {
        "rows": booked, "count": len(booked),
        "cancelled": cancelled, "cancelled_count": len(cancelled),
        "excluded": excluded,
        "follow_ups": sum(1 for e in booked if e.get("follow_up")),
        "window_words": _window_words(w0, w1),
        "as_of": st.get("at"),
        "available": bool(st.get("events") is not None and st.get("ok")),
        "source": ("every calendar in the CRM, read directly — cancelled and "
                   "test bookings are shown separately, never inside the count"),
    }


def upcoming(days: int = 7) -> dict:
    """From now (not midnight) forward `days` days — the tiles' view."""
    now = now_sydney()
    res = booked_between(now.date(), (now + dt.timedelta(days=days)).date())
    rows = [e for e in res["rows"] if e.get("when") and e["when"] >= now.isoformat()]
    return {**res, "rows": rows, "count": len(rows),
            "window_words": f"now → {_day_words((now + dt.timedelta(days=days)).date())}"}


def _window_words(w0: dt.date, w1: dt.date) -> str:
    if str(w0) == str(today_sydney()):
        return f"today → {_day_words(w1)}"
    return f"{_day_words(w0)} → {_day_words(w1)}"


def _day_words(d) -> str:
    d = dt.date.fromisoformat(str(d)[:10]) if not isinstance(d, dt.date) else d
    return d.strftime("%b %-d")


def format_when(iso: str | None) -> str:
    d = parse_when(iso) if iso else None
    if not d:
        return "time not recorded"
    return d.strftime("%B %-d, %Y, %-I:%M %p")
