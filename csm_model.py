"""csm_model.py — the ONE CSM-investment model core (pure math, no I/O).

Reproduces the Sequence-to-Success v2 / Served_Retention_CSM_Model_v2 figures
as a regression target, then layers the honest-ROI rulings (DECISIONS #146):

  R1  GROSS ROI = credited lift / FULLY-LOADED cost. The source's 3.5x uses
      $80k unloaded; loaded (~$89.6k at 12% SG) is rendered beside it.
  R2  TWO CLOCKS, never blended: COHORT (lifetime lift of the year-one book
      / year-one cost — the source model's own convention, surfaced) and
      STEADY-STATE (trailing-12m credited lift / trailing-12m loaded cost,
      from month 13). The 4x target lives on the COHORT clock. Year-1 4x
      exists in NO scenario (upside Y1 ~= 2.6x) — stated, never a verdict.
  R3  LAYER vs HIRE: structural-tagged lift (guarantee-policy refund
      avoidance) is excluded from the HIRE lens.
  R4  FUNDING PATH != RETURN. The director-comp offset finances the hire;
      it never changes the hire's economics. Offset figures arrive ONLY via
      owner config (never constants in this file — grep-asserted).
  R5  Lift is credited over Gate-0 baseline only, evidence-linked.
  R6  Estimates, not advice.

SOURCE-MODEL CONVENTIONS SURFACED (never silently fixed):
  * cohort ROI divides LIFETIME lift by ONE YEAR of cost (labelled).
  * contribution margin implied by the workbook ~= 55.2% (8,867/16,053) —
    differs from FY26 P&L CM 42.9% and the Notion page's ~68%; all three
    rendered as a labelled note, none silently substituted.
  * printed base "net Y1 $73k" vs component-derived $74k (154k - 80k):
    source rounding; regression tolerances carry it.
  * the $6.5k/mo break-even treats attributable MRR at ~100% margin;
    margin-adjusted (~68% CM) the same cost needs ~$9.5k — both stated.

The per-client DECOMPOSITION (avg-MRR cascade) is the engine's own,
calibrated to the source anchors because the workbook internals are not
available locally; every decomposed slider is labelled what-if. The
scenario ANCHORS themselves are the source's printed numbers.

All dates are passed in; no clock reads here (see csm_engine for wiring).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# SOURCE REGRESSION TARGETS (Sequence-to-Success v2 — printed figures)
# ---------------------------------------------------------------------------

SOURCE = {
    "per_client_baseline": 26_088.0,
    "per_client_with_csm": 42_141.0,
    "per_client_lift": 16_053.0,
    "per_client_contribution_lift": 8_867.0,
    "book_size": 30,
    "incremental_revenue_y1": 263_000.0,
    "incremental_revenue_lifetime": 482_000.0,
    "contribution_y1": 143_000.0,
    "contribution_lifetime": 266_000.0,
    "refunds_avoided_y1": 11_000.0,
    "refunds_avoided_lifetime": 12_000.0,
    "comp_base_annual": 80_000.0,
    "net_y1": 73_000.0,          # printed; components give 74k — source rounding
    "net_lifetime": 198_000.0,
    "roi_y1": 1.9,
    "roi_lifetime": 3.5,
    "break_even_net_mrr_month6": 6_500.0,
}

# Scenario anchors: renewal rate (%), OTE ($/yr), net Y1, net lifetime — printed.
SCENARIO_ANCHORS = {
    "floor":  {"renewal_pct": 48.0, "ote": 67_000.0, "net_y1": -3_000.0,  "net_lifetime": 49_000.0,  "roi_lifetime": 1.7},
    "base":   {"renewal_pct": 60.0, "ote": 80_000.0, "net_y1": 73_000.0,  "net_lifetime": 198_000.0, "roi_lifetime": 3.5},
    "upside": {"renewal_pct": 72.0, "ote": 88_000.0, "net_y1": 145_000.0, "net_lifetime": 338_000.0, "roi_lifetime": 4.8},
}

# Source placeholders (Gate-0 measurement replaces these; labels ride along).
PLACEHOLDERS = {
    "renewal_rate_baseline_pct": 40.0,
    "in_term_completion_pct": 85.0,
    "refund_cause_split_structural": 0.5,   # unmeasured in source; B2 replaces
}

# Comp table defaults (PDF). The SIGNED OFFER replaces these via config.
COMP_TABLE_DEFAULTS = {
    "base_monthly": 4_000.0,
    "renewal_bonus": 500.0,
    "renewal_clawback_days": 90,
    "lock12_bonus": 800.0,
    "stepup_sprint_pct_first6": 0.10,
    "continuity_save_bonus": 150.0,
    "referral_pct": 0.05,
    "nrr_bonus_quarterly": 1_500.0,
    "nrr_bonus_threshold": 1.00,
    "sg_rate": 0.12,               # verify against payroll config at wiring
    "on_costs_annual": 0.0,        # config; source's loaded quote is SG-only
    "tools_annual": 0.0,
    "employment_form": "employee",  # or "contractor" (flat — no SG/on-costs)
    "variable_floor_quarters": 0,   # guaranteed-variable-floor option
    "variable_floor_quarterly": 0.0,
}

RAMP_MONTHS = 2                    # source: two-month ramp
HORIZON_MONTHS = 36                # cohort lifetime + two steady-state years
CM_SOURCE = SOURCE["per_client_contribution_lift"] / SOURCE["per_client_lift"]  # ~0.5524

CONVENTION_NOTES = [
    "Cohort ROI = LIFETIME lift ÷ ONE YEAR of cost — the source model's own "
    "convention, rendered as 'cohort clock', never blended with steady-state.",
    "Workbook-implied contribution margin ≈ 55.2% (8,867/16,053); FY26 P&L CM "
    "is 42.9%; the Notion plan page uses ~68%. All three shown; the engine "
    "uses the workbook's own margin for regression fidelity.",
    "Printed base net Y1 $73k vs component-derived $74k ($154k credited − "
    "$80k comp): source rounding, carried as regression tolerance.",
    "The $6.5k/mo month-6 break-even divides cost by 12 months at ~100% "
    "margin on attributable MRR; margin-adjusted (~68% CM, per the plan page) "
    "the same cost needs ~$9.5k/mo. Both stated wherever break-even renders.",
    "Refunds-avoided attribution: guarantee-policy-driven avoidance is "
    "STRUCTURAL (the restructure's), relationship-prevented is HIRE's; the "
    "split is a placeholder until B2 measures it.",
]


# ---------------------------------------------------------------------------
# Interpolation on the source's own axis (renewal rate)
# ---------------------------------------------------------------------------

def _lagrange3(x, pts):
    """Quadratic through three (x, y) points."""
    (x0, y0), (x1, y1), (x2, y2) = pts
    return (
        y0 * (x - x1) * (x - x2) / ((x0 - x1) * (x0 - x2))
        + y1 * (x - x0) * (x - x2) / ((x1 - x0) * (x1 - x2))
        + y2 * (x - x0) * (x - x1) / ((x2 - x0) * (x2 - x1))
    )


def _anchor_pts(key):
    a = SCENARIO_ANCHORS
    return [
        (a["floor"]["renewal_pct"], a["floor"][key]),
        (a["base"]["renewal_pct"], a["base"][key]),
        (a["upside"]["renewal_pct"], a["upside"][key]),
    ]


def ote_at(renewal_pct: float) -> float:
    """OTE ($/yr) implied by the source scenarios at a renewal rate."""
    return _lagrange3(renewal_pct, _anchor_pts("ote"))


def credited_lift_lifetime_at(renewal_pct: float) -> float:
    """Credited lifetime lift (contribution + refunds avoided) at a renewal
    rate, on the source's scenario axis. credited = net_lifetime + OTE."""
    pts = [
        (a["renewal_pct"], a["net_lifetime"] + a["ote"])
        for a in SCENARIO_ANCHORS.values()
    ]
    return _lagrange3(renewal_pct, pts)


