"""
dashboard/routes.py
-------------------
Flask blueprint for the Jarvis CFO dashboard.
"""
from __future__ import annotations

import json
import logging
import os

from flask import (
    Blueprint, render_template, request, jsonify, make_response, redirect,
    url_for, Response, stream_with_context,
)

from dashboard.auth import require_auth, require_owner, DASHBOARD_TOKEN, COOKIE_NAME, COOKIE_MAX_AGE
from dashboard.chat import chat as chat_fn, chat_stream as chat_stream_fn
from config import CFO_REFRESH_KEY

logger = logging.getLogger(__name__)

# Cache-bust static assets per deploy: Railway exposes the git sha; fall back
# to process start time so every restart still busts.
import time as _time
_ASSET_VERSION = (os.environ.get("RAILWAY_GIT_COMMIT_SHA", "") or str(int(_time.time())))[:12]

bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)


def _repetition_failure(reply: str, history: list, user_msg: str) -> bool:
    """A drafted deterministic reply that is VERBATIM-identical to a recent assistant reply, in
    response to a DIFFERENT user message, is a routing failure (the incident's canned-line re-fire).
    Return True → suppress it and fall to the thread-aware/model path. Re-asking the SAME question is
    fine (answered consistently), so we compare the user messages too."""
    if not reply:
        return False
    def _n(s):
        return " ".join((s or "").lower().split())
    r = _n(reply)
    users = [m.get("content") for m in (history or []) if m.get("role") == "user"]
    prev_user = _n(users[-2]) if len(users) >= 2 else ""   # the message before the current one
    if _n(user_msg) == prev_user:
        return False   # genuinely the same question re-asked → a consistent repeat is acceptable
    for m in reversed(history or []):
        if m.get("role") == "assistant":
            return _n(m.get("content")) == r   # identical to the immediately prior answer → failure
    return False


@bp.route("/")
@require_auth
def index():
    """Serve the main dashboard page with the last snapshot inlined.

    Instant paint: the page renders from the embedded snapshot immediately,
    then the client refreshes from /api/snapshot in the background.
    """
    import json as _json
    from snapshot import load_persisted
    snap = load_persisted()
    # </ must not appear inside an inline <script> block
    boot = _json.dumps(snap).replace("</", "<\\/") if snap else "null"
    from config import PICOVOICE_ACCESS_KEY
    wake_ppn = os.path.exists(os.path.join(
        os.path.dirname(__file__), "static", "wake", "hey_edith_wasm.ppn"))
    edith_cfg = _json.dumps({
        "picovoiceKey": PICOVOICE_ACCESS_KEY,   # authed page only, by design
        "wakePpnPresent": wake_ppn,
        "wakePpnPath": "/dashboard/static/wake/hey_edith_wasm.ppn",
    })
    return render_template("dashboard.html", boot_snapshot=boot, edith_cfg=edith_cfg,
                           asset_v=_ASSET_VERSION)


@bp.route("/login", methods=["GET"])
def login_page():
    """Login form — username/password once per-user auth is enabled, else the legacy token field."""
    import dashboard.auth as auth
    return render_template("login.html", per_user=auth.per_user_enabled())


@bp.route("/login", methods=["POST"])
def login_submit():
    """Per-user login (username + password) → server-side session with role. Legacy token still
    accepted ONLY while no per-user accounts are configured (safe migration)."""
    from flask import session
    import dashboard.auth as auth
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    actor = auth.verify_login(username, password)
    if actor:
        session.permanent = True
        session["actor"] = actor
        auth.audit_login(actor, ok=True)
        return redirect(url_for("dashboard.index"))
    if username:
        auth.audit_login({"user": username}, ok=False)

    # Legacy token path — only while per-user auth is not yet enabled.
    token = request.form.get("token", "").strip()
    if not auth.per_user_enabled() and token and token == DASHBOARD_TOKEN:
        resp = make_response(redirect(url_for("dashboard.index")))
        resp.set_cookie(COOKIE_NAME, DASHBOARD_TOKEN, max_age=COOKIE_MAX_AGE,
                        httponly=True, samesite="Lax", secure=True)
        return resp
    return render_template("login.html", error="Invalid credentials",
                           per_user=auth.per_user_enabled()), 401


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    from flask import session
    session.pop("actor", None)
    resp = make_response(redirect(url_for("dashboard.login_page")))
    resp.delete_cookie(COOKIE_NAME)
    return resp


@bp.route("/api/snapshot", methods=["GET"])
@require_auth
def api_snapshot():
    """Return current snapshot as JSON."""
    from snapshot import load_persisted
    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404
    resp = jsonify(snap)
    # Never let a client/proxy serve a stale snapshot after a refresh.
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


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

    resp = jsonify({
        "status": "refreshed",
        "ok": snap.get("ok"),
        "degraded_count": len(snap.get("degraded", [])),
        "generated_at": snap.get("generated_at"),
    })
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


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
            # Brief "movers": engine values only, no recomputation
            "cash_in_bank": (snap.get("cash_position") or {}).get("cash_in_bank"),
            "runway_months": (snap.get("cash_position") or {}).get("runway_months"),
            "total_monthly_burn": (snap.get("cash_position") or {}).get("total_monthly_burn"),
            "active_clients": (snap.get("active_clients") or {}).get("active_count"),
            "next_mrr": ch.get("next_mrr"),
            "stripe_collected_30d": (((snap.get("stripe") or {}).get("revenue") or {}).get("current") or {}).get("total_aud"),
            "failed_charges": (snap.get("stripe") or {}).get("failed_charges_count"),
        })

    return jsonify(result)


@bp.route("/api/voice-status", methods=["GET"])
@require_auth
def api_voice_status():
    """Voice layer health: ElevenLabs configured? usage vs caps. No key material."""
    from dashboard.voice import tts_usage
    return jsonify(tts_usage())


@bp.route("/api/memory-status", methods=["GET"])
@require_auth
def api_memory_status():
    """Persistent-memory health for the UI badge — so a DB failure is LOUD, never a
    silent fall-back to forgetting. Returns online + reason + table row counts. No
    secrets (the connection string never leaves the server)."""
    import memory
    import db
    status = memory.memory_status()          # {online, reason}
    status["schema"] = db.schema_overview()  # {} when offline; counts when up
    return jsonify(status)


@bp.route("/api/tts", methods=["GET", "POST"])
@require_auth
def api_tts():
    """Stream ElevenLabs audio for the given text (server-proxied; key never
    leaves the server). GET supports progressive playback via an <audio> src.
    On any TTS failure returns JSON {fallback: true} so the client drops to
    browser speechSynthesis — a TTS failure never blocks the answer."""
    from dashboard.voice import stream_tts
    from flask import Response

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        voice_id = data.get("voice_id")
    else:
        text = request.args.get("text", "")
        voice_id = request.args.get("voice_id")
    return tts_response(text, voice_id)


