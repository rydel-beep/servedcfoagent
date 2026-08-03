"""P3 automation-health registry: state evaluation, honest UNKNOWN, positive confirmation."""
import datetime as dt

import automations as AU
from helpers import now_sydney


def _iso(hours_ago):
    return (now_sydney() - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def _integ(job, ok=True, last_ok_h=1.0, detail="ran ok"):
    return {"job:" + job: {"ok": ok, "last_ok_at": _iso(last_ok_h) if last_ok_h is not None else None,
                           "detail": detail}}


def _wire_tl(monkeypatch, integrations, freshness=None):
    import timeline_adapter as TA
    monkeypatch.setattr(TA, "configured", lambda: True)
    monkeypatch.setattr(TA, "automation_status",
                        lambda: {"integrations": integrations, "freshness": freshness or {}})


def _quiet_edith(monkeypatch):
    monkeypatch.setattr(AU, "_edith_health", lambda: [])


def test_running_within_window(monkeypatch):
    _wire_tl(monkeypatch, _integ("daily_sync", ok=True, last_ok_h=5)); _quiet_edith(monkeypatch)
    row = next(r for r in AU.health()["automations"] if r["id"] == "tl:daily_sync")
    assert row["state"] == "RUNNING" and "5.0h ago" in row["detail"]


def test_stale_when_window_missed(monkeypatch):
    _wire_tl(monkeypatch, _integ("daily_sync", ok=True, last_ok_h=40)); _quiet_edith(monkeypatch)
    row = next(r for r in AU.health()["automations"] if r["id"] == "tl:daily_sync")
    assert row["state"] == "STALE" and "expected every 26h" in row["detail"]


def test_failing_with_error_detail(monkeypatch):
    _wire_tl(monkeypatch, _integ("relay_tick", ok=False, last_ok_h=1, detail="error: boom"))
    _quiet_edith(monkeypatch)
    row = next(r for r in AU.health()["automations"] if r["id"] == "tl:relay_tick")
    assert row["state"] == "FAILING" and "boom" in row["detail"]


def test_bridge_down_is_unknown_never_green(monkeypatch):
    import timeline_adapter as TA
    monkeypatch.setattr(TA, "configured", lambda: True)
    monkeypatch.setattr(TA, "automation_status", lambda: None)
    _quiet_edith(monkeypatch)
    h = AU.health()
    assert h["counts"]["UNKNOWN"] >= 1 and h["counts"]["RUNNING"] == 0
    evs = AU.salience_events()
    assert evs and evs[0]["type"] == "automation_unknown"
    assert not any(e["type"] == "automation_all_green" for e in evs)


def test_all_green_positive_confirmation(monkeypatch):
    integ = {}
    for aid, _, _ in AU.TIMELINE_JOBS:
        integ.update(_integ(aid.split(":", 1)[1], ok=True, last_ok_h=1))
    _wire_tl(monkeypatch, integ); _quiet_edith(monkeypatch)
    evs = AU.salience_events()
    assert len(evs) == 1 and evs[0]["type"] == "automation_all_green"
    assert "All %d automations green" % len(AU.TIMELINE_JOBS) in evs[0]["spoken"]
    # watermark id is week-bucketed → same week = same id (announce once)
    assert evs[0]["id"] == AU.salience_events()[0]["id"]


def test_failure_event_day_bucketed(monkeypatch):
    _wire_tl(monkeypatch, _integ("daily_sync", ok=False, detail="error: 401")); _quiet_edith(monkeypatch)
    evs = AU.salience_events()
    fail = [e for e in evs if e["type"] == "automation_failing"]
    assert fail and "401" in fail[0]["spoken"] and now_sydney().date().isoformat() in fail[0]["id"]


def test_handler_specific_job(monkeypatch):
    _wire_tl(monkeypatch, _integ("daily_sync", ok=True, last_ok_h=3)); _quiet_edith(monkeypatch)
    r, h = AU.handle_automation_health("did the sync run today?")
    assert h and "Timeline Asana sync" in r and "RUNNING" in r


def test_handler_full_readout_mixed(monkeypatch):
    integ = {}
    integ.update(_integ("daily_sync", ok=True, last_ok_h=2))
    integ.update(_integ("relay_tick", ok=False, detail="error: kaput"))
    _wire_tl(monkeypatch, integ); _quiet_edith(monkeypatch)
    r, h = AU.handle_automation_health("are the automations healthy?")
    assert h and "FAILING" in r and "kaput" in r and "not counting those as green" in r


def test_handler_ignores_unrelated():
    assert AU.handle_automation_health("how are the clients doing?")[1] is False
    assert AU.handle_automation_health("run the allocation")[1] is False