def credited_lift_y1_at(renewal_pct: float) -> float:
    pts = [
        (a["renewal_pct"], a["net_y1"] + a["ote"])
        for a in SCENARIO_ANCHORS.values()
    ]
    return _lagrange3(renewal_pct, pts)


# ---------------------------------------------------------------------------
# Loaded cost (R1)
# ---------------------------------------------------------------------------

def loaded_cost_annual(ote: float, comp: dict | None = None) -> float:
    """Fully-loaded annual cost. Employee: OTE*(1+SG)+on-costs+tools.
    Contractor: flat OTE + tools."""
    c = dict(COMP_TABLE_DEFAULTS)
    if comp:
        c.update(comp)
    if c.get("employment_form") == "contractor":
        return ote + c["tools_annual"]
    return ote * (1.0 + c["sg_rate"]) + c["on_costs_annual"] + c["tools_annual"]


# ---------------------------------------------------------------------------
# The two ROI clocks (R2) — computed at scenario level
# ---------------------------------------------------------------------------

def scenario_roi(name: str, comp: dict | None = None) -> dict:
    a = SCENARIO_ANCHORS[name]
    credited_l = a["net_lifetime"] + a["ote"]
    credited_y1 = a["net_y1"] + a["ote"]
    loaded = loaded_cost_annual(a["ote"], comp)
    return {
        "scenario": name,
        "renewal_pct": a["renewal_pct"],
        "ote": a["ote"],
        "loaded_cost_y1": round(loaded, 2),
        "credited_lift_y1": credited_y1,
        "credited_lift_lifetime": credited_l,
        # COHORT clock: lifetime lift ÷ one year of cost (source convention, labelled)
        "cohort_roi_unloaded": round(credited_l / a["ote"], 2),
        "cohort_roi_loaded": round(credited_l / loaded, 2),
        "y1_roi_unloaded": round(credited_y1 / a["ote"], 2),
        "y1_roi_loaded": round(credited_y1 / loaded, 2),
        "net_y1_printed": a["net_y1"],
        "net_lifetime_printed": a["net_lifetime"],
    }


