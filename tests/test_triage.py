"""tests/test_triage.py — the five-lane triage engine (ACTION_TRIAGE_REPORT,
Rydel-confirmed): dedup by fact key, lane routing, floor/cap, rollups, state,
the suppression audit trail."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import triage


def _reset_state():
    import kv_store
    kv_store.put("triage:state", {})
    kv_store.put("triage:log", {})


def test_fact_key_kills_the_double_emit():
    # the historical flood: the same fact emitted plain AND "Data integrity:"-prefixed
    a = triage.fact_key("Vipin: won but Close Date blank (contract —)")
    b = triage.fact_key("Data integrity: Vipin: won but Close Date blank (contract —)")
    assert a == b
    assert triage.fact_key("something else entirely") != a


def test_route_lanes_and_rollups():
    _reset_state()
    items = [
        {"severity": "S3", "category": "close", "title": "X closed — $9,000", "key": "k1"},
        {"severity": "S2", "category": "data_quality",
         "title": "Vipin: won but Close Date blank (contract —)"},
        {"severity": "S2", "category": "data_integrity",
         "title": "Data integrity: Vipin: won but Close Date blank (contract —)"},
        {"severity": "S2", "category": "data_quality",
         "title": "4 Active clients with $0 MRR"},
        {"severity": "S3", "category": "attr_flag", "title": "Ad board flag: A — $231 spent, 0 leads"},
        {"severity": "S3", "category": "attr_flag", "title": "Ad board flag: B — $225 spent, 0 leads"},
        {"severity": "S3", "category": "anomaly", "title": "CPL $117 -> $201 (+71%)"},
        {"severity": "S3", "category": "loop", "title": "you asked me to remind you: pilot venue?"},
        {"severity": "S1", "category": "failed", "title": "1 charge failed — $1,200 at risk"},
    ]
    for it in items:
        it.setdefault("key", triage.fact_key(it["title"]))
    r = triage.route(items)
    lanes = r["lanes"]
    # noise: the close event, suppressed WITH a reason
    assert len(lanes["noise"]) == 1 and "informational" in lanes["noise"][0]["reason"]
    # dedup + collapse: the "Data integrity:" copy never survives; the ONE fact lives
    # inside the Piolo DELEGATED rollup's detail, not as its own line anywhere
    all_titles = [x.get("title", "") for lane in lanes.values() for x in lane]
    assert not any("Close Date blank" in t for t in all_titles)
    dels = [d for d in lanes["delegated"] if d.get("rollup")]
    assert dels and dels[0]["count"] == 1 and "Piolo" in dels[0]["owner"]
    assert sum("Close Date blank" in t for t in dels[0]["detail"]) == 1
    # hygiene: the $0 MRR artifact
    assert any("$0 MRR" in (x.get("title") or "") for x in lanes["hygiene"])
    # attr flags collapse to ONE watch rollup linking /ads
    w = [x for x in lanes["watch"] if x.get("rollup")]
    assert len(w) == 1 and w[0]["count"] == 2 and w[0]["link"]
    # action: anomaly promoted (past any floor), loop (own ask), failed ($1,200)
    acts = lanes["action"]
    cats = {a["category"] for a in acts}
    assert cats == {"anomaly", "loop", "failed"}
    # ranked by dollars-at-stake: $1,200 failed first
    assert acts[0]["category"] == "failed"
    # every routing away from ACTION is logged
    assert r["routed_count"] >= 5


def test_floor_demotes_small_dollars_but_not_promoted():
    _reset_state()
    items = [
        {"severity": "S2", "category": "reconciliation",
         "title": "Unrecognised Stripe payment: Bob ($120)"},
        {"severity": "S3", "category": "anomaly", "title": "spend anomaly $120"},
    ]
    for it in items:
        it["key"] = triage.fact_key(it["title"])
    r = triage.route(items)
    # the $120 payer question drops below the $500 floor → WATCH
    assert any("Bob" in (x.get("title") or "") for x in r["lanes"]["watch"])
    # the anomaly is promoted regardless of size → ACTION
    assert any(x["category"] == "anomaly" for x in r["lanes"]["action"])


def test_dismiss_snooze_state_and_restore():
    _reset_state()
    item = {"severity": "S1", "category": "failed", "title": "1 charge failed — $1,200"}
    item["key"] = triage.fact_key(item["title"])
    assert triage.route([item])["lanes"]["action"]
    triage.set_state(item["key"], "dismissed", who="Rydel", reason="handled by phone")
    r = triage.route([item])
    assert not r["lanes"]["action"] and r["suppressed_count"] == 1
    # dismissed items stay auditable
    assert any("dismissed" in u["reason"] for u in r["user_actioned"])
    triage.set_state(item["key"], "restore")
    assert triage.route([item])["lanes"]["action"]
    # snooze: gone now, back after the window (until < today ⇒ shows again)
    triage.set_state(item["key"], "snoozed", days=7)
    assert not triage.route([item])["lanes"]["action"]
    import kv_store
    s = kv_store.get("triage:state")
    s[item["key"]]["until"] = "2000-01-01"
    kv_store.put("triage:state", s)
    assert triage.route([item])["lanes"]["action"]


def test_action_cap_overflow_stays_visible():
    _reset_state()
    items = [{"severity": "S2", "category": "failed",
              "title": f"charge {i} failed — ${1000 + i:,}"} for i in range(10)]
    for it in items:
        it["key"] = triage.fact_key(it["title"])
    r = triage.route(items)
    # the cap is a DISPLAY cap — route() returns all, ranked; the payload carries cap=7
    assert len(r["lanes"]["action"]) == 10 and r["cap"] == 7
    assert r["lanes"]["action"][0]["dollars"] == 1009   # ranked by dollars desc


def test_suppressed_command_reads_the_log():
    _reset_state()
    items = [{"severity": "S3", "category": "close", "title": "Y closed — $5,000",
              "key": triage.fact_key("Y closed — $5,000")}]
    triage.route(items)
    r, h = triage.handle_suppressed_command("show me what you suppressed")
    assert h and "Y closed" in r and "informational" in r
    assert triage.handle_suppressed_command("hello")[1] is False


def test_triage_action_command(monkeypatch):
    _reset_state()
    import action_feed
    key = triage.fact_key("CPL spiked +71%")
    monkeypatch.setattr(action_feed, "build_action_feed",
                        lambda *a, **k: {"items": [{"title": "CPL spiked +71%", "key": key}]})
    r, h = triage.handle_triage_action_command("snooze CPL for 3 days")
    assert h and "3 days" in r
    import kv_store
    assert kv_store.get("triage:state")[key]["status"] == "snoozed"
    r, h = triage.handle_triage_action_command("restore CPL")
    assert h and key not in (kv_store.get("triage:state") or {})
    # ambiguous / unknown fragments never guess
    r, h = triage.handle_triage_action_command("dismiss zzz-no-such-item")
    assert h and "couldn't pin" in r
