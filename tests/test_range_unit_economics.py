"""
tests/test_range_unit_economics.py
----------------------------------
Range-aware unit economics: NL range parsing, window-consistent math (one window →
every input), the confirmed bases (spend-in-window, cash-ROAS, contract-value LTV),
and edge cases (zero/small windows, no div-by-zero).
"""
from __future__ import annotations

import sys, os, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import range_unit_economics as rue

TODAY = dt.date(2026, 6, 25)


def test_parse_range_variants():
    def p(t): return rue.parse_range(t, TODAY)
    assert p("LTGP:CAC in May")[0:2] == (dt.date(2026, 5, 1), dt.date(2026, 5, 31))
    assert p("ROAS last 3 weeks")[0:2] == (TODAY - dt.timedelta(days=20), TODAY)
    assert p("CAC between 2026-03-01 and 2026-03-15")[0:2] == (dt.date(2026, 3, 1), dt.date(2026, 3, 15))
    assert p("this month")[0] == dt.date(2026, 6, 1)
    assert p("last month")[0:2] == (dt.date(2026, 5, 1), dt.date(2026, 5, 31))
    assert p("year to date")[0] == dt.date(2026, 1, 1)
    assert p("Q1 2026")[0:2] == (dt.date(2026, 1, 1), dt.date(2026, 3, 31))
    assert p("yesterday")[0] == dt.date(2026, 6, 24)
    assert p("last 30 days")[0] == TODAY - dt.timedelta(days=29)
    # a future month name (December, with today in June) assumes last year
    assert p("December")[0].year == 2025
    assert p("how's business") is None


# A tiny faithful LTC tracker. The sheet has TWO "Call Outcome" cols: col 16 = SETTER
# outcome ("SET"), col 23 = CLOSER outcome ("won" = a close). The engine must read col 23.
_HDR = [""]*41
_HDR[1]="Input Date"; _HDR[3]="Lead Name"; _HDR[16]="Call Outcome"; _HDR[22]="Show Status"
_HDR[23]="Call Outcome"; _HDR[26]="Offer Sold"; _HDR[27]="Close Date"
_HDR[28]="4 · MONEY Contract Value"; _HDR[32]="Cash Collected"; _HDR[40]="Commission Closer"
_LTC = [_HDR]
def _row(close, contract, cash, closer, outcome="won", input=None, show="Showed"):
    r = [""]*41
    r[1]=input if input is not None else close   # Input Date (cohort window)
    r[3]="Lead"; r[16]="SET"; r[22]=show; r[23]=outcome; r[26]="Scale Engine"; r[27]=close
    r[28]=str(contract); r[32]=str(cash); r[40]=str(closer)
    return r
_LTC += [
    _row("5/10/2026", 16000, 5000, 1500),               # May, won
    _row("5/20/2026", 18000, 6000, 1500),               # May, won
    _row("5/22/2026", 9000, 2000, 0, outcome="lost"),   # May but NOT won → excluded
    _row("6/24/2026", 14000, 4000, 1500),               # NOT May
]
# Setter log: lead/setter/won/cash/fee/bonus/.../notes(date)
def _pl(setter, fee, bonus, date):
    r = [""]*10; r[2]=setter; r[5]=str(fee); r[6]=str(bonus); r[9]=date; return r
_PL = [["SETTER PAYOUT LOG"]] + [
    _pl("Coby", 50, 250, "05/15/2026 payout"),   # May
    _pl("Maran", 50, 300, "05/18/2026 payout"),  # May
    _pl("Coby", 50, 100, "06/24/2026 payout"),   # not May
]


def _mock(monkeypatch, ltc=_LTC, pl=_PL, spend=4000.0, margin=70.0):
    import sheet_mirror, meta_spend
    monkeypatch.setattr(sheet_mirror, "read_by_name",
                        lambda n: ltc if "Lead-to-Cash" in n else (pl if "SETTER" in n else None))
    monkeypatch.setattr(meta_spend, "spend_in_range",
                        lambda s, e: {"spend": spend, "source": "meta_daily_store", "degraded": []})
    monkeypatch.setattr(rue, "_gross_margin", lambda: margin)


