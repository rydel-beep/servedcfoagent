"""tests/test_ship_pipeline.py — the deploy pipeline's control flow (#171).

The real steps (pytest, git push, Railway, Playwright) are stubbed; what is
pinned is the ORDER and the decisions: a failing preflight never pushes; a
deploy that never serves is reported, not gated; a failed gate reverts and
pushes the revert; a passing run ends with production == the tested commit.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ship  # noqa: E402

_REAL_WAIT_WARM = ship.wait_warm


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    ship.REPORT.clear()
    ship.REPORT.update({"base": "http://test", "steps": [], "ok": False})
    monkeypatch.setattr(ship, "ROOT", str(tmp_path))
    monkeypatch.setattr(ship, "head", lambda: "abc123def456abc123def456abc123def456abc1")
    monkeypatch.setattr(sys, "argv", ["ship.py"])
    monkeypatch.setattr(ship, "POLL_S", 0)
    monkeypatch.setattr(ship, "DEPLOY_WAIT_S", 1)
    # never poll the real production /health from a test
    monkeypatch.setattr(ship, "wait_warm", lambda: ship.step(
        "production warm (snapshot present)", True, "stubbed"))


def _names():
    return [s["step"] for s in ship.REPORT["steps"]]


def test_a_failing_preflight_is_refused_before_any_push(monkeypatch):
    calls = []
    monkeypatch.setattr(ship, "sh", lambda cmd, timeout=0: (
        calls.append(cmd) or ((1, "SyntaxError: deliberate") if "compileall" in cmd else (0, ""))))
    monkeypatch.setattr(ship, "push", lambda: (_ for _ in ()).throw(AssertionError("pushed!")))
    assert ship.main() == 2
    assert "git push origin main" not in _names()
    assert any(s["step"] == "every file compiles" and not s["ok"] for s in ship.REPORT["steps"])
    assert "Production is unchanged" in ship.REPORT["summary"]


def test_a_dirty_tree_never_ships(monkeypatch):
    monkeypatch.setattr(ship, "sh", lambda cmd, timeout=0: (
        (0, " M close_register.py\n") if "status" in cmd else (0, "")))
    assert ship.main() == 2
    assert ship.REPORT["steps"][0]["step"] == "working tree clean"
    assert not ship.REPORT["steps"][0]["ok"]


def test_a_passing_run_pushes_waits_gates_and_reports_the_commit(monkeypatch):
    monkeypatch.setattr(ship, "sh", lambda cmd, timeout=0: (
        (0, "") if "status" in cmd else (0, "1553 passed")))
    monkeypatch.setattr(ship, "live_commit", lambda: "abc123def456")
    monkeypatch.setattr(ship, "run_gates", lambda: (ship.step("render gate", True) or
                                                    ship.step("behaviour gate", True) or True))
    assert ship.main() == 0
    assert _names() == ["working tree clean", "every file compiles", "the app imports",
                        "full test suite", "git push origin main",
                        "production serves the pushed commit",
                        "production warm (snapshot present)", "render gate", "behaviour gate"]
    assert ship.REPORT["ok"] and "abc123def456" in ship.REPORT["summary"]


def test_a_deploy_that_never_serves_is_reported_not_gated(monkeypatch):
    monkeypatch.setattr(ship, "sh", lambda cmd, timeout=0: (
        (0, "") if "status" in cmd else (0, "ok")))
    monkeypatch.setattr(ship, "live_commit", lambda: "oldoldoldold")
    monkeypatch.setattr(ship, "run_gates", lambda: (_ for _ in ()).throw(AssertionError("gated!")))
    assert ship.main() == 4
    assert "never served" in ship.REPORT["summary"]


def test_a_failed_gate_reverts_and_pushes_the_revert(monkeypatch):
    cmds = []
    serving = {"c": "abc123def456"}

    def _sh(cmd, timeout=0):
        cmds.append(cmd)
        if cmd[:2] == ["git", "revert"]:
            serving["c"] = "rev000000000"           # the revert, once pushed, serves
        return (0, "") if "status" in cmd else (0, "ok")
    monkeypatch.setattr(ship, "sh", _sh)
    monkeypatch.setattr(ship, "live_commit", lambda: serving["c"])
    heads = iter(["abc123def456abc123def456abc123def456abc1", "rev000000000rev000000000rev000000000rev0"])
    monkeypatch.setattr(ship, "head", lambda: next(heads, "rev000000000rev000000000rev000000000rev0"))
    monkeypatch.setattr(ship, "run_gates", lambda: (ship.step("render gate", False, "tile empty") or False))
    assert ship.main() == 5
    assert ["git", "revert", "--no-edit", "abc123def456abc123def456abc123def456abc1"] in cmds
    pushes = [c for c in cmds if c[:2] == ["git", "push"]]
    assert len(pushes) == 2 and all(c == ["git", "push", "origin", "main"] for c in pushes)
    assert "reverted" in ship.REPORT["summary"]


def test_gates_only_mode_never_pushes(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ship.py", "--gates-only"])
    monkeypatch.setattr(ship, "sh", lambda cmd, timeout=0: (_ for _ in ()).throw(AssertionError(cmd)))
    monkeypatch.setattr(ship, "live_commit", lambda: "live00000000")
    monkeypatch.setattr(ship, "run_gates", lambda: True)
    assert ship.main() == 0
    assert "git push origin main" not in _names()


def test_the_pipelines_own_evidence_never_dirties_the_tree(monkeypatch):
    monkeypatch.setattr(ship, "sh", lambda cmd, timeout=0: (
        (0, "?? dashboard/evidence/ship-abc123/\n M SENTINEL_QUEUE.md\n") if "status" in cmd
        else (0, "ok")))
    monkeypatch.setattr(sys, "argv", ["ship.py", "--dry-run"])
    assert ship.main() == 0
    assert ship.REPORT["steps"][0] == {"step": "working tree clean", "ok": True, "detail": ""}



def test_the_gates_wait_for_a_warm_production(monkeypatch):
    """3 Oct: both reverts were 30 s page timeouts gated mid-boot-rebuild."""
    import io
    import json as _j
    seen = iter([{"snapshot": "missing"}, {"snapshot": {"present": True}}])
    monkeypatch.setattr(ship.time, "sleep", lambda s: None)
    monkeypatch.setattr(ship.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(
        _j.dumps({"subsystems": next(seen)}).encode()))
    _REAL_WAIT_WARM()
    st = ship.REPORT["steps"][-1]
    assert st["step"] == "production warm (snapshot present)" and st["ok"]
    assert "not warm" not in st.get("detail", "")
