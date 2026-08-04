"""
boot_banner.py
--------------
Structured boot visibility (DECISIONS #112 — the deploy-safety layer). Two jobs:

1. pre_import(name): one log line BEFORE each risky module import in app.py, so a
   boot-crashing import's LAST log lines always name exactly what was being imported.
2. emit(): the startup banner — commit sha, Sydney boot time, python version, which
   dashboard modules imported OK, config presence (env var NAMES ONLY — values are never
   logged, ever), DB connectivity, worker pid. The same facts are kept in BOOT_INFO for
   /health, so "what version is live" is answerable at a glance.

Additive only: nothing here changes application behavior; every probe is guarded.
"""
from __future__ import annotations

import logging
import os
import platform

logger = logging.getLogger("boot")

# Presence is reported for these NAMES. Values are NEVER read into the log path.
_EXPECTED_ENV = [
    "DATABASE_URL", "CFO_REFRESH_KEY", "DASHBOARD_TOKEN", "EDITH_BRIDGE_SECRET",
    "FLASK_SECRET_KEY", "GHL_SALES_API_KEY", "GHL_SALES_LOCATION_ID", "GHL_EMAIL_TOKEN",
    "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID", "STRIPE_API_KEY", "STRIPE_MCP_BASE",
    "XERO_CLIENT_ID", "XERO_CLIENT_SECRET", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
]

BOOT_INFO: dict = {"modules_ok": []}


def commit_sha() -> str:
    return (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12]


def pre_import(name: str) -> None:
    """Log intent BEFORE a module-level import so a SyntaxError/ImportError crash's
    final log line identifies the module that killed the boot."""
    logger.info("boot: importing %s ...", name)


def module_ok(name: str) -> None:
    BOOT_INFO["modules_ok"].append(name)
    logger.info("boot: %s OK", name)


def emit() -> None:
    """The one-block startup banner. Guarded — must never crash a boot itself."""
    try:
        from helpers import now_sydney
        booted_at = now_sydney().isoformat()
    except Exception:
        booted_at = "unknown"
    env_presence = {k: ("present" if os.environ.get(k) else "absent") for k in _EXPECTED_ENV}
    try:
        import db
        db_state = "ok" if db.memory_online() else f"unavailable ({db.last_error() or 'unknown'})"
    except Exception as e:  # noqa: BLE001
        db_state = f"probe failed ({type(e).__name__})"
    BOOT_INFO.update({
        "commit": commit_sha(),
        "booted_at": booted_at,
        "python": platform.python_version(),
        "worker_pid": os.getpid(),
        "db": db_state,
    })
    logger.info(
        "boot banner | commit=%s | booted_at=%s | python=%s | worker=%d | db=%s | "
        "modules_ok=%s | env(NAMES only)=%s",
        BOOT_INFO["commit"], booted_at, BOOT_INFO["python"], BOOT_INFO["worker_pid"],
        db_state, ",".join(BOOT_INFO["modules_ok"]),
        " ".join(f"{k}:{v}" for k, v in env_presence.items()),
    )