def test_window_consistent_may(monkeypatch):
    _mock(monkeypatch)
    r = rue.unit_economics("2026-05-01", "2026-05-31")
    c = r["components"]
    assert c["closes"] == 2                       # only the two May deals
    assert c["contract_value_total"] == 34000.0   # 16k + 18k (June deal excluded)
    assert c["cash_collected_total"] == 11000.0
    assert c["closer_comm"] == 3000.0             # 1500 + 1500
    assert c["setter_comm"] == 650.0              # (50+250)+(50+300), June excluded
    assert c["ad_spend"] == 4000.0
    # CAC = (4000 + 3000 + 650) / 2 = 3825
    assert r["cac_loaded"] == 3825.0
    # LTGP = avg_contract 17000 × 0.70 = 11900 ; LTGP:CAC = 11900/3825
    assert c["avg_contract"] == 17000.0
    assert r["ltgp_cac"] == round(11900 / 3825, 2)
    # ROAS = cash 11000 / spend 4000 = 2.75 (cash basis)
    assert r["roas"] == 2.75
    # LTV:CAC = avg_contract 17000 / CAC 3825
    assert r["ltv_cac"] == round(17000 / 3825, 2)
    assert c["attribution"] == "spend-in-window" and c["roas_revenue_basis"] == "cash_collected"


def test_zero_closes_no_divzero(monkeypatch):
    _mock(monkeypatch)
    r = rue.unit_economics("2026-01-01", "2026-01-31")  # no deals
    assert r["ltgp_cac"] is None and r["cac_loaded"] is None and r["ltv_cac"] is None
    assert any("No closes" in c for c in r["caveats"])


def test_spend_no_closes_flagged(monkeypatch):
    _mock(monkeypatch, ltc=[_LTC[0]], spend=5000.0)  # header only → 0 closes, but spend
    r = rue.unit_economics("2026-05-01", "2026-05-31")
    assert r["cac_loaded"] is None and any("No closes" in c for c in r["caveats"])


def test_command_handler(monkeypatch):
    _mock(monkeypatch)
    from helpers import today_sydney  # ensure import path
    reply, handled = rue.handle_unit_econ_command("what's our LTGP:CAC in May 2026?")
    assert handled and "LTGP:CAC for May 2026" in reply and "×" in reply
    assert rue.handle_unit_econ_command("how's the coffee?")[1] is False


def test_roas_cash_basis(monkeypatch):
    _mock(monkeypatch, spend=2000.0)
    r = rue.unit_economics("2026-05-01", "2026-05-31")
    assert r["roas"] == round(11000.0 / 2000.0, 2)  # cash / spend, not contracted


def test_cohort_by_input_date(monkeypatch):
    import datetime as dt
    _mock(monkeypatch)
    # May cohort by INPUT DATE: rows with input in May = the 3 May rows (10th/20th won, 22nd lost).
    cf = rue.cohort_funnel(dt.date(2026, 5, 1), dt.date(2026, 5, 31))
    assert cf["leads_in"] == 3 and cf["closes"] == 2          # 2 of the 3 May-input leads won
    assert cf["lead_to_close_pct"] == round(100 * 2 / 3, 1)   # 66.7%
    # The money view (by Close Date) and cohort (by Input Date) are surfaced together.
    res = rue.unit_economics("2026-05-01", "2026-05-31")
    assert res["cohort"]["leads_in"] == 3 and res["components"]["closes"] == 2


def test_cohort_voice_command(monkeypatch):
    _mock(monkeypatch)
    reply, handled = rue.handle_unit_econ_command("how is this month's lead flow converting?")
    assert handled and "cohort" in reply.lower() and "lead→close" in reply.lower()
    # A pure money question must NOT be hijacked by the cohort branch.
    assert "LTGP:CAC for" in rue.handle_unit_econ_command("what's our LTGP:CAC in May 2026?")[0]
