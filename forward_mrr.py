"""
forward_mrr.py
--------------
Compute forward recognized MRR from the Finance Sheet RECOGNIZED tab.
Shows the churn-adjusted ramp: what monthly recognized revenue BECOMES
as contracts expire and new signings ramp in.

Uses the per-client, per-month recognition schedule. Never fabricates
renewal assumptions — uses 0% renewal (historical: 0/12 renewed) and
lets the sales pipeline fill the gap.
"""
from __future__ import annotations

import csv
import io
import logging
import math
from datetime import datetime, date

import requests

from config import FINANCE_SHEET_CONFIG, HTTP_TIMEOUT
from helpers import today_sydney

logger = logging.getLogger(__name__)

# Known churned clients — exclude even if sheet says Active
KNOWN_CHURNED = frozenset([
    "advocate", "vietnamese mint", "gloria jean", "1st edition bar",
    "johnnies", "hanmade", "nonnas", "asian streat", "riverloop",
    "v noodle", "bunni beez", "hayat", "hippo noodle", "rising sun",
])


def _is_churned(name: str) -> bool:
    nl = name.lower()
    return any(c in nl for c in KNOWN_CHURNED)


def _parse_date(val: str) -> date | None:
    val = val.strip()
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_money(val: str) -> float | None:
    val = val.strip().replace(",", "").replace("$", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _json_safe(obj):
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _fetch_recognized_tab() -> list[list[str]]:
    """Fetch the RECOGNIZED tab (gid 1407663952) as raw rows."""
    sid = FINANCE_SHEET_CONFIG["sheet_id"]
    gid = "1407663952"
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/export?format=csv&gid={gid}"
    )
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            logger.error("RECOGNIZED tab fetch failed (status %d)", resp.status_code)
            return []
        return list(csv.reader(io.StringIO(resp.text)))
    except requests.RequestException as e:
        logger.error("RECOGNIZED tab request failed: %s", e)
        return []


def _month_col_indices(headers: list[str]) -> list[tuple[str, int]]:
    """Find month columns (e.g. 'January 2026') and return (label, index) pairs."""
    months = []
    for i, h in enumerate(headers):
        h = h.strip()
        # Match "Month YYYY" pattern
        parts = h.split()
        if len(parts) == 2:
            month_names = [
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december",
            ]
            if parts[0].lower() in month_names:
                try:
                    int(parts[1])
                    months.append((h, i))
                except ValueError:
                    pass
    return months


