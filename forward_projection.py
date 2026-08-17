"""
forward_projection.py
---------------------
THE TWO-LAYER FORWARD PROJECTION (forward-MRR wave, 2026-08-13).

  COMMITTED — deterministic, from two committed sources, per client per month:
    1. the RECOGNIZED tab's per-client recognition schedule (the contracted
       runway — Piolo's sheet, read via forward_mrr.per_client_recognition,
       ONE sheet path), and
    2. owner DECLARATIONS (client_overrides): a resign (amount·term·cadence·
       start) OVERRIDES the client's committed months with the normalised MRR
       through the declared term; a churn zeroes the client from its effective
       date; a downgrade caps at the new MRR. One-off cadence lands in
       committed CASH for its month — never the MRR line.
  ASSUMED — the undecided pool: a client whose committed coverage has ENDED
    by month m (and no live declaration covers m) contributes their CURRENT
    MRR to assumed_pool[m]. The rendered assumed layer is
       assumed[m] = assumed_pool[m] × renewal_pct / 100
    — the ONE stated formula; the dashboard slider applies it client-side to
    the engine's pool curve (a labelled what-if; committed is slider-immune
    by construction — the engine never takes a pct parameter for committed).

SCENARIO NEVER CONTAMINATES ACTUALS: nothing here writes anywhere; the
assumption default is config (kv, journaled on change); slider positions are
NOT journal events (what-ifs); every assumed figure is labelled.

Reconciliation: month-0 committed must equal the RECOGNIZED tab's
current-month total exactly (same tab, same parse — by construction, and
asserted at build); the client-roster MRR (Health tab) rides beside as a
cross-source check with any drift DISCLOSED, never hidden.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KV_CONFIG = "projection:config"
_KV_CONFIG_JOURNAL = "projection:config_journal"

# Config defaults: horizon 12 months; default renewal assumption 0% — the
# HONEST default (historical: 0/12 finished clients re-signed). The slider is
# the what-if; the default is config, journaled when changed.
CONFIG_DEFAULTS = {"horizon_months": 12, "default_renewal_pct": 0}
_CONFIG_BOUNDS = {"horizon_months": (3, 24), "default_renewal_pct": (0, 100)}


def config() -> dict:
    out = dict(CONFIG_DEFAULTS)
    try:
        import kv_store
        stored = kv_store.get(_KV_CONFIG) or {}
        for k in out:
            if stored.get(k) is not None:
                out[k] = int(stored[k])
    except Exception as e:
        logger.info("projection config fell back to defaults: %s", e)
    return out


def set_config(actor: dict, updates: dict) -> tuple[dict | None, str | None]:
    """Owner-only (route-gated). Journaled {who, when, key, old→new}."""
    cur = config()
    changes = []
    for k, v in (updates or {}).items():
        if k not in CONFIG_DEFAULTS:
            return None, f"unknown config key '{k}'"
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None, f"bad value for {k}"
        lo, hi = _CONFIG_BOUNDS[k]
        if not (lo <= v <= hi):
            return None, f"{k} must be between {lo} and {hi}"
        if v != cur[k]:
            changes.append((k, cur[k], v))
    if not changes:
        return cur, None
    import kv_store
    from helpers import now_sydney
    for k, old, new in changes:
        cur[k] = new
    kv_store.put(_KV_CONFIG, cur)
    j = kv_store.get(_KV_CONFIG_JOURNAL) or []
    for k, old, new in changes:
        j.append({"at": now_sydney().strftime("%Y-%m-%d %H:%M"),
                  "who": (actor or {}).get("user") or "unknown",
                  "key": k, "old": old, "new": new})
    kv_store.put(_KV_CONFIG_JOURNAL, j[-100:])
    return cur, None


# ── month helpers ────────────────────────────────────────────────────────────

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _label(y: int, m: int) -> str:
    return f"{_MONTHS[m - 1]} {y}"


def _horizon_labels(today, n: int) -> list[str]:
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append(_label(y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _label_bounds(label: str):
    """(first_day, last_day) of a 'Month YYYY' label."""
    import calendar
    import datetime as dt
    name, year = label.rsplit(" ", 1)
    m = _MONTHS.index(name) + 1
    y = int(year)
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def _declaration_view(ov: dict) -> dict:
    """Normalise a live declaration for projection: coverage window + value."""
    import datetime as dt

    def _d(v):
        try:
            return dt.date.fromisoformat(str(v)[:10]) if v else None
        except ValueError:
            return None
    kind = ov.get("change_type")
    return {
        "kind": kind,
        "client": ov.get("client_name"),
        "id": ov.get("id"),
        "effective": _d(ov.get("effective_date")),
        "start": _d(ov.get("start_date")) or _d(str(ov.get("created_at") or "")[:10]),
        "new_mrr": ov.get("new_mrr"),
        "amount": ov.get("amount"),
        "cadence": ov.get("cadence"),
        "term_months": ov.get("term_months"),
    }


# ── THE ENGINE ───────────────────────────────────────────────────────────────

def project() -> dict:
    """The two-layer projection. Committed takes NO assumption parameter —
    slider-immunity is structural."""
    from helpers import today_sydney
    import client_overrides
    import forward_mrr
    today = today_sydney()
    cfg = config()
    labels = _horizon_labels(today, cfg["horizon_months"])
    rec = forward_mrr.per_client_recognition()
    degraded = list(rec.get("degraded") or [])
    sheet_clients = rec.get("clients") or {}

    decls = {}
    try:
        for ov in client_overrides.active_overrides():
            decls[client_overrides._norm(ov["client_name"])] = _declaration_view(ov)
    except Exception as e:
        degraded.append({"metric": "forward_projection",
                         "reason": f"declaration store unavailable: {e}"})

    committed = [0.0] * len(labels)
    oneoff_cash = [0.0] * len(labels)
    assumed_pool = [0.0] * len(labels)
    per_client = {}
    all_names = set(sheet_clients) | {d["client"] for d in decls.values()
                                      if d.get("client")}
    for name in sorted(all_names):
        srow = sheet_clients.get(name) or {}
        dv = decls.get(client_overrides._norm(name))
        mrr_now = srow.get("monthly_value") or 0
        if not mrr_now:
            # PROD-CAUGHT (probe, deploy a4684572): the sheet's Monthly
            # Recognized column is blank/0 for most rows — the client's live
            # run-rate is their LATEST non-zero month in the recognition
            # schedule (same tab, same parse). Without this the assumed pool
            # was all zeros and the slider moved nothing — the witnessed
            # dead-slider class all over again.
            for _lbl in labels:
                v = (srow.get("monthly") or {}).get(_lbl)
                if v:
                    mrr_now = v
        if not mrr_now:
            mrr_now = (dv or {}).get("new_mrr") or 0
        row = {"source": "sheet", "committed_until": None, "mrr_now": mrr_now,
               "declared": None}
        covered_until = None
        for i, label in enumerate(labels):
            m0, m1 = _label_bounds(label)
            val = None
            src = None
            if dv:
                row["declared"] = {"kind": dv["kind"],
                                   "effective": str(dv["effective"] or ""),
                                   "cadence": dv.get("cadence")}
                if dv["kind"] == "churn":
                    # committed only until the churn effective date's month
                    if dv["effective"] and m0 >= dv["effective"].replace(day=1):
                        val, src = 0.0, "declared churn"
                elif dv["kind"] == "renewal":
                    if dv.get("cadence") == "one_off":
                        # cash in the start month; no MRR, ever — and the
                        # client's SHEET-committed months ride untouched (a
                        # one-off never displaces contracted recognition)
                        if dv["start"] and m0 <= dv["start"] <= m1:
                            oneoff_cash[i] += float(dv.get("amount") or 0)
                    else:
                        start = dv["start"] or today
                        end = dv["effective"]
                        in_term = (m1 >= start and (end is None or m0 <= end))
                        if in_term and dv.get("new_mrr") is not None:
                            val, src = float(dv["new_mrr"]), "declared resign"
                        elif in_term and dv.get("new_mrr") is None:
                            # legacy renewal without MRR: keep current MRR
                            val, src = float(mrr_now or 0), "declared resign (MRR unchanged)"
                elif dv["kind"] in ("downgrade", "downsell"):
                    # downsell (CSM wave) projects exactly like a downgrade:
                    # the floor MRR caps the sheet-committed months from the
                    # effective date on.
                    if dv["effective"] and m1 >= dv["effective"] \
                            and dv.get("new_mrr") is not None:
                        sheet_v = (srow.get("monthly") or {}).get(label)
                        if sheet_v:
                            val = min(float(dv["new_mrr"]), sheet_v)
                            src = "declared " + dv["kind"]
                elif dv["kind"] == "expansion":
                    # EXPANSION (CSM wave): an ADDITIVE stream on top of the
                    # client's base recognition — the sheet months ride
                    # untouched (val stays None so the sheet block below still
                    # applies). One-off → cash in its start month, never MRR.
                    if dv.get("cadence") == "one_off":
                        if dv["start"] and m0 <= dv["start"] <= m1:
                            oneoff_cash[i] += float(dv.get("amount") or 0)
                    else:
                        try:
                            import client_overrides as _co
                            _norm_add = _co.normalize_mrr(
                                float(dv.get("amount") or 0),
                                dv.get("cadence") or "monthly")
                        except Exception:
                            _norm_add = None
                        start = dv["start"] or today
                        end = dv["effective"]
                        if _norm_add and m1 >= start and (end is None or m0 <= end):
                            committed[i] += float(_norm_add)
                            row["source"] = "declaration"
            if val is None and src is None:
                sheet_v = (srow.get("monthly") or {}).get(label)
                if sheet_v:
                    val, src = float(sheet_v), "sheet"
            if val:
                committed[i] += val
                covered_until = label
                if src != "sheet":
                    row["source"] = "declaration"
        row["committed_until"] = covered_until
        # THE ASSUMED POOL: every month AFTER this client's committed coverage
        # ends (a churn declaration removes them — churned is decided, not
        # undecided). A client committed through October is undecided from
        # November on: current MRR × the assumption is the what-if layer.
        churned = bool(dv and dv["kind"] == "churn")
        if not churned and mrr_now:
            last_committed = -1
            for i, label in enumerate(labels):
                m0, m1 = _label_bounds(label)
                has_committed = False
                if dv and dv["kind"] == "renewal" and dv.get("cadence") != "one_off":
                    end = dv["effective"]
                    if end and m0 <= end and (dv["start"] is None or m1 >= dv["start"]):
                        has_committed = True
                if (srow.get("monthly") or {}).get(label):
                    has_committed = True
                if has_committed:
                    last_committed = i
            for i in range(last_committed + 1, len(labels)):
                assumed_pool[i] += float(mrr_now)
        per_client[name] = row

    committed = [round(v, 2) for v in committed]
    assumed_pool = [round(v, 2) for v in assumed_pool]
    oneoff_cash = [round(v, 2) for v in oneoff_cash]

    # ── month-0 reconciliation: the projection's base == the present truth ──
    recon = {"month0_committed": committed[0] if committed else None,
             "recognized_now": None, "exact": None,
             "roster_mrr": None, "roster_drift": None}
    try:
        cur_label = labels[0]
        sheet_now = round(sum((c.get("monthly") or {}).get(cur_label) or 0
                              for c in sheet_clients.values()), 2)
        recon["recognized_now"] = sheet_now
        # committed month-0 may legitimately differ from the raw sheet ONLY by
        # a declaration whose coverage touches month 0 — that overlay is
        # DISCLOSED (declaration_delta); anything else is drift, flagged.
        decl_delta = round(committed[0] - sheet_now, 2) if committed else None
        recon["declaration_delta"] = decl_delta
        m0_start, m0_end = _label_bounds(cur_label)
        touching = [d["client"] for d in decls.values()
                    if (d["kind"] == "churn" and d["effective"]
                        and d["effective"] <= m0_end)
                    or (d["kind"] in ("renewal", "downgrade", "downsell", "expansion")
                        and (d["start"] is None or d["start"] <= m0_end)
                        and (d["effective"] is None or d["effective"] >= m0_start))]
        recon["declarations_touching_month0"] = touching
        recon["exact"] = bool(committed and (abs(decl_delta) < 0.01
                                             or (decl_delta and touching)))
    except Exception as e:
        degraded.append({"metric": "forward_projection",
                         "reason": f"reconciliation leg failed: {e}"})
    try:
        from snapshot import load_persisted
        ch = (load_persisted() or {}).get("client_health") or {}
        if ch.get("current_mrr") is not None:
            recon["roster_mrr"] = ch["current_mrr"]
            if recon["month0_committed"] is not None:
                recon["roster_drift"] = round(
                    recon["month0_committed"] - ch["current_mrr"], 2)
                recon["roster_note"] = ("Health-tab roster MRR vs RECOGNIZED-tab "
                                        "month-0 — different sheet tabs; drift "
                                        "disclosed, never hidden")
    except Exception:
        pass

    return {
        "months": labels,
        "committed": committed,
        "assumed_pool": assumed_pool,
        "oneoff_cash": oneoff_cash,
        "default_renewal_pct": cfg["default_renewal_pct"],
        "horizon_months": cfg["horizon_months"],
        "assumption_formula": "assumed[m] = assumed_pool[m] × renewal_pct / 100 "
                              "(what-if — the slider layer; committed is "
                              "slider-immune by construction)",
        "historical_note": "historical renewal rate: 0/12 finished clients "
                           "re-signed — the honest default is 0%",
        "per_client": per_client,
        "reconciliation": recon,
        "degraded": degraded,
        "ok": not degraded,
    }


# ── sentinel watch (rides ad_sentinel.nightly_extras) ────────────────────────

def sentinel_watch() -> dict:
    """Committed-vs-recognized drift (month-0 must reconcile) · warning-clear
    integrity (every live renewal/churn declaration has a journal line)."""
    out = {}
    try:
        p = project()
        r = p.get("reconciliation") or {}
        out["month0"] = {"committed": r.get("month0_committed"),
                         "recognized_now": r.get("recognized_now"),
                         "declaration_delta": r.get("declaration_delta"),
                         "ok": bool(r.get("exact"))}
        if not out["month0"]["ok"]:
            _feed(f"forward projection month-0 DRIFT: committed "
                  f"{r.get('month0_committed')} vs recognized "
                  f"{r.get('recognized_now')} with no declaration explaining it",
                  loud=True)
    except Exception as e:
        out["month0"] = {"error": str(e)[:100]}
    try:
        import client_overrides
        import renewal_loop
        jn = renewal_loop.journal_entries()
        jtext = " ".join(str(e.get("detail") or "") for e in jn)
        missing = [ov["client_name"] for ov in client_overrides.active_overrides()
                   if ov["client_name"] not in jtext]
        out["clear_integrity"] = {"live_declarations_unjournaled": missing}
        if missing:
            _feed(f"warning-clear integrity: {len(missing)} live declaration(s) "
                  f"with no journal line — {missing[:3]}", loud=True)
    except Exception as e:
        out["clear_integrity"] = {"error": str(e)[:80]}
    return out


def _feed(msg: str, loud: bool = False) -> None:
    try:
        import ad_sentinel
        ad_sentinel._feed(msg, loud=loud)
    except Exception:
        pass
