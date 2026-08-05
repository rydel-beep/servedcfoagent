"""
Close-count integrity + the insufficient-data fix (CLOSE_INTEGRITY_AND_SIGNAL_REPORT).

Rails: won rows without an Input Date COUNT as closes (the parser gap, fixed); min-n
thresholds UNCHANGED; provisional is signal, never a decision (a 2-lead creative can
never render DOUBLE DOWN); ladder roll-up sums == component sums and aggregate levels
earn REAL verdicts with the SAME thresholds; the integrity matrix classifies
disagreements deterministically and NEW ones queue for salience once; the board payload
carries hygiene + ladder.
"""
from __future__ import annotations

import datetime as dt

import attribution_engine as eng
import attribution_verdicts as AV
import close_integrity as CI
from tests.test_attribution import HDR, row, contact, resolver, RES_A

W0, W1 = dt.date(2026, 7, 1), dt.date(2026, 7, 31)


# ── Phase 1: the counting fix ────────────────────────────────────────────────

def test_won_row_without_input_date_still_counts_as_close():
    r_ = row("John Tamayo", "jt@x.com", input_date="", closer="won",
             close_date="2026-07-20", contract="24000", cash="4000")
    out = eng.compute_from_inputs([HDR, r_], [contact("c1", "jt@x.com", "John Tamayo")],
                                  {}, resolver({"120000000000000001": RES_A}), W0, W1,
                                  canonical={"closes": 1, "cash": 4000.0})
    assert out["totals"]["closes"] == 1                      # was parser-invisible before
    assert out["reconciliation"]["checks"]["closes"]["ok"]
    assert out["totals"]["leads"] == 0                        # no input date → not a cohort lead


def test_non_won_row_without_input_date_still_dropped():
    r_ = row("Ghost", "g@x.com", input_date="", setter="dq")
    out = eng.compute_from_inputs([HDR, r_], [], {}, resolver({}), W0, W1)
    assert out["totals"]["leads"] == 0 and out["totals"]["closes"] == 0


# ── gate integrity: thresholds untouched; provisional ≠ verdict ──────────────

def test_min_n_constants_unchanged():
    assert eng.MIN_N_LEADS_KILL == 30 and eng.MIN_N_CLOSES_SCALE == 3
    assert AV.MIN_N_LEADS_KILL == 30 and AV.MIN_N_CLOSES_SCALE == 3


def _v_row(**kw):
    base = {"creative_key": "x", "label": "X", "tier": "ad", "leads": 0, "qualified": 0,
            "sets": 0, "shows": 0, "closes_cohort": 0, "closes": 0, "cash": 0.0,
            "contract": 0.0, "spend": 0.0, "revenue_unknown": 0, "impressions": 0,
            "clicks": 0, "campaigns": [], "cost_per_lead": None, "ltgp_cac": None}
    base.update(kw)
    base["gates"] = {"n_leads": base["leads"], "n_closes": base["closes"],
                     "sufficient_for_scale": base["closes"] >= 3,
                     "sufficient_for_kill": base["leads"] >= 30}
    return base


def test_two_lead_creative_can_never_render_double_down():
    r = _v_row(leads=2, qualified=2, sets=1, spend=100.0, ltgp_cac=9.9, ltgp=9900.0)
    res = {"creatives": [r]}
    AV.apply(res, 3.0)
    assert r["verdict"] == "WATCH"                       # never DOUBLE DOWN below n
    assert r["provisional"]["trend"] == "strong"          # signal, clearly labelled
    assert "provisional" in r["provisional"]["label"].lower() or \
           "TRENDING" in r["provisional"]["label"]
    assert "DOUBLE" not in r["provisional"]["label"]      # a label is not a decision


def test_provisional_progress_states_what_is_missing():
    r = _v_row(leads=17, closes=1, qualified=10, sets=6, spend=1700.0)
    p = AV.provisional_for_row(r, 3.0, AV.baselines([r]))
    assert "13 more lead" in p["progress"] and "2 more close" in p["progress"]


def test_confirmed_verdict_has_no_provisional():
    r = _v_row(leads=40, closes=4, qualified=30, sets=12, shows=8, spend=1000.0,
               ltgp_cac=5.0, ltgp=40000.0, cost_per_close_loaded=2000.0)
    res = {"creatives": [r]}
    AV.apply(res, 3.0)
    assert r["verdict"] == "DOUBLE DOWN" and "provisional" not in r


# ── the ladder ───────────────────────────────────────────────────────────────

def _ladder_fixture():
    rows = [
        _v_row(creative_key="b008 a", label="B008_A04_Brash", leads=17, qualified=10,
               sets=6, shows=5, closes=1, cash=5170.0, contract=14500.0, spend=1739.0,
               ltgp=11600.0, cost_per_close_loaded=3841.0),
        _v_row(creative_key="b008 b", label="B008_A03_Proof", leads=1, qualified=1,
               sets=1, shows=1, closes=1, cash=8305.0, contract=15100.0, spend=62.0,
               ltgp=12080.0, cost_per_close_loaded=2180.0),
        _v_row(creative_key="b008 c", label="B008_A07_Pain", leads=14, qualified=8,
               sets=3, shows=2, closes=1, cash=6000.0, contract=15000.0, spend=500.0,
               ltgp=12000.0, cost_per_close_loaded=2618.0),
        _v_row(creative_key="g x", label="G3 Served Graphic News", leads=3, spend=231.0),
    ]
    return {"creatives": rows, "window": {"days": 30}}


