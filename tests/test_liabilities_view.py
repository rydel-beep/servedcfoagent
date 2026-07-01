import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import liabilities_view as lv


def test_amex_command(monkeypatch):
    import snapshot
    monkeypatch.setattr(snapshot, "load_persisted",
                        lambda: {"xero": {"amex_owing": {"owing": 18153.0, "as_of": "2026-07-01"}}})
    reply, handled = lv.handle_amex_command("what do we owe on amex?")
    assert handled and "Amex owing: $18,153" in reply and "separate from cash" in reply
    assert lv.handle_amex_command("how's the weather")[1] is False


def test_amex_clear(monkeypatch):
    import snapshot
    monkeypatch.setattr(snapshot, "load_persisted", lambda: {"xero": {"amex_owing": {"owing": 0.0, "as_of": "x"}}})
    assert "clear" in lv.handle_amex_command("amex balance")[0].lower()
