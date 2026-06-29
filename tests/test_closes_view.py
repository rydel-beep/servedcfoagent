"""
tests/test_closes_view.py
-------------------------
Deterministic close recall (the anti-fabrication fix): recent closes + biggest deal read
VERBATIM from the mirror, never invented. Command detection routes factual close questions
away from the model. Mirror read is monkeypatched.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import closes_view

# Header + won/lost rows. Col 16 = setter Call Outcome, col 23 = closer (the "won" one).
_HDR = [""]*30
_HDR[3]="Lead Name"; _HDR[7]="Business Name"; _HDR[16]="Call Outcome"; _HDR[23]="Call Outcome"
_HDR[26]="Offer Sold"; _HDR[27]="Close Date"; _HDR[28]="Contract Value"
def _row(name, biz, close, contract, offer="Scale Engine", outcome="won"):
    r=[""]*30
    r[3]=name; r[7]=biz; r[16]="SET"; r[23]=outcome; r[26]=offer; r[27]=close; r[28]=str(contract)
    return r
_ROWS=[_HDR,
    _row("Lucas Reid","The Cally Hotel","6/24/2026",18300,"Growth Pro"),
    _row("Deepa Ghimire","Lovefish Barangaroo","6/24/2026",14500),
    _row("Old","Small Cafe","6/01/2026",9000),
    _row("Lost Guy","Nope Diner","6/20/2026",99999,outcome="lost"),  # not won → excluded
]

def _mock(monkeypatch, rows=_ROWS):
    import sheet_mirror
    monkeypatch.setattr(sheet_mirror, "read_by_name", lambda n: rows if "Lead-to-Cash" in n else None)


def test_recent_closes_verbatim_newest_first(monkeypatch):
    _mock(monkeypatch)
    r = closes_view.recent_closes(limit=5)
    assert r["total"] == 3                          # the lost deal excluded
    names = [c["business"] for c in r["closes"]]
    assert names[:2] == ["The Cally Hotel", "Lovefish Barangaroo"] and "Nope Diner" not in names


def test_biggest_deal_from_real_values(monkeypatch):
    _mock(monkeypatch)
    b = closes_view.biggest_deal()
    assert b["business"] == "The Cally Hotel" and b["contract"] == 18300.0   # not the 99999 lost row


def test_command_detection_closes_and_biggest(monkeypatch):
    _mock(monkeypatch)
    reply, handled = closes_view.handle_closes_command("what are the last few closes?")
    assert handled and "Last few closes:" in reply and "The Cally Hotel" in reply
    assert "Bondi" not in reply                       # only real data
    r2, h2 = closes_view.handle_closes_command("what's our biggest deal?")
    assert h2 and "Biggest deal" in r2 and "The Cally Hotel" in r2
    assert closes_view.handle_closes_command("how's the weather")[1] is False


def test_biggest_deal_defers_when_no_data(monkeypatch):
    _mock(monkeypatch, rows=[_HDR])                  # header only, no deals
    reply, handled = closes_view.handle_closes_command("biggest deal")
    assert handled and ("don't have" in reply or "check" in reply)   # defers, never invents
