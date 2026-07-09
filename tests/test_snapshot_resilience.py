"""
tests/test_snapshot_resilience.py
---------------------------------
Regression guards for the 2026-07-09 outage: a scorecard em-dash crashed _pull_deep_dive
(float('—')), which crashed build_snapshot, which took the whole dashboard down. Guards:
  1) _parse_float tolerates blanks + human placeholders → None, never raises.
  2) build_snapshot fail-softs a crashing source (degrades it, still builds).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sales_analytics_pull as sap


def test_parse_float_tolerates_placeholders():
    assert sap._parse_float("—") is None          # the exact crash input
    assert sap._parse_float("–") is None and sap._parse_float("-") is None
    assert sap._parse_float("N/A") is None and sap._parse_float("TBC") is None
    assert sap._parse_float("") is None and sap._parse_float(None) is None
    assert sap._parse_float("3.5") == 3.5 and sap._parse_float("1,200") == 1200.0
    assert sap._parse_float("42%") == 42.0


def test_safe_result_degrades_a_crashing_source():
    from snapshot import _safe_result
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        bad = pool.submit(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        out = _safe_result(bad, "sales_analytics")
    assert out["degraded"][0]["metric"] == "sales_analytics"
    assert "boom" in out["degraded"][0]["reason"]      # labelled, not raised


def test_safe_result_passes_through_success():
    from snapshot import _safe_result
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        good = pool.submit(lambda: {"value": 42, "degraded": []})
    assert _safe_result(good, "x") == {"value": 42, "degraded": []}
