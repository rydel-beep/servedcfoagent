"""
tests/test_active_clients.py
-----------------------------
Tests for derived active-client logic.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from active_clients import derive_active_clients, _names_match, _is_churned


# ── Name matching ─────────────────────────────────────────────

def test_exact_match():
    assert _names_match("Gone Burger", "Gone Burger")


def test_case_insensitive():
    assert _names_match("gone burger", "Gone Burger")


def test_apostrophe_variants():
    assert _names_match("Butler's Cucina", "Butlers cucina")


def test_accent_match():
    assert _names_match("Monty's Fusions Café", "Monty's Fusions")


def test_prefix_match():
    assert _names_match("Nonnas", "Nonnas Pizzeria and Cucina")


def test_substring_match():
    assert _names_match("Blue Bells", "Bluebells Takeaway")


def test_no_false_positive():
    assert not _names_match("At Thai", "Chiangmai Thai")


def test_short_names_no_false_positive():
    assert not _names_match("At", "Cat")


# ── Churned detection ─────────────────────────────────────────

def test_churned_exact():
    assert _is_churned("Riverloop Cafe")


def test_churned_prefix():
    assert _is_churned("Nonnas Pizzeria and Cucina")


def test_not_churned():
    assert not _is_churned("Gone Burger")


def test_churned_bunni():
    assert _is_churned("Bunni Beez")


# ── derive_active_clients ─────────────────────────────────────

def _health(name, mrr=2000, status="Active"):
    return {"name": name, "status": status, "package": "sc", "current_mrr": mrr, "next_mrr": mrr}


def _won(biz, contract=12000, cash=6000, close_date="2026-05-15"):
    return {"business": biz, "close_date": close_date, "contract": contract, "cash": cash, "offer": "Scale Engine"}


def test_both_agree_is_active():
    """Client in both Health tab and Won deals → active, sources_agree True."""
    result = derive_active_clients(
        health_clients=[_health("Gone Burger")],
        won_deals=[_won("Gone Burger")],
    )
    assert result["active_count"] == 1
    assert result["active"][0]["sources_agree"] is True
    assert result["active"][0]["contract_value"] == 12000


def test_health_only_legacy():
    """Client in Health tab but no Won deal → legacy, still active."""
    result = derive_active_clients(
        health_clients=[_health("At Thai")],
        won_deals=[],
    )
    assert result["active_count"] == 1
    assert result["active"][0]["sources_agree"] == "legacy"
    assert result["legacy_pre_tracker"] == 1


def test_won_only_discrepancy():
    """Client Won in LTC but not in Health → active with discrepancy."""
    result = derive_active_clients(
        health_clients=[],
        won_deals=[_won("DANKA Cafe and Lounge", contract=14500, cash=6500)],
    )
    assert result["active_count"] == 1
    assert result["pending_health_update"] == 1
    assert len(result["discrepancies"]) == 1
    assert "not yet in Health tab" in result["discrepancies"][0]["reason"]
    assert result["active"][0]["contract_value"] == 14500


def test_churned_excluded():
    """Churned client excluded even if in both sources."""
    result = derive_active_clients(
        health_clients=[_health("Riverloop Cafe", mrr=0)],
        won_deals=[_won("Riverloop Cafe")],
    )
    assert result["active_count"] == 0
    assert "Riverloop Cafe" in result["churned_excluded"]


def test_churned_with_lingering_health():
    """Churned client in Health tab only → excluded."""
    result = derive_active_clients(
        health_clients=[_health("Bunni Beez", mrr=0)],
        won_deals=[],
    )
    assert result["active_count"] == 0
    assert "Bunni Beez" in result["churned_excluded"]


def test_zero_mrr_flagged():
    """Active client with $0 MRR → still active but flagged."""
    result = derive_active_clients(
        health_clients=[_health("Pottery Green Bakers Gordon", mrr=0)],
        won_deals=[],
    )
    assert result["active_count"] == 1
    assert result["active"][0]["mrr_flag"] == "active_zero_mrr"
    assert len(result["discrepancies"]) == 1


def test_five_new_clients():
    """The 5 new clients appear correctly."""
    new_clients = [
        _won("CASA de Amor Mexican bar and kitchen", 14500, 8305, "2026-05-29"),
        _won("Masala Factory", 14500, 7975, "2026-05-25"),
        _won("DANKA Cafe and Lounge", 14500, 6500, "2026-05-13"),
        _won("Dcthai", 15100, 8305, "2026-05-22"),
        _won("Rung Brisbane", 14500, 13750, "2026-04-30"),
    ]
    result = derive_active_clients(
        health_clients=[_health("Gone Burger"), _health("At Thai")],
        won_deals=new_clients + [_won("Gone Burger")],
    )
    assert result["active_count"] == 7  # 2 health + 5 new
    assert result["pending_health_update"] == 5
    assert len(result["discrepancies"]) == 5
    new_names = {d["name"] for d in result["discrepancies"]}
    assert "Rung Brisbane" in new_names
    assert "Dcthai" in new_names


def test_name_normalisation_dcthai():
    """DC Thai / Dcthai matching."""
    result = derive_active_clients(
        health_clients=[_health("Dcthai", mrr=2500)],
        won_deals=[_won("Dcthai", 15100, 8305)],
    )
    assert result["active_count"] == 1
    assert result["confirmed_both_sources"] == 1


def test_stripe_validation():
    """Stripe MRR validation is included when provided."""
    result = derive_active_clients(
        health_clients=[_health("Test Client", mrr=3000)],
        won_deals=[],
        stripe_mrr=57000.0,
    )
    sv = result["stripe_validation"]
    assert sv is not None
    assert sv["derived_mrr"] == 3000.0
    assert sv["stripe_mrr"] == 57000.0
    assert sv["gap"] == 54000.0


def test_confidence_high():
    """No discrepancies → high confidence."""
    result = derive_active_clients(
        health_clients=[_health("Test")],
        won_deals=[_won("Test")],
    )
    assert result["confidence"] == "high"


def test_confidence_low():
    """Many discrepancies → low confidence."""
    result = derive_active_clients(
        health_clients=[],
        won_deals=[_won(f"Client {i}") for i in range(5)],
    )
    assert result["confidence"] == "low"


# ── Estimated MRR from contract ──────────────────────────────

def test_estimated_mrr_from_contract():
    """Won-only client gets estimated_mrr = contract / 6."""
    result = derive_active_clients(
        health_clients=[],
        won_deals=[_won("New Client", contract=14500)],
    )
    client = result["active"][0]
    assert client["estimated_mrr"] == round(14500 / 6, 2)
    assert client["awaiting_stripe"] is True
    assert client["mrr_source"] == "estimated_from_contract"


def test_projected_mrr_includes_estimated():
    """projected_mrr = confirmed + estimated."""
    result = derive_active_clients(
        health_clients=[_health("Existing", mrr=3000)],
        won_deals=[_won("New Deal", contract=12000)],
    )
    assert result["confirmed_mrr"] == 3000.0
    assert result["estimated_mrr"] == 2000.0
    assert result["projected_mrr"] == 5000.0


def test_confirmed_client_not_awaiting_stripe():
    """Health tab client is not marked as awaiting Stripe."""
    result = derive_active_clients(
        health_clients=[_health("Confirmed")],
        won_deals=[_won("Confirmed")],
    )
    assert result["active"][0]["awaiting_stripe"] is False
    assert result["active"][0]["estimated_mrr"] is None
