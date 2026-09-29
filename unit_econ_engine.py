"""unit_econ_engine.py — THE ONE UNIT-ECONOMICS ENGINE (#170, Rydel 29 Sep).

LTV, CAC, LTGP and both ratios, to the brief's definitions and nothing else:

  CAC (LOADED)   = acquisition cost in the window ÷ closes in the window —
                   sales_cost's TRUE CAC (ad spend + rulebook commissions +
                   set bounties + manager retainer + sales tooling). Spend-
                   only beside. Commission for an unruled package is PENDING
                   (counted nowhere, named).
  LTV EXPECTED   = per close, from the close's own package:
                   contract ex-GST × MEASURED in-term completion
                   + Σ_k renewal^k × the renewal term's value (the signed
                     term, re-priced at the signed contract), for as many
                     whole renewal terms as fit inside the HORIZON CAP
                     (default 36 months — never an unbounded series).
                   Renewal is credited only to retainer packages (the
                   measurement's own population). Expansion: EXCLUDED — not
                   measured.
  LTV FLOOR      = the signed contract ex-GST. No renewals, no completion
                   haircut, no expansion — the certain number.
  LTGP           = LTV × gross margin (pl_engine: management-basis trailing-3,
                   FY26 63.8% as the labelled fallback).
  RATIOS         = average per-close LTV (closes that carry a contract) ÷
                   CAC per close — expected AND floor — on TRAILING 90 DAYS
                   (the headline), month to date (labelled "few closes —
                   moves a lot") and the latest mature cohort (≥ 60 days).

The inputs are MEASURED from payment history (csm_baselines.
measure_from_payments), re-measured monthly and stored with n and the 95%
interval. Never measured → expected is None and says so. A placeholder or a
bound is never used as an estimate.
"""
from __future__ import annotations

import datetime as dt
import logging
import os

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_MEASURED = "unit_econ:measured"
HORIZON_MONTHS = int(os.getenv("LTV_HORIZON_MONTHS", "36"))
MATURE_DAYS = 60
BENCHMARK = 3.0


# ── the measured inputs ─────────────────────────────────────────────────────

def measured() -> dict | None:
    return kv_store.get(K_MEASURED)


def inputs() -> dict:
    m = measured() or {}
    ren = m.get("renewal") or {}
    com = m.get("completion") or {}
    ok = ren.get("value") is not None and com.get("value") is not None
    return {
        "measured": ok,
        "measured_on": m.get("measured"),
        "renewal_pct": ren.get("value"), "renewal_n": ren.get("n"),
        "renewal_ci95": ren.get("ci95"),
        "renewal_excluded": ren.get("n_excluded"),
        "completion_pct": com.get("value"), "completion_n": com.get("n"),
        "horizon_months": HORIZON_MONTHS,
        "method": m.get("method"),
        "note": (None if ok else "renewal/completion not yet measured — "
                 "expected LTV is withheld; the floor stands alone"),
    }


def _fetch_payment_history(days: int = 550):
    """Read-only: Stripe charges by direct GET (the cash_truth reader writes
    a partial marker, so it isn't used here), matched by the one matcher,
    plus the tracker's won rows for package, start and contract."""
    import calendar
    import re
    from helpers import SYDNEY_TZ
    from payback_reconciliation import _sget
    import stripe_reconcile as SR
    import unmatched_payments as UP
    import attribution_engine as AE

    def _n(s):
        return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

    since = today_sydney() - dt.timedelta(days=days)
    params = {"limit": 100, "created[gte]": calendar.timegm(since.timetuple()),
              "expand[]": ["data.customer"]}
    raw, after = [], None
    for _ in range(30):
        p = dict(params)
        if after:
            p["starting_after"] = after
        r = _sget("/v1/charges", p)
        if r.get("error"):
            raise RuntimeError(f"stripe: {str(r['error'])[:120]}")
        raw.extend(r.get("data") or [])
        if not r.get("has_more"):
            break
        after = raw[-1]["id"]
    else:
        raise RuntimeError("stripe pagination cap hit — history truncated")
    data_start = since
    if raw:
        data_start = dt.datetime.fromtimestamp(min(c["created"] for c in raw),
                                               tz=SYDNEY_TZ).date()
    idx, roster = UP._index()
    if idx is None:
        raise RuntimeError("tracker mirror unreadable")
    by_client, unmatched = {}, 0
    for c in raw:
        if not (c.get("paid") and c.get("status") == "succeeded"):
            continue
        amt = ((c.get("amount") or 0) - (c.get("amount_refunded") or 0)) / 100.0
        if amt <= 0:
            continue
        cust = c.get("customer") if isinstance(c.get("customer"), dict) else {}
        bd = c.get("billing_details") or {}
        m = SR._match_payment(cust.get("name") or bd.get("name") or "",
                              (cust.get("email") or bd.get("email")
                               or c.get("receipt_email") or "").lower(),
                              amt, idx, roster)
        if not m.get("business"):
            unmatched += 1
            continue
        d = dt.datetime.fromtimestamp(c["created"], tz=SYDNEY_TZ).date()
        by_client.setdefault(m["business"], []).append((d, amt))
    leads, _ = AE.parse_tracker(AE._tracker_rows_clean())
    leads, _f = AE.dedupe_won(leads)
    won = {}
    for l in leads:
        if l.get("won"):
            for k in (l.get("business"), l.get("name")):
                if _n(k):
                    won.setdefault(_n(k), l)
    deals, no_row = {}, []
    for client in by_client:
        l = won.get(_n(client))
        if l is None:
            no_row.append(client)
            continue
        cd = l.get("close_date")
        deals[client] = {"offer": l.get("offer"), "contract": l.get("contract"),
                         "close_date": dt.date.fromisoformat(str(cd)[:10]) if cd else None}
    return by_client, deals, data_start, {"charges": len(raw),
                                          "unmatched_charges": unmatched,
                                          "clients_without_won_row": no_row}