def tts_response(text: str, voice_id=None):
    """Shared TTS proxy core (dashboard route above + the Timeline bridge).
    Caller is responsible for auth. The text is rewritten FOR THE EAR here —
    currency, ratios, acronyms, dates, eye-formatting — so BOTH surfaces speak
    cleanly; the client keeps the eye-formatted text for its captions."""
    from dashboard.voice import stream_tts
    from flask import Response
    from speech_normalize import normalize_for_speech
    text = normalize_for_speech(text)

    try:
        gen = stream_tts(text, voice_id_override=voice_id)
        # Pull the first chunk eagerly so failures surface as JSON, not mid-stream
        first = next(gen)
    except (RuntimeError, StopIteration) as e:
        reason = str(e) or "no audio"
        return jsonify({"fallback": True, "reason": reason}), 503

    def stream():
        yield first
        yield from gen

    return Response(stream(), mimetype="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


@bp.route("/api/brief", methods=["POST"])
@require_auth
def api_brief():
    """Compose the spoken daily brief from the engines (text; client TTS's it)."""
    from snapshot import load_persisted
    from dashboard.voice import build_brief
    import history_store

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available"}), 404

    entries = history_store.last_n_snapshots(2)
    history = []
    for entry in entries:
        s = entry.get("snapshot", {})
        ch = s.get("client_health") or {}
        history.append({
            "mrr": ch.get("current_mrr"),
            "stripe_collected_30d": (((s.get("stripe") or {}).get("revenue") or {}).get("current") or {}).get("total_aud"),
            "active_clients": (s.get("active_clients") or {}).get("active_count"),
            "failed_charges": (s.get("stripe") or {}).get("failed_charges_count"),
        })

    token = request.cookies.get(COOKIE_NAME, "anon")
    result = build_brief(snap, history, token)
    return jsonify(result)


@bp.route("/api/greeting", methods=["GET"])
@require_auth
def api_greeting():
    """EDITH's boot greeting: resolved location + salient NEW events, composed fresh each time.
    Session-gated — a quick refresh/resume within the idle gap returns the SAME greeting (no
    re-greet, no re-watermarking). A genuinely new session composes fresh and advances the feed."""
    return greeting_response(force=(request.args.get("fresh") == "1"))


def greeting_response(force: bool = False):
    """Shared greeting core (dashboard route above + the Timeline bridge). The
    25-min re-greet gate and the salience watermark are deliberately SHARED across
    surfaces — news is announced once, whichever window he opens first."""
    import time as _t
    import kv_store
    from snapshot import load_persisted
    from dashboard.voice import build_greeting
    snap = load_persisted() or {}
    _IDLE = 25 * 60
    last = kv_store.get("greeting:last_delivered") or {}
    if not force and last.get("ts") and (_t.time() - last["ts"]) < _IDLE and last.get("payload"):
        return jsonify({**last["payload"], "regreet": False})
    payload = build_greeting(snap, mark=True)   # composes, watermarks, remembers shape
    kv_store.put("greeting:last_delivered", {"ts": _t.time(), "payload": payload})
    return jsonify({**payload, "regreet": True})


# ── Collaboration layer (work log, queue, verification, digest, journal) ─────
@bp.route("/api/collab/log", methods=["GET", "POST"])
@require_auth
def api_collab_log():
    import collab
    from dashboard.auth import current_actor
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        actor = current_actor()
        body = (d.get("body") or "").strip()
        if not body:
            return jsonify({"ok": False, "error": "empty — type something to post"}), 400
        e = collab.add_entry(actor.get("user"), d.get("kind", "suggestion"),
                             body, d.get("link_type"), d.get("link_ref"), d.get("parent_id"))
        if not e:
            # loud server-side surfacing — role + endpoint so the next such bug is diagnosable fast
            logger.error("collab LOG WRITE FAILED — user=%s role=%s endpoint=/api/collab/log kind=%s",
                         actor.get("user"), actor.get("role"), d.get("kind"))
            return jsonify({"ok": False, "error": "couldn’t save to the log — please retry"}), 500
        return jsonify({"ok": True, "entry": e})
    return jsonify({"entries": collab.list_entries(
        start=request.args.get("start"), end=request.args.get("end"),
        author=request.args.get("author"), kind=request.args.get("kind"),
        include_archived=request.args.get("archived") == "1")})


@bp.route("/api/collab/queue", methods=["GET"])
@require_auth
def api_collab_queue():
    import collab
    from snapshot import load_persisted
    return jsonify({"queue": collab.queue(load_persisted() or {})})


@bp.route("/api/collab/resolve", methods=["POST"])
@require_auth
def api_collab_resolve():
    import collab
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    actor = current_actor()
    if not d.get("flag_id"):
        return jsonify({"ok": False, "error": "flag_id required"}), 400
    res = collab.resolve_item(d["flag_id"], d.get("note", ""), actor)
    if isinstance(res, dict) and res.get("ok") is False:
        logger.error("collab RESOLVE FAILED — user=%s role=%s endpoint=/api/collab/resolve flag=%s",
                     actor.get("user"), actor.get("role"), d.get("flag_id"))
        return jsonify(res), 500
    return jsonify(res)


@bp.route("/api/collab/digest", methods=["GET"])
@require_auth
def api_collab_digest():
    import collab
    return jsonify(collab.digest("rydel", advance=request.args.get("peek") != "1"))


@bp.route("/api/collab/journal", methods=["GET"])
@require_auth
def api_collab_journal():
    import collab
    from dashboard.auth import current_actor
    return jsonify({"journal": collab.journal(start=request.args.get("start"),
                                              end=request.args.get("end"),
                                              role=current_actor().get("role"))})


@bp.route("/api/collab/export", methods=["POST"])
@require_auth
def api_collab_export():
    import collab
    return jsonify(collab.export_archive())


@bp.route("/api/whoami", methods=["GET"])
@require_auth
def api_whoami():
    from dashboard.auth import current_actor
    return jsonify(current_actor())


@bp.route("/api/geolocation", methods=["POST"])
@require_auth
def api_geolocation():
    """Dashboard-provided browser coordinates (consented) → reverse-geocode + cache as last-known,
    so the greeting follows Rydel when he travels. Silent, best-effort."""
    import location
    data = request.get_json(silent=True) or {}
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"ok": False, "error": "lat/lon required"}), 400
    loc = location.set_geo(float(lat), float(lon))
    return jsonify({"ok": True, "place": (loc or {}).get("place")})


@bp.route("/api/action-feed", methods=["GET"])
@require_auth
def api_action_feed():
    """ZONE 3 — the consolidated action feed (owner-only): salience + data-quality + reconciliation,
    ranked by severity with plain-language actions. One feed, not scattered warnings."""
    import action_feed
    from snapshot import load_persisted
    return jsonify(action_feed.build_action_feed(load_persisted() or {}))


@bp.route("/api/forecast", methods=["GET"])
@require_auth
def api_forecast():
    """The forecasting block (owner-only): 13-week cash flow, dynamic runway, MRR scenarios,
    accuracy. Every figure is a PROJECTION with visible, adjustable assumptions. Deterministic base."""
    import forecasting_engine
    from snapshot import load_persisted
    return jsonify(forecasting_engine.build_forecast(load_persisted() or {}))


@bp.route("/api/capacity", methods=["GET"])
@require_auth
def api_capacity():
    """Team & Capacity block (owner-only, behind dashboard auth): department load, hire trigger,
    hiring budget, constraint check. Raise signals are a separate owner-only call. Deterministic."""
    import capacity_engine
    from snapshot import load_persisted
    snap = load_persisted() or {}
    payload = capacity_engine.build_capacity(snap)
    if request.args.get("raises") == "1":
        payload["raise_signals"] = capacity_engine.raise_signals(snap)
    return jsonify(payload)


