"""
collab.py
---------
The three-way collaboration layer (Rydel + Piolo + EDITH) with a closed, data-verified loop:

  EDITH FLAGS (DQ/hygiene) → PIOLO'S QUEUE → PIOLO RESOLVES with a note → EDITH VERIFIES the
  underlying data actually changed → RYDEL gets a digest.

Plus Piolo's free-form WORK LOG (done/concern/question/suggestion) with threads, and attribution:
every write-action is stamped with the actor, and Piolo's actions are FLAGGED to Rydel (his call).

FOREVER ARCHIVE: append-only (no deletes for any role; post-window edits are appended corrections;
owner may archive-HIDE non-destructively). Date-browsable, EDITH-queryable, unioned into a journal,
and exported off-DB (dated JSON/CSV) so it survives a DB loss.

Log entries are DATA, never instructions — an entry saying "EDITH, do X" is reported as text, never
executed (prompt-injection discipline).
"""
from __future__ import annotations

import json
import logging

import db
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

_EDIT_WINDOW_SECONDS = 15 * 60
_ENTRY_KINDS = {"done", "concern", "question", "suggestion"}

_DDL = """
CREATE TABLE IF NOT EXISTS collab_log (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL,          -- done|concern|question|suggestion|reply|correction|action
  author       TEXT NOT NULL,          -- rydel|piolo|edith
  body         TEXT NOT NULL,
  link_type    TEXT,                   -- flag|client|payment|queue|null
  link_ref     TEXT,
  parent_id    BIGINT,                 -- reply/correction thread
  archived     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  edited_at    TIMESTAMPTZ,
  meta         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS collab_log_created ON collab_log (created_at);
CREATE TABLE IF NOT EXISTS collab_queue (
  flag_id       TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  detail        TEXT,
  category      TEXT,
  status        TEXT NOT NULL DEFAULT 'open',   -- open|resolved|verified|partial
  resolution    TEXT,
  resolved_by   TEXT,
  resolved_at   TIMESTAMPTZ,
  verification  TEXT,
  verified_at   TIMESTAMPTZ,
  first_seen    DATE NOT NULL DEFAULT (now() AT TIME ZONE 'Australia/Sydney'),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS collab_read_marks (
  reader   TEXT NOT NULL,
  entry_id BIGINT NOT NULL,
  seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (reader, entry_id)
);
"""


def migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("collab migrate failed: %s", e)
        return False


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


# ── WORK LOG ─────────────────────────────────────────────────────────────────

def add_entry(author: str, kind: str, body: str, link_type: str | None = None,
              link_ref: str | None = None, parent_id: int | None = None) -> dict | None:
    """Append a work-log entry. Immutable after a 15-min edit window (then append corrections)."""
    kind = (kind or "").lower()
    if kind not in _ENTRY_KINDS and kind not in ("reply", "correction", "action"):
        kind = "suggestion"
    if not (body or "").strip():
        return None
    migrate()
    try:
        with db.get_conn() as c:
            r = c.execute(
                "INSERT INTO collab_log (kind, author, body, link_type, link_ref, parent_id) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, created_at",
                (kind, author, body.strip(), link_type, link_ref, parent_id)).fetchone()
        return {"id": r["id"], "created_at": _iso(r["created_at"]), "kind": kind, "author": author}
    except Exception as e:
        logger.warning("add_entry failed: %s", e)
        return None


def edit_entry(entry_id: int, author: str, new_body: str) -> tuple[bool, str]:
    """Edit within the 15-min window; after that, APPEND a correction (never overwrite)."""
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT author, created_at FROM collab_log WHERE id=%s", (entry_id,)).fetchone()
            if not r:
                return False, "not found"
            if r["author"] != author:
                return False, "only the author can edit"
            age = (now_sydney() - r["created_at"]).total_seconds()
            if age <= _EDIT_WINDOW_SECONDS:
                c.execute("UPDATE collab_log SET body=%s, edited_at=now() WHERE id=%s",
                          (new_body.strip(), entry_id))
                return True, "edited"
    except Exception as e:
        logger.warning("edit_entry failed: %s", e)
        return False, "error"
    # window passed → append-only correction
    add_entry(author, "correction", new_body, link_type="entry", link_ref=str(entry_id), parent_id=entry_id)
    return True, "appended-correction"


