"""tests/test_gap_window_hold.py — #170: one late tracker row must not close
the gap behind it.

Witnessed 29 Sep: the gap window starts "the day after the last tracker
close". Koji's row (23 Sep) moved it to 24 Sep; Orlando (9 Sep), Harman and
William (11 Sep) — still with no tracker close row — fell out of the gap
ledger, lost their contracts and charges, and LTGP:CAC read 0.97× MTD.
"""
from __future__ import annotations

import contextlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store
import gap_reconcile as G

HEADER = ["Input Date", "Lead Name", "Business Name", "Close Date"]
ROWS = [HEADER,
        ["2026-08-01", "Old Client", "Old Venue", "2026-08-20"],
        ["2026-09-22", "Koji", "Pompoko Ramen", "2026-09-23"],       # the late row
        ["2026-09-06", "Harman singh", "Grappino", ""],              # never recorded
        ["2026-08-27", "William Cooney", "Phoenix hotel", ""]]

GHL = [{"contact_name": "Orlando Rinaldi", "opp_name": "Food Corp", "close_date": "2026-09-09"},
       {"contact_name": "Harman singh", "opp_name": "Grappino", "close_date": "2026-09-11"},
       {"contact_name": "William Cooney", "opp_name": "Phoenix hotel", "close_date": "2026-09-11"},
       {"contact_name": "Koji", "opp_name": "Pompoko", "close_date": "2026-09-23"},
       {"contact_name": "Scott Cho", "opp_name": "Amoroso", "close_date": "2026-09-26"}]


class _Conn:
    def execute(self, *a, **k):
        class R:
            def fetchall(self_inner):
                days = {}
                for g in GHL:
                    days[g["close_date"]] = days.get(g["close_date"], 0) + 1
                return [{"d": d, "n": n} for d, n in days.items()]
        return R()


def _wire(monkeypatch, journal_starts):
    kv_store.delete(G._KV_STATE)
    kv_store.put(G._KV_JOURNAL, [{"at": "2026-09-20", "event": "gap detected",
                                  "detail": f"{s} → 2026-09-20 (last tracker close x)"}
                                 for s in journal_starts])
    monkeypatch.setattr(G, "_tracker_rows", lambda: ROWS)
    monkeypatch.setattr(G.db, "get_conn", lambda: contextlib.nullcontext(_Conn()))
    monkeypatch.setattr(G, "_ghl_closed_in_window",
                        lambda w0, w1: [g for g in GHL if w0 <= g["close_date"] <= w1])


def test_a_late_row_does_not_orphan_earlier_unrecorded_closes(monkeypatch):
    _wire(monkeypatch, ["2026-08-21"])
    st = G.detect_gap(force=True)
    assert st["gap"]["start"] == "2026-09-09"            # not 2026-09-24
    held = {h["person"] for h in st["held_open_by"]}
    assert held == {"Orlando Rinaldi", "Harman singh", "William Cooney"}
    assert "Koji" not in held                              # recorded → does not hold


def test_the_window_advances_once_the_tracker_records_them(monkeypatch):
    _wire(monkeypatch, ["2026-08-21"])
    rows = [HEADER, ["2026-08-01", "Old Client", "Old Venue", "2026-08-20"],
            ["2026-09-22", "Koji", "Pompoko Ramen", "2026-09-23"],
            ["2026-09-06", "Harman singh", "Grappino", "2026-09-11"],
            ["2026-08-27", "William Cooney", "Phoenix hotel", "2026-09-11"],
            ["2026-05-19", "Orlando Rinaldi", "Food Corp", "2026-09-09"]]
    monkeypatch.setattr(G, "_tracker_rows", lambda: rows)
    st = G.detect_gap(force=True)
    assert st["gap"]["start"] == "2026-09-24"
    assert "held_open_by" not in st


def test_no_episode_memory_keeps_the_old_rule(monkeypatch):
    _wire(monkeypatch, [])
    st = G.detect_gap(force=True)
    assert st["gap"]["start"] == "2026-09-24"


def test_a_same_day_cache_from_the_old_rule_is_recomputed(monkeypatch):
    _wire(monkeypatch, ["2026-08-21"])
    from helpers import today_sydney
    kv_store.put(G._KV_STATE, {"ok": True, "detected_on": str(today_sydney()),
                               "gap": {"start": "2026-09-24", "end": "x"}})   # no rule stamp
    st = G.detect_gap()
    assert st["gap"]["start"] == "2026-09-09" and st["rule"] == G._GAP_RULE


def test_a_raw_tracker_money_cell_becomes_a_number():
    """#170 incident: '$27,900' reached the tiles as text and broke them."""
    assert G._money("$27,900") == 27900.0 and G._money("18300") == 18300.0
    assert G._money(18300) == 18300.0
    assert G._money("") is None and G._money("TBC") is None and G._money(None) is None
