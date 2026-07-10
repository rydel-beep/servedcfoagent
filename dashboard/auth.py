"""
dashboard/auth.py
-----------------
Token-based authentication for the Jarvis dashboard.
Single-user, cookie-based sessions.
"""
from __future__ import annotations

import functools
import logging
import os
import secrets

from flask import redirect, request, make_response, url_for

logger = logging.getLogger(__name__)

# Token from env, or generate and persist locally
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
            logger.info("Generated dashboard token, saved to %s", _token_file)
        except OSError as e:
            logger.warning("Could not write token file: %s", e)

COOKIE_NAME = "dash_token"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def _set_auth_cookie(resp):
    resp.set_cookie(
        COOKIE_NAME, DASHBOARD_TOKEN,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=True,
    )
    return resp


def require_auth(f):
    """Decorator that checks for valid dashboard token in cookie or query param."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # Check query param first (first visit with token link)
        token_param = request.args.get("t")
        if token_param == DASHBOARD_TOKEN:
            return _set_auth_cookie(make_response(redirect(request.path)))

        # Check cookie
        cookie_token = request.cookies.get(COOKIE_NAME)
        if cookie_token == DASHBOARD_TOKEN:
            # SLIDING SESSION: re-set the cookie on every authenticated request so active
            # use never hits the 30-day max-age cliff (the cliff made every dashboard API
            # silently 302 to the login page — the front-end parsed login HTML as JSON and
            # showed a generic error with a dead refresh button).
            return _set_auth_cookie(make_response(f(*args, **kwargs)))

        # Not authenticated. API calls get an explicit 401 (fetch() can't handle a redirect
        # to login HTML — it parses as JSON and fails opaquely); pages redirect to login.
        if "/api/" in (request.path or ""):
            from flask import jsonify
            return jsonify({"error": "session expired — log in again",
                            "login": url_for("dashboard.login_page")}), 401
        return redirect(url_for("dashboard.login_page"))

    return wrapper
