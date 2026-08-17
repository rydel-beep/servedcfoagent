"""
tests/test_csm_confidentiality.py
---------------------------------
THE LAW (#146): every CSM artefact is OWNER-ONLY. Identity × route matrix
(piolo/coo, ad_domain, sales, anon), EDITH silence for non-owners, memory
non-persistence, discreet mode, export preflight strip, ship-notes structural
exclusion, nav non-announcement, the director-figure grep sweep, and the
security-replay leak probes.
"""
from __future__ import annotations
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


def _clients(monkeypatch):
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    monkeypatch.setenv("PIOLO_PASSWORD", "piolo-test-pw")
    monkeypatch.setenv("SALES_PASSWORD", "sales-test-pw")
    monkeypatch.setenv("ROMANO_PASSWORD", "romano-test-pw")
    from app import app
    app.config["TESTING"] = True

    def login(user):
        c = app.test_client()
        r = c.post("/dashboard/login", data={"username": user, "password": f"{user}-test-pw"})
        assert r.status_code == 302, f"{user} login failed"
        return c
    return app, login


_CSM_APIS = ("/dashboard/api/csm/summary", "/dashboard/api/csm/model",
             "/dashboard/api/csm/scoreboard", "/dashboard/api/csm/baselines",
             "/dashboard/api/csm/calendar", "/dashboard/api/csm/gates",
             "/dashboard/api/csm/risks", "/dashboard/api/csm/config",
             "/dashboard/api/csm/card", "/dashboard/api/csm/analysis",
             "/dashboard/api/csm/analysis.pdf",
             "/dashboard/api/csm/comp-preflight",
             "/dashboard/api/csm/comp-page.pdf",
             "/dashboard/api/csm/scenario-overlay",
             "/dashboard/api/csm/explain")


def test_identity_route_matrix(monkeypatch):
    """piolo (full-visibility coo) 403s on EVERY csm API — the ruled
    exception; ad_domain + sales walled; anon refused; owner 200."""
    _kv_reset(monkeypatch)
    app, login = _clients(monkeypatch)
    piolo = login("piolo")
    for path in _CSM_APIS:
        r = piolo.get(path)
        # /explain is POST-only → GET resolves 405 at routing (piolo POST is
        # asserted 403 in test_posts_owner_only)
        want = (403, 405) if path.endswith("/explain") else (403,)
        assert r.status_code in want, f"piolo reached {path}: {r.status_code}"
    assert piolo.get("/dashboard/csm").status_code == 302   # page redirects
    romano = login("romano")
    for path in ("/dashboard/csm", "/dashboard/api/csm/summary",
                 "/dashboard/api/csm/card"):
        assert romano.get(path).status_code in (302, 403)
    sales = login("sales")
    for path in ("/dashboard/csm", "/dashboard/api/csm/summary"):
        assert sales.get(path).status_code in (302, 403)
    anon = app.test_client()
    for path in ("/dashboard/csm",) + _CSM_APIS:
        want = (302, 401, 403, 405) if path.endswith("/explain") else (302, 401, 403)
        assert anon.get(path).status_code in want, path
    assert anon.post("/dashboard/api/csm/explain",
                     json={"q": "csm"}).status_code in (302, 401, 403)
    # owner reaches the cheap endpoints (heavier ones exercised elsewhere)
    rydel = login("rydel")
    assert rydel.get("/dashboard/api/csm/config").status_code == 200
    assert rydel.get("/dashboard/api/csm/comp-preflight").status_code == 200


def test_posts_owner_only(monkeypatch):
    _kv_reset(monkeypatch)
    app, login = _clients(monkeypatch)
    piolo = login("piolo")
    for path, body in (("/dashboard/api/csm/config", {"start_date": "2026-12-01"}),
                       ("/dashboard/api/csm/gates", {"id": "floor_test", "done": True}),
                       ("/dashboard/api/csm/risks", {"id": "routing_around", "status": "ok"}),
                       ("/dashboard/api/csm/discreet", {"on": True}),
                       ("/dashboard/api/csm/tier", {"client": "X", "tier": 1}),
                       ("/dashboard/api/csm/analysis", {}),
                       ("/dashboard/api/csm/explain", {"q": "csm"})):
        assert piolo.post(path, json=body).status_code == 403, path


def test_discreet_mode_hides_card(monkeypatch):
    _kv_reset(monkeypatch)
    app, login = _clients(monkeypatch)
    rydel = login("rydel")
    import csm_plan
    monkeypatch.setattr(csm_plan, "summary", lambda: {
        "card_line": "CSM · test", "next_action": {"item": "x", "owner": "Rydel"},
        "phase_strip": {}, "one_number": {}, "dial_4x": {}, "gate0": {},
        "top_risks": []})
    r0 = rydel.get("/dashboard/api/csm/card")
    assert r0.status_code == 200 and r0.get_json()["show"] is True
    assert rydel.post("/dashboard/api/csm/discreet", json={"on": True}).status_code == 200
    r1 = rydel.get("/dashboard/api/csm/card")
    assert r1.get_json() == {"show": False, "discreet": True}
    # the scenario overlay (a CSM mention on the finance dashboard) hides too
    r2 = rydel.get("/dashboard/api/csm/scenario-overlay")
    assert r2.get_json().get("enabled") is False
    assert rydel.post("/dashboard/api/csm/discreet", json={"on": False}).status_code == 200
    assert rydel.get("/dashboard/api/csm/card").get_json()["show"] is True


