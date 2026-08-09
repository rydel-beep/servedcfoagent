"""
scripts/gate_close_migrations.py — the post-deploy live pass for the audit gate
close (run via `railway ssh /opt/venv/bin/python scripts/gate_close_migrations.py
[--dry-run]`). Read-only against external systems; writes only to kv (journaled).

Order:
  1 · F8  — rederive_ghl_dates_sydney (dry-run first; then real) — old→new per
            date, evidence ids, reason F8-sydney-day, window crossings.
  2 · F16 — dedupe_accuracy_history (journaled).
  3 · IDEMPOTENCE — both re-run; must convert/change NOTHING the second time.
  4 · Live measurements: full I17 sweep · recon check · claims re-proof ·
      cold/warm roster timing · scorecard v1 data-state block.
Prints one JSON document — paste into dashboard/audit_artifacts/08.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, ".")

DRY = "--dry-run" in sys.argv
out: dict = {"dry_run": DRY}

import resolution                                             # noqa: E402
import ads_truth                                              # noqa: E402

# 1 · F8
out["f8_dry"] = resolution.rederive_ghl_dates_sydney(dry_run=True)
if not DRY:
    out["f8_apply"] = resolution.rederive_ghl_dates_sydney()
    out["f8_idempotence"] = resolution.rederive_ghl_dates_sydney()
    # 2 · F16
    out["f16_dedupe"] = ads_truth.dedupe_accuracy_history()
    out["f16_idempotence"] = ads_truth.dedupe_accuracy_history()

# 4 · live measurements
import ad_sentinel                                            # noqa: E402
import attribution_engine as AE                               # noqa: E402
import roster_engine                                          # noqa: E402

t0 = time.time()
out["full_i17"] = ad_sentinel.full_i17_sweep()
out["full_i17_runtime_s"] = round(time.time() - t0, 1)

r = AE.compute(days=30, basis="cohort")
out["recon"] = (r.get("reconciliation") or {}).get("ok")
out["degraded"] = r.get("degraded")
out["claims_reproof"] = ad_sentinel.claims_reproof()

AE._cache.clear()                       # simulate the cold worker
t0 = time.time()
_res, meta = roster_engine.load_result(30, None, None, "cohort", None)
out["roster_cold_s"] = round(time.time() - t0, 3)
out["roster_cold_served_from"] = meta["served_from"]
t0 = time.time()
roster_engine.load_result(30, None, None, "cohort", None)
out["roster_second_s"] = round(time.time() - t0, 3)

import kv_store                                               # noqa: E402
acc = kv_store.get("ads_truth:accuracy") or []
out["accuracy_rows"] = [{k: v for k, v in row.items() if k != "spine"}
                        for row in acc[-3:]]
out["evidence_journal_n"] = len(kv_store.get("resolution:journal") or [])
out["integrity_pending_n"] = len(kv_store.get("integrity:pending") or [])
out["sentinel_cost_rows"] = (kv_store.get("sentinel:cost") or [])[-3:]

print(json.dumps(out, default=str, indent=1))
