"""
forecasting_engine.py
---------------------
The projection layer — 13-week cash flow, MRR scenarios, dynamic runway, and forecast-accuracy
tracking. Every number is a PROJECTION with VISIBLE, ADJUSTABLE assumptions (never presented as an
actual, never contaminating actuals). Inputs are deterministic/one-engine (MRR from client_health,
cash inflow from Stripe, burn from the engine, velocity from capacity_engine); the assumptions are
Rydel's judgment inputs (kv_store, "set by you", voice-tunable).

HONESTY ARCHITECTURE (non-negotiable):
- labelled PROJECTION; assumptions shown + adjustable; confidence from input volatility; small-sample
  flags; separate from actuals.
- FORECAST ACCURACY: each projection is logged; when actuals land, projected-vs-actual + running bias
  is shown ("my last 3 MRR forecasts ran +4% optimistic") — a forecaster that grades itself.

KEY INSIGHT this surfaces: static runway (cash ÷ burn) assumes ZERO inflow. The business is
cash-positive (inflow > outflow), so dynamic runway is far longer — cash is growing, not draining.
"""
from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_K_ASSUMPTIONS = "forecast:assumptions"
_K_PROJECTION_LOG = "forecast:projection_log"

DEFAULT_ASSUMPTIONS = {
    "monthly_cash_inflow": None,      # default = Stripe trailing-30d gross (actual cash); adjustable
    "collection_rate_pct": 100,       # % of expected new-deal cash actually collected
    "net_new_closes_per_month": None,  # default = capacity_engine net velocity; adjustable
    "monthly_churn_clients": None,    # default = velocity churn; adjustable
    "avg_mrr_per_client": None,       # default = MRR / active clients
    "weekly_tax_setaside": 0,         # BAS/tax set-aside per week (0 = off; adjustable)
    "renewal_rate_pct": None,         # % of expiring contracts that renew; default = historical (0%)
    "php_per_aud": 43,
    "horizon_weeks": 13,
    "forecast_months": 6,
}


def assumptions() -> dict:
    a = dict(DEFAULT_ASSUMPTIONS)
    a.update(kv_store.get(_K_ASSUMPTIONS) or {})
    return a


def set_assumption(key: str, value) -> bool:
    if key not in DEFAULT_ASSUMPTIONS:
        return False
    cur = kv_store.get(_K_ASSUMPTIONS) or {}
    cur[key] = value
    kv_store.put(_K_ASSUMPTIONS, cur)
    return True


# ── Deterministic base inputs (one engine) ───────────────────────────────────

def _snap():
    from snapshot import load_persisted
    return load_persisted() or {}


