"""
notion_content.py — Universal advisor Phase 4: read-only content review adapter.

Reads the ACTUAL content pieces (Email Library, Lead Magnets, Content Pieces,
Email Command Centre) from Notion via the dedicated READ-ONLY integration
(NOTION_TOKEN on this service — a separate integration from the timeline's
write-capable one). Review mode = read-and-discuss WITH Rydel:

  • a deterministic tier-2 lister ("what emails went out this week?")
  • a CONTEXT INJECTION (content_context) that puts the piece's VERBATIM copy in
    front of the model for the advisory register — critique grounded in the real
    text, quoting only what's written. The injection block instructs the model to
    say so when something isn't in the text — never paraphrase copy into
    something it doesn't say.

BOUNDARIES (absolute): GET/POST-query reads only — no page create/update/archive,
no sends, no schedules, no GHL pushes. EDITH never contacts clients; reviewing is
advising Rydel, nothing else. GHL email stats were probed 3 Aug 2026 with the
existing sales-location key → 401 on every email/campaign endpoint, so
performance stats are cleanly SKIPPED (copy-only review), stated when relevant.

Fail-honest: without NOTION_TOKEN, handlers say the integration isn't connected —
they never invent content.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import time

import requests

from helpers import now_sydney

logger = logging.getLogger(__name__)

_API = "https://api.notion.com/v1"
_VER = "2025-09-03"
# Database/data-source ids (Rydel-provided). Overridable by env without a deploy.
SOURCES = {
    "email":       ("Email Library",        "NOTION_EMAIL_LIBRARY_ID",   "3118984c-0474-8002-bb33-000b0cbfd361"),
    "lead_magnet": ("Lead Magnets",         "NOTION_LEAD_MAGNETS_ID",    "a4be22d4-d068-4414-bb82-21be82a6659d"),
    "content":     ("Content Pieces",       "NOTION_CONTENT_PIECES_ID",  "927ea6f5-cceb-49fd-a717-a89e31feccc0"),
    # The "Email Command Centre" turned out to be a PAGE ("Email Marketing — Command
    # Centre", discovered 2026-08-03 once the token landed), not a row database — it
    # holds the Newsletter SOP / offer-strategy child pages. It joins content review as
    # the RULES reference (_rules_copy), not as a listable library.
    "command":     ("Email Marketing — Command Centre", "NOTION_COMMAND_CENTRE_ID",
                    "3498984c-0474-81b6-b0a3-c8c5be0dc6b4"),
}
_CACHE_SECONDS = 120
_cache: dict = {}


def _token() -> str:
    return os.environ.get("NOTION_TOKEN", "")


def configured() -> bool:
    return bool(_token())


def _hdr():
    return {"Authorization": "Bearer " + _token(), "Notion-Version": _VER,
            "Content-Type": "application/json"}


def _req(method: str, path: str, body=None):
    """READ-ONLY http: GET, or POST only to /query and /search (Notion's read verbs)."""
    if method == "POST" and not (path.endswith("/query") or path == "/search"):
        raise ValueError("notion_content is read-only — refusing POST to " + path)
    try:
        fn = requests.get if method == "GET" else requests.post
        r = fn(_API + path, headers=_hdr(), timeout=15, **({"json": body} if body is not None else {}))
        if r.status_code != 200:
            logger.warning("notion %s %s -> %s %s", method, path, r.status_code, r.text[:120])
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("notion %s %s failed: %s", method, path, e)
        return None


def _data_source_id(key: str) -> str | None:
    """Resolve a configured id to a data_source id (accepts either form; cached)."""
    label, env, default = SOURCES[key]
    raw = (os.environ.get(env) or default).strip()
    ck = "dsid:" + key
    if ck in _cache:
        return _cache[ck]
    dsid = None
    if raw:
        if _req("GET", "/data_sources/" + raw) is not None:
            dsid = raw
        else:
            db = _req("GET", "/databases/" + raw)
            srcs = (db or {}).get("data_sources") or []
            dsid = srcs[0]["id"] if srcs else None
    else:
        found = _req("POST", "/search", {"query": label, "page_size": 10}) or {}
        for res in found.get("results", []):
            if res.get("object") == "data_source":
                dsid = res["id"]; break
            if res.get("object") == "database":
                srcs = res.get("data_sources") or []
                if srcs:
                    dsid = srcs[0]["id"]; break
    _cache[ck] = dsid
    return dsid


def _title_of(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])).strip()
    return "(untitled)"


