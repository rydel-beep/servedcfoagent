"""tests/test_gate_account.py — THE GATE ACCOUNT (#171, Phase 0).

Owner's eyes, nobody's hands: the gate role reads every page exactly as the
owner does and is refused every action — structurally, by method, before any
route body runs — plus the few GET paths that act (EDITH voice, scans). The
credential never appears in code, logs or the repo; the gate scripts resolve
it from the env or a git-ignored file and never print it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


@pytest.fixture()
def app_client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-171")
    import app as appmod
    return appmod.app


def _as(app, role, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": user, "role": role, "display": user}
    return c


# ── the account exists only when its env var does; the value is never ours ──

def test_gate_account_is_env_enabled_and_never_defaulted(monkeypatch):
    import dashboard.auth as A
    monkeypatch.delenv("GATE_BOT_PASSWORD", raising=False)
    assert "gate" not in A._accounts()
    monkeypatch.setenv("GATE_BOT_PASSWORD", "x-test-only")
    acct = A._accounts()["gate"]
    assert acct["role"] == "gate"
    assert A.verify_login("gate", "x-test-only")["role"] == "gate"
    assert A.verify_login("gate", "wrong") is None


def test_no_credential_value_is_written_anywhere_in_the_repo():
    """The agent creates no credential: no default, no example value, no
    file with content. `.gate_password` is git-ignored and ships empty."""
    src = _read("dashboard", "auth.py")
    assert re.search(r'GATE_BOT_PASSWORD",\s*""\)', src)          # env read, empty default
    assert "GATE_BOT_PASSWORD=" not in _read("scripts", "gate_creds.py")
    ignore = _read(".gitignore")
    assert ".gate_password" in ignore
    tracked = subprocess.run(["git", "ls-files", ".gate_password"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    assert tracked == "", "the gate password file must never be tracked"


# ── sees as the owner ───────────────────────────────────────────────────────

def test_gate_reads_every_owner_page(app_client):
    c = _as(app_client, "gate", "gate")
    for path in ("/dashboard/today", "/dashboard/sales", "/dashboard/landing",
                 "/dashboard/scale", "/dashboard/scale/travelling",
                 "/dashboard/system", "/dashboard/closes", "/dashboard/csm",
                 "/dashboard/api/travelling", "/dashboard/api/unit-economics",
                 "/dashboard/api/register", "/dashboard/api/comp/rules",
                 "/dashboard/api/drawer/ltv_cac", "/dashboard/api/whoami"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code)


def test_gate_payloads_are_never_scrubbed():
    """Exactly as the owner sees them — a scrubbed page is not the owner's."""
    import role_access as RA
    payload = {"commission": 1, "salary": 2, "ok": 3}
    assert RA.scrubbed_for("gate", payload) == payload
    assert RA.scrubbed_for("owner", payload) == payload
    assert "commission" not in RA.scrubbed_for("sales", payload)


def test_gate_is_finance_grade_for_reads_but_never_the_owner():
    import dashboard.auth as A
    assert A.is_finance("gate")
    assert not A.is_gate("owner") and A.is_gate("gate")


# ── performs NO action ──────────────────────────────────────────────────────

def test_gate_is_refused_every_action_by_method(app_client):
    c = _as(app_client, "gate", "gate")
    for path in ("/dashboard/api/register/declare", "/dashboard/api/register/rebuild",
                 "/dashboard/api/unmatched/confirm", "/dashboard/api/closes/confirm",
                 "/dashboard/api/travelling/save", "/dashboard/api/scale/commit-plan",
                 "/dashboard/api/scale/behaviour-verified", "/dashboard/api/refresh-now",
                 "/dashboard/api/comp/rules", "/dashboard/api/parity/exceptions",
                 "/dashboard/api/csm/discreet", "/dashboard/api/scale/scenarios",
                 "/dashboard/api/pl/mapping"):
        r = c.post(path, json={})
        j = r.get_json() or {}
        # 200 + "did: nothing" — never a 403 (the browser would log a console
        # error and the gates would fail on the gate's own refusal)
        assert r.status_code == 200 and j.get("refused") == "gate", (path, r.status_code, j)
        assert j.get("ok") is False and "read-only" in j.get("error", ""), path
        assert r.headers.get("X-Gate-Refused") == "1"
    assert (c.delete("/dashboard/memory/api/conversation/1").get_json() or {}).get("refused") == "gate"


def test_gate_is_refused_the_get_paths_that_act(app_client):
    c = _as(app_client, "gate", "gate")
    r = c.get("/dashboard/api/greeting")
    assert (r.get_json() or {}).get("refused") == "gate"
    # a status READ is not an action
    assert (c.get("/dashboard/api/voice-status").get_json() or {}).get("refused") != "gate"


def test_gate_may_use_the_compute_only_calculators(app_client):
    """The page renders with these; they persist nothing. Pinned: each is
    documented in its route as computing, never committing."""
    import dashboard.auth as A
    src = _read("dashboard", "routes.py")
    for frag in A._GATE_ALLOWED_POST_FRAGMENTS:
        assert A.gate_refusal(frag, "POST") is None
        if frag in ("/api/scale/simulate", "/api/scale/run", "/api/scale/solve"):
            i = src.index(f'@bp.route("{frag}"')
            assert "never commits" in src[i:i + 300], frag
        if frag == "/api/scale/expiring-preview":
            i = src.index(f'@bp.route("{frag}"')
            assert "journal NOTHING" in src[i:i + 400]
    assert A.gate_refusal("/dashboard/api/scale/scenarios", "POST")   # saves → refused


def test_a_new_post_route_is_refused_to_the_gate_by_construction():
    """Fail-closed: a route nobody thought about is still an action. Pinned
    on a throwaway Flask app wearing the real decorator."""
    from flask import Flask, jsonify
    from dashboard.auth import require_auth
    t = Flask("t171")
    t.secret_key = "t"

    @t.route("/dashboard/api/t171/new-action", methods=["POST"])
    @require_auth
    def _new_action():
        return jsonify({"did": "something"})

    @t.route("/dashboard/api/t171/new-read", methods=["GET"])
    @require_auth
    def _new_read():
        return jsonify({"saw": "everything"})

    r = _as(t, "gate", "gate").post("/dashboard/api/t171/new-action")
    assert r.get_json().get("refused") == "gate" and "did" not in r.get_json().get("saw", "")
    assert _as(t, "gate", "gate").get("/dashboard/api/t171/new-read").get_json() == {"saw": "everything"}
    assert _as(t, "owner", "rydel").post("/dashboard/api/t171/new-action").status_code == 200


# ── the gate scripts: resolve, never print ──────────────────────────────────

def test_gate_scripts_resolve_the_credential_and_never_print_it(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import gate_creds as G
    monkeypatch.setattr(G, "PASSWORD_FILE", str(tmp_path / ".gate_password"))
    monkeypatch.delenv("GATE_BOT_PASSWORD", raising=False)
    monkeypatch.delenv("GATE_OWNER_PASSWORD", raising=False)
    assert G.resolve() == (None, None, "none")
    (tmp_path / ".gate_password").write_text("\n")           # empty file = not set
    assert G.resolve() == (None, None, "none")
    (tmp_path / ".gate_password").write_text("from-file\n")
    assert G.resolve() == ("gate", "from-file", "gate-file")
    monkeypatch.setenv("GATE_BOT_PASSWORD", "from-env")
    assert G.resolve() == ("gate", "from-env", "gate-env")
    monkeypatch.delenv("GATE_BOT_PASSWORD")
    (tmp_path / ".gate_password").write_text("")
    monkeypatch.setenv("GATE_OWNER_PASSWORD", "owner-interim")
    assert G.resolve() == ("rydel", "owner-interim", "owner-env")
    for mode in ("gate-env", "gate-file", "owner-env", "none"):
        assert "from-" not in G.describe(mode) and "owner-interim" not in G.describe(mode)
    # the gates print the MODE, never PW
    for script in ("render_gate.py", "behaviour_gate.py", "ship.py"):
        src = _read("scripts", script)
        assert not re.search(r"print\([^)]*\bPW\b", src), script
        assert "gate_creds" in src or script == "ship.py"


def test_the_pipeline_reverts_on_a_failed_gate_and_pushes_exactly_main():
    src = _read("scripts", "ship.py")
    assert '"git", "push", "origin", "main"' in src
    assert '"git", "revert", "--no-edit"' in src
    assert "pytest" in src and "compileall" in src and '"import app"' in src
    # the behaviour gate, as the gate account, treats a refused save as the
    # contract and never posts the badge
    bg = _read("scripts", "behaviour_gate.py")
    assert "read-only" in bg and "AS_GATE" in bg
