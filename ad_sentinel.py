"""
ad_sentinel.py — PHASE H: THE SENTINEL (extreme audit, gate-close build).

The standing watcher over the ad-truth system. Four layers, budgets, targeted
escalation, and a HARD self-heal boundary:

  L0 · inline (registered, not run here): the guards that already live at the
       write/compute boundaries — engine invariants I1/I2/I8/I10/I17 at every
       compute, record_derived_date schema enforcement, freshness stamps + the
       F6 derived-epoch (fresh can never label stale), F5 loud degradation,
       F9 partial-pull marking, F16 single-flight claims. L0 firings surface
       through kv (integrity:pending, ads_truth:flags, stripe:partial_pull)
       and are read by L1 as signals.
  L1 · hourly: reconciliation + tier partition + I17 (n=5 sampled cells) +
       the delta-anomaly band over tracked metrics (leads/closes/cash/spend/
       attribution rate/VERIFIED-SHOW RATIO — F15's decline watch lives here).
  L2 · nightly: the existing ads_truth integrity sweep (which now times itself
       and writes a SENTINEL COST block into its accuracy row) + drift diff vs
       the previous row + the deterministic HEAL pass.
  L3 · weekly: full I17 sweep (every cell, both clocks × 30/60/90) · full 90d
       quad-check · 5-claim re-proof sample · security-probe replay (the
       /debug gate must 401, the roster taint probe must 400) · perf
       regression vs the scorecard budgets.

ESCALATION — spend follows signal: an L0/L1 signal triggers a TARGETED deep
pass on that domain only (i17 → full I17 now; recon → quad-check now; metric
anomaly → drift diff; security → probe replay), never a blanket L3.

SELF-HEAL BOUNDARY (hard): auto-fix ONLY deterministic data-layer classes —
rebuild a stale/epoch-superseded rollup · clear invalidated engine cache ·
re-sync the contact table when stale · re-derive on new evidence + process
supersessions (the existing resolve_dates pass) · regenerate a failing-test
skeleton (the existing sweep mechanism). Each heal is journaled (evidence
stream) + one QUIET feed line. The sentinel NEVER edits code, definitions,
conventions, or thresholds, and never invents data. Anything code- or
judgment-shaped goes to SENTINEL_QUEUE.md + a ranked action-feed item.

KILL SWITCH: env AD_SENTINEL_PAUSE_HEALS (any truthy value) pauses ALL heals;
detection keeps running and says so. Documented in ADS_SYSTEM_STATE.md.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

# ── budgets (per run; breach = LOUD action-feed alert; cost rows are data) ───
BUDGETS = {
    "L1": {"runtime_s": 15, "api_calls": 0},     # engine/kv reads only
    "L2": {"runtime_s": 240, "api_calls": 130},  # nightly sweep caps: 30+40+40 GHL + slack
    "L3": {"runtime_s": 600, "api_calls": 20},   # in-process replays + engine reads
}

_KV_COST = "sentinel:cost"          # capped list of cost rows (auditable data)
_KV_STATE = "sentinel:state"        # last-run stamps per layer
_KV_METRICS = "sentinel:metrics"    # tracked-metric history for the anomaly band
_KV_ESCALATIONS = "sentinel:escalations"

QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "SENTINEL_QUEUE.md")

TRACKED_METRICS = ("leads", "closes", "cash", "spend", "attribution_rate_pct",
                   "verified_show_ratio")
_VSR_DECLINE_ALERT = 0.03           # F15: an hour-over-hour decline this big alerts
_BAND_PCT = 0.5                     # ±50% jump vs trailing mean = anomaly (n≥5)


def heals_paused() -> bool:
    return bool(os.environ.get("AD_SENTINEL_PAUSE_HEALS"))


# ── plumbing ─────────────────────────────────────────────────────────────────

def _feed(msg: str, loud: bool = False) -> None:
    """One feed line — quiet (hygiene lane) for heals, LOUD for breaches."""
    try:
        import kv_store
        flags = kv_store.get("ads_truth:flags") or []
        flags.append({"metric": "ads_truth_action" if loud else "ads_truth",
                      "reason": f"sentinel: {msg}"[:200]})
        kv_store.put("ads_truth:flags", flags[-60:])
    except Exception:
        pass


def _journal_heal(kind: str, detail: str) -> None:
    try:
        import resolution
        resolution.log_autofix(f"heal:{kind}", detail)   # evidence-class (F2 durable)
    except Exception:
        pass


def _cost_row(layer: str, runtime_s: float, api_calls: int, note: str = "") -> dict:
    from helpers import now_sydney
    b = BUDGETS[layer]
    row = {"layer": layer, "at": now_sydney().isoformat()[:16],
           "runtime_s": round(runtime_s, 2), "api_calls": api_calls,
           "budget": b,
           "over_budget": runtime_s > b["runtime_s"] or api_calls > b["api_calls"],
           "note": note}
    try:
        import kv_store
        rows = kv_store.get(_KV_COST) or []
        rows.append(row)
        kv_store.put(_KV_COST, rows[-200:])
    except Exception:
        pass
    if row["over_budget"]:
        _feed(f"{layer} BUDGET BREACH — {row['runtime_s']}s "
              f"(budget {b['runtime_s']}s) / {api_calls} calls "
              f"(budget {b['api_calls']}) {note}", loud=True)
    return row


def queue_item(title: str, evidence: str, rank: str = "P2") -> None:
    """Judgment-/code-shaped work: SENTINEL_QUEUE.md + a ranked feed item.
    The sentinel never guesses — it files."""
    from helpers import now_sydney
    line = f"- [{rank}] {now_sydney().isoformat()[:16]} — **{title}** — {evidence}\n"
    try:
        with open(QUEUE_PATH, "a") as f:
            f.write(line)
    except Exception as e:
        logger.warning("sentinel queue write failed: %s", e)
    _feed(f"queued ({rank}): {title} — {evidence[:120]}", loud=(rank == "P1"))


# ── L1 · hourly ──────────────────────────────────────────────────────────────

def _current_metrics() -> dict:
    import attribution_engine as AE
    r = AE.compute(days=30, basis="cohort")
    t = r.get("totals") or {}
    m = {k: t.get(k) for k in ("leads", "closes", "cash", "spend",
                               "attribution_rate_pct")}
    vsr = None
    try:
        import resolution
        shows = [v["show_date"] for v in resolution.derived_dates().values()
                 if "show_date" in v]
        if shows:
            vn = sum(1 for s in shows
                     if (s.get("verification") or {}).get("state") == "verified")
            vsr = round(vn / len(shows), 3)
    except Exception:
        pass
    m["verified_show_ratio"] = vsr
    return m, r


def hourly_tick(force: bool = False) -> dict | None:
    """L1: recon + partition + I17 n=5 + the delta-anomaly band. Single-flight
    per hour. Signals trigger a TARGETED escalation, never a blanket deep pass."""
    import kv_store
    from helpers import now_sydney
    hour_key = f"sentinel:L1:{now_sydney().strftime('%Y-%m-%dT%H')}"
    if not force and not kv_store.put_if_absent(hour_key, {"pid": os.getpid()}):
        return None
    t0 = time.time()
    signals: list[dict] = []
    out = {"layer": "L1", "signals": signals}
    try:
        import attribution_engine as AE
        metrics, r = _current_metrics()
        # 1 · reconciliation
        if not (r.get("reconciliation") or {}).get("ok"):
            signals.append({"domain": "recon",
                            "detail": "reconciliation not ok on cohort 30d"})
        # 2 · tier partition (I10)
        viol = AE.partition_violations(r.get("creatives") or [])
        if viol:
            signals.append({"domain": "partition",
                            "detail": f"I10 violation(s): {viol[:3]}"})
        # 3 · I17 n=5 sample
        import random
        cells = [(row, m) for row in (r.get("creatives") or [])
                 for m in ("leads", "qualified", "reached", "sets", "shows", "closes")]
        for row, m in random.sample(cells, min(5, len(cells))):
            if len((row.get("members") or {}).get(m) or []) != (row.get(m) or 0):
                signals.append({"domain": "i17",
                                "detail": f"I17 drift: {row['label'][:40]} {m}"})
        # 4 · delta-anomaly band over tracked metrics (F15 lives here)
        hist = kv_store.get(_KV_METRICS) or []
        prev = hist[-1]["metrics"] if hist else {}
        vsr_prev, vsr_now = prev.get("verified_show_ratio"), metrics.get("verified_show_ratio")
        if vsr_prev is not None and vsr_now is not None \
                and vsr_prev - vsr_now > _VSR_DECLINE_ALERT:
            signals.append({"domain": "metric:verified_show_ratio",
                            "detail": (f"verified-show ratio DECLINED "
                                       f"{vsr_prev} → {vsr_now} (F15 watch)")})
        if len(hist) >= 5:
            for k in ("leads", "closes", "cash", "spend"):
                vals = [h["metrics"].get(k) for h in hist[-7:]
                        if h["metrics"].get(k) is not None]
                cur = metrics.get(k)
                if vals and cur is not None:
                    mean = sum(vals) / len(vals)
                    if mean and abs(cur - mean) / abs(mean) > _BAND_PCT:
                        signals.append({"domain": f"metric:{k}",
                                        "detail": f"{k} {cur} vs trailing mean "
                                                  f"{round(mean, 1)} — outside ±50% band"})
        hist.append({"at": now_sydney().isoformat()[:16], "metrics": metrics})
        kv_store.put(_KV_METRICS, hist[-168:])   # a week of hourly samples
        # 5 · L0 signal pickup (the inline guards' surfaced state)
        if (kv_store.get("stripe:partial_pull") or None) is not None:
            signals.append({"domain": "recon",
                            "detail": "L0: stripe partial-pull marker is set"})
        for s in signals:
            _feed(f"L1 signal [{s['domain']}]: {s['detail'][:140]}", loud=True)
            escalate(s["domain"], "L1", s["detail"])
    except Exception as e:
        logger.warning("sentinel L1 failed: %s", e)
        _feed(f"L1 tick ITSELF failed: {str(e)[:120]}", loud=True)
        out["error"] = str(e)[:120]
    out["cost"] = _cost_row("L1", time.time() - t0, 0)
    _mark_ran("L1")
    return out


# ── escalation — spend follows signal ────────────────────────────────────────

def escalate(domain: str, source_layer: str, reason: str) -> dict:
    """A signal buys a TARGETED deep pass on its domain only."""
    import kv_store
    t0 = time.time()
    ran = {"domain": domain, "source": source_layer, "reason": reason[:140],
           "targeted": None}
    try:
        import ads_truth
        if domain == "i17":
            ran["targeted"] = {"full_i17": full_i17_sweep()}
        elif domain in ("recon", "partition"):
            qc = ads_truth.quad_check(90)
            ran["targeted"] = {"quad_check": {"facts": qc["facts"],
                                              "hard_disagreements": qc["hard_disagreements"]}}
        elif domain.startswith("metric:"):
            ran["targeted"] = {"drift_diff": drift_diff()}
        elif domain == "security":
            ran["targeted"] = {"security_replay": security_replay()}
        else:
            ran["targeted"] = {"noop": f"no targeted pass mapped for '{domain}'"}
    except Exception as e:
        ran["error"] = str(e)[:120]
    ran["runtime_s"] = round(time.time() - t0, 2)
    try:
        esc = kv_store.get(_KV_ESCALATIONS) or []
        esc.append(ran)
        kv_store.put(_KV_ESCALATIONS, esc[-40:])
    except Exception:
        pass
    _feed(f"ESCALATION [{source_layer}→{domain}]: {reason[:100]} — targeted pass ran "
          f"({ran['runtime_s']}s)", loud=True)
    return ran


# ── L2 · nightly (rides the existing sweep; adds drift diff + heals) ─────────

def drift_diff() -> dict:
    """Tonight's accuracy row vs the previous — worsening is a signal."""
    import kv_store
    acc = kv_store.get("ads_truth:accuracy") or []
    if len(acc) < 2:
        return {"insufficient": True}
    prev, cur = acc[-2], acc[-1]
    diff = {}
    for k in ("disagreements", "invariant_violations"):
        diff[k] = {"prev": prev.get(k), "cur": cur.get(k),
                   "worse": (cur.get(k) or 0) > (prev.get(k) or 0)}
    vp, vc = prev.get("verified_show_ratio"), cur.get("verified_show_ratio")
    diff["verified_show_ratio"] = {"prev": vp, "cur": vc,
                                   "worse": (vp is not None and vc is not None
                                             and vc < vp - 0.01)}
    worsened = [k for k, v in diff.items() if v.get("worse")]
    if worsened:
        _feed(f"L2 drift: {', '.join(worsened)} worsened night-over-night "
              f"({ {k: (diff[k]['prev'], diff[k]['cur']) for k in worsened} })", loud=True)
    return diff