@bp.route("/api/voice-config", methods=["POST"])
@require_auth
def api_voice_config():
    """Set the runtime voice (audition tool): {voice_id, stability, similarity}.
    Empty body resets to the locked default. No redeploy needed."""
    from dashboard.voice import save_voice_config, tts_usage
    cfg = save_voice_config(request.get_json(silent=True) or {})
    out = tts_usage()
    out["saved"] = cfg
    return jsonify(out)


# Entrance music slot: env-configurable, Railway-volume-aware.
# /data (volume) survives redeploys; the app-dir fallback does NOT — the
# status payload flags that so the UI can say "re-upload after each deploy".
_HAS_VOLUME = os.path.isdir("/data")
_ENTRANCE_FILE = os.environ.get(
    "ENTRANCE_AUDIO_PATH",
    "/data/entrance.mp3" if _HAS_VOLUME
    else os.path.join(os.path.dirname(__file__), "..", "state", "entrance.mp3"))
_ENTRANCE_MAX_BYTES = 15 * 1024 * 1024
_ENTRANCE_TYPES = {"audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/aac"}


def _entrance_status() -> dict:
    present = os.path.exists(_ENTRANCE_FILE)
    return {
        "present": present,
        "bytes": os.path.getsize(_ENTRANCE_FILE) if present else 0,
        "volatile": not _HAS_VOLUME and not os.environ.get("ENTRANCE_AUDIO_PATH"),
    }


@bp.route("/audio/entrance", methods=["GET"])
@require_auth
def audio_entrance():
    """EDITH's wake track — the user-uploaded file only. The build ships NO
    audio files; absent slot → 404 and the client plays the synth power-up."""
    from flask import send_file
    if os.path.exists(_ENTRANCE_FILE):
        return send_file(_ENTRANCE_FILE, mimetype="audio/mpeg", max_age=300)
    return jsonify({"error": "no entrance audio uploaded"}), 404


@bp.route("/api/entrance-audio", methods=["GET", "POST", "DELETE"])
@require_auth
def api_entrance_audio():
    """Status / upload / remove for the user-supplied entrance track.
    Stored at ENTRANCE_AUDIO_PATH (volume), never in the repo."""
    if request.method == "GET":
        return jsonify(_entrance_status())

    if request.method == "DELETE":
        if os.path.exists(_ENTRANCE_FILE):
            os.remove(_ENTRANCE_FILE)
        return jsonify({"ok": True, "present": False})

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    if f.mimetype and f.mimetype not in _ENTRANCE_TYPES:
        return jsonify({"error": f"unsupported type {f.mimetype} (mp3/m4a only)"}), 415
    blob = f.read(_ENTRANCE_MAX_BYTES + 1)
    if len(blob) > _ENTRANCE_MAX_BYTES:
        return jsonify({"error": "file too large (15MB max)"}), 413
    os.makedirs(os.path.dirname(_ENTRANCE_FILE), exist_ok=True)
    with open(_ENTRANCE_FILE, "wb") as out:
        out.write(blob)
    logger.info("Entrance audio uploaded (%d bytes) -> %s", len(blob), _ENTRANCE_FILE)
    out_status = _entrance_status()
    out_status["ok"] = True
    return jsonify(out_status)


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
    fp = snap.get("financial_position") or {}

    # Get growth rate from projection for 3-month forecast
    projection = (snap.get("client_health") or {}).get("mrr_projection") or {}
    growth_rate = projection.get("growth_rate_latest")

    # Get binding constraint from deficiency analysis
    da = snap.get("deficiency_analysis") or {}
    deficiencies = da.get("deficiencies") or []
    binding = deficiencies[0].get("label") if deficiencies else None

    burn = snap.get("monthly_burn") or {}
    total_burn = burn.get("total_recurring_burn")

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
        financial_position=fp,
        growth_rate_pct=growth_rate,
        binding_constraint=binding,
        forward_mrr=snap.get("forward_mrr"),
        cash_position=snap.get("cash_position"),
        raises=data.get("raises"),
        total_monthly_burn=total_burn,
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


