"""
config.py
---------
Central configuration for the CFO agent.
All env vars and constants live here. No other module reads os.environ directly.
"""
from __future__ import annotations

import os

# ── Stripe MCP ───────────────────────────────────────────────────────────────
STRIPE_MCP_BASE = os.getenv(
    "STRIPE_MCP_BASE",
    "https://served-stripe-mcp-production-a5a2.up.railway.app",
)

# ── GHL Sales Pipeline ──────────────────────────────────────────────────────
GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_KEY = os.getenv("GHL_SALES_API_KEY", "")
GHL_LOCATION_ID = os.getenv("GHL_SALES_LOCATION_ID", "")
GHL_SALES_PIPELINE_ID = os.getenv("GHL_SALES_PIPELINE_ID", "JJQLCr1fl7OHyrpRwSJp")

# ── Google Sheets ────────────────────────────────────────────────────────────
# Swappable config: change sheet ID, tab, or column names without touching code.
SHEET_CONFIG = {
    "sheet_id": os.getenv("SHEETS_ID", "1BrL-xhKSm1rW9RwwkWneqcrvGKQp5D-AfAkKeRUreDY"),
    "tab_name": os.getenv("SHEETS_TAB", "Lead-to-Cash Tracker"),
    "columns": {
        "input_date":         os.getenv("SHEETS_COL_INPUT_DATE", "Input Date"),
        "close_date":         os.getenv("SHEETS_COL_CLOSE_DATE", "Close Date"),
        "closer_outcome":     os.getenv("SHEETS_COL_CLOSER_OUTCOME", "Call Outcome"),
        "closer_outcome_idx": 23,  # second "Call Outcome" column (closer block)
        "offer_sold":         os.getenv("SHEETS_COL_OFFER_SOLD", "Offer Sold"),
        "cash_collected":     os.getenv("SHEETS_COL_CASH_COLLECTED", "Cash Collected"),
        "contract_value":     os.getenv("SHEETS_COL_CONTRACT_VALUE",
                                        "4 \u00b7 MONEY (update from Stripe) Contract Value"),
        "net_cash":           os.getenv("SHEETS_COL_NET_CASH", "Net Cash"),
        "commission_setter":  os.getenv("SHEETS_COL_COMMISSION_SETTER",
                                        "5 \u00b7 COMMISSIONS Commission Setter"),
        "commission_closer":  os.getenv("SHEETS_COL_COMMISSION_CLOSER", "Commission Closer"),
        "setter_name":        os.getenv("SHEETS_COL_SETTER_NAME",
                                        "2 \u00b7 SETTER FUNNEL Setter"),
        "lead_source":        os.getenv("SHEETS_COL_LEAD_SOURCE", "Lead Source"),
    },
}

# ── Finance Sheet (Salary + Recognized Revenue) ────────────────────────────
FINANCE_SHEET_CONFIG = {
    "sheet_id": os.getenv("FINANCE_SHEET_ID", "1n7OcGrOsdWb6OgFqZHzOYCcgUG8U4P3qWwy89w00CTg"),
    "salary_tab": os.getenv("FINANCE_SALARY_TAB", "SALARY"),
    "recognized_tab": os.getenv("FINANCE_RECOGNIZED_TAB", "RECOGNIZED"),
    "salary_aud_col": os.getenv("FINANCE_SALARY_AUD_COL", "SALARY (AUD)"),
    "salary_total_label": "TOTAL SALARY (AUD)",
    "payroll_variance_threshold": 1.5,  # flag when xero wages > N × baseline
}

# ── Closer Commission (Kalin) — Layer 1 per-deal, REFERENCE ONLY ────────────
# Source: Closer Comp Plan v3.2, May 2026. Layer 1 (per-deal) ONLY.
# KPI bonus / milestones / cash-bonus tiers are NOT modelled here (mix-dependent).
# PRIMARY source for closer commission is the sheet's Commission Closer column.
# This table exists for future expected-vs-actual validation, not for computing totals.
CLOSER_COMMISSION_BY_OFFER = {
    "growth_pro":    700,
    "cafe_walkins":  800,
    "scale_engine":  1500,
    "se_split":      1500,   # paid 2x750, but $1500 total per deal
    "content_scale": 1750,
    "dwy":           300,
}
# May 2026 one-month override: Growth Pro pays $900 instead of $700.
CLOSER_GP_MAY_OVERRIDE_AUD = 900
CLOSER_MAY_OVERRIDE_ACTIVE = True   # set False from June 2026 onward

# ── Xero ───────────────────────────────────────────────────────────────────
XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET", "")
XERO_REDIRECT_URI = os.getenv("XERO_REDIRECT_URI", "")

# Token file: default to /data/ (Railway Volume mount). Falls back to ./state/
# for local dev if /data/ doesn't exist.
_xero_token_env = os.getenv("XERO_TOKEN_FILE", "")
if _xero_token_env:
    XERO_TOKEN_FILE = _xero_token_env
elif os.path.isdir("/data"):
    XERO_TOKEN_FILE = "/data/xero_tokens.json"
else:
    XERO_TOKEN_FILE = "state/xero_tokens.json"

# ── Snapshot ─────────────────────────────────────────────────────────────────
SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE", "snapshot_state.json")
CFO_REFRESH_KEY = os.getenv("CFO_REFRESH_KEY", "")

# ── Timeouts ─────────────────────────────────────────────────────────────────
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "10"))

# ── Trailing windows (days) ─────────────────────────────────────────────────
WINDOW_CURRENT = 30
WINDOW_PREVIOUS = 60  # we subtract current from this to get the prior period
