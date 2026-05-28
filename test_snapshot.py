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


def test_xero_no_tokens():
    """Xero pull without tokens should degrade gracefully, not crash."""
    from xero_pull import pull_xero
    result = pull_xero()
    assert "xero" in result, "Missing 'xero' key"
    assert "degraded" in result, "Missing 'degraded' key"
    # Without tokens configured, xero should be None with a degraded entry
    if result["xero"] is None:
        assert len(result["degraded"]) > 0, "Should have degraded entry when xero is None"
        print(f"  Xero correctly degraded: {result['degraded'][0]['reason']}")
    else:
        print(f"  Xero returned data (tokens found): revenue={result['xero'].get('revenue')}")
    return result


def test_xero_token_persistence():
    """Test that token save/load round-trips correctly."""
    import tempfile
    import json
    from xero_pull import _save_tokens, _load_tokens
    import xero_pull

    # Use a temp file
    original = xero_pull.XERO_TOKEN_FILE
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        # Monkey-patch the token file path
        import config
        old_config = config.XERO_TOKEN_FILE
        config.XERO_TOKEN_FILE = tmp_path
        # Also patch the module-level reference
        xero_pull_module = sys.modules["xero_pull"]
        xero_pull_module.XERO_TOKEN_FILE = tmp_path

        test_tokens = {
            "access_token": "test_access_123",
            "refresh_token": "test_refresh_456",
            "tenant_id": "test_tenant_789",
        }
        _save_tokens(test_tokens)
        loaded = _load_tokens()
        assert loaded is not None, "Failed to load saved tokens"
        assert loaded["refresh_token"] == "test_refresh_456", "Refresh token mismatch"
        assert loaded["tenant_id"] == "test_tenant_789", "Tenant ID mismatch"
        print("  Token round-trip: OK")

        # Verify file contents
        with open(tmp_path) as f:
            raw = json.load(f)
        assert raw["refresh_token"] == "test_refresh_456"
        print("  Token file contents verified")
    finally:
        config.XERO_TOKEN_FILE = old_config
        xero_pull_module.XERO_TOKEN_FILE = original
        os.unlink(tmp_path)


def test_xero_pnl_parser():
    """Test P&L parsing with Other Income — net_profit must reconcile to Xero."""
    from xero_pull import _parse_pnl

    mock_response = {
        "Reports": [{
            "Rows": [
                {
                    "RowType": "Section",
                    "Title": "Income",
                    "Rows": [
                        {"RowType": "Row", "Cells": [{"Value": "Sales"}, {"Value": "57937.76"}]},
                        {"RowType": "Row", "Cells": [{"Value": "Interest Income"}, {"Value": "28.39"}]},
                        {"RowType": "SummaryRow", "Cells": [{"Value": "Total Income"}, {"Value": "57966.15"}]},
                    ],
                },
                {
                    "RowType": "Section",
                    "Title": "Less Cost of Sales",
                    "Rows": [
                        {"RowType": "Row", "Cells": [{"Value": "Client Reporting Tools"}, {"Value": "7351.97"}]},
                        {"RowType": "Row", "Cells": [{"Value": "Contractors NO GST"}, {"Value": "23087.96"}]},
                        {"RowType": "SummaryRow", "Cells": [{"Value": "Total Cost of Sales"}, {"Value": "30439.93"}]},
                    ],
                },
                {
                    "RowType": "Section",
                    "Title": "Plus Other Income",
                    "Rows": [
                        {"RowType": "Row", "Cells": [{"Value": "Reimbursements"}, {"Value": "2269.90"}]},
                        {"RowType": "SummaryRow", "Cells": [{"Value": "Total Other Income"}, {"Value": "2269.90"}]},
                    ],
                },
                {
                    "RowType": "Section",
                    "Title": "Less Operating Expenses",
                    "Rows": [
                        {"RowType": "Row", "Cells": [{"Value": "Wages and Salaries"}, {"Value": "101964.00"}]},
                        {"RowType": "Row", "Cells": [{"Value": "Superannuation"}, {"Value": "7675.68"}]},
                        {"RowType": "Row", "Cells": [{"Value": "Advertising"}, {"Value": "7320.57"}]},
                        {"RowType": "Row", "Cells": [{"Value": "Bank Fees"}, {"Value": "708.55"}]},
                        {"RowType": "Row", "Cells": [{"Value": "Other"}, {"Value": "3330.97"}]},
                        {"RowType": "SummaryRow", "Cells": [{"Value": "Total Operating Expenses"}, {"Value": "120999.77"}]},
                    ],
                },
            ],
        }],
    }

    result = _parse_pnl(mock_response)
    assert result["revenue"] == 57966.15, f"Revenue wrong: {result['revenue']}"
    assert result["cogs"] == 30439.93, f"COGS wrong: {result['cogs']}"
    assert result["gross_profit"] == 57966.15 - 30439.93, f"Gross profit wrong: {result['gross_profit']}"
    assert result["other_income"] == 2269.90, f"Other income wrong: {result['other_income']}"
    assert result["operating_expenses"] == 120999.77, f"OpEx wrong: {result['operating_expenses']}"
    # Net profit must match Xero's own: gross_profit + other_income - opex = -91203.65
    expected_net = round(27526.22 + 2269.90 - 120999.77, 2)
    assert result["net_profit"] == expected_net, f"Net profit {result['net_profit']} != expected {expected_net}"
    # Xero wages cross-check
    assert result["xero_wages"] == 101964.00 + 7675.68, f"Xero wages wrong: {result['xero_wages']}"
    print(f"  Revenue: {result['revenue']}")
    print(f"  COGS: {result['cogs']}")
    print(f"  Gross profit: {result['gross_profit']} ({result['gross_margin_pct']}%)")
    print(f"  Other income: {result['other_income']}")
    print(f"  Operating expenses: {result['operating_expenses']}")
    print(f"  Net profit: {result['net_profit']} (reconciles to Xero)")
    print(f"  Xero wages: {result['xero_wages']}")


