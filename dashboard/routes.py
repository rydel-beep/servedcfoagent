"""
dashboard/routes.py
-------------------
Flask blueprint for the Jarvis CFO dashboard.
"""
from __future__ import annotations

import json
import logging
import os

from flask import Blueprint, render_template, request, jsonify, make_response, redirect, url_for

from dashboard.auth import require_auth, DASHBOARD_TOKEN, COOKIE_NAME, COOKIE_MAX_AGE
from dashboard.chat import chat as chat_fn
from config import CFO_REFRESH_KEY

logger = logging.getLogger(__name__)

bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)


@bp.route("/")
@require_auth
def index():
    """Serve the main dashboard page."""
    return render_template("dashboard.html")


@bp.route("/login", methods=["GET"])
def login_page():
    """Token entry form."""
    return render_template("login.html")


@bp.route("/login", methods=["POST"])
def login_submit():
    """Validate token and set cookie."""
    token = request.form.get("token", "").strip()
    if token == DASHBOARD_TOKEN:
        resp = make_response(redirect(url_for("dashboard.index")))
        resp.set_cookie(
            COOKIE_NAME, DASHBOARD_TOKEN,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
        )
        return resp
    return render_template("login.html", error="Invalid token"), 401


@bp.route("/api/snapshot", methods=["GET"])
@require_auth
def api_snapshot():
    """Return current snapshot as JSON."""
    from snapshot import load_persisted
    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404
    return jsonify(snap)


@bp.route("/api/refresh", methods=["POST"])
@require_auth
def api_refresh():
    """Trigger a snapshot refresh server-side."""
    if not CFO_REFRESH_KEY:
        return jsonify({"error": "CFO_REFRESH_KEY not configured"}), 500

    from snapshot import build_snapshot
    snap = build_snapshot()

    # Update the in-memory cache in app.py too
    import app as app_module
    app_module._current_snapshot = snap

    return jsonify({
        "status": "refreshed",
        "ok": snap.get("ok"),
        "degraded_count": len(snap.get("degraded", [])),
        "generated_at": snap.get("generated_at"),
    })


@bp.route("/api/chat", methods=["POST"])
@require_auth
def api_chat():
    """Handle chat message with snapshot context."""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    from snapshot import load_persisted
    snap = load_persisted()
    snapshot_json = json.dumps(snap, indent=2) if snap else "{}"

    token = request.cookies.get(COOKIE_NAME, "anon")
    result = chat_fn(message, snapshot_json, token)
    return jsonify(result)