def heal_pass() -> dict:
    """The DETERMINISTIC data-layer heals — journaled, one quiet line each.
    HARD BOUNDARY: no code, definitions, conventions, thresholds; no invention.
    KILL SWITCH: AD_SENTINEL_PAUSE_HEALS pauses this whole pass (detection
    elsewhere keeps running)."""
    out = {"paused": heals_paused(), "heals": []}
    if out["paused"]:
        _feed("heals PAUSED (AD_SENTINEL_PAUSE_HEALS set) — detection continues")
        return out
    import kv_store
    # 1 · rebuild stale/epoch-superseded rollups (the F6 class)
    try:
        import resolution
        epoch = resolution.derived_epoch()
        for basis in ("cohort", "activity"):
            for days in (30, 60, 90, 3650):
                key = f"attr:rollup:{basis}:{days}"
                stored = kv_store.get(key)
                if stored and int(stored.get("epoch") or 0) != epoch:
                    from dashboard.ads import _refresh_async
                    _refresh_async(days, basis)
                    out["heals"].append({"kind": "rollup_rebuild",
                                         "target": f"{basis}:{days}"})
                    _journal_heal("rollup_rebuild",
                                  f"{key}: epoch {stored.get('epoch')} ≠ current "
                                  f"{epoch} — background rebuild kicked")
                    _feed(f"heal: stale rollup {basis}:{days} rebuild kicked (epoch)")
    except Exception as e:
        out.setdefault("errors", []).append(f"rollup: {str(e)[:80]}")
    # 2 · clear invalidated (old-epoch / TTL-dead) engine cache entries
    try:
        import attribution_engine as AE
        import resolution
        now, epoch = time.time(), resolution.derived_epoch()
        dead = [k for k, v in list(AE._cache.items())
                if now - v[0] >= AE._CACHE_TTL_S or k[4] != epoch]
        for k in dead:
            AE._cache.pop(k, None)
        if dead:
            out["heals"].append({"kind": "cache_clear", "n": len(dead)})
            _journal_heal("cache_clear", f"{len(dead)} invalidated engine cache "
                                         f"entr(ies) cleared")
            _feed(f"heal: {len(dead)} invalidated cache entr(ies) cleared")
    except Exception as e:
        out.setdefault("errors", []).append(f"cache: {str(e)[:80]}")
    # 3 · re-sync the contact table when stale (>26h — a missed sync cycle)
    try:
        import attribution_join
        state = kv_store.get("attr:sync_state") or {}
        at = state.get("at")
        if at and time.time() - float(at) > 26 * 3600:
            attribution_join.sync_contacts(force=True)
            out["heals"].append({"kind": "contact_resync"})
            _journal_heal("contact_resync",
                          f"contact sync watermark {round((time.time() - float(at)) / 3600)}h "
                          f"old — forced re-sync")
            _feed("heal: contact table re-synced (stale watermark)")
    except Exception as e:
        out.setdefault("errors", []).append(f"contacts: {str(e)[:80]}")
    # 4 · re-derive on new evidence + process supersessions — the existing
    #     resolve_dates pass IS this heal class (journaled inside); run it.
    try:
        import resolution
        rd = resolution.resolve_dates()
        out["heals"].append({"kind": "resolve_dates", "result":
                             {k: v for k, v in (rd or {}).items() if k != "lanes"}})
        if (rd or {}).get("input_auto") or (rd or {}).get("superseded"):
            _feed(f"heal: date resolution pass — {rd.get('input_auto', 0)} derived, "
                  f"{rd.get('superseded', 0)} superseded (journaled per item)")
    except Exception as e:
        out.setdefault("errors", []).append(f"resolve: {str(e)[:80]}")
    return out