def build_forward_mrr() -> dict:
    """Build the forward recognized MRR model.

    Returns:
        dict with keys:
        - current_month_mrr: recognized MRR for current month
        - forward_months: list of {month, recognized_mrr, clients, expiring, delta}
        - mtm_floor: month-to-month client revenue (the floor)
        - clients: per-client detail with contract lifecycle
        - expiry_schedule: contracts expiring by month
        - renewal_rate_historical: 0% (0/12)
        - degraded: list of data quality issues
    """
    degraded = []
    all_rows = _fetch_recognized_tab()
    if not all_rows or len(all_rows) < 2:
        degraded.append({
            "metric": "forward_mrr",
            "reason": "Failed to fetch RECOGNIZED tab from Finance Sheet",
        })
        return {"forward_mrr": None, "degraded": degraded}

    headers = all_rows[0]
    data_rows = [r for r in all_rows[1:] if r[0].strip()]
    month_cols = _month_col_indices(headers)

    today = today_sydney()
    current_month_label = f"{today.strftime('%B')} {today.year}"

    # Parse all active clients
    clients = []
    mtm_clients = []
    expiry_schedule: dict[str, list] = {}

    for row in data_rows:
        name = row[0].strip()
        status = row[1].strip()
        if status == "Finished" or _is_churned(name):
            continue
        if status != "Active":
            continue

        pkg = row[2].strip()
        term = row[3].strip()
        start_str = row[4].strip()
        end_str = row[5].strip()
        contract_val = _parse_money(row[6]) if len(row) > 6 else None
        monthly_val = _parse_money(row[7]) if len(row) > 7 else None

        if monthly_val is None or monthly_val <= 0:
            continue

        start_dt = _parse_date(start_str)
        end_dt = _parse_date(end_str) if end_str and end_str != "-" else None

        client = {
            "name": name,
            "package": pkg,
            "term": term,
            "monthly_value": round(monthly_val, 2),
            "contract_value": round(contract_val, 2) if contract_val else None,
            "start_date": start_dt.isoformat() if start_dt else None,
            "end_date": end_dt.isoformat() if end_dt else None,
        }

        if term == "Month to Month" or (not end_dt and end_str in ("-", "")):
            client["type"] = "mtm"
            mtm_clients.append(client)
        else:
            client["type"] = "fixed"
            if end_dt:
                month_key = f"{end_dt.year}-{end_dt.month:02d}"
                if month_key not in expiry_schedule:
                    expiry_schedule[month_key] = []
                expiry_schedule[month_key].append({
                    "name": name,
                    "monthly_value": round(monthly_val, 2),
                    "end_date": end_dt.isoformat(),
                })

        clients.append(client)

    # Build per-month forward MRR from the sheet's recognition columns
    forward_months = []
    for month_label, col_idx in month_cols:
        month_mrr = 0.0
        month_clients = 0
        for row in data_rows:
            name = row[0].strip()
            status = row[1].strip()
            if status != "Active" or _is_churned(name):
                continue
            cell = row[col_idx].strip() if col_idx < len(row) else ""
            val = _parse_money(cell)
            if val is not None and val > 0:
                month_mrr += val
                month_clients += 1

        # Only include current and future months
        # Parse month label to date for comparison
        month_names = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12,
        }
        parts = month_label.split()
        if len(parts) == 2:
            m_num = month_names.get(parts[0])
            m_year = int(parts[1])
            if m_num and (m_year > today.year or (m_year == today.year and m_num >= today.month)):
                forward_months.append({
                    "month": month_label,
                    "recognized_mrr": round(month_mrr, 2),
                    "clients": month_clients,
                })

    # Add deltas
    for i, fm in enumerate(forward_months):
        if i == 0:
            fm["delta"] = 0
            fm["delta_pct"] = 0
        else:
            prev = forward_months[i - 1]["recognized_mrr"]
            fm["delta"] = round(fm["recognized_mrr"] - prev, 2)
            fm["delta_pct"] = (
                round(fm["delta"] / prev * 100, 1) if prev > 0 else None
            )

    # MTM floor
    mtm_floor = sum(c["monthly_value"] for c in mtm_clients)

    # Current month MRR
    current_mrr = None
    for fm in forward_months:
        if fm["month"] == current_month_label:
            current_mrr = fm["recognized_mrr"]
            break

    # Expiry schedule sorted
    sorted_expiry = []
    for month_key in sorted(expiry_schedule.keys()):
        contracts = expiry_schedule[month_key]
        total = sum(c["monthly_value"] for c in contracts)
        sorted_expiry.append({
            "month": month_key,
            "contracts_expiring": len(contracts),
            "mrr_at_risk": round(total, 2),
            "clients": contracts,
        })

    # Contribution margin per client (avg)
    active_count = len(clients)
    avg_monthly_per_client = (
        round(sum(c["monthly_value"] for c in clients) / active_count, 2)
        if active_count > 0 else None
    )

    result = {
        "current_month": current_month_label,
        "current_recognized_mrr": current_mrr,
        "forward_months": forward_months,
        "mtm_floor": round(mtm_floor, 2),
        "mtm_clients": len(mtm_clients),
        "active_clients": active_count,
        "avg_monthly_per_client": avg_monthly_per_client,
        "expiry_schedule": sorted_expiry,
        "renewal_rate_historical": {
            "rate": 0.0,
            "renewed": 0,
            "churned": 12,
            "note": "0/12 finished clients have re-signed historically",
        },
        "clients": clients,
        "degraded": degraded,
    }

    return _json_safe(result)
