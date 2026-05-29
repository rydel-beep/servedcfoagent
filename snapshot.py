"""
snapshot.py
-----------
Orchestrates data pulls and assembles the CFO snapshot.
Persists the last good snapshot to disk so a Railway restart preserves it.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from config import SNAPSHOT_FILE, FINANCE_SHEET_CONFIG
from helpers import now_sydney
from stripe_pull import pull_stripe
from ghl_pull import pull_ghl
from sheets_pull import pull_sheets
from xero_pull import pull_xero
from finance_sheets_pull import pull_salary_baseline, pull_recognized_revenue, pull_client_health
from sales_analytics_pull import pull_sales_analytics
from hormozi_metrics import compute_all as compute_hormozi
from verdicts import build_verdicts
from xero_wages_categoriser import (
    compute_true_team_cost,
    compute_owner_pay_breakdown,
    categorise_contractors_account,
    OWNER_RECURRING_GROSS_MONTHLY,
)
import history_store

logger = logging.getLogger(__name__)


def build_snapshot() -> dict:
    """Pull all sources in parallel and assemble a single snapshot dict."""
    ts = now_sydney()

    with ThreadPoolExecutor(max_workers=8) as pool:
        f_stripe = pool.submit(pull_stripe)
        f_ghl = pool.submit(pull_ghl)
        f_sheets = pool.submit(pull_sheets)
        f_xero = pool.submit(pull_xero)
        f_salary = pool.submit(pull_salary_baseline)
        f_recognized = pool.submit(pull_recognized_revenue)
        f_sales = pool.submit(pull_sales_analytics)
        f_health = pool.submit(pull_client_health)

    stripe_result = f_stripe.result()
    ghl_result = f_ghl.result()
    sheets_result = f_sheets.result()
    xero_result = f_xero.result()
    salary_result = f_salary.result()
    recognized_result = f_recognized.result()
    sales_result = f_sales.result()
    health_result = f_health.result()

    # Merge degraded lists
    degraded = (
        stripe_result.get("degraded", [])
        + ghl_result.get("degraded", [])
        + sheets_result.get("degraded", [])
        + xero_result.get("degraded", [])
        + salary_result.get("degraded", [])
        + recognized_result.get("degraded", [])
        + sales_result.get("degraded", [])
        + health_result.get("degraded", [])
    )

    # Build costs block from actual sheet commission values
    sheets_data = sheets_result.get("sheets")
    costs = None
    if sheets_data:
        costs = {
            "closer_commission": sheets_data.get("closer_commission_total"),
            "setter_commission": sheets_data.get("setter_commission_total"),
            "source": "sheet actuals (Commission Closer #20, Commission Setter #19)",
        }

    # Build profit block from Xero P&L data
    xero_data = xero_result.get("xero")
    profit = None
    if xero_data:
        profit = {
            "revenue": xero_data.get("revenue"),
            "cogs": xero_data.get("cogs"),
            "gross_profit": xero_data.get("gross_profit"),
            "gross_margin_pct": xero_data.get("gross_margin_pct"),
            "other_income": xero_data.get("other_income"),
            "operating_expenses": xero_data.get("operating_expenses"),
            "net_profit": xero_data.get("net_profit"),
            "period": xero_data.get("period"),
            "source": "Xero P&L report",
        }

    # Build categorised payroll block using true_team_cost
    payroll_baseline = salary_result.get("payroll_baseline")
    true_team = compute_true_team_cost(salary_tab_baseline=payroll_baseline)
    true_team_cost = true_team["true_team_cost_monthly"]

    # Owner pay breakdown (compares Xero Wages and Salaries against expected)
    xero_wages = xero_data.get("xero_wages") if xero_data else None
    owner_breakdown = compute_owner_pay_breakdown(xero_wages)

    # Contractors split (team payroll vs subcontractor COGS)
    contractors_total = xero_data.get("xero_contractors") if xero_data else None
    contractors_split = categorise_contractors_account(contractors_total, payroll_baseline)

    payroll = {
        "true_team_cost": true_team,
        "owner_pay_breakdown": owner_breakdown,
        "contractors_split": contractors_split,
    }

    # Flag excess in owner pay as a data-quality issue
    if owner_breakdown.get("excess_flag"):
        degraded.append({
            "metric": "owner_pay_excess",
            "reason": owner_breakdown["excess_flag"],
        })

    if profit:
        profit["payroll"] = payroll

    # Build revenue views cross-reference
    stripe_data = stripe_result.get("stripe")
    stripe_rev = None
    if stripe_data and stripe_data.get("revenue"):
        stripe_rev = stripe_data["revenue"]["current"].get("total_aud")

    recognized = recognized_result.get("recognized_revenue")
    recognized_validation = recognized_result.get("recognized_validation", {})

    # CHECK 3: Cross-source range check (recognized vs Xero revenue)
    xero_rev = xero_data.get("revenue") if xero_data else None
    if recognized is not None and xero_rev is not None and xero_rev > 0:
        ratio = round(recognized / xero_rev, 2)
        recognized_validation["cross_source_ratio"] = ratio
        recognized_validation["range_ok"] = 0.5 <= ratio <= 1.8
        if not recognized_validation["range_ok"]:
            degraded.append({
                "metric": "recognized_range_check",
                "reason": (
                    f"Recognized revenue ${recognized:,.2f} is {ratio}x Xero revenue"
                    f" ${xero_rev:,.2f} — outside expected range (0.5x–1.8x), verify"
                ),
            })
    else:
        recognized_validation["cross_source_ratio"] = None
        recognized_validation["range_ok"] = None

    revenue_views = {
        "stripe_cash_trailing_30d": stripe_rev,
        "xero_pl_period": xero_rev,
        "recognized_current_month": recognized,
        "recognized_month": recognized_result.get("recognized_month"),
        "recognized_client_count": recognized_result.get("recognized_client_count"),
        "recognized_validation": recognized_validation,
    }

    snapshot = {
        "generated_at": ts.isoformat(),
        "timezone": "Australia/Sydney",
        "currency": "AUD",
        "stripe": stripe_data,
        "ghl": ghl_result.get("ghl"),
        "sheets": sheets_data,
        "xero": xero_data,
        "sales": sales_result.get("sales"),
        "client_health": health_result.get("client_health"),
        "costs": costs,
        "profit": profit,
        "revenue_views": revenue_views,
        "degraded": degraded if degraded else [],
        "ok": len(degraded) == 0,
    }

    # Hormozi metrics + verdict layer (computed AFTER snapshot assembled)
    hormozi = compute_hormozi(snapshot, true_team_cost=true_team_cost)
    verdicts = build_verdicts(snapshot, hormozi)
    snapshot["hormozi"] = hormozi
    snapshot["verdicts"] = verdicts

    _persist(snapshot)

    # History logging — non-critical, must never fail the snapshot
    try:
        history_store.append(snapshot)
    except Exception as e:
        logger.error("History store write failed (non-critical): %s", e)

    return snapshot


def _persist(snapshot: dict) -> None:
    """Write snapshot to disk so it survives process restarts."""
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(snapshot, f, indent=2)
        logger.info("Snapshot persisted to %s", SNAPSHOT_FILE)
    except OSError as e:
        logger.error("Failed to persist snapshot: %s", e)


def load_persisted() -> dict | None:
    """Load the last persisted snapshot from disk, if it exists."""
    if not os.path.exists(SNAPSHOT_FILE):
        return None
    try:
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load persisted snapshot: %s", e)
        return None
