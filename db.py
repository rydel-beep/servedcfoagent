"""
db.py
-----
Postgres-backed persistent memory for EDITH (conversations, messages, distilled facts).

GRACEFUL DEGRADATION is the contract: if DATABASE_URL is absent, the driver is missing,
or the DB is unreachable, every public call becomes a safe no-op (returns None / [] /
False) and `memory_online()` returns False. The app then runs on in-session memory and
surfaces "persistent memory offline" — it must NEVER crash or block a reply because of DB.

Conversational memory is a recall convenience, NOT the system of record. Financial truth
lives in the live engines; never let a stored fact override a live number. Never store
secrets (tokens/keys/passwords) here.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from config import DATABASE_URL
from helpers import now_sydney

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.rows import dict_row
    _DRIVER_OK = True
except Exception as e:  # pragma: no cover - import guard
    psycopg = None
    dict_row = None
    _DRIVER_OK = False
    logger.warning("psycopg not available — persistent memory disabled: %s", e)

# Last connection error, surfaced to the UI ("memory offline — <reason>") without leaking creds.
_last_error: str | None = None


def db_configured() -> bool:
    """True if we have both a driver and a connection string. Cheap, no I/O."""
    return _DRIVER_OK and bool(DATABASE_URL)


def last_error() -> str | None:
    return _last_error


@contextmanager
def get_conn():
    """Yield a short-lived autocommit connection. Raises on failure (callers guard)."""
    global _last_error
    if not db_configured():
        raise RuntimeError("DB not configured")
    conn = psycopg.connect(DATABASE_URL, connect_timeout=10, autocommit=True, row_factory=dict_row)
    try:
        _last_error = None
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def memory_online() -> bool:
    """Live health check: can we actually reach the DB right now? Safe (never raises)."""
    global _last_error
    if not db_configured():
        _last_error = "DATABASE_URL not set" if _DRIVER_OK else "psycopg driver missing"
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as e:
        _last_error = f"{type(e).__name__}"
        logger.error("DB health check failed: %s", e)
        return False


# ── Schema migration (idempotent — safe to run on every boot) ────────────────
_MIGRATION_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS conversations (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel         TEXT NOT NULL DEFAULT 'text',
    title           TEXT,
    summary         TEXT,
    tokens_used     BIGINT NOT NULL DEFAULT 0,
    archived        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS messages (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,
    content          TEXT NOT NULL,
    channel          TEXT,
    intent           TEXT,
    token_count      INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_facts (
    id                      BIGSERIAL PRIMARY KEY,
    fact                    TEXT NOT NULL,
    category                TEXT NOT NULL DEFAULT 'context',
    source_conversation_id  BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_referenced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    weight                  REAL NOT NULL DEFAULT 1.0,
    active                  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_content_trgm ON messages USING gin (content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_facts_category_active ON memory_facts (category, active);
CREATE INDEX IF NOT EXISTS idx_facts_fact_trgm ON memory_facts USING gin (fact gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_conversations_active ON conversations (archived, last_active_at DESC);
"""


def migrate() -> bool:
    """Apply the schema. Idempotent. Returns True on success, False (logged) on any failure."""
    global _last_error
    if not db_configured():
        _last_error = "DATABASE_URL not set" if _DRIVER_OK else "psycopg driver missing"
        logger.warning("Skipping migration — %s", _last_error)
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_MIGRATION_SQL)
        logger.info("Memory schema migration applied (idempotent)")
        return True
    except Exception as e:
        _last_error = f"{type(e).__name__}"
        logger.error("Memory schema migration failed: %s", e)
        return False


def schema_overview() -> dict:
    """Return tables + row counts + whether pg_trgm is installed. Safe; {} on failure."""
    if not db_configured():
        return {}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                out = {}
                for t in ("conversations", "messages", "memory_facts"):
                    cur.execute(f"SELECT count(*) AS n FROM {t}")
                    out[t] = cur.fetchone()["n"]
                cur.execute("SELECT 1 AS ok FROM pg_extension WHERE extname = 'pg_trgm'")
                out["pg_trgm"] = cur.fetchone() is not None
                return out
    except Exception as e:
        logger.error("schema_overview failed: %s", e)
        return {}


# ── Conversations & messages (Phase 2: persist) ──────────────────────────────
from config import MEMORY_IDLE_GAP_HOURS  # noqa: E402


