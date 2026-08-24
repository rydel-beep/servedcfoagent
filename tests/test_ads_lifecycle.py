"""
tests/test_ads_lifecycle.py — the lifecycle engine under R-A2 (strategy
migration): review cycles, peer-relative pull candidates, set grouping —
plus every carried-over doctrine (status triad, decisions/convergence/aging,
stances-never-move-cards, labels).

GHOST GREP lives here too: zero live references to the retired 4-day/$200
rotation in code or rendered copy (historical journals exempt).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import ads_lifecycle as L
import ads_discussion as D


def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


TODAY = dt.date(2026, 8, 24)


def mk_row(key="120000000000000001", leads=0, spend=0.0, closes=0, verdict=None,
           n_leads=None, n_closes=None, launch="2026-08-16", active_days=None,
           never=False, ad_ids=None, label="Creative A"):
    n_leads = leads if n_leads is None else n_leads
    n_closes = closes if n_closes is None else n_closes
    gates = {"n_leads": n_leads, "n_closes": n_closes,
             "sufficient_for_kill": n_leads >= 30,
             "sufficient_for_scale": n_closes >= 3}
    lineage = None if launch is None else {
        "launch": launch, "active_days": active_days, "never_delivered": never}
    return {"tier": "ad", "creative_key": key, "label": label, "leads": leads,
            "closes": closes, "spend": spend, "verdict": verdict, "gates": gates,
            "lineage": lineage, "ad_ids": ad_ids or [key]}


ST_LIVE = {"status": "delivering", "label": "LIVE", "rank": 3,
           "reason": "impressions", "layer": None, "as_of": "x",
           "degraded": None, "blocked_by_parent": False}
ST_PAUSED = {"status": "paused", "label": "PAUSED", "rank": 1,
             "reason": "paused at the ad layer (deliberate park)",
             "layer": "ad", "as_of": "x", "degraded": None,
             "blocked_by_parent": False}


def _fix_today(monkeypatch):
    import helpers
    monkeypatch.setattr(helpers, "today_sydney", lambda: TODAY)


def _row_sufficient(**kw):
    kw.setdefault("leads", 35)
    kw.setdefault("closes", 3)
    kw.setdefault("spend", 900)
    return mk_row(**kw)


# ── THE GHOST GREP: nothing of the retired rotation survives live ────────────

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_ghost_grep_no_live_rotation_references():
    """Zero live references to the $200 threshold, the 4-day boundary, the
    'rotation' vocabulary, or the old spend bands — in live code paths and
    rendered copy. Historical docs/journals are exempt (labelled)."""
    live_files = ["ads_lifecycle.py", "attribution_flags.py",
                  "dashboard/ads.py", "dashboard/templates/ads.html",
                  "dashboard/static/js/adsapp.js"]
    for f in live_files:
        src = open(os.path.join(_ROOT, f), encoding="utf-8").read()
        low = src.lower()
        assert "test_spend" not in low, f
        assert "test_days" not in low, f
        assert "$200" not in src, f
        assert "spend_band" not in low and "adx-sband" not in low, f
        # 'rotation' survives ONLY in supersession notes (R-A history), never
        # as live vocabulary: no rotation clock/lane/rule/panel remains
        for ghost in ("rotation clock", "rotation rules", "rotation lane",
                      "rotation call", "rotation window", "rotation boundary",
                      "rotation_kill"):
            assert ghost not in low, (f, ghost)
    # the old kv config keys are never READ in live code
    src = open(os.path.join(_ROOT, "ads_lifecycle.py")).read()
    assert 'kv_store.get("ads:rotation_rules")' not in src
    assert "kill_candidate_flags" not in src        # replaced by review_flags


# ── R-A2 config + set mapping ────────────────────────────────────────────────

def test_strategy_defaults_and_journal(monkeypatch):
    _kv_reset(monkeypatch)
    st = L.strategy()
    assert st["review_cycle_days"] == 7 and st["review_due_through"] == 8
    assert st["pull_cpl_mult"] == 1.5 and st["starved_share_pct"] == 5
    assert st["budgets"]["graphics"] == [60, 70]
    assert st["budgets"]["retargeting"] == [40, 40]
    assert st["budgets"]["broad_video"] is None      # unset until Rydel enters it
    out, err = L.set_strategy({"user": "rydel"}, {"review_cycle_days": 8,
                                                  "budgets": {"broad_video": [80, 100]}})
    assert err is None and out["review_cycle_days"] == 8
    j = L.strategy_journal()
    assert any(e["key"] == "review_cycle_days" and e["new"] == 8 for e in j)
    assert any(e["key"] == "budget:broad_video" for e in j)
    assert L.set_strategy({"user": "rydel"}, {"nonsense": 1})[1]
    assert L.set_strategy({"user": "rydel"}, {"review_cycle_days": 99})[1]


def test_set_mapping_ids_are_truth(monkeypatch):
    _kv_reset(monkeypatch)
    out, err = L.map_adset({"user": "rydel"}, "230000000000000001", "graphics")
    assert err is None
    assert L.set_roles_map() == {"230000000000000001": "graphics"}
    assert any(e["key"] == "adset:230000000000000001"
               for e in L.strategy_journal())
    # reversible
    L.map_adset({"user": "rydel"}, "230000000000000001", "unmapped")
    assert L.set_roles_map() == {}
    # a NAME is refused — ids only
    assert L.map_adset({"user": "rydel"}, "Graphics Set Q3", "graphics")[1]
    assert L.map_adset({"user": "rydel"}, "230000000000000001", "cold")[1]


def test_roles_for_ads_via_entity_map(monkeypatch):
    _kv_reset(monkeypatch)
    L.map_adset({"user": "rydel"}, "230000000000000001", "broad_video")
    es = {"ads": {"120000000000000001": {"adset_id": "230000000000000001"},
                  "120000000000000002": {"adset_id": "230000000000000009"}}}
    roles, sids = L.roles_for_ads(["120000000000000001", "120000000000000002"], es)
    assert roles == ["broad_video"]
    assert set(sids) == {"230000000000000001", "230000000000000009"}


# ── the review clock ─────────────────────────────────────────────────────────

def test_review_clock_starts_at_first_delivery_and_due_boundary(monkeypatch):
    _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    # launched 6 days ago → in cycle, not due
    rv = L.review_clock("120000000000000001", str(TODAY - dt.timedelta(days=6)), TODAY)
    assert rv["cycle_day"] == 6 and rv["due"] is False
    assert rv["anchored_on"] == "first delivery"
    # day 7 → due; day 8 → still due (the due-window)
    assert L.review_clock("k", str(TODAY - dt.timedelta(days=7)), TODAY)["due"] is True
    assert L.review_clock("k", str(TODAY - dt.timedelta(days=8)), TODAY)["due"] is True
    assert L.review_clock("k", None, TODAY) is None      # no launch → honest None


def test_review_clock_resets_on_keep(monkeypatch):
    store = _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    key = "120000000000000001"
    launch = str(TODAY - dt.timedelta(days=9))
    assert L.review_clock(key, launch, TODAY)["due"] is True
    ok, err = L.keep_running({"user": "romano"}, key, "still ramping")
    assert ok and err is None
    rv = L.review_clock(key, launch, TODAY)
    assert rv["cycle_day"] == 0 and rv["due"] is False
    assert rv["anchored_on"] == "last review"
    # journaled + in the dated session record
    assert store["ads:lifecycle:journal"][-1]["action"] == "review_keep"
    sess = store["ads:review_sessions"][str(TODAY)]
    assert sess["kept"][0]["creative"] == key and "romano" in sess["reviewers"]


# ── peer-relative pull candidates (the three signals, each labelled) ─────────

def _spend_env(monkeypatch, cur_days, prev_days=None):
    """Seed the archive + entity map: 3 creatives in one mapped set."""
    _fix_today(monkeypatch)
    es = {"ads": {f"12000000000000000{i}": {"adset_id": "230000000000000001"}
                  for i in (1, 2, 3)}}
    days = {}
    for offset, per_ad in (cur_days or {}).items():
        d = str(TODAY - dt.timedelta(days=offset))
        days[d] = {aid: {"spend": sp, "impressions": 10}
                   for aid, sp in per_ad.items()}
    for offset, per_ad in (prev_days or {}).items():
        d = str(TODAY - dt.timedelta(days=offset))
        days[d] = {aid: {"spend": sp, "impressions": 10}
                   for aid, sp in per_ad.items()}
    monkeypatch.setattr(L, "_entity_store", lambda: es)
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": days})
    return es


def test_pull_zero_leads_with_share_fires_alone(monkeypatch):
    _kv_reset(monkeypatch)
    es = _spend_env(monkeypatch, {1: {"120000000000000001": 100.0,
                                      "120000000000000002": 100.0,
                                      "120000000000000003": 100.0}})
    L.map_adset({"user": "rydel"}, "230000000000000001", "graphics")
    rows = [mk_row(key="120000000000000001", leads=0, label="Zero"),
            mk_row(key="120000000000000002", leads=8, label="Fine"),
            mk_row(key="120000000000000003", leads=6, label="Also fine")]
    pc = L.pull_candidates(rows, es)
    f = pc["flags"]["120000000000000001"]
    assert [s["signal"] for s in f["signals"]] == ["zero_leads_with_share"]
    assert "spending its share, producing nothing" in f["signals"][0]["detail"]
    assert "120000000000000002" not in pc["flags"]


def test_pull_relative_cpl_with_min_evidence_guard(monkeypatch):
    _kv_reset(monkeypatch)
    es = _spend_env(monkeypatch, {1: {"120000000000000001": 300.0,
                                      "120000000000000002": 100.0,
                                      "120000000000000003": 100.0}})
    L.map_adset({"user": "rydel"}, "230000000000000001", "targeted_video")
    # expensive at n=5 vs peers at n=10 → relative_cpl fires
    rows = [mk_row(key="120000000000000001", leads=5, label="Expensive"),
            mk_row(key="120000000000000002", leads=10, label="Cheap"),
            mk_row(key="120000000000000003", leads=10, label="Cheap 2")]
    pc = L.pull_candidates(rows, es)
    sigs = [s["signal"] for s in pc["flags"]["120000000000000001"]["signals"]]
    assert sigs == ["relative_cpl"]
    assert "expensive vs its peers" in pc["flags"]["120000000000000001"]["signals"][0]["detail"]
    # THE GUARD: the same shape at n=1 (a fluke) never flags on CPL
    rows_fluke = [mk_row(key="120000000000000001", leads=1, label="Fluke"),
                  mk_row(key="120000000000000002", leads=10),
                  mk_row(key="120000000000000003", leads=10)]
    pc2 = L.pull_candidates(rows_fluke, es)
    sigs2 = [s["signal"] for s in (pc2["flags"].get("120000000000000001")
                                   or {}).get("signals") or []]
    assert "relative_cpl" not in sigs2


def test_pull_starved_two_cycles_is_its_own_label(monkeypatch):
    _kv_reset(monkeypatch)
    # 2% share this cycle AND last cycle → starved (allocation ≠ expense)
    es = _spend_env(monkeypatch,
                    cur_days={1: {"120000000000000001": 2.0,
                                  "120000000000000002": 49.0,
                                  "120000000000000003": 49.0}},
                    prev_days={8: {"120000000000000001": 2.0,
                                   "120000000000000002": 49.0,
                                   "120000000000000003": 49.0}})
    L.map_adset({"user": "rydel"}, "230000000000000001", "broad_video")
    rows = [mk_row(key="120000000000000001", leads=2, label="Starved"),
            mk_row(key="120000000000000002", leads=5),
            mk_row(key="120000000000000003", leads=5)]
    pc = L.pull_candidates(rows, es)
    sigs = [s["signal"] for s in pc["flags"]["120000000000000001"]["signals"]]
    assert "starved" in sigs
    detail = next(s["detail"] for s in pc["flags"]["120000000000000001"]["signals"]
                  if s["signal"] == "starved")
    assert "allocation problem" in detail and "not an expense problem" in detail


def test_retargeting_never_ranks_against_cold_peers(monkeypatch):
    """Set-scoping is structural: a retargeting creative competes only inside
    Set 4 — a terrible retarget CPL vs great cold CPLs never flags."""
    _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    es = {"ads": {"120000000000000001": {"adset_id": "230000000000000004"},
                  "120000000000000002": {"adset_id": "230000000000000001"},
                  "120000000000000003": {"adset_id": "230000000000000001"}}}
    days = {str(TODAY - dt.timedelta(days=1)): {
        "120000000000000001": {"spend": 300.0, "impressions": 10},
        "120000000000000002": {"spend": 100.0, "impressions": 10},
        "120000000000000003": {"spend": 100.0, "impressions": 10}}}
    monkeypatch.setattr(L, "_entity_store", lambda: es)
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": days})
    L.map_adset({"user": "rydel"}, "230000000000000004", "retargeting")
    L.map_adset({"user": "rydel"}, "230000000000000001", "broad_video")
    rows = [mk_row(key="120000000000000001", leads=3, label="Retarget"),  # $100 CPL
            mk_row(key="120000000000000002", leads=20, label="Cold A"),   # $5 CPL
            mk_row(key="120000000000000003", leads=20, label="Cold B")]
    pc = L.pull_candidates(rows, es)
    # the retarget creative is ALONE in its set (no peers) → never flagged;
    # and no flag anywhere references a cross-set comparison
    assert "120000000000000001" not in pc["flags"]
    assert "peer-relative within each mapped ad set only" in pc["note"]


def test_no_auto_pull_path_exists():
    """Attempted: no code path moves a card from a pull flag. The classifier
    only LABELS; a decision requires move() with an actor + reason."""
    import inspect
    src = inspect.getsource(L.pull_candidates) + inspect.getsource(L.classify_stage)
    for token in ("move(", "_put_decisions", "reset_review_clock"):
        assert token not in src
    assert "humans decide" in (inspect.getdoc(L.pull_candidates) or "")


# ── lanes (R-A2) ─────────────────────────────────────────────────────────────

def _st_cfg():
    return dict(L.STRATEGY_DEFAULTS, budgets={})


def test_lanes_running_due_and_verdict_paths(monkeypatch):
    _kv_reset(monkeypatch)
    cfg = _st_cfg()
    rv_in = {"due": False, "cycle_day": 3, "label": "cycle day 3 · review due day 7–8"}
    rv_due = {"due": True, "cycle_day": 7, "label": "cycle day 7 · review due day 7–8"}
    assert L.classify_stage(mk_row(leads=2), ST_LIVE, cfg, rv_in, None)["lane"] == "running"
    s = L.classify_stage(mk_row(leads=2), ST_LIVE, cfg, rv_due, None)
    assert s["lane"] == "due_for_review"
    # pull flags ride the why, labelled peer-relative + human-decides
    pf = {"signals": [{"signal": "relative_cpl", "detail": "x"}]}
    s2 = L.classify_stage(mk_row(leads=2), ST_LIVE, cfg, rv_due, pf)
    assert "PULL CANDIDATE" in s2["why"] and "human decides" in s2["why"]
    # verdict engine untouched: DOUBLE DOWN at min-n → scale_candidate even mid-cycle
    s3 = L.classify_stage(_row_sufficient(verdict="DOUBLE DOWN"), ST_LIVE, cfg,
                          rv_in, None)
    assert s3["lane"] == "scale_candidate"
    # a verdict KILL surfaces at review with the PILL as the statistical layer
    s4 = L.classify_stage(_row_sufficient(verdict="KILL"), ST_LIVE, cfg, rv_in, None)
    assert s4["lane"] == "due_for_review" and "pill is the statistical layer" in s4["why"]
    assert L.classify_stage(mk_row(), ST_PAUSED, cfg, rv_in, None)["lane"] == "archive"
    # a review judgment is never dressed as a verdict
    assert "verdict" not in L.classify_stage(mk_row(leads=2), ST_LIVE, cfg,
                                             rv_due, pf)["why"].split("PULL")[0].lower()


def test_below_min_n_never_scale_candidate(monkeypatch):
    _kv_reset(monkeypatch)
    cfg = _st_cfg()
    for leads in (0, 1, 5, 29):
        row = mk_row(leads=leads, spend=900)
        assert L.classify_stage(row, ST_LIVE, cfg, None, None)["lane"] != "scale_candidate"


# ── decisions: pull relabel + carried-over mechanics ─────────────────────────

def test_move_pull_and_legacy_kill_alias(monkeypatch):
    store = _kv_reset(monkeypatch)
    row = _row_sufficient()
    dec, err, _f = L.move({"user": "romano", "display": "Romano"},
                          row["creative_key"], "pull", "losing to its set peers",
                          row, "due_for_review")
    assert err is None and dec["state"] == "marked_to_pull"
    assert store["ads:lifecycle:journal"][-1]["to"] == "marked_to_pull"
    # legacy alias still lands as pull (API compat)
    L.reverse({"user": "rydel"}, row["creative_key"], "undo")
    dec2, err2, _ = L.move({"user": "romano"}, row["creative_key"], "kill", "r",
                           row, "due_for_review")
    assert err2 is None and dec2["state"] == "marked_to_pull"
    # blank reason still rejected (R-B carried)
    assert L.move({"user": "romano"}, row["creative_key"], "pull", "  ",
                  row, None)[1]


def test_pull_convergence_and_historical_kill_carryover(monkeypatch):
    store = _kv_reset(monkeypatch)
    row = _row_sufficient()

    def _block(rows, status):
        monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {}})
        monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
        monkeypatch.setattr(L, "status_for", lambda *a, **k: status)
        return L.build_block(rows, record_render=False)
    L.move({"user": "romano"}, row["creative_key"], "pull", "r", row, "due_for_review")
    b = _block([row], ST_PAUSED)                   # next sync: Meta paused
    card = b["cards"][row["creative_key"]]
    assert card["decision"]["executed"] is True
    assert card["archive_label"] == "pulled — verified in Meta"
    assert store["ads:lifecycle:journal"][-1]["to"] == "pulled (verified)"
    # a HISTORICAL marked_to_kill decision (pre-R-A2) renders in the pull lane
    # with the pre-R-A2 note — mechanics identical, history never erased
    store["ads:lifecycle:decisions"] = {row["creative_key"]: {
        "state": "marked_to_kill", "by": "romano", "by_display": "Romano",
        "at": "2026-08-12 10:00", "reason": "old-world kill", "executed": False,
        "label": row["label"], "ad_ids_at_move": row["ad_ids"]}}
    b2 = _block([row], ST_LIVE)
    card2 = b2["cards"][row["creative_key"]]
    assert card2["lane"] == "marked_to_pull"
    assert card2["decision"]["pre_ra2"] is True


def test_injection_detection(monkeypatch):
    _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    fresh = mk_row(key="120000000000000001",
                   launch=str(TODAY - dt.timedelta(days=2)), label="New")
    old = mk_row(key="120000000000000002",
                 launch=str(TODAY - dt.timedelta(days=40)), label="Old")
    b = L.build_block([fresh, old], record_render=False)
    assert b["cards"]["120000000000000001"]["injected"] is True
    assert b["cards"]["120000000000000002"]["injected"] is False


def test_review_session_journal_one_dated_record(monkeypatch):
    store = _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    row = _row_sufficient()
    L.keep_running({"user": "romano", "display": "Romano"},
                   "120000000000000002", "hook still fresh")
    L.move({"user": "romano", "display": "Romano"}, row["creative_key"],
           "pull", "CPL 2x its set median", row, "due_for_review")
    L._session_record({"user": "romano"}, "pulled", row["creative_key"],
                      "CPL 2x its set median")
    sessions = L.review_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s["date"] == str(TODAY) and s["cohort_size"] == 2
    assert len(s["kept"]) == 1 and len(s["pulled"]) == 1
    assert s["kept"][0]["reason"] == "hook still fresh"
    assert "romano" in s["reviewers"]


# ── sets overview: partition + budget drift ──────────────────────────────────

def test_sets_partition_and_budget_drift(monkeypatch):
    _kv_reset(monkeypatch)
    es = _spend_env(monkeypatch, {1: {"120000000000000001": 92.0,
                                      "120000000000000002": 30.0,
                                      "120000000000000003": 20.0}})
    L.map_adset({"user": "rydel"}, "230000000000000001", "graphics")
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    rows = [mk_row(key="120000000000000001", leads=3, label="G1"),
            mk_row(key="120000000000000002", leads=2, label="G2"),
            mk_row(key="120000000000000003", leads=1, label="G3")]
    sv = L.sets_overview(rows, rows)
    g = sv["roles"]["graphics"]
    # actual == archive rollup; drift fires (spent $142 vs $60–70 intended)
    assert g["actual_yesterday"] == 142.0
    assert g["budget_drift"] and "over" in g["budget_drift"]
    assert sv["partition"]["ok"]                    # Σ set spend == archive total
    assert g["ranking"][0]["delivery_share_pct"] > g["ranking"][-1]["delivery_share_pct"]
    # unmapped surfacing: unmap → the same spend lands in unmapped, partition holds
    L.map_adset({"user": "rydel"}, "230000000000000001", "unmapped")
    sv2 = L.sets_overview(rows, rows)
    assert sv2["unmapped"] and sv2["unmapped"][0]["window_spend"] == 142.0
    assert sv2["partition"]["ok"]


def test_broad_vs_targeted_pair_and_fallback(monkeypatch):
    _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    es = {"ads": {"120000000000000001": {"adset_id": "230000000000000001"},
                  "120000000000000009": {"adset_id": "230000000000000002"},
                  "120000000000000002": {"adset_id": "230000000000000001"},
                  "120000000000000003": {"adset_id": "230000000000000002"}}}
    days = {str(TODAY - dt.timedelta(days=1)): {
        "120000000000000001": {"spend": 50.0, "impressions": 10},
        "120000000000000009": {"spend": 30.0, "impressions": 10},
        "120000000000000002": {"spend": 40.0, "impressions": 10},
        "120000000000000003": {"spend": 60.0, "impressions": 10}}}
    monkeypatch.setattr(L, "_entity_store", lambda: es)
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": days})
    L.map_adset({"user": "rydel"}, "230000000000000001", "broad_video")
    L.map_adset({"user": "rydel"}, "230000000000000002", "targeted_video")
    rows = [
        # ONE creative with ads in BOTH sets — the exact pair
        mk_row(key="120000000000000001", leads=6, label="Paired",
               ad_ids=["120000000000000001", "120000000000000009"]),
        mk_row(key="120000000000000002", leads=4, label="Broad only"),
        mk_row(key="120000000000000003", leads=2, label="Targeted only")]
    bt = L.broad_vs_targeted(rows)
    assert bt["available"]
    assert len(bt["pairs"]) == 1
    pr = bt["pairs"][0]
    assert pr["match"].startswith("exact")
    assert pr["broad"]["spend_window"] == 50.0
    assert pr["targeted"]["spend_window"] == 30.0
    assert "not available" in pr["evidence_note"] or "per-set" in pr["evidence_note"]
    agg = bt["set_aggregate"]
    assert agg["broad_video"]["creatives"] == 1 and agg["targeted_video"]["creatives"] == 1
    assert bt["shared_creatives"] == 1 and "excluded" in bt["aggregate_note"]
    # unmapped → honest unavailability
    _kv_reset(monkeypatch)
    bt2 = L.broad_vs_targeted(rows)
    assert bt2["available"] is False and "map the Broad and Targeted" in bt2["reason"]


# ── carried-over doctrines (regression) ──────────────────────────────────────

def test_status_triad_carried_over(monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: True)
    import time
    from helpers import today_sydney
    es = {"ads": {"120000000000000001": {"effective_status": "CAMPAIGN_PAUSED"}}}
    ss = {"refreshed_at": time.time(),
          "days": {str(today_sydney()): {"120000000000000001": {
              "spend": 0.0, "impressions": 0}}}}
    st = L.status_for(["120000000000000001"], es, ss)
    assert st["label"] == "NOT DELIVERING · campaign paused"
    assert st["blocked_by_parent"] is True


def test_stances_never_move_cards_carried(monkeypatch):
    store = _kv_reset(monkeypatch)
    monkeypatch.setattr(D, "context_stamp", lambda *a, **k: {"at": "t"})
    _fix_today(monkeypatch)
    row = mk_row(leads=1, launch=str(TODAY - dt.timedelta(days=3)))
    for u in ("romano", "isaiah", "inna"):
        D.post({"user": u, "display": u, "role": "ad_domain"}, "pull it",
               row["creative_key"], stance="kill")
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    b = L.build_block([row], record_render=False)
    assert b["cards"][row["creative_key"]]["lane"] == "running"   # unmoved
    assert store.get("ads:lifecycle:decisions") in (None, {})
    import inspect
    assert "stance" not in inspect.getsource(L.classify_stage)
    assert "stance" not in inspect.getsource(L.pull_candidates)


def test_review_flags_replace_kill_cards(monkeypatch):
    _kv_reset(monkeypatch)
    _fix_today(monkeypatch)
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    due = mk_row(key="120000000000000001",
                 launch=str(TODAY - dt.timedelta(days=9)), leads=2)
    b = L.build_block([due], record_render=False)
    fl = L.review_flags([due], block=b)
    assert len(fl) == 1 and fl[0]["kind"] == "review_due"
    assert "due for review" in fl[0]["headline"]
    assert "session=1" in fl[0]["link"]
    assert "humans decide" in fl[0]["question"]
