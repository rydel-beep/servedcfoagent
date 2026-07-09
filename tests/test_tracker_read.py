"""
tests/test_tracker_read.py
--------------------------
READ-BEFORE-ASSERT: field states come from a deterministic read, never inference. The incident is
the acceptance test — the three cash cells are FILLED and must be reported as such; a 'blank' claim
that's contradicted triggers resync → re-read → correct + root cause + incident.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kv_store, tracker_read as tr, incident_log

# Header + rows mirroring the real Lead-to-Cash Tracker columns (business=7, close=27, contract=28,
# cash=32, outcome=16, offer somewhere). Minimal but positionally faithful for the read.
def _fixture():
    hdr = [""] * 33
    hdr[7] = "Business Name"; hdr[16] = "Call Outcome"; hdr[27] = "Close Date"
    hdr[28] = "Contract Value"; hdr[32] = "Cash Collected"; hdr[10] = "Offer Sold"
    def row(biz, close, contract, cash, offer="Scale Engine", outcome="Won"):
        r = [""] * 33
        r[7] = biz; r[10] = offer; r[16] = outcome; r[27] = close; r[28] = contract; r[32] = cash
        return r
    return [hdr,
            row("Hung's Chinese", "7/8/2026", "$15,100", "$8,305.00"),
            row("Lost Sheep Cafe", "7/7/2026", "$14,500", "$15,950.00"),
            row("Akuna Cafe", "6/30/2026", "$18,300", "$1,650.00", offer="Growth Pro"),
            row("Cafe Mambo", "6/1/2026", "$9,000", "")]   # a genuinely blank one


def _patch(monkeypatch):
    monkeypatch.setattr(tr, "_rows", _fixture)
    monkeypatch.setattr(tr, "sync_state", lambda key=tr._KEY: {"last_sync_at": None, "age_seconds": 0})
    monkeypatch.setattr(tr, "resync", lambda key=tr._KEY: {"last_sync_at": None, "age_seconds": 0})
    tr._names_cache.update(ts=0, names=[])
    kv_store._MEM.clear()


def test_reads_cells_verbatim(monkeypatch):
    _patch(monkeypatch)
    r = tr.read_client_row("Hung", fresh=False)
    assert r["found"] and r["cash_collected"] == "$8,305.00" and r["cash_is_blank"] is False
    assert tr.read_client_row("Lost Sheep", fresh=False)["cash_collected"] == "$15,950.00"
    # a genuinely blank cell IS reported blank (truth, not inference)
    assert tr.read_client_row("Mambo", fresh=False)["cash_is_blank"] is True


def test_client_matching_precise(monkeypatch):
    _patch(monkeypatch)
    assert tr._clients_in_text("cash collected for Lost Sheep Cafe") == ["Lost Sheep Cafe"]
    assert set(tr._clients_in_text("is cash blank for Hung and Akuna")) == {"Hung's Chinese", "Akuna Cafe"}
    assert tr._clients_in_text("that's wrong, it's not blank") == []      # no 'That Bakery' false hit
    assert tr._clients_in_text("cafe") == []                             # common word alone → nothing


def test_client_context_never_says_blank_for_filled(monkeypatch):
    _patch(monkeypatch)
    ctx = tr.client_context("is cash collected blank for Hung's Chinese?")
    assert "$8,305.00" in ctx and "VERIFIED TRACKER ROWS" in ctx and "never infer" in ctx


def test_self_check_corrects_and_logs_incident(monkeypatch):
    _patch(monkeypatch)
    reply, handled = tr.handle_self_check(
        "that's wrong, it's not blank I just checked",
        thread="cash collected is blank for Hung's and Lost Sheep and Akuna")
    assert handled
    assert "You're right" in reply and "$8,305.00" in reply and "$15,950.00" in reply
    # incident logged for the read-before-assert gap
    assert incident_log.recent(1) and "blank" in incident_log.recent(1)[0]["claimed"]


def test_self_check_confirms_when_right(monkeypatch):
    _patch(monkeypatch)
    # thread did NOT claim blank → re-read stands by the truth, no false "you're right", no incident
    reply, handled = tr.handle_self_check("are you sure that's right?",
                                          thread="Lost Sheep cash collected is $15,950")
    assert handled and "$15,950.00" in reply and "You're right — I asserted" not in reply
    assert incident_log.recent(1) == []


def test_incident_copy_block(monkeypatch):
    _patch(monkeypatch)
    incident_log.log_incident(asked="cash for X", claimed="blank", truth="X: $1", trace="re-read",
                              suspected="no read path")
    reply, handled = incident_log.handle_incident_query("show me the incident")
    assert handled and "EDITH INCIDENT" in reply and "cannot self-patch" in reply.lower() or "can't" in reply.lower()
