"""role_access.py — R-PIOLO: the estate, by role, deny by default.

Rydel's ruling (2026-09-23): Piolo sees what Rydel sees — the home dashboard,
Ads, Sales, Money, Plan (the simulator, the compass, how we're travelling),
System, and the decision cards — as READ. He keeps his queue actions. Three
things stay owner-only, each for a stated reason he can lift with one line:

  CSM            the Miguel restructure and the director comp offset. Miguel
                 hears it from Rydel in person first.
  PER-PERSON PAY the comp rules page, the commission column on SALES, and any
                 figure that says what ONE person earns. Piolo sees the TOTAL
                 commission cost inside CAC and outflows — never who earns it.
  MONEY TRUTH    the actions that change what the numbers ARE: applying date
                 cards, confirming proposed closes and payer aliases,
                 declarations, rule edits, refresh and config changes.

HOW IT IS ENFORCED — one central allowlist, not a check per page:

  · a path must appear in COO_READ (GET) or COO_WRITE (anything else);
    everything else is denied, so a NEW route is denied to Piolo until
    somebody puts it in this file on purpose.
  · the carve-outs are checked FIRST and deny even if a path is also listed —
    belt and braces, so a careless addition to the allowlist cannot open one.
  · `@require_owner` stays exactly where it is on the actions. This layer is
    the second lock, not a replacement for the first.

And one rule that has nothing to do with paths: an aggregate that only ONE
person contributed to IS that person's pay. `hide_single_person_total()` is
how a total gets suppressed rather than quietly revealing a carve-out.
"""
from __future__ import annotations

# ── the carve-outs — checked first, deny always ─────────────────────────────

CARVE_OUTS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("csm",
     ("/dashboard/csm", "/dashboard/api/csm/"),
     "the CSM restructure — Miguel hears it from Rydel first"),
    ("per-person pay",
     ("/dashboard/api/comp/",),
     "per-person compensation is owner-only; the total cost is not"),
    ("owner memory",
     ("/dashboard/memory",),
     "EDITH's fact store and conversation transcripts carry owner-scope "
     "context — flagged to Rydel as a judgement call, one line lifts it"),
    ("EDITH's voice",
     ("/dashboard/api/tts", "/dashboard/api/voice-status",
      "/dashboard/api/entrance-audio", "/dashboard/audio/entrance",
      "/dashboard/api/voice-config"),
     "the voice is owner-exclusive; chat is not"),
)

# ── money-truth actions — owner-only, named so the refusal can say why ──────

MONEY_TRUTH: tuple[str, ...] = (
    "/dashboard/api/capital/deploy",
    "/dashboard/api/capital/reset",
    "/dashboard/api/capital/review",
    "/dashboard/api/capital/settings",
    "/dashboard/api/gap/rebuild",
    "/dashboard/api/ghl-backfill",
    "/dashboard/api/health-row",
    "/dashboard/api/outflow-bands/assign",
    "/dashboard/api/projection/config",
    "/dashboard/api/refresh",
    "/dashboard/api/refresh-now",
    "/dashboard/api/renewal/declare",
    "/dashboard/api/renewal/reverse",
    "/dashboard/api/renewal/scan",
    "/dashboard/api/resync",
    "/dashboard/api/scale/bands",
    "/dashboard/api/scale/behaviour-verified",
    "/dashboard/api/scale/commit-plan",
    "/dashboard/api/scale/north-star",      # POST sets the plan's north star
    "/dashboard/api/scale/scenarios",       # POST persists a scenario
    "/dashboard/api/system/run-checks",
    "/dashboard/api/targets/reset",
    "/dashboard/api/targets/set",
    "/dashboard/api/test-leads/confirm",
    "/dashboard/api/test-leads/override",
    "/dashboard/api/travelling/save",
    "/dashboard/api/unmatched/confirm",     # confirming a payer alias (#161)
    "/dashboard/api/closes/confirm",        # confirming a proposed close (#161)
)

