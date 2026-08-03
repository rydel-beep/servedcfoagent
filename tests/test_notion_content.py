"""P4 content review: read-only enforcement, fail-honest, verbatim grounding blocks."""
import pytest

import notion_content as NC

PAGES = {"results": [
    {"id": "pg1", "last_edited_time": "2099-01-01T00:00:00Z", "created_time": "2099-01-01T00:00:00Z",
     "properties": {"Name": {"type": "title", "title": [{"plain_text": "Winback Email — July"}]},
                    "Status": {"type": "status", "status": {"name": "Sent"}}}},
    {"id": "pg2", "last_edited_time": "2099-01-01T00:00:00Z", "created_time": "2099-01-01T00:00:00Z",
     "properties": {"Name": {"type": "title", "title": [{"plain_text": "Spring Launch Teaser"}]},
                    "Status": {"type": "status", "status": {"name": "Draft"}}}}]}
BLOCKS = {"results": [
    {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Subject: They came back."}]},
     "has_children": False},
    {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Your best table is waiting."}]},
     "has_children": False}], "has_more": False}


def _wire(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "secret-test")
    NC._cache.clear()

    def fake_req(method, path, body=None):
        if path.startswith("/data_sources/") and path.endswith("/query"):
            return PAGES
        if path.startswith("/data_sources/"):
            return {"id": path.rsplit("/", 1)[1]}
        if path.startswith("/blocks/"):
            return BLOCKS
        return None
    monkeypatch.setattr(NC, "_req", fake_req)


def test_read_only_guard_refuses_non_query_post():
    with pytest.raises(ValueError):
        NC._req("POST", "/pages")           # a write would have to come through here


def test_source_is_get_and_query_only():
    import inspect
    src = inspect.getsource(NC)
    for verb in ("requests.put", "requests.patch", "requests.delete"):
        assert verb not in src


def test_token_absent_is_honest(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    r, h = NC.handle_content_list("what emails went out this week?")
    assert h and "isn't connected" in r and "won't invent" in r
    ctx = NC.content_context("review this week's emails with me")
    assert "NOT connected" in ctx and "do not invent" in ctx


def test_list_recent_titles_verbatim(monkeypatch):
    _wire(monkeypatch)
    r, h = NC.handle_content_list("what emails went out this week?")
    assert h and "Winback Email — July" in r and "Sent" in r and "Spring Launch Teaser" in r


def test_review_context_quotes_real_copy(monkeypatch):
    _wire(monkeypatch)
    ctx = NC.content_context("review this week's emails with me")
    assert "VERBATIM from Notion Email Library" in ctx
    assert "Subject: They came back." in ctx and "Your best table is waiting." in ctx
    assert "Quote ONLY from this text" in ctx
    assert "copy-only" in ctx                   # GHL stats honestly absent


def test_named_piece_targets_that_page(monkeypatch):
    _wire(monkeypatch)
    ctx = NC.content_context("let's review the winback email")
    assert "Winback Email — July" in ctx and "Spring Launch Teaser" not in ctx


def test_non_review_messages_inject_nothing():
    assert NC.content_context("how's cash looking?") == ""
    assert NC.handle_content_list("how's cash looking?")[1] is False


def test_recall_never_starved_by_fact_bloat(monkeypatch):
    """2026-08-03: 60 distilled facts alone exceeded MEMORY_MAX_CONTEXT_CHARS, so the
    trigram-recall section was tail-truncated away — cross-conversation recall silently
    died. Facts must leave headroom; the recall section must survive a bloated store."""
    import memory, db as _db
    monkeypatch.setattr(_db, "db_configured", lambda: True)
    monkeypatch.setattr(_db, "active_facts",
                        lambda limit=60: [{"id": i, "category": "business",
                                           "fact": "F%03d " % i + "x" * 150,
                                           "last_referenced_at": None} for i in range(60)])
    monkeypatch.setattr(_db, "search_messages",
                        lambda q, exclude_conversation_id=None, limit=6:
                        [{"role": "assistant", "content": "Here's the full review of the "
                          "slowest weeknight email — hooks solid", "created_at": None,
                          "conversation_id": 19, "sim": 0.46}])
    monkeypatch.setattr(_db, "touch_facts", lambda ids: None)
    r = memory.build_recall_context("what did you make of the weeknight email?",
                                    conversation_id=20)
    assert "Relevant earlier discussion" in r["block"]
    assert "slowest weeknight email" in r["block"]
    assert "older facts trimmed" in r["block"]
    assert len(r["block"]) <= memory.MEMORY_MAX_CONTEXT_CHARS + 100
