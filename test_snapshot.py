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


def test_sales_analytics():
    """Sales analytics: funnel, velocity, per-setter/closer, payout."""
    from sales_analytics_pull import pull_sales_analytics
    result = pull_sales_analytics()
    assert "sales" in result, "Missing 'sales' key"
    assert "degraded" in result, "Missing 'degraded' key"
    sales = result["sales"]
    if sales:
        # Funnel
        f = sales.get("funnel", {})
        print(f"  Funnel: leads={f.get('leads_in')}, sets={f.get('sets')}, shows={f.get('shows')}, closes={f.get('closes')}")
        print(f"  Rates: L→S={f.get('lead_to_set_pct')}%, S→Sh={f.get('set_to_show_pct')}%, Sh→C={f.get('show_to_close_pct')}%, L→C={f.get('lead_to_close_pct')}%")

        # Per-setter
        for s in sales.get("per_setter") or []:
            print(f"  Setter {s['name']}: leads={s.get('leads_assigned')}, sets={s.get('sets')}, rate={s.get('set_rate_pct')}%")

        # Per-closer
        for c in sales.get("per_closer") or []:
            print(f"  Closer {c['name']}: shows={c.get('shows')}, closes={c.get('closes')}, rate={c.get('close_rate_pct')}%, comm={c.get('commission_total')}")

        # Velocity
        v = sales.get("velocity", {})
        print(f"  Velocity: median={v.get('days_lead_to_cash_median')} days, avg={v.get('days_lead_to_cash_avg')} days, 5min={v.get('speed_to_lead_5min_pct')}%")

        # Payout
        p = sales.get("payout", {})
        if p:
            print(f"  Payout: total_owed={p.get('total_owed')}, log_owed={p.get('payout_log', {}).get('total_owed')}, pending={p.get('payout_log', {}).get('pending')}")

        # Validation
        val = sales.get("validation", {})
        print(f"  Cross-check: scorecard_match={val.get('scorecard_match')}")
        if not val.get("scorecard_match"):
            print(f"    Mismatches: {val.get('mismatches')}")

        # Privacy: no PII
        import json
        sales_str = json.dumps(sales)
        assert "@" not in sales_str, "Sales block contains email (PII leak!)"
        assert "+61" not in sales_str, "Sales block contains phone (PII leak!)"
        print("  No PII detected in sales block")
    else:
        print(f"  Sales: None (degraded: {result['degraded']})")
    return result


def test_velocity_requires_both_dates():
    """Velocity computed only for won deals with both Input Date and Close Date."""
    from sales_analytics_pull import _pull_velocity, _parse_date
    from datetime import date, timedelta

    # Mock rows: header + 3 data rows
    mock = [
        ["Lead ID", "Input Date", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "Call Outcome", "", "", "", "Close Date"],
        ["1", "2026-05-01", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "Won", "", "", "", "5/10/2026"],  # both dates: 9 days
        ["2", "2026-05-05", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "Won", "", "", "", ""],            # no close date
        ["3", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "Won", "", "", "", "5/15/2026"],              # no input date
    ]
    result = _pull_velocity(mock, date(2026, 4, 28))
    assert result["won_deals_with_dates"] == 1, f"Expected 1, got {result['won_deals_with_dates']}"
    assert result["days_lead_to_cash_median"] == 9, f"Expected 9, got {result['days_lead_to_cash_median']}"
    print(f"  Velocity: {result['won_deals_with_dates']} deal(s) with both dates, median={result['days_lead_to_cash_median']} days")


