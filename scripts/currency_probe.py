"""Phase-0 CURRENCY PROBE (2026-09-17) — read-only. Enumerates every job's
last-success signal: kv key ages, snapshot source freshness, mirror sync
state, MRR snapshot continuity, GHL mirror recency + per-day activity,
tracker per-day cadence (for the gap detector), sentinel state.

ZERO writes: no kv puts, no syncs triggered, no external calls except the
local Postgres + the persisted snapshot. GHL/Sheets/Stripe/Xero untouched.
"""
import json
import datetime as dt

import db
from helpers import today_sydney

out = {"probe_at": str(today_sydney())}

# 1 ── every kv key's last touch (the master currency signal)
try:
    with db.get_conn() as c:
        rows = c.execute("SELECT k, updated_at FROM kv_store ORDER BY k").fetchall()
    keys = [{"k": r["k"], "at": str(r["updated_at"])[:16]} for r in rows]
    out["kv_key_count"] = len(keys)
    # group by prefix for the digest; full list only for stale ones
    today = today_sydney()
    stale, fresh_prefixes = [], {}
    for k in keys:
        try:
            age = (today - dt.date.fromisoformat(k["at"][:10])).days
        except ValueError:
            age = None
        pref = k["k"].split(":")[0]
        cur = fresh_prefixes.setdefault(pref, {"n": 0, "newest": "", "oldest": "9999"})
        cur["n"] += 1
        cur["newest"] = max(cur["newest"], k["at"])
        cur["oldest"] = min(cur["oldest"], k["at"])
        if age is not None and age > 3 and not any(
                k["k"].startswith(p) for p in ("sentinel:L", "ads_truth:sweep")):
            stale.append({**k, "age_days": age})
    out["kv_prefix_digest"] = fresh_prefixes
    stale.sort(key=lambda x: -(x["age_days"] or 0))
    out["kv_stale_keys_gt3d"] = stale[:80]
except Exception as e:
    out["kv_error"] = str(e)[:200]

# 2 ── snapshot source freshness + degraded
try:
    from snapshot import load_persisted
    snap = load_persisted() or {}
    out["snapshot"] = {
        "generated_at": snap.get("generated_at"),
        "degraded": snap.get("degraded"),
        "source_freshness": snap.get("source_freshness"),
        "refresh_health": snap.get("refresh_health"),
    }
except Exception as e:
    out["snapshot_error"] = str(e)[:200]

# 3 ── tracker sheet-mirror sync state
try:
    import sheet_mirror
    out["sheet_mirror"] = sheet_mirror.status() if hasattr(sheet_mirror, "status") else None
    if out["sheet_mirror"] is None:
        import tracker_read
        out["sheet_mirror"] = tracker_read.sync_state()
except Exception as e:
    out["sheet_mirror_error"] = str(e)[:200]

# 4 ── MRR snapshot continuity (last 40 days)
try:
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT snap_date, current_mrr, client_count FROM mrr_snapshots "
            "WHERE snap_date > current_date - 45 ORDER BY snap_date").fetchall()
    dates = [str(r["snap_date"]) for r in rows]
    missing = []
    d = today_sydney() - dt.timedelta(days=44)
    while d <= today_sydney():
        if str(d) not in dates:
            missing.append(str(d))
        d += dt.timedelta(days=1)
    out["mrr_snapshots"] = {"have": len(dates), "first": dates[0] if dates else None,
                            "last": dates[-1] if dates else None,
                            "missing_days": missing,
                            "latest": dict(rows[-1]) if rows else None}
except Exception as e:
    out["mrr_error"] = str(e)[:200]

# 5 ── GHL mirror recency + per-day opportunity creation (gap detector, GHL side)
try:
    with db.get_conn() as c:
        r = c.execute("SELECT count(*) n, max(updated_at) mx, max(created_at) mxc "
                      "FROM ghl_opportunities").fetchone()
        out["ghl_mirror"] = {"opps": r["n"], "max_updated": str(r["mx"]),
                             "max_created": str(r["mxc"])}
        rows = c.execute(
            "SELECT date(created_at) d, count(*) n FROM ghl_opportunities "
            "WHERE created_at > current_date - 75 GROUP BY 1 ORDER BY 1").fetchall()
        out["ghl_opps_by_day"] = {str(r["d"]): r["n"] for r in rows}
        r2 = c.execute("SELECT count(*) n, max(date_updated) mx FROM ghl_contacts").fetchone()
        out["ghl_mirror"]["contacts"] = r2["n"]
        out["ghl_mirror"]["contacts_max_updated"] = str(r2["mx"])
except Exception as e:
    out["ghl_mirror_error"] = str(e)[:200]

# 6 ── tracker per-day cadence from the READ mirror (gap detector, tracker side)
try:
    import sales_analytics_pull as sap
    rows = None
    for fn in ("_rows", "_sheet_rows", "raw_rows", "get_rows"):
        if hasattr(sap, fn):
            try:
                rows = getattr(sap, fn)()
                break
            except TypeError:
                pass
    if rows is None:
        import tracker_read
        st = tracker_read.sync_state()
        out["tracker_note"] = f"no bulk row fn on sales_analytics_pull; sync_state={st}"
    else:
        def daily(idx):
            counts = {}
            for r in rows:
                if len(r) > idx and r[idx]:
                    ds = str(r[idx]).strip()[:20]
                    counts[ds] = counts.get(ds, 0) + 1
            return counts
        out["tracker_daily_raw"] = {"input_col1": daily(1), "set_col13": None,
                                    "close_col27": daily(27),
                                    "n_rows": len(rows)}
except Exception as e:
    out["tracker_error"] = str(e)[:200]

# 7 ── sentinel state
try:
    import kv_store
    for k in ("sentinel:state", "sentinel:cost", "sentinel:metrics",
              "sentinel:escalations", "csm:sentinel", "renewal:last_scan_meta",
              "projection:config", "forecast:assumptions"):
        v = kv_store.get(k)
        if v is not None:
            s = json.dumps(v, default=str)
            out.setdefault("kv_values", {})[k] = (json.loads(s) if len(s) < 3000
                                                  else s[:3000] + "...TRUNC")
except Exception as e:
    out["sentinel_error"] = str(e)[:200]

print(json.dumps(out, indent=1, default=str))
