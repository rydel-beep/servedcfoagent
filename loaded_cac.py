"""
loaded_cac.py
-------------
The setter-commission half of the fully-loaded CAC, read ACTUAL from the SETTER
PAYOUT LOG.

CAC was understating the setter cost: it used the scorecard's $50-per-qualified-set
figure only (~$500), missing the 5%-of-cash-collected half of setter comp. The real
per-deal figures (set_fee $50 + pct_bonus 5% of cash) live in the SETTER PAYOUT LOG.

That log's gid (552970662) now returns HTTP 400 — so we read it BY NAME
("SETTER PAYOUT LOG"), which returns 200. Its by-name column layout differs from the
old gid layout:
  col1 Deal/Lead · col2 Setter · col3 Won · col4 Cash · col5 set_fee · col6 pct_bonus
  · col7 total_owed · col8 Status · col9 Notes (carries the payout date)

Window basis: the by-name log has NO set/close-date column, and joining lead names to
the main tracker's close dates matched only ~7/164 deals (unreliable). So we window by
the log's PAYOUT date (the only complete, reliable signal) and LABEL it as such.
Read-only; AUD; degrades to None (caller falls back to the scorecard figure) on failure.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, timedelta

import requests

from config import SHEET_CONFIG, HTTP_TIMEOUT
from helpers import today_sydney

logger = logging.getLogger(__name__)

_TAB_NAME = "SETTER PAYOUT LOG"
_SETTERS = {"coby", "maran", "unattributed"}
# Column indices in the by-name export (see module docstring).
_C_LEAD, _C_SETTER, _C_WON, _C_CASH, _C_FEE, _C_BONUS, _C_OWED, _C_STATUS, _C_NOTES = 1, 2, 3, 4, 5, 6, 7, 8, 9


def _money(s: str) -> float | None:
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date_in(s: str) -> date | None:
    """Extract an MM/DD/YYYY date from a cell that may carry trailing text ('06/23/2026 payout')."""
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def read_setter_comp(window_start: str | None = None, window_end: str | None = None) -> dict:
    """Window-matched setter commission (set_fee + 5% bonus) read actual from the log.

    window_start/end: ISO dates; default = trailing 30d ending today (matches the sales window).
    Returns {setter_comm, set_fees, pct_bonus, deal_count, window, source, basis, degraded}.
    setter_comm is None (with a degraded entry) when the log can't be read.
    """
    degraded = []
    today = today_sydney()
    try:
        w1 = date.fromisoformat(window_end) if window_end else today
        w0 = date.fromisoformat(window_start) if window_start else (today - timedelta(days=30))
    except (TypeError, ValueError):
        w1, w0 = today, today - timedelta(days=30)

    sid = SHEET_CONFIG["sheet_id"]
    url = (f"https://docs.google.com/spreadsheets/d/{sid}"
           f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(_TAB_NAME)}")
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            raise requests.RequestException(f"HTTP {resp.status_code}")
        rows = list(csv.reader(io.StringIO(resp.text)))
    except requests.RequestException as e:
        degraded.append({
            "metric": "loaded_cac_setter",
            "reason": f"SETTER PAYOUT LOG read failed ({e}); CAC falls back to scorecard setter figure.",
            "severity": "optional",
        })
        return {"setter_comm": None, "degraded": degraded}

    set_fees = pct_bonus = 0.0
    deal_count = 0
    for row in rows:
        if len(row) <= _C_NOTES:
            continue
        if (row[_C_SETTER].strip().lower() if len(row) > _C_SETTER else "") not in _SETTERS:
            continue
        fee = _money(row[_C_FEE]) or 0.0
        bonus = _money(row[_C_BONUS]) or 0.0
        if fee == 0 and bonus == 0:
            continue
        d = _date_in(row[_C_NOTES])
        if d is None or not (w0 <= d <= w1):
            continue
        set_fees += fee
        pct_bonus += bonus
        deal_count += 1

    total = round(set_fees + pct_bonus, 2)
    return {
        "setter_comm": total,
        "set_fees": round(set_fees, 2),
        "pct_bonus": round(pct_bonus, 2),
        "deal_count": deal_count,
        "window": {"start": str(w0), "end": str(w1)},
        "source": "SETTER PAYOUT LOG (by name; actual per-deal $50 set fee + 5% cash bonus)",
        "basis": ("payout-date-windowed — the log has no set/close-date column and the "
                  "tracker name-join matched only ~7/164 deals, so payout date is the reliable key"),
        "degraded": degraded,
    }