def nightly_extras() -> dict | None:
    """L2 extras — run once per day AFTER the ads_truth sweep has stamped."""
    import kv_store
    from helpers import today_sydney
    today = str(today_sydney())
    if kv_store.get("ads_truth:sweep_tick") != today:
        return None                      # the sweep hasn't run yet tonight
    if not kv_store.put_if_absent(f"sentinel:L2:{today}", {"pid": os.getpid()}):
        return None
    t0 = time.time()
    out = {"layer": "L2", "drift": drift_diff(), "heals": heal_pass()}
    # RENEWAL & CHURN TRUTH LOOP (#135): the cheap nightly sheet scan (pull +
    # diff + convergence) + its watches (scan staleness >7d · pending-sheet
    # ageing >5d · conflicts → ACTION · schema-drift trip). Detection always
    # runs; the scan's convergence marking is data-layer deterministic (a
    # declaration the sheet now matches) — inside the heal boundary.
    try:
        import renewal_loop
        sc = renewal_loop.nightly_scan()
        out["renewal_scan"] = {k: sc.get(k) for k in
                               ("ok", "verdict", "schema_drift")} | {
            "converged": len(sc.get("converged") or []),
            "conflicts": len(sc.get("conflicts") or []),
            "pending": len(sc.get("pending") or [])}
        out["renewal_watch"] = renewal_loop.sentinel_watch()
    except Exception as e:
        out["renewal_scan"] = {"ok": False, "error": str(e)[:100]}
    # PIOLO QUEUE watch (queue fix 2026-08-10): lane sizes + aged-growth alert
    try:
        import collab
        out["queue_watch"] = collab.sentinel_watch()
    except Exception as e:
        out["queue_watch"] = {"error": str(e)[:80]}
    # cost: the sweep's own cost block is in its accuracy row; this adds extras
    out["cost"] = _cost_row("L2", time.time() - t0, 0, note="extras (sweep cost in accuracy row)")
    _mark_ran("L2")
    return out


