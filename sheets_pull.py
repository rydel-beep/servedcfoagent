"""
sheets_pull.py
--------------
Pull financial data from the Lead-to-Cash Tracker Google Sheet.
Sheet ID, tab name, and column mapping are all configurable via SHEET_CONFIG.
Commission values come from the actual sheet columns, never computed from offer type.
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

# Column index for the closer's "Call Outcome" (second occurrence of that header).
# The sheet has two "Call Outcome" columns: index 16 (setter) and index 23 (closer).
CLOSER_OUTCOME_IDX = SHEET_CONFIG["columns"].get("closer_outcome_idx", 23)


def _fetch_tab() -> tuple[list[str], list[list[str]]]:
    """
    Fetch the configured sheet tab as (headers, raw_rows).
    Returns raw row lists (not dicts) so callers can use column index for
    duplicate header names.
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
        all_rows = list(csv.reader(io.StringIO(resp.text)))
        if len(all_rows) < 2:
            return [], []
        headers = all_rows[0]
        data = [r for r in all_rows[1:] if any(cell.strip() for cell in r)]
        return headers, data
    except requests.RequestException as e:
        logger.error("Sheet request failed: %s", e)
        return [], []


def _col_index(headers: list[str], col_key: str) -> int | None:
    """Find column index by header name from SHEET_CONFIG. Returns None if missing."""
    col_name = SHEET_CONFIG["columns"].get(col_key, "")
    if not col_name or col_name not in headers:
        return None
    return headers.index(col_name)


def _validate_columns(headers: list[str]) -> list[str]:
    """Check required columns exist. Return list of missing config keys."""
    required_keys = [
        "close_date", "cash_collected", "contract_value",
        "commission_setter", "commission_closer", "offer_sold",
    ]
    missing = []
    for key in required_keys:
        col_name = SHEET_CONFIG["columns"].get(key, "")
        if not col_name or col_name not in headers:
            missing.append(key)
    if len(headers) <= CLOSER_OUTCOME_IDX:
        missing.append("closer_outcome (index out of range)")
    return missing


def _parse_money(val: str) -> float | None:
    """Parse a money string like '$14,500' or '12500' to float. Returns None if empty/invalid."""
    val = val.strip().replace("$", "").replace(",", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_date(val: str) -> date | None:
    """Parse date from multiple formats seen in the sheet. Returns None on failure."""
    val = val.strip()
    if not val:
        return None
    # Try YYYY-MM-DD
    if len(val) >= 10 and val[4] == "-":
        try:
            parts = val[:10].split("-")
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass
    # Try M/D/YYYY
    if "/" in val:
        try:
            parts = val.split("/")
            if len(parts) == 3:
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass
    # Try D-Mon-YYYY
    try:
        from datetime import datetime as dt
        return dt.strptime(val, "%d-%b-%Y").date()
    except ValueError:
        pass
    return None


def _cell(row: list[str], idx: int | None) -> str:
    """Safe cell access by index."""
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def pull_sheets() -> dict:
    """
    Pull and aggregate financial data from the Lead-to-Cash Tracker.
    Commission values come from the actual sheet columns (Commission Closer,
    Commission Setter), never computed from offer type.
    Returns dict ready to merge into snapshot. No PII is included.
    """
    degraded = []

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

    # Resolve column indices
    idx_close_date = _col_index(headers, "close_date")
    idx_input_date = _col_index(headers, "input_date")
    idx_cash = _col_index(headers, "cash_collected")
    idx_contract = _col_index(headers, "contract_value")
    idx_net_cash = _col_index(headers, "net_cash")
    idx_comm_closer = _col_index(headers, "commission_closer")
    idx_comm_setter = _col_index(headers, "commission_setter")
    idx_offer_sold = _col_index(headers, "offer_sold")
    idx_setter_name = _col_index(headers, "setter_name")

    today = today_sydney()
    cutoff = today - timedelta(days=WINDOW_CURRENT)

    # Aggregates
    cash_collected_total = 0.0
    contract_value_total = 0.0
    net_cash_total = 0.0
    setter_commission_total = 0.0
    closer_commission_total = 0.0
    deals_won = 0
    deals_won_in_window = 0
    setter_breakdown: dict[str, float] = {}
    blank_closer_commission_count = 0
    blank_setter_commission_count = 0
    unparseable_cells: list[str] = []
    offer_breakdown: dict[str, int] = {}

    for row in rows:
        # Filter: closer Call Outcome (index 23) must be "Won"
        closer_outcome = _cell(row, CLOSER_OUTCOME_IDX).strip().lower()
        if closer_outcome != "won":
            continue

        deals_won += 1

        # Date filtering: close_date primary, input_date fallback
        close_dt = _parse_date(_cell(row, idx_close_date))
        input_dt = _parse_date(_cell(row, idx_input_date))
        effective_date = close_dt or input_dt

        in_window = effective_date is not None and effective_date >= cutoff
        if not in_window:
            continue

        deals_won_in_window += 1

        # Offer sold
        offer = _cell(row, idx_offer_sold).strip()
        if offer:
            offer_breakdown[offer] = offer_breakdown.get(offer, 0) + 1

        # Cash, contract, net cash
        cash = _parse_money(_cell(row, idx_cash))
        contract = _parse_money(_cell(row, idx_contract))
        net_cash = _parse_money(_cell(row, idx_net_cash))
        if cash is not None:
            cash_collected_total += cash
        if contract is not None:
            contract_value_total += contract
        if net_cash is not None:
            net_cash_total += net_cash

        # Closer commission — actual from sheet
        closer_raw = _cell(row, idx_comm_closer).strip()
        closer_comm = _parse_money(closer_raw)
        if closer_raw and closer_comm is None:
            unparseable_cells.append(f"Commission Closer: {closer_raw!r}")
        if closer_comm is not None:
            closer_commission_total += closer_comm
        else:
            blank_closer_commission_count += 1

        # Setter commission — actual from sheet
        setter_raw = _cell(row, idx_comm_setter).strip()
        setter_comm = _parse_money(setter_raw)
        if setter_raw and setter_comm is None:
            unparseable_cells.append(f"Commission Setter: {setter_raw!r}")
        if setter_comm is not None:
            setter_commission_total += setter_comm
        else:
            blank_setter_commission_count += 1

        # Setter breakdown by name (from the Setter column, not Notes)
        setter_name = _cell(row, idx_setter_name).strip() or "Unattributed"
        if setter_comm is not None:
            setter_breakdown[setter_name] = setter_breakdown.get(setter_name, 0.0) + setter_comm

    # Surface blank-commission Won deals as degraded
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
            "net_cash": net_cash_total,
            "closer_commission_total": closer_commission_total,
            "setter_commission_total": setter_commission_total,
            "setter_breakdown": setter_breakdown if setter_breakdown else None,
            "offer_breakdown": offer_breakdown if offer_breakdown else None,
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
