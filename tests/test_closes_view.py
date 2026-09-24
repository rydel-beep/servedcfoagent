"""
tests/test_closes_view.py
-------------------------
Deterministic close recall (the anti-fabrication fix), now on the ONE CLOSE
REGISTER (#164): recent closes, biggest deal and windowed counts read the
register — the same population every surface counts — never a private
tracker parse, never the model's imagination. The register is seeded in kv.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import closes_view
import close_register as CR
import kv_store


def _entry(person, client, close_date, contract, offer="Scale Engine",
           status="confirmed", cash=None, input_date=None, missing=None):
    key = person.lower().replace(" ", " ")
    return {
        "id": f"cr:{key}", "key": key, "person": person, "client": client,
        "email": None, "contact_id": None, "opp_id": "opp1",
        "close_date": close_date, "dated_by": "tracker",
        "sources": [{"source": "tracker", "provenance": "tracker close row",
                     "close_date": close_date}],
        "corroboration_pending": [], "status": status,
        "contract": {"value": contract, "source": "tracker contract cell",
                     "signed": True},
        "cash": {"amount": cash, "charge_ids": [], "source":
                 ("matched Stripe charges" if cash is not None else
                  "no matched Stripe/Xero payment on file"),
                 "tracker_cell": None},
        "closer": None, "closer_ghl_owner_id": None, "setter": None,
        "closer_commission_cell": None, "setter_commission_cell": None,
        "offer": offer,
        "lead": {"input_date": input_date, "lead_source": None,
                 "tracker_row": True},
        "attribution": {"tier": "unattributed",
                        "why": "lead is on the tracker but carries no ad stamp",
                        "creative_key": None, "creative": None},
        "clocks": {"activity": close_date, "cohort": input_date,
                   "cohort_why": None if input_date else "no lead arrival date"},
        "evidence": {"opp_id": "opp1"},
        "chips": {"tracker_row": True, "ghl_opp": True, "stripe": bool(cash),
                  "form": False},
        "missing": missing or [],
    }


def _seed(entries):
    kv_store.put(CR.K_REGISTER, {
        "at": "2026-06-25T09:00:00+10:00", "window_days": 3650,
        "entries": entries,
        "confirmed": sum(1 for e in entries if e["status"] == "confirmed"),
        "proposed": sum(1 for e in entries
                        if e["status"] == "proposed-needs-evidence")})


ENTRIES = [
    _entry("Lucas Reid", "The Cally Hotel", "2026-06-24", 18300.0, "Growth Pro"),
    _entry("Deepa Ghimire", "Lovefish Barangaroo", "2026-06-24", 14500.0),
    _entry("Old Deal", "Small Cafe", "2026-06-01", 9000.0),
    _entry("Maybe Guy", "Nope Diner", "2026-06-20", 99999.0,
           status="proposed-needs-evidence"),   # proposed → excluded from recall
]


def test_recent_closes_verbatim_newest_first():
    _seed(ENTRIES)
    r = closes_view.recent_closes(limit=5)
    assert r["total"] == 3                          # the proposed deal excluded
    names = [c["business"] for c in r["closes"]]
    assert names[:2] == ["The Cally Hotel", "Lovefish Barangaroo"]
    assert "Nope Diner" not in names


def test_biggest_deal_from_real_values():
    _seed(ENTRIES)
    b = closes_view.biggest_deal()
    assert b["business"] == "The Cally Hotel" and b["contract"] == 18300.0


def test_command_detection_closes_and_biggest():
    _seed(ENTRIES)
    reply, handled = closes_view.handle_closes_command("what are the last few closes?")
    assert handled and "Last few closes:" in reply and "The Cally Hotel" in reply
    assert "Bondi" not in reply                       # only real data
    r2, h2 = closes_view.handle_closes_command("what's our biggest deal?")
    assert h2 and "Biggest deal" in r2 and "The Cally Hotel" in r2
    assert closes_view.handle_closes_command("how's the weather")[1] is False


def test_biggest_deal_defers_when_no_data():
    _seed([])
    reply, handled = closes_view.handle_closes_command("biggest deal")
    assert handled and ("don't have" in reply or "rebuilding" in reply)


def test_this_month_is_honoured_not_discarded(monkeypatch):
    """'What have we closed this month' answered ALL-TIME before #164 —
    the phrase was discarded. Now the window binds and the clock is named."""
    from helpers import today_sydney
    t = today_sydney()
    this_month = str(t.replace(day=1))
    entries = ENTRIES + [_entry("New Person", "NEW VENUE", this_month, 5000.0)]
    _seed(entries)
    reply, handled = closes_view.handle_closes_command("what have we closed this month")
    assert handled
    assert "NEW VENUE" in reply
    assert "The Cally Hotel" not in reply             # June — outside the window
    assert "activity clock" in reply                   # the clock is stated


def test_count_command_reads_register():
    _seed(ENTRIES)
    reply, handled = closes_view.handle_close_count_command("how many closes in June")
    assert handled and reply.startswith("3 closes in")
    assert "register" in reply.lower()


def test_no_private_tracker_reader_left():
    """closes_view must never grow its own tracker parse again."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "closes_view.py")).read()
    assert "sheet_mirror" not in src
    assert "_fetch_tab" not in src
    assert "close_register" in src
