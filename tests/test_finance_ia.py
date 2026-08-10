"""
tests/test_finance_ia.py — FINANCE DASHBOARD IA (2026-08-10): summarize, don't
dump. The worklog + bookkeeping queue leave the dashboard scroll and become
live summary cards; each gets a dedicated URL-addressable page.

Contracts under test: card == page counts (ONE engine, no parallel counting) ·
active-first / completed-collapsed defaults · auth inherited exactly (owner in;
ad_domain + sales OUT; anon walled) · layout reflow (the heavy sections are
gone from the template; the zone map carries the cards).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import collab
from helpers import today_sydney

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _entry(eid, kind, body, days_ago=0, parent=None, author="piolo"):
    d = today_sydney() - dt.timedelta(days=days_ago)
    return {"id": eid, "kind": kind, "body": body, "author": author,
            "parent_id": parent, "created_at": f"{d}T09:00:00", "archived": False}


# ── worklog semantics: active = un-replied raises; done collapsed ────────────

def test_worklog_active_first_semantics(monkeypatch):
    monkeypatch.setattr(collab, "list_entries", lambda **kw: [
        _entry(1, "done", "reconciled May"),
        _entry(2, "done", "chased invoices"),
        _entry(3, "concern", "3 clients look churned", days_ago=5),      # overdue
        _entry(4, "question", "is the BAS set-aside right?", days_ago=1),
        _entry(5, "suggestion", "batch the Wise payouts", days_ago=2),
        _entry(6, "reply", "yes it is", parent=4, author="rydel"),       # answers #4
    ])
    d = collab.worklog_page_data()
    active_ids = [e["id"] for e in d["active"]]
    assert active_ids == [3, 5]                     # overdue first, replied gone
    assert d["counts"] == {"active": 2, "overdue": 1, "completed": 3}
    assert d["active"][0]["overdue"] is True and d["active"][0]["age_days"] == 5
    # the answered question moved to completed (handled work), reply attached
    ans = next(e for e in d["completed"] if e["id"] == 4)
    assert ans["replied"] is True and ans["replies"][0]["body"] == "yes it is"


def test_worklog_overdue_boundary_today_sydney(monkeypatch):
    monkeypatch.setattr(collab, "list_entries", lambda **kw: [
        _entry(1, "concern", "exactly at boundary", days_ago=3),
        _entry(2, "concern", "past boundary", days_ago=4),
    ])
    d = collab.worklog_page_data()
    by = {e["id"]: e for e in d["active"]}
    assert by[1]["overdue"] is False                # 3d = at, not past
    assert by[2]["overdue"] is True


def test_worklog_summary_equals_page_counts(monkeypatch):
    """The card is DERIVED from the page generator — equality by construction,
    asserted anyway (the anti-parallel-counting guard)."""
    monkeypatch.setattr(collab, "list_entries", lambda **kw: [
        _entry(1, "done", "x"), _entry(2, "concern", "y", days_ago=6),
        _entry(3, "question", "z"),
    ])
    page = collab.worklog_page_data()
    card = collab.worklog_summary()
    assert card["active"] == page["counts"]["active"] == 2
    assert card["overdue"] == page["counts"]["overdue"] == 1
    assert card["completed"] == page["counts"]["completed"] == 1
    assert card["most_urgent"]["body"].startswith("y")    # oldest overdue leads


# ── route-level: card == page, live, through the actual endpoints ────────────

def _owner_client(monkeypatch):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    monkeypatch.setenv("RYDEL_PASSWORD", "rp")
    from app import app
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/dashboard/login",
                  data={"username": "rydel", "password": "rp"}).status_code == 302
    return c


def test_ops_summary_card_equals_queue_page_count(monkeypatch):
    from tests.test_piolo_queue import _rig, _item
    fdb, holder, _ = _rig(monkeypatch, [
        _item("Vipin: won but Close Date blank (contract 12500.0)"),
        _item("5 Active client(s) with $0 MRR: Masala Factory"),
    ])
    monkeypatch.setattr(collab, "list_entries", lambda **kw: [
        _entry(1, "concern", "open raise", days_ago=1)])
    c = _owner_client(monkeypatch)
    card = c.get("/dashboard/api/ops-summary").get_json()
    page_q = c.get("/dashboard/api/collab/queue").get_json()["queue"]
    page_active = sum(1 for i in page_q if i["lane"] == "active")
    assert card["bookkeeping"]["active"] == page_active == 2      # EXACT equality
    page_wl = c.get("/dashboard/api/worklog").get_json()
    assert card["worklog"]["active"] == page_wl["counts"]["active"] == 1


# ── auth inheritance: owner in, scoped roles OUT, anon walled ────────────────

def test_pages_owner_in_scoped_roles_out(monkeypatch):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    monkeypatch.setenv("RYDEL_PASSWORD", "rp")
    monkeypatch.setenv("SALES_PASSWORD", "sp")
    monkeypatch.setenv("MEDIA_BUYER_PASSWORD", "mbp")   # Romano / ad_domain (#136)
    from app import app
    app.config["TESTING"] = True
    # owner reaches both pages + APIs
    c = app.test_client()
    c.post("/dashboard/login", data={"username": "rydel", "password": "rp"})
    assert c.get("/dashboard/worklog").status_code == 200
    assert c.get("/dashboard/bookkeeping").status_code == 200
    assert c.get("/dashboard/worklog").status_code == 200          # URL round-trip
    # ad_domain (romano) is fail-closed OUT of every finance surface
    r_cli = app.test_client()
    assert r_cli.post("/dashboard/login",
                      data={"username": "romano", "password": "mbp"}).status_code == 302
    for path in ("/dashboard/worklog", "/dashboard/bookkeeping",
                 "/dashboard/api/ops-summary", "/dashboard/api/worklog"):
        resp = r_cli.get(path)
        assert resp.status_code in (302, 403), f"ad_domain leaked into {path}"
        if resp.status_code == 302:
            assert "/ads" in resp.headers.get("Location", ""), path
    # sales likewise
    s_cli = app.test_client()
    assert s_cli.post("/dashboard/login",
                      data={"username": "sales", "password": "sp"}).status_code == 302
    for path in ("/dashboard/worklog", "/dashboard/bookkeeping"):
        assert s_cli.get(path).status_code in (302, 403), f"sales leaked into {path}"
    # anon
    a_cli = app.test_client()
    for path in ("/dashboard/worklog", "/dashboard/bookkeeping",
                 "/dashboard/api/ops-summary"):
        assert a_cli.get(path).status_code in (302, 401), path


# ── layout reflow + default-view contracts (structural) ──────────────────────

def test_dashboard_no_longer_dumps_the_lists():
    html = open(os.path.join(ROOT, "dashboard", "templates", "dashboard.html")).read()
    assert "section-collab-queue" not in html          # the dumps are GONE
    assert "collab-log-body" not in html
    assert "section-ops-cards" in html                 # the cards are in
    assert 'href="/dashboard/worklog"' in html and 'href="/dashboard/bookkeeping"' in html
    js = open(os.path.join(ROOT, "dashboard", "static", "js", "dashboard.js")).read()
    assert "'section-ops-cards'" in js                 # zone map carries the cards
    assert "'section-collab-queue'" not in js
    assert "renderOpsCards()" in js


def test_pages_default_views_are_active_first():
    wl = open(os.path.join(ROOT, "dashboard", "templates", "worklog.html")).read()
    # completed is present but NOT the default render (excluded ≠ deleted)
    assert 'id="wl-completed" style="display:none"' in wl
    assert "Show completed" in wl
    assert "← Dashboard" in wl                         # back affordance
    bk = open(os.path.join(ROOT, "dashboard", "templates", "bookkeeping.html")).read()
    assert "lane === 'active'" in bk or 'lane === "active"' in bk.replace("'", '"')
    assert "aged / irrelevant" in bk and "← Dashboard" in bk
