"""
tests/test_loaded_cac.py
------------------------
Fully-loaded CAC: real setter commission ($50/set + 5% cash) read from the SETTER
PAYOUT LOG (by name), window-matched; + the hormozi resolver (log actual → scorecard fallback).
"""
from __future__ import annotations

import sys, os, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import loaded_cac
from hormozi_metrics import _resolved_setter_comm, m2_cac_breakdown


class _Resp:
    def __init__(self, text, status=200): self.text, self.status_code = text, status


# col layout: lead(1) setter(2) won(3) cash(4) set_fee(5) pct_bonus(6) owed(7) status(8) notes/date(9)
_CSV = "\r\n".join([
    "SETTER PAYOUT LOG,,,,,,,,,",
    ",,,,,,,,,",                                   # padding
    ",Deal / Lead,Setter,Won,,,,,Status,Notes",     # header-ish
    ",The Leopard Deli,Coby,Yes,$5000,$50,$227.27,$277.27,Paid,06/23/2026 payout",  # in window
    ",Patel Piyush,Maran,No,,$50,$0.00,$50.00,Paid,06/10/2026 payout",              # in window
    ",Old Deal,Coby,Yes,$2000,$50,$100.00,$150.00,Paid,01/05/2026 payout",          # OUT of window
    ",NotASetter,Bob,Yes,$1000,$50,$50,$100,Paid,06/12/2026 payout",                # wrong setter → skip
])


def test_window_matched_setter_comp(monkeypatch):
    monkeypatch.setattr(loaded_cac.requests, "get", lambda *a, **k: _Resp(_CSV))
    r = loaded_cac.read_setter_comp("2026-05-26", "2026-06-25")
    # in-window Coby+Maran: set_fees 50+50=100 ; bonuses 227.27+0 = 227.27 ; total 327.27
    assert r["set_fees"] == 100.0
    assert r["pct_bonus"] == 227.27
    assert r["setter_comm"] == 327.27
    assert r["deal_count"] == 2  # old deal + wrong-setter excluded


def test_log_read_failure_degrades(monkeypatch):
    monkeypatch.setattr(loaded_cac.requests, "get", lambda *a, **k: _Resp("", 400))
    r = loaded_cac.read_setter_comp("2026-05-26", "2026-06-25")
    assert r["setter_comm"] is None
    assert r["degraded"] and r["degraded"][0]["severity"] == "optional"


def test_resolver_prefers_log_then_scorecard():
    log_snap = {"loaded_cac": {"setter_comm": 1507.27}, "sales": {"payout": {"total_owed": 500}}}
    assert _resolved_setter_comm(log_snap) == (1507.27, "setter_payout_log_actual")
    # log unavailable → scorecard fallback
    fallback = {"loaded_cac": {"setter_comm": None}, "sales": {"payout": {"total_owed": 500}}}
    assert _resolved_setter_comm(fallback) == (500, "scorecard_50_per_set_only")


def test_cac_uses_loaded_setter_and_breaks_down():
    snap = {"loaded_cac": {"setter_comm": 1507.27},
            "ad_spend_resolved": {"value": 8757.5, "source": "meta_live", "window_days": 30},
            "costs": {"closer_commission": 7200.0, "setter_commission": 0.0},
            "sales": {"funnel": {"closes": 4}, "deep": {"money": {"avg_contract": 16537.5}},
                      "payout": {"total_owed": 500}},
            "xero": {"gross_margin_pct": 71.1}}
    cac = m2_cac_breakdown(snap)
    assert cac["value"] == round((8757.5 + 7200 + 1507.27) / 4, 2) == 4366.19
    iu = cac["inputs_used"]
    assert iu["setter_payout"] == 1507.27 and iu["setter_comm_source"] == "setter_payout_log_actual"
    assert "Loaded: ad" in iu["breakdown"] and "setter $1,507 (log)" in iu["breakdown"]
