"""
tests/test_evidence_horizon.py — F2 (extreme audit): the trust journal's evidence
horizon. Root cause: `integrity:autofix_log` caps at 200 and the nightly sweeps
flood it — at audit the oldest surviving entry was ONE DAY old, so the #131
ruling-conversion evidence (charge ids) was on track to age out ~2 days after
conversion, stranding the very derivations the refund ruling (R1) depends on.

Fix under test: evidence-class entries (derivation provenance, ruling
conversions, supersessions, verifications) are partitioned into the durable
`resolution:journal` (cap 1000 ≫ the derivation population); routine sweep
noise stays in the 200-cap rolling log.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store
import resolution


def _reset():
    kv_store.put("integrity:autofix_log", [])
    kv_store.put("resolution:journal", [])


def test_charge_id_evidence_survives_a_hard_sweep_flood():
    """Run the sweep hard: a >2-day-old charge-id conversion entry must still
    resolve after 500 routine entries — the exact failure mode of the audit."""
    _reset()
    old = {"rule": "ruling-conversion DECISIONS #131",
           "detail": "Test Client: close_date 2026-07-15 derived from Stripe "
                     "charge ch_3XYZOLD (ID-exact email match)",
           "ts": "2026-08-01"}     # 8 days before 'today' at write time
    kv_store.put("integrity:autofix_log", [old])
    kv_store.put("resolution:journal", [old])
    # the flood: 500 routine sweep entries (non-evidence class)
    for i in range(500):
        resolution.log_autofix("A5 self-retiring flag", f"sweep noise {i}")
    rolling = kv_store.get("integrity:autofix_log") or []
    assert len(rolling) == 200                       # the rolling cap held
    assert not any("ch_3XYZOLD" in e["detail"] for e in rolling)   # aged out there…
    ej = resolution.evidence_journal()
    assert any("ch_3XYZOLD" in e["detail"] for e in ej)            # …but NOT here
    assert not any("sweep noise" in e["detail"] for e in ej)       # noise excluded


def test_every_evidence_class_rule_lands_in_the_partition():
    _reset()
    for rule, detail in [
        ("date derived (close_date)", "x: close_date = 2026-08-01 via derived:stripe"),
        ("date superseded (close_date)", "x: source 2026-08-02 supersedes derived"),
        ("ruling-conversion DECISIONS #131", "x: charge ch_1 (ID-exact)"),
        ("T2 spine derivation", "set+show derived for close 'x'"),
        ("show verified (call)", "x: call 123 180s"),
        ("reached derivation", "'x' marked reached"),
    ]:
        resolution.log_autofix(rule, detail)
    assert len(resolution.evidence_journal()) == 6


def test_routine_rules_stay_out_of_the_partition():
    _reset()
    resolution.log_autofix("A5 self-retiring flag", "noise")
    resolution.log_autofix("A1 normalization", "noise")
    assert resolution.evidence_journal() == []


def test_partition_caps_at_1000_not_unbounded():
    _reset()
    for i in range(1050):
        resolution.log_autofix("date derived (set_date)", f"lead {i}")
    ej = resolution.evidence_journal()
    assert len(ej) == 1000
    assert ej[-1]["detail"] == "lead 1049"    # newest kept, oldest trimmed


def test_record_derived_date_writes_the_partition_end_to_end():
    _reset()
    resolution.record_derived_date("evidence horizon lead", "close_date", "2026-08-05",
                                   "derived:stripe", {"charge_id": "ch_E2E"})
    assert any("ch_E2E" in e["detail"] for e in resolution.evidence_journal())
