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
from finance_sheets_pull import pull_salary_baseline, pull_recognized_revenue
from sales_analytics_pull import pull_sales_analytics

logger = logging.getLogger(__name__)


def build_snapshot() -> dict:
    """Pull all sources in parallel and assemble a single snapshot dict."""
    ts = now_sydney()

    with ThreadPoolExecutor(max_workers=7) as pool:
        f_stripe = pool.submit(pull_stripe)
        f_ghl = pool.submit(pull_ghl)
        f_sheets = pool.submit(pull_sheets)
        f_xero = pool.submit(pull_xero)
        f_salary = pool.submit(pull_salary_baseline)
        f_recognized = pool.submit(pull_recognized_revenue)
        f_sales = pool.submit(pull_sales_analytics)

    stripe_result = f_stripe.result()
    ghl_result = f_ghl.result()
    sheets_result = f_sheets.result()
    xero_result = f_xero.result()
    salary_result = f_salary.result()
    recognized_result = f_recognized.result()
    sales_result = f_sales.result()

    # Merge degraded lists
    degraded = (
        stripe_result.get("degraded", [])
        + ghl_result.get("degraded", [])
        + sheets_result.get("degraded", [])
        + xero_result.get("degraded", [])
        + salary_result.get("degraded", [])
        + recognized_result.get("degraded", [])
        + sales_result.get("degraded", [])
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

    # Build payroll cross-check
    payroll_baseline = salary_result.get("payroll_baseline")
    payroll = None
    if xero_data and xero_data.get("xero_wages") is not None:
        xero_wages = xero_data["xero_wages"]
        payroll = {
            "xero_wages_actual": xero_wages,
            "fixed_baseline_monthly": payroll_baseline,
        }
        if payroll_baseline and payroll_baseline > 0:
            variance = round(xero_wages - payroll_baseline, 2)
            variance_ratio = round(xero_wages / payroll_baseline, 1)
            payroll["variance"] = variance
            payroll["variance_pct"] = variance_ratio
            threshold = FINANCE_SHEET_CONFIG["payroll_variance_threshold"]
            if variance_ratio > threshold:
                payroll["flag"] = (
                    f"Xero wages ${xero_wages:,.2f} is {variance_ratio}x the "
                    f"fixed-payroll baseline ${payroll_baseline:,.2f} — investigate "
                    f"(possible multi-period posting, commissions miscoded to wages, "
                    f"or catch-up batch)"
                )
                degraded.append({
                    "metric": "payroll_variance",
                    "reason": (
                        f"Xero wages ${xero_wages:,.2f} vs baseline "
                        f"${payroll_baseline:,.2f} ({variance_ratio}x) — verify in Xero ledger"
                    ),
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
        "costs": costs,
        "profit": profit,
        "revenue_views": revenue_views,
        "degraded": degraded if degraded else [],
        "ok": len(degraded) == 0,
    }

    _persist(snapshot)
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
