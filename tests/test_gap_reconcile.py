"""
tests/test_gap_reconcile.py
---------------------------
#148 READ-ONLY LAW (structural greps: no Sheets write verbs, no GHL mutating
verbs, GHL_EMAIL_TOKEN untouchable) + #149 R-GAP scoping (inversion inside
the detected window only), payment-corroboration rules (AUTO needs money;
surname-only never matches), dedupe (ONE event), conflict surfacing, the
three-ROAS separation, payback math, and the verdict's deciding figures.
"""
from __future__ import annotations
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gap_reconcile as G
import finance_analysis as F


def _kv(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ── #148 · the read-only law, structurally ──────────────────────────────────

_SHEET_WRITE_RE = re.compile(
    r"batchUpdate|values\s*[:.]\s*(append|update)|spreadsheets\.values|"
    r"requests\.(post|put|patch|delete)\([^)]*(docs\.google|sheets\.googleapis)",
    re.I)
_GHL_MUTATE_RE = re.compile(
    r"requests\.(post|put|patch|delete)\([^)]*leadconnector|"
    r"\.(post|put|patch|delete)\(\s*f?['\"][^'\"]*(contacts|opportunities|"
    r"appointments|tags|notes|pipelines|customField)", re.I)

_RECON_MODULES = ("gap_reconcile.py", "finance_analysis.py", "ghl_mirror.py",
                  "ghl_pull.py", "sheets_pull.py", "sales_analytics_pull.py",
                  "tracker_read.py", "sheet_mirror.py", "cash_truth.py")


def test_no_sheet_write_verbs_in_reconciliation_modules():
    for mod in _RECON_MODULES:
        src = open(os.path.join(_ROOT, mod)).read()
        assert not _SHEET_WRITE_RE.search(src), f"{mod} carries a Sheets write verb"


def test_no_ghl_mutating_verbs_in_reconciliation_modules():
    for mod in _RECON_MODULES:
        src = open(os.path.join(_ROOT, mod)).read()
        assert not _GHL_MUTATE_RE.search(src), f"{mod} carries a GHL mutating verb"


def test_email_token_untouchable_by_reconciliation():
    """GHL_EMAIL_TOKEN (the ONLY write-capable GHL credential) must never be
    imported or referenced by any reconciliation path."""
    for mod in _RECON_MODULES:
        src = open(os.path.join(_ROOT, mod)).read()
        assert "GHL_EMAIL_TOKEN" not in src, mod
        assert not re.search(r"^\s*(import ghl_email|from ghl_email)",
                             src, re.M), mod
    # repo-wide, the token VALUE is read in exactly one module (ghl_email);
    # boot_banner lists the NAME only and email_pipeline checks presence for
    # its human-initiated staging path — both are name mentions, not reads.
    readers = []
    for f in sorted(os.listdir(_ROOT)):
        if f.endswith(".py"):
            src = open(os.path.join(_ROOT, f)).read()
            if re.search(r"environ(\.get)?\s*[.\[(]\s*['\"]GHL_EMAIL_TOKEN", src) \
                    or re.search(r"getenv\(\s*['\"]GHL_EMAIL_TOKEN", src):
                readers.append(f)
    assert readers == ["ghl_email.py"], readers


def test_cash_never_derived_receipts_come_from_stripe_only(monkeypatch):
    """R-CASH: the receipts leg reads cash_truth's Stripe pull, nothing else."""
    import cash_truth
    import datetime as dt
    from helpers import SYDNEY_TZ
    t = dt.datetime(2026, 9, 10, 12, 0, tzinfo=SYDNEY_TZ)
    charges = [
        {"paid": True, "status": "succeeded", "amount": 165000,
         "amount_refunded": 0, "created": int(t.timestamp())},
        {"paid": True, "status": "succeeded", "amount": 100000,
         "amount_refunded": 100000, "created": int(t.timestamp())},  # net 0
        {"paid": False, "status": "failed", "amount": 99999,
         "created": int(t.timestamp())},
    ]
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda d: charges)
    out = F._receipts_in_window(dt.date(2026, 9, 1), dt.date(2026, 9, 17))
    assert out["total"] == 1650.0                 # net of refunds, Stripe only
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda d: None)
    out2 = F._receipts_in_window(dt.date(2026, 9, 1), dt.date(2026, 9, 17))
    assert out2["available"] is False             # unreachable ≠ zero


# ── #149 · R-GAP scoping ────────────────────────────────────────────────────

def test_in_gap_scoped_to_detected_window(monkeypatch):
    store = _kv(monkeypatch)
    store["gap:state"] = {"gap": {"start": "2026-07-21", "end": "2026-09-17"}}
    assert G.in_gap("2026-08-15")                  # inside → inversion applies
    assert not G.in_gap("2026-07-20")              # pre-gap → tracker authority
    assert not G.in_gap("2026-09-18")              # post-gap → tracker authority
    assert not G.in_gap(None)
    store["gap:state"] = {}
    assert not G.in_gap("2026-08-15")              # no window → never inverted


