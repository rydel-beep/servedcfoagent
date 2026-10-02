"""tests/test_truth_engine.py — THE SALES TRUTH ENGINE (#171), Phases 1–5.

Phase 1: an incomplete close appears in the queue naming its gaps; the form
fills it, journals it, recomputes immediately, emits the Piolo line; a
personal-account payment is never business cash; match cards confirm/reject
and re-trigger measurement. Phase 2: coverage + sensitivity; amber below the
threshold; prepaid deals take no haircut. Phase 3: a seeded GHL closed-won
with no register close raises a named finding; a seeded amount mismatch shows
both values; reminders name Kalin / Piolo. Phase 4: the recompute is logged
with its lag; change-ledger sides sum to the change. Phase 5: the statement's
identity check passes on real rows; a forced mismatch blanks the tile.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import close_register as CR
import kv_store

TODAY = dt.date.today()


def _stub_sources(monkeypatch, tracker=(), ghl=(), recorder=(), payments=()):
    import close_detect as CD
    monkeypatch.setattr(CD, "_from_tracker", lambda: list(tracker))
    monkeypatch.setattr(CD, "_from_ghl", lambda: list(ghl))
    monkeypatch.setattr(CD, "_from_stage_recorder", lambda: list(recorder))
    monkeypatch.setattr(CD, "_from_payments", lambda: list(payments))


def _stub_enrichment(monkeypatch, leads=None, ledger=None, charges=None, forms=None):
    monkeypatch.setattr(CR, "_tracker_leads", lambda: leads or {})
    monkeypatch.setattr(CR, "_gap_ledger", lambda: ledger or {})
    monkeypatch.setattr(CR, "_matched_charges", lambda: charges or {})
    monkeypatch.setattr(CR, "_attribution_index", lambda: ({}, None))
    monkeypatch.setattr(CR, "_form_entries", lambda: forms or {})
    kv_store.put(CR.K_DECLARED, [])
    kv_store.put(CR.K_TERMS, {})
    kv_store.put(CR.K_JOURNAL, [])
    # keep the invalidation path local: no engine rebuilds in a unit test
    import close_detect as CD
    monkeypatch.setattr(CD, "invalidate_now", lambda reason: (CR.build() and {"reason": reason}))


def _g(person, close, opp="opp-1", contact="ct-1"):
    return {"person": person, "close_date": close, "source": "ghl stage",
            "provenance": "GHL opportunity in stage 'Closed Deal'",
            "evidence": {"opp_id": opp, "contact_id": contact}, "email": None,
            "owner_id": "owner-9"}


def _t(person, close):
    return {"person": person, "close_date": close, "source": "tracker",
            "provenance": "tracker close row", "evidence": {}, "email": None}


# ═══ PHASE 1 · the complete close ══════════════════════════════════════════

def test_an_incomplete_close_is_in_the_queue_naming_its_gaps(monkeypatch):
    _stub_sources(monkeypatch, ghl=[_g("Max Rocky", "2026-09-29")],
                  tracker=[_t("Full Deal", "2026-09-10")])
    _stub_enrichment(monkeypatch, leads={
        "full deal": {"name": "Full Deal", "business": "Full Deal Cafe", "close_date": "2026-09-10",
                     "contract": 18300.0, "offer": "Growth Pro", "closer": "kalin", "setter": "maran",
                     "input_date": "2026-08-01", "name_norm": "full deal"}})
    CR.build()
    q = CR.missing_details_queue()
    by = {r["person"]: r for r in q["rows"]}
    assert "Max Rocky" in by
    g = by["Max Rocky"]["gaps"]
    for want in ("client or venue name", "package", "contract value ex-GST", "payment schedule",
                 "a matched payment (Stripe or Xero bank feed)", "closer", "setter",
                 "closed-deal form", "tracker close row"):
        assert want in g, want
    assert "CRM Closed Won stage" not in g           # it has the GHL stage
    assert any("Kalin" in o for o in by["Max Rocky"]["owners"])
    # the tracker-complete deal still lacks a schedule, a payment and the form
    assert "Full Deal" in by
    assert "contract value ex-GST" not in by["Full Deal"]["gaps"]
    assert "package" not in by["Full Deal"]["gaps"]
    # oldest first
    assert [r["close_date"] for r in q["rows"]] == sorted(r["close_date"] for r in q["rows"])


def test_the_form_fills_journals_recomputes_and_emits_the_piolo_line(monkeypatch):
    _stub_sources(monkeypatch, ghl=[_g("Max Rocky", "2026-09-29")])
    _stub_enrichment(monkeypatch)
    CR.build()
    res = CR.fill_in("Max Rocky", {
        "client": "Rocky's Italian", "package": "Scale Engine", "term_months": 6,
        "contract_ex_gst": "14,500", "closer": "kalin", "setter": "maran",
        "payment_type": "split", "notes": "3-part split",
        "schedule": [
            {"amount": 5500, "gst": "inc", "due": "2026-09-29", "received": "2026-09-29",
             "account": "business", "evidence_id": ""},
            {"amount": 5225, "gst": "inc", "due": "2026-10-29"},
            {"amount": 5225, "gst": "inc", "due": "2026-11-29"}]}, actor="piolo")
    assert res["ok"], res
    e = res["entry"]
    assert e["contract"]["value"] == 14500.0 and e["contract"]["signed"] is True
    assert e["package"] == "scale_engine" and e["term_months"] == 6
    assert e["closer"] == "kalin" and e["setter"] == "maran"
    assert e["client"] == "Rocky's Italian"
    # recomputed immediately: the register already carries the ruling
    assert CR.record("max rocky")["ruling"]["by"] == "piolo"
    left = res["gaps_left"]
    for gone in ("package", "term (months)", "contract value ex-GST", "payment schedule",
                 "closer", "setter", "client or venue name"):
        assert gone not in left, gone
    # received, business account, NO evidence id → cash pending the bank feed, not cash
    assert e["cash"]["amount"] is None
    assert e["ruled_cash"]["pending_bank_feed"][0]["state"] == "cash pending bank feed"
    # journaled with who/when
    j = CR.journal_entries()
    assert j[-1]["kind"] == "owner_ruling" and j[-1]["actor"] == "piolo"
    assert "Rocky's Italian" in j[-1]["detail"]
    # the Piolo line: what to type at source
    assert res["piolo_line"] and any("Offer = Scale Engine" in x and "14,500.00" in x
                                     for x in res["piolo_line"]["edits"])


def test_a_personal_account_payment_is_never_business_cash_and_raises_a_piolo_item(monkeypatch):
    _stub_sources(monkeypatch, ghl=[_g("Max Rocky", "2026-09-29")])
    _stub_enrichment(monkeypatch)
    CR.build()
    kv_store.put("feed:extra:close_register_fill", [])
    res = CR.fill_in("Max Rocky", {
        "client": "Rocky's Italian", "package": "Scale Engine", "term_months": 6,
        "contract_ex_gst": 14500,
        "schedule": [{"amount": 5500, "gst": "inc", "due": "2026-09-29",
                      "received": "2026-09-29", "account": "personal", "evidence_id": "bank-x"}]},
        actor="rydel")
    assert res["ok"]
    e = res["entry"]
    assert e["cash"]["amount"] is None
    assert "outside business accounts" in e["ruled_cash"]["outside_business_accounts"][0]["state"]
    assert res["personal_account_payments"] == 1
    assert any("PERSONAL account" in x for x in res["piolo_line"]["edits"])
    feed = kv_store.get("feed:extra:close_register_fill")
    assert feed and feed[-1]["kind"] == "personal_account_payment"


def test_a_ruling_is_reversible(monkeypatch):
    _stub_sources(monkeypatch, ghl=[_g("Max Rocky", "2026-09-29")])
    _stub_enrichment(monkeypatch)
    CR.build()
    assert CR.fill_in("Max Rocky", {"client": "R", "package": "Growth Pro", "term_months": 6,
                                    "contract_ex_gst": 9000, "schedule": []}, "rydel")["ok"]
    assert CR.record("max rocky")["contract"]["value"] == 9000.0
    r = CR.revoke_deal_terms("max rocky", "rydel")
    assert r["ok"] and r["entry"]["contract"]["value"] is None
    assert CR.journal_entries()[-1]["kind"] == "owner_ruling_revoked"
    assert not CR.revoke_deal_terms("max rocky", "rydel")["ok"]


def test_the_form_refuses_what_it_must(monkeypatch):
    _stub_sources(monkeypatch, ghl=[_g("Max Rocky", "2026-09-29")])
    _stub_enrichment(monkeypatch)
    CR.build()
    assert "term" in CR.fill_in("Max Rocky", {"package": "Growth Pro", "contract_ex_gst": 1}, "r")["error"]
    assert "contract" in CR.fill_in("Max Rocky", {"package": "Growth Pro", "term_months": 6}, "r")["error"]
    bad = CR.fill_in("Max Rocky", {"package": "Growth Pro", "term_months": 6, "contract_ex_gst": 100,
                                   "schedule": [{"amount": 100, "received": "2026-09-01",
                                                 "account": "wallet"}]}, "r")
    assert "business or personal" in bad["error"]
    # a package the rulebook does not know is refused, never inferred
    assert not CR.fill_in("Max Rocky", {"package": "Mystery", "term_months": 6,
                                        "contract_ex_gst": 100}, "r")["ok"]
    # custom is always allowed, labelled
    ok = CR.fill_in("Max Rocky", {"package": "custom", "package_custom": "photography + ads",
                                  "term_months": 3, "contract_ex_gst": 2000}, "r")
    assert ok["ok"] and ok["entry"]["package"] == "custom"
    assert "photography" in ok["entry"]["package_words"]


def test_a_new_close_recorded_nowhere_is_labelled_awaiting_evidence(monkeypatch):
    _stub_sources(monkeypatch)
    _stub_enrichment(monkeypatch)
    CR.build()
    res = CR.fill_in("Brand New", {"client": "New Venue", "close_date": "2026-10-01",
                                   "package": "Growth Pro", "term_months": 6,
                                   "contract_ex_gst": 12000, "schedule": []}, "rydel")
    assert res["ok"]
    e = CR.record("brand new")
    assert e["label"] == "owner-recorded — awaiting GHL/Xero evidence"
    assert e["dated_by"] == "owner ruling"
    assert "CRM Closed Won stage" in e["gaps"]


def test_the_rate_card_offers_custom_and_never_infers():
    rc = CR.rate_card()
    labels = [p["label"] for p in rc]
    assert "Custom package" in labels and "Growth Pro" in labels
    assert next(p for p in rc if p["key"] == "growth_pro")["term_months"] == 6


# ═══ PHASE 1.4 · match cards ═══════════════════════════════════════════════

def test_match_cards_seed_from_the_proposals_and_the_three_rulings_are_decided():
    import match_proposals as MP
    kv_store.delete(MP.K_STATE)
    c = MP.cards(include_decided=True)
    assert c["pending_count"] == 22 + 12 - 3
    decided = {d["id"]: d for d in c["decided"]}
    assert decided["stripe:norvinacabo"]["client"] == "Asian Streat"
    assert decided["xero:kinfunkengwong"]["client"] == "Noodle Asia"
    assert decided["xero:warnersatthebay"]["decision"] == "confirm"
    whos = {p["who"] for p in c["pending"]}
    assert "Adrian Sheather" in whos and "Lost Sheep Cafe" in whos
    assert abs(c["pending_stripe_total"] - (226928.20 - 30800.00)) < 0.01


def test_confirm_writes_the_alias_journals_and_asks_for_a_remeasure(monkeypatch):
    import match_proposals as MP
    import unmatched_payments as UP
    import unit_econ_engine as UE
    kv_store.delete(MP.K_STATE); kv_store.put(MP.K_JOURNAL, []); kv_store.delete(UE.K_REMEASURE_DUE)
    calls = []
    monkeypatch.setattr(UP, "confirm", lambda payer, client, actor="x", charge_id=None:
                        calls.append((payer, client, actor)) or {"ok": True})
    res = MP.decide("stripe:adriansheather", "confirm", "rydel")
    assert res["ok"] and calls == [("Adrian Sheather", "Rising Sun Workshop", "rydel")]
    assert kv_store.get(UE.K_REMEASURE_DUE)["reason"].startswith("match confirmed")
    assert MP.journal()[-1]["decision"] == "confirm"
    assert not MP.decide("stripe:adriansheather", "confirm", "rydel")["ok"]   # already decided
    # a proposal with no name needs one
    assert "name the client" in MP.decide("stripe:prashantsharma", "confirm", "rydel")["error"]


def test_someone_else_and_reject_are_journaled_and_xero_contacts_map(monkeypatch):
    import match_proposals as MP
    import client_receipts as CRx
    kv_store.delete(MP.K_STATE); kv_store.put(MP.K_JOURNAL, [])
    kv_store.put(CRx.K_MAP, {}); kv_store.put(CRx.K_JOURNAL, [])
    r = MP.decide("xero:stephwicks", "someone_else", "piolo", client="Wicks Bakery")
    assert r["ok"] and CRx.client_for("Steph Wicks")["client"] == "Wicks Bakery"
    r2 = MP.decide("stripe:xuanhieonguyen", "reject", "rydel", words="not a client payment")
    assert r2["ok"] and MP.state()["items"]["stripe:xuanhieonguyen"]["decision"] == "reject"
    assert MP.cards()["pending_count"] == 31 - 2


def test_confirm_can_record_package_start_and_contract_in_the_same_step(monkeypatch):
    import match_proposals as MP
    import client_receipts as CRx
    _stub_sources(monkeypatch)
    _stub_enrichment(monkeypatch)
    CR.build()
    kv_store.delete(MP.K_STATE); kv_store.put(CRx.K_MAP, {})
    r = MP.decide("xero:lostsheepcafe", "confirm", "rydel",
                  terms={"package": "Scale Engine", "contract_ex_gst": "14500", "start_date": "2026-07-01"})
    assert r["ok"] and r["terms"]["ok"]
    e = CR.record("lost sheep cafe")
    assert e["contract"]["value"] == 14500.0 and e["term_months"] == 6


def test_the_requested_remeasure_runs_on_the_tick(monkeypatch):
    import unit_econ_engine as UE
    ran = []
    monkeypatch.setattr(UE, "remeasure", lambda: ran.append(1) or {})
    kv_store.delete(UE.K_MEASURED)
    kv_store.delete(UE.K_REMEASURE_DUE)
    assert UE.due_tick() is False
    UE.request_remeasure("test")
    assert UE.due_tick() is True and ran == [1]
    assert kv_store.get(UE.K_REMEASURE_DUE) is None


# ═══ PHASE 2 · coverage, sensitivity, amber ════════════════════════════════

INP = {"measured": True, "renewal_pct": 22.2, "renewal_ci95": [9.0, 45.2],
       "renewal_n": 18, "completion_pct": 72.7, "completion_n": 18,
       "horizon_months": 36, "measured_on": "2026-09-29", "note": None}


def _e(person, cv, offer=None, gaps=None):
    return {"person": person, "offer": offer, "client": person + " Co",
            "contract": {"value": cv, "source": "tracker contract cell"},
            "gaps": gaps if gaps is not None else (["payment schedule"] if cv else ["contract value ex-GST"])}


def test_the_coverage_line_counts_and_flags(monkeypatch):
    import unit_econ_engine as UE
    import sales_cost
    entries = [_e("A", 18300.0, "Growth Pro", gaps=[]), _e("B", 4799.0, "Walk in Engine", gaps=[]),
               _e("C", None), _e("D", None), _e("E", None)]
    monkeypatch.setattr(CR, "closes", lambda w0, w1, clock="activity": entries)
    monkeypatch.setattr(sales_cost, "build", lambda w0, w1: {
        "true_cac": {"total": 20000.0, "ad_spend": 12000.0, "components": []},
        "commissions": {"pending_deals": 0, "pending_range": None}})
    w = UE.window("2026-07-05", "2026-10-02", "trailing_90d", inp=INP, margin=(65.0, "t"))
    cov = w["coverage"]
    assert cov["with_contract"] == 2 and cov["closes"] == 5 and cov["missing_details"] == 3
    assert cov["line"] == "based on 2 of 5 closes — 3 missing details"
    assert cov["pct"] == 40.0 and cov["ok"] is False
    assert w["sensitivity"]["ltv_cac_low"] < w["ltv_cac_expected"] < w["sensitivity"]["ltv_cac_high"]


def test_the_tile_goes_amber_below_the_threshold_and_says_so(monkeypatch):
    from dashboard import exec_top
    kv_store.put(exec_top.K_UNIT, {"computed_at": "2026-10-02T09:00:00+10:00", "error": None, "data": {
        "engine": {"inputs": {**INP}, "identity_check": {"ok": True},
                   "headline": {"window": {"start": "2026-07-05", "end": "2026-10-02"},
                                "ltv_cac_expected": 3.5, "ltv_cac_floor": 3.8, "ltgp_cac_expected": 2.3,
                                "ltgp_cac_floor": 2.5, "ltv_pending": ["C"], "closes": 5,
                                "coverage": {"line": "based on 2 of 5 closes — 3 missing details",
                                             "ok": False, "pct": 40.0}},
                   "mtd": {}}}})
    monkeypatch.setattr(exec_top, "_age_h", lambda iso: 0.1)
    import close_register as _CR
    monkeypatch.setattr(_CR, "proposed_note", lambda *a, **k: None)
    tiles = {t["id"]: t for t in exec_top.build_tiles({})}
    t = tiles["ltv_cac"]
    assert t["state"] == "amber"
    assert "based on 2 of 5 closes — 3 missing details" in t["sub"]
    assert "incomplete — fill the queue" in t["sub"]
    assert t["value"] == "3.50×"


def test_prepaid_deals_take_no_completion_haircut():
    import unit_econ_engine as UE
    r = UE.ltv_for({"person": "Scott Cho", "offer": "Walk-In Engine", "term_months": 3,
                    "contract": {"value": 4799.0}, "cash": {"amount": 5278.90}}, INP)
    assert r["expected"] == 4799.0


def test_walkin_conversion_is_measured_separately_and_credited_nowhere():
    import unit_econ_engine as UE
    today = dt.date(2026, 10, 2)
    deals = {f"W{i}": {"offer": "Walk in Engine", "close_date": dt.date(2026, 1, 10)} for i in range(6)}
    by = {f"W{i}": [(dt.date(2026, 1, 10), 5278.9)] for i in range(6)}
    by["W0"] += [(dt.date(2026, 5, 1), 2000.0), (dt.date(2026, 6, 1), 2000.0), (dt.date(2026, 7, 1), 2000.0)]
    m = UE.walkin_conversion(by, deals, today)
    assert m["n"] == 6 and m["converted"] == 1 and m["credited"] is False
    assert m["value"] == round(100 / 6, 1)
    small = UE.walkin_conversion({k: v for k, v in list(by.items())[:3]},
                                 {k: v for k, v in list(deals.items())[:3]}, today)
    assert small["value"] is None and "too few" in small["note"]


# ═══ PHASE 3 · the four-source cross-check ═════════════════════════════════

def test_a_seeded_ghl_close_the_register_lacks_is_a_named_loud_finding(monkeypatch):
    _stub_sources(monkeypatch, tracker=[_t("Signed Deal", "2026-09-10")])
    _stub_enrichment(monkeypatch)
    CR.build()
    import close_detect as CD
    monkeypatch.setattr(CD, "_from_ghl", lambda: [_g("Ghost Close", "2026-09-28")])
    monkeypatch.setattr(CD, "_from_payments", lambda: [])
    rec = CR.reconcile()
    f = [x for x in rec["findings"] if x["kind"] == "known_to_source_missing_from_register"]
    assert f and f[0]["person"] == "Ghost Close" and f[0]["severity"] == "S1"
    assert "GHL closed stage" in f[0]["detail"] and rec["ok"] is False
    assert any(s["source"] == "GHL closed stage" for s in rec["sources_checked"])


def test_a_seeded_amount_mismatch_shows_both_values(monkeypatch):
    _stub_sources(monkeypatch, tracker=[_t("Signed Deal", "2026-09-10")])
    _stub_enrichment(monkeypatch, leads={"signed deal": {
        "name": "Signed Deal", "business": "Signed Cafe", "close_date": "2026-09-10",
        "contract": 10000.0, "cash": "9000", "offer": "Growth Pro", "name_norm": "signed deal"}},
        charges={"signed cafe": [{"charge_id": "ch_1", "amount": 5500.0, "client": "Signed Cafe"}]})
    CR.build()
    e = CR.record("signed deal")
    assert e["cash"]["amount"] == 5500.0 and e["cash"]["tracker_cell"] == "9000"
    # and a ruling that disagrees with the tracker's contract
    CR.fill_in("Signed Deal", {"package": "Growth Pro", "term_months": 6,
                               "contract_ex_gst": 12000, "schedule": []}, "rydel")
    rec = CR.reconcile()
    kinds = [x["kind"] for x in rec["findings"]]
    assert "amount_disagreement" in kinds
    cash = next(x for x in rec["findings"] if "cash —" in x["detail"])
    assert "$9,000.00" in cash["detail"] and "$5,500.00" in cash["detail"]
    contract = next(x for x in rec["findings"] if "contract —" in x["detail"])
    assert "$12,000.00" in contract["detail"] and "$10,000.00" in contract["detail"]


def test_uncorroborated_after_three_days_and_habit_reminders_name_the_owner(monkeypatch):
    old = str(TODAY - dt.timedelta(days=4))
    _stub_sources(monkeypatch, ghl=[_g("Solo Deal", old)])
    _stub_enrichment(monkeypatch)
    CR.build()
    rec = CR.reconcile()
    unc = [x for x in rec["findings"] if x["kind"] == "uncorroborated_after_n_days"]
    assert unc and unc[0]["person"] == "Solo Deal"
    owners = {(r["owner"], r["detail"].split(": ", 1)[1][:20]) for r in rec["reminders"]}
    assert any(o == "Kalin" and d.startswith("submit the Closed") for o, d in owners)
    assert any(o == "Piolo" and d.startswith("add the tracker") for o, d in owners)
    assert any(o == "Piolo" and d.startswith("raise/confirm the") for o, d in owners)
    # the Xero leg is honest about what it cannot read
    assert any(x["kind"] == "source_limited" and x["source"] == "Xero" for x in rec["findings"])


def test_the_crosscheck_runs_on_every_event_and_the_lag_is_logged(monkeypatch):
    import close_detect as CD
    import freshness
    monkeypatch.setattr(freshness, "_block_builders", lambda: ())
    monkeypatch.setattr(CR, "build", lambda days=3650: {"entries": []})
    monkeypatch.setattr(CR, "reconcile", lambda: {"findings": [{"severity": "S2"}], "ok": True})
    kv_store.put("events:recompute_log", [])
    out = CD.invalidate_now("test payment matched")
    assert out["reconciled"] == {"findings": 1, "ok": True}
    assert out["lag_seconds"] >= 0 and out["lag_budget_seconds"] == 120 and out["within_budget"]
    log = kv_store.get("events:recompute_log")
    assert log[-1]["reason"] == "test payment matched" and log[-1]["within_budget"]


# ═══ PHASE 4 · the change ledger ═══════════════════════════════════════════

def _view(ltv_rows, components, closes, ltv_exp, cac, ratio):
    return {"as_of": "2026-10-02T10:00:00+10:00", "margin": {"pct": 60.0},
            "headline": {"ltv_cac_expected": ratio, "ltgp_cac_expected": round(ratio * 0.6, 2),
                         "ltv_cac_floor": None, "ltgp_cac_floor": None,
                         "ltv_expected": ltv_exp, "ltv_floor": None, "cac_loaded": cac,
                         "acquisition_total": sum(c["amount"] for c in components),
                         "closes": closes, "ltv_known": len([r for r in ltv_rows if r.get("expected") is not None]),
                         "cac_components": components, "rows": ltv_rows,
                         "ltv_pending": [r["person"] for r in ltv_rows if r.get("expected") is None]},
            "mtd": {}}


def test_change_ledger_sides_sum_to_the_change_and_name_the_causes():
    import change_ledger as CL
    kv_store.put(CL.K_HISTORY, [])
    rows0 = [{"person": "Koji", "client": "Koji Ramen", "expected": 20000.0, "floor": 18300.0, "contract_ex_gst": 18300.0},
             {"person": "Max", "client": "Rocky's Italian", "expected": None, "floor": None}]
    comps0 = [{"label": "ad spend", "amount": 9000.0}, {"label": "commissions on closes", "amount": 1000.0}]
    v0 = _view(rows0, comps0, 2, 20000.0, 5000.0, 4.0)
    CL.record({**v0, "as_of": "2026-10-01T08:00:00+10:00"})
    rows1 = [{"person": "Koji", "client": "Koji Ramen", "expected": 20000.0, "floor": 18300.0, "contract_ex_gst": 18300.0},
             {"person": "Max", "client": "Rocky's Italian", "expected": 16000.0, "floor": 14500.0, "contract_ex_gst": 14500.0}]
    comps1 = [{"label": "ad spend", "amount": 10200.0}, {"label": "commissions on closes", "amount": 1800.0}]
    v1 = _view(rows1, comps1, 2, 18000.0, 6000.0, 3.0)
    CL.record(v1)
    d = CL.decompose(CL.state_at_or_before("2026-10-01T09:00:00+10:00"), CL._compact(v1), "headline", "ltv_cac")
    assert d["changed"] and d["from"] == 4.0 and d["to"] == 3.0
    assert abs(d["sides"]["sum"] - d["delta"]) <= 0.011
    whats = " ".join(c["what"] for c in d["causes"])
    assert "Rocky's Italian gained a contract value ($14,500 ex-GST)" in whats
    assert "ad spend rose $1,200" in whats and "commissions on closes rose $800" in whats
    assert d["sentence"].startswith("Since your last look: LTV:CAC 4.00× → 3.00× (-1.00×) because")


def test_change_ledger_unchanged_names_what_is_pending():
    import change_ledger as CL
    kv_store.put(CL.K_HISTORY, [])
    rows = [{"person": "Koji", "client": "Koji Ramen", "expected": 20000.0, "floor": 18300.0},
            {"person": "Max", "client": "Rocky's Italian", "expected": None, "floor": None}]
    comps = [{"label": "ad spend", "amount": 9000.0}]
    v = _view(rows, comps, 2, 20000.0, 4500.0, 4.44)
    CL.record({**v, "as_of": "2026-10-01T08:00:00+10:00"})
    CL.record(v)
    d = CL.decompose(CL.state_at_or_before("2026-10-01T09:00:00+10:00"), CL._compact(v), "headline", "ltv_cac")
    assert not d["changed"]
    assert d["sentence"] == "Unchanged at 4.44× because Rocky's Italian has no contract value yet."


def test_the_previous_visit_stamp_is_kept_for_the_ledger(monkeypatch):
    from dashboard import today as T
    import change_ledger as CL
    kv_store.put(T.K_LASTSEEN, {"rydel": "2026-10-01T08:00:00+10:00"})
    monkeypatch.setattr("dashboard.auth.current_actor", lambda: {"user": "rydel"})
    T._since_you_last_looked(True)
    assert CL.previous_visit("rydel") == "2026-10-01T08:00:00+10:00"


# ═══ PHASE 5 · the daily verified statement ════════════════════════════════

def _engine_view_real():
    """A view whose headline rows and cost lines reproduce its ratios exactly."""
    rows = [{"person": "A", "client": "A Co", "floor": 18300.0, "expected": 20000.0},
            {"person": "B", "client": "B Co", "floor": 4799.0, "expected": 4799.0},
            {"person": "C", "client": "C Co", "floor": None, "expected": None}]
    comps = [{"label": "ad spend", "amount": 9000.0}, {"label": "commissions on closes", "amount": 1500.0},
             {"label": "set bounties", "amount": 300.0}, {"label": "manager retainer", "amount": 500.0},
             {"label": "sales tooling", "amount": 700.0}]
    acq = 12000.0
    cac = round(acq / 3, 2)                       # 4000.00
    avg_exp = round((20000 + 4799) / 2, 2)        # 12399.50
    avg_fl = round((18300 + 4799) / 2, 2)         # 11549.50
    m = 60.0
    h = {"window": {"start": "2026-07-05", "end": "2026-10-02"}, "rows": rows, "closes": 3,
         "ltv_known": 2, "cac_components": comps, "acquisition_total": acq, "cac_loaded": cac,
         "cac_spend_only": 3000.0, "ltv_expected": avg_exp, "ltv_floor": avg_fl,
         "ltv_cac_expected": round(avg_exp / cac, 2), "ltv_cac_floor": round(avg_fl / cac, 2),
         "ltgp_cac_expected": round(avg_exp * m / 100 / cac, 2),
         "ltgp_cac_floor": round(avg_fl * m / 100 / cac, 2),
         "ltv_pending": ["C"], "commission_pending": 0,
         "coverage": {"line": "based on 2 of 3 closes — 1 missing details", "ok": False, "pct": 66.7},
         "sensitivity": {"renewal_low": 9.0, "renewal_high": 45.2, "ltv_cac_low": 2.9, "ltv_cac_high": 3.4,
                         "ltgp_cac_low": 1.7, "ltgp_cac_high": 2.0}}
    return {"as_of": "2026-10-02T06:30:00+10:00", "inputs": {**INP}, "margin": {"pct": m, "provenance": "test"},
            "benchmark": {"value": 3.0, "label": "3:1"}, "headline": h,
            "mtd": {"window": {"start": "2026-10-01", "end": "2026-10-02"}, "rows": [], "closes": 0,
                    "cac_components": [], "coverage": {"line": "no closes in this window"}},
            "identity_check": {"ok": None}}


def test_the_statement_reproduces_the_ratios_by_hand_and_passes(monkeypatch):
    import metrics_statement as MS
    from dashboard import exec_top
    monkeypatch.setattr(exec_top, "refresh_cache", lambda: {})
    monkeypatch.setattr(CR, "reconciliation_latest", lambda: {"at": "x", "ok": True, "findings": []})
    monkeypatch.setattr(CR, "missing_details_queue", lambda limit=None: {"rows": [], "total": 1})
    s = MS.generate(view=_engine_view_real())
    assert s["identity"]["ok"], s["identity"]
    rep = s["checks"]["headline"]["reproduction"]
    assert rep["sum_acquisition"] == 12000.0 and rep["k"] == 2 and rep["n"] == 3
    assert rep["ltv_cac"] == 3.1 and rep["ltgp_cac"] == 1.86
    assert kv_store.get(MS.K_IDENTITY)["ok"] is True
    names = [m["name"] for m in s["metrics"]]
    assert "LTV:CAC (trailing 90 days)" in names and "CAC loaded (month to date)" in names
    m = next(x for x in s["metrics"] if x["name"] == "LTV:CAC (trailing 90 days)")
    assert m["coverage"] == "based on 2 of 3 closes — 1 missing details"
    assert m["band"]["ratio"] == [2.9, 3.4] and m["floor"] == 2.89
    assert MS.latest()["date"] == s["date"]
    assert kv_store.get("feed:extra:statement") == []


def test_a_forced_mismatch_fails_the_check_blanks_the_tile_and_raises_a_finding(monkeypatch):
    import metrics_statement as MS
    import unit_econ_engine as UE
    from dashboard import exec_top
    monkeypatch.setattr(exec_top, "refresh_cache", lambda: {})
    monkeypatch.setattr(CR, "reconciliation_latest", lambda: {})
    monkeypatch.setattr(CR, "missing_details_queue", lambda limit=None: {"rows": [], "total": 0})
    s = MS.generate(view=_engine_view_real(), force_mismatch=True)
    assert not s["identity"]["ok"] and "headline ltv_cac" in s["identity"]["failed"]
    assert "engine 3.1 vs hand 3.6" in s["identity"]["detail"]
    feed = kv_store.get("feed:extra:statement")
    assert feed and feed[0]["severity"] == "S1"
    # the engine view carries the flag → the tile is withheld
    monkeypatch.setattr(UE, "measured", lambda: {})
    monkeypatch.setattr(UE, "window", lambda *a, **k: {"closes": 0, "rows": [], "label": ""})
    v = UE.view()
    assert v["identity_check"]["ok"] is False
    kv_store.put(exec_top.K_UNIT, {"computed_at": "2026-10-02T09:00:00+10:00", "error": None,
                                   "data": {"engine": {**_engine_view_real(),
                                                       "identity_check": v["identity_check"]}}})
    monkeypatch.setattr(exec_top, "_age_h", lambda iso: 0.1)
    monkeypatch.setattr(CR, "proposed_note", lambda *a, **k: None)
    tiles = {t["id"]: t for t in exec_top.build_tiles({})}
    assert tiles["ltv_cac"]["value"] == "check failed — being investigated"
    assert tiles["ltgp_cac"]["state"] == "degraded" and tiles["ltgp_cac"]["raw"] is None
    # and it clears on the next passing run
    MS.generate(view=_engine_view_real())
    assert kv_store.get(MS.K_IDENTITY)["ok"] is True


def test_edith_answers_sales_vs_acquisition_cost_from_the_statement(monkeypatch):
    import metrics_statement as MS
    from dashboard import exec_top
    monkeypatch.setattr(exec_top, "refresh_cache", lambda: {})
    monkeypatch.setattr(CR, "reconciliation_latest", lambda: {"at": "x", "ok": False,
                                                                "findings": [{"severity": "S2"}]})
    monkeypatch.setattr(CR, "missing_details_queue", lambda limit=None: {"rows": [], "total": 4})
    MS.generate(view=_engine_view_real())
    reply, ok = MS.handle_statement_command("how are we doing on sales vs acquisition cost?")
    assert ok
    first = reply.split(". ")[0]
    assert "1.86 dollars of gross profit for every dollar" in first and "LTV:CAC 3.10×" in first
    assert "above the 3:1 benchmark" in first and "verified by hand" in first
    assert "On signed contracts alone it is 2.89×." in reply
    assert "based on 2 of 3 closes" in reply and "4 close(s) are still missing details" in reply
    assert "1 open finding" in reply
    assert MS.handle_statement_command("what's the weather")[1] is False


def test_the_statement_runs_once_each_morning(monkeypatch):
    import metrics_statement as MS
    from helpers import today_sydney
    ran = []
    monkeypatch.setattr(MS, "generate", lambda: ran.append(1) or {})
    kv_store.delete(MS.K_DAY + str(today_sydney()))
    kv_store.delete(f"statement:lock:{today_sydney()}")
    import helpers
    monkeypatch.setattr(MS, "now_sydney", lambda: helpers.now_sydney().replace(hour=7))
    assert MS.daily_tick() is True
    kv_store.put(MS.K_DAY + str(today_sydney()), {"x": 1})
    assert MS.daily_tick() is False and ran == [1]


# ═══ the registry + the pages ═══════════════════════════════════════════════

def test_new_surfaces_are_registered_in_plain_words():
    from dashboard import definitions as D
    for k in ("deals_missing_details", "fill_in_form", "match_proposals_pending",
              "verified_statement", "coverage_line", "change_ledger",
              "system_crosscheck", "system_events", "gate_account"):
        e = D.entry(k)
        assert e and e.get("meaning"), k
        for f in ("meaning", "computed", "changing", "default_from", "good"):
            assert not D.jargon_hits(e.get(f) or ""), (k, f)


@pytest.fixture()
def app_client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-171")
    import app as appmod
    return appmod.app


def _as(app, role, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": user, "role": role, "display": user}
    return c


def test_the_queue_count_is_one_number_on_today_sales_and_closes(app_client):
    import re
    c = _as(app_client, "owner", "rydel")
    vals = set()
    for path in ("/dashboard/today", "/dashboard/sales", "/dashboard/closes"):
        html = c.get(path).get_data(as_text=True)
        m = re.search(r'data-metric="deals_missing_details"[^>]*data-value="(\d+)"', html)
        assert m, path
        vals.add(m.group(1))
        assert 'id="missing-details"' in html
    assert len(vals) == 1
    # finance sees the form too; the gate sees the panel and cannot submit
    assert "mdq-fill" in _as(app_client, "coo", "piolo").get("/dashboard/today").get_data(as_text=True)
    r = _as(app_client, "gate", "gate").post("/dashboard/api/register/fill", json={})
    assert (r.get_json() or {}).get("refused") == "gate"
