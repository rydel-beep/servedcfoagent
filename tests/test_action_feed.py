"""tests/test_action_feed.py — Zone 3 consolidated action feed: aggregation, ranking, dedup, handler."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import action_feed

def _snap():
    return {"degraded": [
                {"metric": "client_reconciliation", "reason": "4 won deals not on Health tab: A, B"},
                {"metric": "zero_mrr_active_clients", "reason": "3 Active clients with $0 MRR"},
                {"metric": "some_internal_flag", "reason": "ignore me"}],
            "stripe_reconciliation": {"paid_missing_from_tracker": [{"id": "ch_1", "amt": 500}]}}

def test_aggregates_and_ranks(monkeypatch):
    import salience
    monkeypatch.setattr(salience, "collect", lambda s=None: [
        {"id": "f", "type": "failed", "salience": 100, "ago": 0, "spoken": "1 charge failed"},
        {"id": "c", "type": "close", "salience": 80, "ago": 0, "spoken": "X closed — $9,000"}])
    fe = action_feed.build_action_feed(_snap())
    sevs = [i["severity"] for i in fe["items"]]
    assert sevs == sorted(sevs, key=lambda s: {"S1":0,"S2":1,"S3":2}[s])   # ranked S1→S3
    assert fe["counts"]["S1"] == 1                                          # the failed charge
    # data-quality flags mapped to actions; unknown internal flag excluded
    titles = " ".join(i["title"] for i in fe["items"])
    assert "won deals not on Health" in titles and "ignore me" not in titles
    assert any(i["category"] == "reconciliation" for i in fe["items"])      # paid-but-unlogged

def test_handler(monkeypatch):
    import salience
    monkeypatch.setattr(salience, "collect", lambda s=None: [])
    monkeypatch.setattr(action_feed, "build_action_feed", lambda snap=None, include_owner=True: {
        "items": [], "counts": {"S1": 0, "S2": 1, "S3": 0}, "cap": 7,
        "lanes": {"action": [{"severity": "S2", "category": "threshold",
                              "title": "do a thing — $900", "why": "money at stake"}],
                  "delegated": [{"rollup": True, "owner": "Piolo",
                                 "title": "3 tracker date fixes with Piolo"}],
                  "hygiene": [], "watch": [], "noise": []},
        "suppressed_count": 1, "routed_count": 4,
        "headline": "1 decision for you · 1 with the team."})
    r, h = action_feed.handle_action_feed_command("what needs my attention?")
    assert h and "do a thing" in r and "money at stake" in r
    assert "Piolo" in r and "suppressed" in r          # the delegated line + audit hint
    assert action_feed.handle_action_feed_command("hello")[1] is False

def test_lanes_in_payload(monkeypatch):
    import salience
    monkeypatch.setattr(salience, "collect", lambda s=None: [
        {"id": "c", "type": "close", "salience": 80, "ago": 0, "spoken": "X closed — $9,000"}])
    fe = action_feed.build_action_feed(_snap())
    assert "lanes" in fe and fe["cap"] == 7
    # the close event is noise (suppressed with reason), never an action
    assert any("X closed" in (n.get("title") or "") for n in fe["lanes"]["noise"])
    assert not any("X closed" in (a.get("title") or "") for a in fe["lanes"]["action"])
    # every item carries its stable fact key (the dismiss/snooze handle)
    assert all(it.get("key") for it in fe["items"])
