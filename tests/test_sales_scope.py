"""
Sales-role scoping — fail-closed allowlist. The sales session must reach ONLY the reactivation
surface; every financial/admin endpoint must be denied, and unknown paths denied BY DEFAULT.
"""
import os
import importlib

import dashboard.auth as auth


def test_sales_permitted_allows_only_reactivation_surface():
    allow = [
        "/dashboard/leads",
        "/dashboard/leads/",
        "/dashboard/logout",
        "/dashboard/api/reactivation",
        "/dashboard/api/reactivation/export.csv",
        "/dashboard/api/reactivation/brief.pdf",
        "/dashboard/api/lead-lookup",
        "/dashboard/api/whoami",
    ]
    for p in allow:
        assert auth.sales_permitted(p), f"sales should reach {p}"


def test_sales_denied_all_financial_and_admin_endpoints():
    deny = [
        "/dashboard/",                       # the full financial dashboard shell
        "/dashboard/api/snapshot",
        "/dashboard/api/quarterly-pack",
        "/dashboard/api/quarterly-review",
        "/dashboard/api/unit-economics",
        "/dashboard/api/payback",
        "/dashboard/api/targets",
        "/dashboard/api/targets/set",
        "/dashboard/api/collab/log",
        "/dashboard/api/collab/queue",
        "/dashboard/api/memory-status",
        "/dashboard/api/forecast",
        "/dashboard/api/capacity",
        "/dashboard/api/chat",               # chat carries the financial snapshot as context
        "/dashboard/api/briefing-pdf",
        "/dashboard/api/ghl-backfill",
        "/dashboard/api/data-sources",
        "/dashboard/api/some-future-endpoint",   # fail-closed: unknown paths denied by default
    ]
    for p in deny:
        assert not auth.sales_permitted(p), f"sales must NOT reach {p}"


def test_sales_account_enabled_only_with_password(monkeypatch):
    monkeypatch.setenv("SALES_PASSWORD", "sekret-team-pw")
    accts = auth._accounts()
    assert "sales" in accts and accts["sales"]["role"] == "sales"
    got = auth.verify_login("sales", "sekret-team-pw")
    assert got and got["role"] == "sales" and got["display"] == "Sales Team"
    assert auth.verify_login("sales", "wrong") is None


def test_no_sales_account_without_password(monkeypatch):
    monkeypatch.delenv("SALES_PASSWORD", raising=False)
    assert "sales" not in auth._accounts()
