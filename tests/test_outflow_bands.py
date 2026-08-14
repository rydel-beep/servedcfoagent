"""
tests/test_outflow_bands.py — OUTFLOW TRUTH (Part A) + STRIPE HEALTH (Part B).

A: account-code-primary classification (a tax account with a misleading
payee-looking name still bands by ACCOUNT; a payee keyword alone never flips
a band) · I-OUTFLOW partition · FLAGGED never silently assigned · one-click
assign journaled + reversible · burn excludes tax/personal (the June $26.5k
class) · EDITH answers unblended · access.
B: canary classification (auth/scope/rate-limit/service-down/no-key) · the
overlay replaces MCP miscounts + retires the artifact mismatch flag while a
REAL mismatch still flags (F5 loudness preserved).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import outflow_bands as OB
import stripe_health as SH


def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


# ── A1: the classifier — account-primary, never keyword-first ───────────────

def test_org_chart_accounts_band_correctly(monkeypatch):
    _kv_reset(monkeypatch)
    assert OB.classify_account("Income Tax Expense") == ("tax_statutory",
                                                         "org chart of accounts")
    assert OB.classify_account("Personal Expense")[0] == "personal"
    assert OB.classify_account("Advertising")[0] == "opex"
    assert OB.classify_account("Superannuation")[0] == "opex"   # real cost — veto-noted
    assert OB.classify_account("Wages and Salaries")[0] == "opex"


def test_account_primary_never_payee_keyword(monkeypatch):
    """The classifier reads LEDGER ACCOUNT names only. An OpEx account whose
    name happens to contain a payee-ish word stays where the CHART puts it;
    an unknown account with a tax-token NAME goes to tax (account-name signal,
    still not a payee); a plain unknown account is FLAGGED, never guessed."""
    _kv_reset(monkeypatch)
    # 'Consulting & Accounting' contains 'accounting' — chart says OPEX; no
    # keyword rule may move it
    assert OB.classify_account("Consulting & Accounting")[0] == "opex"
    # unknown account whose NAME is a tax account → tax band (ledger signal)
    band, basis = OB.classify_account("ATO Integrated Client Account")
    assert band == "tax_statutory" and "account name" in basis
    # a genuinely unknown account → FLAGGED, stated
    band2, basis2 = OB.classify_account("Mystery Widget Costs")
    assert band2 == "flagged" and "never silently assigned" in basis2


def test_partition_invariant_i_outflow(monkeypatch):
    _kv_reset(monkeypatch)
    lines = [{"label": "Advertising", "amount": 10197.36},
             {"label": "Income Tax Expense", "amount": 26553.75},
             {"label": "Personal Expense", "amount": 129.48},
             {"label": "Mystery Widget Costs", "amount": 500.0},
             {"label": "Wages and Salaries", "amount": 11165.0}]
    b = OB.band_line_items(lines)
    assert b["partition"]["ok"] is True
    total = round(sum(l["amount"] for l in lines), 2)
    assert b["partition"]["total"] == total
    assert round(sum(b["bands"].values()), 2) == total     # sum of bands == reality
    assert b["bands"]["tax_statutory"] == 26553.75
    assert b["bands"]["personal"] == 129.48
    assert b["bands"]["flagged"] == 500.0


def test_june_restatement_the_witnessed_skew(monkeypatch):
    """The payoff: June 2026's blended $95,861.08 OpEx restates to
    $69,307.33 OpEx + $26,553.75 tax — classification, not a data change."""
    _kv_reset(monkeypatch)
    june = [{"label": "Income Tax Expense", "amount": 26553.75},
            {"label": "Advertising", "amount": 8111.11},
            {"label": "Contractors NO GST", "amount": 22529.40},
            {"label": "Wages and Salaries", "amount": 8964.00},
            {"label": "Closer Commission", "amount": 7900.00},
            {"label": "Refunds and Rebates Expense", "amount": 7645.00},
            {"label": "Client Reporting Tools", "amount": 5417.63},
            {"label": "Setter Commission", "amount": 3175.90},
            {"label": "Travel - International", "amount": 2998.48},
            {"label": "Superannuation", "amount": 1075.68},
            {"label": "Subscriptions", "amount": 345.08},
            {"label": "Consulting & Accounting", "amount": 156.60},
            {"label": "Telephone & Internet", "amount": 153.64},
            {"label": "Contractors WITH GST REMITTLY", "amount": 754.55},
            {"label": "Motor Vehicle Expenses", "amount": 69.35},
            {"label": "Travel - National", "amount": 9.96},
            {"label": "Bank Fees", "amount": 0.95}]
    b = OB.band_line_items(june)
    assert b["partition"]["total"] == 95861.08              # the blended lie
    assert b["bands"]["tax_statutory"] == 26553.75          # flagged, not hidden
    assert b["bands"]["opex"] == 69307.33                   # the managed truth
    assert b["partition"]["ok"]


def test_flagged_assign_journaled_reversible(monkeypatch):
    store = _kv_reset(monkeypatch)
    assert OB.classify_account("Mystery Widget Costs")[0] == "flagged"
    out, err = OB.assign({"user": "rydel"}, "Mystery Widget Costs", "opex")
    assert err is None
    assert OB.classify_account("Mystery Widget Costs") == ("opex",
                                                           "owner-assigned rule (journaled)")
    j = store["outflow:band_journal"]
    assert j[-1]["who"] == "rydel" and j[-1]["new"] == "opex" \
        and j[-1]["old"] == "flagged"
    # reversible: assigning back to 'flagged' clears the rule, journaled
    OB.assign({"user": "rydel"}, "Mystery Widget Costs", "flagged")
    assert OB.classify_account("Mystery Widget Costs")[0] == "flagged"
    assert store["outflow:band_journal"][-1]["new"] == "flagged"
    # invalid band refused
    assert OB.assign({"user": "rydel"}, "X", "slush_fund")[1]


def test_burn_excludes_tax_and_personal(monkeypatch):
    """The June class: Income Tax Expense no longer inflates recurring burn's
    other_opex; personal is excluded + surfaced. Total burn is tax-free."""
    from opex_pull import get_monthly_burn
    xero = {"opex_line_items": [
        {"label": "Income Tax Expense", "amount": 26553.75},
        {"label": "Personal Expense", "amount": 129.48},
        {"label": "Office Expenses", "amount": 153.74}],
        "cogs_line_items": [], "revenue": 90000, "cogs": 0}
    b = get_monthly_burn(xero, true_team_cost=29671, salary_baseline=18891.0)
    assert b["tax_statutory_excluded"] == 26553.75
    assert b["personal_excluded"] == 129.48
    assert b["other_opex"] == 153.74                       # tax/personal NOT here
    # burn = team + owner + ads(0) + subs + other — no tax inside
    assert b["total_recurring_burn"] == round(
        18891.0 + 6800.0 + 0 + 3867.0 + 153.74, 2)


def test_edith_answers_unblended(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setattr(OB, "monthly_bands", lambda n=3: {
        "months": [{"month": "2026-06", "opex": 69307.33,
                    "tax_statutory": 26553.75, "personal": 0.0,
                    "blended_total": 95861.08, "partition_ok": True,
                    "flagged_items": [], "tax_items": []}],
        "accrual": {"monthly_accrued_share": 4500.0}})
    ans, handled = OB.handle_expense_query("what are our real monthly expenses?")
    assert handled
    assert "$69,307" in ans and "$26,554" in ans           # both stated, separate
    assert "not operating cost" in ans
    assert "planning estimate" in ans                      # accrued labelled
    # the blended number appears only LABELLED as blended
    assert "blended P&L total" in ans


def test_monthly_bands_caches_closed_months(monkeypatch):
    store = _kv_reset(monkeypatch)
    import xero_pull
    calls = []

    def fake_pl(start, end):
        calls.append(start)
        return {"ok": True, "operating_expenses": 100.0,
                "opex_line_items": [{"label": "Advertising", "amount": 100.0}]}
    monkeypatch.setattr(xero_pull, "pull_pl_range", fake_pl)
    monkeypatch.setattr(OB, "_month_windows",
                        lambda n: [("2026-06", "2026-06-01", "2026-06-30"),
                                   ("2026-07", "2026-07-01", "2026-07-31")])
    import helpers
    d1 = OB.monthly_bands(2)
    assert all(r["partition_ok"] for r in d1["months"])
    n_first = len(calls)
    d2 = OB.monthly_bands(2)
    # closed months served from cache; only the current month re-pulls
    assert len(calls) < n_first * 2


# ── access: finance surface ─────────────────────────────────────────────────

def test_outflow_routes_access(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-test-pw")
    monkeypatch.setenv("ROMANO_PASSWORD", "romano-test-pw")
    monkeypatch.setattr(OB, "monthly_bands", lambda n=6: {"months": [],
                                                          "accrual": {}})
    from app import app
    app.config["TESTING"] = True

    def login(u):
        c = app.test_client()
        assert c.post("/dashboard/login", data={"username": u,
                                                "password": f"{u}-test-pw"}).status_code == 302
        return c
    assert login("rydel").get("/dashboard/api/outflow-bands").status_code == 200
    r = login("romano").get("/dashboard/api/outflow-bands")
    assert r.status_code in (302, 403)                     # ad_domain walled
    anon = app.test_client()
    assert anon.get("/dashboard/api/outflow-bands").status_code in (302, 401)
    assert login("romano").post("/dashboard/api/outflow-bands/assign",
                                json={"account": "x", "band": "opex"}).status_code in (302, 403)


# ── Part B: the canary + the overlay ────────────────────────────────────────

def _mock_sget(monkeypatch, status=200, body=None, err=None):
    monkeypatch.setattr(SH, "_sget", lambda path, params=None: (status, body or {"data": []}, err))


def test_canary_classifications(monkeypatch):
    _kv_reset(monkeypatch)
    _mock_sget(monkeypatch, 200, {"data": [{}]})
    assert SH.canary_probe()["ok"] is True
    _mock_sget(monkeypatch, 401, {"error": {"message": "Invalid API Key"}})
    c = SH.canary_probe()
    assert c["cls"] == "auth" and "STRIPE_SECRET_KEY" in c["fix"] \
        and "never minted" in c["fix"]
    _mock_sget(monkeypatch, 403, {"error": {"message": "scope"}})
    assert SH.canary_probe()["cls"] == "scope"
    _mock_sget(monkeypatch, 429, {"error": {"message": "rate"}})
    assert SH.canary_probe()["cls"] == "rate_limit"
    _mock_sget(monkeypatch, 503, {})
    assert SH.canary_probe()["cls"] == "service_down"
    monkeypatch.setattr(SH, "_sget",
                        lambda p, q=None: (None, None, "no key configured"))
    assert SH.canary_probe()["cls"] == "no_key"


def test_canary_failure_is_loud_and_self_retiring(monkeypatch):
    store = _kv_reset(monkeypatch)
    _mock_sget(monkeypatch, 401, {"error": {"message": "bad key"}})
    SH.canary_probe()
    items = store["feed:extra:stripe"]
    assert items and items[0]["severity"] == "S1" and "auth" in items[0]["title"]
    _mock_sget(monkeypatch, 200, {"data": []})
    SH.canary_probe()
    assert store["feed:extra:stripe"] == []                # self-retired on OK


def test_overlay_replaces_miscounted_subs_and_retires_artifact_flag(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setattr(SH, "subscriptions_direct",
                        lambda: {"active": 24, "past_due": 1, "cancelled": 3,
                                 "trialing": None,
                                 "source": "stripe_direct (restricted key, read-only)"})
    monkeypatch.setattr(SH, "failed_charges_direct", lambda days=30: 3)
    block = {"mrr": 59316.0, "subscriptions": {"active": 1, "past_due": 1,
                                               "cancelled": 1, "trialing": 0},
             "failed_charges_count": 21}
    degraded = [{"metric": "stripe_mrr_subs_mismatch",
                 "reason": "MRR $59,316 with only 1 active sub(s)"},
                {"metric": "customer_count", "reason": "proxy"}]
    SH.overlay(block, degraded)
    assert block["subscriptions"]["active"] == 24          # the direct truth
    assert block["subscriptions_mcp"]["active"] == 1       # kept for audit
    assert block["failed_charges_count"] == 3
    assert block["failed_charges_mcp"] == 21
    # $59,316 / 24 subs ≈ $2.5k/sub — the artifact flag retires...
    assert not any(d["metric"] == "stripe_mrr_subs_mismatch" for d in degraded)
    # ...but the unrelated degraded entry SURVIVES (F5 never softened)
    assert any(d["metric"] == "customer_count" for d in degraded)


def test_overlay_keeps_real_mismatch_loud(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setattr(SH, "subscriptions_direct",
                        lambda: {"active": 2, "past_due": 0, "cancelled": 0,
                                 "trialing": None, "source": "stripe_direct"})
    monkeypatch.setattr(SH, "failed_charges_direct", lambda days=30: None)
    block = {"mrr": 59316.0, "subscriptions": {"active": 1},
             "failed_charges_count": 21}
    degraded = [{"metric": "stripe_mrr_subs_mismatch", "reason": "old"}]
    SH.overlay(block, degraded)
    # $59,316 / 2 subs = $29.7k/sub — STILL implausible → the flag survives,
    # re-worded against the DIRECT count
    surviving = [d for d in degraded if d["metric"] == "stripe_mrr_subs_mismatch"]
    assert surviving and "DIRECT" in surviving[0]["reason"]
    # failed overlay unavailable → the MCP number stays untouched
    assert block["failed_charges_count"] == 21


def test_scope_denied_keeps_mcp_with_note(monkeypatch):
    _kv_reset(monkeypatch)
    monkeypatch.setattr(SH, "subscriptions_direct", lambda: None)   # scope denied
    monkeypatch.setattr(SH, "failed_charges_direct", lambda days=30: None)
    block = {"mrr": 100.0, "subscriptions": {"active": 1},
             "failed_charges_count": 21}
    degraded = []
    SH.overlay(block, degraded)
    assert block["subscriptions"] == {"active": 1}          # MCP value kept
    assert "subscriptions_source" not in block              # no false labelling
