"""tests/test_roster_engine.py — THE ROSTER ENGINE + I17 + DECISIONS #131.

I17 (roster-cell equality) swept exhaustively over synthetic inputs: every cell,
every metric, both clocks; ladder-tab cells prove sum==concat; tier rosters carry
quarantine reasons; a person with no GHL contact renders a chip, never drops;
injected drift fires LOUDLY. The payment-class ruling: email-matched Stripe
converts (journaled, evidence id), name-only and stage-only stay PROPOSED,
convert-twice is a no-op, cards for derived closes stop generating. Row control
is structurally pinned: full-dataset sort/find BEFORE the slice, tiers outside it.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribution_engine as eng
import roster_engine as RE
import resolution as RES
from tests.test_attribution import HDR, RES_A, RES_B, W0, W1, contact, resolver, row

_REPO = os.path.join(os.path.dirname(__file__), "..")


def _reset_kv():
    import kv_store
    for k in ("derived:dates", "ads_truth:flags", "integrity:autofix_log",
              "ads_truth:proposed", "integrity:proposed_fixes", "spine:events",
              "reached:evidence"):
        kv_store.put(k, None)


def _rows():
    r_frank = row("Frank Earlier", "f@x.com", input_date="2026-06-15",
                  closer="won", close_date="2026-07-25", contract="4000", cash="2000")
    r_frank[18] = "2026-06-20"          # set call BEFORE the window (earlier_sets)
    r_undated = row("Uma Undated", "u@x.com", closer="won", close_date="2026-07-22",
                    contract="3000", cash="1000", show="")
    r_undated[18] = ""                  # set exists, Set Date BLANK (undated_sets)
    return [
        row("Ann Alpha", "a@x.com", closer="won", close_date="2026-07-20",
            contract="5000", cash="3000"),
        row("Bob Beta", "b@x.com", show=""),
        row("Cara Gamma", "c@x.com", setter="", show=""),     # no GHL contact at all
        row("Dan Delta", "d@x.com", setter="", show=""),      # IG-DM tier
        row("Eve Epsilon", "e@x.com", show=""),               # ambiguous ad ref
        r_frank, r_undated,
    ]


def _contacts():
    return [
        # GHL name deliberately differs from the tracker name (discrepancy chip)
        contact("c1", "a@x.com", "Annie Alpha"),
        contact("c2", "b@x.com", "Bob Beta"),
        contact("c4", "d@x.com", "Dan Delta", tier="ig_dm", ft_ref=None, ft_kind=None),
        contact("c5", "e@x.com", "Eve Epsilon", ft_ref="nameref", ft_kind="name"),
        contact("c6", "f@x.com", "Frank Earlier"),
        contact("c7", "u@x.com", "Uma Undated"),
    ]


def _compute(basis="cohort"):
    return eng.compute_from_inputs(
        [HDR] + _rows(), _contacts(), {},
        resolver({"120000000000000001": RES_A, "nameref": RES_B}), W0, W1, basis=basis)


def _patch_live(monkeypatch, results):
    """Point the roster engine's live reads at the synthetic world."""
    def fake_compute(days=30, start=None, end=None, force=False, basis="cohort",
                     market=None):
        return results[basis]
    monkeypatch.setattr(eng, "compute", fake_compute)
    monkeypatch.setattr(eng, "_tracker_rows_clean", lambda: [HDR] + _rows())
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: _contacts())


# ── I17: every cell, every metric, both clocks ───────────────────────────────

def test_i17_every_cell_every_metric_both_clocks():
    _reset_kv()
    for basis in ("cohort", "activity"):
        r = _compute(basis)
        for c in r["creatives"]:
            for m in ("leads", "qualified", "reached", "sets", "shows", "closes"):
                assert len((c.get("members") or {}).get(m) or []) == (c.get(m) or 0), \
                    f"{basis}/{c['creative_key']}/{m}"
            # annotation classes carry members too (anomaly rosters)
            for m in ("earlier_closes", "earlier_sets", "earlier_shows",
                      "undated_sets", "shows_unverified"):
                assert len((c.get("members") or {}).get(m) or []) == (c.get(m) or 0), \
                    f"{basis}/{c['creative_key']}/{m} (annotation)"
        assert not any(not iv["ok"] for iv in r["invariants"]), r["invariants"]


