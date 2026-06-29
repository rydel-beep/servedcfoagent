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
# Restricted READ-ONLY Stripe key (Balance + Payouts + Balance transactions = Read).
# Lets the app read the REAL /v1/balance + /v1/payouts objects — the three money states —
# instead of the aggregate-only MCP. Absent → money-state reader degrades gracefully.
# Server-side only; NEVER commit. Accepts STRIPE_SECRET_KEY or STRIPE_RESTRICTED_KEY.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_RESTRICTED_KEY", "")
# How far back to read recent payouts for the "in transit to bank" state.
STRIPE_PAYOUT_LOOKBACK_DAYS = int(os.getenv("STRIPE_PAYOUT_LOOKBACK_DAYS", "14"))

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
    "health_tab": os.getenv("FINANCE_HEALTH_TAB", "Health"),
    "salary_total_label": "TOTAL SALARY (AUD)",
    "payroll_variance_threshold": 1.5,  # flag when xero wages > N × baseline
}

# ── Closer Commission (Kalin) — Layer 1 per-deal, REFERENCE ONLY ────────────
# Source: Closer Comp Plan v3.2, May 2026. Layer 1 (per-deal) ONLY.
# KPI bonus / milestones / cash-bonus tiers are NOT modelled here (mix-dependent).
# PRIMARY source for closer commission is the sheet's Commission Closer column.
# This table exists for future expected-vs-actual validation, not for computing totals.
CLOSER_COMMISSION_BY_OFFER = {
    "growth_pro":    750,
    "cafe_walkins":  800,
    "scale_engine":  1500,
    "se_split":      1500,   # Scale Engine split into 3x payments, $1500 total per deal
    "content_scale": 1750,
    "dwy":           300,
}
# May 2026 one-month override: Growth Pro paid $900 instead of $750. May only.
CLOSER_GP_MAY_OVERRIDE_AUD = 900
CLOSER_MAY_OVERRIDE_ACTIVE = False  # May 2026 is over; GP reverts to $750

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

# ── Cash-on-Hand Override ────────────────────────────────────────────────────
# Cash on hand is now read LIVE from Xero (Bank Summary closing balances of the three
# CommBank accounts below; Amex excluded). This figure is only a LAST-KNOWN FALLBACK,
# shown loudly-labelled when the live Xero read fails — never a silent stale number.
# Rydel-confirmed 2026-06-29 (override $172k include-BAS decision): #2352 + #4041 + BAS #2353.
CASH_ON_HAND_LAST_KNOWN = float(os.getenv("CASH_ON_HAND_LAST_KNOWN",
                                          os.getenv("CASH_ON_HAND_OVERRIDE", "171847.80")))
# Account-name markers for the cash-on-hand accounts (matched in the Bank Summary report
# by name, NOT account number — "notn in use" shares #2352's number). Rydel-confirmed:
# Business Transaction #2352 + Bus Online Saver #4041 + BAS/Tax #2353 (include-BAS). Amex excluded.
CASH_ACCOUNT_MARKERS = [m.strip() for m in
                        os.getenv("CASH_ACCOUNT_MARKERS", "#2352,#4041,#2353").split(",") if m.strip()]
CASH_STRIPE_INCOMING = float(os.getenv("CASH_STRIPE_INCOMING", "18000"))
CASH_DEPLOYABLE_BUFFER = float(os.getenv("CASH_DEPLOYABLE_BUFFER", "40000"))
CASH_TAX_RESERVED = float(os.getenv("CASH_TAX_RESERVED", "20000"))
# Date the override figures were last confirmed by Rydel (YYYY-MM-DD).
# The snapshot flags the cash position as stale when this is > 7 days old.
CASH_CONFIRMED_DATE = os.getenv("CASH_CONFIRMED_DATE", "2026-06-04")

