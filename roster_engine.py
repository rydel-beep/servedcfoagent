"""
roster_engine.py
----------------
THE ROSTER ENGINE (DECISIONS #131 session): one query path from a cell-spec to
the humans behind the number. Every surface that lists people behind a funnel
count consumes THIS — the grid cell drills (every tab), the tier rows, the
creative-dossier lead ledger, the anomaly panels. A person list computed
anywhere else is a doctrine violation (the old dossier join and the client-side
anomaly filter were deleted in this build).

CELL-SPEC: {level: creative|name|batch|campaign|account, key, metric, window
(days|start/end), basis (clock), market}. Tier rows (IG DM / Unattributed /
Ambiguous) are creative-level cells whose key is the tier key.

I17 — ROSTER-CELL EQUALITY: attribution_engine records members at the SAME line
every counter increments; this module only materializes those lists. count ==
len(people) is checked here anyway; drift raises a LOUD kv flag and the payload
says so (never a quiet skew).

Flags render, never filter: a roster is always complete for its cell. Identity
gaps, name discrepancies, missing dates arrive as CHIPS on the row.

Deterministic and read-only: compute() result + tracker parse + contact table +
the derived-dates store. No network calls of its own (GHL notes are a dashboard
nicety layered on top by the route, capped and stamped there).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

METRICS = ("leads", "qualified", "reached", "sets", "shows", "closes")
ANOMALY_METRICS = ("earlier_closes", "earlier_sets", "earlier_shows",
                   "undated_sets", "shows_unverified")
LEVELS = ("creative", "name", "batch", "campaign", "account")

_TIER_KEYS = {"__ig_dm__", "__unattributed__", "__ambiguous__"}

_STATE_RANK = {"closed": 5, "show": 4, "set": 3, "reached": 2, "qualified": 1, "lead": 0}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 @.]", "", str(s or "").lower()).strip()


def _tracker_link() -> str | None:
    """Book-level link to the Lead-to-Cash tracker. Row-level anchors are NOT
    emitted: the clean view drops test-lead rows, so a computed row number would
    point at the wrong line — a wrong link is worse than a book link."""
    try:
        from config import SHEET_CONFIG
        sid = SHEET_CONFIG.get("sheet_id")
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else None
    except Exception:
        return None


def _member_rows(result: dict, level: str, key: str) -> tuple[list[dict], str | None]:
    """The creative rows whose members make up this cell. Returns (rows, error)."""
    creatives = result.get("creatives") or []
    if level == "creative":
        rows = [c for c in creatives if c["creative_key"] == key]
        return rows, None if rows else f"unknown creative '{key}'"
    import attribution_verdicts
    groups = attribution_verdicts.ladder_groups(result).get(level) or {}
    if level == "account":
        return groups.get("__account__") or [], None
    rows = groups.get(key)
    return (rows or []), (None if rows else f"unknown {level} group '{key}'")


def _identity(lead: dict | None, name_norm: str, by_email: dict, by_name: dict):
    """Identity chip + GHL contact for a person. IDs are truth, names are labels."""
    contact = None
    if lead and lead.get("email") and lead["email"] in by_email:
        contact = by_email[lead["email"]]
        chip = "id-linked"
    else:
        hits = by_name.get(name_norm) or []
        if len(hits) == 1:
            contact = hits[0]
            chip = "name-match (unlinked)"
        elif hits:
            chip = "ambiguous name (multiple GHL contacts — quarantined)"
        elif lead is not None:
            chip = "tracker-only (no GHL contact)"
        else:
            chip = "ghl-only (no tracker row)"
    ghl_name = (contact or {}).get("name")
    discrepancy = bool(ghl_name and lead and _norm(ghl_name) != lead.get("name_norm"))
    return contact, chip, ghl_name, discrepancy


def _event_for(metric: str, lead: dict | None, derived: dict) -> dict:
    """THE EVENT that placed this person in the cell: its date + provenance chip.
    Tracker always wins; a derived date carries its provenance; a blank stays an
    honest blank with the reason."""
    d = derived or {}
    if metric in ("leads", "qualified", "reached"):
        if lead and lead.get("input_date"):
            prov = (d.get("input_date") or {}).get("provenance") or "tracker"
            return {"kind": "entered", "date": str(lead["input_date"]), "provenance": prov}
        return {"kind": "entered", "date": None,
                "provenance": "tracker (Input Date blank)"}
    if metric in ("sets", "earlier_sets", "undated_sets"):
        if lead and lead.get("set_date"):
            prov = (d.get("set_date") or {}).get("provenance") or "tracker"
            return {"kind": "set booked", "date": str(lead["set_date"]), "provenance": prov}
        if (d.get("set_date") or {}).get("date"):
            return {"kind": "set booked", "date": d["set_date"]["date"],
                    "provenance": d["set_date"]["provenance"]}
        return {"kind": "set booked", "date": None,
                "provenance": "tracker (set exists, Set Date blank — Piolo queue)"}
    if metric in ("shows", "earlier_shows", "shows_unverified"):
        if lead and lead.get("show"):
            return {"kind": "showed", "date": str(lead["set_date"]) if lead.get("set_date") else None,
                    "provenance": "show:tracker-authority",
                    "note": "shows have no own date column — the set-call date is shown"}
        sd = d.get("show_date") or {}
        if sd.get("date"):
            state = ((sd.get("verification") or {}).get("state"))
            via = ((sd.get("verification") or {}).get("via"))
            prov = via if state == "verified" else "show:unverified (status-only)"
            return {"kind": "showed", "date": sd["date"], "provenance": prov}
        return {"kind": "showed", "date": None, "provenance": "no show evidence recorded"}
    if metric in ("closes", "earlier_closes"):
        if lead and lead.get("close_date"):
            prov = (d.get("close_date") or {}).get("provenance") or "tracker"
            return {"kind": "closed", "date": str(lead["close_date"]), "provenance": prov}
        cd = d.get("close_date") or {}
        if cd.get("date"):
            return {"kind": "closed", "date": cd["date"], "provenance": cd["provenance"]}
        return {"kind": "closed", "date": None,
                "provenance": "tracker (Close Date blank — dateless close)"}
    return {"kind": metric, "date": None, "provenance": "unknown metric"}


def _funnel_chips(lead: dict | None, view_row: dict | None, derived: dict) -> list[dict]:
    """Downstream funnel state: qualified → reached → set → show → closed, each
    with provenance. Chips render, never filter."""
    d = derived or {}
    lv = lead or {}
    vr = view_row or {}

    def chip(name, on, prov):
        return {"chip": name, "on": bool(on), "provenance": prov if on else None}

    show_on = lv.get("show") or bool(d.get("show_date"))
    show_prov = ("show:tracker-authority" if lv.get("show") else
                 ((d.get("show_date") or {}).get("verification") or {}).get("via")
                 or ("show:unverified (status-only)" if d.get("show_date") else None))
    closed_on = bool(lv.get("won") and (lv.get("close_date") or d.get("close_date")))
    closed_prov = ((d.get("close_date") or {}).get("provenance")
                   if (lv.get("close_date") is None and d.get("close_date")) else "tracker")
    return [
        chip("qualified", vr.get("qualified"), "engine (≠DQ + revenue floor + form)"),
        chip("reached", vr.get("reached") or lv.get("set") or lv.get("show") or lv.get("won"),
             "tracker set/show/close" if (lv.get("set") or lv.get("show") or lv.get("won"))
             else "GHL contact evidence (sweep)"),
        chip("set", lv.get("set") or bool(d.get("set_date")),
             (d.get("set_date") or {}).get("provenance") if not lv.get("set_date")
             and d.get("set_date") else "tracker"),
        chip("show", show_on, show_prov),
        chip("closed", closed_on, closed_prov if closed_on else None),
    ]


def _quarantine_reason(view_row: dict | None, lead: dict | None, tier_key: str) -> str | None:
    """Tier rosters state WHY each person sits in the tier — per person, plain."""
    vr = view_row or {}
    if tier_key == "__ambiguous__":
        cands = ((vr.get("creative") or {}).get("candidates")) or []
        if cands:
            ids = ", ".join(str(c.get("ad_id")) for c in cands[:4])
            return (f"name matches {len(cands)} ads ({ids}) — quarantined, never "
                    f"assigned to one")
        return "ambiguous ad reference — quarantined"
    if tier_key == "__unattributed__":
        if vr.get("joined_via") is None and not (lead or {}).get("email"):
            return "no GHL contact by email or name — attribution impossible"
        if vr.get("joined_via") is None:
            return "no GHL contact matched (email + name both missed)"
        return "GHL contact has no resolvable ad reference (organic / untagged entry)"
    if tier_key == "__ig_dm__":
        return "came in via Instagram DM — channel-level, no ad-level identity exists"
    return None


def build(days=30, start=None, end=None, basis="cohort", market=None,
          level="creative", key=None, metric="leads") -> dict:
    """Cell-spec → roster. Deterministic, engine-side, no UI arithmetic."""
    if metric not in METRICS + ANOMALY_METRICS:
        return {"error": f"bad metric '{metric}'"}
    if level not in LEVELS:
        return {"error": f"bad level '{level}'"}
    if level == "account":
        key = "__account__"
    if not key:
        return {"error": "key required"}

    import attribution_engine as AE
    result = AE.compute(days=days, start=start, end=end, basis=basis, market=market)
    AE.assert_same_basis(result)     # I11: the roster inherits the cell's clock
    member_rows, err = _member_rows(result, level, key)
    if err and not member_rows:
        return {"error": err}

    # the cell number exactly as rendered (sum over member creatives == the
    # ladder cell because _aggregate sums the same members)
    cell_value = sum((r.get(metric) or 0) for r in member_rows)
    name_norms: list[str] = []
    for r in member_rows:
        name_norms.extend((r.get("members") or {}).get(metric) or [])

    # ── enrichment sources (one parse, one contact load, one derived read) ────
    leads_all, _cm = AE.parse_tracker(AE._tracker_rows_clean())
    by_norm: dict = {}
    for l in leads_all:
        cur = by_norm.get(l["name_norm"])
        if cur is None or (l.get("won") and not cur.get("won")):
            by_norm[l["name_norm"]] = l
    view_by_norm = {v.get("name_norm"): v for v in (result.get("rows") or [])
                    if v.get("name_norm")}
    deals_by_norm: dict = {}
    for r in member_rows:
        for dl in r.get("deals") or []:
            deals_by_norm.setdefault(_norm(dl.get("name")), dl)
    try:
        import resolution
        derived_store = resolution.derived_dates() or {}
    except Exception:
        derived_store = {}
    by_email: dict = {}
    by_name: dict = {}
    try:
        import attribution_join
        from config import GHL_LOCATION_ID
        for c in attribution_join.load_contacts():
            if c.get("email"):
                by_email.setdefault(c["email"], c)
            if c.get("name"):
                by_name.setdefault(_norm(c["name"]), []).append(c)
    except Exception as e:
        logger.info("roster contact join degraded: %s", e)
        GHL_LOCATION_ID = None
    tracker_link = _tracker_link()
    tier_key = key if key in _TIER_KEYS else None

    people = []
    for nm in name_norms:
        lead = by_norm.get(nm)
        vr = view_by_norm.get(nm)
        deal = deals_by_norm.get(nm)
        derived = derived_store.get(nm) or {}
        contact, ident_chip, ghl_name, discrepancy = _identity(lead, nm, by_email, by_name)
        event = _event_for(metric, lead, derived)
        lv = lead or {}
        person = {
            "name": (lead or {}).get("name") or (vr or {}).get("name") or nm,
            "name_norm": nm,
            "ghl_name": ghl_name if discrepancy else None,
            "name_discrepancy": discrepancy,
            "business": lv.get("business") or (vr or {}).get("business"),
            "identity": ident_chip,
            "event": event,
            "funnel": _funnel_chips(lead, vr, derived),
            "input_date": str(lv["input_date"]) if lv.get("input_date") else None,
            "setter_outcome": lv.get("setter_outcome") or None,
            "setter_notes": lv.get("setter_notes") or None,
            "dq_reason": lv.get("dq_reason") or None,
            "revenue": (vr or {}).get("revenue"),
            "pipeline_stage": None,   # filled by the route's mirror join (db)
            "contact_id": (contact or {}).get("id"),
            "ghl_link": (f"https://app.gohighlevel.com/v2/location/{GHL_LOCATION_ID}"
                         f"/contacts/detail/{contact['id']}"
                         if contact and GHL_LOCATION_ID else None),
            "tracker_link": tracker_link if lead is not None else None,
            "email": lv.get("email") or None,
        }
        if metric in ("closes", "earlier_closes") or lv.get("won"):
            person["cash"] = (deal or {}).get("cash", lv.get("cash"))
            person["contract"] = (deal or {}).get("contract", lv.get("contract"))
            person["close_date"] = event["date"] if metric in ("closes", "earlier_closes") \
                else (str(lv["close_date"]) if lv.get("close_date") else None)
        if tier_key:
            person["tier_reason"] = _quarantine_reason(vr, lead, tier_key)
        # sort keys the panel uses (event date / funnel state / cash) — data, not UI math
        st = "lead"
        for ch in person["funnel"]:
            if ch["on"] and ch["chip"] in ("qualified", "reached", "set", "show"):
                st = ch["chip"] if ch["chip"] != "qualified" else "qualified"
            if ch["chip"] == "closed" and ch["on"]:
                st = "closed"
        person["state"] = st
        person["state_rank"] = _STATE_RANK.get("closed" if st == "closed" else
                                               "show" if st == "show" else
                                               "set" if st == "set" else
                                               "reached" if st == "reached" else
                                               "qualified" if st == "qualified" else "lead", 0)
        people.append(person)

    # I17 runtime check — LOUD on drift, never a quiet skew
    i17 = {"ok": len(people) == cell_value, "cell": cell_value, "roster": len(people)}
    if not i17["ok"]:
        try:
            import kv_store
            flags = kv_store.get("ads_truth:flags") or []
            flags.append({"metric": "ads_truth_action",
                          "reason": (f"I17 ROSTER-CELL DRIFT: {level}/{key} {metric} "
                                     f"({basis} {days}d) cell={cell_value} "
                                     f"roster={len(people)} — the mismatch class is back")})
            kv_store.put("ads_truth:flags", flags[-60:])
        except Exception:
            pass
        logger.warning("I17 drift: %s/%s %s cell=%s roster=%s", level, key, metric,
                       cell_value, len(people))

    label = member_rows[0]["label"] if level == "creative" and member_rows else key
    empty_reason = None
    if not people:
        w = result.get("window") or {}
        scope = {"creative": f"creative", "name": "creative name", "batch": "batch",
                 "campaign": "campaign", "account": "account"}[level]
        empty_reason = (f"no {metric.replace('_', ' ')} events for this {scope} in this "
                        f"{w.get('days')}d {basis} window"
                        + (f" (market: {market})" if market else "")
                        + " — honest empty, not an error")
    return {
        "cellspec": {"level": level, "key": key, "metric": metric,
                     "days": days, "start": start, "end": end,
                     "basis": basis, "market": market or "all"},
        "label": label,
        "window": result.get("window"), "basis": result.get("basis"),
        "count": cell_value, "people": people, "i17": i17,
        "empty_reason": empty_reason,
        "clock_note": ("lead-cohort clock: this window's leads and everything that "
                       "later happened to them" if result.get("basis") == "cohort"
                       else "activity clock: events dated in this window"),
    }
