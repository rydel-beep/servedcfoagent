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
    "sheet_id": os.getenv("SHEETS_ID", "1vFRjlKdpqfa4veDWW2BdpI3TQA9v7tUf9l2EBWNr4E0"),
    "tab_name": os.getenv("SHEETS_TAB", "RAW DATA SHEET"),
    "columns": {
        "input_date":         os.getenv("SHEETS_COL_INPUT_DATE", "Input date"),
        "close_date":         os.getenv("SHEETS_COL_CLOSE_DATE", "Close date"),
        "funnel_stage":       os.getenv("SHEETS_COL_FUNNEL_STAGE", "Funnel Stage"),
        "cash_collected":     os.getenv("SHEETS_COL_CASH_COLLECTED", "Cash Collected"),
        "contract_value":     os.getenv("SHEETS_COL_CONTRACT_VALUE", "Contract Value"),
        "commission_setter":  os.getenv("SHEETS_COL_COMMISSION_SETTER", "Commission Setter"),
        "commission_closer":  os.getenv("SHEETS_COL_COMMISSION_CLOSER", "Commission Closer"),
        "commission_remarks": os.getenv("SHEETS_COL_COMMISSION_REMARKS", "Commission Remarks"),
        "notes_manual":       os.getenv("SHEETS_COL_NOTES_MANUAL", "Notes (Manual)"),
        "lead_source":        os.getenv("SHEETS_COL_LEAD_SOURCE", "Lead Source"),
    },
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

# ── Snapshot ─────────────────────────────────────────────────────────────────
SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE", "snapshot_state.json")
CFO_REFRESH_KEY = os.getenv("CFO_REFRESH_KEY", "")

# ── Timeouts ─────────────────────────────────────────────────────────────────
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "10"))

# ── Trailing windows (days) ─────────────────────────────────────────────────
WINDOW_CURRENT = 30
WINDOW_PREVIOUS = 60  # we subtract current from this to get the prior period
