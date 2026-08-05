"""
SERVED AD TRACKING — the dedicated dashboard (AD_DASHBOARD_REPORT). Adversarial tests:

- ISOLATION: media_buyer (SHIPS DISABLED; enabled only via MEDIA_BUYER_PASSWORD) reaches
  /ads and NOTHING financial — the fail-closed allowlist 403s every finance surface, and
  new endpoints are denied by default. Sales can't see /ads. Anon sees nothing.
- ROSTER == COUNT: the drill roster for any creative+stage+window is exactly the
  engine's cohort — length equals the scoreboard cell, structurally and asserted.
- FLAGS: deterministic against stated thresholds; min-n respected; zero-flag windows
  render honestly; thresholds read from manual_targets.
- THE WINDOW ECHO: /ads/api/board echoes the window it computed — the client's
  stale-mix guard depends on it.
"""
from __future__ import annotations

import datetime as dt

import pytest

import attribution_engine as eng
import attribution_flags as AF
from tests.test_attribution import HDR, row, contact, resolver, RES_A

W0, W1 = dt.date(2026, 7, 1), dt.date(2026, 7, 31)


def _client(monkeypatch, mb_password=None):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    if mb_password:
        monkeypatch.setenv("MEDIA_BUYER_PASSWORD", mb_password)
        monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")   # per-user mode on
    else:
        monkeypatch.delenv("MEDIA_BUYER_PASSWORD", raising=False)
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def _fake_result():
    rows = [HDR,
            row("A One", "a1@x.com", closer="won", close_date="2026-07-20",
                contract="15000", cash="6000"),
            row("A Two", "a2@x.com", setter="no pick up"),
            row("A Three", "a3@x.com")]
    contacts = [contact("c1", "a1@x.com", "A One"), contact("c2", "a2@x.com", "A Two"),
                contact("c3", "a3@x.com", "A Three")]
    spend = {"120000000000000001": {"name": "Creative A", "spend": 900.0,
                                    "impressions": 10, "clicks": 2}}
    return eng.compute_from_inputs(rows, contacts, spend,
                                   resolver({"120000000000000001": RES_A}), W0, W1)


# ── isolation ────────────────────────────────────────────────────────────────

def test_media_buyer_disabled_no_account(monkeypatch):
    c = _client(monkeypatch, mb_password=None)
    r = c.post("/dashboard/login", data={"username": "romano", "password": "whatever"})
    assert b"Invalid" in r.data or r.status_code in (200, 401)
    assert c.get("/ads/").status_code in (302, 401)      # no session → login


def test_media_buyer_enabled_reaches_ads_only(monkeypatch):
    c = _client(monkeypatch, mb_password="romano-test-pw")
    r = c.post("/dashboard/login", data={"username": "romano", "password": "romano-test-pw"})
    assert r.status_code == 302
    monkeypatch.setattr("attribution_engine.compute",
                        lambda **kw: _fake_result() | {"window": {"days": kw.get("days", 30),
                                                                  "start": "x", "end": "y"}},
                        raising=True)
    assert c.get("/ads/").status_code == 200
    assert c.get("/ads/api/board?days=30").status_code == 200
    # THE SWEEP: every finance surface 403s or bounces the role — fail-closed
    resp = c.post("/dashboard/api/chat", json={"history": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 403, f"chat → {resp.status_code}"
    for path in ("/dashboard/api/reactivation", "/dashboard/api/snapshot",
                 "/dashboard/api/greeting", "/dashboard/api/collab/queue",
                 "/dashboard/targets", "/dashboard/data-sources", "/dashboard/leads"):
        resp = c.get(path)
        assert resp.status_code in (403, 302), f"{path} → {resp.status_code}"
        if resp.status_code == 302:
            assert "/ads" in resp.headers.get("Location", ""), path
    assert c.get("/dashboard/").status_code == 302        # bounced to /ads
    # /cfo/* never honors a session — X-CFO-KEY or legacy cookie only
    assert c.get("/cfo/snapshot").status_code == 401
    assert c.get("/cfo/attribution?days=30").status_code == 401


def test_sales_role_cannot_reach_ads(monkeypatch):
    monkeypatch.setenv("SALES_PASSWORD", "sales-test-pw")
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    from app import app
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/dashboard/login",
                  data={"username": "sales", "password": "sales-test-pw"}).status_code == 302
    r = c.get("/ads/")
    assert r.status_code == 302 and "/dashboard/leads" in r.headers.get("Location", "")
    assert c.get("/ads/api/board?days=30").status_code == 403


def test_anon_sees_nothing(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/ads/").status_code in (302, 401)
    assert c.get("/ads/api/board?days=30").status_code == 401


# ── the window echo (the stale-mix guard's contract) ─────────────────────────

def test_board_echoes_its_window(monkeypatch):
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    seen = {}

    def fake_compute(**kw):
        seen["days"] = kw.get("days")
        r = _fake_result()
        r["window"] = {"start": "s", "end": "e", "days": kw.get("days")}
        return r
    monkeypatch.setattr("attribution_engine.compute", fake_compute, raising=True)
    d = c.get("/ads/api/board?days=60").get_json()
    assert seen["days"] in (60, 90)     # 60 requested (+ a 90d trailing probe is allowed)
    assert d["window"]["days"] == 60
    assert "scoreboard" in d and "scorecard" in d and "rows" in d   # atomic payload


# ── roster == count ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage,field", [("leads", "leads"), ("qualified", "qualified"),
                                         ("sets", "sets"), ("shows", "shows"),
                                         ("closes", "closes")])
