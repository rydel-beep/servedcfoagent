"""
tests/test_scoreboard_contract.py — scoreboard date-binding + contract value
(DECISIONS #140).

Contract value is a ONE-ENGINE windowed metric BESIDE cash (never swapped);
a blank contract cell adds 0 AND is counted (blank ≠ zero), never a real $0;
the tiles + delta follow the selected window on the same clock; cash is
UNCHANGED (additive). The delta covers custom ranges (all-time skipped honestly).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attribution_engine as eng
from tests.test_attribution import HDR, RES_A, contact, resolver, row

W0, W1 = dt.date(2026, 7, 1), dt.date(2026, 7, 31)


def _world(basis="activity"):
    # 3 closes in-window: two with contract, one BLANK contract (won, no value)
    rows = [HDR,
            row("Signed Full", "a@x.com", input_date="2026-07-05", closer="won",
                close_date="2026-07-20", contract="15000", cash="15000"),
            row("Signed Partial", "b@x.com", input_date="2026-07-06", closer="won",
                close_date="2026-07-22", contract="10000", cash="4000"),
            row("Blank Contract", "c@x.com", input_date="2026-07-07", closer="won",
                close_date="2026-07-25", contract="", cash="2000")]
    contacts = [contact("c1", "a@x.com", "Signed Full"),
                contact("c2", "b@x.com", "Signed Partial"),
                contact("c3", "c@x.com", "Blank Contract")]
    return eng.compute_from_inputs(rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}),
                                   W0, W1, basis=basis)


def test_contract_total_beside_cash_never_swapped():
    h = eng.scoreboard_view(_world())["headline"]
    assert h["cash_total"] == 21000.0                 # 15000 + 4000 + 2000 (unchanged)
    assert h["contract_total"] == 25000.0             # 15000 + 10000 (+ blank adds 0)
    assert h["cash_total"] != h["contract_total"]     # two distinct truths
    assert h["closes_total"] == 3


def test_blank_contract_is_counted_not_zero_filled():
    h = eng.scoreboard_view(_world())["headline"]
    # the blank close is NOT summed as $0 into contract — it's COUNTED as missing
    assert h["contract_missing"] == 1
    # and the total reflects only the two recorded contracts (blank excluded)
    assert h["contract_total"] == 25000.0
    # the deal carries the honest note
    r = _world()
    deals = [d for c in r["creatives"] for d in c.get("deals") or []]
    blank = next(d for d in deals if d["name"] == "Blank Contract")
    assert blank["contract"] is None and "blank" in blank["note"]


def test_cash_unchanged_by_the_contract_addition():
    # cash reads identically with contract added — additive, no regression
    h = eng.scoreboard_view(_world())["headline"]
    assert h["cash_total"] == 21000.0
    assert h["cash_tiers"].get("ad") == 21000.0


def test_contract_follows_the_clock():
    # both clocks compute contract for their window (same window here → same value)
    for basis in ("cohort", "activity"):
        h = eng.scoreboard_view(_world(basis))["headline"]
        assert h["contract_total"] == 25000.0
        assert h["basis"] == basis


def test_contract_missing_is_a_drillable_roster_metric():
    import roster_engine as RE
    assert "contract_missing" in RE.ANOMALY_METRICS
    # the event handler treats it as a close, with the honest note
    ev = RE._event_for("contract_missing", {"close_date": dt.date(2026, 7, 25)}, {})
    assert ev["kind"] == "closed" and "not recorded" in ev["note"]


# ── the delta follows the selected window (custom included) ───────────────────

def test_delta_follows_custom_window_and_includes_contract(monkeypatch):
    import dashboard.ads as ADS
    calls = []

    def fake_compute(days=30, start=None, end=None, force=False, basis="cohort",
                     market=None, **kw):
        calls.append((start, end))
        r = _world(basis)
        r["window"] = {"start": start or "2026-07-01", "end": end or "2026-07-14",
                       "days": (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
                       if (start and end) else int(days)}
        return r
    monkeypatch.setattr("attribution_engine.compute", fake_compute, raising=True)
    # a 14-day custom range → the delta must compare the PRECEDING 14 days
    board = ADS._build_board(30, "2026-07-01", "2026-07-14", "activity")
    cmp = board["compare"]
    assert cmp is not None, "custom range must still get a delta"
    assert cmp["length_days"] == 14
    assert "prior 14d" in cmp["label"]
    assert "contract" in cmp["deltas"]                # contract joined the delta
    # the comparison window was the 14 days immediately before (2026-06-17..06-30)
    assert ("2026-06-17", "2026-06-30") in calls


def test_delta_skipped_for_all_time_honestly(monkeypatch):
    import dashboard.ads as ADS

    def fake_compute(days=30, start=None, end=None, **kw):
        r = _world("activity")
        r["window"] = {"start": "2016-08-11", "end": "2026-08-10", "days": ADS.ALL_DAYS}
        return r
    monkeypatch.setattr("attribution_engine.compute", fake_compute, raising=True)
    board = ADS._build_board(ADS.ALL_DAYS, None, None, "activity")
    assert board["compare"] is None                   # no period precedes "all time"


def test_js_shows_contract_beside_cash_not_swapped_and_gap():
    js = open(os.path.join(os.path.dirname(__file__), "..",
                           "dashboard", "static", "js", "adsapp.js")).read()
    seg = js.split("function renderHeadline")[1].split("function renderBanner")[0]
    assert "h.cash_total" in seg and "h.contract_total" in seg   # BOTH shown
    assert "cash · reconciled" in seg and "contract · tracker" in seg  # distinct provenance
    assert "contractGap(h)" in seg                    # the gap is rendered
    assert "missing contract value" in seg            # blank note
    assert "data-headdrill" in seg                    # drillable
    # the delta carries contract
    assert "cmp.deltas.contract" in js