def archive_entry(entry_id: int, by_owner: bool) -> bool:
    """Non-destructive archive-hide (owner only). Never deletes; stays in exports + searches."""
    if not by_owner:
        return False
    try:
        with db.get_conn() as c:
            c.execute("UPDATE collab_log SET archived=TRUE WHERE id=%s", (entry_id,))
        return True
    except Exception:
        return False


def list_entries(start=None, end=None, author=None, kind=None, include_archived=False,
                 limit: int = 200) -> list[dict]:
    if not db.db_configured():
        return []
    q = "SELECT * FROM collab_log WHERE 1=1"
    args: list = []
    if not include_archived:
        q += " AND NOT archived"
    if start:
        q += " AND created_at >= %s"; args.append(start)
    if end:
        q += " AND created_at <= %s"; args.append(end)
    if author:
        q += " AND author = %s"; args.append(author)
    if kind:
        q += " AND kind = %s"; args.append(kind)
    q += " ORDER BY created_at DESC LIMIT %s"; args.append(limit)
    try:
        with db.get_conn() as c:
            rows = c.execute(q, tuple(args)).fetchall()
        return [{**dict(r), "created_at": _iso(r["created_at"]), "edited_at": _iso(r.get("edited_at"))}
                for r in rows]
    except Exception as e:
        logger.info("list_entries failed: %s", e)
        return []


def thread(entry_id: int) -> list[dict]:
    """An entry + its replies/corrections in order."""
    try:
        with db.get_conn() as c:
            rows = c.execute("SELECT * FROM collab_log WHERE id=%s OR parent_id=%s ORDER BY created_at",
                             (entry_id, entry_id)).fetchall()
        return [{**dict(r), "created_at": _iso(r["created_at"])} for r in rows]
    except Exception:
        return []


def mark_seen(reader: str, entry_id: int) -> None:
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO collab_read_marks (reader, entry_id) VALUES (%s,%s) "
                      "ON CONFLICT DO NOTHING", (reader, entry_id))
    except Exception:
        pass


# ── ACTIONS (attribution + flag Piolo's writes to Rydel) ─────────────────────

def record_action(actor: dict, description: str, link_type: str | None = None,
                  link_ref: str | None = None) -> None:
    """Attribute a write-action to its actor. Piolo's actions are FLAGGED to Rydel (his call):
    they land in the log as kind='action' so the digest + salience surface them to the owner."""
    who = (actor or {}).get("user", "rydel")
    add_entry(who, "action", description, link_type=link_type, link_ref=link_ref)


# ── QUEUE (flags → resolve → EDITH verifies) ─────────────────────────────────

def _live_flags(snap: dict | None = None) -> list[dict]:
    """The current open hygiene/DQ items, from the action feed (deterministic)."""
    try:
        import action_feed
        feed = action_feed.build_action_feed(snap)
        return [{"flag_id": _flag_id(it), "title": it["title"], "detail": it.get("action"),
                 "category": it.get("category")}
                for it in feed.get("items", [])
                if it.get("category") in ("reconciliation", "data_quality")]
    except Exception as e:
        logger.info("_live_flags failed: %s", e)
        return []


def _flag_id(item: dict) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", (item.get("category", "") + ":" + item.get("title", ""))[:120].lower())


def queue(snap: dict | None = None) -> list[dict]:
    """Piolo's queue: the live flags, each overlaid with any resolution + verification state."""
    migrate()
    live = _live_flags(snap)
    live_ids = {f["flag_id"] for f in live}
    states = {}
    try:
        with db.get_conn() as c:
            for r in c.execute("SELECT * FROM collab_queue").fetchall():
                states[r["flag_id"]] = dict(r)
    except Exception:
        pass
    out = []
    for f in live:
        st = states.get(f["flag_id"]) or {}
        out.append({**f, "status": st.get("status", "open"),
                    "resolution": st.get("resolution"), "resolved_by": st.get("resolved_by"),
                    "verification": st.get("verification"),
                    "first_seen": _iso(st.get("first_seen")) if st.get("first_seen") else str(today_sydney()),
                    "still_present": True})
    # resolved-but-still-verifying items no longer live → verified (data changed)
    for fid, st in states.items():
        if fid not in live_ids and st.get("status") in ("resolved", "partial"):
            out.append({"flag_id": fid, "title": st.get("title", fid), "status": "verified",
                        "resolution": st.get("resolution"), "resolved_by": st.get("resolved_by"),
                        "verification": "✓ verified — the flag condition is gone", "still_present": False})
    return out


