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

from dashboard.auth import require_auth, DASHBOARD_TOKEN, COOKIE_NAME, COOKIE_MAX_AGE
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
    import time as _t
    import kv_store
    from snapshot import load_persisted
    from dashboard.voice import build_greeting
    snap = load_persisted() or {}
    _IDLE = 25 * 60
    last = kv_store.get("greeting:last_delivered") or {}
    force = (request.args.get("fresh") == "1")
    if not force and last.get("ts") and (_t.time() - last["ts"]) < _IDLE and last.get("payload"):
        return jsonify({**last["payload"], "regreet": False})
    payload = build_greeting(snap, mark=True)   # composes, watermarks, remembers shape
    kv_store.put("greeting:last_delivered", {"ts": _t.time(), "payload": payload})
    return jsonify({**payload, "regreet": True})


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

    token = request.cookies.get(COOKIE_NAME, "anon")
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

    # ── TIER 2: deterministic DATA handlers — GATED. A conversational ramble (long, declarative,
    # no data-request structure) SKIPS these entirely and falls through to the model (TIER 3).
    # Default-to-conversation: when unsure, a generic reply beats a jarring data non-sequitur.
    import intent_router, range_unit_economics, payback_reconciliation
    import leads_view, closes_view, liabilities_view, salary_view
    if not intent_router.is_conversational_ramble(user_msg):
        _thread = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        # (handler, entity_scoped?) — entity_scoped lookups are entity-filtered (the Romano rule);
        # superlative/recency lookups (latest lead, biggest deal) surface entities by design → exempt.
        _tier2 = [
            (range_unit_economics.handle_unit_econ_command, False),
            (payback_reconciliation.handle_payback_command, False),
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

    result = chat_fn(history, snapshot_json, token, voice=voice, memory_block=_mem_block)

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

    from snapshot import load_persisted
    snap = load_persisted()
    snapshot_json = json.dumps(snap, indent=2) if snap else "{}"
    token = request.cookies.get(COOKIE_NAME, "anon")

    # Persistent memory: resume/start conversation, persist user turn (async), build recall.
    import memory
    channel = "voice" if voice else "text"
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
    # ── TIER 2 (voice path): GATED — a conversational ramble skips the data handlers → model.
    # This is the surface the Romano misfire happened on. Default-to-conversation when unsure.
    import intent_router
    if _cmd_reply is None and not intent_router.is_conversational_ramble(user_msg):
        import range_unit_economics, payback_reconciliation, leads_view, closes_view, liabilities_view, salary_view
        _thread = " ".join((m.get("content") or "") for m in (history or [])[-6:])
        _tier2 = [
            (range_unit_economics.handle_unit_econ_command, False),
            (payback_reconciliation.handle_payback_command, False),
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
            _cmd_reply = _r
            break
    if _cmd_reply is not None:
        memory.record_turn(conv_id, "assistant", _cmd_reply, channel=channel, intent="command")
        def gen_cmd():
            yield sse("meta", {"intent": "command", "context_tokens": 0})
            yield sse("done", {"reply": _cmd_reply})
        return Response(gen_cmd(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    recall = memory.build_recall_context(user_msg, conversation_id=conv_id)
    # Ground affordability/salary questions on VERIFIED SALARY-tab figures (deterministic).
    import salary_view
    _mem_block = recall["block"]
    _sal_ctx = salary_view.salary_context(user_msg)
    if _sal_ctx:
        _mem_block = _sal_ctx + "\n\n" + (_mem_block or "")

    @stream_with_context
    def generate():
        final_reply = ""
        try:
            for event_type, payload in chat_stream_fn(history, snapshot_json, token,
                                                      voice=voice, memory_block=_mem_block):
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
    return jsonify({"sources": sheet_mirror.get_sources(),
                    "interval_seconds": __import__("config").SHEET_SYNC_INTERVAL_SECONDS})


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