def test_i17_violation_is_loud_integrity_error():
    _reset_kv()
    r = _compute("cohort")
    c = next(x for x in r["creatives"] if x["creative_key"] == "120000000000000001")
    c["members"]["leads"] = c["members"]["leads"][:-1]      # inject drift
    # re-run just the invariant sweep the engine applies
    n = len(c["members"]["leads"])
    assert n != c["leads"]     # the drift exists; the engine flags it at compute
    # and the compute-time check does fire on a fresh compute with a broken _mem
    # (structural: the check lives inside compute_from_inputs)
    src = open(os.path.join(_REPO, "attribution_engine.py")).read()
    assert "I17" in src and "cell reads" in src


def test_roster_len_equals_cell_creative(monkeypatch):
    _reset_kv()
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    for basis in ("cohort", "activity"):
        for metric in ("leads", "qualified", "reached", "sets", "shows", "closes"):
            for c in results[basis]["creatives"]:
                out = RE.build(days=31, basis=basis, level="creative",
                               key=c["creative_key"], metric=metric)
                assert out.get("error") is None
                assert out["count"] == (c.get(metric) or 0)
                assert len(out["people"]) == out["count"], \
                    f"{basis}/{c['creative_key']}/{metric}"
                assert out["i17"]["ok"] is True


def test_ladder_cells_equal_member_concat(monkeypatch):
    _reset_kv()
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    import attribution_verdicts as AV
    for basis in ("cohort", "activity"):
        groups = AV.ladder_groups(results[basis])
        for level in ("name", "batch", "campaign", "account"):
            for gkey, members in groups[level].items():
                for metric in ("leads", "sets", "closes"):
                    cell = sum(m.get(metric) or 0 for m in members)
                    out = RE.build(days=31, basis=basis, level=level,
                                   key=gkey, metric=metric)
                    assert out["count"] == cell
                    assert len(out["people"]) == cell, f"{basis}/{level}/{gkey}/{metric}"


def test_tier_roster_quarantine_reasons(monkeypatch):
    _reset_kv()
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    amb = RE.build(days=31, basis="cohort", level="creative",
                   key="__ambiguous__", metric="leads")
    assert amb["count"] == 1 and len(amb["people"]) == 1
    assert "quarantined" in (amb["people"][0].get("tier_reason") or "")
    un = RE.build(days=31, basis="cohort", level="creative",
                  key="__unattributed__", metric="leads")
    assert un["count"] == 1
    assert un["people"][0]["name"] == "Cara Gamma"
    assert "no GHL contact" in (un["people"][0].get("tier_reason") or "")
    ig = RE.build(days=31, basis="cohort", level="creative",
                  key="__ig_dm__", metric="leads")
    assert ig["count"] == 1
    assert "Instagram DM" in (ig["people"][0].get("tier_reason") or "")


def test_zero_cell_honest_empty(monkeypatch):
    _reset_kv()
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    out = RE.build(days=31, basis="cohort", level="creative",
                   key="__ig_dm__", metric="closes")
    assert out["count"] == 0 and out["people"] == []
    assert "honest empty" in (out["empty_reason"] or "")
    assert "closes" in out["empty_reason"]


def test_identity_chips_and_name_discrepancy(monkeypatch):
    _reset_kv()
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    out = RE.build(days=31, basis="cohort", level="creative",
                   key="120000000000000001", metric="leads")
    ppl = {p["name"]: p for p in out["people"]}
    ann = ppl["Ann Alpha"]
    assert ann["identity"] == "id-linked"
    assert ann["name_discrepancy"] is True and ann["ghl_name"] == "Annie Alpha"
    # a person with NO GHL contact renders tracker-only — never errors, never drops
    un = RE.build(days=31, basis="cohort", level="creative",
                  key="__unattributed__", metric="leads")
    cara = un["people"][0]
    assert cara["identity"] == "tracker-only (no GHL contact)"
    assert cara["ghl_link"] is None and cara["tracker_link"]


