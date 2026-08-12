"""
tests/test_ads_lifecycle.py — BOARD v2: the lifecycle engine.

LANE TRUTH: the four R-A boundary permutations exact · scale requires a
verdict (below-min-n NEVER lands in scale_candidate) · determinism · the two
kill kinds named · kill lane == dashboard kill cards (one computation).
STATUS TRUTH: triad vs raw status + delivery buckets · parent layer named ·
Meta-dead → DEGRADED, never a stale green.
DECISION LOOP: blank reason REJECTED · journal + attribution + feed ·
below-min-n friction · convergence (kill → paused; scale → new ad id) ·
ageing names the mover · owner reversal · disagreement chip · decision pins.
STANCES: opinions never votes (structural) · supersession counts once ·
one store · stance whitelist.
RULES: ruled defaults 4d/$200 · edits journaled who/old→new · bounds.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import ads_lifecycle as L
import ads_discussion as D


# ── fixtures ─────────────────────────────────────────────────────────────────

def _kv_reset(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: store.pop(k, None))
    return store


def mk_row(key="120000000000000001", leads=0, spend=0.0, closes=0, verdict=None,
           n_leads=None, n_closes=None, launch="2026-08-01", active_days=4,
           never=False, ad_ids=None, label="Burner"):
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


ST_LIVE = {"status": "delivering", "reason": "impressions", "layer": None,
           "as_of": "x", "degraded": None}
ST_PAUSED = {"status": "paused", "reason": "paused at the campaign layer",
             "layer": "campaign", "as_of": "x", "degraded": None}
RULES = dict(L.RULE_DEFAULTS)


# ── LANE TRUTH: the four R-A boundary permutations ───────────────────────────

def test_boundary_by_days_zero_leads_kill_candidate():
    # day 4 with $150 → boundary hit by DAYS; 0 leads → kill candidate
    s = L.classify_stage(mk_row(leads=0, spend=150, active_days=4), ST_LIVE, RULES)
    assert s["lane"] == "kill_candidate" and s["kill_basis"] == "rotation"
    assert s["rotation"]["boundary_by"] == "days"


def test_boundary_by_days_one_lead_watch():
    s = L.classify_stage(mk_row(leads=1, spend=150, active_days=4), ST_LIVE, RULES)
    assert s["lane"] == "watch"


def test_boundary_by_spend_zero_leads_kill_candidate():
    # day 2 with $200 → boundary hit by SPEND; 0 leads → kill candidate
    s = L.classify_stage(mk_row(leads=0, spend=200, active_days=2), ST_LIVE, RULES)
    assert s["lane"] == "kill_candidate" and s["kill_basis"] == "rotation"
    assert s["rotation"]["boundary_by"] == "spend"


def test_boundary_by_spend_one_lead_watch():
    s = L.classify_stage(mk_row(leads=1, spend=200, active_days=2), ST_LIVE, RULES)
    assert s["lane"] == "watch"


def test_inside_window_is_testing_with_progress():
    s = L.classify_stage(mk_row(leads=0, spend=163, active_days=3), ST_LIVE, RULES)
    assert s["lane"] == "testing"
    assert "day 3" in s["rotation"]["label"] and "$163" in s["rotation"]["label"]
    assert not s["rotation"]["boundary_hit"]


def test_rotation_clock_reads_first_delivery_active_days():
    # the clock is per-ad lifetime from FIRST DELIVERY (#133 active days),
    # labelled as its own clock — never the table's window
    s = L.classify_stage(mk_row(active_days=7, spend=50, leads=2), ST_LIVE, RULES)
    assert s["rotation"]["launch"] == "2026-08-01"
    assert s["rotation"]["day"] == 7
    assert "FIRST DELIVERY" in s["rotation"]["clock_note"]


# ── scale gate: verdict-backed ONLY ──────────────────────────────────────────

def test_scale_requires_verdict_never_hot_day2():
    # a hot early ad (5 leads, no verdict) past the spend boundary → WATCH
    s = L.classify_stage(mk_row(leads=5, spend=250, active_days=2), ST_LIVE, RULES)
    assert s["lane"] == "watch"
    # DOUBLE DOWN at sufficient n → scale_candidate
    s2 = L.classify_stage(mk_row(leads=40, spend=900, closes=4, active_days=30,
                                 verdict="DOUBLE DOWN"), ST_LIVE, RULES)
    assert s2["lane"] == "scale_candidate"


def test_below_min_n_never_scale_candidate():
    # every below-min-n permutation stays out of the statistical lane
    for leads in (0, 1, 5, 29):
        for spend in (0, 199, 200, 900):
            row = mk_row(leads=leads, spend=spend, active_days=10)
            assert L.classify_stage(row, ST_LIVE, RULES)["lane"] != "scale_candidate"


def test_verdict_kill_is_named_verdict_not_rotation():
    s = L.classify_stage(mk_row(leads=34, spend=900, active_days=30,
                                verdict="KILL"), ST_LIVE, RULES)
    assert s["lane"] == "kill_candidate" and s["kill_basis"] == "verdict"


def test_paused_is_archive_and_degraded_lineage_is_testing():
    assert L.classify_stage(mk_row(), ST_PAUSED, RULES)["lane"] == "archive"
    s = L.classify_stage(mk_row(launch=None), ST_LIVE, RULES)
    assert s["lane"] == "testing" and "degraded" in s["why"]
    s2 = L.classify_stage(mk_row(never=True), ST_LIVE, RULES)
    assert s2["lane"] == "testing" and "never delivered" in s2["why"]


def test_classifier_deterministic_and_stance_blind():
    row = mk_row(leads=0, spend=250, active_days=2)
    assert L.classify_stage(row, ST_LIVE, RULES) == L.classify_stage(row, ST_LIVE, RULES)
    # THE GUARD (Law 4), structural: no stance input exists anywhere in the
    # classify/move paths — stances cannot move cards by construction.
    import inspect
    assert "stance" not in inspect.getsource(L.classify_stage)
    assert "stance" not in inspect.getsource(L.move)
    assert "stance" not in inspect.getsource(L._check_convergence)


# ── STATUS TRUTH ─────────────────────────────────────────────────────────────

def _stores(effective="ACTIVE", impressions_today=0, refreshed_min_ago=5):
    import time
    from helpers import today_sydney
    es = {"ads": {"120000000000000001": {"effective_status": effective}}}
    ss = {"refreshed_at": time.time() - refreshed_min_ago * 60,
          "days": {str(today_sydney()): {"120000000000000001": {
              "spend": 0.0, "impressions": impressions_today}}}}
    return es, ss


def test_status_delivering_green(monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: True)
    es, ss = _stores(impressions_today=50)
    st = L.status_for(["120000000000000001"], es, ss)
    assert st["status"] == "delivering" and st["as_of"]


def test_status_enabled_not_delivering_amber_honest_reason(monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: True)
    es, ss = _stores(effective="ACTIVE", impressions_today=0)
    st = L.status_for(["120000000000000001"], es, ss)
    assert st["status"] == "enabled_not_delivering"
    assert "unknown" in st["reason"]          # honest when the cause isn't visible
    es2, ss2 = _stores(effective="PENDING_REVIEW", impressions_today=0)
    st2 = L.status_for(["120000000000000001"], es2, ss2)
    assert st2["status"] == "enabled_not_delivering" and "review" in st2["reason"]


def test_status_parent_layer_named(monkeypatch):
    # ad enabled, campaign off → effective CAMPAIGN_PAUSED → grey, layer NAMED
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: True)
    es, ss = _stores(effective="CAMPAIGN_PAUSED", impressions_today=0)
    st = L.status_for(["120000000000000001"], es, ss)
    assert st["status"] == "paused" and st["layer"] == "campaign"
    es2, ss2 = _stores(effective="ADSET_PAUSED")
    assert L.status_for(["120000000000000001"], es2, ss2)["layer"] == "ad set"


def test_status_meta_dead_degraded_never_stale_green(monkeypatch):
    import meta_entities
    monkeypatch.setattr(meta_entities, "configured", lambda: False)
    es, ss = _stores(impressions_today=50)     # delivery data EXISTS, source dead
    st = L.status_for(["120000000000000001"], es, ss)
    assert st["status"] == "unknown" and st["degraded"]
    # stale archive (>26h) also refuses to claim green
    monkeypatch.setattr(meta_entities, "configured", lambda: True)
    es2, ss2 = _stores(impressions_today=50, refreshed_min_ago=27 * 60)
    st2 = L.status_for(["120000000000000001"], es2, ss2)
    assert st2["status"] == "unknown" and "stale" in st2["degraded"]


# ── RULES (R-A) ──────────────────────────────────────────────────────────────

def test_rules_ruled_defaults_and_journaled_edits(monkeypatch):
    _kv_reset(monkeypatch)
    rl = L.rules()
    assert rl["test_days"] == 4 and rl["test_spend"] == 200.0   # THE ruling
    out, err = L.set_rules({"user": "rydel"}, {"test_spend": 300})
    assert err is None and out["test_spend"] == 300.0
    j = L.rules_journal()
    assert j[-1]["who"] == "rydel" and j[-1]["old"] == 200.0 and j[-1]["new"] == 300.0
    assert L.rules()["test_spend"] == 300.0      # live without a deploy
    # bounds + unknown keys refused
    assert L.set_rules({"user": "rydel"}, {"test_days": 0})[1]
    assert L.set_rules({"user": "rydel"}, {"nonsense": 5})[1]


def test_classifier_reads_edited_rules(monkeypatch):
    _kv_reset(monkeypatch)
    L.set_rules({"user": "rydel"}, {"test_spend": 100})
    s = L.classify_stage(mk_row(leads=0, spend=150, active_days=1), ST_LIVE, L.rules())
    assert s["lane"] == "kill_candidate"         # $150 ≥ the edited $100


# ── DECISION LOOP (R-B) ──────────────────────────────────────────────────────

def _row_sufficient(**kw):
    return mk_row(leads=35, closes=3, spend=900, active_days=30, **kw)


def test_move_blank_reason_rejected(monkeypatch):
    _kv_reset(monkeypatch)
    for blank in ("", "   ", None):
        dec, err, _f = L.move({"user": "romano"}, "120000000000000001", "kill",
                              blank, _row_sufficient(), "watch")
        assert dec is None and "reason" in err


def test_move_journaled_attributed_and_feeds(monkeypatch):
    store = _kv_reset(monkeypatch)
    dec, err, _f = L.move({"user": "romano", "display": "Romano"},
                          "120000000000000001", "kill", "CPL 3x account average",
                          _row_sufficient(), "watch")
    assert err is None and dec["state"] == "marked_to_kill"
    assert dec["by"] == "romano" and dec["reason"] == "CPL 3x account average"
    j = store["ads:lifecycle:journal"]
    assert j[-1]["who"] == "romano" and j[-1]["to"] == "marked_to_kill" \
        and j[-1]["reason"] == "CPL 3x account average"
    feed = store["feed:extra:ads_decisions"]
    assert len(feed) == 1 and "CPL 3x account average" in feed[0]["title"]
    assert "pause" in feed[0]["action"] and "does not control Meta" in feed[0]["action"]


def test_below_min_n_friction_then_confirm(monkeypatch):
    _kv_reset(monkeypatch)
    row = mk_row(leads=2, spend=250, active_days=3)     # below both min-n gates
    dec, err, friction = L.move({"user": "romano"}, "120000000000000001",
                                "kill", "burning cash", row, "watch")
    assert dec is None and err is None and friction["friction"]
    assert "rotation call, not a verdict" in friction["note"]
    dec2, err2, f2 = L.move({"user": "romano"}, "120000000000000001", "kill",
                            "burning cash", row, "watch", confirm_below_min_n=True)
    assert err2 is None and f2 is None and dec2["below_min_n"] is True


def test_reversal_owner_reason_required(monkeypatch):
    store = _kv_reset(monkeypatch)
    L.move({"user": "romano"}, "120000000000000001", "kill", "r",
           _row_sufficient(), "watch")
    ok, err = L.reverse({"user": "rydel"}, "120000000000000001", "")
    assert not ok and "reason" in err
    ok2, err2 = L.reverse({"user": "rydel"}, "120000000000000001", "changed my mind")
    assert ok2 and err2 is None
    assert "120000000000000001" not in store["ads:lifecycle:decisions"]
    assert store["ads:lifecycle:journal"][-1]["action"] == "reverse"   # never vanishes


def _block(monkeypatch, rows, status):
    import meta_entities
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {"x": {}}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: status)
    return L.build_block(rows, record_render=False)


def test_decision_pins_lane_and_disagreement_chip(monkeypatch):
    _kv_reset(monkeypatch)
    row = _row_sufficient(verdict="DOUBLE DOWN")        # engine: scale_candidate
    L.move({"user": "romano", "display": "Romano"}, row["creative_key"],
           "kill", "fatigued creative", row, "scale_candidate")
    b = _block(monkeypatch, [row], ST_LIVE)
    card = b["cards"][row["creative_key"]]
    assert card["lane"] == "marked_to_kill"             # the human pins
    assert card["disagreement"] == "engine: scale-candidate"   # surfaced, never silent
    assert card["engine_lane"] == "scale_candidate"


def test_kill_convergence_on_paused_status(monkeypatch):
    store = _kv_reset(monkeypatch)
    row = _row_sufficient()
    L.move({"user": "romano", "display": "Romano"}, row["creative_key"],
           "kill", "r", row, "watch")
    b = _block(monkeypatch, [row], ST_PAUSED)           # next sync: Meta paused
    card = b["cards"][row["creative_key"]]
    assert card["lane"] == "archive" and "killed" in card["archive_label"]
    assert card["decision"]["executed"] is True
    j = store["ads:lifecycle:journal"]
    assert j[-1]["action"] == "converged" and "paused" in j[-1]["reason"]
    assert store["feed:extra:ads_decisions"] == []      # feed item self-retired


def test_scale_convergence_on_new_ad_id(monkeypatch):
    store = _kv_reset(monkeypatch)
    row = _row_sufficient(verdict="DOUBLE DOWN")
    L.move({"user": "rydel"}, row["creative_key"], "scale", "winner", row,
           "scale_candidate")
    row2 = dict(row, ad_ids=row["ad_ids"] + ["120000000000000009"])  # duplication
    b = _block(monkeypatch, [row2], ST_LIVE)
    card = b["cards"][row["creative_key"]]
    assert card["decision"]["executed"] is True
    assert "new ad id" in card["decision"]["convergence"]
    assert store["ads:lifecycle:journal"][-1]["to"] == "scaled (verified)"


def test_unexecuted_decision_ages_naming_the_mover(monkeypatch):
    store = _kv_reset(monkeypatch)
    row = _row_sufficient()
    L.move({"user": "romano", "display": "Romano"}, row["creative_key"],
           "kill", "r", row, "watch")
    # backdate the mark 3 days
    d = store["ads:lifecycle:decisions"]
    from datetime import timedelta
    from helpers import today_sydney
    d[row["creative_key"]]["at"] = str(today_sydney() - timedelta(days=3)) + " 09:00"
    b = _block(monkeypatch, [row], ST_LIVE)             # STILL delivering
    card = b["cards"][row["creative_key"]]
    assert card["decision"]["age_days"] == 3 and not card["decision"]["executed"]
    L._publish_feed()
    feed = store["feed:extra:ads_decisions"]
    assert "3d ago" in feed[0]["title"] and "Romano" in feed[0]["title"]
    assert feed[0]["severity"] == "S2"                  # aged → raised severity
    # sentinel convergence-lag watch names it too
    monkeypatch.setattr(L, "_sentinel_feed", lambda *a, **k: None)
    import roster_engine
    monkeypatch.setattr(roster_engine, "load_result",
                        lambda *a, **k: ({"creatives": []}, {}))
    w = L.sentinel_watch()
    assert w["convergence_lag"] and w["convergence_lag"][0]["by"] == "Romano" \
        and w["convergence_lag"][0]["age_days"] == 3


def test_paused_without_decision_archived_labelled(monkeypatch):
    _kv_reset(monkeypatch)
    b = _block(monkeypatch, [_row_sufficient()], ST_PAUSED)
    card = b["cards"]["120000000000000001"]
    assert card["lane"] == "archive"
    assert card["archive_label"] == "paused (no decision recorded)"


# ── kill lane == dashboard kill cards (consolidation) ────────────────────────

def test_kill_cards_are_the_kill_lane(monkeypatch):
    _kv_reset(monkeypatch)
    rows = [
        mk_row(key="120000000000000001", leads=0, spend=250, active_days=2,
               label="Rot Kill"),                       # rotation kill
        mk_row(key="120000000000000002", leads=34, spend=900, active_days=30,
               verdict="KILL", label="Verdict Kill"),   # verdict kill
        mk_row(key="120000000000000003", leads=1, spend=250, active_days=5,
               label="Watcher"),                        # watch — not a card
    ]
    import meta_entities
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {"x": {}}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    block = L.build_block(rows, record_render=False)
    lane_keys = {k for k, c in block["cards"].items() if c["lane"] == "kill_candidate"}
    flags = L.kill_candidate_flags(rows)
    assert {f["creative_key"] for f in flags} == lane_keys   # ONE computation
    bases = {f["creative_key"]: f["kill_basis"] for f in flags}
    assert bases["120000000000000001"] == "rotation"
    assert bases["120000000000000002"] == "verdict"
    assert all("view=board" in f["link"] for f in flags)
    # a decided card leaves the flag rail (the feed carries the mark)
    L.move({"user": "romano"}, "120000000000000002", "kill", "r", rows[1], "kill_candidate")
    assert {f["creative_key"] for f in L.kill_candidate_flags(rows)} == \
        {"120000000000000001"}


def test_old_spend_no_leads_rule_retired():
    import attribution_flags as AF
    import inspect
    assert "ad_flag_spend_no_leads" not in AF.DEFAULTS
    # the executable rule is gone (the source keeps only the pointer comment)
    src = inspect.getsource(AF.flags)
    assert 'th["ad_flag_spend_no_leads"]' not in src
    assert '"spend_no_leads",' not in src


# ── STANCES (R-C) via the ONE discussion store ───────────────────────────────

def _actor(u):
    return {"user": u, "display": u.capitalize(), "role": "ad_domain"}


def _no_stamp(monkeypatch):
    monkeypatch.setattr(D, "context_stamp", lambda *a, **k: {"at": "t"})


ANCHOR = "120000000000000001"


def test_stance_posts_counts_and_supersedes(monkeypatch):
    _kv_reset(monkeypatch)
    _no_stamp(monkeypatch)
    c1, e1 = D.post(_actor("isaiah"), "CPL is triple the account", ANCHOR, stance="kill")
    assert e1 is None and c1["stance"] == "kill"
    s = D.stances_by_anchor()[ANCHOR]
    assert s["counts"] == {"kill": 1, "scale": 0, "hold": 0}
    # Inna posts Hold → "1 kill · 1 hold"
    D.post(_actor("inna"), "", ANCHOR, stance="hold")          # stance-only allowed
    s = D.stances_by_anchor()[ANCHOR]
    assert s["counts"]["kill"] == 1 and s["counts"]["hold"] == 1
    # Isaiah changes his mind → supersedes, still counts ONCE
    c3, _ = D.post(_actor("isaiah"), "actually the hook is fine", ANCHOR, stance="hold")
    s = D.stances_by_anchor()[ANCHOR]
    assert s["counts"] == {"kill": 0, "scale": 0, "hold": 2}
    assert s["by"]["isaiah"] == "hold"
    # the superseded comment is journaled, never edited
    old = next(c for c in D._store()["comments"] if c["id"] == c1["id"])
    assert old["stance_superseded_by"] == c3["id"]
    assert old["journal"][-1]["action"] == "stance_superseded"


def test_stance_whitelist_and_body_rules(monkeypatch):
    _kv_reset(monkeypatch)
    _no_stamp(monkeypatch)
    _c, err = D.post(_actor("isaiah"), "x", ANCHOR, stance="nuke")
    assert err and "stance" in err
    _c2, err2 = D.post(_actor("isaiah"), "", ANCHOR)           # no stance, no text
    assert err2                                                 # still rejected
    c3, err3 = D.post(_actor("isaiah"), None, ANCHOR, stance="hold")
    assert err3 is None and c3["body"] == "" and c3["stance"] == "hold"


def test_one_store_stance_rides_every_render(monkeypatch):
    _kv_reset(monkeypatch)
    _no_stamp(monkeypatch)
    D.post(_actor("isaiah"), "kill it", ANCHOR, stance="kill")
    wire = D.list_comments(creative=ANCHOR)[0]
    assert wire["stance"] == "kill"                    # panel + dossier wire shape
    assert ANCHOR in D.stances_by_anchor()             # chip
    assert "stance: KILL" in D.edith_context()         # EDITH context digest


def test_tombstoned_stance_leaves_the_summary(monkeypatch):
    _kv_reset(monkeypatch)
    _no_stamp(monkeypatch)
    c, _ = D.post(_actor("isaiah"), "kill it", ANCHOR, stance="kill")
    D.delete(_actor("isaiah"), c["id"])
    assert ANCHOR not in D.stances_by_anchor()


def test_stances_never_move_cards(monkeypatch):
    """Attempt the auto-move path — none exists. Three kill stances change
    NOTHING about the lane or the decision store."""
    store = _kv_reset(monkeypatch)
    _no_stamp(monkeypatch)
    row = mk_row(leads=1, spend=250, active_days=5)     # engine: watch
    for u in ("romano", "isaiah", "inna"):
        D.post(_actor(u), "kill this", ANCHOR, stance="kill")
    b = _block(monkeypatch, [row], ST_LIVE)
    assert b["cards"][ANCHOR]["lane"] == "watch"        # unmoved
    assert store.get("ads:lifecycle:decisions") in (None, {})
    assert b["stances"][ANCHOR]["counts"]["kill"] == 3  # summarized, that's all


# ── EDITH drills ─────────────────────────────────────────────────────────────

def _mock_all_time(monkeypatch, rows):
    import roster_engine
    monkeypatch.setattr(roster_engine, "load_result",
                        lambda *a, **k: ({"creatives": rows}, {}))


def test_edith_why_did_we_kill(monkeypatch):
    _kv_reset(monkeypatch)
    row = _row_sufficient(label="Burner Hook")
    _mock_all_time(monkeypatch, [row])
    L.move({"user": "romano", "display": "Romano"}, row["creative_key"],
           "kill", "CPL tripled after day 3", row, "watch")
    ans, handled = L.handle_decision_recall("why did we kill Burner Hook?")
    assert handled and "Romano" in ans and "CPL tripled after day 3" in ans
    # no decision → the engine's read, honestly labelled
    ok, _e = L.reverse({"user": "rydel"}, row["creative_key"], "undo")
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {"x": {}}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    ans2, handled2 = L.handle_decision_recall("why did we kill Burner Hook?")
    assert handled2 and "No human decision" in ans2


def test_edith_what_does_the_team_think(monkeypatch):
    _kv_reset(monkeypatch)
    _no_stamp(monkeypatch)
    row = _row_sufficient(label="Burner Hook")
    _mock_all_time(monkeypatch, [row])
    D.post(_actor("isaiah"), "CPL is triple", row["creative_key"], stance="kill")
    D.post(_actor("inna"), "give it the week", row["creative_key"], stance="hold")
    ans, handled = L.handle_stance_recall("what does the team think of Burner Hook?")
    assert handled
    assert "1 kill" in ans and "1 hold" in ans
    assert "CPL is triple" in ans and "give it the week" in ans
    assert "opinions" in ans                            # the guard, stated


# ── sentinel: stage drift + rules integrity ──────────────────────────────────

def test_sentinel_stage_drift_zero_on_unchanged_inputs(monkeypatch):
    store = _kv_reset(monkeypatch)
    row = _row_sufficient()
    import roster_engine
    monkeypatch.setattr(roster_engine, "load_result",
                        lambda *a, **k: ({"creatives": [row]}, {}))
    monkeypatch.setattr(L, "_entity_store", lambda: {"ads": {"x": {}}})
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    monkeypatch.setattr(L, "status_for", lambda *a, **k: ST_LIVE)
    L.build_block([row], record_render=True)            # the render stamp
    fired = []
    monkeypatch.setattr(L, "_sentinel_feed", lambda m, loud=False: fired.append(m))
    w = L.sentinel_watch()
    assert w["stage_drift"] == []                       # zero drift, recompute == render
    assert w["rules"]["ok"]


def test_sentinel_rules_integrity_catches_unjournaled_edit(monkeypatch):
    store = _kv_reset(monkeypatch)
    store["ads:rotation_rules"] = {"test_days": 9}      # a direct kv write, no journal
    import roster_engine
    monkeypatch.setattr(roster_engine, "load_result",
                        lambda *a, **k: ({"creatives": []}, {}))
    monkeypatch.setattr(L, "_spend_store", lambda: {"refreshed_at": 0, "days": {}})
    fired = []
    monkeypatch.setattr(L, "_sentinel_feed", lambda m, loud=False: fired.append(m))
    w = L.sentinel_watch()
    assert not w["rules"]["ok"]
    assert any("NO edit journal" in m for m in fired)
