"""
team_model.py
-------------
Builds the team structure and cost model from the SALARY tab.
Exposes per-role costs by department/function for hiring analysis.

PRIVACY: per-role salary detail is CFO/owner-view only.
Never expose individual names or salaries in sales-team exports.
"""
from __future__ import annotations

import csv
import io
import logging

import requests

from config import FINANCE_SHEET_CONFIG, HTTP_TIMEOUT
from finance_sheets_pull import _fetch_tab, _parse_money
from xero_wages_categoriser import OWNER_RECURRING_GROSS_MONTHLY

logger = logging.getLogger(__name__)

# Map departments to functional categories
_DEPT_TO_FUNCTION = {
    "C-LEVEL": "leadership",
    "PAID ADS": "delivery_ads",
    "PR": "delivery_pr",
    "MEDIA": "delivery_content",
    "TECH": "delivery_tech",
    "SMM": "delivery_smm",
}

# Per-person overrides where department tag is wrong (Rydel-confirmed 2026-06-04)
_PERSON_FUNCTION_OVERRIDE = {
    "tristan borebor": "delivery_tech",
    "ryan piolo dulay": "admin",
    # Miguel Delmendo → leadership (matches C-LEVEL, no override needed)
    # KC Garces → leadership (matches C-LEVEL, no override needed)
    # Rydel Limjoco → leadership (matches C-LEVEL, no override needed)
}


def build_team_model() -> dict:
    """Build the team structure from the SALARY tab.

    Returns per-role costs grouped by function, with aggregate totals.
    No individual names — only role titles and departments.
    """
    tab = FINANCE_SHEET_CONFIG["salary_tab"]
    rows = _fetch_tab(tab)

    if not rows or len(rows) < 2:
        return {
            "available": False,
            "error": "SALARY tab not accessible",
            "roles": [],
            "by_function": {},
            "total_team_salary": 0,
            "total_with_owner": 0,
        }

    # Parse roles (skip header row 0)
    roles = []
    for row in rows[1:]:
        if len(row) < 6:
            continue
        role = (row[2] or "").strip()
        dept = (row[3] or "").strip()
        status = (row[4] or "").strip()
        salary = _parse_money(row[5])

        if not role or salary is None or salary <= 0:
            continue
        if status.lower() in ("inactive", "terminated"):
            continue

        # Check person-level override first (Rydel-confirmed assignments)
        first = (row[1] or "").strip()
        last = (row[0] or "").strip()
        full_name = f"{first} {last}".lower().strip()
        function = _PERSON_FUNCTION_OVERRIDE.get(full_name, _DEPT_TO_FUNCTION.get(dept, "other"))

        roles.append({
            "role": role,
            "department": dept,
            "function": function,
            "monthly_cost": round(salary, 2),
        })

    # Group by function
    by_function: dict[str, dict] = {}
    for r in roles:
        fn = r["function"]
        if fn not in by_function:
            by_function[fn] = {"roles": [], "total": 0, "headcount": 0}
        by_function[fn]["roles"].append({
            "role": r["role"],
            "monthly_cost": r["monthly_cost"],
        })
        by_function[fn]["total"] += r["monthly_cost"]
        by_function[fn]["headcount"] += 1

    # Round function totals
    for fn in by_function:
        by_function[fn]["total"] = round(by_function[fn]["total"], 2)

    total_team_salary = round(sum(r["monthly_cost"] for r in roles), 2)

    # Total including owner gross pay (from xero_wages_categoriser)
    total_with_owner = round(total_team_salary + OWNER_RECURRING_GROSS_MONTHLY, 2)

    # Identify single-points-of-failure (functions with only 1 person)
    spof = [
        fn for fn, data in by_function.items()
        if data["headcount"] == 1 and fn != "leadership"
    ]

    return {
        "available": True,
        "roles": roles,
        "by_function": by_function,
        "total_team_salary": total_team_salary,
        "owner_gross_monthly": OWNER_RECURRING_GROSS_MONTHLY,
        "total_with_owner": total_with_owner,
        "headcount": len(roles),
        "single_points_of_failure": spof,
    }
