"""
tests/test_memory.py
--------------------
Persistent-memory wiring guards (the refresh-resume fix). These run WITHOUT a DB —
they verify the graceful-degradation contract and the history reconstruction logic,
not the live Postgres (that's proven against the deployment).
"""
import memory
import db
from dashboard.chat import _sanitize_history


def test_resume_thread_is_noop_when_db_offline():
    """No DB locally → resume_thread must return the client history unchanged (and never raise)."""
    assert not db.db_configured()                       # no DATABASE_URL in test env
    h = [{"role": "user", "content": "hi"}]
    assert memory.resume_thread(123, h) is h or memory.resume_thread(123, h) == h


def test_resume_thread_trusts_full_client_history():
    """When the client still holds the thread (>1 msg), don't rebuild/duplicate from DB."""
    h = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
         {"role": "user", "content": "c"}]
    assert memory.resume_thread(123, h) == h


def test_resume_thread_handles_none_conversation():
    h = [{"role": "user", "content": "hi"}]
    assert memory.resume_thread(None, h) == h


def test_memory_status_never_raises_offline():
    s = memory.memory_status()
    assert s["online"] is False and s["reason"]          # loud reason, not silent


def test_sanitize_collapses_consecutive_roles():
    """Reconstructed threads can double a role; the sanitizer must restore strict
    user/assistant alternation (else Anthropic 400s)."""
    h = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"},
         {"role": "assistant", "content": "c"}, {"role": "assistant", "content": "d"},
         {"role": "user", "content": "e"}]
    out = _sanitize_history(h)
    roles = [m["role"] for m in out]
    assert roles[0] == "user"
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    assert out[0]["content"] == "a\nb"                   # merged, nothing lost
