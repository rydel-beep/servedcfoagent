"""Dashboard hardening (server-rendered truth · crash isolation · real-browser
gate). These tests pin the STRUCTURAL laws; the render itself is asserted by
scripts/render_gate.py in a real browser (the only admissible "visible" proof).
"""

import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ── LAW 1: headline values are SERVER-RENDERED (JS enhances, never fills) ───

def test_landing_template_renders_tiles_server_side():
    html = _read("dashboard", "templates", "dashboard.html")
    # tiles come from the exec context — jinja-rendered, not JS-filled
    assert "{% for t in exec.tiles %}" in html
    assert "{{ t.value }}" in html
    assert "{{ t.stamp }}" in html          # freshness stamp law
    assert "{{ exec.verdict.line }}" in html
    # the landing page must NOT load the 5,600-line client-fill monolith
    assert "dashboard.js" not in html
    # no chart library on the landing page; chat libs are deferred
    assert "chart.umd.min.js" not in html
    for lib in ("marked", "purify"):
        line = next(l for l in html.splitlines() if lib in l and "script" in l)
        assert "defer" in line


def test_landing_route_serves_values_without_js():
    """Flask-level proof of the JS-disabled property: the raw HTML carries
    8 tiles + verdict + cards before any script could run."""
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-hardening")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    r = c.get("/dashboard/")
    assert r.status_code == 200
    html = r.data.decode()
    assert len(re.findall(r'class="exec-tile state-', html)) == 8
    assert 'id="exec-verdict"' in html
    assert 'class="landing-card' in html
    assert r.headers.get("Cache-Control") == "no-store"
    # undefined is a labelled state, never a bare blank: every tile value div
    # is non-empty in the rendered HTML
    values = re.findall(r'<div class="exec-tile-value">\s*([^<]*?)\s*</div>', html)
    assert len(values) == 8
    assert all(v.strip() for v in values)


def test_exec_top_labels_undefined_states():
    """No kv caches at all → every tile still renders a value or a labelled
    reason, with state degraded/amber — never a silent blank."""
    from dashboard import exec_top
    tiles = exec_top.build_tiles(None)
    assert len(tiles) == 8
    for t in tiles:
        assert t["value"], t
        if t["value"] == "—":
            assert t["sub"] or t["sr_note"], f"tile {t['id']} shows — with no labelled reason"
        assert t["state"] in ("ok", "amber", "degraded")


def test_exec_top_staleness_states():
    from dashboard.exec_top import _state_for
    assert _state_for(1.0, None) == "ok"
    assert _state_for(7.0, None) == "amber"       # stale > threshold = AMBER
    assert _state_for(None, None) == "amber"
    assert _state_for(0.5, "boom") == "degraded"  # failed = DEGRADED, never silent


# ── LAW 2: every panel is an error boundary ─────────────────────────────────

def test_render_orchestrator_is_boundary_table():
    js = _read("dashboard", "static", "js", "dashboard.js")
    assert "function boundary(sectionId, name, fn)" in js
    # the render pass goes through the table — no bare sequential chain
    assert "panelTable(snap).forEach(function (row) { boundary(row[0], row[1], row[2]); });" in js
    # loadAll's self-fetching panels ride boundaries too
    for name in ("'actionFeed'", "'ratioTiles'", "'ar'", "'decisionCards'", "'csmCard'"):
        assert re.search(r"boundary\([^)]*" + name, js), name
    # the boundary fails HONESTLY in place and reports to telemetry
    assert "Panel unavailable — " in js
    assert "panel_boundary" in js


def test_area_pages_skip_zones_and_absent_sections():
    js = _read("dashboard", "static", "js", "dashboard.js")
    assert "if (document.body && document.body.dataset.area) return;" in js  # applyZones
    assert "if (sectionId && !document.getElementById(sectionId)) return;" in js  # boundary skip


# ── LAW 3: no always-on audio/mic on the data page ──────────────────────────

def test_voice_is_opt_in():
    ejs = _read("dashboard", "static", "js", "edith.js")
    assert "lsGet('edith-wake', '1')" not in ejs
    assert "lsGet('edith-clap', '1')" not in ejs
    assert "lsGet('edith-wake', '0')" in ejs
    assert "lsGet('edith-clap', '0')" in ejs
    # no autoplay attribute anywhere in the dashboard templates
    for tpl in os.listdir(os.path.join(ROOT, "dashboard", "templates")):
        if tpl.endswith(".html"):
            assert "autoplay" not in _read("dashboard", "templates", tpl).lower(), tpl


# ── LAW 4: telemetry — browser crashes reach the server ─────────────────────

