"""
triage.py
---------
THE FIVE-LANE TRIAGE ENGINE (ACTION_TRIAGE_REPORT, Rydel-confirmed 2026-08-06).
The action zone shows DECISIONS, not facts. Every raw feed item passes four tests
(real? Rydel's? matters? actionable now?) and lands in exactly one lane:

  ACTION    — Rydel's decisions, ranked by dollars-at-stake, CAPPED at 7 visible,
              every item carries a number-bearing why-line. Never ages out —
              leaves only by decision, delegation, or explicit dismiss/snooze.
  DELEGATED — team work collapsed to rollup lines (detail expandable).
  HYGIENE   — data artifacts → the hygiene panel, off the decision surface.
  WATCH     — visible but quiet; ad-board flags collapse to ONE scorecard line.
  NOISE     — informational events suppressed WITH a stated reason, auditable.

Nothing is deleted: every routing away from ACTION is logged (kv triage:log,
rebuilt per run) and EDITH answers "show me what you suppressed". Dismiss/snooze/
delegate state persists in kv triage:state keyed by the stable fact key.

Dedup doctrine: ONE FACT = ONE LINE. The historical flood (72 lines, 2 decisions)
was driven by the same 19 blank-Close-Date facts emitted twice (data_quality +
"Data integrity:"-prefixed) — the fact key strips prefixes before comparing.
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

_KV_STATE = "triage:state"   # {key: {status, until, who, reason, ts}}
_KV_LOG = "triage:log"       # latest routing table for every non-ACTION item

ACTION_CAP = 7               # ranked by dollars-at-stake; overflow stays visible under "more"
DOLLAR_FLOOR = 500           # below → WATCH unless the category is promoted
# categories promoted to ACTION regardless of the floor (trend/risk beats size)
_PROMOTED = {"anomaly", "failed", "past_due", "attr_verdict", "hire_trigger", "threshold"}
# Rydel's own asks — ACTION by definition (the why-line is the ask itself)
_OWN_ASKS = {"loop", "capital", "collab"}
# informational events — never decisions (suppressed with reason, auditable)
_NOISE_CATS = {"close", "payout", "lead"}


def fact_key(title: str) -> str:
    """Stable key for ONE FACT: prefix-stripped, normalised — the dedup + state key."""
    t = re.sub(r"^\s*data integrity:\s*", "", (title or "").strip(), flags=re.I)
    t = re.sub(r"\s+", " ", t.lower())
    t = re.sub(r"[^a-z0-9 $]", "", t)[:90]
    return hashlib.sha1(t.encode()).hexdigest()[:12]


def _dollars(text: str) -> int | None:
    m = re.search(r"\$([\d,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _number_bearing(text: str) -> bool:
    """The ACTION one-line rule: a why-line must carry a number ($, %, count, ratio)."""
    return bool(re.search(r"[\$%\d]", text or ""))


def _is_blank_date_fact(title: str) -> bool:
    return bool(re.search(r"\b(close date blank|blank close date|missing input date|"
                          r"input date blank|won row missing input date)\b", title or "", re.I))


def _state() -> dict:
    try:
        import kv_store
        return kv_store.get(_KV_STATE) or {}
    except Exception:
        return {}


def _today() -> str:
    from helpers import today_sydney
    return str(today_sydney())


def route(items: list[dict]) -> dict:
    """Classify raw feed items into the five lanes. Deterministic; logs every
    non-ACTION routing with its reason; applies dismiss/snooze/delegate state."""
    state = _state()
    today = _today()
    seen: set[str] = set()
    lanes = {"action": [], "delegated": [], "hygiene": [], "watch": [], "noise": []}
    date_fixes: list[dict] = []        # the Piolo blank-dates rollup detail
    logging_fixes: list[dict] = []     # the team cash-logging rollup detail
    ad_flags: list[dict] = []          # the /ads scorecard rollup detail
    log: list[dict] = []
    user_actioned: list[dict] = []     # dismissed/snoozed items (still auditable)

    for it in items:
        title = it.get("title") or ""
        cat = it.get("category") or ""
        key = fact_key(title)
        if key in seen:                # ONE FACT = ONE LINE — the double-emit killer
            log.append({"key": key, "title": title[:120], "lane": "dedup",
                        "reason": "duplicate of an item already routed (one fact = one line)"})
            continue
        seen.add(key)
        it = dict(it, key=key, dollars=_dollars(title))

        # user state first: dismissed/snoozed/delegated overrides the lane
        st = state.get(key) or {}
        if st.get("status") == "dismissed":
            user_actioned.append(dict(it, reason=f"dismissed by {st.get('who', 'owner')}"
                                                 + (f": {st['reason']}" if st.get("reason") else "")))
            continue
        if st.get("status") == "snoozed" and (st.get("until") or "") >= today:
            user_actioned.append(dict(it, reason=f"snoozed until {st.get('until')}"))
            continue
        if st.get("status") == "delegated":
            lanes["delegated"].append(dict(it, owner=st.get("who") or "team",
                                           why=f"delegated to {st.get('who') or 'team'}"))
            continue

        # lane rules (Rydel-confirmed routing)
        if cat in _NOISE_CATS:
            it["reason"] = "informational event, not a decision (greeting/salience carries it)"
            lanes["noise"].append(it)
            log.append({"key": key, "title": title[:120], "lane": "noise", "reason": it["reason"]})
        elif _is_blank_date_fact(title):
            date_fixes.append(it)      # collapses to ONE delegated line below
        elif cat in ("unlogged", "needs_logging"):
            logging_fixes.append(it)
        elif cat == "attr_flag":
            ad_flags.append(it)        # collapses to ONE watch line linking /ads
        elif cat in ("data_quality", "data_integrity"):
            it["reason"] = "data artifact — the hygiene panel's job, not a decision"
            lanes["hygiene"].append(it)
            log.append({"key": key, "title": title[:120], "lane": "hygiene", "reason": it["reason"]})
        elif cat == "reconciliation":
            if re.search(r"unrecognised|confirm payer", title, re.I):
                it["why"] = "payer identity is your call — one reply teaches the alias"
                lanes["action"].append(it)
            else:
                it["reason"] = "cross-system mismatch — hygiene"
                lanes["hygiene"].append(it)
                log.append({"key": key, "title": title[:120], "lane": "hygiene",
                            "reason": it["reason"]})
        elif cat in _OWN_ASKS:
            it["why"] = "your own open loop — stays until you answer it"
            lanes["action"].append(it)
        elif cat in _PROMOTED:
            it["why"] = title if _number_bearing(title) else "risk signal (promoted past the floor)"
            lanes["action"].append(it)
        else:
            # unmapped generator: borderline defaults to VISIBLE (watch), never silent
            it["reason"] = f"unmapped generator '{cat}' — borderline, kept visible"
            lanes["watch"].append(it)
            log.append({"key": key, "title": title[:120], "lane": "watch", "reason": it["reason"]})

    # the $500 floor: dollar items below it demote to WATCH (promoted cats exempt above)
    kept = []
    for it in lanes["action"]:
        d = it.get("dollars")
        cat = it.get("category") or ""
        if (d is not None and d < DOLLAR_FLOOR and cat not in _PROMOTED
                and cat not in _OWN_ASKS):
            it["reason"] = f"${d:,} is under the ${DOLLAR_FLOOR} action floor — watching"
            lanes["watch"].append(it)
            log.append({"key": it["key"], "title": (it.get("title") or "")[:120],
                        "lane": "watch", "reason": it["reason"]})
        else:
            kept.append(it)
    # rank by dollars-at-stake desc (no dollars → severity order), cap at 7 visible
    sev = {"S1": 0, "S2": 1, "S3": 2}
    kept.sort(key=lambda x: (-(x.get("dollars") or 0), sev.get(x.get("severity"), 3)))
    lanes["action"] = kept

    # the DELEGATED rollups (one line each, detail carried for expansion)
    if date_fixes:
        total = sum((x.get("dollars") or 0) for x in date_fixes)
        lanes["delegated"].insert(0, {
            "rollup": True, "count": len(date_fixes), "owner": "Piolo",
            "title": f"{len(date_fixes)} tracker date fix(es) with Piolo — blank Close/Input "
                     f"Dates" + (f" (~${total:,} contract value invisible until fixed)" if total else ""),
            "detail": [x.get("title") for x in date_fixes], "category": "data_quality",
            "key": "rollup:date_fixes"})
        for x in date_fixes:
            log.append({"key": x["key"], "title": (x.get("title") or "")[:120],
                        "lane": "delegated", "reason": "collapsed into the Piolo date-fix rollup"})
    if logging_fixes:
        lanes["delegated"].append({
            "rollup": True, "count": len(logging_fixes), "owner": "team",
            "title": f"{len(logging_fixes)} cash-logging gap(s) with the team — tracker "
                     f"cells trailing Stripe",
            "detail": [x.get("title") for x in logging_fixes], "category": "needs_logging",
            "key": "rollup:needs_logging"})
        for x in logging_fixes:
            log.append({"key": x["key"], "title": (x.get("title") or "")[:120],
                        "lane": "delegated", "reason": "collapsed into the team logging rollup"})

    # the WATCH rollup for ad flags: ONE line, the scorecard already renders them all
    if ad_flags:
        top = max(ad_flags, key=lambda x: x.get("dollars") or 0)
        lanes["watch"].insert(0, {
            "rollup": True, "count": len(ad_flags), "link": "/dashboard/ads",
            "title": f"{len(ad_flags)} creative flag(s) on the ad board — top: "
                     f"{(top.get('title') or '')[:80]}",
            "detail": [x.get("title") for x in ad_flags], "category": "attr_flag",
            "key": "rollup:attr_flags"})
        for x in ad_flags:
            log.append({"key": x["key"], "title": (x.get("title") or "")[:120],
                        "lane": "watch", "reason": "collapsed into the ad-board scorecard rollup"})

    for it in user_actioned:
        log.append({"key": it["key"], "title": (it.get("title") or "")[:120],
                    "lane": "user", "reason": it["reason"]})

    try:
        import kv_store
        kv_store.put(_KV_LOG, {"as_of": today, "entries": log[:200]})
    except Exception as e:
        logger.info("triage log persist failed: %s", e)

    return {"lanes": lanes, "cap": ACTION_CAP, "floor": DOLLAR_FLOOR,
            "suppressed_count": len(lanes["noise"]) + len(user_actioned),
            "routed_count": len(log), "user_actioned": user_actioned}


def set_state(key: str, status: str, who: str = "", reason: str = "",
              days: int | None = None) -> dict:
    """dismiss / snooze / delegate — the ONLY ways an ACTION item leaves (plus decision).
    Persisted, logged, reversible ('restore')."""
    import datetime as dt
    import kv_store
    from helpers import today_sydney
    s = _state()
    if status == "restore":
        s.pop(key, None)
    else:
        entry = {"status": status, "who": who, "reason": reason, "ts": str(today_sydney())}
        if status == "snoozed":
            entry["until"] = str(today_sydney() + dt.timedelta(days=days or 7))
        s[key] = entry
    kv_store.put(_KV_STATE, s)
    return s.get(key) or {"status": "restored"}


def find_key_by_fragment(frag: str) -> tuple[str | None, str | None]:
    """Resolve a user-typed fragment to the single matching feed item (key, title)."""
    import action_feed
    feed = action_feed.build_action_feed()
    fl = (frag or "").strip().lower()
    hits = [(it.get("key") or fact_key(it.get("title") or ""), it.get("title") or "")
            for it in feed.get("items", []) if fl and fl in (it.get("title") or "").lower()]
    if len(hits) == 1:
        return hits[0]
    return None, None if not hits else f"{len(hits)} items match"


# ── EDITH: the triage partner ────────────────────────────────────────────────

_SUPPRESSED_RE = re.compile(
    r"(show|what).{0,20}(suppress|hid|hidden|filtered|routed away)|suppressed (list|items)|"
    r"what did you (hide|suppress|filter)", re.I)
_TRIAGE_ACT_RE = re.compile(
    r"^\s*(dismiss|snooze|delegate|restore)\s+(.+?)(?:\s+to\s+(\w[\w ]*))?"
    r"(?:\s+for\s+(\d+)\s*days?)?\s*$", re.I)
_WHY_HERE_RE = re.compile(r"why (is|are) (this|that|these|it) (here|showing|on the list)|"
                          r"why am i seeing (this|that)", re.I)


def handle_suppressed_command(text: str) -> tuple[str | None, bool]:
    """'show me what you suppressed' — the full audit trail, nothing is silent."""
    if not text or not _SUPPRESSED_RE.search(text):
        return None, False
    import kv_store
    lg = kv_store.get(_KV_LOG) or {}
    entries = lg.get("entries") or []
    if not entries:
        return "Nothing has been suppressed or routed away — the zone shows everything raw.", True
    by_lane: dict[str, list] = {}
    for e in entries:
        by_lane.setdefault(e["lane"], []).append(e)
    parts = [f"Routing log (as of {lg.get('as_of')}): {len(entries)} item(s) routed off the "
             f"action list — nothing deleted."]
    labels = {"noise": "SUPPRESSED as noise", "hygiene": "routed to HYGIENE",
              "delegated": "collapsed into DELEGATED rollups", "watch": "moved to WATCH",
              "dedup": "deduped (same fact twice)", "user": "dismissed/snoozed by you"}
    for lane, es in by_lane.items():
        parts.append(f"\n{labels.get(lane, lane)} ({len(es)}):")
        for e in es[:8]:
            parts.append(f"• {e['title'][:90]} — {e['reason']}")
        if len(es) > 8:
            parts.append(f"…and {len(es) - 8} more.")
    return "\n".join(parts), True


def handle_triage_action_command(text: str) -> tuple[str | None, bool]:
    """'dismiss <item>' / 'snooze <item> for N days' / 'delegate <item> to <who>' /
    'restore <item>' — explicit, logged, reversible."""
    m = _TRIAGE_ACT_RE.match(text or "")
    if not m:
        return None, False
    verb, frag, who, days = m.group(1).lower(), m.group(2), m.group(3), m.group(4)
    key, title = find_key_by_fragment(frag)
    if not key:
        hint = title if isinstance(title, str) else None
        return (f"I couldn't pin that to one item{' — ' + hint if hint else ''}. "
                f"Give me a more specific fragment of its title.", True)
    status = {"dismiss": "dismissed", "snooze": "snoozed", "delegate": "delegated",
              "restore": "restore"}[verb]
    set_state(key, status, who=(who or "").strip(), days=int(days) if days else None)
    if verb == "snooze":
        return f"Snoozed for {days or 7} days: {title[:90]} — it comes back after that.", True
    if verb == "delegate":
        return f"Delegated to {who or 'the team'}: {title[:90]} — it moves to the delegated line.", True
    if verb == "restore":
        return f"Restored: {title[:90]} — back in its lane.", True
    return f"Dismissed: {title[:90]} — logged and recoverable ('restore {frag}').", True


def handle_why_here_command(text: str) -> tuple[str | None, bool]:
    """'why is this here' — the lane rules in one breath."""
    if not text or not _WHY_HERE_RE.search(text):
        return None, False
    import action_feed
    feed = action_feed.build_action_feed()
    acts = (feed.get("lanes") or {}).get("action") or []
    if not acts:
        return ("The action list is empty — everything current is routed: hygiene to the "
                "hygiene panel, team work to the delegated line, ad flags to the /ads "
                "scorecard. Ask 'show me what you suppressed' for the full log.", True)
    lines = [f"{len(acts)} item(s) passed the four tests (real, yours, material, actionable):"]
    for it in acts[:ACTION_CAP]:
        lines.append(f"• {(it.get('title') or '')[:80]} — {it.get('why') or 'your decision'}")
    return "\n".join(lines), True