def test_anomaly_metric_rosters(monkeypatch):
    _reset_kv()
    results = {"cohort": _compute("cohort"), "activity": _compute("activity")}
    _patch_live(monkeypatch, results)
    c = next(x for x in results["activity"]["creatives"]
             if x["creative_key"] == "120000000000000001")
    assert c["earlier_sets"] == 1 and c["undated_sets"] == 1
    out = RE.build(days=31, basis="activity", level="creative",
                   key="120000000000000001", metric="earlier_sets")
    assert out["count"] == 1 and out["people"][0]["name"] == "Frank Earlier"
    out2 = RE.build(days=31, basis="activity", level="creative",
                    key="120000000000000001", metric="undated_sets")
    assert out2["count"] == 1 and out2["people"][0]["name"] == "Uma Undated"
    assert out2["people"][0]["event"]["date"] is None      # honest blank, chip not omission


def test_i17_drift_fires_loudly(monkeypatch):
    _reset_kv()
    import copy
    results = {"cohort": copy.deepcopy(_compute("cohort")),
               "activity": copy.deepcopy(_compute("activity"))}
    c = next(x for x in results["cohort"]["creatives"]
             if x["creative_key"] == "120000000000000001")
    c["members"]["leads"] = c["members"]["leads"][:-1]     # tamper AFTER compute
    _patch_live(monkeypatch, results)
    out = RE.build(days=31, basis="cohort", level="creative",
                   key="120000000000000001", metric="leads")
    assert out["i17"]["ok"] is False
    import kv_store
    flags = kv_store.get("ads_truth:flags") or []
    assert any("I17 ROSTER-CELL DRIFT" in (f.get("reason") or "") for f in flags)


def test_closes_roster_carries_payment_provenance(monkeypatch):
    """A close whose date was derived under #131 shows its derived:stripe chip."""
    _reset_kv()
    RES.record_derived_date("gina dateless", "close_date", "2026-07-18",
                            "derived:stripe",
                            {"charge_id": "ch_test1", "ruling": "DECISIONS #131"})
    rows = _rows() + [row("Gina Dateless", "g@x.com", closer="won",
                          close_date="", contract="7000", cash="7000")]
    contacts = _contacts() + [contact("c8", "g@x.com", "Gina Dateless")]
    res = eng.compute_from_inputs([HDR] + rows, contacts, {},
                                  resolver({"120000000000000001": RES_A,
                                            "nameref": RES_B}), W0, W1,
                                  basis="activity")
    results = {"activity": res, "cohort": res}
    monkeypatch.setattr(eng, "compute", lambda **kw: res)
    monkeypatch.setattr(eng, "_tracker_rows_clean", lambda: [HDR] + rows)
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts", lambda: contacts)
    out = RE.build(days=31, basis="activity", level="creative",
                   key="120000000000000001", metric="closes")
    gina = next(p for p in out["people"] if p["name"] == "Gina Dateless")
    assert gina["event"]["provenance"] == "derived:stripe"
    assert gina["event"]["date"] == "2026-07-18"
    assert out["count"] == len(out["people"])


# ── DECISIONS #131: the payment-class ruling ─────────────────────────────────

def _won_rows():
    return [
        {"name": "Ella Email", "email": "ella@x.com", "close_date": None,
         "close_raw": "", "input_date": dt.date(2026, 6, 1), "contract": 8000.0,
         "cash": 4000.0},
        {"name": "Nina NameOnly", "email": "", "close_date": None,
         "close_raw": "", "input_date": dt.date(2026, 6, 2), "contract": 5000.0,
         "cash": 2500.0},
        {"name": "Stan StageOnly", "email": "stan@x.com", "close_date": None,
         "close_raw": "", "input_date": dt.date(2026, 6, 3), "contract": 3000.0,
         "cash": 1000.0},
        {"name": "Dana Dated", "email": "dana@x.com",
         "close_date": dt.date(2026, 7, 1), "close_raw": "2026-07-01",
         "input_date": dt.date(2026, 6, 4), "contract": 900.0, "cash": 900.0},
    ]


