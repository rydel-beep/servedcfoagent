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
import re

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
    """Every OPEN opportunity, classified with bucket + warmth + days-stale + tracker join.
    Bulk-loads contacts + notes (a few queries, not per-lead round-trips)."""
    today = today_sydney()
    opps = ghl_mirror.read_opportunities(open_only=True)
    contacts = ghl_mirror.read_all_contacts()
    notes_idx = ghl_mirror.notes_by_contact()
    idx = _tracker_index() if join_tracker else {"by_email": {}, "by_name": {}}
    out = []
    for o in opps:
        stage = o.get("stage_name") or ""
        value = float(o.get("monetary_value") or 0)
        created = _parse(o.get("created_at"))
        age_days = (today - created).days if created else None
        cid = o.get("contact_id")
        notes = notes_idx.get(cid, []) if cid else []
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

        contact = contacts.get(cid) if cid else None
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


def find_lead_by_name(name: str) -> list[dict]:
    """Look up open leads by lead/contact name (for 'where did we leave off with X'). Scored +
    deduped by contact so short single-letter names can't spuriously match. Exact matches win
    outright; otherwise partials. Never invents — [] if none, caller offers closest matches."""
    ql = (name or "").strip().lower()
    q = _norm(ql)
    if len(q) < 3:
        return []
    qtoks = [t for t in re.split(r"[^a-z0-9]+", ql) if len(t) >= 3]
    contacts = ghl_mirror.read_all_contacts()
    best: dict = {}   # dedupe key -> (score, hit)
    for o in ghl_mirror.read_opportunities(open_only=True):
        c = contacts.get(o.get("contact_id"))
        disp = (" ".join(x for x in [(c or {}).get("first_name"), (c or {}).get("last_name")] if x)
                or o.get("name") or "")
        dl = disp.lower(); dn = _norm(dl)
        if len(dn) < 3:
            continue
        score = 0
        if q == dn:
            score = 3                                   # exact
        elif len(q) >= 4 and q in dn:
            score = 2                                   # query is a substring of the name
        elif len(dn) >= 6 and dn in q:
            score = 2                                   # name substantially contained in the query
        elif len(qtoks) >= 2 and sum(1 for t in qtoks if t in dl) >= 2:
            score = 2                                   # 2+ query tokens present
        elif len(qtoks) >= 1 and len(q) >= 5 and all(t in dl for t in qtoks):
            score = 1                                   # all (few) query tokens present
        if not score:
            continue
        key = o.get("contact_id") or o.get("id")
        if key not in best or score > best[key][0]:
            best[key] = (score, {"opp": o, "contact": c, "display": disp})
    if not best:
        return []
    top = max(s for s, _ in best.values())
    if top == 3:                                        # a clean exact match — don't muddy with partials
        return [h for s, h in best.values() if s == 3]
    return [h for _, h in sorted(best.values(), key=lambda x: -x[0])]


import re as _re
_REACT_LIST_RE = _re.compile(r"\b(which|what|who).{0,20}(leads?|clients?).{0,20}(reactivat|re-?engage|reach out|follow up|revive|win back)"
                             r"|\breactivation (list|leads?|candidates?)\b|\bwho should we (reach out to|follow up|call)\b", _re.I)
_LEFTOFF_RE = _re.compile(r"\bwhere (did|do) we (leave|left) off (with|on)\s+(.+?)[\?\.]?$|\bwhere.{0,12}left off.{0,6}with\s+(.+)$", _re.I)
_STALE_COUNT_RE = _re.compile(r"\bhow many\b.{0,30}\b(stale|reactivation|cold|unresponsive|pitched)\b.{0,20}\bleads?\b"
                              r"|\bhow many\b.{0,20}\bleads?\b.{0,30}\b(over|above|worth)\b.{0,6}\$?[\d,]+k?", _re.I)
_HYGIENE_RE = _re.compile(r"\b(notes?|note) hygiene\b|\bhow many leads? (have|with) no notes\b|\bleads? without notes\b", _re.I)


