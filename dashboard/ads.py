"""
ads.py — SERVED AD TRACKING, the dedicated dashboard (AD_DASHBOARD_REPORT).

ISOLATION BY CONSTRUCTION: this blueprint serves ONLY the ad domain. It calls the
attribution engine in-process (no /cfo/* pass-through), so a media_buyer session gets
the full ad picture here while auth.py's fail-closed allowlist 403s every finance
surface. Roles: owner + coo see it; media_buyer (Romano) when MEDIA_BUYER_PASSWORD is
set (SHIPS DISABLED); sales bounced by its own allowlist.

ZERO NEW MATH: /api/board is compute() + scoreboard_view() + the flags module in ONE
atomic payload per window (the toggle fix — one fetch, one render, the window echoed
back for the stale-mix guard). /api/roster filters the SAME engine rows/deals the
counts were built from — roster length == the count, structurally and test-enforced.

Read-only everywhere. GHL notes are fetched live per roster (≤30 contacts, throttled),
labelled with source + stamp; tracker notes come from the mirror with the sheet stamp.
"""
from __future__ import annotations

import logging
import re
import time

from flask import Blueprint, jsonify, render_template, request

from dashboard.auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("ads", __name__)

_STAGES = {
    "leads": lambda r: True,
    "qualified": lambda r: r["qualified"],
    "reached": lambda r: r["qualified"] and r.get("reached"),   # Gate 2 Option A
    "sets": lambda r: r["set"],
    "shows": lambda r: r["show"],
}


ALL_DAYS = 3650   # the "All" window (the tracker's full history fits comfortably)


def _window_args():
    raw = request.args.get("days", 30)
    if str(raw).lower() == "all":
        return ALL_DAYS, request.args.get("start"), request.args.get("end")
    try:
        days = min(max(int(raw), 1), 365)
    except ValueError:
        return None, None, None
    return days, request.args.get("start"), request.args.get("end")


def _basis_arg():
    b = request.args.get("basis", "cohort")
    return b if b in ("cohort", "activity") else "cohort"


def _market_arg():
    """None = all markets; 'au'|'us'|'unknown' = the engine-level filter (I15)."""
    m = (request.args.get("market") or "all").lower()
    return m if m in ("au", "us", "unknown") else None


