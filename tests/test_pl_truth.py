"""NET PROFIT, TRUTHFULLY (#165).

Pinned here:
  1 the ladder arithmetic, GST discipline, PIF spreading, tax accrual
  2 calendar-only windows — no rolling window survives as a citable source
  3 LTGP on GROSS margin, never contribution
  4 the answer guard: an unbacked number cannot pass; deflection cannot pass
  5 the mapping never silently bins an account
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


# ── 1 · THE LADDER ──────────────────────────────────────────────────────────

def test_the_ladder_arithmetic_holds():
    import pl_engine as PL
    r = PL._rungs(100000, 5900, 36200, 20000, 22000, 0, "")
    assert r["net_revenue"] == 94100.0
    assert r["gross_profit"] == 57900.0
    assert r["contribution"] == 37900.0
    assert r["operating_profit"] == 15900.0
    # tax accrues on PBT at 25%, and the note says whose estimate it is
    tax = round(max(r["operating_profit"], 0) * PL.TAX_RATE, 2)
    assert tax == 3975.0
    r2 = PL._rungs(100000, 5900, 36200, 20000, 22000, tax, "planning estimate")
    assert r2["net_profit"] == 11925.0
    assert "estimate" in r2["tax_note"]


def test_gst_never_sits_inside_revenue():
    """A $3,355 Stripe receipt is $3,050 of revenue."""
    assert round(3355 / 1.1, 2) == 3050.0
    src = _code_only(_read("pl_engine.py"))
    assert "/ 1.1" in src, "Stripe receipts must be divided to ex-GST"
    # and GST/PAYG/BAS never appear as ladder cost lines
    import pl_mapping as PM
    for name in ("GST paid", "PAYG Withholding", "BAS payment"):
        c = PM.classify(name)
        assert c["line"] in ("tax_statutory", "unmapped"), name
        assert c["line"] != "overhead"


def test_a_pif_spreads_on_the_management_basis():
    """A $14,500 prepayment over a 6-month term is $2,416.67 a month of
    management revenue — the Health tab's own MRR column already carries
    contract ÷ term, and the engine pro-rates it by days of service."""
    import pl_engine as PL
    rows = [{"name": "PIF Client", "status": "Active",
             "start": dt.date(2026, 8, 1), "end": dt.date(2027, 1, 31),
             "mrr": round(14500 / 6, 2)}]
    orig = PL._roster_rows
    PL._roster_rows = lambda: rows
    try:
        aug = PL.contract_revenue("2026-08")
        sep_half = PL.contract_revenue("2026-02")   # outside the term
    finally:
        PL._roster_rows = orig
    assert aug["total"] == round(14500 / 6, 2)      # full month inside term
    assert sep_half["total"] == 0.0                 # outside the term: nothing
    # partial month: starts mid-month
    rows[0]["start"] = dt.date(2026, 8, 16)
    PL._roster_rows = lambda: rows
    try:
        part = PL.contract_revenue("2026-08")
    finally:
        PL._roster_rows = orig
    assert 0 < part["total"] < aug["total"]
    assert part["clients"][0]["fraction"] == round(16 / 31, 3)


def test_windows_are_calendar_only_no_rolling_source_survives():
    """The mid-month rolling read produced '6.9%'. It can no longer be
    cited: the engine has no rolling window, EDITH's context no longer
    carries the snapshot profit block, and the dump withholds it."""
    import pl_engine as PL
    assert set(PL.WINDOWS) == {"mtd", "last_month", "t3", "t12", "fytd",
                               "same_month_ly"}
    src = _code_only(_read("pl_engine.py"))
    assert "WINDOW_CURRENT" not in src
    assert "timedelta(days=30)" not in src
    chat = _read("dashboard", "chat.py")
    code = _code_only(chat)
    assert 'snap.get("profit")' not in code, \
        "the rolling profit block is back in EDITH's context"
    assert '_s.pop("profit", None)' in code, \
        "the raw dump must withhold the rolling block"


def test_month_bounds_and_backwalk():
    import pl_engine as PL
    assert PL.month_bounds("2026-02") == ("2026-02-01", "2026-02-28")
    assert PL.month_bounds("2026-08") == ("2026-08-01", "2026-08-31")


# ── 2 · NORMALISATION + ONE-OFFS ────────────────────────────────────────────

def test_an_annual_subscription_is_spread_and_a_one_off_is_flagged(monkeypatch):
    import pl_engine as PL
    kv_store._MEM.clear()
    # recognised month with a lumpy subscriptions line
    month = {"ok": True, "month": "2026-08",
             "window": {"start": "2026-08-01", "end": "2026-08-31"},
             "revenue": 80000.0,
             "opex_line_items": [
                 {"label": "Subscriptions", "amount": 6540.97},
                 {"label": "Contractors NO GST", "amount": 28030.26},
                 {"label": "Advertising", "amount": 8727.04}],
             "cogs_line_items": [], "pulled_at": "2026-09-24T10:00:00"}
    for pm in ("2026-07", "2026-06", "2026-05"):
        kv_store.put(PL.K_XERO_MONTH.format(m=pm), {
            "ok": True, "month": pm, "revenue": 78000.0,
            "opex_line_items": [{"label": "Subscriptions", "amount": 540.97},
                                {"label": "Contractors NO GST", "amount": 27000.0},
                                {"label": "Advertising", "amount": 9000.0}],
            "cogs_line_items": [], "pulled_at": "x"})
    kv_store.put(PL.K_XERO_MONTH.format(m="2026-08"), month)
    monkeypatch.setattr(PL, "_roster_rows", lambda: [
        {"name": "C1", "status": "Active", "start": dt.date(2026, 1, 1),
         "end": dt.date(2027, 1, 1), "mrr": 72000.0}])
    monkeypatch.setattr(PL, "_cur_month", lambda: "2026-09")
    PL.set_normalisation("Subscriptions", 540.97, "rydel",
                         "annual licences spread monthly")
    mg = PL.management("2026-08")
    assert mg["ok"]
    # normalised: overhead carries the monthly figure, and the adjustment
    # names the spread
    labels = [a["label"] for a in mg["adjustments"]]
    assert any("Subscriptions: normalised" in l for l in labels)
    # the same lumpy line is ALSO flagged as a one-off, in the open
    flagged = [f["account"] for f in mg["one_offs_flagged"]]
    assert "Subscriptions" in flagged


# ── 3 · LTGP ON GROSS ───────────────────────────────────────────────────────

def test_ltgp_margin_is_gross_never_contribution():
    import pl_engine as PL
    import compass_engine as CE
    kv_store._MEM.clear()
    gm = PL.gross_margin_for_ltgp()
    assert gm["pct"] == 63.8                        # the FY26 fallback
    assert "contribution" in gm["provenance"].lower()   # the reason stated
    assert CE.FY26_MARGIN_PCT == 63.8
    fa = _code_only(_read("finance_analysis.py"))
    assert "42.9" not in fa, "the contribution fallback is back"
    assert "gross_margin_for_ltgp" in fa


def test_the_before_after_is_material():
    """2.95× on contribution → ≈4.4× on gross, same CAC: the defect halved
    the reported return on acquisition."""
    ltv, cac = 33716.25, 4900.0
    was = round(ltv * 0.429 / cac, 2)
    now = round(ltv * 0.638 / cac, 2)
    assert was < 3.0 < now


# ── 4 · THE ANSWER GUARD ────────────────────────────────────────────────────

_CTX = ("PROFIT & LOSS (the P&L engine): management_mtd net_profit 15389.02 "
        "net_margin_pct 19.0 revenue 81106.81 · recognised net 20518.7 "
        "margin 25.3 · committed_mrr 72887.52")


def test_the_witnessed_failure_cannot_happen_again():
    from dashboard import answer_guard as AG
    reply = "Net profit margin is 6.9% — $3,400 ÷ $49,396."
    out, v = AG.apply(reply, _CTX)
    assert not v["ok"]
    assert {n["text"] for n in v["unbacked"]} == {"6.9%", "$3,400", "$49,396"}
    assert "can't back" in out and "6.9%" in out


def test_engine_backed_numbers_pass_with_normal_rounding():
    from dashboard import answer_guard as AG
    _, v = AG.apply("Net was $15,389 (19%) on revenue of about $81,100; "
                    "recognised came to $20,519 at 25.3%.", _CTX)
    assert v["ok"], v


def test_deflection_is_rewritten():
    from dashboard import answer_guard as AG
    out, v = AG.apply("Best to pull the live P&L from the finance dashboard.", _CTX)
    assert v["deflection"] and "let me pull it" in out


def test_general_turns_are_not_policed():
    from dashboard import answer_guard as AG
    _, v = AG.apply("A decent espresso machine is about $700.", None)
    assert v.get("skipped")


def test_an_injected_stale_summary_figure_cannot_pass():
    """The acceptance drill: a figure from a cached summary that is NOT in
    this turn's engine context is blocked even though it once was true."""
    from dashboard import answer_guard as AG
    stale = "Last month we did $49,396 in revenue."
    _, v = AG.apply(stale, _CTX)
    assert not v["ok"]
    assert v["unbacked"][0]["text"] == "$49,396"


