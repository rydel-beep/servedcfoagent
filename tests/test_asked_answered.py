"""tests/test_asked_answered.py — D2's permanent regression class: a question whose
answer exists must NEVER be asked. Pre-ask recall check (belt), conversation
resolution detection (braces), incidents logged, greeting path clean."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import open_loops as OL


def _reset():
    import kv_store
    kv_store.put("openloops:reminders", [])
    kv_store.put("convo:incidents", [])


def test_preask_check_resolves_instead_of_asking(monkeypatch):
    """Seed a fact + its loop → the loop resolves with the answer attached and the
    greeting NEVER surfaces the question. The near-miss is still logged (prevention
    counts)."""
    _reset()
    OL.add_reminder("— which venue did I pick as the pilot for the reservations "
                    "platform, and when does it start?")
    monkeypatch.setattr(OL, "_preask_answer", lambda what: {
        "fact_id": 169, "sim": 0.41,
        "answer": "The pilot venue for the reservations platform is Chiangmai Thai, "
                  "starting mid-September."})
    due = OL.due_followups(snap={})
    assert not any("pilot" in (d.get("spoken") or "") for d in due)   # never asked
    loops = OL._load()
    assert loops[0]["resolved"] is True
    assert "Chiangmai Thai" in loops[0]["resolution"]["answer"]
    assert "pre-ask recall" in loops[0]["resolution"]["via"]
    # the near-miss incident was captured silently
    import kv_store
    inc = kv_store.get("convo:incidents") or []
    assert any(i["class"] == "asked_answered_near_miss" for i in inc)
    # resolved loops never re-fire
    assert not any("pilot" in (d.get("spoken") or "") for d in OL.due_followups(snap={}))


def test_preask_only_touches_question_shaped_loops(monkeypatch):
    """A plain reminder ('reconnect Xero this week') is NOT a question — the pre-ask
    check must leave it alone even when memory matches loosely."""
    _reset()
    OL.add_reminder("reconnect Xero this week")
    called = []
    monkeypatch.setattr(OL, "_preask_answer",
                        lambda what: called.append(what) or None)
    due = OL.due_followups(snap={})
    assert any("Xero" in (d.get("spoken") or "") for d in due)   # still surfaces
    # the real _preask_answer gates on question shape itself:
    assert OL._QUESTION_RE.search("reconnect Xero this week") is None


def test_conversation_answer_resolves_the_loop():
    """Braces: Rydel states the answer in ANY conversation → the loop resolves with
    the answer attached, without him ever saying 'drop it'."""
    _reset()
    OL.add_reminder("— which venue did I pick as the pilot for the reservations "
                    "platform, and when does it start?")
    resolved = OL.check_resolution(
        "For the record: the pilot venue for the reservations platform is "
        "Chiangmai Thai, starting mid-September.")
    assert len(resolved) == 1
    loops = OL._load()
    assert loops[0]["resolved"] and "Chiangmai Thai" in loops[0]["resolution"]["answer"]


def test_questions_never_resolve_loops():
    """The question itself (or EDITH echoing it) must never count as the answer."""
    _reset()
    OL.add_reminder("— which venue did I pick as the pilot for the reservations "
                    "platform, and when does it start?")
    assert OL.check_resolution("which venue is the pilot for the reservations platform?") == []
    assert OL._load()[0]["resolved"] is False


def test_unrelated_statement_does_not_resolve():
    _reset()
    OL.add_reminder("— which venue did I pick as the pilot for the reservations "
                    "platform, and when does it start?")
    assert OL.check_resolution("the CPL spike came from the retargeting batch") == []
    assert OL._load()[0]["resolved"] is False


def test_correction_capture_and_scan_wiring():
    _reset()
    import convo_quality as CQ
    CQ.scan_user_turn("No, I said Chiangmai Thai — I already told you this.")
    import kv_store
    inc = kv_store.get("convo:incidents") or []
    assert any(i["class"] == "correction" for i in inc)
    # wired on every recorded user turn at both chat sites
    src = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "routes.py")).read()
    assert src.count("convo_quality.scan_user_turn(user_msg)") == 2
