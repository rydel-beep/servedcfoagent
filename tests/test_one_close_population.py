"""
tests/test_one_close_population.py
----------------------------------
THE SINGLE-CALL-SITE GUARD (#164). Phase 0 found seven surfaces building
their own close lists — /ads said 1, SALES said 1, EDITH said 1, each for a
DIFFERENT reason, while four deals had closed. These tests pin the shape
that ended it: the close population lives in close_register; everything
else reads it. A parallel close set reappearing fails the build by name.
"""
from __future__ import annotations
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(path):
    return open(os.path.join(ROOT, path)).read()


def test_sales_scoreboard_has_no_inline_close_filter():
    src = _src("sales_scoreboard.py")
    assert "close_register" in src
    # the deleted fork: an inline tracker-row won/close_date filter
    assert not re.search(
        r"closes_in\s*=\s*\[l for l in leads_all", src), (
        "sales_scoreboard grew its own close list again — the SALES headline "
        "and the SALES cash figure will fork the moment they disagree")


def test_closes_view_reads_only_the_register():
    src = _src("closes_view.py")
    assert "close_register" in src
    for banned in ("sheet_mirror", "_fetch_tab", "read_by_name"):
        assert banned not in src, f"closes_view reads {banned} — a third tracker parser reborn"


def test_closes_union_is_a_thin_read_of_the_register():
    src = _src("finance_analysis.py")
    body = src.split("def _closes_union")[1].split("\ndef ")[0]
    assert "close_register" in body
    for banned in ("gap_reconcile", "AE.compute", "attribution_engine"):
        assert banned not in body, (
            f"_closes_union consults {banned} directly — the union logic "
            "belongs in close_register.build, not here")


def test_range_unit_economics_reads_the_register():
    src = _src("range_unit_economics.py")
    body = src.split("def _ltc_in_window")[1].split("\ndef ")[0]
    assert "close_register" in body
    assert "_read_ltc_clean" not in body


def test_compass_mix_reads_the_register():
    src = _src("compass_engine.py")
    assert "CR.closes(" in src or "close_register" in src
    assert not re.search(r"if l\.get\(\"won\"\) and l\.get\(\"close_date\"\):\n"
                         r"\s+cd = l\[\"close_date\"\]", src)


def test_only_close_register_merges_the_detection_sources():
    """close_detect's source readers are the ONE implementation; only
    close_detect itself, close_register and the probes may call them."""
    allowed = {"close_register.py", "close_detect.py"}
    hits = []
    for base, _dirs, files in os.walk(ROOT):
        if any(p in base for p in (".venv", "node_modules", ".git", "tests",
                                   "scripts", "docs", "pd-", "scale",
                                   "prompts", "state")):
            continue
        for f in files:
            if not f.endswith(".py") or f in allowed:
                continue
            try:
                s = open(os.path.join(base, f)).read()
            except OSError:
                continue
            if re.search(r"_from_tracker\(|_from_ghl\(|_from_stage_recorder\(", s):
                hits.append(f)
    assert not hits, f"detection sources called outside the register: {hits}"


def test_ads_headline_is_never_a_bare_subset():
    """The /ads closes tile: total + tier breakdown + the clock IN WORDS,
    the cohort figure beside it. A bare 'CLOSES' meaning a subset fails."""
    js = _src(os.path.join("dashboard", "static", "js", "adsapp.js"))
    seg = js.split("function renderHeadline")[1].split("function cohortIsYoung")[0]
    assert "closed in this window (activity clock)" in seg
    assert "cohort clock:" in seg
    assert "counts a close in the window its LEAD arrived" in seg
    assert "proposed close(s) — needs evidence" in seg
    assert "state.board.register" in seg          # the register block feeds it
    assert "closes_count" in seg                   # the scan-2 shared key


def test_shared_scan_keys_are_stamped_on_every_close_surface():
    sales = _src(os.path.join("dashboard", "templates", "sales_board.html"))
    trav = _src(os.path.join("dashboard", "templates", "travelling.html"))
    ledger = _src(os.path.join("dashboard", "templates", "closes.html"))
    for tpl, name in ((sales, "sales_board"), (trav, "travelling"),
                      (ledger, "closes")):
        assert 'data-metric="closes_count"' in tpl, f"{name} lost its closes_count stamp"
        assert 'data-metric="closes_cash"' in tpl, f"{name} lost its closes_cash stamp"


