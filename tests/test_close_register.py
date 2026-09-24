"""
tests/test_close_register.py
----------------------------
THE ONE CLOSE POPULATION (#164). Detection is evidence-first, cash is
matched Stripe only, contract rides the evidence ladder chipped signed vs
derived, every record carries BOTH clock placements, a close with no
evidence cannot exist, and the reconciliation names what a source knows
that the register lacks. All sources are stubbed — no network, no sheets.
"""
from __future__ import annotations
import sys, os, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import close_register as CR
import kv_store


def _stub_sources(monkeypatch, tracker=(), ghl=(), recorder=(), payments=()):
    import close_detect as CD
    monkeypatch.setattr(CD, "_from_tracker", lambda: list(tracker))
    monkeypatch.setattr(CD, "_from_ghl", lambda: list(ghl))
    monkeypatch.setattr(CD, "_from_stage_recorder", lambda: list(recorder))
    monkeypatch.setattr(CD, "_from_payments", lambda: list(payments))


def _stub_enrichment(monkeypatch, leads=None, ledger=None, charges=None,
                     att=None, forms=None):
    monkeypatch.setattr(CR, "_tracker_leads", lambda: leads or {})
    monkeypatch.setattr(CR, "_gap_ledger", lambda: ledger or {})
    monkeypatch.setattr(CR, "_matched_charges", lambda: charges or {})
    monkeypatch.setattr(CR, "_attribution_index", lambda: (att or {}, None))
    monkeypatch.setattr(CR, "_form_entries", lambda: forms or {})
    kv_store.put(CR.K_DECLARED, [])


def _t(person, close, **kw):
    return {"person": person, "close_date": close, "source": "tracker",
            "provenance": "tracker close row", "evidence": kw.get("evidence", {}),
            "email": None}


def _g(person, close, opp="opp-1", contact="ct-1"):
    return {"person": person, "close_date": close, "source": "ghl stage",
            "provenance": "GHL opportunity in stage 'Closed Deal'",
            "evidence": {"opp_id": opp, "contact_id": contact},
            "email": None, "owner_id": "owner-9"}


TODAY = str(dt.date.today())


def test_one_source_is_proposed_two_are_confirmed(monkeypatch):
    _stub_sources(monkeypatch,
                  ghl=[_g("Solo Deal", "2026-09-16")],
                  tracker=[_t("Signed Deal", "2026-09-10")])
    _stub_enrichment(monkeypatch)
    out = CR.build()
    by = {e["person"]: e for e in out["entries"]}
    assert by["Solo Deal"]["status"] == "proposed-needs-evidence"
    assert by["Signed Deal"]["status"] == "confirmed"      # tracker = authority
    assert out["proposed"] == 1 and out["confirmed"] == 1


def test_ledger_charge_evidence_confirms_a_ghl_only_close(monkeypatch):
    """Orlando's shape: the fast detector saw one source while his charges
    sat in the gap ledger — the register merges the evidence and confirms."""
    _stub_sources(monkeypatch, ghl=[_g("Orlando Rinaldi", "2026-09-09")])
    _stub_enrichment(monkeypatch, ledger={
        "orlando rinaldi": {"person": "Orlando Rinaldi",
                            "evidence": {"charge_ids": ["ch_1"], "opp_id": "opp-1"},
                            "stripe": {"cash_to_date": 1650.0},
                            "contract_value": 18000.0,
                            "contract_provenance": "Health-tab contract value",
                            "health_row": {"name": "Food Corp"}}})
    out = CR.build()
    e = out["entries"][0]
    assert e["status"] == "confirmed"
    assert e["cash"]["amount"] == 1650.0
    assert "ch_1" in e["cash"]["charge_ids"]
    assert e["client"] == "Food Corp"