def test_roster_length_equals_the_cell(monkeypatch, stage, field):
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    result = _fake_result()
    monkeypatch.setattr("attribution_engine.compute", lambda **kw: result, raising=True)
    monkeypatch.setattr("attribution_join.load_contacts", lambda: [], raising=True)
    monkeypatch.setattr("dashboard.ads._ghl_notes_for", lambda ids: {}, raising=True)
    cell = next(x for x in result["creatives"] if x["creative_key"] == "creative a")[field]
    d = c.get(f"/ads/api/roster?days=30&creative=creative%20a&stage={stage}").get_json()
    assert d["count"] == cell == len(d["people"])


def test_roster_person_fields_and_no_padding(monkeypatch):
    c = _client(monkeypatch)
    c.post("/dashboard/login", data={"token": "test-dash-token"})
    result = _fake_result()
    monkeypatch.setattr("attribution_engine.compute", lambda **kw: result, raising=True)
    monkeypatch.setattr("attribution_join.load_contacts", lambda: [], raising=True)
    monkeypatch.setattr("dashboard.ads._ghl_notes_for", lambda ids: {}, raising=True)
    d = c.get("/ads/api/roster?days=30&creative=creative%20a&stage=leads").get_json()
    p = next(x for x in d["people"] if x["name"] == "A Three")
    assert p["revenue"]["state"] in ("parsed", "unknown")
    assert p["notes"] == []            # NO GHL match, no tracker notes → empty, not filler


# ── flags ────────────────────────────────────────────────────────────────────

def _flag_kinds(result, **kw):
    return {f["kind"] for f in AF.flags(result, th={**AF.DEFAULTS, **kw})}


def test_spend_no_leads_flag_fires_at_threshold():
    r = {"creatives": [{"tier": "ad", "label": "Burner", "creative_key": "burner",
                        "leads": 0, "qualified": 0, "sets": 0, "shows": 0, "closes": 0,
                        "cash": 0, "spend": 200.0, "cost_per_lead": None,
                        "revenue_unknown": 0, "gates": {}}],
         "totals": {"leads": 0}, "window": {"days": 30}, "flags": []}
    assert "spend_no_leads" in _flag_kinds(r)
    assert "spend_no_leads" not in _flag_kinds(r, ad_flag_spend_no_leads=500.0)  # adjustable


def test_leads_no_sets_respects_min_n():
    def mk(leads):
        return {"creatives": [{"tier": "ad", "label": "X", "creative_key": "x",
                               "leads": leads, "qualified": 0, "sets": 0, "shows": 0,
                               "closes": 0, "cash": 0, "spend": 0, "cost_per_lead": None,
                               "revenue_unknown": 0, "gates": {}}],
                "totals": {"leads": leads}, "window": {"days": 30}, "flags": []}
    assert "leads_no_sets" in _flag_kinds(mk(9))
    assert "leads_no_sets" not in _flag_kinds(mk(5))       # below the sample floor


def test_attribution_drop_flag_needs_trailing():
    r = {"creatives": [], "totals": {"leads": 10, "attribution_rate_pct": 70.0},
         "window": {"days": 30}, "flags": []}
    assert not AF.flags(r, trailing_attr_rate=None)        # no trailing → no claim
    fl = AF.flags(r, trailing_attr_rate=86.0)
    assert any(f["kind"] == "attribution_drop" for f in fl)


def test_zero_flag_state_is_honest_and_leaders_empty_window():
    r = {"creatives": [], "totals": {"leads": 0}, "window": {"days": 30}, "flags": []}
    sc = AF.scorecard(r)
    assert sc["flags"] == [] and sc["leaders"] == []


def test_flags_read_manual_target_thresholds(monkeypatch):
    monkeypatch.setattr("manual_targets.get_resolved",
                        lambda: {"ad_flag_spend_no_leads": 999.0}, raising=True)
    assert AF.thresholds()["ad_flag_spend_no_leads"] == 999.0


# ── read-only: no writes to sheet/GHL/Meta in the new modules ────────────────

def test_ads_modules_are_read_only():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for mod in ("dashboard/ads.py", "attribution_flags.py"):
        src = (root / mod).read_text()
        for verb in ("requests.post", "requests.put", "requests.delete", "rq.post",
                     "rq.put", "rq.delete"):
            assert verb not in src, f"{mod} must never write ({verb})"
