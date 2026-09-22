"""system_page.py — THE SYSTEM PAGE, ASSEMBLED FROM STORED RESULTS ONLY.

"The System tab is glitchy." Phase 0 found why, and none of it was mysterious:

  · Two of the three sections were filled by inline `fetch()` after load,
    each replacing a skeleton — so the page reflowed twice on every visit.
  · The page inherits the dashboard's TEN-MINUTE AUTO-REFRESH, which calls
    render(snapshot) and rebuilds every panel on a page nobody touched.
  · The telemetry section rendered a RAW STREAM of the last dozen client
    errors, so a noisy hour looked like a broken system.

So this module builds the whole page server-side from results that are
ALREADY STORED — health rows, the job registry, freshness stamps, telemetry
aggregates. Loading the page runs no scan, no sync, and no heavy query. The
only work on the request path is reading kv and a sync-state table.

"Run checks now" is a separate, explicit owner action.
"""

from __future__ import annotations

import logging
from collections import Counter

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

K_RUN_STATE = "system:check_run"      # the async Run-checks-now state


def _guard(name, fn, empty):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        logger.warning("system page: %s failed: %s", name, e)
        return {**empty, "error": f"{name} could not be read: {str(e)[:120]}"}


def build() -> dict:
    """Everything the System page renders. Every value comes from a store;
    nothing here calls a source or runs a check."""
    import freshness as F
    out = {"at": now_sydney().isoformat(), "sections": {}}

    out["sections"]["sources"] = _guard(
        "data sources", F.sources, {"rows": [], "stale": [], "ok": None})

    out["sections"]["checks"] = _guard("the three checks", _checks, {"rows": []})
    out["sections"]["jobs"] = _guard("jobs and the watchdog", _jobs, {"rows": []})
    out["sections"]["errors"] = _guard(
        "browser errors", _browser_errors, {"groups": [], "total": 0})
    out["sections"]["gates"] = _guard("latest gate results", _gates, {"rows": []})

    out["run_state"] = run_state()
    out["poll_seconds"] = _poll_seconds()
    out["headline"] = _headline(out["sections"])
    return out


def _poll_seconds() -> int:
    import os
    try:
        return max(int(os.environ.get("SYSTEM_POLL_SECONDS", "60")), 15)
    except ValueError:
        return 60


def _headline(sections: dict) -> dict:
    """One calm line at the top. Never a colour without a word."""
    src = sections.get("sources") or {}
    checks = sections.get("checks") or {}
    stale = src.get("stale") or []
    degraded = [r for r in (src.get("rows") or []) if r.get("status") == "degraded"]
    last = (checks.get("rows") or [{}])[0] if checks.get("rows") else {}
    scans_ok = all(last.get(k) is not False
                   for k in ("scan1_ok", "scan2_ok", "scan3_ok")) if last else None
    if degraded:
        return {"state": "degraded",
                "line": f"{len(degraded)} source is not reporting: "
                        + ", ".join(r["label"] for r in degraded[:3])}
    if stale:
        names = ", ".join(r["label"] for r in (src.get("rows") or [])
                          if r["key"] in stale)
        return {"state": "stale", "line": f"Everything is running; {names} is past its budget."}
    if scans_ok is False:
        return {"state": "stale", "line": "The last estate scan found something."}
    if scans_ok is None:
        return {"state": "unknown", "line": "No estate scan has recorded a result yet."}
    return {"state": "ok",
            "line": "Every source is inside its budget and the last estate scan passed all three."}


def _checks() -> dict:
    """The three scans — from the stored HEALTH rows. Never runs one."""
    import ground_truth as GT
    h = GT.health() or {}
    rows = []
    for r in (h.get("rows") or []):
        rows.append({
            "at": r.get("at"), "commit": (r.get("commit") or "")[:7],
            "works": r.get("scan1_ok"), "agrees_with_itself": r.get("scan2_ok"),
            "agrees_with_reality": r.get("scan3_ok"),
            "pages": r.get("pages"), "findings": r.get("findings"),
            "top": r.get("top"), "runtime_s": r.get("runtime_s"),
        })
    gt = h.get("ground_truth") or {}
    return {"rows": rows, "stale_warning": h.get("stale_warning"),
            "reality_checks": (gt.get("checks") or [])[:12],
            "budget": h.get("budget") or {},
            "note": ("three scans: it works · it agrees with itself · it "
                     "agrees with the outside world")}


