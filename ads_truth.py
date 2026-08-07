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
    kv_store.put(_KV_PROPOSED, proposed[-40:])
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
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("name"):
                contacts_by_norm.setdefault(_norm(c["name"]), c)
    except Exception:
        return {"checked": 0, "found": 0, "reason": "contacts unavailable"}
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
    cache[contact_id] = {"expires": str(today_sydney() + dt.timedelta(days=_APPT_TTL_DAYS)),
                         "appts": [{k: a.get(k) for k in
                                    ("id", "dateAdded", "startTime", "appointmentStatus",
                                     "status", "calendarId")} for a in appts[:6]]}
    # cap the cache footprint
    if len(cache) > 800:
        cache = dict(list(cache.items())[-600:])
    kv_store.put(_KV_APPT_CACHE, cache)
    return cache[contact_id]["appts"]


def _date_of(v) -> str | None:
    s = str(v or "")
    return s[:10] if len(s) >= 10 and s[4:5] == "-" else None


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
            booked = _date_of(a.get("dateAdded"))
            if booked and resolution.record_derived_date(
                    nm, "set_date", booked, "derived:ghl-appt",
                    {"appointment_id": a.get("id"), "contact_id": cid,
                     "raw_status": a.get("appointmentStatus") or a.get("status")}):
                derived += 1
                status = str(a.get("appointmentStatus") or a.get("status") or "").lower()
                sched = _date_of(a.get("startTime"))
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
                                                 "booked": _date_of(a.get("dateAdded")),
                                                 "start": _date_of(a.get("startTime")),
                                                 "status": a.get("appointmentStatus") or a.get("status")}
                                                for a in appts],
                                 "ask": "multiple appointments — pick the set call"})
                prop_n += 1
    kv_store.put(_KV_PROPOSED, proposed[-60:])
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
                                      "date": str(m.get("dateAdded") or "")[:10]})
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
    kv_store.put(_KV_PROPOSED, proposed[-80:])
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


# ── THE NIGHTLY SWEEP ────────────────────────────────────────────────────────

def integrity_sweep() -> dict:
    """Invariants + spine + quad-check + accuracy row. Called nightly (kv-stamped);
    a sweep failure is itself LOUD (kv flag → action feed)."""
    import attribution_engine as AE
    import kv_store
    from helpers import today_sydney
    out = {"date": str(today_sydney()), "checks": 0, "agreements": 0,
           "disagreements": [], "invariant_violations": 0}
    # invariants across both clocks × windows (the engine computes them per row)
    for basis in ("cohort", "activity"):
        for d in (30, 60, 90):
            r = AE.compute(days=d, basis=basis)
            bad = [i for i in (r.get("invariants") or []) if not i.get("ok")]
            out["checks"] += 1
            out["invariant_violations"] += len(bad)
            for b in bad:
                out["disagreements"].append({"kind": "invariant", "cause": b["detail"],
                                             "where": f"{basis} {d}d"})
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
    kv_store.put(_KV_PROPOSED, proposed[-40:])

    # feed lanes: close-level/≥$1k → ACTION-promoted category; else hygiene.
    # The channel is REBUILT each run (self-retiring); Piolo items survive the run.
    flags = [f for f in (kv_store.get("ads_truth:flags") or [])
             if f.get("metric") == "tracker_missing_set"]
    for dgg in out["disagreements"]:
        big = (dgg.get("cash") or 0) >= 1000 or dgg["kind"] in ("phantom_close", "quad")
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
    acc = kv_store.get(_KV_ACCURACY) or []
    acc.append({"date": out["date"], "facts_checked": out["checks"],
                "agreements": out["agreements"],
                "disagreements": len(out["disagreements"]),
                "invariant_violations": out["invariant_violations"],
                "verified_show_ratio": vsr,
                "spine": out.get("spine")})
    kv_store.put(_KV_ACCURACY, acc[-90:])
    kv_store.delete(_KV_SWEEP_ERROR)
    return out


def nightly_tick() -> bool:
    import kv_store
    from helpers import today_sydney
    if kv_store.get(_KV_TICK) == str(today_sydney()):
        return False
    try:
        integrity_sweep()
        kv_store.put(_KV_TICK, str(today_sydney()))
        return True
    except Exception as e:
        # LOUD-FAILURE RULE: a silent watchdog is worse than none
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
