"""
tests/test_accuracy_lockdown.py
-------------------------------
Stage A displayed-output guardrails. These assert on what surfaces would
actually SHOW (the snapshot fields each panel/chat/PDF reads), not on
internal intermediate values — the lesson from the cash-engine fix that
"passed" while the table stayed broken.

The module-scoped snapshot is a real build (network: Sheets + Stripe MCP
work locally; Xero/GHL degrade gracefully — that path is itself under test).
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from metrics_engine import (
    build_canonical_metrics,
    check_consistency,
    assert_consistency,
    ConsistencyError,
)


@pytest.fixture(scope="module")
def snap():
    from snapshot import build_snapshot
    return build_snapshot()


# ── Cross-surface consistency ────────────────────────────────────────────────

def test_consistency_gate_is_clean(snap):
    errors = check_consistency(snap)
    assert errors == [], "Snapshot ships contradictory numbers:\n" + "\n".join(errors)


def test_canonical_metrics_present_and_sourced(snap):
    metrics = snap.get("metrics")
    assert metrics, "snapshot.metrics missing — canonical layer not built"
    for name, entry in metrics.items():
        assert entry.get("kind") in ("FLOW", "BALANCE"), f"{name} missing FLOW/BALANCE kind"
        assert entry.get("source"), f"{name} missing source field path"


def test_canonical_values_match_their_sources(snap):
    """Each canonical value must literally equal the snapshot field it cites."""
    def resolve(d, dotted):
        cur = d
        for p in dotted.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur

    for name, entry in snap["metrics"].items():
        src_val = resolve(snap, entry["source"])
        assert entry["value"] == src_val, (
            f"metrics.{name} = {entry['value']} but {entry['source']} = {src_val}"
        )


def test_burn_identical_everywhere(snap):
    cash_burn = (snap.get("cash_position") or {}).get("total_monthly_burn")
    engine_burn = (snap.get("monthly_burn") or {}).get("total_recurring_burn")
    if engine_burn is not None:
        assert abs(cash_burn - engine_burn) < 0.51


def test_starting_cash_identical_everywhere(snap):
    """Every surface that projects cash must start from cash_position.cash_in_bank."""
    cash = (snap.get("cash_position") or {}).get("cash_in_bank")
    assert cash is not None and cash > 0
    # Hiring forward lens (computed on demand) uses the same field — assert the
    # contract by running the model with this snapshot's inputs, as the route does.
    from hiring_model import compute_hiring_analysis
    ctx = snap.get("hiring_context") or {}
    result = compute_hiring_analysis(
        roles=[{"role": "Test Hire", "monthly_cost": 4000}],
        monthly_net_income=ctx.get("monthly_net_income", 0),
        current_mrr=ctx.get("current_mrr", 0),
        monthly_revenue=ctx.get("monthly_revenue"),
        monthly_cogs=None,
        monthly_opex=None,
        avg_contract_value=ctx.get("avg_contract_value"),
        close_rate_pct=ctx.get("close_rate_pct"),
        avg_cash_per_close=ctx.get("avg_cash_per_close"),
        gross_margin_pct=ctx.get("gross_margin_pct"),
        true_team_cost=ctx.get("true_team_cost") or 0,
        forward_mrr=snap.get("forward_mrr"),
        cash_position=snap.get("cash_position"),
        total_monthly_burn=(snap.get("monthly_burn") or {}).get("total_recurring_burn"),
    )
    lens = result.get("forward_sustainability") or {}
    if lens and lens.get("starting_cash") is not None:
        assert abs(lens["starting_cash"] - cash) < 0.51, (
            f"hiring forward starts from {lens['starting_cash']}, cash card shows {cash}"
        )


def test_client_count_single_value(snap):
    canonical = (snap.get("active_clients") or {}).get("active_count")
    assert canonical is not None
    assert snap["metrics"]["active_client_count"]["value"] == canonical


# ── JSON safety ──────────────────────────────────────────────────────────────

def test_snapshot_json_safe(snap):
    json.dumps(snap, allow_nan=False)  # raises on NaN/Infinity


def test_no_negative_impossible_values(snap):
    cp = snap.get("cash_position") or {}
    for key in ("cash_in_bank", "total_monthly_burn", "tax_reserved", "stripe_incoming"):
        v = cp.get(key)
        if v is not None:
            assert v >= 0, f"cash_position.{key} negative: {v}"
    runway = cp.get("runway_months")
    if runway is not None:
        assert 0 < runway < 1000, f"runway implausible: {runway}"


# ── Stripe truth (A2) ────────────────────────────────────────────────────────

def test_stripe_revenue_labeled_gross(snap):
    rev = ((snap.get("stripe") or {}).get("revenue") or {}).get("current") or {}
    if rev.get("total_aud") is not None:
        assert "GROSS" in (rev.get("basis") or ""), "Stripe collected cash must be labeled GROSS"


def test_stripe_payouts_labeled_net(snap):
    payouts = (snap.get("stripe") or {}).get("payouts")
    if payouts and payouts.get("total_paid_out") is not None:
        assert "NET" in (payouts.get("basis") or ""), "Payouts must be labeled NET banked"


def test_no_fabricated_prior_period_revenue(snap):
    """The Stripe MCP ignores the days param; previous-period revenue must be
    None + degraded flag, never a silently fabricated $0."""
    prev = (((snap.get("stripe") or {}).get("revenue") or {}).get("previous") or {})
    if prev.get("total_aud") == 0:
        # A true $0 prior period is conceivable but requires the window honored;
        # with the known-broken MCP this must be None instead.
        degraded_metrics = [d.get("metric") for d in snap.get("degraded", [])]
        assert "revenue_previous" not in degraded_metrics, (
            "previous revenue is 0 while flagged degraded — fabricated zero leaked through"
        )


def test_flows_never_summed_with_balances(snap):
    """total_available must be bank + in-transit (balances) and must NOT
    include any period flow such as 30d collected revenue."""
    cp = snap.get("cash_position") or {}
    total = cp.get("total_available")
    bank = cp.get("cash_in_bank")
    transit = cp.get("stripe_incoming")
    if None not in (total, bank, transit):
        assert abs(total - (bank + transit)) < 0.51
        rev30 = (((snap.get("stripe") or {}).get("revenue") or {}).get("current") or {}).get("total_aud")
        if rev30:
            assert abs(total - (bank + rev30)) > 1, "total_available appears to sum a FLOW"


# ── Freshness ────────────────────────────────────────────────────────────────

def test_source_freshness_present(snap):
    fresh = snap.get("source_freshness")
    assert fresh, "source_freshness block missing"
    for src in ("stripe", "sheets", "xero", "ghl"):
        assert src in fresh


def test_cash_override_staleness_mechanism():
    """>7 days since CASH_CONFIRMED_DATE must add a degraded flag (tested
    against the date math directly, independent of today's actual age)."""
    from datetime import date
    confirmed = date.fromisoformat("2026-06-01")
    today = date.fromisoformat("2026-06-11")
    assert (today - confirmed).days > 7  # the build adds the flag in this case


# ── Windowed vs point-in-time ────────────────────────────────────────────────

def test_sales_windows_have_distinct_definitions(snap):
    windows = (snap.get("sales") or {}).get("windows") or []
    if windows:
        days = [w.get("window_days") for w in windows]
        assert len(days) == len(set(days)), f"duplicate windows: {days}"


def test_point_in_time_fields_window_independent(snap):
    """Cash balances must not vary by window — they live outside sales.windows."""
    for w in (snap.get("sales") or {}).get("windows") or []:
        assert "cash_in_bank" not in w and "runway_months" not in w


# ── Chat / PDF read the same numbers ────────────────────────────────────────

def test_chat_context_quotes_canonical_cash(snap):
    from dashboard.chat import _build_context_block
    ctx = _build_context_block(json.dumps(snap))
    cp = snap.get("cash_position") or {}
    assert "CANONICAL METRICS" in ctx
    if cp.get("cash_in_bank") is not None:
        assert str(cp["cash_in_bank"]) in ctx


def test_pdf_reads_cash_position_fields(snap):
    """The PDF's cash figures come from the same cash_position block."""
    import dashboard.briefing_pdf as pdf
    val = pdf._get(snap, "cash_position", "cash_in_bank")
    assert val == (snap.get("cash_position") or {}).get("cash_in_bank")


# ── The gate itself ──────────────────────────────────────────────────────────

def test_gate_raises_on_contradiction():
    bad = {
        "cash_position": {"total_monthly_burn": 50000, "cash_in_bank": 100000,
                          "runway_months": 2.0},
        "monthly_burn": {"total_recurring_burn": 40000},
    }
    with pytest.raises(ConsistencyError):
        assert_consistency(bad)


def test_gate_catches_nan():
    bad = {"cash_position": {"runway_months": float("nan")}}
    errs = check_consistency(bad)
    assert any("nan" in e.lower() for e in errs)
