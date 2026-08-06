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

# Boot visibility (DECISIONS #112): a pre_import line before each risky module-level
# import means a boot-crashing SyntaxError/ImportError always names its module in the
# final log lines. Imports still crash the boot on purpose — with the build gate +
# healthcheck, a crashed boot never replaces the serving deployment.
import boot_banner

# Register dashboard blueprint
boot_banner.pre_import("dashboard.routes")
from dashboard.routes import bp as dashboard_bp
app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
boot_banner.module_ok("dashboard.routes")

# Register EDITH memory blueprint (Phase 5 UI). Self-contained; degrades to no-op if DB down.
boot_banner.pre_import("dashboard.memory_routes")
from dashboard.memory_routes import bp as memory_bp
app.register_blueprint(memory_bp, url_prefix="/dashboard/memory")
boot_banner.module_ok("dashboard.memory_routes")

# Owner-gated Timeline bridge (Layer 2 of the double gate; fail-closed without
# EDITH_BRIDGE_SECRET). Token-only auth — never session/cookie. See dashboard/bridge.py.
boot_banner.pre_import("dashboard.bridge")
from dashboard.bridge import bp as bridge_bp
app.register_blueprint(bridge_bp, url_prefix="/bridge")
boot_banner.module_ok("dashboard.bridge")

# SERVED AD TRACKING — the dedicated ad dashboard (owner/coo + media_buyer-when-enabled;
# isolation by construction: ad-domain data only, auth.py fail-closed scoping).
boot_banner.pre_import("dashboard.ads")
from dashboard.ads import bp as ads_bp
app.register_blueprint(ads_bp, url_prefix="/ads")
boot_banner.module_ok("dashboard.ads")

boot_banner.emit()


