"""Email engine Phase A: the three gates + the pinned location + send impossibility."""
import pytest

import email_pipeline as EP
import ghl_email as GE

G = {"wins": [{"source": "meta", "id": "w1", "title": "The Raama — Google multi-action",
               "body": "Raama Indian did $26,922 tracked revenue from $2,444 in ad spend. 11x return."}],
     "voice_examples": [{"title": "v", "copy": "Your best table is waiting."}],
     "content_piece": None, "lead_magnet": {"download_url": "https://servedmarketing.com.au/guide"}}


def test_proof_gate_passes_traceable():
    r = EP.proof_gate("Raama Indian did $26,922 from $2,444 — an 11x return.", G)
    assert r["ok"], r["failures"]


def test_proof_gate_fails_invented_win():
    r = EP.proof_gate("Nonna's Kitchen saw an 11x blowout month with $88,000 revenue.", G)
    assert not r["ok"]
    joined = " ".join(r["failures"])
    assert "$88,000" in joined or "Nonna" in joined


def test_link_gate_fails_dead_and_wrong_source(monkeypatch):
    class R: status_code = 404
    monkeypatch.setattr(EP._rq, "get", lambda *a, **k: R())
    r = EP.link_gate('<a href="https://servedmarketing.com.au/nope">x</a>', G)
    assert not r["ok"] and "dead link" in r["failures"][0]
    class R2: status_code = 200
    monkeypatch.setattr(EP._rq, "get", lambda *a, **k: R2())
    r2 = EP.link_gate('<a href="https://www.canva.com/design/abc">asset</a>', G)
    assert not r2["ok"] and "wrong-source" in " ".join(r2["failures"])


def test_relation_gate_orphaned_ytpush_and_winback_off():
    assert not EP.relation_gate("content-linked", {"content_piece": None})["ok"]
    r = EP.relation_gate("winback", {})
    assert not r["ok"] and "doctrine" in r["failures"][0]


def test_location_pinned_by_construction():
    with pytest.raises(GE.LocationViolation):
        GE._request("GET", "/contacts/", params={"locationId": "SOMEONE_ELSES_LOCATION"})
    with pytest.raises(GE.LocationViolation):
        GE._request("POST", "/emails/builder", json_body={"locationId": "clientX"}, location_id="clientX")


def test_send_structurally_impossible_without_chain():
    out = GE.send_email({"anything": 1}, chain_token=None)
    assert "_refused" in out
    out2 = GE.send_email({"anything": 1}, chain_token="forged")
    assert "_refused" in out2                     # verify_chain_token always False in v1


def test_generation_is_weekly_only():
    """ONE WRITER PER LANE: content-linked + winback generation are dead-coded."""
    for t in ("content-linked", "winback"):
        r = EP.generate_draft(t)
        assert not r["ok"] and "ingest" in r["reason"].lower(), t
    assert EP.GENERATABLE == ("weekly",)


def test_pd_status_map_and_history_flags():
    assert EP.PD_STATUS_MAP["rydel review"] == "READY_FOR_REVIEW"
    assert EP.PD_STATUS_MAP["loaded in ghl"] == "STAGED_IN_GHL"
    assert EP.PD_STATUS_MAP["sent"] == "SENT"


def test_cadence_never_fires_outside_window(monkeypatch):
    import helpers, datetime as dt
    class FakeNow(dt.datetime):
        pass
    # Tuesday 09:05 Sydney → no fire
    monkeypatch.setattr(EP, "now_sydney",
                        lambda: dt.datetime(2026, 8, 4, 9, 5, tzinfo=dt.timezone.utc))
    assert EP.cadence_tick() is None


def test_chain_token_single_use_and_binding(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "get", lambda k: store.get(k))
    t = EP.mint_chain_token(7, 3)
    assert not EP.verify_chain_token(t, draft_id=7, count=99)   # wrong count consumed it
    t2 = EP.mint_chain_token(7, 3)
    assert EP.verify_chain_token(t2, draft_id=7, count=3)
    assert not EP.verify_chain_token(t2, draft_id=7, count=3)   # single-use
    assert not EP.verify_chain_token("forged", draft_id=7, count=3)


def test_send_requires_staged_and_chain(monkeypatch):
    monkeypatch.setattr(EP, "get_draft", lambda i: {"id": i, "status": "APPROVED",
                                                    "subject_options": ["x"], "type": "weekly",
                                                    "ghl_draft_id": None})
    r = EP.send_draft(1, 5, "any")
    assert not r["ok"] and "STAGED_IN_GHL" in r["reason"]