def test_telemetry_hook_is_first_script():
    html = _read("dashboard", "templates", "dashboard.html")
    tele = html.find("telemetry.html")
    ext = min(x for x in (html.find("fonts.googleapis"), html.find("cdn.jsdelivr"))
              if x >= 0)
    assert 0 < tele < ext, "telemetry include must precede every external resource"
    panel = _read("dashboard", "templates", "panel_page.html")
    assert panel.find("telemetry.html") < panel.find("cdn.jsdelivr")


def test_client_error_endpoint_stores_and_rate_limits():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-hardening")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    import kv_store
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    r = c.post("/dashboard/api/client-error",
               json={"kind": "uncaught", "detail": "x" * 999, "route": "/dashboard/"})
    assert r.status_code == 200 and r.get_json()["stored"] is True
    ring = kv_store.get("telemetry:client_errors")
    assert ring and len(ring[-1]["detail"]) <= 400        # truncated, no dumps
    # anonymous POST is refused (auth-gated)
    c2 = appmod.app.test_client()
    assert c2.post("/dashboard/api/client-error", json={}).status_code == 401


def test_render_health_watch_shapes():
    import render_health
    rate = render_health.error_rate_last_hours(2)
    assert "total" in rate and "per_hour" in rate
    sc = render_health.self_check()
    assert "ok" in sc and "problems" in sc
    # feed channel is registered with the action feed
    assert "feed:extra:render_health" in _read("action_feed.py")


def test_action_feed_severity_always_string():
    """The Phase-0 500: int severity keys made jsonify(sort_keys) throw and
    dead-crashed the panel silently. Pinned at both ends."""
    from action_feed import _norm_severity
    assert _norm_severity(2) == "S2"
    assert _norm_severity("S1") == "S1"
    assert _norm_severity(None) == "S3"
    assert _norm_severity("weird") == "S3"
    assert '"severity": 2' not in _read("gap_reconcile.py")
    assert '"severity": "S2"' in _read("gap_reconcile.py")


# ── LAW 5/6: IA — cards == pages, one rendering path ────────────────────────

def test_card_count_equals_page_count():
    from dashboard.routes import _AREAS
    from dashboard import exec_top
    cards = exec_top.build_cards(None, owner=True)
    hrefs = {c["href"] for c in cards}
    # every area page has a card; the three standalone pages too
    for area in _AREAS:
        assert f"/dashboard/view/{area}" in hrefs, f"area {area} has no landing card"
    for page in ("/dashboard/worklog", "/dashboard/bookkeeping", "/dashboard/csm"):
        assert page in hrefs
    assert len(hrefs) == len(_AREAS) + 3          # no dead links, no orphans
    # non-owner never sees owner-only cards
    anon_cards = exec_top.build_cards(None, owner=False)
    assert not any(c.get("owner_only") for c in anon_cards)
    assert "/dashboard/view/decisions" not in {c["href"] for c in anon_cards}


def test_area_partials_cover_all_sections_once():
    """No orphan panels: every section of the old monolith lives in exactly
    one area partial (csm-card/ops-cards became landing cards)."""
    part_dir = os.path.join(ROOT, "dashboard", "templates", "partials")
    seen = {}
    for fn in os.listdir(part_dir):
        if fn.startswith("area_"):
            for sid in re.findall(r'<section\b[^>]*\bid="(section-[\w-]+)"',
                                  _read("dashboard", "templates", "partials", fn)):
                assert sid not in seen, f"{sid} in both {seen[sid]} and {fn}"
                seen[sid] = fn
    assert len(seen) >= 40


def test_old_ratio_kpi_cells_removed():
    """2.3 — ONE rendering path for LTV:CAC / LTGP:CAC (the honest engine).
    The standing-engine KPI cells that rendered '—' are gone."""
    econ = _read("dashboard", "templates", "partials", "area_unit-econ.html")
    assert 'id="val-ltvcac"' not in econ
    assert 'id="val-ltgpcac-kpi"' not in econ
    js = _read("dashboard", "static", "js", "dashboard.js")
    assert "setMetric('val-ltgpcac-kpi'" not in js


def test_decisions_area_is_owner_only():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-hardening")
    import app as appmod
    c = appmod.app.test_client()
    # anonymous → redirect to login (302), never the page
    r = c.get("/dashboard/view/decisions")
    assert r.status_code in (302, 401, 403)


# ── the gate itself is pinned as the deploy law ─────────────────────────────

def test_render_gate_exists_with_core_assertions():
    gate = _read("scripts", "render_gate.py")
    for needle in ("executive tiles, expected 8",
                   "headline values are NOT server-rendered",
                   "horizontal overflow",
                   "java_script_enabled=False",
                   "GATE_OWNER_PASSWORD"):
        assert needle in gate
    # artefacts land in the repo evidence folder, never /tmp
    assert 'os.path.join(ROOT, "dashboard", "evidence"' in gate
