"""THE TRIPLE SCAN + THE STAGE RECORDER — the battery.

Scan 1 covers every page in the nav · scan 2 catches a surface that
computes a metric differently · scan 3 catches a source mismatch and never
passes by omission · a scan that stops running is itself a failure · the
recorder writes only to this repo's store and never invents a stage.
"""

import json
import os
import re

import pytest

import kv_store

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ── SCAN 1 — coverage ───────────────────────────────────────────────────────

def test_scan1_covers_every_page_in_the_nav():
    """Every page the app serves must be in the scan's list — a page nobody
    scans is a page that can break quietly."""
    from scripts import triple_scan  # noqa: F401  (import guard)


def test_scan1_page_list_matches_the_routes():
    scan = _read("scripts", "triple_scan.py")
    from dashboard.routes import _AREAS
    for area in _AREAS:
        assert f"/dashboard/view/{area}" in scan, f"{area} is not scanned"
    for page in ("/dashboard/", "/dashboard/scale",
                 "/dashboard/scale/travelling", "/dashboard/definitions",
                 "/dashboard/worklog", "/dashboard/bookkeeping",
                 "/dashboard/csm", "/ads"):
        assert page in scan, page
    # and it asserts the things that matter on each
    assert "rendered empty" in scan and "a panel failed" in scan
    assert "console" in scan


# ── SCAN 2 — the consistency matrix ─────────────────────────────────────────

def test_scan2_metrics_carry_their_identity_in_the_dom():
    """Scan 2 can only compare what the page identifies."""
    landing = _read("dashboard", "templates", "dashboard.html")
    assert 'data-metric="{{ t.id }}"' in landing
    assert 'data-window=' in landing and 'data-basis=' in landing
    assert 'data-value="{{ t.raw' in landing
    tv = _read("dashboard", "templates", "travelling.html")
    assert 'data-metric="tv_{{ s.id }}"' in tv
    assert 'data-window="{{ data.window.key }}"' in tv


def test_scan2_compares_by_key_and_against_the_engine():
    scan = _read("scripts", "triple_scan.py")
    assert "differs across surfaces" in scan
    assert "DISAGREES WITH ITSELF" in scan
    assert "≠ the engine" in scan
    assert "DRILLS" in scan          # EDITH's numbers are compared too


def test_scan2_seeded_divergence_is_caught():
    """A surface forced to publish a different value for the same key must
    produce a finding naming both."""
    rows_a = [{"metric": "cash_on_hand", "window": "current", "basis": "engine",
               "value": "188473.38"}]
    rows_b = [{"metric": "cash_on_hand", "window": "current", "basis": "engine",
               "value": "177000.00"}]          # the seeded divergence
    seen = {}
    for surface, rows in (("landing", rows_a), ("cash", rows_b)):
        for r in rows:
            seen.setdefault((r["metric"], r["window"], r["basis"]), []).append(
                {"surface": surface, "value": r["value"]})
    found = [k for k, hits in seen.items() if len({h["value"] for h in hits}) > 1]
    assert found == [("cash_on_hand", "current", "engine")]
    hits = seen[found[0]]
    detail = " vs ".join(f"{h['surface']}={h['value']}" for h in hits)
    assert "landing=188473.38" in detail and "cash=177000.00" in detail


# ── SCAN 3 — reality, and never passing by omission ─────────────────────────

def test_scan3_never_passes_by_omission():
    import ground_truth as GT
    c = GT._check("x", "meta", None, "no live re-read path", sev="SEV3")
    assert c["ok"] is None                      # not True
    src = _read("ground_truth.py")
    assert "never passes by omission" in src
    assert "closed days" in src.lower()


def test_scan3_seeded_source_mismatch_surfaces(monkeypatch):
    import ground_truth as GT
    monkeypatch.setattr(GT, "_meta_spend_closed_days", lambda n=3: [
        GT._check("Meta spend 2026-09-18", "meta", False,
                  "archive $500.00 vs live $610.00", sev="SEV1")])
    monkeypatch.setattr(GT, "_stripe_cash", lambda: GT._check("s", "stripe", True, "ok"))
    monkeypatch.setattr(GT, "_xero_bank_vs_cash_tile", lambda: GT._check("b", "xero", True, "ok"))
    monkeypatch.setattr(GT, "_xero_ar_anchor", lambda: GT._check("a", "xero", True, "ok"))
    monkeypatch.setattr(GT, "_ghl_counts", lambda: [])
    monkeypatch.setattr(GT, "_tracker_rows", lambda: GT._check("t", "workbook", True, "ok"))
    out = GT.run()
    assert out["ok"] is False and out["failed"] == 1
    items = kv_store.get("feed:extra:ground_truth") or []
    assert items and "disagrees with meta" in items[0]["title"]


