"""
sheets_pull.py
--------------
Pull financial data from the Google Sheets payout tracker.
Sheet ID, tab name, and column mapping are all configurable via SHEET_CONFIG.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta

import requests

from config import SHEET_CONFIG, HTTP_TIMEOUT, WINDOW_CURRENT
from helpers import today_sydney

logger = logging.getLogger(__name__)


def _fetch_tab() -> tuple[list[str], list[dict]]:
    """
    Fetch the configured sheet tab as (headers, rows).
    Returns ([], []) on failure.
    """
    sid = SHEET_CONFIG["sheet_id"]
    tab = SHEET_CONFIG["tab_name"]
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab)}"
    )
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            logger.error("Sheet fetch failed (status %d)", resp.status_code)
            return [], []
        rows = list(csv.reader(io.StringIO(resp.text)))
        if len(rows) < 2:
            return [], []
        headers = rows[0]
        data = []
        for row in rows[1:]:
            if any(cell.strip() for cell in row):
                data.append({headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))})
        return headers, data
    except requests.RequestException as e:
        logger.error("Sheet request failed: %s", e)
        return [], []


def _validate_columns(headers: list[str]) -> list[str]:
    """Check that all required columns exist. Return list of missing column names."""
    required = SHEET_CONFIG["columns"]
    return [key for key, col_name in required.items() if col_name not in headers]


def _parse_money(val: str) -> float | None:
    """Parse a money string like '12500' or '$1,650.00' to float. Returns None if empty/invalid."""
    val = val.strip().replace("$", "").replace(",", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_date_mdy(val: str) -> date | None:
    """Parse M/D/YYYY format. Returns None on failure."""
    val = val.strip()
    if not val:
        return None
    try:
        parts = val.split("/")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass
    return None


def _parse_date_dmy(val: str) -> date | None:
    """Parse D-Mon-YYYY format (e.g. '9-Apr-2026'). Returns None on failure."""
    val = val.strip()
    if not val:
        return None
    try:
        from datetime import datetime as dt
        return dt.strptime(val, "%d-%b-%Y").date()
    except ValueError:
        pass
    return None


def _parse_close_date(val: str) -> date | None:
    """Try multiple date formats for Close date column."""
    result = _parse_date_mdy(val)
    if result:
        return result
    return _parse_date_dmy(val)


def _identify_setter(notes: str) -> str:
    """Identify setter from Notes (Manual) field."""
    n = notes.lower().strip()
    words = n.split()
    if not words or words[0] != "set":
        return "None"
    if " mm" in n or n.endswith("mm") or "maran" in n:
        return "Maran"
    if "coby" in n:
        return "Coby"
    return "Unattributed"


def pull_sheets() -> dict:
    """
    Pull and aggregate financial data from the configured Google Sheet.
    Commission values come from the actual sheet columns (Commission Closer #20,
    Commission Setter #19), never computed from offer type.
    Returns dict ready to merge into snapshot. No PII is included.
    """
    degraded = []
    cols = SHEET_CONFIG["columns"]

    headers, rows = _fetch_tab()
    if not headers:
        degraded.append({"metric": "sheets", "reason": "Failed to fetch Google Sheet"})
        return {"sheets": None, "degraded": degraded}

    missing = _validate_columns(headers)
    if missing:
        degraded.append({
            "metric": "sheets",
            "reason": f"Missing required columns: {', '.join(missing)}",
        })
        return {"sheets": None, "degraded": degraded}

    today = today_sydney()
    cutoff = today - timedelta(days=WINDOW_CURRENT)

    # Aggregates
    cash_collected_total = 0.0
    contract_value_total = 0.0
    setter_commission_total = 0.0
    closer_commission_total = 0.0
    deals_won = 0
    deals_won_in_window = 0
    commission_paid_count = 0
    commission_tbp_count = 0
    setter_breakdown: dict[str, float] = {}
    blank_closer_commission_count = 0
    blank_setter_commission_count = 0
    unparseable_cells: list[str] = []

    for row in rows:
        stage = row.get(cols["funnel_stage"], "").strip().lower()
        if stage != "won":
            continue

        deals_won += 1

        # Use close_date for financial window filtering; fall back to input_date
        close_raw = row.get(cols["close_date"], "").strip()
        input_raw = row.get(cols["input_date"], "").strip()
        close_dt = _parse_close_date(close_raw)
        input_dt = _parse_date_mdy(input_raw)
        effective_date = close_dt or input_dt

        in_window = effective_date is not None and effective_date >= cutoff
        if not in_window:
            continue

        deals_won_in_window += 1

        # Cash & contract
        cash = _parse_money(row.get(cols["cash_collected"], ""))
        contract = _parse_money(row.get(cols["contract_value"], ""))
        if cash is not None:
            cash_collected_total += cash
        if contract is not None:
            contract_value_total += contract

        # Closer commission — actual from sheet
        closer_raw = row.get(cols["commission_closer"], "").strip()
        closer_comm = _parse_money(closer_raw)
        if closer_raw and closer_comm is None:
            unparseable_cells.append(f"Commission Closer: {closer_raw!r}")
        if closer_comm is not None:
            closer_commission_total += closer_comm
        else:
            blank_closer_commission_count += 1

        # Setter commission — actual from sheet
        setter_raw = row.get(cols["commission_setter"], "").strip()
        setter_comm = _parse_money(setter_raw)
        if setter_raw and setter_comm is None:
            unparseable_cells.append(f"Commission Setter: {setter_raw!r}")
        if setter_comm is not None:
            setter_commission_total += setter_comm
        else:
            blank_setter_commission_count += 1

        # Commission remarks
        remarks = row.get(cols["commission_remarks"], "").strip().lower()
        if remarks == "paid":
            commission_paid_count += 1
        elif remarks == "tbp":
            commission_tbp_count += 1

        # Setter breakdown by person
        notes = row.get(cols["notes_manual"], "")
        setter = _identify_setter(notes)
        if setter_comm is not None:
            setter_breakdown[setter] = setter_breakdown.get(setter, 0.0) + setter_comm

    # Surface blank-commission Won deals as degraded so they get verified
    if blank_closer_commission_count > 0:
        degraded.append({
            "metric": "closer_commission",
            "reason": f"{blank_closer_commission_count} won deal(s) had blank closer commission — verify in sheet",
        })
    if blank_setter_commission_count > 0:
        degraded.append({
            "metric": "setter_commission",
            "reason": f"{blank_setter_commission_count} won deal(s) had blank setter commission — verify in sheet",
        })
    if unparseable_cells:
        degraded.append({
            "metric": "commission_parse",
            "reason": f"Could not parse {len(unparseable_cells)} commission cell(s): {unparseable_cells}",
        })

    return {
        "sheets": {
            "deals_won_total": deals_won,
            "deals_won_in_window": deals_won_in_window,
            "cash_collected": cash_collected_total,
            "contract_value": contract_value_total,
            "closer_commission_total": closer_commission_total,
            "setter_commission_total": setter_commission_total,
            "setter_breakdown": setter_breakdown if setter_breakdown else None,
            "commission_remarks": {
                "paid_count": commission_paid_count,
                "tbp_count": commission_tbp_count,
            },
            "data_quality": {
                "blank_closer_commission": blank_closer_commission_count,
                "blank_setter_commission": blank_setter_commission_count,
            },
            "period": {
                "label": f"trailing {WINDOW_CURRENT} days (won deals by close/input date)",
                "start": str(cutoff),
                "end": str(today),
            },
        },
        "degraded": degraded,
    }
