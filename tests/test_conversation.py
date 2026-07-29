"""Conversational continuity: advisory routing, anaphora parsing, scenario math, repetition guard."""
import conversation as C
import scenario_engine as S


def test_advisory_matches_strategy_not_lookup():
    assert C._ADVISORY_RE.search("How can we reduce CAC?")
    assert C._ADVISORY_RE.search("how do we improve ROAS")
    assert not C._ADVISORY_RE.search("what's our CAC?")          # a lookup, not advisory


def test_anaphora_delta_parsing():
    assert C._parse_deltas("an extra 3 more closes")[0] == {"closes_add": 3}
    assert C._parse_deltas("what if we had 5 more closes?")[0] == {"closes_add": 5}
    assert C._parse_deltas("with double the ad spend")[0] == {"ad_mult": 2.0}
    assert C._parse_deltas("what if ad spend halves?")[0] == {"ad_mult": 0.5}
    assert C._parse_deltas("and over 60 days?")[1] == 60
    assert C._parse_deltas("and the ratio?")[2] == "ltgp_cac"


def test_active_metric_from_history():
    h = [{"role": "user", "content": "how's ROAS?"}, {"role": "assistant", "content": "ROAS is 13x"}]
    assert C.active_metric(h) == "roas"
    assert C.active_metric([{"role": "user", "content": "what about 3 more closes?"}]) is None


def test_clarifier_only_with_concrete_delta():
    # concrete delta, no metric context → clarifier (handled)
    r, h = C.handle_anaphora("what about 3 more closes?", [])
    assert h and "which metric" in r.lower()
    # vague what-if, no metric, no delta → falls through (forecast/model owns it)
    r2, h2 = C.handle_anaphora("what if things go well?", [])
    assert h2 is False


def test_scenario_cac_math(monkeypatch):
    base = {"window_days": 30, "ad_spend": 9600, "closer_comm": 10200, "setter_comm": 2550,
            "closes": 8, "cac_loaded": 2794.0, "contract_value_total": 128000, "avg_contract": 16000,
            "gross_margin_pct": 80.0, "ltgp_cac": 4.58, "roas": 13.3}
    monkeypatch.setattr(S, "base_components", lambda w=30: base)
    r = S.compute("cac", {"closes_add": 3}, 30)                  # 22350 / 11 = 2031.8
    assert abs(r["scenario_value"] - 2031.82) < 1 and r["pct_change"] < 0
    r2 = S.compute("cac", {"closes_add": 3}, 30, scale_comms=True)   # comms scale per-close
    assert r2["scenario_value"] > r["scenario_value"]           # scaling comms → higher CAC
    r3 = S.compute("roas", {"ad_mult": 2.0}, 30)               # halves ROAS
    assert abs(r3["scenario_value"] - 6.65) < 0.2


def test_repetition_guard_logic():
    from dashboard.routes import _repetition_failure
    hist = [{"role": "user", "content": "cac?"}, {"role": "assistant", "content": "CAC is $2,793."}]
    # a DIFFERENT question that would re-emit the identical line → failure
    assert _repetition_failure("CAC is $2,793.", hist, "loaded cac please") is True
    # the SAME question re-asked → acceptable (not a failure)
    hist2 = hist + [{"role": "user", "content": "loaded cac please"}, {"role": "assistant", "content": "CAC is $2,793."}]
    assert _repetition_failure("CAC is $2,793.", hist2, "cac?") is False