def solve_renewal_for_cohort_roi(target: float = 4.0, comp: dict | None = None,
                                 loaded: bool = True) -> dict:
    """The 4x frontier solve: renewal rate at which cohort ROI hits target.
    Bisection on [floor, upside+12] — cost varies with the rate (OTE scales)."""
    def roi(r):
        cost = loaded_cost_annual(ote_at(r), comp) if loaded else ote_at(r)
        return credited_lift_lifetime_at(r) / cost

    lo, hi = 40.0, 90.0
    if roi(hi) < target:
        return {"target": target, "renewal_pct": None,
                "note": "target unreachable inside the modelled range"}
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if roi(mid) < target:
            lo = mid
        else:
            hi = mid
    r = round((lo + hi) / 2.0, 1)
    return {
        "target": target,
        "renewal_pct": r,
        "cohort_roi_at_solution": round(roi(r), 3),
        "between_base_and_upside": (
            SCENARIO_ANCHORS["base"]["renewal_pct"] <= r
            <= SCENARIO_ANCHORS["upside"]["renewal_pct"]
        ),
        "clock": "cohort",
        "cost_basis": "loaded" if loaded else "unloaded",
        "y1_note": "Year-1 4x exists in NO scenario (upside Y1 ~= 2.6x); the "
                   "cohort clock carries the target — leading indicators lead.",
    }


# ---------------------------------------------------------------------------
# Monthly curve (M2) — start-date-driven, 2-month ramp, 36-month horizon
# ---------------------------------------------------------------------------

def monthly_curve(scenario: str = "base", comp: dict | None = None) -> dict:
    """Distribute the scenario's credited lift across HORIZON_MONTHS.
    Convention (engine's own, labelled): months 1-2 ramp at 25%/50% of the
    year-one steady weight; months 3-12 flat so months 1-12 sum to the Y1
    figure; months 13-36 flat so the horizon sums to lifetime. Loaded cost
    accrues evenly from month 1 (year-one OTE basis each year)."""
    a = SCENARIO_ANCHORS[scenario]
    credited_y1 = a["net_y1"] + a["ote"]
    credited_l = a["net_lifetime"] + a["ote"]
    ramp = [0.25, 0.50]
    # w = steady monthly weight for months 3..12: (0.25+0.5+10w') ... solve
    steady_units = sum(ramp) + 10.0
    w_y1 = credited_y1 / steady_units
    lift = [w_y1 * ramp[0], w_y1 * ramp[1]] + [w_y1] * 10
    tail_total = credited_l - credited_y1
    lift += [tail_total / 24.0] * 24
    loaded_m = loaded_cost_annual(a["ote"], comp) / 12.0
    cost = [loaded_m] * HORIZON_MONTHS
    cum_lift, cum_cost, rows = 0.0, 0.0, []
    for i in range(HORIZON_MONTHS):
        cum_lift += lift[i]
        cum_cost += cost[i]
        rows.append({
            "month": i + 1,
            "credited_lift": round(lift[i], 2),
            "loaded_cost": round(cost[i], 2),
            "cum_lift": round(cum_lift, 2),
            "cum_cost": round(cum_cost, 2),
        })
    return {
        "scenario": scenario,
        "ramp_months": RAMP_MONTHS,
        "horizon_months": HORIZON_MONTHS,
        "months": rows,
        "distribution_note": "engine distribution convention (workbook "
                             "monthly internals not available) — labelled",
    }


