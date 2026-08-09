"""
tests/test_hardening_wave.py — audit hardening batch:

  F3  — stale invariant alerts SELF-RETIRE (journaled) when their condition
        clears on every swept clock×window; the feed shows LIVE state.
  F9  — a Stripe page error AFTER partial data is a LOUD partial (kv-marked,
        degraded in the cash view); the #131 ruling pass and the P1 card
        builder SKIP rather than derive from a fragment (drill B13 re-run).
  F16 — the nightly sweep is SINGLE-FLIGHT: the day is claimed atomically
        BEFORE the 76s sweep; the loser walks away. Accuracy history keeps ONE
        row per date (idempotent last-wins append + journaled one-off de-dupe).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ads_truth
import cash_truth
import kv_store
import resolution


# ── F16 · single-flight nightly ──────────────────────────────────────────────

def test_put_if_absent_claims_once():
    kv_store.delete("test:claim")
    assert kv_store.put_if_absent("test:claim", {"pid": 1}) is True
    assert kv_store.put_if_absent("test:claim", {"pid": 2}) is False
    assert kv_store.get("test:claim") == {"pid": 1}


def test_nightly_tick_single_flight(monkeypatch):
    """Two workers hit the tick the same day → the sweep runs ONCE."""
    from helpers import today_sydney
    today = str(today_sydney())
    kv_store.delete(ads_truth._KV_TICK)
    kv_store.delete(f"{ads_truth._KV_TICK}:claim:{today}")
    runs = []
    monkeypatch.setattr(ads_truth, "integrity_sweep", lambda: runs.append(1))
    assert ads_truth.nightly_tick() is True          # worker A claims + runs
    kv_store.delete(ads_truth._KV_TICK)              # simulate worker B's view:
    assert ads_truth.nightly_tick() is False         # stamp unseen but claim held
    assert len(runs) == 1


def test_nightly_tick_failed_sweep_releases_the_claim(monkeypatch):
    """A failed sweep must not burn the day — the claim is released so a later
    tick can retry (the old stamp-on-success retry semantics survive)."""
    from helpers import today_sydney
    today = str(today_sydney())
    kv_store.delete(ads_truth._KV_TICK)
    kv_store.delete(f"{ads_truth._KV_TICK}:claim:{today}")
    monkeypatch.setattr(ads_truth, "integrity_sweep",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ads_truth.nightly_tick() is False
    calls = []
    monkeypatch.setattr(ads_truth, "integrity_sweep", lambda: calls.append(1))
    assert ads_truth.nightly_tick() is True          # the retry got through
    assert calls == [1]


def test_accuracy_history_one_row_per_date():
    kv_store.put("ads_truth:accuracy", [
        {"date": "2026-08-07", "facts_checked": 24, "disagreements": 26},
        {"date": "2026-08-07", "facts_checked": 24, "disagreements": 1},
        {"date": "2026-08-08", "facts_checked": 24, "disagreements": 1},
        {"date": "2026-08-08", "facts_checked": 24, "disagreements": 1},
    ])
    kv_store.put("integrity:autofix_log", [])
    out = ads_truth.dedupe_accuracy_history()
    assert out["removed"] == 2
    acc = kv_store.get("ads_truth:accuracy")
    assert [r["date"] for r in acc] == ["2026-08-07", "2026-08-08"]
    assert acc[0]["disagreements"] == 1              # LAST row per date kept
    # journaled
    assert any("F16" in e["rule"] for e in kv_store.get("integrity:autofix_log"))
    # idempotent
    assert ads_truth.dedupe_accuracy_history()["removed"] == 0


# ── F9 · stripe partial-failure is LOUD (drill B13 re-run) ───────────────────

def _pages(monkeypatch, pages):
    """Feed _sget a scripted page sequence."""
    seq = list(pages)
    import payback_reconciliation

    def sget(path, params):
        return seq.pop(0)
    monkeypatch.setattr(payback_reconciliation, "_sget", sget)
    import config
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test", raising=False)
    monkeypatch.setattr(cash_truth, "STRIPE_SECRET_KEY", "sk_test", raising=False)


def test_partial_page_marks_loud_not_silent(monkeypatch):
    import calendar, datetime as dt
    ch = {"id": "ch_ok", "paid": True, "status": "succeeded", "amount": 100000,
          "amount_refunded": 0, "created": calendar.timegm(dt.datetime(2026, 8, 1).timetuple()),
          "currency": "aud", "customer": {}, "billing_details": {},
          "balance_transaction": {}}
    monkeypatch.setattr("config.STRIPE_SECRET_KEY", "sk_test", raising=False)
    import importlib
    _pages(monkeypatch, [
        {"data": [ch], "has_more": True, "error": None},
        {"data": [], "has_more": False, "error": "rate limited (test)"},
    ])
    from config import STRIPE_SECRET_KEY  # noqa: F401
    kv_store.delete("stripe:partial_pull")
    out = cash_truth._raw_recent_charges(30)
    assert out == [ch]                               # the fragment is returned…
    partial = cash_truth.stripe_pull_partial()       # …but MARKED, never absorbed
    assert partial and "rate limited" in partial["error"]


def test_clean_pull_clears_the_partial_marker(monkeypatch):
    kv_store.put("stripe:partial_pull", {"date": "2026-08-08", "error": "old"})
    _pages(monkeypatch, [{"data": [], "has_more": False, "error": None}])
    cash_truth._raw_recent_charges(30)
    assert cash_truth.stripe_pull_partial() is None


def test_total_failure_still_returns_none(monkeypatch):
    _pages(monkeypatch, [{"data": [], "has_more": False, "error": "down"}])
    assert cash_truth._raw_recent_charges(30) is None


def test_ruling_pass_skips_on_partial(monkeypatch):
    """#131 must never derive a close date from an incomplete charge list."""
    kv_store.put("stripe:partial_pull", {"date": "2026-08-09", "error": "partial (test)"})
    kv_store.put("ads_truth:flags", [])
    out = resolution.apply_payment_class_ruling()
    assert "skipped" in out and "partial" in out["skipped"]
    flags = kv_store.get("ads_truth:flags")
    assert any("SKIPPED" in f["reason"] and "F9" in f["reason"] for f in flags)
    kv_store.delete("stripe:partial_pull")