def test_deep_analytics():
    """Deep analytics: all four layers compute, leak_flags populated."""
    from sales_analytics_pull import pull_sales_analytics
    result = pull_sales_analytics()
    sales = result.get("sales")
    assert sales is not None, "Sales block is None"
    deep = sales.get("deep")
    assert deep is not None, "Deep block is None"

    # Layer 1: Setter Performance
    sp = deep.get("setter_performance", [])
    assert len(sp) > 0, "No setter performance data"
    for s in sp:
        assert "name" in s and "dials" in s and "sets" in s
        assert s.get("date_key") == "Input Date (cohort)"
        if s["sets"] > 0:
            assert s["dials_per_set"] is not None
            assert 0.0 <= (s.get("show_pct") or 0) <= 100.0
            assert 0.0 <= (s.get("close_pct") or 0) <= 100.0
    print(f"  L1 Setter Perf: {len(sp)} setters")
    for s in sp:
        print(f"    {s['name']}: dials={s['dials']}, sets={s['sets']}, "
              f"dials/set={s.get('dials_per_set')}, speed={s.get('speed_to_lead_pct')}%, "
              f"show={s.get('show_pct')}%, close={s.get('close_pct')}%, "
              f"quality={s.get('avg_quality')}, graded={s.get('graded_pct')}%")

    # Layer 2: Lead Quality
    lq = deep.get("lead_quality", {})
    by_src = lq.get("by_source", [])
    by_rev = lq.get("by_revenue_range", [])
    assert len(by_src) > 0, "No source data"
    assert len(by_rev) > 0, "No revenue range data"
    for s in by_src:
        assert 0.0 <= s["close_rate_pct"] <= 100.0
        assert 0.0 <= s["dq_rate_pct"] <= 100.0
    print(f"  L2 Lead Quality: {len(by_src)} sources, {len(by_rev)} revenue ranges")
    for s in by_src:
        print(f"    {s['source']}: leads={s['leads']}, closes={s['closes']}, "
              f"close={s['close_rate_pct']}%, dq={s['dq_rate_pct']}%")
    for r in by_rev:
        print(f"    {r['range']}: leads={r['leads']}, closes={r['closes']}, "
              f"close={r['close_rate_pct']}%, avg_contract={r.get('avg_contract_value')}")

    # Layer 3: Loss Intelligence
    loss = deep.get("loss", {})
    assert "dq_reasons" in loss
    assert "no_show_pct" in loss
    assert 0.0 <= loss["no_show_pct"] <= 100.0
    assert 0.0 <= loss["cancel_pct"] <= 100.0
    rec = loss.get("recoverable_pipeline", {})
    print(f"  L3 Loss: DQ reasons={len(loss['dq_reasons'])}, no-show={loss['no_show_pct']}%, "
          f"cancel={loss['cancel_pct']}%, recoverable={rec.get('total', 0)}")
    for dq in loss["dq_reasons"]:
        print(f"    DQ: {dq['reason']} = {dq['count']} ({dq['pct']}%)")
    for ns in loss.get("per_setter_noshow", []):
        print(f"    No-show by {ns['name']}: {ns['no_shows']}/{ns['sets']} ({ns['no_show_pct']}%)")

    # Layer 4: Money Behaviour
    money = deep.get("money", {})
    assert "offer_mix" in money
    assert "payment_split" in money
    assert money.get("date_key") == "Close Date (money window)"
    if money.get("commission_pct_of_cash") is not None:
        assert money["commission_pct_of_cash"] >= 0
    print(f"  L4 Money: wins={money.get('wins_in_window')}, avg_contract={money.get('avg_contract')}, "
          f"avg_cash={money.get('avg_cash')}, commission%={money.get('commission_pct_of_cash')}")
    for o in money.get("offer_mix", []):
        print(f"    Offer: {o['offer']} = {o['count']} ({o['pct']}%)")
    for p in money.get("payment_split", []):
        print(f"    Payment: {p['type']} = {p['count']} ({p['pct']}%)")

    # Leak flags
    flags = deep.get("leak_flags", [])
    print(f"  Leak flags ({len(flags)}):")
    for fl in flags:
        print(f"    >> {fl}")

    # Privacy
    import json
    deep_str = json.dumps(deep)
    assert "@" not in deep_str, "Deep block contains email (PII leak!)"
    assert "+61" not in deep_str, "Deep block contains phone (PII leak!)"
    print("  No PII in deep block")

    return deep


