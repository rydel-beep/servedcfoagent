"""
deficiency_analysis.py
----------------------
Cross-layer deficiency analysis: team, funnel, financial, and interaction insights.
Ranks deficiencies by growth impact. Surfaces the few things actually limiting
the next stage of growth, not everything wrong.
"""
from __future__ import annotations


def _get(d: dict, path: str):
    obj = d
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def _safe_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def build_deficiency_analysis(
    snap: dict,
    team_model: dict,
    hormozi: dict,
    true_team_cost: float,
) -> dict:
    """Build ranked deficiency analysis across all business layers."""
    deficiencies: list[dict] = []

    funnel = _get(snap, "sales.funnel") or {}
    deep = _get(snap, "sales.deep") or {}
    ch = snap.get("client_health") or {}
    xero = snap.get("xero") or {}
    profit = snap.get("profit") or {}

    closes = funnel.get("closes") or 0
    shows = funnel.get("shows") or 0
    sets = funnel.get("sets") or 0
    leads = funnel.get("leads_in") or 0
    sh2c = funnel.get("show_to_close_pct")
    s2sh = funnel.get("set_to_show_pct")

    current_mrr = _safe_float(ch.get("current_mrr"))
    gm_pct = _safe_float(xero.get("gross_margin_pct"))

    # Money metrics
    money = deep.get("money") or {}
    avg_contract = _safe_float(money.get("avg_contract"))
    avg_cash = _safe_float(money.get("avg_cash_per_close"))

    # ── FUNNEL DEFICIENCIES ─────────────────────────────────────
    if sh2c is not None and sh2c < 35.0 and shows > 0:
        at_target = round(shows * 0.35)
        missed = at_target - closes
        monthly_impact = missed * avg_cash if avg_cash > 0 else None
        deficiencies.append({
            "category": "funnel",
            "name": "Show→Close conversion",
            "severity": "critical" if sh2c < 25 else "high",
            "current": f"{sh2c}%",
            "target": "35%",
            "impact": f"{missed} missed closes/mo" + (f" (~${monthly_impact:,.0f} cash)" if monthly_impact else ""),
            "growth_impact_monthly": monthly_impact,
            "fix": "Objection handling training, offer clarity, follow-up sequences",
        })

    if s2sh is not None and s2sh < 70.0 and sets > 0:
        at_target = round(sets * 0.70)
        missed = at_target - shows
        deficiencies.append({
            "category": "funnel",
            "name": "Set→Show rate",
            "severity": "high" if s2sh < 60 else "medium",
            "current": f"{s2sh}%",
            "target": "70%",
            "impact": f"{missed} missed shows/mo",
            "growth_impact_monthly": None,
            "fix": "Confirmation sequences, day-of reminders, setter pre-qualification",
        })

    # Speed-to-lead
    setter_perf = deep.get("setter_performance") or []
    for sp in setter_perf:
        stl = sp.get("speed_to_lead_pct")
        if stl is not None and stl < 50:
            deficiencies.append({
                "category": "funnel",
                "name": f"Speed-to-lead ({sp['name']})",
                "severity": "medium",
                "current": f"{stl}%",
                "target": "50%",
                "impact": "Slower response = lower qualification rate",
                "growth_impact_monthly": None,
                "fix": "Immediate response SOP, CRM auto-assign, mobile notifications",
            })
            break  # Only flag once (worst offender)

    # ── TEAM DEFICIENCIES ───────────────────────────────────────
    if team_model.get("available"):
        spof = team_model.get("single_points_of_failure") or []
        for fn in spof:
            fn_data = team_model["by_function"].get(fn, {})
            roles = fn_data.get("roles", [])
            role_name = roles[0]["role"] if roles else fn
            deficiencies.append({
                "category": "team",
                "name": f"Single point of failure: {role_name}",
                "severity": "medium",
                "current": "1 person",
                "target": "2+ for critical functions",
                "impact": f"If {role_name} is unavailable, {fn} stops entirely",
                "growth_impact_monthly": None,
                "fix": f"Cross-train or hire backup for {fn}",
            })

    # ── FINANCIAL DEFICIENCIES ──────────────────────────────────
    # Margin pressure
    if gm_pct > 0 and gm_pct < 50:
        deficiencies.append({
            "category": "financial",
            "name": "Gross margin pressure",
            "severity": "high",
            "current": f"{gm_pct}%",
            "target": "50%+",
            "impact": "Low margin limits hiring capacity and resilience",
            "growth_impact_monthly": None,
            "fix": "Review COGS, renegotiate supplier contracts, raise prices",
        })

    # Team cost ratio
    if current_mrr > 0:
        cost_ratio = true_team_cost / current_mrr * 100
        if cost_ratio > 50:
            deficiencies.append({
                "category": "financial",
                "name": "Team cost ratio",
                "severity": "high",
                "current": f"{cost_ratio:.0f}% of MRR",
                "target": "<40%",
                "impact": "Payroll consuming too much revenue — limits growth investment",
                "growth_impact_monthly": round((cost_ratio - 40) / 100 * current_mrr, 0),
                "fix": "Grow MRR faster than headcount, or hold hiring until ratio improves",
            })

    # Client concentration
    ac = snap.get("active_clients") or {}
    client_count = ac.get("active_count") or ch.get("total_clients") or 0
    if client_count > 0 and current_mrr > 0:
        avg_mrr_per_client = current_mrr / client_count
        # If top client is >20% of MRR, flag concentration risk
        # We don't have per-client MRR breakdown, so flag if fewer than 10 clients
        if client_count < 10:
            deficiencies.append({
                "category": "financial",
                "name": "Client concentration",
                "severity": "medium",
                "current": f"{client_count} clients",
                "target": "15+ for stability",
                "impact": "Losing 1 client = significant MRR hit",
                "growth_impact_monthly": None,
                "fix": "Diversify client base, longer contracts, upsell existing",
            })

    # ── INTERACTION INSIGHTS ────────────────────────────────────
    # Check if the binding constraint is sales or delivery
    interactions = []

    # If close rate is low but we have plenty of leads, sales is the constraint
    if sh2c is not None and sh2c < 35 and leads > 20:
        interactions.append(
            "Your constraint is conversion, not lead volume. "
            "Adding delivery capacity won't help until close rate improves — "
            "you'd be hiring to serve deals you're not closing."
        )

    # If close rate is good but lead volume is thin
    if sh2c is not None and sh2c >= 35 and leads < 15:
        interactions.append(
            "Close rate is healthy but lead volume is thin. "
            "More setters or higher ad spend would feed the funnel — "
            "your closer has capacity."
        )

    # Deceleration + hiring
    proj = ch.get("projection") or {}
    if proj.get("decelerating"):
        interactions.append(
            "Growth is decelerating. Hiring now adds fixed cost into a slowing "
            "trajectory — consider whether the hire accelerates growth enough "
            "to reverse the deceleration."
        )

    # ── RANK BY IMPACT ──────────────────────────────────────────
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    deficiencies.sort(key=lambda d: (
        severity_order.get(d["severity"], 9),
        -(d.get("growth_impact_monthly") or 0),
    ))

    return {
        "deficiencies": deficiencies[:8],  # Top 8 max
        "binding_constraint": deficiencies[0] if deficiencies else None,
        "interaction_insights": interactions,
        "total_deficiencies": len(deficiencies),
    }
