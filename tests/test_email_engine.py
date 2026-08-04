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
