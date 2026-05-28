"""
xero_pull.py
------------
Pull Profit & Loss data from Xero for the CFO snapshot.
OAuth2 token refresh with persist-first pattern: new refresh token is saved
to disk BEFORE the access token is used for any API call.
"""
from __future__ import annotations

import json
import logging
import os

import requests

from config import (
    XERO_CLIENT_ID, XERO_CLIENT_SECRET,
    XERO_TOKEN_FILE, HTTP_TIMEOUT, WINDOW_CURRENT,
)
from helpers import today_sydney

logger = logging.getLogger(__name__)

XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE = "https://api.xero.com"


def _load_tokens() -> dict | None:
    """Load saved tokens from disk. Returns None if missing/corrupt."""
    if not os.path.exists(XERO_TOKEN_FILE):
        return None
    try:
        with open(XERO_TOKEN_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load Xero tokens: %s", e)
        return None


def _save_tokens(tokens: dict) -> None:
    """Persist tokens to disk. Creates parent directory if needed."""
    os.makedirs(os.path.dirname(XERO_TOKEN_FILE) or ".", exist_ok=True)
    with open(XERO_TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    logger.info("Xero tokens persisted to %s", XERO_TOKEN_FILE)


def _refresh_access_token(stored: dict) -> dict | None:
    """
    Exchange refresh token for new access + refresh tokens.
    PERSIST-FIRST: saves new refresh token before returning.
    Returns updated token dict or None on failure.
    """
    try:
        resp = requests.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": stored["refresh_token"],
                "client_id": XERO_CLIENT_ID,
                "client_secret": XERO_CLIENT_SECRET,
            },
            timeout=(5, HTTP_TIMEOUT),
        )
        if resp.status_code != 200:
            logger.error("Xero token refresh failed %d: %s", resp.status_code, resp.text[:300])
            return None
        data = resp.json()
    except requests.RequestException as e:
        logger.error("Xero token refresh request failed: %s", e)
        return None

    updated = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "tenant_id": stored.get("tenant_id"),
    }

    # PERSIST-FIRST: save new refresh token before using access token
    _save_tokens(updated)

    return updated


def _fetch_profit_and_loss(access_token: str, tenant_id: str) -> dict | None:
    """Fetch P&L report from Xero for the trailing window."""
    today = today_sydney()
    from datetime import timedelta
    start = today - timedelta(days=WINDOW_CURRENT)

    try:
        resp = requests.get(
            f"{XERO_API_BASE}/api.xro/2.0/Reports/ProfitAndLoss",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
            },
            params={
                "fromDate": str(start),
                "toDate": str(today),
            },
            timeout=(5, HTTP_TIMEOUT),
        )
        if resp.status_code != 200:
            logger.error("Xero P&L API %d: %s", resp.status_code, resp.text[:300])
            return None
        return resp.json()
    except requests.RequestException as e:
        logger.error("Xero P&L request failed: %s", e)
        return None


def _extract_row_value(rows: list[dict], title: str) -> float | None:
    """Find a row by Title and return its total value."""
    for row in rows:
        if row.get("RowType") == "Row":
            cells = row.get("Cells", [])
            if cells and cells[0].get("Value", "").strip().lower() == title.lower():
                if len(cells) > 1:
                    try:
                        return float(cells[1].get("Value", 0))
                    except (ValueError, TypeError):
                        return None
        # Check summary rows
        if row.get("RowType") == "SummaryRow":
            cells = row.get("Cells", [])
            if cells and title.lower() in cells[0].get("Value", "").strip().lower():
                if len(cells) > 1:
                    try:
                        return float(cells[1].get("Value", 0))
                    except (ValueError, TypeError):
                        return None
    return None


def _extract_section_total(report_rows: list[dict], section_title: str) -> float | None:
    """Find a section by title and return its summary total."""
    for section in report_rows:
        if section.get("RowType") == "Section":
            title = section.get("Title", "").strip()
            if section_title.lower() in title.lower():
                rows = section.get("Rows", [])
                for row in rows:
                    if row.get("RowType") == "SummaryRow":
                        cells = row.get("Cells", [])
                        if len(cells) > 1:
                            try:
                                return float(cells[1].get("Value", 0))
                            except (ValueError, TypeError):
                                pass
    return None


def _parse_pnl(data: dict) -> dict:
    """Parse Xero P&L response into structured profit data."""
    reports = data.get("Reports", [])
    if not reports:
        return {}

    report = reports[0]
    rows = report.get("Rows", [])

    revenue = _extract_section_total(rows, "Income") or _extract_section_total(rows, "Revenue")
    cogs = _extract_section_total(rows, "Cost of Sales") or _extract_section_total(rows, "Direct Costs")
    operating_expenses = _extract_section_total(rows, "Operating Expenses") or _extract_section_total(rows, "Expense")

    gross_profit = None
    if revenue is not None and cogs is not None:
        gross_profit = revenue - abs(cogs)
    elif revenue is not None:
        gross_profit = revenue

    gross_margin_pct = None
    if gross_profit is not None and revenue and revenue != 0:
        gross_margin_pct = round(gross_profit / revenue * 100, 1)

    net_profit = None
    if gross_profit is not None and operating_expenses is not None:
        net_profit = gross_profit - abs(operating_expenses)
    elif gross_profit is not None:
        net_profit = gross_profit

    return {
        "revenue": revenue,
        "cogs": abs(cogs) if cogs is not None else None,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "operating_expenses": abs(operating_expenses) if operating_expenses is not None else None,
        "net_profit": net_profit,
    }


def pull_xero() -> dict:
    """
    Pull Xero P&L data. Returns dict ready to merge into snapshot.
    Failure → null + degraded, never blocks other sources.
    """
    degraded = []

    if not XERO_CLIENT_ID or not XERO_CLIENT_SECRET:
        degraded.append({
            "metric": "xero",
            "reason": "XERO_CLIENT_ID or XERO_CLIENT_SECRET not set",
        })
        return {"xero": None, "degraded": degraded}

    stored = _load_tokens()
    if not stored or not stored.get("refresh_token"):
        degraded.append({
            "metric": "xero",
            "reason": "No Xero refresh token — visit /xero/connect to authorize",
        })
        return {"xero": None, "degraded": degraded}

    if not stored.get("tenant_id"):
        degraded.append({
            "metric": "xero",
            "reason": "No Xero tenant_id — re-authorize via /xero/connect",
        })
        return {"xero": None, "degraded": degraded}

    # Refresh access token (persist-first)
    tokens = _refresh_access_token(stored)
    if not tokens:
        degraded.append({
            "metric": "xero",
            "reason": "Xero token refresh failed — may need to re-authorize via /xero/connect",
        })
        return {"xero": None, "degraded": degraded}

    # Fetch P&L
    pnl_data = _fetch_profit_and_loss(tokens["access_token"], tokens["tenant_id"])
    if not pnl_data:
        degraded.append({
            "metric": "xero_pnl",
            "reason": "Xero P&L API call failed",
        })
        return {"xero": None, "degraded": degraded}

    parsed = _parse_pnl(pnl_data)
    if not parsed:
        degraded.append({
            "metric": "xero_pnl",
            "reason": "Could not parse Xero P&L report — report may be empty",
        })
        return {"xero": None, "degraded": degraded}

    today = today_sydney()
    from datetime import timedelta
    start = today - timedelta(days=WINDOW_CURRENT)

    return {
        "xero": {
            **parsed,
            "period": {
                "label": f"trailing {WINDOW_CURRENT} days",
                "start": str(start),
                "end": str(today),
            },
        },
        "degraded": degraded,
    }
