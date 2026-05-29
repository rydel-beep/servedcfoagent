"""
tests/test_dashboard.py
-----------------------
Tests for the Jarvis dashboard: auth, API endpoints, chat fallback.
"""
from __future__ import annotations

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("CFO_REFRESH_KEY", "test-key-123")
os.environ.setdefault("DASHBOARD_TOKEN", "test-dash-token")

# Clear any existing anthropic key for fallback testing
_original_key = os.environ.pop("ANTHROPIC_API_KEY", None)


def _get_app():
    """Get Flask test client with dashboard token set."""
    # Reload auth module to pick up env var
    import importlib
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_unauth_redirects_to_login():
    """Unauthenticated request to /dashboard should redirect to login."""
    client = _get_app()
    resp = client.get("/dashboard/")
    assert resp.status_code == 302
    assert "/dashboard/login" in resp.headers.get("Location", "")
    print("  Unauth → 302 redirect to /login")


def test_login_page_renders():
    """GET /dashboard/login returns 200 with login form."""
    client = _get_app()
    resp = client.get("/dashboard/login")
    assert resp.status_code == 200
    assert b"token" in resp.data.lower()
    print("  Login page renders (200)")


def test_invalid_token_rejected():
    """POST /dashboard/login with wrong token returns 401."""
    client = _get_app()
    resp = client.post("/dashboard/login", data={"token": "wrong-token"})
    assert resp.status_code == 401
    print("  Invalid token → 401")


def test_valid_token_sets_cookie():
    """POST /dashboard/login with correct token sets cookie and redirects."""
    client = _get_app()
    resp = client.post("/dashboard/login", data={"token": "test-dash-token"})
    assert resp.status_code == 302
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("dash_token" in c for c in cookies), f"Cookie not set: {cookies}"
    print("  Valid token → cookie set, redirect")


def test_cookie_grants_access():
    """With valid cookie, /dashboard returns 200."""
    client = _get_app()
    # Login first
    client.post("/dashboard/login", data={"token": "test-dash-token"})
    # Now access dashboard
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert b"Served" in resp.data
    print("  Cookie grants access (200)")


def test_api_snapshot_returns_json():
    """GET /dashboard/api/snapshot returns JSON (with auth)."""
    client = _get_app()
    client.post("/dashboard/login", data={"token": "test-dash-token"})
    resp = client.get("/dashboard/api/snapshot")
    # Could be 200 (if snapshot exists) or 404 (no snapshot yet)
    assert resp.status_code in (200, 404)
    data = resp.get_json()
    assert data is not None
    print(f"  API snapshot: {resp.status_code}")


def test_chat_no_api_key_returns_fallback():
    """Chat endpoint without ANTHROPIC_API_KEY returns graceful fallback."""
    import dashboard.chat as chat_mod
    chat_mod.ANTHROPIC_API_KEY = ""

    client = _get_app()
    client.post("/dashboard/login", data={"token": "test-dash-token"})
    resp = client.post(
        "/dashboard/api/chat",
        data=json.dumps({"message": "What's my MRR?"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["reply"] is None
    assert "not configured" in data["error"].lower() or "unavailable" in data["error"].lower()
    print("  Chat without API key → graceful fallback")


def test_query_param_token():
    """First visit with ?t=<token> sets cookie and redirects."""
    client = _get_app()
    resp = client.get("/dashboard/?t=test-dash-token")
    assert resp.status_code == 302
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("dash_token" in c for c in cookies)
    print("  Query param token → cookie set")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")

    # Restore API key if it was set
    if _original_key:
        os.environ["ANTHROPIC_API_KEY"] = _original_key

    sys.exit(0 if passed == len(tests) else 1)