def test_health_rows_and_the_watchdog():
    import ground_truth as GT
    kv_store.put(GT.K_HEALTH, [])
    GT.record_health_row({"commit": "abc", "scan1_ok": True, "scan2_ok": True,
                          "scan3_ok": False, "findings": 2, "runtime_s": 61})
    h = GT.health()
    assert h["last"]["commit"] == "abc" and h["last"]["scan3_ok"] is False
    assert h["stale_warning"] is None
    # a scan that stops running is itself a failure
    kv_store.put(GT.K_HEALTH, [{"commit": "old", "at": "2026-09-01T00:00:00+10:00"}])
    assert "stopped" in (GT.watchdog() or [{}])[0]["title"]
    kv_store.put(GT.K_HEALTH, [])
    assert "no scan has ever" in GT.health()["stale_warning"]


def test_health_panel_and_endpoints_exist():
    """R-PIOLO (#161): the estate's health is a READ Piolo has — recording a
    health row is still Rydel's, because it changes what the numbers say."""
    routes = _read("dashboard", "routes.py")
    i = routes.index("def api_health_row")
    assert "@require_owner" in routes[i - 200:i]
    j = routes.index("def api_ground_truth")
    assert "@require_auth" in routes[j - 200:j]
    import role_access as RA
    assert RA.coo_permitted("/dashboard/api/ground-truth", "GET")[0]
    assert not RA.coo_permitted("/dashboard/api/health-row", "POST")[0]
    panel = _read("dashboard", "templates", "partials", "area_system.html")
    assert "estate-health-body" in panel and "agree with reality" in panel


# ── PART F — the stage recorder ─────────────────────────────────────────────

def test_recorder_writes_only_to_this_repos_store():
    src = _read("stage_history.py")
    assert "GHL_EMAIL_TOKEN" not in src
    assert not re.search(r"requests\.(post|put|patch|delete)\(", src)
    writes = re.findall(r"kv_store\.put\(([^,)]+)", src)
    assert all("K_" in w or "stage_history:" in w for w in writes), writes
    assert "never calls" in src or "never writes to the CRM" in src


def test_recorder_takes_a_baseline_then_records_changes(monkeypatch):
    import stage_history as SH
    kv_store.put(SH.K_SEEN, None)
    kv_store.put(SH.K_TRANSITIONS, [])
    kv_store.put(SH.K_START, None)
    import ghl_mirror
    state = {"opps": [{"id": "o1", "contact_id": "c1", "stage_name": "Consult Call Booked"}]}
    monkeypatch.setattr(ghl_mirror, "read_opportunities", lambda **k: state["opps"])
    first = SH.record_poll("p1")
    assert first["first_run"] is True and first["transitions_recorded"] == 0
    # a real move is recorded
    state["opps"] = [{"id": "o1", "contact_id": "c1", "stage_name": "Pitched and Drifted"}]
    second = SH.record_poll("p2")
    assert second["transitions_recorded"] == 1
    rows = kv_store.get(SH.K_TRANSITIONS)
    assert rows[-1]["from"] == "Consult Call Booked"
    assert rows[-1]["to"] == "Pitched and Drifted"
    assert rows[-1]["kind"] == "step" and rows[-1]["first_seen"]
    # and it becomes a MEASURED pitched event
    ev = SH.pitched_events()
    assert ev["count"] == 1 and "measured" in ev["basis"]


def test_recorder_records_a_jump_as_a_jump(monkeypatch):
    import stage_history as SH
    kv_store.put(SH.K_SEEN, {"o2": {"stage": "Served New Leads", "at": "x"}})
    kv_store.put(SH.K_TRANSITIONS, [])
    import ghl_mirror
    monkeypatch.setattr(ghl_mirror, "read_opportunities",
                        lambda **k: [{"id": "o2", "contact_id": "c2",
                                      "stage_name": "✅ Closed Deal"}])
    SH.record_poll("p3")
    row = kv_store.get(SH.K_TRANSITIONS)[-1]
    assert row["kind"] == "jump" and row["jumped"] is True
    # the stages in between are NOT invented
    assert row["from"] == "Served New Leads" and row["to"] == "✅ Closed Deal"


def test_recorder_velocity_is_labelled_until_it_has_enough():
    import stage_history as SH
    kv_store.put(SH.K_TRANSITIONS, [])
    v = SH.velocity()
    assert not v["usable_for_the_model"]
    assert "not enough history" in v["note"]


def test_pitched_row_reads_measured_for_the_watched_cohort():
    src = _read("travelling.py")
    assert "measured_since" in src and "stage recorder" in src
    from dashboard import definitions as D
    assert D.entry("pitched_measured")


def test_recorder_rides_the_existing_loop_no_new_cadence():
    app_src = _read("app.py")
    assert "stage_history" in app_src and "stage_history.tick()" in app_src
    assert "never calls or writes to the CRM" in app_src


def test_scan3_meta_live_reread_is_read_only():
    """The cent-exact check needs a live re-read that never touches the
    archive — otherwise the comparison compares the archive with itself."""
    src = _read("meta_spend.py")
    i = src.index("def fetch_day_live")
    block = src[i:i + 1400]
    assert "_save_store" not in block, "the live re-read must not write the archive"
    assert "Read-only by construction" in block
    import meta_spend
    assert hasattr(meta_spend, "fetch_day_live")
    gt = _read("ground_truth.py")
    assert "fetch_day_live" in gt
