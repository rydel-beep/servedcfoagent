"""shell.py — THE PERSISTENT SHELL (the finish line, Part 1).

Before this, every page was its own island: no nav, no way to get from one
surface to another except the landing's card grid, and no way to tell where
you were. This module computes the nav ONCE, server-side, so it is part of
the first paint like every other headline — JS enhances it (the palette, the
shortcuts); it never fills it.

The nav is role-aware and FAIL-CLOSED: an ad_domain session is given the ads
link and nothing else, because the route guards refuse the rest anyway and a
link that 403s is a lie about what you can do.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The jobs, in the order Rydel works them. (key, label, href, owner_only)
NAV = [
    ("today",     "Today",     "/dashboard/today",           False),
    ("ads",       "Ads",       "/ads",                       False),
    ("sales",     "Sales",     "/dashboard/sales",           True),
    ("money",     "Money",     "/dashboard/view/cash",       True),
    ("plan",      "Plan",      "/dashboard/scale",           True),
    ("csm",       "CSM",       "/dashboard/csm",             True),
    ("decisions", "Decisions", "/dashboard/view/decisions",  True),
    ("system",    "System",    "/dashboard/system",          False),
]

# Where each page sits, so a breadcrumb is the real trail and not decoration.
CRUMBS = {
    "today":       [("Today", None)],
    "ads":         [("Ads", None)],
    "sales":       [("Sales", None)],
    "money":       [("Money", "/dashboard/view/cash")],
    "plan":        [("Plan", "/dashboard/scale")],
    "csm":         [("CSM", None)],
    "decisions":   [("Decisions", None)],
    "system":      [("System", None)],
}

# Every area page, and which nav item owns it.
AREA_PARENT = {
    "brief": "today", "sales": "sales", "cash": "money", "unit-econ": "money",
    "projection": "plan", "renewals": "money", "outflows": "money",
    "receivables": "money", "team": "plan", "decisions": "decisions",
    "system": "system",
}


def _decisions_count() -> int | None:
    try:
        import kv_store
        d = (kv_store.get("exec:cache:decisions") or {}).get("data") or {}
        return d.get("count")
    except Exception as e:  # noqa: BLE001
        logger.info("nav decisions count unavailable: %s", e)
        return None


def _health_dot() -> tuple[str, str]:
    """(state, why) for the System dot. Green only when the last triple scan
    passed and it actually ran; a scan that stopped running is amber, never
    silently green."""
    try:
        import ground_truth as GT
        h = GT.health() or {}
        if h.get("stale_warning"):
            return "amber", h["stale_warning"]
        last = h.get("last") or {}
        if not last:
            return "amber", "no scan has recorded a result yet"
        ok = all(last.get(k) is not False
                 for k in ("scan1_ok", "scan2_ok", "scan3_ok"))
        if ok:
            return "green", "the last estate scan passed all three"
        failed = [k.replace("_ok", "") for k in ("scan1_ok", "scan2_ok", "scan3_ok")
                  if last.get(k) is False]
        return "red", f"the last estate scan failed: {', '.join(failed)}"
    except Exception as e:  # noqa: BLE001
        return "amber", f"health unreadable ({str(e)[:60]})"


def nav_context(active: str = "", crumbs: list | None = None) -> dict:
    """What every page needs to render the shell. Cheap: kv reads only, no
    engine call and no external pull on the request path."""
    from dashboard.auth import is_owner, is_finance, is_ad_domain, current_actor
    try:
        owner = is_finance()   # R-PIOLO-PARITY (#167): finance-grade nav
    except Exception:
        owner = False
    try:
        ad_only = is_ad_domain()
    except Exception:
        ad_only = False
    try:
        actor = current_actor()
    except Exception:
        actor = {}

    # NOT "items": jinja resolves `nav.items` to dict.items, the same
    # collision that bit `c.values` in #156. The key is `links`.
    links = []
    if ad_only:
        # fail-closed: the one surface this role may reach
        links.append({"key": "ads", "label": "Ads", "href": "/ads",
                      "active": active == "ads", "count": None})
    else:
        n_dec = _decisions_count()
        import role_access as _RA
        for key, label, href, owner_only in NAV:
            if key == "csm" and owner and not is_owner() and _RA.csm_withdrawn():
                continue          # withdrawn from finance by the owner's toggle
            if owner_only and not owner:
                continue
            links.append({"key": key, "label": label, "href": href,
                          "active": (active == key),
                          "count": (n_dec if key == "decisions" else None)})
    dot, why = ("green", "") if ad_only else _health_dot()
    return {
        "links": links,
        "active": active,
        "crumbs": crumbs if crumbs is not None else CRUMBS.get(active, []),
        "health_dot": dot,
        "health_why": why,
        "actor": actor.get("display") or "",
        "owner": owner,
        "ad_only": ad_only,
    }


def palette_targets(owner: bool, ad_only: bool = False) -> list[dict]:
    """What ⌘K can jump to. Pages always; clients and creatives when the
    caches hold them. Built server-side and embedded, so the palette opens
    instantly and works with one round trip fewer."""
    out = []

    def add(kind, label, href, hint=""):
        out.append({"kind": kind, "label": label, "href": href, "hint": hint})

    if ad_only:
        add("page", "Ads", "/ads", "the ad dashboard")
        return out

    add("page", "Today", "/dashboard/today", "are we winning?")
    add("page", "Ads", "/ads", "creatives, spend, verdicts")
    if owner:
        add("page", "Sales", "/dashboard/sales", "the team scoreboard")
        add("page", "Closes ledger", "/dashboard/closes",
            "every close, its evidence, and what's missing — the one population")
        add("page", "Money", "/dashboard/view/cash", "cash & capital")
        add("page", "Plan", "/dashboard/scale", "the scaling compass")
        add("page", "How we're travelling", "/dashboard/scale/travelling",
            "the live month beside the model")
        add("page", "CSM", "/dashboard/csm", "the owner-only cockpit")
        add("page", "Decisions", "/dashboard/view/decisions", "needs your ruling")
    add("page", "System", "/dashboard/system", "is the estate honest")
    add("page", "Definitions", "/dashboard/definitions", "what every word means")
    for area, label in (("brief", "Morning brief"), ("sales", "Ads & sales"),
                        ("unit-econ", "Unit economics"),
                        ("projection", "Forward projection"),
                        ("renewals", "Renewals & churn"),
                        ("outflows", "Outflows & BAS"),
                        ("receivables", "Receivables"),
                        ("team", "Team & strategy")):
        if area in ("brief", "sales") or owner:
            add("page", label, f"/dashboard/view/{area}")
    add("page", "Work log", "/dashboard/worklog")
    add("page", "Bookkeeping queue", "/dashboard/bookkeeping")
    add("page", "Leads", "/dashboard/leads")

    if owner:
        try:
            from snapshot import load_persisted
            snap = load_persisted() or {}
            for c in ((snap.get("client_health") or {}).get("clients") or [])[:120]:
                name = c.get("name") or c.get("client")
                if name:
                    add("client", name, f"/dashboard/view/renewals#{name}",
                        "client")
        except Exception as e:  # noqa: BLE001
            logger.info("palette clients unavailable: %s", e)
        try:
            import kv_store
            board = kv_store.get("ads_lifecycle:board") or {}
            for row in (board.get("rows") or [])[:80]:
                nm = row.get("name") or row.get("creative")
                if nm:
                    add("creative", nm, f"/ads?creative={nm}", "creative")
        except Exception as e:  # noqa: BLE001
            logger.info("palette creatives unavailable: %s", e)
    return out
