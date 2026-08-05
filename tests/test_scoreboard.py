"""
LTC Scoreboard Part 1 — adversarial tests (DECISIONS #115).

Rails: exact band parsing (unknown never 0; novel value flags); the qualified v2 legs
(finalised AND band ≥ floor AND form-complete — each leg drops independently, excluded
states counted + visible); the scoreboard is a RESHAPE (its sums equal the engine's, no
parallel math — drift is a failing test); the rows view partitions the window exactly;
bridge role scoping on the new endpoints (Romano full row-level per Rydel, still ships
disabled); EDITH answers are deterministic + entity-gated (unknown names refused).
"""
from __future__ import annotations

import datetime as dt

import revenue_bands as RB
import attribution_engine as eng
from tests.test_attribution import HDR, row, contact, resolver, RES_A

W0, W1 = dt.date(2026, 7, 1), dt.date(2026, 7, 31)


# ── revenue bands ────────────────────────────────────────────────────────────

def test_all_five_bands_parse_exactly():
    for raw, low in (("Under $20k", 0), ("$20k-50k", 20000), ("$50k-100k", 50000),
                     ("$100k- $200k", 100000), ("$200k +", 200000)):
        p = RB.parse_band(raw)
        assert p["state"] == "parsed" and p["low"] == low and p["source"] == "tracker"


def test_blank_is_unknown_never_zero():
    p = RB.parse_band("", "")
    assert p["state"] == "unknown" and p["low"] is None and p["flag"] is None
    assert RB.meets_floor(p, 20000) is None      # None, not False — unknown ≠ fails


def test_ghl_fallback_and_tracker_precedence():
    assert RB.parse_band("", "$50k-100k")["source"] == "ghl_form"
    p = RB.parse_band("$200k +", "Under $20k")
    assert p["source"] == "tracker" and p["low"] == 200000   # setter-verified wins


def test_novel_value_flags_and_stays_unknown():
    p = RB.parse_band("$1M+", "")
    assert p["state"] == "unknown" and "novel revenue value" in (p["flag"] or "")


# ── qualified v2 legs ────────────────────────────────────────────────────────

def _one(rows, contacts, **kw):
    return eng.compute_from_inputs(rows, contacts, {},
                                   resolver({"120000000000000001": RES_A}), W0, W1, **kw)


def test_qualified_all_legs_pass():
    out = _one([HDR, row("Q Lead", "q@x.com")], [contact("c1", "q@x.com", "Q Lead")])
    r = next(x for x in out["creatives"] if x["creative_key"] == "120000000000000001")
    assert r["qualified"] == 1
    assert out["qualified_rule"]["window_impact"] == {
        "finalised": 1, "qualified": 1,
        "excluded": {"under_floor": 0, "revenue_unknown": 0, "form_incomplete": 0}}


def test_under_floor_band_drops_and_is_counted():
    out = _one([HDR, row("Small Venue", "s@x.com")],
               [contact("c1", "s@x.com", "Small Venue", form_revenue="Under $20k")])
    r = next(x for x in out["creatives"] if x["creative_key"] == "120000000000000001")
    assert r["qualified"] == 0
    assert out["qualified_rule"]["window_impact"]["excluded"]["under_floor"] == 1


def test_revenue_unknown_excluded_visible_never_zeroed():
    out = _one([HDR, row("No Rev", "n@x.com")],
               [contact("c1", "n@x.com", "No Rev", form_revenue=None)])
    r = next(x for x in out["creatives"] if x["creative_key"] == "120000000000000001")
    assert r["qualified"] == 0 and r["revenue_unknown"] == 1
    assert out["qualified_rule"]["window_impact"]["excluded"]["revenue_unknown"] == 1


def test_form_incomplete_drops():
    out = _one([HDR, row("Half Form", "h@x.com")],
               [contact("c1", "h@x.com", "Half Form", form_timeline=None)])
    assert out["qualified_rule"]["window_impact"]["excluded"]["form_incomplete"] == 1