def resolve_item(flag_id: str, note: str, actor: dict) -> dict:
    """Piolo marks a queue item done with a note. Does NOT clear the flag — EDITH verifies next."""
    migrate()
    who = (actor or {}).get("user", "piolo")
    live = {f["flag_id"]: f for f in _live_flags()}
    title = (live.get(flag_id) or {}).get("title", flag_id)
    try:
        with db.get_conn() as c:
            c.execute(
                "INSERT INTO collab_queue (flag_id, title, status, resolution, resolved_by, resolved_at) "
                "VALUES (%s,%s,'resolved',%s,%s,now()) ON CONFLICT (flag_id) DO UPDATE SET "
                "status='resolved', resolution=EXCLUDED.resolution, resolved_by=EXCLUDED.resolved_by, "
                "resolved_at=now(), updated_at=now()", (flag_id, title, note, who))
    except Exception as e:
        logger.warning("resolve_item failed: %s", e)
        return {"ok": False}
    record_action(actor, f"resolved queue item “{title}”: {note}", link_type="flag", link_ref=flag_id)
    return verify_item(flag_id)


def verify_item(flag_id: str, snap: dict | None = None) -> dict:
    """EDITH re-checks the underlying condition against fresh data. The flag clears only if the
    condition is GONE — never on the resolver's say-so alone. Stated factually, not accusatorially."""
    still_live = flag_id in {f["flag_id"] for f in _live_flags(snap)}
    verification = ("✓ verified — the tracker no longer shows this; the flag has cleared."
                    if not still_live else
                    "⚠ still open — the data hasn’t changed yet (may need a resync, or the row didn’t "
                    "save). It stays until the tracker reflects it.")
    status = "verified" if not still_live else "partial"
    try:
        with db.get_conn() as c:
            c.execute("UPDATE collab_queue SET status=%s, verification=%s, verified_at=now(), "
                      "updated_at=now() WHERE flag_id=%s", (status, verification, flag_id))
    except Exception:
        pass
    return {"ok": True, "flag_id": flag_id, "status": status, "verification": verification}


def queue_count(snap: dict | None = None) -> int:
    return sum(1 for q in queue(snap) if q.get("status") in ("open", "partial"))


# ── DIGEST (Rydel's "Piolo since you last looked" — watermarked) ─────────────

def digest(reader: str = "rydel", advance: bool = True) -> dict:
    """What Piolo has done/raised since Rydel last looked. Watermarked so it's not re-shown."""
    import kv_store
    wm = (kv_store.get("collab:digest_watermark") or {}).get(reader)
    entries = list_entries(start=wm, author="piolo", limit=100)
    entries = [e for e in entries if e["created_at"] != wm]     # strict after
    buckets = {"action": [], "done": [], "concern": [], "question": [], "suggestion": []}
    for e in entries:
        buckets.setdefault(e["kind"], []).append(e)
    if advance and entries:
        marks = kv_store.get("collab:digest_watermark") or {}
        marks[reader] = entries[0]["created_at"]      # newest (list is DESC)
        kv_store.put("collab:digest_watermark", marks)
    return {"since": wm, "count": len(entries), **{k: v for k, v in buckets.items()},
            "has_questions": bool(buckets["question"]), "has_concerns": bool(buckets["concern"])}


def digest_line() -> str | None:
    """A one-line salience headline for a new concern/question from Piolo (does NOT advance the wm)."""
    import kv_store
    wm = (kv_store.get("collab:salience_watermark") or {}).get("rydel")
    fresh = [e for e in list_entries(author="piolo", limit=20)
             if e["kind"] in ("concern", "question") and (not wm or e["created_at"] > wm)]
    if not fresh:
        return None
    e = fresh[0]
    return f"Piolo raised a {e['kind']}: {e['body'][:80]}"


def mark_salience_seen():
    import kv_store
    latest = list_entries(author="piolo", limit=1)
    if latest:
        m = kv_store.get("collab:salience_watermark") or {}
        m["rydel"] = latest[0]["created_at"]
        kv_store.put("collab:salience_watermark", m)


