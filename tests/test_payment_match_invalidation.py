"""tests/test_payment_match_invalidation.py — #170: a matched payment moves
the numbers.

Witnessed: "LTGP:CAC still isn't updated even after payment from Scott was
added." The scheduled unmatched-payments scan matched charges but never
invalidated; close_detect.tick only invalidates on a NEW close key, and the
close register rebuilds only on invalidation. A payment matched to a client
already in the register therefore never reached the tiles.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store
import unmatched_payments as UP


def _wire(monkeypatch, charges, match):
    calls = []
    monkeypatch.setattr(UP, "_index", lambda: ({"idx": 1}, {"roster": 1}))
    monkeypatch.setattr(UP, "_charges", lambda days: charges)
    import stripe_reconcile as SR
    monkeypatch.setattr(SR, "_match_payment",
                        lambda name, email, amount, idx, roster: match(name))
    import close_detect
    monkeypatch.setattr(close_detect, "invalidate_now",
                        lambda reason: calls.append(reason) or {"reason": reason})
    return calls


_CH = {"id": "ch_scott_1", "customer_name": "Scott Example", "amount": 5278.90,
       "date": "2026-09-26", "_email": "scott@example.com"}


def test_a_newly_matched_payment_invalidates(monkeypatch):
    kv_store.delete(UP.K_STATE)
    calls = _wire(monkeypatch, [_CH],
                  lambda n: {"business": "Amoroso Gelateria", "basis": "email"})
    res = UP.scan()
    assert res["newly_matched"] == ["ch_scott_1"]
    assert len(calls) == 1 and "ch_scott_1" in calls[0]


def test_the_same_match_twice_does_not_churn(monkeypatch):
    kv_store.delete(UP.K_STATE)
    calls = _wire(monkeypatch, [_CH],
                  lambda n: {"business": "Amoroso Gelateria", "basis": "email"})
    UP.scan()
    UP.scan()
    assert len(calls) == 1


def test_an_unmatched_payment_does_not_invalidate(monkeypatch):
    kv_store.delete(UP.K_STATE)
    calls = _wire(monkeypatch, [_CH], lambda n: {"why": "no match"})
    res = UP.scan()
    assert res["count"] == 1 and not calls


# ── the 15-minute cursor (#170, Rydel: ≤20-minute contract) ─────────────────

def test_the_cursor_matches_only_unseen_charges_and_invalidates(monkeypatch):
    kv_store.delete(UP.K_STATE)
    calls = _wire(monkeypatch, [], lambda n: {"business": "Amoroso Gelateria",
                                              "basis": "confirmed alias"})
    UP.scan()                                   # standing state, no charges
    res = UP.scan_new([_CH])
    assert res == {"new": 1, "newly_matched": ["ch_scott_1"]}
    assert len(calls) == 1
    assert UP.scan_new([_CH]) == {"new": 0}     # seen → nothing to do
    assert len(calls) == 1


def test_the_cursor_never_runs_before_a_full_scan(monkeypatch):
    kv_store.delete(UP.K_STATE)
    calls = _wire(monkeypatch, [], lambda n: {"business": "X"})
    assert UP.scan_new([_CH])["new"] == 0 and not calls


def test_an_unmatched_new_charge_lands_on_the_panel(monkeypatch):
    kv_store.delete(UP.K_STATE)
    _wire(monkeypatch, [], lambda n: {"why": "no match"})
    UP.scan()
    UP.scan_new([_CH])
    st = UP.latest()
    assert st["count"] == 1 and st["total_unmatched"] == 5278.9
