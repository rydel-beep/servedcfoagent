"""
app.py
------
Flask application for the CFO agent.

Endpoints:
  GET  /health         — liveness check
  GET  /cfo/snapshot   — protected (X-CFO-KEY header or dashboard cookie), returns latest snapshot JSON
  POST /cfo/refresh    — protected by X-CFO-KEY header, triggers a fresh pull
"""
from __future__ import annotations

import logging
import os
import time

import requests as http_requests
from flask import Flask, jsonify, redirect, request

from config import (
    CFO_REFRESH_KEY, STRIPE_MCP_BASE, XERO_TOKEN_FILE,
    XERO_CLIENT_ID, XERO_CLIENT_SECRET, XERO_REDIRECT_URI,
)
from snapshot import build_snapshot, load_persisted

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "cfo-dashboard-dev-key-change-me")

# Register dashboard blueprint
from dashboard.routes import bp as dashboard_bp
app.register_blueprint(dashboard_bp, url_prefix="/dashboard")

# In-memory cache of the latest snapshot
_current_snapshot: dict | None = None

# Max age (seconds) before a persisted snapshot triggers auto-refresh on startup
_STALE_THRESHOLD = 4 * 3600  # 4 hours
# Keys that must be present — if missing, the snapshot predates current code
_REQUIRED_KEYS = {"active_clients", "client_reconciliation"}


def _snapshot_needs_refresh(snap: dict | None) -> bool:
    """Check if the persisted snapshot is stale or missing critical sections."""
    if snap is None:
        return True
    # Missing required keys means snapshot predates current code
    if not _REQUIRED_KEYS.issubset(snap.keys()):
        logger.info("Snapshot missing keys %s — needs refresh",
                     _REQUIRED_KEYS - snap.keys())
        return True
    # Check age
    gen_at = snap.get("generated_at")
    if gen_at:
        try:
            from datetime import datetime
            from helpers import now_sydney
            generated = datetime.fromisoformat(gen_at)
            age_seconds = (now_sydney() - generated).total_seconds()
            if age_seconds > _STALE_THRESHOLD:
                logger.info("Snapshot is %.1f hours old — needs refresh",
                            age_seconds / 3600)
                return True
        except (ValueError, TypeError):
            return True
    else:
        return True
    return False


def _startup_refresh() -> None:
    """Auto-refresh the snapshot on startup if it's stale or incomplete."""
    global _current_snapshot
    existing = load_persisted()
    if _snapshot_needs_refresh(existing):
        logger.info("Startup auto-refresh triggered")
        try:
            snap = build_snapshot()
            _current_snapshot = snap
            logger.info("Startup refresh complete — ok=%s, degraded=%d",
                        snap.get("ok"), len(snap.get("degraded", [])))
        except Exception as e:
            logger.error("Startup refresh failed: %s — using stale snapshot", e)
            _current_snapshot = existing
    else:
        _current_snapshot = existing
        logger.info("Persisted snapshot is fresh — skipping startup refresh")


def _get_snapshot() -> dict | None:
    global _current_snapshot
    if _current_snapshot is not None:
        return _current_snapshot
    _current_snapshot = load_persisted()
    return _current_snapshot


# ── Scheduled refresh ────────────────────────────────────────────────────────
# Before this, the snapshot only refreshed on process restart or a manual
# POST /cfo/refresh — observed going 4 days stale in production. A daemon
# thread now re-pulls every REFRESH_INTERVAL_HOURS (default 6).
_REFRESH_INTERVAL_HOURS = float(os.environ.get("REFRESH_INTERVAL_HOURS", "6"))


def _scheduled_refresh_loop() -> None:
    import threading as _t  # noqa: F401  (documents intent; thread started below)
    global _current_snapshot
    while True:
        time.sleep(_REFRESH_INTERVAL_HOURS * 3600)
        try:
            if _snapshot_needs_refresh(_get_snapshot()):
                logger.info("Scheduled refresh triggered (interval %.1fh)", _REFRESH_INTERVAL_HOURS)
                snap = build_snapshot()
                _current_snapshot = snap
                logger.info("Scheduled refresh complete — ok=%s, degraded=%d",
                            snap.get("ok"), len(snap.get("degraded", [])))
            else:
                logger.info("Scheduled refresh skipped — snapshot still fresh")
        except Exception as e:
            # Includes ConsistencyError: keep serving the last good snapshot.
            logger.error("Scheduled refresh failed: %s — keeping previous snapshot", e)


def _start_scheduled_refresh() -> None:
    import threading
    t = threading.Thread(target=_scheduled_refresh_loop, daemon=True, name="cfo-scheduled-refresh")
    t.start()
    logger.info("Scheduled refresh thread started (every %.1fh)", _REFRESH_INTERVAL_HOURS)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def _snapshot_request_authorized() -> bool:
    """Allow X-CFO-KEY header (machine consumers) or a valid dashboard cookie (owner)."""
    key = request.headers.get("X-CFO-KEY", "")
    if CFO_REFRESH_KEY and key == CFO_REFRESH_KEY:
        return True
    from dashboard.auth import COOKIE_NAME, DASHBOARD_TOKEN
    cookie_token = request.cookies.get(COOKIE_NAME)
    return bool(DASHBOARD_TOKEN) and cookie_token == DASHBOARD_TOKEN


