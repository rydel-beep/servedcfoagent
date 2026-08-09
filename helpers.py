"""
helpers.py
----------
Shared helpers. Every module imports from here.
"""
from __future__ import annotations

from datetime import date, datetime
import pytz

SYDNEY_TZ = pytz.timezone("Australia/Sydney")


def today_sydney() -> date:
    """Return the current date in Australia/Sydney timezone."""
    return datetime.now(tz=SYDNEY_TZ).date()


def now_sydney() -> datetime:
    """Return the current datetime in Australia/Sydney timezone."""
    return datetime.now(tz=SYDNEY_TZ)


def sydney_day(value) -> date | None:
    """THE derivation-boundary day helper (audit F8). The Sydney-local calendar
    day of a timestamp — NEVER the UTC slice.

    Root cause F8 fixed here, at the source: GHL/Postgres timestamps are UTC;
    `str(ts)[:10]` takes the UTC day, so any event before ~10–11am Sydney lands
    on the PREVIOUS day (drill B9: 2026-07-09T22:30Z is 08:30 AEST on the 10th
    but sliced to 07-09). Every derivation path converts through here.

    Accepts: aware/naive datetimes (naive = assumed UTC — the upstream wire
    format), ISO strings with Z/offset/millis, bare YYYY-MM-DD strings, dates.
    Returns a date or None. DST-correct via pytz (AEST↔AEDT)."""
    import re as _re
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_v = value if value.tzinfo else value.replace(tzinfo=__import__("pytz").utc)
        return dt_v.astimezone(SYDNEY_TZ).date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:                       # a bare date has no clock to convert — pass through
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?"
                  r"(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", s)
    if not m:
        return None
    naive = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
    off = m.group(7)
    import pytz as _pytz
    if off and off != "Z":
        sign = 1 if off[0] == "+" else -1
        hh, mm = int(off[1:3]), int(off.replace(":", "")[3:5] or 0)
        from datetime import timedelta, timezone
        aware = naive.replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm)))
    else:
        aware = _pytz.utc.localize(naive)    # Z or offset-less wire timestamps = UTC
    return aware.astimezone(SYDNEY_TZ).date()
