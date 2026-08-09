"""
ads_truth.py
------------
THE ADS TRUTH LOOP (ADS_TRUTH_DIAGNOSIS → DECISIONS #126): the standing machinery
that keeps every /ads number provably true without anyone asking.

  · SPINE CENSUS (I9): every close implies an upstream conversation. Sourcing
    order T1 tracker (authoritative) → T2 GHL appointment (deterministic,
    auto-derived, journaled, reversible) → T3 call/notes evidence (PROPOSED lane,
    Rydel confirms) → T0 nothing (HUMAN lane — a phantom close is a data
    emergency, S1 in the feed). Derivations emit Piolo-queue items so tracker
    gaps get fixed at SOURCE, never silently patched forever.
  · REACHED SWEEP (Gate 2 Option A): deterministic GHL contact evidence for
    qualified leads with no tracker set/show — connected call ≥ reached_call_
    seconds or a two-way thread → kv reached:evidence {contact_id: evidence}.
    Incremental, rate-capped, journaled. The engine reads the cache only.
  · QUAD-CHECK: four independent reads per fact (render/rollup · engine
    recompute · GHL re-derivation · tracker rows) — agreement demanded,
    disagreement SURFACED with cause, never reconciled silently.
  · NIGHTLY SWEEP: invariants + quad-check on all ≤90d closes + K random cells;
    accuracy row appended (kv ads_truth:accuracy); disagreements → feed lanes
    (close-level or ≥$1k → ACTION); NEW cause classes auto-file a PROPOSED
    regression-test skeleton. If the sweep itself fails, THAT surfaces too.

Read-only against GHL and the tracker. One engine: every count here is read from
attribution_engine.compute() or raw sources for cross-checking — never a third
computation of a rendered metric.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KV_ACCURACY = "ads_truth:accuracy"      # capped list of nightly rows
_KV_CAUSES = "ads_truth:causes"          # known disagreement cause classes
_KV_PROPOSED = "ads_truth:proposed"      # T3 spine cards + auto-filed test skeletons
_KV_SPINE = "spine:events"               # derived events the engine counts (provenance)
_KV_REACHED = "reached:evidence"         # {contact_id: {kind, detail, ts, provenance}}
_KV_TICK = "ads_truth:sweep_tick"
_KV_SWEEP_ERROR = "ads_truth:sweep_error"

REACHED_CALL_SECONDS = 60    # config-surfaced (Gate 2); connected call ≥ this = reached
SET_CALL_SECONDS = 120       # T3 threshold: a call this long evidences a conversation
K_RANDOM_CELLS = 25

# GHL appointment statuses treated as a kept/держана conversation. The RAW status is
# always recorded in evidence; unknown statuses are surfaced, never guessed.
_APPT_KEPT = {"confirmed", "showed", "completed"}


def _norm(s):
    return re.sub(r"[^a-z0-9 @.]", "", str(s or "").lower()).strip()


def _journal(action: str, detail: str) -> None:
    try:
        import resolution
        resolution.log_autofix(action, detail)   # ONE journal (the resolution engine's)
    except Exception:
        pass


def _leads_index(leads_all: list[dict]) -> dict:
    """norm → the BEST tracker row for close-matching: prefer the WON row (duplicate
    names exist — a naive last-write-wins map produced 3 false 'no tracker won row'
    CRITICALs + 1 false phantom on the first live sweep, 2026-08-07)."""
    idx: dict = {}
    for l in leads_all:
        cur = idx.get(l["name_norm"])
        if cur is None or (l.get("won") and not cur.get("won")):
            idx[l["name_norm"]] = l
    return idx


def _dedup_proposed(items: list[dict]) -> list[dict]:
    """The proposed queue is append-across-runs; a cap-trim can forget an id and
    re-append it (found live 2026-08-08: setdate:multi:lucas reid ×2). Dedup by
    id, first occurrence wins — excluded ≠ deleted, but never listed twice."""
    seen: set = set()
    out = []
    for p in items or []:
        pid = p.get("id")
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        out.append(p)
    return out


def _publish_flags(flags: list[dict]) -> None:
    """The sweep's OWN kv channel (attr:data_quality_flags is overwritten by every
    engine compute — findings there would silently vanish). REBUILT each sweep:
    a fixed cause self-retires."""
    import kv_store
    kv_store.put("ads_truth:flags", flags[-60:])


# ── GHL evidence readers (read-only, existing token) ─────────────────────────

def _ghl_get(path: str, params: dict | None = None):
    import requests
    from config import GHL_API_KEY, GHL_BASE
    r = requests.get(f"{GHL_BASE}{path}",
                     headers={"Authorization": f"Bearer {GHL_API_KEY}",
                              "Version": "2021-07-28"},
                     params=params or {}, timeout=(5, 20))
    return r


def contact_appointments(contact_id: str) -> list[dict]:
    try:
        r = _ghl_get(f"/contacts/{contact_id}/appointments")
        if r.status_code != 200:
            return []
        return (r.json() or {}).get("events") or []
    except Exception as e:
        logger.info("appointments read failed: %s", e)
        return []


# ── SPINE CENSUS (I9) ────────────────────────────────────────────────────────

def spine_census(days: int = 90) -> dict:
    """Every close's evidence lane. T1 needs no API; T2/T3 read GHL only for the
    closes T1 misses (18/18 were T1 at the 2026-08-07 baseline)."""
    import attribution_engine as AE
    import kv_store
    from helpers import today_sydney
    r = AE.compute(days=days, basis="activity")
    leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
    by_norm = _leads_index(leads_all)
    contacts_by_norm = {}
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("name"):
                contacts_by_norm.setdefault(_norm(c["name"]), c)
    except Exception:
        pass

    lanes = {"T1": [], "T2": [], "T3": [], "T0": []}
    derived = kv_store.get(_KV_SPINE) or []
    proposed = kv_store.get(_KV_PROPOSED) or []
    known_prop = {p.get("id") for p in proposed}
    for c in r["creatives"]:
        for dl in c.get("deals") or []:
            nm = _norm(dl["name"])
            lead = by_norm.get(nm)
            if lead and (lead.get("set") or lead.get("set_date")) and lead.get("show"):
                lanes["T1"].append(dl["name"])
                continue
            # T2: a GHL appointment object, contact ID exact
            contact = contacts_by_norm.get(nm)
            appts = contact_appointments(contact["id"]) if contact else []
            kept = [a for a in appts
                    if str(a.get("appointmentStatus") or a.get("status") or ""
                           ).lower() in _APPT_KEPT]
            if kept:
                lanes["T2"].append(dl["name"])
                ev = {"name_norm": nm, "kind": "set",
                      "provenance": "derived:ghl-appointment",
                      "evidence": {"appointment_id": kept[0].get("id"),
                                   "raw_status": kept[0].get("appointmentStatus")
                                   or kept[0].get("status"),
                                   "contact_id": contact["id"]},
                      "ts": str(today_sydney())}
                if not any(e.get("name_norm") == nm and e.get("kind") == "set"
                           for e in derived):
                    derived.append(ev)
                    derived.append({**ev, "kind": "show"})
                    import resolution as _res
                    _res.bump_derived_epoch(f"spine set+show for {nm}")   # F6
                    _journal("T2 spine derivation",
                             f"set+show derived for close '{dl['name']}' from GHL "
                             f"appointment {kept[0].get('id')} (status "
                             f"{ev['evidence']['raw_status']})")
                    _piolo_item(dl["name"], contact["id"], "appointment")
            elif contact:
                # T3: notes/call evidence without an appointment → PROPOSED, Rydel rules
                pid = f"spine:T3:{nm}"
                if pid not in known_prop:
                    proposed.append({"id": pid, "kind": "T3_spine",
                                     "close": dl["name"], "contact_id": contact["id"],
                                     "ask": ("close has no tracker set and no GHL "
                                             "appointment — confirm a conversation "
                                             "happened to derive set/show, or fix the "
                                             "tracker row")})
                lanes["T3"].append(dl["name"])
            else:
                lanes["T0"].append(dl["name"])
                _flag_phantom(dl["name"], c.get("label"))
    kv_store.put(_KV_SPINE, derived[-200:])
    kv_store.put(_KV_PROPOSED, _dedup_proposed(proposed)[-40:])
    return {"days": days, "counts": {k: len(v) for k, v in lanes.items()},
            "lanes": lanes, "total": sum(len(v) for v in lanes.values())}


def _piolo_item(name: str, contact_id: str, evidence_kind: str) -> None:
    """Tracker hygiene loop: a derivation means the tracker is missing the event —
    fix at source, don't patch silently forever. Lives on the sweep's own channel
    (rebuilt per run → self-retiring when the tracker gets fixed)."""
    try:
        import kv_store
        flags = kv_store.get("ads_truth:flags") or []
        reason = (f"tracker missing set for {name} — GHL {evidence_kind} evidence "
                  f"exists (contact {contact_id}); fill the Set cell at source")
        if not any(f.get("reason") == reason for f in flags):
            flags.append({"metric": "tracker_missing_set", "reason": reason})
            kv_store.put("ads_truth:flags", flags[-60:])
    except Exception:
        pass


def _flag_phantom(name: str, creative: str) -> None:
    """T0: a close with ZERO evidence anywhere — a data emergency, S1-loud."""
    try:
        import kv_store
        pending = kv_store.get("integrity:pending") or []
        pid = f"integrity:phantom_close:{_norm(name)}"
        if not any(p.get("id") == pid for p in pending):
            pending.append({"id": pid,
                            "detail": f"PHANTOM CLOSE: '{name}' under {creative} has no "
                                      f"tracker lead, no GHL contact, no evidence anywhere",
                            "fix": "verify the deal is real; fix the tracker row or the join"})
            kv_store.put("integrity:pending", pending[-40:])
    except Exception:
        pass


# ── REACHED SWEEP (Gate 2 Option A — incremental, rate-capped) ───────────────

def reached_sweep(max_contacts: int = 30) -> dict:
    """Populate kv reached:evidence for qualified leads with NO tracker evidence,
    via GHL appointments (any kept status implies contact). Incremental — a few
    dozen contacts per night; the engine only ever reads the cache."""
    import attribution_engine as AE
    import kv_store
    from helpers import today_sydney
    cache = kv_store.get(_KV_REACHED) or {}          # POSITIVE evidence only
    swept_none = kv_store.get(_KV_REACHED + ":none") or {}   # negatives (skip re-checks)
    r = AE.compute(days=3650, basis="cohort")
    todo = []
    contacts_by_norm = {}
    valid_ids: set = set()
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("id"):
                valid_ids.add(c["id"])
            if c.get("name"):
                contacts_by_norm.setdefault(_norm(c["name"]), c)
    except Exception:
        return {"checked": 0, "found": 0, "reason": "contacts unavailable"}
    # F7 — CONTACT-MERGE DROOP: a GHL merge deletes the old contact id; its
    # cached reached-evidence entry then vouches for a ghost while the NEW id
    # waits its turn in the 40/night queue. Prune ids no longer in the contact
    # table (journaled) so the re-check happens THIS sweep, not eventually.
    pruned = [cid for cid in list(cache) if cid not in valid_ids] if valid_ids else []
    for cid in pruned:
        cache.pop(cid, None)
    for cid in ([c for c in list(swept_none) if c not in valid_ids] if valid_ids else []):
        swept_none.pop(cid, None)
    if pruned:
        _journal("reached derivation prune (F7)",
                 f"{len(pruned)} cached reached id(s) no longer exist in GHL "
                 f"(contact merge/delete) — pruned; evidence re-checks this sweep")
    for row in (r.get("rows") or []):
        if not row.get("qualified") or row.get("set") or row.get("show") \
                or row.get("close_date") or row.get("reached"):
            continue
        c = contacts_by_norm.get(_norm(row["name"]))
        if c and c["id"] not in cache and c["id"] not in swept_none:
            todo.append((row["name"], c["id"]))
    checked = found = 0
    for name, cid in todo[:max_contacts]:
        checked += 1
        appts = contact_appointments(cid)
        if appts:
            cache[cid] = {"kind": "ghl-appointment", "detail": f"{len(appts)} appointment(s)",
                          "provenance": "derived:ghl-appointment",
                          "ts": str(today_sydney())}
            found += 1
            _journal("reached derivation",
                     f"'{name}' marked reached — GHL appointment evidence ({cid})")
        else:
            swept_none[cid] = {"ts": str(today_sydney())}
    kv_store.put(_KV_REACHED, cache)                 # engine reads keys = positives only
    kv_store.put(_KV_REACHED + ":none", swept_none)
    if found or pruned:
        import resolution as _res
        _res.bump_derived_epoch(f"reached evidence ×{found}, pruned ×{len(pruned)}")  # F6/F7
    return {"checked": checked, "found": found, "remaining": max(0, len(todo) - checked)}


# ── FULL-FUNNEL EVENT SWEEP (DECISIONS #128 — widen from the close spine) ────

_KV_APPT_CACHE = "ghl:appt_cache"   # {contact_id: {ts, appts:[...]}} — 7d TTL
_APPT_TTL_DAYS = 7


def _cached_appointments(contact_id: str) -> list[dict]:
    """Batched/cached GHL appointment reads — never a full-location crawl."""
    import kv_store
    from helpers import today_sydney
    cache = kv_store.get(_KV_APPT_CACHE) or {}
    hit = cache.get(contact_id)
    today = str(today_sydney())
    if hit and (today <= str(hit.get("expires") or "")):
        return hit.get("appts") or []
    appts = contact_appointments(contact_id)
    import datetime as dt
    kept = [{k: a.get(k) for k in
             ("id", "dateAdded", "startTime", "appointmentStatus",
              "status", "calendarId")} for a in appts[:6]]
    # #134 (triple-sweep, the Matt Annenberg catch): an UPCOMING appointment is
    # the mutable class — it can be cancelled/rebooked after caching, and a 7d
    # TTL let a cancelled consult render as "upcoming" for days. Entries
    # carrying any not-yet-past startTime expire DAILY; past-only entries keep
    # the 7d TTL (history doesn't change). startTime is location-local — the
    # ISO-prefix string compare against the Sydney day is exact.
    has_upcoming = any(str(a.get("startTime") or "")[:10] >= today for a in kept)
    ttl = 1 if has_upcoming else _APPT_TTL_DAYS
    cache[contact_id] = {"expires": str(today_sydney() + dt.timedelta(days=ttl)),
                         "appts": kept}
    # cap the cache footprint
    if len(cache) > 800:
        cache = dict(list(cache.items())[-600:])
    kv_store.put(_KV_APPT_CACHE, cache)
    return cache[contact_id]["appts"]


def _date_of(v) -> str | None:
    """F8: the SYDNEY day of a GHL timestamp — never the UTC slice. The old
    `str(v)[:10]` derived a booking before ~10am Sydney onto the previous day
    (today_sydney doctrine violation at the derivation boundary, drill B9)."""
    from helpers import sydney_day
    d = sydney_day(v)
    return str(d) if d else None


def event_sweep(max_contacts: int = 40) -> dict:
    """Derive set/show DATES per the encoded conventions (#128):
      set  = the appointment's BOOKED date (dateAdded) — setter action.
      show = the appointment's SCHEDULED date, requiring kept-status evidence.
    Scope: attributed leads whose tracker set has NO date (the 122-strong dateless
    class) — single unambiguous appointment → AUTO; multiple → PROPOSED lane.
    Batched + cached + incremental; GHL calls counted and reported."""
    import attribution_engine as AE
    import kv_store
    import resolution
    r = AE.compute(days=3650, basis="cohort")
    contacts_by_norm = {}
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("name"):
                contacts_by_norm.setdefault(_norm(c["name"]), c)
    except Exception:
        return {"skipped": "contacts unavailable"}
    already = resolution.derived_dates()
    proposed = kv_store.get(_KV_PROPOSED) or []
    known_prop = {p.get("id") for p in proposed}
    todo = []
    for v in (r.get("rows") or []):
        nm = _norm(v["name"])
        if v.get("set") and not v.get("set_date") and not (already.get(nm) or {}).get("set_date"):
            c = contacts_by_norm.get(nm)
            if c:
                todo.append((nm, v["name"], c["id"]))
    calls = derived = prop_n = 0
    for nm, name, cid in todo[:max_contacts]:
        appts = _cached_appointments(cid)
        calls += 1
        if not appts:
            continue
        if len(appts) == 1:
            a = appts[0]
            import consult_schedule
            # #134 tz truth: appointment-endpoint stamps are LOCATION-LOCAL —
            # source-aware day, never the naive=UTC path (the F8-appt class)
            booked = consult_schedule.appt_day(a.get("dateAdded"))
            if booked and resolution.record_derived_date(
                    nm, "set_date", booked, "derived:ghl-appt",
                    {"appointment_id": a.get("id"), "contact_id": cid,
                     "raw_status": a.get("appointmentStatus") or a.get("status")}):
                derived += 1
                status = str(a.get("appointmentStatus") or a.get("status") or "").lower()
                sched = consult_schedule.appt_day(a.get("startTime"))
                if sched and status in _APPT_KEPT:
                    resolution.record_derived_date(
                        nm, "show_date", sched, "derived:ghl-appt",
                        {"appointment_id": a.get("id"), "contact_id": cid,
                         "raw_status": status})
        else:
            pid = f"setdate:multi:{nm}"
            if pid not in known_prop:
                proposed.append({"id": pid, "kind": "set_date_candidates",
                                 "close": name, "contact_id": cid,
                                 "candidates": [{"appointment_id": a.get("id"),
                                                 "booked": __import__("consult_schedule").appt_day(a.get("dateAdded")),
                                                 "start": __import__("consult_schedule").appt_day(a.get("startTime")),
                                                 "status": a.get("appointmentStatus") or a.get("status")}
                                                for a in appts],
                                 "ask": "multiple appointments — pick the set call"})
                prop_n += 1
    kv_store.put(_KV_PROPOSED, _dedup_proposed(proposed)[-60:])
    return {"ghl_calls": calls, "derived_set_dates": derived,
            "proposed_multi": prop_n, "remaining": max(0, len(todo) - max_contacts)}


# ── SHOW VERIFICATION (SHOW TRUTH, DECISIONS #129) ───────────────────────────
# Attendance requires EVIDENCE, not the absence of a noshow flag. Live GHL
# vocabulary has NO completed/showed status — a kept-status "show" is a guess.
# Tiers: VERIFIED (call ≥ set_call_seconds on/after the scheduled date, ID-exact
# contact — or a downstream CLOSE: nobody closes without the conversation) ·
# UNVERIFIED (status only — counted separately, PROPOSED card each) ·
# NOT-A-SHOW (cancelled/invalid/noshow — set only, unchanged).
# D1 baseline 2026-08-08: 18/19 derived shows were status-only (the inflation
# bound); D2: call records cover 86% of known-real conversations.

_KV_CONV_CACHE = "ghl:call_cache"   # {contact_id: {expires, calls:[{id,duration,date}]}}


def contact_calls(contact_id: str) -> list[dict]:
    """Call-type messages (type 1, meta.call) for a contact — batched, cached 7d."""
    import kv_store
    from helpers import today_sydney
    import datetime as dt
    cache = kv_store.get(_KV_CONV_CACHE) or {}
    hit = cache.get(contact_id)
    if hit and str(today_sydney()) <= str(hit.get("expires") or ""):
        return hit.get("calls") or []
    calls = []
    try:
        r = _ghl_get("/conversations/search",
                     {"locationId": __import__("config").GHL_LOCATION_ID,
                      "contactId": contact_id})
        if r.status_code == 200:
            for conv in (r.json() or {}).get("conversations", [])[:3]:
                r2 = _ghl_get(f"/conversations/{conv['id']}/messages", {"limit": 100})
                if r2.status_code != 200:
                    continue
                msgs = ((r2.json() or {}).get("messages") or {}).get("messages") or []
                for m in msgs:
                    if m.get("type") == 1 or "call" in str(m.get("messageType", "")).lower():
                        meta = (m.get("meta") or {}).get("call") or {}
                        calls.append({"id": m.get("id"),
                                      "duration": meta.get("duration"),
                                      "status": meta.get("status"),
                                      "date": _date_of(m.get("dateAdded"))})  # F8: Sydney day
    except Exception as e:
        logger.info("contact_calls failed: %s", e)
    cache[contact_id] = {"expires": str(today_sydney() + dt.timedelta(days=7)),
                         "calls": calls[:20]}
    if len(cache) > 800:
        cache = dict(list(cache.items())[-600:])
    kv_store.put(_KV_CONV_CACHE, cache)
    return calls


def show_verification_pass(max_contacts: int = 40) -> dict:
    """Classify every derived show: outcome-evidenced → call-evidenced → unverified
    (PROPOSED card, near-miss call shown as context). Later call records upgrade
    UNVERIFIED → VERIFIED automatically (journaled, a quiet positive). Idempotent."""
    import attribution_engine as AE
    import kv_store
    import resolution
    try:
        import manual_targets
        min_s = float((manual_targets.get_resolved() or {}).get("set_call_seconds") or 120)
    except Exception:
        min_s = 120.0
    store = resolution.derived_dates()
    r_all = AE.compute(days=3650, basis="cohort")
    closed_norms = set()
    for c in r_all["creatives"]:
        for dl in c.get("deals") or []:
            closed_norms.add(_norm(dl["name"]))
    # TRACKER AUTHORITY: a row the setter explicitly marked "Showed" IS attendance —
    # questioning it would invert the authority doctrine. Verified, no card.
    tracker_showed = set()
    try:
        leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
        tracker_showed = {l["name_norm"] for l in leads_all if l.get("show")}
    except Exception:
        pass
    proposed = kv_store.get(_KV_PROPOSED) or []
    known_prop = {p.get("id") for p in proposed}
    out = {"checked": 0, "verified_outcome": 0, "verified_call": 0,
           "unverified": 0, "upgraded": 0, "ghl_calls": 0}
    changed = False
    for nm, v in list(store.items()):
        e = v.get("show_date")
        if not e:
            continue
        cur = (e.get("verification") or {}).get("state")
        if cur == "verified":
            continue
        if out["checked"] >= max_contacts:
            break
        out["checked"] += 1
        if nm in closed_norms:
            e["verification"] = {"state": "verified", "via": "show:outcome-evidenced"}
            _journal("show verified (outcome)",
                     f"{nm}: closed downstream of the appointment — attendance proven")
            out["verified_outcome"] += 1
            changed = True
            if cur == "unverified":
                out["upgraded"] += 1
            continue
        if nm in tracker_showed:
            e["verification"] = {"state": "verified", "via": "show:tracker-authority"}
            out["verified_tracker"] = out.get("verified_tracker", 0) + 1
            changed = True
            # a stale attendance card for a tracker-Showed lead is noise — retire it
            proposed = [p for p in proposed if p.get("id") != f"attendance:{nm}"]
            known_prop.discard(f"attendance:{nm}")
            continue
        cid = (e.get("evidence") or {}).get("contact_id")
        calls = contact_calls(cid) if cid else []
        out["ghl_calls"] += 1
        hit = next((c for c in calls
                    if isinstance(c.get("duration"), (int, float))
                    and c["duration"] >= min_s
                    and c.get("date") and c["date"] >= e["date"]), None)
        if hit:
            e["verification"] = {"state": "verified", "via": "show:call-evidenced",
                                 "call": hit}
            _journal("show verified (call)",
                     f"{nm}: call {hit['id']} {hit['duration']}s on {hit['date']} "
                     f"≥ scheduled {e['date']}")
            out["verified_call"] += 1
            if cur == "unverified":
                out["upgraded"] += 1
                _quiet_positive(f"show upgraded to VERIFIED: {nm} — call evidence landed")
            changed = True
        else:
            near = max((c for c in calls if isinstance(c.get("duration"), (int, float))),
                       key=lambda c: c["duration"], default=None)
            e["verification"] = {"state": "unverified", "via": "status-only",
                                 "near_miss": near}
            out["unverified"] += 1
            changed = True
            pid = f"attendance:{nm}"
            if pid not in known_prop:
                ctx = (f" (context: a {near['duration']}s call on {near['date']} — "
                       f"before the scheduled date)" if near else " (no call record found)")
                proposed.append({"id": pid, "kind": "attendance",
                                 "close": nm, "contact_id": cid,
                                 "ask": f"confirm attendance for {nm}{ctx}"})
                known_prop.add(pid)
    if changed:
        import kv_store as _kv
        _kv.put("derived:dates", store)
        resolution.bump_derived_epoch("show verification pass")   # F6
    kv_store.put(_KV_PROPOSED, _dedup_proposed(proposed)[-80:])
    return out


def _quiet_positive(msg: str) -> None:
    try:
        import kv_store
        flags = kv_store.get("ads_truth:flags") or []
        flags.append({"metric": "ads_truth_positive", "reason": msg})
        kv_store.put("ads_truth:flags", flags[-60:])
    except Exception:
        pass


_CONFIRM_ATT_RE = re.compile(r"confirm attendance for (.+)", re.I)


def handle_confirm_attendance(text: str) -> tuple[str | None, bool]:
    """Rydel converts an UNVERIFIED show on his word — journaled, provenance
    'show:rydel-confirmed'."""
    m = _CONFIRM_ATT_RE.match((text or "").strip())
    if not m:
        return None, False
    frag = m.group(1).strip().lower()
    import resolution
    import kv_store
    store = resolution.derived_dates()
    hits = [nm for nm, v in store.items()
            if "show_date" in v and frag in nm
            and (v["show_date"].get("verification") or {}).get("state") != "verified"]
    if len(hits) != 1:
        return (f"{len(hits)} unverified show(s) match '{frag}' — give me a fragment "
                f"matching exactly one.", True)
    nm = hits[0]
    store[nm]["show_date"]["verification"] = {"state": "verified",
                                              "via": "show:rydel-confirmed"}
    kv_store.put("derived:dates", store)
    resolution.bump_derived_epoch(f"attendance confirmed for {nm}")   # F6
    _journal("show verified (Rydel)", f"{nm}: attendance confirmed by Rydel")
    proposed = [p for p in (kv_store.get(_KV_PROPOSED) or [])
                if p.get("id") != f"attendance:{nm}"]
    kv_store.put(_KV_PROPOSED, proposed)
    return f"Attendance confirmed for {nm} — the show now counts as VERIFIED (journaled).", True


# ── QUAD-CHECK ───────────────────────────────────────────────────────────────

def quad_check(days: int = 90, sample_cells: int = 0) -> dict:
    """Four reads per close fact: (1) the served rollup/board, (2) a fresh engine
    recompute, (3) GHL re-derivation (contact + won-stage as the VALIDATOR — its
    dead lane is a KNOWN standing cause, surfaced not absorbed), (4) tracker rows.
    Returns the truth table; disagreements carry causes."""
    import attribution_engine as AE
    import kv_store
    facts = []
    # (1) the served board (rollup — what the dashboard renders)
    stored = (kv_store.get(f"attr:rollup:activity:{days}") or {}).get("board") or {}
    board_rows = {r["creative_key"]: r for r in
                  ((stored.get("scoreboard") or {}).get("rows") or [])}
    # (2) fresh recompute
    r2 = AE.compute(days=days, basis="activity", force=True)
    # (4) tracker (won-preferring index — duplicate names never read as missing)
    leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
    by_norm = _leads_index(leads_all)
    # (3) GHL mirror won-stage per contact
    won_contacts = set()
    try:
        import db
        if db.db_configured():
            with db.get_conn() as conn:
                for row in conn.execute("SELECT contact_id FROM ghl_opportunities "
                                        "WHERE status = 'won' AND deleted = FALSE").fetchall():
                    won_contacts.add(row["contact_id"])
    except Exception:
        pass
    contacts_by_norm = {}
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("name"):
                contacts_by_norm.setdefault(_norm(c["name"]), c)
    except Exception:
        pass

    agreements = disagreements = 0
    for c in r2["creatives"]:
        for dl in c.get("deals") or []:
            nm = _norm(dl["name"])
            lead = by_norm.get(nm)
            board_row = board_rows.get(c["creative_key"])
            contact = contacts_by_norm.get(nm)
            reads = {
                "board_close_counted": bool(board_row and board_row.get("closes", 0) > 0)
                if board_row is not None else None,
                "engine_close": True,
                "tracker_won_row": bool(lead and lead.get("won")),
                "ghl_won_stage": (contact["id"] in won_contacts) if contact else None,
            }
            causes = []
            if reads["board_close_counted"] is False:
                causes.append("board rollup stale or row absent — refresh path")
            if not reads["tracker_won_row"]:
                causes.append("no tracker won row — CRITICAL (authority missing)")
            if reads["ghl_won_stage"] is False:
                causes.append("GHL closed-won lane dead (KNOWN standing cause — "
                              "ops rule stands; validator, not authority)")
            elif reads["ghl_won_stage"] is None:
                causes.append("no GHL contact match — join gap (validator unavailable)")
            core_ok = reads["engine_close"] and reads["tracker_won_row"]
            if core_ok and not causes:
                agreements += 1
            elif core_ok and all(("KNOWN standing" in x) or ("rollup stale" in x)
                                 or ("join gap" in x) for x in causes):
                agreements += 1   # agreement on authority; validator gaps SURFACED
            else:
                disagreements += 1
            facts.append({"close": dl["name"], "creative": c["label"][:40],
                          "cash": dl["cash"], "reads": reads, "causes": causes})
    return {"days": days, "facts": len(facts), "agreements": agreements,
            "hard_disagreements": disagreements, "table": facts}


# ── #133 SENTINEL WATCHES: launch-field freshness + clock-label integrity ────

def launch_freshness_check(out: dict) -> None:
    """The durable lineage store must keep up with the spend store (a lagging
    merge silently ages every "launched / N active days" surface), and pending
    lifetime probes must not persist across nights (an unprobed censored ad
    shows "on or before" forever — honest but unfinished). Appends
    kind=launch_freshness disagreements; never raises."""
    import kv_store
    try:
        import launch_lineage
        import meta_entities
        st_ads = (launch_lineage._load().get("ads")) or {}
        pend = sum(1 for r2 in st_ads.values()
                   if r2.get("censored") and not r2.get("lifetime_probed"))
        missing_days = 0
        for dday, admap in ((meta_entities._load_json(meta_entities.AD_SPEND_STORE)
                             .get("days")) or {}).items():
            for aid, rrow in (admap or {}).items():
                if launch_lineage._delivered(rrow):
                    rec = st_ads.get(aid)
                    if not rec or dday not in (rec.get("delivery_days") or []):
                        missing_days += 1
        out["launch_lineage"] = {"ads": len(st_ads), "pending_probes": pend,
                                 "missing_day_entries": missing_days}
        if missing_days:
            out["disagreements"].append({
                "kind": "launch_freshness",
                "cause": (f"launch lineage store lags the spend store by "
                          f"{missing_days} delivered day-entr"
                          f"{'y' if missing_days == 1 else 'ies'} — refresh() is "
                          f"not keeping up; launched/active-days surfaces are ageing"),
                "where": "launch_lineage vs meta_ad_spend_daily"})
        prev = kv_store.get("launch:pending_prev") or {}
        if pend and prev.get("count") and prev.get("date") != out.get("date"):
            out["disagreements"].append({
                "kind": "launch_freshness",
                "cause": (f"{pend} lifetime launch probe(s) still pending since "
                          f"{prev.get('date')} — those ads show 'launched on or "
                          f"before' instead of an exact day (probe blocked?)"),
                "where": "launch_lineage pending probes"})
        kv_store.put("launch:pending_prev", {"date": out.get("date"), "count": pend})
    except Exception as e:
        out["launch_lineage"] = {"error": str(e)[:80]}


def clock_label_check(out: dict) -> None:
    """A sampled custom range must echo its clock (basis), carry the human label
    the UI renders, echo its exact box, and the I11 guard must still refuse
    cross-clock math. Drift here = the date control could render a mislabelled
    clock (the two-clock contamination class). Appends kind=clock_label
    disagreements (ACTION-promoted); never raises."""
    import attribution_engine as AE
    from helpers import today_sydney
    try:
        import datetime as _dt
        cw1 = today_sydney() - _dt.timedelta(days=1)
        cw0 = cw1 - _dt.timedelta(days=6)
        probs = []
        legs = {}
        for basis in ("cohort", "activity"):
            rr = AE.compute(start=str(cw0), end=str(cw1), basis=basis)
            legs[basis] = rr
            if rr.get("basis") != basis:
                probs.append(f"{basis}: engine echoed basis={rr.get('basis')!r}")
            if not rr.get("basis_label"):
                probs.append(f"{basis}: basis_label missing — the UI would render "
                             f"an unlabelled clock")
            ww = rr.get("window") or {}
            if str(ww.get("start")) != str(cw0) or str(ww.get("end")) != str(cw1):
                probs.append(f"{basis}: window echo {ww.get('start')}..{ww.get('end')} "
                             f"!= requested {cw0}..{cw1}")
        try:
            AE.assert_same_basis(legs["cohort"], legs["activity"])
            probs.append("I11 guard FAILED to raise on a cross-clock mix")
        except ValueError:
            pass
        out["clock_label"] = {"ok": not probs, "range": f"{cw0}..{cw1}",
                              "problems": probs}
        for p in probs:
            out["disagreements"].append({"kind": "clock_label",
                                         "cause": f"range clock-label integrity: {p}",
                                         "where": f"{cw0}..{cw1}"})
    except Exception as e:
        out["clock_label"] = {"error": str(e)[:80]}


def consult_freshness_check(out: dict) -> None:
    """#134 sentinel watch: the consult-datetime surface must not silently rot.
    Coverage = set-leads (last 60d) whose GHL contact has an appointment-cache
    entry; unfetched contacts PERSISTING across nights (the warm passes should
    converge them to zero) flag as a disagreement. Never raises."""
    import kv_store
    try:
        import attribution_engine as AE
        import attribution_join
        import consult_schedule
        import datetime as _dt
        from helpers import today_sydney
        cache = consult_schedule._cache()
        leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
        by_email = {}
        by_name = {}
        for c in attribution_join.load_contacts():
            if c.get("email"):
                by_email.setdefault(c["email"], c)
            if c.get("name"):
                by_name.setdefault(_norm(c["name"]), c)
        floor = today_sydney() - _dt.timedelta(days=60)
        want = unfetched = tracker_only = 0
        for l in leads_all:
            if not l.get("set"):
                continue
            ld = l.get("set_date") or l.get("input_date")
            if not ld or ld < floor:
                continue
            want += 1
            c = by_email.get(l["email"]) or by_name.get(l["name_norm"])
            if not c:
                tracker_only += 1
            elif c.get("id") not in cache:
                unfetched += 1
        out["consult_freshness"] = {"set_leads_60d": want, "unfetched": unfetched,
                                    "tracker_only": tracker_only}
        prev = kv_store.get("consult:unfetched_prev") or {}
        if unfetched and prev.get("count") and prev.get("date") != out.get("date"):
            out["disagreements"].append({
                "kind": "consult_freshness",
                "cause": (f"{unfetched} set-lead contact(s) still lack an "
                          f"appointment-cache entry since {prev.get('date')} — "
                          f"their roster rows show 'fetch pending' instead of a "
                          f"consult datetime (warm passes not converging)"),
                "where": "ghl:appt_cache coverage, 60d set-leads"})
        kv_store.put("consult:unfetched_prev", {"date": out.get("date"),
                                                "count": unfetched})
    except Exception as e:
        out["consult_freshness"] = {"error": str(e)[:80]}


# ── THE NIGHTLY SWEEP ────────────────────────────────────────────────────────

def integrity_sweep() -> dict:
    """Invariants + spine + quad-check + accuracy row. Called nightly (kv-stamped);
    a sweep failure is itself LOUD (kv flag → action feed). PHASE H: the sweep is
    the sentinel's L2 detection leg — it times itself and its accuracy row
    carries a SENTINEL COST block (runtime + API calls vs budget, auditable)."""
    import time as _time
    _t0 = _time.time()
    import attribution_engine as AE
    import kv_store
    from helpers import today_sydney
    out = {"date": str(today_sydney()), "checks": 0, "agreements": 0,
           "disagreements": [], "invariant_violations": 0}
    # invariants across both clocks × windows (the engine computes them per row)
    live_invariant_ids: set = set()
    for basis in ("cohort", "activity"):
        for d in (30, 60, 90):
            r = AE.compute(days=d, basis=basis)
            bad = [i for i in (r.get("invariants") or []) if not i.get("ok")]
            out["checks"] += 1
            out["invariant_violations"] += len(bad)
            for b in bad:
                live_invariant_ids.add(b.get("id"))
                out["disagreements"].append({"kind": "invariant", "cause": b["detail"],
                                             "where": f"{basis} {d}d"})
    # F3 — SELF-RETIRING INVARIANT ALERTS (the A5 doctrine applied to this class):
    # an integrity:pending entry born from a past transient violation retires
    # (journaled) once no swept clock×window still fails it — the feed shows
    # LIVE state, not history. Mirrors the phantom prune below.
    try:
        pending = kv_store.get("integrity:pending") or []
        stale = [p for p in pending
                 if str(p.get("id", "")).startswith("invariant:")
                 and p["id"] not in live_invariant_ids]
        if stale:
            kv_store.put("integrity:pending",
                         [p for p in pending if p not in stale])
            for p in stale:
                _journal("invariant alert retired (F3)",
                         f"{p['id']}: condition clear on every swept clock×window "
                         f"— self-retired")
            out["invariant_alerts_retired"] = len(stale)
    except Exception as e:
        logger.info("invariant retire pass failed: %s", e)
    # undated sets (the 2026-08-07 class): tracker hygiene rollup, one line
    try:
        r_act90 = AE.compute(days=90, basis="activity")
        undated = sum(c.get("undated_sets", 0) for c in r_act90["creatives"])
        if undated:
            out["disagreements"].append({"kind": "tracker_hygiene",
                                         "cause": f"{undated} closing deal(s) have a set "
                                                  f"with NO Set Date in the tracker — the "
                                                  f"activity clock can't place them",
                                         "where": "activity 90d"})
    except Exception:
        pass
    spine = spine_census(90)
    out["spine"] = spine["counts"]
    if spine["counts"]["T0"]:
        out["disagreements"].append({"kind": "phantom_close",
                                     "cause": f"{spine['counts']['T0']} close(s) with "
                                              f"zero evidence", "where": "spine"})
    qc = quad_check(90)
    out["checks"] += qc["facts"]
    out["agreements"] += qc["agreements"]
    for f in qc["table"]:
        hard = [x for x in f["causes"]
                if "KNOWN standing" not in x and "join gap" not in x
                and "rollup stale" not in x]
        if hard:
            out["disagreements"].append({"kind": "quad", "close": f["close"],
                                         "cash": f["cash"], "cause": "; ".join(hard)})
    try:
        out["reached_sweep"] = reached_sweep()
    except Exception as e:
        out["reached_sweep"] = {"error": str(e)[:80]}
    # #128 additions: (a) the date-resolution pass over new dateless events +
    # supersession processing for source fills; (b) the incremental event sweep
    try:
        import resolution
        out["date_resolution"] = resolution.resolve_dates()
    except Exception as e:
        out["date_resolution"] = {"error": str(e)[:80]}
    try:
        out["event_sweep"] = event_sweep()
    except Exception as e:
        out["event_sweep"] = {"error": str(e)[:80]}
    # #129: attendance verification (later call records upgrade UNVERIFIED →
    # VERIFIED automatically — journaled, surfaced as a quiet positive)
    try:
        out["show_verification"] = show_verification_pass()
    except Exception as e:
        out["show_verification"] = {"error": str(e)[:80]}
    # I17 (ROSTER-CELL EQUALITY) nightly sampling: 20 random cells across both
    # clocks — the rendered number vs the member roster recorded at increment
    # time. Any drift is the old count/detail mismatch class reborn → LOUD.
    try:
        import random
        cells = []
        for basis in ("cohort", "activity"):
            r = AE.compute(days=90, basis=basis)
            for row in (r.get("creatives") or []):
                for m in ("leads", "qualified", "reached", "sets", "shows", "closes"):
                    cells.append((basis, row, m))
        drift = 0
        sample = random.sample(cells, min(20, len(cells)))
        for basis, row, m in sample:
            n = len((row.get("members") or {}).get(m) or [])
            if n != (row.get(m) or 0):
                drift += 1
                out["disagreements"].append({
                    "kind": "i17_roster_drift",
                    "cause": (f"I17: '{row['label'][:40]}' {m} cell={row.get(m)} but "
                              f"roster={n} — count/detail mismatch"),
                    "where": f"{basis} 90d"})
        out["i17_sample"] = {"checked": len(sample), "drift": drift}
    except Exception as e:
        out["i17_sample"] = {"error": str(e)[:80]}

    launch_freshness_check(out)
    clock_label_check(out)
    consult_freshness_check(out)

    # NEW cause classes → auto-file a PROPOSED regression-test skeleton
    causes = kv_store.get(_KV_CAUSES) or {}
    proposed = kv_store.get(_KV_PROPOSED) or []
    for dgg in out["disagreements"]:
        key = re.sub(r"\d+", "N", dgg["cause"])[:80]
        if key not in causes:
            causes[key] = {"first_seen": out["date"], "kind": dgg["kind"]}
            proposed.append({"id": f"test:{len(causes)}", "kind": "regression_test_skeleton",
                             "ask": f"new disagreement cause class seen {out['date']}: "
                                    f"'{dgg['cause']}' — a regression test should pin it",
                             "skeleton": (f"def test_cause_{len(causes)}():\n"
                                          f"    # {dgg['cause']}\n"
                                          f"    assert False  # write the repro")})
    kv_store.put(_KV_CAUSES, causes)
    kv_store.put(_KV_PROPOSED, _dedup_proposed(proposed)[-40:])

    # feed lanes: close-level/≥$1k → ACTION-promoted category; else hygiene.
    # The channel is REBUILT each run (self-retiring); Piolo items survive the run.
    # Ruling-conversion notices (DECISIONS #131) survive 7 days — "notify once"
    # must not mean "wiped by the same sweep that produced it".
    def _keep(f):
        if f.get("metric") == "tracker_missing_set":
            return True
        if "DECISIONS #131" in (f.get("reason") or ""):
            import datetime as _dt
            try:
                age = (today_sydney() - _dt.date.fromisoformat(f.get("date") or "")).days
            except Exception:
                return False
            return age <= 7
        return False
    flags = [f for f in (kv_store.get("ads_truth:flags") or []) if _keep(f)]
    for dgg in out["disagreements"]:
        big = (dgg.get("cash") or 0) >= 1000 or dgg["kind"] in ("phantom_close", "quad",
                                                               "i17_roster_drift",
                                                               "clock_label")
        flags.append({"metric": "ads_truth_action" if big else "ads_truth",
                      "reason": f"ads truth sweep: {dgg['kind']} — {dgg['cause'][:110]}"})
    _publish_flags(flags)
    # prune stale phantom entries (a fixed join no longer haunts the feed)
    live_phantoms = {f"integrity:phantom_close:{_norm(n)}"
                     for n in (spine.get("lanes") or {}).get("T0", [])}
    pending = kv_store.get("integrity:pending") or []
    pending = [p for p in pending
               if not str(p.get("id", "")).startswith("integrity:phantom_close:")
               or p["id"] in live_phantoms]
    kv_store.put("integrity:pending", pending)

    # F11 — ORPHAN DERIVATION CENSUS (drill B15): a derivation whose tracker row
    # was deleted is inert but was immortal + invisible. Counted nightly into a
    # visible bucket (excluded ≠ deleted — nothing is auto-removed; a deliberate
    # tracker deletion is a human's call to mirror).
    try:
        import resolution
        _leads_all = AE.parse_tracker(AE._tracker_rows_clean())[0]
        # BOTH normal forms (review finding 7): resolution._norm strips '@'/'.'
        # while the engine's keeps them — a live "St. Ali"-style lead's derived
        # key would otherwise read as an orphan and invite a wrongful delete.
        tracker_norms = ({l["name_norm"] for l in _leads_all}
                         | {resolution._norm(l["name"]) for l in _leads_all})
        orphans = [nm for nm in (resolution.derived_dates() or {})
                   if nm not in tracker_norms]
        out["orphan_derivations"] = {"count": len(orphans), "names": orphans[:20]}
        if orphans:
            flags = kv_store.get("ads_truth:flags") or []
            flags.append({"metric": "ads_truth",
                          "reason": (f"{len(orphans)} orphan derivation(s) — derived "
                                     f"dates whose tracker row no longer exists "
                                     f"({', '.join(orphans[:5])}) — inert; delete from "
                                     f"the derived store only if the row removal was "
                                     f"deliberate (F11 census)")})
            kv_store.put("ads_truth:flags", flags[-60:])
    except Exception as e:
        out["orphan_derivations"] = {"error": str(e)[:80]}

    # verified-show ratio — the honesty metric for attendance itself
    vsr = None
    try:
        import resolution
        shows = [v["show_date"] for v in resolution.derived_dates().values()
                 if "show_date" in v]
        if shows:
            v_n = sum(1 for s in shows
                      if (s.get("verification") or {}).get("state") == "verified")
            vsr = round(v_n / len(shows), 3)
    except Exception:
        pass
    # SENTINEL COST (Phase H): runtime + external API calls this sweep actually
    # spent, against the L2 budget — cost is auditable data, not a feeling.
    api_calls = 0
    for leg, keys in (("reached_sweep", ("checked",)),
                      ("event_sweep", ("ghl_calls",)),
                      ("show_verification", ("ghl_calls",))):
        for k in keys:
            v = (out.get(leg) or {}).get(k)
            if isinstance(v, (int, float)):
                api_calls += int(v)
    runtime_s = round(_time.time() - _t0, 2)
    sentinel_cost = None
    try:
        from ad_sentinel import BUDGETS
        b = BUDGETS["L2"]
        sentinel_cost = {"layer": "L2", "runtime_s": runtime_s,
                         "api_calls": api_calls, "budget": b,
                         "over_budget": (runtime_s > b["runtime_s"]
                                         or api_calls > b["api_calls"])}
        if sentinel_cost["over_budget"]:
            flags = kv_store.get("ads_truth:flags") or []
            flags.append({"metric": "ads_truth_action",
                          "reason": (f"sentinel: L2 BUDGET BREACH — sweep took "
                                     f"{runtime_s}s / {api_calls} API calls "
                                     f"(budget {b['runtime_s']}s / {b['api_calls']})")})
            kv_store.put("ads_truth:flags", flags[-60:])
        rows_cost = kv_store.get("sentinel:cost") or []
        rows_cost.append({**sentinel_cost, "at": out["date"]})
        kv_store.put("sentinel:cost", rows_cost[-200:])
    except Exception:
        pass
    out["sentinel_cost"] = sentinel_cost
    acc = kv_store.get(_KV_ACCURACY) or []
    row = {"date": out["date"], "facts_checked": out["checks"],
           "agreements": out["agreements"],
           "disagreements": len(out["disagreements"]),
           "invariant_violations": out["invariant_violations"],
           "verified_show_ratio": vsr,
           "sentinel_cost": sentinel_cost,
           "spine": out.get("spine")}
    # F16 idempotent guard: ONE accuracy row per day, last write wins — a retry
    # (or any residual race) can never double the history again
    acc = [r for r in acc if r.get("date") != out["date"]] + [row]
    kv_store.put(_KV_ACCURACY, acc[-90:])
    kv_store.delete(_KV_SWEEP_ERROR)
    return out


def dedupe_accuracy_history() -> dict:
    """F16 one-off (journaled): the pre-fix race left TWO accuracy rows per day
    (08-07, 08-08 at audit). Keep the LAST row per date — the later run reflects
    the settled state a single nightly run would have recorded. Idempotent."""
    import kv_store
    acc = kv_store.get(_KV_ACCURACY) or []
    seen: dict = {}
    for r in acc:
        seen[r.get("date")] = r          # last write per date wins
    deduped = list(seen.values())
    removed = len(acc) - len(deduped)
    if removed:
        kv_store.put(_KV_ACCURACY, deduped[-90:])
        _journal("F16 accuracy de-dupe",
                 f"removed {removed} doubled accuracy row(s) from the nightly "
                 f"double-run race; one row per date retained (last wins)")
    return {"before": len(acc), "after": len(deduped), "removed": removed}


def nightly_tick() -> bool:
    import datetime as _dt
    import os
    import kv_store
    from helpers import today_sydney
    today = str(today_sydney())
    if kv_store.get(_KV_TICK) == today:
        return False
    # F16 SINGLE-FLIGHT: claim the day BEFORE the 76s sweep (atomic set-if-
    # absent). The old code stamped AFTER the sweep — two workers hitting their
    # 6h timers near-simultaneously both passed the gate and doubled the run
    # (cost + duplicate accuracy rows). Loser of the claim walks away.
    import time as _time
    claim_key = f"{_KV_TICK}:claim:{today}"
    if not kv_store.put_if_absent(claim_key, {"pid": os.getpid(),
                                              "at_epoch": _time.time()}):
        # Review finding 9a: a worker killed MID-SWEEP (deploy/restart) leaves
        # the claim set with no tick stamp — the sweep would silently skip the
        # rest of the day. A claim older than 2h with the day still unswept is
        # STALE: reclaim it (loudly) and retry.
        held = kv_store.get(claim_key) or {}
        age = _time.time() - float(held.get("at_epoch") or _time.time())
        if age > 2 * 3600 and kv_store.get(_KV_TICK) != today:
            logger.warning("F16: stale sweep claim (%.0fs old, day unswept) — "
                           "reclaiming", age)
            kv_store.delete(claim_key)
            if not kv_store.put_if_absent(claim_key, {"pid": os.getpid(),
                                                      "at_epoch": _time.time()}):
                return False
        else:
            return False
    kv_store.delete(f"{_KV_TICK}:claim:"
                    f"{today_sydney() - _dt.timedelta(days=1)}")   # yesterday's claim GC
    try:
        integrity_sweep()
        kv_store.put(_KV_TICK, today)
        return True
    except Exception as e:
        # LOUD-FAILURE RULE: a silent watchdog is worse than none.
        # F16: release the claim so a later tick can RETRY the day — a failed
        # sweep must not burn the date.
        kv_store.delete(claim_key)
        logger.warning("ads truth sweep FAILED: %s", e)
        try:
            kv_store.put(_KV_SWEEP_ERROR, {"date": str(today_sydney()),
                                           "error": str(e)[:160]})
            flags = kv_store.get("attr:data_quality_flags") or []
            flags.append({"metric": "ads_truth_sweep_down",
                          "reason": f"the ads truth sweep itself failed: {str(e)[:100]}"})
            kv_store.put("attr:data_quality_flags", flags[-60:])
        except Exception:
            pass
        return False


# ── EDITH: "how accurate is the ad data?" ────────────────────────────────────

_ACCURACY_RE = re.compile(r"how (accurate|reliable|true).{0,20}(ad|ads|attribution|board)|"
                          r"(ad|ads) (data )?(accuracy|accurate)|trust the (ad|ads) (numbers|data)", re.I)


def handle_accuracy_command(text: str) -> tuple[str | None, bool]:
    if not text or not _ACCURACY_RE.search(text):
        return None, False
    import kv_store
    acc = kv_store.get(_KV_ACCURACY) or []
    err = kv_store.get(_KV_SWEEP_ERROR)
    if err:
        return (f"Honest answer: the accuracy sweep itself failed on {err['date']} "
                f"({err['error']}) — I can't vouch for tonight's numbers until it runs."), True
    if not acc:
        return ("The nightly truth sweep hasn't produced its first accuracy row yet — "
                "it checks every close ≤90d against four independent reads "
                "(board · engine · GHL · tracker) plus all invariants."), True
    last = acc[-1]
    parts = [f"Last sweep ({last['date']}): {last['facts_checked']} fact(s) checked, "
             f"{last['agreements']} agreed, {last['disagreements']} disagreement(s), "
             f"{last['invariant_violations']} invariant violation(s)."]
    sp = last.get("spine") or {}
    if sp:
        parts.append(f"Close evidence lanes: {sp.get('T1', 0)} tracker · "
                     f"{sp.get('T2', 0)} derived · {sp.get('T3', 0)} proposed · "
                     f"{sp.get('T0', 0)} PHANTOM (target zero).")
    if len(acc) >= 2:
        parts.append(f"Trend: {acc[-2]['disagreements']} → {last['disagreements']} "
                     f"disagreements night-over-night.")
    return " ".join(parts), True
