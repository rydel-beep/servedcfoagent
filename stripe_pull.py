"""
stripe_pull.py
--------------
Pull metrics from the Stripe MCP service (read-only).
POST /call  {"tool": "<name>", "arguments": {...}}
"""
from __future__ import annotations

import logging
import requests

from config import STRIPE_MCP_BASE, HTTP_TIMEOUT, WINDOW_CURRENT, WINDOW_PREVIOUS
from helpers import today_sydney

logger = logging.getLogger(__name__)


def _call_tool(tool: str, arguments: dict | None = None) -> dict | None:
    """Call a single Stripe MCP tool. Returns the result dict or None on failure."""
    try:
        resp = requests.post(
            f"{STRIPE_MCP_BASE}/call",
            json={"tool": tool, "arguments": arguments or {}},
            timeout=(5, HTTP_TIMEOUT),  # (connect, read)
        )
        if resp.status_code != 200:
            logger.error("Stripe MCP %s returned %d: %s", tool, resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        if "error" in data and "result" not in data:
            logger.error("Stripe MCP %s error: %s", tool, data["error"])
            return None
        return data.get("result", data)
    except requests.RequestException as e:
        logger.error("Stripe MCP %s request failed: %s", tool, e)
        return None


def pull_stripe() -> dict:
    """
    Pull all Stripe metrics. Returns a dict ready to merge into the snapshot.
    Any failed source sets the value to None and adds a degraded entry.
    """
    degraded = []
    today = today_sydney()

    # ── MRR ──────────────────────────────────────────────────────────────
    mrr_data = _call_tool("get_stripe_mrr")
    if mrr_data and mrr_data.get("mrr") is not None:
        mrr = mrr_data["mrr"]
    else:
        mrr = None
        degraded.append({"metric": "mrr", "reason": "Stripe MCP get_stripe_mrr failed or returned null"})

    # ── Revenue (current window) ─────────────────────────────────────────
    rev_current = _call_tool("get_stripe_revenue", {"days": WINDOW_CURRENT})
    rev_combined = _call_tool("get_stripe_revenue", {"days": WINDOW_PREVIOUS})

    if rev_current and rev_current.get("total_aud") is not None:
        revenue_current = rev_current["total_aud"]
        txn_count_current = rev_current.get("transaction_count")
    else:
        revenue_current = None
        txn_count_current = None
        degraded.append({"metric": "revenue_current", "reason": "Stripe MCP get_stripe_revenue failed"})

    # ── Revenue (previous window = combined - current) ───────────────────
    if (
        rev_combined
        and rev_combined.get("total_aud") is not None
        and revenue_current is not None
    ):
        revenue_previous = rev_combined["total_aud"] - revenue_current
    else:
        revenue_previous = None
        if revenue_current is not None:
            degraded.append({"metric": "revenue_previous", "reason": "Stripe MCP 60-day revenue call failed"})

    # ── Subscriptions ────────────────────────────────────────────────────
    subs_data = _call_tool("get_stripe_subscriptions")
    if subs_data:
        subscriptions = {
            "active": subs_data.get("active"),
            "cancelled": subs_data.get("cancelled"),
            "past_due": subs_data.get("past_due"),
            "trialing": subs_data.get("trialing"),
        }
    else:
        subscriptions = None
        degraded.append({"metric": "subscriptions", "reason": "Stripe MCP get_stripe_subscriptions failed"})

    # ── Customer count (known degraded — proxy only) ─────────────────────
    cust_data = _call_tool("get_stripe_customer_count", {"days": WINDOW_CURRENT})
    cust_total = None
    cust_new = None
    if cust_data:
        raw_total = cust_data.get("total")
        raw_new = cust_data.get("new_last_n_days")
        if raw_total not in (None, "unknown"):
            cust_total = raw_total
        if raw_new not in (None, "unknown"):
            cust_new = raw_new

    proxy_active = subscriptions["active"] if subscriptions else None
    customer_count = {
        "value": cust_total,
        "new_trailing_30d": cust_new,
        "proxy_active_subscriptions": proxy_active,
        "note": "true count unavailable from Stripe MCP — proxy only"
        if cust_total is None
        else None,
    }
    if cust_total is None:
        degraded.append({"metric": "customer_count", "reason": "Stripe MCP returns 'unknown' — using active subscriptions as proxy"})

    # ── Failed charges ───────────────────────────────────────────────────
    fail_data = _call_tool("get_stripe_failed_charges", {"days": WINDOW_CURRENT})
    if fail_data and fail_data.get("failed_count") is not None:
        failed_charges_count = fail_data["failed_count"]
    else:
        failed_charges_count = None
        degraded.append({"metric": "failed_charges", "reason": "Stripe MCP get_stripe_failed_charges failed"})

    # ── Payouts ──────────────────────────────────────────────────────────
    payout_data = _call_tool("get_stripe_payouts", {"days": WINDOW_CURRENT})
    if payout_data and payout_data.get("total_paid_out") is not None:
        payouts = {
            "total_paid_out": payout_data["total_paid_out"],
            "payout_count": payout_data.get("payout_count"),
        }
    else:
        payouts = None
        degraded.append({"metric": "payouts", "reason": "Stripe MCP get_stripe_payouts failed"})

    # ── Compute period labels ────────────────────────────────────────────
    from datetime import timedelta
    current_start = today - timedelta(days=WINDOW_CURRENT)
    previous_start = today - timedelta(days=WINDOW_PREVIOUS)

    return {
        "stripe": {
            "mrr": mrr,
            "revenue": {
                "current": {
                    "total_aud": revenue_current,
                    "transaction_count": txn_count_current,
                    "period": {
                        "label": f"trailing {WINDOW_CURRENT} days",
                        "start": str(current_start),
                        "end": str(today),
                    },
                },
                "previous": {
                    "total_aud": revenue_previous,
                    "period": {
                        "label": f"trailing {WINDOW_CURRENT} days (prior period)",
                        "start": str(previous_start),
                        "end": str(current_start),
                    },
                },
            },
            "subscriptions": subscriptions,
            "customer_count": customer_count,
            "failed_charges_count": failed_charges_count,
            "payouts": payouts,
        },
        "degraded": degraded,
    }
