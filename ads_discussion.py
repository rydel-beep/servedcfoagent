"""
ads_discussion.py
-----------------
THE anchored, context-stamped discussion engine for /ads (one store, many
renders: the Discussion panel, dossier Notes, row badges, the owner feed,
EDITH's context). This is the FIRST non-owner WRITE surface on the CFO
service — the rails are load-bearing:

  IDENTITY FROM SESSION, NEVER FROM CLIENT — author comes from the
  authenticated actor; a client-supplied name is ignored by construction
  (there is no author parameter).
  CONTEXT STAMP, SERVER-SIDE — at post time the server captures what the
  author was viewing (window label + clock + the anchored creative's live
  metrics) from the ONE engine for the view params the client sent. The
  client names the VIEW; the server supplies the VALUES.
  EXCLUDED ≠ DELETED — edits journal the old body; deletes tombstone
  ("comment removed by {author}") with history auditable; resolve collapses,
  never removes.
  UNTRUSTED TEXT — bodies are stored raw (length-capped plain text) and
  escaped AT EVERY RENDER (JS esc(), EDITH transcript, feed titles are
  server-built from trusted fields only).

Store: kv "ads:discussion" {"seq": n, "comments": [...]} — comment volume is
team-note scale; Postgres kv gives durability + the _MEM fallback for tests.
Rate limit: 10 posts / user / 10 minutes (abuse posture).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KV = "ads:discussion"
_KV_FEED = "feed:extra:ads_discussion"   # action_feed registry channel (owner feed);
                                         # REPLACED wholesale each publish (A5-style)
_BODY_MAX = 2000
_RATE_N, _RATE_WINDOW_S = 10, 600
_CAP = 2000                              # store cap — tombstones included, oldest out

_ANCHOR_RE = re.compile(r"^(board|[0-9]{10,20}|__ig_dm__|__unattributed__|__ambiguous__)$")


def _store() -> dict:
    try:
        import kv_store
        d = kv_store.get(_KV)
        if isinstance(d, dict) and isinstance(d.get("comments"), list):
            return d
    except Exception as e:
        logger.info("discussion store read failed: %s", e)
    return {"seq": 0, "comments": []}


def _put(d: dict) -> None:
    import kv_store
    d["comments"] = d["comments"][-_CAP:]
    kv_store.put(_KV, d)


def _now_iso() -> str:
    from helpers import now_sydney
    return now_sydney().strftime("%Y-%m-%d %H:%M")


def _clean_body(body) -> str | None:
    b = str(body or "").strip()
    if not b or len(b) > _BODY_MAX:
        return None
    return b


def context_stamp(anchor: str, days=30, start=None, end=None, basis="cohort") -> dict:
    """SERVER-SIDE stamp: the one-engine values for the view the author named.
    Never trusts client numbers — computes them. Cheap: the author's view is
    warm by definition (they were just looking at it)."""
    stamp = {"clock": basis, "at": _now_iso()}
    try:
        import attribution_engine as AE
        r = AE.compute(days=days, start=start, end=end, basis=basis)
        w = r.get("window") or {}
        stamp["window"] = f"{w.get('start')} → {w.get('end')}"
        if anchor == "board":
            t = r.get("totals") or {}
            stamp["metrics"] = {"leads": t.get("leads"), "closes": t.get("closes"),
                                "spend": t.get("spend")}
        else:
            row = next((c for c in (r.get("creatives") or [])
                        if c.get("creative_key") == anchor), None)
            if row:
                stamp["creative"] = (row.get("label") or "")[:60]
                stamp["metrics"] = {"leads": row.get("leads"),
                                    "cpl": row.get("cost_per_lead"),
                                    "spend": row.get("spend"),
                                    "verdict": row.get("verdict") or
                                               ((row.get("provisional") or {}).get("label"))}
    except Exception as e:
        logger.info("context stamp degraded: %s", e)
        stamp["degraded"] = "engine values unavailable at post time"
    return stamp


def _rate_limited(d: dict, user: str) -> bool:
    import time
    now = time.time()
    recent = [c for c in d["comments"]
              if c.get("author", {}).get("user") == user
              and (now - float(c.get("_ts", 0))) < _RATE_WINDOW_S]
    return len(recent) >= _RATE_N


def post(actor: dict, body, anchor: str, *, reply_to=None,
         days=30, start=None, end=None, basis="cohort") -> tuple[dict | None, str | None]:
    """Create a comment (or one-level reply). Author = the SESSION actor,
    always. Returns (comment, error)."""
    b = _clean_body(body)
    if b is None:
        return None, f"comment must be 1–{_BODY_MAX} characters of text"
    anchor = str(anchor or "board").strip()
    if not _ANCHOR_RE.match(anchor):
        return None, "bad anchor — a creative key or 'board'"
    d = _store()
    user = (actor or {}).get("user") or "unknown"
    if _rate_limited(d, user):
        return None, f"rate limit: {_RATE_N} notes per {_RATE_WINDOW_S // 60} minutes"
    if reply_to is not None:
        parent = next((c for c in d["comments"] if c.get("id") == reply_to), None)
        if parent is None or parent.get("state") == "tombstone":
            return None, "reply target missing or removed"
        if parent.get("reply_to"):
            return None, "one reply level only — reply to the top-level note"
        anchor = parent["anchor"]           # a reply lives on its parent's anchor
    import time
    d["seq"] += 1
    c = {
        "id": d["seq"],
        "author": {"user": user, "display": (actor or {}).get("display") or user,
                   "role": (actor or {}).get("role")},
        "body": b,
        "anchor": anchor,
        "reply_to": reply_to,
        "state": "active",
        "created": _now_iso(),
        "edited": None,
        "journal": [],
        "context_stamp": context_stamp(anchor, days=days, start=start, end=end,
                                       basis=basis),
        "_ts": time.time(),
    }
    d["comments"].append(c)
    _put(d)
    _publish_feed(d)
    return c, None


def _own(d: dict, cid, actor: dict) -> tuple[dict | None, str | None]:
    c = next((x for x in d["comments"] if x.get("id") == cid), None)
    if c is None:
        return None, "no such comment"
    if c.get("author", {}).get("user") != (actor or {}).get("user"):
        return None, "you can only change your own notes"
    if c.get("state") == "tombstone":
        return None, "comment was removed"
    return c, None


def edit(actor: dict, cid, body) -> tuple[dict | None, str | None]:
    b = _clean_body(body)
    if b is None:
        return None, f"comment must be 1–{_BODY_MAX} characters of text"
    d = _store()
    c, err = _own(d, cid, actor)
    if err:
        return None, err
    c["journal"].append({"at": _now_iso(), "action": "edit", "old_body": c["body"]})
    c["body"] = b
    c["edited"] = _now_iso()
    _put(d)
    return c, None


def delete(actor: dict, cid) -> tuple[dict | None, str | None]:
    """Tombstone, never vanish: the body is cleared, the slot says who removed
    it, the journal keeps the history (auditable, not rendered)."""
    d = _store()
    c, err = _own(d, cid, actor)
    if err:
        return None, err
    c["journal"].append({"at": _now_iso(), "action": "delete", "old_body": c["body"]})
    c["body"] = ""
    c["state"] = "tombstone"
    c["edited"] = _now_iso()
    _put(d)
    return c, None


def resolve(actor: dict, cid, note=None) -> tuple[dict | None, str | None]:
    """Anyone with the role may resolve (with an optional note). Resolved
    threads collapse but stay browsable — excluded ≠ deleted."""
    d = _store()
    c = next((x for x in d["comments"] if x.get("id") == cid), None)
    if c is None or c.get("state") == "tombstone":
        return None, "no such comment"
    if c.get("reply_to"):
        return None, "resolve the top-level note, not a reply"
    c["journal"].append({"at": _now_iso(), "action": "resolve",
                         "by": (actor or {}).get("user")})
    c["state"] = "resolved"
    c["resolved_by"] = (actor or {}).get("display") or (actor or {}).get("user")
    n = _clean_body(note) if note else None
    if n:
        c["resolution_note"] = n[:400]
    _put(d)
    return c, None


def _render(c: dict) -> dict:
    """The wire shape — raw body rides (the CLIENT escapes at render); a
    tombstone never carries its old body on the wire."""
    out = {k: c.get(k) for k in ("id", "anchor", "reply_to", "state", "created",
                                 "edited", "context_stamp", "resolved_by",
                                 "resolution_note")}
    out["author"] = {"display": c.get("author", {}).get("display"),
                     "user": c.get("author", {}).get("user")}
    if c.get("state") == "tombstone":
        out["body"] = ""
        out["tombstone_text"] = f"comment removed by {out['author']['display']}"
    else:
        out["body"] = c.get("body")
    out["was_edited"] = bool(c.get("edited") and c.get("state") == "active")
    return out


def list_comments(creative=None, author=None, state=None, limit=200) -> list[dict]:
    """Newest-first; unresolved (active) top-levels pin above resolved. Replies
    ride under their parents."""
    d = _store()
    rows = d["comments"]
    if creative:
        rows = [c for c in rows if c.get("anchor") == creative]
    if author:
        rows = [c for c in rows if c.get("author", {}).get("user") == str(author).lower()]
    if state:
        rows = [c for c in rows if c.get("state") == state]
    tops = [c for c in rows if not c.get("reply_to")]
    tops.sort(key=lambda c: (0 if c.get("state") == "active" else 1, -c.get("id", 0)))
    out = []
    all_by_parent: dict = {}
    for c in d["comments"]:
        if c.get("reply_to"):
            all_by_parent.setdefault(c["reply_to"], []).append(c)
    for cmt in tops[:limit]:
        r = _render(cmt)
        r["replies"] = [_render(x) for x in sorted(all_by_parent.get(cmt["id"], []),
                                                   key=lambda x: x.get("id", 0))]
        out.append(r)
    return out


def counts_by_anchor() -> dict:
    """Active-note counts for the row badges (a door, per the standard)."""
    d = _store()
    out: dict = {}
    for c in d["comments"]:
        if c.get("state") == "active":
            out[c.get("anchor")] = out.get(c.get("anchor"), 0) + 1
    return out


def _publish_feed(d: dict) -> None:
    """Owner feed items via the action-feed registry channel — REPLACED
    wholesale (self-retiring). Titles are server-built from trusted fields;
    comment BODIES never ride into the feed (untrusted text stays escaped at
    its own render surfaces)."""
    try:
        import kv_store
        items = []
        for c in [x for x in d["comments"] if x.get("state") != "tombstone"][-10:]:
            label = (c.get("context_stamp") or {}).get("creative") or \
                    ("the board" if c.get("anchor") == "board" else c.get("anchor"))
            kind = "replied on" if c.get("reply_to") else "commented on"
            items.append({
                "severity": "S3", "category": "discussion",
                "id": f"ads-discussion:{c['id']}",
                "title": f"{c.get('author', {}).get('display')} {kind} {label}",
                "action": (f"open /ads?dossier={c.get('anchor')}"
                           if c.get("anchor") != "board" else "open /ads"),
            })
        kv_store.put(_KV_FEED, items)
    except Exception as e:
        logger.info("discussion feed publish failed: %s", e)


# ── EDITH (read-only — she never posts) ──────────────────────────────────────

def edith_context(max_notes: int = 12) -> str:
    """A compact digest for EDITH's internal context: who noted what, with
    stamps. Plain text; her renderer escapes."""
    notes = [c for c in _store()["comments"]
             if c.get("state") == "active"][-max_notes:]
    if not notes:
        return ""
    lines = ["AD TEAM DISCUSSION (internal notes, read-only):"]
    for c in reversed(notes):
        st = c.get("context_stamp") or {}
        m = st.get("metrics") or {}
        stamp = " · ".join(x for x in (
            st.get("creative"), st.get("clock"), st.get("window"),
            f"CPL ${m.get('cpl')}" if m.get("cpl") is not None else None,
            str(m.get("verdict") or "") or None) if x)
        lines.append(f"- {c['author']['display']} ({c['created']}): "
                     f"\"{c['body'][:200]}\" [viewing: {stamp}]")
    return "\n".join(lines)


_RECALL_RE = re.compile(
    r"(what|any(thing)?|has|did).{0,40}(not(ed|ice)|comment|remark|observ|"
    r"discuss|says?|said|posted).{0,60}(ads?|creative|b\d{3}|board)|"
    r"(romano|isaiah|inna).{0,30}(not(ed|ice)|comment|say|said|think)", re.I)


def handle_discussion_recall(text: str) -> tuple[str | None, bool]:
    """EDITH deterministic handler: 'what has Romano noticed this week' →
    real quotes + stamps. Read-only."""
    t = (text or "").strip()
    if not _RECALL_RE.search(t):
        return None, False
    tl = t.lower()
    author = next((u for u in ("romano", "isaiah", "inna", "rydel", "piolo")
                   if u in tl), None)
    notes = list_comments(author=author, state="active", limit=8)
    who = (author.capitalize() if author else "the team")
    if not notes:
        return (f"No open discussion notes from {who} on the ad board yet.", True)
    lines = [f"Notes from {who} (newest first):"]
    for n in notes[:6]:
        st = n.get("context_stamp") or {}
        m = st.get("metrics") or {}
        stamp_bits = [b for b in (st.get("creative"),
                                  st.get("clock"), st.get("window"),
                                  f"CPL ${m.get('cpl')}" if m.get("cpl") is not None else None,
                                  m.get("verdict")) if b]
        lines.append(f"· {n['author']['display']} ({n['created']}): \"{n['body'][:180]}\""
                     + (f" — viewing {' · '.join(str(b) for b in stamp_bits)}" if stamp_bits else ""))
        for rp in (n.get("replies") or [])[:2]:
            if rp.get("state") == "active":
                lines.append(f"    ↳ {rp['author']['display']}: \"{rp['body'][:120]}\"")
    return ("\n".join(lines), True)
