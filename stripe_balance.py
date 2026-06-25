"""
stripe_balance.py
-----------------
Read the REAL Stripe money states from /v1/balance and /v1/payouts — READ-ONLY.

The aggregate MCP can't return the Balance object or individual Payout objects, so the
dashboard used to estimate ("$18,000 pending"). With a restricted read-only key this reads
the truth and distinguishes the THREE money states Rydel cares about:

  1. AVAILABLE      — balance.available: settled in Stripe, payable now.
  2. PENDING/INCOMING — balance.pending: collected, not yet settled into Stripe (the upcoming payout).
  3. IN TRANSIT TO BANK — recent payouts that LEFT Stripe (status pending/in_transit/paid) but
     haven't arrived in CommBank yet (arrival_date >= today). "paid" = Stripe sent it; bank
     settlement lags 1-3 days. failed/canceled payouts drop out.

READ-ONLY: only GET /v1/balance and GET /v1/payouts. No payout creation/modification.
Key is server-side (config), never logged. AUD throughout; non-AUD is flagged, never silently FX'd.
"""
from __future__ import annotations

import logging

import requests

from config import STRIPE_SECRET_KEY, STRIPE_PAYOUT_LOOKBACK_DAYS, HTTP_TIMEOUT
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

_API = "https://api.stripe.com"
_RETRY_STATUS = {429, 500, 502, 503, 529}
_MAX_RETRIES = 3
# A "paid" payout whose arrival_date has passed is assumed settled in CommBank. Active
# (pending/in_transit) payouts are always in-transit regardless of date.
_ACTIVE_STATUSES = {"pending", "in_transit"}


def _get(path: str, params: dict | None = None) -> tuple[dict | None, str | None]:
    """GET the Stripe API (read-only) with backoff. Returns (json, error). Key never logged."""
    backoff = 1.5
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.get(
                f"{_API}{path}",
                params=params or {},
                auth=(STRIPE_SECRET_KEY, ""),  # Stripe uses the key as basic-auth username
                timeout=(5, HTTP_TIMEOUT),
            )
        except requests.RequestException as e:
            last_err = f"request failed: {e}"
        else:
            if resp.status_code == 200:
                return resp.json(), None
            try:
                msg = resp.json().get("error", {}).get("message", resp.text[:160])
            except ValueError:
                msg = resp.text[:160]
            last_err = f"HTTP {resp.status_code}: {msg}"
            if resp.status_code not in _RETRY_STATUS:
                return None, last_err  # auth/permission/validation — surface immediately
        if attempt < _MAX_RETRIES:
            try:
                import time
                time.sleep(backoff)
            except Exception:
                pass
            backoff *= 2
    return None, last_err


def _aud_sum(buckets: list, currency: str = "aud") -> tuple[float, list]:
    """Sum a balance array's AUD amounts (cents → dollars). Returns (aud_total, other_ccy)."""
    total = 0.0
    other = []
    for b in buckets or []:
        ccy = (b.get("currency") or "").lower()
        amt = (b.get("amount") or 0) / 100.0
        if ccy == currency:
            total += amt
        elif amt:
            other.append({"currency": ccy.upper(), "amount": round(amt, 2)})
    return round(total, 2), other


def read_stripe_money_states() -> dict:
    """Read the three real money states from Stripe. Returns {stripe_money|None, degraded[]}."""
    degraded = []
    if not STRIPE_SECRET_KEY:
        degraded.append({
            "metric": "stripe_money_states",
            "reason": ("No STRIPE_SECRET_KEY — can't read /v1/balance or /v1/payouts. "
                       "Stripe balance/in-transit are estimates until a read-only key is added."),
            "severity": "optional",
        })
        return {"stripe_money": None, "degraded": degraded}

    today = today_sydney()

    # ── /v1/balance → available + pending ────────────────────────────────────
    bal, bal_err = _get("/v1/balance")
    if bal is None:
        degraded.append({"metric": "stripe_money_states",
                         "reason": f"Stripe /v1/balance read failed ({bal_err}).",
                         "severity": "optional"})
        return {"stripe_money": None, "degraded": degraded}

    available, avail_other = _aud_sum(bal.get("available"))
    pending, pend_other = _aud_sum(bal.get("pending"))
    non_aud = avail_other + pend_other
    if non_aud:
        degraded.append({"metric": "stripe_money_currency",
                         "reason": f"Stripe balance has non-AUD buckets {non_aud} — shown AUD-only, no FX.",
                         "severity": "optional"})

    # ── /v1/payouts → recent objects with status + arrival_date ──────────────
    since = today - __import__("datetime").timedelta(days=STRIPE_PAYOUT_LOOKBACK_DAYS)
    import calendar
    created_gte = calendar.timegm(since.timetuple())
    pay, pay_err = _get("/v1/payouts", {"limit": 50, "created[gte]": created_gte})
    payouts = []
    in_transit_total = 0.0
    recently_paid_total = 0.0
    if pay is None:
        degraded.append({"metric": "stripe_payouts",
                         "reason": f"Stripe /v1/payouts read failed ({pay_err}) — in-transit unavailable.",
                         "severity": "optional"})
    else:
        import datetime as _dt
        for p in pay.get("data", []):
            ccy = (p.get("currency") or "").lower()
            amt = (p.get("amount") or 0) / 100.0
            status = p.get("status")
            arr_ts = p.get("arrival_date")
            arr_date = _dt.date.fromtimestamp(arr_ts) if arr_ts else None
            # In transit = active statuses, OR paid-but-not-yet-arrived (arrival_date >= today).
            not_arrived = arr_date is None or arr_date >= today
            is_in_transit = (status in _ACTIVE_STATUSES) or (status == "paid" and not_arrived)
            row = {
                "id": p.get("id"),
                "amount": round(amt, 2),
                "currency": ccy.upper(),
                "status": status,
                "arrival_date": str(arr_date) if arr_date else None,
                "in_transit": bool(is_in_transit and ccy == "aud" and status not in ("failed", "canceled")),
            }
            payouts.append(row)
            if row["in_transit"]:
                in_transit_total += amt
            elif status == "paid" and ccy == "aud":
                recently_paid_total += amt  # arrival_date passed → assumed settled in CommBank

    now_iso = now_sydney().isoformat()
    stripe_money = {
        "available": available,                 # state 1: settled in Stripe, payable now
        "pending_incoming": pending,            # state 2: collected, settling into Stripe
        "in_transit_to_bank": round(in_transit_total, 2),  # state 3: left Stripe, not yet in CommBank
        "recently_paid_settling": round(recently_paid_total, 2),  # paid, arrival_date passed (should be in CommBank)
        "payouts_recent": payouts,
        "payout_lookback_days": STRIPE_PAYOUT_LOOKBACK_DAYS,
        "currency": "AUD",
        "non_aud_buckets": non_aud or None,
        "as_of": now_iso,
        "source": "Stripe API /v1/balance + /v1/payouts (read-only)",
        "definitions": {
            "available": "balance.available — settled in Stripe, payable now",
            "pending_incoming": "balance.pending — collected, not yet settled into Stripe (upcoming payout)",
            "in_transit_to_bank": "recent payouts (pending/in_transit, or paid not-yet-arrived) — left Stripe, not yet in CommBank",
            "recently_paid_settling": "paid payouts whose arrival_date has passed — Stripe says delivered; allow 1-3d CommBank settle",
        },
    }
    return {"stripe_money": stripe_money, "degraded": degraded}