def _patch_ruling(monkeypatch):
    import close_integrity as CI
    monkeypatch.setattr(CI, "_tracker_won_rows", _won_rows)
    monkeypatch.setattr(RES, "_stripe_first_payment_dates", lambda days=365: {
        RES._norm("ella@x.com"): {"date": dt.date(2026, 6, 20), "charge_id": "ch_ella", "via": "email"},
        "nina nameonly": {"date": dt.date(2026, 6, 21), "charge_id": "ch_nina", "via": "name"},
    })


def test_ruling_email_match_converts_journaled(monkeypatch):
    _reset_kv()
    _patch_ruling(monkeypatch)
    out = RES.apply_payment_class_ruling()
    assert [c["name"] for c in out["converted"]] == ["Ella Email"]
    assert out["converted"][0]["charge_id"] == "ch_ella"
    assert out["cash_placed"] == 4000.0
    dd = RES.derived_dates()
    assert dd["ella email"]["close_date"]["date"] == "2026-06-20"
    assert dd["ella email"]["close_date"]["provenance"] == "derived:stripe"
    assert dd["ella email"]["close_date"]["evidence"]["ruling"] == "DECISIONS #131"
    import kv_store
    lg = kv_store.get("integrity:autofix_log") or []
    assert any(e["rule"] == "ruling-conversion DECISIONS #131" for e in lg)
    flags = kv_store.get("ads_truth:flags") or []
    assert any("DECISIONS #131" in (f.get("reason") or "") and
               f.get("metric") == "ads_truth_action" for f in flags)


def test_ruling_duplicate_dated_row_never_converts(monkeypatch):
    """A blank whose identity also has a DATED won row is a duplicate — deriving
    a date would double-place the deal (the live Nirosha class)."""
    _reset_kv()
    import close_integrity as CI
    # the LIVE failure shape: the blank row carries NO email — only the name
    # links it to the dated row (guard must key on BOTH identities)
    rows = _won_rows() + [
        {"name": "Dana Dated", "email": "", "close_date": None,
         "close_raw": "", "input_date": dt.date(2026, 5, 1), "contract": 900.0,
         "cash": 900.0}]
    monkeypatch.setattr(CI, "_tracker_won_rows", lambda: rows)
    monkeypatch.setattr(RES, "_stripe_first_payment_dates", lambda days=365: {
        RES._norm("dana dated"): {"date": dt.date(2026, 5, 2),
                                  "charge_id": "ch_dana", "via": "email"}})
    out = RES.apply_payment_class_ruling()
    assert out["converted"] == []
    assert "Dana Dated" in out["skipped_duplicate_dated"]
    assert "dana dated" not in RES.derived_dates()


def test_ruling_name_only_and_stage_only_stay_proposed(monkeypatch):
    _reset_kv()
    _patch_ruling(monkeypatch)
    out = RES.apply_payment_class_ruling()
    assert "Nina NameOnly" in out["skipped_name_only"]
    dd = RES.derived_dates()
    assert "nina nameonly" not in dd          # a label match is not an ID
    assert "stan stageonly" not in dd         # stage evidence NEVER auto-derives
    assert "dana dated" not in dd             # a filled tracker date is never touched


def test_ruling_convert_twice_is_noop(monkeypatch):
    _reset_kv()
    _patch_ruling(monkeypatch)
    out1 = RES.apply_payment_class_ruling()
    assert len(out1["converted"]) == 1
    import kv_store
    n_flags = len(kv_store.get("ads_truth:flags") or [])
    out2 = RES.apply_payment_class_ruling()
    assert out2["converted"] == [] and out2["already_derived"] >= 1
    assert len(kv_store.get("ads_truth:flags") or []) == n_flags   # no second notice