def _base_inputs(snap: dict) -> dict:
    """Resolve the projection's base inputs from the engines + assumptions (assumptions win)."""
    a = assumptions()
    ch = snap.get("client_health") or {}
    mrr = ch.get("current_mrr") or 0
    active = (snap.get("active_clients") or {}).get("active_count") or ch.get("active_count") or 0
    cp = snap.get("cash_position") or {}
    cash = cp.get("cash_in_bank")
    burn = cp.get("total_monthly_burn") or 0

    # actual cash inflow run-rate — Stripe trailing-30d gross (the real money in), adjustable
    stripe_rev = (((snap.get("stripe") or {}).get("revenue") or {}).get("current") or {}).get("total_aud")
    inflow = a["monthly_cash_inflow"] if a["monthly_cash_inflow"] is not None else stripe_rev

    # velocity + churn from the one engine (capacity_engine), adjustable
    try:
        import capacity_engine
        vel = capacity_engine.net_velocity(snap)
        closes_pm = vel["90d"]["closes"] / 3.0
        churn_pm = vel["90d"]["churn"] / 3.0
        noisy = vel["90d"]["noisy"]
    except Exception:
        closes_pm, churn_pm, noisy = 0, 0, True
    if a["net_new_closes_per_month"] is not None:
        closes_pm = a["net_new_closes_per_month"]
    if a["monthly_churn_clients"] is not None:
        churn_pm = a["monthly_churn_clients"]
    avg_mrr = a["avg_mrr_per_client"] if a["avg_mrr_per_client"] is not None else (round(mrr / active, 2) if active else 0)

    # EXPIRY DRAG: forward_mrr projects MRR decline from contracts expiring/not renewing — attrition
    # that recent-churn-events (often 0) miss. Use the avg monthly MRR decline as the attrition base,
    # so the forecast isn't optimistically flat. (New-deal MRR is added on top in the scenarios.)
    # forward_mrr's deltas assume 0% renewal (a pure floor). Apply an ADJUSTABLE renewal rate
    # (default = the historical rate, currently 0/12 = 0%) so the attrition reflects Rydel's view.
    expiry_drag = 0.0
    renewal_rate = 0.0
    try:
        fmb = snap.get("forward_mrr") or {}
        renewal_rate = ((fmb.get("renewal_rate_historical") or {}).get("rate") or 0.0)
        if a["renewal_rate_pct"] is not None:
            renewal_rate = a["renewal_rate_pct"] / 100.0
        drags = [-(m.get("delta") or 0) for m in (fmb.get("forward_months") or []) if (m.get("delta") or 0) < 0]
        if drags:
            expiry_drag = round(sum(drags) / len(drags) * (1 - renewal_rate), 2)
    except Exception:
        pass

    return {"mrr": mrr, "active": active, "cash": cash, "burn": burn,
            "monthly_cash_inflow": inflow, "closes_per_month": round(closes_pm, 2),
            "churn_per_month": round(churn_pm, 2), "avg_mrr_per_client": avg_mrr,
            "expiry_drag_mrr": expiry_drag, "renewal_rate_pct": round(renewal_rate * 100, 1),
            "collection_rate_pct": a["collection_rate_pct"], "noisy": noisy,
            "weekly_tax_setaside": a["weekly_tax_setaside"]}


# ── 13-week cash-flow forecast ───────────────────────────────────────────────

