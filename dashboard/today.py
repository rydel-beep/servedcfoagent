"""today.py — TODAY: "are we winning?" in ten seconds (the finish line, Part 2).

Eight tiles, one verdict line, three short lists. Nothing else — the rule is
that anything which does not help answer the question in ten seconds belongs
on another page.

THE TILES ARE MOVED, NEVER RECOMPUTED. Six of the eight are lifted straight
out of `exec_top.build_tiles()` — the same objects the landing renders, from
the same kv caches, written by the same scheduled loop. A second engine
computing "cash on hand" a second way is exactly how the estate came to say
100% and 70% for one show rate, so this module does not own a single number
it could have borrowed.

The two tiles TODAY adds — this week's leads and consults, and ad spend vs
plan — are computed on the refresh loop like everything else and READ here.
The request path never calls Stripe, Xero, Meta, the CRM or a sheet.

Every tile carries a 30-day trend and a vs-plan delta. Both are honest: the
trend draws only where day-level history supports it, and the delta names
what it is comparing against — the committed plan when one exists, the prior
period when one does not.
"""

from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

K_WEEK = "today:cache:week"        # this week's leads + consults booked
K_SPEND = "today:cache:spend"      # ad spend MTD vs plan
K_TRAVEL = "today:cache:travelling"  # the travelling verdict line
K_TRENDS = "today:cache:trends"    # the day-level 30-day series per tile
K_LASTSEEN = "today:last_seen"     # {user: iso} — for "since you last looked"

# The eight, in the order Rydel reads them. Six are MOVED from exec_top.
MOVED_TILES = ("cash_on_hand", "committed_mrr", "ar_outstanding",
               "cash_net_mtd", "ltv_cac", "ltgp_cac")

# tile id → (history field for the trend, plan key, polarity, unit)
TREND_SPEC = {
    "cash_on_hand":  ("cash_position.cash_in_bank", "", "gain", "money"),
    "committed_mrr": ("client_health.current_mrr", "net_mrr", "gain", "money"),
    "ar_outstanding": ("", "", "cost", "money"),
    "cash_net_mtd":  ("", "cash_in", "gain", "money"),
    "ltv_cac":       ("", "", "gain", "ratio"),
    "ltgp_cac":      ("", "", "gain", "ratio"),
    "week_flow":     ("", "leads", "gain", "count"),
    "ad_spend":      ("", "spend", "cost", "money"),
}


# ── the refresh loop's share (never the request path) ───────────────────────

def refresh_cache() -> dict:
    """Compute the two tiles TODAY adds, plus the travelling verdict. Rides
    the same scheduled loop as every other cache; each block is guarded, so
    one failing source degrades its own tile and nothing else."""
    out = {}

    def _wrap(fn, label):
        try:
            return {"computed_at": now_sydney().isoformat(), "data": fn(),
                    "error": None}
        except Exception as e:  # noqa: BLE001
            logger.warning("today cache %s failed: %s", label, e)
            return {"computed_at": now_sydney().isoformat(), "data": None,
                    "error": str(e)[:160]}

    def _week():
        """Leads in, and consults booked, since Monday. The setter's week."""
        import travelling
        t = today_sydney()
        w0 = t - dt.timedelta(days=t.weekday())          # Monday
        inw, _all = travelling._lead_rows(w0, t)
        ap = travelling._appointments(w0, t)
        return {"leads": len(inw), "consults_booked": len(ap["booked"]),
                "upcoming": len(ap["upcoming"]),
                "week_start": str(w0), "as_of": str(t)}

    def _spend():
        """Meta spend month-to-date, against the plan or the month before."""
        import meta_spend
        t = today_sydney()
        m0 = t.replace(day=1)
        cur = (meta_spend.spend_in_range(str(m0), str(t)) or {}).get("spend")
        prev_end = m0 - dt.timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        # the same number of days into last month, so it compares like for like
        prev_same = min(prev_start + dt.timedelta(days=(t - m0).days), prev_end)
        prev = (meta_spend.spend_in_range(str(prev_start), str(prev_same))
                or {}).get("spend")
        return {"mtd": cur, "prior_same_days": prev,
                "days_in": (t - m0).days + 1,
                "prior_window": f"{prev_start} → {prev_same}"}

    def _travel():
        import travelling
        d = travelling.build(window="mtd", compare="usual")
        return {"verdict": d.get("verdict"),
                "top_gap": (d.get("gaps") or [{}])[0].get("sentence")}

    out["week"] = _wrap(_week, "week")
    kv_store.put(K_WEEK, out["week"])
    out["spend"] = _wrap(_spend, "spend")
    kv_store.put(K_SPEND, out["spend"])
    out["travelling"] = _wrap(_travel, "travelling")
    kv_store.put(K_TRAVEL, out["travelling"])

    def _trends():
        """Day-level history is a 38 MB file read line by line — that is
        loop work, not page-load work. TODAY reads the answer."""
        import trend
        return {tid: trend.sparkline(field, 30)
                for tid, (field, _p, _pol, _u) in TREND_SPEC.items() if field}
    out["trends"] = _wrap(_trends, "trends")
    kv_store.put(K_TRENDS, out["trends"])
    logger.info("today caches refreshed: %s",
                {k: ("err" if v.get("error") else "ok") for k, v in out.items()})
    return out