# ── owner-only for a different reason: it destroys something ───────────────
# Not money truth, so it gets its own list and its own honest refusal. The
# forever-archive rule means nobody deletes in the collaboration log; this is
# the same instinct applied to the ad board's own record.

DESTRUCTIVE: tuple[str, ...] = (
    "/ads/api/discussion/delete",
)


# ── what Piolo may READ (GET) ───────────────────────────────────────────────
# Explicit by design. A route that is not here is refused, which is what makes
# "a new route is denied until granted" true rather than aspirational.

COO_READ: tuple[str, ...] = (
    # the ad dashboard
    "/ads/", "/ads/api/board", "/ads/api/deal", "/ads/api/discussion",
    "/ads/api/dossier", "/ads/api/experiment", "/ads/api/review/sessions",
    "/ads/api/roster", "/ads/api/sets", "/ads/api/strategy",
    # the shell + pages
    "/dashboard/", "/dashboard/landing", "/dashboard/today",
    "/dashboard/sales", "/dashboard/scale", "/dashboard/scale/travelling",
    "/dashboard/system", "/dashboard/targets", "/dashboard/worklog",
    "/dashboard/bookkeeping", "/dashboard/data-sources",
    "/dashboard/definitions", "/dashboard/leads", "/dashboard/login",
    "/dashboard/logout", "/dashboard/view/*", "/dashboard/static/*",
    # money + the engines behind it
    "/dashboard/api/ar", "/dashboard/api/bas", "/dashboard/api/capacity",
    "/dashboard/api/capital", "/dashboard/api/nets",
    "/dashboard/api/outflow-bands", "/dashboard/api/payback",
    "/dashboard/api/projection", "/dashboard/api/forecast",
    "/dashboard/api/unit-economics", "/dashboard/api/unit-econ-honest",
    "/dashboard/api/roas", "/dashboard/api/renewal/clients",
    "/dashboard/api/renewal/state", "/dashboard/api/quarterly-pack",
    "/dashboard/api/quarterly-review", "/dashboard/api/finance-analysis",
    "/dashboard/api/finance-analysis.pdf", "/dashboard/api/briefing-pdf",
    "/dashboard/api/snapshot", "/dashboard/api/history",
    # sales + leads
    "/dashboard/api/sales-summary", "/dashboard/api/leads",
    "/dashboard/api/lead-lookup", "/dashboard/api/reactivation",
    "/dashboard/api/reactivation/brief.pdf",
    "/dashboard/api/reactivation/export.csv",
    "/dashboard/api/test-lead-scan",
    # plan
    "/dashboard/api/scale/backtest", "/dashboard/api/scale/calibration-log",
    "/dashboard/api/scale/defaults", "/dashboard/api/scale/expiring",
    "/dashboard/api/scale/plan-vs-actual", "/dashboard/api/scale/scenario-pdf",
    "/dashboard/api/travelling", "/dashboard/api/travelling/history",
    "/dashboard/api/travelling/remodel",
    # these answer GET with their current state; their POST is owner-only
    "/dashboard/api/scale/north-star", "/dashboard/api/scale/scenarios",
    "/dashboard/api/system/run-checks",
    # the working surfaces
    "/dashboard/api/action-feed", "/dashboard/api/decision-cards",
    "/dashboard/api/collab/digest", "/dashboard/api/collab/journal",
    "/dashboard/api/collab/queue", "/dashboard/api/collab/log",
    "/dashboard/api/worklog", "/dashboard/api/greeting",
    "/dashboard/api/unmatched",                      # #161, read
    "/dashboard/api/closes/pending",                 # #161, read
    # system + plumbing
    "/dashboard/api/system", "/dashboard/api/freshness",
    "/dashboard/api/health", "/dashboard/api/ground-truth",
    "/dashboard/api/telemetry", "/dashboard/api/data-sources",
    "/dashboard/api/tab-map", "/dashboard/api/targets",
    "/dashboard/api/definitions", "/dashboard/api/drawer/*",
    "/dashboard/api/gap", "/dashboard/api/ops-summary",
    "/dashboard/api/memory-status", "/dashboard/api/whoami",
)