def cash_flow_13wk(snap: dict | None = None) -> dict:
    """Week-by-week projected cash from known inflows (recurring cash run-rate + expected new-deal
    cash) − outflows (burn + tax set-aside). Returns the curve, the minimum week, and drivers.
    PROJECTION — assumptions visible + adjustable."""
    snap = snap or _snap()
    b = _base_inputs(snap)
    a = assumptions()
    weeks = int(a["horizon_weeks"])
    start = b["cash"]
    if start is None or b["monthly_cash_inflow"] is None:
        return {"available": False, "reason": "cash-on-hand or Stripe cash inflow unavailable",
                "is_projection": True}

    weekly_inflow = b["monthly_cash_inflow"] / (52 / 12)   # recurring cash run-rate → weekly
    # expected NEW-deal cash/week from velocity × avg cash per close × collection rate
    new_cash_pm = b["closes_per_month"] * b["avg_mrr_per_client"] * (b["collection_rate_pct"] / 100)
    weekly_new = new_cash_pm / (52 / 12)
    weekly_outflow = b["burn"] / (52 / 12) + b["weekly_tax_setaside"]
    net_weekly = weekly_inflow + weekly_new - weekly_outflow

    # BAS/PAYG obligations land in their DUE WEEKS (the one bas_engine — estimates,
    # labelled). Skipped automatically if the user set a manual weekly_tax_setaside
    # (their smoothing wins; no double-count).
    obligations, ob_hits = [], {}
    if not b["weekly_tax_setaside"]:
        try:
            import bas_engine
            obligations = bas_engine.scheduled_obligations()
        except Exception:
            obligations = []

    today = today_sydney()
    curve, cash = [], start
    for w in range(1, weeks + 1):
        cash += net_weekly
        we = today + dt.timedelta(weeks=w)
        for ob in obligations:
            try:
                d = dt.date.fromisoformat(ob["due"])
            except (ValueError, TypeError):
                continue
            if we - dt.timedelta(days=6) <= d <= we and (ob["amount"] or 0):
                cash -= ob["amount"]
                ob_hits[str(d)] = {"week": w, "label": ob["label"],
                                   "amount": ob["amount"], "confidence": ob["confidence"]}
        curve.append({"week": w, "week_ending": str(we),
                      "projected_cash": round(cash, 2)})
    lo = min(curve, key=lambda x: x["projected_cash"])
    return {
        "available": True, "is_projection": True,
        "starting_cash": round(start, 2), "horizon_weeks": weeks,
        "weekly_inflow_recurring": round(weekly_inflow, 2),
        "weekly_inflow_new_deals": round(weekly_new, 2),
        "weekly_outflow": round(weekly_outflow, 2),
        "net_weekly": round(net_weekly, 2),
        "cash_positive": net_weekly >= 0,
        "tax_obligations_in_horizon": ob_hits or None,
        "curve": curve,
        "minimum_week": {"week": lo["week"], "week_ending": lo["week_ending"],
                         "projected_cash": lo["projected_cash"]},
        "ending_cash": curve[-1]["projected_cash"],
        "drivers": {"recurring_cash_monthly": b["monthly_cash_inflow"], "burn_monthly": b["burn"],
                    "new_closes_per_month": b["closes_per_month"], "avg_cash_per_close": b["avg_mrr_per_client"],
                    "collection_rate_pct": b["collection_rate_pct"]},
        "assumptions_note": "PROJECTION — recurring cash = Stripe trailing-30d gross; new-deal cash = "
                            "velocity × avg × collection rate; outflow = engine burn. All adjustable "
                            "(set forecast inflow / collection rate / closes per month).",
        "confidence": "low" if b["noisy"] else "medium",
    }


# ── Dynamic runway (vs static) ───────────────────────────────────────────────

def dynamic_runway(snap: dict | None = None) -> dict:
    """Runway from the cash-flow forecast (incorporates inflows) alongside the conservative static
    runway (cash ÷ burn, no inflow). The honest picture when the business is cash-positive."""
    snap = snap or _snap()
    b = _base_inputs(snap)
    cf = cash_flow_13wk(snap)
    cp = snap.get("cash_position") or {}
    static = cp.get("runway_months")
    if not cf.get("available"):
        return {"available": False, "static_runway_months": static, "is_projection": True}
    net_weekly = cf["net_weekly"]
    if net_weekly >= 0:
        dyn = None  # cash-positive → not draining
        read = ("cash-positive — projected +${:,.0f}/mo, so cash GROWS; static runway ({}mo) assumes "
                "zero inflow and understates your position.").format(net_weekly * 52 / 12, static)
    else:
        months = (b["cash"] / (-net_weekly * 52 / 12)) if net_weekly else None
        dyn = round(months, 1) if months else None
        read = f"dynamic runway ~{dyn}mo including projected inflows (static is {static}mo, no inflow)."
    return {"available": True, "is_projection": True, "static_runway_months": static,
            "dynamic_runway_months": dyn, "net_monthly": round(net_weekly * 52 / 12, 2),
            "cash_positive": net_weekly >= 0, "read": read}


# ── MRR forecast + scenarios + what-ifs ──────────────────────────────────────