@app.route("/cfo/snapshot", methods=["GET"])
def get_snapshot():
    # The snapshot contains payroll, cash balances, and the full financial picture.
    # It was public in the daily-pulse era; locked 2026-06-11.
    if not _snapshot_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    snap = _get_snapshot()
    if snap is None:
        return jsonify({"error": "No snapshot available yet. POST /cfo/refresh to generate one."}), 404
    resp = jsonify(snap)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


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


# accounting.reports.read is the BROAD reports scope — covers Profit & Loss AND
# Balance Sheet / Bank Summary (needed for live bank-account closing balances).
# Replaces the granular accounting.reports.profitandloss.read (which was P&L-only).
# Expanding the scope requires a one-time re-consent at /xero/connect.
XERO_SCOPES = "offline_access accounting.reports.read accounting.settings.read"


@app.route("/xero/connect", methods=["GET"])
def xero_connect():
    """Start Xero OAuth2 flow — redirects browser to Xero consent page."""
    if not XERO_CLIENT_ID or not XERO_REDIRECT_URI:
        return jsonify({"error": "XERO_CLIENT_ID or XERO_REDIRECT_URI not configured"}), 500
    auth_url = (
        "https://login.xero.com/identity/connect/authorize"
        f"?response_type=code"
        f"&client_id={XERO_CLIENT_ID}"
        f"&redirect_uri={XERO_REDIRECT_URI}"
        f"&scope={XERO_SCOPES.replace(' ', '+')}"
    )
    return redirect(auth_url)


@app.route("/xero/callback", methods=["GET"])
def xero_callback():
    """Handle Xero OAuth2 callback — exchange code for tokens, save tenant ID."""
    from xero_pull import _save_tokens

    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing authorization code"}), 400

    # Exchange code for tokens
    try:
        token_resp = http_requests.post(
            "https://identity.xero.com/connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": XERO_REDIRECT_URI,
                "client_id": XERO_CLIENT_ID,
                "client_secret": XERO_CLIENT_SECRET,
            },
            timeout=(5, 15),
        )
        if token_resp.status_code != 200:
            logger.error("Xero token exchange failed %d: %s", token_resp.status_code, token_resp.text[:300])
            return jsonify({"error": "Token exchange failed", "detail": token_resp.text[:300]}), 502
        token_data = token_resp.json()
    except http_requests.RequestException as e:
        logger.error("Xero token exchange request failed: %s", e)
        return jsonify({"error": f"Token exchange request failed: {e}"}), 502

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token or not refresh_token:
        return jsonify({"error": "Missing tokens in Xero response"}), 502

    # Fetch tenant ID from connections endpoint
    tenant_id = None
    try:
        conn_resp = http_requests.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(5, 10),
        )
        if conn_resp.status_code == 200:
            connections = conn_resp.json()
            if connections:
                tenant_id = connections[0].get("tenantId")
    except http_requests.RequestException as e:
        logger.warning("Failed to fetch Xero connections: %s", e)

    # Persist tokens via shared helper (uses XERO_TOKEN_FILE, creates dirs)
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "tenant_id": tenant_id,
    }
    _save_tokens(tokens)
    logger.info("Xero tokens saved via OAuth callback (tenant_id=%s)", tenant_id)

    return jsonify({
        "status": "connected",
        "tenant_id": tenant_id,
        "token_file": XERO_TOKEN_FILE,
        "message": "Xero OAuth complete. Refresh /cfo/snapshot to include Xero data.",
    })


@app.route("/debug/stripe-ping", methods=["GET"])
def debug_stripe_ping():
    """Test single Stripe MCP call with timing. Remove after debugging."""
    t0 = time.time()
    try:
        resp = http_requests.get(f"{STRIPE_MCP_BASE}/health", timeout=(5, 10))
        health_ms = round((time.time() - t0) * 1000)
        health_status = resp.status_code
    except Exception as e:
        health_ms = round((time.time() - t0) * 1000)
        health_status = str(e)

    t1 = time.time()
    try:
        resp = http_requests.post(
            f"{STRIPE_MCP_BASE}/call",
            json={"tool": "get_stripe_mrr", "arguments": {}},
            timeout=(5, 15),
        )
        mrr_ms = round((time.time() - t1) * 1000)
        mrr_result = resp.json() if resp.status_code == 200 else {"error": resp.status_code}
    except Exception as e:
        mrr_ms = round((time.time() - t1) * 1000)
        mrr_result = {"error": str(e)}

    return jsonify({
        "stripe_mcp_base": STRIPE_MCP_BASE,
        "health": {"status": health_status, "ms": health_ms},
        "mrr_call": {"result": mrr_result, "ms": mrr_ms},
    })


