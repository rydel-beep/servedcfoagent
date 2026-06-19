# EDITH — PERSISTENT MEMORY (Postgres) — BUILD REPORT

Built 2026-06-19. Persistent, cross-session/-device conversational memory for EDITH, backed by
Railway Postgres. Built entirely in **new modules** — no edits to the chat path (`chat.py` /
`routes.py` / `chat.js`), which a parallel session owns (streaming voice). The only remaining
integration is a documented ~3-line hook (§7).

## 1. Postgres setup
- Rydel provisioned a **PostgreSQL** service on the Railway project (one-click) and referenced
  both URLs into CFOagent. **PostgreSQL 18.4.**
- `config.DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL")` —
  **prefers the internal URL** (`postgres.railway.internal`, fast, no egress) and falls back to
  the public proxy. In prod the app uses internal; local tests force `DATABASE_PUBLIC_URL`
  (internal only resolves inside Railway).
- Driver: **`psycopg[binary]>=3.2`** (sync, matches the gunicorn worker model; no ORM — raw SQL
  fits the codebase). Added to `requirements.txt`.

## 2. Schema (`db.migrate()` — idempotent, runs on boot)
- **conversations** — id, started_at, last_active_at, channel (text/voice/mixed), title, summary,
  tokens_used, archived.
- **messages** — id, conversation_id FK (ON DELETE CASCADE), role, content, channel, intent
  (business/general from the router), token_count, created_at.
- **memory_facts** — id, fact, category (decision/preference/context/person/business),
  source_conversation_id, created_at, last_referenced_at, weight, active.
- Indexes: `messages(conversation_id, created_at)`; **GIN trigram** on `messages.content` and
  `memory_facts.fact` (keyword recall, `pg_trgm`); `memory_facts(category, active)`;
  `conversations(archived, last_active_at)`. `CREATE EXTENSION pg_trgm` is in the migration.

## 3. Recall strategy (selective — never a full-history dump)
`memory.build_recall_context(user_message, conversation_id)` assembles, within a char budget
(`MEMORY_MAX_CONTEXT_CHARS`, default 8000):
- **ALWAYS:** the active distilled facts (the "knows me" layer) — compact, highest-weight first.
- **ON RELEVANCE:** top trigram matches (`MEMORY_RECALL_MATCHES`, default 6) from **prior**
  conversations (excludes the current one — its recent turns are already in the live thread the
  model receives). Verified: a real query scored the right message at 0.474 sim, with no false
  positives on an unrelated query.
- The current conversation's recent turns are supplied by the existing chat thread itself
  (`MEMORY_RECENT_TURNS` is the cap when reconstructing a fresh load).
- Used facts get `last_referenced_at` bumped (recall keeps them sharp). Returns provenance
  (`recalled: [{date, snippet}]`) so the UI can show "recalled from <date>".

## 4. Distillation (`memory.distill_conversation`, async)
- End-of-conversation / every-N-turns, a `CHAT_MODEL` call extracts durable facts (decisions,
  preferences, persistent business context, people) as strict JSON, then `db.upsert_fact`
  **de-dupes** (≥0.6 trigram similarity → bump weight + timestamp instead of inserting).
- **Decay:** `db.decay_facts` lowers weight of facts unreferenced for N days and deactivates
  those below threshold — memory stays sharp, not noisy.
- Verified live: a real distillation call produced *"The team decided to hire a creative video
  editor next quarter."* (category `decision`).

## 5. Guardrails (accuracy boundary)
- **Memory is conversational context, NOT financial truth.** The recall block is explicitly
  labelled "NOT financial truth; verify figures against live data." A stored fact can never
  override a live engine number — the live snapshot still attaches for business intent and is
  authoritative. Facts are timestamped so staleness is visible.
- **No secrets stored:** distillation is instructed to skip secrets, and `_looks_like_secret`
  strips any fact containing a long opaque token before it's written.

## 6. Management UI — `/dashboard/memory` (auth-gated, standalone page)
- Distilled facts grouped by category: inline **edit**, **activate/deactivate**, **delete**.
- Conversations: open **transcript**, **Forget** (archive), **Delete** (hard, cascades).
- **Clear ALL memory** with a typed `CLEAR` confirmation (privacy control).
- Live **online/offline banner** from `memory_status()`.
- Built as new files only: `dashboard/memory_routes.py` (blueprint), `templates/memory.html`,
  `static/js/memory.js`. Registered in `app.py` at `/dashboard/memory`.

## 7. Degradation
Every `db.py` / `memory.py` call is wrapped: if `DATABASE_URL` is unset, the driver is missing,
or the DB is unreachable → persistence is a no-op, recall returns an empty block, the UI shows
"persistent memory OFFLINE", and the app keeps serving on in-session memory. Verified: with no
DB env, `memory_status() = {online: False, reason: "DATABASE_URL not set"}`, recall returns
empty, `record_turn` no-ops — no crash. Tests: **183/183 green**.

## 8. Chat-path hook — APPLIED + VERIFIED END-TO-END (commit e6ba6b8)
DONE. Wired into BOTH `/api/chat` and `/api/chat-stream`: resume/start conversation → persist
user turn (async) → inject recall block into the system prompt (`memory_block` param on
`chat`/`chat_stream`/`build_system_prompt`, default "" = unchanged) → persist assistant turn +
async distillation on completion. **Verified live in prod:** stated a codename in conversation
A, archived A, then in a SEPARATE conversation B EDITH recalled "Bluefin Tuna Launch, March
2027" from Postgres with provenance. EDITH now remembers across sessions end-to-end.

The patch that was applied:

```python
# in dashboard/routes.py api_chat / api_chat_stream, after reading `history` + token:
import memory
conv_id = memory.start_conversation("voice" if data.get("voice") else "text")
user_msg = history[-1]["content"] if history else ""
memory.record_turn(conv_id, "user", user_msg, channel=..., intent=None)   # async, non-blocking

# build the recall block and prepend to the system prompt the model receives:
recall = memory.build_recall_context(user_msg, conversation_id=conv_id)
snapshot_json_or_system += recall["block"]      # whichever the chat builder consumes

# after the reply is produced:
memory.record_turn(conv_id, "assistant", reply_text, channel=..., intent=result.get("intent"))
memory.maybe_distill_async(conv_id)             # periodic distillation
```
The frontend can pass/persist a `conversation_id` to pin a thread; until then `start_conversation`
resumes the most recent active conversation (idle gap `MEMORY_IDLE_GAP_HOURS`, default 12h).
This hook is the ONLY thing between "engine ready" and "EDITH remembers live."

## Config (env, all optional)
`DATABASE_URL` (internal, set), `DATABASE_PUBLIC_URL` (set), `MEMORY_IDLE_GAP_HOURS=12`,
`MEMORY_RECENT_TURNS=12`, `MEMORY_RECALL_MATCHES=6`, `MEMORY_MAX_CONTEXT_CHARS=8000`.
