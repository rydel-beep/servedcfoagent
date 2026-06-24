"""
tests/test_refresh_health.py
----------------------------
The header pill must be GREEN when core sources are healthy and RED only on a
genuine core-source failure — not on the always-present optional/known degradations
(Xero/GHL unconfigured, Stripe-MCP limits, bookkeeping data-quality flags).
Regression guard for the "always red" bug (2026-06-24 audit).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from metrics_engine import classify_refresh_health, OPTIONAL_DEGRADED_METRICS


# The exact steady-state degraded set from a HEALTHY day (2026-06-19): 12 entries,
# all optional. This MUST classify green or the pill is always-red again.
HEALTHY_STEADY_STATE = [
    "revenue_previous", "customer_count", "stripe_mrr_subs_mismatch", "ghl_pipeline",
    "closer_commission", "setter_commission", "won_but_unlogged", "xero",
    "funnel_cross_check", "client_reconciliation", "zero_mrr_active_clients",
    "cash_override_stale",
]


def test_healthy_steady_state_is_green():
    rh = classify_refresh_health([{"metric": m} for m in HEALTHY_STEADY_STATE])
    assert rh["status"] == "green"
    assert rh["core_failures"] == []
    assert len(rh["optional_degraded"]) == len(HEALTHY_STEADY_STATE)


def test_all_steady_state_metrics_are_classified_optional():
    for m in HEALTHY_STEADY_STATE:
        assert m in OPTIONAL_DEGRADED_METRICS, f"{m} would wrongly trip the pill red"


def test_health_tab_401_is_red():
    # Finance sheet 401 → core source failures.
    degraded = [{"metric": m} for m in HEALTHY_STEADY_STATE] + [
        {"metric": "client_health"}, {"metric": "payroll_baseline"},
        {"metric": "recognized_revenue"},
        {"metric": "client_roster_source", "severity": "core"},
    ]
    rh = classify_refresh_health(degraded)
    assert rh["status"] == "red"
    assert "client_health" in rh["core_failures"]
    assert "client_roster_source" in rh["core_failures"]


def test_stripe_mcp_down_is_red():
    rh = classify_refresh_health([{"metric": "mrr"}, {"metric": "subscriptions"}])
    assert rh["status"] == "red"


def test_clean_snapshot_is_green():
    assert classify_refresh_health([])["status"] == "green"
    assert classify_refresh_health(None)["status"] == "green"


def test_explicit_severity_overrides():
    # An entry explicitly tagged core trips red even if its name is unknown.
    assert classify_refresh_health([{"metric": "novel", "severity": "core"}])["status"] == "red"
    # An entry explicitly tagged optional stays green even if its name is unknown.
    assert classify_refresh_health([{"metric": "novel", "severity": "optional"}])["status"] == "green"


def test_unclassified_defaults_to_core():
    # A brand-new unexpected failure must be visible (red), not silently swallowed.
    assert classify_refresh_health([{"metric": "totally_new_failure"}])["status"] == "red"