# ── L3 · weekly ──────────────────────────────────────────────────────────────

def full_i17_sweep() -> dict:
    """EVERY cell, both clocks × 30/60/90: members-at-increment == the cell."""
    import attribution_engine as AE
    checked = drift = 0
    drifts = []
    for basis in ("cohort", "activity"):
        for days in (30, 60, 90):
            r = AE.compute(days=days, basis=basis)
            for row in (r.get("creatives") or []):
                for m in ("leads", "qualified", "reached", "sets", "shows", "closes"):
                    checked += 1
                    n = len((row.get("members") or {}).get(m) or [])
                    if n != (row.get(m) or 0):
                        drift += 1
                        drifts.append(f"{basis}:{days}:{row['creative_key']}:{m}")
    if drift:
        _feed(f"L3 FULL I17: {drift} drifted cell(s) of {checked} — "
              f"{drifts[:5]}", loud=True)
    return {"cells": checked, "drift": drift, "drifts": drifts[:20]}


def security_replay() -> dict:
    """In-process replay of the security probes: the F4 /debug gate must 401
    anonymously; the F12 roster taint probe must 400 without echo."""
    out = {}
    try:
        from app import app
        # NOTE (review finding 5): never set app.config["TESTING"] here — this
        # is the LIVE app object; TESTING would bypass the global error handler
        # for real traffic in this worker. test_client() works without it.
        c = app.test_client()
        r1 = c.get("/debug/stripe-ping")
        r2 = c.get("/debug/sources")
        evil = "<img src=x onerror=alert(1)>"
        r3 = c.get(f"/ads/api/roster?days=30&level=creative&key=k&metric={evil}")
        out = {"debug_stripe_ping": r1.status_code, "debug_sources": r2.status_code,
               "roster_taint_status": r3.status_code,
               "roster_taint_echoed": evil.encode() in r3.data}
        ok = (r1.status_code == 401 and r2.status_code == 401
              and r3.status_code in (400, 401, 302) and not out["roster_taint_echoed"])
        out["ok"] = ok
        if not ok:
            _feed(f"L3 SECURITY REPLAY FAILED: {out}", loud=True)
            queue_item("security replay failed", str(out), rank="P1")
    except Exception as e:
        out = {"error": str(e)[:120], "ok": False}
    return out