# ── Meta Marketing API (live ad spend, read-only) ────────────────────────────
# Reuse the Ad Monitor's System User token (ads_read). Set on the CFO Railway
# service; NEVER hardcode or put in client code. Absent → meta_spend degrades to
# None and ad spend falls back to the Xero Advertising line (labelled), never a hardcode.
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")  # digits or act_<digits>
META_API_VERSION = os.getenv("META_API_VERSION", "v21.0")
# Retroactive backfill: Meta attribution firms up over ~72h. We re-fetch a daily
# series every refresh (never freeze), and mark the trailing N days provisional.
META_BACKFILL_DAYS = int(os.getenv("META_BACKFILL_DAYS", "7"))
# Windows the dashboard's selector uses; ROAS/CAC default to the 30d window.
META_SPEND_WINDOWS = [7, 30, 60, 90]
META_PRIMARY_WINDOW = 30
# Daily spend store (per-day granularity + last-fetched), survives restarts.
META_SPEND_STORE = os.getenv("META_SPEND_STORE", "state/meta_spend_daily.json")

# ── Postgres sheet-mirror (live-backed cache) ────────────────────────────────
# A faithful Postgres mirror of the source sheet tabs. Only the sync job hits the
# Sheets API; EDITH reads the mirror (ms, no rate limit). Reuses the memory Postgres.
SHEET_SYNC_INTERVAL_SECONDS = int(os.getenv("SHEET_SYNC_INTERVAL_SECONDS", "90"))
SHEET_MIRROR_ENABLED = os.getenv("SHEET_MIRROR_ENABLED", "1") not in ("0", "false", "False")
# A mirrored tab is "stale" (read falls back to live) if its last successful sync is
# older than this many seconds.
SHEET_MIRROR_MAX_STALE_SECONDS = int(os.getenv("SHEET_MIRROR_MAX_STALE_SECONDS", "600"))

# ── Manual targets / benchmarks / goalposts (Rydel-set, no live source) ──────
# Persisted on the Railway volume so a redeploy/rebuild never wipes a set target.
# Falls back to ./state for local dev. These are MANUAL inputs — Rydel is the
# source of truth; nothing here masks a live-sourced metric.
if os.path.isdir("/data"):
    MANUAL_TARGETS_STORE = os.getenv("MANUAL_TARGETS_STORE", "/data/manual_targets.json")
else:
    MANUAL_TARGETS_STORE = os.getenv("MANUAL_TARGETS_STORE", "state/manual_targets.json")

# ── Anthropic chat model ─────────────────────────────────────────────────────
# Single source of truth for the model every Claude-calling endpoint uses, so the
# string can never drift across endpoints again. Override via the CHAT_MODEL env
# var on Railway; the in-code default must always be a CURRENT, valid model ID.
# History: the old hardcoded "claude-sonnet-4-20250514" (Sonnet 4, dated ID) was
# RETIRED 2026-06-15 and began returning 404 not_found_error. Replaced with the
# documented drop-in, claude-sonnet-4-6 (Sonnet 4.6).
CHAT_MODEL = os.getenv("CHAT_MODEL", "claude-sonnet-4-6")

# ── Snapshot ─────────────────────────────────────────────────────────────────
SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE", "snapshot_state.json")
CFO_REFRESH_KEY = os.getenv("CFO_REFRESH_KEY", "")
# Picovoice (wake word) — client-side by design (WASM init); injected only
# into the authed dashboard page, never into public assets.
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")

# ── Persistent memory (Postgres) ─────────────────────────────────────────────
# Prefer the internal DATABASE_URL (Railway private network — faster, no egress);
# fall back to DATABASE_PUBLIC_URL (proxy) so it works even if only the public
# reference is wired. Absent entirely → memory degrades to in-session (no crash).
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL", "")
# New conversation if the prior one has been idle longer than this (hours).
MEMORY_IDLE_GAP_HOURS = float(os.getenv("MEMORY_IDLE_GAP_HOURS", "12"))
# Recall budget: recent turns always included + top relevance matches from history.
MEMORY_RECENT_TURNS = int(os.getenv("MEMORY_RECENT_TURNS", "12"))
MEMORY_RECALL_MATCHES = int(os.getenv("MEMORY_RECALL_MATCHES", "6"))
MEMORY_MAX_CONTEXT_CHARS = int(os.getenv("MEMORY_MAX_CONTEXT_CHARS", "8000"))

# ── Timeouts ─────────────────────────────────────────────────────────────────
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "10"))

# ── Trailing windows (days) ─────────────────────────────────────────────────
WINDOW_CURRENT = 30
WINDOW_PREVIOUS = 60  # we subtract current from this to get the prior period