def test_ledger_page_carries_the_contract():
    tpl = _src(os.path.join("dashboard", "templates", "closes.html"))
    # evidence chips, both clock links, the owner dialog, and no free-text path
    for needed in ("GHL {{ '✓' if r.chips.ghl_opp else '✗' }}",
                   "Stripe {{ '✓' if r.chips.stripe else '✗' }}",
                   "tracker {{ '✓' if r.chips.tracker_row else '✗' }}",
                   "clock=activity", "clock=cohort",
                   "matched Stripe charges only (R-CASH)",
                   "/dashboard/api/register/evidence-options",
                   "/dashboard/api/register/declare"):
        assert needed in tpl, f"closes.html lost: {needed}"


def test_register_endpoints_are_role_gated():
    import sys
    sys.path.insert(0, ROOT)
    import role_access as RA
    # piolo may read the ledger and the register
    for path in ("/dashboard/closes", "/dashboard/api/register",
                 "/dashboard/api/register/reconciliation"):
        ok, why = RA.coo_permitted(path, "GET")
        assert ok, f"{path}: {why}"
    # record-a-close and rebuild are owner-only money-truth actions
    for path in ("/dashboard/api/register/declare",
                 "/dashboard/api/register/rebuild"):
        ok, why = RA.coo_permitted(path, "POST")
        assert not ok and "owner" in why.lower()


def test_scorecard_cell_is_labelled_a_reference_not_a_count():
    src = _src("metrics_engine.py")
    assert "NEVER a close" in src and "close_register" in src


import pytest


@pytest.fixture()
def app_client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-164")
    import sys
    sys.path.insert(0, ROOT)
    import app as appmod
    return appmod.app


def _as(app, role, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": user, "role": role, "display": user}
    return c


def test_register_api_scrubs_per_person_pay_for_coo(app_client, monkeypatch):
    """R-PIOLO: register entries carry the tracker's commission cells — the
    coo's read gets them REMOVED whole-key, never zeroed; the owner's read
    keeps them."""
    import close_register as CR
    import kv_store
    entry = {
        "id": "cr:pay test", "key": "pay test", "person": "Pay Test",
        "client": "PAY VENUE", "email": None, "contact_id": None,
        "opp_id": "opp9", "close_date": "2026-09-10", "dated_by": "tracker",
        "sources": [{"source": "tracker", "provenance": "tracker close row",
                     "close_date": "2026-09-10"}],
        "corroboration_pending": [], "status": "confirmed",
        "contract": {"value": 10000.0, "source": "tracker contract cell",
                     "signed": True},
        "cash": {"amount": 1000.0, "charge_ids": ["ch_p"],
                 "source": "matched Stripe charges", "tracker_cell": None},
        "closer": "Kalin", "closer_ghl_owner_id": None, "setter": "Coby",
        "closer_commission_cell": 900.0, "setter_commission_cell": 125.0,
        "offer": "Growth Pro",
        "lead": {"input_date": "2026-08-01", "lead_source": None,
                 "tracker_row": True},
        "attribution": {"tier": "unattributed", "why": "no ad stamp",
                        "creative_key": None, "creative": None},
        "clocks": {"activity": "2026-09-10", "cohort": "2026-08-01",
                   "cohort_why": None},
        "evidence": {"opp_id": "opp9"},
        "chips": {"tracker_row": True, "ghl_opp": True, "stripe": True,
                  "form": False},
        "missing": [],
    }
    kv_store.put(CR.K_REGISTER, {"at": "seeded", "entries": [entry],
                                 "confirmed": 1, "proposed": 0})
    coo = _as(app_client, "coo", "piolo")
    r = coo.get("/dashboard/api/register?window=90d&clock=activity")
    assert r.status_code == 200
    body = r.get_json()
    blob = str(body)
    assert "closer_commission_cell" not in blob
    assert "900.0" not in blob and "125.0" not in blob
    assert body["entries"][0]["person"] == "Pay Test"    # the close itself stays
    owner = _as(app_client, "owner", "rydel")
    ro = owner.get("/dashboard/api/register?window=90d&clock=activity")
    assert ro.get_json()["entries"][0]["closer_commission_cell"] == 900.0


def test_declare_and_evidence_options_refused_for_coo(app_client):
    coo = _as(app_client, "coo", "piolo")
    assert coo.get("/dashboard/api/register/evidence-options").status_code == 403
    assert coo.post("/dashboard/api/register/declare", json={}).status_code == 403
    assert coo.post("/dashboard/api/register/rebuild").status_code == 403
