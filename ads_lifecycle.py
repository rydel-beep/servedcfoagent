"""
ads_lifecycle.py
----------------
THE AD LIFECYCLE ENGINE (Board v2): rotation rules (R-A), the ONE status
classifier (Law 3), the ONE stage classifier (Law 1), the decision journal +
convergence loop (Law 2 / R-B), and the stance-summary consumer (Law 4 / R-C).

The Board is a VIEW — every number it shows is either an engine field
(window/all-time creatives from attribution_engine via the rollup layer) or a
field computed HERE, once, at one call site. No route or JS ever re-derives a
lane, a status, or a rotation clock.

TWO KINDS OF KILL, NEVER CONFUSED (Law 1):
  - ROTATION kill-candidate: R-A fired — the test boundary (min(4 active days,
    $200 lifetime spend), config, ruled) passed with 0 lifetime leads. A
    cost/delivery decision, legitimate at low n. `basis: "rotation"`.
  - VERDICT kill: the statistical KILL from attribution_verdicts (min-n 30
    leads, standing ruling). `basis: "verdict"`. The lane chip always names
    which fired; a rotation lane never renders as statistical proof.

DECISION BOARD, NOT CONTROL PANEL (Law 2): Meta access is ads_read. A move
records a journaled decision with a MANDATORY reason and spawns the human
action; convergence is VERIFIED when a later status sync sees Meta actually
changed (kill → paused at any layer; scale → a new ad id joins the creative,
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

_KV_RULES = "ads:rotation_rules"
_KV_RULES_JOURNAL = "ads:rotation_rules_journal"
_KV_DECISIONS = "ads:lifecycle:decisions"
_KV_JOURNAL = "ads:lifecycle:journal"
_KV_FEED = "feed:extra:ads_decisions"     # action-feed registry channel
_KV_LAST_RENDER = "ads:lifecycle:last_render"

# R-A (DECISIONS #143): Rydel's ruled rotation defaults — editable in the
# rules panel (kv), journaled per edit; these values ARE the ruling.
RULE_DEFAULTS = {
    "test_days": 4,          # active DELIVERY days (#133: runtime never counts paused days)
    "test_spend": 200.0,     # lifetime spend, AUD
    "freshness_days": 2,     # delivery horizon: impressions within N days = DELIVERING
}
_RULE_BOUNDS = {"test_days": (1, 60), "test_spend": (10.0, 10000.0),
                "freshness_days": (1, 7)}

DECISION_STATES = {"kill": "marked_to_kill", "scale": "marked_to_scale"}

# statuses that mean "on" at the ad's own toggle but possibly not delivering
_AMBER_REASONS = {
    "PENDING_REVIEW": "in review (Meta has not approved delivery yet)",
    "PREAPPROVED": "pre-approved — not yet fully approved",
    "PENDING_BILLING_INFO": "billing issue on the account",
    "IN_PROCESS": "processing at Meta",
    "WITH_ISSUES": "flagged WITH_ISSUES by Meta",
}
_PAUSE_LAYER = {"PAUSED": "ad", "CAMPAIGN_PAUSED": "campaign",
                "ADSET_PAUSED": "ad set", "ARCHIVED": "ad (archived)",
                "DISAPPROVED": "ad (disapproved)"}


# ── rotation rules (R-A) ─────────────────────────────────────────────────────

def rules() -> dict:
    """The live rotation thresholds — kv-backed, ruled defaults."""
    out = dict(RULE_DEFAULTS)
    try:
        import kv_store
        stored = kv_store.get(_KV_RULES) or {}
        for k in out:
            if stored.get(k) is not None:
                out[k] = type(RULE_DEFAULTS[k])(stored[k])
    except Exception as e:
        logger.info("rotation rules fell back to ruled defaults: %s", e)
    return out


def set_rules(actor: dict, updates: dict) -> tuple[dict | None, str | None]:
    """Edit the live thresholds (no deploy). Every edit journaled
    {who, when, key, old -> new}. Bounds-checked; unknown keys refused."""
    cur = rules()
    changes = []
    for k, v in (updates or {}).items():
        if k not in RULE_DEFAULTS:
            return None, f"unknown rule '{k}'"
        try:
            v = type(RULE_DEFAULTS[k])(v)
        except (TypeError, ValueError):
            return None, f"bad value for {k}"
        lo, hi = _RULE_BOUNDS[k]
        if not (lo <= v <= hi):
            return None, f"{k} must be between {lo} and {hi}"
        if v != cur[k]:
            changes.append((k, cur[k], v))
    if not changes:
        return cur, None
    from helpers import now_sydney
    import kv_store
    for k, old, new in changes:
        cur[k] = new
    kv_store.put(_KV_RULES, cur)
    j = kv_store.get(_KV_RULES_JOURNAL) or []
    for k, old, new in changes:
        j.append({"at": now_sydney().strftime("%Y-%m-%d %H:%M"),
                  "who": (actor or {}).get("user") or "unknown",
                  "key": k, "old": old, "new": new})
    kv_store.put(_KV_RULES_JOURNAL, j[-200:])
    return cur, None


def rules_journal() -> list:
    try:
        import kv_store
        return kv_store.get(_KV_RULES_JOURNAL) or []
    except Exception:
        return []


# ── the status engine (Law 3): DELIVERING / ENABLED-NOT-DELIVERING / PAUSED ──

def _spend_store() -> dict:
    import meta_entities
    return meta_entities._load_json(meta_entities.AD_SPEND_STORE)


def _entity_store() -> dict:
    import meta_entities
    return meta_entities._load_json(meta_entities.ENTITY_STORE)


def _recent_delivery_days(spend_store: dict, horizon_days: int) -> list[str]:
    from datetime import timedelta
    from helpers import today_sydney
    t = today_sydney()
    return [str(t - timedelta(days=i)) for i in range(horizon_days)]


def status_for(ad_ids: list[str], entity_store: dict, spend_store: dict,
               rl: dict | None = None) -> dict:
    """ONE status classification for a creative (its member ad ids).
    Returns {status: delivering|enabled_not_delivering|paused|unknown,
             reason, layer, as_of, degraded}. NEVER the ad's own toggle alone:
    delivery truth comes from the daily buckets; the pausing layer is named
    from effective_status (which folds parents). A dead Meta source returns
    status 'unknown' with the reason — never a stale green (F5)."""
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
        return {"status": "unknown", "reason": degraded, "layer": None,
                "as_of": as_of, "degraded": degraded}

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
        return {"status": "delivering", "reason": "impressions within the "
                f"last {rl.get('freshness_days', 2)} day(s) (daily-delivery archive)",
                "layer": None, "as_of": as_of, "degraded": None}
    # enabled-but-blocked states (review/billing/issues) are the AMBER class
    # with their reason NAMED — the ad is on, Meta isn't delivering it
    for s in statuses:
        if s in _AMBER_REASONS:
            return {"status": "enabled_not_delivering", "reason": _AMBER_REASONS[s],
                    "layer": None, "as_of": as_of, "degraded": None}
    if any(s == "ACTIVE" for s in statuses):
        # enabled at every layer, zero recent delivery — the dangerous middle
        return {"status": "enabled_not_delivering",
                "reason": ("reason unknown — commonly learning phase or "
                           "budget-limited (not visible under ads_read)"),
                "layer": None, "as_of": as_of, "degraded": None}
    if statuses:
        for s in statuses:            # name the pausing layer (parents first is
            if s in _PAUSE_LAYER:     # how Meta orders effective_status anyway)
                return {"status": "paused", "reason": f"paused at the {_PAUSE_LAYER[s]} layer",
                        "layer": _PAUSE_LAYER[s], "as_of": as_of, "degraded": None}
        return {"status": "enabled_not_delivering",
                "reason": f"Meta status {statuses[0]} — no recent delivery",
                "layer": None, "as_of": as_of, "degraded": None}
    # no entity record (deleted/unlisted ad), no recent delivery
    return {"status": "paused", "reason": "not in the Meta ad listing (deleted or "
            "archived out) and no recent delivery",
            "layer": "ad (unlisted)", "as_of": as_of, "degraded": None}


# ── the ONE stage classifier (Law 1) ─────────────────────────────────────────

def classify_stage(row_all: dict, status: dict, rl: dict) -> dict:
    """THE stage classifier — the only function that assigns an engine lane.
    Inputs are ENGINE fields only: the all-time (lifetime) creative row
    (leads/spend/verdict/gates/lineage from attribution_engine) + the status
    triad + the rules. Deterministic; zero I/O. Decision overlay is applied by
    the caller (a human move PINS the card; this stays the engine's opinion).

    Lanes: testing · kill_candidate (basis rotation|verdict) · watch ·
    scale_candidate · archive (paused/killed)."""
    lin = (row_all or {}).get("lineage") or {}
    leads = int((row_all or {}).get("leads") or 0)
    spend = float((row_all or {}).get("spend") or 0)
    verdict = (row_all or {}).get("verdict")
    gates = (row_all or {}).get("gates") or {}
    launch = lin.get("launch")
    active_days = lin.get("active_days")

    rotation = None
    if launch and active_days is not None:
        by_days = active_days >= int(rl["test_days"])
        by_spend = spend >= float(rl["test_spend"])
        rotation = {
            "launch": launch,
            "launch_approx": bool(lin.get("launch_approx")),
            "day": active_days,                      # ACTIVE delivery days (#133)
            "spend": round(spend, 2),
            "test_days": int(rl["test_days"]),
            "test_spend": float(rl["test_spend"]),
            "boundary_hit": by_days or by_spend,
            "boundary_by": ("days" if by_days else "spend") if (by_days or by_spend) else None,
            "label": (f"day {active_days} · ${spend:,.0f}/${rl['test_spend']:,.0f}"
                      + (" · clock ≈ (launch probe pending)" if lin.get("launch_approx") else "")),
            "clock_note": "rotation clock: per-ad lifetime from FIRST DELIVERY "
                          "(active delivery days) — not the table's date window",
        }

    def out(lane, why, basis=None):
        return {"lane": lane, "why": why, "kill_basis": basis,
                "rotation": rotation, "status": status}

    # archive: verified-paused at any layer is terminal until Meta changes
    if status.get("status") == "paused":
        return out("archive", f"paused in Meta — {status.get('reason')}")
    if lin.get("never_delivered"):
        return out("testing", "never delivered — no rotation clock exists yet "
                              "(lifetime impressions 0)")
    if rotation is None:
        return out("testing", "rotation clock unavailable — launch lineage "
                              "degraded/pending; boundary can't be judged (not a zero)")
    if not rotation["boundary_hit"]:
        return out("testing", f"inside the test window — {rotation['label']}")
    # boundary reached — R-A branches
    if leads == 0:
        return out("kill_candidate",
                   f"R-A fired: boundary by {rotation['boundary_by']} "
                   f"({rotation['label']}) with 0 lifetime leads — a rotation "
                   "call (cost/delivery), NOT statistical proof", basis="rotation")
    if verdict == "KILL":
        return out("kill_candidate",
                   f"VERDICT KILL at n={gates.get('n_leads')} leads — the "
                   "statistical kill (min-n honored)", basis="verdict")
    if verdict == "DOUBLE DOWN":
        # the ONLY path into the statistical lane: a verdict at sufficient n.
        # Provisional/trending rows — however hot — stay WATCH (R-A).
        return out("scale_candidate",
                   f"verdict-backed: DOUBLE DOWN at n={gates.get('n_leads')} "
                   f"leads / {gates.get('n_closes')} closes")
    return out("watch", f"survived the boundary with {leads} lifetime lead(s) — "
                        "evidence accumulating toward a verdict")


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
        return None, "move target must be 'kill' or 'scale'", None
    key = str(creative_key or "").strip()
    if not re.match(r"^[0-9]{10,20}$", key):
        return None, "bad creative key", None
    if row_all is not None and below_min_n(row_all) and not confirm_below_min_n:
        return None, None, {
            "friction": True,
            "note": "below evidence threshold — this is a rotation call, not a "
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
    if dec.get("state") == "marked_to_kill" and status.get("status") == "paused":
        dec["executed"] = True
        dec["converged_at"] = _now()
        dec["convergence"] = f"verified in Meta — {status.get('reason')}"
        _journal({"at": dec["converged_at"], "who": "status-sync",
                  "action": "converged", "creative": key, "label": dec.get("label"),
                  "from": "marked_to_kill", "to": "killed (verified)",
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
            verb = "pause" if dec.get("state") == "marked_to_kill" else "scale"
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
        rl["test_days"], rl["test_spend"]))
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def build_block(creatives_all: list[dict], record_render: bool = True) -> dict:
    """THE lifecycle block for the board payload: per-creative status triad,
    engine lane, decision overlay (+ convergence check), stance summaries,
    and the live rules. `creatives_all` = the ALL-TIME engine creatives
    (lifetime numbers — the rotation clock's scope). One call site."""
    rl = rules()
    es = _entity_store()
    ss = _spend_store()
    decisions = _decisions()
    converged_any = False
    cards: dict = {}
    for row in creatives_all or []:
        if row.get("tier") != "ad":
            continue
        key = row.get("creative_key")
        if not key:
            continue
        st = status_for(row.get("ad_ids") or [], es, ss, rl)
        stage = classify_stage(row, st, rl)
        dec = decisions.get(key)
        if dec and _check_convergence(key, dec, st, row):
            converged_any = True
        card = {
            "engine_lane": stage["lane"],
            "engine_why": stage["why"],
            "kill_basis": stage.get("kill_basis"),
            "rotation": stage.get("rotation"),
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
            # SURFACED NEVER SILENT: the human's decision pins the card; when
            # the engine now disagrees with the marked direction, chip it.
            marked_dir = "kill" if dec["state"] == "marked_to_kill" else "scale"
            eng = stage["lane"]
            disagrees = ((marked_dir == "kill" and eng == "scale_candidate")
                         or (marked_dir == "scale"
                             and eng in ("kill_candidate", "archive")))
            if disagrees and not dec.get("executed"):
                card["disagreement"] = f"engine: {eng.replace('_', '-')}"
            # display lane: the decision overlay
            if dec.get("executed"):
                card["lane"] = "archive"
                card["archive_label"] = ("killed — verified in Meta"
                                         if dec["state"] == "marked_to_kill"
                                         else "scaled — executed")
            else:
                card["lane"] = dec["state"]
        else:
            card["lane"] = stage["lane"]
            if stage["lane"] == "archive":
                card["archive_label"] = "paused (no decision recorded)"
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
        "cards": cards,
        "stances": stances,
        "lanes_order": ["testing", "kill_candidate", "marked_to_kill", "watch",
                        "scale_candidate", "marked_to_scale", "archive"],
        "lane_labels": {
            "testing": "TESTING (rotation window)",
            "kill_candidate": "KILL CANDIDATE",
            "marked_to_kill": "MARKED TO KILL",
            "watch": "WATCH",
            "scale_candidate": "SCALE CANDIDATE",
            "marked_to_scale": "MARKED TO SCALE",
            "archive": "KILLED / PAUSED (archive)",
        },
    }
    if record_render:
        try:
            import kv_store, time as _t
            kv_store.put(_KV_LAST_RENDER, {
                "at": _t.time(),
                "lanes": {k: c["lane"] for k, c in cards.items()},
                "hashes": {k: c["inputs_hash"] for k, c in cards.items()},
                "stances": {a: {s: n for s, n in v.get("counts", {}).items()}
                            for a, v in stances.items()},
            })
        except Exception as e:
            logger.info("render stamp skipped: %s", e)
    return block


def kill_candidate_flags(creatives_all: list[dict], limit: int = 6,
                         block: dict | None = None) -> list[dict]:
    """THE dashboard kill cards — LITERALLY the Board's kill lane: derived
    from the same built lifecycle block (pass `block` to reuse a serve's;
    otherwise built here by the one path). Consolidation: attribution_flags'
    old window-scoped spend_no_leads rule is retired; R-A's boundary replaces
    it. A decided card leaves this rail (its lane is marked_to_*; the feed
    carries the mark). Each card deep-links to the Board."""
    if block is None:
        block = build_block(creatives_all, record_render=False)
    by_key = {r.get("creative_key"): r for r in (creatives_all or [])
              if r.get("tier") == "ad"}
    out = []
    for key, card in (block.get("cards") or {}).items():
        if card.get("lane") != "kill_candidate":
            continue
        row = by_key.get(key) or {}
        rot = card.get("rotation") or {}
        if card.get("kill_basis") == "rotation":
            headline = (f"{rot.get('label', '')} · 0 lifetime leads — rotation "
                        "boundary reached")
            q = "rotation kill candidate (cost call, low n) — pause it in Ads Manager?"
        else:
            g = row.get("gates") or {}
            headline = f"VERDICT KILL at n={g.get('n_leads')} leads"
            q = "statistical kill — the verdict engine's call at sufficient n"
        out.append({"severity": 1, "kind": "rotation_kill_candidate",
                    "creative": row.get("label") or key,
                    "creative_key": key,
                    "kill_basis": card.get("kill_basis"),
                    "headline": headline, "question": q,
                    "link": f"/ads?view=board&dossier={key}",
                    "id": f"adflag:rotation_kill:{key}"})
        if len(out) >= limit:
            break
    return out


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
    # 4 · rules journal integrity (journal exists whenever rules differ from ruled defaults)
    rl = rules()
    edited = any(rl[k] != RULE_DEFAULTS[k] for k in RULE_DEFAULTS)
    jn = rules_journal()
    out["rules"] = {"live": rl, "edited": edited, "journal_entries": len(jn),
                    "ok": (not edited) or bool(jn)}
    if not out["rules"]["ok"]:
        _sentinel_feed("rotation rules differ from ruled defaults with NO edit "
                       "journal — someone wrote kv directly", loud=True)
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
    r"why\s+(did|was|have)?\s*(we|you)?\s*(kill|pause|stop|scale)\w*\s+(.{2,60})", re.I)
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