def test_years_dates_and_small_counts_pass():
    from dashboard import answer_guard as AG
    _, v = AG.apply("Since 2026 we've closed 4 deals; margin 19% as of "
                    "September 24.", _CTX)
    assert v["ok"], v


def test_both_chat_paths_run_the_guard():
    code = _code_only(_read("dashboard", "chat.py"))
    assert code.count("answer_guard.apply(") >= 2
    assert "system if business_intent else None" in code


# ── 5 · HANDLERS + DECOY ────────────────────────────────────────────────────

def test_the_margin_drill_answers_three_bases_with_periods(monkeypatch):
    import pl_engine as PL
    kv_store._MEM.clear()
    kv_store.put(PL.K_SUMMARY, {"computed_at": "x", "error": None, "data": {
        "management_mtd": {"ok": True, "window_words": "September 2026 (month to date)",
                           "net_profit": 15389.02, "net_revenue": 81106.81,
                           "net_margin_pct": 19.0, "gross_margin_pct": 58.6,
                           "operating_margin_pct": 25.3,
                           "projection": {"available": True, "net_profit": 16000,
                                          "net_margin_pct": 19.5}},
        "recognised_last_month": {"ok": True, "window_words": "August 2026",
                                  "net_profit": 20518.7, "net_revenue": 81106.81,
                                  "net_margin_pct": 25.3, "gross_margin_pct": 58.6,
                                  "operating_margin_pct": 25.3},
        "run_rate_t3": {"ok": False, "reason": "months pending"},
        "fy26_baseline": PL.FY26, "as_of": "2026-09-24T20:00:00"}})
    r, h = PL.handle_margin_query("what's our net profit margin")
    assert h
    assert "Management (September 2026 (month to date))" in r
    assert "Recognised (August 2026)" in r
    assert "19.0%" in r and "25.3%" in r
    assert "As of 2026-09-24" in r
    assert "never blended" in r


