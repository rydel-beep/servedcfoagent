"""
tests/test_leads_view.py
------------------------
Leads visibility: most-recently-ENTERED lead from the mirrored tracker (newest by Input
Date + Time), command detection, and PII-safety (Email/Phone never returned). The mirror
read is monkeypatched; live behaviour verified on the deployed app.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import leads_view

# Header (row 0) + 3 leads; Email/Phone present in the source but must NOT surface.
_HDR = ["1 · LEAD INTAKE Lead ID", "Input Date", "Input Time", "Lead Name", "Email", "Phone", "Lead Source", "Business Name"]
_ROWS = [
    _HDR,
    ["", "2026-06-29", "6:37 AM", "The Takeout Co.", "secret@gmail.com", "+61400000000", "Facebook", "The Takeout Co"],
    ["", "2026-06-29", "2:29 AM", "Maude Dixon", "maude@x.com", "+61411111111", "Facebook", "Maude"],
    ["", "2026-06-28", "9:00 PM", "Old Lead", "old@x.com", "+61422222222", "Instagram", "Old Biz"],
]

def _mock(monkeypatch, rows=_ROWS):
    import sheet_mirror
    monkeypatch.setattr(sheet_mirror, "read_by_name", lambda n: rows if "Lead-to-Cash" in n else None)


def test_latest_lead_is_newest_by_date_then_time(monkeypatch):
    _mock(monkeypatch)
    ll = leads_view.latest_lead()
    assert ll["name"] == "The Takeout Co." and ll["date"] == "2026-06-29" and ll["time"] == "6:37 AM"
    # same-day ordering: 6:37 AM beats 2:29 AM
    r = leads_view.recent_leads(limit=3)
    assert [x["name"] for x in r["leads"]] == ["The Takeout Co.", "Maude Dixon", "Old Lead"]
    assert r["total"] == 3


def test_pii_never_returned(monkeypatch):
    _mock(monkeypatch)
    blob = str(leads_view.recent_leads(limit=5))
    assert "@" not in blob and "+6140" not in blob          # no email / phone leaks
    assert "secret@gmail.com" not in blob


def test_command_detection(monkeypatch):
    _mock(monkeypatch)
    reply, handled = leads_view.handle_leads_command("who's the latest lead?")
    assert handled and "Latest lead: The Takeout Co." in reply
    reply2, h2 = leads_view.handle_leads_command("show me recent leads")
    assert h2 and "Most recent leads:" in reply2 and "Maude Dixon" in reply2
    assert leads_view.handle_leads_command("what's our cash")[1] is False
    # distinct from a CLOSE question (must not hijack)
    assert leads_view.handle_leads_command("what are the last few closes")[1] is False


def test_degrades_when_no_data(monkeypatch):
    _mock(monkeypatch, rows=[])
    r = leads_view.recent_leads()
    assert r["leads"] == [] and r["degraded"]


def test_lead_count_by_input_date(monkeypatch):
    import datetime as dt
    _mock(monkeypatch)
    # fixture has 3 leads: 2026-06-29 x2, 2026-06-28 x1
    assert leads_view.count_leads(dt.date(2026,6,1), dt.date(2026,6,30))["count"] == 3
    assert leads_view.count_leads(dt.date(2026,6,29), dt.date(2026,6,29))["count"] == 2
    assert leads_view.count_leads(None, None)["count"] == 3   # all-time


def test_lead_count_command_deterministic(monkeypatch):
    _mock(monkeypatch)
    reply, handled = leads_view.handle_lead_count_command("how many leads in June 2026?")
    assert handled and reply.startswith("3 leads in June 2026") and "scorecard" in reply
    assert leads_view.handle_lead_count_command("how many leads total")[0].startswith("3 leads total")
    # a count question must NOT be caught by the display handler (different intent)
    assert leads_view.handle_leads_command("how many leads in June 2026?")[1] is False
    # non-count question ignored
    assert leads_view.handle_lead_count_command("what's the weather")[1] is False
