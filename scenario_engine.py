"""
scenario_engine.py
------------------
Deterministic WHAT-IFs over the canonical unit-economics formulas (one-engine). It recomputes a
metric with stated parameter deltas using the SAME formulas as range_unit_economics /
three_x_model — no parallel math. Hypotheticals are LABELLED and never touch actuals.

Metrics: loaded CAC, ROAS, LTGP:CAC (the conversation's live topics). Deltas: ± closes, ± ad spend,
± commissions, CPL shift, different window. Second-order: commissions scale per-close by default
with a flat-hold variant offered.
"""
from __future__ import annotations

import datetime as dt
import logging

logger = logging.getLogger(__name__)

_METRICS = {"cac", "roas", "ltgp_cac"}


def base_components(window_days: int = 30) -> dict | None:
    """The canonical base for the window — the SAME engine the dashboard/quarterly use."""
    try:
        import range_unit_economics as R
        from helpers import today_sydney
        today = today_sydney()
        res = R.unit_economics(str(today - dt.timedelta(days=window_days - 1)), str(today))
        if "error" in res:
            return None
        comp = res.get("components", {}) or {}
        return {
            "window_days": window_days,
            "ad_spend": comp.get("ad_spend"), "closer_comm": comp.get("closer_comm"),
            "setter_comm": comp.get("setter_comm"), "closes": comp.get("closes"),
            "cac_loaded": comp.get("cac_loaded"), "contract_value_total": comp.get("contract_value_total"),
            "avg_contract": comp.get("avg_contract"), "gross_margin_pct": comp.get("gross_margin_pct"),
            "ltgp_cac": res.get("ltgp_cac"), "roas": res.get("roas"),
        }
    except Exception as e:
        logger.info("scenario base_components failed: %s", e)
        return None


def _cac(ad, closer, setter, closes):
    if not closes:
        return None
    return round((ad + closer + setter) / closes, 2)


def compute(metric: str, deltas: dict, window_days: int = 30, scale_comms: bool = False) -> dict | None:
    """Recompute `metric` under `deltas`. Returns {base, scenario, pct_change, formula, assumption}.
    deltas keys: closes_add, closes_set, ad_mult, ad_add, closer_mult, setter_mult, avg_contract_set.
    scale_comms=True → commissions scale per-close (closer/setter comm per close held constant)."""
    b = base_components(window_days)
    if not b:
        return None
    ad = b["ad_spend"] or 0; closer = b["closer_comm"] or 0; setter = b["setter_comm"] or 0
    closes = b["closes"] or 0
    if any(v is None for v in (b["ad_spend"], b["closer_comm"], b["setter_comm"], b["closes"])):
        return {"available": False, "reason": "the base window is missing a component", "base": b}

    # apply deltas
    new_closes = closes
    if deltas.get("closes_set") is not None:
        new_closes = deltas["closes_set"]
    if deltas.get("closes_add"):
        new_closes = closes + deltas["closes_add"]
    new_ad = ad * deltas.get("ad_mult", 1.0) + deltas.get("ad_add", 0)
    new_closer = closer * deltas.get("closer_mult", 1.0)
    new_setter = setter * deltas.get("setter_mult", 1.0)
    # second-order: commissions scale per-close if requested (per-close comm held constant)
    if scale_comms and closes:
        per_close_closer = closer / closes
        per_close_setter = setter / closes
        new_closer = round(per_close_closer * new_closes, 2)
        new_setter = round(per_close_setter * new_closes, 2)

    out = {"metric": metric, "window_days": window_days, "base": b, "scale_comms": scale_comms,
           "assumption": ("holding ad spend and commissions flat" if not scale_comms
                          else "scaling commissions per-close (per-close rate held constant)")}

    if metric == "cac":
        base_v = _cac(ad, closer, setter, closes)
        scen_v = _cac(new_ad, new_closer, new_setter, new_closes)
        out.update({"base_value": base_v, "scenario_value": scen_v,
                    "cost_base": round(new_ad + new_closer + new_setter, 2), "closes": new_closes,
                    "formula": f"(ad {new_ad:,.0f} + closer {new_closer:,.0f} + setter {new_setter:,.0f}) / {new_closes} closes"})
    elif metric == "roas":
        # ROAS = contracted / ad spend; contracted scales with closes (avg contract held)
        avg = b["avg_contract"] or (b["contract_value_total"] / closes if closes else 0)
        new_contract = avg * new_closes
        base_v = b["roas"]
        scen_v = round(new_contract / new_ad, 2) if new_ad else None
        out.update({"base_value": base_v, "scenario_value": scen_v,
                    "formula": f"{new_contract:,.0f} contracted / {new_ad:,.0f} ad spend"})
    elif metric == "ltgp_cac":
        avg = b["avg_contract"] or 0; gm = (b["gross_margin_pct"] or 0) / 100.0
        new_cac = _cac(new_ad, new_closer, new_setter, new_closes)
        ltgp = avg * gm
        base_v = b["ltgp_cac"]
        scen_v = round(ltgp / new_cac, 2) if new_cac else None
        out.update({"base_value": base_v, "scenario_value": scen_v, "new_cac": new_cac,
                    "formula": f"LTGP {ltgp:,.0f} / CAC {new_cac:,.0f}"})
    else:
        return None

    if out.get("base_value") and out.get("scenario_value"):
        out["pct_change"] = round((out["scenario_value"] - out["base_value"]) / out["base_value"] * 100, 1)
    return out
