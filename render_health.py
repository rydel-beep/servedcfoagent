"""render_health.py — RENDER HEALTH IS A SENTINEL SUBJECT (dashboard hardening).

Three watches, all riding the existing scheduled-refresh loop (no new cadence):

1 · SELF-CHECK: the server-render pipeline is asserted end-to-end — exec_top
    must produce its 8 tiles + a verdict; template render must succeed. A
    landing page that cannot render its tiles is a FEED ITEM, not a surprise.
    (The FULL real-browser assertion — Playwright, console, viewport — runs at
    the deploy gate; this rung asserts the server-rendered truth between
    deploys. Client-side crashes between deploys reach watch #2.)
2 · CLIENT ERROR RATE: browser errors POSTed to /api/client-error are bucketed
    hourly; a spike raises a feed item naming the top error.
3 · FRESHNESS: any exec tile amber/degraded past threshold raises a feed item
    naming the source.

Feed channel: feed:extra:render_health (registered in action_feed).
"""

from __future__ import annotations

import logging

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

_KV_FEED = "feed:extra:render_health"
_KV_LAST = "render_health:last"
ERROR_SPIKE_PER_HOUR = 10


def error_rate_last_hours(n: int = 6) -> dict:
    import datetime as dt
    now = now_sydney()
    buckets = {}
    for i in range(n):
        h = now - dt.timedelta(hours=i)
        key = "telemetry:err_count:" + h.strftime("%Y-%m-%d-%H")
        try:
            buckets[h.strftime("%H:00")] = int(kv_store.get(key) or 0)
        except Exception:
            buckets[h.strftime("%H:00")] = 0
    return {"per_hour": buckets, "total": sum(buckets.values())}


def self_check() -> dict:
    """Assert the server-render pipeline. Returns the check result and stores
    it under render_health:last (the /api/telemetry 'render health' row)."""
    result = {"at": now_sydney().isoformat(), "ok": False, "problems": []}
    try:
        from snapshot import load_persisted
        from dashboard import exec_top
        snap = load_persisted()
        data = exec_top.build(snap, owner=True)
        tiles = data.get("tiles") or []
        if len(tiles) != 8:
            result["problems"].append(f"exec top produced {len(tiles)} tiles, expected 8")
        empties = [t["id"] for t in tiles if not str(t.get("value") or "").strip()]
        if empties:
            result["problems"].append(f"tiles with EMPTY value (labelled states are fine, blanks are not): {empties}")
        degraded = [t["id"] for t in tiles if t.get("state") == "degraded"]
        amber = [t["id"] for t in tiles if t.get("state") == "amber"]
        if not (data.get("verdict") or {}).get("line"):
            result["problems"].append("verdict line empty")
        if not data.get("cards"):
            result["problems"].append("no summary cards built")
        result.update({"tiles": len(tiles), "degraded_tiles": degraded,
                       "amber_tiles": amber, "cards": len(data.get("cards") or [])})
        result["ok"] = not result["problems"]
    except Exception as e:  # noqa: BLE001
        result["problems"].append(f"exec_top build raised: {str(e)[:200]}")
    kv_store.put(_KV_LAST, result)
    return result


def _freshness_items() -> list[dict]:
    last = kv_store.get(_KV_LAST) or {}
    items = []
    for tid in last.get("degraded_tiles") or []:
        items.append({"severity": "S2", "category": "render_health",
                      "title": f"exec tile DEGRADED — {tid}",
                      "action": "open the tile's drawer for the failing "
                                "source; the tile shows the labelled reason "
                                "(never silent)"})
    for tid in last.get("amber_tiles") or []:
        items.append({"severity": "S3", "category": "render_health",
                      "title": f"exec tile stale — {tid}",
                      "action": "source cache older than threshold — the "
                                "scheduled refresh should clear it; if it "
                                "persists, the upstream pull is the story"})
    return items


def tick() -> dict:
    """Run all three watches; publish the feed channel. Called from the
    scheduled-refresh loop right after exec_top.refresh_cache()."""
    out = {"self_check": None, "spike": None}
    items = []
    try:
        sc = self_check()
        out["self_check"] = sc["ok"]
        if not sc["ok"]:
            items.append({"severity": "S1", "category": "render_health",
                          "title": "LANDING PAGE SELF-CHECK FAILING — " +
                                   "; ".join(sc["problems"])[:120],
                          "action": "the server-rendered executive top is "
                                    "broken — check render_health:last and "
                                    "the deploy gate artefacts"})
        items.extend(_freshness_items())
    except Exception as e:  # noqa: BLE001
        logger.warning("render_health self_check failed: %s", e)
    # EXPLAIN-EVERYTHING rung: the definitions registry must keep 100%
    # coverage of the rendered elements after every deploy
    try:
        from dashboard import definitions
        missing, total = definitions.coverage_check()
        if missing:
            items.append({"severity": "S2", "category": "render_health",
                          "title": f"definitions registry lost coverage — "
                                   f"{len(missing)}/{total} elements "
                                   f"unexplained (first: {missing[0]})",
                          "action": "add the missing entries to "
                                    "dashboard/definitions.json — every "
                                    "element must carry its explanation"})
    except Exception as e:  # noqa: BLE001
        logger.info("definitions coverage watch failed: %s", e)
    try:
        rate = error_rate_last_hours(1)
        out["spike"] = rate["total"]
        if rate["total"] >= ERROR_SPIKE_PER_HOUR:
            ring = kv_store.get("telemetry:client_errors") or []
            top = ring[-1] if ring else {}
            items.append({"severity": "S2", "category": "render_health",
                          "title": f"client error spike — {rate['total']} browser "
                                   f"errors in the last hour",
                          "action": ("top error: " + str(top.get("kind")) + " · " +
                                     str(top.get("detail"))[:120] +
                                     " · route " + str(top.get("route")))})
    except Exception as e:  # noqa: BLE001
        logger.warning("render_health rate watch failed: %s", e)
    kv_store.put(_KV_FEED, items)
    return out
