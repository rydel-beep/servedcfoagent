"""metrics_statement.py — "TODAY'S NUMBERS, VERIFIED" (#171, Phase 5).

Each morning (and on demand) the statement lists every headline unit-
economics metric with its value, window, inputs, sources, as-of and
coverage — and then REPRODUCES the two ratios by hand from the listed closes
and cost lines. The identity that must hold, exactly as the engine defines
the ratio:

    LTV:CAC  = ( Σ expected LTV over closes with a contract ÷ k )
             ÷ ( Σ acquisition cost in the window ÷ n )
    LTGP:CAC = the same with each LTV × gross margin

where k = closes carrying a contract value and n = every close in the window
(cost is spread across all of them; the coverage line says k of n). The
statement sums the listed rows itself; if its figure differs from the
engine's by more than 0.01×, the identity check FAILS, the tiles show
"check failed — being investigated" instead of a number, and a loud finding
is raised. Nothing here invents a number: a metric the engine withholds is
listed as withheld with the reason.

EDITH answers "how are we doing on sales vs acquisition cost" from the
statement — one direct sentence first (the answer contract).
"""
from __future__ import annotations

import logging
import re

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_LATEST = "statement:latest"
K_DAY = "statement:day:"          # + YYYY-MM-DD
K_IDENTITY = "statement:identity"
TOLERANCE = 0.011                 # ratios are published at 2 dp


def _reproduce(w: dict, margin_pct: float) -> dict:
    """Σ over the LISTED rows and cost lines — never the engine's own totals."""
    rows = w.get("rows") or []
    known = [r for r in rows if r.get("floor") is not None]
    k, n = len(known), int(w.get("closes") or 0)
    comps = w.get("cac_components") or []
    acq = round(sum(float(c.get("amount") or 0) for c in comps), 2)
    out = {"k": k, "n": n, "sum_expected_ltv": round(sum(float(r.get("expected") or 0) for r in known
                                                        if r.get("expected") is not None), 2),
           "sum_floor_ltv": round(sum(float(r.get("floor") or 0) for r in known), 2),
           "sum_acquisition": acq, "components": comps,
           "expected_known": sum(1 for r in known if r.get("expected") is not None)}
    if not n or not acq:
        out.update({"ltv_cac": None, "ltgp_cac": None, "ltv_cac_floor": None, "ltgp_cac_floor": None,
                    "note": "no closes or no acquisition cost in the window — ratio undefined"})
        return out
    cac = round(acq / n, 2)
    out["cac_per_close"] = cac
    if out["expected_known"]:
        avg_exp = round(out["sum_expected_ltv"] / out["expected_known"], 2)
        out["ltv_cac"] = round(avg_exp / cac, 2)
        out["ltgp_cac"] = round(avg_exp * margin_pct / 100 / cac, 2)
    else:
        out["ltv_cac"] = out["ltgp_cac"] = None
    if k:
        avg_fl = round(out["sum_floor_ltv"] / k, 2)
        out["ltv_cac_floor"] = round(avg_fl / cac, 2)
        out["ltgp_cac_floor"] = round(avg_fl * margin_pct / 100 / cac, 2)
    else:
        out["ltv_cac_floor"] = out["ltgp_cac_floor"] = None
    return out


def _check(engine_val, hand_val) -> dict:
    if engine_val is None and hand_val is None:
        return {"ok": True, "engine": None, "hand": None, "note": "both undefined"}
    if engine_val is None or hand_val is None:
        return {"ok": False, "engine": engine_val, "hand": hand_val,
                "note": "one side is undefined and the other is not"}
    return {"ok": abs(float(engine_val) - float(hand_val)) <= TOLERANCE,
            "engine": engine_val, "hand": hand_val,
            "diff": round(float(engine_val) - float(hand_val), 3)}


def _metric(name, value, unit, window, inputs, sources, as_of, coverage, meaning, floor=None, band=None):
    return {"name": name, "value": value, "floor": floor, "unit": unit, "window": window,
            "inputs": inputs, "sources": sources, "as_of": as_of, "coverage": coverage,
            "band": band, "meaning": meaning,
            "withheld": value is None}


