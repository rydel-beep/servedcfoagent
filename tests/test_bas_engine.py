"""tests/test_bas_engine.py — the ONE BAS/PAYG estimation engine: exact BAS
quarters + agent due dates, ledger math + the payment-drop assumption (flagged),
the credits band, the set-aside to the cent, config fidelity (no phantom lines),
the disclaimer on every surface, forecast integration, read-only Xero."""
from __future__ import annotations
import datetime as dt
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bas_engine as BE


def _reset():
    import kv_store
    for k in ("bas:estimate", "bas:config", "bas:history", "bas:daily_tick",
              "bas:calibration"):
        kv_store.put(k, None)
    kv_store.put("bas:config", {})


def _inputs(gst_open=41138.08, gst_now=49956.18, paygw_now=2132.0,
            income_tax=20911.68, revenue=103192.18, bas_bank=100182.62,
            opening_present=True):
    tl = {"2026-08-06": {"GST": gst_now, "PAYG Withholdings Payable": paygw_now,
                         "Income Tax Payable": income_tax}}
    if opening_present:
        tl["2026-06-30"] = {"GST": gst_open, "Income Tax Payable": 20948.68}
    return {"ok": True, "tax_lines": tl,
            "pnl": {"2026-07-01..2026-08-06": {
                "revenue": revenue, "cogs": None,
                "opex_line_items": [
                    {"label": "Advertising", "amount": 10197.36},
                    {"label": "Contractors NO GST", "amount": 17490.04},
                    {"label": "Wages and Salaries", "amount": 8932.00},
                    {"label": "Subscriptions", "amount": 1627.31}],
                "cogs_line_items": []}},
            "bas_account_balance": bas_bank}


TODAY = dt.date(2026, 8, 6)


def test_bas_calendar_exact():
    # BAS quarters, never another convention
    s, e = BE.quarter_bounds(dt.date(2026, 8, 6))
    assert (str(s), str(e)) == ("2026-07-01", "2026-09-30")
    assert BE.quarter_label(s) == "Jul–Sep 2026"
    # agent (extended) due dates, incl. the Oct–Dec year rollover
    assert str(BE.due_date(dt.date(2026, 7, 1), "agent")) == "2026-11-25"
    assert str(BE.due_date(dt.date(2026, 10, 1), "agent")) == "2027-02-28"
    assert str(BE.due_date(dt.date(2026, 1, 1), "agent")) == "2026-05-26"
    assert str(BE.due_date(dt.date(2026, 4, 1), "agent")) == "2026-08-25"
    # standard for comparison
    assert str(BE.due_date(dt.date(2026, 7, 1), "standard")) == "2026-10-28"


def test_compute_ledger_math_and_projection():
    _reset()
    est = BE._compute(_inputs(), TODAY)
    gst = est["gst"]
    assert gst["available"] and gst["qtd_net"] == round(49956.18 - 41138.08, 2)
    # projection = run-rate to 92 days, and it is LABELLED modelled
    assert gst["projected_full_quarter"] == round(gst["qtd_net"] / 37 * 92, 2)
    assert "modelled" in est["current_obligation"]["confidence"]
    # accrued vs projected are DISTINCT fields (never conflated)
    assert est["current_obligation"]["accrued_so_far"] != est["current_obligation"]["amount"]
    # the disclaimer rides the payload
    assert est["disclaimer"] == BE.DISCLAIMER


def test_payment_drop_assumption_is_flagged():
    _reset()
    # the agent pays the prior BAS: the account drops far below opening
    est = BE._compute(_inputs(gst_open=41138.08, gst_now=9000.0), TODAY)
    gst = est["gst"]
    assert gst["payment_adjustment"] == 41138.08
    assert gst["qtd_net"] == round(9000.0 - 41138.08 + 41138.08, 2)  # = 9,000 accrued
    assert "assumption" in gst["payment_adjustment_note"]
    # once paid, the prior obligation line disappears
    assert est["prior_obligation"] is None
    # unpaid case keeps it, dated to the AGENT deadline
    est2 = BE._compute(_inputs(), TODAY)
    assert est2["prior_obligation"]["amount"] == 41138.08
    assert est2["prior_obligation"]["due"] == "2026-08-25"


