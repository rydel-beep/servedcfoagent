"""
meta_range.py
-------------
THE one range-builder for every Meta insights request (DECISIONS #138). Makes
API error #3018 ("start date cannot be beyond 37 months from the current date")
STRUCTURALLY IMPOSSIBLE, and returns range-scoped degradation so a failure on
one span never blunt-degrades a healthy one.

Every /insights call in the codebase routes through `insights()` — grep-asserted
single call-site (I13-style). It is pure range logic; the caller passes its own
low-level GET (`fetch_all(path, params) -> (rows|None, err)`), so this module
stays DRY without merging meta_spend and meta_entities.

CLAMP  — start = max(requested_start, api_floor). api_floor rolls DAILY from
         today_sydney; NEVER cached across days (Meta's window rolls forward
         every day). Boundary pinned empirically: the edge is exactly calendar-
         37-months before today; default 3-day safety margin sits inside it.
SCOPE  — a per-ad request is bound to that ad's own lifetime (launch→now); an ad
         born 2026-07 never references 2023. Only account aggregates approach
         the floor.
CHUNK  — spans longer than _MAX_CHUNK_DAYS split into sequential requests, merged
         deterministically; a single chunk's failure degrades ONLY its own days
         (loud, retryable), never the whole range.
DISCLOSE — a clamp truncation carries `clamped_from` so the UI can say
         "Meta spend via API from {floor}; earlier from archive/pre-retention",
         a NAMED limit — never a red badge, never a partial rendered as complete.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import os

logger = logging.getLogger(__name__)

_RETENTION_MONTHS = 37
_SAFETY_MARGIN_DAYS = int(os.getenv("META_RETENTION_SAFETY_DAYS", "3"))
_MAX_CHUNK_DAYS = int(os.getenv("META_INSIGHTS_MAX_CHUNK_DAYS", "90"))


def _cal_minus_months(d: dt.date, months: int) -> dt.date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def api_floor(today: dt.date | None = None) -> dt.date:
    """The earliest `since` Meta will accept today. Calendar 37 months back +
    safety margin. Computed FRESH every call — the boundary rolls daily, so a
    cached floor would reject valid days tomorrow (or accept rejected ones)."""
    if today is None:
        from helpers import today_sydney
        today = today_sydney()
    return _cal_minus_months(today, _RETENTION_MONTHS) + dt.timedelta(days=_SAFETY_MARGIN_DAYS)


def clamp(start: str | dt.date, end: str | dt.date, *, ad_launch: str | dt.date | None = None,
          today: dt.date | None = None) -> dict:
    """Resolve a request's real, retrievable [start, end] in Sydney days.
    Returns {start, end, clamped_from, floor, empty, reason}. `empty` = the
    whole request is outside the API window / after end (honest no-fetch)."""
    def _d(v):
        return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
    if today is None:
        from helpers import today_sydney
        today = today_sydney()
    s, e = _d(start), _d(end)
    floor = api_floor(today)
    if e > today:                       # future end clamped (never fetch tomorrow)
        e = today
    orig_s = s
    if ad_launch is not None:           # SCOPE: never ask before this ad existed
        s = max(s, _d(ad_launch))
    clamped_from = None
    if s < floor:                       # CLAMP: never ask before the API boundary
        clamped_from = str(orig_s)
        s = floor
    if s > e:                           # nothing retrievable in-window
        return {"start": None, "end": None, "clamped_from": clamped_from or str(orig_s),
                "floor": str(floor), "empty": True,
                "reason": "requested range is entirely before the Meta API "
                          "retention floor or after today"}
    return {"start": str(s), "end": str(e), "clamped_from": clamped_from,
            "floor": str(floor), "empty": False, "reason": None}


def chunks(start: str, end: str, max_days: int = _MAX_CHUNK_DAYS) -> list[tuple[str, str]]:
    """Split [start, end] (inclusive, Sydney days) into ≤max_days spans. DST is a
    non-issue: these are calendar-day strings, not clock arithmetic."""
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    out = []
    cur = s
    while cur <= e:
        chunk_end = min(e, cur + dt.timedelta(days=max_days - 1))
        out.append((str(cur), str(chunk_end)))
        cur = chunk_end + dt.timedelta(days=1)
    return out


def insights(path: str, base_params: dict, start, end, fetch_all, *,
             source: str, ad_launch=None, today=None) -> dict:
    """THE builder. Clamp → scope → chunk → sequential fetch → merge. Returns
    {rows, clamped_from, floor, empty, degraded}. `degraded` entries are
    RANGE-SCOPED: {source, range, cause} — one per failed chunk only, so a
    healthy chunk's days stay live. Never raises."""
    cl = clamp(start, end, ad_launch=ad_launch, today=today)
    if cl["empty"]:
        return {"rows": [], "clamped_from": cl["clamped_from"], "floor": cl["floor"],
                "empty": True, "degraded": []}
    rows: list = []
    degraded: list = []
    for cs, ce in chunks(cl["start"], cl["end"]):
        params = dict(base_params)
        params["time_range"] = json.dumps({"since": cs, "until": ce})
        got, err = fetch_all(path, params)
        if got is None:
            degraded.append({"source": source, "range": f"{cs}..{ce}", "cause": str(err)[:160]})
            continue
        rows.extend(got)
    return {"rows": rows, "clamped_from": cl["clamped_from"], "floor": cl["floor"],
            "empty": False, "degraded": degraded}


def clamp_note(clamped_from: str | None, floor: str) -> str | None:
    """The honest disclosure string for a truncated range (None when nothing was
    clamped)."""
    if not clamped_from:
        return None
    return (f"Meta spend via API from {floor} (Meta's 37-month API limit rolls "
            f"daily); earlier days from the archive where captured, else "
            f"pre-API-retention · requested from {clamped_from}")