def generate(view: dict | None = None, force_mismatch: bool = False) -> dict:
    """Build + store the statement. force_mismatch is for the drill only: it
    perturbs the hand figure so the failure path can be proved end to end."""
    import unit_econ_engine as UE
    import freshness as F
    v = view or UE.view()
    inp, margin = v.get("inputs") or {}, (v.get("margin") or {})
    m_pct = float(margin.get("pct") or 0)
    h, mtd = v.get("headline") or {}, v.get("mtd") or {}
    try:
        src = {r["key"]: r for r in F.sources().get("rows", [])}
    except Exception as e:  # noqa: BLE001
        src = {"_error": str(e)[:120]}
    as_of = v.get("as_of")

    def _src_words(keys):
        bits = []
        for key in keys:
            r = src.get(key) if isinstance(src, dict) else None
            if r:
                bits.append(f"{r['label']}: {r['age_words']} ({r['status']})")
        return bits or ["source freshness unavailable"]

    inputs_words = ([f"renewal {inp['renewal_pct']}% (n={inp['renewal_n']}, 95% "
                     f"{inp['renewal_ci95']})", f"completion {inp['completion_pct']}% "
                     f"(n={inp['completion_n']})", f"horizon {inp['horizon_months']} months",
                     f"gross margin {m_pct}% — {margin.get('provenance')}"]
                    if inp.get("measured") else [inp.get("note") or "inputs not measured"])
    metrics = []
    for wk, w, label in (("headline", h, "trailing 90 days"), ("mtd", mtd, "month to date")):
        win = w.get("window") or {}
        wwords = f"{label} · {win.get('start')} → {win.get('end')} · closed in the window"
        cov = w.get("coverage") or {}
        sens = w.get("sensitivity") or {}
        for key, nm, meaning in (("ltv_cac", "LTV:CAC",
                                  "for every $1 it cost to win a client, the dollars of revenue "
                                  "they are expected to pay over their whole time with us"),
                                 ("ltgp_cac", "LTGP:CAC",
                                  "for every $1 it cost to win a client, the gross profit they are "
                                  "expected to leave us")):
            metrics.append(_metric(
                f"{nm} ({label})", w.get(f"{key}_expected"), "×", wwords, inputs_words,
                _src_words(("tracker_mirror", "stripe", "ghl_opportunities", "meta_today", "engine_blocks")),
                as_of, cov.get("line"), meaning, floor=w.get(f"{key}_floor"),
                band=({"renewal": [sens.get("renewal_low"), sens.get("renewal_high")],
                       "ratio": [sens.get(f"{key}_low"), sens.get(f"{key}_high")]}
                      if sens.get(f"{key}_low") is not None else None)))
        metrics.append(_metric(
            f"CAC loaded ({label})", w.get("cac_loaded"), "$ per close", wwords,
            [f"{c['label']} ${float(c['amount'] or 0):,.2f}" for c in (w.get("cac_components") or [])]
            + ([f"commission pending on {w['commission_pending']} close(s) — not counted; "
                f"rulebook range {w.get('commission_pending_range')}"] if w.get("commission_pending") else []),
            _src_words(("meta_today", "tracker_mirror", "engine_blocks")), as_of, cov.get("line"),
            "everything it cost to win the closes in this window, spread across them"))

    # THE HAND CHECK — headline and month to date, expected and floor
    checks = {}
    for wk, w in (("headline", h), ("mtd", mtd)):
        rep = _reproduce(w, m_pct)
        if force_mismatch and rep.get("ltv_cac") is not None:
            rep["ltv_cac"] = round(rep["ltv_cac"] + 0.5, 2)
            rep["forced"] = True
        checks[wk] = {
            "reproduction": rep,
            "ltv_cac": _check(w.get("ltv_cac_expected"), rep.get("ltv_cac")),
            "ltgp_cac": _check(w.get("ltgp_cac_expected"), rep.get("ltgp_cac")),
            "ltv_cac_floor": _check(w.get("ltv_cac_floor"), rep.get("ltv_cac_floor")),
            "ltgp_cac_floor": _check(w.get("ltgp_cac_floor"), rep.get("ltgp_cac_floor")),
        }
    failed = [f"{wk} {k}" for wk, c in checks.items()
              for k in ("ltv_cac", "ltgp_cac", "ltv_cac_floor", "ltgp_cac_floor") if not c[k]["ok"]]
    identity = {"ok": not failed, "at": now_sydney().isoformat(),
                "failed": failed,
                "detail": ("; ".join(f"{f}: engine {checks[f.split()[0]][f.split()[1]]['engine']} vs "
                                     f"hand {checks[f.split()[0]][f.split()[1]]['hand']}" for f in failed)
                           if failed else "Σ LTGP ÷ Σ acquisition cost reproduced the engine to 0.01×")}
    kv_store.put(K_IDENTITY, identity)

    # the reconciliation + the queue
    try:
        import close_register as CR
        recon = CR.reconciliation_latest() or {}
        queue = CR.missing_details_queue(limit=12)
    except Exception as e:  # noqa: BLE001
        recon, queue = {"error": str(e)[:120]}, {"rows": [], "total": 0}
    stmt = {
        "title": "Today's numbers, verified",
        "date": str(today_sydney()), "generated_at": now_sydney().isoformat(),
        "as_of": as_of, "metrics": metrics, "identity": identity, "checks": checks,
        "coverage": {"headline": h.get("coverage"), "mtd": mtd.get("coverage")},
        "benchmark": v.get("benchmark"),
        "reconciliation": {"at": recon.get("at"), "ok": recon.get("ok"),
                           "findings": (recon.get("findings") or [])[:12],
                           "count": len(recon.get("findings") or [])},
        "queue": {"total": queue.get("total"), "rows": [
            {"client": r.get("client") or r.get("person"), "close_date": r.get("close_date"),
             "gaps": r.get("gaps")} for r in queue.get("rows") or []]},
        "walkin_conversion": v.get("walkin_conversion"),
    }
    kv_store.put(K_LATEST, stmt)
    kv_store.put(K_DAY + stmt["date"], stmt)
    if failed:
        try:
            kv_store.put("feed:extra:statement", [{
                "kind": "identity_check_failed", "severity": "S1",
                "title": "the verified statement could not reproduce the ratio by hand",
                "detail": identity["detail"], "action": "the LTV:CAC tiles are withheld until it passes"}])
        except Exception:  # noqa: BLE001
            pass
    else:
        kv_store.put("feed:extra:statement", [])
    # the tiles read the identity flag through the engine view → rebuild them
    try:
        from dashboard import exec_top
        exec_top.refresh_cache()
    except Exception as e:  # noqa: BLE001
        logger.info("statement: tile refresh skipped: %s", e)
    return stmt


