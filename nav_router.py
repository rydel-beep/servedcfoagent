"""
nav_router.py
-------------
"Show me X" is a NAVIGATION COMMAND, not an impossible display request. This router
runs FIRST in the deterministic chain so a display ask can never fall through to the
model (whose emergent "I'm text and voice only" line caused the incident this build
fixes). Every navigation pairs an ACTION (SSE `nav` event, schema in nav_registry) with
a SHORT spoken confirmation that adds value — never a silent jump, never a monologue.

Channel honesty: on the TIMELINE surface (until Part 2 adopts the handler) the same
intents return the honest cross-surface answer — the section lives on the finance
dashboard; numbers offered aloud — and NO action is emitted.

Entity gating: creatives resolve against the LIVE engine result (cached). Ambiguous →
ask, listing the candidates. Nonexistent → honest refusal, NO navigation. Figures in
confirmations come from the same engine result — no new math anywhere here.
"""
from __future__ import annotations

import logging
import re

import nav_registry as R

logger = logging.getLogger(__name__)

_NAV_VERB = r"(?:show me|show|open|pull up|bring up|go to|take me to|navigate to|jump to|back to|switch to)"

_AD_BOARD_RE = re.compile(
    _NAV_VERB + r"\s+(?:the\s+)?(?:ad|ads|advert\w*|attribution|creative)\s*"
                r"(?:tracking\s*)?(?:dashboard|board|section|page|scoreboard|tracker)\b", re.I)
_SCOREBOARD_RE = re.compile(_NAV_VERB + r"\s+(?:the\s+)?scoreboard\b", re.I)

_ANCHOR_PHRASES = {
    "brief": r"(?:morning\s+)?brief",
    "cash": r"cash(?:\s+position)?",
    "forward": r"forward(?:\s+view)?",
    "mrr": r"mrr(?:\s+trend)?",
    "churn": r"churn",
    "economics": r"(?:unit\s+)?economics",
    "pnl": r"p\s*&\s*l|pnl|waterfall",
    "funnel": r"funnel",
    "clients": r"client\s*health|clients?\s+(?:section|view|page)",
    "team": r"team\s+(?:section|view|page)|capacity\s+(?:section|view)",
    "pipeline": r"pipeline",
    "reps": r"reps?\s+(?:section|view|page)",
    "dq": r"data\s+quality|dq\s+(?:section|view)",
    "action_feed": r"action\s+feed",
    "capital": r"capital(?:\s+allocation)?",
}
_PAGE_PHRASES = {
    "leads_page": r"leads?\s+page|lead\s+reactivation",
    "targets_page": r"targets?\s+page",
    "data_sources": r"data\s+sources?(?:\s+page)?",
}

_WINDOW_RE = re.compile(
    r"(?:filter|set|switch|change|go)\s+(?:\w+\s+){0,2}?to\s+(?:the\s+)?(?:last\s+)?(\d{1,3})\s*"
    r"d(?:ays?)?\b|(\d{1,3})\s*day\s+window", re.I)
_KILLS_RE = re.compile(
    r"(?:just|only|filter\s+to|show)\s+(?:show\s+)?(?:me\s+)?(?:the\s+)?"
    r"(?:ones?\s+to\s+kill|kills?|double[\s-]downs?|watch(?:es|list)?)\b", re.I)
_SORT_RE = re.compile(r"(?:now\s+)?sort(?:\s+(?:it|them|the\s+board))?\s+by\s+(\w[\w :]*)", re.I)
_DRILL_RE = re.compile(
    _NAV_VERB + r"\s+(?:the\s+creative\s+|creative\s+|ad\s+)?[\"“']?(?P<cr>[\w][\w .&·()\[\]/-]{1,60}?)[\"”']?\s*$", re.I)
_CAPABILITY_RE = re.compile(
    r"what\s+can\s+you\s+(?:show|display|pull\s+up)|what\s+(?:sections|views|screens)\s+"
    r"(?:are\s+there|can\s+i\s+see)|can\s+you\s+(?:show|display)\s+(?:things|stuff|anything)", re.I)