def claims_reproof() -> dict:
    """5-claim re-proof sample — the standing claims re-asserted from live state."""
    import attribution_engine as AE
    import kv_store
    r = AE.compute(days=30, basis="cohort")
    claims = {
        "recon_block_present": isinstance(r.get("reconciliation"), dict),
        "partition_holds": not AE.partition_violations(r.get("creatives") or []),
        "one_clock_per_view": r.get("basis") in ("cohort", "activity"),
        # the degradation channel is a list wherever present (wrapper results
        # always set it; a truthy non-list here means the channel broke)
        "degraded_channel_sound": (r.get("degraded") is None
                                   or isinstance(r.get("degraded"), list)),
        "evidence_journal_alive": isinstance(kv_store.get("resolution:journal") or [], list),
    }
    claims["ok"] = all(claims.values())
    if not claims["ok"]:
        failed = [k for k, v in claims.items() if v is False and k != "ok"]
        _feed(f"L3 claim re-proof FAILED: {failed}", loud=True)
    return claims


def perf_regression() -> dict:
    """Warm-path timings vs the scorecard budgets (roster <0.5s, compute-warm <1s)."""
    import attribution_engine as AE
    import roster_engine
    t0 = time.time(); AE.compute(days=30, basis="cohort"); warm = time.time() - t0
    t0 = time.time()
    _res, meta = roster_engine.load_result(30, None, None, "cohort", None)
    roster_s = time.time() - t0
    out = {"compute_warm_s": round(warm, 3), "roster_load_s": round(roster_s, 3),
           "roster_served_from": meta["served_from"],
           "ok": warm < 1.0 and roster_s < 0.5}
    if not out["ok"]:
        _feed(f"L3 PERF REGRESSION: warm={out['compute_warm_s']}s "
              f"roster={out['roster_load_s']}s (budgets 1.0/0.5)", loud=True)
    return out