def test_card_builder_keeps_existing_cards_on_partial(monkeypatch):
    import close_integrity
    monkeypatch.setattr(close_integrity, "_tracker_won_rows",
                        lambda: [{"name": "Partial Test", "email": "p@x.com",
                                  "close_date": None, "contract": 1000, "cash": 500}])
    kv_store.put("stripe:partial_pull", {"date": "2026-08-09", "error": "partial (test)"})
    kv_store.put("integrity:proposed_fixes",
                 {"as_of": "2026-08-08", "cards": [{"kind": "P1_close_date_candidate",
                                                    "name": "Kept Card", "id": "pfix:x"}]})
    cards = resolution.propose_fixes()
    assert [c["name"] for c in cards] == ["Kept Card"]   # no rebuild from a fragment
    kv_store.delete("stripe:partial_pull")


# ── F3 · invariant alerts self-retire ────────────────────────────────────────

def test_stale_invariant_pendings_retire_when_clear(monkeypatch):
    """15 stale invariant-class pendings at audit while every current invariant
    was all-ok — after the sweep they retire (journaled); non-invariant and
    still-live entries survive."""
    from tests.test_ads_dashboard import _fake_result
    result = _fake_result()          # all rows coherent → zero live violations
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: result)
    monkeypatch.setattr(AE, "parse_tracker", lambda rows: ([], {}))
    monkeypatch.setattr(AE, "_tracker_rows_clean", lambda: [])
    # keep the sweep to the invariant leg — everything downstream is stubbed
    for fn in ("spine_census", "quad_check", "reached_sweep", "event_sweep",
               "show_verification_pass"):
        monkeypatch.setattr(ads_truth, fn,
                            lambda *a, **kw: {"counts": {"T0": 0, "T1": 0, "T2": 0, "T3": 0},
                                              "lanes": {"T0": []}, "facts": 0,
                                              "agreements": 0, "table": [],
                                              "days": 90, "total": 0})
    import resolution as res
    monkeypatch.setattr(res, "resolve_dates", lambda: {})
    # NOTE: _fake_result carries ONE genuinely-live violation
    # (invariant:120000000000000001 — I1 shows>sets) — it must SURVIVE the
    # retire pass, proving retirement is condition-driven, not a blanket wipe.
    kv_store.put("integrity:pending", [
        {"id": "invariant:120000000000000001", "detail": "still live — must survive"},
        {"id": "invariant:deadcreative", "detail": "stale transient"},
        {"id": "invariant:I10:someone", "detail": "stale transient"},
        {"id": "integrity:phantom_close:x", "detail": "not an invariant"},
        {"id": "other:thing", "detail": "unrelated — must survive"},
    ])
    kv_store.put("integrity:autofix_log", [])
    out = ads_truth.integrity_sweep()
    assert out.get("invariant_alerts_retired") == 2
    ids = {p["id"] for p in kv_store.get("integrity:pending")}
    assert "invariant:120000000000000001" in ids     # live condition → stays
    assert "invariant:deadcreative" not in ids       # clear condition → retired
    assert "invariant:I10:someone" not in ids
    assert "other:thing" in ids
    lg = kv_store.get("integrity:autofix_log")
    assert any("F3" in e["rule"] for e in lg)