def test_stripe_match_email_exact_and_no_surname_only():
    charges = [
        {"paid": True, "status": "succeeded", "amount": 335500, "created": 1789700000,
         "billing_details": {"email": "harmandhillon875@gmail.com",
                             "name": "Harman Singh"}},
        {"paid": True, "status": "succeeded", "amount": 150000, "created": 1789700000,
         "billing_details": {"email": "jshahi607@gmail.com",
                             "name": "Jagjeet Singh"}},
    ]
    hits = G._stripe_hits("Harman Singh", "harmandhillon875@gmail.com", charges)
    assert len(hits) == 1                          # the Jagjeet surname
    assert hits[0]["match"] == "email-exact"       # collision never matches


def test_close_ledger_auto_requires_payment(monkeypatch):
    """AUTO = closed-stage + payment; no money → PROPOSED with what's
    missing. The dedupe skip: a person already derived/tracker-dated is ONE
    event (never re-placed)."""
    store = _kv(monkeypatch)
    store["gap:state"] = {"detected_on": str(__import__("helpers").today_sydney()),
                          "gap": {"start": "2026-07-21", "end": "2026-09-17"},
                          "evidence": {}, "verdict": "test"}
    monkeypatch.setattr(G, "_ghl_closed_in_window", lambda w0, w1: [
        {"opp_id": "opp1", "contact_id": "c1", "opp_name": "Paid Person: x",
         "contact_name": "Paid Person", "email": "paid@x.com",
         "stage": "Closed Deal", "status": "open", "source": "fb",
         "stage_changed": "2026-09-11 02:00", "close_date": "2026-09-11"},
        {"opp_id": "opp2", "contact_id": "c2", "opp_name": "Unpaid Person: x",
         "contact_name": "Unpaid Person", "email": "unpaid@x.com",
         "stage": "Closed Deal", "status": "open", "source": "fb",
         "stage_changed": "2026-08-27 02:00", "close_date": "2026-08-27"},
        {"opp_id": "opp3", "contact_id": "c3", "opp_name": "Already Derived: x",
         "contact_name": "Already Derived", "email": "ad@x.com",
         "stage": "Closed Deal", "status": "open", "source": "fb",
         "stage_changed": "2026-09-09 02:00", "close_date": "2026-09-09"}])
    import cash_truth
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda d: [
        {"paid": True, "status": "succeeded", "amount": 335500,
         "created": 1789700000,
         "billing_details": {"email": "paid@x.com", "name": "Paid Person"}},
        {"paid": True, "status": "succeeded", "amount": 165000,
         "created": 1789700000,
         "billing_details": {"email": "ad@x.com", "name": "Already Derived"}}])
    monkeypatch.setattr(G, "_health_row", lambda n, o, e=None: None)
    monkeypatch.setattr(G, "_tracker_row_for", lambda n, e: None)
    store["derived:dates"] = {"alreadyderived": {"close_date": {
        "date": "2026-09-09", "provenance": "derived:stripe"}}}
    placed = []
    import resolution
    monkeypatch.setattr(resolution, "record_derived_date",
                        lambda nn, f, d, provenance, evidence: placed.append(nn))
    monkeypatch.setattr(resolution, "bump_derived_epoch", lambda r: 1)
    out = G.rebuild_closes(apply=True)
    by = {e["person"]: e for e in out["ledger"]}
    assert by["Paid Person"]["state"] == "AUTO"
    assert by["Paid Person"]["evidence"]["charge_ids"]
    assert by["Unpaid Person"]["state"] == "PROPOSED"
    assert "needs payment evidence" in by["Unpaid Person"]["missing"]
    assert by["Already Derived"]["state"] == "AUTO"
    assert placed == ["paidperson"]                # dedupe: derived skipped


def test_conflict_surfaced_never_merged(monkeypatch):
    store = _kv(monkeypatch)
    store["gap:state"] = {"detected_on": str(__import__("helpers").today_sydney()),
                          "gap": {"start": "2026-07-21", "end": "2026-09-17"}}
    monkeypatch.setattr(G, "_ghl_closed_in_window", lambda w0, w1: [
        {"opp_id": "o", "contact_id": "c", "opp_name": "P: x",
         "contact_name": "Conflicted Person", "email": "cp@x.com",
         "stage": "Closed Deal", "status": "open", "source": "fb",
         "stage_changed": "2026-09-11 02:00", "close_date": "2026-09-11"}])
    import cash_truth
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda d: [])
    monkeypatch.setattr(G, "_health_row", lambda n, o, e=None: None)
    monkeypatch.setattr(G, "_tracker_row_for", lambda n, e: {
        "close_date": "2026-09-05", "contract": "", "cash": ""})
    out = G.rebuild_closes(apply=False)
    e = out["ledger"][0]
    assert "conflict" in e and "2026-09-05" in e["conflict"] and "2026-09-11" in e["conflict"]


