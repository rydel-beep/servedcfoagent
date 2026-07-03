"""
tests/test_metric_consistency.py
--------------------------------
ONE ENGINE PER METRIC — the guard that makes the four-way contradiction un-shippable.
Asserts the snapshot's hormozi values are IDENTICAL to the engine's for the same window,
and that ROAS is the locked contracted basis. If any consumer ever recomputes a metric
independently and drifts, this suite fails.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hormozi_metrics as hz

# A fixed engine result — every delegated metric must echo THESE values verbatim.
_ENG = {
    "ltgp_cac": 2.69, "roas": 5.4, "ltv_cac": 7.77, "cac_loaded": 2433.98, "caveats": [],
    "components": {"ltgp": 6547.0, "cac_loaded": 2433.98, "closes": 6, "avg_contract": 18300.0,
                   "gross_margin_pct": 71.1, "contract_value_total": 109800.0, "ad_spend": 8473.0,
                   "new_deal_cash": 24965.0, "cac_breakdown": "ad + closer + setter ÷ 6 closes",
                   "window": {"days": 30}},
    "cohort": {"sets": 26, "show_to_close_pct": 44.4},
}


def test_hormozi_equals_engine(monkeypatch):
    monkeypatch.setattr(hz, "_engine_30d", lambda: _ENG)
    h = hz.compute_all({}, targets={})
    # every delegated metric == the engine's value (one value, everywhere)
    assert h["ltgp_cac"]["value"] == _ENG["ltgp_cac"]
    assert h["ltgp_to_cac"]["value"] == _ENG["ltgp_cac"]      # KPI alias agrees too
    assert h["roas"]["value"] == _ENG["roas"]
    assert h["ltv_to_cac"]["value"] == _ENG["ltv_cac"]
    assert h["cac_loaded"]["value"] == _ENG["cac_loaded"]


def test_greeting_headline_equals_engine(monkeypatch):
    monkeypatch.setattr(hz, "_engine_30d", lambda: _ENG)
    hl = hz.compute_all({}, targets={})["_sales_headline"]
    # the greeting reads THIS — same sets/closes/cash as the engine, never the scorecard
    assert hl["sets"] == 26 and hl["closes"] == 6 and hl["new_deal_cash"] == 24965.0


def test_roas_is_contracted_not_cash(monkeypatch):
    monkeypatch.setattr(hz, "_engine_30d", lambda: _ENG)
    roas = hz.compute_all({}, targets={})["roas"]
    assert "contracted" in roas["read"].lower() and "cash" not in roas["read"].lower()
    # and the range engine itself computes contracted (not cash)
    import range_unit_economics as rue
    src = open(os.path.join(os.path.dirname(__file__), "..", "range_unit_economics.py")).read()
    assert "roas = round(contract_total / ad_spend" in src   # contracted formula, single site


def test_no_duplicate_roas_formula():
    """No site other than the range engine may compute ROAS from a revenue/spend ratio."""
    import glob
    offenders = []
    for f in glob.glob(os.path.join(os.path.dirname(__file__), "..", "*.py")):
        if os.path.basename(f) in ("range_unit_economics.py",):
            continue
        src = open(f).read()
        # a bare "roas = ... / ad_spend" formula outside the engine is a duplicate
        import re
        if re.search(r"roas\s*=\s*round\([^)]*/\s*ad_spend", src):
            offenders.append(os.path.basename(f))
    assert not offenders, f"duplicate ROAS formula in: {offenders}"
