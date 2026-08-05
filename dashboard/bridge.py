"""
bridge.py — the owner-gated Timeline↔EDITH bridge (LAYER 2 of the double gate).

The Timeline Dashboard (separate service) renders a voice widget for Rydel only and
proxies its requests here, minting a SHORT-LIVED HMAC token per outbound request
(60s TTL, shared secret EDITH_BRIDGE_SECRET set on both Railway services, never in
any browser). This module independently validates that token on EVERY request —
client-side hiding on the Timeline is presentation, THIS is the security boundary.

Token format:  v1:<expiry_epoch>:<user>:<purpose> . base64url(HMAC-SHA256(secret, payload))
Validation:    constant-time signature check, hard expiry, purpose == "timeline",
               user ∈ EDITH_BRIDGE_OWNERS (default: rydel). Anything else → 403.
Replay:        tokens are single-use per worker process (best-effort in-process
               nonce cache; the hard 60s expiry is the cross-worker backstop —
               tokens only ever travel server-to-server over TLS).

ONE BRAIN: every endpoint here delegates to the SAME cores the CFO dashboard uses
(chat_stream_response / tts_response / greeting_response in dashboard/routes.py)
with channel="timeline" — separate conversation thread, shared memory/watermarks.
Fail-closed: no EDITH_BRIDGE_SECRET configured → every request 403s.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from functools import wraps

from flask import Blueprint, g, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("bridge", __name__)

_PURPOSE = "timeline"
_MAX_SKEW_TTL = 120          # reject tokens claiming to live longer than this (mint bug guard)
_seen_sigs: dict[str, float] = {}   # sig -> expiry (in-process single-use cache)


def _secret() -> bytes:
    return (os.environ.get("EDITH_BRIDGE_SECRET") or "").encode()


def _owners() -> set[str]:
    raw = os.environ.get("EDITH_BRIDGE_OWNERS", "rydel")
    return {u.strip() for u in raw.split(",") if u.strip()}


def _media_buyers() -> set[str]:
    """MEDIA_BUYER role (attribution Phase 4 design — SHIPS DISABLED). Empty until Rydel
    sets EDITH_BRIDGE_MEDIA_BUYERS (e.g. "romano"). A media_buyer token is valid ONLY on
    routes that opt in via require_bridge_any_role — every owner route 403s it."""
    raw = os.environ.get("EDITH_BRIDGE_MEDIA_BUYERS", "")
    return {u.strip() for u in raw.split(",") if u.strip()}


def validate_bridge_token(raw: str) -> str | None:
    """Return the authenticated owner username, or None. Never raises."""
    secret = _secret()
    if not secret or not raw or "." not in raw:
        return None
    payload, _, sig = raw.rpartition(".")
    want = base64.urlsafe_b64encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    if not hmac.compare_digest(sig, want):
        return None
    parts = payload.split(":")
    if len(parts) != 4 or parts[0] != "v1":
        return None
    _, expiry_s, user, purpose = parts
    try:
        # float (µs precision): tokens minted in the same second must still be
        # unique, or back-to-back requests trip the single-use replay guard
        expiry = float(expiry_s)
    except ValueError:
        return None
    now = time.time()
    if now >= expiry or expiry - now > _MAX_SKEW_TTL:
        return None
    if purpose != _PURPOSE or (user not in _owners() and user not in _media_buyers()):
        return None
    # best-effort single-use (per worker): a replayed signature is refused
    for s, exp in list(_seen_sigs.items()):
        if exp < now:
            _seen_sigs.pop(s, None)
    if sig in _seen_sigs:
        logger.warning("bridge: replayed token refused (user=%s)", user)
        return None
    _seen_sigs[sig] = expiry
    return user


def _resolve_role(user: str) -> str | None:
    if user in _owners():
        return "owner"
    if user in _media_buyers():
        return "media_buyer"
    return None


def require_bridge(f):
    """OWNER-ONLY gate — every pre-existing route keeps exactly this bar. A media_buyer
    token validates cryptographically but is refused here (server-side 403, the
    sales-role pattern): the role reaches ONLY routes wearing require_bridge_any_role."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = validate_bridge_token(request.headers.get("X-Bridge-Token", ""))
        if not user or _resolve_role(user) != "owner":
            return jsonify({"error": "forbidden"}), 403
        # downstream tier handlers attribute via dashboard.auth.current_actor()
        g.actor = {"user": user, "role": "owner", "display": "Rydel"}
        return f(*args, **kwargs)
    return wrapper


