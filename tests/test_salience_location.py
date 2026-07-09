"""
tests/test_salience_location.py
-------------------------------
Salience feed (deterministic events, ranking, watermark/dedup) + location resolution (override,
fallback chain, honest 'where am I'). No network / no DB (kv_store falls back to an in-process dict).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kv_store, salience, location


def _reset():
    kv_store._MEM.clear()


def test_ranking_money_at_risk_first(monkeypatch):
    _reset()
    monkeypatch.setattr(salience, "_days_ago", lambda d: 0)
    import closes_view, leads_view
    monkeypatch.setattr(closes_view, "recent_closes",
                        lambda limit=15: {"closes": [{"business": "Lost Sheep Cafe", "close_date": "2026-07-07",
                                                      "contract": 14500.0, "offer": "Scale Engine"}]})
    monkeypatch.setattr(leads_view, "recent_leads", lambda limit=25: {"leads": []})
    snap = {"stripe": {"failed_charges_count": 1, "subscriptions": {"past_due": 0}, "payouts": {}}}
    ev = salience.collect(snap)
    # failed charge (100) ranks above the close (80)
    assert ev[0]["type"] == "failed" and ev[1]["type"] == "close"
    assert "Lost Sheep Cafe closed — $14,500" in ev[1]["spoken"]   # figure verbatim


def test_watermark_dedup(monkeypatch):
    _reset()
    monkeypatch.setattr(salience, "_days_ago", lambda d: 0)
    import closes_view, leads_view
    monkeypatch.setattr(closes_view, "recent_closes",
                        lambda limit=15: {"closes": [{"business": "Lost Sheep Cafe", "close_date": "2026-07-07",
                                                      "contract": 14500.0, "offer": "Scale Engine"}]})
    monkeypatch.setattr(leads_view, "recent_leads", lambda limit=25: {"leads": []})
    snap = {"stripe": {}}
    first = salience.collect(snap)
    assert len(first) == 1
    salience.mark_told(first)                 # greeting surfaced it
    assert salience.collect(snap) == []       # same news is NOT re-announced


def test_nothing_new_is_empty():
    _reset()
    assert salience.summary_line([]) == "Nothing new since we last spoke."


def test_leads_batched(monkeypatch):
    _reset()
    monkeypatch.setattr(salience, "_days_ago", lambda d: 0)
    import closes_view, leads_view
    monkeypatch.setattr(closes_view, "recent_closes", lambda limit=15: {"closes": []})
    monkeypatch.setattr(leads_view, "recent_leads",
                        lambda limit=25: {"leads": [{"business": "A", "source": "Facebook", "date": "2026-07-07", "time": "1"},
                                                    {"business": "B", "source": "Instagram", "date": "2026-07-07", "time": "2"}]})
    ev = salience.collect({"stripe": {}})
    assert len(ev) == 1 and "2 new leads" in ev[0]["spoken"]


def test_location_override_and_describe():
    _reset()
    # forward-geocode is network; stub set_override by writing the kv directly
    kv_store.put("location:override", {"place": "Sydney, NSW", "lat": -33.87, "lon": 151.2,
                                       "timezone": "Australia/Sydney", "source": "override"})
    loc = location.resolve()
    assert loc["place"] == "Sydney, NSW" and loc["source"] == "override"
    assert "Sydney" in location.describe() and "you told me" in location.describe()
    location.clear_override()
    assert location.resolve()["source"] == "default"       # falls back to Newcastle


def test_location_command_parsing():
    _reset()
    # "where am I" is deterministic (no network)
    r, h = location.handle_location_command("where do you think I am?")
    assert h and "Newcastle" in r
    # clear
    r, h = location.handle_location_command("I'm back home")
    assert h and "cleared" in r.lower()
    # a non-location utterance is ignored
    assert location.handle_location_command("what's our cash") == (None, False)


def test_whats_new_handler(monkeypatch):
    _reset()
    monkeypatch.setattr(salience, "top", lambda snap=None, n=3: [
        {"id": "close:x", "spoken": "Lost Sheep Cafe closed — $14,500", "_ids": None}])
    r, h = salience.handle_whats_new("what's new?")
    assert h and "Lost Sheep Cafe closed — $14,500" in r
    assert salience.handle_whats_new("how's the weather") == (None, False)


def test_location_strips_time_qualifiers(monkeypatch):
    _reset()
    captured = {}

    def _cap(place):
        captured["p"] = place
        return {"place": place, "lat": 1, "lon": 1, "source": "override"}
    monkeypatch.setattr(location, "set_override", _cap)
    for utter, expect in [("I'm in Melbourne this week", "Melbourne"),
                          ("I'm travelling to Gold Coast", "Gold Coast"),
                          ("I'm in New York for a few days", "New York")]:
        captured.clear()
        r, h = location.handle_location_command(utter)
        assert h and captured["p"] == expect, f"{utter!r} → {captured.get('p')!r}"