def get_or_create_active_conversation(channel: str = "text") -> int | None:
    """Resume the most recent non-archived conversation if active within the idle gap,
    else start a new one. Returns conversation id, or None if DB unavailable."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM conversations
                WHERE archived = FALSE
                  AND last_active_at > now() - (%s * interval '1 hour')
                ORDER BY last_active_at DESC
                LIMIT 1
                """,
                (MEMORY_IDLE_GAP_HOURS,),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "INSERT INTO conversations (channel) VALUES (%s) RETURNING id",
                (channel,),
            )
            return cur.fetchone()["id"]
    except Exception as e:
        logger.error("get_or_create_active_conversation failed: %s", e)
        return None


def add_message(conversation_id: int, role: str, content: str,
                channel: str | None = None, intent: str | None = None,
                token_count: int | None = None) -> bool:
    """Persist one turn + bump the conversation's last_active_at/tokens. Safe no-op on failure."""
    if not conversation_id or not content:
        return False
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (conversation_id, role, content, channel, intent, token_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (conversation_id, role, content, channel, intent, token_count),
            )
            cur.execute(
                """
                UPDATE conversations
                SET last_active_at = %s, tokens_used = tokens_used + COALESCE(%s, 0),
                    channel = CASE WHEN channel <> %s THEN 'mixed' ELSE channel END
                WHERE id = %s
                """,
                (now_sydney(), token_count, channel or "text", conversation_id),
            )
        return True
    except Exception as e:
        logger.error("add_message failed: %s", e)
        return False


def recent_messages(conversation_id: int, limit: int = 12) -> list[dict]:
    """Most recent turns of one conversation, oldest-first. [] on failure."""
    if not conversation_id:
        return []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
            return list(reversed(cur.fetchall()))
    except Exception as e:
        logger.error("recent_messages failed: %s", e)
        return []


# ── Selective recall (Phase 3) ───────────────────────────────────────────────
def search_messages(query: str, exclude_conversation_id: int | None = None,
                    limit: int = 6, min_similarity: float = 0.30) -> list[dict]:
    """Trigram keyword recall across PRIOR conversations. Returns top matches with a
    snippet + date. Empty on short query or failure.

    Uses word_similarity(query, content) (ASYMMETRIC) — it scores the query against the
    best-matching span inside each message, so a short query ("runway") matches a long
    message that mentions it. Plain similarity() normalises by both strings' length and
    scores a short-query-vs-long-message near zero, which made cross-session recall almost
    never fire."""
    q = (query or "").strip()
    if len(q) < 4:
        return []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.role, m.content, m.created_at, m.conversation_id,
                       word_similarity(%s, m.content) AS sim
                FROM messages m
                WHERE (%s::bigint IS NULL OR m.conversation_id <> %s::bigint)
                  AND word_similarity(%s, m.content) >= %s
                ORDER BY sim DESC, m.created_at DESC
                LIMIT %s
                """,
                (q, exclude_conversation_id, exclude_conversation_id, q, min_similarity, limit),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("search_messages failed: %s", e)
        return []


def active_facts(limit: int = 60) -> list[dict]:
    """The distilled always-on memory layer, highest-weight first. [] on failure."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, fact, category, last_referenced_at, weight
                FROM memory_facts
                WHERE active = TRUE
                ORDER BY weight DESC, last_referenced_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("active_facts failed: %s", e)
        return []


def touch_facts(fact_ids: list[int]) -> None:
    """Mark facts as freshly referenced (recall keeps them sharp). Safe no-op on failure."""
    if not fact_ids:
        return
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE memory_facts SET last_referenced_at = %s WHERE id = ANY(%s)",
                (now_sydney(), list(fact_ids)),
            )
    except Exception as e:
        logger.error("touch_facts failed: %s", e)


