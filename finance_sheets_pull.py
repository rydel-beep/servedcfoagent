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

import requests

from config import FINANCE_SHEET_CONFIG, HTTP_TIMEOUT
from helpers import today_sydney

logger = logging.getLogger(__name__)

SKIP_MARKERS = {"end month", "churned", "x", "renewal", "end month previous month", ""}


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