def test_the_decoy_is_declined():
    import pl_engine as PL
    r, h = PL.handle_margin_query("what's our EBITDA by state")
    assert h and "isn't a metric the engine computes" in r
    assert not re.search(r"\d", r.replace("net, gross", ""))  # no invented figures


def test_the_bridge_drill_names_the_items():
    import pl_engine as PL
    kv_store._MEM.clear()
    kv_store.put(PL.K_SUMMARY, {"computed_at": "x", "data": {
        "bridge_last_month": {"month": "2026-08", "items": [
            {"label": "income tax accrual (management only)", "amount": 5129.68,
             "why": "management accrues 25% monthly"},
            {"label": "revenue basis (contracts vs the books)", "amount": 8218.81,
             "why": "invoiced one-offs and AR"}],
            "nets": {"management": 15389.02, "recognised": 20518.7,
                     "cash": 10245.5}}}})
    r, h = PL.handle_bridge_query("why is this month below run-rate")
    assert h and "income tax accrual" in r and "$5,130" in r


# ── 6 · THE MAPPING ─────────────────────────────────────────────────────────

def test_an_unknown_account_is_never_silently_binned():
    import pl_mapping as PM
    kv_store._MEM.clear()
    c = PM.classify("Mystery Vendor Costs")
    assert c["line"] == "unmapped" and c["needs_call"]
    lines = PM.ladder_lines([{"label": "Mystery Vendor Costs", "amount": 999.0}],
                            50000.0)
    assert lines["unmapped"]["total"] == 999.0
    assert lines["unmapped"]["items"][0]["account"] == "Mystery Vendor Costs"


