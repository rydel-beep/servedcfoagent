"""
tests/test_review_fixes.py — the gate-close adversarial review pass (9 verified
findings on the fix-wave diff, all fixed before ship). Each test pins one:

  1 · unified_cash_view's refund leg SHARES the payments pull — a clean second
      pull no longer clears the first pull's partial marker.
  2 · the #131 ruling pass refuses a fragment ON THE RUN IN WHICH the partial
      happens (post-pull guard), not just the next run.
  3 · Stripe charge dates are the SYDNEY day of the epoch (never server-local).
  4 · complete contact syncs tombstone rows absent from the feed (F7's root —
      source-contract test; live confirmation post-deploy via sync state).
  7 · the orphan census recognises BOTH normal forms — a "St. Ali"-style name
      is never mislabelled an orphan.
  9 · put_if_absent fails CLOSED on DB errors; a stale mid-sweep claim (dead
      worker) is reclaimed after 2h instead of burning the day.
"""
from __future__ import annotations

import calendar
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ads_truth
import cash_truth
import kv_store
import resolution


def _charge(created_utc: dt.datetime, charge_id="ch_tz", amount=100000, refunded=0):
    return {"id": charge_id, "paid": True, "status": "succeeded",
            "amount": amount, "amount_refunded": refunded,
            "refunded": refunded >= amount,
            "created": calendar.timegm(created_utc.timetuple()),
            "currency": "aud", "customer": {"name": "TZ Test", "email": "t@x.com"},
            "billing_details": {}, "balance_transaction": {}}


# ── 3 · Sydney day for charge epochs ─────────────────────────────────────────

def test_charge_dates_are_sydney_days_not_server_local():
    # 2026-07-09 22:30 UTC = 08:30 AEST on the 10th — the F8/B9 class on Stripe
    ch = cash_truth._filter_succeeded([_charge(dt.datetime(2026, 7, 9, 22, 30))])
    assert ch[0]["date"] == dt.date(2026, 7, 10)
    rep_raw = [_charge(dt.datetime(2026, 7, 9, 22, 30), refunded=100000)]
    rep = cash_truth.refund_report(90, raw=rep_raw)
    assert rep["refunds"][0]["date"] == "2026-07-10"


# ── 1 · one pull per cash view — marker survives ─────────────────────────────

def test_cash_view_states_its_own_pulls_partial_even_if_a_later_pull_is_clean(monkeypatch):
    """The exact review scenario: the PAYMENTS pull errors on page 3 (fragment),
    the refund leg's later pull succeeds clean and clears the global marker —
    the view must STILL report the fragment as partial (snapshot-after-own-pull),
    never ship it as complete."""
    frag = [_charge(dt.datetime(2026, 8, 1, 3, 0), charge_id="ch_frag")]
    clean = [_charge(dt.datetime(2026, 8, 1, 3, 0), charge_id="ch_clean")]
    calls = {"n": 0}

    def sequenced_pull(days=90):
        calls["n"] += 1
        if calls["n"] == 1:                       # payments pull → PARTIAL
            cash_truth._mark_partial("rate limited page 3 (test)")
            return frag
        cash_truth._mark_partial(None)            # refund pull → clean, clears
        return clean
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", sequenced_pull)
    monkeypatch.setattr(cash_truth, "_tracker_index",
                        lambda: {"entries": [], "by_email": {}, "by_name": {},
                                 "sync_label": "test"})
    monkeypatch.setattr(cash_truth, "_update_lag_watermarks", lambda p, n: {})
    out = cash_truth.unified_cash_view(90)
    assert calls["n"] == 2
    # the view carries ITS pull's partial state though the marker is now clear
    assert out["partial_pull"] and "rate limited" in out["partial_pull"]["error"]
    assert any(d["metric"] == "stripe_partial_pull" for d in out["degraded"])
    assert cash_truth.stripe_pull_partial() is None   # marker = latest pull, by design
    kv_store.delete("stripe:partial_pull")


# ── 2 · the ruling pass refuses the fragment on its OWN run ──────────────────