def test_edith_silence_for_non_owner():
    """Non-owner drill: (None, False) — silent fall-through, never a refusal
    that confirms the domain exists. Context injector likewise empty."""
    import csm_plan
    for actor in ({"user": "piolo", "role": "coo"},
                  {"user": "romano", "role": "ad_domain"},
                  {"user": "sales", "role": "sales"}, {}, None):
        reply, handled = csm_plan.handle_csm_command("csm roi status", actor)
        assert reply is None and handled is False, actor
        assert csm_plan.csm_context("what about the csm hire", actor) == ""


def test_edith_owner_drill_answers(monkeypatch):
    _kv_reset(monkeypatch)
    import csm_plan
    monkeypatch.setattr(csm_plan, "summary", lambda: {
        "card_line": "CSM · pre-start · Gate 0 0/7 · path to 4x: 68.7% renewal",
        "next_action": {"item": "tick the floor test", "owner": "Rydel"}})
    reply, handled = csm_plan.handle_csm_command(
        "csm roi status", {"user": "rydel", "role": "owner"})
    assert handled and "68.7" in reply
    assert "/dashboard/csm" in reply          # the deep link rides every answer
    r2, h2 = csm_plan.handle_csm_command(
        "what renewal rate gets us to 4x", {"user": "rydel", "role": "owner"})
    assert h2 and "%" in r2 and "cohort" in r2.lower()


def test_csm_turns_never_persist_to_memory(monkeypatch):
    """The whole point: a CSM turn (either side) never lands in shared
    memory — the trigram recall would replay it to Piolo otherwise."""
    _kv_reset(monkeypatch)
    app, login = _clients(monkeypatch)
    rydel = login("rydel")
    import memory
    recorded = []
    monkeypatch.setattr(memory, "record_turn",
                        lambda conv_id, role, content, **kw: recorded.append((role, content)))
    monkeypatch.setattr(memory, "maybe_distill_async", lambda cid: recorded.append(("distill", cid)))
    import csm_plan
    monkeypatch.setattr(csm_plan, "summary", lambda: {
        "card_line": "CSM · test line", "next_action": {"item": "x", "owner": "Rydel"}})
    r = rydel.post("/dashboard/api/chat",
                   json={"history": [{"role": "user", "content": "csm roi status"}]})
    assert r.status_code == 200
    assert "CSM" in (r.get_json().get("reply") or "")
    joined = " ".join(str(c) for _, c in recorded)
    assert "csm" not in joined.lower(), recorded


def test_ship_notes_structurally_excluded():
    """served-ship-notes captures as ad_domain; the fail-closed allowlist
    cannot reach any csm path (and no csm path contains the '/ads' fragment)."""
    from dashboard.auth import ad_domain_permitted, sales_permitted
    for p in ("/dashboard/csm", "/dashboard/api/csm/summary",
              "/dashboard/api/csm/card", "/dashboard/api/csm/comp-page.pdf"):
        assert not ad_domain_permitted(p), p
        assert not sales_permitted(p), p


def test_csm_not_announced_by_nav():
    """nav_registry pages are voice-announced to every role — csm must NOT
    be registered (an owner-only page must not be spoken to non-owners)."""
    import nav_registry
    assert not any("csm" in str(v).lower()
                   for v in nav_registry.PAGES.items())
    assert "csm" not in nav_registry.capability_text("dashboard").lower()


def test_no_csm_writes_to_shared_surfaces():
    """Structural sweep: the csm modules never touch the announce-to-Piolo /
    shared-feed paths."""
    for mod in ("csm_plan.py", "csm_baselines.py", "csm_docs.py", "csm_model.py"):
        src = open(os.path.join(os.path.dirname(__file__), "..", mod)).read()
        for forbidden in ("collab.add_entry(", "collab.record_action(",
                          "'feed:extra", '"feed:extra', "build_action_feed(",
                          "upsert_fact(", "salience."):
            assert forbidden not in src, f"{mod} writes to {forbidden}"


