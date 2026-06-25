"""
tests/test_stripe_balance.py
----------------------------
Real Stripe money states from /v1/balance + /v1/payouts (read-only): the three
states, AUD handling, in-transit classification, failed-payout drop, graceful degrade.
"""
from __future__ import annotations

import sys
import os
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import stripe_balance


def test_no_key_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(stripe_balance, "STRIPE_SECRET_KEY", "")
    r = stripe_balance.read_stripe_money_states()
    assert r["stripe_money"] is None
    assert r["degraded"][0]["metric"] == "stripe_money_states"
    assert r["degraded"][0]["severity"] == "optional"


def _ts(d):
    import calendar
    return calendar.timegm(d.timetuple())


def test_three_states_and_in_transit(monkeypatch):
    monkeypatch.setattr(stripe_balance, "STRIPE_SECRET_KEY", "rk_live_x")
    today = stripe_balance.today_sydney()
    payouts = {"data": [
        # active → in transit regardless of date
        {"id": "po_1", "amount": 1372000, "currency": "aud", "status": "in_transit",
         "arrival_date": _ts(today + dt.timedelta(days=1))},
        # paid, not yet arrived → in transit
        {"id": "po_2", "amount": 1152495, "currency": "aud", "status": "paid",
         "arrival_date": _ts(today)},
        # paid, arrival passed → recently paid (assumed settled), NOT in transit
        {"id": "po_3", "amount": 282088, "currency": "aud", "status": "paid",
         "arrival_date": _ts(today - dt.timedelta(days=2))},
        # failed → dropped from everything
        {"id": "po_4", "amount": 999900, "currency": "aud", "status": "failed",
         "arrival_date": _ts(today)},
    ]}
    def fake_get(path, params=None):
        if path == "/v1/balance":
            return {"available": [{"amount": 0, "currency": "aud"}],
                    "pending": [{"amount": 1371324, "currency": "aud"}]}, None
        return payouts, None
    monkeypatch.setattr(stripe_balance, "_get", fake_get)

    sm = stripe_balance.read_stripe_money_states()["stripe_money"]
    assert sm["available"] == 0.0
    assert sm["pending_incoming"] == 13713.24
    # in transit = po_1 (13720) + po_2 (11524.95)
    assert sm["in_transit_to_bank"] == round(13720.00 + 11524.95, 2)
    # recently paid (settled) = po_3
    assert sm["recently_paid_settling"] == 2820.88
    # failed dropped
    statuses = {p["id"]: p["in_transit"] for p in sm["payouts_recent"]}
    assert statuses["po_4"] is False and statuses["po_1"] is True and statuses["po_3"] is False


def test_non_aud_flagged(monkeypatch):
    monkeypatch.setattr(stripe_balance, "STRIPE_SECRET_KEY", "rk_live_x")
    def fake_get(path, params=None):
        if path == "/v1/balance":
            return {"available": [{"amount": 5000, "currency": "usd"}],
                    "pending": [{"amount": 100000, "currency": "aud"}]}, None
        return {"data": []}, None
    monkeypatch.setattr(stripe_balance, "_get", fake_get)
    r = stripe_balance.read_stripe_money_states()
    assert r["stripe_money"]["pending_incoming"] == 1000.0
    assert r["stripe_money"]["available"] == 0.0  # USD excluded from AUD sum
    assert any(d["metric"] == "stripe_money_currency" for d in r["degraded"])


def test_balance_read_failure_degrades(monkeypatch):
    monkeypatch.setattr(stripe_balance, "STRIPE_SECRET_KEY", "rk_live_x")
    monkeypatch.setattr(stripe_balance, "_get", lambda p, q=None: (None, "HTTP 401: bad key"))
    r = stripe_balance.read_stripe_money_states()
    assert r["stripe_money"] is None
    assert any("balance" in d["reason"].lower() for d in r["degraded"])
