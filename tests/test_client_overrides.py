"""
tests/test_client_overrides.py
------------------------------
Churn/downgrade overrides: apply-to-roster math, client matching, money parsing, the
confirmation echo, and the Piolo queue. The Postgres store is mocked (live write-path
verified on the deployed app).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import client_overrides as co

_ROSTER = [
    {"name": "Hono Grill", "current_mrr": 3050, "status": "Active"},
    {"name": "Naan Sense", "current_mrr": 3050, "status": "Active"},
    {"name": "The Cally Hotel", "current_mrr": 3050, "status": "Active"},
]


def test_apply_churn_and_downgrade():
    co_map = {"honogrill": {"client_name": "Hono Grill", "change_type": "churn"},
              "naansense": {"client_name": "Naan Sense", "change_type": "downgrade", "new_mrr": 1500}}
    import types
    # monkeypatch active_map via a stub
    orig = co.active_map
    co.active_map = lambda: co_map
    try:
        clients, mrr_delta, active_delta = co.apply_to_clients([dict(c) for c in _ROSTER])
        names = [c["name"] for c in clients]
        assert "Hono Grill" not in names                 # churned → dropped
        assert active_delta == -1
        naan = next(c for c in clients if c["name"] == "Naan Sense")
        assert naan["current_mrr"] == 1500               # downgraded
        assert mrr_delta == (-3050) + (1500 - 3050)      # churn -3050, downgrade -1550
    finally:
        co.active_map = orig


def test_match(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: _ROSTER)
    assert [c["name"] for c in co._match("Hono Grill")] == ["Hono Grill"]
    assert [c["name"] for c in co._match("hono")] == ["Hono Grill"]      # substring
    assert co._match("Nonexistent Cafe") == []


def test_money():
    assert co._money("1500") == 1500 and co._money("$1,500") == 1500 and co._money("1.5k") == 1500


def test_churn_confirmation_echo(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: _ROSTER)
    pend = {}
    monkeypatch.setattr(co, "_get_pending", lambda tok: pend.get(tok))
    monkeypatch.setattr(co, "_set_pending", lambda tok, p: pend.__setitem__(tok, p))
    reply, handled = co.handle_client_writeback_command("mark Hono Grill as churned", "tok")
    assert handled and "Hono Grill" in reply and "CHURNED" in reply and "confirm" in reply.lower()
    assert pend["tok"]["change_type"] == "churn" and pend["tok"]["old_mrr"] == 3050


def test_downgrade_needs_amount(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: _ROSTER)
    monkeypatch.setattr(co, "_get_pending", lambda tok: None)
    monkeypatch.setattr(co, "_set_pending", lambda tok, p: None)
    r, h = co.handle_client_writeback_command("downgrade Naan Sense to 1500", "tok")
    assert h and "Naan Sense" in r and "1,500" in r and "confirm" in r.lower()
    # ambiguous / missing amount
    r2, _ = co.handle_client_writeback_command("downgrade Naan Sense", "tok")
    assert "what MRR" in r2 or "new monthly" in r2


def test_piolo_queue(monkeypatch):
    monkeypatch.setattr(co, "active_overrides", lambda: [
        {"client_name": "Hono Grill", "change_type": "churn", "old_mrr": 3050, "effective_date": "2026-07-03"},
        {"client_name": "Naan Sense", "change_type": "downgrade", "old_mrr": 3050, "new_mrr": 1500},
    ])
    reply, handled = co.handle_pending_updates_query("what does Piolo need to update?")
    assert handled and "Hono Grill" in reply and "Churned" in reply and "Naan Sense" in reply and "1,500" in reply
