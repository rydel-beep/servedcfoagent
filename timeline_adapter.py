"""
timeline_adapter.py — EDITH's read adapter for the Timeline Dashboard world.

Universal-advisor Phase 2: deterministic, verbatim-grounded reads of the delivery
world (per-client delivery/onboarding state, overdue/stale tasks, signals, client
events, feedback) over the Timeline's token-gated /bridge/data/* API. READ-ONLY —
this module contains no write path of any kind.

Auth: mints the same 60s HMAC bridge tokens (EDITH_BRIDGE_SECRET, shared with the
timeline service) the widget path uses, reversed direction. Fail-honest: if the
bridge is unreachable or unconfigured, handlers SAY so — they never invent
delivery state.

Discipline (matches the rest of the tier-2 handlers):
  • figures/names verbatim from the API payloads — no derived metric math here
  • entity gate: ambiguous client names → ask; unknown names → say not found
  • freshness stated from the Timeline's OWN sync clock, never assumed
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

_TTL = 60
_PURPOSE = "timeline"
_CACHE_SECONDS = 45          # answer-time cache so one spoken exchange = one fetch
_cache: dict[str, tuple[float, dict]] = {}


def _base() -> str:
    return (os.environ.get("TIMELINE_BRIDGE_URL") or "").rstrip("/")


def configured() -> bool:
    return bool(_base() and os.environ.get("EDITH_BRIDGE_SECRET"))


def _mint() -> str:
    secret = (os.environ.get("EDITH_BRIDGE_SECRET") or "").encode()
    payload = "v1:%.6f:%s:%s" % (time.time() + _TTL, "rydel", _PURPOSE)   # µs → unique per request
    sig = base64.urlsafe_b64encode(
        hmac.new(secret, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return payload + "." + sig


def _get(path: str, params: dict | None = None) -> dict | None:
    """Token-per-request GET with a short cache. None on any failure (fail-honest)."""
    key = path + repr(sorted((params or {}).items()))
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_SECONDS:
        return hit[1]
    if not configured():
        return None
    try:
        r = requests.get(_base() + path, params=params,
                         headers={"X-Bridge-Token": _mint()},
                         timeout=int(os.environ.get("HTTP_TIMEOUT", "10")))
        if r.status_code != 200:
            logger.warning("timeline bridge %s -> %s", path, r.status_code)
            return None
        data = r.json()
        _cache[key] = (now, data)
        return data
    except Exception as e:  # noqa: BLE001
        logger.warning("timeline bridge %s failed: %s", path, e)
        return None


# ── fetchers ──────────────────────────────────────────────────────────────────
def overview():
    return _get("/bridge/data/overview")


def client_detail(client_key: str):
    from urllib.parse import quote
    return _get("/bridge/data/client/%s" % quote(client_key or "", safe=""))


def risk():
    return _get("/bridge/data/risk")


def signals(open_only: bool = False):
    return _get("/bridge/data/signals", {"open_only": open_only} if open_only else None)


def events(limit: int = 12):
    return _get("/bridge/data/events", {"limit": limit})


def automation_status():
    return _get("/bridge/data/automation-status")


# ── freshness line (the Timeline's own clock, verbatim) ───────────────────────
def _freshness_line(ov: dict | None) -> str:
    fr = (ov or {}).get("freshness") or {}
    h = fr.get("hours_since_sync")
    if h is None:
        return ""
    if fr.get("stale"):
        return " (Timeline data is STALE — last synced %.1f hours ago.)" % h
    return " (Timeline synced %.1f h ago.)" % h


# ── entity gate ───────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def resolve_client(name: str) -> tuple[dict | None, list]:
    """(match, candidates). match=None + candidates=[] → unknown;
    match=None + candidates=[...] → ambiguous, ask."""
    ov = overview()
    rows = (ov or {}).get("clients") or []
    n = _norm(name)
    if not n or not rows:
        return None, []
    exact = [c for c in rows if _norm(c.get("client_name")) == n or _norm(c.get("client_key")) == n]
    if len(exact) == 1:
        return exact[0], []
    part = [c for c in rows if n in _norm(c.get("client_name")) or n in _norm(c.get("client_key"))]
    if len(part) == 1:
        return part[0], []
    return None, part


_UNREACHABLE = ("I can't reach the Timeline bridge right now, so I won't guess at "
                "delivery state. The dashboard itself is unaffected — try me again shortly.")


# ── tier-2 handlers (message → (reply|None, handled)) ─────────────────────────
_OVERDUE_RE = re.compile(r"\b(overdue|stalled?|stale (?:tasks|work)|behind schedule|slipp(?:ing|ed))\b", re.I)
_SIGNALS_RE = re.compile(r"\b(complaints?|praise|signals?)\b", re.I)
_EVENTS_RE = re.compile(r"\b(client )?events?( coming| upcoming)?\b.*\b(coming up|upcoming|soon|next|scheduled)\b|\bupcoming events\b|\bevents coming up\b", re.I)
_CLIENT_Q_RE = re.compile(
    r"(?:where(?:'s| is)\s+(?P<a>.+?)(?:'s)?\s+(?:onboarding|delivery)\s+(?:at|up to)"
    r"|how(?:'s| is)\s+(?P<b>.+?)\s+(?:doing|going|tracking)(?:\s+overall)?"
    r"|(?:onboarding|delivery)\s+(?:status|state)\s+(?:for|of)\s+(?P<c>.+?)"
    r"|(?:full picture|complete (?:view|picture)|overview)\s+(?:on|of|for)\s+(?P<d>.+?)(?:\s*[—-].*)?)\s*\??$", re.I)

_WEEK_RE = re.compile(r"\bthis week\b|\bpast week\b|\blast 7\b", re.I)


def handle_timeline_risk(msg: str) -> tuple[str | None, bool]:
    """'what's overdue / stalled right now' → the Timeline's own drill, verbatim counts."""
    if not msg or not _OVERDUE_RE.search(msg):
        return None, False
    r = risk()
    if r is None:
        return _UNREACHABLE, True
    ov = overview()
    parts = []
    for key, label in (("overdue", "overdue"), ("at_risk", "at risk"), ("stale", "stale")):
        d = r.get(key) or {}
        total = d.get("total", d.get("count"))
        rows = d.get("items") or d.get("tasks") or []
        if total is None:
            total = len(rows)
        by_client = d.get("per_client") or {}      # the drill's own rollup — verbatim
        if not by_client:
            for t in rows:
                ck = t.get("client_name") or t.get("client_key") or "?"
                by_client[ck] = by_client.get(ck, 0) + 1
        worst = sorted(by_client.items(), key=lambda x: -x[1])[:3]
        head = "%d %s" % (total, label)
        if worst:
            head += " (worst: %s)" % ", ".join("%s %d" % (k, v) for k, v in worst)
        parts.append(head)
    return "Delivery risk right now — %s.%s" % ("; ".join(parts), _freshness_line(ov)), True


def handle_timeline_signals(msg: str) -> tuple[str | None, bool]:
    """'any complaints this week?' / 'any praise?' → real signal rows with dates."""
    if not msg or not _SIGNALS_RE.search(msg):
        return None, False
    data = signals()
    if data is None:
        return _UNREACHABLE, True
    rows = data.get("signals") or []
    want_praise = bool(re.search(r"\bpraise\b", msg, re.I))
    if want_praise:
        rows = [s for s in rows if (s.get("kind") or "") == "positive"]
    else:
        rows = [s for s in rows if (s.get("kind") or "complaint") != "positive"]
    if _WEEK_RE.search(msg):
        from helpers import today_sydney
        import datetime as _dt
        cutoff = (today_sydney() - _dt.timedelta(days=7)).isoformat()
        rows = [s for s in rows if (s.get("created_at") or "") >= cutoff]
        scope = "this week"
    else:
        scope = "on record"
    label = "praise" if want_praise else "complaints"
    if not rows:
        return "No %s %s on the Timeline.%s" % (label, scope, _freshness_line(overview())), True
    rows = sorted(rows, key=lambda s: s.get("created_at") or "", reverse=True)[:5]
    lines = ["%s — %s (%s%s)" % (
        s.get("client_key") or "?",
        (s.get("description") or "").strip()[:110],
        (s.get("created_at") or "")[:10],
        (", severity " + s["severity"]) if s.get("severity") and not want_praise else "")
        for s in rows]
    return "%d %s %s. Most recent: %s.%s" % (
        len(rows), label, scope, " · ".join(lines), _freshness_line(overview())), True


def handle_timeline_events(msg: str) -> tuple[str | None, bool]:
    """'what events are coming up?' → real countdowns."""
    if not msg or not _EVENTS_RE.search(msg):
        return None, False
    data = events()
    if data is None:
        return _UNREACHABLE, True
    evs = data.get("events") or []
    if not evs:
        return "No upcoming client events on the Timeline.%s" % _freshness_line(overview()), True
    lines = []
    for e in evs[:5]:
        lines.append("%s — %s on %s (%s days out, %s/%s deliverables done)" % (
            e.get("client_key") or "?", e.get("name") or "?", e.get("event_date") or "?",
            e.get("days_out", "?"), e.get("done", "?"), e.get("total", "?")))
    return "Upcoming events: %s.%s" % (" · ".join(lines), _freshness_line(overview())), True


def handle_timeline_client(msg: str) -> tuple[str | None, bool]:
    """'where's Pizzicotto's onboarding at' / 'how's X doing overall' → per-client
    delivery state, cross-joined with finance when asked 'overall' (each fact labelled)."""
    if not msg:
        return None, False
    m = _CLIENT_Q_RE.search(msg.strip())
    if not m:
        return None, False
    name = (m.group("a") or m.group("b") or m.group("c") or m.group("d") or "").strip().rstrip("?.!")
    name = re.sub(r"\s*\b(please|thanks|thank you|mate)\b.*$", "", name, flags=re.I).strip()
    if not name or len(name) > 60:
        return None, False
    # pronouns/anaphora are NOT entities — let the conversation brain resolve them
    # from thread context ("how is it doing?" must never substring-match a client)
    if name.lower() in {"it", "that", "this", "he", "she", "they", "them", "we",
                        "things", "everything", "stuff", "business", "the business"}:
        return None, False
    if not configured():
        return None, False          # bridge absent → let the model converse normally
    match, cands = resolve_client(name)
    if match is None and cands:
        return ("A few Timeline clients match \"%s\": %s — which one?"
                % (name, ", ".join(c.get("client_name") or "?" for c in cands[:5])), True)
    if match is None:
        ov = overview()
        if ov is None:
            return _UNREACHABLE, True
        return ("I don't see a client called \"%s\" on the Timeline — I'm not going to "
                "guess. Closest I have is the roster on the dashboard." % name), True
    detail = client_detail(match.get("client_key") or "")
    if detail is None:
        return _UNREACHABLE, True
    h = detail.get("health") or {}
    summ = detail.get("summary") or {}
    bits = ["%s — onboarding: %s" % (match.get("client_name"), detail.get("onboarding_status") or "?"),
            "health %s (%s)" % (h.get("score", "?"), h.get("light", "?")),
            "%s open tasks, %s overdue" % (summ.get("open_tasks", "?"), summ.get("overdue", "?"))]
    comps = detail.get("complaints") or []
    if comps:
        bits.append("%d signal(s) on record, latest %s" % (
            len(comps), (comps[0].get("created_at") or "")[:10]))
    evs = detail.get("events") or []
    if evs:
        e = evs[0]
        bits.append("next event %s on %s" % (e.get("name") or "?", e.get("event_date") or "?"))
    reply = "; ".join(bits) + "." + _freshness_line(overview())
    # cross-domain join, finance side labelled from ITS source
    if re.search(r"\boverall\b|\ball up\b|\bfull picture\b", msg, re.I):
        fin = _finance_line(match.get("client_name") or "")
        if fin:
            reply += " " + fin
    return reply, True


def _finance_line(client_name: str) -> str:
    """Finance join from the CFO snapshot (its own source, labelled). Verbatim fields."""
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        n = _norm(client_name)
        for c in ((snap.get("active_clients") or {}).get("active") or []):
            cn = _norm(c.get("name") or "")
            if not cn or (cn != n and n not in cn and cn not in n):
                continue
            bits = []
            if c.get("current_mrr") is not None:
                bits.append("MRR $%s" % c["current_mrr"])
            if c.get("cash_collected") is not None:
                bits.append("cash collected $%s" % c["cash_collected"])
            if c.get("package"):
                bits.append("package %s" % c["package"])
            if c.get("status"):
                bits.append("status %s" % c["status"])
            if c.get("awaiting_stripe"):
                bits.append("awaiting Stripe")
            if bits:
                return "Finance side (CFO snapshot): %s." % "; ".join(bits)
            return ""
        return ""
    except Exception:  # noqa: BLE001
        return ""


def conversation_context() -> str:
    """Compact delivery-world grounding injected into TIER-3 turns on the timeline
    channel (the deterministic tier-2 handlers stay exact and take precedence). Gives
    the model the REAL client roster + headline risk + freshness so conversational
    delivery talk is grounded, with the entity rule stated in-band. ≤ ~2k chars."""
    ov = overview()
    if ov is None:
        return ("[TIMELINE CONTEXT] The Timeline bridge is unreachable right now — if he "
                "asks about delivery state, SAY SO; never invent tasks, signals or client "
                "state. [END TIMELINE CONTEXT]")
    rows = (ov.get("clients") or [])[:40]
    ents = []
    for c in rows:
        bits = [str(c.get("health_score", "?"))]
        for k in ("overdue", "real_breaches", "open_tasks"):
            if c.get(k):
                bits.append("%s %s" % (k.replace("_", " "), c[k]))
                break
        ents.append("%s (%s)" % (c.get("client_name", "?"), ", ".join(bits)))
    fr = ov.get("freshness") or {}
    tot = ov.get("totals") or {}
    head = ("[TIMELINE CONTEXT — live delivery world, synced %.1fh ago. These are the ONLY "
            "Timeline clients; a name not on this list is NOT a client (say so, never invent). "
            "Figures here are the dashboard's own; deeper task/signal/event detail comes from "
            "the data handlers — if it isn't in front of you, offer to pull it rather than "
            "guessing.]" % (fr.get("hours_since_sync") if fr.get("hours_since_sync") is not None else -1))
    parts = [head]
    if tot:
        parts.append("Totals: " + ", ".join("%s %s" % (k, v) for k, v in list(tot.items())[:6]))
    parts.append("Clients (health): " + "; ".join(ents))
    parts.append("[END TIMELINE CONTEXT]")
    out = "\n".join(parts)
    return out[:2200]


def gate_a_pending() -> list | None:
    """Pending Gate-A PDF reviews (the relay's single pending-state source,
    /bridge/data/gate-a-pending). None = unreachable (say so, never guess)."""
    d = _get("/bridge/data/gate-a-pending")
    if d is None:
        return None
    return d.get("pending") or []