def _build_board(days, start, end, basis, force=False, market=None):
    """The full board payload — ONE atomic build (window + basis + market echoed for
    the stale-mix guard). Persisted as a rollup keyed (basis, days) for instant
    serves (all-markets only; market views compute directly — they are small)."""
    import attribution_engine
    import attribution_flags
    result = attribution_engine.compute(days=days, start=start, end=end,
                                        force=force, basis=basis, market=market)
    trailing, r90 = None, None
    try:
        if not (start or end):
            r90 = result if days == 90 else attribution_engine.compute(90, basis=basis,
                                                                        market=market)
            attribution_engine.assert_same_basis(result, r90)   # I11: clock purity
            trailing = (r90.get("totals") or {}).get("attribution_rate_pct")
    except ValueError:
        raise
    except Exception as e:
        logger.info("trailing rate unavailable: %s", e)
    sc = attribution_flags.scorecard(result, trailing_attr_rate=trailing)
    identity = None
    try:
        identity = attribution_flags.identity_health(
            result, trailing_result=(r90 if (not (start or end) and days != 90) else None))
        if identity.get("degradation_flag"):
            sc["flags"].insert(0, identity["degradation_flag"])
    except Exception as e:
        logger.info("identity health unavailable: %s", e)
    attribution_flags.record_flag_salience(sc["flags"])
    hygiene = None
    try:
        import close_integrity
        hygiene = close_integrity.latest()
        if hygiene is None or force:
            hygiene = close_integrity.refresh(30)
    except Exception as e:
        logger.info("hygiene block unavailable: %s", e)
    ladder = None
    try:
        import attribution_verdicts
        floor = (result.get("verdict_layer") or {}).get("floor") or 3.0
        ladder = attribution_verdicts.ladder(result, floor)
    except Exception as e:
        logger.info("ladder unavailable: %s", e)
    import attribution_engine as AE
    # THE ACTIVITY CASH STRIP (ADS TRUTH, within #120): the cohort view carries one
    # LABELLED line of activity-clock finance truth — computed by the one engine,
    # never mixed into grid math (it lives outside the grid payload's rows).
    cash_strip = None
    if basis == "cohort" and not (start or end):
        try:
            r_act = attribution_engine.compute(days, basis="activity", market=market)
            sb_act = AE.scoreboard_view(r_act)
            cash_strip = {"cash_total": sb_act["headline"]["cash_total"],
                          "closes_total": sb_act["headline"]["closes_total"],
                          "clock": "activity",
                          "label": (f"cash collected this window (activity clock): "
                                    f"${sb_act['headline']['cash_total']:,.0f} across "
                                    f"{sb_act['headline']['closes_total']} close(s)")}
        except Exception as e:
            logger.info("cash strip unavailable: %s", e)
    # HEADLINE DELTAS: vs the preceding equal-length window — the same engine with
    # an explicit comparison window, clearly labelled, never mixed into the grid.
    compare = None
    if not (start or end) and days in (30, 60, 90):
        try:
            import datetime as _dt
            from helpers import today_sydney as _ts
            _w1 = _ts(); _w0 = _w1 - _dt.timedelta(days=days - 1)
            prev = attribution_engine.compute(
                start=str(_w0 - _dt.timedelta(days=days)),
                end=str(_w0 - _dt.timedelta(days=1)), basis=basis, market=market)
            attribution_engine.assert_same_basis(result, prev)
            pt, ct = prev.get("totals") or {}, result.get("totals") or {}
            compare = {"label": f"vs prior {days}d",
                       "window": prev.get("window"),
                       "deltas": {k: (round((ct.get(k) or 0) - (pt.get(k) or 0), 2)
                                      if ct.get(k) is not None or pt.get(k) is not None
                                      else None)
                                  for k in ("leads", "closes", "cash", "spend")},
                       "prior": {k: pt.get(k) for k in ("leads", "closes", "cash", "spend")}}
        except Exception as e:
            logger.info("headline compare unavailable: %s", e)
    unverified_shows = None
    derived_map = None
    try:
        import resolution
        dd = resolution.derived_dates() or {}
        unverified_shows = [
            {"name": k, "date": v["show_date"]["date"],
             "near_miss": (v["show_date"].get("verification") or {}).get("near_miss")}
            for k, v in dd.items()
            if "show_date" in v
            and (v["show_date"].get("verification") or {}).get("state") != "verified"][:40]
        derived_map = {k: {f: {"date": v[f]["date"], "provenance": v[f]["provenance"]}
                           for f in v} for k, v in list(dd.items())[:80]}
    except Exception:
        pass
    return {
        "unverified_shows": unverified_shows,
        "derived_dates": derived_map,
        "hygiene": hygiene, "identity": identity, "ladder": ladder,
        "window": result.get("window"), "basis": result.get("basis"),
        "basis_label": result.get("basis_label"),
        "market": result.get("market"), "market_note": result.get("market_note"),
        "compare": compare,
        "cash_strip": cash_strip,
        "invariants": result.get("invariants"),
        "scoreboard": AE.scoreboard_view(result),
        "scorecard": sc, "rows": result.get("rows"),
        "qualified_rule": result.get("qualified_rule"),
        "reconciliation": result.get("reconciliation"),
        "freshness": result.get("freshness"),
        "ig_non_lead_inquiries": result.get("ig_non_lead_inquiries"),
    }


def _rollup_key(basis, days):
    return f"attr:rollup:{basis}:{days}"


def _serve_board(days, start, end, basis, force, market=None):
    """Rollup-backed serve: fresh when the engine is warm; a persisted rollup served
    STALE-LABELLED (never as fresh) while a background refresh runs; prefetch of the
    adjacent windows after any fresh build."""
    import attribution_engine as AE
    import kv_store, threading, time as _t
    custom = bool(start or end)
    if market is not None:
        payload = _build_board(days, start, end, basis, force=force, market=market)
        payload["stale"] = False
        return payload
    w_cached = False
    if not custom:
        import datetime as dt
        from helpers import today_sydney
        w1 = today_sydney(); w0 = w1 - dt.timedelta(days=days - 1)
        hit = AE._cache.get((str(w0), str(w1), basis))
        w_cached = bool(hit and _t.time() - hit[0] < AE._CACHE_TTL_S)
    if custom or w_cached or force:
        payload = _build_board(days, start, end, basis, force=force)
        payload["stale"] = False
        if not custom:
            kv_store.put(_rollup_key(basis, days), {"at": _t.time(), "board": payload})
            _prefetch_adjacent(days, basis)
        return payload
    stored = kv_store.get(_rollup_key(basis, days))
    if stored and stored.get("board"):
        board = stored["board"]
        board["stale"] = True
        board["stale_age_s"] = int(_t.time() - (stored.get("at") or 0))
        _refresh_async(days, basis)
        return board
    payload = _build_board(days, start, end, basis)     # cold, no rollup — build now
    payload["stale"] = False
    kv_store.put(_rollup_key(basis, days), {"at": _t.time(), "board": payload})
    _prefetch_adjacent(days, basis)
    return payload