def mrr_forecast(snap: dict | None = None, months: int | None = None,
                 velocity_delta: float = 0.0, churn_mult: float = 1.0) -> dict:
    """MRR projected forward under BASE (trailing velocity), with best/worst scenarios and live
    what-ifs (velocity_delta adds closes/mo; churn_mult scales churn). Deterministic base, adjustable.
    PROJECTION."""
    snap = snap or _snap()
    b = _base_inputs(snap)
    months = months or int(assumptions()["forecast_months"])
    avg = b["avg_mrr_per_client"]

    drag = b.get("expiry_drag_mrr") or 0.0   # MRR/mo lost to expiries (attrition)

    def project(closes_pm, churn_pm, attrition_mult=1.0):
        rows, mrr = [], b["mrr"]
        # net MRR/mo = new-deal MRR − (mid-contract churn + expiry drag) × attrition scaling
        net_mrr = closes_pm * avg - (churn_pm * avg + drag) * attrition_mult
        for m in range(1, months + 1):
            mrr = max(0, mrr + net_mrr)
            rows.append({"month": m, "mrr": round(mrr, 2)})
        return rows, round(net_mrr, 2)

    base_closes = b["closes_per_month"] + velocity_delta
    base, base_net = project(base_closes, b["churn_per_month"], churn_mult)
    best, best_net = project(base_closes * 1.5, b["churn_per_month"], 0.5)      # more sales, less attrition
    worst, worst_net = project(base_closes * 0.5, b["churn_per_month"], 2.0)    # fewer sales, more attrition

    return {
        "available": True, "is_projection": True, "months": months,
        "current_mrr": b["mrr"], "avg_mrr_per_client": avg,
        "base_closes_per_month": round(base_closes, 2),
        "base_churn_per_month": round(b["churn_per_month"] * churn_mult, 2),
        "expiry_drag_mrr_per_month": drag,
        "scenarios": {
            "base": {"net_mrr_per_month": base_net, "curve": base, "end_mrr": base[-1]["mrr"]},
            "best": {"net_mrr_per_month": best_net, "curve": best, "end_mrr": best[-1]["mrr"],
                     "note": "velocity +50%, churn −50%"},
            "worst": {"net_mrr_per_month": worst_net, "curve": worst, "end_mrr": worst[-1]["mrr"],
                      "note": "velocity −50%, churn ×2"},
        },
        "what_if_applied": {"velocity_delta": velocity_delta, "churn_mult": churn_mult}
                           if (velocity_delta or churn_mult != 1.0) else None,
        "confidence": "low" if b["noisy"] else "medium",
        "renewal_rate_pct": b.get("renewal_rate_pct"),
        "assumptions_note": (f"PROJECTION — new-deal MRR (trailing velocity × avg) minus attrition "
                             f"(expiries at {b.get('renewal_rate_pct')}% renewal + mid-contract churn). "
                             "At the historical 0% renewal, expiries outpace new deals. Adjustable: "
                             "set renewal rate / closes per month / churn per month / avg MRR."),
    }


# ── Forecast accuracy tracking ───────────────────────────────────────────────

def record_projection(kind: str, horizon_label: str, projected: float, for_period: str) -> None:
    """Log a projection so it can be graded when the actual lands."""
    log = kv_store.get(_K_PROJECTION_LOG) or []
    log.append({"kind": kind, "horizon": horizon_label, "projected": projected,
                "for_period": for_period, "made_on": str(today_sydney()), "actual": None})
    kv_store.put(_K_PROJECTION_LOG, log[-200:])


def grade_projection(kind: str, for_period: str, actual: float) -> None:
    log = kv_store.get(_K_PROJECTION_LOG) or []
    for r in log:
        if r["kind"] == kind and r["for_period"] == for_period and r.get("actual") is None:
            r["actual"] = actual
            r["error_pct"] = round((r["projected"] - actual) / actual * 100, 1) if actual else None
    kv_store.put(_K_PROJECTION_LOG, log)