def test_zero_balance_line_omitted_means_zero_not_unknown():
    _reset()
    inp = _inputs()
    del inp["tax_lines"]["2026-08-06"]["PAYG Withholdings Payable"]
    est = BE._compute(inp, TODAY)
    # the report was present → missing PAYGW line reads 0 via the LEDGER, not the model
    assert est["paygw"]["qtd"] == 0.0 and "ledger" in est["paygw"]["source"]
    # whole report missing → the $541/wk model, LABELLED
    est2 = BE._compute({"ok": True, "tax_lines": {}, "pnl": {},
                        "bas_account_balance": None}, TODAY)
    assert "modelled" in est2["paygw"]["source"]
    assert est2["gst"]["available"] is False


def test_credits_band_rules():
    band = BE.credits_band([
        {"label": "Advertising", "amount": 10000},          # certain 10%
        {"label": "Contractors NO GST", "amount": 20000},   # never
        {"label": "Wages and Salaries", "amount": 9000},    # never
        {"label": "Superannuation", "amount": 1000},        # never
        {"label": "Travel - International", "amount": 1600},# never
        {"label": "Subscriptions", "amount": 1000},         # maybe → high only
    ])
    assert band["low"] == 1000.0 and band["high"] == 1100.0


def test_set_aside_to_the_cent_and_free_cash():
    _reset()
    import kv_store
    est = BE._compute(_inputs(), TODAY)
    sa = est["set_aside"]
    assert sa["spoken_for"] == round(49956.18 + 2132.0 + 20911.68, 2)
    assert sa["covered"] and sa["buffer"] == round(100182.62 - sa["spoken_for"], 2)
    kv_store.put("bas:estimate", est)
    fc = BE.free_cash_view(172000.00)
    assert fc["free"] == round(172000.00 - sa["spoken_for"], 2)
    assert "accountant" in fc["note"]           # the disclaimer rides the split
    assert BE.free_cash_view(None) is None      # unknown cash → no invented split


def test_config_fidelity_no_phantom_lines():
    _reset()
    import kv_store
    # instalments active but amount UNSET → the line exists amount-pending and is
    # EXCLUDED from totals (never invented)
    est = BE._compute(_inputs(), TODAY)
    assert est["instalment"]["active"] and est["instalment"]["amount"] is None
    assert "pending" in est["instalment"]["note"]
    base = est["current_obligation"]["amount"]
    # setting the amount (Rydel, provenance recorded) flows into the obligation
    r, h = BE.handle_set_instalment("set PAYG instalment to $5,250")
    assert h and "5,250" in r
    cfg = kv_store.get("bas:config")
    assert cfg["instalment_amount"] == 5250.0
    assert cfg["instalment_amount_provenance"]["set_by"] == "Rydel"
    est2 = BE._compute(_inputs(), TODAY)
    assert est2["current_obligation"]["amount"] == round(base + 5250.0, 2)
    # instalments OFF → NO instalment involvement at all (adversarial P4)
    BE.set_config("instalments_active", False)
    BE.set_config("instalment_amount", None)
    est3 = BE._compute(_inputs(), TODAY)
    assert est3["instalment"]["active"] is False
    assert est3["current_obligation"]["amount"] == base


