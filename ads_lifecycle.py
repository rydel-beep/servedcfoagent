"""
ads_lifecycle.py
----------------
THE AD LIFECYCLE ENGINE (Board v2 · R-A2 strategy): the R-A2 review-cycle
engine (four standing ad sets, 7–8-day reviews, PEER-RELATIVE pull
candidates), the ONE status classifier (Law 3), the ONE stage classifier
(Law 1), the decision journal + convergence loop (Law 2 / R-B), and the
stance-summary consumer (Law 4 / R-C).

The Board is a VIEW — every number it shows is either an engine field
(window/all-time creatives from attribution_engine via the rollup layer) or a
field computed HERE, once, at one call site. No route or JS ever re-derives a
lane, a status, or a review clock.

R-A2 (DECISIONS #147 — supersedes the retired #143 fixed-boundary ruling,
which stays browsable in history, never erased): campaigns never stop; the unit of
competition is THE AD SET; creatives share a set budget and Meta's delivery
allocation is itself a signal; underperformance is peer-relative within the
set over the review window — no absolute spend/day threshold exists.
Review-cycle judgments are provisional + peer-relative, LABELLED — never
dressed as verdicts; the verdict engine (min-n 30 leads / 3 closes) is
untouched and, with creatives living longer, now actually reachable.

DECISION BOARD, NOT CONTROL PANEL (Law 2): Meta access is ads_read. A move
records a journaled decision with a MANDATORY reason and spawns the human
action; convergence is VERIFIED when a later status sync sees Meta actually
changed (pull → paused at any layer; scale → a new ad id joins the creative,
i.e. duplication — budget changes are invisible under ads_read, so a scale
mark may alternatively be confirmed executed by a human, journaled).

STANCES ARE OPINIONS, NEVER VOTES (the encoded guard): nothing in this module
reads stance counts when computing lanes or applying decisions — the only
stance consumer is the summary chip + the move-dialog display. A decision is
always an explicit move + reason by a named human.
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

ALL_DAYS = 3650                      # the engine's "Maximum" window = lifetime

_KV_STRATEGY = "ads:strategy_rules"            # R-A2 config (supersedes ads:rotation_rules)
_KV_STRATEGY_JOURNAL = "ads:strategy_journal"
_KV_SET_ROLES = "ads:set_roles"                # {adset_id: role} — owner-mapped, ids are truth
_KV_REVIEW_CLOCK = "ads:review_clock"          # {creative_key: last-review ISO date}
_KV_REVIEW_SESSIONS = "ads:review_sessions"    # {date: {who, kept[], pulled[], ...}}
_KV_DECISIONS = "ads:lifecycle:decisions"
_KV_JOURNAL = "ads:lifecycle:journal"
_KV_FEED = "feed:extra:ads_decisions"     # action-feed registry channel
_KV_LAST_RENDER = "ads:lifecycle:last_render"
# The retired R-A kv keys (ads:rotation_rules + its journal) are ORPHANED,
# never read — their history stays browsable in kv (excluded ≠ deleted).

# R-A2 (DECISIONS #147, supersedes #143): FOUR STANDING AD SETS run
# continuously; review every 7–8 days; underperformance is PEER-RELATIVE
# within the creative's ad set — no absolute spend/day kill threshold exists.
SET_ROLES = ("broad_video", "targeted_video", "graphics", "retargeting")
SET_ROLE_LABELS = {
    "broad_video": "Broad video (no interest targeting — Meta finds the ICP)",
    "targeted_video": "Targeted video (demo + interest targeting)",
    "graphics": "Graphics (~10 creatives)",
    "retargeting": "Retargeting (compares only against itself — never cold peers)",
}
STRATEGY_DEFAULTS = {
    "review_cycle_days": 7,      # the ritual cadence; due-window through day 8
    "review_due_through": 8,
    "pull_cpl_mult": 1.5,        # CPL > 1.5× SET median → pull candidate
    "pull_min_leads": 3,         # min-evidence guard: the relative-CPL flag
                                 # needs ≥3 leads (a 1-lead fluke never ranks a peer)
    "starved_share_pct": 5,      # delivery share < 5% …
    "starved_cycles": 2,         # … for two consecutive cycles = STARVED (≠ expensive)
    "budget_drift_pct": 30,      # actual daily spend outside intended ±pct → drift signal
    "freshness_days": 2,         # status triad delivery horizon (carried over)
}
_STRATEGY_BOUNDS = {"review_cycle_days": (3, 21), "review_due_through": (3, 28),
                    "pull_cpl_mult": (1.1, 5.0), "pull_min_leads": (1, 20),
                    "starved_share_pct": (1, 25), "starved_cycles": (1, 5),
                    "budget_drift_pct": (10, 100), "freshness_days": (1, 7)}
# intended daily budgets per role (AUD ranges) — config; None = not set (no
# drift check until Rydel enters it). Graphics + retargeting per the ruling.
BUDGET_DEFAULTS = {"broad_video": None, "targeted_video": None,
                   "graphics": [60, 70], "retargeting": [40, 40]}

# marked_to_pull replaces marked_to_kill (R-A2 relabel — mechanics identical:
# mandatory reason, Meta convergence, ageing). Legacy "kill" stays accepted
# as an API alias; HISTORICAL decisions keep their marked_to_kill label and
# render with a "pre-R-A2" note.
DECISION_STATES = {"pull": "marked_to_pull", "kill": "marked_to_pull",
                   "scale": "marked_to_scale"}

# STATUS TRIAD (ruled 2026-08-12, status-clarity wave): PAUSED (grey) is the
# ad paused AT ITS OWN LAYER — a deliberate park. Everything that leaves the
# ad ENABLED while Meta doesn't deliver it is the AMBER class ("the dangerous
# middle state"), with the reason IN THE LABEL: parent paused (campaign/ad
# set), review/billing/issues, or the honest "reason unknown". Every state
# carries a rendered `label` (no glyph needs decoding) and a sort `rank`.
_AMBER_REASONS = {
    "PENDING_REVIEW": ("in review", "in Meta review — not approved for delivery yet"),
    "PREAPPROVED": ("in review", "pre-approved — not yet fully approved"),
    "PENDING_BILLING_INFO": ("billing issue", "billing issue on the ad account"),
    "IN_PROCESS": ("processing", "processing at Meta"),
    "WITH_ISSUES": ("has issues", "flagged WITH_ISSUES by Meta"),
    "DISAPPROVED": ("disapproved", "disapproved by Meta review"),
    # parent layers: the ad's own toggle is ON — enabled-but-dead, not parked
    "CAMPAIGN_PAUSED": ("campaign paused", "the ad is enabled but its CAMPAIGN "
                                           "is paused — nothing can deliver"),
    "ADSET_PAUSED": ("ad set paused", "the ad is enabled but its AD SET is "
                                      "paused — nothing can deliver"),
}
_PARENT_BLOCKED = ("CAMPAIGN_PAUSED", "ADSET_PAUSED")
_PAUSE_LAYER = {"PAUSED": "ad", "ARCHIVED": "ad (archived)"}
STATUS_RANK = {"delivering": 3, "enabled_not_delivering": 2, "paused": 1,
               "unknown": 0}


# ── R-A2 strategy config (supersedes the retired R-A fixed boundary) ─────────

def strategy() -> dict:
    """The live strategy config — kv-backed, R-A2 ruled defaults. Includes
    per-role intended daily budgets ({role: [min,max] or None})."""
    out = dict(STRATEGY_DEFAULTS)
    out["budgets"] = {r: (list(v) if v else None) for r, v in BUDGET_DEFAULTS.items()}
    try:
        import kv_store
        stored = kv_store.get(_KV_STRATEGY) or {}
        for k in STRATEGY_DEFAULTS:
            if stored.get(k) is not None:
                out[k] = type(STRATEGY_DEFAULTS[k])(stored[k])
        for r in SET_ROLES:
            b = (stored.get("budgets") or {}).get(r)
            if b is not None:
                out["budgets"][r] = [float(b[0]), float(b[1])]
    except Exception as e:
        logger.info("strategy config fell back to ruled defaults: %s", e)
    return out


def set_strategy(actor: dict, updates: dict) -> tuple[dict | None, str | None]:
    """Edit the live strategy config (no deploy). Journaled {who, when, key,
    old→new}. budgets: {"budgets": {role: [min,max]|null}}."""
    cur = strategy()
    changes = []
    for k, v in (updates or {}).items():
        if k == "budgets":
            for role, rng in (v or {}).items():
                if role not in SET_ROLES:
                    return None, f"unknown set role '{role}'"
                if rng is not None:
                    try:
                        rng = [float(rng[0]), float(rng[1])]
                    except (TypeError, ValueError, IndexError):
                        return None, f"budget for {role} must be [min, max]"
                    if not (0 < rng[0] <= rng[1] <= 5000):
                        return None, f"budget range for {role} out of bounds"
                if rng != cur["budgets"].get(role):
                    changes.append((f"budget:{role}", cur["budgets"].get(role), rng))
                    cur["budgets"][role] = rng
            continue
        if k not in STRATEGY_DEFAULTS:
            return None, f"unknown strategy key '{k}'"
        try:
            v = type(STRATEGY_DEFAULTS[k])(v)
        except (TypeError, ValueError):
            return None, f"bad value for {k}"
        lo, hi = _STRATEGY_BOUNDS[k]
        if not (lo <= v <= hi):
            return None, f"{k} must be between {lo} and {hi}"
        if v != cur[k]:
            changes.append((k, cur[k], v))
            cur[k] = v
    if not changes:
        return cur, None
    from helpers import now_sydney
    import kv_store
    kv_store.put(_KV_STRATEGY, cur)
    j = kv_store.get(_KV_STRATEGY_JOURNAL) or []
    for k, old, new in changes:
        j.append({"at": now_sydney().strftime("%Y-%m-%d %H:%M"),
                  "who": (actor or {}).get("user") or "unknown",
                  "key": k, "old": old, "new": new})
    kv_store.put(_KV_STRATEGY_JOURNAL, j[-200:])
    return cur, None


def strategy_journal() -> list:
    try:
        import kv_store
        return kv_store.get(_KV_STRATEGY_JOURNAL) or []
    except Exception:
        return []


# backwards-compat shim for the status triad's freshness read (carried over)
def rules() -> dict:
    return strategy()


# ── the SET MAPPING (owner config: Meta adset ids → the four roles) ──────────

def set_roles_map() -> dict:
    """{adset_id: role}. IDs are truth — membership comes from Meta's own
    adset ids (the entity map), never name-parsing."""
    try:
        import kv_store
        m = kv_store.get(_KV_SET_ROLES)
        return {str(k): v for k, v in (m or {}).items() if v in SET_ROLES}
    except Exception:
        return {}


def map_adset(actor: dict, adset_id: str, role) -> tuple[dict | None, str | None]:
    """Assign a Meta ad set to one of the four roles (owner/coo, journaled,
    reversible — role=None/'unmapped' clears)."""
    aid = str(adset_id or "").strip()
    if not re.match(r"^\d{5,25}$", aid):
        return None, "adset_id must be the Meta id (ids are truth)"
    if role in (None, "", "unmapped"):
        role = None
    elif role not in SET_ROLES:
        return None, f"role must be one of {', '.join(SET_ROLES)} (or unmapped)"
    import kv_store
    from helpers import now_sydney
    m = set_roles_map()
    old = m.get(aid)
    if role is None:
        m.pop(aid, None)
    else:
        m[aid] = role
    kv_store.put(_KV_SET_ROLES, m)
    j = kv_store.get(_KV_STRATEGY_JOURNAL) or []
    j.append({"at": now_sydney().strftime("%Y-%m-%d %H:%M"),
              "who": (actor or {}).get("user") or "unknown",
              "key": f"adset:{aid}", "old": old, "new": role or "unmapped"})
    kv_store.put(_KV_STRATEGY_JOURNAL, j[-200:])
    return {"adset_id": aid, "role": role}, None


def roles_for_ads(ad_ids: list, entity_store: dict) -> tuple[list[str], list[str]]:
    """(roles, adset_ids) for a creative's member ads — via the entity map's
    adset ids and the owner mapping. Unmapped ids yield no role (the caller
    renders 'unmapped set' honestly)."""
    m = set_roles_map()
    roles, sids = [], []
    for a in ad_ids or []:
        e = ((entity_store.get("ads") or {}).get(str(a))
             or (entity_store.get("extras") or {}).get(str(a)) or {})
        sid = e.get("adset_id")
        if sid:
            sid = str(sid)
            if sid not in sids:
                sids.append(sid)
            r = m.get(sid)
            if r and r not in roles:
                roles.append(r)
    return roles, sids


# ── the status engine (Law 3): DELIVERING / ENABLED-NOT-DELIVERING / PAUSED ──

def _spend_store() -> dict:
    """The daily-delivery archive via the SEEDING loader — a fresh deploy's
    empty local file reseeds from the kv mirror (Railway files die per
    deploy); a raw file read here would render every status DEGRADED until
    the first engine compute (probe-caught on deploy c32f6541)."""
    import meta_entities
    return meta_entities._load_spend_store()


def _entity_store() -> dict:
    """The entity map via its TTL loader (stale-but-present serves and
    refreshes in background; only a truly empty first boot fetches inline —
    the same semantics the dossier identity path already uses)."""
    import meta_entities
    try:
        return meta_entities.refresh_entity_map()
    except Exception as e:
        logger.info("entity map load degraded: %s", e)
        return meta_entities._load_json(meta_entities.ENTITY_STORE)


def _recent_delivery_days(spend_store: dict, horizon_days: int) -> list[str]:
    from datetime import timedelta
    from helpers import today_sydney
    t = today_sydney()
    return [str(t - timedelta(days=i)) for i in range(horizon_days)]


def _st(status: str, label: str, reason: str, layer=None, as_of=None,
        degraded=None, blocked_by_parent=False) -> dict:
    """The one status shape: label is the RENDERED text (both views show it
    verbatim — no glyph needs decoding); rank is the sort ordinal."""
    return {"status": status, "label": label, "rank": STATUS_RANK[status],
            "reason": reason, "layer": layer, "as_of": as_of,
            "degraded": degraded, "blocked_by_parent": blocked_by_parent}


def status_for(ad_ids: list[str], entity_store: dict, spend_store: dict,
               rl: dict | None = None) -> dict:
    """ONE status classification for a creative (its member ad ids).
    Returns {status, label, rank, reason, layer, as_of, degraded,
    blocked_by_parent}. The ruled triad: LIVE (delivering per the daily
    buckets) · NOT DELIVERING (the ad's own toggle is ON but Meta isn't
    delivering it — reason in the label: campaign/ad-set paused, review,
    billing, issues, or the honest 'reason unknown') · PAUSED (parked at the
    ad's OWN layer). Never the toggle alone; a dead Meta source returns
    'unknown' with the cause — never a stale green (F5)."""
    rl = rl or rules()
    ad_ids = [str(a) for a in (ad_ids or []) if a]
    import time as _t
    from helpers import now_sydney
    refreshed = float(spend_store.get("refreshed_at") or 0)
    as_of = None
    if refreshed:
        age_min = int((_t.time() - refreshed) / 60)
        as_of = f"{now_sydney().strftime('%Y-%m-%d %H:%M')} (delivery data {age_min}m old)"
    degraded = None
    try:
        import meta_entities
        if not meta_entities.configured():
            degraded = "Meta not configured — live status unknowable"
    except Exception as e:
        degraded = f"Meta module unavailable: {e}"
    if not degraded and not (entity_store.get("ads") or entity_store.get("extras")):
        degraded = "Meta entity map empty — toggle state unknowable"
    if not degraded and refreshed and (_t.time() - refreshed) > 26 * 3600:
        degraded = (f"delivery archive stale ({int((_t.time() - refreshed) / 3600)}h "
                    "since last Meta refresh) — status would be a guess")
    if degraded:
        return _st("unknown", "STATUS UNKNOWN · Meta source degraded", degraded,
                   as_of=as_of, degraded=degraded)

    days = spend_store.get("days") or {}
    recent = _recent_delivery_days(spend_store, int(rl.get("freshness_days", 2)))
    delivering = False
    for d in recent:
        bucket = days.get(d) or {}
        for aid in ad_ids:
            row = bucket.get(aid)
            if row and (float(row.get("spend") or 0) > 0
                        or int(float(row.get("impressions") or 0)) > 0):
                delivering = True
                break
        if delivering:
            break

    def _ent(aid):
        return ((entity_store.get("ads") or {}).get(aid)
                or (entity_store.get("extras") or {}).get(aid) or {})
    statuses = [s for s in (_ent(a).get("effective_status") for a in ad_ids) if s]

    if delivering:
        return _st("delivering", "LIVE",
                   f"impressions within the last {rl.get('freshness_days', 2)} "
                   "day(s) (daily-delivery archive)", as_of=as_of)
    # AMBER: enabled at the ad's own layer, Meta not delivering — reason in
    # the label. Parent-paused counts HERE (the ad itself is on): an
    # enabled-but-dead ad is a different problem from a deliberately paused one.
    for s in statuses:
        if s in _AMBER_REASONS:
            short, detail = _AMBER_REASONS[s]
            return _st("enabled_not_delivering", f"NOT DELIVERING · {short}",
                       detail, as_of=as_of,
                       blocked_by_parent=s in _PARENT_BLOCKED)
    if any(s == "ACTIVE" for s in statuses):
        return _st("enabled_not_delivering", "NOT DELIVERING · reason unknown",
                   "enabled at every layer with zero recent delivery — commonly "
                   "learning phase or budget-limited (not visible under ads_read)",
                   as_of=as_of)
    if statuses:
        for s in statuses:
            if s in _PAUSE_LAYER:
                return _st("paused", "PAUSED",
                           f"paused at the {_PAUSE_LAYER[s]} layer (deliberate park)",
                           layer=_PAUSE_LAYER[s], as_of=as_of)
        return _st("enabled_not_delivering",
                   f"NOT DELIVERING · {statuses[0].lower().replace('_', ' ')}",
                   f"Meta status {statuses[0]} — no recent delivery", as_of=as_of)
    # no entity record (deleted/unlisted ad), no recent delivery
    return _st("paused", "PAUSED · unlisted",
               "not in the Meta ad listing (deleted or archived out) and no "
               "recent delivery", layer="ad (unlisted)", as_of=as_of)


# ── the REVIEW CYCLE (R-A2 — replaces the rotation) ──────────────────────────

def _review_clock_map() -> dict:
    try:
        import kv_store
        m = kv_store.get(_KV_REVIEW_CLOCK)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def review_clock(creative_key: str, launch: str | None, today=None) -> dict | None:
    """THE review clock: CALENDAR days since the last review decision (the
    ritual is a calendar cadence), anchored at first delivery until the first
    review. None when no launch is known (honest, never a zero)."""
    if not launch:
        return None
    import datetime as dt
    from helpers import today_sydney
    today = today or today_sydney()
    anchor = _review_clock_map().get(creative_key) or launch
    try:
        a = dt.date.fromisoformat(str(anchor)[:10])
    except (ValueError, TypeError):
        return None
    cyc = strategy()
    day = (today - a).days
    return {"anchor": str(a),
            "anchored_on": "last review" if creative_key in _review_clock_map()
                           else "first delivery",
            "cycle_day": day,
            "cycle_days": cyc["review_cycle_days"],
            "due": day >= cyc["review_cycle_days"],
            "label": f"cycle day {day} · review due day {cyc['review_cycle_days']}"
                     f"–{cyc['review_due_through']}",
            "clock_note": "review clock: calendar days since the last review "
                          "decision (first delivery until then) — resets on "
                          "each KEEP/PULL; campaigns never stop"}


def reset_review_clock(creative_key: str, today=None) -> None:
    import kv_store
    from helpers import today_sydney
    m = _review_clock_map()
    m[str(creative_key)] = str(today or today_sydney())
    kv_store.put(_KV_REVIEW_CLOCK, m)


def set_spend_window(days: int, end=None) -> dict:
    """Per-ad spend over a trailing window from the daily archive, keyed by
    adset id via the entity map: {adset_id: {ad_id: spend}}. The set grain is
    a ROLLUP of the per-ad archive — one source."""
    import datetime as dt
    from helpers import today_sydney
    end = end or today_sydney()
    ss = _spend_store()
    es = _entity_store()
    days_map = ss.get("days") or {}
    out: dict = {}
    for i in range(days):
        d = str(end - dt.timedelta(days=i))
        for aid, row in (days_map.get(d) or {}).items():
            sp = float(row.get("spend") or 0)
            if sp <= 0:
                continue
            e = ((es.get("ads") or {}).get(aid)
                 or (es.get("extras") or {}).get(aid) or {})
            sid = str(e.get("adset_id") or "__no_adset__")
            out.setdefault(sid, {})
            out[sid][aid] = round(out[sid].get(aid, 0.0) + sp, 2)
    return out


def _median(vals: list[float]) -> float | None:
    v = sorted(vals)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def pull_candidates(creatives_all: list[dict], entity_store: dict,
                    cfg: dict | None = None) -> dict:
    """PEER-RELATIVE pull ranking, computed WITHIN each mapped ad set over the
    trailing review window (retargeting therefore only ever compares against
    itself — structural). Flags (each labelled with WHICH signal fired):
      zero_leads_with_share — 0 lifetime leads with ≥ set-median spend share
      relative_cpl — CPL > pull_cpl_mult × set median (min-evidence guard:
        the creative needs ≥ pull_min_leads leads AND ≥2 peers with leads —
        a 1-lead fluke never ranks a peer)
      starved — delivery share < starved_share_pct for TWO consecutive
        cycles (a budget-allocation problem, NOT an expense problem — never
        blended with relative_cpl)
    The system RANKS AND FLAGS; humans decide — no auto-pull path exists."""
    cfg = cfg or strategy()
    window = int(cfg["review_cycle_days"])
    cur = set_spend_window(window)
    prev = None      # lazily built for the starved check's second cycle
    roles = set_roles_map()
    by_key = {c.get("creative_key"): c for c in creatives_all or []
              if c.get("tier") == "ad"}
    # creative spend per set over the window (per-ad grain, exact)
    per_set: dict = {}
    for sid, ads in cur.items():
        if sid not in roles:
            continue           # unmapped sets never rank (surfaced elsewhere)
        rows = {}
        for c in creatives_all or []:
            if c.get("tier") != "ad":
                continue
            sp = sum(ads.get(str(a), 0.0) for a in (c.get("ad_ids") or []))
            if sp > 0:
                rows[c["creative_key"]] = round(sp, 2)
        if rows:
            per_set[sid] = rows
    flags: dict = {}
    for sid, rows in per_set.items():
        total = sum(rows.values())
        if total <= 0 or len(rows) < 2:
            continue           # a 1-creative set has no peers to rank against
        shares = {k: v / total for k, v in rows.items()}
        med_share = _median(list(shares.values()))
        cpls = {}
        for k in rows:
            c = by_key.get(k) or {}
            leads = int(c.get("leads") or 0)
            if leads >= int(cfg["pull_min_leads"]):
                cpls[k] = rows[k] / leads
        med_cpl = _median(list(cpls.values())) if len(cpls) >= 2 else None
        for k in rows:
            c = by_key.get(k) or {}
            leads = int(c.get("leads") or 0)
            fired = []
            if leads == 0 and med_share is not None and shares[k] >= med_share:
                fired.append({"signal": "zero_leads_with_share",
                              "detail": f"0 lifetime leads at {shares[k]*100:.0f}% "
                                        f"delivery share (set median "
                                        f"{med_share*100:.0f}%) — spending its "
                                        f"share, producing nothing"})
            if med_cpl is not None and k in cpls \
                    and cpls[k] > float(cfg["pull_cpl_mult"]) * med_cpl:
                fired.append({"signal": "relative_cpl",
                              "detail": f"CPL ${cpls[k]:,.0f} vs set median "
                                        f"${med_cpl:,.0f} (>{cfg['pull_cpl_mult']}×) "
                                        f"at n={leads} — expensive vs its peers"})
            if shares[k] < float(cfg["starved_share_pct"]) / 100:
                if prev is None:
                    import datetime as dt
                    from helpers import today_sydney
                    prev = set_spend_window(
                        window, end=today_sydney() - dt.timedelta(days=window))
                prows = prev.get(sid) or {}
                ptotal = sum(prows.values())
                pshare = (sum(prows.get(str(a), 0.0)
                              for a in (c.get("ad_ids") or [])) / ptotal
                          if ptotal > 0 else None)
                if pshare is not None \
                        and pshare < float(cfg["starved_share_pct"]) / 100:
                    fired.append({"signal": "starved",
                                  "detail": f"delivery share {shares[k]*100:.1f}% "
                                            f"(prior cycle {pshare*100:.1f}%) — "
                                            f"Meta is starving it two cycles "
                                            f"running: an allocation problem, "
                                            f"not an expense problem"})
            if fired:
                flags.setdefault(k, {"set": sid, "role": roles.get(sid),
                                     "share_pct": round(shares[k] * 100, 1),
                                     "window_spend": rows[k],
                                     "signals": fired})
    return {"flags": flags, "per_set_spend": per_set,
            "window_days": window,
            "note": "peer-relative within each mapped ad set only — no "
                    "absolute threshold, no cross-set ranking, no auto-pull"}


# ── the ONE stage classifier (Law 1 carried; R-A2 lanes) ─────────────────────

def classify_stage(row_all: dict, status: dict, rl: dict,
                   review: dict | None = None,
                   pull_flags: dict | None = None) -> dict:
    """THE stage classifier — the only function that assigns an engine lane.
    Deterministic over engine fields. R-A2 lanes: running · due_for_review ·
    watch · scale_candidate · archive. Pull-candidacy is a FLAG on the card
    (peer-relative, labelled), never a lane of its own and never auto-acted.
    The verdict path is UNTOUCHED: DOUBLE DOWN at min-n → scale_candidate;
    review judgments are provisional + peer-relative, never verdicts."""
    lin = (row_all or {}).get("lineage") or {}
    leads = int((row_all or {}).get("leads") or 0)
    verdict = (row_all or {}).get("verdict")
    gates = (row_all or {}).get("gates") or {}

    def out(lane, why):
        return {"lane": lane, "why": why, "review": review,
                "pull_flags": pull_flags, "status": status}

    if status.get("status") == "paused" or status.get("blocked_by_parent"):
        return out("archive", f"parked in Meta — {status.get('reason')}")
    if lin.get("never_delivered"):
        return out("running", "never delivered — no review clock exists yet "
                              "(lifetime impressions 0)")
    if verdict == "DOUBLE DOWN":
        # verdict engine untouched: the statistical lane needs min-n. Under
        # R-A2 scale = keep + replicate/duplicate (convergence unchanged).
        return out("scale_candidate",
                   f"verdict-backed: DOUBLE DOWN at n={gates.get('n_leads')} "
                   f"leads / {gates.get('n_closes')} closes")
    if review and review.get("due"):
        why = f"review due — {review['label']}"
        if pull_flags:
            sigs = ", ".join(s["signal"] for s in pull_flags.get("signals") or [])
            why += f" · PULL CANDIDATE ({sigs}) — peer-relative, human decides"
        return out("due_for_review", why)
    if verdict == "KILL":
        # a statistical KILL at min-n surfaces as due-for-review with the
        # verdict pill carrying the stats — the review ritual is where humans
        # act; the pill (not the lane) is the statistical claim
        return out("due_for_review",
                   f"VERDICT KILL at n={gates.get('n_leads')} leads — bring "
                   "to review (the pill is the statistical layer)")
    if gates.get("sufficient_for_kill") or gates.get("sufficient_for_scale"):
        return out("watch", f"at evidence ({leads} lifetime leads) — verdict "
                            "layer active; runs until review or verdict")
    if review is None:
        return out("running", "review clock unavailable — launch lineage "
                              "degraded/pending (not a zero)")
    return out("running", f"in cycle — {review['label']}")


def below_min_n(row_all: dict) -> bool:
    g = (row_all or {}).get("gates") or {}
    return not (g.get("sufficient_for_kill") or g.get("sufficient_for_scale"))


# ── decisions (Law 2 / R-B): journaled moves + convergence ──────────────────

def _decisions() -> dict:
    try:
        import kv_store
        d = kv_store.get(_KV_DECISIONS)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _put_decisions(d: dict) -> None:
    import kv_store
    kv_store.put(_KV_DECISIONS, d)


def _journal(entry: dict) -> None:
    try:
        import kv_store
        j = kv_store.get(_KV_JOURNAL) or []
        j.append(entry)
        kv_store.put(_KV_JOURNAL, j[-500:])
    except Exception as e:
        logger.warning("lifecycle journal write failed: %s", e)


def journal(limit: int = 100) -> list:
    try:
        import kv_store
        return (kv_store.get(_KV_JOURNAL) or [])[-limit:]
    except Exception:
        return []


def _now() -> str:
    from helpers import now_sydney
    return now_sydney().strftime("%Y-%m-%d %H:%M")


def move(actor: dict, creative_key: str, to: str, reason,
         row_all: dict | None, engine_lane: str | None,
         confirm_below_min_n: bool = False) -> tuple[dict | None, str | None, dict | None]:
    """Record a decision (R-B). Returns (decision, error, friction).
    MANDATORY non-empty reason; below-min-n needs explicit confirm (friction);
    attributed to the SESSION actor; journaled; feed item with the reason."""
    r = str(reason or "").strip()
    if not r:
        return None, "a reason is required — the dialog rejects blank", None
    if len(r) > 500:
        return None, "reason too long (500 max)", None
    if to not in DECISION_STATES:
        return None, "move target must be 'pull' or 'scale'", None
    key = str(creative_key or "").strip()
    if not re.match(r"^[0-9]{10,20}$", key):
        return None, "bad creative key", None
    if row_all is not None and below_min_n(row_all) and not confirm_below_min_n:
        return None, None, {
            "friction": True,
            "note": "below evidence threshold — this is a review-cycle call, not a "
                    "verdict. Confirm to record it as one.",
        }
    d = _decisions()
    prior = d.get(key)
    state = DECISION_STATES[to]
    who = (actor or {}).get("user") or "unknown"
    entry = {
        "state": state,
        "by": who,
        "by_display": (actor or {}).get("display") or who,
        "at": _now(),
        "reason": r,
        "engine_lane_at_move": engine_lane,
        "below_min_n": bool(row_all is not None and below_min_n(row_all)),
        "ad_ids_at_move": sorted((row_all or {}).get("ad_ids") or []),
        "executed": False,
        "converged_at": None,
        "convergence": None,
        "label": ((row_all or {}).get("label") or key)[:60],
    }
    d[key] = entry
    _put_decisions(d)
    _journal({"at": entry["at"], "who": who, "action": "move",
              "creative": key, "label": entry["label"],
              "from": (prior or {}).get("state") or engine_lane or "unmarked",
              "to": state, "reason": r})
    _publish_feed()
    return entry, None, None


def reverse(actor: dict, creative_key: str, reason) -> tuple[bool, str | None]:
    """Owner reversal (R-B): clears the decision — reason required, journaled.
    The decision store forgets; the journal never does."""
    r = str(reason or "").strip()
    if not r:
        return False, "a reason is required for a reversal too"
    key = str(creative_key or "").strip()
    d = _decisions()
    prior = d.get(key)
    if not prior:
        return False, "no decision recorded for this creative"
    del d[key]
    _put_decisions(d)
    who = (actor or {}).get("user") or "unknown"
    _journal({"at": _now(), "who": who, "action": "reverse", "creative": key,
              "label": prior.get("label"), "from": prior.get("state"),
              "to": "unmarked", "reason": r})
    _publish_feed()
    return True, None


def confirm_executed(actor: dict, creative_key: str, note=None) -> tuple[bool, str | None]:
    """Human execution confirm for SCALE marks (budget changes are invisible
    under ads_read — duplication auto-converges, budget raises need a human
    word). Journaled; the card settles."""
    key = str(creative_key or "").strip()
    d = _decisions()
    dec = d.get(key)
    if not dec:
        return False, "no decision recorded for this creative"
    if dec.get("executed"):
        return False, "already executed/converged"
    dec["executed"] = True
    dec["converged_at"] = _now()
    dec["convergence"] = f"confirmed executed by {(actor or {}).get('display') or 'a human'}" \
                         + (f" — {str(note).strip()[:200]}" if note else "")
    _put_decisions(d)
    _journal({"at": dec["converged_at"], "who": (actor or {}).get("user") or "unknown",
              "action": "confirm_executed", "creative": key,
              "label": dec.get("label"), "from": dec["state"],
              "to": dec["state"] + " (executed)", "reason": str(note or "")[:200]})
    _publish_feed()
    return True, None


def _check_convergence(key: str, dec: dict, status: dict,
                       row_all: dict | None) -> bool:
    """The next status sync verifies Meta actually changed. Kill → Meta shows
    paused at any layer. Scale → a NEW ad id joined the creative (duplication
    detected). Returns True if the decision converged on this sync."""
    if dec.get("executed"):
        return False
    if dec.get("state") in ("marked_to_kill", "marked_to_pull") \
            and (status.get("status") == "paused"
                 or status.get("blocked_by_parent")):
        dec["executed"] = True
        dec["converged_at"] = _now()
        dec["convergence"] = f"verified in Meta — {status.get('reason')}"
        _journal({"at": dec["converged_at"], "who": "status-sync",
                  "action": "converged", "creative": key, "label": dec.get("label"),
                  "from": dec["state"], "to": "pulled (verified)",
                  "reason": dec["convergence"]})
        return True
    if dec.get("state") == "marked_to_scale" and row_all is not None:
        now_ids = set(str(a) for a in (row_all.get("ad_ids") or []))
        then_ids = set(dec.get("ad_ids_at_move") or [])
        new = now_ids - then_ids
        if new:
            dec["executed"] = True
            dec["converged_at"] = _now()
            dec["convergence"] = (f"verified in Meta — {len(new)} new ad id(s) "
                                  "joined the creative (duplication detected)")
            _journal({"at": dec["converged_at"], "who": "status-sync",
                      "action": "converged", "creative": key, "label": dec.get("label"),
                      "from": "marked_to_scale", "to": "scaled (verified)",
                      "reason": dec["convergence"]})
            return True
    return False


def _age_days(iso_min: str) -> int:
    try:
        from datetime import date
        from helpers import today_sydney
        return (today_sydney() - date.fromisoformat(str(iso_min)[:10])).days
    except (ValueError, TypeError):
        return 0


def _publish_feed() -> None:
    """Owner action-feed items via the registry channel — REPLACED wholesale
    (self-retiring). Pending (unexecuted) decisions ride with their reason and
    AGE; converged ones retire from the feed (the journal keeps them)."""
    try:
        import kv_store
        items = []
        for key, dec in _decisions().items():
            if dec.get("executed"):
                continue
            age = _age_days(dec.get("at"))
            verb = ("pause" if dec.get("state") in ("marked_to_kill", "marked_to_pull")
                    else "scale")
            title = (f"{dec.get('by_display')} marked {dec.get('label')} to "
                     f"{verb.upper()} — “{dec.get('reason', '')[:80]}”")
            if age >= 1:
                title += f" · marked {age}d ago — still awaiting Ads Manager"
            items.append({
                "severity": "S2" if age >= 2 else "S3", "category": "ads_decision",
                "id": f"ads-decision:{key}",
                "title": title,
                "action": f"{verb} “{dec.get('label')}” in Ads Manager — the board "
                          "records decisions, it does not control Meta",
                "link": f"/ads?view=board&dossier={key}",
            })
        kv_store.put(_KV_FEED, items)
    except Exception as e:
        logger.info("decision feed publish failed: %s", e)


# ── the lifecycle block (ONE attach point — dashboard/ads.py board serve) ────

def _inputs_hash(row_all: dict, status: dict, dec: dict | None, rl: dict) -> str:
    lin = (row_all or {}).get("lineage") or {}
    basis = "|".join(str(x) for x in (
        (row_all or {}).get("leads"), round(float((row_all or {}).get("spend") or 0), 2),
        (row_all or {}).get("verdict"), lin.get("launch"), lin.get("active_days"),
        lin.get("never_delivered"), status.get("status"), status.get("layer"),
        (dec or {}).get("state"), (dec or {}).get("executed"),
        rl["review_cycle_days"], _review_clock_map().get((row_all or {}).get("creative_key"))))
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def build_block(creatives_all: list[dict], record_render: bool = True) -> dict:
    """THE lifecycle block for the board payload: per-creative status triad,
    R-A2 review clock + peer-relative pull flags, engine lane, decision
    overlay (+ convergence check), set membership, stance summaries, and the
    live strategy config. `creatives_all` = the ALL-TIME engine creatives
    (lifetime numbers — the review clock's scope). One call site."""
    rl = strategy()
    es = _entity_store()
    ss = _spend_store()
    decisions = _decisions()
    pc = pull_candidates(creatives_all, es, rl)
    cycle_window = int(rl["review_cycle_days"]) + 1
    import datetime as dt
    from helpers import today_sydney
    today = today_sydney()
    converged_any = False
    cards: dict = {}
    for row in creatives_all or []:
        if row.get("tier") != "ad":
            continue
        key = row.get("creative_key")
        if not key:
            continue
        st = status_for(row.get("ad_ids") or [], es, ss, rl)
        lin = row.get("lineage") or {}
        review = review_clock(key, lin.get("launch"), today)
        pf = (pc.get("flags") or {}).get(key)
        stage = classify_stage(row, st, rl, review, pf)
        dec = decisions.get(key)
        if dec and _check_convergence(key, dec, st, row):
            converged_any = True
        roles, sids = roles_for_ads(row.get("ad_ids") or [], es)
        injected = False
        try:
            injected = bool(lin.get("launch") and
                            (today - dt.date.fromisoformat(str(lin["launch"]))).days
                            <= cycle_window)
        except (ValueError, TypeError):
            pass
        card = {
            "engine_lane": stage["lane"],
            "engine_why": stage["why"],
            "review": stage.get("review"),
            "pull_flags": stage.get("pull_flags"),
            "sets": roles,                       # mapped roles (may be several —
            "adset_ids": sids,                   # the broad+targeted pair case)
            "unmapped_set": bool(sids and not roles),
            "injected": injected,                # first cycle after injection
            "status": st,
            "below_min_n": below_min_n(row),
            "lifetime": {"leads": row.get("leads"), "closes": row.get("closes"),
                         "spend": row.get("spend")},
            "inputs_hash": _inputs_hash(row, st, dec, rl),
        }
        if dec:
            age = _age_days(dec.get("at"))
            card["decision"] = {k: dec.get(k) for k in
                                ("state", "by", "by_display", "at", "reason",
                                 "executed", "converged_at", "convergence",
                                 "engine_lane_at_move", "below_min_n")}
            card["decision"]["age_days"] = age
            if dec["state"] == "marked_to_kill":
                card["decision"]["pre_ra2"] = True   # historical label, kept
            # SURFACED NEVER SILENT: the human's decision pins the card; when
            # the engine now disagrees with the marked direction, chip it.
            marked_dir = ("pull" if dec["state"] in ("marked_to_kill",
                                                     "marked_to_pull")
                          else "scale")
            eng = stage["lane"]
            disagrees = ((marked_dir == "pull" and eng == "scale_candidate")
                         or (marked_dir == "scale" and eng == "archive"))
            if disagrees and not dec.get("executed"):
                card["disagreement"] = f"engine: {eng.replace('_', '-')}"
            # display lane: the decision overlay (historical kills render in
            # the pull lane with the pre-R-A2 note — mechanics identical)
            if dec.get("executed"):
                card["lane"] = "archive"
                card["archive_label"] = ("pulled — verified in Meta"
                                         if marked_dir == "pull"
                                         else "scaled — executed")
            else:
                card["lane"] = ("marked_to_pull" if marked_dir == "pull"
                                else "marked_to_scale")
        else:
            card["lane"] = stage["lane"]
            if stage["lane"] == "archive":
                card["archive_label"] = (
                    ("blocked — " + st.get("label", "").replace("NOT DELIVERING · ", "")
                     if st.get("blocked_by_parent") else "paused")
                    + " (no decision recorded)")
        cards[key] = card
    if converged_any:
        _put_decisions(decisions)
        _publish_feed()
    try:
        import ads_discussion
        stances = ads_discussion.stances_by_anchor()
    except Exception as e:
        logger.info("stance summary unavailable: %s", e)
        stances = {}
    block = {
        "rules": rl,
        "set_roles": set_roles_map(),
        "set_role_labels": SET_ROLE_LABELS,
        "cards": cards,
        "stances": stances,
        "pull_note": pc.get("note"),
        "lanes_order": ["running", "due_for_review", "marked_to_pull", "watch",
                        "scale_candidate", "marked_to_scale", "archive"],
        "lane_labels": {
            "running": "RUNNING (in cycle)",
            "due_for_review": "DUE FOR REVIEW",
            "marked_to_pull": "MARKED TO PULL",
            "watch": "WATCH",
            "scale_candidate": "SCALE CANDIDATE",
            "marked_to_scale": "MARKED TO SCALE",
            "archive": "PULLED / PAUSED (archive)",
        },
    }
    if record_render:
        try:
            import kv_store, time as _t
            kv_store.put(_KV_LAST_RENDER, {
                "at": _t.time(),
                "lanes": {k: c["lane"] for k, c in cards.items()},
                "statuses": {k: (c.get("status") or {}).get("status")
                             for k, c in cards.items()},
                "hashes": {k: c["inputs_hash"] for k, c in cards.items()},
                "stances": {a: {s: n for s, n in v.get("counts", {}).items()}
                            for a, v in stances.items()},
            })
        except Exception as e:
            logger.info("render stamp skipped: %s", e)
    return block


def review_flags(creatives_all: list[dict],
                 block: dict | None = None) -> list[dict]:
    """The dashboard's review-cycle cards (replaces the retired kill cards):
    'due for review: N · pull candidates: M' — doors into the Review Session.
    Derived from the same built block (one computation)."""
    if block is None:
        block = build_block(creatives_all, record_render=False)
    cards = block.get("cards") or {}
    due = [k for k, c in cards.items() if c.get("lane") == "due_for_review"]
    pulls = [k for k, c in cards.items() if c.get("pull_flags")]
    out = []
    if due:
        out.append({"severity": 2, "kind": "review_due",
                    "creative": None,
                    "headline": f"{len(due)} creative(s) due for review"
                                + (f" · {len(pulls)} pull candidate(s) "
                                   f"(peer-relative)" if pulls else ""),
                    "question": "open the Review Session — the weekly ritual: "
                                "keep or pull, per set, humans decide",
                    "link": "/ads?view=board&session=1",
                    "id": f"adflag:review_due:{len(due)}"})
    return out


def keep_running(actor: dict, creative_key: str, reason=None) -> tuple[bool, str | None]:
    """The Review Session's KEEP action: resets the creative's review clock
    (reason optional, encouraged), journaled + recorded in the dated session."""
    key = str(creative_key or "").strip()
    if not re.match(r"^[0-9]{10,20}$", key):
        return False, "bad creative key"
    reset_review_clock(key)
    who = (actor or {}).get("user") or "unknown"
    r = str(reason or "").strip()
    _journal({"at": _now(), "who": who, "action": "review_keep",
              "creative": key, "from": "due_for_review", "to": "running",
              "reason": r or "(kept — no note)"})
    _session_record(actor, "kept", key, r)
    return True, None


def _session_record(actor: dict, action: str, creative_key: str, reason: str) -> None:
    """One dated review-session record per Sydney day — the browsable ritual
    history ({who, date, kept[], pulled[], cohort notes})."""
    try:
        import kv_store
        from helpers import today_sydney
        sessions = kv_store.get(_KV_REVIEW_SESSIONS) or {}
        d = str(today_sydney())
        s = sessions.get(d) or {"date": d, "kept": [], "pulled": [],
                                "reviewers": []}
        who = (actor or {}).get("user") or "unknown"
        if who not in s["reviewers"]:
            s["reviewers"].append(who)
        s[action if action in ("kept", "pulled") else "kept"].append(
            {"creative": creative_key, "reason": (reason or "")[:200], "by": who,
             "at": _now()})
        sessions[d] = s
        kv_store.put(_KV_REVIEW_SESSIONS, dict(list(sessions.items())[-30:]))
    except Exception as e:
        logger.info("review session record failed: %s", e)


def review_sessions(limit: int = 10) -> list[dict]:
    try:
        import kv_store
        sessions = kv_store.get(_KV_REVIEW_SESSIONS) or {}
        out = [sessions[d] for d in sorted(sessions)][-limit:]
        for s in out:
            s["cohort_size"] = len(s.get("kept") or []) + len(s.get("pulled") or [])
        return out
    except Exception:
        return []


# ── the SETS view (the ad set as first-class unit) ───────────────────────────

def sets_overview(creatives_window: list[dict], creatives_all: list[dict]) -> dict:
    """Per-role rollup: mapped adset ids · intended vs ACTUAL daily spend
    (archive rollup) with drift · window funnel (sum of member creatives) ·
    within-set peer table · status rollup · injected count. Unmapped sets
    with recent delivery surface honestly — never silently binned."""
    import datetime as dt
    from helpers import today_sydney
    rl = strategy()
    es = _entity_store()
    roles = set_roles_map()
    today = today_sydney()
    window7 = set_spend_window(int(rl["review_cycle_days"]))
    yesterday = set_spend_window(1, end=today - dt.timedelta(days=1))
    block = build_block(creatives_all, record_render=False)
    win_by_key = {c.get("creative_key"): c for c in creatives_window or []
                  if c.get("tier") == "ad"}
    adset_names = {}
    for aid, a in ((es.get("ads") or {}) | (es.get("extras") or {})).items():
        if a.get("adset_id"):
            adset_names[str(a["adset_id"])] = a.get("adset_name") or ""
    out_roles = {}
    for role in SET_ROLES:
        sids = [sid for sid, r in roles.items() if r == role]
        member_keys = [k for k, c in (block.get("cards") or {}).items()
                       if role in (c.get("sets") or [])]
        spend7 = round(sum(sum((window7.get(s) or {}).values()) for s in sids), 2)
        spend_y = round(sum(sum((yesterday.get(s) or {}).values()) for s in sids), 2)
        budget = (rl.get("budgets") or {}).get(role)
        drift = None
        if budget:
            lo, hi = float(budget[0]), float(budget[1])
            tol = float(rl["budget_drift_pct"]) / 100
            if spend_y > hi * (1 + tol):
                drift = (f"spent ${spend_y:,.0f} yesterday vs ${lo:,.0f}–"
                         f"${hi:,.0f}/day intended (over)")
            elif spend_y < lo * (1 - tol) and spend_y >= 0:
                drift = (f"spent ${spend_y:,.0f} yesterday vs ${lo:,.0f}–"
                         f"${hi:,.0f}/day intended (under)")
        funnel = {"leads": 0, "sets": 0, "closes": 0, "spend": 0.0}
        multi = 0
        ranking = []
        set_total7 = spend7 or 0.0
        for k in member_keys:
            card = block["cards"][k]
            w = win_by_key.get(k) or {}
            spans = len(card.get("sets") or []) > 1
            if spans:
                multi += 1
            else:
                for f in ("leads", "sets", "closes"):
                    funnel[f] += int(w.get(f) or 0)
                funnel["spend"] += float(w.get("spend") or 0)
            ads_in = _member_ads_in_set(k, sids, es, creatives_all)
            cr_spend7 = round(sum((window7.get(s) or {}).get(a, 0.0)
                                  for s in sids for a in ads_in), 2)
            share = round(100 * cr_spend7 / set_total7, 1) if set_total7 else 0.0
            ranking.append({
                "creative_key": k,
                "label": next((c.get("label") for c in creatives_all
                               if c.get("creative_key") == k), k),
                "delivery_share_pct": share,
                "window_spend": cr_spend7,
                "leads": (w.get("leads") if not spans else None),
                "cpl": (w.get("cost_per_lead") if not spans else None),
                "verdict": w.get("verdict"),
                "provisional": (w.get("provisional") or {}).get("label")
                                if isinstance(w.get("provisional"), dict) else None,
                "spans_sets": spans,
                "spans_note": ("in multiple sets — leads/CPL are creative-"
                               "total, not set-splittable" if spans else None),
                "status": (card.get("status") or {}).get("status"),
                "pull_flags": [s["signal"] for s in
                               (card.get("pull_flags") or {}).get("signals") or []],
                "injected": card.get("injected"),
                "due": bool((card.get("review") or {}).get("due")),
            })
        ranking.sort(key=lambda r: -r["delivery_share_pct"])
        statuses = {}
        for k in member_keys:
            s = (block["cards"][k].get("status") or {}).get("status") or "unknown"
            statuses[s] = statuses.get(s, 0) + 1
        out_roles[role] = {
            "label": SET_ROLE_LABELS[role],
            "adset_ids": sids,
            "adset_names": [adset_names.get(s, "") for s in sids],
            "creatives": len(member_keys),
            "intended_daily": budget,
            "actual_yesterday": spend_y,
            "actual_window": spend7,
            "actual_daily_avg": round(spend7 / max(int(rl["review_cycle_days"]), 1), 2),
            "budget_drift": drift,
            "funnel_window": {k2: round(v, 2) for k2, v in funnel.items()},
            "funnel_note": (f"{multi} creative(s) span multiple sets — their "
                            f"leads are excluded here (not set-splittable)"
                            if multi else None),
            "status_rollup": statuses,
            "injected_this_cycle": sum(1 for k in member_keys
                                       if block["cards"][k].get("injected")),
            "ranking": ranking,
        }
    # unmapped sets with recent delivery — surfaced, never binned
    unmapped = []
    for sid, ads in window7.items():
        if sid in roles or sid == "__no_adset__":
            continue
        sp = round(sum(ads.values()), 2)
        if sp > 0:
            unmapped.append({"adset_id": sid, "adset_name": adset_names.get(sid, ""),
                             "window_spend": sp, "ads": len(ads)})
    unmapped.sort(key=lambda u: -u["window_spend"])
    # partition: Σ set spend (incl. unmapped + no-adset) == archive total
    all_spend = round(sum(sum(a.values()) for a in window7.values()), 2)
    mapped_spend = round(sum(r["actual_window"] for r in out_roles.values()), 2)
    unmapped_spend = round(sum(u["window_spend"] for u in unmapped), 2)
    no_adset = round(sum((window7.get("__no_adset__") or {}).values()), 2)
    return {"roles": out_roles, "unmapped": unmapped,
            "partition": {"mapped": mapped_spend, "unmapped": unmapped_spend,
                          "no_adset_record": no_adset, "total": all_spend,
                          "ok": abs(mapped_spend + unmapped_spend + no_adset
                                    - all_spend) < 0.05,
                          "invariant": "Σ set spend == archive account total "
                                       "over the window"},
            "window_days": int(rl["review_cycle_days"]),
            "strategy": rl}


def _member_ads_in_set(creative_key: str, sids: list, es: dict,
                       creatives_all: list) -> list:
    row = next((c for c in creatives_all or []
                if c.get("creative_key") == creative_key), None)
    out = []
    for a in (row or {}).get("ad_ids") or []:
        e = ((es.get("ads") or {}).get(str(a))
             or (es.get("extras") or {}).get(str(a)) or {})
        if str(e.get("adset_id") or "") in sids:
            out.append(str(a))
    return out


# ── broad vs targeted (the strategy's live experiment) ───────────────────────

def broad_vs_targeted(creatives_window: list[dict]) -> dict:
    """Does Meta's broad delivery beat manual targeting? Creatives with ads
    in BOTH Set 1 and Set 2 render side-by-side per set (spend/delivery from
    the archive — exact; leads/CPL are creative-total, labelled not-set-
    splittable). Where no pairing exists: the set-level aggregate, labelled.
    Every figure carries the evidence caveat."""
    rl = strategy()
    es = _entity_store()
    roles = set_roles_map()
    broad_ids = [s for s, r in roles.items() if r == "broad_video"]
    targ_ids = [s for s, r in roles.items() if r == "targeted_video"]
    if not broad_ids or not targ_ids:
        return {"available": False,
                "reason": "map the Broad and Targeted ad sets first (the "
                          "strategy panel) — no comparison without ids"}
    window = set_spend_window(int(rl["review_cycle_days"]))
    pairs = []
    agg = {"broad_video": {"spend": 0.0, "leads": 0, "creatives": 0},
           "targeted_video": {"spend": 0.0, "leads": 0, "creatives": 0}}
    shared = 0
    for c in creatives_window or []:
        if c.get("tier") != "ad":
            continue
        b_ads = _member_ads_in_set(c["creative_key"], broad_ids, es,
                                   creatives_window)
        t_ads = _member_ads_in_set(c["creative_key"], targ_ids, es,
                                   creatives_window)
        b_sp = round(sum((window.get(s) or {}).get(a, 0.0)
                         for s in broad_ids for a in b_ads), 2)
        t_sp = round(sum((window.get(s) or {}).get(a, 0.0)
                         for s in targ_ids for a in t_ads), 2)
        if b_ads and t_ads:
            shared += 1
            pairs.append({
                "label": c.get("label"), "creative_key": c["creative_key"],
                "match": "exact (same creative, ads in both sets)",
                "broad": {"spend_window": b_sp},
                "targeted": {"spend_window": t_sp},
                "leads_total": c.get("leads"),
                "cpl_total": c.get("cost_per_lead"),
                "evidence_note": (f"n={c.get('leads') or 0} leads (creative-"
                                  f"total — per-set lead split not available; "
                                  f"delivery/spend ARE per-set from the archive)"),
            })
        elif b_ads:
            agg["broad_video"]["spend"] += b_sp
            agg["broad_video"]["leads"] += int(c.get("leads") or 0)
            agg["broad_video"]["creatives"] += 1
        elif t_ads:
            agg["targeted_video"]["spend"] += t_sp
            agg["targeted_video"]["leads"] += int(c.get("leads") or 0)
            agg["targeted_video"]["creatives"] += 1
    for k in agg:
        a = agg[k]
        a["spend"] = round(a["spend"], 2)
        a["cpl"] = round(a["spend"] / a["leads"], 2) if a["leads"] else None
    return {"available": True, "pairs": pairs,
            "set_aggregate": agg,
            "shared_creatives": shared,
            "aggregate_note": ("set aggregates count only creatives EXCLUSIVE "
                               "to each set" +
                               (f"; {shared} shared creative(s) excluded from "
                                f"per-set lead counts (not splittable)"
                                if shared else "")),
            "window_days": int(rl["review_cycle_days"]),
            "evidence_note": "min-evidence honesty: CPL comparisons below the "
                             "verdict min-n are provisional signal, never proof"}


# ── sentinel watches (called from ad_sentinel.nightly_extras) ────────────────

def sentinel_watch() -> dict:
    """Nightly lifecycle watches: status freshness · convergence lag (>2d →
    HYGIENE item naming the mover) · stage-classifier drift (recompute vs the
    rendered lanes for unchanged inputs — zero drift, I17 applied to stages) ·
    rules-journal integrity · stance-summary integrity."""
    import kv_store
    out: dict = {}
    # 1 · status freshness
    ss = _spend_store()
    import time as _t
    age_h = ((_t.time() - float(ss.get("refreshed_at") or 0)) / 3600
             if ss.get("refreshed_at") else None)
    out["status_freshness"] = {"age_h": round(age_h, 1) if age_h is not None else None,
                               "ok": age_h is not None and age_h < 26}
    if not out["status_freshness"]["ok"]:
        _sentinel_feed("board status freshness: delivery archive "
                       + (f"{round(age_h)}h old" if age_h is not None else "never refreshed")
                       + " — statuses render DEGRADED until Meta refreshes", loud=True)
    # 2 · convergence lag
    lag = []
    for key, dec in _decisions().items():
        if dec.get("executed"):
            continue
        age = _age_days(dec.get("at"))
        if age > 2:
            lag.append({"creative": dec.get("label"), "by": dec.get("by_display"),
                        "age_days": age, "state": dec.get("state")})
            _sentinel_feed(f"decision unexecuted {age}d: {dec.get('by_display')} "
                           f"marked “{dec.get('label')}” "
                           f"{dec.get('state', '').replace('marked_to_', 'to ')} — "
                           "still not applied in Ads Manager")
    out["convergence_lag"] = lag
    _publish_feed()                       # refresh feed ages nightly
    # 3 · stage-classifier drift (unchanged inputs must classify identically)
    drift = []
    try:
        last = kv_store.get(_KV_LAST_RENDER) or {}
        if last.get("lanes"):
            import roster_engine
            r_all, _m = roster_engine.load_result(ALL_DAYS, None, None,
                                                  basis="cohort", market=None)
            block = build_block(r_all.get("creatives") or [], record_render=False)
            for key, lane in (last["lanes"] or {}).items():
                card = block["cards"].get(key)
                if not card:
                    continue
                if card["inputs_hash"] == (last.get("hashes") or {}).get(key) \
                        and card["lane"] != lane:
                    drift.append({"creative": key, "rendered": lane,
                                  "recomputed": card["lane"]})
            if drift:
                _sentinel_feed(f"STAGE DRIFT: {len(drift)} card(s) reclassified on "
                               f"unchanged inputs — {drift[:3]}", loud=True)
    except Exception as e:
        out["drift_error"] = str(e)[:100]
    out["stage_drift"] = drift
    # 4 · strategy-config journal integrity (edits must be journaled) +
    #     R-A2 watches: review overdue · budget drift · set partition
    rl = strategy()
    edited = any(rl[k] != STRATEGY_DEFAULTS[k] for k in STRATEGY_DEFAULTS) \
        or any((rl.get("budgets") or {}).get(r) != BUDGET_DEFAULTS.get(r)
               for r in SET_ROLES) or bool(set_roles_map())
    jn = strategy_journal()
    out["rules"] = {"live": {k: rl[k] for k in STRATEGY_DEFAULTS},
                    "edited": edited, "journal_entries": len(jn),
                    "ok": (not edited) or bool(jn)}
    if not out["rules"]["ok"]:
        _sentinel_feed("strategy config differs from R-A2 defaults with NO "
                       "edit journal — someone wrote kv directly", loud=True)
    try:
        import roster_engine
        r_all2, _m2 = roster_engine.load_result(ALL_DAYS, None, None,
                                                basis="cohort", market=None)
        creatives_all2 = r_all2.get("creatives") or []
        blk = build_block(creatives_all2, record_render=False)
        overdue = []
        for k, c in (blk.get("cards") or {}).items():
            rv = c.get("review") or {}
            if rv.get("due") and rv.get("cycle_day", 0) > int(rl["review_due_through"]) + 3 \
                    and c.get("lane") == "due_for_review":
                overdue.append({"creative": k, "cycle_day": rv["cycle_day"]})
        out["review_overdue"] = overdue
        if overdue:
            _sentinel_feed(f"review overdue: {len(overdue)} creative(s) past "
                           f"day {int(rl['review_due_through']) + 3} unreviewed — "
                           "the 7–8 day ritual is slipping")
        sv = sets_overview(creatives_all2, creatives_all2)
        drifts = [(r, v["budget_drift"]) for r, v in (sv.get("roles") or {}).items()
                  if v.get("budget_drift")]
        out["budget_drift"] = drifts
        for r, dmsg in drifts:
            _sentinel_feed(f"set budget drift [{r}]: {dmsg}")
        out["set_partition"] = sv.get("partition")
        if not (sv.get("partition") or {}).get("ok"):
            _sentinel_feed("SET PARTITION violated: Σ set spend ≠ archive "
                           "account total — the rollup lost money", loud=True)
        out["unmapped_sets"] = len(sv.get("unmapped") or [])
        if out["unmapped_sets"]:
            _sentinel_feed(f"{out['unmapped_sets']} ad set(s) with recent spend "
                           "are UNMAPPED to a role — map them on the strategy panel")
    except Exception as e:
        out["ra2_watch_error"] = str(e)[:100]
    # 5 · stance-summary integrity (chip == stored stances)
    try:
        import ads_discussion
        fresh = ads_discussion.stances_by_anchor()
        last = kv_store.get(_KV_LAST_RENDER) or {}
        mism = []
        for a, rendered in (last.get("stances") or {}).items():
            live = (fresh.get(a) or {}).get("counts") or {}
            if {k: v for k, v in rendered.items() if v} != {k: v for k, v in live.items() if v}:
                mism.append(a)
        out["stance_integrity"] = {"checked": len(last.get("stances") or {}),
                                   "mismatched_since_render": len(mism)}
    except Exception as e:
        out["stance_integrity"] = {"error": str(e)[:80]}
    # 6 · STATUS-MISMATCH SAMPLING (ground-truth sweep 2): N random rendered
    # ads/night — fresh per-ad effective_status from Meta (direct GETs, ≤8
    # calls) re-classified vs the rendered state. Drift LOUD. A stale entity
    # map self-heals on its next TTL refresh; this watch catches it lying
    # in the meantime.
    try:
        import meta_entities
        if meta_entities.configured():
            import random
            last = kv_store.get(_KV_LAST_RENDER) or {}
            rendered = last.get("statuses") or {}
            # id-keyed cards only: a name-keyed multi-candidate creative folds
            # several ads — a single fresh lookup can't re-derive its state
            pool = [k for k in rendered if re.match(r"^\d{10,20}$", str(k))]
            keys = random.sample(pool, min(8, len(pool)))
            rl2 = rules()
            ss2 = _spend_store()
            drifted = []
            checked = 0
            for key in keys:
                j, err = meta_entities._get(key, {
                    "access_token": meta_entities.META_ACCESS_TOKEN,
                    "fields": "effective_status"})
                if not j or not j.get("effective_status"):
                    continue
                checked += 1
                fresh_es = {"ads": {key: {"effective_status": j["effective_status"]}}}
                fresh = status_for([key], fresh_es, ss2, rl2)
                if fresh["status"] != rendered.get(key):
                    drifted.append({"ad": key, "rendered": rendered.get(key),
                                    "fresh": fresh["status"],
                                    "fresh_effective": j["effective_status"]})
            out["status_sampling"] = {"checked": checked, "drift": drifted,
                                      "api_calls": len(keys)}
            if drifted:
                _sentinel_feed(f"STATUS DRIFT vs fresh Meta: {len(drifted)}/{checked} "
                               f"sampled ad(s) render a different state — {drifted[:2]}",
                               loud=True)
        else:
            out["status_sampling"] = {"skipped": "Meta not configured"}
    except Exception as e:
        out["status_sampling"] = {"error": str(e)[:80]}
    return out


def _sentinel_feed(msg: str, loud: bool = False) -> None:
    try:
        import ad_sentinel
        ad_sentinel._feed(msg, loud=loud)
    except Exception:
        pass


# ── EDITH (read-only) ────────────────────────────────────────────────────────

def _find_creative(name_frag: str) -> tuple[str | None, str | None]:
    """Resolve a spoken name fragment to (creative_key, label) via the
    all-time engine slice (rollup-backed — no build)."""
    frag = (name_frag or "").strip().lower()
    if len(frag) < 3:
        return None, None
    try:
        import roster_engine
        r_all, _m = roster_engine.load_result(ALL_DAYS, None, None,
                                              basis="cohort", market=None)
        best = None
        for c in (r_all.get("creatives") or []):
            if c.get("tier") != "ad":
                continue
            lbl = (c.get("label") or "").lower()
            if frag in lbl:
                if best is None or len(c.get("label") or "") < len(best[1] or ""):
                    best = (c.get("creative_key"), c.get("label"))
        return best or (None, None)
    except Exception as e:
        logger.info("creative resolve failed: %s", e)
        return None, None


_WHY_KILL_RE = re.compile(
    r"why\s+(did|was|have)?\s*(we|you)?\s*(kill|pull|pause|stop|scale)\w*\s+(.{2,60})", re.I)
_TEAM_THINK_RE = re.compile(
    r"what\s+(does|do)\s+the\s+team\s+think\s+(of|about)\s+(.{2,60})|"
    r"(team|anyone)('s)?\s+(stance|opinion)s?\s+on\s+(.{2,60})", re.I)


def handle_decision_recall(text: str) -> tuple[str | None, bool]:
    """EDITH: 'why did we kill {ad}' → the move reason + mover (journal truth);
    falls back to the verdict when no human decision exists."""
    m = _WHY_KILL_RE.search(text or "")
    if not m:
        return None, False
    frag = re.sub(r"[?.!]+$", "", m.group(4) or "").strip()
    key, label = _find_creative(frag)
    if not key:
        return (f"I can't find a creative matching “{frag}” on the ad board.", True)
    dec = _decisions().get(key)
    if dec:
        lines = [f"{label} — {dec['state'].replace('_', ' ')} by "
                 f"{dec.get('by_display')} on {dec.get('at')}:",
                 f"  reason: “{dec.get('reason')}”"]
        if dec.get("executed"):
            lines.append(f"  {dec.get('convergence')} ({dec.get('converged_at')})")
        else:
            lines.append(f"  still awaiting execution in Ads Manager "
                         f"({_age_days(dec.get('at'))}d)")
        if dec.get("below_min_n"):
            lines.append("  (marked below the evidence threshold — a rotation "
                         "call, not a statistical verdict)")
        return ("\n".join(lines), True)
    # no human decision — the engine's view
    try:
        import roster_engine
        r_all, _m2 = roster_engine.load_result(ALL_DAYS, None, None,
                                               basis="cohort", market=None)
        row = next((c for c in (r_all.get("creatives") or [])
                    if c.get("creative_key") == key), None)
        if row:
            st = status_for(row.get("ad_ids") or [], _entity_store(),
                            _spend_store())
            stage = classify_stage(row, st, rules())
            return (f"No human decision is recorded for {label}. "
                    f"The engine's read: {stage['lane'].replace('_', ' ')} — "
                    f"{stage['why']}", True)
    except Exception as e:
        logger.info("decision recall engine leg failed: %s", e)
    return (f"No decision recorded for {label} and the engine read is "
            "unavailable right now.", True)


def handle_stance_recall(text: str) -> tuple[str | None, bool]:
    """EDITH: 'what does the team think of {ad}' → stances + quotes (one
    store: ads_discussion)."""
    m = _TEAM_THINK_RE.search(text or "")
    if not m:
        return None, False
    frag = re.sub(r"[?.!]+$", "", (m.group(3) or m.group(7) or "")).strip()
    key, label = _find_creative(frag)
    if not key:
        return (f"I can't find a creative matching “{frag}” on the ad board.", True)
    import ads_discussion
    summary = ads_discussion.stances_by_anchor().get(key)
    notes = ads_discussion.list_comments(creative=key, state="active", limit=6)
    if not summary and not notes:
        return (f"No team notes or stances on {label} yet.", True)
    lines = [f"Team view on {label}:"]
    if summary:
        counts = summary.get("counts") or {}
        chip = " · ".join(f"{n} {s}" for s, n in counts.items() if n)
        by = ", ".join(f"{u}: {s}" for u, s in (summary.get("by") or {}).items())
        lines.append(f"  stances: {chip or 'none'}" + (f" ({by})" if by else ""))
    for n in notes[:4]:
        st = (n.get("stance") or "").upper()
        lines.append(f"  · {n['author']['display']}" + (f" [{st}]" if st else "")
                     + (f": “{n['body'][:150]}”" if n.get("body") else " (stance only)"))
    lines.append("  (stances are opinions — a decision is always an explicit "
                 "move + reason by a named human)")
    return ("\n".join(lines), True)