# ── the request path (reads only) ───────────────────────────────────────────

def _runway_days(snap: dict) -> tuple[str, float | None]:
    cp = (snap or {}).get("cash_position") or {}
    months = cp.get("runway_months")
    if months is None:
        return "runway not computed", None
    days = round(float(months) * 30.44)
    return f"{days} days of runway on recurring burn", float(months)


def build(snap: dict | None, owner: bool) -> dict:
    """Everything TODAY renders, server-side. Guarded end to end: the page
    degrades a tile, never the page."""
    from dashboard import exec_top
    import trend

    snap = snap or {}
    tiles: list[dict] = []

    # ── the six MOVED tiles ──
    try:
        by_id = {t["id"]: t for t in exec_top.build_tiles(snap)}
    except Exception as e:  # noqa: BLE001
        logger.exception("today: exec tiles unavailable")
        by_id = {}
    for tid in MOVED_TILES:
        t = by_id.get(tid)
        if not t:
            tiles.append(exec_top._tile(
                tid, tid.replace("_", " ").title(), "—",
                "this tile's engine did not report", "", "degraded"))
            continue
        tiles.append(dict(t))     # a copy — TODAY never mutates the landing's

    # cash on hand carries runway days beside it (the spec's one addition)
    if tiles and tiles[0]["id"] == "cash_on_hand":
        line, _months = _runway_days(snap)
        tiles[0]["sub"] = f"{line} · {tiles[0]['sub']}"

    # ── the two TODAY adds ──
    wk = kv_store.get(K_WEEK) or {}
    wkd, wkerr = wk.get("data"), wk.get("error")
    if wkd:
        tiles.append(exec_top._tile(
            "week_flow", "Leads and consults this week",
            f"{wkd['leads']} leads · {wkd['consults_booked']} consults",
            (f"booked since Monday {wkd['week_start']}"
             f" · {wkd['upcoming']} still ahead of us"),
            f"one attribution engine + the GHL appointment cache · computed "
            f"{exec_top._fmt_age(exec_top._age_h(wk.get('computed_at')))}",
            exec_top._state_for(exec_top._age_h(wk.get("computed_at")), None),
            drawer=None, raw=wkd["leads"]))
    else:
        tiles.append(exec_top._tile(
            "week_flow", "Leads and consults this week", "—",
            wkerr or "not yet computed — first refresh pending", "", "degraded"))

    sp = kv_store.get(K_SPEND) or {}
    spd, sperr = sp.get("data"), sp.get("error")
    if spd and spd.get("mtd") is not None:
        tiles.append(exec_top._tile(
            "ad_spend", "Ad spend (month to date)",
            exec_top._fmt_money(spd["mtd"], cents=False),
            f"{spd['days_in']} days in · Meta, the only paid channel running",
            f"Meta ad archive · computed "
            f"{exec_top._fmt_age(exec_top._age_h(sp.get('computed_at')))}",
            exec_top._state_for(exec_top._age_h(sp.get("computed_at")), None),
            drawer=None, raw=spd["mtd"]))
    else:
        tiles.append(exec_top._tile(
            "ad_spend", "Ad spend (month to date)", "—",
            sperr or "not yet computed — first refresh pending", "", "degraded"))

    # ── trend + delta on every tile ──
    cached_trends = (kv_store.get(K_TRENDS) or {}).get("data") or {}
    for t in tiles:
        field, plan_key, polarity, unit = TREND_SPEC.get(t["id"], ("", "", "gain", "money"))
        t["trend"] = cached_trends.get(t["id"]) or {
            "points": [], "days": 0,
            "note": ("no day-level history is kept for this one yet" if not field
                     else "the trend has not been computed yet — first refresh pending")}
        try:
            ref_actual = t.get("raw")
            if t["id"] == "ad_spend" and spd:
                d = trend.delta(spd.get("mtd"), "", plan_key, polarity, unit)
                if d.get("value") is None and spd.get("prior_same_days") is not None \
                        and spd.get("mtd") is not None:
                    diff = spd["mtd"] - spd["prior_same_days"]
                    d = {"state": "bad" if diff > 0 else "good",
                         "word": (f"${abs(diff):,.0f} "
                                  f"{'over' if diff > 0 else 'under'} the same days "
                                  f"last month"),
                         "basis": spd["prior_window"], "value": round(diff, 2)}
            elif t["id"] == "week_flow" and wkd:
                d = {"state": "flat", "word": "no committed plan to pace against",
                     "basis": "plan", "value": None}
            else:
                d = _delta_from_cache(ref_actual, cached_trends.get(t["id"]),
                                      plan_key, polarity, unit)
            t["delta"] = d
        except Exception as e:  # noqa: BLE001
            t["delta"] = {"state": "flat", "word": f"comparison unavailable ({str(e)[:40]})",
                          "basis": "", "value": None}

    # ── the verdict line (a door to travelling) ──
    tv = kv_store.get(K_TRAVEL) or {}
    tvd = tv.get("data") or {}
    verdict = {
        "line": tvd.get("verdict") or (
            tv.get("error") or "the month's read is not yet computed — "
            "first refresh pending (labelled, not blank)"),
        "gap": tvd.get("top_gap") or "",
        "href": "/dashboard/scale/travelling",
        "state": "degraded" if not tvd.get("verdict") else "ok",
        "age": exec_top._fmt_age(exec_top._age_h(tv.get("computed_at"))),
    }

    return {
        "tiles": tiles[:8],
        "verdict": verdict,
        "rulings": _rulings(owner),
        "since": _since_you_last_looked(owner),
        "pulse": _pulse(),
        "today": str(today_sydney()),
        "snapshot_age": exec_top._fmt_age(exec_top._age_h(snap.get("generated_at"))),
    }


