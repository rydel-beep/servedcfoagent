"""
memory.py
---------
EDITH's persistent-memory service (Phases 2-4), built on db.py.

Contract:
- Conversational convenience, NOT the system of record. Financial truth comes from the live
  engines; a stored fact must NEVER override a live number. Facts carry a source timestamp so
  stale context is visible.
- Graceful degradation: if the DB is offline, persistence is a no-op, recall returns an empty
  block, and the app keeps working on in-session memory.
- Persistence is fire-and-forget on a daemon thread — ZERO added latency to a reply or speech.
- Never store secrets. Distillation is told to skip them and a guard strips secret-shaped text.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading

import db
from config import (
    CHAT_MODEL, MEMORY_RECENT_TURNS, MEMORY_RECALL_MATCHES, MEMORY_MAX_CONTEXT_CHARS,
)
from helpers import now_sydney

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Block secret-shaped strings from ever entering a stored fact.
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|xer[o0]|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key|token|password|"
    r"secret|client_secret|[A-Za-z0-9_-]{32,})",
    re.I,
)


def memory_status() -> dict:
    """Health for the UI banner. Never raises."""
    online = db.memory_online()
    return {"online": online, "reason": None if online else (db.last_error() or "offline")}


# ── Phase 2: persist (fire-and-forget) ───────────────────────────────────────
def start_conversation(channel: str = "text") -> int | None:
    return db.get_or_create_active_conversation(channel)


def resume_thread(conversation_id: int | None, client_history: list) -> list:
    """Rebuild the model's message thread so a REFRESH resumes instead of restarting.

    Mid-session the client still holds the running thread (many messages) — trust it.
    But after a refresh / new tab the client's in-memory history is gone, so the request
    arrives with just the new user turn; we then reload the resumed conversation's recent
    messages from the DB and prepend them, so EDITH continues the thread she can no longer
    see client-side. THIS is the link that was missing — recent_messages existed but was
    never wired into a request.

    Call this BEFORE persisting the new user turn so the just-typed message isn't
    duplicated. No-op (returns client_history unchanged) if the DB is offline.
    """
    if not conversation_id or not db.db_configured():
        return client_history
    if isinstance(client_history, list) and len(client_history) > 1:
        return client_history  # client still has the thread — don't duplicate it
    try:
        prior = db.recent_messages(conversation_id, MEMORY_RECENT_TURNS * 2)
    except Exception as e:  # pragma: no cover - defensive
        logger.error("resume_thread failed: %s", e)
        return client_history
    if not prior:
        return client_history
    rebuilt = [{"role": m["role"], "content": m["content"]}
               for m in prior if m.get("content") and m.get("role") in ("user", "assistant")]
    logger.info("resume_thread: rebuilt %d prior turns for conversation %s",
                len(rebuilt), conversation_id)
    return rebuilt + list(client_history or [])


def record_turn(conversation_id: int | None, role: str, content: str,
                channel: str = "text", intent: str | None = None,
                token_count: int | None = None) -> None:
    """Persist one turn on a background thread. Never blocks the caller; failures are
    logged and silently degrade to in-session (the DB row just won't exist)."""
    if not conversation_id or not content or not db.db_configured():
        return

    def _write():
        try:
            db.add_message(conversation_id, role, content, channel, intent, token_count)
        except Exception as e:  # pragma: no cover - defensive
            logger.error("record_turn background write failed: %s", e)

    threading.Thread(target=_write, daemon=True, name="edith-mem-write").start()


# ── Phase 3: selective recall ────────────────────────────────────────────────
_PAST_REF_RE = re.compile(
    r"\b(remember|recall|we (?:talked|discussed|decided|said|agreed)|last time|earlier|"
    r"you (?:said|told|mentioned)|previously|the other day|what did we|did we (?:decide|say))\b",
    re.I,
)


def build_recall_context(user_message: str, conversation_id: int | None = None) -> dict:
    """Assemble the memory block to prepend to the system prompt.

    ALWAYS includes the active distilled facts (the "knows me" layer). When the user
    references the past (or names a specific topic), ALSO retrieves the top relevant older
    messages from PRIOR conversations via trigram search. Capped to a char budget.

    Returns {block, used_fact_ids, recalled:[{date,snippet}], context_chars}. Empty block
    if the DB is offline — never raises.
    """
    empty = {"block": "", "used_fact_ids": [], "recalled": [], "context_chars": 0}
    if not db.db_configured():
        return empty
    try:
        lines: list[str] = []
        used_fact_ids: list[int] = []
        recalled: list[dict] = []

        facts = db.active_facts(limit=60)
        if facts:
            lines.append("What EDITH knows (durable context — NOT financial truth; verify "
                         "figures against live data):")
            # Reserve headroom for the recall section below. Without this, once the fact
            # store grows past the budget the recall snippets get tail-truncated away and
            # cross-conversation recall silently dies (found 2026-08-03: 60 facts = 8044
            # chars > 8000 budget → "Relevant earlier discussion" never reached the model).
            fact_budget = MEMORY_MAX_CONTEXT_CHARS - 2000
            used = len(lines[-1])
            for f in facts:
                ts = f.get("last_referenced_at")
                stamp = ts.date().isoformat() if hasattr(ts, "date") else ""
                line = f"- [{f['category']}] {f['fact']}" + (f" (as of {stamp})" if stamp else "")
                if used + len(line) > fact_budget:
                    lines.append(f"…({len(facts) - len(used_fact_ids)} older facts trimmed "
                                 "to keep room for recall)")
                    break
                lines.append(line)
                used += len(line) + 1
                used_fact_ids.append(f["id"])

        # Relevance recall: always try (cheap); the search itself filters by similarity.
        # Bias toward including when the user explicitly references the past.
        hits = db.search_messages(user_message, exclude_conversation_id=conversation_id,
                                  limit=MEMORY_RECALL_MATCHES)
        if hits:
            lines.append("\nRelevant earlier discussion (recalled from past conversations):")
            for h in hits:
                ts = h.get("created_at")
                stamp = ts.date().isoformat() if hasattr(ts, "date") else "?"
                snippet = " ".join((h["content"] or "").split())[:240]
                lines.append(f"- [{stamp}] {h['role']}: {snippet}")
                recalled.append({"date": stamp, "snippet": snippet[:120]})

        # Archived facts stay retrievable (maintenance demotes, never deletes):
        # topical matches come back labelled, on demand only.
        try:
            import memory_maintenance
            arch = memory_maintenance.search_archived(user_message, limit=3)
            if arch:
                lines.append("\nArchived facts matching this topic (demoted, still true "
                             "unless superseded):")
                for a in arch:
                    lines.append(f"- (archived) [{a['category']}] {a['fact']}")
        except Exception:
            pass

        if not lines:
            return empty

        block = ("\n[EDITH MEMORY]\n" + "\n".join(lines) + "\n[END MEMORY]\n")
        # Enforce the token/char budget — facts first, then trim recall tail.
        if len(block) > MEMORY_MAX_CONTEXT_CHARS:
            block = block[:MEMORY_MAX_CONTEXT_CHARS] + "\n…(memory truncated to budget)\n[END MEMORY]\n"

        if used_fact_ids:
            db.touch_facts(used_fact_ids)
        return {"block": block, "used_fact_ids": used_fact_ids,
                "recalled": recalled, "context_chars": len(block)}
    except Exception as e:
        logger.error("build_recall_context failed: %s", e)
        return empty


# ── Phase 4: distillation (the "knows me" layer) ─────────────────────────────
_DISTILL_SYSTEM = """You extract DURABLE memory facts from a conversation transcript for an
AI assistant's long-term memory. Return ONLY a JSON array (no prose) of objects:
  {"fact": "<concise standalone fact>", "category": "decision|preference|context|person|business"}

Rules:
- Capture only things worth remembering across future sessions: decisions made, stated
  preferences, persistent business context, and people (names + roles).
- Each fact must be self-contained (understandable without the transcript), one sentence.
- Do NOT include transient chit-chat, questions, or anything time-bound to just this chat.
- NEVER include secrets, API keys, tokens, passwords, or financial figures (those live in the
  real ledgers, not memory). If nothing durable, return [].
- At most 8 facts. Prefer fewer, higher-signal facts."""


def _looks_like_secret(text: str) -> bool:
    t = (text or "")
    # Only treat as secret if it has a long opaque token; plain words like "token" alone
    # in a normal sentence shouldn't trip it, so require a 24+ char opaque run too.
    return bool(re.search(r"[A-Za-z0-9_\-]{24,}", t)) and bool(_SECRET_RE.search(t))


def distill_conversation(conversation_id: int, max_turns: int = 30) -> int:
    """Summarise a conversation's durable facts into memory_facts (dedup + secret guard).
    Returns count stored/updated. Safe: 0 on any failure. Intended to run async."""
    if not conversation_id or not db.db_configured() or not ANTHROPIC_API_KEY:
        return 0
    try:
        turns = db.recent_messages(conversation_id, limit=max_turns)
        if not turns:
            return 0
        transcript = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
        if len(transcript) > 12000:
            transcript = transcript[-12000:]

        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CHAT_MODEL,
            max_tokens=600,
            system=_DISTILL_SYSTEM,
            messages=[{"role": "user", "content": f"Transcript:\n{transcript}"}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        # Tolerate code fences / stray prose around the JSON array.
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return 0
        facts = json.loads(m.group(0))

        stored = 0
        for item in facts:
            if not isinstance(item, dict):
                continue
            fact = (item.get("fact") or "").strip()
            cat = (item.get("category") or "context").strip().lower()
            if cat not in ("decision", "preference", "context", "person", "business"):
                cat = "context"
            if not fact or _looks_like_secret(fact):
                continue
            if db.upsert_fact(fact, cat, source_conversation_id=conversation_id) is not None:
                stored += 1
        logger.info("distill_conversation %s -> %d facts", conversation_id, stored)
        return stored
    except Exception as e:
        logger.error("distill_conversation failed: %s", e)
        return 0


def maybe_distill_async(conversation_id: int | None) -> None:
    """Fire-and-forget distillation (end of conversation / every N turns). Never blocks."""
    if not conversation_id or not db.db_configured() or not ANTHROPIC_API_KEY:
        return
    threading.Thread(target=distill_conversation, args=(conversation_id,),
                     daemon=True, name="edith-mem-distill").start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("status:", memory_status())
    cid = start_conversation("text")
    print("conversation:", cid)
    record_turn(cid, "user", "We decided to hire a creative video editor next quarter.", intent="business")
    import time; time.sleep(1)
    record_turn(cid, "assistant", "Noted — creative video editor hire planned for next quarter.", intent="business")
    time.sleep(1)
    print("recall:", build_recall_context("what did we decide about the video editor hire?", conversation_id=None)["recalled"])
    print("distilled facts:", distill_conversation(cid))
    print("active facts now:", [f["fact"] for f in db.active_facts()])