_refreshing: set = set()


def _refresh_async(days, basis):
    key = (days, basis)
    if key in _refreshing:
        return
    _refreshing.add(key)

    def _run():
        import kv_store, time as _t
        try:
            payload = _build_board(days, None, None, basis, force=True)
            payload["stale"] = False
            kv_store.put(_rollup_key(basis, days), {"at": _t.time(), "board": payload})
        except Exception as e:
            logger.warning("rollup refresh failed (%s,%s): %s", basis, days, e)
        finally:
            _refreshing.discard(key)
    import threading
    threading.Thread(target=_run, daemon=True, name=f"rollup-{basis}-{days}").start()


def _prefetch_adjacent(days, basis):
    # ALL_DAYS included so ?window=all and the dossier's all-time leg serve from
    # rollups instead of a cold multi-minute compute (perf budget: grid <2s)
    for d in (30, 60, 90, ALL_DAYS):
        if d != days:
            _refresh_async(d, basis)


def _compute(days, start, end, force=False, basis="cohort", market=None):
    import attribution_engine
    return attribution_engine.compute(days=days, start=start, end=end, force=force,
                                      basis=basis, market=market)


@bp.route("/", methods=["GET"])
@require_auth
def page():
    from flask import current_app
    import os as _os
    asset_v = int(_os.path.getmtime(_os.path.join(current_app.root_path,
                                                  "dashboard", "static", "js", "adsapp.js")))
    return render_template("ads.html", asset_v=asset_v)


@bp.route("/api/board", methods=["GET"])
@require_auth
def board():
    """ONE atomic payload per (window, basis) — served from the rollup layer: fresh when
    warm, stale-LABELLED with a background refresh when not (never silently stale)."""
    days, start, end = _window_args()
    if days is None:
        return jsonify({"error": "bad days"}), 400
    basis = _basis_arg()
    payload = _serve_board(days, start, end, basis, force=request.args.get("force") == "1",
                           market=_market_arg())
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


def _ghl_notes_for(contact_ids: list[str]) -> dict:
    """Live GHL notes per contact (probe-proven endpoint), throttled, capped, stamped.
    Returns {contact_id: [{body, date, source}]} — missing/empty stays absent."""
    import requests as rq
    from config import GHL_BASE, GHL_API_KEY
    from helpers import now_sydney
    out: dict = {}
    stamp = now_sydney().strftime("%Y-%m-%d %H:%M")
    for cid in contact_ids[:8]:   # speed: inline notes for the first 8; the rest stay tracker-only
        try:
            r = rq.get(f"{GHL_BASE}/contacts/{cid}/notes",
                       headers={"Authorization": f"Bearer {GHL_API_KEY}",
                                "Version": "2021-07-28"}, timeout=(5, 12))
            if r.status_code == 200:
                notes = [{"body": _strip_html(n.get("body"))[:300],
                          "date": str(n.get("dateAdded", ""))[:10],
                          "source": f"GHL · fetched {stamp}"}
                         for n in (r.json().get("notes") or [])[:3]
                         if _strip_html(n.get("body"))]
                if notes:
                    out[cid] = notes
        except rq.RequestException:
            pass
        time.sleep(0.12)
    return out