def test_scheduled_obligations_and_forecast_week():
    _reset()
    import kv_store
    est = BE._compute(_inputs(), TODAY)
    kv_store.put("bas:estimate", est)
    obs = BE.scheduled_obligations()
    assert [o["kind"] for o in obs] == ["bas_prior", "bas_current"]
    assert obs[0]["due"] == "2026-08-25" and obs[0]["amount"] == 41138.08
    # the 13-week forecast books each obligation in its DUE WEEK
    import forecasting_engine as FE
    snap = {"client_health": {"current_mrr": 50000, "active_count": 10},
            "cash_position": {"cash_in_bank": 200000.0, "total_monthly_burn": 43000},
            "stripe": {"revenue": {"current": {"total_aud": 60000}}}}
    fc = FE.cash_flow_13wk(snap)
    hits = fc["tax_obligations_in_horizon"]
    assert hits and "2026-08-25" in hits
    wk = hits["2026-08-25"]["week"]
    # the curve drops by the obligation in that week (vs the smooth net_weekly path)
    smooth = fc["starting_cash"] + fc["net_weekly"] * wk
    assert abs((smooth - sum(h["amount"] for h in hits.values()
                             if h["week"] <= wk)) - fc["curve"][wk - 1]["projected_cash"]) < 1.0
    # a manual weekly set-aside disables the spike path (no double count)
    FE.set_assumption("weekly_tax_setaside", 500)
    try:
        fc2 = FE.cash_flow_13wk(snap)
        assert fc2["tax_obligations_in_horizon"] is None
    finally:
        FE.set_assumption("weekly_tax_setaside", 0)


def test_salience_t14_t3_and_watermark_ids(monkeypatch):
    _reset()
    import kv_store
    est = BE._compute(_inputs(), TODAY)
    kv_store.put("bas:estimate", est)
    import helpers
    # T-14: 2026-08-12 is 13 days before the 25 Aug prior-BAS deadline
    monkeypatch.setattr(helpers, "today_sydney", lambda: dt.date(2026, 8, 12))
    ev = BE.salience_events()
    due = [e for e in ev if e["type"] == "bas_due"]
    assert due and due[0]["id"].endswith(":14") and "estimate" in due[0]["spoken"]
    # T-3 fires the higher-salience id
    monkeypatch.setattr(helpers, "today_sydney", lambda: dt.date(2026, 8, 23))
    ev3 = [e for e in BE.salience_events() if e["type"] == "bas_due"]
    assert ev3[0]["id"].endswith(":3") and ev3[0]["salience"] > due[0]["salience"]


def test_edith_answers_carry_the_disclaimer():
    _reset()
    import kv_store
    kv_store.put("bas:estimate", BE._compute(_inputs(), TODAY))
    for q in ("what's our BAS looking like?", "when's the BAS due?",
              "how much should I set aside?"):
        r, h = BE.handle_bas_command(q)
        assert h and "accountant" in r, q          # the standing line, spoken
    r, _ = BE.handle_bas_command("when's the BAS due?")
    assert "2026-08-25" in r and "2026-11-25" in r  # agent dates, both obligations
    r, _ = BE.handle_bas_command("how much should I set aside?")
    assert "73,000" in r.replace("$", "") or "73,00" in r  # spoken-for ≈ $73.0k
    assert BE.handle_bas_command("hello there")[1] is False


def test_decomposition_delta_arithmetic():
    _reset()
    est = BE._compute(_inputs(), TODAY)
    est["history"] = [{"date": "2026-06-30", "gst": 41138.08, "paygw": None}]
    d = BE._decompose(est)
    assert d["delta_net"] == round(est["gst"]["projected_full_quarter"] - 41138.08, 2)
    # the residual IS the unexplained remainder — named, never hidden
    assert d["residual_spend_mix_and_timing"] == d["delta_net"]
    # the EOFY-journal caveat fires for the Jul-start quarter
    assert "EOFY" in (d["caveat"] or "")


def test_read_only_xero_and_one_engine():
    src = open(os.path.join(os.path.dirname(__file__), "..", "bas_engine.py")).read()
    for needle in ("requests.post", "requests.put", "requests.delete",
                   "http_requests.post", "requests.patch"):
        assert needle not in src   # kv_store.put is local state, not Xero
    # every surface reads bas_engine — no second BAS math in the render paths
    routes = open(os.path.join(os.path.dirname(__file__), "..", "dashboard", "routes.py")).read()
    assert "bas_engine.estimate()" in routes and "bas_engine.scheduled_obligations()" in routes
    fe = open(os.path.join(os.path.dirname(__file__), "..", "forecasting_engine.py")).read()
    assert "bas_engine.scheduled_obligations()" in fe
