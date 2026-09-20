"""compass_engine.py — THE SCALING COMPASS (forward + backward planning).

Given the rates we've MEASURED, what spend, leads, calls, closes, cash and
people does it take to hit a target MRR or cash-collected by a date — and
which constraint is binding each month.

THE EQUATION (per market lane, per month):
  Spend ÷ CPL(S) = Leads · ×set = Calls booked · ×show = Shows · ×close =
  Clients · ×cash schedule per package = Cash · ×MRR per package = MRR added
  · − the cliff (terms ending × (1 − resign)) = Net MRR.
  CPL(S) = CPL₀ × (S/S₀)^ε — never linear.

DOCTRINE:
· ONE ENGINE — every measured default reads the standing engines
  (attribution_engine funnel, meta_spend, finance_analysis closes/receipts,
  forward_projection book, outflow bands, capacity/config). Nothing is
  recomputed locally; the compass only COMPOSES.
· SCENARIO LANE — this module is the scenario engine's forward-model
  extension (scenario_engine.py's charter): every run is a LABELLED
  hypothetical; nothing here ever writes a declaration, the tracker, GHL or
  any actuals store. Scenario pins (client resign toggles) exist only inside
  a request's inputs.
· Assumptions are labelled with provenance + n; small-n honesty everywhere;
  tax accrual is shown BESIDE burn, never inside.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import random

import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

K_DEFAULTS = "compass:defaults"
K_SCENARIOS = "compass:scenarios"
K_PLAN = "compass:plan2027"
K_BACKTEST = "compass:backtest"

HORIZON_END = "2027-12"          # config: the 2027 compass horizon
MIN_CASH_BUFFER = 30000.0        # config default; owner-tunable input
HIRE_LEAD_WEEKS = 8
CPL_THRESHOLD_MULT = 2.0         # leads-constraint: CPL beyond this × CPL₀
CLIENT_FINANCED_BENCHMARK = 2.0  # 30-day cash ÷ CAC (benchmark, not target)
DEFAULT_EPSILON = 0.2            # labelled assumption when the fit lacks n
DEFAULT_LAG = [0.70, 0.20, 0.10]  # labelled fallback close-lag curve
FY26_MARGIN_PCT = 42.9

# capacity throughput defaults (config where unmeasured — labelled)
THROUGHPUT_DEFAULTS = {
    "leads_per_setter_month": 175,     # config (unmeasured — labelled)
    "calls_per_closer_month": 60,      # booked calls a closer can take
    "clients_per_delivery": 7,         # FIXED-COSTS tab tool seats ≈ 7/pod
}
ROLE_COSTS_MONTHLY = {               # Manila lane defaults (config, labelled)
    "setter": 1400.0, "closer": 2500.0, "delivery": 1800.0, "csm": 2000.0,
}
RAMP_WEEKS = {"setter": 4, "closer": 6, "delivery": 6, "csm": 8}


# ── helpers ─────────────────────────────────────────────────────────────────

def _month_add(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m += k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def _item(value, n, window, provenance, assumption=False):
    return {"value": value, "n": n, "window": window,
            "provenance": provenance, "assumption": bool(assumption)}


# ── MEASURED DEFAULTS (kv-cached; refreshed on the scheduled loop) ──────────

def measured_defaults(force: bool = False) -> dict:
    cached = kv_store.get(K_DEFAULTS)
    if cached and not force:
        return cached
    out = {"computed_at": now_sydney().isoformat(), "items": {}}
    it = out["items"]
    t = today_sydney()
    w0, w1 = t - dt.timedelta(days=89), t
    win = f"{w0}→{w1} (90d)"

    # funnel counts — the ONE attribution engine
    leads_n = sets_n = shows_n = 0
    won_leads = []
    lag_pairs = []
    mix: dict[str, int] = {}
    markets = {"au": 0, "us": 0, "unknown": 0}
    try:
        import attribution_engine as AE
        res = AE.compute(start=str(w0), end=str(w1), basis="activity")
        for c in res.get("creatives", []):
            leads_n += c.get("leads") or 0
            sets_n += c.get("sets") or 0
            shows_n += c.get("shows") or 0
    except Exception as e:  # noqa: BLE001
        logger.warning("compass funnel read failed: %s", e)

    # per-lead detail for lag/mix/lanes (same engine's row loader + won-dedupe)
    leads_all = []
    try:
        import attribution_engine as AE
        rows = AE._tracker_rows_clean()
        leads_all, _cm = AE.parse_tracker(rows)
        leads_all, _dupes = AE.dedupe_won(leads_all)
    except Exception as e:  # noqa: BLE001
        logger.warning("compass lead-detail read failed: %s", e)
    lag_window0 = t - dt.timedelta(days=179)
    for l in leads_all or []:
        try:
            idate = l.get("input_date")
            if idate and w0 <= idate <= w1:
                mk = (l.get("market") or "unknown").lower()
                markets[mk if mk in markets else "unknown"] += 1
            if l.get("won") and l.get("close_date"):
                cd = l["close_date"]
                if lag_window0 <= cd <= w1:
                    offer = (l.get("offer") or "unknown").strip().lower() or "unknown"
                    mix[offer] = mix.get(offer, 0) + 1
                    if idate:
                        off = (cd.year - idate.year) * 12 + cd.month - idate.month
                        lag_pairs.append(max(0, min(off, 5)))
        except Exception:
            continue

    # spend + CPL
    spend90 = None
    try:
        import meta_spend
        spend90 = (meta_spend.spend_in_range(str(w0), str(w1)) or {}).get("spend")
    except Exception as e:  # noqa: BLE001
        logger.warning("compass spend read failed: %s", e)
    monthly_spend0 = round((spend90 or 0) / 3.0, 2) if spend90 else None
    cpl = round(spend90 / leads_n, 2) if spend90 and leads_n else None
    it["cpl"] = _item(cpl, leads_n, win, "Meta spend (archive) ÷ tracker leads")
    it["monthly_spend_baseline"] = _item(monthly_spend0, 3, win,
                                         "trailing-90d Meta spend ÷ 3 (S₀ for the ε curve)")
    it["set_rate"] = _item(round(sets_n / leads_n, 4) if leads_n else None,
                           leads_n, win, "sets ÷ leads (tracker, booked appointments)")
    it["show_rate"] = _item(round(shows_n / sets_n, 4) if sets_n else None,
                            sets_n, win, "verified shows ÷ sets (tracker)")

    # closes + close rate (union engine — the gap-window class)
    closes90 = []
    try:
        import finance_analysis as FA
        closes90 = FA._closes_union(str(w0), str(w1), "activity")
    except Exception as e:  # noqa: BLE001
        logger.warning("compass closes read failed: %s", e)
    it["close_rate"] = _item(round(len(closes90) / shows_n, 4) if shows_n else None,
                             shows_n, win,
                             "union closes ÷ verified shows (Rydel's '35%' lives "
                             "here — adjustable)")

    # deal mix (180d won offers, normalised over known packages)
    known = {}
    for offer, cnt in mix.items():
        key = _pkg_key(offer)
        known[key] = known.get(key, 0) + cnt
    tot_mix = sum(known.values())
    it["deal_mix"] = _item(
        {k: round(v / tot_mix, 3) for k, v in known.items()} if tot_mix else
        {"growth pro": 1.0},
        tot_mix, "180d won rows", "tracker offer column on won rows",
        assumption=not tot_mix)

    # lag curve
    if len(lag_pairs) >= 8:
        counts = [0.0] * 3
        for off in lag_pairs:
            counts[min(off, 2)] += 1
        s = sum(counts)
        it["lag_curve"] = _item([round(c / s, 3) for c in counts], len(lag_pairs),
                                "180d closes", "close month − lead month (tracker)")
    else:
        it["lag_curve"] = _item(DEFAULT_LAG, len(lag_pairs), "180d closes",
                                f"insufficient pairs (n={len(lag_pairs)}) — "
                                "labelled default", assumption=True)

    # per-package economics (MRR from the active book by package; term from
    # config authority; cash schedule measured from close cash÷contract m0)
    it["packages"] = _item(_package_economics(closes90), None, "config + book",
                           "PACKAGE_TERMS + active-book MRR by package + "
                           "measured month-0 cash share")

    # renewal rate — CSM Gate-0 B1, measured-bounded: plan on the MIDPOINT of
    # [lower_bound, value] (survivorship makes the point value an upper
    # estimate), labelled with both bounds
    renewal, prov, ren_n = None, "unmeasured", None
    try:
        import csm_baselines
        b1 = csm_baselines.measure_renewal_rate()
        up = b1.get("value")
        low = b1.get("lower_bound", up)
        ren_n = b1.get("n_decided")
        if up is not None:
            mid = (float(up) + float(low if low is not None else up)) / 2.0
            renewal = round(mid / 100.0, 3)
            prov = (f"CSM Gate-0 B1 bounded [{low}–{up}%] → planning midpoint "
                    f"{mid:.0f}% ({b1.get('label')})")
    except Exception as e:  # noqa: BLE001
        logger.info("compass renewal read failed: %s", e)
    if renewal is None:
        renewal, prov = 0.0, ("historical 0/12 finished clients re-signed — "
                              "the projection engine's honest default")
    it["renewal_rate"] = _item(renewal, ren_n, "trailing 12mo terms",
                               prov, assumption=renewal in (0.0, 1.0))

    # ε — CPL elasticity from the account's own monthly spend-vs-CPL variance
    it["cpl_epsilon"] = _epsilon_fit()

    # commissions — the tab holds NO structure (finding, surfaced): the
    # 'Closer Payout & KPI' tab is a per-client payout projection grid.
    comm_rate = None
    try:
        import range_unit_economics as R
        r = R.unit_economics(str(w0), str(w1))
        comp = r.get("components") or {}
        cash_win = comp.get("cash_collected_total")
        cm = (comp.get("closer_comm") or 0) + (comp.get("setter_comm") or 0)
        if cash_win:
            comm_rate = round(cm / cash_win, 4)
    except Exception:
        pass
    from config import FY26_COMMISSIONS_PCT_OF_SALES
    fy26 = round(FY26_COMMISSIONS_PCT_OF_SALES / 100, 4)
    if comm_rate and abs(comm_rate - fy26) <= fy26:      # within 2× of FY26
        it["commission_pct_of_cash"] = _item(
            comm_rate, None, win,
            "tracker commission cells ÷ cash in window; FY26 sanity 6.3% "
            "(closer 5.1 + setter 1.2) beside")
    else:
        it["commission_pct_of_cash"] = _item(
            fy26, None, "FY26 actuals",
            ("FY26 6.3% of sales (Rydel 2026-09-17). "
             + (f"In-window read {comm_rate*100:.1f}% DISAGREES — distorted "
                "by lagging tracker cash cells (the gap class); SURFACED, "
                "never averaged. " if comm_rate else "")
             + "The 'Closer Payout & KPI' tab holds a payout projection "
               "grid, NOT a base/% structure (finding)"),
            assumption=True)
    it["commission_structure_finding"] = _item(
        "Closer Payout & KPI tab = per-client MRR/payout projection grid; no "
        "base/% structure recorded there", None, "workbook read",
        "finance_tabs read-only export", assumption=False)

    # OpEx ex-tax — outflow bands trailing avg + FIXED COSTS tab total
    it["opex_monthly_ex_tax"] = _opex_measured()
    from config import SALES_TOOLING_MONTHLY
    it["sales_tooling_monthly"] = _item(SALES_TOOLING_MONTHLY, None, "config",
                                        "itemised subscriptions override")

    # market lanes
    it["lanes"] = _item(
        {"au": markets.get("au", 0) + markets.get("unknown", 0),
         "us": markets.get("us", 0)},
        sum(markets.values()), win,
        "tracker Market column (#127; unknown counted AU-side). US small-n "
        "falls back to AU rates, labelled")

    # team + throughput
    it["team"] = _item(_team_snapshot(), None, "roster/config",
                       "setters/closers from the sales roster; throughput "
                       "config where unmeasured (labelled)")

    # seasonality — needs 12+ months of lead history; not yet available
    it["seasonality"] = _item({str(m): 1.0 for m in range(1, 13)}, None,
                              "insufficient prior-year lead history",
                              "flat 1.0 — labelled assumption", assumption=True)

    kv_store.put(K_DEFAULTS, out)
    return out


def _pkg_key(offer: str) -> str:
    o = (offer or "").lower()
    if "growth" in o or "gp" in o:
        return "growth pro"
    if "scale" in o or "se" == o.strip():
        return "scale engine"
    if "fire" in o:
        return "firestarter"
    if "walk" in o or "cafe" in o:
        return "cafe walk-ins"
    if "web" in o:
        return "web sub"
    if "content" in o:
        return "content scale"
    return "growth pro" if not o or o == "unknown" else o


def _package_economics(closes90: list[dict]) -> dict:
    """Per-package: MRR (median of the active book's package rows), term
    (config authority), contract (mrr×term), cash schedule (month-0 share
    measured from closes' cash÷contract; remainder spread over the term)."""
    from config import PACKAGE_TERMS
    book: dict[str, list[float]] = {}
    try:
        from snapshot import load_persisted
        pool = ((load_persisted() or {}).get("active_clients") or {}).get("active") or []
        for c in pool:
            pkg = _pkg_key(c.get("package") or "")
            if c.get("current_mrr"):
                book.setdefault(pkg, []).append(float(c["current_mrr"]))
    except Exception:
        pass
    # measured month-0 cash share from the 90d closes (cash ÷ contract)
    shares = [min(1.0, float(c["cash"]) / float(c["contract"]))
              for c in closes90
              if c.get("cash") and c.get("contract") and float(c["contract"]) > 0]
    m0_share = round(sum(shares) / len(shares), 3) if shares else 0.17
    out = {}
    for pkg in ("growth pro", "scale engine", "cafe walk-ins", "web sub"):
        term = int(PACKAGE_TERMS.get(pkg, 6))
        vals = sorted(book.get(pkg, []))
        mrr = vals[len(vals) // 2] if vals else {"growth pro": 3050.0,
                                                 "scale engine": 3500.0,
                                                 "cafe walk-ins": 2200.0,
                                                 "web sub": 199.0}[pkg]
        contract = round(mrr * term, 2)
        # cash schedule: m0 = measured deposit share; remainder equal over
        # the remaining term months (sums exactly to the contract — tested)
        n_rest = max(term - 1, 1)
        rest = (1.0 - m0_share) / n_rest
        sched = [round(m0_share, 4)] + [round(rest, 6)] * n_rest
        sched[-1] = round(1.0 - sum(sched[:-1]), 6)   # exact sum to 1
        out[pkg] = {"mrr": mrr, "term": term, "contract": contract,
                    "cash_schedule": sched,
                    "m0_share_measured_n": len(shares),
                    "gross_margin_pct": FY26_MARGIN_PCT,
                    "delivery_cost_monthly": round(mrr * (1 - FY26_MARGIN_PCT / 100), 2),
                    "mrr_provenance": (f"active-book median (n={len(vals)})"
                                       if vals else "config default (no book rows — labelled)")}
    return out


def _epsilon_fit() -> dict:
    """CPL(S) = CPL₀ (S/S₀)^ε — fit ε from monthly spend vs CPL over the last
    9 months where both exist; needs n≥6 months and spend variance."""
    try:
        import meta_spend
        import attribution_engine as AE
        t = today_sydney()
        pts = []
        for k in range(1, 10):
            m_end = (t.replace(day=1) - dt.timedelta(days=1)) if k == 1 else None
            m1 = _month_add(str(t)[:7], -k)
            d0 = dt.date.fromisoformat(m1 + "-01")
            d1 = (d0 + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
            sp = (meta_spend.spend_in_range(str(d0), str(d1)) or {}).get("spend")
            if not sp:
                continue
            res = AE.compute(start=str(d0), end=str(d1), basis="activity")
            leads = sum(c.get("leads") or 0 for c in res.get("creatives", []))
            if leads >= 10:
                pts.append((sp, sp / leads))
        if len(pts) >= 6:
            xs = [math.log(p[0]) for p in pts]
            ys = [math.log(p[1]) for p in pts]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            denom = sum((x - mx) ** 2 for x in xs)
            if denom > 0.05:   # needs real spend variance
                eps = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
                if 0.0 <= eps <= 0.6:
                    return _item(round(eps, 3), len(pts),
                                 "9 monthly spend/CPL points",
                                 "log-log OLS on the account's own months")
                # a slope near/above 1 says "spend buys nothing" — with n≈9
                # confounded months (creatives, seasonality, lead quality)
                # that is an UNINFORMATIVE fit, not a planning truth. Surface
                # the raw fit; plan on the labelled default.
                return _item(DEFAULT_EPSILON, len(pts), "9 monthly points",
                             f"account fit ε≈{eps:.2f} is confounded "
                             f"(slope ≥0.6 on n={len(pts)} mixed months — "
                             "creative/seasonality changes, not pure "
                             "elasticity); planning default 0.2, adjustable; "
                             "raw fit SURFACED, not silently used",
                             assumption=True)
        return _item(DEFAULT_EPSILON, len(pts), "9 monthly points",
                     f"fit unsupported (n={len(pts)} or no spend variance) — "
                     "labelled default 0.2", assumption=True)
    except Exception as e:  # noqa: BLE001
        return _item(DEFAULT_EPSILON, 0, "unavailable",
                     f"fit failed ({str(e)[:60]}) — labelled default 0.2",
                     assumption=True)


def _opex_measured() -> dict:
    """OpEx ex-tax AND ex-acquisition: the outflow-truth OpEx band CONTAINS
    the Advertising and Closer/Setter-Commission P&L accounts — the model
    already carries spend and commissions explicitly, so they are SUBTRACTED
    here (double-count guard, derivation labelled)."""
    try:
        import outflow_bands
        mb = outflow_bands.monthly_bands(4)
        rows = mb.get("months") or mb.get("rows") or []
        vals = [r.get("opex") for r in rows if r.get("opex")]
        if vals:
            avg = round(sum(vals[:-1]) / max(len(vals) - 1, 1), 2) \
                if len(vals) > 1 else vals[0]
            ad_m = comm_m = 0.0
            try:
                import meta_spend
                t = today_sydney()
                ad_m = ((meta_spend.spend_in_range(
                    str(t - dt.timedelta(days=89)), str(t)) or {})
                    .get("spend") or 0) / 3.0
            except Exception:
                pass
            try:
                import range_unit_economics as R
                t = today_sydney()
                r = R.unit_economics(str(t - dt.timedelta(days=89)), str(t))
                comp = r.get("components") or {}
                comm_m = ((comp.get("closer_comm") or 0)
                          + (comp.get("setter_comm") or 0)) / 3.0
            except Exception:
                pass
            net = round(avg - ad_m - comm_m, 2)
            return _item(net, len(vals) - 1 if len(vals) > 1 else 1,
                         "trailing full months",
                         f"outflow-truth OpEx band ${avg:,.0f}/mo − advertising "
                         f"${ad_m:,.0f} − commissions ${comm_m:,.0f} (both "
                         "modelled explicitly — double-count guard); tax/"
                         "personal banded OUT upstream")
    except Exception as e:  # noqa: BLE001
        logger.info("compass opex read failed: %s", e)
    return _item(29671.0, None, "config", "true-team-cost config fallback "
                 "(CLAUDE.md) — labelled", assumption=True)


def _team_snapshot() -> dict:
    setters = closers = None
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        per_setter = (snap.get("sales") or {}).get("per_setter") or \
                     ((snap.get("sales") or {}).get("deep") or {}).get("setter_performance") or []
        setters = len([s for s in per_setter if s.get("name")]) or None
        per_closer = (snap.get("sales") or {}).get("per_closer") or []
        closers = len([c for c in per_closer if c.get("name")]) or None
    except Exception:
        pass
    return {"setters": setters or 2, "closers": closers or 1,
            "delivery": 7,           # config — team roster delivery seats
            "throughput": dict(THROUGHPUT_DEFAULTS),
            "role_costs_monthly": dict(ROLE_COSTS_MONTHLY),
            "ramp_weeks": dict(RAMP_WEEKS),
            "measured": {"setters": bool(setters), "closers": bool(closers)}}


# ── INPUTS (controls with measured defaults) ────────────────────────────────

def default_inputs() -> dict:
    d = measured_defaults()
    it = d["items"]
    t = today_sydney()
    m0 = _month_add(str(t)[:7], 1)               # planning starts next month
    horizon = _months_between(m0, HORIZON_END) + 1
    v = lambda k, fb=None: (it.get(k) or {}).get("value", fb)
    return {
        "start_month": m0,
        "horizon_months": max(horizon, 6),
        "spend_path": {"shape": "flat",
                       "start": v("monthly_spend_baseline") or 10000.0,
                       "ramp_pct": 0.0, "explicit": []},
        "cpl0": v("cpl") or 90.0,
        "epsilon": v("cpl_epsilon", DEFAULT_EPSILON),
        "set_rate": v("set_rate") or 0.15,
        "show_rate": v("show_rate") or 0.9,
        "close_rate": v("close_rate") or 0.28,
        "deal_mix": v("deal_mix") or {"growth pro": 1.0},
        "packages": v("packages") or {},
        "lag_curve": v("lag_curve") or DEFAULT_LAG,
        "renewal_rate": v("renewal_rate") or 0.0,
        "commission_pct_of_cash": v("commission_pct_of_cash") or 0.063,
        "opex_monthly_ex_tax": v("opex_monthly_ex_tax") or 29671.0,
        "sales_tooling_monthly": v("sales_tooling_monthly") or 2132.0,
        "seasonality": v("seasonality") or {},
        "team": v("team") or _team_snapshot(),
        "hires": [],                                  # planned hires
        "min_cash_buffer": MIN_CASH_BUFFER,
        "hire_lead_weeks": HIRE_LEAD_WEEKS,
        "us_lane": {"enabled": False,
                    "note": f"US n={((v('lanes') or {}).get('us'))} in 90d — "
                            "falls back to AU rates, labelled"},
        "resign_pins": {},        # SCENARIO PINS ONLY — never declarations
        "slider_resign_pct": None,  # None → renewal_rate
    }


# ── BOOK STATE (the existing clients — one engine) ──────────────────────────

def book_state(horizon_months: int, start_month: str,
               resign_rate: float, resign_pins: dict | None = None) -> dict:
    """Existing-book MRR path from the ONE projection engine: committed +
    assumed×resign, with SCENARIO PINS (per-client toggles) lifting a
    client's assumed lane to committed-equivalent inside this run only."""
    import forward_projection as FP
    import client_overrides
    proj = FP.project()
    labels = proj.get("months") or []
    committed = proj.get("committed") or []
    assumed = proj.get("assumed_pool") or []
    oneoff = proj.get("oneoff_cash") or []
    per_client = proj.get("per_client") or {}
    pins = {client_overrides._norm(k): bool(x)
            for k, x in (resign_pins or {}).items()}
    # a pinned client's MRR moves from the assumed pool to committed-like
    # continuation after their committed_until — approximated by adding
    # their MRR to committed and removing from assumed for those months
    def label_ym(lbl):
        for fmt in ("%B %Y", "%b %Y"):     # projection labels are "October 2026"
            try:
                d = dt.datetime.strptime(str(lbl), fmt)
                return f"{d.year:04d}-{d.month:02d}"
            except Exception:
                continue
        return None
    lab_ym = [label_ym(l) for l in labels]
    pin_add = [0.0] * len(labels)
    for name, row in per_client.items():
        nn = client_overrides._norm(name)
        if not pins.get(nn):
            continue
        mrr = float(row.get("mrr_now") or 0)
        cu = row.get("committed_until")
        cu_i = labels.index(cu) if cu in labels else -1
        for i in range(cu_i + 1, len(labels)):
            pin_add[i] += mrr
    book_mrr, book_cash = [], []
    for k in range(horizon_months):
        ym = _month_add(start_month, k)
        if ym in lab_ym:
            i = lab_ym.index(ym)
            pinned = pin_add[i]
            rest_assumed = max(float(assumed[i]) - pinned, 0.0)
            # month-0 identity: everyone in the assumed pool is PAYING today
            # (month-to-month actives) — attrition starts the following
            # month; month 0 must equal the present MRR truth (verified)
            factor = 1.0 if k == 0 else resign_rate
            mrr = float(committed[i]) + pinned + rest_assumed * factor
            cash = mrr + float(oneoff[i] or 0)
        else:
            # beyond the projection horizon: decay the last modelled book by
            # the renewal rate every 6 months (labelled approximation)
            base = book_mrr[-1] if book_mrr else 0.0
            mrr = base * (resign_rate ** (1 / 6)) if resign_rate > 0 else \
                base * 0.89  # ~half-life 6mo — labelled
            cash = mrr
        book_mrr.append(round(mrr, 2))
        book_cash.append(round(cash, 2))
    return {"mrr": book_mrr, "cash": book_cash, "labels_source": "forward_projection",
            "note": ("existing-book cash ≈ its recognised MRR + declared one-offs "
                     "(stated assumption); beyond the projection horizon the book "
                     "decays at the renewal rate (labelled)")}


def cash_position_base() -> dict:
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        cp = snap.get("cash_position") or {}
        cash = cp.get("cash_in_bank")
        set_aside = cp.get("tax_reserved") or 0
        return {"cash_ex_setaside": round((cash or 0) - set_aside, 2),
                "cash": cash, "tax_set_aside": set_aside,
                "as_of": cp.get("cash_as_of")}
    except Exception:
        return {"cash_ex_setaside": 0.0, "cash": None, "tax_set_aside": 0}


# ── FORWARD RUN (the equation, per month) ───────────────────────────────────

def forward(inputs: dict, _book: dict | None = None) -> dict:
    inp = {**default_inputs(), **(inputs or {})}
    H = int(inp["horizon_months"])
    m0 = inp["start_month"]
    resign = float(inp["slider_resign_pct"] / 100.0
                   if inp.get("slider_resign_pct") is not None
                   else inp["renewal_rate"] or 0.0)
    book = _book or book_state(H, m0, resign, inp.get("resign_pins"))
    base_cash = cash_position_base()
    pkgs = inp["packages"]
    mix = _norm_mix(inp["deal_mix"], pkgs)
    lag = list(inp["lag_curve"])
    s_lag = sum(lag) or 1.0
    lag = [x / s_lag for x in lag]
    eps = float(inp["epsilon"])
    S0 = float(inp["spend_path"].get("start") or 1.0) or 1.0
    comm_rate = float(inp["commission_pct_of_cash"])
    tooling = float(inp["sales_tooling_monthly"])
    team = inp["team"]
    thr = team.get("throughput") or THROUGHPUT_DEFAULTS
    buffer_ = float(inp["min_cash_buffer"])
    tax_note = _tax_beside()

    months = []
    spend_path = _spend_series(inp["spend_path"], H)
    closes_realised = [dict() for _ in range(H + 3)]   # month → {pkg: n}
    cohort_meta = []       # per lead-month: numerator, eventual closes
    new_streams = []       # {start_i, pkg, n} MRR streams from new closes
    hires = sorted(inp.get("hires") or [], key=lambda h: h.get("month") or "")
    headcount = {"setters": float(team.get("setters") or 0),
                 "closers": float(team.get("closers") or 0),
                 "delivery": float(team.get("delivery") or 0)}
    auto_hire_cards = []
    cum_net = 0.0
    dip = None
    active_new_clients = 0.0

    for k in range(H):
        ym = _month_add(m0, k)
        seas = float((inp.get("seasonality") or {}).get(str(int(ym[5:7])), 1.0))
        spend = spend_path[k] * seas
        cpl = float(inp["cpl0"]) * ((spend / S0) ** eps if spend > 0 else 1.0)
        leads = spend / cpl if cpl > 0 else 0.0
        sets_ = leads * float(inp["set_rate"])
        shows = sets_ * float(inp["show_rate"])
        closes_cohort = shows * float(inp["close_rate"])
        # lag: this lead-month's closes realise over k, k+1, k+2
        for t_off, share in enumerate(lag):
            tgt = k + t_off
            if tgt < H + 3:
                for pkg, mshare in mix.items():
                    closes_realised[tgt][pkg] = closes_realised[tgt].get(pkg, 0.0) \
                        + closes_cohort * share * mshare
        cohort_meta.append({"month": ym, "spend": spend, "leads": leads,
                            "closes_eventual": closes_cohort})
        months.append({"month": ym, "spend": round(spend, 2),
                       "cpl": round(cpl, 2), "leads": round(leads, 1),
                       "calls_booked": round(sets_, 1),
                       "shows": round(shows, 1)})

    # realise closes → cash, MRR streams, costs, constraints
    for k in range(H):
        row = months[k]
        ym = row["month"]
        realised = closes_realised[k]
        n_closes = sum(realised.values())
        row["closes"] = round(n_closes, 2)
        row["closes_by_package"] = {p: round(n, 2) for p, n in realised.items() if n > 0.005}
        for pkg, n in realised.items():
            if n > 0:
                new_streams.append({"start": k, "pkg": pkg, "n": n})

        # cash from ALL new-cohort streams due this month
        cash_new = 0.0
        for s in new_streams:
            pk = pkgs.get(s["pkg"]) or {}
            sched = pk.get("cash_schedule") or []
            off = k - s["start"]
            if 0 <= off < len(sched):
                cash_new += s["n"] * sched[off] * float(pk.get("contract") or 0)
        # new-cohort MRR active this month (within term, then ×renewal)
        mrr_new = 0.0
        clients_active_new = 0.0
        for s in new_streams:
            pk = pkgs.get(s["pkg"]) or {}
            term = int(pk.get("term") or 6)
            off = k - s["start"]
            if off < 0:
                continue
            alive = s["n"] if off < term else s["n"] * (resign if resign else 0.0)
            if off < term or resign:
                mrr_new += alive * float(pk.get("mrr") or 0)
                clients_active_new += alive
        active_new_clients = clients_active_new

        book_mrr = book["mrr"][k]
        book_cash = book["cash"][k]
        net_mrr = book_mrr + mrr_new
        prev_book = book["mrr"][k - 1] if k else book_mrr
        churn_mrr = max(prev_book - book_mrr, 0.0)

        # capacity + utilisation (ramp: a hire counts 50% during ramp weeks)
        eff = dict(headcount)
        for h in hires + auto_hire_cards:
            if not h.get("month") or h["month"] > ym:
                continue
            ramp_m = math.ceil((h.get("ramp_weeks")
                                or RAMP_WEEKS.get(h.get("role", ""), 6)) / 4.33)
            started = _months_between(h["month"], ym)
            eff[h.get("role_key", h.get("role", "delivery"))] = \
                eff.get(h.get("role_key", h.get("role", "delivery")), 0.0) \
                + (0.5 if started < ramp_m else 1.0)
        setters_needed = row["leads"] / float(thr["leads_per_setter_month"])
        closers_needed = row["calls_booked"] / float(thr["calls_per_closer_month"])
        total_clients = clients_active_new + _book_clients_estimate(book_mrr)
        delivery_needed = total_clients / float(thr["clients_per_delivery"])
        util = {
            "setters": round(setters_needed / eff.get("setters", 1) * 100, 1) if eff.get("setters") else None,
            "closers": round(closers_needed / eff.get("closers", 1) * 100, 1) if eff.get("closers") else None,
            "delivery": round(delivery_needed / eff.get("delivery", 1) * 100, 1) if eff.get("delivery") else None,
        }
        # AUTO HIRE CARDS: utilisation crossing 100% → hire dated lead-time back
        for role_key, needed, per in (("setters", setters_needed, "setter"),
                                      ("closers", closers_needed, "closer"),
                                      ("delivery", delivery_needed, "delivery")):
            if eff.get(role_key) and needed > eff[role_key] and \
                    not any(c["role_key"] == role_key and c["for_month"] == ym
                            for c in auto_hire_cards):
                lead_m = math.ceil(float(inp["hire_lead_weeks"]) / 4.33)
                start = _month_add(ym, 0)
                order_by = _month_add(ym, -lead_m)
                auto_hire_cards.append({
                    "role": per, "role_key": role_key, "month": start,
                    "order_by": order_by, "for_month": ym,
                    "cost_monthly": ROLE_COSTS_MONTHLY.get(per, 2000.0),
                    "ramp_weeks": RAMP_WEEKS.get(per, 6),
                    "card": (f"hire {per} by {order_by} (starts {start}; "
                             f"{RAMP_WEEKS.get(per,6)}w ramp; "
                             f"${ROLE_COSTS_MONTHLY.get(per,2000.0):,.0f}/mo)")})

        # commissions are % of SALES (new-deal collections) — FY26 6.3% of
        # sales, never of the standing book's recurring collections (stated;
        # renewal commissions, if ever agreed, are not modelled)
        commissions = comm_rate * cash_new
        # hires: planned + auto (cost from start month; ramp affects capacity)
        hire_cost = 0.0
        for h in hires + auto_hire_cards:
            if h.get("month") and h["month"] <= ym:
                hire_cost += float(h.get("cost_monthly")
                                   or ROLE_COSTS_MONTHLY.get(h.get("role", ""), 0))
        # delivery variable cost for NEW clients (existing book's delivery
        # cost already lives inside measured OpEx)
        delivery_var = 0.0
        for s in new_streams:
            pk = pkgs.get(s["pkg"]) or {}
            off = k - s["start"]
            term = int(pk.get("term") or 6)
            if 0 <= off < term:
                delivery_var += s["n"] * float(pk.get("delivery_cost_monthly") or 0)

        opex = float(inp["opex_monthly_ex_tax"])
        costs = row["spend"] + commissions + opex + hire_cost + delivery_var
        cash_in = cash_new + book_cash
        net = cash_in - costs
        cum_net += net
        position = base_cash["cash_ex_setaside"] + cum_net
        if dip is None or position < dip:
            dip = position

        # CAC (period) — this month's acquisition costs ÷ realised closes.
        # Sales labour is commission-only today (no fixed sales salaries) —
        # stated; sales-role hires would move this.
        acq = row["spend"] + commissions + tooling
        cac_period = round(acq / n_closes, 2) if n_closes >= 0.05 else None
        cac_period_spend_only = round(row["spend"] / n_closes, 2) \
            if n_closes >= 0.05 else None
        # LTGP per close (mix-weighted)
        ltgp_close = sum(mix[p] * float((pkgs.get(p) or {}).get("contract") or 0)
                         * float((pkgs.get(p) or {}).get("gross_margin_pct") or FY26_MARGIN_PCT) / 100
                         for p in mix)
        ltgp_cac = round(ltgp_close / cac_period, 2) if cac_period else None
        cash_30d_per_client = sum(
            mix[p] * ((pkgs.get(p) or {}).get("cash_schedule") or [0])[0]
            * float((pkgs.get(p) or {}).get("contract") or 0) for p in mix)
        client_financed = round(cash_30d_per_client / cac_period, 2) if cac_period else None

        # BINDING CONSTRAINT — first true, with its number
        binding = None
        if row["cpl"] > CPL_THRESHOLD_MULT * float(inp["cpl0"]):
            binding = {"name": "LEADS", "why": f"CPL ${row['cpl']:,.0f} > "
                       f"{CPL_THRESHOLD_MULT}× CPL₀ (${float(inp['cpl0']):,.0f}) — "
                       "spend is buying diminishing leads"}
        elif util.get("setters") and util["setters"] > 100 or \
                util.get("closers") and util["closers"] > 100:
            worst = max((util.get("setters") or 0), (util.get("closers") or 0))
            role = "setters" if (util.get("setters") or 0) >= (util.get("closers") or 0) else "closers"
            binding = {"name": "SALES CAPACITY",
                       "why": f"{role} at {worst:.0f}% utilisation"}
        elif util.get("delivery") and util["delivery"] > 100:
            binding = {"name": "DELIVERY CAPACITY",
                       "why": f"delivery at {util['delivery']:.0f}% "
                              f"({total_clients:.0f} clients / "
                              f"{eff.get('delivery',0):.0f} seats × {thr['clients_per_delivery']})"}
        elif position < buffer_:
            binding = {"name": "CASH", "why": f"position ${position:,.0f} < "
                       f"buffer ${buffer_:,.0f}"}
        elif churn_mrr >= (mrr_new - (months[k-1].get('mrr_new') or 0 if k else 0)) and churn_mrr > 0 \
                and net_mrr <= (months[k-1].get("net_mrr") or net_mrr if k else net_mrr):
            binding = {"name": "RETENTION", "why": f"churn ${churn_mrr:,.0f} ≥ "
                       f"new MRR added — the book shrinks"}
        if binding is None:
            binding = {"name": "LEADS (spend is the lever)",
                       "why": "no constraint breaks — lead volume (spend) "
                              "limits growth this month"}

        row.update({
            "cash_new_cohort": round(cash_new, 2),
            "cash_existing_book": round(book_cash, 2),
            "cash_in": round(cash_in, 2),
            "mrr_new": round(mrr_new, 2),
            "mrr_book": round(book_mrr, 2),
            "net_mrr": round(net_mrr, 2),
            "churn_mrr": round(churn_mrr, 2),
            "commissions": round(commissions, 2),
            "opex_ex_tax": round(opex + delivery_var + hire_cost, 2),
            "costs_total": round(costs, 2),
            "net_cash": round(net, 2),
            "position": round(position, 2),
            "cac_period": cac_period,
            "cac_period_spend_only": cac_period_spend_only,
            "ltgp_cac": ltgp_cac,
            "client_financed_check": client_financed,
            "utilisation": util,
            "headcount_effective": {r: round(v, 1) for r, v in eff.items()},
            "binding_constraint": binding,
        })

    # cohort CAC + payback (per lead-month, via the lag curve)
    cohorts = []
    for k, meta in enumerate(cohort_meta):
        n_ev = meta["closes_eventual"]
        if n_ev < 0.05:
            continue
        comm_est = comm_rate * n_ev * sum(
            mix[p] * float((pkgs.get(p) or {}).get("contract") or 0) for p in mix)
        cac_cohort = round((meta["spend"] + comm_est + tooling) / n_ev, 2)
        cac_cohort_spend_only = round(meta["spend"] / n_ev, 2)
        # payback: cumulative mix-weighted cash schedule vs CAC
        cum, payback = 0.0, None
        contract_mix = sum(mix[p] * float((pkgs.get(p) or {}).get("contract") or 0) for p in mix)
        sched_len = max(len((pkgs.get(p) or {}).get("cash_schedule") or []) for p in mix)
        for off in range(sched_len):
            share = sum(mix[p] * (((pkgs.get(p) or {}).get("cash_schedule") or [0]*sched_len)[off]
                                  if off < len((pkgs.get(p) or {}).get("cash_schedule") or []) else 0)
                        for p in mix)
            cum += share * contract_mix
            if payback is None and cum >= cac_cohort:
                payback = off + 1
        cohorts.append({"lead_month": meta["month"], "cac_cohort": cac_cohort,
                        "cac_cohort_spend_only": cac_cohort_spend_only,
                        "closes_eventual": round(n_ev, 2),
                        "payback_months": payback})

    return {
        "inputs_hash": _hash_inputs(inp),
        "start_month": m0, "horizon_months": H,
        "months": months,
        "cohorts": cohorts,
        "hire_cards": [h["card"] for h in auto_hire_cards] +
                      [f"planned: {h.get('role')} from {h.get('month')}" for h in hires],
        "auto_hires": auto_hire_cards,
        "capital_dip": round(dip, 2) if dip is not None else None,
        "cash_base": base_cash,
        "tax_beside": tax_note,
        "book_note": book.get("note"),
        "label": "SCENARIO — labelled hypothetical; never actuals",
    }


def _spend_series(path: dict, H: int) -> list[float]:
    shape = (path or {}).get("shape") or "flat"
    start = float((path or {}).get("start") or 0)
    if shape == "explicit" and path.get("explicit"):
        ex = [float(x) for x in path["explicit"]]
        return (ex + [ex[-1]] * H)[:H]
    if shape == "ramp":
        r = float(path.get("ramp_pct") or 0) / 100.0
        return [start * ((1 + r) ** k) for k in range(H)]
    return [start] * H


def _norm_mix(mix: dict, pkgs: dict) -> dict:
    m = {k: float(v) for k, v in (mix or {}).items() if float(v) > 0 and k in (pkgs or {})}
    if not m:
        m = {"growth pro": 1.0} if "growth pro" in (pkgs or {}) else \
            {next(iter(pkgs)): 1.0} if pkgs else {}
    s = sum(m.values()) or 1.0
    return {k: v / s for k, v in m.items()}


def _book_clients_estimate(book_mrr: float) -> float:
    """Existing-book client count ≈ book MRR ÷ current avg MRR/client."""
    try:
        from snapshot import load_persisted
        ch = (load_persisted() or {}).get("client_health") or {}
        n = len(ch.get("clients") or [])
        mrr = ch.get("current_mrr")
        if n and mrr:
            return book_mrr / (mrr / n)
    except Exception:
        pass
    return book_mrr / 2200.0


def _tax_beside() -> dict:
    try:
        import bas_engine
        est = bas_engine.current_estimate() if hasattr(bas_engine, "current_estimate") else None
        if est:
            return {"note": "tax accrual BESIDE burn (set-aside logic) — never inside",
                    "estimate": est}
    except Exception:
        pass
    return {"note": "tax accrual shown BESIDE burn via the BAS set-aside "
                    "logic — never inside OpEx; BAS settles quarterly "
                    "(Oct/Jan/Apr/Jul)"}


def _hash_inputs(inp: dict) -> str:
    return hashlib.sha256(json.dumps(inp, sort_keys=True, default=str)
                          .encode()).hexdigest()[:12]


# ── TARGET SOLVER (bisection over the spend path scale) ─────────────────────

def solve(target: dict, inputs: dict | None = None) -> dict:
    """target = {kind: 'mrr'|'cash_month'|'cash_cumulative', month: 'YYYY-MM',
    value: float}. Bisection over a scale factor applied to the chosen spend
    shape. Infeasible → what breaks first + nearest feasible outcome."""
    inp = {**default_inputs(), **(inputs or {})}
    kind, month, value = target.get("kind"), target.get("month"), float(target.get("value") or 0)

    def outcome(run):
        idx = None
        for i, r in enumerate(run["months"]):
            if r["month"] == month:
                idx = i
                break
        if idx is None:
            return None
        if kind == "mrr":
            return run["months"][idx]["net_mrr"]
        if kind == "cash_month":
            return run["months"][idx]["cash_in"]
        if kind == "cash_cumulative":
            return sum(r["cash_in"] for r in run["months"][:idx + 1])
        return None

    def run_at(scale):
        p = dict(inp["spend_path"])
        p["start"] = float(p.get("start") or 0) * scale
        if p.get("explicit"):
            p["explicit"] = [float(x) * scale for x in p["explicit"]]
        return forward({**inp, "spend_path": p})

    lo, hi = 0.1, 12.0
    run_hi = run_at(hi)
    got_hi = outcome(run_hi)
    if got_hi is None:
        return {"error": f"target month {month} outside the horizon"}
    if got_hi < value:
        # infeasible even at 12× spend — name what breaks first at hi
        first_bind = next((r["binding_constraint"] for r in run_hi["months"]
                           if r["binding_constraint"]["name"] not in
                           ("LEADS (spend is the lever)",)), None)
        return {"feasible": False,
                "nearest": {"scale": hi, "outcome": got_hi,
                            "spend_month0": run_hi["months"][0]["spend"]},
                "breaks_first": first_bind or
                {"name": "LEADS", "why": "even 12× spend cannot reach the "
                 "target under the ε CPL curve — the rate stack is the limit"},
                "target": target, "label": run_hi["label"]}
    for _ in range(28):
        mid = (lo + hi) / 2
        got = outcome(run_at(mid))
        if got is None:
            break
        if got >= value:
            hi = mid
        else:
            lo = mid
    final = run_at(hi)
    return {"feasible": True, "scale": round(hi, 3),
            "achieved": outcome(final), "target": target,
            "required": {
                "spend_by_month": [{"month": r["month"], "spend": r["spend"],
                                    "leads": r["leads"],
                                    "calls": r["calls_booked"],
                                    "closes": r["closes"],
                                    "commissions": r["commissions"]}
                                   for r in final["months"]],
                "hires": final["hire_cards"],
                "capital_dip": final["capital_dip"]},
            "roadmap": final, "label": final["label"]}


# ── UNCERTAINTY (P25/P75 via simple Monte Carlo; deterministic seed) ────────

def bands(inputs: dict | None = None, runs: int = 120) -> dict:
    inp = {**default_inputs(), **(inputs or {})}
    d = measured_defaults()["items"]
    rng = random.Random(_hash_inputs(inp))          # deterministic per inputs

    def beta_like(rate, n):
        """Sample a rate with its measurement n (small n → wide)."""
        n = max(int(n or 5), 5)
        a = max(rate * n, 0.5)
        b = max((1 - rate) * n, 0.5)
        return min(max(rng.betavariate(a, b), 0.001), 0.999)

    paths_mrr, paths_cash = [], []
    for _ in range(runs):
        s = dict(inp)
        s["set_rate"] = beta_like(inp["set_rate"], (d.get("set_rate") or {}).get("n"))
        s["show_rate"] = beta_like(inp["show_rate"], (d.get("show_rate") or {}).get("n"))
        s["close_rate"] = beta_like(inp["close_rate"], (d.get("close_rate") or {}).get("n"))
        s["cpl0"] = inp["cpl0"] * rng.lognormvariate(0, 0.15)
        r = forward(s)
        paths_mrr.append([m["net_mrr"] for m in r["months"]])
        paths_cash.append([m["cash_in"] for m in r["months"]])

    def pct(paths, q):
        out = []
        for i in range(len(paths[0])):
            col = sorted(p[i] for p in paths)
            out.append(round(col[int(q * (len(col) - 1))], 2))
        return out
    return {"runs": runs,
            "mrr": {"p25": pct(paths_mrr, 0.25), "p75": pct(paths_mrr, 0.75)},
            "cash_in": {"p25": pct(paths_cash, 0.25), "p75": pct(paths_cash, 0.75)},
            "note": "rates sampled with their measured n (small n = wide "
                    "bands, honestly); CPL lognormal σ=0.15; deterministic "
                    "seed from the inputs hash"}


# ── CALIBRATION (backtest: predicted vs actual, last 3 complete months) ─────

def backtest(n_months: int = 3, store: bool = True) -> dict:
    import attribution_engine as AE
    import meta_spend
    import finance_analysis as FA
    t = today_sydney()
    rows = []
    for k in range(1, n_months + 1):
        ym = _month_add(str(t)[:7], -k)
        d0 = dt.date.fromisoformat(ym + "-01")
        d1 = (d0 + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        # rates as measured in the 90d BEFORE the month started
        r0, r1 = d0 - dt.timedelta(days=90), d0 - dt.timedelta(days=1)
        try:
            res = AE.compute(start=str(r0), end=str(r1), basis="activity")
            L = sum(c.get("leads") or 0 for c in res.get("creatives", []))
            S = sum(c.get("sets") or 0 for c in res.get("creatives", []))
            Sh = sum(c.get("shows") or 0 for c in res.get("creatives", []))
            C = len(FA._closes_union(str(r0), str(r1), "activity"))
            sp_prior = (meta_spend.spend_in_range(str(r0), str(r1)) or {}).get("spend") or 0
            cpl = sp_prior / L if L else None
            set_r = S / L if L else None
            show_r = Sh / S if S else None
            close_r = C / Sh if Sh else None
        except Exception as e:  # noqa: BLE001
            rows.append({"month": ym, "error": str(e)[:100]})
            continue
        # actual spend in the month → predicted stages (period basis; the lag
        # caveat is stated: closes lag lead months)
        sp = (meta_spend.spend_in_range(str(d0), str(d1)) or {}).get("spend") or 0
        pred_leads = sp / cpl if cpl else None
        pred_sets = pred_leads * set_r if pred_leads and set_r else None
        pred_shows = pred_sets * show_r if pred_sets and show_r else None
        pred_closes = pred_shows * close_r if pred_shows and close_r else None
        # actuals in the month
        try:
            res_m = AE.compute(start=str(d0), end=str(d1), basis="activity")
            a_leads = sum(c.get("leads") or 0 for c in res_m.get("creatives", []))
            a_sets = sum(c.get("sets") or 0 for c in res_m.get("creatives", []))
            a_shows = sum(c.get("shows") or 0 for c in res_m.get("creatives", []))
            a_closes = len(FA._closes_union(str(d0), str(d1), "activity"))
        except Exception as e:  # noqa: BLE001
            rows.append({"month": ym, "error": str(e)[:100]})
            continue

        def ape(p, a):
            if p is None or not a:
                return None
            return round(abs(p - a) / a * 100, 1)
        rows.append({"month": ym, "spend_actual": round(sp, 2),
                     "leads": {"pred": round(pred_leads or 0, 1), "actual": a_leads,
                               "ape_pct": ape(pred_leads, a_leads)},
                     "sets": {"pred": round(pred_sets or 0, 1), "actual": a_sets,
                              "ape_pct": ape(pred_sets, a_sets)},
                     "shows": {"pred": round(pred_shows or 0, 1), "actual": a_shows,
                               "ape_pct": ape(pred_shows, a_shows)},
                     "closes": {"pred": round(pred_closes or 0, 1), "actual": a_closes,
                                "ape_pct": ape(pred_closes, a_closes)}})
    # MAPE per stage
    mape = {}
    for st in ("leads", "sets", "shows", "closes"):
        vals = [r[st]["ape_pct"] for r in rows
                if r.get(st) and r[st].get("ape_pct") is not None]
        mape[st] = round(sum(vals) / len(vals), 1) if vals else None
    verdict_bits = [f"{st} ±{v}%" for st, v in mape.items() if v is not None]
    out = {"computed_at": now_sydney().isoformat(), "months": rows,
           "mape_pct": mape,
           "verdict": ("period-basis backtest: " + ", ".join(verdict_bits) +
                       " (closes lag lead-months — stated)") if verdict_bits
           else "backtest could not compute (engine reads failed)",
           "basis": "rates frozen at each month's start (90d prior window); "
                    "actual spend in-month; period realisation"}
    if store:
        kv_store.put(K_BACKTEST, out)
    return out


# ── SCENARIOS + PLAN OF RECORD ──────────────────────────────────────────────

def save_scenario(name: str, inputs: dict, note: str = "") -> dict:
    name = (name or "").strip()[:60]
    if not name:
        return {"error": "scenario needs a name"}
    store = kv_store.get(K_SCENARIOS) or {}
    store[name] = {"saved_at": now_sydney().isoformat(), "inputs": inputs,
                   "note": note[:300]}
    kv_store.put(K_SCENARIOS, store)
    return {"ok": True, "saved": name, "count": len(store)}


def list_scenarios(full: bool = False) -> dict:
    s = kv_store.get(K_SCENARIOS) or {}
    return {"scenarios": [{"name": k, "saved_at": v.get("saved_at"),
                           "note": v.get("note"),
                           **({"inputs": v.get("inputs")} if full else {})}
                          for k, v in s.items()]}


def commit_plan(name: str, actor: str) -> dict:
    """'Commit as Plan 2027' — a LABELLED plan-of-record, versioned. NEVER
    actuals: it lives in its own kv key and only pacing math reads it."""
    store = kv_store.get(K_SCENARIOS) or {}
    sc = store.get(name)
    if not sc:
        return {"error": f"unknown scenario '{name}'"}
    prior = kv_store.get(K_PLAN) or {}
    version = (prior.get("version") or 0) + 1
    run = forward(sc["inputs"])
    plan = {"version": version, "name": name, "committed_at": now_sydney().isoformat(),
            "by": actor, "inputs": sc["inputs"],
            "roadmap": [{k: r.get(k) for k in ("month", "spend", "leads",
                                               "calls_booked", "closes",
                                               "net_mrr", "cash_in")}
                        for r in run["months"]],
            "label": "PLAN OF RECORD (versioned scenario) — never actuals"}
    kv_store.put(K_PLAN, plan)
    return {"ok": True, "version": version, "months": len(plan["roadmap"])}


def plan_vs_actual() -> dict:
    """Monthly pacing: plan vs the ONE engine's actuals, with cause hints."""
    plan = kv_store.get(K_PLAN)
    if not plan:
        return {"available": False, "note": "no plan committed yet"}
    import attribution_engine as AE
    import meta_spend
    import finance_analysis as FA
    t = today_sydney()
    cur = str(t)[:7]
    rows = []
    for p in plan["roadmap"]:
        if p["month"] > cur:
            break
        d0 = dt.date.fromisoformat(p["month"] + "-01")
        d1 = min((d0 + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1), t)
        try:
            sp = (meta_spend.spend_in_range(str(d0), str(d1)) or {}).get("spend") or 0
            res = AE.compute(start=str(d0), end=str(d1), basis="activity")
            leads = sum(c.get("leads") or 0 for c in res.get("creatives", []))
            closes = len(FA._closes_union(str(d0), str(d1), "activity"))
        except Exception as e:  # noqa: BLE001
            rows.append({"month": p["month"], "error": str(e)[:80]})
            continue
        hints = []
        if p["spend"] and sp < 0.85 * p["spend"]:
            hints.append("spend under plan — leads shortfall likely upstream of rates")
        if p["leads"] and leads < 0.85 * p["leads"] and sp >= 0.85 * (p["spend"] or 0):
            hints.append("CPL above plan (spend on plan, leads short)")
        if p["closes"] and closes < 0.7 * p["closes"]:
            hints.append("close conversion under plan — check show/close rates")
        rows.append({"month": p["month"],
                     "spend": {"plan": p["spend"], "actual": round(sp, 2)},
                     "leads": {"plan": p["leads"], "actual": leads},
                     "closes": {"plan": p["closes"], "actual": closes},
                     "partial": p["month"] == cur,
                     "cause_hints": hints})
    return {"available": True, "version": plan["version"],
            "name": plan["name"], "rows": rows,
            "label": plan["label"]}


# ── EXPIRING PANEL (Part 1) + SALES PULSE (Part 2) ──────────────────────────

def expiring(window_days: int = 30) -> dict:
    """Clients whose committed coverage ends inside the window. Chips:
    declared (ACTUAL) / toggle (SCENARIO pin, request-scoped) / slider."""
    import forward_projection as FP
    import client_overrides
    proj = FP.project()
    per_client = proj.get("per_client") or {}
    decls = {}
    try:
        for ov in client_overrides.active_overrides():
            decls[client_overrides._norm(ov["client_name"])] = ov.get("kind")
    except Exception:
        pass
    t = today_sydney()
    rows = []
    for name, row in per_client.items():
        cu = row.get("committed_until")
        if not cu:
            continue
        end = None
        for fmt in ("%B %Y", "%b %Y"):
            try:
                end = dt.datetime.strptime(str(cu), fmt)
                break
            except Exception:
                continue
        if end is None:
            continue
        # coverage ends at that month's END
        term_end = (dt.date(end.year, end.month, 1)
                    + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        days_left = (term_end - t).days
        if days_left < -5 or days_left > window_days:
            continue
        kind = decls.get(client_overrides._norm(name))
        rows.append({"client": name,
                     "package": row.get("package") or "—",
                     "mrr": row.get("mrr_now"),
                     "term_end": str(term_end), "days_left": days_left,
                     "declared": kind,
                     "chip": ("ACTUAL — declared " + kind) if kind in
                             ("renewal", "extension") else "slider/toggle"})
    rows.sort(key=lambda r: r["days_left"])
    n_declared = len([r for r in rows if r["declared"] in ("renewal", "extension")])
    return {"window_days": window_days, "rows": rows,
            "expiring": len(rows), "declared": n_declared,
            "note": ("toggles are SCENARIO PINS ONLY — they move the picture "
                     "live and journal NOTHING; the declaration flow is the "
                     "only path to actuals")}


def sales_pulse(fresh: bool = False) -> dict:
    """SHOW RATE (t30, verified) · CLOSE RATE (t30) · BOOKED CALLS NEXT 7d
    (GHL kept appointments, read-only)."""
    cached = kv_store.get("compass:pulse")
    if cached and not fresh:
        return cached
    t = today_sydney()
    w0 = t - dt.timedelta(days=29)
    out = {"computed_at": now_sydney().isoformat()}
    try:
        import attribution_engine as AE
        import finance_analysis as FA
        res = AE.compute(start=str(w0), end=str(t), basis="activity")
        sets_n = sum(c.get("sets") or 0 for c in res.get("creatives", []))
        shows_n = sum(c.get("shows") or 0 for c in res.get("creatives", []))
        closes_n = len(FA._closes_union(str(w0), str(t), "activity"))
        out["show_rate"] = {"value": round(shows_n / sets_n, 3) if sets_n else None,
                            "n": sets_n, "window": "t30 · verified basis"}
        out["close_rate"] = {"value": round(closes_n / shows_n, 3) if shows_n else None,
                             "n": shows_n, "window": "t30 · closes ÷ verified shows"}
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:120]
    try:
        out["booked_calls_7d"] = booked_calls_next_7d()
    except Exception as e:  # noqa: BLE001
        out["booked_calls_7d"] = {"count": None, "error": str(e)[:120]}
    kv_store.put("compass:pulse", out)
    return out


def booked_calls_next_7d() -> dict:
    """Consults scheduled in the next 7 days from the GHL appointment CACHE
    (read-only; kept status only — cancelled never counts)."""
    import consult_schedule as CS
    now = now_sydney()
    horizon = now + dt.timedelta(days=7)
    cache = CS._cache()
    upcoming = []
    for cid, hit in (cache or {}).items():
        appts = (hit or {}).get("appts") or []
        cur, _dead = CS.pick_current(appts, now=now)
        if not cur:
            continue
        d = CS.parse_appt_dt(cur.get("startTime"))
        if d and now <= d <= horizon:
            upcoming.append({"when": d.isoformat(),
                             "formatted": CS.format_consult(d),
                             "contact_id": cid,
                             "status": (cur.get("appointmentStatus")
                                        or cur.get("status") or "")})
    upcoming.sort(key=lambda u: u["when"])
    return {"count": len(upcoming), "consults": upcoming[:25],
            "source": "GHL appointment cache (read-only, kept status; "
                      "cancelled never counts)"}


def expiring_preview(pins: dict | None, slider_pct: float | None,
                     horizon_months: int = 15) -> dict:
    """The projection-page toggle path: SCENARIO book deltas only — no
    declaration, no journal, nothing persisted. Returns the book MRR path
    under (pins, slider) beside the un-pinned path."""
    d = measured_defaults()
    base_resign = float(((d["items"].get("renewal_rate") or {}).get("value")) or 0.0)
    resign = (slider_pct / 100.0) if slider_pct is not None else base_resign
    m0 = _month_add(str(today_sydney())[:7], 1)
    with_pins = book_state(horizon_months, m0, resign, pins or {})
    without = book_state(horizon_months, m0, resign, {})
    # per-month MRR the pins moved from the slider lane to committed-like
    # continuation — the chart overlay shifts exactly this between layers
    pin_add = [round(a - b, 2) for a, b in zip(with_pins["mrr"], without["mrr"])]
    return {"start_month": m0,
            "book_mrr": with_pins["mrr"], "book_mrr_unpinned": without["mrr"],
            "pin_add": pin_add,
            "resign_rate_applied": resign,
            "label": "SCENARIO PREVIEW — pins journal nothing; the "
                     "declaration flow is the only path to actuals"}


def simulate_month(inputs: dict | None = None, spend: float | None = None,
                   cpl_override: float | None = None,
                   cpl_curve: bool = False) -> dict:
    """THE SIMULATOR's single-month chain — the SAME formulas as forward()
    with the lag collapsed to this month (identity-tested against forward's
    first month under lag [1,0,0]). Constant CPL by default; the measured
    curve only when cpl_curve=True. Pure arithmetic on the engine's measured
    defaults — a labelled what-if, writes nothing."""
    inp = {**default_inputs(), **(inputs or {})}
    S = float(spend if spend is not None else inp["spend_path"].get("start") or 0)
    S0 = float(inp["spend_path"].get("start") or 1.0) or 1.0
    cpl0 = float(cpl_override if cpl_override is not None else inp["cpl0"])
    eps = float(inp["epsilon"]) if cpl_curve else 0.0
    cpl_eff = cpl0 * ((S / S0) ** eps if S > 0 and eps else 1.0)
    leads = S / cpl_eff if cpl_eff > 0 else 0.0
    calls = leads * float(inp["set_rate"])
    shows = calls * float(inp["show_rate"])
    clients = shows * float(inp["close_rate"])
    pkgs = inp["packages"]
    mix = _norm_mix(inp["deal_mix"], pkgs)
    contract_mix = sum(mix[p] * float((pkgs.get(p) or {}).get("contract") or 0)
                       for p in mix)
    mrr_mix = sum(mix[p] * float((pkgs.get(p) or {}).get("mrr") or 0) for p in mix)
    m0_share = sum(mix[p] * ((pkgs.get(p) or {}).get("cash_schedule") or [0])[0]
                   for p in mix)
    margin_mix = sum(mix[p] * float((pkgs.get(p) or {}).get("gross_margin_pct")
                                    or FY26_MARGIN_PCT) / 100 for p in mix)
    cash_now = clients * m0_share * contract_mix
    cash_term = clients * contract_mix
    mrr_added = clients * mrr_mix
    comm_rate = float(inp["commission_pct_of_cash"])
    tooling = float(inp["sales_tooling_monthly"])
    commissions_term = comm_rate * cash_term
    cac = ((S + commissions_term + tooling) / clients) if clients >= 0.01 else None
    cac_spend_only = (S / clients) if clients >= 0.01 else None
    ltgp_per_client = contract_mix * margin_mix
    return {"spend": round(S, 2), "cpl_effective": round(cpl_eff, 2),
            "cpl_base": round(cpl0, 2), "cpl_curve": bool(cpl_curve),
            "leads": round(leads, 1), "calls": round(calls, 1),
            "shows": round(shows, 1), "clients": round(clients, 2),
            "cash_this_month": round(cash_now, 2),
            "cash_over_term": round(cash_term, 2),
            "mrr_added": round(mrr_added, 2),
            "commissions_over_term": round(commissions_term, 2),
            "cac": round(cac, 2) if cac else None,
            "cac_spend_only": round(cac_spend_only, 2) if cac_spend_only else None,
            "ltgp_per_client": round(ltgp_per_client, 2),
            "ltgp_cac": round(ltgp_per_client / cac, 2) if cac else None,
            "mix": {k: round(v, 3) for k, v in mix.items()},
            "contract_avg": round(contract_mix, 2),
            "mrr_avg": round(mrr_mix, 2),
            "margin_avg": round(margin_mix, 4),
            "tooling": tooling,
            "comm_rate": comm_rate,
            "epsilon": float(inp["epsilon"]),
            "spend_baseline": S0,
            "m0_share": round(m0_share, 4),
            "rates": {"set": inp["set_rate"], "show": inp["show_rate"],
                      "close": inp["close_rate"]},
            "label": "what-if — never the books"}


def confidence_word(n) -> str:
    """Sample-size honesty IN WORDS (the registry's language)."""
    if n is None:
        return "rough"
    n = int(n)
    if n >= 60:
        return "solid"
    if n >= 20:
        return "fair"
    return "rough"


def accuracy_sentence() -> str:
    """The backtest verdict as ONE plain sentence for the top of the
    simulator — real numbers, no jargon."""
    bt = kv_store.get(K_BACKTEST) or {}
    mape = bt.get("mape_pct") or {}
    if not any(v is not None for v in mape.values()):
        return ("This model hasn't been scored against real months yet — "
                "treat it as a compass, not a speedometer.")
    bits = []
    if mape.get("leads") is not None:
        bits.append(f"within about ±{mape['leads']:.0f}% on leads")
    if mape.get("closes") is not None:
        # translate the % into clients-per-month at the current run rate
        rows = bt.get("months") or []
        actuals = [r["closes"]["actual"] for r in rows if r.get("closes")]
        avg = (sum(actuals) / len(actuals)) if actuals else None
        if avg is not None:
            off = round(avg * mape["closes"] / 100)
            bits.append(f"about ±{max(off, 1):.0f} client(s) a month on signings")
        else:
            bits.append(f"±{mape['closes']:.0f}% on signings")
    return ("Over the last 3 months this model was " + " and ".join(bits) +
            " — a compass, not a speedometer (one of those months had a "
            "patchy tracker).")


def sentinel_watch() -> list[dict]:
    """The compass's sentinel rung → feed:extra:compass: backtest drift ·
    plan-vs-actual variance · capacity threshold inside the hire lead time."""
    items = []
    try:
        bt = kv_store.get(K_BACKTEST) or {}
        for stage, v in (bt.get("mape_pct") or {}).items():
            if v is not None and v > 35:
                items.append({"severity": "S2", "category": "compass",
                              "title": f"compass calibration drift — {stage} "
                                       f"MAPE {v}%",
                              "action": "the measured rates moved — re-read "
                                        "/scale calibration before trusting "
                                        "forward runs at this stage"})
    except Exception as e:  # noqa: BLE001
        logger.info("compass backtest watch failed: %s", e)
    try:
        pv = plan_vs_actual()
        for r in (pv.get("rows") or []):
            if r.get("partial") or r.get("error"):
                continue
            for hint in r.get("cause_hints") or []:
                items.append({"severity": "S2", "category": "compass",
                              "title": f"Plan 2027 variance — {r['month']}",
                              "action": hint})
    except Exception as e:  # noqa: BLE001
        logger.info("compass plan watch failed: %s", e)
    try:
        run = (kv_store.get("compass:base_run") or {}).get("run") or {}
        lead_m = math.ceil(HIRE_LEAD_WEEKS / 4.33)
        for m in (run.get("months") or [])[:lead_m + 1]:
            u = m.get("utilisation") or {}
            for role, pct in u.items():
                if pct and pct > 90:
                    items.append({"severity": "S2", "category": "compass",
                                  "title": f"capacity threshold — {role} at "
                                           f"{pct:.0f}% in {m['month']} "
                                           f"(inside the {HIRE_LEAD_WEEKS}w "
                                           "hire lead time)",
                                  "action": "open /scale team view — the "
                                            "hire card is dated; ordering "
                                            "later than it says means the "
                                            "constraint binds"})
                    break
            else:
                continue
            break
    except Exception as e:  # noqa: BLE001
        logger.info("compass capacity watch failed: %s", e)
    kv_store.put("feed:extra:compass", items[:10])
    return items


def refresh_cache() -> None:
    """Rides the scheduled loop: defaults + pulse + the Base first-paint run
    always; backtest monthly (kv-stamped)."""
    try:
        measured_defaults(force=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("compass defaults refresh failed: %s", e)
    try:
        sales_pulse(fresh=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("compass pulse refresh failed: %s", e)
    try:
        run = forward(default_inputs())
        kv_store.put("compass:base_run", {"computed_at": now_sydney().isoformat(),
                                          "run": run})
    except Exception as e:  # noqa: BLE001
        logger.warning("compass base-run refresh failed: %s", e)
    try:
        stamp = "compass:backtest:stamp:" + str(today_sydney())[:7]
        if kv_store.put_if_absent(stamp, {"at": now_sydney().isoformat()}):
            backtest()
    except Exception as e:  # noqa: BLE001
        logger.warning("compass backtest refresh failed: %s", e)
    try:
        sentinel_watch()
    except Exception as e:  # noqa: BLE001
        logger.warning("compass sentinel watch failed: %s", e)