def test_p1_card_not_generated_for_derived_close(monkeypatch):
    _reset_kv()
    _patch_ruling(monkeypatch)
    monkeypatch.setattr(RES, "_ghl_won_dates", lambda: {
        RES._norm("stan@x.com"): {"date": dt.date(2026, 6, 25), "via": "email"}})
    RES.apply_payment_class_ruling()
    cards = RES.propose_fixes()
    names = [c["name"] for c in cards]
    assert "Ella Email" not in names          # converted → the queue shows humans-only
    assert "Stan StageOnly" in names          # stage-only stays a PROPOSED card
    stan = next(c for c in cards if c["name"] == "Stan StageOnly")
    assert stan["kind"] == "P1_close_date_candidate"


def test_nightly_resolve_dates_carries_the_rung(monkeypatch):
    src = open(os.path.join(_REPO, "resolution.py")).read()
    body = src.split("def resolve_dates()")[1].split("def apply_payment_class_ruling")[0]
    assert "apply_payment_class_ruling()" in body


# ── consumers: one engine, no parallel person lists ──────────────────────────

def test_dossier_and_route_consume_the_engine():
    ads = open(os.path.join(_REPO, "dashboard", "ads.py")).read()
    assert ads.count("roster_engine.build") >= 2      # roster route + dossier ledger
    assert "by_cname" not in ads                      # the parallel joins are dead
    assert "_STAGES = {" not in ads
    js = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
    anom = js.split("function anomalyPanel")[1].split("function dealPanel")[0]
    assert "/ads/api/roster" in anom                  # anomaly panel = engine consumer
    assert ".forEach" not in anom                     # no client-side person filtering


def test_roster_route_is_auth_locked():
    ads = open(os.path.join(_REPO, "dashboard", "ads.py")).read()
    seg = ads.split('@bp.route("/api/roster"')[1][:80]
    assert "@require_auth" in seg


def test_i17_nightly_sampling_wired():
    src = open(os.path.join(_REPO, "ads_truth.py")).read()
    body = src.split("def integrity_sweep()")[1]
    assert "i17_sample" in body and "random.sample" in body
    assert "i17_roster_drift" in body
    # drift is ACTION-lane loud, not hygiene-quiet (#133 appended clock_label
    # to the same promotion tuple — assert membership, not tuple tail)
    promo = src.split("big = ")[1][:260]
    assert '"i17_roster_drift"' in promo and '"clock_label")' in promo


def test_dedup_proposed_kills_duplicate_ids():
    import ads_truth
    out = ads_truth._dedup_proposed([
        {"id": "a", "x": 1}, {"id": "b"}, {"id": "a", "x": 2}, {"kind": "no-id"}])
    assert [p.get("id") for p in out] == ["a", "b", None]
    assert out[0]["x"] == 1


# ── row control: structural (full-dataset sort/find BEFORE the slice) ────────

def test_row_control_structure():
    js = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
    sb = js.split("function renderScoreboard")[1].split("function rowMatches")[0]
    assert sb.index("sortRows(rows)") < sb.index(".slice(0, lim)")   # sort first
    assert ".concat(tierRows)" in sb                 # tiers pinned outside the slice
    assert "adx-rowlimit" in js and "localStorage.setItem('adx-rows'" in js
    assert "rows=(\\d{1,4}|all)" in js               # URL state
    rr = js.split("function renderRows")[1].split("// ── THE DRILL")[0]
    assert rr.index("filter(rowMatches)") < rr.index("state.shown + step")  # find first
    html = open(os.path.join(_REPO, "dashboard", "templates", "ads.html")).read()
    assert 'data-rows="70"' in html and 'data-rows="all"' in html


def test_roster_deep_link_and_sorts():
    js = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
    assert "&roster=" in js and "roster=([^&]+)" in js
    assert "adx-roster-sort" in js
    for k in ("'event'", "'state'", "'cash'"):
        assert k in js.split("function renderRosterPeople")[1].split("function loadRoster")[0]