def _status_of(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "status":
            return ((prop.get("status") or {}).get("name")) or ""
    return ""


def list_recent(key: str, days: int = 7, limit: int = 10) -> list[dict] | None:
    """Most recently edited pages in a source. None = unreachable (fail-honest)."""
    if not configured():
        return None
    ck = "recent:%s:%s:%s" % (key, days, limit)
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    dsid = _data_source_id(key)
    if not dsid:
        return None
    body = {"page_size": min(limit * 3, 50),
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]}
    q = _req("POST", "/data_sources/%s/query" % dsid, body)
    if q is None:
        return None
    cutoff = (now_sydney() - _dt.timedelta(days=days)).isoformat()
    out = []
    for pg in q.get("results", []):
        edited = (pg.get("last_edited_time") or "").replace("Z", "+00:00")
        if days and edited and edited < cutoff:
            continue
        out.append({"id": pg["id"], "title": _title_of(pg), "status": _status_of(pg),
                    "edited": edited[:10], "created": (pg.get("created_time") or "")[:10]})
        if len(out) >= limit:
            break
    _cache[ck] = (time.time(), out)
    return out


def page_copy(page_id: str, max_chars: int = 6000) -> str | None:
    """The page's actual written copy, verbatim plain text (blocks, one nest level)."""
    if not configured():
        return None

    def _texts(block):
        t = block.get(block.get("type"), {}) or {}
        return "".join(x.get("plain_text", "") for x in (t.get("rich_text") or []))

    out, cursor = [], None
    for _ in range(20):
        path = "/blocks/%s/children?page_size=100" % page_id + (("&start_cursor=" + cursor) if cursor else "")
        data = _req("GET", path)
        if data is None:
            return None if not out else "\n".join(out)[:max_chars]
        for b in data.get("results", []):
            line = _texts(b)
            if line:
                out.append(line)
            if b.get("has_children") and b.get("type") not in ("child_page", "child_database"):
                sub = _req("GET", "/blocks/%s/children?page_size=50" % b["id"])
                for sb in (sub or {}).get("results", []):
                    sline = _texts(sb)
                    if sline:
                        out.append("  " + sline)
            if sum(len(x) for x in out) > max_chars:
                return "\n".join(out)[:max_chars]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return "\n".join(out)[:max_chars]


# ── tier-2 lister ─────────────────────────────────────────────────────────────
_LIST_RE = re.compile(r"\b(what|which|list|show)\b.{0,30}\b(emails?|newsletters?|lead magnets?|content pieces?)\b"
                      r".{0,40}\b(this week|recent|lately|went out|drafted|in the library)\b", re.I)
_KEY_FOR = (("newsletter", "email"), ("email", "email"), ("lead magnet", "lead_magnet"),
            ("content piece", "content"), ("content", "content"))

_NOT_CONNECTED = ("The read-only Notion integration isn't connected on my side yet "
                  "(NOTION_TOKEN missing) — I won't invent content. Once it's set and the "
                  "libraries are shared with it, I can read the real pieces.")


def _key_from(msg: str) -> str:
    low = msg.lower()
    for word, key in _KEY_FOR:
        if word in low:
            return key
    return "email"


def _window_days(msg: str) -> int:
    low = msg.lower()
    if re.search(r"\bmonth\b|\b30 days\b|\blast 4 weeks\b", low):
        return 30
    if re.search(r"\bfortnight\b|\btwo weeks\b|\b2 weeks\b|\bweek or two\b|\b14 days\b", low):
        return 14
    return 7


