"""
verdicts.py
-----------
Assembles a ranked verdict layer: what's wrong, sized by dollar impact.
Top leaks first, wins below. Maximum 5 leaks — forced prioritisation.
"""
from __future__ import annotations


def _safe_float(v) -> float:
    """Coerce to float or 0."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _get(d: dict, path: str):
    obj = d
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def build_verdicts(snap: dict, hormozi: dict) -> dict:
    """Build the ranked verdict layer from hormozi metrics + existing flags."""
    leaks: list[dict] = []
    wins: list[dict] = []

    # ── Hormozi metric leaks ────────────────────────────────────────────
    for key, m in hormozi.items():
        status = m.get("status", "unknown")
        if status in ("critical", "watch"):
            leaks.append({
                "name": f"Hormozi {key}",
                "category": _categorise_hormozi(key),
                "current": _format_value(key, m.get("value")),
                "benchmark": _format_value(key, m.get("benchmark")),
                "dollar_impact_monthly": _safe_float(m.get("dollar_gap")),
                "read": m.get("read", ""),
                "evidence_path": f"hormozi.{key}",
            })
        elif status == "healthy":
            wins.append({
                "name": f"Hormozi {key}",
                "value": _format_value(key, m.get("value")),
                "read": m.get("read", ""),
            })

    # ── Sales deep leak_flags → dollar-sized leaks ──────────────────────
    funnel = _get(snap, "sales.funnel") or {}
    deep_money = _get(snap, "sales.deep.money") or {}
    closes = funnel.get("closes") or 0
    avg_contract = deep_money.get("avg_contract") or 0

    # Set→Show gap
    s2sh = funnel.get("set_to_show_pct")
    sets = funnel.get("sets") or 0
    if s2sh is not None and s2sh < 70.0 and sets > 0:
        # Each % point of show rate = (sets × 1%) more shows → (shows × close_rate) more closes
        sh2c = funnel.get("show_to_close_pct") or 0
        additional_shows = sets * (70.0 - s2sh) / 100
        additional_closes = additional_shows * (sh2c / 100) if sh2c else 0
        dollar_impact = round(additional_closes * avg_contract, 2)
        leaks.append({
            "name": "Set→Show conversion",
            "category": "sales",
            "current": f"{s2sh}%",
            "benchmark": "70%",
            "dollar_impact_monthly": dollar_impact,
            "read": (f"Set→Show {s2sh}% vs 70% target — "
                     f"{additional_shows:.0f} missed shows/mo, "
                     f"~{additional_closes:.0f} lost closes worth ${dollar_impact:,.0f}"),
            "likely_cause": "No-show/cancel rate or confirmation process",
            "evidence_path": "sales.deep.loss.per_setter_noshow",
        })

    # Show→Close gap
    sh2c = funnel.get("show_to_close_pct")
    shows = funnel.get("shows") or 0
    if sh2c is not None and sh2c < 35.0 and shows > 0:
        additional_closes = shows * (35.0 - sh2c) / 100
        dollar_impact = round(additional_closes * avg_contract, 2)
        leaks.append({
            "name": "Show→Close conversion",
            "category": "sales",
            "current": f"{sh2c}%",
            "benchmark": "35%",
            "dollar_impact_monthly": dollar_impact,
            "read": (f"Show→Close {sh2c}% vs 35% target — "
                     f"~{additional_closes:.0f} missed closes worth ${dollar_impact:,.0f}/mo"),
            "evidence_path": "sales.deep.loss.loss_reasons",
        })

    # ── Owner pay excess flag (from categoriser) ────────────────────────
    profit_block = snap.get("profit") or {}
    payroll = profit_block.get("payroll") or {}
    owner_breakdown = payroll.get("owner_pay_breakdown") or {}
    excess = owner_breakdown.get("excess")
    excess_flag = owner_breakdown.get("excess_flag")

    if excess_flag and excess is not None and abs(excess) > 0:
        leaks.append({
            "name": "Owner pay excess in Wages and Salaries",
            "category": "data_quality",
            "current": f"${owner_breakdown.get('raw_wages_and_salaries', 0):,.0f}",
            "benchmark": f"${owner_breakdown.get('recurring_gross', 0):,.0f} (recurring gross)",
            "dollar_impact_monthly": round(abs(excess), 2),
            "read": excess_flag,
            "likely_cause": "Miscoded bonus or multi-period posting (pre-fix period)",
            "evidence_path": "profit.payroll.owner_pay_breakdown",
        })

    # ── Revenue range targeting waste ───────────────────────────────────
    by_rev = _get(snap, "sales.deep.lead_quality.by_revenue_range") or []
    for rng in by_rev:
        if rng.get("targeting_flag") and rng.get("leads", 0) >= 5:
            wasted_leads = rng["leads"]
            # Cost per wasted lead ≈ total ad spend / total leads
            total_leads = funnel.get("leads_in") or 1
            ad_spend = _safe_float(_get(snap, "xero.xero_ad_spend"))
            cost_per_lead = ad_spend / total_leads if ad_spend > 0 and total_leads > 0 else 0
            dollar_impact = round(wasted_leads * cost_per_lead, 2)
            leaks.append({
                "name": f"Wasted leads: {rng['range']}",
                "category": "sales",
                "current": f"{rng['leads']} leads, 0 closes",
                "benchmark": "Reallocate to closing segments",
                "dollar_impact_monthly": dollar_impact,
                "read": rng["targeting_flag"],
                "evidence_path": "sales.deep.lead_quality.by_revenue_range",
            })

    # ── Sort by dollar impact, apply rank ───────────────────────────────
    # Tiebreak: critical > watch > healthy > unknown
    status_order = {"critical": 0, "watch": 1, "data_quality": 1, "healthy": 2, "unknown": 3}
    leaks.sort(key=lambda x: (
        -x["dollar_impact_monthly"],
        status_order.get(x.get("category", ""), 3),
    ))

    # Trim to top 5
    top_leaks = leaks[:5]
    for i, leak in enumerate(top_leaks, 1):
        leak["rank"] = i

    # ── Headline ────────────────────────────────────────────────────────
    if top_leaks:
        top = top_leaks[0]
        headline = (f"Top issue: {top['name']} "
                    f"(${top['dollar_impact_monthly']:,.0f}/mo impact). "
                    f"{len(top_leaks)} leak{'s' if len(top_leaks) > 1 else ''} flagged.")
    else:
        headline = "All metrics at or above benchmark — no leaks detected."

    # ── Wins from Hormozi ───────────────────────────────────────────────
    # Add other healthy signals
    mrr = _get(snap, "stripe.mrr")
    if mrr is not None:
        wins.append({
            "name": "Stripe MRR",
            "value": f"${mrr:,.0f}",
            "read": f"MRR ${mrr:,.0f} — recurring revenue base",
        })

    return {
        "headline": headline,
        "top_leaks": top_leaks,
        "wins": wins,
    }


def _categorise_hormozi(key: str) -> str:
    mapping = {
        "ltgp_cac": "unit_economics",
        "cac_loaded": "unit_economics",
        "payback_days": "money",
        "gross_margin": "money",
        "op_efficiency": "operations",
        "sales_velocity": "sales",
    }
    return mapping.get(key, "unit_economics")


def _format_value(key: str, value) -> str:
    if value is None:
        return "N/A"
    if key in ("ltgp_cac", "op_efficiency"):
        return f"{value}×"
    if key == "gross_margin":
        return f"{value}%"
    if key == "payback_days":
        return f"{value:.0f} days"
    if key in ("cac_loaded", "sales_velocity"):
        return f"${value:,.0f}"
    return str(value)