def _jobs() -> dict:
    """The job registry and the watchdog — what runs, when it last ran, and
    whether anything has quietly stopped."""
    import freshness as F
    rows = []
    tick = F.last_tick() or {}
    rows.append({
        "job": "Freshness tick",
        "what": "rebuilds the engine blocks when their inputs move",
        "at": tick.get("at"), "words": F.relative(tick.get("at")),
        "detail": tick.get("why") or tick.get("note") or "",
        "ok": tick.get("at") is not None,
    })
    last_ref = F.last_refresh() or {}
    rows.append({
        "job": "Refresh now (manual)",
        "what": "the owner's explicit pull + rebuild",
        "at": last_ref.get("at"), "words": F.relative(last_ref.get("at")),
        "detail": (f"by {last_ref.get('by')}" if last_ref.get("by")
                   else last_ref.get("note", "not used yet")),
        "ok": last_ref.get("ok", True),
    })
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        rows.append({
            "job": "Scheduled snapshot",
            "what": "the heavy pull — Stripe, Xero, sheets",
            "at": snap.get("generated_at"),
            "words": F.relative(snap.get("generated_at")),
            "detail": f"{len(snap.get('degraded') or [])} source(s) degraded",
            "ok": bool(snap.get("ok", True)),
        })
    except Exception as e:  # noqa: BLE001
        rows.append({"job": "Scheduled snapshot", "at": None, "ok": False,
                     "detail": str(e)[:100], "words": "unknown", "what": ""})
    try:
        import stage_history
        started = stage_history.started_at()
        rows.append({"job": "Stage recorder",
                     "what": "remembers every CRM stage change",
                     "at": None, "words": f"watching since {started or 'not started'}",
                     "detail": "reads the mirror another job refreshed; never writes to the CRM",
                     "ok": bool(started)})
    except Exception:
        pass
    # EDITH's brain — the thing nothing was watching when the SDK broke it.
    try:
        import kv_store
        brain = kv_store.get("edith:last_chat") or {}
        rows.append({
            "job": "EDITH's answers",
            "what": "the model call behind chat and voice",
            "at": brain.get("at"), "words": F.relative(brain.get("at")),
            "detail": (brain.get("error") or f"answering on {brain.get('model', 'the chat model')}"
                       if brain else "no answer recorded yet"),
            "ok": bool(brain.get("ok")) if brain else None,
        })
    except Exception as e:  # noqa: BLE001
        logger.info("brain pulse unavailable: %s", e)

    watchdog = []
    try:
        import ground_truth as GT
        watchdog = GT.watchdog() or []
    except Exception as e:  # noqa: BLE001
        logger.info("watchdog unavailable: %s", e)
    return {"rows": rows, "watchdog": watchdog,
            "note": "a job that stops running is a failure in itself"}


def _browser_errors(hours: int = 24) -> dict:
    """AGGREGATED, never a raw stream. Phase 0: the page rendered the last
    dozen individual errors, so one noisy hour read as a broken system.
    Grouped by what actually went wrong, with counts and a last-seen."""
    ring = kv_store.get("telemetry:client_errors") or []
    if not ring:
        return {"groups": [], "total": 0, "window_hours": hours,
                "note": "nothing recorded — quiet is healthy"}
    import datetime as dt
    cutoff = now_sydney() - dt.timedelta(hours=hours)
    recent = []
    for e in ring:
        try:
            at = dt.datetime.fromisoformat(str(e.get("at")).replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=now_sydney().tzinfo)
            if at >= cutoff:
                recent.append((at, e))
        except Exception:
            continue
    groups: dict = {}
    for at, e in recent:
        key = (str(e.get("kind") or "error"),
               str(e.get("detail") or "")[:90].split("\n")[0])
        g = groups.setdefault(key, {"kind": key[0], "detail": key[1],
                                    "count": 0, "routes": Counter(),
                                    "last_at": None})
        g["count"] += 1
        g["routes"][str(e.get("route") or "?")] += 1
        if g["last_at"] is None or at.isoformat() > g["last_at"]:
            g["last_at"] = at.isoformat()
    rows = sorted(groups.values(), key=lambda g: -g["count"])
    import freshness as F
    for g in rows:
        g["routes"] = [{"route": r, "n": n} for r, n in g["routes"].most_common(3)]
        g["last_words"] = F.relative(g["last_at"])
    return {"groups": rows[:12], "distinct": len(rows), "total": len(recent),
            "window_hours": hours, "stored": len(ring),
            "note": ("grouped by what went wrong, with counts — a raw stream "
                     "of individual errors made a noisy hour look like a "
                     "broken system")}