def handle_content_list(msg: str) -> tuple[str | None, bool]:
    if not msg or not _LIST_RE.search(msg):
        return None, False
    if not configured():
        return _NOT_CONNECTED, True
    key = _key_from(msg)
    days = _window_days(msg)
    rows = list_recent(key, days=days)
    label = SOURCES[key][0]
    if rows is None:
        return "I can't reach the %s in Notion right now — not guessing at its contents." % label, True
    if not rows:
        return "Nothing edited in the %s in the last %d days." % (label, days), True
    lines = ["%s (%s, edited %s)" % (r["title"], r["status"] or "no status", r["edited"]) for r in rows]
    return "%s — last %d days: %s. Say \"review <title>\" and we'll go through the actual copy together." % (
        label, days, "; ".join(lines)), True


# ── context injection for the advisory register ──────────────────────────────
_REVIEW_RE = re.compile(r"\b(review|critique|go (?:over|through)|look at|read me|pull up|walk (?:me )?through)\b"
                        r".{0,60}\b(emails?|newsletters?|lead magnets?|content pieces?|copy|draft)\b"
                        r"|\breview\b.{0,50}\bwith me\b", re.I)


def content_context(msg: str) -> str:
    """Verbatim content block for review turns. Empty string when not a review ask.
    Grounding contract mirrors tracker_read.client_context: quote only this text."""
    if not msg or not _REVIEW_RE.search(msg):
        return ""
    if not configured():
        return ("[CONTENT REVIEW] The read-only Notion integration is NOT connected "
                "(NOTION_TOKEN missing). Tell Rydel plainly; do not invent or recall content "
                "from memory as if read today. [END CONTENT REVIEW]")
    key = _key_from(msg)
    label = SOURCES[key][0]
    # a NAMED piece is findable regardless of edit date; the un-named flow reviews recent
    rows = list_recent(key, days=0, limit=10)
    if rows is None:
        return ("[CONTENT REVIEW] Notion (%s) is unreachable right now — say so; do not "
                "invent content. [END CONTENT REVIEW]" % label)
    if not rows:
        return ("[CONTENT REVIEW] %s: the library is empty or unreadable — say so. "
                "[END CONTENT REVIEW]" % label)
    # named piece? ("review the launch email" → title token match)
    target = None
    low = _norm(msg)
    for r in rows:
        toks = [t for t in re.findall(r"[a-z0-9]{4,}", r["title"].lower()) if t not in
                ("email", "newsletter", "draft", "week", "this")]
        if toks and any(t in low for t in toks):
            target = r
            break
    recent_cutoff = (now_sydney() - _dt.timedelta(days=14)).date().isoformat()
    recent = [r for r in rows if (r.get("edited") or "") >= recent_cutoff]
    picks = [target] if target else (recent[:2] or rows[:2])
    parts = ["[CONTENT REVIEW — VERBATIM from Notion %s, fetched %s. Quote ONLY from this text; "
             "if something isn't in it, say it isn't there. Performance stats are NOT available "
             "(GHL email metrics unreachable with current access) — review is copy-only.]"
             % (label, now_sydney().isoformat(timespec="minutes"))]
    for r in picks:
        copy = page_copy(r["id"]) or "(couldn't fetch this page's body)"
        parts.append("--- %s (status: %s, edited %s) ---\n%s" % (r["title"], r["status"] or "?",
                                                                 r["edited"], copy))
    if key == "email":
        rules = _rules_copy()
        if rules:
            parts.append("[NEWSLETTER RULES — verbatim from Notion 'Newsletter SOP — Manual "
                         "First'; critique consistency against THESE rules]\n" + rules)
    parts.append("[END CONTENT REVIEW]")
    return "\n\n".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower())


def _rules_copy() -> str:
    """The Newsletter SOP's verbatim text (child page of the Command Centre page) —
    the 'newsletter rules' the review register critiques against. Cached 1h."""
    hit = _cache.get("rules")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    out = ""
    page_id = (os.environ.get("NOTION_COMMAND_CENTRE_ID") or SOURCES["command"][2]).strip()
    kids = _req("GET", "/blocks/%s/children?page_size=100" % page_id) if page_id else None
    for b in (kids or {}).get("results", []):
        if b.get("type") == "child_page" and "newsletter sop" in (b["child_page"].get("title") or "").lower():
            out = page_copy(b["id"], max_chars=2500) or ""
            break
    _cache["rules"] = (time.time(), out)
    return out
