"""
scripts/ground_truth_sweep2.py — GROUND-TRUTH SWEEP 2 (read-only).
Run in the Railway container: python3 -m scripts.ground_truth_sweep2

Sections: A) red-dash diagnosis (witnessed rows) · B) per-ad spend truth for
3 boxes vs FRESH Meta pulls (closed days cent-exact; today = intraday) ·
C) status truth: pre- vs post- forced entity refresh · D) archive
reconciliation · E) contract-value tile re-proof (tile == drill) ·
F) freshness-stamp truth · G) preview-link sample.
Every comparison row carries IDs. GETs only.
"""
import json
import re
import time
from datetime import timedelta

import ads_lifecycle as L
import meta_entities as ME
import meta_range as MR
from helpers import today_sydney


def main():
    out = {}
    rl = L.rules()
    today = today_sydney()

    # ── A · red-dash diagnosis: window rows vs lifecycle cards + witnessed rows
    import attribution_engine as AE
    r30 = AE.compute(days=30, basis="cohort")
    win_ads = [c for c in (r30.get("creatives") or []) if c.get("tier") == "ad"]
    import roster_engine
    r_all, meta_all = roster_engine.load_result(L.ALL_DAYS, None, None,
                                                basis="cohort", market=None)
    creatives_all = [c for c in (r_all.get("creatives") or []) if c.get("tier") == "ad"]
    block = L.build_block(creatives_all, record_render=True)
    cards = block["cards"]
    missing = [{"key": c["creative_key"], "label": (c.get("label") or "")[:40]}
               for c in win_ads if c["creative_key"] not in cards]
    out["A_window_rows"] = len(win_ads)
    out["A_rows_without_card"] = missing            # these rendered the red dash
    es = L._entity_store()
    ss = L._spend_store()
    witnessed = []
    pat = re.compile(r"(^|\b)G\d|Q326|graphic", re.I)
    for c in creatives_all:
        if not pat.search(c.get("label") or ""):
            continue
        st = L.status_for(c.get("ad_ids") or [], es, ss, rl)
        eff = [((es.get("ads") or {}).get(str(a)) or (es.get("extras") or {}).get(str(a))
                or {}).get("effective_status") for a in (c.get("ad_ids") or [])]
        witnessed.append({"label": (c.get("label") or "")[:44],
                          "key": c.get("creative_key"), "eff": eff,
                          "now_renders": st["label"], "reason": st["reason"][:80],
                          "had_card": c["creative_key"] in cards})
    out["A_witnessed_rows"] = witnessed[:25]

    # ── B · per-ad spend truth: 3 boxes vs FRESH pulls ───────────────────────
    def fresh_pull(s, e):
        res = MR.insights(
            f"{ME._account_id()}/insights",
            {"access_token": ME.META_ACCESS_TOKEN, "level": "ad",
             "fields": "ad_id,spend,impressions", "time_increment": 1, "limit": 500},
            str(s), str(e), ME._get_all, source="ground_truth_sweep2")
        agg = {}
        for r in res["rows"]:
            a = agg.setdefault(r["ad_id"], {"spend": 0.0, "impressions": 0})
            a["spend"] += float(r.get("spend") or 0)
            a["impressions"] += int(float(r.get("impressions") or 0))
        return agg, res["degraded"]

    def compare(box_name, s, e, closed):
        fresh, dg = fresh_pull(s, e)
        store = ME.spend_by_ad_in_range(str(s), str(e))
        sys_ads = store["ads"]
        mism = []
        for aid in set(fresh) | set(sys_ads):
            fs = round((fresh.get(aid) or {}).get("spend", 0.0), 2)
            ss_ = round((sys_ads.get(aid) or {}).get("spend", 0.0), 2)
            fi = (fresh.get(aid) or {}).get("impressions", 0)
            si = (sys_ads.get(aid) or {}).get("impressions", 0)
            if abs(fs - ss_) > 0.005 or fi != si:
                mism.append({"ad_id": aid, "fresh_spend": fs, "system_spend": ss_,
                             "fresh_imp": fi, "system_imp": si})
        return {"box": box_name, "window": f"{s}..{e}", "closed_days": closed,
                "ads_fresh": len(fresh), "ads_system": len(sys_ads),
                "fresh_total": round(sum(a["spend"] for a in fresh.values()), 2),
                "system_total": round(sum(a["spend"] for a in sys_ads.values()), 2),
                "mismatches": mism[:15], "mismatch_count": len(mism),
                "pull_degraded": dg}

    y = today - timedelta(days=1)
    out["B_spend"] = [
        compare("last7_closed", y - timedelta(days=6), y, True),
        compare("last30_closed", y - timedelta(days=29), y, True),
        compare("today_intraday", today, today, False),
    ]

    # ── C · status truth: pre- vs post- forced entity refresh ────────────────
    pre = {k: (c.get("status") or {}).get("status") for k, c in cards.items()}
    t0 = time.time()
    es_fresh = ME.refresh_entity_map(force=True)
    out["C_entity_refresh_s"] = round(time.time() - t0, 2)
    drift = []
    for c in creatives_all:
        key = c.get("creative_key")
        st = L.status_for(c.get("ad_ids") or [], es_fresh, ss, rl)
        if st["status"] != pre.get(key):
            eff = [((es_fresh.get("ads") or {}).get(str(a))
                    or (es_fresh.get("extras") or {}).get(str(a)) or {})
                   .get("effective_status") for a in (c.get("ad_ids") or [])]
            drift.append({"key": key, "label": (c.get("label") or "")[:36],
                          "rendered": pre.get(key), "fresh": st["status"],
                          "fresh_eff": eff})
    counts = {}
    for c in creatives_all:
        s = L.status_for(c.get("ad_ids") or [], es_fresh, ss, rl)["status"]
        counts[s] = counts.get(s, 0) + 1
    out["C_status_counts_fresh"] = counts
    out["C_render_vs_fresh_drift"] = drift[:20]
    out["C_drift_count"] = len(drift)

    # ── D · archive reconciliation (Σ per-ad vs account-level) ───────────────
    out["D_reconcile"] = {
        "7d": ME.reconcile_spend(str(y - timedelta(days=6)), str(y)),
        "30d": ME.reconcile_spend(str(y - timedelta(days=29)), str(y)),
    }

    # ── E · contract tile re-proof: tile == the drill behind it ──────────────
    sb = AE.scoreboard_view(r30)
    tile = (sb.get("headline") or {}).get("contract_total")
    drill = roster_engine.build(days=30, start=None, end=None, basis="cohort",
                                market=None, level="account", key="__account__",
                                metric="closes")
    people = drill.get("people") or []
    drill_sum = round(sum(float(p.get("contract") or 0) for p in people), 2)
    out["E_contract"] = {"tile": tile, "drill_sum": drill_sum,
                         "closes_in_drill": len(people),
                         "missing_contract": sum(1 for p in people
                                                 if p.get("close_date") and
                                                 p.get("contract") is None),
                         "exact": (tile is not None
                                   and round(float(tile), 2) == drill_sum)}

    # ── F · freshness-stamp truth ────────────────────────────────────────────
    st = L.status_for(["1"], es_fresh, ss, rl)
    claimed = None
    m = re.search(r"delivery data (\d+)m old", st.get("as_of") or "")
    if m:
        claimed = int(m.group(1))
    actual = int((time.time() - float(ss.get("refreshed_at") or 0)) / 60)
    out["F_stamp"] = {"claimed_min": claimed, "actual_min": actual,
                      "truthful": claimed is not None and abs(claimed - actual) <= 1}

    # ── G · preview links sample ─────────────────────────────────────────────
    linked = [(aid, a.get("preview_link")) for aid, a in (es_fresh.get("ads") or {}).items()
              if a.get("preview_link")]
    out["G_previews"] = {"ads_with_link": len(linked),
                         "sample": [{"ad_id": a, "link_present": bool(l),
                                     "https": str(l).startswith("https://")}
                                    for a, l in linked[:5]]}

    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
