"""
history_store.py
----------------
Append-only daily snapshot logger. JSON Lines on the Railway volume.
Non-critical: if writing fails, log loudly but never fail the snapshot.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil

from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Path: /data/ on Railway, ./state/ locally
_env_path = os.getenv("SNAPSHOT_HISTORY_FILE", "")
if _env_path:
    HISTORY_FILE = _env_path
elif os.path.isdir("/data"):
    HISTORY_FILE = "/data/snapshot_history.jsonl"
else:
    HISTORY_FILE = "state/snapshot_history.jsonl"

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


def append(snapshot: dict) -> None:
    """Append one snapshot entry to the history file."""
    try:
        _maybe_rotate()
        os.makedirs(os.path.dirname(HISTORY_FILE) or ".", exist_ok=True)
        ts = now_sydney()
        entry = {
            "ts": ts.isoformat(),
            "date": str(today_sydney()),
            "schema_version": SCHEMA_VERSION,
            "snapshot": snapshot,
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        logger.info("History appended to %s", HISTORY_FILE)
    except Exception as e:
        logger.error("Failed to append history: %s", e)


def _maybe_rotate() -> None:
    """If history file exceeds MAX_FILE_BYTES, gzip it and start fresh."""
    if not os.path.exists(HISTORY_FILE):
        return
    try:
        size = os.path.getsize(HISTORY_FILE)
        if size < MAX_FILE_BYTES:
            return
        today = today_sydney()
        archive = HISTORY_FILE.replace(".jsonl", f"-{today.strftime('%Y%m')}.jsonl.gz")
        with open(HISTORY_FILE, "rb") as f_in:
            with gzip.open(archive, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        # Truncate the current file
        with open(HISTORY_FILE, "w") as f:
            pass
        logger.info("History rotated to %s", archive)
    except Exception as e:
        logger.error("History rotation failed: %s", e)


def last_n_snapshots(n: int = 7) -> list[dict]:
    """Read the last N snapshot entries from history."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        entries = []
        with open(HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries[-n:]
    except Exception as e:
        logger.error("Failed to read history: %s", e)
        return []


def last_n_days(n: int = 7) -> list[dict]:
    """Read entries from the last N calendar days."""
    today = today_sydney()
    from datetime import timedelta
    cutoff = str(today - timedelta(days=n))
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        entries = []
        with open(HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("date", "") >= cutoff:
                    entries.append(entry)
        return entries
    except Exception as e:
        logger.error("Failed to read history: %s", e)
        return []


def series(field_path: str, n: int = 30) -> list[dict]:
    """
    Extract a time series of a specific field from the last N entries.
    Returns [{date, value}] for trajectory analysis.
    """
    entries = last_n_snapshots(n)
    result = []
    for entry in entries:
        snap = entry.get("snapshot", {})
        val = snap
        for part in field_path.split("."):
            if isinstance(val, dict):
                val = val.get(part)
            else:
                val = None
                break
        result.append({"date": entry.get("date"), "value": val})
    return result
