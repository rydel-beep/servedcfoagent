"""
quarterly_format.py
-------------------
TYPE-AWARE metric formatting registry (fixes D1 at root). Every metric has a declared TYPE, and one
formatter renders it consistently everywhere it appears — so a ratio can never render as dollars
(LTGP:CAC "$5"), a percent never as a count, etc. The linter reads the same registry to check that
rendered strings match declared types.

Types: currency ($1,234) · ratio (4.51x) · percent (81.5%) · count (16) · days (82d) · text.
"""
from __future__ import annotations

import math

# metric label (as it appears in tables/prose)  →  declared type
METRIC_TYPES = {
    "Contracted revenue": "currency",
    "New-deal cash collected": "currency",
    "Avg contract value": "currency",
    "Closes": "count",
    "Loaded CAC": "currency",
    "LTGP:CAC": "ratio",
    "LTV:CAC": "ratio",
    "ROAS": "ratio",
    "Ad spend": "currency",
    "Leads (cohort)": "count",
    "Leads": "count",
    "Lead->close %": "percent",
    "Close rate": "percent",
    "Xero revenue (P&L)": "currency",
    "Xero revenue": "currency",
    "Xero net profit": "currency",
    "Xero gross profit": "currency",
    "Xero operating expenses": "currency",
    "Gross margin": "percent",
    "MRR": "currency",
    "Closing MRR": "currency",
    "New MRR added": "currency",
    "Churn MRR": "currency",
    "Hires": "count",
    "Delivery hires": "count",
    "Lead volume (volume path)": "count",
    "Ad spend (spend path)": "currency",
    "Close rate (efficiency ALT)": "percent",
}


def type_of(metric: str) -> str:
    if metric in METRIC_TYPES:
        return METRIC_TYPES[metric]
    m = (metric or "").lower()
    # last-resort inference (kept narrow; ratio BEFORE currency so "LTGP:CAC" isn't caught by "cac")
    if "cac" in m and (":" in m or "ltv" in m or "ltgp" in m or "roas" in m):
        return "ratio"
    if "%" in m or "rate" in m or "margin" in m:
        return "percent"
    if any(k in m for k in ("revenue", "cash", "spend", "cac", "contract", "profit", "mrr", "value", "$")):
        return "currency"
    if any(k in m for k in ("close", "lead", "hire", "count", "deal")):
        return "count"
    return "text"


def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and (math.isinf(v) or math.isnan(v)))


def fmt_value(value, mtype: str) -> str:
    """Format a raw value per its declared type. None/inf/nan → 'n/a' (never a fake number)."""
    if _bad(value):
        return "n/a"
    try:
        if mtype == "currency":
            n = int(round(float(value)))
            return f"-${abs(n):,}" if n < 0 else f"${n:,}"
        if mtype == "ratio":
            return f"{float(value):.2f}x"
        if mtype == "percent":
            return f"{float(value):.1f}%"
        if mtype == "count":
            return f"{int(round(float(value))):,}"
        if mtype == "days":
            return f"{int(round(float(value)))}d"
        return str(value)
    except (ValueError, TypeError):
        return str(value)


def fmt_metric(metric: str, value) -> str:
    """Format `value` for the named `metric` using its declared type."""
    return fmt_value(value, type_of(metric))


def fmt_delta(metric: str, delta, pct=None) -> str:
    """Signed delta in the metric's own units + optional % change."""
    if _bad(delta):
        return "n/a"
    t = type_of(metric)
    body = fmt_value(abs(delta), t)
    sign = "-" if delta < 0 else "+"
    out = f"{sign}{body}"
    if pct is not None and not _bad(pct):
        out += f" ({pct:+.0f}%)"
    return out