# ── FOREVER ARCHIVE — date browsing, search, month summary, journal, export ──

def month_summary(year: int, month: int) -> dict:
    import calendar
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d} 23:59:59"
    ents = list_entries(start=start, end=end, include_archived=True, limit=1000)
    by_kind = {}
    for e in ents:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    verified = 0
    for q in queue():
        if q.get("status") == "verified":
            verified += 1
    return {"period": f"{calendar.month_name[month]} {year}", "total": len(ents),
            "by_kind": by_kind, "verified_resolutions": verified}


def search(query: str, limit: int = 20) -> list[dict]:
    """Deterministic substring/trigram-ish search over the full archive (verbatim records)."""
    if not query or not db.db_configured():
        return []
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT * FROM collab_log WHERE body ILIKE %s ORDER BY created_at DESC LIMIT %s",
                (f"%{query.strip()}%", limit)).fetchall()
        return [{**dict(r), "created_at": _iso(r["created_at"])} for r in rows]
    except Exception as e:
        logger.info("search failed: %s", e)
        return []


def journal(start=None, end=None, role: str = "owner", limit: int = 100) -> list[dict]:
    """The unified company journal — a READ-ONLY union over existing audit trails in date order:
    work log + client write-back + target changes + incidents. No new write paths."""
    events: list[dict] = []
    for e in list_entries(start=start, end=end, limit=limit):
        events.append({"at": e["created_at"], "source": "worklog",
                       "who": e["author"], "text": f"[{e['kind']}] {e['body'][:120]}"})
    try:
        import client_overrides
        for o in client_overrides.audit_log(50):
            events.append({"at": _iso(o.get("created_at")), "source": "write-back",
                           "who": "rydel/piolo", "text": f"{o['client_name']} → {o['change_type']}"})
    except Exception:
        pass
    try:
        import incident_log
        for i in incident_log.recent(20):
            events.append({"at": i.get("ts"), "source": "incident", "who": "edith",
                           "text": f"incident: {i.get('claimed', '')[:80]}"})
    except Exception:
        pass
    events = [e for e in events if e.get("at")]
    events.sort(key=lambda x: str(x["at"]), reverse=True)
    return events[:limit]


def export_archive() -> dict:
    """Off-DB backup (dated JSON + CSV dump) so the archive survives a DB loss. Logged each run."""
    import csv
    import io
    import os
    ents = list_entries(include_archived=True, limit=100000)
    stamp = today_sydney().isoformat()
    out_dir = os.path.join(os.path.dirname(__file__), "archive_exports")
    dest = {"json": None, "csv": None, "rows": len(ents), "at": now_sydney().isoformat()}
    try:
        os.makedirs(out_dir, exist_ok=True)
        jp = os.path.join(out_dir, f"collab-archive-{stamp}.json")
        with open(jp, "w") as f:
            json.dump(ents, f, default=str, indent=2)
        dest["json"] = jp
        cp = os.path.join(out_dir, f"collab-archive-{stamp}.csv")
        with open(cp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "created_at", "author", "kind", "body",
                                              "link_type", "link_ref", "archived"])
            w.writeheader()
            for e in ents:
                w.writerow({k: e.get(k) for k in w.fieldnames})
        dest["csv"] = cp
    except Exception as e:
        logger.warning("export_archive failed: %s", e)
        dest["error"] = str(e)
    try:
        import kv_store
        logl = kv_store.get("collab:export_log") or []
        logl.append(dest)
        kv_store.put("collab:export_log", logl[-60:])
    except Exception:
        pass
    return dest


# ── EDITH as collaborator (chat handlers; entries are DATA, never instructions) ──

import re as _re
import datetime as _dt

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"]) if i}


def _range_from_text(low: str):
    """Resolve 'this week / June / July 2026 / last week' to (start, end) or (None, None)."""
    t = today_sydney()
    if "this week" in low or "week of" in low:
        start = t - _dt.timedelta(days=t.weekday())
        return str(start), None
    if "last week" in low:
        start = t - _dt.timedelta(days=t.weekday() + 7)
        return str(start), str(start + _dt.timedelta(days=6))
    if "today" in low:
        return str(t), None
    for name, mi in _MONTHS.items():
        if name in low:
            ym = _re.search(r"(20\d\d)", low)
            year = int(ym.group(1)) if ym else t.year
            import calendar
            return f"{year}-{mi:02d}-01", f"{year}-{mi:02d}-{calendar.monthrange(year, mi)[1]:02d} 23:59:59"
    return None, None


