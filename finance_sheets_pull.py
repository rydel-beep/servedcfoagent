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
# Updated 2026-06-02: Removed Asian Streat, 1st Edition Bar, The Advocate —
# all three have active June 2026 MRR in the Health tab (renewed/still active).
CONFIRMED_CHURNED_PREFIXES = [
    "Nonnas",
    "Riverloop",
    "V Noodle",
    "Bunni Beez",
]


def _is_confirmed_churned(name: str) -> bool:
    """Check if a client name matches a confirmed churned client."""
    for prefix in CONFIRMED_CHURNED_PREFIXES:
        if name.startswith(prefix) or prefix.startswith(name):
            return True
    return False

# Month column mapping in Health tab (col 8 = 10/2025, col 15 = 5/2026, etc.)
_HEALTH_MONTH_START_COL = 8
_HEALTH_MONTH_LABELS = [
    "10/2025", "11/2025", "12/2025",
    "1/2026", "2/2026", "3/2026", "4/2026", "5/2026",
    "6/2026", "7/2026", "8/2026", "9/2026",
]


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


def _current_month_col_index() -> int | None:
    """Return the column index in the Health tab for the current Sydney month."""
    today = today_sydney()
    label = f"{today.month}/{today.year}"
    try:
        offset = _HEALTH_MONTH_LABELS.index(label)
        return _HEALTH_MONTH_START_COL + offset
    except ValueError:
        return None


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
    - Monthly MRR totals for trend chart (Oct 2025 → Sep 2026)
    - At-risk clients (contracts expiring within 60 days)
    No PII beyond client business names (public entities).
    """
    degraded = []
    tab = FINANCE_SHEET_CONFIG.get("health_tab", "Health")
    rows = _fetch_tab(tab)

    if not rows or len(rows) < 3:
        degraded.append({"metric": "client_health", "reason": f"Failed to fetch {tab} tab"})
        return {"client_health": None, "degraded": degraded}

    # Row 0 is title, Row 1 is headers, data starts at Row 2
    data_rows = rows[2:]
    today = today_sydney()

    col_idx = _current_month_col_index()
    next_col_idx = col_idx + 1 if col_idx is not None else None

    clients = []
    total_current = 0.0
    total_next = 0.0
    active_count = 0
    web_sub_count = 0

    # Monthly totals for trend chart
    monthly_totals = {label: 0.0 for label in _HEALTH_MONTH_LABELS}

    # Churn risk tracking
    at_risk = []

    for row in data_rows:
        name = row[0].strip() if len(row) > 0 else ""
        if not name or name.upper().startswith("TOTAL"):
            continue

        status = row[1].strip() if len(row) > 1 else ""
        package = row[2].strip() if len(row) > 2 else ""

        # Skip non-client rows (footers, blanks)
        if status not in ("Active", "Web Sub"):
            continue

        # Skip confirmed churned clients (still marked Active in sheet)
        if _is_confirmed_churned(name):
            continue

        # Parse contract dates — col 5 = start, col 6 = end
        contract_start = _parse_date_mmddyyyy(row[5]) if len(row) > 5 else None
        contract_end = _parse_date_mmddyyyy(row[6]) if len(row) > 6 else None

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

        if status == "Active":
            active_count += 1
        elif status == "Web Sub":
            web_sub_count += 1

        total_current += current_mrr
        total_next += next_mrr

        # Accumulate monthly totals for trend chart
        for i, label in enumerate(_HEALTH_MONTH_LABELS):
            ci = _HEALTH_MONTH_START_COL + i
            if ci < len(row):
                val = _parse_money(row[ci])
                if val is not None:
                    monthly_totals[label] += val

        # Churn risk: contracts expiring within 60 days (future only).
        # Past end dates with current revenue = renewed/month-to-month, not churn risk.
        days_to_end = None
        risk_level = None
        if contract_end:
            days_to_end = (contract_end - today).days
            if days_to_end > 0 and days_to_end <= 30:
                risk_level = "critical"
            elif days_to_end > 0 and days_to_end <= 60:
                risk_level = "watch"
            # Past dates with revenue = renewed, skip churn risk

        if risk_level and current_mrr > 0:
            at_risk.append({
                "name": name,
                "contract_end": str(contract_end),
                "days_remaining": days_to_end,
                "risk_level": risk_level,
                "monthly_revenue": round(current_mrr, 2),
            })

        client_entry = {
            "name": name,
            "status": status,
            "package": package,
            "current_mrr": round(current_mrr, 2),
            "next_mrr": round(next_mrr, 2),
        }
        if contract_start:
            client_entry["contract_start"] = str(contract_start)
        if contract_end:
            client_entry["contract_end"] = str(contract_end)
            if days_to_end is not None:
                client_entry["days_to_end"] = max(days_to_end, 0)

        clients.append(client_entry)

    current_label = f"{today.month}/{today.year}"
    next_month = today.month + 1 if today.month < 12 else 1
    next_year = today.year if today.month < 12 else today.year + 1
    next_label = f"{next_month}/{next_year}"

    # Build trend data array (sorted chronologically)
    trend = []
    for label in _HEALTH_MONTH_LABELS:
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
    # Compute month-over-month growth rates from historical trend data
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

    # Base MRR for projection = next month from Health tab
    base_mrr = round(total_next, 2) if total_next > 0 else round(total_current, 2)
    churn_risk = round(revenue_at_risk_30d, 2)

    # 3-month forward projection
    months_forward = []
    proj_base = base_mrr
    for i in range(3):
        proj_month_num = (today.month + 1 + i) % 12 or 12
        proj_year = today.year + ((today.month + 1 + i - 1) // 12)
        month_label_proj = f"{proj_month_num}/{proj_year}"

        optimistic = round(proj_base * (1 + growth_3mo_avg / 100), 2) if growth_3mo_avg else proj_base
        pessimistic = round(proj_base - churn_risk, 2)

        months_forward.append({
            "month": month_label_proj,
            "base": round(proj_base, 2),
            "optimistic": optimistic,
            "pessimistic": max(pessimistic, 0),
        })

        proj_base = round(proj_base * (1 + growth_3mo_avg / 100), 2) if growth_3mo_avg else proj_base

    projection = {
        "growth_rate_mom": historical_rates,
        "growth_rate_3mo_avg": growth_3mo_avg,
        "next_month_base": base_mrr,
        "churn_risk_mrr": churn_risk,
        "next_month_worst": max(round(base_mrr - churn_risk, 2), 0),
        "months_forward": months_forward,
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
            "revenue_at_risk_30d": round(revenue_at_risk_30d, 2),
            "revenue_at_risk_60d": round(revenue_at_risk_60d, 2),
            "projection": projection,
            "clients": clients,
        },
        "degraded": degraded,
    }
