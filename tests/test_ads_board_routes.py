"""
tests/test_ads_board_routes.py — BOARD v2 route layer.

ACCESS: ad_domain moves + stances allowed and attributed · reversal
owner-only · rules edits owner/coo only · finance walled unchanged · anon
locked · the board is /ads (?view=board is client-side — same route, same
wall). DECISION LOOP over HTTP: blank reason 400 · friction 409 · journal +
feed. STRUCTURE: the board payload carries the lifecycle block + the
consolidated kill cards; card numbers are THE scoreboard rows (view parity
by construction — no second endpoint exists). TAINT: stance whitelist at the
boundary; hostile bodies never echo unescaped from the new endpoints.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import ads_lifecycle as L
from tests.test_ads_lifecycle import mk_row, _row_sufficient, ST_LIVE


def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


def _team_client(monkeypatch):
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    monkeypatch.setenv("PIOLO_PASSWORD", "piolo-test-pw")
    monkeypatch.setenv("ROMANO_PASSWORD", "romano-test-pw")
    monkeypatch.setenv("ISAIAH_PASSWORD", "isaiah-test-pw")
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def _login(c, user):
    r = c.post("/dashboard/login", data={"username": user, "password": f"{user}-test-pw"})
    assert r.status_code == 302, f"{user} login failed"


def _mock_lifecycle(monkeypatch, rows=None):
    rows = rows if rows is not None else [_row_sufficient()]
    monkeypatch.setattr("dashboard.ads._all_time_creatives",
                        lambda basis: (rows, {}), raising=True)
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {"x": {}}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    return rows


# ── the board payload carries the lifecycle block + kill cards ───────────────

def test_board_payload_carries_lifecycle_and_kill_cards(monkeypatch):
    _kv_reset(monkeypatch)
    rows = _mock_lifecycle(monkeypatch, [
        mk_row(key="120000000000000001", leads=0, spend=250, active_days=2,
               label="Rot Kill")])
    from tests.test_ads_dashboard import _fake_result
    result = _fake_result()
    monkeypatch.setattr("attribution_engine.compute", lambda **kw: result, raising=True)
    monkeypatch.setattr("dashboard.ads._serve_board",
                        lambda *a, **k: {"window": result["window"], "basis": "cohort",
                                         "scoreboard": {"rows": []},
                                         "scorecard": {"flags": [{"kind": "other",
                                                                  "severity": 2}]},
                                         "stale": False}, raising=True)
    c = _team_client(monkeypatch)
    _login(c, "romano")
    d = c.get("/ads/api/board?days=30").get_json()
    lc = d["lifecycle"]
    assert lc["rules"]["test_days"] == 4 and lc["rules"]["test_spend"] == 200.0
    card = lc["cards"]["120000000000000001"]
    assert card["lane"] == "kill_candidate" and card["kill_basis"] == "rotation"
    assert card["status"]["status"] == "delivering"
    assert card["rotation"]["label"].startswith("day 2")
    # consolidated kill cards ride the scorecard, prepended, deep-linking
    kinds = [f["kind"] for f in d["scorecard"]["flags"]]
    assert kinds[0] == "rotation_kill_candidate" and "other" in kinds
    # idempotent across serves (rollup payloads are reused objects)
    d2 = c.get("/ads/api/board?days=30").get_json()
    assert [f["kind"] for f in d2["scorecard"]["flags"]].count("rotation_kill_candidate") == 1


# ── decision loop over HTTP ──────────────────────────────────────────────────

def test_move_http_blank_reason_400_then_journal_feed(monkeypatch):
    store = _kv_reset(monkeypatch)
    _mock_lifecycle(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "romano")
    r = c.post("/ads/api/lifecycle/move",
               json={"creative": "120000000000000001", "to": "kill", "reason": "  "})
    assert r.status_code == 400 and "reason" in r.get_json()["error"]
    r2 = c.post("/ads/api/lifecycle/move",
                json={"creative": "120000000000000001", "to": "kill",
                      "reason": "CPL 3x the account"})
    assert r2.status_code == 200
    dec = r2.get_json()["decision"]
    assert dec["by"] == "romano" and dec["state"] == "marked_to_kill"
    assert store["ads:lifecycle:journal"][-1]["reason"] == "CPL 3x the account"
    assert "CPL 3x the account" in store["feed:extra:ads_decisions"][0]["title"]


def test_move_http_friction_below_min_n(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_lifecycle(monkeypatch, [mk_row(leads=2, spend=250, active_days=3)])
    c = _team_client(monkeypatch)
    _login(c, "isaiah")
    r = c.post("/ads/api/lifecycle/move",
               json={"creative": "120000000000000001", "to": "kill", "reason": "r"})
    assert r.status_code == 409 and r.get_json()["friction"]
    r2 = c.post("/ads/api/lifecycle/move",
                json={"creative": "120000000000000001", "to": "kill", "reason": "r",
                      "confirm_below_min_n": True})
    assert r2.status_code == 200 and r2.get_json()["decision"]["below_min_n"]


def test_reverse_owner_only(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_lifecycle(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "romano")
    c.post("/ads/api/lifecycle/move",
           json={"creative": "120000000000000001", "to": "kill", "reason": "r"})
    r = c.post("/ads/api/lifecycle/reverse",
               json={"creative": "120000000000000001", "reason": "undo"})
    assert r.status_code == 403                      # mover ≠ owner
    c2 = _team_client(monkeypatch)
    _login(c2, "rydel")
    r2 = c2.post("/ads/api/lifecycle/reverse",
                 json={"creative": "120000000000000001", "reason": ""})
    assert r2.status_code == 400                     # reason required on reversal
    r3 = c2.post("/ads/api/lifecycle/reverse",
                 json={"creative": "120000000000000001", "reason": "changed call"})
    assert r3.status_code == 200


def test_move_unknown_creative_404_and_anon_locked(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_lifecycle(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "romano")
    assert c.post("/ads/api/lifecycle/move",
                  json={"creative": "999999999999", "to": "kill",
                        "reason": "r"}).status_code == 404
    anon = _team_client(monkeypatch)
    for p, j in (("/ads/api/lifecycle/move", {}), ("/ads/api/lifecycle/reverse", {}),
                 ("/ads/api/rotation-rules", None)):
        r = anon.post(p, json=j or {}) if j is not None else anon.get(p)
        assert r.status_code in (302, 401), p


# ── rules panel over HTTP (R-A) ──────────────────────────────────────────────

def test_rules_get_all_roles_edit_owner_coo_only(monkeypatch):
    _kv_reset(monkeypatch)
    c = _team_client(monkeypatch)
    _login(c, "romano")
    d = c.get("/ads/api/rotation-rules").get_json()
    assert d["rules"]["test_days"] == 4 and "R-A" in d["ruling"]
    r = c.post("/ads/api/rotation-rules", json={"test_spend": 300})
    assert r.status_code == 403                      # ad_domain can't edit a ruling's params
    c2 = _team_client(monkeypatch)
    _login(c2, "piolo")                              # coo can
    r2 = c2.post("/ads/api/rotation-rules", json={"test_spend": 300})
    assert r2.status_code == 200
    j = r2.get_json()["journal"]
    assert j[-1]["who"] == "piolo" and j[-1]["old"] == 200.0 and j[-1]["new"] == 300.0


# ── stance boundary (taint + attribution) ────────────────────────────────────

def test_stance_whitelist_at_boundary_and_attribution(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setattr("ads_discussion.context_stamp", lambda *a, **k: {"at": "t"})
    c = _team_client(monkeypatch)
    _login(c, "isaiah")
    evil = "<img src=x onerror=alert(1)>"
    r = c.post("/ads/api/discussion?days=30",
               json={"body": "x", "anchor": "120000000000000001", "stance": evil})
    assert r.status_code == 400                      # whitelist — taint impossible
    r2 = c.post("/ads/api/discussion?days=30",
                json={"body": evil, "anchor": "120000000000000001", "stance": "kill",
                      "author": "rydel"})            # author param ignored by construction
    assert r2.status_code == 200
    note = r2.get_json()["note"]
    assert note["author"]["user"] == "isaiah" and note["stance"] == "kill"
    # the hostile body rides the wire raw (client esc()s at render) and NEVER
    # lands in the feed titles or the stance summary
    import ads_discussion as D
    s = D.stances_by_anchor()["120000000000000001"]
    assert s["by"]["isaiah"] == "kill"
    import kv_store
    for it in kv_store.get("feed:extra:ads_discussion") or []:
        assert evil not in (it.get("title") or "")


def test_move_dialog_data_shows_opinions(monkeypatch):
    """R-C: the move dialog reads /api/discussion for the card — the SAME
    store — so the decider sees stances + notes before confirming."""
    _kv_reset(monkeypatch)
    monkeypatch.setattr("ads_discussion.context_stamp", lambda *a, **k: {"at": "t"})
    c = _team_client(monkeypatch)
    _login(c, "isaiah")
    c.post("/ads/api/discussion?days=30",
           json={"body": "CPL is triple", "anchor": "120000000000000001",
                 "stance": "kill"})
    c2 = _team_client(monkeypatch)
    _login(c2, "romano")
    d = c2.get("/ads/api/discussion?creative=120000000000000001").get_json()
    assert d["notes"][0]["stance"] == "kill"
    assert d["notes"][0]["author"]["user"] == "isaiah"
    assert "CPL is triple" in d["notes"][0]["body"]