def test_ruling_pass_refuses_fragment_same_run(monkeypatch):
    kv_store.delete("stripe:partial_pull")            # previous state CLEAN
    import close_integrity
    monkeypatch.setattr(close_integrity, "_tracker_won_rows",
                        lambda: [{"name": "Fragment Venue", "email": "f@x.com",
                                  "close_date": None, "contract": 1000, "cash": 500}])

    def pull_goes_partial(days=365):
        cash_truth._mark_partial("blew up mid-pagination (test)")
        return {"f@x.com": {"date": dt.date(2026, 8, 1), "charge_id": "ch_bad",
                            "via": "email"}}
    monkeypatch.setattr(resolution, "_stripe_first_payment_dates", pull_goes_partial)
    kv_store.put("ads_truth:flags", [])
    out = resolution.apply_payment_class_ruling()
    assert "skipped" in out and "post-pull" in out["skipped"]
    assert not (resolution.derived_dates().get("fragment venue") or {}).get("close_date")
    flags = kv_store.get("ads_truth:flags")
    assert any("mid-run" in f["reason"] for f in flags)
    kv_store.delete("stripe:partial_pull")


# ── 4 · tombstone on complete sync (source contract) ─────────────────────────

def test_sync_contacts_tombstones_on_complete_fetch():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "attribution_join.py")).read()
    i = src.index("def sync_contacts")
    body = src[i:i + 4000]
    assert "SET deleted = TRUE" in body and "if complete:" in body
    assert "tombstoned" in body        # reported in sync state for live verify


# ── 7 · orphan census understands both normal forms ──────────────────────────

def test_dotted_name_derivation_is_not_an_orphan(monkeypatch):
    from tests.test_polish_wave import _stub_sweep_legs
    from tests.test_attribution import HDR, row
    _stub_sweep_legs(monkeypatch, [HDR, row("St. Ali Cafe", "st@ali.com")])
    # the derived store key uses resolution._norm (strips the '.')
    key = resolution._norm("St. Ali Cafe")
    assert "." not in key
    kv_store.put("derived:dates", {
        key: {"close_date": {"date": "2026-08-01", "provenance": "derived:stripe",
                             "evidence": {"charge_id": "x"}, "ts": "2026-08-01"}}})
    out = ads_truth.integrity_sweep()
    assert out["orphan_derivations"]["count"] == 0


# ── 9 · fail-closed claims + stale-claim reclaim ─────────────────────────────

def test_put_if_absent_fails_closed_on_db_error(monkeypatch):
    import db
    monkeypatch.setattr(db, "db_configured", lambda: True)
    monkeypatch.setattr(db, "get_conn",
                        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(kv_store, "_migrate", lambda: True)
    assert kv_store.put_if_absent("test:failclosed", {"pid": 1}) is False


def test_stale_mid_sweep_claim_is_reclaimed(monkeypatch):
    from helpers import today_sydney
    today = str(today_sydney())
    kv_store.delete(ads_truth._KV_TICK)
    # a worker died mid-sweep 3h ago: claim held, day never stamped
    kv_store.put(f"{ads_truth._KV_TICK}:claim:{today}",
                 {"pid": 999, "at_epoch": time.time() - 3 * 3600})
    runs = []
    monkeypatch.setattr(ads_truth, "integrity_sweep", lambda: runs.append(1))
    assert ads_truth.nightly_tick() is True           # reclaimed + ran
    assert runs == [1]


def test_fresh_claim_is_respected(monkeypatch):
    from helpers import today_sydney
    today = str(today_sydney())
    kv_store.delete(ads_truth._KV_TICK)
    kv_store.put(f"{ads_truth._KV_TICK}:claim:{today}",
                 {"pid": 999, "at_epoch": time.time() - 60})   # a LIVE sweep
    monkeypatch.setattr(ads_truth, "integrity_sweep",
                        lambda: (_ for _ in ()).throw(AssertionError("ran twice")))
    assert ads_truth.nightly_tick() is False
