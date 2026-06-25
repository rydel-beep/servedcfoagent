"""
tests/test_sheet_mirror.py
--------------------------
Sheet-mirror: fetch URL (name vs gid), hashing, lookup mapping, the resync / sources
voice commands, and graceful degradation when Postgres is absent. (Live DB sync/read is
verified on the deployed app — the Railway-internal DB isn't reachable from local tests.)
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sheet_mirror


class _Resp:
    def __init__(self, text, status=200): self.text, self.status_code = text, status


def test_mirrored_tabs_focused_scope():
    keys = set(sheet_mirror.MIRRORED_TABS)
    assert keys == {"ltc_tracker", "team_scorecard", "setter_payout_log", "setter_deep_dive",
                    "health", "recognized", "salary"}
    # Health mirrors BY GID (its name points at the wrong tab); others by name.
    assert sheet_mirror.MIRRORED_TABS["health"]["gid"] == 1407663952
    assert "gid" not in sheet_mirror.MIRRORED_TABS["ltc_tracker"]
    assert sheet_mirror.MIRRORED_TABS["salary"]["tab"] == "SALARY"


def test_live_fetch_name_vs_gid(monkeypatch):
    seen = {}
    def fake_get(url, timeout=None):
        seen["url"] = url
        return _Resp("a,b\r\nc,d\r\n")
    monkeypatch.setattr(sheet_mirror.requests, "get", fake_get)
    rows = sheet_mirror._live_fetch("BOOK", "My Tab")
    assert rows == [["a", "b"], ["c", "d"]] and "gviz" in seen["url"] and "My%20Tab" in seen["url"]
    sheet_mirror._live_fetch("BOOK", "ignored", gid=999)
    assert "export?format=csv&gid=999" in seen["url"]


def test_hash_deterministic_and_sensitive():
    a = [["1", "x"], ["2", "y"]]
    assert sheet_mirror._content_hash(a) == sheet_mirror._content_hash([["1", "x"], ["2", "y"]])
    assert sheet_mirror._content_hash(a) != sheet_mirror._content_hash([["1", "x"], ["2", "z"]])


def test_lookup_maps(monkeypatch):
    # read_by_name/gid resolve to the right key, then read_tab (no DB → None).
    monkeypatch.setattr(sheet_mirror.db, "db_configured", lambda: False)
    assert sheet_mirror.read_by_name("Lead-to-Cash Tracker") is None  # mapped, but no DB
    assert sheet_mirror.read_by_name("Nonexistent Tab") is None
    assert sheet_mirror.read_by_gid(1407663952) is None
    assert sheet_mirror._NAME_TO_KEY["SETTER PAYOUT LOG"] == "setter_payout_log"
    assert sheet_mirror._GID_TO_KEY[1407663952] == "health"


def test_resync_command_detection():
    for t in ["resync", "sync now", "pull the latest", "refresh your data", "re-sync the tracker"]:
        assert sheet_mirror._RESYNC_RE.search(t), t
    for t in ["what's my cash", "how are sales", "set the target to 3"]:
        assert not sheet_mirror._RESYNC_RE.search(t), t


def test_sources_query_detection():
    for t in ["what's plugged into your system", "what data are you reading",
              "is your data current", "how fresh is your data"]:
        assert sheet_mirror._SOURCES_RE.search(t), t
    assert not sheet_mirror._SOURCES_RE.search("what's our runway")


def test_resync_command_graceful_no_db(monkeypatch):
    monkeypatch.setattr(sheet_mirror.db, "db_configured", lambda: False)
    reply, handled = sheet_mirror.handle_resync_command("sync now", rebuild_snapshot=False)
    assert handled and "Synced" in reply  # degrades, still answers
    assert sheet_mirror.handle_resync_command("what's my cash?")[1] is False


def test_sources_query_graceful_no_db(monkeypatch):
    monkeypatch.setattr(sheet_mirror.db, "db_configured", lambda: False)
    reply, handled = sheet_mirror.handle_sources_query("what's plugged into your system?")
    assert handled and ("isn't reporting" in reply or "reading" in reply)
