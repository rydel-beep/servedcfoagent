"""PIOLO'S ACCESS · SAME-DAY CLOSES · MONEY UNDER ANOTHER NAME (#161).

Three things are pinned here:
  1 R-PIOLO — full read, his queue actions, three carve-outs, deny by default
  2 evidence-first close detection + event-driven recompute
  3 a payer is attached to a client by identity or by a ruling, never by
    resemblance
"""

import json
import os
import re

import pytest

import kv_store

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def _code_only(src: str) -> str:
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in src.splitlines())


@pytest.fixture()
def app_client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-161")
    import app as appmod
    return appmod.app


def _as(app, role, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": user, "role": role, "display": user}
    return c


# ── PART 1 · R-PIOLO ────────────────────────────────────────────────────────

def test_piolo_reads_the_estate(app_client):
    c = _as(app_client, "coo", "piolo")
    for path in ("/dashboard/today", "/dashboard/sales", "/dashboard/scale",
                 "/dashboard/scale/travelling", "/dashboard/system",
                 "/dashboard/api/travelling", "/dashboard/api/unit-economics",
                 "/dashboard/api/decision-cards", "/dashboard/api/ar",
                 "/dashboard/api/outflow-bands", "/dashboard/api/scale/defaults"):
        assert c.get(path).status_code == 200, path


def test_parity_replaces_the_carve_outs(app_client):
    """R-PIOLO-PARITY (#167, supersedes #161): the finance role reaches the
    old carve-outs and passes the old money-truth gates. The safeguard is
    attribution + owner reversal, not a locked door. Only the THREE strict
    items refuse him."""
    c = _as(app_client, "coo", "piolo")
    assert c.get("/dashboard/csm").status_code == 200          # toggle ON
    assert c.get("/dashboard/api/comp/rules").status_code == 200
    assert c.get("/dashboard/api/comp/cost").status_code == 200
    for path in ("/dashboard/api/renewal/declare", "/dashboard/api/targets/set",
                 "/dashboard/api/scale/commit-plan", "/dashboard/api/gap/rebuild",
                 "/dashboard/api/unmatched/confirm", "/dashboard/api/closes/confirm",
                 "/dashboard/api/refresh-now"):
        assert c.post(path, json={}).status_code != 403, path
    # the three strict items
    assert c.post("/dashboard/api/csm/discreet", json={"on": True}).status_code == 403
    assert c.get("/dashboard/api/parity/exceptions").status_code == 403
    assert c.post("/dashboard/api/parity/exceptions",
                  json={"section": "csm", "withdrawn": True}).status_code == 403


def test_a_new_route_is_inherited_by_finance_automatically():
    """#167 inverts #161: parity by INHERITANCE. A brand-new owner route is
    reachable by finance with no grant; only the exception list denies."""
    import role_access as RA
    assert RA.coo_permitted("/dashboard/api/brand-new-thing", "GET")[0]
    assert RA.coo_permitted("/dashboard/api/brand-new-thing", "POST")[0]
    RA.set_exception("csm", True, "rydel")
    try:
        assert not RA.coo_permitted("/dashboard/api/csm/model", "GET")[0]
    finally:
        RA.set_exception("csm", False, "rydel")
    assert RA.coo_permitted("/dashboard/api/csm/model", "GET")[0]


def test_the_exception_list_ships_empty_and_journals():
    """#167: the toggle ships ON (CSM included — NOT withdrawn); every flip
    is journaled with who and when."""
    import role_access as RA
    import kv_store as _kv
    _kv._MEM.pop(RA.K_EXCEPTIONS, None)
    assert RA.exceptions() == []
    assert RA.csm_withdrawn() is False
    RA.set_exception("csm", True, "rydel")
    j = _kv.get(RA.K_JOURNAL)
    assert j[-1]["withdrawn"] is True and j[-1]["by"] == "rydel"
    RA.set_exception("csm", False, "rydel")
    assert RA.exceptions() == []
    assert RA.set_exception("nonsense", True, "rydel")["ok"] is False


def test_other_roles_are_exactly_as_walled_as_before(app_client):
    """#167 changed FINANCE only. ad_domain, sales and anonymous keep their
    fail-closed scopes — spot-checked across the finance estate."""
    for role, user in (("ad_domain", "romano"), ("sales", "kalin")):
        c = _as(app_client, role, user)
        for path in ("/dashboard/api/snapshot", "/dashboard/api/comp/rules",
                     "/dashboard/api/unit-economics", "/dashboard/api/pl",
                     "/dashboard/api/csm/model"):
            assert c.get(path).status_code in (302, 403), (role, path)
    anon = app_client.test_client()
    assert anon.get("/dashboard/api/snapshot").status_code in (302, 401)


def test_the_commission_column_is_rendered_for_piolo_too(app_client):
    """#167: per-person pay is his at parity — the column renders for both."""
    owner = _as(app_client, "owner", "rydel").get("/dashboard/sales").data.decode()
    coo = _as(app_client, "coo", "piolo").get("/dashboard/sales").data.decode()
    assert ">Commission<" in owner
    assert ">Commission<" in coo
    assert "pay: owner-only" not in coo


def test_a_total_that_is_one_persons_pay_is_suppressed():
    import role_access as RA
    one = [{"name": "Kalin", "commission": 2250.0, "closes": 2},
           {"name": "Coby", "commission": 0.0, "closes": 0}]
    two = [{"name": "Kalin", "commission": 2250.0, "closes": 2},
           {"name": "Coby", "commission": 550.0, "closes": 1}]
    assert RA.hide_single_person_total(one) is True
    assert RA.hide_single_person_total(two) is False
    assert "commission" not in RA.scrub_person_pay(one)[0]


def test_edith_refuses_per_person_pay_only_to_non_finance(monkeypatch):
    """#167: finance hears pay figures; a non-finance role still doesn't."""
    import sales_cost
    monkeypatch.setattr("dashboard.auth.is_finance", lambda: False)
    reply, handled = sales_cost.handle_commission_query(
        "what do commissions cost us per client")
    assert handled and "limited to the owner and the finance role" in reply


def test_edith_answers_csm_for_piolo_unless_withdrawn():
    import csm_plan
    import role_access as RA
    assert csm_plan._csm_role_ok({"user": "piolo", "role": "coo"}) is True
    RA.set_exception("csm", True, "rydel")
    try:
        reply, handled = csm_plan.handle_csm_command(
            "csm roi status", {"user": "piolo", "role": "coo"})
        assert reply is None and handled is False
    finally:
        RA.set_exception("csm", False, "rydel")


def test_edith_voice_is_his_too(app_client):
    """#167: chat AND voice, same fallback rules. The routes answer a
    finance session (the TTS may 4xx on missing text — the door is open)."""
    import role_access as RA
    for path in ("/dashboard/api/tts", "/dashboard/api/voice-status",
                 "/dashboard/api/chat-stream"):
        assert RA.coo_permitted(path, "GET")[0], path
    c = _as(app_client, "coo", "piolo")
    assert c.get("/dashboard/api/voice-status").status_code == 200


# ── PART 3 · evidence-first detection ───────────────────────────────────────

def test_a_close_is_never_created_without_evidence():
    src = _code_only(_read("close_detect.py"))
    assert "record_derived_date" in src
    fn = src[src.index("def confirm("):src.index("def invalidate_now(")]
    assert "no detected close with that key" in fn
    assert "carries no evidence links" in fn


def test_confirm_refuses_a_key_that_was_never_detected(monkeypatch):
    kv_store._MEM.clear()
    import close_detect
    kv_store.put(close_detect.K_DETECTED, {"entries": []})
    res = close_detect.confirm("someone-who-never-closed")
    assert res["ok"] is False and "thin air" in res["error"]


def test_detection_merges_sources_and_names_what_is_missing(monkeypatch):
    kv_store._MEM.clear()
    import close_detect
    monkeypatch.setattr(close_detect, "_from_tracker", lambda: [])
    monkeypatch.setattr(close_detect, "_from_stage_recorder", lambda: [])
    monkeypatch.setattr(close_detect, "_from_payments", lambda: [])
    monkeypatch.setattr(close_detect, "_from_ghl", lambda: [{
        "person": "Koji Sample", "close_date": str(__import__("helpers").today_sydney()),
        "source": "ghl stage", "provenance": "GHL opportunity in stage 'Closed Deal'",
        "evidence": {"opp_id": "opp1", "contact_id": "c1"}, "email": None}])
    res = close_detect.scan()
    e = res["entries"][0]
    assert e["state"] == "DETECTED"             # one source only
    assert "tracker" in e["corroboration_pending"]
    assert "contract value" in e["missing"]
    assert "a matched payment" in e["missing"]


def test_two_sources_make_it_confirmed(monkeypatch):
    kv_store._MEM.clear()
    import close_detect
    from helpers import today_sydney
    d = str(today_sydney())
    monkeypatch.setattr(close_detect, "_from_tracker", lambda: [])
    monkeypatch.setattr(close_detect, "_from_stage_recorder", lambda: [{
        "person": "Koji Sample", "close_date": d, "source": "stage recorder",
        "provenance": "recorded move into 'Closed Deal'",
        "evidence": {"opp_id": "opp1"}, "email": None}])
    monkeypatch.setattr(close_detect, "_from_payments", lambda: [])
    monkeypatch.setattr(close_detect, "_from_ghl", lambda: [{
        "person": "Koji Sample", "close_date": d, "source": "ghl stage",
        "provenance": "GHL opportunity in stage 'Closed Deal'",
        "evidence": {"opp_id": "opp1", "contact_id": "c1"}, "email": None}])
    res = close_detect.scan()
    assert res["entries"][0]["state"] == "CONFIRMED"


def test_a_new_close_invalidates_immediately(monkeypatch):
    """Not on a timer. The whole defect was a pipeline that waited."""
    kv_store._MEM.clear()
    import close_detect
    from helpers import today_sydney
    calls = {"epoch": 0, "blocks": 0}

    def _fake_builders():
        def _b():
            calls["blocks"] += 1
        return (("exec_top", _b),)

    import freshness
    monkeypatch.setattr(freshness, "_block_builders", _fake_builders)
    monkeypatch.setattr("resolution.bump_derived_epoch",
                        lambda reason: calls.__setitem__("epoch", calls["epoch"] + 1))
    monkeypatch.setattr(close_detect, "_from_tracker", lambda: [])
    monkeypatch.setattr(close_detect, "_from_stage_recorder", lambda: [])
    monkeypatch.setattr(close_detect, "_from_payments", lambda: [])
    monkeypatch.setattr(close_detect, "_from_ghl", lambda: [{
        "person": "Brand New", "close_date": str(today_sydney()),
        "source": "ghl stage", "provenance": "stage",
        "evidence": {"opp_id": "o9"}, "email": None}])
    res = close_detect.tick()
    assert res["new"], "a first sighting must count as new"
    assert calls["epoch"] == 1 and calls["blocks"] == 1
    again = close_detect.tick()
    assert not again["new"], "the same close must not re-fire every tick"


def test_the_tick_runs_on_the_five_minute_loop():
    src = _code_only(_read("freshness.py"))
    fn = src[src.index("def tick("):src.index("def _block_builders")]
    assert "close_detect.tick()" in fn


def test_detection_is_not_limited_to_the_gap_window():
    """The gap ledger only looks inside a detected window, which is why a
    close today could be invisible."""
    src = _code_only(_read("close_detect.py"))
    assert "gap_window" not in src and "detect_gap" not in src


# ── PART 3 · payments ───────────────────────────────────────────────────────

def test_a_payer_is_never_attached_on_a_resemblance():
    import stripe_reconcile as sr
    idx = {"by_email": {}, "contacts": [({"nirosha", "dushani", "jayasekara"},
                                         "Nirosha Dushani Jayasekara", "jayasekara")],
           "by_business": {}, "surname_map": {"jayasekara": {"Nirosha Dushani Jayasekara"}}}
    roster = {"active": set(), "amounts": {}}
    kv_store._MEM.clear()
    m = sr._match_payment("Nirosha Jayasekara", "", 1000, idx, roster)
    assert m["category"] == "needs_review" and "business" not in m


def test_a_confirmed_alias_is_remembered_and_reused(monkeypatch):
    kv_store._MEM.clear()
    import unmatched_payments as UP
    import stripe_reconcile as sr
    monkeypatch.setattr(UP, "scan", lambda *a, **k: {"count": 0, "total_unmatched": 0})
    monkeypatch.setattr("close_detect.invalidate_now", lambda reason: {"rebuilt": []})
    res = UP.confirm("Sanatani Rombola", "Koji", actor="rydel", charge_id="ch_1")
    assert res["ok"]
    assert sr._aliases()[sr._norm("Sanatani Rombola")] == "Koji"
    j = UP.journal()[-1]
    assert j["by"] == "rydel" and j["charge_id"] == "ch_1"
    idx = {"by_email": {}, "contacts": [], "by_business": {}, "surname_map": {}}
    m = sr._match_payment("Sanatani Rombola", "", 3000, idx,
                          {"active": set(), "amounts": {}})
    assert m["business"] == "Koji" and m["basis"] == "confirmed alias"


def test_confirming_an_alias_moves_the_numbers(monkeypatch):
    kv_store._MEM.clear()
    import unmatched_payments as UP
    fired = {}
    monkeypatch.setattr(UP, "scan", lambda *a, **k: {"count": 0, "total_unmatched": 0})
    monkeypatch.setattr("close_detect.invalidate_now",
                        lambda reason: fired.setdefault("reason", reason) or {"rebuilt": ["exec_top"]})
    UP.confirm("Someone Else", "Some Venue", actor="rydel")
    assert "alias confirmed" in fired["reason"]


def test_cash_still_comes_only_from_stripe():
    """R-CASH: the new modules read charges, never derive money."""
    for mod in ("unmatched_payments.py", "close_detect.py"):
        src = _code_only(_read(mod))
        assert "_recent_charges" in src or "charge" in src
        for forbidden in ("monetary_value or", "amount = contract",
                          "cash = contract"):
            assert forbidden not in src, mod


def test_the_panel_reads_stored_results_only():
    src = _code_only(_read("unmatched_payments.py"))
    fn = src[src.index("def panel("):src.index("def matched_without_close(")]
    assert "_charges(" not in fn and "scan(" not in fn


def test_the_package_never_writes_to_the_tracker():
    src = _code_only(_read("close_detect.py"))
    fn = src[src.index("def piolo_package("):src.index("def confirm(")]
    assert "READ-ONLY law" in _read("close_detect.py")
    for verb in ("values().update", "append_row", "batchUpdate", "requests.post"):
        assert verb not in fn


def test_a_confirmed_alias_counts_as_payment_evidence():
    """The alias store existed and the gap ledger never read it: money under
    a payer name Rydel had already ruled on still counted as no payment, so
    the close stayed PROPOSED and out of every metric."""
    kv_store._MEM.clear()
    import gap_reconcile as GR
    import stripe_reconcile as SR
    SR.learn_alias("Sanatani Rombola", "Koji")
    charges = [{"id": "ch_koji", "paid": True, "status": "succeeded",
                "amount": 300000, "created": 1758500000,
                "customer": {"name": "Sanatani Rombola", "email": "s@r.com"},
                "billing_details": {}}]
    none_ = GR._stripe_hits("Someone Unrelated", "nobody@x.com", charges)
    assert none_ == []
    hits = GR._stripe_hits("Koji Person", "koji@venue.com", charges, client="Koji")
    assert len(hits) == 1 and hits[0]["match"] == "confirmed alias"
    assert hits[0]["charge_id"] == "ch_koji"


def test_piolo_is_never_shown_a_door_he_cannot_open(app_client):
    """No dead links: a nav entry or an in-page link he cannot open is worse
    than the carve-out itself — it reads as something broken."""
    import role_access as RA
    c = _as(app_client, "coo", "piolo")
    dead = {}
    for page in ("/dashboard/today", "/dashboard/sales", "/dashboard/scale",
                 "/dashboard/system", "/dashboard/landing",
                 "/dashboard/scale/travelling"):
        r = c.get(page)
        assert r.status_code == 200, page
        links = set(re.findall(r'href="(/dashboard[^"#?]*)"', r.data.decode()))
        bad = [l for l in sorted(links) if not RA.coo_permitted(l, "GET")[0]]
        if bad:
            dead[page] = bad
    assert not dead, dead


# ── the carve-out has to hold in the PAYLOAD, not just at the door ──────────

def test_the_snapshot_carries_no_per_person_pay_to_a_non_owner(app_client):
    """Found by the leak hunt: the snapshot is one object many surfaces read,
    and it carried per-closer commission totals, per-setter payouts WITH
    NAMES, per-deal commission detail and the roster's salaries — to a role
    the comp routes correctly refuse."""
    import json
    owner = json.loads(_as(app_client, "owner", "rydel")
                       .get("/dashboard/api/snapshot").data.decode())
    coo = _as(app_client, "coo", "piolo").get("/dashboard/api/snapshot").data.decode()
    if "error" in owner:
        pytest.skip("no snapshot on this machine")
    # #167: finance sees the snapshot UNTOUCHED; the scrub now guards only
    # non-finance roles (asserted through scrubbed_for directly)
    payload = json.loads(coo)
    assert "comp_scope" not in payload
    import role_access as RA
    other = RA.scrubbed_for("some_future_role", json.loads(coo))
    assert other.get("comp_scope") == "owner-only"


def test_a_scrubbed_payload_never_reads_as_nobody_was_paid():
    js = _read("dashboard", "static", "js", "dashboard.js")
    i = js.index("function renderCommissions")
    fn = js[i:i + 2000]
    assert "comp_scope === 'owner-only'" in fn
    assert fn.index("comp_scope") < fn.index("No commission data"), (
        "the owner-only branch must come BEFORE the empty-state branch, or "
        "Piolo is told nobody earned anything")


def test_finance_is_never_scrubbed_and_others_always_are():
    import role_access as RA
    snap = {"sales": {"per_closer": [{"name": "Kalin", "commission_total": 900.0}],
                      "payout": {"per_setter": []}},
            "costs": {"closer_commission": 900.0}}
    assert RA.scrubbed_for("coo", snap) is snap          # parity (#167)
    assert RA.scrubbed_for("owner", snap) is snap
    other = RA.scrubbed_for("ad_domain", snap)
    assert "closer_commission" not in json.dumps(other)


def test_the_owner_sees_the_payload_untouched():
    import role_access as RA
    snap = {"costs": {"closer_commission": 900.0}}
    assert RA.scrubbed_for("owner", snap) is snap


def test_us_first_tracker_dates_are_not_silently_dropped():
    """Caught on live data: the tracker writes 9/23/2026 meaning September.
    Read day-first it raises on month 23 — and the exception was swallowed,
    so thirteen close rows (Koji's among them) vanished while the row count
    still looked healthy."""
    import close_detect as C
    assert C._date("9/23/2026") == "2026-09-23"
    assert C._date("7/16/2026") == "2026-07-16"
    assert C._date("2026-09-23") == "2026-09-23"
    assert C._date("23/09/2026") == "2026-09-23"      # unambiguous day-first
    assert C._date("") is None and C._date("nonsense") is None


def test_a_matched_payment_does_not_become_a_second_close(monkeypatch):
    """A payment names a CLIENT; a close is keyed by the PERSON who signed.
    Without the bridge, Grappino's payment reads as a close beside Harman's."""
    kv_store._MEM.clear()
    import close_detect as C
    from helpers import today_sydney
    monkeypatch.setattr(C, "_client_to_person",
                        lambda: {"grappino ristorante": "Harman singh"})
    monkeypatch.setattr("unmatched_payments.matched_without_close", lambda: [
        {"client": "Grappino Ristorante", "payer": "Harman Singh",
         "charge_id": "ch_x", "amount": 3355.0, "date": str(today_sydney())}])
    monkeypatch.setattr(C, "_from_tracker", lambda: [])
    monkeypatch.setattr(C, "_from_stage_recorder", lambda: [])
    monkeypatch.setattr(C, "_from_ghl", lambda: [{
        "person": "Harman singh", "close_date": str(today_sydney()),
        "source": "ghl stage", "provenance": "stage",
        "evidence": {"opp_id": "o1"}, "email": None}])
    res = C.scan()
    assert len(res["entries"]) == 1, [e["person"] for e in res["entries"]]
    assert res["entries"][0]["state"] == "CONFIRMED"


def test_a_sentence_is_never_learned_as_a_client_name():
    """Found in production: the alias store held somebody's whole sentence
    ("resigning with us same price, Bluebells as well, …") as a client name,
    learned through the conversational path."""
    import stripe_reconcile as sr
    kv_store._MEM.clear()
    assert sr.learn_alias("Sanatani Rombola", "Pompoko Ramen") is True
    assert sr.learn_alias("walkway", "resigning with us same price, Bluebells "
                          "as well, Panini is resigning at 2k per month") is False
    assert "walkway" not in sr._aliases()
    ok, why = sr.alias_looks_like_a_name("a" * 80)
    assert not ok and "sentence" in why


def test_a_non_owner_turn_never_gets_owner_scope_memory(monkeypatch):
    """Found LIVE: asked "what's the csm roi status", Piolo got a silent
    fall-through from the CSM handler — which handed the question to the
    MODEL, which answered from remembered context, cost range and all.
    Silence is not confidentiality when something else is listening."""
    import memory
    facts = [
        {"id": 1, "category": "context", "fact": "The CSM hire is Miguel; "
         "the restructure offsets his comp against the director line.",
         "last_referenced_at": None},
        {"id": 2, "category": "context", "fact": "Kalin's commission is $750 "
         "on a Growth Pro close.", "last_referenced_at": None},
        {"id": 3, "category": "context", "fact": "Rydel prefers the numbers "
         "before the narrative.", "last_referenced_at": None},
    ]
    monkeypatch.setattr("db.db_configured", lambda: True)
    monkeypatch.setattr("db.active_facts", lambda limit=60: facts)
    monkeypatch.setattr("db.search_messages", lambda *a, **k: [])
    monkeypatch.setattr("memory_maintenance.search_archived", lambda *a, **k: [])

    owner_block = memory.build_recall_context("anything", owner=True)["block"]
    coo_block = memory.build_recall_context("anything", owner=False)["block"]
    assert "Miguel" in owner_block and "Kalin" in owner_block
    assert "Miguel" not in coo_block and "Kalin" not in coo_block
    assert "before the narrative" in coo_block, "ordinary context still flows"


def test_both_chat_paths_pass_the_parity_flag():
    """#167: recall passes is_finance() — no fact withheld from his channel."""
    src = _code_only(_read("dashboard", "routes.py"))
    n = src.count("build_recall_context(")
    assert n >= 2
    assert src.count("owner=is_finance()") >= n
    # true_owner=is_owner() (the CSM template's strict flag) is legitimate;
    # a RECALL call carrying is_owner is not
    assert "owner=is_owner()" not in src.replace("true_owner=is_owner()", "")


def test_a_payment_date_never_overrides_a_close_date(monkeypatch):
    """Caught live: William Cooney's close moved from 11 Sep to 1 Sep because
    an earlier instalment landed then and the merge took the earliest date it
    had seen. A payment proves the deal exists, not the day it was signed."""
    kv_store._MEM.clear()
    import close_detect as C
    monkeypatch.setattr(C, "_from_tracker", lambda: [])
    monkeypatch.setattr(C, "_from_stage_recorder", lambda: [])
    monkeypatch.setattr(C, "_from_ghl", lambda: [{
        "person": "William Cooney", "close_date": "2026-09-11",
        "source": "ghl stage", "provenance": "stage",
        "evidence": {"opp_id": "o1"}, "email": None}])
    monkeypatch.setattr(C, "_from_payments", lambda: [{
        "person": "William Cooney", "close_date": "2026-09-01",
        "source": "payment", "provenance": "payment matched",
        "evidence": {"charge_ids": ["ch_1"]}, "email": None}])
    e = C.scan(days=90)["entries"][0]
    assert e["close_date"] == "2026-09-11"
    assert e["dated_by"] == "ghl stage"
    assert e["state"] == "CONFIRMED"


def test_the_panel_publishes_the_real_count_not_the_slice(app_client, monkeypatch):
    """Scan 2 caught this on the live page: the panel shows five rows and was
    publishing the length of the SLICE, so the page said 5 while the engine
    said 10. A page that disagrees with its own engine is the defect scan 2
    exists to find — including when the page is mine."""
    import close_detect
    entries = [{"key": f"k{i}", "person": f"Venue {i}", "close_date": "2026-09-01",
                "state": "DETECTED", "sources": [{"source": "ghl stage",
                                                  "provenance": "stage"}],
                "missing": ["contract value"], "evidence": {}} for i in range(10)]
    monkeypatch.setattr(close_detect, "latest",
                        lambda: {"entries": entries, "at": "now"})
    html = _as(app_client, "owner", "rydel").get("/dashboard/today").data.decode()
    m = re.search(r'data-metric="closes_detected"[^>]*data-value="(\d+)"', html)
    assert m and m.group(1) == "10", html[:0] or (m.group(1) if m else "absent")
    assert "showing" in html and "most recent" in html
