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
            secure=True,
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


@bp.route("/api/history", methods=["GET"])
@require_auth
def api_history():
    """Return last N daily snapshots for sparkline/trend data."""
    import history_store
    n = request.args.get("n", 14, type=int)
    n = min(n, 30)  # cap at 30 entries
    entries = history_store.last_n_snapshots(n)

    # Extract only the fields needed for sparklines (keep payload small)
    result = []
    for entry in entries:
        snap = entry.get("snapshot", {})
        sales = snap.get("sales") or {}
        funnel = sales.get("funnel") or {}
        per_closer = sales.get("per_closer") or []
        deep = sales.get("deep") or {}
        setter_perf = deep.get("setter_performance") or []
        ch = snap.get("client_health") or {}

        result.append({
            "date": entry.get("date"),
            "funnel": {
                "leads_in": funnel.get("leads_in"),
                "sets": funnel.get("sets"),
                "shows": funnel.get("shows"),
                "closes": funnel.get("closes"),
            },
            "setters": [
                {"name": s.get("name"), "sets": s.get("sets"), "dials": s.get("dials"),
                 "show_pct": s.get("show_pct")}
                for s in setter_perf
            ],
            "closers": [
                {"name": c.get("name"), "closes": c.get("closes"),
                 "close_rate_pct": c.get("close_rate_pct"), "commission_total": c.get("commission_total")}
                for c in per_closer
            ],
            "mrr": ch.get("current_mrr"),
            "clients": ch.get("total_clients"),
        })

    return jsonify(result)


@bp.route("/api/hiring-scenario", methods=["POST"])
@require_auth
def api_hiring_scenario():
    """Model one or more hires' affordability and financial impact."""
    from hiring_model import compute_hiring_analysis
    from snapshot import load_persisted

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404

    data = request.get_json(silent=True) or {}

    # Accept either a list of roles or a single role (backwards compat)
    roles = data.get("roles")
    if not roles:
        roles = [{
            "role": data.get("role", "New hire"),
            "monthly_cost": data.get("monthly_cost", 0),
            "is_revenue_generating": data.get("is_revenue_generating", False),
        }]

    ctx = snap.get("hiring_context") or {}
    profit = snap.get("profit") or {}

    result = compute_hiring_analysis(
        roles=roles,
        monthly_net_income=ctx.get("monthly_net_income", 0),
        current_mrr=ctx.get("current_mrr", 0),
        monthly_revenue=ctx.get("monthly_revenue") or profit.get("total_revenue"),
        monthly_cogs=profit.get("total_cogs"),
        monthly_opex=profit.get("total_operating_expenses"),
        avg_contract_value=ctx.get("avg_contract_value"),
        close_rate_pct=ctx.get("close_rate_pct"),
        avg_cash_per_close=ctx.get("avg_cash_per_close"),
        gross_margin_pct=ctx.get("gross_margin_pct"),
        true_team_cost=ctx.get("true_team_cost", 0),
    )
    return jsonify(result)


@bp.route("/api/sales-summary", methods=["GET"])
@require_auth
def api_sales_summary():
    """Generate a sales-team-safe markdown summary for a given window.

    Privacy boundary: ONLY sales/funnel/rep data. No financials, no payroll,
    no commissions, no MRR, no revenue, no CAC, no LTGP.
    """
    from dashboard.sales_summary import build_sales_summary
    from snapshot import load_persisted

    window_days = request.args.get("window_days", 30, type=int)
    if window_days not in (7, 14, 30, 60, 90):
        window_days = 30

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404

    markdown = build_sales_summary(snap, window_days)
    return jsonify({"markdown": markdown, "window_days": window_days})


@bp.route("/api/chat", methods=["POST"])
@require_auth
def api_chat():
    """Handle chat message with conversation history and snapshot context."""
    data = request.get_json(silent=True) or {}
    history = data.get("history", [])
    if not history:
        return jsonify({"error": "Empty message"}), 400

    from snapshot import load_persisted
    snap = load_persisted()
    snapshot_json = json.dumps(snap, indent=2) if snap else "{}"

    token = request.cookies.get(COOKIE_NAME, "anon")
    result = chat_fn(history, snapshot_json, token)
    return jsonify(result)
