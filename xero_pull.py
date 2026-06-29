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


def _fetch_bank_summary(access_token: str, tenant_id: str) -> dict | None:
    """Fetch the Bank Summary report — gives each bank account's CLOSING BALANCE
    (point-in-time as of toDate). Read-only; uses accounting.reports.banksummary.read."""
    today = today_sydney()
    from datetime import date
    frm = date(today.year, today.month, 1)
    try:
        resp = requests.get(
            f"{XERO_API_BASE}/api.xro/2.0/Reports/BankSummary",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
            },
            params={"fromDate": str(frm), "toDate": str(today)},
            timeout=(5, HTTP_TIMEOUT),
        )
        if resp.status_code != 200:
            logger.error("Xero BankSummary API %d: %s", resp.status_code, resp.text[:300])
            return None
        return resp.json()
    except requests.RequestException as e:
        logger.error("Xero BankSummary request failed: %s", e)
        return None


def _extract_cash_on_hand(report: dict, markers: list[str]) -> dict:
    """Sum the CLOSING balance (last column) of the accounts whose name contains one of
    `markers` (e.g. '#2352'). Matched by NAME not number — 'notn in use' shares #2352's
    number. Returns {total, breakdown:[{marker,name,balance}], missing:[markers not found]}."""
    rep = (report.get("Reports") or [{}])[0]
    found: dict[str, dict] = {}

    def walk(rows):
        for r in rows or []:
            if r.get("Rows"):
                walk(r["Rows"])
            cells = r.get("Cells")
            if not cells or len(cells) < 2:
                continue
            name = (cells[0].get("Value") or "").strip()
            if not name:
                continue
            for mk in markers:
                if mk in name and mk not in found:
                    try:
                        bal = float(str(cells[-1].get("Value")).replace(",", "").replace("$", ""))
                    except (TypeError, ValueError):
                        bal = None
                    found[mk] = {"marker": mk, "name": name, "balance": bal}

    walk(rep.get("Rows", []))
    breakdown = [found[mk] for mk in markers if mk in found]
    missing = [mk for mk in markers if mk not in found]
    vals = [b["balance"] for b in breakdown if b["balance"] is not None]
    total = round(sum(vals), 2) if vals else None
    return {"total": total, "breakdown": breakdown, "missing": missing}


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


def _extract_wages(report_rows: list[dict]) -> float | None:
    """Sum wages + superannuation lines from the Operating Expenses section."""
    wage_keywords = {"wages and salaries", "superannuation"}
    total = 0.0
    found = False
    for section in report_rows:
        if section.get("RowType") != "Section":
            continue
        title = section.get("Title", "").strip().lower()
        if "operating expenses" not in title and "expense" not in title:
            continue
        for row in section.get("Rows", []):
            if row.get("RowType") != "Row":
                continue
            cells = row.get("Cells", [])
            if len(cells) < 2:
                continue
            label = cells[0].get("Value", "").strip().lower()
            if label in wage_keywords:
                try:
                    total += float(cells[1].get("Value", 0))
                    found = True
                except (ValueError, TypeError):
                    pass
    return total if found else None


def _extract_line_item(report_rows: list[dict], keyword: str) -> float | None:
    """Find a single line item by keyword in any expense/income section."""
    kw = keyword.lower()
    for section in report_rows:
        if section.get("RowType") != "Section":
            continue
        for row in section.get("Rows", []):
            if row.get("RowType") != "Row":
                continue
            cells = row.get("Cells", [])
            if len(cells) < 2:
                continue
            label = cells[0].get("Value", "").strip().lower()
            if label == kw:
                try:
                    return float(cells[1].get("Value", 0))
                except (ValueError, TypeError):
                    return None
    return None


def _extract_section_lines(report_rows: list[dict], section_title: str) -> list[dict]:
    """Extract all line items from a named section. Returns list of {label, amount}."""
    items = []
    for section in report_rows:
        if section.get("RowType") != "Section":
            continue
        title = section.get("Title", "").strip()
        if section_title.lower() not in title.lower():
            continue
        for row in section.get("Rows", []):
            if row.get("RowType") != "Row":
                continue
            cells = row.get("Cells", [])
            if len(cells) < 2:
                continue
            label = cells[0].get("Value", "").strip()
            try:
                amount = float(cells[1].get("Value", 0))
            except (ValueError, TypeError):
                continue
            if label:
                items.append({"label": label, "amount": amount})
    return items


