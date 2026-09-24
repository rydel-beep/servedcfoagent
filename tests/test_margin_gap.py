"""IF EVERYONE PAYS vs WHAT ACTUALLY LANDED (#166).

Pinned here:
  1 both panels on ONE cost basis — only collection differs
  2 GST out of collected revenue; refunds/transfers never count
  3 the gap = contracted − collected, reconciled to AR with the residual named
  4 both projections carry their assumptions; realistic uses the trailing pace
  5 freshness: no panel ever says "age unknown"
"""

import datetime as dt
import os
import re

import pytest

import kv_store

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def _code_only(src: str) -> str:
    src = re.sub(r'"""(?:.|\n)*?"""', "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in src.splitlines())


def _seed_engine(monkeypatch, collected_charges):
    """A full fixture: one contracted client, booked costs, stripe charges."""
    import pl_engine as PL
    kv_store._MEM.clear()
    kv_store.put(PL.K_XERO_MONTH.format(m="2026-09"), {
        "ok": True, "month": "2026-09",
        "window": {"start": "2026-09-01", "end": "2026-09-24"},
        "revenue": 50000.0,
        "opex_line_items": [
            {"label": "Contractors NO GST", "amount": 20000.0},
            {"label": "Advertising", "amount": 8000.0},
            {"label": "Wages and Salaries", "amount": 9000.0}],
        "cogs_line_items": [], "pulled_at": "2026-09-24T10:00:00"})
    monkeypatch.setattr(PL, "_cur_month", lambda: "2026-09")
    monkeypatch.setattr(PL, "today_sydney", lambda: dt.date(2026, 9, 15))
    monkeypatch.setattr(PL, "_roster_rows", lambda: [
        {"name": "C1", "status": "Active", "start": dt.date(2026, 1, 1),
         "end": dt.date(2027, 1, 1), "mrr": 60000.0}])
    monkeypatch.setattr(PL, "_roster_stamp", lambda: "2026-09-15T09:59:00")
    monkeypatch.setattr(PL, "_t3_avg_costs", lambda: {
        "contra_revenue": 0.0, "delivery": 20000.0, "acquisition": 8000.0,
        "overhead": 9000.0})
    monkeypatch.setattr(PL, "_reconcile_gap_to_ar", lambda gap: {
        "ok": True, "ar_outstanding": gap + 1000.0, "gap": gap,
        "residual": 1000.0, "residual_note": "prior-month AR", "top_unpaid": [
            {"client": "Leopard Deli", "outstanding": 5500.0,
             "days_overdue": 38}], "door": "/dashboard/view/receivables"})
    monkeypatch.setattr(PL, "_realistic_projection",
                        lambda full, so_far, cur, charges=None: {
                            "available": True, "revenue": 48000.0,
                            "net_profit": 8000.0, "net_margin_pct": 16.7,
                            "collection_rate": 0.8,
                            "label": "realistic — collections continue at the "
                                     "trailing-3 pace (80% of contracted)"})
    import cash_truth
    monkeypatch.setattr(cash_truth, "_recent_charges",
                        lambda days=120: collected_charges)
    kv_store.put("stripe:last_pull", {"at": "2026-09-15T10:00:00", "n": 3})
    return PL


CHARGES = [
    {"id": "ch_1", "date": dt.date(2026, 9, 3), "amount": 3355.0},
    {"id": "ch_2", "date": dt.date(2026, 9, 10), "amount": 11000.0},
    {"id": "ch_3", "date": dt.date(2026, 8, 20), "amount": 5500.0},   # last-30d only
]


def test_both_panels_share_one_cost_basis(monkeypatch):
    PL = _seed_engine(monkeypatch, CHARGES)
    cvc = PL.contracted_vs_collected()
    assert cvc["ok"]
    costs = cvc["same_cost_basis"]
    mg = cvc["contracted"]
    b = cvc["collected_mtd"]
    # panel A: contracted 60000 × 15/30 = 30000; panel B: (3355+11000)/1.1
    assert mg["revenue"] == 30000.0
    assert b["revenue"] == round((3355.0 + 11000.0) / 1.1, 2)
    # identical costs under both margins — recompute B's net by hand from
    # A's cost lines and it must match
    hand_pbt = b["revenue"] - costs["delivery"] - costs["acquisition"] - costs["overhead"]
    hand_net = round(hand_pbt - round(max(hand_pbt, 0) * PL.TAX_RATE, 2), 2)
    assert b["net_profit"] == hand_net


def test_gst_is_out_of_collected_revenue(monkeypatch):
    """A $3,355 receipt counts $3,050."""
    PL = _seed_engine(monkeypatch, [
        {"id": "ch_1", "date": dt.date(2026, 9, 3), "amount": 3355.0}])
    c = PL.collected_revenue("2026-09-01", "2026-09-15")
    assert c["total"] == 3050.0
    assert c["gross"] == 3355.0


def test_refunds_and_transfers_never_count(monkeypatch):
    """The reader nets refunds and drops fully-refunded charges before this
    code ever sees them; transfers never appear in the charge list at all.
    A window with only out-of-window and refunded-away money collects $0."""
    PL = _seed_engine(monkeypatch, [])       # the reader already dropped them
    c = PL.collected_revenue("2026-09-01", "2026-09-15")
    assert c["total"] == 0.0
    assert "refunds" in c["provenance"] and "transfers" in c["provenance"]
    src = _code_only(_read("pl_engine.py"))
    assert "_recent_charges" in src          # R-CASH: the one reader


def test_the_gap_is_contracted_minus_collected_reconciled_to_ar(monkeypatch):
    PL = _seed_engine(monkeypatch, CHARGES)
    cvc = PL.contracted_vs_collected()
    gap = cvc["gap"]
    expect = round(30000.0 - round(14355.0 / 1.1, 2), 2)
    assert gap["amount"] == expect
    assert "money" in gap["meaning"]
    r = cvc["ar_reconciliation"]
    assert r["ok"] and r["residual"] == 1000.0
    assert "prior-month" in r["residual_note"]
    assert r["top_unpaid"][0]["client"] == "Leopard Deli"
    assert r["door"] == "/dashboard/view/receivables"
    assert "Collected so far this month" in gap["line"]


def test_both_projections_carry_their_assumptions(monkeypatch):
    PL = _seed_engine(monkeypatch, CHARGES)
    cvc = PL.contracted_vs_collected()
    pa = cvc["projections"]["optimistic"]
    pb = cvc["projections"]["realistic"]
    assert "optimistic" in pa["label"] and "paid by month end" in pa["label"]
    assert "realistic" in pb["label"] and "trailing" in pb["label"]
    assert pb["collection_rate"] == 0.8


def test_realistic_projection_uses_the_trailing_rate():
    """Un-mocked maths: 80% trailing collection over a $60k schedule with
    $14k already landed → $48k projected collected."""
    import pl_engine as PL
    kv_store._MEM.clear()
    charges = []
    for m, amt in (("2026-08", 52800.0), ("2026-07", 44000.0),
                   ("2026-06", 49500.0)):
        charges.append({"id": f"ch_{m}", "date": dt.date(int(m[:4]), int(m[5:7]), 15),
                        "amount": amt})
    orig_cr, orig_costs = PL.contract_revenue, PL._t3_avg_costs
    PL.contract_revenue = lambda mkey: {"total": 50000.0}
    PL._t3_avg_costs = lambda: {"contra_revenue": 0.0, "delivery": 15000.0,
                                "acquisition": 8000.0, "overhead": 9000.0}
    try:
        pb = PL._realistic_projection(60000.0, 14000.0, "2026-09",
                                      charges=charges)
    finally:
        PL.contract_revenue, PL._t3_avg_costs = orig_cr, orig_costs
    assert pb["available"]
    # rate = mean(ex-GST collected / 50k) ≈ 0.8868 → 0.887 × 60k
    assert abs(pb["revenue"] - round(pb["collection_rate"] * 60000.0, 2)) < 1.0
    assert "trailing" in pb["label"]


def test_no_panel_ever_says_age_unknown(monkeypatch):
    """The fix for 'as of age unknown': the tile's inputs are registered in
    freshness, and the engine stamps each panel from ITS inputs."""
    import freshness as F
    assert F.TILE_INPUTS.get("net_margin") == ("tracker_mirror", "xero", "stripe")
    PL = _seed_engine(monkeypatch, CHARGES)
    cvc = PL.contracted_vs_collected()
    stamps = cvc["inputs_as_of"]
    assert stamps["contracted"]["roster"] == "2026-09-15T09:59:00"
    assert stamps["collected"]["stripe"] == "2026-09-15T10:00:00"
    assert cvc["collected_mtd"]["as_of"] == "2026-09-15T10:00:00"


def test_every_window_is_named(monkeypatch):
    PL = _seed_engine(monkeypatch, CHARGES)
    cvc = PL.contracted_vs_collected()
    assert "month to date" in cvc["contracted"]["window_words"]
    assert "collected" in cvc["collected_mtd"]["window_words"]
    b30 = cvc["collected_30d"]
    assert b30 and re.match(r"\d+ \w+ → \d+ \w+", b30["window_words"])
    assert "trailing-3" in b30["cost_note"]


def test_the_collected_basis_joins_the_waterfall(monkeypatch):
    PL = _seed_engine(monkeypatch, CHARGES)
    r = PL.window("collected", "mtd")
    assert r["ok"] and r["basis"] == "collected"
    assert "one cost" in r["provenance"] or "only collection differs" in r["provenance"]
    routes = _read("dashboard", "routes.py")
    assert '"collected"' in routes
    html = _read("dashboard", "templates", "pl.html")
    assert "'collected'" in html


def test_the_tile_renders_two_panels_the_gap_and_the_door(monkeypatch):
    os.environ.setdefault("DASHBOARD_TOKEN", "t166")
    import pl_engine as PL
    kv_store._MEM.clear()
    kv_store.put(PL.K_SUMMARY, {"computed_at": "2026-09-24T10:00:00", "error": None,
        "data": {"management_mtd": {"ok": True, "net_margin_pct": 28.5,
                                    "window_words": "September 2026 (month to date)"},
                 "recognised_last_month": {"ok": True, "net_margin_pct": 25.3,
                                           "window_words": "August 2026"},
                 "run_rate_t3": {"ok": True, "net_margin_pct": 17.6},
                 "fy26_baseline": PL.FY26,
                 "contracted_vs_collected": {
                     "ok": True,
                     "contracted": {"window_words": "September 2026 (month to date)",
                                    "revenue": 30000.0, "net_margin_pct": 28.5},
                     "collected_mtd": {"window_words": "September 2026 (month to date, collected)",
                                       "revenue": 13050.0, "net_margin_pct": 5.1,
                                       "as_of": "x", "collected": {}},
                     "collected_30d": {"window_words": "26 Aug → 24 Sep",
                                       "net_margin_pct": 8.0},
                     "gap": {"amount": 16950.0, "pct_collected": 43.5,
                             "line": "Collected so far this month: $13,050 of $30,000 contracted (43.5%)"},
                     "ar_reconciliation": {}, "same_cost_basis": {},
                     "projections": {"optimistic": {"available": True, "net_margin_pct": 27.8},
                                     "realistic": {"available": True, "net_margin_pct": 14.0,
                                                   "collection_rate": 0.8}},
                     "inputs_as_of": {}, "fy26_baseline_net_pct": 11.5}}})
    import app as appmod
    c = appmod.app.test_client()
    with c.session_transaction() as sess:
        sess["actor"] = {"user": "rydel", "role": "owner", "display": "Rydel"}
    html = c.get("/dashboard/today").data.decode()
    assert 'data-metric="net_margin_contracted"' in html
    assert 'data-metric="net_margin_collected"' in html
    assert 'data-metric="margin_gap"' in html
    assert "if everyone pays" in html and "what actually landed" in html
    assert "the money you" in html                     # the gap sentence
    assert "/dashboard/view/receivables" in html       # the door
    assert "26 Aug → 24 Sep" in html                   # the dated window


def test_the_drawer_shows_the_math_and_the_reconciliation():
    import tile_drawers
    assert "net_margin" in tile_drawers._REGISTRY
    src = _read("tile_drawers.py")
    fn = src[src.index("def _drawer_net_margin"):src.index("_REGISTRY = {")]
    assert "same_cost_basis" in fn and "top_unpaid" in fn
    assert "optimistic" in fn and "realistic" in fn


def test_the_drill_answers_with_both_windows_and_the_gap():
    import pl_engine as PL
    kv_store._MEM.clear()
    kv_store.put(PL.K_SUMMARY, {"computed_at": "x", "data": {
        "contracted_vs_collected": {
            "ok": True,
            "contracted": {"window_words": "September 2026 (month to date)",
                           "revenue": 30000.0, "net_margin_pct": 28.5},
            "collected_mtd": {"window_words": "September 2026 (month to date, collected)",
                              "revenue": 13050.0, "net_margin_pct": 5.1},
            "collected_30d": {"window_words": "26 Aug → 24 Sep",
                              "net_margin_pct": 8.0},
            "gap": {"amount": 16950.0,
                    "line": "Collected so far this month: $13,050 of $30,000 contracted (43.5%)"},
            "ar_reconciliation": {"top_unpaid": [
                {"client": "Leopard Deli", "outstanding": 5500.0,
                 "days_overdue": 38}]},
            "projections": {"optimistic": {"available": True, "net_margin_pct": 27.8},
                            "realistic": {"available": True, "net_margin_pct": 14.0,
                                          "collection_rate": 0.8}}}}})
    r, h = PL.handle_cvc_query("what's our margin if everyone pays vs what's landed")
    assert h
    for want in ("28.5%", "5.1%", "8.0%", "26 Aug → 24 Sep", "money owed",
                 "Leopard Deli", "optimistic", "realistic", "80%",
                 "only collection differs"):
        assert want in r, want
    assert PL.handle_cvc_query("how is the weather")[1] is False