def _cached_result(days: int = 30):
    """The engine's in-process cached result if warm — nav replies never force a long
    recompute just to decorate a confirmation."""
    try:
        import attribution_engine as AE
        from helpers import today_sydney
        import datetime as dt
        w1 = today_sydney()
        w0 = w1 - dt.timedelta(days=days - 1)
        hit = AE._cache.get((str(w0), str(w1)))
        return hit[1] if hit else None
    except Exception:
        return None


def _engine(days: int = 30):
    import attribution_engine as AE
    return AE.compute(days=days)


def _ad_board_line() -> str:
    r = _cached_result(30)
    if not r:
        return "Pulling up the ad tracking board."
    t = r.get("totals") or {}
    top = next((c for c in r.get("creatives") or [] if c["tier"] == "ad"
                and (c["spend"] or c["leads"])), None)
    bits = [f"{t.get('attribution_rate_pct')}% of the window's leads are ad-attributed"]
    if top:
        bits.append(f"top spender is {top['label'][:40]} — "
                    f"{top['leads']} leads, {top['closes']} closes")
    return "Pulling up the ad tracking board — " + "; ".join(bits) + "."


def _resolve_creative(name: str):
    """(matches, source_result). Tries the 30d live result, then a warm 90d cache."""
    nl = name.strip().lower()
    for result in (_engine(30), _cached_result(90)):
        if not result:
            continue
        ads = [c for c in result.get("creatives") or [] if c["tier"] == "ad"]
        hits = [c for c in ads if nl in c["label"].lower() or nl in c["creative_key"]]
        if hits:
            return hits, result
    return [], None