# ── what Piolo may DO (non-GET) — his queue, the ad board, and pure maths ───

COO_WRITE: tuple[str, ...] = (
    # his queue + work log (the collaboration loop this account exists for)
    "/dashboard/api/collab/log", "/dashboard/api/collab/resolve",
    "/dashboard/api/collab/restore", "/dashboard/api/collab/undismiss",
    "/dashboard/api/collab/export", "/dashboard/api/triage",
    # the ad board's own actions
    "/ads/api/discussion", "/ads/api/discussion/edit",
    "/ads/api/discussion/resolve", "/ads/api/lifecycle/move",
    "/ads/api/review/keep", "/ads/api/strategy", "/ads/api/strategy/map-set",
    "/ads/api/lifecycle/confirm-executed", "/ads/api/lifecycle/reverse",
    # modelling: computes, never commits (scenario-never-contaminates-actuals)
    "/dashboard/api/scale/simulate", "/dashboard/api/scale/solve",
    "/dashboard/api/scale/run", "/dashboard/api/scale/expiring-preview",
    "/dashboard/api/hiring-scenario", "/dashboard/api/brief",
    # EDITH chat on his channel (owner-scope facts withheld by the memory
    # scoping, not by this layer) + browser housekeeping
    "/dashboard/api/chat", "/dashboard/api/chat-stream",
    "/dashboard/api/client-error", "/dashboard/api/geolocation",
    "/dashboard/logout",
)


def _matches(path: str, patterns) -> str | None:
    """Exact match, or a prefix ONLY where the pattern says so with a trailing
    star. Anything looser and a nested route would inherit a grant nobody
    made — "/dashboard/" as a prefix would hand over the whole estate, which
    is the exact failure this file exists to prevent."""
    p = (path or "").rstrip("/") or "/"
    for pat in patterns:
        if pat.endswith("*"):
            if (path or "").startswith(pat[:-1]):
                return pat
        elif (pat.rstrip("/") or "/") == p:
            return pat
    return None


def carve_out_for(path: str) -> tuple[str, str] | None:
    """(name, reason) if this path is inside a carve-out."""
    for name, patterns, reason in CARVE_OUTS:
        for pat in patterns:
            if (path or "").startswith(pat):
                return name, reason
    return None


def coo_permitted(path: str, method: str = "GET") -> tuple[bool, str]:
    """May a coo session reach this? → (allowed, reason when not)."""
    carve = carve_out_for(path)
    if carve:
        return False, f"{carve[0]} — owner-only: {carve[1]}"
    if (method or "GET").upper() == "GET":
        # A GET is a read. Money-truth is about what a request CHANGES, and
        # several of those endpoints answer GET with their current state —
        # the plan's north star, the scenario list, whether a check is
        # running. Reading those is exactly what "full read" means.
        if _matches(path, COO_READ) or _matches(path, COO_WRITE):
            return True, ""
        return False, "not granted to this role yet"
    if _matches(path, MONEY_TRUTH):
        return False, ("this changes what the numbers are — owner-only "
                       "(R-PIOLO money-truth carve-out)")
    if _matches(path, DESTRUCTIVE):
        return False, "this deletes a record — owner-only"
    if _matches(path, COO_WRITE):
        return True, ""
    return False, "not granted to this role yet"


# ── the arithmetic carve-out ────────────────────────────────────────────────

def hide_single_person_total(rows: list, value_key: str = "commission") -> bool:
    """True when showing the TOTAL would show one person's pay.

    A month in which only Kalin closed makes "total commission" and "Kalin's
    commission" the same number. The total is suppressed then, with an
    owner-only chip — an honest blank beats a number that says more than it
    means."""
    contributors = [r for r in (rows or [])
                    if float((r or {}).get(value_key) or 0) > 0]
    return len(contributors) == 1


def scrub_person_pay(rows: list, keys=("commission",)) -> list:
    """Return the rows without the per-person pay columns."""
    out = []
    for r in rows or []:
        c = dict(r)
        for k in keys:
            c.pop(k, None)
        out.append(c)
    return out
