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
    by_norm = {l["name_norm"]: l for l in leads_all}
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
    fix at source, don't patch silently forever."""
    try:
        import kv_store
        flags = kv_store.get("attr:data_quality_flags") or []
        reason = (f"tracker missing set for {name} — GHL {evidence_kind} evidence "
                  f"exists (contact {contact_id}); fill the Set cell at source")
        if not any(f.get("reason") == reason for f in flags):
            flags.append({"metric": "tracker_missing_set", "reason": reason})
            kv_store.put("attr:data_quality_flags", flags[-40:])
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
    # (4) tracker
    leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
    by_norm = {l["name_norm"]: l for l in leads_all}
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

    # feed lanes: close-level/≥$1k → ACTION-promoted category; else hygiene
    flags = kv_store.get("attr:data_quality_flags") or []
    for dgg in out["disagreements"]:
        big = dgg.get("cash", 0) and dgg["cash"] >= 1000 or dgg["kind"] in ("phantom_close", "quad")
        reason = f"ads truth sweep: {dgg['kind']} — {dgg['cause'][:110]}"
        if not any(f.get("reason") == reason for f in flags):
            flags.append({"metric": "ads_truth_action" if big else "ads_truth",
                          "reason": reason})
    kv_store.put("attr:data_quality_flags", flags[-60:])

    acc = kv_store.get(_KV_ACCURACY) or []
    acc.append({"date": out["date"], "facts_checked": out["checks"],
                "agreements": out["agreements"],
                "disagreements": len(out["disagreements"]),
                "invariant_violations": out["invariant_violations"],
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