@app.errorhandler(Exception)
def _log_uncaught(e):
    """Structured last-words logging for any exception escaping a handler (DECISIONS
    #112) — no silent worker deaths. HTTP errors (404/405/…) pass through untouched."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    logger.error("UNCAUGHT %s on %s %s: %s", type(e).__name__,
                 request.method, request.path, e, exc_info=True)
    return jsonify({"error": "internal error", "class": type(e).__name__}), 500

# In-memory cache of the latest snapshot
_current_snapshot: dict | None = None

# Max age (seconds) before a persisted snapshot triggers auto-refresh.
# Tightened from 4h → 90min so a deal closed/entered today surfaces the same day
# without waiting out a long stale window. Manual POST /cfo/refresh still forces an
# unconditional rebuild regardless of this threshold. Env-overridable.
_STALE_THRESHOLD = int(os.environ.get("STALE_THRESHOLD_SECONDS", str(90 * 60)))
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
_REFRESH_INTERVAL_HOURS = float(os.environ.get("REFRESH_INTERVAL_HOURS", "2"))


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


def _email_cadence_loop() -> None:
    """Monday 09:00 Sydney drafts-only cadence (weekly generation + Library + PD ingest
    sweeps). By construction this can NEVER stage or send — it only writes pipeline rows
    (see EMAIL_SYSTEM_STATE.md + DECISIONS #110). kv-stamped so 2 workers fire once."""
    while True:
        time.sleep(15 * 60)
        try:
            import email_pipeline
            email_pipeline.cadence_tick()
        except Exception as e:  # noqa: BLE001
            logger.warning("email cadence tick failed: %s", e)


def _start_email_cadence() -> None:
    import threading
    threading.Thread(target=_email_cadence_loop, daemon=True, name="email-cadence").start()
    logger.info("email cadence thread started (Mon 09:00 Sydney window)")


def _start_scheduled_refresh() -> None:
    import threading
    t = threading.Thread(target=_scheduled_refresh_loop, daemon=True, name="cfo-scheduled-refresh")
    t.start()
    logger.info("Scheduled refresh thread started (every %.1fh)", _REFRESH_INTERVAL_HOURS)


@app.route("/health", methods=["GET"])
def health():
    """Liveness + subsystem triage. Never raises (each probe is guarded) so it's usable to
    diagnose an incident in seconds: server, DB/mirror, snapshot freshness, and which data
    sources are degraded. Returns 200 always (the server IS up if this responds); the body
    carries the real state."""
    subsystems: dict = {"server": "ok"}
    # Deploy identity (DECISIONS #112): which build is live, when it booted, what imported.
    boot = {"commit": boot_banner.BOOT_INFO.get("commit"),
            "booted_at": boot_banner.BOOT_INFO.get("booted_at"),
            "modules_ok": boot_banner.BOOT_INFO.get("modules_ok")}

    # DB / mirror reachability
    try:
        import db
        if not db.db_configured():
            subsystems["db"] = "not_configured"
        else:
            with db.get_conn() as c:
                c.execute("SELECT 1")
            subsystems["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        subsystems["db"] = f"error: {type(e).__name__}"

    # Snapshot presence + freshness + degraded sources
    try:
        from helpers import now_sydney
        snap = load_persisted()
        if not snap:
            subsystems["snapshot"] = "missing"
        else:
            gen = snap.get("generated_at")
            age_min = None
            try:
                import datetime as _dt
                g = _dt.datetime.fromisoformat(gen)
                age_min = round((now_sydney() - g).total_seconds() / 60, 1)
            except Exception:
                pass
            deg = snap.get("degraded") or []
            subsystems["snapshot"] = {
                "present": True,
                "generated_at": gen,
                "age_minutes": age_min,
                "stale": (age_min is not None and age_min > 180),
                "ok": bool(snap.get("ok")),
                "degraded_count": len(deg),
                "degraded_sources": sorted({(d.get("metric") or "?") for d in deg})[:12],
            }
    except Exception as e:  # noqa: BLE001
        subsystems["snapshot"] = f"error: {type(e).__name__}"

    # Overall: 'ok' only if server+db+snapshot are healthy; else 'degraded' (never a lie).
    snap_state = subsystems.get("snapshot")
    healthy = (subsystems.get("db") in ("ok", "not_configured")
               and isinstance(snap_state, dict) and snap_state.get("present")
               and not snap_state.get("stale"))
    return jsonify({"status": "ok" if healthy else "degraded", "subsystems": subsystems,
                    "commit": boot["commit"], "booted_at": boot["booted_at"],
                    "modules_ok": boot["modules_ok"]})


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


@app.route("/cfo/attribution", methods=["GET"])
def get_attribution():
    """Per-creative ad attribution (owner surface — same gate as the snapshot: it names
    real leads/deals). Windows: ?days=30|60|90 or ?start=&end= (ISO). ads_read only."""
    if not _snapshot_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    import attribution_engine
    try:
        days = min(max(int(request.args.get("days", 30)), 1), 365)
    except ValueError:
        return jsonify({"error": "bad days"}), 400
    result = attribution_engine.compute(
        days=days, start=request.args.get("start"), end=request.args.get("end"),
        force=request.args.get("force") == "1")
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _attribution_compute_from_args():
    """Shared window/force parsing for the scoreboard + rows views. Same engine call —
    same cache — zero parallel math."""
    import attribution_engine
    try:
        days = min(max(int(request.args.get("days", 30)), 1), 365)
    except ValueError:
        return None, (jsonify({"error": "bad days"}), 400)
    return attribution_engine.compute(
        days=days, start=request.args.get("start"), end=request.args.get("end"),
        force=request.args.get("force") == "1"), None


@app.route("/cfo/attribution/scoreboard", methods=["GET"])
def get_attribution_scoreboard():
    """The per-creative tally scoreboard — a reshape of the engine result (owner gate)."""
    if not _snapshot_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    import attribution_engine
    result, err = _attribution_compute_from_args()
    if err:
        return err
    resp = jsonify(attribution_engine.scoreboard_view(result))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/cfo/attribution/rows", methods=["GET"])
def get_attribution_rows():
    """The live tracker rows with each lead's creative + revenue state + highlights.
    Filters: ?creative=<key>&tier=ad|ig_dm|unattributed&q=<name/business substring>."""
    if not _snapshot_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    result, err = _attribution_compute_from_args()
    if err:
        return err
    rows = result.get("rows") or []
    creative = request.args.get("creative")
    tier = request.args.get("tier")
    q = (request.args.get("q") or "").strip().lower()
    if creative:
        rows = [r for r in rows if r["creative"]["key"] == creative]
    if tier:
        rows = [r for r in rows if r["creative"]["tier"] == tier]
    if q:
        rows = [r for r in rows if q in (r["name"] or "").lower()
                or q in (r["business"] or "").lower()]
    resp = jsonify({"window": result.get("window"), "rows": rows, "total": len(rows),
                    "qualified_rule": result.get("qualified_rule"),
                    "freshness": result.get("freshness"),
                    "reconciliation": result.get("reconciliation")})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# Scope set must match what the Xero app has ENABLED, or consent 500s with
# invalid_scope. This app exposes only GRANULAR report scopes — the broad
# accounting.reports.read / accounting.transactions.read are NOT enabled
# (verified empirically against the live authorize endpoint). Granular set:
#   offline_access                          - refresh token (stops silent expiry)
#   accounting.reports.profitandloss.read   - P&L (keeps existing pull working)
#   accounting.reports.banksummary.read     - bank account closing balances
#   accounting.reports.balancesheet.read    - balances (cross-check / fallback)
XERO_SCOPES = (
    "offline_access "
    "accounting.reports.profitandloss.read "
    "accounting.reports.banksummary.read "
    "accounting.reports.balancesheet.read"
)


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


@app.route("/debug/xero-probe", methods=["GET"])
def debug_xero_probe():
    """BAS/PAYG Phase-0 CAPABILITY PROBE (read-only, X-CFO-KEY gated). ONE token
    refresh (single-use refresh tokens — persist-first on this volume), then a
    status-code sweep of the endpoints the BAS layer could use, plus the tax-relevant
    Balance Sheet lines (GST / PAYG / BAS accounts) at the requested dates. Never
    writes to Xero; never returns credentials."""
    key = request.headers.get("X-CFO-KEY", "")
    if not CFO_REFRESH_KEY or key != CFO_REFRESH_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    from xero_pull import _load_tokens, _refresh_access_token, XERO_API_BASE

    stored = _load_tokens()
    if not stored or not stored.get("refresh_token"):
        return jsonify({"error": "No Xero tokens found"}), 404
    tokens = _refresh_access_token(stored)
    if not tokens:
        return jsonify({"error": "Token refresh failed"}), 502
    hdrs = {"Authorization": f"Bearer {tokens['access_token']}",
            "Xero-Tenant-Id": tokens["tenant_id"], "Accept": "application/json"}

    def _try(path, params=None):
        try:
            r = http_requests.get(f"{XERO_API_BASE}{path}", headers=hdrs,
                                  params=params or {}, timeout=(5, 20))
            body = None
            if r.status_code != 200:
                body = r.text[:160]
            return {"status": r.status_code, "detail": body}
        except Exception as e:
            return {"status": None, "detail": str(e)[:160]}

    today = today_sydney()
    probes = {
        "reports_pnl": _try("/api.xro/2.0/Reports/ProfitAndLoss",
                            {"fromDate": str(today.replace(day=1)), "toDate": str(today)}),
        "reports_banksummary": _try("/api.xro/2.0/Reports/BankSummary",
                                    {"fromDate": str(today.replace(day=1)), "toDate": str(today)}),
        "reports_balancesheet": _try("/api.xro/2.0/Reports/BalanceSheet", {"date": str(today)}),
        "reports_trialbalance": _try("/api.xro/2.0/Reports/TrialBalance", {"date": str(today)}),
        "reports_list": _try("/api.xro/2.0/Reports"),
        "invoices_linelevel": _try("/api.xro/2.0/Invoices", {"page": 1, "pageSize": 1}),
        "banktransactions_linelevel": _try("/api.xro/2.0/BankTransactions", {"page": 1}),
        "taxrates_settings": _try("/api.xro/2.0/TaxRates"),
        "organisation_settings": _try("/api.xro/2.0/Organisation"),
        "payroll_au_employees": _try("/payroll.xro/1.0/Employees"),
        "payroll_au_activitystatement": _try("/payroll.xro/1.0/Settings"),
    }

    # Tax-relevant Balance Sheet lines at each requested date (defaults: last quarter
    # boundary + today) — the ledger-derived GST/PAYG path available with CURRENT scopes.
    bs_dates = [d.strip() for d in
                (request.args.get("bs_dates") or "").split(",") if d.strip()] or [str(today)]
    tax_lines = {}
    for d in bs_dates[:6]:
        try:
            r = http_requests.get(f"{XERO_API_BASE}/api.xro/2.0/Reports/BalanceSheet",
                                  headers=hdrs, params={"date": d}, timeout=(5, 20))
            if r.status_code != 200:
                tax_lines[d] = {"error": f"http {r.status_code}"}
                continue
            rep = (r.json().get("Reports") or [{}])[0]
            hits = []

            def walk(rows):
                for row in rows or []:
                    if row.get("Rows"):
                        walk(row["Rows"])
                    cells = row.get("Cells") or []
                    if len(cells) >= 2:
                        name = (cells[0].get("Value") or "").strip()
                        low = name.lower()
                        if any(k in low for k in ("gst", "payg", "bas", "tax", "ato")):
                            try:
                                val = float(str(cells[1].get("Value")).replace(",", ""))
                            except (TypeError, ValueError):
                                val = None
                            hits.append({"account": name, "balance": val})

            walk(rep.get("Rows", []))
            tax_lines[d] = {"lines": hits}
        except Exception as e:
            tax_lines[d] = {"error": str(e)[:160]}

    return jsonify({"as_of": str(today), "org": "via connected tenant",
                    "granted_scopes_requested_at_consent": XERO_SCOPES,
                    "probes": probes, "balance_sheet_tax_lines": tax_lines,
                    "note": "read-only capability probe; 403 = scope not granted"})


# ── Startup auto-refresh (runs once per worker, non-blocking) ──────────
import threading

def _deferred_startup():
    """Run startup refresh in a background thread so the worker can start serving."""
    with app.app_context():
        # Apply the persistent-memory schema (idempotent; no-op + logged if DB absent).
        try:
            import db as _db
            if _db.db_configured():
                _db.migrate()
        except Exception as _e:  # never let memory setup block the app
            logger.error("Memory migrate-on-boot skipped: %s", _e)
        # Sheet mirror: create tables + start the background sync loop (live-backed cache).
        try:
            import sheet_mirror
            sheet_mirror.migrate()
            sheet_mirror.start_sync_loop()
        except Exception as _e:
            logger.error("Sheet-mirror boot skipped: %s", _e)
        # GHL mirror: create tables + start the opportunities sync loop (contacts/notes via resync/backfill).
        try:
            import ghl_mirror
            ghl_mirror.migrate()
            ghl_mirror.start_sync_loop()
        except Exception as _e:
            logger.error("GHL-mirror boot skipped: %s", _e)
        # MRR snapshot: start the durable monthly/quarter-boundary MRR history (G3) — take one now.
        try:
            import mrr_snapshot
            mrr_snapshot.migrate()
            mrr_snapshot.take_snapshot()
        except Exception as _e:
            logger.error("MRR-snapshot boot skipped: %s", _e)
        # Capital allocation: create tables + seed the six buckets (the deciding layer).
        try:
            import capital_allocation
            capital_allocation.migrate()
        except Exception as _e:
            logger.error("Capital-allocation boot skipped: %s", _e)
        # Ad attribution: attr_contacts table + periodic recompute (lazy on request too).
        try:
            import attribution_join
            import attribution_engine
            attribution_join.migrate()
            attribution_engine.start_loop()
        except Exception as _e:
            logger.error("Attribution boot skipped: %s", _e)
        _startup_refresh()
        _start_scheduled_refresh()
    _start_email_cadence()

_startup_thread = threading.Thread(target=_deferred_startup, daemon=True)
_startup_thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