def _delta_from_cache(actual, spark, plan_key, polarity, unit):
    """The same comparison trend.delta makes, but off the series the loop
    already computed — so the page never re-reads the history file."""
    import trend as _t
    if actual is None:
        return {"state": "flat", "word": "no figure to compare", "basis": "none",
                "value": None}
    row = _t._plan_for_month(str(today_sydney())[:7]) if plan_key else None
    if row and row.get(plan_key) is not None:
        ref, basis = row[plan_key], f"the committed plan (v{row.get('_version')})"
    elif spark and spark.get("first") is not None:
        ref = spark["first"]
        basis = f"where it stood on {(spark.get('span') or '').split(' → ')[0]}"
    else:
        return {"state": "flat", "word": "nothing to compare against yet",
                "basis": "no plan committed and not enough history", "value": None}
    diff = actual - ref
    mag = (f"${abs(diff):,.0f}" if unit == "money"
           else f"{abs(diff):.2f}×" if unit == "ratio"
           else f"{abs(diff):,.0f}")
    if abs(diff) < (abs(ref) * 0.005 if ref else 0.005):
        return {"state": "flat", "word": f"level with {basis}", "basis": basis,
                "value": round(diff, 2)}
    if polarity == "cost":
        return {"state": "bad" if diff > 0 else "good",
                "word": f"{mag} {'over' if diff > 0 else 'under'} {basis}",
                "basis": basis, "value": round(diff, 2)}
    return {"state": "good" if diff > 0 else "bad",
            "word": f"{mag} {'above' if diff > 0 else 'below'} {basis}",
            "basis": basis, "value": round(diff, 2)}