def remeasure() -> dict:
    """THE SENTINEL'S MONTHLY RE-MEASUREMENT — stored with n and the CI."""
    import csm_baselines as B
    by_client, deals, data_start, meta = _fetch_payment_history()
    out = B.measure_from_payments(by_client, deals, today_sydney(), data_start)
    out["coverage"] = meta
    out["at"] = now_sydney().isoformat()
    out["month"] = str(today_sydney())[:7]
    prior = measured()
    kv_store.put(K_MEASURED, out)
    try:
        import close_register as CR
        CR.journal("measurement",
                   f"renewal {out['renewal']['value']}% (n={out['renewal']['n']}, "
                   f"95% {out['renewal']['ci95']}); completion "
                   f"{out['completion']['value']}% (n={out['completion']['n']})"
                   + (f" — was renewal {prior['renewal']['value']}%, completion "
                      f"{prior['completion']['value']}%" if prior else ""),
                   "sentinel", {})
    except Exception as e:  # noqa: BLE001
        logger.info("unit econ: measurement journal failed: %s", e)
    return out


def monthly_tick() -> bool:
    """Re-measure once per calendar month (and on a cold store)."""
    m = measured()
    if m and m.get("month") == str(today_sydney())[:7]:
        return False
    if not kv_store.put_if_absent(f"unit_econ:remeasure:{str(today_sydney())[:7]}",
                                  {"at": now_sydney().isoformat()}):
        return False
    try:
        remeasure()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("unit econ re-measure failed: %s", e)
        kv_store.delete(f"unit_econ:remeasure:{str(today_sydney())[:7]}")
        return False


# ── per close ───────────────────────────────────────────────────────────────

def _term_and_package(e: dict) -> tuple[str | None, int | None, str]:
    import csm_baselines as B
    from config import PACKAGE_TERMS
    pkg = B._pkg_key(e.get("package") or e.get("offer"))
    if e.get("term_months"):
        return pkg, int(e["term_months"]), "ruled term"
    if pkg:
        return pkg, int(PACKAGE_TERMS.get(pkg) or B.RETAINER_TERMS[pkg]), "package term (config)"
    return None, None, "package unknown"