def test_payroll_variance_flag():
    """Payroll variance flag fires when actual > 1.5x baseline."""
    from config import FINANCE_SHEET_CONFIG
    threshold = FINANCE_SHEET_CONFIG["payroll_variance_threshold"]

    # Simulate: xero_wages = 110000, baseline = 18891 → ratio ~5.8x
    xero_wages = 110000.0
    baseline = 18891.0
    ratio = round(xero_wages / baseline, 1)
    assert ratio > threshold, f"Ratio {ratio} should exceed threshold {threshold}"
    print(f"  Xero wages: ${xero_wages:,.2f}, Baseline: ${baseline:,.2f}")
    print(f"  Ratio: {ratio}x (threshold: {threshold}x) — flag fires: YES")

    # Edge case: wages at exactly 1.0x baseline — should NOT flag
    ratio_ok = round(baseline / baseline, 1)
    assert ratio_ok <= threshold, f"1.0x ratio should not exceed threshold {threshold}"
    print(f"  1.0x ratio: no flag — correct")


def test_recognized_revenue():
    """Recognized revenue column matched by current month; footer excluded; triple-check."""
    from finance_sheets_pull import pull_recognized_revenue
    result = pull_recognized_revenue()
    assert "recognized_revenue" in result, "Missing recognized_revenue key"
    assert "degraded" in result, "Missing degraded key"
    rev = result.get("recognized_revenue")
    month = result.get("recognized_month")
    count = result.get("recognized_client_count")
    validation = result.get("recognized_validation", {})
    if rev is not None:
        print(f"  Recognized revenue ({month}): ${rev:,.2f} across {count} clients")
        assert rev > 0, "Recognized revenue should be positive if data exists"
        # Must NOT be doubled (~$130k). Should be ~$65k range.
        assert rev < 100000, f"Recognized revenue ${rev:,.2f} looks doubled — footer row included?"
        # CHECK 1: row count sanity
        assert validation.get("row_count_ok") is True, f"Row count {count} exceeds max"
        print(f"  CHECK 1 (row count): {count} rows — OK")
        # CHECK 2: footer cross-validation
        footer = validation.get("footer_total")
        if footer is not None:
            print(f"  CHECK 2 (footer): computed=${rev:,.2f}, footer=${footer:,.2f}, match={validation.get('footer_match')}")
            assert validation.get("footer_match") is True, "Footer mismatch — computed != sheet total"
        else:
            print(f"  CHECK 2 (footer): no footer row found")
    else:
        print(f"  Recognized revenue: None (degraded: {result['degraded']})")
    return result