def _rulings(owner: bool) -> dict:
    """Needs your ruling — the count, and the top three NAMED."""
    if not owner:
        return {"count": None, "cards": [], "hidden": True}
    try:
        # from the kv cache the loop writes — building the cards is an engine
        # call and must never happen on a page load.
        cached = (kv_store.get("exec:cache:decisions") or {}).get("data") or {}
        if cached.get("top3") is not None:
            return {"count": cached.get("count"), "hidden": False,
                    "cards": cached.get("top3") or [],
                    "href": "/dashboard/view/decisions"}
        import decision_cards
        cards = (decision_cards.build_cards() or {}).get("cards") or []
        def _why(c):
            # `evidence` is a dict on several card kinds — the one action
            # line is the sentence a human reads, so use that.
            for key in ("action", "missing", "known"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    return v[:110]
            return ""
        # NOT "items" — jinja resolves `x.items` to dict.items and the page
        # 500s. Third time this collision has bitten the codebase (`c.values`
        # in #156, `nav.items` earlier in this wave); a test now forbids it.
        return {"count": len(cards), "hidden": False,
                "cards": [{"title": c.get("title"), "why": _why(c)}
                          for c in cards[:3]],
                "href": "/dashboard/view/decisions"}
    except Exception as e:  # noqa: BLE001
        logger.info("today: rulings unavailable: %s", e)
        return {"count": None, "cards": [], "hidden": False,
                "error": f"the ruling queue did not answer ({str(e)[:70]})"}


def _since_you_last_looked(owner: bool) -> dict:
    """Shown only when the last visit was more than a day ago — otherwise it
    is noise on a page whose whole job is ten seconds."""
    from dashboard.auth import current_actor
    try:
        user = (current_actor() or {}).get("user") or "rydel"
    except Exception:
        user = "rydel"
    marks = kv_store.get(K_LASTSEEN) or {}
    last = marks.get(user)
    now = now_sydney()
    marks[user] = now.isoformat()
    try:
        kv_store.put(K_LASTSEEN, marks)
    except Exception:
        pass
    if not last:
        return {"show": False, "reason": "first visit recorded"}
    try:
        gap_h = (now - dt.datetime.fromisoformat(last)).total_seconds() / 3600.0
    except Exception:
        return {"show": False, "reason": "last visit unreadable"}
    if gap_h < 24:
        return {"show": False, "reason": f"last looked {gap_h:.0f}h ago"}
    items = []
    try:
        import collab
        d = collab.digest(user, advance=False)      # peek: never consumes it
        for kind in ("concern", "question", "done", "action"):
            for e in (d.get(kind) or [])[:2]:
                items.append(f"Piolo {kind}: {(e.get('body') or '')[:90]}")
    except Exception as e:  # noqa: BLE001
        logger.info("today: digest unavailable: %s", e)
    return {"show": True, "gap_h": round(gap_h, 1), "last": last,
            "lines": items[:5],
            "note": (f"you last looked {gap_h / 24:.0f} days ago"
                     if gap_h >= 48 else "you last looked yesterday")}


def _pulse() -> list[dict]:
    """The sales pulse strip — the SAME three the landing carries, from the
    same cache. Show rate is on the confirmed basis with its range, because
    there is one show-basis rule now (travelling.show_basis)."""
    from dashboard import exec_top
    try:
        return exec_top.build_pulse()
    except Exception as e:  # noqa: BLE001
        logger.info("today: pulse unavailable: %s", e)
        return []
