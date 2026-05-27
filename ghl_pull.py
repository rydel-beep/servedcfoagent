"""
ghl_pull.py
-----------
Pull sales pipeline metrics from GHL for the Served Marketing location.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import requests

from config import (
    GHL_BASE, GHL_API_KEY, GHL_LOCATION_ID,
    GHL_SALES_PIPELINE_ID, HTTP_TIMEOUT, WINDOW_CURRENT,
)
from helpers import today_sydney

logger = logging.getLogger(__name__)


def _ghl_headers() -> dict:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": "2021-07-28",
    }


def _fetch_pipeline_stages() -> dict[str, str]:
    """Return {stage_id: stage_name} for the sales pipeline."""
    try:
        resp = requests.get(
            f"{GHL_BASE}/opportunities/pipelines",
            headers=_ghl_headers(),
            params={"locationId": GHL_LOCATION_ID},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error("GHL pipelines API %d: %s", resp.status_code, resp.text[:200])
            return {}
        for pipeline in resp.json().get("pipelines", []):
            if pipeline.get("id") == GHL_SALES_PIPELINE_ID:
                return {s["id"]: s["name"] for s in pipeline.get("stages", [])}
    except requests.RequestException as e:
        logger.error("GHL pipelines request failed: %s", e)
    return {}


def _fetch_all_opportunities() -> list[dict]:
    """Paginate all opportunities in the sales pipeline."""
    opps: list[dict] = []
    params = {
        "pipeline_id": GHL_SALES_PIPELINE_ID,
        "location_id": GHL_LOCATION_ID,
        "limit": 100,
    }
    page = 1
    while True:
        try:
            resp = requests.get(
                f"{GHL_BASE}/opportunities/search",
                headers=_ghl_headers(),
                params=params,
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.error("GHL opps search %d: %s", resp.status_code, resp.text[:200])
                break
            data = resp.json()
            batch = data.get("opportunities", [])
            opps.extend(batch)
            meta = data.get("meta", {})
            next_after = meta.get("nextAfterId") or meta.get("startAfterId")
            if not next_after or len(batch) < 100:
                break
            params["startAfterId"] = next_after
            page += 1
        except requests.RequestException as e:
            logger.error("GHL opps request failed (page %d): %s", page, e)
            break
    return opps


def pull_ghl() -> dict:
    """
    Pull GHL pipeline metrics. Returns dict ready to merge into snapshot.
    """
    degraded = []

    if not GHL_API_KEY or not GHL_LOCATION_ID:
        degraded.append({
            "metric": "ghl_pipeline",
            "reason": "GHL_SALES_API_KEY or GHL_SALES_LOCATION_ID not set",
        })
        return {"ghl": None, "degraded": degraded}

    stages = _fetch_pipeline_stages()
    if not stages:
        degraded.append({
            "metric": "ghl_pipeline_stages",
            "reason": "Failed to fetch pipeline stages from GHL",
        })

    opps = _fetch_all_opportunities()
    if opps is None:
        opps = []
        degraded.append({
            "metric": "ghl_opportunities",
            "reason": "Failed to fetch opportunities from GHL",
        })

    today = today_sydney()
    cutoff = today - timedelta(days=WINDOW_CURRENT)

    # Aggregate
    total_opps = len(opps)
    total_value = 0.0
    stage_breakdown = {}
    status_counts = {"open": 0, "won": 0, "lost": 0, "abandoned": 0}
    new_in_window = 0

    for opp in opps:
        monetary = opp.get("monetaryValue") or 0
        try:
            monetary = float(monetary)
        except (ValueError, TypeError):
            monetary = 0.0
        total_value += monetary

        stage_id = opp.get("pipelineStageId", "unknown")
        stage_name = stages.get(stage_id, stage_id)
        if stage_name not in stage_breakdown:
            stage_breakdown[stage_name] = {"count": 0, "value": 0.0}
        stage_breakdown[stage_name]["count"] += 1
        stage_breakdown[stage_name]["value"] += monetary

        status = (opp.get("status") or "open").lower()
        if status in status_counts:
            status_counts[status] += 1

        created = opp.get("createdAt", "")
        if created:
            try:
                created_date = created[:10]  # "YYYY-MM-DD"
                from datetime import date as dt_date
                parts = created_date.split("-")
                opp_date = dt_date(int(parts[0]), int(parts[1]), int(parts[2]))
                if opp_date >= cutoff:
                    new_in_window += 1
            except (ValueError, IndexError):
                pass

    won = status_counts["won"]
    lost = status_counts["lost"]
    conversion_rate = round(won / (won + lost) * 100, 1) if (won + lost) > 0 else None

    return {
        "ghl": {
            "pipeline_id": GHL_SALES_PIPELINE_ID,
            "total_opportunities": total_opps,
            "total_pipeline_value": total_value,
            "new_in_trailing_window": new_in_window,
            "status": status_counts,
            "conversion_rate_pct": conversion_rate,
            "stage_breakdown": stage_breakdown,
            "period": {
                "label": f"trailing {WINDOW_CURRENT} days (new opps window)",
                "start": str(cutoff),
                "end": str(today),
            },
        },
        "degraded": degraded,
    }
