"""
dashboard/auth.py
-----------------
Per-user authentication with roles + actor identity, replacing the single shared DASHBOARD_TOKEN.

Two accounts (env-configured): rydel (owner) and piolo (coo). Piolo has FULL visibility + authority
(Rydel's call 2026-07-21) — the roles differ only by IDENTITY: every action is attributed, and
Piolo's write-actions are flagged to Rydel. Server-side Flask session carries {user, role}; each
request exposes the actor via g.actor / current_actor().

SAFE MIGRATION: setting RYDEL_PASSWORD + PIOLO_PASSWORD both ENABLES per-user login AND RETIRES the
legacy shared token — atomically. Until the passwords are set, the old token path still works (no
lockout, no behaviour change), so this deploys safely before the credentials exist.
"""
from __future__ import annotations

import functools
import hmac
import logging
import os
import secrets

from flask import redirect, request, make_response, url_for, session, g, jsonify

logger = logging.getLogger(__name__)

# ── Legacy shared token (fallback only while no per-user accounts are configured) ──
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
if not DASHBOARD_TOKEN:
    _token_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".dashboard_token")
    if os.path.exists(_token_file):
        with open(_token_file) as f:
            DASHBOARD_TOKEN = f.read().strip()
    if not DASHBOARD_TOKEN:
        DASHBOARD_TOKEN = secrets.token_urlsafe(32)
        try:
            with open(_token_file, "w") as f:
                f.write(DASHBOARD_TOKEN)
        except OSError as e:
            logger.warning("Could not write token file: %s", e)

COOKIE_NAME = "dash_token"
COOKIE_MAX_AGE = 30 * 24 * 3600


# ── Per-user accounts (from env; passwords are server-side secrets) ──────────
def _accounts() -> dict:
    accts: dict = {}
    rp = os.environ.get("RYDEL_PASSWORD", "")
    pp = os.environ.get("PIOLO_PASSWORD", "")
    if rp:
        accts["rydel"] = {"role": "owner", "pw": rp, "display": "Rydel"}
    if pp:
        accts["piolo"] = {"role": "coo", "pw": pp, "display": "Piolo"}
    return accts


def per_user_enabled() -> bool:
    """True once at least one per-user password is set — this also retires the legacy token."""
    return bool(_accounts())


def verify_login(username: str, password: str) -> dict | None:
    """Constant-time credential check. Returns {user, role, display} or None."""
    a = _accounts().get((username or "").strip().lower())
    if a and password and hmac.compare_digest(a["pw"], password):
        return {"user": (username or "").strip().lower(), "role": a["role"], "display": a["display"]}
    return None


def current_actor() -> dict:
    """The acting user for this request — {user, role, display}. Set by require_auth; falls back to
    owner (rydel) on the legacy-token path so attribution is never blank."""
    act = getattr(g, "actor", None) or session.get("actor")
    return act or {"user": "rydel", "role": "owner", "display": "Rydel"}


def is_owner() -> bool:
    return current_actor().get("role") == "owner"


def audit_login(actor: dict, ok: bool = True) -> None:
    """Append a login event to the durable audit (kv_store); never stores the password."""
    try:
        import kv_store
        from helpers import now_sydney
        log = kv_store.get("auth:login_log") or []
        log.append({"user": actor.get("user") if actor else "(unknown)",
                    "ok": ok, "at": now_sydney().isoformat(),
                    "ip": (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:45]})
        kv_store.put("auth:login_log", log[-500:])
    except Exception as e:
        logger.info("audit_login failed: %s", e)


def _set_legacy_cookie(resp):
    resp.set_cookie(COOKIE_NAME, DASHBOARD_TOKEN, max_age=COOKIE_MAX_AGE,
                    httponly=True, samesite="Lax", secure=True)
    return resp


def require_auth(f):
    """Authenticate + set g.actor. Per-user session first; legacy token ONLY while no per-user
    accounts are configured (so setting the passwords retires the token)."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        act = session.get("actor")
        if act:
            g.actor = act
            return f(*args, **kwargs)

        # Legacy shared-token path — disabled once per-user auth is enabled.
        if not per_user_enabled():
            token_param = request.args.get("t")
            if token_param == DASHBOARD_TOKEN:
                return _set_legacy_cookie(make_response(redirect(request.path)))
            if request.cookies.get(COOKIE_NAME) == DASHBOARD_TOKEN:
                g.actor = {"user": "rydel", "role": "owner", "display": "Rydel"}
                return _set_legacy_cookie(make_response(f(*args, **kwargs)))

        # Not authenticated.
        if "/api/" in (request.path or ""):
            return jsonify({"error": "session expired — log in again",
                            "login": url_for("dashboard.login_page")}), 401
        return redirect(url_for("dashboard.login_page"))

    return wrapper


def require_owner(f):
    """Owner-only gate (server-side). Both accounts have full caps today, so this is reserved for
    anything Rydel later marks owner-only; returns 403 for a non-owner actor."""
    @functools.wraps(f)
    @require_auth
    def wrapper(*args, **kwargs):
        if not is_owner():
            return jsonify({"error": "owner-only", "role": current_actor().get("role")}), 403
        return f(*args, **kwargs)
    return wrapper