def latest() -> dict | None:
    return kv_store.get(K_LATEST)


def daily_tick() -> bool:
    """Once each morning after 06:00 Sydney (rides the freshness loop)."""
    t = today_sydney()
    if now_sydney().hour < 6:
        return False
    if kv_store.get(K_DAY + str(t)):
        return False
    if not kv_store.put_if_absent(f"statement:lock:{t}", {"at": now_sydney().isoformat()}):
        return False
    try:
        generate()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("statement: daily generation failed: %s", e)
        kv_store.delete(f"statement:lock:{t}")
        return False


# ── EDITH ───────────────────────────────────────────────────────────────────

_STATEMENT_RE = re.compile(
    r"how are we (doing|going|tracking) on sales (vs|versus|against) (acquisition|cac)|"
    r"sales (vs|versus|against) (cost of )?acquisition|verified (numbers|statement)|"
    r"today'?s numbers,? verified|are the numbers verified", re.I)


def handle_statement_command(text: str) -> tuple[str | None, bool]:
    if not text or not _STATEMENT_RE.search(text):
        return None, False
    s = latest()
    if not s:
        return ("The verified statement hasn't been generated yet today — it runs each "
                "morning; ask again in a few minutes or open Today to generate it."), True
    m = {x["name"]: x for x in s["metrics"]}
    ltv, ltgp = m.get("LTV:CAC (trailing 90 days)") or {}, m.get("LTGP:CAC (trailing 90 days)") or {}
    bench = (s.get("benchmark") or {}).get("value") or 3.0
    if not s["identity"]["ok"]:
        return (f"I can't give you a verified ratio right now: the hand check failed "
                f"({s['identity']['detail']}) and the tiles are withheld until it passes."), True
    if ltv.get("value") is None:
        return (f"Over the last 90 days the ratio is undefined — "
                f"{ltv.get('coverage') or 'no close carries a contract value'}."), True
    v = ltv["value"]
    verdict = ("above" if v >= bench else "below")
    first = (f"Over the last 90 days we expect {ltgp.get('value') or 0:.2f} dollars of gross profit "
             f"for every dollar spent winning a client (LTGP:CAC {ltgp.get('value')}×) — "
             f"LTV:CAC {v:.2f}×, {verdict} the {bench:.0f}:1 benchmark, verified by hand this morning.")
    parts = [first]
    if ltv.get("floor") is not None:
        parts.append(f"On signed contracts alone it is {ltv['floor']:.2f}×.")
    if ltv.get("coverage"):
        parts.append(f"That is {ltv['coverage']}.")
    if ltv.get("band") and ltv["band"].get("ratio") and ltv["band"]["ratio"][0] is not None:
        b = ltv["band"]
        parts.append(f"Across the renewal range {b['renewal'][0]:.0f}–{b['renewal'][1]:.0f}% it "
                     f"runs {b['ratio'][0]:.2f}×–{b['ratio'][1]:.2f}×.")
    q = s.get("queue") or {}
    if q.get("total"):
        parts.append(f"{q['total']} close(s) are still missing details — filling them moves this.")
    r = s.get("reconciliation") or {}
    if r.get("count"):
        parts.append(f"The nightly cross-check has {r['count']} open finding(s).")
    return " ".join(parts), True