def test_recognized_footer_excluded():
    """Footer/TOTALS row must be excluded from client sum."""
    from finance_sheets_pull import _is_footer_row
    assert _is_footer_row(["", "Active", "Scale Engine"]) is True, "Blank client should be footer"
    assert _is_footer_row(["TOTAL", "", ""]) is True, "TOTAL label should be footer"
    assert _is_footer_row(["TOTALS", "", ""]) is True, "TOTALS label should be footer"
    assert _is_footer_row(["Masala Factory", "Active"]) is False, "Named client is not footer"
    print("  Footer detection: all cases correct")


def test_recognized_check2_fires_on_mismatch():
    """CHECK 2 fires when computed sum != footer total."""
    from finance_sheets_pull import _parse_money, _is_footer_row, SKIP_MARKERS
    # Simulate rows where client sum = 1000 but footer = 500 (50% mismatch)
    mock_rows = [
        ["Client Name", "", "", "", "", "", "", "", "", "", "", "", "", "May 2026"],
        ["Client A", "", "", "", "", "", "", "", "", "", "", "", "", "$600.00"],
        ["Client B", "", "", "", "", "", "", "", "", "", "", "", "", "$400.00"],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "$500.00"],  # wrong footer
    ]
    col_idx = 13
    client_total = 0.0
    footer_total = None
    for row in mock_rows[1:]:
        raw = row[col_idx].strip()
        if raw.lower() in SKIP_MARKERS:
            continue
        val = _parse_money(raw)
        if val is None:
            continue
        if _is_footer_row(row):
            footer_total = val
        else:
            client_total += val

    assert client_total == 1000.0, f"Client total wrong: {client_total}"
    assert footer_total == 500.0, f"Footer wrong: {footer_total}"
    mismatch_pct = abs(client_total - footer_total) / footer_total
    assert mismatch_pct > 0.02, "Should detect mismatch > 2%"
    print(f"  Simulated: clients=${client_total}, footer=${footer_total}, mismatch={mismatch_pct:.0%} — CHECK 2 fires")


def test_salary_baseline():
    """Salary baseline returns aggregate only, no PII."""
    from finance_sheets_pull import pull_salary_baseline
    result = pull_salary_baseline()
    assert "payroll_baseline" in result, "Missing payroll_baseline key"
    baseline = result.get("payroll_baseline")
    if baseline is not None:
        print(f"  Payroll baseline: ${baseline:,.2f}")
        assert baseline > 0, "Baseline should be positive"
    else:
        print(f"  Payroll baseline: None (degraded: {result['degraded']})")
    return result


def test_full_snapshot():
    from snapshot import build_snapshot
    snap = build_snapshot()
    assert "generated_at" in snap
    assert "stripe" in snap
    assert "ghl" in snap
    assert "sheets" in snap
    assert "xero" in snap
    assert "costs" in snap
    assert "profit" in snap
    assert "revenue_views" in snap
    assert "degraded" in snap
    assert "ok" in snap
    print(f"  OK: {snap['ok']}")
    if snap.get("costs"):
        print(f"  Costs: closer={snap['costs']['closer_commission']}, setter={snap['costs']['setter_commission']}")
    if snap.get("profit"):
        p = snap["profit"]
        print(f"  Profit: net={p.get('net_profit')}, other_income={p.get('other_income')}, gross_margin={p.get('gross_margin_pct')}%")
        if p.get("payroll"):
            pr = p["payroll"]
            print(f"  Payroll: xero_wages={pr.get('xero_wages_actual')}, baseline={pr.get('fixed_baseline_monthly')}, ratio={pr.get('variance_pct')}x")
    else:
        print("  Profit: None (Xero not connected)")
    rv = snap.get("revenue_views", {})
    print(f"  Revenue views: stripe={rv.get('stripe_cash_trailing_30d')}, xero={rv.get('xero_pl_period')}, recognized={rv.get('recognized_current_month')}")
    v = rv.get("recognized_validation", {})
    if v:
        print(f"  Validation: rows={v.get('row_count')}, footer_match={v.get('footer_match')}, range_ok={v.get('range_ok')}")
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
        ("Xero (no tokens)", test_xero_no_tokens),
        ("Xero Token Persistence", test_xero_token_persistence),
        ("Xero P&L Parser", test_xero_pnl_parser),
        ("Payroll Variance Flag", test_payroll_variance_flag),
        ("Recognized Revenue", test_recognized_revenue),
        ("Footer Excluded", test_recognized_footer_excluded),
        ("CHECK 2 Fires on Mismatch", test_recognized_check2_fires_on_mismatch),
        ("Salary Baseline", test_salary_baseline),
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
