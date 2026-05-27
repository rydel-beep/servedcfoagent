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