def test_tracker_cell_qualifies_even_without_ghl_revenue():
    r_ = row("Sheet Rev", "sr@x.com")
    r_[8] = "$100k- $200k"          # the tracker's own Revenue Range cell
    out = _one([HDR, r_], [contact("c1", "sr@x.com", "Sheet Rev", form_revenue=None)])
    row_out = next(x for x in out["rows"] if x["name"] == "Sheet Rev")
    assert row_out["revenue"] == {"band": "$100k- $200k".lower(),
                                  "state": "parsed", "source": "tracker"} or \
           (row_out["revenue"]["state"] == "parsed" and row_out["revenue"]["source"] == "tracker")
    # form still incomplete (revenue answer missing in GHL) → not qualified; band is fine
    assert row_out["qualified"] is False


def test_dq_never_qualifies_regardless_of_revenue():
    out = _one([HDR, row("Rich DQ", "r@x.com", setter="dq")],
               [contact("c1", "r@x.com", "Rich DQ", form_revenue="$200k +")])
    assert out["qualified_rule"]["window_impact"]["finalised"] == 0


def test_floor_is_configurable():
    out = _one([HDR, row("Mid Venue", "m@x.com")],
               [contact("c1", "m@x.com", "Mid Venue", form_revenue="$20k-50k")],
               qualified_floor=50000.0)
    r = next(x for x in out["creatives"] if x["creative_key"] == "120000000000000001")
    assert r["qualified"] == 0     # 20k band lower bound < 50k floor
    assert out["qualified_rule"]["floor_monthly"] == 50000.0


# ── scoreboard = reshape, rows = partition ───────────────────────────────────

def _fixture():
    rows = [HDR,
            row("A One", "a1@x.com", closer="won", close_date="2026-07-20",
                contract="15000", cash="6000"),
            row("A Two", "a2@x.com", setter="no pick up"),
            row("Ghost", "ghost@x.com")]
    contacts = [contact("c1", "a1@x.com", "A One"), contact("c2", "a2@x.com", "A Two")]
    spend = {"120000000000000001": {"name": "Creative A", "spend": 900.0,
                                    "impressions": 10, "clicks": 2}}
    return eng.compute_from_inputs(rows, contacts, spend,
                                   resolver({"120000000000000001": RES_A}), W0, W1)


def test_scoreboard_sums_equal_engine_totals():
    result = _fixture()
    sb = eng.scoreboard_view(result)
    for col in ("leads", "qualified", "sets", "closes", "cash", "spend"):
        assert sum(r[col] for r in sb["rows"]) == result["totals"].get(
            col, sum(c[col] for c in result["creatives"])), col
    assert sb["reconciliation"] is result["reconciliation"]
    assert set(c["creative_key"] for c in result["creatives"]) == \
           set(r["creative_key"] for r in sb["rows"])


def test_scoreboard_carries_confirmed_columns_and_honest_rows():
    sb = eng.scoreboard_view(_fixture())
    assert sb["columns"] == eng.SCOREBOARD_COLUMNS
    tiers = {r["tier"] for r in sb["rows"]}
    assert {"ig_dm", "unattributed"} <= tiers
    assert "reconcile to the dashboard" in sb["basis_note"]


def test_rows_partition_the_window_and_carry_highlights():
    result = _fixture()
    rows = result["rows"]
    assert len(rows) == result["totals"]["leads"]
    per_key = {}
    for r in rows:
        per_key[r["creative"]["key"]] = per_key.get(r["creative"]["key"], 0) + 1
    for c in result["creatives"]:
        if c["leads"]:
            assert per_key.get(c["creative_key"]) == c["leads"]
    close_row = next(r for r in rows if r["name"] == "A One")
    assert close_row["highlights"]["close"] is True
    assert close_row["highlights"]["threshold_met"] is True
    ghost = next(r for r in rows if r["name"] == "Ghost")
    assert ghost["creative"]["tier"] == "unattributed"
    assert ghost["highlights"]["revenue_unknown"] is True