# ── Distilled facts CRUD (Phase 4 + 5) ───────────────────────────────────────
def upsert_fact(fact: str, category: str = "context",
                source_conversation_id: int | None = None, weight: float = 1.0,
                dedupe_similarity: float = 0.6) -> int | None:
    """Insert a distilled fact, or — if a near-duplicate active fact already exists —
    bump its weight + last_referenced_at instead (keeps memory sharp, not noisy).
    Returns the fact id, or None on failure."""
    f = (fact or "").strip()
    if not f:
        return None
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM memory_facts
                WHERE active = TRUE AND category = %s
                  AND similarity(fact, %s) >= %s
                ORDER BY similarity(fact, %s) DESC LIMIT 1
                """,
                (category, f, dedupe_similarity, f),
            )
            dup = cur.fetchone()
            if dup:
                cur.execute(
                    "UPDATE memory_facts SET weight = weight + 0.5, last_referenced_at = %s "
                    "WHERE id = %s",
                    (now_sydney(), dup["id"]),
                )
                return dup["id"]
            cur.execute(
                """
                INSERT INTO memory_facts (fact, category, source_conversation_id, weight)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (f, category, source_conversation_id, weight),
            )
            return cur.fetchone()["id"]
    except Exception as e:
        logger.error("upsert_fact failed: %s", e)
        return None


def list_facts(include_inactive: bool = False) -> list[dict]:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, fact, category, source_conversation_id, created_at,
                       last_referenced_at, weight, active
                FROM memory_facts
                WHERE (%s OR active = TRUE)
                ORDER BY category, weight DESC, last_referenced_at DESC
                """,
                (include_inactive,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("list_facts failed: %s", e)
        return []


def update_fact(fact_id: int, fact: str | None = None, category: str | None = None,
                active: bool | None = None) -> bool:
    sets, vals = [], []
    if fact is not None:
        sets.append("fact = %s"); vals.append(fact.strip())
    if category is not None:
        sets.append("category = %s"); vals.append(category)
    if active is not None:
        sets.append("active = %s"); vals.append(active)
    if not sets:
        return False
    vals.append(fact_id)
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE memory_facts SET {', '.join(sets)} WHERE id = %s", vals)
            return cur.rowcount > 0
    except Exception as e:
        logger.error("update_fact failed: %s", e)
        return False


def delete_fact(fact_id: int) -> bool:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM memory_facts WHERE id = %s", (fact_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_fact failed: %s", e)
        return False


def decay_facts(stale_days: int = 45, deactivate_below: float = 0.5) -> int:
    """Lower the weight of facts not referenced in `stale_days`, and deactivate any
    that fall below threshold — memory stays sharp instead of accreting noise.
    Returns count deactivated. Safe (0 on failure)."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memory_facts
                SET weight = GREATEST(0, weight - 0.5)
                WHERE active = TRUE AND last_referenced_at < now() - (%s * interval '1 day')
                """,
                (stale_days,),
            )
            cur.execute(
                "UPDATE memory_facts SET active = FALSE WHERE active = TRUE AND weight < %s",
                (deactivate_below,),
            )
            return cur.rowcount
    except Exception as e:
        logger.error("decay_facts failed: %s", e)
        return 0


# ── Conversation management (Phase 5 UI) ─────────────────────────────────────
def list_conversations(limit: int = 50, include_archived: bool = False) -> list[dict]:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.started_at, c.last_active_at, c.channel, c.title,
                       c.summary, c.tokens_used, c.archived,
                       (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c
                WHERE (%s OR c.archived = FALSE)
                ORDER BY c.last_active_at DESC
                LIMIT %s
                """,
                (include_archived, limit),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("list_conversations failed: %s", e)
        return []


def get_transcript(conversation_id: int) -> list[dict]:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, channel, intent, created_at
                FROM messages WHERE conversation_id = %s
                ORDER BY created_at, id
                """,
                (conversation_id,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("get_transcript failed: %s", e)
        return []


def archive_conversation(conversation_id: int) -> bool:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE conversations SET archived = TRUE WHERE id = %s", (conversation_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error("archive_conversation failed: %s", e)
        return False


def delete_conversation(conversation_id: int) -> bool:
    """Hard-delete a conversation + its messages (FK ON DELETE CASCADE)."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_conversation failed: %s", e)
        return False


def clear_all_memory(include_transcripts: bool = True) -> bool:
    """Wipe distilled facts, and optionally all conversations/messages. Privacy control."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            if include_transcripts:
                cur.execute("TRUNCATE conversations, messages, memory_facts RESTART IDENTITY CASCADE")
            else:
                cur.execute("TRUNCATE memory_facts RESTART IDENTITY")
        return True
    except Exception as e:
        logger.error("clear_all_memory failed: %s", e)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("db_configured:", db_configured())
    print("memory_online:", memory_online())
    print("migrate:", migrate())
    print("schema_overview:", schema_overview())
    print("now_sydney:", now_sydney().isoformat())
