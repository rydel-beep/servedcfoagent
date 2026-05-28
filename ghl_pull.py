"""
ghl_pull.py
-----------
Pull sales pipeline metrics from GHL for the Served Marketing location.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import requests

# Runaway-loop guard only. Pagination should stop when the cursor is exhausted.
# If this cap is hit, the pull is flagged incomplete — never silently truncated.
MAX_PAGES = 100  # 100 × 100 = 10,000 opps

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
            timeout=(5, HTTP_TIMEOUT),
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


def _fetch_all_opportunities() -> dict:
    """
    Paginate all opportunities in the sales pipeline until the cursor is exhausted.
    Deduplicates by opportunity ID (GHL can return duplicates across pages).
    Stops early when fetched unique count reaches total_reported (if available).
    Returns {opps, complete, total_reported, reason}.
    """
    seen_ids: set[str] = set()
    opps: list[dict] = []
    total_reported: int | None = None
    params = {
        "pipeline_id": GHL_SALES_PIPELINE_ID,
        "location_id": GHL_LOCATION_ID,
        "limit": 100,
    }
    page = 1
    complete = True
    reason = None

    while page <= MAX_PAGES:
        try:
            resp = requests.get(
                f"{GHL_BASE}/opportunities/search",
                headers=_ghl_headers(),
                params=params,
                timeout=(5, HTTP_TIMEOUT),
            )
            if resp.status_code != 200:
                logger.error("GHL opps search %d: %s", resp.status_code, resp.text[:200])
                complete = False
                reason = f"HTTP {resp.status_code} on page {page}"
                break
            data = resp.json()
            batch = data.get("opportunities", [])

            meta = data.get("meta", {})

            # Capture total from first response if available
            if total_reported is None:
                raw_total = meta.get("total")
                if raw_total is not None:
                    try:
                        total_reported = int(raw_total)
                    except (ValueError, TypeError):
                        pass

            # Deduplicate by opportunity ID
            new_in_batch = 0
            for opp in batch:
                opp_id = opp.get("id")
                if opp_id and opp_id in seen_ids:
                    continue
                if opp_id:
                    seen_ids.add(opp_id)
                opps.append(opp)
                new_in_batch += 1

            # Stop if we've reached total_reported (all records fetched)
            if total_reported is not None and len(opps) >= total_reported:
                logger.info("GHL fetched %d unique opps — reached total_reported %d", len(opps), total_reported)
                break

            # Stop if cursor exhausted or batch was short
            next_after = meta.get("nextAfterId") or meta.get("startAfterId")
            if not next_after or len(batch) < 100:
                break

            # Stop if an entire page was duplicates (cursor is looping)
            if new_in_batch == 0:
                logger.warning("GHL page %d returned 0 new opps (all duplicates) — stopping", page)
                break

            params["startAfterId"] = next_after
            page += 1
        except requests.RequestException as e:
            logger.error("GHL opps request failed (page %d): %s", page, e)
            complete = False
            reason = f"request failed on page {page}: {e}"
            break

    # If we exited because page > MAX_PAGES, flag it
    if page > MAX_PAGES:
        complete = False
        reason = f"pagination safety cap hit at {len(opps)} unique opps (MAX_PAGES={MAX_PAGES})"
        logger.warning("GHL %s", reason)

    return {
        "opps": opps,
        "complete": complete,
        "total_reported": total_reported,
        "reason": reason,
    }


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

    fetch_result = _fetch_all_opportunities()
    opps = fetch_result["opps"]
    complete = fetch_result["complete"]
    total_reported = fetch_result["total_reported"]
    fetch_reason = fetch_result["reason"]

    if not complete:
        degraded.append({
            "metric": "ghl_opportunities",
            "reason": f"GHL pagination incomplete — {fetch_reason or 'unknown'} — data may be incomplete",
        })

    # Cross-check fetched vs reported total
    if total_reported is not None and len(opps) < total_reported:
        degraded.append({
            "metric": "ghl_count_mismatch",
            "reason": f"Fetched {len(opps)} opps but GHL reports {total_reported} total — pipeline metrics may be understated",
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
            "total_reported": total_reported,
            "complete": complete,
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
