"""
tests/test_xss_roster.py — F12 (extreme audit): reflected XSS via the ?roster=
deep link. Root cause: level/metric parsed from the URL rendered into the
drill-title innerHTML unescaped, BEFORE server validation could reject (the
only real vector of 64 taint suspects — every stored-XSS surface esc()s).

Fix under test: client-side whitelist of level+metric at the boundary + esc()
on every URL-derived string in the title. These are taint-regression tests —
part of the standing taint set.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_ads_dashboard import _client

JS = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "js", "adsapp.js")


def _js():
    with open(JS) as f:
        return f.read()


def test_js_whitelists_level_and_metric_before_render():
    js = _js()
    assert "VALID_LEVELS" in js and "VALID_METRICS" in js
    i_guard = js.index("VALID_METRICS[metric]")
    i_open = js.index("openDrill(esc(String(label || key)")
    assert i_guard < i_open        # the guard fires BEFORE anything renders


def test_js_escapes_metric_in_the_drill_title():
    js = _js()
    # the title concatenation must esc() the URL-derived metric — a bare
    # `+ metric +` in the loadRoster title line is the original vector
    m = re.search(r"openDrill\(esc\(String\(label \|\| key\)[^\n]*", js)
    assert m and "esc(metric)" in m.group(0)


def test_all_deep_link_metrics_are_in_the_whitelist():
    """Every metric the server accepts must be deep-linkable — the whitelist
    must not silently orphan a legitimate cell-spec."""
    import roster_engine
    js = _js()
    block = js[js.index("VALID_METRICS"):js.index("VALID_METRICS") + 400]
    for m in roster_engine.METRICS + roster_engine.ANOMALY_METRICS:
        assert m + ":" in block, f"metric '{m}' missing from the client whitelist"


def test_server_rejects_crafted_metric_without_echo(monkeypatch):
    """Adversarial re-run of the F12 probe: a crafted ?metric= is 400-rejected
    and the payload never reflects the raw string."""
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    evil = "<img src=x onerror=alert(1)>"
    r = c.get(f"/ads/api/roster?days=30&level=creative&key=k&metric={evil}")
    assert r.status_code == 400
    assert evil.encode() not in r.data
