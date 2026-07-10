"""
stripe_reconcile.py
-------------------
Stripe ↔ Lead-to-Cash tracker reconciliation.

Purpose: catch the exact gap that hid Lucas/Cally — a client who PAID via Stripe
but whose tracker row isn't logged (or whose money columns are blank). It flags
"paid in Stripe, no matching tracker entry" so EDITH proactively surfaces it
instead of silently missing the client.

Matching runs SERVER-SIDE only, here, because it needs the tracker's email/name
columns (cols 3/4/5) which are PII and must NEVER reach the snapshot. The output
is name/amount/date level only — no emails leave this module (asserted before return).

ACTIVATED 2026-07-09: per-charge data now comes from the Stripe API directly
(read-only restricted key, via cash_truth._recent_charges — same reads the
payback reconciliation uses). The original MCP-tool dependency is obsolete: the
aggregate-only MCP never grew a list-charges tool, but the rk_ key on Railway
reads /v1/charges fine. Without the key this still degrades cleanly to a
"pending" status with a degraded[] entry; it never fabricates matches.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, timedelta

import requests

from config import SHEET_CONFIG, HTTP_TIMEOUT
from helpers import today_sydney

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 30
_AMOUNT_TOLERANCE = 1.0  # AUD, for amount fallback matching


def _list_recent_charges(days: int) -> dict | None:
    """Succeeded charges via the read-only Stripe key (cash_truth's shared reader),
    in this module's expected shape. None = no key / API failure."""
    try:
        from cash_truth import _recent_charges
        charges = _recent_charges(days)
    except Exception as e:
        logger.error("Reconcile charge fetch failed: %s", e)
        return None
    if charges is None:
        return None
    return {"charges": [{"id": c["id"], "amount": c["amount"], "currency": c["currency"],
                         "created": str(c["date"]), "status": "succeeded",
                         "customer_name": c["customer_name"],
                         "customer_email": c["_email"]} for c in charges]}


def _norm(s: str) -> str:
    """Normalize a name/business for loose matching."""
    s = (s or "").strip().lower()
    s = re.sub(r"\b(the|pty|ltd|co|restaurant|cafe|café|bar|kitchen|and|&)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fetch_tracker_rows() -> tuple[list[str], list[list[str]]]:
    """Fetch the Lead-to-Cash tracker (full sheet, by name — no row cutoff)."""
    sid = SHEET_CONFIG["sheet_id"]
    tab = SHEET_CONFIG["tab_name"]
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab)}"
    )
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            return [], []
        rows = list(csv.reader(io.StringIO(resp.text)))
        if len(rows) < 2:
            return [], []
        return rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    except requests.RequestException as e:
        logger.error("Reconcile tracker fetch failed: %s", e)
        return [], []


def _cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if idx < len(row) else ""


def _build_tracker_index(headers: list[str], rows: list[list[str]]) -> dict:
    """Index tracker rows by email and normalized name/business for matching.
    Columns: 3 Lead Name, 4 Email, 7 Business Name. Emails stay inside this dict
    and never leave the module."""
    by_email: dict[str, str] = {}   # email -> business/lead label
    by_name: set[str] = set()       # normalized name + business tokens
    for r in rows:
        name = _cell(r, 3)
        email = _cell(r, 4).lower()
        business = _cell(r, 7)
        label = business or name
        if email and "@" in email:
            by_email[email] = label
        if name:
            by_name.add(_norm(name))
        if business:
            by_name.add(_norm(business))
    return {"by_email": by_email, "by_name": by_name}


def reconcile_stripe_tracker() -> dict:
    """Flag Stripe payments with no matching tracker entry.

    Returns dict for the snapshot under 'stripe_reconciliation'. PII-safe:
    only customer/business names + amounts + dates in the output, never emails.
    """
    degraded: list[dict] = []
    today = today_sydney()

    charges_res = _list_recent_charges(_LOOKBACK_DAYS)
    if not charges_res or "charges" not in charges_res:
        # No read-only Stripe key / API unreachable — honest pending state.
        degraded.append({
            "metric": "stripe_reconciliation",
            "reason": (
                "Stripe↔tracker reconciliation pending: per-charge reads unavailable "
                "(no read-only STRIPE_SECRET_KEY or API failure). Incomplete Won rows "
                "are still surfaced via the 'won_but_unlogged' flag."
            ),
        })
        return {
            "stripe_reconciliation": {
                "status": "pending_stripe_key",
                "paid_missing_from_tracker": None,
                "checked_charges": 0,
            },
            "degraded": degraded,
        }

    headers, rows = _fetch_tracker_rows()
    if not headers:
        degraded.append({
            "metric": "stripe_reconciliation",
            "reason": "Reconciliation could not read the tracker — skipped this cycle.",
        })
        return {
            "stripe_reconciliation": {"status": "tracker_unavailable",
                                      "paid_missing_from_tracker": None,
                                      "checked_charges": 0},
            "degraded": degraded,
        }

    idx = _build_tracker_index(headers, rows)
    cutoff = today - timedelta(days=_LOOKBACK_DAYS)

    unmatched: list[dict] = []
    checked = 0
    for ch in charges_res["charges"]:
        if (ch.get("status") or "succeeded") != "succeeded":
            continue
        checked += 1
        email = (ch.get("customer_email") or "").lower()
        name = ch.get("customer_name") or ""
        nname = _norm(name)
        # Match priority: email exact → normalized name/business exact.
        matched = False
        if email and email in idx["by_email"]:
            matched = True
        elif nname and nname in idx["by_name"]:
            matched = True
        if not matched:
            unmatched.append({
                # name only — never the email
                "customer": name or "(unnamed Stripe customer)",
                "amount": ch.get("amount"),
                "date": ch.get("created"),
            })

    result = {
        "status": "ok",
        "checked_charges": checked,
        "lookback_days": _LOOKBACK_DAYS,
        "paid_missing_from_tracker": unmatched,
        "match_method": "email exact → normalized name/business exact",
    }
    if unmatched:
        degraded.append({
            "metric": "stripe_paid_not_in_tracker",
            "reason": (
                f"{len(unmatched)} Stripe payment(s) have no matching Lead-to-Cash "
                f"tracker entry — someone paid but isn't logged. Verify and add to "
                f"the tracker."
            ),
        })

    # PII guard: assert no email slipped into the output.
    blob = str(result)
    assert "@" not in blob, "stripe_reconciliation output must not contain emails"

    return {"stripe_reconciliation": result, "degraded": degraded}
