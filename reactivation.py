"""
reactivation.py
---------------
DETERMINISTIC lead classification over the GHL mirror (Phase 2). Pure queries — every count/value
EDITH quotes about leads comes from here, cross-checkable against GHL's own stage filters.

Definitions (Rydel's Phase-0 calls, 2026-07-27):
- STALE: open opportunity, created 90+ days ago, in a reactivatable COLD stage.
- PITCHED-STALLED: open, reached a consult/pitch stage, no stage-change for 21+ days.
- EXCLUDED from reactivation (still counted in hygiene): Disqualified, Ban Leads (DND), Won.
- WARMTH = stage-reached weight × value factor × last-touch recency.

No fabrication: a lead's stage/value/dates are the mirror's verbatim rows; the tracker join is
email→name smart-matched and flagged when unmatched, never forced.
"""
from __future__ import annotations

import datetime as dt
import logging

import ghl_mirror
from helpers import today_sydney

logger = logging.getLogger(__name__)

STALE_DAYS = 90
PITCH_STALL_DAYS = 21

# Stage taxonomy (from the live pipeline "1 SERVED Client Acquisition")
PITCH_STAGES = {"Consult Call Booked", "2nd Consult Call Booked"}
COLD_REACTIVATABLE = {
    "Unresponsive/Not Interested", "Stale", "Client will reconnect", "Call Back to Set",
    "Called But Didn't Pick Up", "Consult Call No Show", "Consult Call Cancelled", "Hung Up",
}
TOP_FUNNEL = {"Served New Leads", "Lead Magnets(PDF downloaded)", "Skool Shortlist"}
DEAD_EXCLUDED = {"Disqualified", "Ban Leads (DND)"}   # Rydel: never a reactivation target
WON_STAGES = {"✅ Closed Deal"}

# Stage-reached weight (higher = warmer / further down the funnel)
_STAGE_WEIGHT = {
    "2nd Consult Call Booked": 100, "Consult Call Booked": 90,
    "Consult Call Cancelled": 62, "Consult Call No Show": 60, "Call Back to Set": 52,
    "Client will reconnect": 48, "Lead Magnets(PDF downloaded)": 42, "Skool Shortlist": 40,
    "Served New Leads": 38, "Called But Didn't Pick Up": 30, "Hung Up": 22,
    "Stale": 28, "Unresponsive/Not Interested": 20,
}


def _parse(ts) -> dt.date | None:
    if ts is None:
        return None
    if isinstance(ts, dt.datetime):
        return ts.date()
    if isinstance(ts, dt.date):
        return ts
    try:
        return dt.date.fromisoformat(str(ts)[:10])
    except Exception:
        return None


def _last_touch(opp: dict, note_dates: list[dt.date]) -> dt.date | None:
    cands = [_parse(opp.get("last_stage_change_at")), _parse(opp.get("last_status_change_at")),
             _parse(opp.get("updated_at"))] + list(note_dates)
    cands = [d for d in cands if d]
    return max(cands) if cands else None


def _warmth(stage_name: str, value: float, days_since_touch: int | None) -> float:
    sw = _STAGE_WEIGHT.get(stage_name, 15)
    value_factor = 1.0 + min(max(value, 0), 50000) / 10000.0     # 1.0 .. 6.0
    if days_since_touch is None:
        recency = 0.6
    elif days_since_touch <= 30:
        recency = 1.0
    elif days_since_touch <= 90:
        recency = 0.85
    elif days_since_touch <= 180:
        recency = 0.7
    else:
        recency = 0.55
    return round(sw * value_factor * recency, 1)


# ── Tracker join (email → name-token; unmatched flagged, never forced) ────────

def _norm(s) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _tracker_index() -> dict:
    """Build email- and name-token indexes from the Lead-to-Cash mirror for the GHL join."""
    idx = {"by_email": {}, "by_name": {}}
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name("Lead-to-Cash Tracker") or []
        if not rows:
            return idx
        hi = next((i for i, r in enumerate(rows[:8]) if any("close date" in (c or "").lower() for c in r)), 0)
        header = [c.lower() for c in rows[hi]]
        def col(*names):
            for nm in names:
                for i, h in enumerate(header):
                    if nm in h:
                        return i
            return None
        ce, cn, cb, cout = col("email"), col("lead name", "name"), col("business"), col("call outcome", "outcome")
        for r in rows[hi + 1:]:
            def g(i):
                return r[i].strip() if (i is not None and i < len(r)) else ""
            email = g(ce).lower(); name = g(cn); outcome = g(cout)
            rec = {"name": name, "business": g(cb), "outcome": outcome}
            if email:
                idx["by_email"][email] = rec
            if name:
                idx["by_name"][_norm(name)] = rec
    except Exception as e:
        logger.info("_tracker_index failed: %s", e)
    return idx


def _join_tracker(contact: dict | None, idx: dict) -> dict | None:
    if not contact:
        return None
    email = (contact.get("email") or "").lower()
    if email and email in idx["by_email"]:
        return {**idx["by_email"][email], "match": "email"}
    nm = _norm((contact.get("first_name") or "") + (contact.get("last_name") or ""))
    if nm and nm in idx["by_name"]:
        return {**idx["by_name"][nm], "match": "name"}
    return None


