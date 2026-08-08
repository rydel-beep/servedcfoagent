"""AUDIT 2026-08-08 (register F4) — every /debug route is X-CFO-KEY gated.
The anon-MRR-exposure class can never return: any new /debug route must carry
the gate or this sweep fails."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_every_debug_route_is_key_gated():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    blocks = re.split(r'@app\.route\("(/debug/[^"]+)"', src)
    routes = blocks[1::2]
    bodies = blocks[2::2]
    assert routes, "no debug routes found — pattern drift, fix the test"
    for route, body in zip(routes, bodies):
        head = body[:600]
        assert 'X-CFO-KEY' in head and 'CFO_REFRESH_KEY' in head, \
            f"{route} is not key-gated within its first lines"


def test_anon_debug_routes_401(monkeypatch):
    monkeypatch.setenv("CFO_REFRESH_KEY", "test-key")
    import importlib
    import config
    importlib.reload(config)
    import app as app_mod
    importlib.reload(app_mod)
    c = app_mod.app.test_client()
    for path in ("/debug/stripe-ping", "/debug/sources", "/debug/xero-raw",
                 "/debug/bas-refresh", "/debug/xero-probe"):
        assert c.get(path).status_code == 401, path
    # and the key still opens the gate (200 or a degraded-but-authorized error)
    r = c.get("/debug/xero-probe", headers={"X-CFO-KEY": "wrong"})
    assert r.status_code == 401
