"""
quarterly_model_store.py
-----------------------
The SELF-IMPROVEMENT LOOP's memory. Persists each quarter's 3x/requirements model so the NEXT
quarter can grade it against what actually happened, plus a linter-findings trend. Durable via
kv_store (Postgres-backed).

Keys:
  qmodel:<label>      the saved 3x model + key actuals for one quarter (e.g. "Q2 2026")
  qlinter:trend       rolling list of linter results per generation (recurring findings → build items)
"""
from __future__ import annotations

import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_TREND_CAP = 60


def save_model(label: str, model: dict, actuals: dict | None = None) -> None:
    """Persist the quarter's 3x model + the actuals it was built from (for later grading)."""
    try:
        kv_store.put(f"qmodel:{label}", {
            "label": label, "saved_at": str(today_sydney()),
            "model": _slim(model), "actuals": actuals or {}})
    except Exception as e:
        logger.info("save_model failed: %s", e)


def load_model(label: str) -> dict | None:
    try:
        return kv_store.get(f"qmodel:{label}")
    except Exception:
        return None


def _slim(model: dict) -> dict:
    """Keep just what grading needs (targets, requirements, assumptions, binding constraint)."""
    if not isinstance(model, dict):
        return {}
    return {
        "multiple": model.get("multiple"),
        "targets": model.get("targets"),
        "targets_current": model.get("targets_current"),
        "assumptions": model.get("assumptions"),
        "requirements_table": model.get("requirements_table"),
        "binding_constraint": (model.get("binding_constraint") or {}).get("lever"),
        "spend_required": (model.get("spend") or {}).get("ad_spend_required"),
        "leads_required": ((model.get("funnel") or {}).get("volume_path") or {}).get("leads_required"),
    }


def record_linter(label: str, result: dict) -> None:
    try:
        trend = kv_store.get("qlinter:trend") or []
        trend.append({"label": label, "at": str(today_sydney()),
                      "hard": result.get("summary", {}).get("hard", 0),
                      "warn": result.get("summary", {}).get("warn", 0),
                      "warnings": (result.get("warnings") or [])[:10]})
        kv_store.put("qlinter:trend", trend[-_TREND_CAP:])
    except Exception as e:
        logger.info("record_linter failed: %s", e)


def linter_trend() -> list[dict]:
    try:
        return kv_store.get("qlinter:trend") or []
    except Exception:
        return []


def grade_prior_quarter(prior_label: str, current_pack: dict) -> dict | None:
    """Grade the PRIOR quarter's 3x model against what actually happened this quarter — per lever,
    required vs delivered, which assumptions held. Returns None if no prior model was saved (so the
    grading section only appears once there's a track record)."""
    saved = load_model(prior_label)
    if not saved or not saved.get("model"):
        return None
    m = saved["model"]
    comp = (current_pack.get("unit_economics") or {}).get("components", {}) or {}
    funnel = (current_pack.get("sales") or {}).get("funnel") or {}
    rc = current_pack.get("revenue_cash") or {}

    rows = []

    def pct(req, act):
        return round(100 * act / req, 0) if (req and act is not None) else None

    # leads ramp
    req_leads = m.get("leads_required")
    act_leads = funnel.get("leads_in")
    if req_leads and act_leads is not None:
        rows.append({"lever": "Lead volume", "required": req_leads, "delivered": act_leads,
                     "achieved_pct": pct(req_leads, act_leads)})
    # closes
    req_closes = (m.get("targets") or {}).get("closes")
    act_closes = comp.get("closes")
    if req_closes and act_closes is not None:
        rows.append({"lever": "Closes", "required": req_closes, "delivered": act_closes,
                     "achieved_pct": pct(req_closes, act_closes)})
    # ad spend / CPL drift band
    req_spend = m.get("spend_required")
    act_spend = comp.get("ad_spend")
    if req_spend and act_spend is not None:
        rows.append({"lever": "Ad spend", "required": req_spend, "delivered": act_spend,
                     "achieved_pct": pct(req_spend, act_spend)})
    # CPL drift actual vs the band assumption
    prev_cpl = None
    try:
        pm = m.get("requirements_table") or []
        prev_cpl = (saved.get("model", {}).get("spend") or {}).get("cost_per_lead_current")
    except Exception:
        pass
    act_cpl = (act_spend / act_leads) if (act_spend and act_leads) else None

    return {"prior_label": prior_label, "rows": rows,
            "cpl_prior": prev_cpl, "cpl_actual": round(act_cpl, 2) if act_cpl else None,
            "note": ("Auto-grades the prior quarter's model against actuals. Assumptions that held vs "
                     "broke calibrate the next model — the model gets honest about its own record.")}