def require_bridge_any_role(f):
    """Owner OR media_buyer (attribution surface only). g.actor carries the real role so
    handlers can scope further. media_buyer stays inert until EDITH_BRIDGE_MEDIA_BUYERS
    is set — shipping disabled by default."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = validate_bridge_token(request.headers.get("X-Bridge-Token", ""))
        role = _resolve_role(user) if user else None
        if not role:
            return jsonify({"error": "forbidden"}), 403
        g.actor = {"user": user, "role": role,
                   "display": "Rydel" if role == "owner" else user.title()}
        return f(*args, **kwargs)
    return wrapper


@bp.route("/ping", methods=["GET"])
@require_bridge
def bridge_ping():
    return jsonify({"ok": True, "user": g.actor["user"], "surface": _PURPOSE})


@bp.route("/chat-stream", methods=["POST"])
@require_bridge
def bridge_chat_stream():
    """Same SSE contract as /dashboard/api/chat-stream, channel='timeline'."""
    from dashboard.routes import chat_stream_response
    data = request.get_json(silent=True) or {}
    history = data.get("history", [])
    voice = bool(data.get("voice"))
    if not history:
        return jsonify({"error": "Empty message"}), 400
    # STT diagnosability: log the raw transcript per turn so "she misheard" reports
    # can be traced to what the browser actually transcribed.
    logger.info("timeline transcript (voice=%s): %.200s", voice,
                (history[-1].get("content") or "").replace("\n", " "))
    return chat_stream_response(history, voice, channel=_PURPOSE,
                                token="%s:%s" % (_PURPOSE, g.actor["user"]))


@bp.route("/tts", methods=["GET", "POST"])
@require_bridge
def bridge_tts():
    from dashboard.routes import tts_response
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        text, voice_id = data.get("text", ""), data.get("voice_id")
    else:
        text, voice_id = request.args.get("text", ""), request.args.get("voice_id")
    return tts_response(text, voice_id)


@bp.route("/greeting", methods=["GET"])
@require_bridge
def bridge_greeting():
    from dashboard.routes import greeting_response
    return greeting_response(force=(request.args.get("fresh") == "1"))


# ── EMAIL ENGINE (Phase A: drafts + review — zero outbound; owner-token gated) ─
@bp.route("/email/list", methods=["GET"])
@require_bridge
def bridge_email_list():
    import email_pipeline as EP
    d = EP.pipeline_digest()
    return jsonify({"digest": d, "drafts": _json_safe(EP.list_drafts())})


@bp.route("/email/draft/<int:draft_id>", methods=["GET"])
@require_bridge
def bridge_email_draft(draft_id):
    import email_pipeline as EP
    row = EP.get_draft(draft_id)
    return (jsonify(_json_safe(row)), 200) if row else (jsonify({"error": "not found"}), 404)


@bp.route("/email/generate", methods=["POST"])
@require_bridge
def bridge_email_generate():
    import email_pipeline as EP
    data = request.get_json(silent=True) or {}
    return jsonify(EP.generate_draft((data.get("type") or "weekly").strip(),
                                     note=data.get("note") or "", actor=g.actor["user"]))


@bp.route("/email/act", methods=["POST"])
@require_bridge
def bridge_email_act():
    import email_pipeline as EP
    data = request.get_json(silent=True) or {}
    return jsonify(EP.act(int(data.get("id") or 0), (data.get("action") or "").strip(),
                          note=data.get("note") or "", actor=g.actor["user"]))


def _json_safe(x):
    import datetime as _d
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_json_safe(v) for v in x]
    if isinstance(x, (_d.datetime, _d.date)):
        return x.isoformat()
    return x


@bp.route("/email/ingest", methods=["POST"])
@require_bridge
def bridge_email_ingest():
    """Both sweeps: the Email Library (content-linked) and the PD Email Review DB (winback)."""
    import email_pipeline as EP
    return jsonify(_json_safe({"library": EP.ingest_from_library(actor=g.actor["user"]),
                               "pd": EP.ingest_from_pd(actor=g.actor["user"])}))


@bp.route("/email/stage", methods=["POST"])
@require_bridge
def bridge_email_stage():
    import email_pipeline as EP
    data = request.get_json(silent=True) or {}
    return jsonify(_json_safe(EP.stage_draft(int(data.get("id") or 0), actor=g.actor["user"])))


@bp.route("/email/recipients/<int:draft_id>", methods=["GET"])
@require_bridge
def bridge_email_recipients(draft_id):
    import email_pipeline as EP
    return jsonify(_json_safe(EP.recipients_view(draft_id)))


@bp.route("/email/send", methods=["POST"])
@require_bridge
def bridge_email_send():
    """Owner send chain steps 2-5: mint on confirm, execute, read back, audit.
    Two-step: {'id','count'} → returns a chain token + the echo line;
    {'id','count','chain_token','confirm':true} → executes."""
    import email_pipeline as EP
    d = request.get_json(silent=True) or {}
    draft_id = int(d.get("id") or 0)
    count = int(d["count"]) if str(d.get("count", "")).lstrip("-").isdigit() else -1
    if not d.get("confirm"):
        rec = EP.recipients_view(draft_id)
        if not rec.get("ok"):
            return jsonify(rec)
        row = EP.get_draft(draft_id)
        subj = (row["subject_options"] or ["?"])[0] if row else "?"
        tok = EP.mint_chain_token(draft_id, rec["count"])
        return jsonify({"ok": True, "step": "confirm_required", "chain_token": tok,
                        "echo": "Send %r to %d recipients now?" % (subj[:70], rec["count"]),
                        "count": rec["count"], "definition": rec["definition"]})
    return jsonify(_json_safe(EP.send_draft(draft_id, count, d.get("chain_token") or "",
                                            actor=g.actor["user"])))


@bp.route("/attribution", methods=["GET"])
@require_bridge_any_role
def attribution():
    """Per-creative attribution + verdicts for the Timeline AD TRACKING section (Phase 4).
    The ONLY bridge route a media_buyer role can reach (require_bridge_any_role); owners
    see it too. Read-only analysis — no Meta write capability exists anywhere in v1."""
    import attribution_engine
    try:
        days = min(max(int(request.args.get("days", 30)), 1), 365)
    except ValueError:
        return jsonify({"error": "bad days"}), 400
    result = attribution_engine.compute(
        days=days, start=request.args.get("start"), end=request.args.get("end"),
        force=request.args.get("force") == "1")
    logger.info("bridge attribution read by %s (%s)", g.actor["user"], g.actor["role"])
    return jsonify(result)
