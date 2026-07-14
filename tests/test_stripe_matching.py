"""
tests/test_stripe_matching.py
-----------------------------
Multi-signal Stripe↔client matcher: the 4 incident archetypes (email, name-token, distinctive
surname, common-surname ambiguity) + alias learning. Deterministic — identity index mocked.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kv_store, stripe_reconcile as sr

def _idx():
    # (contact_tokens, business, surname)
    contacts = [
        (sr._tokens("Nirosha Dushani Jayasekara"), "Nirosha Dushani Jayasekara", "jayasekara"),
        (sr._tokens("Jeni"), "Gone Burger", "jeni"),
        (sr._tokens("Glen Fitzgerald"), "62Thirty Cafe & Bar", "fitzgerald"),
        (sr._tokens("Hardeep Singh"), "Client A", "singh"),
        (sr._tokens("Satnam Singh"), "Client B", "singh"),
        (sr._tokens("Ajit Singh"), "Client C", "singh"),
    ]
    surname_map = {}
    for _t, b, s in contacts:
        surname_map.setdefault(s, set()).add(b)
    return {"by_email": {"jeni@gb.com": "Gone Burger"}, "contacts": contacts,
            "by_business": {"gone burger": "Gone Burger"}, "surname_map": surname_map}

_ROSTER = {"active": {"gone burger", "texas charcoal chicken"}, "amounts": {"gone burger": 1275.0}}

def _reset(monkeypatch):
    kv_store._MEM.clear()

def test_email_match(monkeypatch):
    _reset(monkeypatch)
    m = sr._match_payment("Jeni Arul", "jeni@gb.com", 1500, _idx(), _ROSTER)
    assert m["category"] == "existing_client_repeat" and m["business"] == "Gone Burger" and m["basis"] == "email"

def test_name_token_match(monkeypatch):
    _reset(monkeypatch)  # Nirosha Jayasekara ⊆ Nirosha Dushani Jayasekara
    m = sr._match_payment("Nirosha Jayasekara", "", 1677.5, _idx(), _ROSTER)
    assert m["confidence"] == "high" and m["business"] == "Nirosha Dushani Jayasekara" and "contact name" in m["basis"]

def test_distinctive_surname(monkeypatch):
    _reset(monkeypatch)  # Fiona FITZGERALD → unique surname → Glen's venue
    m = sr._match_payment("Fiona Fitzgerald", "", 5500, _idx(), _ROSTER)
    assert m["confidence"] == "high" and m["business"] == "62Thirty Cafe & Bar" and "surname" in m["basis"]

def test_common_surname_not_forced(monkeypatch):
    _reset(monkeypatch)  # Jagjeet Singh → 3 Singh clients, none Jagjeet → NOT auto-matched
    m = sr._match_payment("Jagjeet Singh", "", 1500, _idx(), _ROSTER)
    assert m["category"] in ("needs_review", "unrecognised")
    assert "business" not in m  # never forced to a wrong Singh

def test_first_name_plus_amount(monkeypatch):
    _reset(monkeypatch)  # "Jeni Arul Pragasam" no email, but first-name Jeni ⊆ + amount 1275 ≈ Gone Burger MRR
    m = sr._match_payment("Jeni Arul Pragasam", "", 1275, _idx(), _ROSTER)
    assert m.get("business") == "Gone Burger"  # resolved via first-name + amount corroboration

def test_unknown_payer_flags(monkeypatch):
    _reset(monkeypatch)
    m = sr._match_payment("Zebedee Quux", "no@match.com", 999, _idx(), _ROSTER)
    assert m["category"] == "unrecognised"

def test_alias_learning(monkeypatch):
    _reset(monkeypatch)
    assert "business" not in sr._match_payment("Jagjeet Singh", "", 1500, _idx(), _ROSTER)
    sr.learn_alias("Jagjeet Singh", "Masala Factory")
    m = sr._match_payment("Jagjeet Singh", "", 1500, _idx(), _ROSTER)
    assert m["business"] == "Masala Factory" and m["basis"] == "confirmed alias"
