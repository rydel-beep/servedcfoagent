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
    if purpose != _PURPOSE or user not in _owners():
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


def require_bridge(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = validate_bridge_token(request.headers.get("X-Bridge-Token", ""))
        if not user:
            return jsonify({"error": "forbidden"}), 403
        # downstream tier handlers attribute via dashboard.auth.current_actor()
        g.actor = {"user": user, "role": "owner", "display": "Rydel"}
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