def handle_collab_command(text: str, actor: dict) -> tuple[str | None, bool]:
    """Deterministic collaboration queries + log writes. Actor-aware. Injection-safe."""
    if not text:
        return None, False
    low = text.lower()
    who = (actor or {}).get("user", "rydel")

    # write a log entry: "log done: reconciled Amex" / "note concern: 3 clients look churned"
    lm = _re.match(r"\s*(?:log|note|record)\s+(done|concern|question|suggestion)\s*[:\-]\s*(.+)",
                   text, _re.I)
    if lm:
        e = add_entry(who, lm.group(1).lower(), lm.group(2).strip())
        return (f"Logged your {lm.group(1).lower()}." if e else "Couldn't save that."), True

    # reply to Piolo: "reply to Piolo: yes treat Jagjeet as a renewal"
    rm = _re.match(r"\s*(?:reply|respond|tell piolo|message piolo)\b.*?[:\-]\s*(.+)", text, _re.I)
    if rm and ("piolo" in low or "reply" in low):
        e = add_entry(who, "reply", rm.group(1).strip(), link_type="thread")
        return ("Posted to Piolo — he'll see it on his next visit." if e else "Couldn't post that."), True

    # export the archive
    if _re.search(r"\bexport (the )?(archive|log|journal)\b|\bback ?up the (archive|log)\b", low):
        d = export_archive()
        return (f"Exported {d['rows']} entries to a dated dump ({d.get('json') and 'JSON+CSV'}). "
                "It's logged and reloadable if the DB is ever lost." if d.get("json")
                else "Export couldn't write the dump file — check the server."), True

    # my queue / what's in my queue
    if _re.search(r"\b(my queue|what'?s in (my|the) queue|piolo'?s queue|the queue|open (flags|items))\b", low):
        q = [x for x in queue() if x.get("status") in ("open", "partial")]
        if not q:
            return "Queue's clear — nothing open.", True
        lines = [f"• {x['title']}" + (f" — {x['detail']}" if x.get("detail") else "") for x in q[:6]]
        return f"{len(q)} open: \n" + "\n".join(lines), True

    # what did Piolo do / concerns / questions (+ optional date range)
    if _re.search(r"\bwhat did piolo\b|\bpiolo('?s)? (work|activity|do|done|log)\b|"
                  r"\b(concerns?|questions?|suggestions?) (from|by|piolo)\b|\bany concerns\b|"
                  r"\bwhat (has |did )?piolo\b", low):
        start, end = _range_from_text(low)
        kind = ("concern" if "concern" in low else "question" if "question" in low
                else "suggestion" if "suggest" in low else None)
        ents = list_entries(start=start, end=end, author="piolo", kind=kind, limit=15)
        if not ents:
            span = "in that period" if start else "recently"
            return f"Nothing from Piolo {span}.", True
        lines = [f"• [{e['kind']}] {e['body'][:90]} ({e['created_at'][:10]})" for e in ents[:8]]
        return (f"Piolo — {len(ents)} " + (f"{kind}s" if kind else "entries") + ":\n" + "\n".join(lines)), True

    # archive search: "when did we first notice X", "every concern about churn", "what did we resolve..."
    if _re.search(r"\b(when did (we|i)|first notice|every (concern|question|entry)|search the (log|archive)|"
                  r"what did (we|i) (resolve|flag|do))\b", low):
        start, end = _range_from_text(low)
        kw = _re.sub(r"\b(when did we first notice|search the (log|archive) for|every|show me|what did we|"
                     r"about|the|concern|question|first|notice)\b", " ", low).strip()
        hits = search(kw, 12) if len(kw) >= 3 else list_entries(start=start, end=end, limit=12)
        if not hits:
            return "Nothing in the archive matches that.", True
        return ("From the archive:\n" + "\n".join(
            f"• {h['created_at'][:10]} [{h['kind']}/{h['author']}] {h['body'][:90]}" for h in hits[:8])), True

    return None, False


