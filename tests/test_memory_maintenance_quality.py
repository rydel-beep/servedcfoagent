"""tests/test_memory_maintenance_quality.py — D3 + the self-improvement loop:
never-delete doctrine, journaled actions, confirmation gates, quality metrics,
proposals applied only on confirmation."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import memory_maintenance as MM
import convo_quality as CQ


def test_never_deletes_doctrine():
    src = open(os.path.join(os.path.dirname(__file__), "..", "memory_maintenance.py")).read()
    assert "DELETE FROM" not in src            # supersede/demote/merge only
    assert "delete_fact" not in src
    assert "active = FALSE" in src             # the archive tier IS deactivation


def test_consolidate_merges_supersedes_and_cards(monkeypatch):
    import kv_store
    kv_store.put("memory:confirm_cards", [])
    kv_store.put("memory:maintenance_journal", [])
    import datetime as dt
    t0, t1 = dt.datetime(2026, 7, 1), dt.datetime(2026, 8, 1)
    pairs = [
        # ≥0.75 same category → MERGE (older archives, newer keeps boosted weight)
        {"ia": 1, "ib": 2, "s": 0.80, "fa": "MRR is 75k", "fb": "MRR is $75k",
         "wa": 1.0, "wb": 1.0, "ca": t0, "cb": t1, "cat": "business"},
        # review band + transition marker in the newer → SUPERSEDE
        {"ia": 3, "ib": 4, "s": 0.60, "fa": "Chloie is on 29k PHP",
         "fb": "Chloie previously on 29k PHP, now 35k PHP", "wa": 1.0, "wb": 1.0,
         "ca": t0, "cb": t1, "cat": "person"},
        # review band, no marker → CONFIRMATION CARD (never guessed)
        {"ia": 5, "ib": 6, "s": 0.58, "fa": "Akuna Cafe health 69",
         "fb": "Butler's Cucina health 71", "wa": 1.0, "wb": 1.0,
         "ca": t0, "cb": t1, "cat": "business"},
    ]
    monkeypatch.setattr(MM, "_pairs", lambda min_sim: pairs)
    archived = []

    class _Cur:
        def execute(self, q, v=None):
            if "active = FALSE" in q:
                archived.append(v[0])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Conn:
        def cursor(self): return _Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import db
    monkeypatch.setattr(db, "get_conn", lambda: _Conn())
    out = MM.consolidate()
    assert out == {"merged": 1, "superseded": 1, "carded": 1}
    assert archived == [1, 3]                    # the OLDER of each ruled pair
    cards = kv_store.get("memory:confirm_cards")
    assert len(cards) == 1 and cards[0]["ids"] == [5, 6]
    j = kv_store.get("memory:maintenance_journal")
    assert [e["action"] for e in j] == ["merged", "superseded"]
    # re-run: the carded pair is not re-carded (idempotent)
    assert MM.consolidate()["carded"] == 0


def test_card_ruling_and_journal_commands(monkeypatch):
    import kv_store
    kv_store.put("memory:confirm_cards", [{"ids": [5, 6], "sim": 0.58,
                                           "a": "fact A", "b": "fact B",
                                           "question": "?"}])
    r, h = MM.handle_memory_maintenance_command("any memory conflicts?")
    assert h and "fact A" in r and "won't guess" in r
    import db
    calls = []
    monkeypatch.setattr(db, "update_fact", lambda fid, **k: calls.append((fid, k)) or True)
    r, h = MM.handle_memory_maintenance_command("memory card 1: keep A")
    assert h and "kept A" in r
    assert calls == [(6, {"active": False})]     # B archived, nothing deleted
    assert kv_store.get("memory:confirm_cards") == []
    r, h = MM.handle_memory_maintenance_command("restore memory fact #6")
    assert h and "Restored" in r
    r, h = MM.handle_memory_maintenance_command("memory journal")
    assert h and "never deleted" in r.lower() or "reversible" in r


def test_quality_metrics_and_gated_proposals():
    import kv_store
    kv_store.put("convo:incidents", [])
    kv_store.put("convo:proposals", [])
    kv_store.put("convo:applied", [])
    kv_store.put("convo:avoid_phrases", [])
    CQ.record_incident("correction", "I told you already")
    CQ.record_incident("asked_answered_near_miss", "pre-ask caught the pilot loop")
    m = CQ.metrics(7)
    assert m["incidents_total"] == 2 and m["by_class"]["correction"] == 1
    assert m["asked_answered"] == 0              # the target metric
    r, h = CQ.handle_quality_command("how's your conversation quality been?")
    assert h and "2 conversation-quality incident" in r and "target zero" in r
    # proposals apply ONLY on confirmation
    kv_store.put("convo:proposals", [{"text": "add 'great question' to the avoid-list",
                                      "kind": "avoid_phrase", "value": "great question",
                                      "week": "2026-W32"}])
    assert CQ.avoid_phrases() == []
    r, h = CQ.handle_quality_command("apply proposal 1")
    assert h and "on your confirmation" in r
    assert CQ.avoid_phrases() == ["great question"]
    r, h = CQ.handle_quality_command("what did you learn this week?")
    assert h and "great question" in r
    # the avoid-list reaches the persona
    src = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "chat.py")).read()
    assert "convo_quality.avoid_phrases()" in src


def test_maintenance_and_quality_ticks_scheduled():
    src = open(os.path.join(os.path.dirname(__file__), "..", "attribution_engine.py")).read()
    for needle in ("memory_maintenance.nightly_tick()", "convo_quality.weekly_tick()",
                   "voice_health.daily_tick()"):
        assert needle in src                     # D3's debt: decay-class job now SCHEDULED
