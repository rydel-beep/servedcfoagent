"""
convo_quality.py
----------------
THE CONVERSATION SELF-IMPROVEMENT LOOP (VOICE_MEMORY_SELFIMPROVE_REPORT, the
upgrade): failures become captured incidents, incidents become permanent tests,
quality is measured over time instead of re-fixed per complaint.

  A. INCIDENT CAPTURE — silent, real-time, cheap: corrections ("I told you"),
     repeated information, asked-answered near-misses (the pre-ask check firing
     IS an incident — prevention logged, not just failure), voice fallbacks.
  B. WEEKLY SELF-REVIEW — counts by class, trend vs prior weeks, worst exchanges
     verbatim, register drift (canned phrases), PROPOSALS (confirmation-gated,
     never auto-applied to her behaviour).
  C. INCIDENT → TEST — every confirmed class has a regression test in the suite.
  D. METRICS — incidents/100 turns, asked-answered count (target 0), fallback
     count, weekly trend.
  E. EDITH ON HERSELF — "how's your conversation quality been?" answered
     truthfully, worst moment included.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KV_INCIDENTS = "convo:incidents"        # capped list {ts, class, snippet}
_KV_WEEKLY = "convo:quality_weekly"      # {iso_week: report}
_KV_PROPOSALS = "convo:proposals"        # confirmation-gated suggestions
_KV_APPLIED = "convo:applied"            # confirmed + applied fixes (the learning log)
_KV_AVOID = "convo:avoid_phrases"        # the avoid-list the persona reads
_KV_TICK = "convo:weekly_tick"

CLASSES = ("correction", "repeated_info", "asked_answered", "asked_answered_near_miss",
           "voice_fallback", "register_drift")

_CORRECTION_RE = re.compile(
    r"\bi (already )?told you\b|\bno[, ]+i said\b|\bwe (already )?(discussed|covered|went over)\b|"
    r"\bas i (said|told you)\b|\byou('re| are) repeating\b|\bi just said\b", re.I)
# canned phrases that mean register drift when they creep into her replies
_CANNED = ("great question", "i hope this helps", "let me know if", "as an ai",
           "certainly!", "absolutely!", "happy to help", "in today's")


def record_incident(cls: str, snippet: str, context: str = "") -> None:
    """Silent capture — no user-facing friction, never raises."""
    if cls not in CLASSES:
        cls = "correction"
    try:
        import kv_store
        from helpers import now_sydney
        inc = kv_store.get(_KV_INCIDENTS) or []
        inc.append({"ts": now_sydney().isoformat(timespec="seconds"), "class": cls,
                    "snippet": (snippet or "")[:200], "context": (context or "")[:120]})
        kv_store.put(_KV_INCIDENTS, inc[-500:])
    except Exception as e:
        logger.info("incident capture failed: %s", e)


def scan_user_turn(text: str) -> None:
    """Called on every recorded user turn: detects corrections + answers that
    resolve open loops. Cheap regex + the loop matcher; silent."""
    if not text:
        return
    try:
        if _CORRECTION_RE.search(text):
            record_incident("correction", text)
        import open_loops
        for r in open_loops.check_resolution(text):
            logger.info("loop resolved from conversation: %s", r)
    except Exception as e:
        logger.info("scan_user_turn failed: %s", e)


def _week(d) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def metrics(days: int = 7) -> dict:
    """The tracked set: incidents by class (window), per-100-turns, fallback count,
    asked-answered (target: ZERO)."""
    import kv_store
    from helpers import now_sydney
    import datetime as dt
    cutoff = (now_sydney() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    inc = [i for i in (kv_store.get(_KV_INCIDENTS) or []) if i["ts"] >= cutoff]
    by_class = {}
    for i in inc:
        by_class[i["class"]] = by_class.get(i["class"], 0) + 1
    turns = None
    try:
        import db
        if db.db_configured():
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM messages "
                            "WHERE created_at > now() - (%s * interval '1 day')", (days,))
                turns = cur.fetchone()["n"]
    except Exception:
        pass
    vh = {}
    try:
        import voice_health
        vh = voice_health.status()
    except Exception:
        pass
    per100 = round(len(inc) / turns * 100, 1) if turns else None
    return {"window_days": days, "incidents_total": len(inc), "by_class": by_class,
            "turns": turns, "incidents_per_100_turns": per100,
            "asked_answered": by_class.get("asked_answered", 0),
            "asked_answered_near_miss": by_class.get("asked_answered_near_miss", 0),
            "voice_fails_today": vh.get("fails_today"),
            "worst": max(inc, key=lambda x: x["ts"]) if inc else None,
            "recent": inc[-5:]}


def weekly_review() -> dict:
    """The self-review job: metrics + register drift scan + trend + proposals
    (confirmation-gated). Persisted per ISO week."""
    import kv_store
    from helpers import now_sydney
    m = metrics(7)
    drift_hits = []
    try:
        import db
        if db.db_configured():
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT content FROM messages WHERE role = 'assistant' "
                            "AND created_at > now() - interval '7 day' "
                            "ORDER BY created_at DESC LIMIT 300")
                for r in cur.fetchall():
                    low = (r["content"] or "").lower()
                    for ph in _CANNED + tuple(kv_store.get(_KV_AVOID) or []):
                        if ph in low:
                            drift_hits.append({"phrase": ph, "snippet": r["content"][:120]})
                            record_incident("register_drift", r["content"][:150], ph)
    except Exception as e:
        logger.info("drift scan failed: %s", e)

    weekly = kv_store.get(_KV_WEEKLY) or {}
    wk = _week(now_sydney().date())
    prev = sorted(k for k in weekly if k < wk)
    prev_total = weekly.get(prev[-1], {}).get("incidents_total") if prev else None
    report = {**m, "week": wk, "register_drift_hits": drift_hits[:10],
              "prior_week_total": prev_total,
              "trend": (None if prev_total is None else m["incidents_total"] - prev_total)}

    # proposals — NEVER auto-applied; Rydel confirms ('apply proposal N')
    proposals = kv_store.get(_KV_PROPOSALS) or []
    have = {p["text"] for p in proposals}
    for d in {h["phrase"] for h in drift_hits}:
        t = f"add '{d}' to the avoid-list (register drift, seen this week)"
        if t not in have and d not in (kv_store.get(_KV_AVOID) or []):
            proposals.append({"text": t, "kind": "avoid_phrase", "value": d, "week": wk})
    if m["asked_answered"] > 0:
        t = "tighten the pre-ask recall threshold (an asked-answered got through)"
        if t not in have:
            proposals.append({"text": t, "kind": "note", "value": None, "week": wk})
    kv_store.put(_KV_PROPOSALS, proposals[-20:])
    weekly[wk] = report
    kv_store.put(_KV_WEEKLY, weekly)
    return report


def weekly_tick() -> bool:
    import kv_store
    from helpers import now_sydney
    wk = _week(now_sydney().date())
    if kv_store.get(_KV_TICK) == wk:
        return False
    try:
        weekly_review()
        kv_store.put(_KV_TICK, wk)
        return True
    except Exception as e:
        logger.warning("weekly review tick failed: %s", e)
        return False


def avoid_phrases() -> list[str]:
    import kv_store
    return kv_store.get(_KV_AVOID) or []


# ── EDITH on herself ─────────────────────────────────────────────────────────

_QUALITY_RE = re.compile(r"(how'?s|how is|what'?s) your (conversation|convo) quality|"
                         r"conversation quality (been|report|this week)|"
                         r"how (are|have) you (been )?(doing|performing) (in )?conversation", re.I)
_LEARNED_RE = re.compile(r"what did you learn (this|last) week|what have you (learned|improved)", re.I)
_PROPOSALS_RE = re.compile(r"(quality|improvement) proposals?|proposed (fixes|improvements)", re.I)
_APPLY_RE = re.compile(r"apply proposal (\d+)", re.I)


def handle_quality_command(text: str) -> tuple[str | None, bool]:
    import kv_store
    if not text:
        return None, False
    m = _APPLY_RE.search(text)
    if m:
        idx = int(m.group(1)) - 1
        proposals = kv_store.get(_KV_PROPOSALS) or []
        if not (0 <= idx < len(proposals)):
            return f"No proposal {idx + 1} — say 'quality proposals' to list them.", True
        p = proposals.pop(idx)
        if p["kind"] == "avoid_phrase" and p.get("value"):
            avoid = kv_store.get(_KV_AVOID) or []
            if p["value"] not in avoid:
                avoid.append(p["value"])
            kv_store.put(_KV_AVOID, avoid)
        applied = kv_store.get(_KV_APPLIED) or []
        from helpers import today_sydney
        applied.append({"ts": str(today_sydney()), "text": p["text"]})
        kv_store.put(_KV_APPLIED, applied[-50:])
        kv_store.put(_KV_PROPOSALS, proposals)
        return f"Applied (on your confirmation): {p['text']}", True
    if _PROPOSALS_RE.search(text):
        proposals = kv_store.get(_KV_PROPOSALS) or []
        if not proposals:
            return "No pending quality proposals.", True
        return "\n".join([f"{i}. {p['text']}" for i, p in enumerate(proposals[:8], 1)]
                         + ["Say 'apply proposal N' to confirm one — nothing applies itself."]), True
    if _LEARNED_RE.search(text):
        applied = kv_store.get(_KV_APPLIED) or []
        if not applied:
            return ("Nothing confirmed-and-applied yet this week — proposals wait for "
                    "your sign-off ('quality proposals' lists them)."), True
        return "Applied fixes (each one you confirmed):\n" + "\n".join(
            f"• [{a['ts']}] {a['text']}" for a in applied[-6:]), True
    if _QUALITY_RE.search(text):
        m7 = metrics(7)
        parts = [f"Last 7 days: {m7['incidents_total']} conversation-quality incident(s)"]
        if m7["by_class"]:
            parts.append("(" + ", ".join(f"{k}: {v}" for k, v in m7["by_class"].items()) + ")")
        if m7["incidents_per_100_turns"] is not None:
            parts.append(f"— {m7['incidents_per_100_turns']} per 100 turns.")
        parts.append(f"Asked-answered: {m7['asked_answered']} (target zero); "
                     f"near-misses the pre-ask check caught: {m7['asked_answered_near_miss']}.")
        weekly = __import__('kv_store').get(_KV_WEEKLY) or {}
        wks = sorted(weekly)[-2:]
        if len(wks) == 2:
            a, b = weekly[wks[0]]["incidents_total"], weekly[wks[1]]["incidents_total"]
            parts.append(f"Trend: {b} this week vs {a} prior.")
        if m7.get("worst"):
            parts.append(f"Honest worst moment: [{m7['worst']['class']}] "
                         f"\"{m7['worst']['snippet'][:100]}\".")
        return " ".join(parts), True
    return None, False