def accuracy(kind: str = "mrr") -> dict:
    """Running projected-vs-actual bias — 'my last N forecasts ran +X% optimistic'."""
    log = [r for r in (kv_store.get(_K_PROJECTION_LOG) or [])
           if r["kind"] == kind and r.get("error_pct") is not None]
    if not log:
        return {"available": False, "graded_count": 0}
    recent = log[-5:]
    bias = round(sum(r["error_pct"] for r in recent) / len(recent), 1)
    return {"available": True, "graded_count": len(log), "recent_bias_pct": bias,
            "direction": "optimistic" if bias > 0 else "conservative",
            "recent": [{"for": r["for_period"], "projected": r["projected"],
                        "actual": r["actual"], "error_pct": r["error_pct"]} for r in recent]}


def build_forecast(snap: dict | None = None) -> dict:
    """The whole forecasting block for the snapshot/dashboard/endpoint."""
    snap = snap or _snap()
    try:
        return {"available": True, "is_projection": True, "assumptions": assumptions(),
                "cash_flow_13wk": cash_flow_13wk(snap), "dynamic_runway": dynamic_runway(snap),
                "mrr_forecast": mrr_forecast(snap), "accuracy": accuracy("mrr")}
    except Exception as e:
        logger.warning("build_forecast failed: %s", e)
        return {"available": False, "reason": f"{type(e).__name__}: {e}", "is_projection": True}


# ── Conversational handlers (TIER 2, deterministic base — always labelled PROJECTION) ────

import re as _re


def _fmt_scenario(sc: dict, months: int) -> str:
    return f"${sc['end_mrr']:,.0f} in {months}mo ({'+' if sc['net_mrr_per_month'] >= 0 else ''}${sc['net_mrr_per_month']:,.0f}/mo)"


