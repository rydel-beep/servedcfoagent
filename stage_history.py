"""stage_history.py — REMEMBER WHAT THE CRM FORGETS.

The CRM mirror polls every 15 minutes but keeps only each deal's CURRENT
stage. So "was this lead pitched?" can only ever be answered as a lower
bound: anyone pitched and later moved on looks like they never were.

This recorder fixes that going forward, with zero human effort: on each
poll it compares what it sees now with what it saw last time and writes
down every change — in THIS REPO'S OWN STORE. It never calls the CRM
itself (it reads the mirror another job already refreshed), never writes
to the CRM, and needs no new token or cadence.

From its start date, "pitched" becomes a MEASURED event for deals observed
from then on; older deals keep the honest "lower bound" label. The same
history gives stage velocity (how long lead → booked → pitched → closed
takes), which the compass can adopt as a measured lag once there is enough
of it — labelled, never assumed.

A change seen only as a jump (two stages moved between polls, or the first
sighting of a deal already deep in the pipeline) is recorded AS a jump. It
is never filled in with stages that were never observed.
"""

from __future__ import annotations

import logging

import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

K_SEEN = "stage_history:last_seen"        # {opportunity_id: {stage, at}}
K_TRANSITIONS = "stage_history:transitions"
K_START = "stage_history:started_at"
MAX_TRANSITIONS = 4000

# the stage names that mean the offer was presented / the deal closed
PITCHED_STAGES = ("pitched and drifted",)
CLOSED_STAGES = ("closed deal", "won")
# How far along the pipeline a stage is. Alternates share a rank — a
# no-show and a booked consult are the same DISTANCE along, they're just
# different outcomes. Without this a normal move (booked → pitched) would
# be miscounted as a jump.
RANKS = {
    "served new leads": 0, "lead magnets(pdf downloaded)": 0,
    "ban leads (dnd)": 0, "stale": 0,
    "called but didn't pick up": 1, "call back to set": 1,
    "unresponsive/not interested": 1,
    "consult call booked": 2, "2nd consult call booked": 2,
    "consult call no show": 2, "consult call cancelled": 2,
    "client will reconnect": 2,
    "pitched and drifted": 3, "disqualified": 3,
    "closed deal": 4,
}


def _rank(stage: str) -> int | None:
    s = (stage or "").strip().lower().lstrip("✅ ").strip()
    for name, rank in RANKS.items():
        if name in s:
            return rank
    return None


def started_at() -> str | None:
    return kv_store.get(K_START)


def record_poll(poll_id: str | None = None) -> dict:
    """Compare this sighting with the last. READ-ONLY against the CRM: it
    reads the mirror table another job maintains."""
    try:
        import ghl_mirror
        opps = ghl_mirror.read_opportunities(open_only=False) or []
    except Exception as e:  # noqa: BLE001
        logger.info("stage recorder: mirror unavailable: %s", e)
        return {"ok": False, "reason": str(e)[:120]}

    now = now_sydney().isoformat()
    poll_id = poll_id or now
    seen = kv_store.get(K_SEEN) or {}
    transitions = kv_store.get(K_TRANSITIONS) or []
    first_run = not seen
    if not kv_store.get(K_START):
        kv_store.put(K_START, str(today_sydney()))

    new_rows, changed, first_sightings = [], 0, 0
    for o in opps:
        oid = o.get("id")
        if not oid:
            continue
        stage = o.get("stage_name") or ""
        prev = seen.get(oid)
        if prev is None:
            # first sighting — recorded as such, never back-filled with
            # stages that were never observed
            seen[oid] = {"stage": stage, "at": now}
            first_sightings += 1
            if not first_run:
                new_rows.append({
                    "opportunity_id": oid, "contact_id": o.get("contact_id"),
                    "from": None, "to": stage, "first_seen": now,
                    "poll": poll_id, "kind": "first sighting",
                    "jumped": (_rank(stage) or 0) > 1})
            continue
        if prev.get("stage") == stage:
            continue
        r_from, r_to = _rank(prev.get("stage")), _rank(stage)
        jumped = (r_from is not None and r_to is not None and r_to - r_from > 1)
        new_rows.append({
            "opportunity_id": oid, "contact_id": o.get("contact_id"),
            "from": prev.get("stage"), "to": stage, "first_seen": now,
            "poll": poll_id, "kind": "jump" if jumped else "step",
            "jumped": jumped})
        seen[oid] = {"stage": stage, "at": now}
        changed += 1

    if new_rows:
        transitions.extend(new_rows)
        kv_store.put(K_TRANSITIONS, transitions[-MAX_TRANSITIONS:])
    kv_store.put(K_SEEN, seen)
    return {"ok": True, "at": now, "watching": len(seen),
            "transitions_recorded": len(new_rows), "changed": changed,
            "first_sightings": first_sightings, "first_run": first_run,
            "note": ("the first run only takes a baseline — changes are "
                     "recorded from the next poll on" if first_run else "")}