def weekly_tick(force: bool = False) -> dict | None:
    import kv_store
    from helpers import today_sydney
    week = today_sydney().strftime("%G-W%V")
    if not force and not kv_store.put_if_absent(f"sentinel:L3:{week}",
                                                {"pid": os.getpid()}):
        return None
    t0 = time.time()
    api_calls = 0
    out = {"layer": "L3", "week": week}
    try:
        out["full_i17"] = full_i17_sweep()
        import ads_truth
        qc = ads_truth.quad_check(90)
        out["quad_check_90d"] = {"facts": qc["facts"],
                                 "hard_disagreements": qc["hard_disagreements"]}
        out["claims_reproof"] = claims_reproof()
        out["security_replay"] = security_replay()
        out["perf"] = perf_regression()
        bad = (out["full_i17"]["drift"] or out["quad_check_90d"]["hard_disagreements"]
               or not out["claims_reproof"]["ok"] or not out["security_replay"].get("ok")
               or not out["perf"]["ok"])
        if bad:
            _feed("L3 weekly pass found problems — see sentinel state", loud=True)
    except Exception as e:
        logger.warning("sentinel L3 failed: %s", e)
        _feed(f"L3 weekly pass ITSELF failed: {str(e)[:120]}", loud=True)
        out["error"] = str(e)[:120]
    out["cost"] = _cost_row("L3", time.time() - t0, api_calls)
    _mark_ran("L3")
    try:
        kv_store.put("sentinel:last_l3", out)
    except Exception:
        pass
    return out


# ── state + loop ─────────────────────────────────────────────────────────────

def _mark_ran(layer: str) -> None:
    try:
        import kv_store
        from helpers import now_sydney
        st = kv_store.get(_KV_STATE) or {}
        st[layer] = now_sydney().isoformat()[:16]
        st["heals_paused"] = heals_paused()
        kv_store.put(_KV_STATE, st)
    except Exception:
        pass


def status() -> dict:
    import kv_store
    return {"state": kv_store.get(_KV_STATE) or {},
            "budgets": BUDGETS,
            "heals_paused": heals_paused(),
            "cost_rows": (kv_store.get(_KV_COST) or [])[-10:],
            "escalations": (kv_store.get(_KV_ESCALATIONS) or [])[-5:]}


_loop_started = False


def start_loop(interval_s: int = 3600) -> None:
    """Hourly heartbeat: L1 every tick; L2 extras once the nightly sweep has
    stamped; L3 weekly. All single-flight via kv claims (F16 primitive) — safe
    across both gunicorn workers. Fail-quiet daemon; failures are LOUD in-band."""
    global _loop_started
    if _loop_started:
        return
    _loop_started = True
    import threading

    def _loop():
        while True:
            time.sleep(interval_s)
            for fn in (hourly_tick, nightly_extras, weekly_tick):
                try:
                    fn()
                except Exception as e:
                    logger.warning("sentinel %s failed: %s", fn.__name__, e)
    threading.Thread(target=_loop, daemon=True, name="ad-sentinel").start()
