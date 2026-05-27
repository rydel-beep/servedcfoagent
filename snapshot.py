"""
snapshot.py
-----------
Orchestrates data pulls and assembles the CFO snapshot.
Persists the last good snapshot to disk so a Railway restart preserves it.
"""
from __future__ import annotations

import json
import logging
import os

from config import SNAPSHOT_FILE
from helpers import now_sydney
from stripe_pull import pull_stripe
from ghl_pull import pull_ghl
from sheets_pull import pull_sheets

logger = logging.getLogger(__name__)


def build_snapshot() -> dict:
    """Pull all sources and assemble a single snapshot dict."""
    ts = now_sydney()

    stripe_result = pull_stripe()
    ghl_result = pull_ghl()
    sheets_result = pull_sheets()

    # Merge degraded lists
    degraded = (
        stripe_result.get("degraded", [])
        + ghl_result.get("degraded", [])
        + sheets_result.get("degraded", [])
    )

    # Build costs block from actual sheet commission values
    sheets_data = sheets_result.get("sheets")
    costs = None
    if sheets_data:
        costs = {
            "closer_commission": sheets_data.get("closer_commission_total"),
            "setter_commission": sheets_data.get("setter_commission_total"),
            "source": "sheet actuals (Commission Closer #20, Commission Setter #19)",
        }

    snapshot = {
        "generated_at": ts.isoformat(),
        "timezone": "Australia/Sydney",
        "currency": "AUD",
        "stripe": stripe_result.get("stripe"),
        "ghl": ghl_result.get("ghl"),
        "sheets": sheets_data,
        "costs": costs,
        "degraded": degraded if degraded else [],
        "ok": len(degraded) == 0,
    }

    _persist(snapshot)
    return snapshot


def _persist(snapshot: dict) -> None:
    """Write snapshot to disk so it survives process restarts."""
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(snapshot, f, indent=2)
        logger.info("Snapshot persisted to %s", SNAPSHOT_FILE)
    except OSError as e:
        logger.error("Failed to persist snapshot: %s", e)


def load_persisted() -> dict | None:
    """Load the last persisted snapshot from disk, if it exists."""
    if not os.path.exists(SNAPSHOT_FILE):
        return None
    try:
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load persisted snapshot: %s", e)
        return None
