"""
scripts/verify_ra2.py — R-A2 strategy-migration PROD probe (read-only).
Run in the container: python3 -m scripts.verify_ra2

Live adset census (ids + names + active ads + 7d spend — the mapping
candidates) · lane counts under R-A2 · the due cohort · sets_overview
partition (with a TEMPORARY in-process mapping if none configured — never
persisted) · broad-vs-targeted availability · sentinel first run · perf.
"""
import collections
import datetime as dt
import json
import time


def main():
    out = {}
    import ads_lifecycle as L
    from helpers import today_sydney
    today = today_sydney()

    # ── live adset census (the mapping candidates) ───────────────────────────
    es = L._entity_store()
    ss = L._spend_store()
    days = ss.get("days") or {}
    spend7 = collections.Counter()
    active_ads = collections.Counter()
    for i in range(7):
        d = str(today - dt.timedelta(days=i))
        for aid, row in (days.get(d) or {}).items():
            sp = float(row.get("spend") or 0)
            if sp > 0:
                e = ((es.get("ads") or {}).get(aid)
                     or (es.get("extras") or {}).get(aid) or {})
                sid = str(e.get("adset_id") or "__none__")
                spend7[sid] += sp
                active_ads[sid] += 0    # ensure key
    names = {}
    ads_per_set = collections.Counter()
    for aid, a in (((es.get("ads") or {}) | (es.get("extras") or {}))).items():
        sid = str(a.get("adset_id") or "")
        if sid:
            names[sid] = a.get("adset_name") or ""
            ads_per_set[sid] += 1
    census = [{"adset_id": sid, "name": names.get(sid, ""),
               "ads_listed": ads_per_set.get(sid, 0),
               "spend_7d": round(sp, 2)}
              for sid, sp in spend7.items() if sid != "__none__"]
    census.sort(key=lambda r: -r["spend_7d"])
    out["live_adsets_7d"] = census
    out["mapping_configured"] = L.set_roles_map()

    # ── the R-A2 block live ──────────────────────────────────────────────────
    import roster_engine
    t0 = time.time()
    r_all, meta_all = roster_engine.load_result(L.ALL_DAYS, None, None,
                                                basis="cohort", market=None)
    creatives_all = [c for c in (r_all.get("creatives") or [])
                     if c.get("tier") == "ad"]
    t0 = time.time()
    block = L.build_block(creatives_all, record_render=True)
    out["block_build_s"] = round(time.time() - t0, 3)
    lanes = collections.Counter(c["lane"] for c in block["cards"].values())
    out["lane_counts"] = dict(lanes)
    out["strategy"] = {k: v for k, v in (block.get("rules") or {}).items()}
    due = [(k, (c.get("review") or {}).get("cycle_day"))
           for k, c in block["cards"].items() if c["lane"] == "due_for_review"]
    out["due_cohort_n"] = len(due)
    out["due_sample"] = due[:6]
    out["injected_n"] = sum(1 for c in block["cards"].values() if c.get("injected"))
    out["pull_flagged_n"] = sum(1 for c in block["cards"].values()
                                if c.get("pull_flags"))
    out["review_flags"] = L.review_flags(creatives_all, block=block)

    # ── sets_overview partition (temp in-process mapping if unconfigured) ────
    seeded = False
    if not L.set_roles_map() and census:
        # TEMPORARY, in-process only (kv monkeypatched) — proves the rollup +
        # partition against real archive data without persisting any mapping
        seeded = True
        tmp = {}
        roles_cycle = ["broad_video", "targeted_video", "graphics", "retargeting"]
        for i, row in enumerate(census[:4]):
            tmp[row["adset_id"]] = roles_cycle[i % 4]
        L.set_roles_map = (lambda _m=tmp: _m)      # in-process shadow only
    t0 = time.time()
    sv = L.sets_overview(creatives_all, creatives_all)
    out["sets_overview_s"] = round(time.time() - t0, 3)
    out["sets_partition"] = sv.get("partition")
    out["sets_roles_summary"] = {
        r: {"creatives": v["creatives"], "actual_window": v["actual_window"],
            "actual_yesterday": v["actual_yesterday"],
            "budget_drift": v["budget_drift"],
            "ranking_n": len(v.get("ranking") or [])}
        for r, v in (sv.get("roles") or {}).items()}
    out["sets_unmapped_n"] = len(sv.get("unmapped") or [])
    out["partition_probe_mapping"] = ("TEMPORARY in-process (not persisted)"
                                      if seeded else "configured mapping")
    bt = L.broad_vs_targeted(creatives_all)
    out["broad_vs_targeted"] = {"available": bt.get("available"),
                                "reason": bt.get("reason"),
                                "pairs": len(bt.get("pairs") or []),
                                "shared": bt.get("shared_creatives")}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
