"""
launch_date_probe.py — READ-ONLY Phase-1 probe for the LAUNCH LINEAGE build (D1).

For a sample of ads with recent delivery, pull the THREE candidate "launch" dates:
  1. created_time        — the ad object's creation date (Meta /{ad_id})
  2. adset start_time    — the scheduled/effective start (Meta /{adset_id})
  3. first-impression    — the first day insights shows delivery (monthly sweep →
                           daily zoom; the D1 ground truth for "launched")
and quantify how often/by how much they diverge. Also confirms daily-granularity
insights are retrievable over an ad's lifetime (constrains active-day counting).

GET-only, ads_read scope. Run with the server env: `railway run python3 scripts/launch_date_probe.py`
Writes dashboard/audit_artifacts/launch_probe.json (no tokens, no PII — ad ids/names/dates only).
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import META_ACCESS_TOKEN, META_API_VERSION  # noqa: E402

BASE = f"https://graph.facebook.com/{META_API_VERSION}"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "dashboard", "audit_artifacts", "launch_probe.json")
SAMPLE_N = int(os.getenv("PROBE_SAMPLE", "25"))


def get(path, params):
    params = dict(params or {})
    params["access_token"] = META_ACCESS_TOKEN
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}/{path}", params=params, timeout=(5, 20))
            if r.status_code == 200:
                return r.json(), None
            err = {}
            try:
                err = r.json().get("error", {})
            except ValueError:
                pass
            if r.status_code not in (500, 502, 503) and err.get("code") not in (1, 2, 4, 17, 613, 80004):
                return None, f"HTTP {r.status_code} code={err.get('code')}: {err.get('message', '')[:120]}"
        except requests.RequestException as e:
            pass
        time.sleep(2 * (attempt + 1))
    return None, "retries exhausted"


def first_delivery(ad_id):
    """Monthly lifetime sweep → first month with impressions → daily zoom in that month."""
    j, err = get(f"{ad_id}/insights", {
        "fields": "impressions,spend", "time_increment": "monthly",
        "date_preset": "maximum", "limit": 100})
    if j is None:
        return None, None, f"monthly insights failed: {err}"
    months = [r for r in j.get("data", []) if float(r.get("impressions") or 0) > 0]
    if not months:
        return None, 0, "no delivery ever (lifetime impressions = 0)"
    m0 = months[0]
    j2, err2 = get(f"{ad_id}/insights", {
        "fields": "impressions,spend", "time_increment": 1, "limit": 100,
        "time_range": json.dumps({"since": m0["date_start"], "until": m0["date_stop"]})})
    if j2 is None:
        return None, None, f"daily zoom failed: {err2}"
    daily = [r for r in j2.get("data", []) if float(r.get("impressions") or 0) > 0]
    lifetime_active_months = {r["date_start"][:7] for r in months}
    return (daily[0]["date_start"] if daily else m0["date_start"],
            len(lifetime_active_months), None)


def main():
    if not META_ACCESS_TOKEN:
        print("no META_ACCESS_TOKEN in env — run under `railway run`")
        sys.exit(1)
    spend = json.load(open("state/meta_ad_spend_daily.json"))
    days = spend.get("days") or {}
    ds = sorted(days.keys())
    first_in_store = {}
    for d in ds:
        for aid, row in (days[d] or {}).items():
            if float(row.get("spend") or 0) > 0 or int(row.get("impressions") or 0) > 0:
                first_in_store.setdefault(aid, d)
    # sample: prioritise left-censored ads (their true launch predates the store),
    # then the most recent launches (freshest divergence data)
    censored = [a for a, d in first_in_store.items() if d == ds[0]]
    fresh = sorted((a for a in first_in_store if a not in censored),
                   key=lambda a: first_in_store[a], reverse=True)
    sample = (censored + fresh)[:SAMPLE_N]
    rows, errors = [], []
    for aid in sample:
        meta, err = get(aid, {"fields": "id,name,created_time,effective_status,"
                                        "adset{id,start_time,end_time}"})
        if meta is None:
            errors.append({"ad_id": aid, "step": "entity", "err": err})
            continue
        fd, active_months, ferr = first_delivery(aid)
        rows.append({
            "ad_id": aid, "name": (meta.get("name") or "")[:60],
            "created_time": (meta.get("created_time") or "")[:10],
            "adset_start_time": ((meta.get("adset") or {}).get("start_time") or "")[:10],
            "first_delivery": fd,
            "first_delivery_err": ferr,
            "lifetime_active_months": active_months,
            "first_in_90d_store": first_in_store.get(aid),
            "store_censored": aid in censored,
            "status": meta.get("effective_status"),
        })
        time.sleep(0.3)
    out = {"probed_at": time.strftime("%Y-%m-%d %H:%M"), "store_min_day": ds[0],
           "sample_n": len(rows), "rows": rows, "errors": errors}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    # divergence summary
    div_cs, div_cf = [], []
    for r in rows:
        if r["created_time"] and r["first_delivery"]:
            import datetime as dt
            c = dt.date.fromisoformat(r["created_time"])
            f0 = dt.date.fromisoformat(r["first_delivery"])
            div_cf.append((f0 - c).days)
    print(f"probed {len(rows)} ads, {len(errors)} errors → {OUT}")
    if div_cf:
        div_cf.sort()
        n = len(div_cf)
        nonzero = sum(1 for d in div_cf if d != 0)
        print(f"created→first-delivery gap days: min {div_cf[0]} · median {div_cf[n//2]} · "
              f"max {div_cf[-1]} · nonzero {nonzero}/{n}")


if __name__ == "__main__":
    main()
