"""tests/test_resolution.py — the resolution engine (FULL_STACK_INTEGRITY_REPORT):
auto-fix log, P1 date-candidate cards (derive, never invent), H1 routing, the
hard no-writes line, EDITH handlers."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolution


def test_autofix_log_appends_and_caps():
    import kv_store
    kv_store.put("integrity:autofix_log", [])
    for i in range(205):
        resolution.log_autofix("A1 normalization", f"detail {i}")
    lg = kv_store.get("integrity:autofix_log")
    assert len(lg) == 200 and lg[-1]["detail"] == "detail 204"
    assert lg[-1]["rule"] == "A1 normalization" and lg[-1]["ts"]


def test_propose_fixes_derives_never_invents(monkeypatch):
    import close_integrity as CI
    import kv_store
    monkeypatch.setattr(CI, "_tracker_won_rows", lambda: [
        {"name": "Vipin", "email": "vipin@x.com", "close_date": None, "close_raw": "",
         "input_date": None, "contract": 12000.0, "cash": 0},
        {"name": "No Candidate", "email": "none@x.com", "close_date": None, "close_raw": "",
         "input_date": None, "contract": 9000.0, "cash": 0},
    ])
    import datetime as dt
    monkeypatch.setattr(resolution, "_ghl_won_dates",
                        lambda: {"vipinxcom": {"date": dt.date(2026, 7, 14), "via": "email"}})
    monkeypatch.setattr(resolution, "_stripe_first_payment_dates", lambda days=365: {})
    monkeypatch.setattr("db.db_configured", lambda: False)   # skip P2 (no mirror)
    cards = resolution.propose_fixes()
    p1 = [c for c in cards if c["kind"] == "P1_close_date_candidate"]
    h1 = [c for c in cards if c["kind"] == "H1_no_candidate"]
    # Vipin gets a DERIVED candidate with its source named; the card only instructs
    assert len(p1) == 1 and p1[0]["name"] == "Vipin"
    assert p1[0]["candidates"][0]["date"] == "2026-07-14"
    assert "GHL" in p1[0]["candidates"][0]["source"]
    assert "never write" in p1[0]["instruction"]
    # no candidate anywhere → HUMAN-FIX, never an invented date
    assert len(h1) == 1 and h1[0]["name"] == "No Candidate"
    assert not h1[0].get("candidates")
    # persisted for the panel/EDITH
    assert kv_store.get("integrity:proposed_fixes")["cards"]


def test_clean_tracker_produces_no_cards(monkeypatch):
    import close_integrity as CI
    monkeypatch.setattr(CI, "_tracker_won_rows", lambda: [
        {"name": "Done", "email": "d@x.com", "close_date": __import__("datetime").date(2026, 7, 1),
         "close_raw": "1/7", "input_date": None, "contract": 1.0, "cash": 1.0}])
    assert resolution.propose_fixes() == []   # A5: nothing blank → no cards generated


def test_edith_handlers(monkeypatch):
    import kv_store
    kv_store.put("integrity:proposed_fixes", {"as_of": "2026-08-06", "cards": [
        {"kind": "P1_close_date_candidate", "name": "Vipin", "field": "Close Date",
         "contract": 12000.0, "candidates": [{"date": "2026-07-14", "source": "GHL stage move"}],
         "instruction": "type it into the tracker", "id": "pfix:x"},
        {"kind": "H1_no_candidate", "name": "Ghost", "field": "Close Date",
         "instruction": "needs the human", "id": "hfix:y"}]})
    r, h = resolution.handle_proposed_fixes_command("any proposed fixes?")
    assert h and "Vipin" in r and "2026-07-14" in r and "Piolo" in r
    kv_store.put("integrity:autofix_log",
                 [{"rule": "A3 alias learned", "detail": "x → y", "ts": "2026-08-06"}])
    r, h = resolution.handle_autofix_log_command("what did you auto-fix?")
    assert h and "A3" in r
    assert resolution.handle_proposed_fixes_command("hello")[1] is False
    assert resolution.handle_autofix_log_command("hello")[1] is False


def test_no_write_paths_exist():
    """THE HARD LINE: resolution never writes to source systems — no gspread/update
    calls, no GHL POSTs, no Stripe mutations anywhere in the module."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "resolution.py")).read()
    for needle in ("update_cell", "batch_update", "append_row", "requests.post",
                   "stripe.Charge.modify", ".update("):
        assert needle not in src