def handle(text: str, ui: dict | None = None, channel: str = "text"):
    """→ (reply, actions, handled). actions=[] on the timeline channel (honest
    cross-surface) and on refusals/asks (no navigation without certainty)."""
    t = (text or "").strip()
    if not t:
        return None, [], False
    ui = ui or {}
    on_timeline = channel == "timeline"
    on_ad_board = (ui.get("section") == "ad_tracking")

    if _CAPABILITY_RE.search(t):
        return R.capability_text("timeline" if on_timeline else "dashboard"), [], True

    # ── the ad board itself ──────────────────────────────────────────────────
    if _AD_BOARD_RE.search(t) or _SCOREBOARD_RE.search(t):
        if on_timeline:
            return ("The ad tracking board lives on the finance dashboard — I can't "
                    "render it here, but I can drive it there, or speak the numbers "
                    "now: want the scoreboard read out?"), [], True
        return _ad_board_line(), [R.navigate("ad_tracking")], True

    # ── window changes (thread-aware: the ad board's own selector when active) ─
    m = _WINDOW_RE.search(t)
    if m and (on_ad_board or re.search(r"window|filter|day", t, re.I)):
        days = int(m.group(1) or m.group(2))
        if on_timeline:
            return None, [], False       # not a display surface; let data handlers speak
        if on_ad_board:
            if days not in R.ADTRACK_WINDOW_DAYS:
                return (f"The ad board runs 30, 60 or 90-day windows — "
                        f"{days} isn't one of them. Which do you want?"), [], True
            return f"Switching the ad board to {days} days.", \
                [R.filter_action("ad_tracking", window=days)], True
        if days in R.GLOBAL_WINDOW_DAYS:
            return f"Setting the window to {days} days.", [R.set_window(days)], True
        return (f"The dashboard windows are 7, 14, 30, 60 or 90 days — "
                f"{days} isn't available. Which one?"), [], True

    # ── verdict filter / sort on the ad board ────────────────────────────────
    m = _KILLS_RE.search(t)
    if m and (on_ad_board or re.search(r"kill|double[\s-]down|watch", t, re.I)):
        raw = m.group(0).lower()
        verdict = ("KILL" if "kill" in raw else
                   "DOUBLE DOWN" if "double" in raw else "WATCH")
        if on_timeline:
            return None, [], False
        actions = [R.filter_action("ad_tracking", verdict=verdict)]
        lead_in = ""
        if not on_ad_board:
            actions.insert(0, R.navigate("ad_tracking"))
            lead_in = "Opening the ad board — "
        label = {"KILL": "the kill candidates", "DOUBLE DOWN": "the double-downs",
                 "WATCH": "the watch list"}[verdict]
        return f"{lead_in}filtering to {label}.", actions, True

    m = _SORT_RE.search(t)
    if m and on_ad_board:
        key = m.group(1).strip().lower().replace(" ", "_")
        alias = {"cash": "cash", "spend": "spend", "leads": "leads", "closes": "closes",
                 "qualified": "qualified", "ltgp_cac": "ltgp_cac", "ltgp": "ltgp_cac",
                 "cost_per_close": "cost_per_close"}.get(key)
        if not alias:
            return (f"I can sort the board by spend, cash, leads, qualified, closes or "
                    f"LTGP-to-CAC — not by “{m.group(1).strip()}”."), [], True
        return f"Sorted by {m.group(1).strip()}.", \
            [R.filter_action("ad_tracking", sort=alias)], True

    # ── pages + anchors ──────────────────────────────────────────────────────
    verb = re.match(_NAV_VERB, t, re.I)
    if verb:
        rest = t[verb.end():].strip()
        for key, pat in _PAGE_PHRASES.items():
            if re.match(r"(?:the\s+)?(?:" + pat + r")\s*[.!?]?$", rest, re.I):
                url, label = R.PAGES[key]
                if on_timeline:
                    return (f"{label.capitalize()} is on the finance dashboard — I can't "
                            f"open it from here. Want the numbers spoken instead?"), [], True
                return f"Opening {label}.", [R.navigate(key)], True
        for key, pat in _ANCHOR_PHRASES.items():
            if re.match(r"(?:the\s+)?(?:" + pat + r")\s*(?:section|view|page)?\s*[.!?]?$",
                        rest, re.I):
                _dom, label = R.ANCHORS[key]
                if on_timeline:
                    return (f"That section lives on the finance dashboard — want me to "
                            f"speak the numbers here instead?"), [], True
                return f"Taking you to {label}.", [R.navigate(key)], True

        # ── creative drill: entity-gated, never a guessed navigation ─────────
        m = _DRILL_RE.match(t)
        cr = (m.group("cr") or "").strip() if m else ""
        cr = re.sub(r"^(?:the|that|this)\s+", "", cr, flags=re.I)
        if cr and len(cr) >= 2 and cr.lower() not in ("me", "it", "that", "the", "this"):
            hits, result = _resolve_creative(cr)
            if len(hits) == 1:
                c = hits[0]
                if on_timeline:
                    return (f"{c['label'][:50]}: {c['leads']} leads, {c['closes']} closes, "
                            f"${c['cash']:,.0f} cash — the drill view is on the finance "
                            f"dashboard."), [], True
                v = c.get("verdict")
                line = (f"Pulling it up — {c['label'][:45]}"
                        + (f" carries the {v.lower()} badge" if v and v != "WATCH"
                           else f" is gated {c.get('gates', {}).get('gate', 'watch')[:40]}" if c.get("gates") else "")
                        + f"; {c['closes']} close(s), ${c['cash']:,.0f} cash on "
                          f"${c['spend']:,.0f} spend.")
                return line, [R.navigate("ad_tracking", creative=c["creative_key"],
                                         drill=True)], True
            if len(hits) > 1:
                names = "; ".join(h["label"][:40] for h in hits[:3])
                return (f"{len(hits)} creatives match “{cr}”: {names} — "
                        f"which one?"), [], True
            if re.search(r"\bad\b|creative|graphic|vsl|b0\d|g\d", cr, re.I):
                return (f"I don't see a creative matching “{cr}” on the board — "
                        f"I won't guess. Say 'show me the ad board' to scan the list."), [], True

    return None, [], False
