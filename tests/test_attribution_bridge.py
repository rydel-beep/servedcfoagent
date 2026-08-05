"""
media_buyer bridge role (Phase 4 CFO-side prep) — the scoping proofs:
  - SHIPS DISABLED: with EDITH_BRIDGE_MEDIA_BUYERS unset, a romano token is invalid
    everywhere, including /bridge/attribution.
  - Enabled: romano reaches /bridge/attribution ONLY; every owner route 403s him
    (ping, email list, send) — server-side, the sales-role pattern.
  - Owner reaches attribution too; owner routes unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import os
import time

os.environ["EDITH_BRIDGE_SECRET"] = "test-bridge-secret"

import dashboard.bridge as B

importlib.reload(B)


def mint(user="rydel", purpose="timeline", ttl=60, secret="test-bridge-secret"):
    payload = f"v1:{time.time() + ttl:.6f}:{user}:{purpose}"
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{payload}.{sig}"


def _client(monkeypatch):
    import app as app_mod
    app_mod.app.config["TESTING"] = True
    monkeypatch.setattr("attribution_engine.compute",
                        lambda **kw: {"ok": True, "creatives": [], "totals": {},
                                      "window": kw}, raising=True)
    return app_mod.app.test_client()


def test_media_buyer_disabled_by_default_403_everywhere(monkeypatch):
    monkeypatch.delenv("EDITH_BRIDGE_MEDIA_BUYERS", raising=False)
    c = _client(monkeypatch)
    for path in ("/bridge/attribution?days=30", "/bridge/ping", "/bridge/email/list"):
        r = c.get(path, headers={"X-Bridge-Token": mint(user="romano")})
        assert r.status_code == 403, path


def test_media_buyer_enabled_reaches_only_attribution(monkeypatch):
    monkeypatch.setenv("EDITH_BRIDGE_MEDIA_BUYERS", "romano")
    c = _client(monkeypatch)
    r = c.get("/bridge/attribution?days=30", headers={"X-Bridge-Token": mint(user="romano")})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    # every owner surface 403s the media buyer — server-side scoping
    assert c.get("/bridge/ping", headers={"X-Bridge-Token": mint(user="romano")}).status_code == 403
    assert c.get("/bridge/email/list", headers={"X-Bridge-Token": mint(user="romano")}).status_code == 403
    assert c.post("/bridge/email/send", json={"id": 1, "count": 1},
                  headers={"X-Bridge-Token": mint(user="romano")}).status_code == 403


def test_owner_reaches_attribution_and_everything_else_unchanged(monkeypatch):
    monkeypatch.setenv("EDITH_BRIDGE_MEDIA_BUYERS", "romano")
    c = _client(monkeypatch)
    assert c.get("/bridge/attribution?days=30",
                 headers={"X-Bridge-Token": mint()}).status_code == 200
    assert c.get("/bridge/ping", headers={"X-Bridge-Token": mint()}).status_code == 200


def test_unknown_user_still_invalid_even_when_role_env_set(monkeypatch):
    monkeypatch.setenv("EDITH_BRIDGE_MEDIA_BUYERS", "romano")
    c = _client(monkeypatch)
    assert c.get("/bridge/attribution?days=30",
                 headers={"X-Bridge-Token": mint(user="mallory")}).status_code == 403
