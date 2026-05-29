"""
xero_wages_categoriser.py
-------------------------
Categorises Xero account data using the permanent rules from CLAUDE.md.
Computes true_team_cost from verified sources.
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

# ── Categorisation rules (mirrors CLAUDE.md, authoritative) ──────────────

CATEGORISATION_RULES = {
    "people": {
        "Rydel Limjoco": {
            "category": "owner",
            "recurring_account": "Wages and Salaries",
            "bonus_account": "Wages Payable",
            "recurring_gross_weekly": 2241,
            "recurring_net_weekly": 1700,
        },
        "Kalin Long": {
            "category": "sales_commission",
            "role": "closer",
            "expected_account": "Closer Commission",
        },
        "Coby Goldner": {
            "category": "sales_commission",
            "role": "setter",
            "expected_account": "Setter Commission",
        },
        "Maran": {
            "category": "sales_commission",
            "role": "setter",
            "expected_account": "Setter Commission",
        },
        "Colby Shaw": {
            "category": "contractor_cogs",
            "role": "videographer",
            "expected_account": "Contractors NO GST",
        },
        "Rictor Kniehl Limjoco": {
            "category": "ignore_personal",
            "reason": "family loan",
        },
    },
    "use_gross_pay_for_cost": True,
    "weeks_per_month": 4.33,
    "fix_date": "2026-05-31",
    "retroactive_recoded_back_to": "2026-03-01",
}

# ── Constants derived from rules ─────────────────────────────────────────

OWNER_RECURRING_GROSS_MONTHLY = round(
    CATEGORISATION_RULES["people"]["Rydel Limjoco"]["recurring_gross_weekly"]
    * CATEGORISATION_RULES["weeks_per_month"],
    2,
)  # $9,704.13 → used as $9,704

SUPER_BASELINE_MONTHLY = 1076.0


def identify_account_bucket(transaction: dict) -> str:
    """
    Return the account bucket for a transaction using ONLY the explicit
    account_name field. Never infers from payee, amount, or description.

    This is the regression-tested function that prevents the May 2026 bug
    where Contractors NO GST entries were misidentified as Wages entries.
    """
    account_name = transaction.get("account_name", "")
    if not account_name:
        return "UNKNOWN"
    return account_name


def flag_window_straddle(window_start: date) -> dict:
    """
    Returns a warning dict if the analysis window includes dates before the
    2026-05-31 fix. Trailing windows straddling the fix produce hybrid numbers.
    """
    fix = date(2026, 5, 31)
    if window_start < fix:
        return {
            "window_straddle": True,
            "warning": (
                "Trailing window includes pre-fix dates. April 2026 Wages and "
                "Salaries contains ~$57k excess (miscoded bonus). Figures reflect "
                "hybrid pre/post-fix data — clean reads from late June 2026."
            ),
        }
    return {"window_straddle": False}


def compute_true_team_cost(salary_tab_baseline: float | None) -> dict:
    """
    Compute the monthly true team cost from verified sources.

    true_team_cost = SALARY tab baseline + owner recurring gross + super baseline

    Returns dict with breakdown and confidence flag.
    """
    owner_gross = OWNER_RECURRING_GROSS_MONTHLY
    super_base = SUPER_BASELINE_MONTHLY

    components = []
    total = 0.0
    flags = []

    # Component 1: SALARY tab (Wise-paid team)
    if salary_tab_baseline is not None and salary_tab_baseline > 0:
        total += salary_tab_baseline
        components.append({
            "name": "salary_tab_baseline",
            "value": salary_tab_baseline,
            "source": "SALARY tab (Finance Sheet)",
        })
    else:
        flags.append("salary_tab_baseline missing or zero")

    # Component 2: Owner recurring gross
    total += owner_gross
    components.append({
        "name": "owner_recurring_gross",
        "value": round(owner_gross, 2),
        "source": "Wages and Salaries (gross, $2,241/wk x 4.33)",
    })

    # Component 3: Super baseline
    total += super_base
    components.append({
        "name": "super_baseline",
        "value": super_base,
        "source": "Superannuation (recurring ~$1,076/mo)",
    })

    confidence = "high" if not flags else "medium"

    return {
        "true_team_cost_monthly": round(total, 2),
        "components": components,
        "confidence": confidence,
        "flags": flags if flags else None,
    }


def compute_owner_pay_breakdown(
    xero_wages_and_salaries: float | None,
    window_start: date | None = None,
    window_days: int = 30,
) -> dict:
    """
    Break down the Wages and Salaries figure into recurring vs excess.

    Derives expected pay runs from window length (1 per ~7 days, typically
    4 per month). Excess above expected recurring is flagged.
    """
    owner_weekly_gross = CATEGORISATION_RULES["people"]["Rydel Limjoco"][
        "recurring_gross_weekly"
    ]

    if xero_wages_and_salaries is None:
        return {
            "recurring_gross": None,
            "excess": None,
            "weeks_detected": None,
            "note": "Wages and Salaries not available",
        }

    # Detect pay runs: how many whole weekly gross amounts fit in the total.
    # This correctly handles months with 3, 4, or 5 pay runs regardless of
    # calendar days. The excess above whole weeks IS the anomaly to surface.
    weeks_in_total = int(xero_wages_and_salaries // owner_weekly_gross)
    # Cap at reasonable maximum for the window (1 per 7 days)
    max_runs = window_days // 7
    expected_runs = min(weeks_in_total, max_runs)
    expected_recurring = expected_runs * owner_weekly_gross
    excess = round(xero_wages_and_salaries - expected_recurring, 2)

    result = {
        "raw_wages_and_salaries": xero_wages_and_salaries,
        "recurring_gross": expected_recurring,
        "weeks_detected": expected_runs,
        "excess": excess,
    }

    # Flag excess
    if abs(excess) > owner_weekly_gross * 0.5:
        straddle = flag_window_straddle(window_start) if window_start else {}
        result["excess_flag"] = (
            f"Wages and Salaries ${xero_wages_and_salaries:,.0f} contains "
            f"${excess:,.0f} above {expected_runs}-week recurring "
            f"(${expected_recurring:,.0f}). "
        )
        if straddle.get("window_straddle"):
            result["excess_flag"] += "Window straddles pre-fix period — likely miscoded bonus."
        else:
            result["excess_flag"] += "Investigate — post-fix periods should be clean."

    return result


def categorise_contractors_account(
    contractors_total: float | None,
    salary_tab_baseline: float | None,
) -> dict:
    """
    Split Contractors NO GST into team payroll (Wise) vs subcontractor COGS.

    Without line-level Xero data, we use the SALARY tab as the source of truth
    for team payroll and attribute the remainder to subcontractor COGS.
    """
    if contractors_total is None:
        return {
            "team_payroll_via_wise": None,
            "subcontractor_cogs": None,
            "note": "Contractors NO GST not available",
        }

    team = salary_tab_baseline or 0
    subs = round(contractors_total - team, 2) if contractors_total > team else 0

    return {
        "total": contractors_total,
        "team_payroll_via_wise": team,
        "subcontractor_cogs": max(subs, 0),
        "note": (
            "Split uses SALARY tab as team payroll truth. Remainder attributed "
            "to subcontractor COGS. Line-level split by payee requires Xero "
            "transaction API (not available in current P&L pull)."
        ),
    }
