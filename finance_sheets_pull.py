"""
finance_sheets_pull.py
----------------------
Pull payroll baseline (SALARY tab) and recognized revenue (RECOGNIZED tab)
from the Finance Google Sheet. No PII is exposed — only aggregate totals.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta

import requests

from config import FINANCE_SHEET_CONFIG, HTTP_TIMEOUT
from helpers import today_sydney

logger = logging.getLogger(__name__)

SKIP_MARKERS = {"end month", "churned", "x", "renewal", "end month previous month", ""}

# Confirmed churned clients — still marked Active in Health tab but no longer active.
# Filter these out of client health, MRR, and trend calculations.
# Uses prefix matching (startswith) since sheet names may be longer.
CONFIRMED_CHURNED_PREFIXES = [
    "1st Edition Bar",
    "Asian Streat",
    "Nonnas",
    "Riverloop",
    "V Noodle",
    "Bunni Beez",
    "The Advocate",
]


def _is_confirmed_churned(name: str) -> bool:
    """Check if a client name matches a confirmed churned client."""
    for prefix in CONFIRMED_CHURNED_PREFIXES:
        if name.startswith(prefix) or prefix.startswith(name):
            return True
    return False

# Health tab GID for direct CSV export (more reliable than tab name)
_HEALTH_TAB_GID = 1407663952

# Health tab column indices (new June 2026 restructured layout)
_H_NAME = 0
_H_STATUS = 1
_H_PACKAGE = 2
_H_TERM = 3
_H_START = 4
_H_END = 5
_H_CONTRACT_VALUE = 6
_H_MONTHLY_REV = 7
# Col 8 is blank separator; monthly MRR columns start at col 9
_H_MONTH_START = 9


def _fetch_tab(tab: str) -> list[list[str]]:
    """Fetch a tab from the finance sheet as raw rows."""
    sid = FINANCE_SHEET_CONFIG["sheet_id"]
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab)}"
    )
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            logger.error("Finance sheet %s fetch failed (status %d)", tab, resp.status_code)
            return []
        all_rows = list(csv.reader(io.StringIO(resp.text)))
        return all_rows
    except requests.RequestException as e:
        logger.error("Finance sheet %s request failed: %s", tab, e)
        return []


def _fetch_tab_by_gid(gid: int) -> list[list[str]]:
    """Fetch a tab from the Finance sheet by GID (more reliable than tab name)."""
    sid = FINANCE_SHEET_CONFIG["sheet_id"]
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/export?format=csv&gid={gid}"
    )
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            logger.error("Finance sheet GID %d fetch failed (status %d)", gid, resp.status_code)
            return []
        return list(csv.reader(io.StringIO(resp.text)))
    except requests.RequestException as e:
        logger.error("Finance sheet GID %d request failed: %s", gid, e)
        return []


def _parse_money(val: str) -> float | None:
    """Parse '$18,891.00' or '18891' to float. Returns None if empty/invalid."""
    val = val.strip().replace("$", "").replace(",", "").replace("₱", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def pull_salary_baseline() -> dict:
    """
    Pull fixed payroll baseline from SALARY tab.
    Returns only the aggregate total — never individual names or salaries.
    """
    degraded = []
    tab = FINANCE_SHEET_CONFIG["salary_tab"]
    rows = _fetch_tab(tab)

    if not rows:
        degraded.append({"metric": "payroll_baseline", "reason": f"Failed to fetch {tab} tab"})
        return {"payroll_baseline": None, "degraded": degraded}

    # Look for the sheet's own TOTAL SALARY (AUD) cell
    total_label = FINANCE_SHEET_CONFIG["salary_total_label"]
    sheet_total = None
    for row in rows:
        for j, cell in enumerate(row):
            if total_label in cell and j + 1 < len(row):
                sheet_total = _parse_money(row[j + 1])
                break
        if sheet_total is not None:
            break

    # Also sum the AUD salary column (col index 5 based on sheet structure)
    # Headers are in row 0; salary data starts row 1
    computed_sum = 0.0
    salary_count = 0
    for row in rows[1:]:
        if len(row) < 6:
            continue
        # Col 5 is the AUD salary column (after LAST NAME, FIRST NAME, ROLE, DEPARTMENT, STATUS)
        val = _parse_money(row[5])
        if val is not None and val > 0:
            computed_sum += val
            salary_count += 1

    baseline = sheet_total if sheet_total is not None else computed_sum

    if baseline == 0:
        degraded.append({"metric": "payroll_baseline", "reason": "Could not determine payroll baseline from SALARY tab"})
        return {"payroll_baseline": None, "degraded": degraded}

    # Flag if sheet total and computed sum disagree
    if sheet_total is not None and computed_sum > 0 and abs(sheet_total - computed_sum) > 1.0:
        degraded.append({
            "metric": "payroll_baseline_mismatch",
            "reason": f"SALARY tab total ${sheet_total:,.2f} vs computed sum ${computed_sum:,.2f} — using sheet total",
        })

    return {
        "payroll_baseline": round(baseline, 2),
        "degraded": degraded,
    }


def _is_footer_row(row: list[str]) -> bool:
    """Detect footer/total rows: blank client name or starts with TOTAL."""
    client = row[0].strip() if row else ""
    return client == "" or client.upper().startswith("TOTAL")


# Maximum expected client rows before we flag suspicious row count
MAX_EXPECTED_CLIENT_ROWS = 40


def pull_recognized_revenue() -> dict:
    """
    Pull current month's recognized (accrual) revenue from RECOGNIZED tab.
    Matches the column header to the current Sydney month/year.
    Skips text markers and footer/totals rows. Includes triple-check validation.
    """
    degraded = []
    tab = FINANCE_SHEET_CONFIG["recognized_tab"]
    rows = _fetch_tab(tab)

    if not rows or len(rows) < 2:
        degraded.append({"metric": "recognized_revenue", "reason": f"Failed to fetch {tab} tab"})
        return {"recognized_revenue": None, "degraded": degraded}

    # Find column for current month (e.g. "May 2026")
    today = today_sydney()
    month_label = today.strftime("%B %Y")  # "May 2026"
    headers = rows[0]

    col_idx = None
    for j, h in enumerate(headers):
        if h.strip() == month_label:
            col_idx = j
            break

    if col_idx is None:
        degraded.append({
            "metric": "recognized_revenue",
            "reason": f"Column '{month_label}' not found in {tab} tab headers",
        })
        return {"recognized_revenue": None, "degraded": degraded}

    # Sum numeric values in that column — skip text markers AND footer rows
    client_total = 0.0
    client_count = 0
    footer_total = None

    for row in rows[1:]:
        if col_idx >= len(row):
            continue
        raw = row[col_idx].strip()
        if raw.lower() in SKIP_MARKERS:
            continue
        val = _parse_money(raw)
        if val is None:
            continue

        if _is_footer_row(row):
            # This is a footer/totals row — capture it for cross-check, don't sum
            footer_total = val
        else:
            client_total += val
            client_count += 1

    client_total = round(client_total, 2)

    # === TRIPLE-CHECK VALIDATION ===
    validation = {}

    # CHECK 1: Row-count sanity
    validation["row_count"] = client_count
    validation["row_count_ok"] = client_count <= MAX_EXPECTED_CLIENT_ROWS
    if not validation["row_count_ok"]:
        degraded.append({
            "metric": "recognized_row_count",
            "reason": (
                f"Recognized revenue summed {client_count} rows, expected ≤{MAX_EXPECTED_CLIENT_ROWS}"
                f" — possible duplicate/footer inclusion"
            ),
        })

    # CHECK 2: Footer cross-validation
    if footer_total is not None:
        validation["footer_total"] = footer_total
        tolerance = 0.02  # 2%
        if footer_total > 0:
            mismatch_pct = abs(client_total - footer_total) / footer_total
            validation["footer_match"] = mismatch_pct <= tolerance
            if not validation["footer_match"]:
                degraded.append({
                    "metric": "recognized_footer_mismatch",
                    "reason": (
                        f"Recognized revenue computed ${client_total:,.2f} but sheet footer"
                        f" says ${footer_total:,.2f} — mismatch, verify"
                    ),
                })
        else:
            validation["footer_match"] = True
    else:
        validation["footer_total"] = None
        validation["footer_match"] = None

    return {
        "recognized_revenue": client_total,
        "recognized_client_count": client_count,
        "recognized_month": month_label,
        "recognized_validation": validation,
        "degraded": degraded,
    }


def _parse_month_columns(headers: list[str]) -> list[tuple[int, str]]:
    """
    Parse month column headers from the Health tab.
    Returns list of (col_index, "M/YYYY") for each month column found.
    Headers are like "January 2026", "February 2026", etc.
    """
    import calendar
    month_name_to_num = {name.lower(): num for num, name in enumerate(calendar.month_name) if num}
    result = []
    for i, h in enumerate(headers):
        if i < _H_MONTH_START:
            continue
        h = h.strip()
        if not h:
            continue
        parts = h.split()
        if len(parts) == 2 and parts[0].lower() in month_name_to_num:
            try:
                m = month_name_to_num[parts[0].lower()]
                y = int(parts[1])
                result.append((i, f"{m}/{y}"))
            except ValueError:
                continue
    return result


def _parse_date_mmddyyyy(val: str) -> date | None:
    """Parse 'MM-DD-YYYY' or 'MM/DD/YYYY' dates from the Health tab."""
    val = val.strip()
    if not val:
        return None
    sep = "-" if "-" in val else ("/" if "/" in val else None)
    if not sep:
        return None
    try:
        parts = val.split(sep)
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass
    return None


def pull_client_health() -> dict:
    """
    Pull per-client health data from the Health tab.
    Returns:
    - Active client count, current/next month MRR, delta
    - Per-client rows with contract dates and churn risk
    - Monthly MRR totals for trend chart
    - At-risk clients (contracts expiring within 60 days)
    No PII beyond client business names (public entities).

    Sheet layout (restructured June 2026):
    Row 0 = headers, Row 1+ = data.
    Cols: Name(0), Status(1), Package(2), Term(3), Start(4), End(5),
          ContractValue(6), MonthlyRev(7), blank(8), month cols(9+).
    Status: "Active" or "Finished". Finished = churned/completed.
    """
    degraded = []
    rows = _fetch_tab_by_gid(_HEALTH_TAB_GID)

    if not rows or len(rows) < 2:
        degraded.append({"metric": "client_health", "reason": "Failed to fetch Health tab"})
        return {"client_health": None, "degraded": degraded}

    # Row 0 is headers, data starts at Row 1
    headers = rows[0]
    data_rows = rows[1:]
    today = today_sydney()

    # Dynamically parse month columns from header row
    month_cols = _parse_month_columns(headers)  # [(col_idx, "M/YYYY"), ...]
    month_labels = [label for _, label in month_cols]

    # Find current and next month column indices
    current_label = f"{today.month}/{today.year}"
    next_month_num = today.month + 1 if today.month < 12 else 1
    next_year = today.year if today.month < 12 else today.year + 1
    next_label = f"{next_month_num}/{next_year}"

    col_idx = None
    next_col_idx = None
    for ci, label in month_cols:
        if label == current_label:
            col_idx = ci
        elif label == next_label:
            next_col_idx = ci

    clients = []
    total_current = 0.0
    total_next = 0.0
    active_count = 0
    web_sub_count = 0

    # Monthly totals for trend chart
    monthly_totals = {label: 0.0 for label in month_labels}

    # Churn risk tracking
    at_risk = []

    # Renewal watch tracking — clients approaching contract renewal
    renewal_watch = []

    for row in data_rows:
        name = row[_H_NAME].strip() if len(row) > _H_NAME else ""
        if not name or name.upper().startswith("TOTAL"):
            continue

        status = row[_H_STATUS].strip() if len(row) > _H_STATUS else ""
        package = row[_H_PACKAGE].strip() if len(row) > _H_PACKAGE else ""

        # Skip non-Active rows (Finished = churned, blank = empty row)
        if status != "Active":
            continue

        # Skip confirmed churned clients (still marked Active in sheet but known churned)
        if _is_confirmed_churned(name):
            continue

        # Parse contract dates — col 4 = start, col 5 = end
        contract_start = _parse_date_mmddyyyy(row[_H_START]) if len(row) > _H_START else None
        contract_end = _parse_date_mmddyyyy(row[_H_END]) if len(row) > _H_END else None

        # Parse contract value (col 6) and monthly recognized revenue (col 7)
        contract_value = _parse_money(row[_H_CONTRACT_VALUE]) if len(row) > _H_CONTRACT_VALUE else None
        monthly_recognized_revenue = _parse_money(row[_H_MONTHLY_REV]) if len(row) > _H_MONTHLY_REV else None

        current_mrr = None
        next_mrr = None

        if col_idx is not None and col_idx < len(row):
            current_mrr = _parse_money(row[col_idx])

        if next_col_idx is not None and next_col_idx < len(row):
            next_mrr = _parse_money(row[next_col_idx])

        # Count zeros as zero, not None
        if current_mrr is None:
            current_mrr = 0.0
        if next_mrr is None:
            next_mrr = 0.0

        # Web Sub is now a package type, not a status
        if package == "Web Sub":
            web_sub_count += 1
        else:
            active_count += 1

        total_current += current_mrr
        total_next += next_mrr

        # Accumulate monthly totals for trend chart
        for ci, label in month_cols:
            if ci < len(row):
                val = _parse_money(row[ci])
                if val is not None:
                    monthly_totals[label] += val

        # Churn risk: contracts expiring within 60 days (future only).
        days_to_end = None
        risk_level = None
        if contract_end:
            days_to_end = (contract_end - today).days
            if days_to_end > 0 and days_to_end <= 30:
                risk_level = "critical"
            elif days_to_end > 0 and days_to_end <= 60:
                risk_level = "watch"

        if risk_level and current_mrr > 0:
            at_risk.append({
                "name": name,
                "contract_end": str(contract_end),
                "days_remaining": days_to_end,
                "risk_level": risk_level,
                "monthly_revenue": round(current_mrr, 2),
            })

        # Prepaid detection: $0 current MRR but contract still active with value
        prepaid_flag = None
        if current_mrr == 0 and contract_end and contract_value and contract_value > 0:
            if (contract_end - today).days > 0:
                prepaid_flag = "prepaid_active"

        client_entry = {
            "name": name,
            "status": "Web Sub" if package == "Web Sub" else "Active",
            "package": package,
            "current_mrr": round(current_mrr, 2),
            "next_mrr": round(next_mrr, 2),
        }
        if contract_value is not None:
            client_entry["contract_value"] = round(contract_value, 2)
        if monthly_recognized_revenue is not None:
            client_entry["monthly_recognized_revenue"] = round(monthly_recognized_revenue, 2)
        if prepaid_flag:
            client_entry["prepaid_flag"] = prepaid_flag
        if contract_start:
            client_entry["contract_start"] = str(contract_start)
        if contract_end:
            client_entry["contract_end"] = str(contract_end)
            if days_to_end is not None:
                client_entry["days_to_end"] = max(days_to_end, 0)

        clients.append(client_entry)

        # Renewal watch: flag clients from month 4+ of their contract
        if contract_start and contract_end:
            total_months = (contract_end - contract_start).days / 30.44
            elapsed_months = (today - contract_start).days / 30.44
            if elapsed_months >= 4 and total_months >= 4:
                renewal_watch.append({
                    "name": name,
                    "contract_start": str(contract_start),
                    "contract_end": str(contract_end),
                    "months_elapsed": round(elapsed_months, 1),
                    "total_months": round(total_months, 1),
                    "days_until_renewal": max((contract_end - today).days, 0),
                    "monthly_revenue": round(current_mrr, 2),
                    "status": "renewal_urgent" if elapsed_months >= 5 else "renewal_prep",
                })

    # Sort renewal watch by days until renewal (most urgent first)
    renewal_watch.sort(key=lambda c: c["days_until_renewal"])

    # Build trend data array (sorted chronologically)
    trend = []
    for label in month_labels:
        trend.append({
            "month": label,
            "mrr": round(monthly_totals[label], 2),
        })

    # Revenue at risk from expiring contracts
    revenue_at_risk_30d = sum(c["monthly_revenue"] for c in at_risk if c["risk_level"] in ("critical", "expired"))
    revenue_at_risk_60d = sum(c["monthly_revenue"] for c in at_risk)

    # Sort at_risk by days remaining
    at_risk.sort(key=lambda c: c["days_remaining"])

    # ── MRR Projection Analysis ───────────────────────────────────────────
    growth_rates = []
    for i in range(1, len(trend)):
        prev_mrr = trend[i - 1]["mrr"]
        curr_mrr = trend[i]["mrr"]
        if prev_mrr > 0 and curr_mrr > 0:
            rate = round((curr_mrr - prev_mrr) / prev_mrr * 100, 1)
            growth_rates.append(rate)

    # Find current month index in trend
    current_trend_idx = None
    for i, t in enumerate(trend):
        if t["month"] == current_label:
            current_trend_idx = i
            break

    # Only use growth rates up to current month (not future projections from sheet)
    historical_rates = growth_rates[:current_trend_idx] if current_trend_idx else growth_rates
    recent_rates = historical_rates[-3:] if len(historical_rates) >= 3 else historical_rates
    growth_3mo_avg = round(sum(recent_rates) / len(recent_rates), 1) if recent_rates else 0.0
    growth_latest = historical_rates[-1] if historical_rates else 0.0

    # Deceleration detection: if last 3 months are monotonically declining
    decelerating = (
        len(recent_rates) >= 3
        and recent_rates[-1] < recent_rates[-2] < recent_rates[-3]
    )

    # Use current month MRR as base (what we have NOW), not next month's
    # contractual runoff — projection models new business growth on top
    base_mrr = round(total_current, 2) if total_current > 0 else round(total_next, 2)
    churn_risk = round(revenue_at_risk_30d, 2)

    months_forward = []
    proj_base = base_mrr
    for i in range(3):
        proj_month_num = (today.month + 1 + i) % 12 or 12
        proj_year = today.year + ((today.month + 1 + i - 1) // 12)
        month_label_proj = f"{proj_month_num}/{proj_year}"

        optimistic = round(proj_base * (1 + growth_3mo_avg / 100), 2) if growth_3mo_avg else proj_base
        # Base case uses latest MoM rate (most recent signal)
        base_growth = round(proj_base * (1 + growth_latest / 100), 2) if growth_latest else proj_base
        pessimistic = round(proj_base - churn_risk, 2)

        months_forward.append({
            "month": month_label_proj,
            "base": base_growth,
            "optimistic": optimistic,
            "pessimistic": max(pessimistic, 0),
        })

        proj_base = base_growth

    # Cap sanity: flag if growth rate exceeds 50%/mo
    growth_flag = None
    if abs(growth_3mo_avg) > 50:
        growth_flag = f"3mo avg growth {growth_3mo_avg}%/mo exceeds 50% — likely a calc artifact, treat with caution"

    projection = {
        "growth_rate_mom": historical_rates,
        "growth_rate_3mo_avg": growth_3mo_avg,
        "growth_rate_latest": growth_latest,
        "decelerating": decelerating,
        "growth_flag": growth_flag,
        "next_month_base": base_mrr,
        "churn_risk_mrr": churn_risk,
        "next_month_worst": max(round(base_mrr - churn_risk, 2), 0),
        "months_forward": months_forward,
        "method": "latest MoM rate for base, 3mo avg for optimistic, churn runoff for pessimistic",
        "caveat": (
            "Growth is decelerating (latest month significantly below 3mo avg). "
            "Base projection uses most recent rate; treat optimistic with caution."
        ) if decelerating else None,
    }

    return {
        "client_health": {
            "active_count": active_count,
            "web_sub_count": web_sub_count,
            "total_clients": active_count + web_sub_count,
            "current_month": current_label,
            "current_mrr": round(total_current, 2),
            "next_month": next_label,
            "next_mrr": round(total_next, 2),
            "mrr_delta": round(total_next - total_current, 2),
            "trend": trend,
            "at_risk": at_risk,
            "renewal_watch": renewal_watch,
            "revenue_at_risk_30d": round(revenue_at_risk_30d, 2),
            "revenue_at_risk_60d": round(revenue_at_risk_60d, 2),
            "projection": projection,
            "clients": clients,
        },
        "degraded": degraded,
    }
