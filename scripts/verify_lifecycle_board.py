"""
scripts/verify_lifecycle_board.py — Board v2 PROD verification probe
(read-only). Run inside the Railway container:  python3 scripts/verify_lifecycle_board.py

Prints a JSON report: rules · store freshness · 10-ad status sample (triad vs
raw effective_status + delivery buckets) · lane counts · kill-lane==kill-cards
consolidation · a live TESTING progress example · EDITH drill answers ·
sentinel lifecycle_watch first run · timings.
"""
import json
import random
import time
from datetime import timedelta

import ads_lifecycle as L


def main():
    out = {}
    rl = L.rules()
    out["rules"] = rl
    es = L._entity_store()
    ss = L._spend_store()
    out["stores"] = {
        "entities": len(es.get("ads") or {}),
        "spend_days": len(ss.get("days") or {}),
        "refreshed_min_ago": round((time.time() - float(ss.get("refreshed_at") or 0)) / 60, 1),
    }

    import roster_engine
    t0 = time.time()
    r_all, meta_all = roster_engine.load_result(L.ALL_DAYS, None, None,
                                                basis="cohort", market=None)
    out["all_time_load_s"] = round(time.time() - t0, 3)
    out["all_time_served_from"] = meta_all.get("served_from")
    creatives = [c for c in (r_all.get("creatives") or []) if c.get("tier") == "ad"]
    out["ad_creatives"] = len(creatives)

    # STATUS TRUTH: 10 sampled ads — triad vs raw status + delivery buckets
    from helpers import today_sydney
    random.seed(7)
    sample = random.sample(creatives, min(10, len(creatives)))
    recent = [str(today_sydney() - timedelta(days=i))
              for i in range(int(rl["freshness_days"]))]
    rows = []
    for c in sample:
        aids = [str(a) for a in (c.get("ad_ids") or [])]
        st = L.status_for(aids, es, ss, rl)
        raw_eff = [((es.get("ads") or {}).get(a) or (es.get("extras") or {}).get(a)
                    or {}).get("effective_status") for a in aids]
        imp = sum(int(float((((ss.get("days") or {}).get(d) or {}).get(a) or {})
                            .get("impressions") or 0))
                  for d in recent for a in aids)
        rows.append({"label": (c.get("label") or "")[:34], "eff": raw_eff,
                     "recent_impressions": imp, "triad": st["status"],
                     "reason": (st.get("reason") or "")[:70],
                     "layer": st.get("layer")})
    out["status_sample"] = rows

    # lane truth + the consolidation, on the live block
    t0 = time.time()
    block = L.build_block(creatives, record_render=True)
    out["block_build_s"] = round(time.time() - t0, 3)
    lanes = {}
    statuses = {}
    for card in block["cards"].values():
        lanes[card["lane"]] = lanes.get(card["lane"], 0) + 1
        s = card["status"]["status"]
        statuses[s] = statuses.get(s, 0) + 1
    out["lane_counts"] = lanes
    out["status_counts"] = statuses
    kills = L.kill_candidate_flags(creatives, limit=50, block=block)
    lane_kill_keys = sorted(k for k, c in block["cards"].items()
                            if c["lane"] == "kill_candidate")
    out["consolidation_ok"] = sorted(f["creative_key"] for f in kills) == lane_kill_keys
    out["kill_cards"] = [{"label": f["creative"][:34], "basis": f["kill_basis"],
                          "headline": f["headline"][:72]} for f in kills[:8]]
    testing = [c for c in block["cards"].values()
               if c["lane"] == "testing" and c.get("rotation")]
    out["testing_examples"] = [t["rotation"]["label"] for t in testing[:3]]

    # EDITH drills (live functions, read-only)
    if creatives:
        name = creatives[0].get("label")
        a1, h1 = L.handle_decision_recall("why did we kill %s?" % name)
        a2, h2 = L.handle_stance_recall("what does the team think of %s?" % name)
        out["edith_kill"] = {"handled": h1, "ans": (a1 or "")[:200]}
        out["edith_team"] = {"handled": h2, "ans": (a2 or "")[:200]}

    # sentinel first run
    t0 = time.time()
    w = L.sentinel_watch()
    out["sentinel_first_run"] = {
        "status_freshness": w.get("status_freshness"),
        "convergence_lag": w.get("convergence_lag"),
        "stage_drift": w.get("stage_drift"),
        "rules_ok": (w.get("rules") or {}).get("ok"),
        "stance_integrity": w.get("stance_integrity"),
        "runtime_s": round(time.time() - t0, 2),
    }
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