@bp.route("/api/briefing-pdf", methods=["GET"])
@require_auth
def api_briefing_pdf():
    """Generate and return the full CFO briefing PDF."""
    from dashboard.briefing_pdf import generate_briefing_pdf
    from snapshot import load_persisted

    snap = load_persisted()
    if snap is None:
        return jsonify({"error": "No snapshot available — trigger a refresh first"}), 404

    try:
        pdf_data = generate_briefing_pdf(snap)
        pdf_bytes = bytes(pdf_data)  # fpdf2 returns bytearray; Flask needs bytes
    except Exception as e:
        logger.exception("PDF generation failed")
        import traceback
        tb = traceback.format_exc()
        return jsonify({"error": str(e), "traceback": tb}), 500

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = "attachment; filename=served-cfo-briefing.pdf"
    resp.headers["Content-Length"] = str(len(pdf_bytes))
    return resp


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

    from dashboard.auth import current_actor
    token = current_actor().get("user") or request.cookies.get(COOKIE_NAME, "anon")
    voice = bool(data.get("voice"))

    # Persistent memory: resume/start a conversation, persist the user turn (async),
    # and build the recall block. All graceful no-ops if the DB is offline.
    import memory
    channel = "voice" if voice else "text"
    conv_id = memory.start_conversation(channel)
    user_msg = (history[-1].get("content") if history else "") or ""
    # Rebuild the thread from the DB if the client lost it (refresh/new tab) BEFORE
    # writing the new turn — this is what makes a refresh RESUME instead of restart.
    history = memory.resume_thread(conv_id, history)
    memory.record_turn(conv_id, "user", user_msg, channel=channel)

    # Data-layer commands: "resync"/"sync now" (immediate mirror sync + rebuild) and
    # "what's plugged into your system / is your data current" — handled locally (no model).
    import sheet_mirror
    for _h in (sheet_mirror.handle_resync_command, sheet_mirror.handle_sources_query):
        _reply, _handled = _h(user_msg)
        if _handled:
            memory.record_turn(conv_id, "assistant", _reply, channel=channel, intent="command")
            return jsonify({"reply": _reply, "error": None, "intent": "command"})

    # Manual target/benchmark/note command? Handle locally (no model), with a
    # confirmation loop. Only manual (no-live-source) values; auth already enforced.
    import manual_targets
    tgt_reply, handled = manual_targets.handle_turn(user_msg, token)
    if handled:
        memory.record_turn(conv_id, "assistant", tgt_reply, channel=channel, intent="command")
        return jsonify({"reply": tgt_reply, "error": None, "intent": "command"})

    # Email-engine review commands ("approve the weekly" → echo → "yes"): confirmation loop.
    import email_pipeline as _ep
    _er, _eh = _ep.handle_review_command(user_msg, token)
    if _eh:
        memory.record_turn(conv_id, "assistant", _er, channel=channel, intent="command")
        return jsonify({"reply": _er, "error": None, "intent": "command"})

    # Client churn/downgrade WRITE-BACK (dashboard override, confirmation loop) + undo + Piolo queue.
    # Checked early so a "yes/no" confirmation lands here. Auth already enforced (only Rydel writes).
    import client_overrides
    for _cb in (lambda m: client_overrides.handle_client_writeback_command(m, token),
                lambda m: client_overrides.handle_undo_command(m, token),
                client_overrides.handle_pending_updates_query,
                client_overrides.handle_client_changes_query):
        _r, _h = _cb(user_msg)
        if _h:
            memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    # Location override + "where am I" + "what's new" — short explicit commands/queries (TIER 1),
    # run before the ramble gate so they always resolve deterministically.
    import location, salience
    for _lh in (location.handle_location_command, salience.handle_whats_new):
        _r, _h = _lh(user_msg)
        if _h:
            memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    # SELF-CHECK LOOP (TIER 1): a challenge to a data claim ("that's wrong / it's not blank / I just
    # checked") triggers in-chat resync → re-read → correct-or-confirm with root cause. Runs before
    # the ramble gate + needs the thread (where the claim was made). Also the incident handoff.
    import tracker_read, incident_log
    _thread6 = " ".join((m.get("content") or "") for m in (history or [])[-6:])
    import stripe_reconcile
    for _sh in (lambda m: tracker_read.handle_self_check(m, _thread6),
                incident_log.handle_incident_query,
                stripe_reconcile.handle_alias_confirm):
        _r, _h = _sh(user_msg)
        if _h:
            memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    # ── TIER 2: deterministic DATA handlers — GATED. A conversational ramble (long, declarative,
    # no data-request structure) SKIPS these entirely and falls through to the model (TIER 3).
    # Default-to-conversation: when unsure, a generic reply beats a jarring data non-sequitur.
    import intent_router, range_unit_economics, payback_reconciliation
    import leads_view, closes_view, liabilities_view, salary_view
    if not intent_router.is_conversational_ramble(user_msg):
        _thread = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        # (handler, entity_scoped?) — entity_scoped lookups are entity-filtered (the Romano rule);
        # superlative/recency lookups (latest lead, biggest deal) surface entities by design → exempt.
        import capacity_engine, forecasting_engine
        _tier2 = [
            (lambda m: __import__('conversation').handle(m, history), False),  # ADVISORY + ANAPHORA/scenario — FIRST so follow-ups ('5 more closes') aren't grabbed by forecast/recital
            (lambda m: __import__('capital_allocation').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # capital allocation: deploy / opportunity-cost / review / set buffer|return
            (lambda m: __import__('open_loops').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # Pillar 1: 'remind me to X' / 'drop it' (internal reminders only)
            (__import__('timeline_adapter').handle_timeline_client, False),   # Universal advisor P2: per-client delivery state (+finance join on 'overall')
            (__import__('timeline_adapter').handle_timeline_risk, False),     # 'what's overdue/stalled' → Timeline drill, verbatim
            (__import__('timeline_adapter').handle_timeline_signals, False),  # complaints/praise from the Timeline signals log
            (__import__('timeline_adapter').handle_timeline_events, False),   # upcoming client events + countdowns
            (__import__('automations').handle_automation_health, False),      # P3: automation-health registry truth
            (__import__('notion_content').handle_content_list, False),        # P4: what emails/lead magnets went out this week
            (__import__('email_pipeline').handle_pipeline_query, False),     # Email engine: what's pending my review / pipeline state
            (capacity_engine.handle_capacity_command, False),  # hiring/capacity/raise/afford questions
            (forecasting_engine.handle_forecast_command, False),  # cash-flow / MRR / runway forecasts
            (__import__('action_feed').handle_action_feed_command, False),  # 'what needs my attention'
            (lambda m: __import__('collab').handle_collab_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # work log / queue / digest
            (__import__('stripe_reconcile').handle_reconciliation_query, False),  # unmatched payments
            (__import__('cash_truth').handle_latest_cash_command, False),   # "last cash collected" → Stripe-actual
            (__import__('cash_truth').handle_needs_logging_command, False), # "what needs logging?"
            (tracker_read.handle_tracker_check, False),    # "check the tracker for X" → verbatim row
            (tracker_read.handle_cash_for, False),         # "cash collected for X" / "why not include"
            (tracker_read.handle_verify_data, False),      # "verify your data" → sync-state summary
            (lambda m: __import__('quarterly_review').handle_quarterly_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # quarterly review / QoQ+YoY / 3x
            (lambda m: __import__('reactivation').handle_reactivation_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # GHL lead reactivation / where-left-off
            (lambda m: __import__('test_leads').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # test-lead exclusion / what's excluded / mark test|real
            (range_unit_economics.handle_unit_econ_command, False),
            (payback_reconciliation.handle_payback_command, False),
            (lambda m: __import__('attribution_queries').handle_scoreboard_command(m), False),  # ad scoreboard (reads the engine)
            (lambda m: __import__('attribution_queries').handle_which_creative_command(m), False),  # which creative brought X
            (lambda m: __import__('attribution_queries').handle_qualified_for_creative_command(m), False),  # qualified per creative
            (leads_view.handle_lead_count_command, False),
            (closes_view.handle_close_count_command, False),
            (leads_view.handle_substage_count_command, False),
            (leads_view.handle_client_count_command, False),
            (liabilities_view.handle_amex_command, False),
            (salary_view.handle_salary_command, True),     # entity-scoped → filter
            (leads_view.handle_leads_command, False),
            (closes_view.handle_closes_command, False),
        ]
        for _h, _entity_scoped in _tier2:
            _r, _handled = _h(user_msg)
            if not _handled:
                continue
            if _entity_scoped and not intent_router.entity_relevant(_r, user_msg, _thread):
                break   # a lookup naming a person he never mentioned → suppress, fall to conversation
            # REPETITION GUARD: a verbatim repeat to a DIFFERENT question is a routing failure, not an
            # answer — suppress it and let the thread-aware/model path answer properly (logged).
            if _repetition_failure(_r, history, user_msg):
                logger.warning("repetition guard: handler %s re-emitted a prior reply for a new msg %r",
                               getattr(_h, "__name__", "lambda"), user_msg[:60])
                break
            # Capacity/raise replies carry salary-derived figures → owner-only, NEVER to memory.
            if _h is not capacity_engine.handle_capacity_command:
                memory.record_turn(conv_id, "assistant", _r, channel=channel, intent="command")
            return jsonify({"reply": _r, "error": None, "intent": "command"})

    recall = memory.build_recall_context(user_msg, conversation_id=conv_id)

    # Ground affordability/salary questions on VERIFIED SALARY-tab figures (deterministic), so the
    # model does its cost/FX math on real numbers instead of memory.
    import salary_view
    _mem_block = recall["block"]
    _sal_ctx = salary_view.salary_context(user_msg)
    if _sal_ctx:
        _mem_block = _sal_ctx + "\n\n" + (_mem_block or "")

    # READ-BEFORE-ASSERT: if the turn asks about a client's tracker field state, read the exact
    # row(s) NOW and hand the model the VERBATIM cells — so it can never infer 'blank' (the incident).
    _trk_ctx = tracker_read.client_context(user_msg)
    if _trk_ctx:
        _mem_block = _trk_ctx + "\n\n" + (_mem_block or "")
    # Universal advisor P4: content-review turns get the piece's VERBATIM Notion copy
    # (read-only integration) so the advisory register critiques the real text.
    import notion_content
    _cc = notion_content.content_context(user_msg)
    if _cc:
        _mem_block = _cc + "\n\n" + (_mem_block or "")
    # Timeline surface: ground Tier-3 conversation in the delivery world (overview
    # digest + entity vocabulary + freshness) so delivery talk is never free-styled.
    if channel == "timeline":
        import timeline_adapter
        _tl_ctx = timeline_adapter.conversation_context()
        if _tl_ctx:
            _mem_block = _tl_ctx + "\n\n" + (_mem_block or "")

    result = chat_fn(history, snapshot_json, token, voice=voice, memory_block=_mem_block, channel=channel)

    reply = result.get("reply")
    if reply:
        memory.record_turn(conv_id, "assistant", reply, channel=channel, intent=result.get("intent"))
        memory.maybe_distill_async(conv_id)
    if recall.get("recalled"):
        result["recalled"] = recall["recalled"]  # transparency: "recalled from <date>"
    return jsonify(result)


@bp.route("/api/chat-stream", methods=["POST"])
@require_auth
def api_chat_stream():
    """Server-Sent Events stream of the reply as it's generated, so the client can
    start TTS on the first sentence (Phase 1). Same brain + intent routing as
    /api/chat; that endpoint stays as the non-streaming fallback.

    Events: `meta` {intent, context_tokens} → many `delta` {text} → `done` {reply}
    or `error` {error}.
    """
    data = request.get_json(silent=True) or {}
    history = data.get("history", [])
    voice = bool(data.get("voice"))
    if not history:
        return jsonify({"error": "Empty message"}), 400
    # Rate/state bucket: the authenticated user, so per-user sessions stop sharing
    # one "anon" bucket (the legacy dash_token cookie no longer exists per-user).
    from dashboard.auth import current_actor
    token = current_actor().get("user") or request.cookies.get(COOKIE_NAME, "anon")
    return chat_stream_response(history, voice,
                                channel=("voice" if voice else "text"), token=token,
                                ui=data.get("ui") or {})


def chat_stream_response(history: list, voice: bool, channel: str, token: str, ui: dict | None = None):
    """The ONE streaming chat core — shared by the dashboard route above and the
    owner-gated Timeline bridge (dashboard/bridge.py). channel scopes the thread
    (db.get_or_create_active_conversation); token scopes rate-limit + pending-state
    buckets. Caller is responsible for auth. Same brain everywhere — never fork."""
    from snapshot import load_persisted
    snap = load_persisted()
    snapshot_json = json.dumps(snap, indent=2) if snap else "{}"

    # Persistent memory: resume/start conversation, persist user turn (async), build recall.
    import memory
    conv_id = memory.start_conversation(channel)
    user_msg = (history[-1].get("content") if history else "") or ""
    # Rebuild the thread from the DB on refresh BEFORE writing the new turn (resume, not restart).
    history = memory.resume_thread(conv_id, history)
    memory.record_turn(conv_id, "user", user_msg, channel=channel)

    def sse(event: str, payload) -> str:
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    # Local commands (short-circuit the model, emit one done event): data-layer
    # resync / sources query first, then manual targets.
    import sheet_mirror, manual_targets
    _cmd_reply = None
    for _h in (sheet_mirror.handle_resync_command, sheet_mirror.handle_sources_query):
        _r, _handled = _h(user_msg)
        if _handled:
            _cmd_reply = _r
            break
    if _cmd_reply is None:
        _r, _handled = manual_targets.handle_turn(user_msg, token)
        if _handled:
            _cmd_reply = _r
    if _cmd_reply is None:
        import email_pipeline as _ep
        _r, _handled = _ep.handle_review_command(user_msg, token)
        if _handled:
            _cmd_reply = _r
    if _cmd_reply is None:
        import client_overrides
        for _cb in (lambda m: client_overrides.handle_client_writeback_command(m, token),
                    lambda m: client_overrides.handle_undo_command(m, token),
                    client_overrides.handle_pending_updates_query,
                    client_overrides.handle_client_changes_query):
            _r, _handled = _cb(user_msg)
            if _handled:
                _cmd_reply = _r
                break
    if _cmd_reply is None:
        import location, salience
        for _lh in (location.handle_location_command, salience.handle_whats_new):
            _r, _handled = _lh(user_msg)
            if _handled:
                _cmd_reply = _r
                break
    if _cmd_reply is None:
        # Self-check challenge loop + incident handoff (voice path), before the ramble gate.
        import tracker_read, incident_log
        _thread6 = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        import stripe_reconcile
        for _sh in (lambda m: tracker_read.handle_self_check(m, _thread6),
                    incident_log.handle_incident_query,
                    stripe_reconcile.handle_alias_confirm):
            _r, _handled = _sh(user_msg)
            if _handled:
                _cmd_reply = _r
                break
    # ── TIER 2 (voice path): GATED — a conversational ramble skips the data handlers → model.
    # This is the surface the Romano misfire happened on. Default-to-conversation when unsure.
    import intent_router
    # ── VOICE-DRIVEN NAVIGATION (deterministic, FIRST): "show me X" is a navigation
    # command — it must NEVER fall through to the model, whose emergent "text and
    # voice only" line caused the 2026-08-05 incident. Timeline channel gets the
    # honest cross-surface answer (no actions) until Part 2 adopts the handler.
    _cmd_actions: list = []
    if _cmd_reply is None:
        try:
            import nav_router
            _nr, _na, _nh = nav_router.handle(user_msg, ui=ui, channel=channel)
            if _nh:
                _cmd_reply, _cmd_actions = _nr, (_na or [])
        except Exception as _e:
            logger.warning("nav router failed (falling through): %s", _e)
    if _cmd_reply is None and not intent_router.is_conversational_ramble(user_msg):
        import range_unit_economics, payback_reconciliation, leads_view, closes_view, liabilities_view, salary_view
        import tracker_read, capacity_engine, forecasting_engine
        _thread = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        _tier2 = [
            (lambda m: __import__('conversation').handle(m, history), False),  # ADVISORY + ANAPHORA/scenario — FIRST so follow-ups ('5 more closes') aren't grabbed by forecast/recital
            (lambda m: __import__('capital_allocation').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # capital allocation: deploy / opportunity-cost / review / set buffer|return
            (lambda m: __import__('open_loops').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # Pillar 1: 'remind me to X' / 'drop it' (internal reminders only)
            (__import__('timeline_adapter').handle_timeline_client, False),   # Universal advisor P2: per-client delivery state (+finance join on 'overall')
            (__import__('timeline_adapter').handle_timeline_risk, False),     # 'what's overdue/stalled' → Timeline drill, verbatim
            (__import__('timeline_adapter').handle_timeline_signals, False),  # complaints/praise from the Timeline signals log
            (__import__('timeline_adapter').handle_timeline_events, False),   # upcoming client events + countdowns
            (__import__('automations').handle_automation_health, False),      # P3: automation-health registry truth
            (__import__('notion_content').handle_content_list, False),        # P4: what emails/lead magnets went out this week
            (__import__('email_pipeline').handle_pipeline_query, False),     # Email engine: what's pending my review / pipeline state
            (capacity_engine.handle_capacity_command, False),
            (forecasting_engine.handle_forecast_command, False),
            (__import__('action_feed').handle_action_feed_command, False),
            (lambda m: __import__('collab').handle_collab_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),
            (__import__('stripe_reconcile').handle_reconciliation_query, False),
            (__import__('cash_truth').handle_latest_cash_command, False),   # "last cash collected" → Stripe-actual
            (__import__('cash_truth').handle_needs_logging_command, False), # "what needs logging?"
            (tracker_read.handle_tracker_check, False),
            (tracker_read.handle_cash_for, False),
            (tracker_read.handle_verify_data, False),
            (lambda m: __import__('quarterly_review').handle_quarterly_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # quarterly review / QoQ+YoY / 3x
            (lambda m: __import__('reactivation').handle_reactivation_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # GHL lead reactivation / where-left-off
            (lambda m: __import__('test_leads').handle_command(m, __import__('dashboard.auth', fromlist=['current_actor']).current_actor()), False),  # test-lead exclusion / what's excluded / mark test|real
            (range_unit_economics.handle_unit_econ_command, False),
            (payback_reconciliation.handle_payback_command, False),
            (lambda m: __import__('attribution_queries').handle_scoreboard_command(m), False),  # ad scoreboard (reads the engine)
            (lambda m: __import__('attribution_queries').handle_which_creative_command(m), False),  # which creative brought X
            (lambda m: __import__('attribution_queries').handle_qualified_for_creative_command(m), False),  # qualified per creative
            (leads_view.handle_lead_count_command, False),
            (closes_view.handle_close_count_command, False),
            (leads_view.handle_substage_count_command, False),
            (leads_view.handle_client_count_command, False),
            (liabilities_view.handle_amex_command, False),
            (salary_view.handle_salary_command, True),      # entity-scoped → filter (Romano rule)
            (leads_view.handle_leads_command, False),
            (closes_view.handle_closes_command, False),
        ]
        for _h, _entity_scoped in _tier2:
            _r, _handled = _h(user_msg)
            if not _handled:
                continue
            if _entity_scoped and not intent_router.entity_relevant(_r, user_msg, _thread):
                break   # suppress a salary lookup about someone he never mentioned → conversation
            if _repetition_failure(_r, history, user_msg):
                logger.warning("repetition guard (stream): re-emit suppressed for %r", user_msg[:60])
                break
            _cmd_reply = _r
            _cmd_sensitive = (_h is capacity_engine.handle_capacity_command)
            break
    if _cmd_reply is not None:
        if not locals().get("_cmd_sensitive"):   # capacity/raise salary figures never enter memory
            memory.record_turn(conv_id, "assistant", _cmd_reply, channel=channel, intent="command")
        def gen_cmd():
            yield sse("meta", {"intent": "command", "context_tokens": 0})
            for _a in (_cmd_actions or []):
                yield sse("nav", _a)          # schema v1 — unknown events are ignored
            yield sse("done", {"reply": _cmd_reply})
        return Response(gen_cmd(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    recall = memory.build_recall_context(user_msg, conversation_id=conv_id)
    # Ground affordability/salary questions on VERIFIED SALARY-tab figures (deterministic).
    import salary_view, tracker_read
    _mem_block = recall["block"]
    _sal_ctx = salary_view.salary_context(user_msg)
    if _sal_ctx:
        _mem_block = _sal_ctx + "\n\n" + (_mem_block or "")
    # READ-BEFORE-ASSERT (voice path): inject verbatim tracker row(s) for client field-state questions.
    _trk_ctx = tracker_read.client_context(user_msg)
    if _trk_ctx:
        _mem_block = _trk_ctx + "\n\n" + (_mem_block or "")
    # Universal advisor P4: content-review turns get the piece's VERBATIM Notion copy
    # (read-only integration) so the advisory register critiques the real text.
    import notion_content
    _cc = notion_content.content_context(user_msg)
    if _cc:
        _mem_block = _cc + "\n\n" + (_mem_block or "")
    # Timeline surface: ground Tier-3 conversation in the delivery world (overview
    # digest + entity vocabulary + freshness) so delivery talk is never free-styled.
    if channel == "timeline":
        import timeline_adapter
        _tl_ctx = timeline_adapter.conversation_context()
        if _tl_ctx:
            _mem_block = _tl_ctx + "\n\n" + (_mem_block or "")

    @stream_with_context
    def generate():
        final_reply = ""
        try:
            for event_type, payload in chat_stream_fn(history, snapshot_json, token,
                                                      voice=voice, memory_block=_mem_block,
                                                      channel=channel):
                if event_type == "delta":
                    yield sse("delta", {"text": payload})
                elif event_type == "meta":
                    yield sse("meta", payload)
                elif event_type == "done":
                    final_reply = payload
                    yield sse("done", {"reply": payload})
                elif event_type == "error":
                    yield sse("error", {"error": payload})
        except Exception as e:  # never let a stream crash leak a 500 mid-SSE
            logger.error("chat-stream generator error: %s", e)
            yield sse("error", {"error": "stream interrupted"})
        finally:
            # Persist the assistant turn once the stream completes (async) + distil.
            if final_reply:
                memory.record_turn(conv_id, "assistant", final_reply, channel=channel)
                memory.maybe_distill_async(conv_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",   # disable proxy buffering so chunks flush live
            "Connection": "keep-alive",
        },
    )


# ── Manual targets / benchmarks / goalposts (Rydel-set, auth-gated) ──────────

@bp.route("/targets", methods=["GET"])
@require_auth
def targets_page():
    """Settings panel to view/edit/reset the manual targets + see change history."""
    return render_template("targets.html")


@bp.route("/api/targets", methods=["GET"])
@require_auth
def api_targets():
    """Current manual targets/benchmarks + recent change history (settings panel)."""
    import manual_targets
    return jsonify({"targets": manual_targets.get_all(), "history": manual_targets.history()})


@bp.route("/api/targets/set", methods=["POST"])
@require_auth
def api_targets_set():
    """Direct set from the settings panel (no confirmation — explicit UI action)."""
    import manual_targets
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    value = data.get("value")
    if key not in manual_targets.DEFAULTS:
        return jsonify({"error": f"Unknown target '{key}'"}), 400
    try:
        rec = manual_targets.set_value(key, float(value))
    except (TypeError, ValueError):
        return jsonify({"error": "value must be numeric"}), 400
    return jsonify({"ok": True, "target": rec})


@bp.route("/api/targets/reset", methods=["POST"])
@require_auth
def api_targets_reset():
    """Reset a target to its documented default."""
    import manual_targets
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    if key not in manual_targets.DEFAULTS:
        return jsonify({"error": f"Unknown target '{key}'"}), 400
    return jsonify({"ok": True, "target": manual_targets.reset_value(key)})


# ── Sheet mirror: data-sources panel + immediate resync (auth-gated) ──────────

@bp.route("/data-sources", methods=["GET"])
@require_auth
def data_sources_page():
    """Transparency panel — what's plugged into EDITH + per-tab freshness."""
    return render_template("data_sources.html")


@bp.route("/api/data-sources", methods=["GET"])
@require_auth
def api_data_sources():
    import sheet_mirror
    payload = {"sources": sheet_mirror.get_sources(),
               "interval_seconds": __import__("config").SHEET_SYNC_INTERVAL_SECONDS}
    try:
        import ghl_mirror
        payload["ghl_sources"] = ghl_mirror.get_sources()
        payload["ghl_counts"] = ghl_mirror.counts()
    except Exception as e:
        logger.info("ghl sources unavailable: %s", e)
    return jsonify(payload)


@bp.route("/api/ghl-backfill", methods=["POST"])
@require_auth
def api_ghl_backfill():
    """One resumable backfill chunk (opps + up to ?cap contacts/notes). Call until remaining==0."""
    import ghl_mirror
    if not ghl_mirror.enabled():
        return jsonify({"ok": False, "error": "GHL mirror not configured"}), 503
    cap = request.args.get("cap", 150, type=int)
    res = ghl_mirror.backfill_chunk(cap=cap)
    return jsonify({"ok": True, **res})


@bp.route("/api/reactivation", methods=["GET"])
@require_auth
def api_reactivation():
    """Deterministic reactivation intelligence: ranked leads + totals + notes-hygiene + reconciliation.
    ?bucket=stale|pitched_stalled  ?min_value=  ?limit=  (PII-bearing → auth-gated only)."""
    import reactivation
    leads = reactivation.classify()
    bucket = request.args.get("bucket")
    min_value = request.args.get("min_value", 0.0, type=float)
    limit = request.args.get("limit", type=int)
    resp = jsonify({
        "list": reactivation.reactivation_list(bucket=bucket, min_value=min_value, limit=limit, leads=leads),
        "totals": reactivation.summary_totals(leads),
        "notes_hygiene": reactivation.notes_hygiene(leads),
        "reconciliation": reactivation.reconciliation(leads),
    })
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _audit_pii_export(kind: str, n: int):
    """Log a deliberate PII-bearing export (contact names/emails/phones) to the forever archive."""
    try:
        import collab
        from dashboard.auth import current_actor
        a = current_actor()
        collab.record_action(a, f"exported the reactivation {kind} ({n} leads, contains contact PII)",
                             link_type="reactivation_export", link_ref=kind)
    except Exception as e:
        logger.info("reactivation export audit failed: %s", e)


@bp.route("/api/capital", methods=["GET"])
@require_auth
def api_capital():
    """The full capital-allocation state — cash, wall, surplus, the idle-cash bleed, buckets, the
    open review + unassigned, and review history. Owner-visible (Piolo has full visibility too)."""
    import capital_allocation
    state = capital_allocation.compute_state()
    state["history"] = capital_allocation.review_history()
    resp = jsonify(state)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/capital/settings", methods=["POST"])
@require_auth
def api_capital_settings():
    """Set the wall / assumed return / cadence. (UI already confirms; voice uses the confirm loop.)"""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    results = {}
    # A field PRESENT in the payload is applied — including an explicit null to CLEAR it (so an
    # assumption can be un-set, never leaving a value I chose). Absent fields are left untouched.
    for field in ("survival_buffer_aud", "assumed_annual_return_pct", "review_cadence"):
        if field in d:
            results[field] = capital_allocation.set_setting(field, d[field])
    return jsonify({"ok": True, "results": results, "state": capital_allocation.compute_state()})


@bp.route("/api/capital/review", methods=["POST"])
@require_auth
def api_capital_review():
    """Review actions: {action: 'run'|'assign'|'commit', ...}."""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    if action == "run":
        return jsonify(capital_allocation.run_review())
    if action == "assign":
        return jsonify(capital_allocation.set_line(d.get("review_id"), d.get("bucket_id"),
                                                   d.get("assigned_aud"), d.get("note")))
    if action == "commit":
        return jsonify(capital_allocation.commit_review(d.get("review_id")))
    if action == "discard":
        return jsonify(capital_allocation.discard_review(d.get("review_id")))
    return jsonify({"ok": False, "error": "unknown action"}), 400


@bp.route("/api/capital/reset", methods=["POST"])
@require_owner
def api_capital_reset():
    """Start over — clear reviews/deployments (+ optionally the buffer/return). Buckets preserved."""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    return jsonify(capital_allocation.reset_all(clear_settings=d.get("clear_settings", True)))


@bp.route("/api/capital/deploy", methods=["POST"])
@require_auth
def api_capital_deploy():
    """Log a deployment — idle_surplus shrinks, the bleed tile drops (the reward loop)."""
    import capital_allocation
    d = request.get_json(silent=True) or {}
    if not d.get("bucket_id") or d.get("amount_aud") is None:
        return jsonify({"ok": False, "error": "bucket_id and amount_aud required"}), 400
    return jsonify(capital_allocation.mark_deployed(d["bucket_id"], d["amount_aud"],
                                                    d.get("note"), d.get("review_id")))


@bp.route("/api/test-lead-scan", methods=["GET"])
@require_auth
def api_test_lead_scan():
    """The excluded-entries AUDIT VIEW: classify both mirrors → the voided list + borderline (owner +
    Piolo). Raw lead access lives ONLY here + the classifier; metrics read the clean view."""
    import test_leads
    return jsonify(test_leads.scan())


@bp.route("/api/test-leads/override", methods=["POST"])
@require_auth
def api_test_lead_override():
    """Manual mark test/real (owner + Piolo). Persisted, audited, REMEMBERED — outranks rules and
    survives re-syncs."""
    import test_leads
    from dashboard.auth import current_actor
    d = request.get_json(silent=True) or {}
    key = d.get("key")
    if not key:
        return jsonify({"ok": False, "error": "key required"}), 400
    actor = current_actor()
    test_leads.set_override(key, bool(d.get("is_test")), actor.get("user"))
    try:
        import collab
        collab.record_action(actor, f"marked a lead {'TEST' if d.get('is_test') else 'REAL'} ({key})",
                             link_type="test_lead_override", link_ref=key)
    except Exception:
        pass
    return jsonify({"ok": True, "key": key, "is_test": bool(d.get("is_test"))})


@bp.route("/api/test-leads/confirm", methods=["POST"])
@require_owner
def api_test_lead_confirm():
    """Owner confirms the first classification pass (enables the repoints) + persists the token rules."""
    import test_leads
    d = request.get_json(silent=True) or {}
    if d.get("rules"):
        test_leads.set_rules(d["rules"])
    test_leads.confirm_first_pass(by="rydel")
    # One-time data-cleaning note in the forever archive (future-you will ask why counts changed).
    try:
        import collab
        collab.add_entry("rydel", "done",
                         f"Data cleaning {today_sydney()}: test leads voided from all sales metrics "
                         "(staff/test-shaped matches; excluded not deleted). Rules: rydel/jaspher/test. "
                         "See the test-lead audit view (/api/test-lead-scan).",
                         link_type="data_cleaning", link_ref=str(today_sydney()))
    except Exception as e:
        logger.info("data-cleaning journal note skipped: %s", e)
    return jsonify({"ok": True, "confirmed": True, "rules": test_leads.rules()})


@bp.route("/leads", methods=["GET"])
@require_auth
def sales_page():
    """The scoped Lead Reactivation view — the sales team's home. Owner/COO can view it too, but a
    sales session is confined to it (fail-closed scoping in require_auth). No financial data here."""
    return render_template("sales.html", asset_v=_ASSET_VERSION)


@bp.route("/api/lead-lookup", methods=["GET"])
@require_auth
def api_lead_lookup():
    """'Where did we leave off with X' for the sales view: grounded summary + contact for one lead.
    ?name= or ?contact_id=. Sales-scope-allowed. PII-bearing (auth-gated)."""
    import reactivation
    res = reactivation.lookup_lead(name=request.args.get("name"),
                                   contact_id=request.args.get("contact_id"))
    resp = jsonify(res)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/reactivation/export.csv", methods=["GET"])
@require_auth
def api_reactivation_csv():
    """CSV of the ranked reactivation list (full fields for GHL smart-lists). Contains contact PII —
    deliberate, auth-gated, audit-logged."""
    import reactivation, reactivation_export
    leads = reactivation.reactivation_list(min_value=request.args.get("min_value", 0.0, type=float),
                                           limit=request.args.get("limit", type=int))
    cap = request.args.get("cap", 200, type=int)
    csv_text = reactivation_export.build_csv(leads, cap=cap)
    _audit_pii_export("CSV", min(len(leads), cap))
    resp = make_response(csv_text)
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f"attachment; filename=reactivation-{today_sydney()}.csv"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/reactivation/brief.pdf", methods=["GET"])
@require_auth
def api_reactivation_brief():
    """Formatted reactivation brief PDF (top-N ranked with grounded summaries + angles). Contact PII —
    deliberate, auth-gated, audit-logged."""
    import reactivation, reactivation_export
    from helpers import today_sydney
    top_n = request.args.get("top_n", 40, type=int)
    leads = reactivation.reactivation_list()
    try:
        pdf = reactivation_export.build_brief_pdf(leads, top_n=top_n)
    except Exception as e:
        logger.exception("reactivation brief failed")
        return jsonify({"error": str(e)}), 500
    _audit_pii_export("brief PDF", min(len(leads), top_n))
    resp = make_response(bytes(pdf))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename=reactivation-brief-{today_sydney()}.pdf"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/resync", methods=["POST"])
@require_auth
def api_resync():
    """Force an immediate sync of all mirrored tabs, then rebuild the snapshot."""
    import sheet_mirror
    res = sheet_mirror.sync_all()
    try:
        from snapshot import build_snapshot
        snap = build_snapshot()
        import app as app_module
        app_module._current_snapshot = snap
        res["snapshot_generated_at"] = snap.get("generated_at")
    except Exception as e:
        logger.error("resync snapshot rebuild failed: %s", e)
        res["snapshot_error"] = str(e)[:160]
    resp = jsonify({"ok": True, "sync": res})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/unit-economics", methods=["GET"])
@require_auth
def api_unit_economics():
    """Range-aware LTGP:CAC / ROAS / LTV:CAC, window-consistent. ?start=&end= (ISO) or ?days=N.

    The dashboard window buttons and EDITH's spoken answers route through this same engine,
    so they never drift for the same window.
    """
    import range_unit_economics
    from helpers import today_sydney
    start = request.args.get("start")
    end = request.args.get("end")
    if not (start and end):
        from datetime import timedelta
        days = request.args.get("days", 30, type=int)
        today = today_sydney()
        start, end = str(today - timedelta(days=days - 1)), str(today)
    res = range_unit_economics.unit_economics(start, end)
    resp = jsonify(res)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/payback", methods=["GET"])
@require_auth
def api_payback():
    """True payback per deal / per offer via Stripe payment reconciliation. ?start=&end= or ?days=N
    (default last 90d). Read-only Stripe; PII-safe (no emails in output)."""
    import payback_reconciliation
    from helpers import today_sydney
    start = request.args.get("start")
    end = request.args.get("end")
    if not (start and end):
        from datetime import timedelta
        days = request.args.get("days", 90, type=int)
        today = today_sydney()
        start, end = str(today - timedelta(days=days - 1)), str(today)
    res = payback_reconciliation.compute_payback(start, end)
    resp = jsonify(res)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/leads", methods=["GET"])
@require_auth
def api_leads():
    """Most recently entered leads from the mirrored tracker. ?limit=N (default 10). PII-safe
    (no email/phone in output)."""
    import leads_view
    limit = request.args.get("limit", 10, type=int)
    resp = jsonify(leads_view.recent_leads(limit=limit))
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _resolve_quarter_args():
    """?year=&q= (calendar) or default to the last completed calendar quarter."""
    import quarterly_pack as qp
    year = request.args.get("year", type=int)
    q = request.args.get("q", type=int)
    if not (year and q in (1, 2, 3, 4)):
        year, q = qp.last_completed_quarter()
    assumptions = {}
    for k, caster in (("multiple", float), ("close_rate_target", float),
                      ("ltgp_cac_floor", float), ("clients_per_delivery_hire", int)):
        v = request.args.get(k, type=caster)
        if v is not None:
            assumptions[k] = v
    return year, q, (assumptions or None)


@bp.route("/api/quarterly-pack", methods=["GET"])
@require_auth
def api_quarterly_pack():
    """The full quarterly review as JSON (packs + QoQ/YoY comparisons + the 3x model). Both roles
    may read. ?year=&q= or default last completed quarter; 3x knobs via ?multiple=&close_rate_target=.
    This is the same object the PDF renders from, so chat answers never drift from the document."""
    import quarterly_review
    year, q, assumptions = _resolve_quarter_args()
    try:
        review = quarterly_review.build_review(year, q, assumptions)
    except Exception as e:
        logger.exception("quarterly pack failed")
        return jsonify({"error": str(e)}), 500
    resp = jsonify(review)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/quarterly-review", methods=["GET"])
@require_auth
def api_quarterly_review():
    """Generate the branded Quarterly Review PDF (both roles may generate — Rydel's full-visibility
    call). Every $-figure is verbatim from the pack (validated; generation fails loudly otherwise).
    The PDF is dated into the forever archive, and the generation is flagged to Rydel (if Piolo runs
    it, it surfaces in the owner digest via collab.record_action). ?year=&q= or default last Q."""
    import quarterly_review
    from dashboard.quarterly_pdf import generate_quarterly_pdf
    from dashboard.auth import current_actor
    from helpers import today_sydney
    year, q, assumptions = _resolve_quarter_args()
    try:
        review = quarterly_review.build_review(year, q, assumptions)
        pdf_bytes = generate_quarterly_pdf(review)
    except ValueError as e:
        # verbatim-number guard tripped — refuse to emit a document with an untraceable figure
        logger.error("Quarterly PDF verbatim check failed: %s", e)
        return jsonify({"error": "verbatim-number check failed — refusing to emit", "detail": str(e)}), 500
    except Exception as e:
        logger.exception("Quarterly PDF generation failed")
        return jsonify({"error": str(e)}), 500

    label = review.get("quarter", {}).get("label", f"Q{q} {year}")
    actor = current_actor()
    # Forever archive: dated record + the PDF file on disk (survives DB loss; joins the export).
    filename = f"served-cfo-quarterly-{label.replace(' ', '-')}-{today_sydney()}.pdf"
    try:
        import collab, os as _os
        arch_dir = _os.path.join(_os.path.dirname(__file__), "archive_exports")
        _os.makedirs(arch_dir, exist_ok=True)
        with open(_os.path.join(arch_dir, filename), "wb") as fh:
            fh.write(pdf_bytes)
        collab.add_entry(actor.get("user", "rydel"), "done",
                         f"Quarterly Review generated: {label} ({filename})",
                         link_type="quarterly_pdf", link_ref=label)
        collab.record_action(actor, f"generated the Quarterly Review PDF for {label}",
                             link_type="quarterly_pdf", link_ref=label)
    except Exception as e:
        logger.info("Quarterly PDF archive step non-fatal error: %s", e)

    resp = make_response(bytes(pdf_bytes))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["Content-Length"] = str(len(pdf_bytes))
    resp.headers["Cache-Control"] = "no-store"
    return resp
