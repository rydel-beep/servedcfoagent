"""
app.py
------
Flask application for the CFO agent.

Endpoints:
  GET  /health         — liveness check
  GET  /cfo/snapshot   — public, unauthenticated, returns latest snapshot JSON
  POST /cfo/refresh    — protected by X-CFO-KEY header, triggers a fresh pull
"""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request

from config import CFO_REFRESH_KEY
from snapshot import build_snapshot, load_persisted

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory cache of the latest snapshot
_current_snapshot: dict | None = None


def _get_snapshot() -> dict | None:
    global _current_snapshot
    if _current_snapshot is not None:
        return _current_snapshot
    _current_snapshot = load_persisted()
    return _current_snapshot


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/cfo/snapshot", methods=["GET"])
def get_snapshot():
    snap = _get_snapshot()
    if snap is None:
        return jsonify({"error": "No snapshot available yet. POST /cfo/refresh to generate one."}), 404
    return jsonify(snap)


@app.route("/cfo/refresh", methods=["POST"])
def refresh_snapshot():
    # Auth check
    key = request.headers.get("X-CFO-KEY", "")
    if not CFO_REFRESH_KEY:
        return jsonify({"error": "CFO_REFRESH_KEY not configured on server"}), 500
    if key != CFO_REFRESH_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    global _current_snapshot
    logger.info("Refresh triggered")
    snap = build_snapshot()
    _current_snapshot = snap
    return jsonify({"status": "refreshed", "ok": snap.get("ok"), "degraded_count": len(snap.get("degraded", []))})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
