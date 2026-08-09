"""
tests/test_polish_wave.py — audit polish batch:

  F7  — a contact merge deletes the old GHL id; its cached reached-evidence
        entry is pruned (journaled) the same sweep, so the droop self-heals
        NOW, not whenever the 40/night queue gets around to it.
  F10 — JOURNAL-FIRST ordering: a crash mid-derivation leaves a journaled-but-
        unapplied entry (detectable), never an applied-but-unjournaled one
        (invisible forever) — drill B14's gap closed.
  F11 — orphan derivations (tracker row deleted) are counted nightly into a
        visible bucket — inert, never auto-deleted, no longer invisible.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ads_truth
import kv_store
import resolution


# ── F10 · journal-first ──────────────────────────────────────────────────────

def test_crash_after_journal_leaves_no_silent_derivation(monkeypatch):
    kv_store.put("derived:dates", {})
    kv_store.put("integrity:autofix_log", [])
    kv_store.put("resolution:journal", [])
    monkeypatch.setattr(resolution, "_put_derived",
                        lambda store: (_ for _ in ()).throw(RuntimeError("crash (test)")))
    try:
        resolution.record_derived_date("crash test lead", "close_date", "2026-08-01",
                                       "derived:stripe", {"charge_id": "ch_CRASH"})
    except RuntimeError:
        pass
    # the store write died — but the journal ALREADY carries the intent
    assert resolution.derived_dates() == {}
    assert any("ch_CRASH" in e["detail"]
               for e in kv_store.get("integrity:autofix_log"))
    assert any("ch_CRASH" in e["detail"] for e in resolution.evidence_journal())


def test_supersede_journals_before_removing(monkeypatch):
    kv_store.put("derived:dates",
                 {"order test": {"close_date": {"date": "2026-08-01",
                                                "provenance": "derived:stripe",
                                                "evidence": {"charge_id": "x"},
                                                "ts": "2026-08-01"}}})
    kv_store.put("integrity:autofix_log", [])
    monkeypatch.setattr(resolution, "_put_derived",
                        lambda store: (_ for _ in ()).throw(RuntimeError("crash (test)")))
    try:
        resolution.supersede_derived("order test", "close_date", "2026-08-02")
    except RuntimeError:
        pass
    assert any("supersede" in e["rule"] for e in kv_store.get("integrity:autofix_log"))


# ── F7 · merge-ghost prune ───────────────────────────────────────────────────

def test_reached_sweep_prunes_merged_away_contact_ids(monkeypatch):
    kv_store.put("reached:evidence", {"ghost_id": {"kind": "ghl-appointment"},
                                      "live_id": {"kind": "ghl-appointment"}})
    kv_store.put("reached:evidence:none", {"ghost_id2": {"ts": "2026-08-01"}})
    kv_store.put("integrity:autofix_log", [])
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: {"rows": []})
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts",
                        lambda: [{"id": "live_id", "name": "Live Person"}])
    out = ads_truth.reached_sweep(max_contacts=0)
    cache = kv_store.get("reached:evidence")
    assert "ghost_id" not in cache and "live_id" in cache
    assert "ghost_id2" not in kv_store.get("reached:evidence:none")
    assert any("F7" in e["rule"] for e in kv_store.get("integrity:autofix_log"))


def test_reached_sweep_never_wipes_on_empty_contacts(monkeypatch):
    """A dead contact pull must NOT read as 'every id merged away'."""
    kv_store.put("reached:evidence", {"live_id": {"kind": "ghl-appointment"}})
    import attribution_engine as AE
    monkeypatch.setattr(AE, "compute", lambda **kw: {"rows": []})
    import attribution_join
    monkeypatch.setattr(attribution_join, "load_contacts",
                        lambda: (_ for _ in ()).throw(RuntimeError("GHL down")))
    out = ads_truth.reached_sweep(max_contacts=0)
    assert out.get("reason") == "contacts unavailable"
    assert kv_store.get("reached:evidence") == {"live_id": {"kind": "ghl-appointment"}}


# ── F11 · orphan census ──────────────────────────────────────────────────────

def _stub_sweep_legs(monkeypatch, tracker_rows):
    from tests.test_ads_dashboard import _fake_result
    import attribution_engine as AE
    result = _fake_result()
    monkeypatch.setattr(AE, "compute", lambda **kw: result)
    monkeypatch.setattr(AE, "_tracker_rows_clean", lambda: tracker_rows)
    for fn in ("spine_census", "quad_check", "reached_sweep", "event_sweep",
               "show_verification_pass"):
        monkeypatch.setattr(ads_truth, fn,
                            lambda *a, **kw: {"counts": {"T0": 0, "T1": 0, "T2": 0, "T3": 0},
                                              "lanes": {"T0": []}, "facts": 0,
                                              "agreements": 0, "table": [],
                                              "days": 90, "total": 0})
    monkeypatch.setattr(resolution, "resolve_dates", lambda: {})


def test_orphan_derivations_are_counted_and_flagged(monkeypatch):
    from tests.test_attribution import HDR, row
    _stub_sweep_legs(monkeypatch, [HDR, row("Real Lead", "real@x.com")])
    kv_store.put("derived:dates", {
        "real lead": {"close_date": {"date": "2026-08-01", "provenance": "derived:stripe",
                                     "evidence": {"charge_id": "x"}, "ts": "2026-08-01"}},
        "deleted row person": {"set_date": {"date": "2026-07-01",
                                            "provenance": "derived:ghl-appt",
                                            "evidence": {"appointment_id": "a"},
                                            "ts": "2026-08-01"}}})
    out = ads_truth.integrity_sweep()
    oc = out["orphan_derivations"]
    assert oc["count"] == 1 and oc["names"] == ["deleted row person"]
    flags = kv_store.get("ads_truth:flags")
    assert any("orphan derivation" in f["reason"] for f in flags)
    # inert — NOTHING deleted from the store
    assert "deleted row person" in resolution.derived_dates()