def _fmt_money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "n/a"


def handle_reactivation_command(text: str, actor: dict | None = None) -> tuple[str | None, bool]:
    """EDITH's lead-reactivation answers (deterministic retrieval; grounded summary for left-off)."""
    if not text:
        return None, False

    # "where did we leave off with [lead]?"
    m = _LEFTOFF_RE.search(text)
    if m:
        name = (m.group(4) or m.group(5) or "").strip().rstrip("?.")
        hits = find_lead_by_name(name)
        if not hits:
            # offer closest matches; NEVER invent a lead
            allnames = []
            for o in ghl_mirror.read_opportunities(open_only=True)[:800]:
                c = ghl_mirror.read_contact(o.get("contact_id")) if o.get("contact_id") else None
                dn = " ".join(x for x in [(c or {}).get("first_name"), (c or {}).get("last_name")] if x) or (o.get("name") or "")
                if dn:
                    allnames.append(dn)
            import difflib
            close = difflib.get_close_matches(name, allnames, n=3, cutoff=0.6)
            return (f"I don't have an open lead matching \"{name}\"."
                    + (f" Closest: {', '.join(close)}." if close else " Try their full name as in GHL.")), True
        if len(hits) > 1:
            names = ", ".join(h["display"] for h in hits[:5])
            return (f"I have {len(hits)} open leads matching \"{name}\": {names}. Which one?"), True
        h = hits[0]; o = h["opp"]
        lead = {"contact_id": o.get("contact_id"), "stage": o.get("stage_name"),
                "value": o.get("monetary_value"), "created": str(o.get("created_at"))[:10] if o.get("created_at") else None,
                "last_touch": str(o.get("last_stage_change_at"))[:10] if o.get("last_stage_change_at") else None}
        try:
            import ghl_notes_summary
            s = ghl_notes_summary.summarize_lead(lead)
        except Exception as e:
            return f"Couldn't read {h['display']}'s notes right now: {e}.", True
        parts = [f"{h['display']} — {o.get('stage_name')}, {_fmt_money(o.get('monetary_value'))}."]
        parts.append(s.get("where_it_left_off") or "No notes logged.")
        if s.get("reactivation_angle"):
            parts.append(f"Angle: {s['reactivation_angle']}")
        return " ".join(parts), True

    # "which leads should we reactivate?"
    if _REACT_LIST_RE.search(text):
        leads = classify()
        lst = reactivation_list(leads=leads, limit=8)
        tot = summary_totals(leads)
        if not lst:
            return "No reactivation candidates right now — the pool is clear.", True
        head = (f"{tot['reactivation_pool']} reactivation leads worth {_fmt_money(tot['reactivation_value'])}. "
                f"Top {len(lst)} by warmth: ")
        items = []
        for l in lst:
            c = ghl_mirror.read_contact(l.get("contact_id")) if l.get("contact_id") else None
            dn = " ".join(x for x in [(c or {}).get("first_name"), (c or {}).get("last_name")] if x) or l.get("name") or "?"
            items.append(f"{dn} ({l['stage']}, {_fmt_money(l['value'])}, {l['days_since_touch']}d quiet)")
        return head + "; ".join(items) + ". Say 'export the reactivation brief' for the full ranked list.", True

    # "how many stale leads over $10k?"
    if _STALE_COUNT_RE.search(text):
        leads = classify(join_tracker=False)
        mv = 0.0
        mm = _re.search(r"\$?\s*([\d,]+)\s*(k)?", text)
        if mm:
            mv = float(mm.group(1).replace(",", "")) * (1000 if mm.group(2) else 1)
        pool = reactivation_list(leads=leads, min_value=mv)
        val = sum(l["value"] for l in pool)
        overtxt = f" over {_fmt_money(mv)}" if mv else ""
        return (f"{len(pool)} reactivation leads{overtxt} — {_fmt_money(val)} in pipeline."), True

    # notes hygiene
    if _HYGIENE_RE.search(text):
        return notes_hygiene()["finding"], True

    return None, False


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