def steady_state_roi(curve: dict) -> dict:
    """Trailing-12-month credited lift / trailing-12-month loaded cost,
    evaluated at each month from 13 (post-ramp) — never blended with cohort."""
    rows = curve["months"]
    out = []
    for i in range(12, len(rows)):
        window = rows[i - 11: i + 1]
        lift = sum(r["credited_lift"] for r in window)
        cost = sum(r["loaded_cost"] for r in window)
        out.append({"month": rows[i]["month"],
                    "t12m_lift": round(lift, 2),
                    "t12m_cost": round(cost, 2),
                    "steady_state_roi": round(lift / cost, 2) if cost else None})
    return {"clock": "steady_state", "from_month": 13, "series": out}


# ---------------------------------------------------------------------------
# Layer vs hire lens (R3)
# ---------------------------------------------------------------------------

ATTRIBUTION_DEFAULTS = {
    "renewals_above_baseline": "hire",
    "continuity_captures": "hire",       # the floor's existence is structural;
                                         # a walked-down 'no' is hers
    "expansion": "hire",
    "in_term_completion": "hire",
    "referrals": "hire",
    "refunds_avoided_policy": "structural",
    "refunds_avoided_relationship": "hire",
}


def layer_vs_hire(scenario: str = "base", structural_split: float | None = None,
                  comp: dict | None = None) -> dict:
    """LAYER ROI (the source's, everything credited) vs HIRE ROI (excludes
    structural-tagged lift: the policy-driven share of refunds avoided)."""
    split = PLACEHOLDERS["refund_cause_split_structural"] if structural_split is None else structural_split
    a = SCENARIO_ANCHORS[scenario]
    credited_l = a["net_lifetime"] + a["ote"]
    # Refunds-avoided is book-level in the source; scale by scenario vs base.
    scale = credited_l / (SCENARIO_ANCHORS["base"]["net_lifetime"] + SCENARIO_ANCHORS["base"]["ote"])
    refunds_l = SOURCE["refunds_avoided_lifetime"] * scale
    structural = refunds_l * split
    loaded = loaded_cost_annual(a["ote"], comp)
    return {
        "scenario": scenario,
        "structural_split": split,
        "structural_split_label": ("placeholder" if structural_split is None
                                   else "measured/config"),
        "structural_lift": round(structural, 2),
        "layer_roi_loaded": round(credited_l / loaded, 2),
        "hire_roi_loaded": round((credited_l - structural) / loaded, 2),
        "note": "On source numbers the structural share is small (~$11-12k of "
                "~$278k credited at base) — the hire lens moves the target "
                "little; both lenses rendered.",
        "attribution_tags": ATTRIBUTION_DEFAULTS,
    }


# ---------------------------------------------------------------------------
# Funding paths (R4) — pure function of OWNER CONFIG inputs; no constants
# ---------------------------------------------------------------------------

def funding_paths(csm_loaded_annual: float,
                  director_current_annual: float | None,
                  director_proposed_annual: float | None,
                  sg_rate: float = 0.12,
                  discretionary_cash: float = 94_000.0) -> dict:
    """Two paths side by side. Director figures arrive from owner config at
    call time — if unset, the path renders as 'offset not configured'.
    Loaded offset = (current - proposed) * (1 + SG): reducing director gross
    also reduces the SG paid on it."""
    if director_current_annual is None or director_proposed_annual is None:
        return {
            "configured": False,
            "offset_funded": None,
            "business_cash_funded": {
                "fixed_cost_delta": round(csm_loaded_annual, 2),
                "runway_months_of_base": round(discretionary_cash / (csm_loaded_annual / 12.0), 1),
                "director_income": "unchanged",
            },
            "note": "director comp offset (owner config) not set — enter "
                    "current + proposed figures in the owner config panel",
        }
    offset_loaded = (director_current_annual - director_proposed_annual) * (1.0 + sg_rate)
    delta = csm_loaded_annual - offset_loaded
    return {
        "configured": True,
        "offset_funded": {
            "loaded_offset": round(offset_loaded, 2),
            "fixed_cost_delta": round(delta, 2),
            "business_cash": "untouched",
            "downside_bounded_to": "director income",
        },
        "business_cash_funded": {
            "fixed_cost_delta": round(csm_loaded_annual, 2),
            "runway_months_of_base": round(discretionary_cash / (csm_loaded_annual / 12.0), 1),
            "director_income": "unchanged",
        },
        "financing_view_warning": "return-per-$-of-NET-cost is a financing "
                                  "view, NEVER ROI (near-zero denominator)",
    }


