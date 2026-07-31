"""
open_loops.py
-------------
Pillar 1A — OPEN-LOOP TRACKING, INTERNAL/SYSTEM ONLY. EDITH holds the threads that are hers or the
system's to close, and resurfaces them with manners (once per cadence, watermarked, "drop it" kills
one). She NEVER creates or chases a client-deal loop — those surface passively on the dashboard only
(the hard internal-only boundary). The loops here are:

  · SYSTEM loops (derived each cycle): pending technical gates + degraded integrations awaiting a
    Rydel action — the Stripe read-only key, Xero re-auth, capital buffer unset, unreviewed borderline
    test-leads, aging Piolo-queue items.
  · REMINDER loops (explicit): "remind me to review the quarterly Friday" — Rydel's own request is the
    loop's authority (it reminds HIM; it is not outreach).

Resolution is silent (the gate clears / the reminder is acknowledged / it's dropped). Follow-ups obey
etiquette: at most every FOLLOWUP_DAYS, watermarked via last_followed_at; "drop it" is permanent.

Store: kv_store (durable, Postgres-backed). No client, prospect, lead, or deal content ever.
"""
from __future__ import annotations

import logging
import re

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_K = "openloops:reminders"        # only explicit reminders persist; system loops are derived live
FOLLOWUP_DAYS = 3                  # never nag more often than this

# Guard: a reminder that reads like EDITH-chasing-a-client is refused (the boundary). Rydel reminding
# himself about anything is fine; EDITH proactively contacting/chasing a client is not — but a reminder
# is internal (to Rydel), so we only block phrasing that implies OUTBOUND contact by EDITH.
_OUTBOUND_CLIENT = re.compile(r"\b(email|message|text|call|dm|contact|chase|reach out to|follow up with)\b.*\b(client|customer|lead|prospect|them|the venue)\b", re.I)


def _load() -> list[dict]:
    return kv_store.get(_K) or []


def _save(loops: list[dict]) -> None:
    kv_store.put(_K, loops[-100:])


def _next_id(loops: list[dict]) -> int:
    return (max((l.get("id", 0) for l in loops), default=0) + 1)


def add_reminder(what: str, follow_up: str | None = None, importance: int = 78) -> dict:
    loops = _load()
    lid = _next_id(loops)
    loops.append({"id": lid, "kind": "reminder", "what": what.strip(),
                  "follow_up": (follow_up or f"you asked me to remind you: {what.strip()}"),
                  "created_at": str(today_sydney()), "last_followed": None,
                  "importance": importance, "resolved": False, "dropped": False})
    _save(loops)
    return {"id": lid}


def resolve(loop_id: int) -> bool:
    loops = _load()
    for l in loops:
        if l.get("id") == loop_id and l["kind"] == "reminder":
            l["resolved"] = True
            _save(loops)
            return True
    return False


def drop(loop_id: int | None = None, match: str | None = None) -> int:
    """Kill a loop permanently. By id, or by fuzzy match on the most recent surfaced reminder."""
    loops = _load()
    n = 0
    for l in loops:
        if l.get("dropped") or l.get("resolved"):
            continue
        if (loop_id is not None and l.get("id") == loop_id) or \
           (match and match.lower() in (l.get("what", "") + l.get("follow_up", "")).lower()):
            l["dropped"] = True
            n += 1
    if loop_id is None and match is None and loops:
        # "drop it" with no target → drop the most recently followed-up reminder
        active = [l for l in loops if not l.get("dropped") and not l.get("resolved")]
        if active:
            active.sort(key=lambda x: (x.get("last_followed") or "", x.get("id")), reverse=True)
            active[0]["dropped"] = True
            n = 1
    _save(loops)
    return n


def _days_since(datestr: str | None) -> int | None:
    if not datestr:
        return None
    try:
        import datetime as dt
        return (today_sydney() - dt.date.fromisoformat(str(datestr)[:10])).days
    except Exception:
        return None


# ── SYSTEM loops (derived live from real state — internal/technical only) ─────