def pitched_events(since: str | None = None) -> dict:
    """MEASURED pitched events: a recorded move INTO a pitched or closed
    stage. Only deals the recorder has watched can produce one."""
    rows = kv_store.get(K_TRANSITIONS) or []
    out = []
    for r in rows:
        to = (r.get("to") or "").strip().lower().lstrip("✅ ").strip()
        if not any(p in to for p in PITCHED_STAGES + CLOSED_STAGES):
            continue
        if since and str(r.get("first_seen", ""))[:10] < since:
            continue
        out.append(r)
    return {"events": out, "count": len(out), "since": since or started_at(),
            "basis": "measured — a recorded move into a pitched or closed stage"}


def watched_contacts() -> set:
    """Contacts whose deals the recorder has watched from the start — the
    cohort whose pitched count is measured rather than a lower bound."""
    seen = kv_store.get(K_SEEN) or {}
    ids = set()
    try:
        import ghl_mirror
        by_id = {o.get("id"): o.get("contact_id")
                 for o in (ghl_mirror.read_opportunities(open_only=False) or [])}
        for oid in seen:
            cid = by_id.get(oid)
            if cid:
                ids.add(cid)
    except Exception:
        pass
    return ids


def velocity(min_n: int = 8) -> dict:
    """Days between observed stages — the compass can adopt this as a
    measured lag once there is enough of it. Labelled until then."""
    import datetime as dt
    rows = kv_store.get(K_TRANSITIONS) or []
    by_opp: dict = {}
    for r in rows:
        by_opp.setdefault(r["opportunity_id"], []).append(r)
    legs: dict = {}
    for oid, rs in by_opp.items():
        rs = sorted(rs, key=lambda x: x.get("first_seen") or "")
        for a, b in zip(rs, rs[1:]):
            if not a.get("to") or not b.get("to"):
                continue
            try:
                d0 = dt.datetime.fromisoformat(a["first_seen"])
                d1 = dt.datetime.fromisoformat(b["first_seen"])
            except Exception:
                continue
            key = f"{a['to']} → {b['to']}"
            legs.setdefault(key, []).append((d1 - d0).total_seconds() / 86400)
    summary = {k: {"days_median": round(sorted(v)[len(v) // 2], 1), "n": len(v)}
               for k, v in legs.items() if len(v) >= 2}
    usable = {k: v for k, v in summary.items() if v["n"] >= min_n}
    return {"legs": summary, "usable_for_the_model": usable,
            "note": ("not enough history yet to feed the model — it keeps "
                     "using the measured close lag from the tracker"
                     if not usable else
                     "enough history to offer the model a measured lag "
                     "(labelled when used)")}


def tick() -> dict:
    """Rides the scheduled loop — same cadence as everything else, no new
    polling of the CRM."""
    try:
        return record_poll()
    except Exception as e:  # noqa: BLE001
        logger.warning("stage recorder tick failed: %s", e)
        return {"ok": False, "reason": str(e)[:150]}
