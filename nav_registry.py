"""
nav_registry.py
---------------
The navigable-target registry for voice/typed UI navigation (AD_SECTION_VOICE_NAV_REPORT
Phase 0). One source of truth for WHAT EXISTS on each surface — the router maps intents
to these targets; the capability answer ("what can you show me?") reads this registry;
nothing is ever navigated that isn't listed here.

Action schema v1 (emitted as SSE event `nav`; unknown fields/targets are ignored
client-side — never a broken page):
    {"v": 1, "type": "navigate"|"set_window"|"filter",
     "target": "<target key>", "params": {...}}
"""
from __future__ import annotations

SCHEMA_VERSION = 1

# CFO-surface scroll anchors: key → (dom_id, spoken name). The 13 existing nav links
# plus the new ad-tracking section.
ANCHORS: dict[str, tuple[str, str]] = {
    "ad_tracking": ("section-ad-tracking", "the ad tracking board"),
    "brief": ("section-brief", "the morning brief"),
    "cash": ("section-cash-position", "the cash position"),
    "forward": ("section-forward", "the forward view"),
    "mrr": ("section-trend", "the MRR trend"),
    "churn": ("section-churn", "churn"),
    "economics": ("section-month-perf", "unit economics"),
    "pnl": ("section-waterfall", "the P&L waterfall"),
    "funnel": ("section-funnel", "the funnel"),
    "clients": ("section-health", "client health"),
    "team": ("section-team", "the team view"),
    "pipeline": ("section-pipeline", "the pipeline"),
    "reps": ("section-reps", "the reps view"),
    "dq": ("section-quality", "data quality"),
    "action_feed": ("section-action-feed", "the action feed"),
    "capital": ("section-capital", "capital allocation"),
}

# Separate pages (full navigation, not a scroll).
PAGES: dict[str, tuple[str, str]] = {
    "leads_page": ("/dashboard/leads", "the leads page"),
    "targets_page": ("/dashboard/targets", "the targets page"),
    "data_sources": ("/dashboard/data-sources", "the data-sources page"),
}

GLOBAL_WINDOW_DAYS = (7, 14, 30, 60, 90)      # the global window bar
ADTRACK_WINDOW_DAYS = (30, 60, 90)            # the ad board's selector
ADTRACK_VERDICTS = ("DOUBLE DOWN", "KILL", "WATCH")
ADTRACK_SORTS = ("spend", "cash", "leads", "qualified", "closes", "ltgp_cac")


def navigate(target: str, **params) -> dict:
    return {"v": SCHEMA_VERSION, "type": "navigate", "target": target,
            "params": {k: v for k, v in params.items() if v is not None}}


def set_window(days: int) -> dict:
    return {"v": SCHEMA_VERSION, "type": "set_window", "params": {"days": int(days)}}


def filter_action(target: str, **params) -> dict:
    return {"v": SCHEMA_VERSION, "type": "filter", "target": target,
            "params": {k: v for k, v in params.items() if v is not None}}


def capability_text(surface: str) -> str:
    """The honest 'what can you show me' answer, per surface."""
    if surface == "timeline":
        return ("Here on the delivery dashboard I can talk you through anything, but the "
                "finance sections — the ad tracking board, cash, funnel, the scoreboard — "
                "live on the finance dashboard. I can speak any of those numbers here, or "
                "you open the finance dashboard and I'll drive it: sections, windows, "
                "drills, all by voice.")
    names = [label for _id, label in ANCHORS.values()]
    pages = [label for _url, label in PAGES.values()]
    return ("On this dashboard I can pull up: " + ", ".join(names[:9]) + ", "
            + ", ".join(names[9:]) + " — plus " + ", ".join(pages) + ". "
            "On the ad board I can switch the window (30, 60, 90 days), drill into a "
            "specific creative, filter to the kills or double-downs, and sort the "
            "scoreboard. Just say it — 'show me the ad board', 'filter to 60 days', "
            "'open Ad B'.")