def ltv_for(e: dict, inp: dict, renewal_pct: float | None = None) -> dict:
    """One close's LTV — expected and floor — with its working."""
    import csm_baselines as B
    cv = (e.get("contract") or {}).get("value")
    person = e.get("person")
    if cv is None:
        return {"person": person, "floor": None, "expected": None,
                "why": "no contract value — LTV pending (named, not zero)"}
    cv = float(cv)
    pkg, term, term_src = _term_and_package(e)
    row = {"person": person, "client": e.get("client"), "package": pkg,
           "term_months": term, "term_source": term_src, "contract_ex_gst": cv,
           "contract_source": (e.get("contract") or {}).get("source"),
           "floor": round(cv, 2)}
    if not inp.get("measured"):
        row.update({"expected": None, "why": inp.get("note")})
        return row
    p = (renewal_pct if renewal_pct is not None else inp["renewal_pct"]) / 100.0
    c = inp["completion_pct"] / 100.0
    in_term = cv * c
    renewals = []
    if pkg in B.RETAINER_TERMS and term:
        for k in range(1, max(0, (HORIZON_MONTHS - term) // term) + 1):
            renewals.append(round(cv * p ** k, 2))
        basis = (f"${cv:,.0f} × {c * 100:.1f}% completion + "
                 f"{len(renewals)} renewal term(s) at {p * 100:.1f}%^k × ${cv:,.0f} "
                 f"(horizon {HORIZON_MONTHS} months)")
    else:
        why = ("not a retainer package" if (pkg or e.get("package") or e.get("term_months"))
               else "package unknown")
        basis = (f"${cv:,.0f} × {c * 100:.1f}% completion — no renewal "
                 f"credited ({why})")
    row.update({"in_term": round(in_term, 2), "renewals": renewals,
                "expected": round(in_term + sum(renewals), 2), "working": basis})
    return row


# ── a window ────────────────────────────────────────────────────────────────

def _margin() -> tuple[float, str]:
    try:
        import pl_engine
        gm = pl_engine.gross_margin_for_ltgp()
        return float(gm["pct"]), gm["provenance"]
    except Exception as e:  # noqa: BLE001
        return 63.8, f"FY26 gross margin 63.8% (labelled fallback: {str(e)[:60]})"


def window(w0, w1, name: str, clock: str = "activity",
           inp: dict | None = None, margin: tuple | None = None) -> dict:
    import close_register as CR
    import sales_cost
    inp = inp or inputs()
    m_pct, m_prov = margin or _margin()
    entries = CR.closes(str(w0), str(w1), clock)
    rows = [ltv_for(e, inp) for e in entries]
    sc = sales_cost.build(str(w0), str(w1)) if clock == "activity" else None
    if clock == "cohort":
        # cohort CAC: the cohort month's acquisition cost ÷ the closes its
        # leads produced (any close date)
        sc = sales_cost.build(str(w0), str(w1))
    n = len(entries)
    acq = (sc or {}).get("true_cac", {}).get("total")
    spend = (sc or {}).get("true_cac", {}).get("ad_spend")
    cac = round(acq / n, 2) if n and acq is not None else None
    cac_spend = round((spend or 0) / n, 2) if n and spend is not None else None
    known = [r for r in rows if r["floor"] is not None]
    k = len(known)

    def _avg(key, rs=known):
        vals = [r[key] for r in rs if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    ltv_exp, ltv_floor = _avg("expected"), _avg("floor")

    def _ratio(x, mult=1.0):
        return round(x * mult / cac, 2) if (x is not None and cac) else None

    out = {
        "name": name, "window": {"start": str(w0), "end": str(w1), "clock": clock},
        "closes": n, "ltv_known": k,
        "ltv_pending": [r["person"] for r in rows if r["floor"] is None],
        "cac_loaded": cac, "cac_spend_only": cac_spend,
        "acquisition_total": acq,
        "cac_components": (sc or {}).get("true_cac", {}).get("components"),
        "commission_pending": ((sc or {}).get("commissions") or {}).get("pending_deals"),
        "commission_pending_range": ((sc or {}).get("commissions") or {}).get("pending_range"),
        "ltv_expected": ltv_exp, "ltv_floor": ltv_floor,
        "ltgp_expected": round(ltv_exp * m_pct / 100, 2) if ltv_exp is not None else None,
        "ltgp_floor": round(ltv_floor * m_pct / 100, 2) if ltv_floor is not None else None,
        "ltv_cac_expected": _ratio(ltv_exp), "ltv_cac_floor": _ratio(ltv_floor),
        "ltgp_cac_expected": _ratio(ltv_exp, m_pct / 100),
        "ltgp_cac_floor": _ratio(ltv_floor, m_pct / 100),
        "rows": rows,
        "few_closes": n < 8,
    }
    # SENSITIVITY — the renewal interval carried through the same maths
    ci = inp.get("renewal_ci95")
    if inp.get("measured") and ci and k and cac:
        lo = [ltv_for(e, inp, ci[0]) for e in entries]
        hi = [ltv_for(e, inp, ci[1]) for e in entries]
        out["sensitivity"] = {
            "renewal_low": ci[0], "renewal_high": ci[1],
            "ltv_cac_low": _ratio(_avg("expected", lo)),
            "ltv_cac_high": _ratio(_avg("expected", hi)),
            "ltgp_cac_low": _ratio(_avg("expected", lo), m_pct / 100),
            "ltgp_cac_high": _ratio(_avg("expected", hi), m_pct / 100)}
    return out


def _mature_cohort_month(today: dt.date) -> tuple[dt.date, dt.date]:
    m1 = today.replace(day=1) - dt.timedelta(days=1)
    while (today - m1).days < MATURE_DAYS:
        m1 = m1.replace(day=1) - dt.timedelta(days=1)
    return m1.replace(day=1), m1


def view() -> dict:
    """Every surface reads THIS — Today, Money, Plan, Ads, SALES, EDITH."""
    t = today_sydney()
    inp = inputs()
    margin = _margin()
    c0, c1 = _mature_cohort_month(t)
    out = {
        "as_of": now_sydney().isoformat(),
        "inputs": inp,
        "margin": {"pct": margin[0], "provenance": margin[1]},
        "benchmark": {"value": BENCHMARK, "label": "3:1 — benchmark, not target"},
        "headline": window(t - dt.timedelta(days=89), t, "trailing_90d", inp=inp, margin=margin),
        "mtd": window(t.replace(day=1), t, "mtd", inp=inp, margin=margin),
        "mature_cohort": window(c0, c1, f"cohort {c0:%b %Y}", clock="cohort",
                                inp=inp, margin=margin),
    }
    out["mtd"]["label"] = "month to date — few closes, moves a lot"
    out["mature_cohort"]["label"] = (f"{c0:%B} leads (≥ {MATURE_DAYS} days old) — "
                                     "that month's cost ÷ the closes its leads produced")
    return out