def test_cash_is_matched_stripe_never_the_tracker_cell(monkeypatch):
    _stub_sources(monkeypatch, tracker=[_t("Jane Doe", "2026-09-05")])
    _stub_enrichment(
        monkeypatch,
        leads={"jane doe": {"name": "Jane Doe", "name_norm": "jane doe",
                            "business": "JD Cafe", "cash": 9999.0,
                            "contract": 12000.0, "input_date": dt.date(2026, 8, 1),
                            "closer": "Kalin", "setter": "Coby",
                            "closer_commission": None, "setter_commission": None,
                            "offer": "Growth Pro", "lead_source": "meta",
                            "email": None, "contact_id": None}},
        charges={"jd cafe": [{"charge_id": "ch_9", "amount": 3000.0,
                              "client": "JD Cafe", "payer": "J Doe",
                              "date": "2026-09-06"}]})
    e = CR.build()["entries"][0]
    assert e["cash"]["amount"] == 3000.0            # matched charges, not 9999
    assert e["cash"]["tracker_cell"] == 9999.0      # the cell rides beside
    assert e["cash"]["charge_ids"] == ["ch_9"]
    assert e["contract"] == {"value": 12000.0, "source": "tracker contract cell",
                             "signed": True}
    assert e["closer"] == "Kalin" and e["setter"] == "Coby"


def test_clock_placements_and_cohort_unplaceable(monkeypatch):
    _stub_sources(monkeypatch,
                  tracker=[_t("Has Lead", "2026-09-10")],
                  ghl=[_g("No Lead", "2026-09-11", opp="opp-2", contact="ct-2")])
    _stub_enrichment(
        monkeypatch,
        leads={"has lead": {"name": "Has Lead", "name_norm": "has lead",
                            "business": "HL", "cash": None, "contract": None,
                            "input_date": dt.date(2026, 8, 20), "closer": None,
                            "setter": None, "closer_commission": None,
                            "setter_commission": None, "offer": None,
                            "lead_source": None, "email": None}},
        ledger={"no lead": {"person": "No Lead",
                            "evidence": {"charge_ids": ["ch_2"]},
                            "stripe": {"cash_to_date": 500.0}}})
    CR.build()
    act = CR.closes("2026-09-01", "2026-09-30", "activity")
    assert {e["person"] for e in act} == {"Has Lead", "No Lead"}
    coh = CR.closes("2026-08-01", "2026-08-31", "cohort")
    assert {e["person"] for e in coh} == {"Has Lead"}   # placed by lead arrival
    t = CR.totals("2026-09-01", "2026-09-30", "cohort")
    assert t["cohort_unplaceable"] == 1
    assert t["cohort_unplaceable_people"] == ["No Lead"]
    # the WHY is words, not a blank
    no_lead = next(e for e in act if e["person"] == "No Lead")
    assert "no lead" in (no_lead["clocks"]["cohort_why"] or "").lower() or \
           "no tracker lead row" in (no_lead["clocks"]["cohort_why"] or "")


def test_totals_tiers_partition_the_count(monkeypatch):
    _stub_sources(monkeypatch,
                  tracker=[_t("Ad Person", "2026-09-08"),
                           _t("Organic Person", "2026-09-09")])
    _stub_enrichment(
        monkeypatch,
        att={"ad person": {"tier": "ad", "creative_key": "123",
                           "label": "B008_A04", "input_date": "2026-08-15"}})
    CR.build()
    t = CR.totals("2026-09-01", "2026-09-30", "activity")
    assert t["count"] == 2
    assert sum(t["tiers"].values()) == t["count"]       # nothing hidden in a tier
    assert t["tiers"] == {"ad": 1, "unattributed": 1}
    ad = CR.record("ad person")
    assert ad["attribution"]["why"] == "id-exact to B008_A04"


def test_declare_close_rejects_free_text_and_accepts_real_evidence(monkeypatch):
    _stub_sources(monkeypatch)
    _stub_enrichment(monkeypatch)
    kv_store.put(CR.K_JOURNAL, [])
    # free text alone → refused
    r = CR.declare_close("Someone", "2026-09-20", "vibes", "", actor="rydel")
    assert not r["ok"]
    # a named kind with no id → refused
    r = CR.declare_close("Someone", "2026-09-20", "stripe_charge", "", actor="rydel")
    assert not r["ok"] and "evidence" in r["error"]
    # evidence that does not exist in its store → refused
    monkeypatch.setattr(CR, "_verify_evidence",
                        lambda k, i: {"ok": False, "why": "not found"})
    r = CR.declare_close("Someone", "2026-09-20", "stripe_charge", "ch_x")
    assert not r["ok"] and "could not be found" in r["error"]
    # real evidence → recorded, journaled, flows through the register
    monkeypatch.setattr(CR, "_verify_evidence",
                        lambda k, i: {"ok": True, "amount": 750.0,
                                      "evidence": {"charge_ids": [i]}})
    monkeypatch.setattr("close_detect.invalidate_now",
                        lambda reason: (_ for _ in ()).throw(RuntimeError("skip")))
    r = CR.declare_close("Someone New", "2026-09-20", "stripe_charge", "ch_ok",
                         actor="rydel", client="SOME VENUE")
    assert r["ok"]
    e = CR.record("someone new")
    assert e and e["declared"] and e["status"] == "confirmed"
    assert e["cash"]["amount"] == 750.0
    j = CR.journal_entries()
    assert any(x["kind"] == "owner_declaration" and "Someone New" in x["detail"]
               for x in j)