# ---------------------------------------------------------------------------
# Comp accrual (M4) — event-based, clawback-aware
# ---------------------------------------------------------------------------

def accrue_comp(events: list[dict], comp: dict | None = None) -> dict:
    """events: [{type, amount?, first6_value?, months_to_churn?}, ...]
    types: renewal | lock12 | stepup | sprint | continuity_save | referral
           | nrr_quarter (with {nrr: float})
    A renewal followed by churn within clawback window reverses its bonus."""
    c = dict(COMP_TABLE_DEFAULTS)
    if comp:
        c.update(comp)
    lines, total = [], 0.0
    for e in events:
        t = e.get("type")
        amt = 0.0
        note = ""
        if t == "renewal":
            amt = c["renewal_bonus"]
            churn_m = e.get("months_to_churn")
            if churn_m is not None and churn_m * 30 <= c["renewal_clawback_days"]:
                amt = 0.0
                note = "clawed back (churn within %sd)" % c["renewal_clawback_days"]
        elif t == "lock12":
            amt = c["lock12_bonus"]
        elif t in ("stepup", "sprint"):
            amt = c["stepup_sprint_pct_first6"] * float(e.get("first6_value", 0.0))
        elif t == "continuity_save":
            amt = c["continuity_save_bonus"]
        elif t == "referral":
            amt = c["referral_pct"] * float(e.get("amount", 0.0))
        elif t == "nrr_quarter":
            if float(e.get("nrr", 0.0)) >= c["nrr_bonus_threshold"]:
                amt = c["nrr_bonus_quarterly"]
        else:
            note = "unknown event type — $0, flagged"
        lines.append({**e, "accrued": round(amt, 2), "note": note})
        total += amt
    return {"lines": lines, "total_accrued": round(total, 2),
            "payroll_truth": "Xero-paid is the payroll truth; this accrual "
                             "is the model's itemised expectation"}


# ---------------------------------------------------------------------------
# Regression self-check (used by tests and the MODEL tab's proof line)
# ---------------------------------------------------------------------------

def regression_check() -> dict:
    """Assert the engine reproduces the printed source figures."""
    checks = []

    def chk(name, got, want, tol):
        ok = abs(got - want) <= tol
        checks.append({"name": name, "got": round(got, 3),
                       "want": want, "tol": tol, "ok": ok})

    base = scenario_roi("base")
    chk("base cohort ROI unloaded", base["cohort_roi_unloaded"], 3.5, 0.05)
    chk("base Y1 ROI unloaded", base["y1_roi_unloaded"], 1.9, 0.05)
    chk("base loaded cost", base["loaded_cost_y1"], 89_600.0, 1.0)
    chk("base cohort ROI loaded", base["cohort_roi_loaded"], 3.1, 0.05)
    floor = scenario_roi("floor")
    chk("floor cohort ROI unloaded", floor["cohort_roi_unloaded"], 1.7, 0.05)
    up = scenario_roi("upside")
    chk("upside cohort ROI unloaded", up["cohort_roi_unloaded"], 4.8, 0.05)
    chk("upside Y1 ROI unloaded", up["y1_roi_unloaded"], 2.6, 0.05)
    chk("per-client lift", SOURCE["per_client_with_csm"] - SOURCE["per_client_baseline"],
        SOURCE["per_client_lift"], 0.01)
    chk("book lifetime lift ~= 30x per-client",
        SOURCE["book_size"] * SOURCE["per_client_lift"],
        SOURCE["incremental_revenue_lifetime"], 600.0)
    curve = monthly_curve("base")
    y1 = sum(r["credited_lift"] for r in curve["months"][:12])
    life = sum(r["credited_lift"] for r in curve["months"])
    chk("curve Y1 sums to credited Y1", y1,
        SCENARIO_ANCHORS["base"]["net_y1"] + SCENARIO_ANCHORS["base"]["ote"], 1.0)
    chk("curve horizon sums to credited lifetime", life,
        SCENARIO_ANCHORS["base"]["net_lifetime"] + SCENARIO_ANCHORS["base"]["ote"], 1.0)
    solve = solve_renewal_for_cohort_roi(4.0)
    checks.append({"name": "4x solve between base and upside",
                   "got": solve["renewal_pct"], "want": "60-72",
                   "tol": None, "ok": bool(solve["between_base_and_upside"])})
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "convention_notes": CONVENTION_NOTES}


if __name__ == "__main__":
    import json
    print(json.dumps(regression_check(), indent=2))