def test_an_owner_ruling_is_journaled_and_wins():
    import pl_mapping as PM
    kv_store._MEM.clear()
    res = PM.set_override("Mystery Vendor Costs", "delivery", "rydel",
                          "it's a client deliverable")
    assert res["ok"]
    c = PM.classify("Mystery Vendor Costs")
    assert c["line"] == "delivery" and "owner" in c["source"]
    j = kv_store.get(PM.K_JOURNAL)
    assert j and j[-1]["to"] == "delivery" and j[-1]["by"] == "rydel"


def test_the_mapping_page_surfaces_needs_your_call():
    import pl_mapping as PM
    kv_store._MEM.clear()
    # "unmapped" is not a rulable line — the API refuses it
    assert PM.set_override("X", "unmapped", "rydel")["ok"] is False
    PM.set_override("Half Known Thing", "overhead", "rydel", "misc")
    page = PM.mapping_page()
    assert any(r["account"] == "half known thing" for r in page["rows"])
    # a tax-named unknown is flagged for confirmation, never silently binned
    assert PM.classify("ATO Instalment Something")["needs_call"] is True
    assert "timing" in page["note"]


# ── 7 · SURFACES + FRESHNESS ────────────────────────────────────────────────

def test_the_pl_page_never_pulls_xero_on_load():
    src = _read("dashboard", "routes.py")
    fn = src[src.index("def pl_page"):src.index("def api_pl(")]
    assert "cached" in fn.lower() or "CACHED" in src[src.index("def pl_page") - 400:
                                                     src.index("def pl_page")]
    assert "refresh_summary" not in _code_only(fn)
    assert "pull_pl_range" not in fn


def test_the_today_tile_reads_the_cache_only():
    src = _code_only(_read("dashboard", "today.py"))
    i = src.index("Net margin (management basis)")
    seg = src[max(0, i - 1600):i + 800]
    assert "cached_summary()" in seg
    assert "refresh_summary" not in seg


def test_the_stripe_stamp_is_no_longer_the_snapshots():
    """A 2-hour job was stamping a 20-minute promise — 'STRIPE RECEIPTS IS
    LATE' by design. The tick probes Stripe itself now."""
    src = _read("freshness.py")
    code = _code_only(src)
    assert "stripe:last_pull" in code
    fn = src[src.index("def tick("):src.index("def _block_builders")]
    assert "_recent_charges(2)" in fn
    stamps = src[src.index("def _source_stamps"):src.index("def sources(")]
    assert "stripe:last_pull" in stamps


def test_the_summary_is_computed_on_the_loop_not_the_request():
    app_src = _code_only(_read("app.py"))
    assert "pl_engine.refresh_summary()" in app_src
    fresh = _read("freshness.py")
    assert '_step("P&L summary", _pl)' in fresh


def test_mtd_contract_revenue_pro_rates_to_today(monkeypatch):
    """Caught live: MTD management revenue counted the FULL month's
    contracts against part-month costs — 37.8% where the honest projection
    said 27.8%. A month-to-date margin earns only the days that have
    happened."""
    import pl_engine as PL
    kv_store._MEM.clear()
    kv_store.put(PL.K_XERO_MONTH.format(m="2026-09"), {
        "ok": True, "month": "2026-09", "revenue": 40000.0,
        "opex_line_items": [{"label": "Advertising", "amount": 5000.0}],
        "cogs_line_items": [], "pulled_at": "x"})
    monkeypatch.setattr(PL, "_cur_month", lambda: "2026-09")
    monkeypatch.setattr(PL, "_roster_rows", lambda: [
        {"name": "C1", "status": "Active", "start": dt.date(2026, 1, 1),
         "end": dt.date(2027, 1, 1), "mrr": 60000.0}])
    import helpers
    monkeypatch.setattr(PL, "today_sydney",
                        lambda: dt.date(2026, 9, 15))
    mg = PL.management("2026-09")
    assert mg["ok"]
    assert mg["revenue"] == 30000.0          # 15 of 30 days
    assert "pro-rated to day 15" in mg["contract_revenue"]["provenance"]