def test_director_figures_grep_sweep():
    """No director comp figure constants anywhere in the csm modules, docs,
    DECISIONS, or specs. (The figures are owner-entered kv config only.)"""
    root = os.path.join(os.path.dirname(__file__), "..")
    targets = ["csm_plan.py", "csm_baselines.py", "csm_docs.py", "csm_model.py",
               "DECISIONS.md", "dashboard/CSM_DIAGNOSIS.md",
               "dashboard/templates/csm.html",
               "docs/CSM_GHL_INGESTION_SPEC.md", "docs/CSM_HEALTH_SCORE_SPEC.md",
               "docs/CSM_ROLE_SCOPE_SPEC.md"]
    pats = [re.compile(r"(?<![\d_])144[,_]?000"), re.compile(r"(?<![\d_.])144k"),
            re.compile(r"(?<![\d_])45[,_]?000(?![\d.])"), re.compile(r"(?<![\d_.])45k")]
    for t in targets:
        src = open(os.path.join(root, t)).read()
        for p in pats:
            assert not p.search(src), f"{t} matches {p.pattern}"


def test_comp_page_preflight_and_refusal(monkeypatch):
    _kv_reset(monkeypatch)
    import csm_docs
    pre = csm_docs.comp_page_preflight()
    assert pre["clean"] and pre["forbidden_token_hits"] == []
    assert "director comp anything" in pre["stripped"]
    # sabotage: a forbidden token in the rendered text must make the
    # generator REFUSE to emit
    monkeypatch.setattr(csm_docs, "comp_page_text",
                        lambda cfg=None: "Base: $4,000 — internal ROI 3.5x")
    with pytest.raises(ValueError):
        csm_docs.comp_page_pdf()


def test_analysis_briefing_has_no_director_figures(monkeypatch):
    _kv_reset(monkeypatch)
    import csm_docs, csm_plan
    monkeypatch.setattr(csm_plan, "summary", lambda: {
        "card_line": "CSM · test", "next_action": {"item": "x", "owner": "Rydel"}})
    monkeypatch.setattr(csm_plan.csm_baselines, "all_baselines",
                        lambda fresh=False: {})
    md, _ = csm_docs.build_analysis_markdown()
    for pat in (r"(?<![\d_])144[,_]?000", r"(?<![\d_])45[,_]?000(?![\d.])"):
        assert not re.search(pat, md)
    assert "owner config" in md          # the reference idiom instead


def test_security_replay_covers_csm(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    import ad_sentinel
    out = ad_sentinel.security_replay()
    assert "csm_anon_codes" in out
    assert out["csm_anon_ok"] is True, out["csm_anon_codes"]


def test_dashboard_js_card_fails_closed():
    """Structural JS: the guard (non-200 → hidden) fires BEFORE the reveal,
    the section ships hidden, and the zone map carries the card."""
    root = os.path.join(os.path.dirname(__file__), "..")
    js = open(os.path.join(root, "dashboard/static/js/dashboard.js")).read()
    i_fetch = js.index("fetch('/dashboard/api/csm/card')")
    i_guard = js.index("sec.style.display = 'none'; return; }   // guard first")
    i_reveal = js.index("sec.style.display = '';")
    assert i_fetch < i_guard < i_reveal
    assert "'section-csm-card'" in js
    html = open(os.path.join(root, "dashboard/templates/dashboard.html")).read()
    assert 'id="section-csm-card" style="display:none"' in html


def test_config_journal_masks_director_values(monkeypatch):
    _kv_reset(monkeypatch)
    import csm_plan
    cfg, err = csm_plan.set_config({"user": "rydel"},
                                   {"director_current_annual": 123456,
                                    "start_date": "2026-12-01"})
    assert err is None and cfg["director_current_annual"] == 123456
    entries = csm_plan.journal_entries(10)
    joined = str(entries)
    assert "123456" not in joined            # masked
    assert "(set)" in joined
    assert "2026-12-01" in joined            # non-director values journal openly


def test_drill_registered_on_both_handler_lists():
    """A drill missing from the STREAMING list is silently dead on voice +
    the Timeline widget — both lists must carry it (structural)."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "dashboard/routes.py")).read()
    assert src.count("handle_csm_command") >= 2      # both tier-2 lists
    # and both sensitivity gates name the handler
    assert src.count("_h is _csm_handler") + src.count("or _h is _csm_handler") >= 2


def test_csm_page_watermark_and_banner():
    html = open(os.path.join(os.path.dirname(__file__), "..",
                             "dashboard/templates/csm.html")).read()
    assert "NOT FOR SCREEN-SHARE" in html
    assert "CONFIDENTIAL" in html
    assert "csm-watermark" in html
    assert "discreet" in html


def test_timeline_deep_link_in_drill_reply(monkeypatch):
    """The Timeline widget's answers carry the owner deep link (reply text —
    no timeline-repo change needed)."""
    import csm_plan
    monkeypatch.setattr(csm_plan, "summary", lambda: {
        "card_line": "CSM · x", "next_action": {"item": "y", "owner": "Rydel"}})
    reply, handled = csm_plan.handle_csm_command(
        "csm", {"user": "rydel", "role": "owner"})
    assert handled and "/dashboard/csm" in reply
