"""
team_roster.py
--------------
Read-only mirror of the SALARY sheet roster. Returns per-person data
grouped by department for the editable scratch-modeling layer in the
dashboard. NEVER writes to the sheet.

The dashboard's scratch layer (add/remove/edit) lives in JS session state
and feeds into burn/runway/hiring analysis. "Reset to actual" restores
this sheet truth.
"""
from __future__ import annotations

import logging

from finance_sheets_pull import _fetch_tab, _parse_money
from config import FINANCE_SHEET_CONFIG

logger = logging.getLogger(__name__)

# Default AUD:PHP fixed rate (Rydel-set, not live API)
DEFAULT_FX_RATE = 44.0

# Person-level department overrides — the sheet has everyone C-LEVEL tagged
# but Rydel confirmed these belong in different functions.
_DEPT_OVERRIDE = {
    "tristan borebor": "TECH",
    "ryan piolo dulay": "ADMIN",
    "kc garces": "MEDIA",
}

# Column indices in the SALARY tab
_COL_LAST = 0
_COL_FIRST = 1
_COL_ROLE = 2
_COL_DEPT = 3
_COL_STATUS = 4
_COL_AUD = 5
_COL_PHP = 6


def pull_team_roster() -> dict:
    """Pull the full team roster from the SALARY sheet tab.

    Returns
    -------
    dict with:
        roster: list of per-person dicts
        by_department: grouped totals
        totals: aggregate AUD/PHP
        degraded: list of data quality issues
    """
    degraded = []
    tab = FINANCE_SHEET_CONFIG["salary_tab"]
    rows = _fetch_tab(tab)

    if not rows or len(rows) < 2:
        degraded.append({"metric": "team_roster", "reason": f"Failed to fetch {tab} tab"})
        return {"roster": None, "degraded": degraded}

    roster = []
    for row in rows[1:]:
        if len(row) < 6:
            continue
        last_name = row[_COL_LAST].strip()
        first_name = row[_COL_FIRST].strip()
        if not last_name and not first_name:
            continue
        # Skip footer/total rows
        if last_name.upper().startswith("TOTAL") or first_name.upper().startswith("TOTAL"):
            continue

        salary_aud = _parse_money(row[_COL_AUD]) if len(row) > _COL_AUD else None
        salary_php = _parse_money(row[_COL_PHP]) if len(row) > _COL_PHP else None

        # Apply department override if exists
        sheet_dept = row[_COL_DEPT].strip() if len(row) > _COL_DEPT else ""
        full_name_key = f"{first_name} {last_name}".lower()
        dept = _DEPT_OVERRIDE.get(full_name_key, sheet_dept)

        roster.append({
            "last_name": last_name,
            "first_name": first_name,
            "role": row[_COL_ROLE].strip() if len(row) > _COL_ROLE else "",
            "department": dept,
            "sheet_department": sheet_dept,
            "status": row[_COL_STATUS].strip() if len(row) > _COL_STATUS else "",
            "salary_aud": salary_aud or 0,
            "salary_php": salary_php or 0,
        })

    if not roster:
        degraded.append({"metric": "team_roster", "reason": "No team members found in SALARY tab"})
        return {"roster": None, "degraded": degraded}

    # Group by department
    by_department = {}
    total_aud = 0.0
    total_php = 0.0
    owner_aud = 0.0

    for person in roster:
        dept = person["department"] or "UNKNOWN"
        if dept not in by_department:
            by_department[dept] = {"headcount": 0, "total_aud": 0.0, "total_php": 0.0}
        by_department[dept]["headcount"] += 1
        by_department[dept]["total_aud"] += person["salary_aud"]
        by_department[dept]["total_php"] += person["salary_php"]

        total_aud += person["salary_aud"]
        total_php += person["salary_php"]

        # Identify owner for separate tracking
        if person["role"].lower() == "owner":
            owner_aud = person["salary_aud"]

    # Round department totals
    for dept in by_department:
        by_department[dept]["total_aud"] = round(by_department[dept]["total_aud"], 2)
        by_department[dept]["total_php"] = round(by_department[dept]["total_php"], 2)

    team_excl_owner = round(total_aud - owner_aud, 2)

    return {
        "roster": roster,
        "by_department": by_department,
        "totals": {
            "headcount": len(roster),
            "total_aud": round(total_aud, 2),
            "total_php": round(total_php, 2),
            "owner_aud": round(owner_aud, 2),
            "team_excl_owner_aud": team_excl_owner,
            "sheet_implied_rate": round(total_php / total_aud, 1) if total_aud > 0 else None,
        },
        "degraded": degraded,
    }