def test_ladder_rollup_sums_equal_component_sums():
    res = _ladder_fixture()
    lad = AV.ladder(res, 3.0)
    b008 = next(a for a in lad["batch"] if a["creative_key"] == "B008")
    members = [r for r in res["creatives"] if r["label"].startswith("B008")]
    for k in ("leads", "qualified", "sets", "shows", "closes", "cash", "spend"):
        assert b008[k] == round(sum(m[k] for m in members), 2), k
    acct = lad["account"]
    for k in ("leads", "closes", "cash", "spend"):
        assert acct[k] == round(sum(r[k] for r in res["creatives"]), 2), k


def test_ladder_level_earns_real_verdict_at_same_thresholds():
    res = _ladder_fixture()
    lad = AV.ladder(res, 3.0)
    b008 = next(a for a in lad["batch"] if a["creative_key"] == "B008")
    # 3 closes across the batch → the SCALE bar clears at batch level
    assert b008["gates"]["sufficient_for_scale"] is True
    assert b008["verdict"] in ("DOUBLE DOWN", "WATCH", "KILL")
    assert b008["verdict"] == "DOUBLE DOWN"       # aggregate LTGP:CAC ≈ 35.7k/9.14k ≥ 3.3
    unb = next(a for a in lad["batch"] if a["creative_key"] == "UNBATCHED")
    assert unb["gates"]["gate"].startswith("watch")
    assert lad["default_level"] == "batch"        # no confirmed creative verdicts → batch


# ── the integrity matrix ─────────────────────────────────────────────────────

def _mx(monkeypatch, won_rows, ghl=(0, 20), stripe_missing=0, stripe_review=0):
    monkeypatch.setattr(CI, "_tracker_won_rows", lambda: won_rows)
    monkeypatch.setattr(CI, "_ghl_won_in_window", lambda a, b: ghl)
    monkeypatch.setattr("stripe_reconcile.reconcile_stripe_tracker", lambda: {
        "stripe_reconciliation": {
            "checked_charges": 10,
            "paid_missing_from_tracker": [{"customer": f"M{i}", "amount": 100}
                                          for i in range(stripe_missing)],
            "needs_review": [{"customer": f"R{i}", "amount": 50}
                             for i in range(stripe_review)]}}, raising=True)
    return CI.run_matrix(30)


def _won(name, close, inp="2026-07-01", contract=1000.0):
    import attribution_engine as AE
    return {"name": name, "email": "", "close_date": AE._date(close) if close else None,
            "close_raw": close or "", "input_date": AE._date(inp) if inp else None,
            "contract": contract, "cash": None}


def test_matrix_classifies_all_disagreement_kinds(monkeypatch):
    from helpers import today_sydney
    today = str(today_sydney())
    won = [_won("Fresh Close", today), _won("Blank Date", None),
           _won("No Input", today, inp=None)]
    m = _mx(monkeypatch, won, ghl=(0, 20), stripe_missing=1, stripe_review=1)
    kinds = {d["kind"] for d in m["disagreements"]}
    assert {"ghl_stage_lag", "tracker_blank_close_date", "tracker_blank_input_date",
            "stripe_paid_missing_from_tracker", "stripe_payer_unplaced"} <= kinds
    assert m["tracker_closes"] == 2 and m["agreement"]["tracker_vs_ghl"] is False
    assert m["agreement"]["tracker_vs_stripe_cash"] is False


def test_matrix_clean_state_agrees(monkeypatch):
    from helpers import today_sydney
    today = str(today_sydney())
    m = _mx(monkeypatch, [_won("Only Close", today)], ghl=(1, 20))
    assert m["agreement"]["tracker_vs_ghl"] is True
    assert m["agreement"]["tracker_vs_stripe_cash"] is True
    assert m["disagreements"] == []


def test_new_disagreement_queues_for_salience_once(monkeypatch):
    store = {}
    import kv_store
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.update({k: v}))
    from helpers import today_sydney
    won = [_won("Blank Date", None)]
    monkeypatch.setattr(CI, "_tracker_won_rows", lambda: won)
    monkeypatch.setattr(CI, "_ghl_won_in_window", lambda a, b: (0, 0))
    monkeypatch.setattr("stripe_reconcile.reconcile_stripe_tracker",
                        lambda: {"stripe_reconciliation": {}}, raising=True)
    CI.refresh(30)
    n1 = len(store.get("integrity:pending"))
    CI.refresh(30)
    assert len(store.get("integrity:pending")) == n1      # same id never re-queued


def test_edith_integrity_answer(monkeypatch):
    from helpers import today_sydney
    today = str(today_sydney())
    monkeypatch.setattr(CI, "latest", lambda: None)
    monkeypatch.setattr(CI, "refresh", lambda days=30: _mx(
        monkeypatch, [_won("Tesla Zhong", today)], ghl=(0, 20)))
    msg, handled = CI.handle_integrity_command("do the systems agree on closes?")
    assert handled and "Tesla Zhong" in msg and "authority" in msg
    assert "lags" in msg or "flagged" in msg


def test_mixed_groups_never_carry_a_verdict():
    # the category error caught live: a grab-bag of unrelated creatives with 30+ mixed
    # leads must not be killed (or scaled) as one unit — coverage, not an angle
    rows = [_v_row(creative_key=f"g{i}", label=f"G{i} Graphic", leads=11, qualified=2,
                   sets=0, spend=200.0) for i in range(3)]
    lad = AV.ladder({"creatives": rows, "window": {"days": 30}}, 3.0)
    unb = next(a for a in lad["batch"] if a["creative_key"] == "UNBATCHED")
    assert unb["leads"] == 33 and unb["verdict"] is None
    assert "mixed group" in unb["verdict_driver"]


def test_ladder_account_row_is_labelled_attributed_only():
    lad = AV.ladder(_ladder_fixture(), 3.0)
    assert "Attributed ads" in lad["account"]["label"]
    assert "WHOLE account" in lad["account"]["note"]
