"""
test_snapshot.py
----------------
Quick integration test: builds a snapshot and validates its structure.
Run: python test_snapshot.py
"""
from __future__ import annotations

import json
import sys
import os

# Ensure we can import from the project root
sys.path.insert(0, os.path.dirname(__file__))

# Set a dummy refresh key for testing
os.environ.setdefault("CFO_REFRESH_KEY", "test-key-123")


def test_helpers():
    from helpers import today_sydney, now_sydney
    d = today_sydney()
    n = now_sydney()
    assert d is not None, "today_sydney() returned None"
    assert n.tzinfo is not None, "now_sydney() should be timezone-aware"
    print(f"  today_sydney() = {d}")
    print(f"  now_sydney()   = {n.isoformat()}")


def test_stripe():
    from stripe_pull import pull_stripe
    result = pull_stripe()
    assert "stripe" in result, "Missing 'stripe' key"
    assert "degraded" in result, "Missing 'degraded' key"
    stripe = result["stripe"]
    print(f"  MRR: {stripe.get('mrr')}")
    print(f"  Revenue current: {stripe['revenue']['current']['total_aud']}")
    print(f"  Revenue previous: {stripe['revenue']['previous']['total_aud']}")
    print(f"  Subscriptions: {stripe.get('subscriptions')}")
    print(f"  Customer count: {stripe.get('customer_count')}")
    print(f"  Failed charges: {stripe.get('failed_charges_count')}")
    print(f"  Payouts: {stripe.get('payouts')}")
    if result["degraded"]:
        print(f"  Degraded: {result['degraded']}")
    return result


def test_sheets():
    from sheets_pull import pull_sheets
    result = pull_sheets()
    assert "sheets" in result, "Missing 'sheets' key"
    sheets = result["sheets"]
    if sheets:
        print(f"  Deals won (total): {sheets['deals_won_total']}")
        print(f"  Deals won (window): {sheets['deals_won_in_window']}")
        print(f"  Cash collected: {sheets['cash_collected']}")
        print(f"  Contract value: {sheets['contract_value']}")
        print(f"  Closer commission (actual): {sheets['closer_commission_total']}")
        print(f"  Setter commission (actual): {sheets['setter_commission_total']}")
        print(f"  Setter breakdown: {sheets.get('setter_breakdown')}")
        print(f"  Data quality: {sheets.get('data_quality')}")
        print(f"  Remarks: {sheets.get('commission_remarks')}")
    if result["degraded"]:
        print(f"  Degraded: {result['degraded']}")
    return result


def test_ghl():
    from ghl_pull import pull_ghl
    result = pull_ghl()
    assert "ghl" in result, "Missing 'ghl' key"
    ghl = result["ghl"]
    if ghl:
        print(f"  Total opps: {ghl['total_opportunities']}")
        print(f"  Pipeline value: {ghl['total_pipeline_value']}")
        print(f"  Status: {ghl['status']}")
        print(f"  Conversion: {ghl['conversion_rate_pct']}%")
    else:
        print("  GHL returned None (likely missing API key)")
    if result["degraded"]:
        print(f"  Degraded: {result['degraded']}")
    return result


def test_full_snapshot():
    from snapshot import build_snapshot
    snap = build_snapshot()
    assert "generated_at" in snap
    assert "stripe" in snap
    assert "ghl" in snap
    assert "sheets" in snap
    assert "costs" in snap
    assert "degraded" in snap
    assert "ok" in snap
    print(f"  OK: {snap['ok']}")
    if snap.get("costs"):
        print(f"  Costs: closer={snap['costs']['closer_commission']}, setter={snap['costs']['setter_commission']}")
    print(f"  Degraded count: {len(snap['degraded'])}")
    for d in snap["degraded"]:
        print(f"    - {d.get('metric', d.get('source', '?'))}: {d['reason']}")
    return snap


def test_flask_app():
    from app import app
    client = app.test_client()

    # Health
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    print("  GET /health: 200 OK")

    # Snapshot before refresh
    resp = client.get("/cfo/snapshot")
    # Could be 200 (if persisted file exists) or 404
    print(f"  GET /cfo/snapshot (before refresh): {resp.status_code}")

    # Refresh without key
    resp = client.post("/cfo/refresh")
    assert resp.status_code == 401
    print("  POST /cfo/refresh (no key): 401")

    # Refresh with key
    resp = client.post("/cfo/refresh", headers={"X-CFO-KEY": "test-key-123"})
    assert resp.status_code == 200
    body = resp.get_json()
    print(f"  POST /cfo/refresh: 200, ok={body.get('ok')}, degraded={body.get('degraded_count')}")

    # Snapshot after refresh
    resp = client.get("/cfo/snapshot")
    assert resp.status_code == 200
    snap = resp.get_json()
    # Verify no PII
    snap_str = json.dumps(snap)
    assert "@" not in snap_str, "Snapshot contains email addresses (PII leak!)"
    assert "+61" not in snap_str, "Snapshot contains phone numbers (PII leak!)"
    print("  GET /cfo/snapshot: 200, no PII detected")
    print(f"  Snapshot keys: {list(snap.keys())}")


if __name__ == "__main__":
    tests = [
        ("Helpers", test_helpers),
        ("Stripe Pull", test_stripe),
        ("Sheets Pull", test_sheets),
        ("GHL Pull", test_ghl),
        ("Full Snapshot", test_full_snapshot),
        ("Flask App", test_flask_app),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            fn()
            print(f"  >> PASS")
            passed += 1
        except Exception as e:
            print(f"  >> FAIL: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
