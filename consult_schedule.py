"""
consult_schedule.py
-------------------
THE consult scheduled-datetime source (DECISIONS #134). One place resolves
"when is this person's consult scheduled" from the cached GHL appointment
objects; the roster engine attaches it as a row FIELD — no per-panel lookups,
no parallel computation anywhere.

THE SEMANTIC PIN (#134): two dates exist per set and BOTH stay, with distinct
jobs. BOOKED-ON (appointment dateAdded / tracker Set Date — the setter action)
remains the WINDOWING clock for the Sets metric (#128, unchanged). SCHEDULED-
FOR (appointment startTime — when the consult happens) is DISPLAY ONLY: it is
what renders beside the tracker link, and it is NEVER a windowing clock.

TIMEZONE TRUTH (probed 2026-08-09, the class the mission warns about): the GHL
/contacts/{id}/appointments endpoint returns OFFSET-LESS, LOCATION-LOCAL
timestamps — hour-distribution proof over the live cache: 130/130 appointments
sit in business hours as written, while the UTC reading would put 121/130
between 7pm and 6am Sydney (26 at midnight, 17 at 1am — setters do not book
consults at 1am). So offset-less appointment strings are parsed as SYDNEY
LOCAL here (localize, never convert); strings carrying Z/an offset convert
normally. This is the OPPOSITE of `helpers.sydney_day`'s naive=UTC default,
which is correct for the Z-suffixed contact/Postgres wire stamps but wrong for
this endpoint — do not "unify" them.

Selection rule (the rebook chain): cancelled/invalid appointments NEVER render
as the consult; among the rest, the earliest UPCOMING appointment wins, else
the latest past one; rebooked ×N counts the cancelled/invalid ones. A
tracker-only set (no GHL appointment object) is an HONEST state, never a
fabricated time. Reads the kv cache only — network lives in warm() (bounded,
TTL'd), called by compute()'s refresh section and the nightly sweep.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from helpers import SYDNEY_TZ, now_sydney

logger = logging.getLogger(__name__)

_KV_APPT_CACHE = "ghl:appt_cache"        # ads_truth owns the writer; we read
_CANCELLED = {"cancelled", "invalid"}    # never "the consult" (#134)

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?"
                    r"(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def parse_appt_dt(value) -> datetime | None:
    """Appointment-endpoint timestamp → aware Sydney datetime.
    OFFSET-LESS = SYDNEY-LOCAL (localized, not converted — see module doc);
    Z/offset = converted. Returns None on anything unparseable."""
    s = str(value or "").strip()
    m = _DT_RE.match(s)
    if not m:
        return None
    try:
        naive = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                         int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
    except ValueError:                        # month 13, day 40 — never a guess
        return None
    off = m.group(7)
    if not off:
        try:
            return SYDNEY_TZ.localize(naive)
        except Exception:                     # DST gap edge — shift is explicit
            return SYDNEY_TZ.localize(naive, is_dst=True)
    if off == "Z":
        import pytz
        return pytz.utc.localize(naive).astimezone(SYDNEY_TZ)
    sign = 1 if off[0] == "+" else -1
    hh, mm = int(off[1:3]), int(off.replace(":", "")[3:5] or 0)
    from datetime import timezone
    aware = naive.replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm)))
    return aware.astimezone(SYDNEY_TZ)


def appt_day(value) -> str | None:
    """The Sydney calendar DAY of an appointment-endpoint timestamp — the
    source-aware counterpart of helpers.sydney_day for THIS endpoint's wire
    format (offset-less = local; Z/offset = converted). The F8 migration ran
    appointment fields through the naive=UTC path and shifted 22 derived
    set/show dates +1 day; every appointment-sourced derivation converts
    through HERE now. Message/contact/Postgres stamps (Z-suffixed or tz-aware)
    stay on helpers.sydney_day — verified per-endpoint, never assumed."""
    d = parse_appt_dt(value)
    return str(d.date()) if d else None


def format_consult(dt: datetime) -> str:
    """THE display format, exactly: "August 14, 2026, 2:30 PM". 12-hour clock:
    midnight = 12:00 AM, midday = 12:00 PM."""
    h24 = dt.hour
    ampm = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return f"{_MONTHS[dt.month - 1]} {dt.day}, {dt.year}, {h12}:{dt.minute:02d} {ampm}"


def _cache() -> dict:
    try:
        import kv_store
        return kv_store.get(_KV_APPT_CACHE) or {}
    except Exception:
        return {}


def _status(a: dict) -> str:
    return str(a.get("appointmentStatus") or a.get("status") or "").lower()


def pick_current(appts: list[dict], now: datetime | None = None) -> tuple[dict | None, int]:
    """(the current kept appointment, rebooked-count). Cancelled/invalid never
    qualify; earliest upcoming wins, else latest past."""
    now = now or now_sydney()
    kept, dead = [], 0
    for a in appts or []:
        if _status(a) in _CANCELLED:
            dead += 1
            continue
        dt_ = parse_appt_dt(a.get("startTime"))
        if dt_ is not None:
            kept.append((dt_, a))
    if not kept:
        return None, dead
    upcoming = sorted((k for k in kept if k[0] >= now), key=lambda k: k[0])
    if upcoming:
        return upcoming[0][1], dead
    return max(kept, key=lambda k: k[0])[1], dead


def consult_field(contact_id: str | None, market: str | None = None,
                  now: datetime | None = None, cache: dict | None = None) -> dict:
    """The roster-row field. States (all honest, never a fabricated time):
      scheduled     — the consult datetime, formatted + provenance
      no_appointment— cache FETCHED and empty/no kept appt → "set (tracker) ·
                      no GHL appointment"
      unfetched     — contact exists but the appointment cache hasn't covered
                      it yet (the warm passes converge this to zero)
      tracker_only  — no GHL contact at all
    US-market leads carry tz_label so the Sydney-local time is explicit."""
    now = now or now_sydney()
    if not contact_id:
        return {"state": "tracker_only",
                "note": "set (tracker) · no GHL appointment"}
    cache = cache if cache is not None else _cache()
    hit = cache.get(contact_id)
    if hit is None:
        return {"state": "unfetched",
                "note": "GHL appointment not fetched yet — the nightly warm "
                        "covers it; not a missing consult"}
    appts = hit.get("appts") or []
    cur, rebooked = pick_current(appts, now=now)
    if cur is None:
        return {"state": "no_appointment", "rebooked": rebooked,
                "note": ("set (tracker) · no GHL appointment"
                         if not rebooked else
                         f"set (tracker) · {rebooked} cancelled GHL "
                         f"appointment(s), no kept one")}
    dt_ = parse_appt_dt(cur.get("startTime"))
    out = {
        "state": "scheduled",
        "formatted": format_consult(dt_),
        "iso": dt_.isoformat(),
        "upcoming": dt_ >= now,
        "rebooked": rebooked,
        "status": _status(cur) or None,
        "appointment_id": cur.get("id"),
        "provenance": "ghl-appointment (scheduled-for · display only — "
                      "windowing stays on booked-on, #134)",
    }
    if (market or "").lower() == "us":
        # the known AEST-vs-US confusion class: the time IS Sydney local — say so
        out["tz_label"] = dt_.tzname()      # AEST / AEDT, DST-correct
    return out


def warm(contact_ids: list[str], cap: int = 20) -> dict:
    """Bounded network warm of the appointment cache for contacts the roster
    will render (7d TTL lives in ads_truth._cached_appointments). Never raises."""
    fetched = 0
    uncached: list[str] = []
    try:
        import ads_truth
        cache = _cache()
        uncached = [c for c in contact_ids if c and c not in cache]
        for cid in uncached:
            if fetched >= cap:
                break
            ads_truth._cached_appointments(cid)
            fetched += 1
    except Exception as e:
        logger.info("consult warm degraded: %s", e)
    return {"fetched": fetched, "remaining": max(0, len(uncached) - fetched)}