def system_loops(snap: dict | None = None) -> list[dict]:
    """Pending technical gates + degraded integrations awaiting a Rydel action. Derived, verbatim
    from real state — never invented, never client-deal."""
    from snapshot import load_persisted
    snap = snap or load_persisted() or {}
    loops: list[dict] = []

    degraded = snap.get("degraded") or []
    # Xero re-auth needed
    if any("xero" in str((d or {}).get("reason", "")).lower() and "auth" in str((d or {}).get("reason", "")).lower()
           for d in degraded):
        loops.append({"kind": "system", "id": "sys:xero_reauth", "importance": 80,
                      "follow_up": "Xero looks like it needs a re-auth (cash is on last-known) — reconnect when you can"})
    # capital buffer not configured (a Rydel decision gate — internal)
    try:
        import capital_allocation
        cap = capital_allocation.compute_state()
        if cap.get("state") == "not_configured":
            loops.append({"kind": "system", "id": "sys:capital_unset", "importance": 45,
                          "follow_up": "your capital survival buffer + assumed return aren't set — the deploy layer's waiting on them"})
    except Exception:
        pass
    # Stripe read-only key gate (a pending technical gate) — read from degraded, cheap.
    if any("stripe" in str((d or {}).get("metric", "")).lower() and "key" in str((d or {}).get("reason", "")).lower()
           for d in degraded):
        loops.append({"kind": "system", "id": "sys:stripe_key", "importance": 70,
                      "follow_up": "the Stripe read-only key looks unset — some payment reads are limited until it's added"})
    # NOTE: system_loops runs INSIDE salience.collect (and action_feed → salience.collect), so it must
    # stay CHEAP and NON-RECURSIVE — no collab.queue (that path calls action_feed → salience, a cycle)
    # and no test_leads.scan (heavy). Those hygiene items surface via their own dashboard panels.
    return loops


# ── Follow-up surfacing (for salience/greeting) ──────────────────────────────

def due_followups(snap: dict | None = None) -> list[dict]:
    """Loops due to resurface: unresolved/undropped reminders past the cadence + all live system
    loops. Each carries a stable watermark id so the greeting layer never nags twice."""
    out = []
    for l in _load():
        if l.get("resolved") or l.get("dropped"):
            continue
        since = _days_since(l.get("last_followed") or l.get("created_at"))
        if l.get("last_followed") and since is not None and since < FOLLOWUP_DAYS:
            continue   # nagged too recently
        out.append({"loop_id": l["id"], "kind": "reminder", "importance": l.get("importance", 50),
                    "spoken": l["follow_up"], "watermark": f"loop:reminder:{l['id']}:{today_sydney()}"})
    for s in system_loops(snap):
        out.append({"loop_id": s["id"], "kind": "system", "importance": s.get("importance", 50),
                    "spoken": s["follow_up"], "watermark": f"loop:{s['id']}"})
    out.sort(key=lambda x: x["importance"], reverse=True)
    return out


def mark_followed(loop_ids: list) -> None:
    """Watermark reminders that a greeting actually surfaced (system loops watermark via salience)."""
    loops = _load()
    changed = False
    for l in loops:
        if l.get("id") in loop_ids and l["kind"] == "reminder":
            l["last_followed"] = str(today_sydney())
            changed = True
    if changed:
        _save(loops)


# ── Voice/text: "remind me to X", "drop it" ──────────────────────────────────

_REMIND_RE = re.compile(r"\bremind me (to |about |that )?(.+)", re.I)
_DROP_RE = re.compile(r"\b(drop|forget|cancel|kill|nevermind|never mind|clear) (it|that|the reminder|this)\b"
                      r"|\bdrop that reminder\b|\bstop reminding me\b", re.I)
_WHEN_RE = re.compile(r"\b(tomorrow|today|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                      r"next week|this week|in \d+ days?|on the \d+)\b", re.I)


def handle_command(text: str, actor: dict | None = None) -> tuple[str | None, bool]:
    if not text:
        return None, False
    if _DROP_RE.search(text):
        n = drop()
        return ("Dropped — I won't bring that up again." if n else "Nothing active to drop."), True
    m = _REMIND_RE.search(text)
    if m:
        body = m.group(2).strip().rstrip(".")
        if not body:
            return None, False
        # Boundary: EDITH won't be asked to CONTACT a client; a self-reminder is fine.
        if _OUTBOUND_CLIENT.search(text):
            return ("I can remind *you* about that, but I don't contact clients or leads — that's off "
                    "limits by design. Want me to just remind you to do it yourself?"), True
        when = _WHEN_RE.search(text)
        when_txt = f" ({when.group(0)})" if when else ""
        add_reminder(body, follow_up=f"you asked me to remind you: {body}{when_txt}")
        return (f"Got it — I'll remind you: {body}{when_txt}. Say 'drop it' anytime to clear it."), True
    return None, False