@bp.route("/api/deal", methods=["GET"])
@require_auth
def deal_panel():
    """THE ANOMALY/DEAL PANEL (?name=): the object behind a badge or feed item —
    tracker row (verbatim fields), why it's invisible/unwindowable in plain English,
    GHL link, and the queue state (queued/cleared). Every number is a door."""
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    import attribution_engine as AE
    nm = re.sub(r"[^a-z0-9 @.]", "", name.lower()).strip()
    leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
    matches = [l for l in leads_all if l["name_norm"] == nm]
    if not matches:
        return jsonify({"error": "no tracker row", "name": name}), 404
    lead = next((l for l in matches if l.get("won")), matches[0])
    why = []
    if lead.get("won") and not lead.get("close_date"):
        why.append("won but Close Date blank — invisible to every windowed close figure")
    if lead.get("set") and not lead.get("set_date"):
        why.append("set exists but Set Date blank — not windowable on the activity clock")
    if not lead.get("input_date"):
        why.append("Input Date blank — excluded from cohort funnels")
    ghl_link = contact_id = None
    try:
        import attribution_join
        from config import GHL_LOCATION_ID
        for c in attribution_join.load_contacts():
            if (lead.get("email") and c.get("email") == lead["email"]) or \
               re.sub(r"[^a-z0-9 @.]", "", (c.get("name") or "").lower()).strip() == nm:
                contact_id = c["id"]
                ghl_link = (f"https://app.gohighlevel.com/v2/location/"
                            f"{GHL_LOCATION_ID}/contacts/detail/{c['id']}")
                break
    except Exception:
        pass
    # queue state: is this deal in the hygiene/Piolo queue right now?
    queue = []
    try:
        import kv_store
        import close_integrity
        mx = close_integrity.latest() or {}
        for d in (mx.get("disagreements") or []):
            if nm in re.sub(r"[^a-z0-9 @.]", "", (d.get("detail") or "").lower()):
                queue.append({"detail": d["detail"], "fix": d["fix"],
                              "owner": d.get("owner"), "state": "queued"})
        for f in (kv_store.get("ads_truth:flags") or []):
            if name.lower() in (f.get("reason") or "").lower():
                queue.append({"detail": f["reason"], "state": "queued (truth sweep)"})
        for card in ((kv_store.get("integrity:proposed_fixes") or {}).get("cards") or []):
            if (card.get("name") or "").lower() == name.lower():
                queue.append({"detail": f"proposed fix: {card.get('instruction')}",
                              "state": f"PROPOSED ({card.get('kind')})",
                              "candidates": card.get("candidates")})
    except Exception as e:
        logger.info("deal queue state degraded: %s", e)
    derived = {}
    try:
        import resolution
        derived = (resolution.derived_dates() or {}).get(nm) or {}
    except Exception:
        pass
    resp = jsonify({
        "name": lead["name"], "business": lead.get("business"),
        "market": lead.get("market"),
        "derived_dates": derived or None,
        "tracker": {k: (str(lead.get(k)) if lead.get(k) is not None else None)
                    for k in ("input_date", "setter_outcome", "set", "set_date", "show",
                              "closer_outcome", "close_date", "contract", "cash",
                              "setter_notes", "dq_reason")},
        "why_invisible": why or None,
        "contact_id": contact_id, "ghl_link": ghl_link,
        "queue": queue or [{"state": "cleared", "detail": "no open queue item for this deal"}],
        "resolution_lane": ("PROPOSED" if any("PROPOSED" in q.get("state", "") for q in queue)
                            else "HUMAN (Piolo queue)" if queue else "clear"),
    })
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/dossier", methods=["GET"])
@require_auth
def dossier():
    """THE CREATIVE DOSSIER (?creative=<key>): identity & delivery · unit economics
    (window + all-time, one engine, min-n labels intact) · the lead ledger with
    funnel-state chips + provenance + links. Linkable/bookmarkable via URL params."""
    days, start, end = _window_args()
    if days is None:
        return jsonify({"error": "bad days"}), 400
    key = request.args.get("creative")
    if not key:
        return jsonify({"error": "creative required"}), 400
    basis, market = _basis_arg(), _market_arg()
    result = _compute(days, start, end, basis=basis, market=market)
    row = next((c for c in (result.get("creatives") or [])
                if c["creative_key"] == key), None)
    r_all = _compute(ALL_DAYS, None, None, basis=basis, market=market)
    row_all = next((c for c in (r_all.get("creatives") or [])
                    if c["creative_key"] == key), None)
    if row is None and row_all is None:
        return jsonify({"error": "unknown creative"}), 404

    # identity & delivery — entity map fields are labelled for what they are
    # (created_time is the ad's CREATED date, not first delivery — stated).
    ident = {}
    try:
        import meta_entities
        store = meta_entities.refresh_entity_map()
        for ad_id in (row or row_all).get("ad_ids") or []:
            a = (store.get("ads") or {}).get(ad_id)
            if a:
                ident = {"status": a.get("effective_status") or a.get("status"),
                         "created_time": a.get("created_time"),
                         "created_time_note": "ad CREATED date (Meta) — not first delivery",
                         "adset": a.get("adset_name") or a.get("adset"),
                         "campaign": a.get("campaign_name") or a.get("campaign")}
                break
    except Exception as e:
        logger.info("dossier identity degraded: %s", e)

    def econ(c):
        if not c:
            return None
        return {k: c.get(k) for k in
                ("leads", "qualified", "reached", "sets", "shows", "closes", "cash",
                 "spend", "cost_per_lead", "cost_per_qualified", "cost_per_set",
                 "cost_per_close", "ltgp_cac", "verdict", "provisional",
                 "earlier_closes", "undated_sets", "sets_src", "shows_src")}

    # the lead ledger: every attributed lead, window-filtered (all-time via ?days=all)
    ledger = [v for v in (result.get("rows") or [])
              if (v.get("creative") or {}).get("key") == key]
    # links: contact id + GHL, same join the roster uses
    try:
        import attribution_join
        from config import GHL_LOCATION_ID
        contacts = attribution_join.load_contacts()
        by_email = {c["email"]: c for c in contacts if c.get("email")}
        by_cname = {}
        for c in contacts:
            if c.get("name"):
                by_cname.setdefault(re.sub(r"[^a-z0-9 @.]", "", c["name"].lower()).strip(), c)
        for v in ledger:
            c = (by_email.get((v.get("email") or "").lower()) if v.get("email") else None) \
                or by_cname.get(re.sub(r"[^a-z0-9 @.]", "", (v["name"] or "").lower()).strip())
            if c:
                v["contact_id"] = c["id"]
                v["ghl_link"] = (f"https://app.gohighlevel.com/v2/location/"
                                 f"{GHL_LOCATION_ID}/contacts/detail/{c['id']}")
    except Exception as e:
        logger.info("dossier links degraded: %s", e)
    ledger.sort(key=lambda v: v.get("input_date") or "", reverse=True)

    resp = jsonify({
        "creative_key": key,
        "label": (row or row_all).get("label"),
        "tier": (row or row_all).get("tier"),
        "campaigns": (row or row_all).get("campaigns"),
        "ad_ids": (row or row_all).get("ad_ids"),
        "history": (row or row_all).get("history"),
        "identity": ident,
        "window": result.get("window"), "basis": basis,
        "market": result.get("market"), "market_note": result.get("market_note"),
        "econ_window": econ(row), "econ_all_time": econ(row_all),
        "min_n": result.get("min_n"),
        "ledger": ledger, "ledger_count": len(ledger),
        "deals": (row or {}).get("deals") or [],
        "deals_all_time": (row_all or {}).get("deals") or [],
    })
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/api/roster", methods=["GET"])
@require_auth
def roster():
    """The humans behind a count: ?creative=<key>&stage=leads|qualified|sets|shows|closes.
    EXACTLY the engine's cohort for that cell — the caller can assert len == count."""
    days, start, end = _window_args()
    if days is None:
        return jsonify({"error": "bad days"}), 400
    stage = request.args.get("stage", "leads")
    creative = request.args.get("creative") or None
    if stage not in _STAGES and stage != "closes":
        return jsonify({"error": "bad stage"}), 400
    # THE CASE-A CLASS FIX: the drill inherits the clicked cell's CLOCK. The old
    # path computed cohort unconditionally — every activity-basis close cell
    # drilled to a different count (5 live instances at diagnosis).
    basis = _basis_arg()
    result = _compute(days, start, end, basis=basis, market=_market_arg())
    import attribution_engine as _AE
    _AE.assert_same_basis(result)   # and the payload states its clock (below)

    people = []
    if stage == "closes":
        # close-date basis — the SAME deals list the count is len() of
        for c in (result.get("creatives") or []):
            if creative and c["creative_key"] != creative:
                continue
            for d in c.get("deals") or []:
                people.append({"name": d["name"], "close_date": d["close_date"],
                               "contract": d["contract"], "cash": d["cash"],
                               "creative": c["label"], "creative_key": c["creative_key"],
                               "stage": "closes", "note": d.get("note")})
        # enrich from the all-time tracker rows (business, revenue, setter fields)
        import attribution_engine as AE
        leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
        by_name = {}
        for l in leads_all:
            by_name.setdefault(l["name_norm"], l)
        for p in people:
            l = by_name.get(re.sub(r"[^a-z0-9 @.]", "", p["name"].lower()).strip())
            if l:
                p.update({"business": l["business"],
                          "input_date": str(l["input_date"]) if l["input_date"] else None,
                          "setter_outcome": l["setter_outcome"] or None,
                          "revenue": {"band": None, "state": "unknown", "source": None},
                          "setter_notes": l.get("setter_notes") or None,
                          "dq_reason": l.get("dq_reason") or None,
                          "email": l["email"] or None})
                try:
                    import revenue_bands
                    p["revenue"] = {k: v for k, v in revenue_bands.parse_band(
                        l.get("revenue_raw")).items() if k in ("band", "state", "source")}
                except Exception:
                    pass
    else:
        pred = _STAGES[stage]
        for r in (result.get("rows") or []):
            if creative and r["creative"]["key"] != creative:
                continue
            if not pred(r):
                continue
            people.append({**{k: r.get(k) for k in
                              ("name", "business", "input_date", "setter_outcome", "set",
                               "set_date", "show", "closer_outcome", "close_date",
                               "contract", "cash", "revenue", "qualified", "finalised",
                               "setter_notes", "dq_reason")},
                           "creative": r["creative"]["label"],
                           "creative_key": r["creative"]["key"], "stage": stage})

    # attach contact ids + GHL notes + pipeline stage (mirror) + the GHL link
    try:
        import attribution_join
        from config import GHL_LOCATION_ID
        contacts = attribution_join.load_contacts()
        by_email = {c["email"]: c for c in contacts if c.get("email")}
        by_cname = {}
        for c in contacts:
            if c.get("name"):
                by_cname.setdefault(re.sub(r"[^a-z0-9 @.]", "", c["name"].lower()).strip(), c)
        want_notes = []
        for p in people:
            key = (p.get("email") or "").lower() or None
            c = (by_email.get(key) if key else None) or \
                by_cname.get(re.sub(r"[^a-z0-9 @.]", "", p["name"].lower()).strip())
            if c:
                p["contact_id"] = c["id"]
                p["ghl_link"] = (f"https://app.gohighlevel.com/v2/location/"
                                 f"{GHL_LOCATION_ID}/contacts/detail/{c['id']}")
                want_notes.append(c["id"])
        notes = _ghl_notes_for(want_notes)
        # pipeline stage from the mirror (open-pipeline coverage; absent = not shown)
        try:
            import db
            if db.db_configured() and want_notes:
                with db.get_conn() as conn:
                    rows_db = conn.execute(
                        "SELECT contact_id, stage_name FROM ghl_opportunities "
                        "WHERE contact_id = ANY(%s) AND deleted = FALSE",
                        (want_notes,)).fetchall()
                stage_by = {r["contact_id"]: r["stage_name"] for r in rows_db}
                for p in people:
                    if p.get("contact_id") in stage_by:
                        p["pipeline_stage"] = stage_by[p["contact_id"]]
        except Exception as e:
            logger.info("pipeline stage join skipped: %s", e)
        from helpers import today_sydney
        sheet_stamp = str(today_sydney())
        for p in people:
            merged = []
            if p.get("setter_notes"):
                merged.append({"body": p["setter_notes"],
                               "source": "tracker · Setter Notes (mirror)"})
            if p.get("dq_reason"):
                merged.append({"body": p["dq_reason"],
                               "source": "tracker · DQ Reason (mirror)"})
            merged.extend(notes.get(p.get("contact_id"), []))
            p["notes"] = merged     # empty list = "no notes recorded" client-side
    except Exception as e:
        logger.warning("roster enrichment degraded: %s", e)

    resp = jsonify({"window": result.get("window"), "stage": stage,
                    "creative": creative, "people": people, "count": len(people),
                    # the drill STATES its clock (I11) — the client renders it in
                    # the panel header and compares against the clicked cell's clock
                    "basis": result.get("basis"),
                    "clock_note": ("lead-cohort clock: this window's leads and "
                                   "everything that later happened to them"
                                   if result.get("basis") == "cohort" else
                                   "activity clock: events dated in this window")})
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp
