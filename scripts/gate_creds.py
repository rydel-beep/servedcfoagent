"""gate_creds.py — WHO THE GATES LOG IN AS, AND WHERE THE PASSWORD COMES FROM (#171).

The deploy gates need a session that sees every page as the owner does. Until
#171 that meant the owner's own password in the process env, which meant
Rydel at the keyboard for every deploy. Now there is a dedicated GATE
ACCOUNT (dashboard/auth.py, role "gate"): owner-grade reads, zero actions.

Resolution order — the first that yields a value wins:
  1. GATE_BOT_PASSWORD in the env                  → user "gate"
  2. the git-ignored file `.gate_password` at the repo root (one line)
                                                    → user "gate"
  3. GATE_OWNER_PASSWORD in the env (the pre-#171 path, e.g. injected by
     `railway run` from the service's own RYDEL_PASSWORD)
                                                    → user GATE_OWNER_USER or "rydel"
  4. nothing                                        → (None, None, "none")

THE VALUE IS NEVER PRINTED, LOGGED OR WRITTEN by anything in this module —
callers get it in memory and pass it straight to the login form. `describe()`
is the only thing safe to print: it names the MODE, never the value.
"""
from __future__ import annotations

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PASSWORD_FILE = os.path.join(ROOT, ".gate_password")
GATE_USER = "gate"


def _file_value() -> str | None:
    try:
        with open(PASSWORD_FILE, encoding="utf-8") as f:
            v = f.read().strip()
        return v or None
    except OSError:
        return None


def resolve() -> tuple[str | None, str | None, str]:
    """→ (user, password, mode). mode ∈ {"gate-env", "gate-file", "owner-env", "none"}."""
    v = (os.environ.get("GATE_BOT_PASSWORD") or "").strip()
    if v:
        return GATE_USER, v, "gate-env"
    v = _file_value()
    if v:
        return GATE_USER, v, "gate-file"
    v = (os.environ.get("GATE_OWNER_PASSWORD") or "").strip()
    if v:
        return os.environ.get("GATE_OWNER_USER", "rydel"), v, "owner-env"
    # INTERIM (until GATE_BOT_PASSWORD exists): under `railway run` the
    # service's own RYDEL_PASSWORD is in the env — never typed, never shown.
    v = (os.environ.get("RYDEL_PASSWORD") or "").strip()
    if v and os.environ.get("RAILWAY_ENVIRONMENT"):
        return "rydel", v, "owner-railway-env"
    return None, None, "none"


def is_gate_mode(mode: str) -> bool:
    return mode in ("gate-env", "gate-file")


def describe(mode: str) -> str:
    """Plain words for a report. Never the value."""
    return {
        "gate-env": "the read-only gate account (password from the environment)",
        "gate-file": "the read-only gate account (password from the git-ignored local file)",
        "owner-env": ("the OWNER account via the environment — interim; set "
                      "GATE_BOT_PASSWORD so the gates stop needing it"),
        "owner-railway-env": ("the OWNER account via the Railway service env (railway run) — "
                              "interim; set GATE_BOT_PASSWORD so the gates stop needing it"),
        "none": ("no gate credential: set GATE_BOT_PASSWORD on Railway and put the "
                 "same value in .gate_password (git-ignored)"),
    }.get(mode, mode)
