"""Timeline bridge (Layer 2): token validation is the security boundary — adversarial cases."""
import base64
import hashlib
import hmac
import importlib
import os
import time

os.environ["EDITH_BRIDGE_SECRET"] = "test-bridge-secret"

import dashboard.bridge as B

importlib.reload(B)  # pick up the env in case another module imported it first


def mint(user="rydel", purpose="timeline", ttl=60, secret="test-bridge-secret"):
    payload = "v1:%d:%s:%s" % (int(time.time()) + ttl, user, purpose)
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return payload + "." + sig


def setup_function(_):
    B._seen_sigs.clear()


def test_valid_token_authenticates_owner():
    assert B.validate_bridge_token(mint()) == "rydel"


def test_forged_signature_refused():
    assert B.validate_bridge_token(mint(secret="wrong-secret")) is None


def test_expired_token_refused():
    assert B.validate_bridge_token(mint(ttl=-5)) is None


def test_overlong_ttl_refused():
    # a token claiming to live 10 minutes is a minting bug or forgery — refuse
    assert B.validate_bridge_token(mint(ttl=600)) is None


def test_wrong_purpose_refused():
    assert B.validate_bridge_token(mint(purpose="dashboard")) is None


def test_non_owner_user_refused():
    for user in ("miguel", "kc", "piolo", "admin", "sales"):
        assert B.validate_bridge_token(mint(user=user)) is None, user


def test_replay_refused_single_use():
    tok = mint()
    assert B.validate_bridge_token(tok) == "rydel"
    assert B.validate_bridge_token(tok) is None      # second use of the SAME token


def test_garbage_and_empty_refused():
    for raw in ("", "v1:9999999999:rydel:timeline", "no-dot-here", "a.b", None):
        assert B.validate_bridge_token(raw or "") is None


def test_fail_closed_without_secret(monkeypatch):
    monkeypatch.delenv("EDITH_BRIDGE_SECRET", raising=False)
    assert B.validate_bridge_token(mint()) is None   # even a well-formed token


def test_endpoints_403_without_token():
    from app import app
    c = app.test_client()
    assert c.get("/bridge/ping").status_code == 403
    assert c.post("/bridge/chat-stream", json={"history": [{"role": "user", "content": "hi"}]}).status_code == 403
    assert c.get("/bridge/tts?text=hello").status_code == 403
    assert c.get("/bridge/greeting").status_code == 403


def test_endpoints_403_with_team_member_token():
    from app import app
    c = app.test_client()
    r = c.get("/bridge/ping", headers={"X-Bridge-Token": mint(user="miguel")})
    assert r.status_code == 403


def test_session_cookie_never_authorizes_bridge():
    # Layer separation: even the owner's DASHBOARD session must not reach /bridge/*.
    from app import app
    c = app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": "rydel", "role": "owner", "display": "Rydel"}
    assert c.get("/bridge/ping").status_code == 403


def test_ping_ok_with_valid_token():
    from app import app
    c = app.test_client()
    r = c.get("/bridge/ping", headers={"X-Bridge-Token": mint()})
    assert r.status_code == 200 and r.get_json()["user"] == "rydel"