def _parse_pnl(data: dict) -> dict:
    """Parse Xero P&L response into structured profit data."""
    reports = data.get("Reports", [])
    if not reports:
        return {}

    report = reports[0]
    rows = report.get("Rows", [])

    revenue = _extract_section_total(rows, "Income") or _extract_section_total(rows, "Revenue")
    cogs = _extract_section_total(rows, "Cost of Sales") or _extract_section_total(rows, "Direct Costs")
    other_income = _extract_section_total(rows, "Other Income")
    operating_expenses = _extract_section_total(rows, "Operating Expenses") or _extract_section_total(rows, "Expense")

    # Extract Xero wages line items for payroll cross-check
    xero_wages = _extract_wages(rows)

    # Extract advertising spend from Operating Expenses
    xero_ad_spend = _extract_line_item(rows, "advertising")

    gross_profit = None
    if revenue is not None and cogs is not None:
        gross_profit = revenue - abs(cogs)
    elif revenue is not None:
        gross_profit = revenue

    gross_margin_pct = None
    if gross_profit is not None and revenue and revenue != 0:
        gross_margin_pct = round(gross_profit / revenue * 100, 1)

    # net_profit = gross_profit + other_income - operating_expenses
    net_profit = None
    gp = gross_profit if gross_profit is not None else 0
    oi = other_income if other_income is not None else 0
    oe = abs(operating_expenses) if operating_expenses is not None else 0
    if gross_profit is not None and operating_expenses is not None:
        net_profit = round(gp + oi - oe, 2)
    elif gross_profit is not None:
        net_profit = round(gp + oi, 2)

    # Extract all line items for categorised burn breakdown
    cogs_lines = _extract_section_lines(rows, "Cost of Sales") or _extract_section_lines(rows, "Direct Costs")
    opex_lines = _extract_section_lines(rows, "Operating Expenses") or _extract_section_lines(rows, "Expense")

    return {
        "revenue": revenue,
        "cogs": abs(cogs) if cogs is not None else None,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "other_income": other_income,
        "operating_expenses": abs(operating_expenses) if operating_expenses is not None else None,
        "net_profit": net_profit,
        "xero_wages": xero_wages,
        "xero_ad_spend": abs(xero_ad_spend) if xero_ad_spend is not None else None,
        "cogs_line_items": cogs_lines,
        "opex_line_items": opex_lines,
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

    # Cash on hand — live CLOSING balances of the CommBank accounts (same refreshed token;
    # Xero refresh tokens are single-use, so we must NOT refresh again here).
    from config import CASH_ACCOUNT_MARKERS
    cash_block = None
    bs = _fetch_bank_summary(tokens["access_token"], tokens["tenant_id"])
    if not bs:
        degraded.append({"metric": "xero_cash_on_hand",
                         "reason": "Xero BankSummary call failed — cash on hand falls back to last-known"})
    else:
        cash = _extract_cash_on_hand(bs, CASH_ACCOUNT_MARKERS)
        if cash["missing"] or cash["total"] is None:
            degraded.append({"metric": "xero_cash_on_hand",
                             "reason": f"cash accounts missing/unreadable: {cash['missing'] or 'no balance'}"})
        cash_block = {
            "cash_on_hand": cash["total"],
            "breakdown": cash["breakdown"],
            "missing_accounts": cash["missing"],
            "as_of": str(today),
            "accounts": "CommBank #2352 + #4041 + BAS #2353 (Amex excluded)",
            "basis": "Bank Summary closing balance (point-in-time), include-BAS (Rydel 2026-06-29)",
            "source": "xero_bank_summary",
        }

    return {
        "xero": {
            **parsed,
            "cash_on_hand": cash_block,
            "period": {
                "label": f"trailing {WINDOW_CURRENT} days",
                "start": str(start),
                "end": str(today),
            },
        },
        "degraded": degraded,
    }
