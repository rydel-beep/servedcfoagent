"""
conftest.py (repo root)
-----------------------
Test auth env MUST exist before any module import freezes it: config.py reads
CFO_REFRESH_KEY / DASHBOARD_TOKEN at import time, and `from config import CFO_REFRESH_KEY`
in app.py freezes the value into that namespace. Individual test files setting these via
os.environ.setdefault is order-dependent (whichever test module runs first and triggers a
config import wins) — the full suite failed test_cfo_snapshot_allows_cfo_key/test_flask_app
that way while each file passed alone. A root conftest loads before every test module,
making the values deterministic.
"""
import os

os.environ.setdefault("CFO_REFRESH_KEY", "test-key-123")
os.environ.setdefault("DASHBOARD_TOKEN", "test-dash-token")
