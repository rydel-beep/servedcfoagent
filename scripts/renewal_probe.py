"""renewal_probe.py — #170/#169 Phase 0: B1 renewal + completion, as measured.
STRICTLY READ-ONLY: kv_store.get of the cached baselines + the persisted
snapshot. No measurement is re-run (that would write the cache)."""
import json
import kv_store

c = (kv_store.get("csm:baseline_cache") or {})
p = c.get("payload") or {}
print("cache date:", c.get("date"))
b1 = p.get("b1_renewal") or {}
for k in ("value", "lower_bound", "n_decided", "n_renewed", "n_not_renewed",
          "n_ambiguous", "confidence_pm", "label", "bound_note"):
    print(f"{k}: {b1.get(k)}")
print("churned_undated:", b1.get("churned_undated"))
print("cohort:")
for e in b1.get("cohort") or []:
    print("  ", json.dumps(e, default=str))
print("edge_cases:")
for e in b1.get("edge_cases") or []:
    print("  ", json.dumps(e, default=str)[:220])
itc = p.get("b1_in_term_completion") or {}
print("\ncompletion:", json.dumps({k: itc.get(k) for k in (
    "value", "label", "skipped_missing_fields", "rows")}, default=str)[:1500])

from snapshot import load_persisted
snap = load_persisted() or {}
act = ((snap.get("active_clients") or {}).get("active") or [])
print("\nactive clients:", len(act))
keys = {}
for a in act:
    for k, v in a.items():
        if v not in (None, "", 0):
            keys[k] = keys.get(k, 0) + 1
print("populated fields:", json.dumps(keys))
won = ((snap.get("sales") or {}).get("won_businesses") or [])
print("won_businesses:", len(won), "sample keys:",
      list(won[0].keys()) if won and isinstance(won[0], dict) else type(won[0]).__name__ if won else None)
ch = (snap.get("client_health") or {}).get("clients") or []
print("client_health rows:", len(ch), "sample keys:", list(ch[0].keys()) if ch else None)