def test_reconciliation_names_the_missing_deal_and_source(monkeypatch):
    """The drill: remove a close from the register → the check fires,
    naming the deal and the source that still sees it."""
    _stub_sources(monkeypatch, ghl=[_g("Vanished Deal", TODAY)])
    _stub_enrichment(monkeypatch)
    CR.build()
    # sabotage: empty the register while the source still holds the close
    kv_store.put(CR.K_REGISTER, {"at": "now", "entries": []})
    rec = CR.reconcile()
    assert rec["ok"] is False
    hit = [f for f in rec["findings"]
           if f["kind"] == "known_to_source_missing_from_register"]
    assert hit and hit[0]["person"] == "Vanished Deal"
    assert "GHL" in hit[0]["source"]


def test_uncorroborated_proposed_close_is_flagged_after_n_days(monkeypatch):
    old = str(dt.date.today() - dt.timedelta(days=10))
    _stub_sources(monkeypatch, ghl=[_g("Stale Proposal", old)])
    _stub_enrichment(monkeypatch)
    CR.build()
    rec = CR.reconcile()
    flags = [f for f in rec["findings"]
             if f["kind"] == "uncorroborated_after_n_days"]
    assert flags and flags[0]["person"] == "Stale Proposal"


def test_piolo_lines_name_the_exact_cells(monkeypatch):
    _stub_sources(monkeypatch, ghl=[_g("Gap Deal", "2026-09-11")])
    _stub_enrichment(monkeypatch, ledger={
        "gap deal": {"person": "Gap Deal",
                     "evidence": {"charge_ids": ["ch_3"]},
                     "stripe": {"cash_to_date": 2000.0}}})
    CR.build()
    lines = CR.piolo_lines()
    row = next(p for p in lines if p["person"] == "Gap Deal")
    assert any("Close Date = 2026-09-11" in e for e in row["edits"])
    assert any("Contract Value" in e for e in row["edits"])


def test_closes_union_reads_the_register(monkeypatch):
    """finance_analysis._closes_union is a thin read of the register —
    travelling/tiles/compass/sales-cash all see the same rows."""
    _stub_sources(monkeypatch, tracker=[_t("Union Row", "2026-09-12")])
    _stub_enrichment(monkeypatch, leads={
        "union row": {"name": "Union Row", "name_norm": "union row",
                      "business": "UNION VENUE", "cash": None,
                      "contract": 7000.0, "input_date": dt.date(2026, 9, 1),
                      "closer": None, "setter": None, "closer_commission": None,
                      "setter_commission": None, "offer": None,
                      "lead_source": None, "email": None}})
    CR.build()
    import finance_analysis as FA
    rows = FA._closes_union("2026-09-01", "2026-09-30", "activity")
    assert len(rows) == 1
    r = rows[0]
    assert r["person"] == "Union Row" and r["contract"] == 7000.0
    assert r["client_row"] == "UNION VENUE"
    assert "register" in r["source"]


def test_a_close_with_no_evidence_cannot_exist(monkeypatch):
    """Every entry must carry at least one source row with provenance."""
    _stub_sources(monkeypatch, ghl=[_g("Evidenced", "2026-09-14")])
    _stub_enrichment(monkeypatch)
    out = CR.build()
    for e in out["entries"]:
        assert e["sources"], f"{e['person']} has no evidence sources"
        assert all(s.get("provenance") for s in e["sources"])