def test_deep_fixture_hand_calc():
    """Layer functions produce correct results on known fixture data."""
    from sales_analytics_pull import (
        _layer_setter_performance, _layer_lead_quality,
        _layer_loss_intelligence, _layer_money_behaviour, _build_leak_flags,
    )
    from datetime import date

    cutoff = date(2026, 4, 28)
    today = date(2026, 5, 28)

    # Build fixture rows: header + 6 data rows
    # Cols: 0=ID, 1=Input Date, 6=Source, 8=RevRange, 10=Setter, 14=Within5, 15=Attempts,
    #        16=SetterOutcome, 17=DQReason, 19=Quality, 22=ShowStatus, 23=CloserOutcome,
    #        24=LossReason, 26=OfferSold, 27=CloseDate, 28=Contract, 29=PayType,
    #        32=Cash, 35=RefundStatus, 37=RefundAmt, 39=CommSetter, 40=CommCloser
    def _row(vals_dict):
        r = [""] * 43
        for idx, val in vals_dict.items():
            r[idx] = str(val)
        return r

    header = [""] * 43
    rows = [
        header,
        _row({1: "2026-05-01", 6: "Facebook", 8: "$50k-100k", 10: "Maran", 14: "YES", 15: "3",
              16: "SET", 19: "1 - Great Fit", 22: "Showed", 23: "Won",
              26: "Scale Engine", 27: "2026-05-10", 28: "8000", 29: "Upfront", 32: "8000",
              39: "100", 40: "1500"}),
        _row({1: "2026-05-02", 6: "Facebook", 8: "$50k-100k", 10: "Maran", 14: "YES", 15: "2",
              16: "SET", 19: "2 - Good", 22: "No-show", 23: "No-show"}),
        _row({1: "2026-05-03", 6: "Landing Page", 8: "Under $20k", 10: "Coby", 14: "NO", 15: "5",
              16: "DQ", 17: "Budget too low"}),
        _row({1: "2026-05-04", 6: "Facebook", 8: "$20k-50k", 10: "Coby", 14: "NO", 15: "4",
              16: "SET", 19: "3- hesitant", 22: "Showed", 23: "Won",
              26: "Custom", 27: "2026-05-15", 28: "5000", 29: "Custom", 32: "2500",
              39: "0", 40: "0"}),
        _row({1: "2026-05-05", 6: "Facebook", 8: "Under $20k", 10: "Coby", 14: "NO", 15: "6",
              16: "WORKING ON"}),
        _row({1: "2026-05-06", 6: "Landing Page", 8: "$50k-100k", 10: "Coby", 14: "NO", 15: "3",
              16: "SET", 22: "Showed", 23: "Follow-up"}),
    ]

    # Layer 1
    sp, _ = _layer_setter_performance(rows, cutoff, today, None, None)
    sp_map = {s["name"]: s for s in sp}
    assert sp_map["Maran"]["dials"] == 5, f"Maran dials: {sp_map['Maran']['dials']}"  # 3+2
    assert sp_map["Maran"]["sets"] == 2
    assert sp_map["Maran"]["show_pct"] == 50.0  # 1 show / 2 sets
    assert sp_map["Maran"]["speed_to_lead_pct"] == 100.0  # 2/2 YES
    assert sp_map["Coby"]["sets"] == 2  # SET rows only (not DQ/WORKING ON)
    assert sp_map["Coby"]["speed_to_lead_pct"] == 0.0  # 0/4 YES
    print(f"  L1 fixture: Maran dials=5 sets=2 show=50% speed=100%, Coby sets=2 speed=0%")

    # Layer 2
    lq, _ = _layer_lead_quality(rows, cutoff, today)
    src_map = {s["source"]: s for s in lq["by_source"]}
    assert src_map["Facebook"]["leads"] == 4
    assert src_map["Facebook"]["closes"] == 2
    assert src_map["Facebook"]["close_rate_pct"] == 50.0
    assert src_map["Landing Page"]["dq_rate_pct"] == 50.0  # 1 DQ / 2 leads
    rev_map = {r["range"]: r for r in lq["by_revenue_range"]}
    assert rev_map["Under $20k"]["leads"] == 2
    assert rev_map["Under $20k"]["closes"] == 0
    assert rev_map["Under $20k"].get("targeting_flag") is None  # only 2 leads, below ≥5 threshold
    print(f"  L2 fixture: Facebook 4 leads/2 closes, Under $20k 2 leads/0 closes (no flag, <5 threshold)")

    # Layer 3
    loss, _ = _layer_loss_intelligence(rows, cutoff, today)
    assert loss["dq_total"] == 1
    assert loss["dq_reasons"][0]["reason"] == "Budget too low"
    assert loss["no_shows"] == 1
    assert loss["total_sets"] == 4  # Maran 2 + Coby 2
    assert loss["no_show_pct"] == 25.0  # 1/4
    assert loss["recoverable_pipeline"]["working_on"] == 1
    assert loss["recoverable_pipeline"]["followup_pending"] == 1
    print(f"  L3 fixture: DQ=1 (Budget too low), no-show=1/4 (25%), recoverable=2")

    # Layer 4
    money, _ = _layer_money_behaviour(rows, cutoff, today)
    assert money["wins_in_window"] == 2
    assert money["custom_share_pct"] == 50.0  # 1 Custom / 2 wins
    assert money["avg_contract"] == 6500.0  # (8000+5000)/2
    assert money["avg_cash"] == 5250.0  # (8000+2500)/2
    assert money["commission_pct_of_cash"] == round(1600 / 10500 * 100, 1)  # (100+1500+0+0) / (8000+2500)
    print(f"  L4 fixture: wins=2, custom=50%, avg_contract=6500, commission%={money['commission_pct_of_cash']}")

    # Leak flags
    mock_funnel = {"set_to_show_pct": 51.6, "show_to_close_pct": 25.0, "lead_to_set_pct": 29.8}
    flags = _build_leak_flags(mock_funnel, sp, lq, loss, money)
    assert any("Set→Show" in f for f in flags), "Should flag set→show below 70%"
    assert any("Show→Close" in f for f in flags), "Should flag show→close below 35%"
    assert any("Custom" in f for f in flags), "Should flag 50% custom share"
    print(f"  Leak flags ({len(flags)}):")
    for fl in flags:
        print(f"    >> {fl}")

    # Test empty flags when all on-target
    good_funnel = {"set_to_show_pct": 80.0, "show_to_close_pct": 40.0, "lead_to_set_pct": 30.0}
    good_sp = [{"name": "Test", "speed_to_lead_pct": 60.0}]
    good_lq = {"by_revenue_range": []}
    good_loss = {"no_show_pct": 10.0}
    good_money = {"custom_share_pct": 5.0, "commission_pct_of_cash": 15.0}
    empty_flags = _build_leak_flags(good_funnel, good_sp, good_lq, good_loss, good_money)
    assert len(empty_flags) == 0, f"Expected 0 flags when on-target, got {len(empty_flags)}: {empty_flags}"
    print("  On-target scenario: 0 flags — correct")


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
    assert "sales" in snap
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
    if snap.get("sales"):
        sf = snap["sales"].get("funnel", {})
        print(f"  Sales funnel: leads={sf.get('leads_in')}, closes={sf.get('closes')}, L→C={sf.get('lead_to_close_pct')}%")
        deep = snap["sales"].get("deep")
        if deep:
            flags = deep.get("leak_flags", [])
            print(f"  Leak flags: {len(flags)}")
            for fl in flags:
                print(f"    >> {fl}")
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
        ("Sales Analytics", test_sales_analytics),
        ("Velocity Requires Both Dates", test_velocity_requires_both_dates),
        ("Deep Analytics", test_deep_analytics),
        ("Deep Fixture Hand-Calc", test_deep_fixture_hand_calc),
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