@app.route("/debug/sources", methods=["GET"])
def debug_sources():
    """Test each source individually with timing. Remove after debugging."""
    results = {}

    t0 = time.time()
    try:
        from stripe_pull import pull_stripe
        r = pull_stripe()
        results["stripe"] = {"ms": round((time.time() - t0) * 1000), "ok": True, "degraded": len(r.get("degraded", []))}
    except Exception as e:
        results["stripe"] = {"ms": round((time.time() - t0) * 1000), "error": str(e)}

    t0 = time.time()
    try:
        from ghl_pull import pull_ghl
        r = pull_ghl()
        results["ghl"] = {"ms": round((time.time() - t0) * 1000), "ok": True, "degraded": len(r.get("degraded", []))}
    except Exception as e:
        results["ghl"] = {"ms": round((time.time() - t0) * 1000), "error": str(e)}

    t0 = time.time()
    try:
        from sheets_pull import pull_sheets
        r = pull_sheets()
        results["sheets"] = {"ms": round((time.time() - t0) * 1000), "ok": True, "degraded": len(r.get("degraded", []))}
    except Exception as e:
        results["sheets"] = {"ms": round((time.time() - t0) * 1000), "error": str(e)}

    t0 = time.time()
    try:
        from xero_pull import pull_xero
        r = pull_xero()
        results["xero"] = {"ms": round((time.time() - t0) * 1000), "ok": r.get("xero") is not None, "degraded": len(r.get("degraded", []))}
    except Exception as e:
        results["xero"] = {"ms": round((time.time() - t0) * 1000), "error": str(e)}

    return jsonify(results)


@app.route("/debug/xero-raw", methods=["GET"])
def debug_xero_raw():
    """Dump raw Xero P&L response structure for diagnosis. Auth-protected."""
    key = request.headers.get("X-CFO-KEY", "")
    if not CFO_REFRESH_KEY or key != CFO_REFRESH_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    from datetime import timedelta
    from xero_pull import _load_tokens, _refresh_access_token, XERO_API_BASE
    from config import XERO_TOKEN_FILE, WINDOW_CURRENT
    from helpers import today_sydney

    stored = _load_tokens()
    if not stored or not stored.get("refresh_token"):
        return jsonify({"error": "No Xero tokens found", "token_file": XERO_TOKEN_FILE}), 404

    tokens = _refresh_access_token(stored)
    if not tokens:
        return jsonify({"error": "Token refresh failed"}), 502

    today = today_sydney()
    start = today - timedelta(days=WINDOW_CURRENT)

    try:
        resp = http_requests.get(
            f"{XERO_API_BASE}/api.xro/2.0/Reports/ProfitAndLoss",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Xero-Tenant-Id": tokens["tenant_id"],
                "Accept": "application/json",
            },
            params={"fromDate": str(start), "toDate": str(today)},
            timeout=(5, 15),
        )
        raw = resp.json() if resp.status_code == 200 else {"http_error": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        raw = {"error": str(e)}

    summary = {
        "date_range": {"fromDate": str(start), "toDate": str(today), "window_days": WINDOW_CURRENT},
        "token_file": XERO_TOKEN_FILE,
        "raw_report": raw,
    }
    return jsonify(summary)


@app.route("/debug/xero-banksummary", methods=["GET"])
def debug_xero_banksummary():
    """Dump raw Xero Bank Summary report for Stage 2A balance-semantics proof.
    Read-only + auth-protected. Needs the accounting.reports.read scope (re-consent).
    """
    key = request.headers.get("X-CFO-KEY", "")
    if not CFO_REFRESH_KEY or key != CFO_REFRESH_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    from datetime import timedelta
    from xero_pull import _load_tokens, _refresh_access_token, XERO_API_BASE
    from config import XERO_TOKEN_FILE
    from helpers import today_sydney

    stored = _load_tokens()
    if not stored or not stored.get("refresh_token"):
        return jsonify({"error": "No Xero tokens found", "token_file": XERO_TOKEN_FILE}), 404

    tokens = _refresh_access_token(stored)
    if not tokens:
        return jsonify({"error": "Token refresh failed"}), 502

    today = today_sydney()
    start = today - timedelta(days=30)

    try:
        resp = http_requests.get(
            f"{XERO_API_BASE}/api.xro/2.0/Reports/BankSummary",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Xero-Tenant-Id": tokens["tenant_id"],
                "Accept": "application/json",
            },
            params={"fromDate": str(start), "toDate": str(today)},
            timeout=(5, 15),
        )
        # 403 here => the token still lacks accounting.reports.read (re-consent not done).
        raw = resp.json() if resp.status_code == 200 else {"http_error": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        raw = {"error": str(e)}

    return jsonify({
        "date_range": {"fromDate": str(start), "toDate": str(today)},
        "note": "Closing-balance column is point-in-time at toDate. Proof tool only; not wired to cash.",
        "raw_report": raw,
    })


# ── Startup auto-refresh (runs once per worker, non-blocking) ──────────
import threading

def _deferred_startup():
    """Run startup refresh in a background thread so the worker can start serving."""
    with app.app_context():
        _startup_refresh()
        _start_scheduled_refresh()

_startup_thread = threading.Thread(target=_deferred_startup, daemon=True)
_startup_thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