# ── Classification ───────────────────────────────────────────────────────────

def classify(join_tracker: bool = True) -> list[dict]:
    """Every OPEN opportunity, classified with bucket + warmth + days-stale + tracker join."""
    today = today_sydney()
    opps = ghl_mirror.read_opportunities(open_only=True)
    idx = _tracker_index() if join_tracker else {"by_email": {}, "by_name": {}}
    out = []
    for o in opps:
        stage = o.get("stage_name") or ""
        value = float(o.get("monetary_value") or 0)
        created = _parse(o.get("created_at"))
        age_days = (today - created).days if created else None
        notes = ghl_mirror.read_notes_for_contact(o.get("contact_id")) if o.get("contact_id") else []
        note_dates = [d for d in (_parse(n.get("date_added")) for n in notes) if d]
        lt = _last_touch(o, note_dates)
        days_since_touch = (today - lt).days if lt else None

        excluded = stage in DEAD_EXCLUDED or stage in WON_STAGES
        bucket = None
        if not excluded:
            if stage in PITCH_STAGES and days_since_touch is not None and days_since_touch >= PITCH_STALL_DAYS:
                bucket = "pitched_stalled"
            elif stage in COLD_REACTIVATABLE and age_days is not None and age_days >= STALE_DAYS:
                bucket = "stale"
            elif stage in PITCH_STAGES:
                bucket = "active_pitch"
            elif stage in (COLD_REACTIVATABLE | TOP_FUNNEL):
                bucket = "watch"

        contact = ghl_mirror.read_contact(o.get("contact_id")) if o.get("contact_id") else None
        tracker = _join_tracker(contact, idx) if join_tracker else None
        out.append({
            "opp_id": o.get("id"), "contact_id": o.get("contact_id"),
            "name": o.get("name"), "stage": stage, "status": o.get("status"),
            "value": value, "created": str(created) if created else None,
            "age_days": age_days, "last_touch": str(lt) if lt else None,
            "days_since_touch": days_since_touch, "notes_count": len(notes),
            "bucket": bucket, "excluded": excluded,
            "warmth": _warmth(stage, value, days_since_touch),
            "tracker": tracker,
        })
    out.sort(key=lambda x: x["warmth"], reverse=True)
    return out


def reactivation_list(bucket: str | None = None, min_value: float = 0.0, limit: int | None = None,
                      leads: list[dict] | None = None) -> list[dict]:
    """Ranked reactivation candidates (stale + pitched_stalled by default), filterable."""
    leads = leads if leads is not None else classify()
    targets = {"stale", "pitched_stalled"} if not bucket else {bucket}
    res = [l for l in leads if l["bucket"] in targets and l["value"] >= min_value]
    res.sort(key=lambda x: x["warmth"], reverse=True)
    return res[:limit] if limit else res


def summary_totals(leads: list[dict] | None = None) -> dict:
    leads = leads if leads is not None else classify()
    buckets = {}
    for l in leads:
        b = l["bucket"] or "excluded" if l["excluded"] else (l["bucket"] or "other")
        d = buckets.setdefault(b, {"count": 0, "value": 0.0})
        d["count"] += 1
        d["value"] += l["value"]
    return {"buckets": buckets, "total_open_leads": len(leads),
            "reactivation_pool": sum(1 for l in leads if l["bucket"] in ("stale", "pitched_stalled")),
            "reactivation_value": round(sum(l["value"] for l in leads
                                            if l["bucket"] in ("stale", "pitched_stalled")), 2)}


def reconciliation(leads: list[dict] | None = None) -> dict:
    """Per-stage OPEN counts from the mirror — the numbers to cross-check against GHL's own filters."""
    leads = leads if leads is not None else classify(join_tracker=False)
    by_stage = {}
    for l in leads:
        d = by_stage.setdefault(l["stage"], {"count": 0, "value": 0.0})
        d["count"] += 1
        d["value"] += l["value"]
    return {"by_stage": dict(sorted(by_stage.items(), key=lambda x: -x[1]["value"])),
            "note": "mirror OPEN opp counts by stage — compare to GHL UI stage filters (the oracle)."}


def notes_hygiene(leads: list[dict] | None = None) -> dict:
    """Team-process finding: what share of stale/reactivation leads have zero notes logged."""
    leads = leads if leads is not None else classify(join_tracker=False)
    pool = [l for l in leads if l["bucket"] in ("stale", "pitched_stalled")]
    no_notes = [l for l in pool if l["notes_count"] == 0]
    n = len(pool)
    return {"reactivation_leads": n, "without_notes": len(no_notes),
            "pct_without_notes": round(100 * len(no_notes) / n, 1) if n else None,
            "finding": (f"{len(no_notes)} of {n} reactivation leads "
                        f"({round(100*len(no_notes)/n) if n else 0}%) have NO notes logged — "
                        "cold reactivation, and a notes-hygiene gap for the team.")}