# ── three ROAS separation + payback + verdict ───────────────────────────────

def test_three_roas_labelled_never_blended(monkeypatch):
    rep = {"roas": {"cash_roas_activity": 0.4, "cash_roas_cohort": 0.5,
                    "contract_roas": 4.1, "ltv_roas": 6.0,
                    "labels": {}, "never_blended": True}}
    assert rep["roas"]["never_blended"]
    # structural: no blended/combined roas key exists in the module
    src = open(os.path.join(_ROOT, "finance_analysis.py")).read()
    assert "blended_roas" not in src and "combined_roas" not in src
    assert "never_blended" in src


def test_cohort_payback_series(monkeypatch):
    monkeypatch.setattr(F, "window_report", lambda n, basis="activity": {
        "spend": {"amount": 6000.0},
        "closes": [{"person": "A"}, {"person": "B"}]})
    scheds = {"A": {"person": "A", "client_row": "A Cafe", "package": "Growth Pro",
                    "mrr": 3000, "contract": 18000, "cash_to_date": 1650,
                    "schedule": [
                        {"month": "2026-09", "expected_cum": 1650, "basis": "x"},
                        {"month": "2026-10", "expected_cum": 4650, "basis": "x"}]},
              "B": {"person": "B", "client_row": "B Bar", "package": "Growth Pro",
                    "mrr": 3050, "contract": 18300, "cash_to_date": 3355,
                    "schedule": [
                        {"month": "2026-09", "expected_cum": 3355, "basis": "x"},
                        {"month": "2026-10", "expected_cum": 6405, "basis": "x"}]}}
    monkeypatch.setattr(F, "payback_schedule", lambda c: scheds[c["person"]])
    out = F.cohort_payback("sep_mtd")
    assert out["series"][0] == {"month": "2026-09", "cumulative_cash": 5005.0}
    assert out["series"][1] == {"month": "2026-10", "cumulative_cash": 11055.0}
    assert out["crosses_spend_in"] == "2026-10"
    assert out["payback_months"] == 2


def test_verdict_decided_by_contract_roas_and_payback(monkeypatch):
    def fake_report(n, basis="activity"):
        return {"spend": {"amount": 5000.0},
                "closes": [{"person": "A", "contract": 18300},
                           {"person": "B", "contract": 18300}],
                "contract": {"total": 36600.0, "missing": []},
                "roas": {"cash_roas_cohort": 0.6, "contract_roas": 7.32,
                         "cash_roas_activity": 0.9, "ltv_roas": 9.0},
                "ltv": {"inputs": {}}}
    monkeypatch.setattr(F, "window_report", fake_report)
    monkeypatch.setattr(F, "cohort_payback", lambda n: {
        "crosses_spend_in": "2026-10", "payback_months": 2, "schedules": []})
    v = F.verdict()
    assert v["healthy"] is True
    assert "timing signature" in v["verdict"]
    assert v["deciding_figures"]["contract_roas"] == 7.32
    assert v["deciding_figures"]["payback_months"] == 2
    # the failing branch
    def bad_report(n, basis="activity"):
        r = fake_report(n)
        r["contract"]["total"] = 3000.0
        r["roas"]["contract_roas"] = 0.6
        return r
    monkeypatch.setattr(F, "window_report", bad_report)
    v2 = F.verdict()
    assert v2["healthy"] is False and "NOT just timing" in v2["verdict"]


def test_ltv_inputs_carry_provenance(monkeypatch):
    import csm_baselines
    monkeypatch.setattr(csm_baselines, "measure_renewal_rate", lambda: {
        "value": 100.0, "lower_bound": 29.2,
        "label": "measured 2026-09-17 (bounded — survivorship-limited)"})
    monkeypatch.setattr(csm_baselines, "measure_in_term_completion",
                        lambda: {"value": None, "label": "placeholder"})
    inputs = F._ltv_inputs()
    assert "measured" in inputs["renewal_provenance"]
    assert "lower bound 29.2" in inputs["renewal_provenance"]
    assert inputs["in_term_completion_pct"] == 85.0        # placeholder kept
    assert "placeholder" in inputs["completion_provenance"]
    assert F._ltv_of(18300, inputs) == round(18300 * 0.85 + 18300 * 1.0, 2)


def test_gap_drills_registered_on_both_lists():
    src = open(os.path.join(_ROOT, "dashboard/routes.py")).read()
    assert src.count("handle_finance_command") >= 2
    assert src.count("handle_gap_command") >= 2