def _gates() -> dict:
    """Latest gate results, with links to their artefacts."""
    import os
    root = os.path.join(os.path.dirname(__file__), "dashboard", "evidence")
    rows = []
    if not os.path.isdir(root):
        return {"rows": [], "note": "no evidence directory on this instance"}
    import json
    for prefix, label in (("gate-", "Render gate"), ("behaviour-", "Behaviour gate"),
                          ("scan-", "Triple scan")):
        dirs = sorted((d for d in os.listdir(root) if d.startswith(prefix)),
                      reverse=True)
        if not dirs:
            continue
        newest = dirs[0]
        rec = {"gate": label, "dir": newest,
               "commit": newest.split("-", 1)[-1][:7]}
        for fname in ("report.json", "scan.json"):
            p = os.path.join(root, newest, fname)
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        d = json.load(f)
                    rec["ok"] = d.get("ok", not d.get("fails"))
                    rec["findings"] = len(d.get("findings") or [])
                    rec["at"] = d.get("utc") or d.get("at")
                except Exception as e:  # noqa: BLE001
                    rec["error"] = str(e)[:80]
                break
        rows.append(rec)
    return {"rows": rows,
            "note": "the artefacts a claim of 'it works' has to point at"}


# ── RUN CHECKS NOW — explicit, async, one at a time, rate-limited ───────────

_MIN_SECONDS_BETWEEN_RUNS = 300


def run_state() -> dict:
    st = kv_store.get(K_RUN_STATE) or {}
    return {"running": bool(st.get("running")),
            "started_at": st.get("started_at"),
            "finished_at": st.get("finished_at"),
            "step": st.get("step"), "progress": st.get("progress"),
            "last_result": st.get("last_result"),
            "by": st.get("by")}


def start_check_run(actor: str = "owner") -> dict:
    """Kick the ground-truth checks off in the background. ONE AT A TIME and
    rate-limited — the System page must never become a way to hammer the
    estate. The result lands as a new HEALTH row; the page picks it up on
    its next poll."""
    import freshness as F
    st = kv_store.get(K_RUN_STATE) or {}
    if st.get("running"):
        return {"ok": False, "already_running": True,
                "why": f"a run started {F.relative(st.get('started_at'))} is still going",
                "state": run_state()}
    since = F._age_min(st.get("finished_at"))
    if since is not None and since * 60 < _MIN_SECONDS_BETWEEN_RUNS:
        return {"ok": False, "rate_limited": True,
                "why": (f"the last run finished {F.relative(st.get('finished_at'))}; "
                        f"these checks call outside services, so they are "
                        f"limited to one every "
                        f"{_MIN_SECONDS_BETWEEN_RUNS // 60} minutes"),
                "state": run_state()}

    kv_store.put(K_RUN_STATE, {"running": True, "by": actor,
                               "started_at": now_sydney().isoformat(),
                               "step": "starting", "progress": 0})

    import threading

    def _run():
        try:
            import ground_truth as GT
            kv_store.put(K_RUN_STATE, {**(kv_store.get(K_RUN_STATE) or {}),
                                       "step": "checking against the outside world",
                                       "progress": 30})
            res = GT.run()
            GT.record_health_row({
                "commit": "manual", "scan1_ok": None, "scan2_ok": None,
                "scan3_ok": res.get("ok"), "findings": res.get("failed") or 0,
                "runtime_s": 0, "top": (res.get("checks") or [{}])[0].get("name"),
                "pages": 0})
            kv_store.put(K_RUN_STATE, {
                "running": False, "by": actor,
                "started_at": (kv_store.get(K_RUN_STATE) or {}).get("started_at"),
                "finished_at": now_sydney().isoformat(),
                "step": "done", "progress": 100,
                "last_result": {"ok": res.get("ok"),
                                "passed": res.get("passed"),
                                "failed": res.get("failed"),
                                "not_comparable": res.get("not_comparable")}})
        except Exception as e:  # noqa: BLE001
            logger.warning("check run failed: %s", e)
            kv_store.put(K_RUN_STATE, {
                "running": False, "by": actor,
                "finished_at": now_sydney().isoformat(),
                "step": "failed", "progress": 100,
                "last_result": {"ok": False, "why": str(e)[:160]}})

    threading.Thread(target=_run, daemon=True, name="system-check-run").start()
    return {"ok": True, "started": True, "state": run_state()}