def handle_forecast_command(text: str) -> tuple[str | None, bool]:
    """Cash-flow / MRR / runway forecasts + what-ifs + accuracy. Deterministic base; PROJECTION-labelled."""
    if not text:
        return None, False
    low = text.lower()
    snap = _snap()

    # set an assumption: "set forecast inflow to 60000", "set collection rate to 80"
    ms = _re.search(r"\bset (forecast |the )?(inflow|collection rate|closes per month|churn per month|"
                    r"tax set-?aside|avg mrr|renewal rate)\b.*?(\d+(?:\.\d+)?)", low)
    if ms:
        km = {"inflow": "monthly_cash_inflow", "collection rate": "collection_rate_pct",
              "closes per month": "net_new_closes_per_month", "churn per month": "monthly_churn_clients",
              "tax set-aside": "weekly_tax_setaside", "tax setaside": "weekly_tax_setaside",
              "avg mrr": "avg_mrr_per_client", "renewal rate": "renewal_rate_pct"}.get(ms.group(2))
        if km and set_assumption(km, float(ms.group(3))):
            return f"Set — forecast {ms.group(2)} is now {ms.group(3)} (your assumption; projections use it).", True

    # what-if scenarios
    wm_churn = _re.search(r"what if churn (doubl|2x|halv|drops? by half|tripl)", low)
    wm_closes = _re.search(r"what if (we )?close (\d+) (more|fewer|less)", low)
    if wm_churn or wm_closes or _re.search(r"\bwhat if\b", low):
        churn_mult, vel_delta = 1.0, 0.0
        if wm_churn:
            g = wm_churn.group(1)
            churn_mult = 2.0 if ("doubl" in g or "2x" in g) else (3.0 if "tripl" in g else 0.5)
        if wm_closes:
            n = int(wm_closes.group(2))
            vel_delta = n if "more" in wm_closes.group(3) else -n
        mf = mrr_forecast(snap, velocity_delta=vel_delta, churn_mult=churn_mult)
        base = mf["scenarios"]["base"]
        lbl = []
        if churn_mult != 1.0:
            lbl.append(f"churn ×{churn_mult}")
        if vel_delta:
            lbl.append(f"{'+' if vel_delta > 0 else ''}{vel_delta} closes/mo")
        return (f"PROJECTION — with {', '.join(lbl) or 'that'}: MRR to {_fmt_scenario(base, mf['months'])} "
                f"vs ${mf['current_mrr']:,.0f} now. {'Small sample — treat as indicative.' if mf['confidence']=='low' else ''} "
                "Adjustable if my velocity/churn base is off."), True

    # dynamic / real runway
    if _re.search(r"\b(dynamic|real|true) runway\b|\brunway.*(with|including) (inflow|income|revenue)|"
                  r"\bare we (actually )?(burning|cash.?positive)\b|\bcash.?positive\b", low):
        dr = dynamic_runway(snap)
        if not dr.get("available"):
            return "I can't read cash/inflow to project runway right now.", True
        return "PROJECTION — " + dr["read"], True

    # 13-week cash flow / tight week
    if _re.search(r"\b(cash ?flow|13.?week|cash forecast|cash (curve|projection)|forecast.*cash)\b|"
                  r"\b(tight|tightest|minimum|lowest) (week|cash)\b|\bwhen.*(cash|tight)", low):
        cf = cash_flow_13wk(snap)
        if not cf.get("available"):
            return f"I can't build the cash forecast — {cf.get('reason')}.", True
        mw = cf["minimum_week"]
        if cf["cash_positive"]:
            body = (f"cash-positive — net +${cf['net_weekly'] * 52 / 12:,.0f}/mo, so cash grows from "
                    f"${cf['starting_cash']:,.0f} to ~${cf['ending_cash']:,.0f} over 13 weeks. No tight week.")
        else:
            body = (f"net ${cf['net_weekly']:,.0f}/week — tightest is week {mw['week']} "
                    f"({mw['week_ending']}) at ~${mw['projected_cash']:,.0f}. Starting ${cf['starting_cash']:,.0f}.")
        _mf = mrr_forecast(snap)
        _caveat = (" Caveat: this holds recurring cash flat — if the projected MRR decline "
                   "(see MRR forecast) lands, inflow tapers too." if _mf["scenarios"]["base"]["net_mrr_per_month"] < 0 else "")
        return (f"PROJECTION (13-week cash flow) — {body} Drivers: ${cf['drivers']['recurring_cash_monthly']:,.0f}/mo "
                f"cash in, ${cf['drivers']['burn_monthly']:,.0f}/mo burn.{_caveat} Assumptions adjustable."), True

    # MRR forecast / scenarios
    if _re.search(r"\b(mrr|revenue) (forecast|projection|outlook)|\bwhere('?s| is) mrr (going|headed)|"
                  r"\bproject (the )?mrr\b|\bbest case\b|\bworst case\b|\bscenarios?\b", low):
        mf = mrr_forecast(snap)
        sc = mf["scenarios"]
        decline = sc["base"]["net_mrr_per_month"] < 0
        tail = (f" The base DECLINES because at {mf['renewal_rate_pct']}% renewal (historical), "
                "expiries outpace new deals — retention is the lever. Set a higher renewal rate to "
                "model fixing it." if decline else "")
        return (f"PROJECTION ({mf['months']}mo MRR) — "
                f"BASE {_fmt_scenario(sc['base'], mf['months'])}; "
                f"BEST {_fmt_scenario(sc['best'], mf['months'])}; "
                f"WORST {_fmt_scenario(sc['worst'], mf['months'])}. Now ${mf['current_mrr']:,.0f}.{tail}"), True

    # forecast accuracy
    if _re.search(r"\bhow accurate\b.*forecast|\bforecast accuracy\b|\bhow (good|reliable) (are|is) your "
                  r"(forecast|projection)|track record\b", low):
        ac = accuracy("mrr")
        if not ac.get("available"):
            return ("No graded forecasts yet — I log each projection and grade it when the actual lands, "
                    "then I can tell you my running bias. Nothing to report until a period closes."), True
        return (f"My last {len(ac['recent'])} MRR forecasts ran {ac['recent_bias_pct']:+}% "
                f"({ac['direction']}) on average, across {ac['graded_count']} graded."), True

    return None, False
