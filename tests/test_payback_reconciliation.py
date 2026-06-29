"""
tests/test_payback_reconciliation.py
------------------------------------
True payback via Stripe reconciliation: the cumulative-cash-crosses-CAC curve, offer
detection, edge cases (never-recovered = ongoing), and graceful no-key behaviour. Stripe
+ tracker are mocked (live reconciliation verified on the deployed app).
"""
from __future__ import annotations
import sys, os, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import payback_reconciliation as pb


def test_payback_crosses_cac_day():
    # close 06-01, CAC 5000; 3000 on close day, 3000 on 06-15 → crosses on 06-15 = 14 days.
    tl = [(dt.date(2026, 6, 1), 3000.0), (dt.date(2026, 6, 15), 3000.0)]
    r = pb._deal_payback(tl, dt.date(2026, 6, 1), 5000.0)
    assert r["recovered"] and r["payback_days"] == 14 and r["collected"] == 6000.0


def test_payback_same_day_upfront():
    tl = [(dt.date(2026, 6, 1), 6000.0)]            # full upfront → day 0
    r = pb._deal_payback(tl, dt.date(2026, 6, 1), 5000.0)
    assert r["recovered"] and r["payback_days"] == 0


def test_payback_pre_close_deposit_counts():
    tl = [(dt.date(2026, 5, 20), 6000.0)]           # deposit before close covers CAC → day 0
    r = pb._deal_payback(tl, dt.date(2026, 6, 1), 5000.0)
    assert r["recovered"] and r["payback_days"] == 0


def test_payback_never_recovered_is_ongoing():
    # split offer: only 2000 collected vs 5000 CAC → ongoing, not a false finite number.
    tl = [(dt.date(2026, 6, 1), 1000.0), (dt.date(2026, 6, 20), 1000.0)]
    r = pb._deal_payback(tl, dt.date(2026, 6, 1), 5000.0)
    assert r["recovered"] is False and r["payback_days"] is None and r["ongoing_days"] == 19


def test_which_offer():
    assert pb._which_offer("what's our payback on Growth Pro") == "Growth Pro"
    assert pb._which_offer("payback for scale engine split") == "Scale Engine Split"
    assert pb._which_offer("scale engine payback") == "Scale Engine"
    assert pb._which_offer("payback by offer") is None


def test_command_detection_and_graceful_no_key(monkeypatch):
    monkeypatch.setattr(pb, "STRIPE_SECRET_KEY", "")
    reply, handled = pb.handle_payback_command("what's our payback on Growth Pro?")
    assert handled and "payback" in reply.lower()       # handled, degrades to a clear message
    assert pb.handle_payback_command("how's cash")[1] is False


def test_compute_payback_rollup(monkeypatch):
    # Mock: 3 won deals (2 Growth Pro recovered, 1 unmatched), CAC 3000.
    monkeypatch.setattr(pb, "STRIPE_SECRET_KEY", "rk_test")
    monkeypatch.setattr(pb, "_won_deals", lambda w0, w1: [
        {"name": "A", "business": "Alpha", "email": "a@x.com", "offer": "Growth Pro",
         "contract": 9000, "close_date": dt.date(2026, 6, 1)},
        {"name": "B", "business": "Beta", "email": "b@x.com", "offer": "Growth Pro",
         "contract": 9000, "close_date": dt.date(2026, 6, 1)},
        {"name": "C", "business": "Gamma", "email": "", "offer": "Scale Engine",
         "contract": 9000, "close_date": dt.date(2026, 6, 1)},
    ])
    import range_unit_economics
    monkeypatch.setattr(range_unit_economics, "unit_economics", lambda s, e: {"cac_loaded": 3000.0})
    def fake_find(email, biz):
        return ((biz, "email", "aud") if email else (None, None, None))
    monkeypatch.setattr(pb, "_find_customer", fake_find)
    monkeypatch.setattr(pb, "_customer_timeline",
                        lambda cid: ([(dt.date(2026, 6, 1), 1500.0), (dt.date(2026, 6, 11), 1500.0)], []))
    res = pb.compute_payback("2026-05-01", "2026-06-30")
    assert res["summary"] == {"closes": 3, "matched": 2, "unmatched": 1, "match_rate_pct": 67}
    gp = res["per_offer"]["Growth Pro"]
    assert gp["deals_recovered"] == 2 and gp["median_payback_days"] == 10.0 and "small sample" in gp["caveat"]
    assert res["matched"][0].get("customer") and "email" not in res["matched"][0]   # PII-safe output
