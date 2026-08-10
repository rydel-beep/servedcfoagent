"""
tests/test_ads_team_access.py — #136: the ad_domain role, the discussion
engine, and preview links. This wave adds the FIRST non-owner WRITE surface
on the CFO service — the drills here are the adversarial proof:

- AUTH MATRIX: {owner, romano, isaiah, inna, sales, anon} × {/ads surfaces,
  discussion verbs, finance routes} — server-side, exact codes.
- IDENTITY: author comes from the session; a crafted request claiming another
  author is structurally ignored (no author parameter exists to spoof).
- EXCLUDED ≠ DELETED: edits journal, deletes tombstone, resolve collapses.
- UNTRUSTED TEXT: hostile bodies ride the wire raw and NEVER unescaped into
  HTML (client esc() structural pins; feed titles never carry bodies).
- CONTEXT STAMP: server-computed from the one engine for the named view.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import ads_discussion as D
from tests.test_ads_dashboard import _fake_result

_REPO = os.path.join(os.path.dirname(__file__), "..")


def _team_client(monkeypatch):
    """Per-user mode with all three ad_domain users + owner + sales enabled
    (staging credentials — the suite's own, never production secrets)."""
    import dashboard.auth as auth_mod
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    monkeypatch.setenv("SALES_PASSWORD", "sales-test-pw")
    monkeypatch.setenv("ROMANO_PASSWORD", "romano-test-pw")
    monkeypatch.setenv("ISAIAH_PASSWORD", "isaiah-test-pw")
    monkeypatch.setenv("INNA_PASSWORD", "inna-test-pw")
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def _login(c, user, pw):
    r = c.post("/dashboard/login", data={"username": user, "password": pw})
    assert r.status_code == 302, f"{user} login failed"


def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


def _mock_engine(monkeypatch):
    result = _fake_result()
    result["window"] = {"start": "2026-07-01", "end": "2026-07-31", "days": 31}
    monkeypatch.setattr("attribution_engine.compute", lambda **kw: result, raising=True)
    monkeypatch.setattr("dashboard.ads._serve_board",
                        lambda *a, **k: {"window": result["window"], "basis": "cohort",
                                         "scoreboard": {"rows": []}, "stale": False},
                        raising=True)
    return result


# ── the three users exist, config-driven ─────────────────────────────────────

def test_three_ad_domain_users_from_env(monkeypatch):
    monkeypatch.setenv("ROMANO_PASSWORD", "r")
    monkeypatch.setenv("ISAIAH_PASSWORD", "i")
    monkeypatch.setenv("INNA_PASSWORD", "n")
    import dashboard.auth as A
    accts = A._accounts()
    for u in ("romano", "isaiah", "inna"):
        assert accts[u]["role"] == "ad_domain", u
    # legacy env still works for romano
    monkeypatch.delenv("ROMANO_PASSWORD")
    monkeypatch.setenv("MEDIA_BUYER_PASSWORD", "legacy")
    assert A._accounts()["romano"]["pw"] == "legacy"
    # config-driven: an unlisted user with a password does NOT appear
    monkeypatch.setenv("AD_DOMAIN_USERS", "romano,isaiah")
    monkeypatch.setenv("INNA_PASSWORD", "n")
    assert "inna" not in A._accounts()


# ── THE AUTH MATRIX ──────────────────────────────────────────────────────────

_ADS_OK = ("/ads/", "/ads/api/board?days=30", "/ads/api/discussion")
_FINANCE = ("/dashboard/api/snapshot", "/dashboard/api/greeting",
            "/dashboard/targets", "/dashboard/api/collab/queue",
            "/dashboard/data-sources", "/dashboard/leads")


def test_auth_matrix_all_roles(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    c = _team_client(monkeypatch)
    # anon: everything locked
    for p in _ADS_OK + _FINANCE:
        r = c.get(p)
        assert r.status_code in (302, 401), f"anon {p} → {r.status_code}"
    # each ad_domain user: /ads yes, finance no
    for user in ("romano", "isaiah", "inna"):
        c2 = _team_client(monkeypatch)
        _login(c2, user, f"{user}-test-pw")
        for p in _ADS_OK:
            r = c2.get(p)
            assert r.status_code == 200, f"{user} {p} → {r.status_code}"
        for p in _FINANCE:
            r = c2.get(p)
            assert r.status_code in (403, 302), f"{user} FINANCE LEAK {p} → {r.status_code}"
            if r.status_code == 302:
                assert "/ads" in (r.headers.get("Location") or ""), \
                    f"{user} {p} redirected somewhere other than /ads"
        # chat (card applies ride EDITH chat) → hard 403
        r = c2.post("/dashboard/api/chat", json={"history": [{"role": "user",
                                                              "content": "apply the date card for X"}]})
        assert r.status_code == 403, f"{user} chat/apply → {r.status_code}"
    # sales: no /ads at all
    c3 = _team_client(monkeypatch)
    _login(c3, "sales", "sales-test-pw")
    for p in _ADS_OK:
        r = c3.get(p)
        assert r.status_code in (403, 302), f"sales reached {p}"
    # owner: everything
    c4 = _team_client(monkeypatch)
    _login(c4, "rydel", "rydel-test-pw")
    assert c4.get("/ads/api/board?days=30").status_code == 200
    assert c4.get("/ads/api/discussion").status_code == 200


def test_deep_link_params_respect_role(monkeypatch):
    """?range/?clock/?roster/?dossier param families under the role — allowed
    on /ads, and the same params on finance routes still 403."""
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "inna", "inna-test-pw")
    assert c.get("/ads/api/board?range=2026-07-01..2026-07-07&clock=activity").status_code == 200
    r = c.get("/dashboard/api/snapshot?range=2026-07-01..2026-07-07")
    assert r.status_code in (403, 302)


# ── discussion: identity, journal, tombstone, resolve, rate limit ────────────

def test_author_is_session_never_client(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "romano", "romano-test-pw")
    # the crafted request CLAIMS to be Rydel — the field does not exist and is ignored
    r = c.post("/ads/api/discussion?days=30", json={
        "body": "spoof attempt", "anchor": "board",
        "author": {"user": "rydel", "display": "Rydel"},
        "user": "rydel"})
    assert r.status_code == 200
    note = r.get_json()["note"]
    assert note["author"]["user"] == "romano"
    assert note["author"]["display"] == "Romano"


def test_edit_journals_delete_tombstones_resolve_collapses(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "isaiah", "isaiah-test-pw")
    cid = c.post("/ads/api/discussion?days=30",
                 json={"body": "first version", "anchor": "board"}).get_json()["note"]["id"]
    # edit journals + marks
    r = c.post("/ads/api/discussion/edit", json={"id": cid, "body": "second version"})
    assert r.get_json()["note"]["was_edited"] is True
    raw = next(x for x in D._store()["comments"] if x["id"] == cid)
    assert raw["journal"][0]["old_body"] == "first version"     # auditable history
    # another user cannot edit it
    c2 = _team_client(monkeypatch)
    _login(c2, "romano", "romano-test-pw")
    assert c2.post("/ads/api/discussion/edit",
                   json={"id": cid, "body": "hijack"}).status_code == 403
    # but CAN resolve it (anyone with the role)
    r = c2.post("/ads/api/discussion/resolve", json={"id": cid, "note": "handled"})
    assert r.get_json()["note"]["state"] == "resolved"
    # delete-own tombstones — the wire never carries the old body again
    cid2 = c.post("/ads/api/discussion?days=30",
                  json={"body": "to be removed", "anchor": "board"}).get_json()["note"]["id"]
    r = c.post("/ads/api/discussion/delete", json={"id": cid2})
    t = r.get_json()["note"]
    assert t["state"] == "tombstone" and t["body"] == ""
    assert "removed by Isaiah" in t["tombstone_text"]
    listed = c.get("/ads/api/discussion").get_json()["notes"]
    tomb = next(n for n in listed if n["id"] == cid2)
    assert tomb["body"] == "" and "to be removed" not in str(tomb)


def test_reply_one_level_and_anchor_inheritance(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    actor = {"user": "romano", "display": "Romano", "role": "ad_domain"}
    top, err = D.post(actor, "top note", "120000000000000001")
    assert err is None
    rep, err = D.post(actor, "a reply", "board", reply_to=top["id"])
    assert err is None and rep["anchor"] == "120000000000000001"   # rides the parent
    _, err = D.post(actor, "too deep", "board", reply_to=rep["id"])
    assert "one reply level" in err


def test_rate_limit_fires(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    actor = {"user": "inna", "display": "Inna", "role": "ad_domain"}
    for i in range(D._RATE_N):
        _, err = D.post(actor, f"note {i}", "board")
        assert err is None
    _, err = D.post(actor, "one too many", "board")
    assert err and "rate limit" in err


def test_context_stamp_is_server_computed_from_the_engine(monkeypatch):
    _kv_reset(monkeypatch)
    result = _mock_engine(monkeypatch)
    row = next(r for r in result["creatives"] if r["tier"] == "ad")
    actor = {"user": "romano", "display": "Romano", "role": "ad_domain"}
    c, err = D.post(actor, "CPL looks high", row["creative_key"], days=31)
    assert err is None
    st = c["context_stamp"]
    assert st["clock"] == "cohort"
    assert st["window"] == "2026-07-01 → 2026-07-31"
    assert st["metrics"]["leads"] == row["leads"]           # THE engine's numbers
    assert st["metrics"]["cpl"] == row["cost_per_lead"]
    assert st["metrics"]["spend"] == row["spend"]


# ── untrusted text: stored + reflected ───────────────────────────────────────

def test_hostile_bodies_never_render_unescaped():
    js = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
    # every discussion render path escapes: body, author display, stamps,
    # tombstone text, resolution notes
    for needle in ("esc(n.body)", "esc(n.author.display)", "esc(n.created)",
                   "esc(n.tombstone_text", "esc(n.resolved_by", "esc(n.resolution_note)"):
        assert needle in js, needle
    # the stamp chip escapes every bit it renders
    seg = js.split("function stampChip")[1].split("function noteHtml")[0]
    assert "esc(String(b))" in seg


def test_stored_xss_rides_wire_raw_but_feed_never_carries_bodies(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    actor = {"user": "romano", "display": "Romano", "role": "ad_domain"}
    payload = "<img src=x onerror=alert(1)>\"'</script>"
    c, err = D.post(actor, payload, "board")
    assert err is None
    assert c["body"] == payload                 # stored raw (client escapes)
    import kv_store
    items = kv_store.get("feed:extra:ads_discussion") or []
    assert items, "feed items published"
    assert all(payload not in str(i) for i in items)   # bodies never ride the feed
    assert all(i.get("category") == "discussion" for i in items)


# ── EDITH recall (read-only) ─────────────────────────────────────────────────

def test_edith_recall_quotes_with_stamps(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_engine(monkeypatch)
    row_key = next(r["creative_key"] for r in _fake_result()["creatives"] if r["tier"] == "ad")
    actor = {"user": "isaiah", "display": "Isaiah", "role": "ad_domain"}
    D.post(actor, "hook fatigue on this one, CPL creeping", row_key, days=31)
    reply, handled = D.handle_discussion_recall("what has isaiah noted on the ads?")
    assert handled and "Isaiah" in reply
    assert "hook fatigue on this one" in reply
    assert "viewing" in reply and "2026-07-01" in reply     # the stamp rides
    # nothing matched → honest empty
    reply2, handled2 = D.handle_discussion_recall("has inna commented on the creatives?")
    assert handled2 and "No open discussion notes" in reply2
    # unrelated text → not handled (the model answers)
    _, handled3 = D.handle_discussion_recall("what's our cash position?")
    assert handled3 is False
    # edith context digest carries the quote + stamp too
    ctx = D.edith_context()
    assert "hook fatigue" in ctx and "viewing:" in ctx


# ── previews: states honest, never a dead link ───────────────────────────────

def test_preview_states_link_deleted_pending():
    import launch_lineage as LL
    es = {"ads": {"111": {"preview_link": "https://fb.me/x", "effective_status": "ACTIVE"},
                  "222": {"effective_status": "PAUSED"}},
          "extras": {}}
    assert LL._preview(["111"], es) == {"preview_link": "https://fb.me/x",
                                        "preview_state": "link"}
    assert LL._preview(["222"], es)["preview_state"] == "pending"
    assert LL._preview(["999"], es)["preview_state"] == "deleted"   # not listed → chip
    js = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
    assert "ad deleted · no preview available" in js
    assert 'esc(lin.preview_link)' in js                             # href escaped
