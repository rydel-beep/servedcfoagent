"""
tests/test_refund_ruling.py — RULING R1 (DECISIONS #132, audit gate close):
refunds are post-close economics.

  (1) A FULLY-REFUNDED charge retains its derived close date — the payment
      cleared, the deal closed; a refund never erases a close from the funnel.
  (2) The refund is NOT invisible: it surfaces in the refund/churn report
      (cash_truth.refund_report) with its charge id and amounts — it moves to
      the right place, it does not vanish.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cash_truth
import kv_store
import resolution


def _fake_raw_charge(charge_id="ch_R1", amount_cents=500000, refunded_cents=500000,
                     created=None, name="Refund Test Venue"):
    import calendar
    created = created or dt.datetime(2026, 7, 15, 3, 0)
    return {"id": charge_id, "paid": True, "status": "succeeded",
            "amount": amount_cents, "amount_refunded": refunded_cents,
            "refunded": refunded_cents >= amount_cents,
            "created": calendar.timegm(created.timetuple()),
            "currency": "aud",
            "customer": {"name": name, "email": "refund@venue.com"},
            "billing_details": {}, "balance_transaction": {}}


def test_fully_refunded_charge_retains_its_derived_close_date(monkeypatch):
    """The derivation was made on charge evidence; the charge is later FULLY
    refunded (it even disappears from the cash view's charge list). The derived
    close date stays — nothing retires it, nothing re-derives it away."""
    kv_store.put("derived:dates", {})
    ok = resolution.record_derived_date(
        "refund test venue", "close_date", "2026-07-15", "derived:stripe",
        {"charge_id": "ch_R1", "matched_by": "email", "ruling": "DECISIONS #131"})
    assert ok
    # after the refund: the charge no longer appears in first-payment evidence
    monkeypatch.setattr(resolution, "_stripe_first_payment_dates", lambda days=365: {})
    import close_integrity
    monkeypatch.setattr(close_integrity, "_tracker_won_rows",
                        lambda: [{"name": "Refund Test Venue", "email": "refund@venue.com",
                                  "close_date": None, "contract": 5000, "cash": 5000}])
    out = resolution.apply_payment_class_ruling()
    assert out["already_derived"] == 1            # skipped up front — nothing converted
    store = resolution.derived_dates()
    assert store["refund test venue"]["close_date"]["date"] == "2026-07-15"
    assert store["refund test venue"]["close_date"]["evidence"]["charge_id"] == "ch_R1"


def test_full_refund_never_flows_into_the_cash_view(monkeypatch):
    """Cash honesty is untouched by R1: a fully-refunded charge nets to $0 and
    stays OUT of the cash charge list (cash was never at risk in this lane)."""
    monkeypatch.setattr(cash_truth, "_raw_recent_charges",
                        lambda days=90: [_fake_raw_charge()])
    charges = cash_truth._recent_charges(90)
    assert charges == []                          # $0 net — filtered, correctly


def test_refund_surfaces_in_the_refund_report(monkeypatch):
    """The refund moves to the RIGHT PLACE: the refund report carries it with
    charge id + amounts + the fully_refunded flag — including the fully-refunded
    charges the cash view drops."""
    monkeypatch.setattr(cash_truth, "_raw_recent_charges",
                        lambda days=90: [
                            _fake_raw_charge(),                                   # full
                            _fake_raw_charge("ch_R2", 300000, 100000,             # partial
                                             name="Partial Refund Cafe"),
                            _fake_raw_charge("ch_R3", 200000, 0, name="Clean")])  # none
    rep = cash_truth.refund_report(90)
    assert rep["count"] == 2
    by_id = {r["charge_id"]: r for r in rep["refunds"]}
    assert by_id["ch_R1"]["fully_refunded"] is True and by_id["ch_R1"]["refunded"] == 5000.0
    assert by_id["ch_R2"]["fully_refunded"] is False and by_id["ch_R2"]["refunded"] == 1000.0
    assert "ch_R3" not in by_id
    assert rep["total_refunded"] == 6000.0
    assert "post-close economics" in rep["note"]


def test_refund_report_degrades_to_none_when_stripe_dead(monkeypatch):
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda days=90: None)
    assert cash_truth.refund_report(90) is None   # degraded, never fabricated
