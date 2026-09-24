"""travelling.py — HOW WE'RE TRAVELLING: the live month beside the model.

Rydel: "where we're trying to go vs how we're actually travelling, stage by
stage." Ten funnel stages of ACTUALS (each a door to the people behind it),
laid against a comparator (the scenario on screen · the committed plan ·
last month · your usual measured rates), with how far through the window we
are, where we're ahead or behind, what that's worth in money, and a plain
read.

DOCTRINE CARRIED IN
· ONE ENGINE — every actual comes from the standing engines (attribution
  tracker rows, consult_schedule appointments, meta_spend, finance_analysis
  closes/receipts, ghl_mirror stages, ads_truth call cache). Nothing is
  recomputed here that an engine already owns.
· R-CASH — cash is Stripe receipts only. Never derived, never the tracker's
  cash column (that column is the team's logging and is shown only as a
  cross-check value).
· READ-ONLY (#148) — every source is read; corrections are Piolo package
  lines. Nothing here writes to the tracker or GHL, ever.
· I17 — every rendered count equals the length of its roster.
· No linear to-date line on a lagged stage; no red on a small sample;
  UNKNOWN is never counted as unqualified; PITCHED is evidenced or absent.
· Scenario/what-if never contaminates actuals: comparators are labelled
  inputs, saved checks are their own journal.
"""

from __future__ import annotations

import datetime as dt
import logging
import math

import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

K_SAVED = "travelling:checks"          # the journaled history strip
BAND_PCT = 0.10                        # flow-stage "on track" band (config)
RATE_TIGHT = 0.08                      # a rate CI at or under this is decisive (A4)
REACHED_SECONDS = 60                   # call ≥ this = a real conversation
QUALIFIED_FLOOR = 20_000.0             # revenue floor for "qualified"

# GHL stages that evidence the offer was presented (current-stage snapshot)
PITCHED_STAGES = ("pitched and drifted",)
CLOSED_STAGES = ("closed deal", "✅ closed deal", "won")


# ── windows ─────────────────────────────────────────────────────────────────

def resolve_window(window: str = "mtd", start: str | None = None,
                   end: str | None = None) -> dict:
    t = today_sydney()
    if window == "custom" and start and end:
        w0 = dt.date.fromisoformat(start)
        w1 = min(dt.date.fromisoformat(end), t)
        total = (dt.date.fromisoformat(end) - w0).days + 1
        elapsed = (w1 - w0).days + 1
        label = f"{w0} to {end}"
    elif window == "d21":
        w0, w1 = t - dt.timedelta(days=20), t
        total = elapsed = 21
        label = "Last 21 days"
    else:
        window = "mtd"
        w0, w1 = t.replace(day=1), t
        import calendar
        total = calendar.monthrange(t.year, t.month)[1]
        elapsed = t.day
        label = "Month to date"
    return {"key": window, "start": w0, "end": w1, "label": label,
            "days_total": total, "days_elapsed": elapsed,
            "days_remaining": max(total - elapsed, 0),
            "elapsed_share": min(elapsed / total, 1.0) if total else 1.0,
            "progress": f"Day {elapsed} of {total}"}


# ── actuals: the ten stages ─────────────────────────────────────────────────

def _lead_rows(w0: dt.date, w1: dt.date) -> tuple[list[dict], list[dict]]:
    """Tracker rows whose lead date falls in the window (ID-exact). Returns
    (in-window rows, all rows) — the second is needed to attribute consults
    and closes that belong to leads from earlier windows."""
    import attribution_engine as AE
    rows = AE._tracker_rows_clean()
    leads, _cm = AE.parse_tracker(rows)
    leads, _dupes = AE.dedupe_won(leads)
    # bridge tracker rows to CRM contacts by EMAIL-EXACT match (the rule the
    # rest of the codebase uses; never a surname guess) so appointments and
    # call records can be attributed to the right person
    by_email = {}
    try:
        import ghl_mirror
        for cid, c in (ghl_mirror.read_all_contacts() or {}).items():
            em = (c.get("email") or "").strip().lower()
            if em:
                by_email.setdefault(em, cid)
    except Exception as e:  # noqa: BLE001
        logger.info("travelling: contact mirror unavailable: %s", e)
    for l in leads:
        em = (l.get("email") or "").strip().lower()
        if em and em in by_email:
            l["contact_id"] = by_email[em]
    inw = [l for l in leads if l.get("input_date") and w0 <= l["input_date"] <= w1]
    return inw, leads


def _qualify(leads: list[dict]) -> dict:
    """The three-way split, computed by THE ONE RULE
    (attribution_engine.qualify_lead) — this view no longer carries its own
    copy (#157). UNKNOWN stays its own bucket. A revenue value the picklist
    doesn't recognise raises a LOUD drift finding rather than quietly
    becoming 'below floor'."""
    import attribution_engine as AE
    q, unq, unknown = [], [], []
    reasons = {"disqualified": 0, "revenue below floor": 0,
               "revenue question unanswered": 0, "revenue value not recognised": 0}
    drift = {}
    for l in leads:
        res = AE.qualify_lead(l, None, QUALIFIED_FLOOR)
        if res.get("flag"):
            drift[res["flag"]] = drift.get(res["flag"], 0) + 1
        if res["state"] == "qualified":
            q.append(l)
        elif res["state"] == "unknown":
            unknown.append(l)
            if res.get("reason") in reasons:
                reasons[res["reason"]] += 1
        else:
            unq.append(l)
            if res.get("reason") in reasons:
                reasons[res["reason"]] += 1
    if drift:
        _publish_picklist_drift(drift)
    return {"qualified": q, "unqualified": unq, "unknown": unknown,
            "reasons": {k: v for k, v in reasons.items() if v},
            "picklist_drift": drift}


def _publish_picklist_drift(drift: dict) -> None:
    """B3 — a picklist value the parser doesn't recognise is a SCHEMA CHANGE,
    named loudly (the same class as a new workbook tab), never a silent
    'unknown'."""
    try:
        items = [{"severity": "S2", "category": "data_quality",
                  "title": f"revenue picklist changed — {n} lead"
                           f"{'s' if n != 1 else ''} on a value the parser "
                           f"doesn't recognise",
                  "action": (flag[:200] + " · add the spelling to "
                             "revenue_bands so these leads stop counting as "
                             "unknown")}
                 for flag, n in list(drift.items())[:5]]
        kv_store.put("feed:extra:picklist_drift", items)
    except Exception as e:  # noqa: BLE001
        logger.info("picklist drift publish failed: %s", e)


def _appointments(w0: dt.date, w1: dt.date) -> dict:
    """Consults BOOKED in the window (booked-on clock, #128) + their state.
    GHL leads this stage — the tracker's Set Date column has been empty
    since April (diagnosis)."""
    import consult_schedule as CS
    # THE CALENDAR-LEVEL SOURCE (#162). The per-contact cache below is only
    # the fallback before the first calendar sync — it holds tracker-lead
    # contacts alone, which is how this function returned 0 booked while the
    # calendars held 12.
    import appointments as AP
    if (AP.store() or {}).get("events"):
        now = now_sydney()
        booked, cancelled, due, upcoming = [], [], [], []
        for e in (AP.store().get("events") or []):
            if e.get("calendar_kind") in ("test", "onboarding"):
                continue
            created = AP.parse_when(e.get("booked_at"))
            start = AP.parse_when(e.get("when"))
            when_clock = created or start          # booked-ON clock (#128)
            if not when_clock or not (w0 <= when_clock.date() <= w1):
                continue
            row = {"contact_id": e.get("contact_id"), "status": e.get("status"),
                   "booked_at": created.isoformat() if created else None,
                   "when": start.isoformat() if start else None,
                   "when_text": AP.format_when(e.get("when")),
                   "owner": e.get("owner"), "title": e.get("title")}
            if e.get("cancelled"):
                cancelled.append(row)
            else:
                booked.append(row)
                if start and start <= now:
                    due.append(row)
                elif start:
                    upcoming.append(row)
        upcoming.sort(key=lambda r: r["when"] or "")
        return {"booked": booked, "cancelled": cancelled, "due": due,
                "upcoming": upcoming}
    cache = CS._cache() or {}
    now = now_sydney()
    booked, cancelled, due, upcoming = [], [], [], []
    for cid, hit in cache.items():
        appts = (hit or {}).get("appts") or []
        seen_live = False
        for a in appts:
            created = CS.parse_appt_dt(a.get("dateAdded") or a.get("createdAt"))
            start = CS.parse_appt_dt(a.get("startTime"))
            status = str(a.get("appointmentStatus") or a.get("status") or "").lower()
            when = created or start
            if not when or not (w0 <= when.date() <= w1):
                continue
            row = {"contact_id": cid, "status": status,
                   "booked_at": (created.isoformat() if created else None),
                   "when": (start.isoformat() if start else None),
                   "when_text": (CS.format_consult(start) if start else None)}
            if status in ("cancelled", "invalid"):
                cancelled.append(row)
                continue
            if seen_live:
                continue          # cancel-then-rebook counts once
            seen_live = True
            booked.append(row)
            if start and start <= now:
                due.append(row)
            elif start:
                upcoming.append(row)
    upcoming.sort(key=lambda r: r["when"] or "")
    return {"booked": booked, "cancelled": cancelled, "due": due,
            "upcoming": upcoming}


def _shows(leads_all: list[dict], due: list[dict], w0, w1) -> dict:
    """Of consults due: verified (call record ≥60s or a recorded outcome) ·
    unverified (appointment status only) · evidenced by a close."""
    by_contact = {}
    for l in leads_all:
        if l.get("contact_id"):
            by_contact[l["contact_id"]] = l
    verified, unverified, by_close, noshow = [], [], [], []
    calls = _call_cache()
    for row in due:
        l = by_contact.get(row["contact_id"]) or {}
        row = {**row, "person": l.get("name") or l.get("business") or row["contact_id"]}
        if row["status"] == "noshow":
            noshow.append(row)
            continue
        if l.get("won"):
            by_close.append(row)
        elif l.get("show") or l.get("closer_outcome"):
            verified.append(row)
        elif any((c.get("duration") or 0) >= REACHED_SECONDS
                 for c in ((calls.get(row["contact_id"]) or {}).get("calls") or [])):
            verified.append(row)
        else:
            unverified.append(row)
    return {"verified": verified, "unverified": unverified,
            "by_close": by_close, "noshow": noshow,
            "all": verified + unverified + by_close}


def _pitched(shown_contact_ids: set, w0: dt.date, w1: dt.date) -> dict:
    """EVIDENCED LOWER BOUND (diagnosis): GHL's CURRENT stage is the only
    record — 'Pitched and Drifted' or a closed stage. No stage history
    exists, so a lead pitched then moved on no longer reads as pitched.
    SCOPED to the people whose consult happened in THIS window — pitching is
    something that happens on a consult, so an all-time stage count would be
    meaningless here. Never inferred from 'showed'."""
    rows, note = [], None
    try:
        import ghl_mirror
        opps = ghl_mirror.read_opportunities(open_only=False) or []
        ids = set(shown_contact_ids)
        for o in opps:
            if o.get("contact_id") not in ids:
                continue
            stage = str(o.get("stage_name") or "").lower()
            if any(p in stage for p in PITCHED_STAGES) or \
                    any(c in stage for c in CLOSED_STAGES):
                rows.append({"contact_id": o.get("contact_id"),
                             "person": o.get("name"),
                             "stage": o.get("stage_name"),
                             "moved_at": str(o.get("last_stage_change_at") or "")[:16]})
        # F — anything the recorder has watched is MEASURED; the rest keeps
        # the honest lower-bound label
        measured, since = 0, None
        try:
            import stage_history
            since = stage_history.started_at()
            watched = stage_history.watched_contacts()
            ev = stage_history.pitched_events(since)
            measured = len({e.get("contact_id") for e in ev["events"]
                            if e.get("contact_id") in ids})
        except Exception as e:  # noqa: BLE001
            logger.info("stage history unavailable: %s", e)
        note = ("a lower bound, counted only among this window's consults — "
                "the CRM records just a lead's current stage, so anyone "
                "pitched and later moved on isn't counted here")
        if since:
            note += (f". {measured} of them are measured, not inferred: the "
                     f"stage recorder has been watching every change since "
                     f"{since}")
    except Exception as e:  # noqa: BLE001
        note = f"GHL stages unavailable ({str(e)[:60]}) — not recorded"
    return {"rows": rows, "count": len(rows), "lower_bound": True,
            "measured_since": locals().get("since"),
            "measured_count": locals().get("measured", 0),
            "note": note,
            "package_line": ("Propose a 'Pitched' outcome column on the "
                             "Lead-to-Cash tracker so this stage is recorded "
                             "at source (a package — the agent never writes)")}


def _closes(w0: dt.date, w1: dt.date) -> dict:
    import finance_analysis as FA
    closes = FA._closes_union(str(w0), str(w1), "activity")
    contract = round(sum(float(c.get("contract") or 0) for c in closes), 2)
    signed = round(sum(float(c.get("contract") or 0) for c in closes
                       if "derived" not in str(c.get("contract_provenance") or "tracker")), 2)
    gap = kv_store.get("gap:state") or {}
    return {"rows": closes, "count": len(closes), "contract": contract,
            "contract_signed": signed,
            "contract_derived": round(contract - signed, 2),
            "gap_open": bool((gap.get("gap") or {}).get("open"))}


def _cash_from_closes(closes: list[dict], w0: dt.date, w1: dt.date) -> dict:
    """R-CASH: Stripe receipts only, receipt-dated, from THIS window's
    closes (cohort cash). All-client receipts ride beside as context."""
    import finance_analysis as FA
    cohort = round(sum(float(c.get("cash") or 0) for c in closes), 2)
    allrec = FA._receipts_in_window(w0, w1)
    return {"cohort": cohort,
            "all_receipts": allrec.get("total") if allrec.get("available") else None,
            "source": "Stripe receipts, receipt-dated",
            "context_note": "receipts from every client — not from this window's ads"}


def _call_cache() -> dict:
    """The shared GHL call-record cache — READ ONLY, never a fetch on the
    request path (a window's roster would be hundreds of API calls)."""
    try:
        return kv_store.get("ghl:call_cache") or {}
    except Exception as e:  # noqa: BLE001
        logger.info("travelling: call cache unavailable: %s", e)
        return {}


def _setter_activity(leads: list[dict]) -> dict:
    """Effort, not a funnel ratio. Cache-only; coverage stated. The cached
    records don't carry a direction, so these are CALL RECORDS on this
    window's leads — said plainly, not dressed up as outbound dials."""
    cache = _call_cache()
    records = conversations = covered = 0
    for l in leads:
        cid = l.get("contact_id")
        hit = cache.get(cid) if cid else None
        if not hit:
            continue
        covered += 1
        for c in (hit.get("calls") or []):
            records += 1
            if (c.get("duration") or 0) >= REACHED_SECONDS:
                conversations += 1
    n = len(leads) or 1
    return {"call_records": records, "conversations": conversations,
            "coverage_pct": round(covered / n * 100, 1),
            "covered": covered, "of": len(leads),
            "note": ("read from the cached call records only — this page never "
                     "calls the CRM. The records don't say which way the call "
                     "went, so these are calls on file, not outbound dials. "
                     f"On file for {covered} of {len(leads)} leads.")}


# ── comparator ──────────────────────────────────────────────────────────────

def _comparator(compare: str, scenario: dict | None, win: dict) -> dict:
    """The thing we're travelling AGAINST. Stages a comparator doesn't model
    fall back to 'your usual' (measured rates), labelled — never an invented
    plan figure."""
    import compass_engine as CE
    d = CE.measured_defaults()["items"]
    v = lambda k, fb=None: (d.get(k) or {}).get("value", fb)
    usual = {"cpl": v("cpl"), "set_rate": v("set_rate"), "show_rate": v("show_rate"),
             "close_rate": v("close_rate"), "spend_month": v("monthly_spend_baseline"),
             "qualified_rate": None}
    out = {"key": compare, "usual": usual, "from_usual": [], "label": "",
           # A5 — a modelled comparison says "planned"; a measured one says
           # "usually". A stage the comparison doesn't model NEVER reads
           # "planned".
           "plan_word": ("planned" if compare in ("scenario", "plan")
                         else "usually")}
    share = win["days_total"] / 30.44      # scale monthly figures to the window

    if compare == "scenario" and scenario:
        sim = CE.simulate_month(scenario)
        out.update({
            "label": "the scenario on screen",
            "spend_month": sim["spend"] * share,
            "cpl": sim["cpl_base"],
            "leads_month": sim["leads"] * share,
            "set_rate": sim["rates"]["set"], "show_rate": sim["rates"]["show"],
            "close_rate": sim["rates"]["close"],
            "cash_per_client": sim["m0_share"] * sim["contract_avg"],
            "mrr_per_client": sim["mrr_avg"]})
    elif compare == "plan":
        plan = kv_store.get("compass:plan2027") or {}
        ym = str(win["end"])[:7]
        row = next((r for r in plan.get("roadmap") or [] if r["month"] == ym), None)
        pi = plan.get("inputs") or {}
        if row:
            out.update({
                "label": f"the committed plan (v{plan.get('version')})",
                "spend_month": row["spend"] * share, "leads_month": row["leads"] * share,
                "cpl": pi.get("cpl0") or usual["cpl"],
                "set_rate": pi.get("set_rate") or usual["set_rate"],
                "show_rate": pi.get("show_rate") or usual["show_rate"],
                "close_rate": pi.get("close_rate") or usual["close_rate"]})
        else:
            out["label"] = "your usual rates (no plan covers this window)"
            out["key"] = "usual"
            out["plan_word"] = "usually"
    elif compare == "last_month":
        t = win["end"]
        pm_end = t.replace(day=1) - dt.timedelta(days=1)
        pm_start = pm_end.replace(day=1)
        prev = snapshot_counts(pm_start, pm_end)
        out.update({
            "label": "last month",
            "spend_month": (prev["spend"] or 0) * (win["days_total"] /
                                                   ((pm_end - pm_start).days + 1)),
            "leads_month": prev["leads"] * (win["days_total"] /
                                            ((pm_end - pm_start).days + 1)),
            "cpl": (prev["spend"] / prev["leads"]) if prev["leads"] and prev["spend"] else usual["cpl"],
            "set_rate": (prev["booked"] / prev["leads"]) if prev["leads"] else usual["set_rate"],
            "show_rate": (prev["showed"] / prev["due"]) if prev["due"] else usual["show_rate"],
            "close_rate": (prev["closed"] / prev["showed"]) if prev["showed"] else usual["close_rate"]})
    if not out.get("label"):
        out.update({"label": "your usual rates (measured over 90 days)",
                    "key": "usual", "plan_word": "usually",
                    "spend_month": (usual["spend_month"] or 0) * share,
                    "cpl": usual["cpl"], "set_rate": usual["set_rate"],
                    "show_rate": usual["show_rate"], "close_rate": usual["close_rate"]})
        out["leads_month"] = ((out["spend_month"] / out["cpl"])
                              if out.get("cpl") else None)
    if out.get("leads_month") is None and out.get("spend_month") and out.get("cpl"):
        out["leads_month"] = out["spend_month"] / out["cpl"]
    # rate fallbacks — record which stages fell back to "your usual"
    for k in ("set_rate", "show_rate", "close_rate", "cpl"):
        if not out.get(k):
            out[k] = usual.get(k)
            out["from_usual"].append(k)
    if compare == "last_month":
        out["plan_word"] = "last month"
    return out


def snapshot_counts(w0: dt.date, w1: dt.date) -> dict:
    """Bare counts for a window (used by the last-month comparator)."""
    try:
        import meta_spend
        spend = (meta_spend.spend_in_range(str(w0), str(w1)) or {}).get("spend")
    except Exception:
        spend = None
    leads, leads_all = _lead_rows(w0, w1)
    ap = _appointments(w0, w1)
    sh = _shows(leads_all, ap["due"], w0, w1)
    cl = _closes(w0, w1)
    return {"spend": spend, "leads": len(leads), "booked": len(ap["booked"]),
            "due": len(ap["due"]), "showed": len(sh["all"]), "closed": cl["count"]}


# ── status words ────────────────────────────────────────────────────────────

def _flow_status(actual, plan_to_date, unit: str, polarity: str = "gain") -> dict:
    """Flow stages: a band around plan-to-date.

    POLARITY (A3): a GAIN metric over plan is 'ahead'; a COST metric over
    plan is 'over plan' — spending more than planned is never 'ahead'."""
    if plan_to_date is None or actual is None:
        return {"word": "no comparison", "tone": "neutral",
                "detail": "the comparison doesn't cover this stage"}
    if plan_to_date <= 0:
        return {"word": "on track", "tone": "ok", "detail": ""}
    diff = actual - plan_to_date
    if abs(diff) <= plan_to_date * BAND_PCT:
        return {"word": ("on budget" if polarity == "cost" else "on track"),
                "tone": "ok", "detail": ""}
    n = abs(diff)
    txt = (f"${n:,.0f}" if unit == "$" else f"{n:,.0f} {unit}")
    if polarity == "cost":
        return ({"word": f"{txt} over plan", "tone": "over", "detail": ""}
                if diff > 0 else
                {"word": f"{txt} under plan", "tone": "under", "detail": ""})
    return ({"word": f"{txt} ahead", "tone": "ahead", "detail": ""} if diff > 0
            else {"word": f"{txt} behind", "tone": "behind", "detail": ""})


def _rate_status(hits, n, plan_rate, polarity: str = "gain",
                 plan_word: str = "planned") -> dict:
    """Conversion stages, THREE-WAY (A4):
      · plan OUTSIDE the sample's confidence interval → ahead / behind
      · plan INSIDE it and the interval is tight (≤ threshold) → on track
      · interval wider than the threshold (small sample) → too early to tell
    A big sample sitting on its plan reads 'on track', not 'too early'."""
    if not n:
        return {"word": "too early to tell", "tone": "neutral",
                "detail": "nothing has reached this stage yet"}
    if plan_rate is None:
        return {"word": "no comparison", "tone": "neutral",
                "detail": "the comparison doesn't cover this rate"}
    p = hits / n
    half = 1.96 * math.sqrt(max(p * (1 - p), 0.01) / n)
    diff = p - plan_rate
    detail = f"{p*100:.0f}% against {plan_rate*100:.0f}% {plan_word}"
    if abs(diff) > half:
        if diff > 0:
            return ({"word": "over plan", "tone": "over", "detail": detail}
                    if polarity == "cost" else
                    {"word": "ahead", "tone": "ahead", "detail": detail})
        return ({"word": "under plan", "tone": "under", "detail": detail}
                if polarity == "cost" else
                {"word": "behind", "tone": "behind", "detail": detail})
    if half <= RATE_TIGHT:
        return {"word": "on track", "tone": "ok",
                "detail": detail + f" — {n} so far, close enough to call it level"}
    return {"word": "too early to tell", "tone": "neutral",
            "detail": f"only {n} so far — the difference is inside the "
                      f"margin for that sample"}


def _outcome_status(projected, plan_count, unit: str = "clients") -> dict:
    """A2: the OUTCOME status — projected count against the plan count. A
    stage can be on course for more clients than planned while its rate is
    well under plan; both are true and both are rendered, separately."""
    if projected is None or not plan_count:
        return {"word": "", "tone": "neutral", "detail": ""}
    diff = projected - plan_count
    if abs(diff) <= max(plan_count * BAND_PCT, 0.5):
        return {"word": "on course", "tone": "ok",
                "detail": f"{projected:.0f} projected against {plan_count:.0f} planned"}
    if diff > 0:
        return {"word": "on course to beat plan", "tone": "ahead",
                "detail": f"{projected:.0f} projected against {plan_count:.0f} planned"}
    return {"word": "short of plan", "tone": "behind",
            "detail": f"{projected:.0f} projected against {plan_count:.0f} planned"}


# ── the build ───────────────────────────────────────────────────────────────

def build(window: str = "mtd", compare: str = "scenario",
          scenario: dict | None = None, start: str | None = None,
          end: str | None = None) -> dict:
    """The whole view's payload — stages, plan markers, projections, status,
    gaps, cross-checks and the read."""
    import compass_engine as CE
    win = resolve_window(window, start, end)
    w0, w1 = win["start"], win["end"]
    cmp_ = _comparator(compare, scenario, win)
    share = win["elapsed_share"]
    remaining = win["days_remaining"]

    # ── actuals ──
    try:
        import meta_spend
        sp = meta_spend.spend_in_range(str(w0), str(w1)) or {}
        spend = sp.get("spend")
        yday = meta_spend.spend_in_range(str(w1 - dt.timedelta(days=1)),
                                         str(w1 - dt.timedelta(days=1))) or {}
        daily_run = yday.get("spend")
    except Exception as e:  # noqa: BLE001
        spend, daily_run = None, None
        logger.warning("travelling spend read failed: %s", e)

    leads, leads_all = _lead_rows(w0, w1)
    qual = _qualify(leads)
    # "your usual" qualified rate — the same rule over the prior 90 days
    usual_qual = None
    try:
        p0 = w0 - dt.timedelta(days=90)
        prior, _ = _lead_rows(p0, w0 - dt.timedelta(days=1))
        pq = _qualify(prior)
        base = len(prior) - len(pq["unknown"])
        usual_qual = (len(pq["qualified"]) / base) if base else None
    except Exception as e:  # noqa: BLE001
        logger.info("travelling: usual qualified rate unavailable: %s", e)
    ap = _appointments(w0, w1)
    sh = _shows(leads_all, ap["due"], w0, w1)
    pit = _pitched({r["contact_id"] for r in sh["all"]}, w0, w1)
    cl = _closes(w0, w1)
    cash = _cash_from_closes(cl["rows"], w0, w1)
    setter = _setter_activity(leads)

    n_leads = len(leads)
    n_booked = len(ap["booked"])
    n_due = len(ap["due"])
    n_closed = cl["count"]
    # A1 — TWO SHOW BASES. "Nobody marked a no-show" is not attendance, so
    # the PRIMARY count is the confirmed one (a call record, a recorded
    # outcome, or a deal that followed). The status-only consults form the
    # upper bound and are named everywhere they matter.
    n_showed = len(sh["verified"]) + len(sh["by_close"])      # confirmed
    n_unconfirmed = len(sh["unverified"])
    n_showed_status = n_showed + n_unconfirmed                # upper bound
    n_closed_of_confirmed = n_closed

    # ── rates ──
    r_book = (n_booked / n_leads) if n_leads else None
    r_show = (n_showed / n_due) if n_due else None            # PRIMARY
    r_show_upper = (n_showed_status / n_due) if n_due else None
    r_close = (n_closed / n_showed) if n_showed else None
    r_close_status = (n_closed / n_showed_status) if n_showed_status else None
    r_qual = (len(qual["qualified"]) /
              (n_leads - len(qual["unknown"]))) if (n_leads - len(qual["unknown"])) else None

    # ── projections (pipeline-aware; never a linear line on a lagged stage) ──
    exp_new_leads = ((daily_run or 0) / cmp_["cpl"] * remaining) if (daily_run and cmp_.get("cpl")) else 0.0
    proj_spend = (spend or 0) + (daily_run or 0) * remaining
    proj_leads = n_leads + exp_new_leads
    bk = r_book if r_book is not None else (cmp_.get("set_rate") or 0)
    proj_booked = n_booked + exp_new_leads * bk
    # projections ride the CONFIRMED rate; the upper bound lives in the row's
    # own working, never in the headline figure
    swr = r_show if r_show is not None else (cmp_.get("show_rate") or 0)
    proj_showed = n_showed + len(ap["upcoming"]) * swr
    proj_showed_upper = (n_showed_status + len(ap["upcoming"]) *
                         (r_show_upper if r_show_upper is not None else swr))
    cr = r_close if r_close is not None else (cmp_.get("close_rate") or 0)
    awaiting = max(n_showed - n_closed, 0)
    lag_in_month = 0.7                      # the measured share closing in-month
    try:
        lag = (CE.measured_defaults()["items"].get("lag_curve") or {}).get("value")
        if lag:
            lag_in_month = float(lag[0])
    except Exception:
        pass
    proj_closed = (n_closed + awaiting * cr
                   + len(ap["upcoming"]) * swr * cr
                   + exp_new_leads * bk * swr * cr * lag_in_month)
    cash_per_client = cmp_.get("cash_per_client")
    if not cash_per_client:
        try:
            sim = CE.simulate_month()
            cash_per_client = sim["m0_share"] * sim["contract_avg"]
        except Exception:
            cash_per_client = 0.0
    proj_cash = cash["cohort"] + max(proj_closed - n_closed, 0) * cash_per_client

    # ── plan-to-date (FLOW stages only) ──
    plan_spend_td = (cmp_.get("spend_month") or 0) * share or None
    plan_leads_td = (cmp_.get("leads_month") or 0) * share or None
    plan_booked_td = (plan_leads_td * (cmp_.get("set_rate") or 0)) if plan_leads_td else None

    # A2 — the plan's COUNT for each conversion stage (what the comparison
    # expects by month end), so outcome and rate are judged separately
    plan_leads_full = cmp_.get("leads_month")
    plan_booked_full = (plan_leads_full * (cmp_.get("set_rate") or 0)
                        if plan_leads_full else None)
    plan_showed_full = (plan_booked_full * (cmp_.get("show_rate") or 0)
                        if plan_booked_full else None)
    plan_closed_full = (plan_showed_full * (cmp_.get("close_rate") or 0)
                        if plan_showed_full else None)
    plan_word = cmp_.get("plan_word", "planned")

    def roster_of(rows, kind):
        out = []
        for r in rows[:400]:
            if kind == "lead":
                out.append({"person": r.get("name") or r.get("business") or "—",
                            "revenue_band": r.get("revenue_raw"),
                            "dq_reason": r.get("dq_reason"),
                            "outcome": r.get("closer_outcome") or r.get("setter_outcome"),
                            "notes": (r.get("setter_notes") or "")[:160],
                            "date": str(r.get("input_date") or "")})
            elif kind == "appt":
                out.append({"person": r.get("person") or r.get("contact_id"),
                            "when": r.get("when_text") or r.get("when"),
                            "status": r.get("status"),
                            "booked_at": (r.get("booked_at") or "")[:10]})
            elif kind == "close":
                out.append({"person": r.get("person"),
                            "date": str(r.get("close_date") or ""),
                            "contract": r.get("contract"),
                            "cash": r.get("cash"),
                            "source": r.get("provenance") or r.get("source")})
            else:
                out.append(r)
        return out

    stages = [
        {"id": "spend", "name": "Ad spend", "kind": "flow", "unit": "$",
         "actual": spend, "actual_text": (f"${spend:,.0f}" if spend is not None else "—"),
         "plan_to_date": plan_spend_td, "projection": proj_spend,
         "projection_text": f"${proj_spend:,.0f}",
         "polarity": "cost",
         "status": _flow_status(spend, plan_spend_td, "$", "cost"),
         "sub": (f"running at ${daily_run:,.0f}/day" if daily_run else
                 "today's spend is still provisional"),
         "roster": [], "roster_kind": "none",
         "math": ("Meta's daily spend archive for the window, plus today "
                  "(labelled provisional). The month-end figure adds "
                  "yesterday's daily rate for each remaining day.")},
        {"id": "leads", "name": "Leads", "kind": "flow", "unit": "leads",
         "actual": n_leads, "actual_text": f"{n_leads}",
         "plan_to_date": plan_leads_td, "projection": proj_leads,
         "projection_text": f"{proj_leads:,.0f}",
         "polarity": "gain",
         "status": _flow_status(n_leads, plan_leads_td, "leads", "gain"),
         "sub": (f"${spend / n_leads:,.0f} per lead" if spend and n_leads else ""),
         "roster": roster_of(leads, "lead"), "roster_kind": "lead",
         "math": "Tracker rows whose lead date falls in the window. Cost per "
                 "lead is spend divided by that count."},
        {"id": "qualified", "name": "Qualified", "kind": "rate",
         "actual": len(qual["qualified"]),
         "actual_text": (f"{r_qual*100:.0f}% qualified" if r_qual is not None else "—"),
         "rate": r_qual, "rate_base": n_leads - len(qual["unknown"]),
         "plan_rate": usual_qual, "projection": None, "projection_text": "",
         "plan_rate_from_usual": True, "plan_word": "usually", "polarity": "gain",
         "status": _rate_status(len(qual["qualified"]),
                                n_leads - len(qual["unknown"]), usual_qual,
                                "gain", "usually"),
         "sub": ((f"usual {usual_qual*100:.0f}% · " if usual_qual else "")
                 + f"{len(qual['unqualified'])} unqualified, "
                 f"{len(qual['unknown'])} unknown"),
         "breakdown": qual["reasons"],
         "roster": roster_of(qual["qualified"], "lead"), "roster_kind": "lead",
         "extra_rosters": {"unqualified": roster_of(qual["unqualified"], "lead"),
                           "unknown": roster_of(qual["unknown"], "lead")},
         "math": ("Not disqualified, revenue at or above $20k a month, and "
                  "the form answered. Leads without tracker context are "
                  "counted as unknown — never as unqualified.")},
        {"id": "booked", "name": "Consults booked", "kind": "flow", "unit": "consults",
         "actual": n_booked, "actual_text": f"{n_booked}",
         "plan_to_date": plan_booked_td, "projection": proj_booked,
         "projection_text": f"{proj_booked:,.0f}",
         "polarity": "gain",
         "outcome_status": _outcome_status(proj_booked, plan_booked_full, "consults"),
         "status": _flow_status(n_booked, plan_booked_td, "consults", "gain"),
         "sub": (f"{len(ap['cancelled'])} cancelled" if ap["cancelled"] else ""),
         "roster": roster_of(ap["booked"], "appt"), "roster_kind": "appt",
         "math": ("Appointments booked in the window, counted on the day they "
                  "were booked. A cancel-and-rebook counts once. This count "
                  "comes from the calendar — the tracker's set-date column has "
                  "been empty since April.")},
        {"id": "due", "name": "Consults due", "kind": "info",
         "actual": n_due, "actual_text": f"{n_due}",
         "sub": (f"{len(ap['upcoming'])} still upcoming"
                 if ap["upcoming"] else "none still upcoming"),
         "status": {"word": "", "tone": "neutral", "detail": ""},
         "roster": roster_of(ap["due"], "appt"), "roster_kind": "appt",
         "extra_rosters": {"upcoming": roster_of(ap["upcoming"], "appt")},
         "math": "Booked consults whose time has passed. Upcoming ones are "
                 "listed separately with their times."},
        {"id": "showed", "name": "Showed", "kind": "rate",
         "actual": n_showed, "actual_text": f"{n_showed}",
         "rate": r_show, "rate_base": n_due,
         "rate_upper": r_show_upper, "unconfirmed": n_unconfirmed,
         "range_text": ((f"{r_show*100:.0f}% confirmed, up to "
                         f"{r_show_upper*100:.0f}% if the {n_unconfirmed} "
                         f"unconfirmed consult{'s' if n_unconfirmed != 1 else ''} "
                         f"turned up")
                        if (r_show is not None and n_unconfirmed) else None),
         "plan_rate": cmp_.get("show_rate"), "plan_word": plan_word,
         "polarity": "gain",
         "projection": proj_showed, "projection_text": f"{proj_showed:,.0f}",
         "projection_upper": proj_showed_upper,
         "outcome_status": _outcome_status(proj_showed, plan_showed_full, "consults"),
         "status": _rate_status(n_showed, n_due, cmp_.get("show_rate"),
                                "gain", plan_word),
         "sub": (f"{n_showed} of {n_due} consults confirmed — "
                 f"{len(sh['verified'])} by a call record or a recorded outcome, "
                 f"{len(sh['by_close'])} by the deal that followed; "
                 f"{n_unconfirmed} nobody marked either way, "
                 f"{len(sh['noshow'])} marked no-show"),
         "confirm_door": (n_unconfirmed > 0),
         "roster": roster_of(sh["verified"] + sh["by_close"], "appt"),
         "roster_kind": "appt",
         "extra_rosters": {"nobody marked these": roster_of(sh["unverified"], "appt"),
                           "no-shows": roster_of(sh["noshow"], "appt")},
         "math": ("Counted only where attendance is confirmed: a call record "
                  "over a minute, a recorded outcome, or a deal that followed. "
                  "Consults nobody marked either way are NOT counted as "
                  "attendance — they set the upper end of the range. Month end "
                  "adds upcoming consults at the confirmed rate.")},
        {"id": "pitched", "name": "Pitched", "kind": "evidence",
         "actual": pit["count"],
         "actual_text": (f"at least {pit['count']}" if pit["count"]
                         else "not recorded yet"),
         "status": {"word": "lower bound" if pit["count"] else "not recorded yet",
                    "tone": "neutral", "detail": pit["note"] or ""},
         "sub": pit["note"] or "",
         "roster": pit["rows"], "roster_kind": "pitched",
         "package_line": pit["package_line"],
         "math": ("Counted only where a source records it: the lead sits in "
                  "the pitched stage, or in a closed stage. It is never "
                  "assumed from someone turning up.")},
        {"id": "closed", "name": "Closed", "kind": "rate",
         "actual": n_closed, "actual_text": f"{n_closed}",
         "rate": r_close, "rate_base": n_showed,
         "plan_rate": cmp_.get("close_rate"), "plan_word": plan_word,
         "polarity": "gain",
         "projection": proj_closed, "projection_text": f"{proj_closed:,.0f}",
         "outcome_status": _outcome_status(proj_closed, plan_closed_full, "clients"),
         "status": _rate_status(n_closed, n_showed, cmp_.get("close_rate"),
                                "gain", plan_word),
         "rate_note": ("measured against confirmed attendance — "
                       f"{n_closed} of {n_showed}"),
         "sub": ("counted inside the open gap window — labelled"
                 if cl["gap_open"] else ""),
         "roster": roster_of(cl["rows"], "close"), "roster_kind": "close",
         "math": ("New clients signed in the window. Month end adds the "
                  "consults still waiting on a decision, the upcoming ones, "
                  "and leads still to arrive — each at this window's rates.")},
        {"id": "contract", "name": "Contract value signed", "kind": "info",
         "actual": cl["contract"], "actual_text": f"${cl['contract']:,.0f}",
         "sub": (f"${cl['contract_derived']:,.0f} of that is worked out from "
                 f"the package rather than recorded" if cl["contract_derived"] else
                 "all recorded on the tracker"),
         "status": {"word": "", "tone": "neutral", "detail": ""},
         "roster": roster_of(cl["rows"], "close"), "roster_kind": "close",
         "math": "The contract value recorded against each new client."},
        {"id": "cash", "name": "Cash, new clients", "kind": "flow", "unit": "$",
         "actual": cash["cohort"], "actual_text": f"${cash['cohort']:,.0f}",
         "plan_to_date": None,
         "projection": proj_cash, "projection_text": f"${proj_cash:,.0f}",
         "status": _flow_status(cash["cohort"],
                                (cmp_.get("cash_per_client") or cash_per_client) *
                                ((cmp_.get("leads_month") or 0) * share *
                                 (cmp_.get("set_rate") or 0) *
                                 (cmp_.get("show_rate") or 0) *
                                 (cmp_.get("close_rate") or 0)) or None, "$", "gain"),
         "polarity": "gain",
         "sub": (f"${cash['all_receipts']:,.0f} came in from every client — "
                 f"not from this window's ads"
                 if cash.get("all_receipts") else ""),
         "roster": roster_of([c for c in cl["rows"] if c.get("cash")], "close"),
         "roster_kind": "close",
         "math": ("Stripe payments received in the window from clients who "
                  "signed in the window. Month end adds the projected new "
                  "clients at their first-month share.")},
    ]

    _decorate(stages, cmp_, win)
    gaps_both = _gap_finder(
        win, cmp_,
        {"leads": n_leads, "booked": n_booked, "due": n_due,
         "showed": n_showed, "showed_status": n_showed_status,
         "closed": n_closed},
        {"book": r_book, "show": r_show, "close": r_close},
        {"book": r_book, "show": r_show_upper, "close": r_close_status},
        cash_per_client, n_unconfirmed)
    gaps = gaps_both["ranked"]
    checks = _cross_checks(leads, ap, sh, cl, cash)
    # A6 — the identities this view must satisfy, stated and tested
    identities = [
        {"name": "consults booked = due + upcoming",
         "left": n_booked, "right": len(ap["due"]) + len(ap["upcoming"]),
         "note": "cancelled consults are counted beside, never inside booked"},
        {"name": "leads = qualified + unqualified + unknown",
         "left": n_leads,
         "right": (len(qual["qualified"]) + len(qual["unqualified"])
                   + len(qual["unknown"])), "note": ""},
        {"name": "consults due = confirmed + unconfirmed + no-shows",
         "left": n_due,
         "right": n_showed + n_unconfirmed + len(sh["noshow"]), "note": ""},
    ]
    for i in identities:
        i["holds"] = abs(i["left"] - i["right"]) < 0.001
    verdict = _verdict(stages, gaps, proj_closed, cmp_, win)
    read = _read(stages, gaps, proj_closed, cmp_, win, qual, n_leads,
                 gaps_both=gaps_both,
                 show_bases={"confirmed": n_showed, "unconfirmed": n_unconfirmed,
                             "upper": n_showed_status, "due": n_due,
                             "rate_confirmed": r_show, "rate_upper": r_show_upper})

    return {
        "window": {**win, "start": str(w0), "end": str(w1)},
        "compare": {"key": cmp_["key"], "label": cmp_["label"],
                    "from_usual": cmp_["from_usual"]},
        "stages": stages, "gaps": gaps, "gaps_both": gaps_both,
        "identities": identities, "checks": checks,
        "show_bases": {"confirmed": n_showed, "unconfirmed": n_unconfirmed,
                       "upper": n_showed_status, "due": n_due,
                       "rate_confirmed": r_show, "rate_upper": r_show_upper},
        "verdict": verdict, "read": read,
        "setter": setter,
        "actual_rates": {"cpl": (spend / n_leads) if (spend and n_leads) else None,
                         "set_rate": r_book, "show_rate": r_show,
                         "close_rate": r_close, "qualified_rate": r_qual,
                         "samples": {"leads": n_leads, "due": n_due,
                                     "showed": n_showed}},
        "computed_at": now_sydney().isoformat(),
        "label": "actuals beside a labelled comparison — nothing here is a "
                 "forecast of record",
    }



def _decorate(stages: list[dict], cmp_: dict, win: dict) -> None:
    """Row geometry for the dual-track funnel + the wireframe's text forms.
    The bar is a VIEW of the same numbers — the outline is the window's plan,
    the solid fill is the actual, the thin marker is where the plan should be
    today. Flow stages only: a lagged stage never gets a to-date line."""
    for s in stages:
        s["bar"] = None
        s["plan_text"] = ""
        if s["kind"] == "flow":
            plan_full = None
            if s.get("plan_to_date") and win["elapsed_share"]:
                plan_full = s["plan_to_date"] / win["elapsed_share"]
            actual = s.get("actual") or 0
            scale = max(actual, plan_full or 0, s.get("projection") or 0) or 1
            s["bar"] = {
                "plan_pct": round(min((plan_full or 0) / scale * 100, 100), 1),
                "actual_pct": round(min(actual / scale * 100, 100), 1),
                "marker_pct": (round(min(s["plan_to_date"] / scale * 100, 100), 1)
                               if s.get("plan_to_date") else None)}
            if s.get("plan_to_date"):
                v = s["plan_to_date"]
                s["plan_text"] = (f"plan ${v:,.0f} to date" if s["unit"] == "$"
                                  else f"plan {v:,.0f} to date")
        elif s["kind"] == "rate" and s.get("rate") is not None:
            word = s.get("plan_word") or cmp_.get("plan_word", "planned")
            if s.get("plan_rate"):
                s["actual_text"] = (f"{word} {s['plan_rate']*100:.0f}%, "
                                    f"actual {s['rate']*100:.0f}%")
                if s.get("plan_rate_from_usual"):
                    s["plan_text"] = ("that figure is your measured rate over "
                                      "90 days, not something anyone planned")
            else:
                s["actual_text"] = f"{s['rate']*100:.0f}%"
            # A1 — the confirmed/upper range rides directly under the rate
            if s.get("range_text"):
                s["plan_text"] = s["range_text"]
            base = s.get("rate_base") or 0
            got = s.get("actual") or 0
            s["sub"] = (f"{got:.0f} of {base:.0f}"
                        + (f" · {s['sub']}" if s.get("sub") else ""))


def _gap_chain(cmp_, counts, rates, cash_per_client) -> list[dict]:
    """(actual rate − compared rate) × the stages below it = clients and
    cash in this window. Ranked, most costly first."""
    out = []
    chain = [
        ("booking rate", rates.get("book"), cmp_.get("set_rate"), counts["leads"],
         (cmp_.get("show_rate") or 0) * (cmp_.get("close_rate") or 0)),
        ("show rate", rates.get("show"), cmp_.get("show_rate"), counts["due"],
         (cmp_.get("close_rate") or 0)),
        ("close rate", rates.get("close"), cmp_.get("close_rate"), counts["showed"], 1.0),
    ]
    for name, actual, plan, base, downstream in chain:
        if actual is None or plan is None or not base:
            continue
        clients = (actual - plan) * base * downstream
        if abs(clients) < 0.05:
            continue
        word = cmp_.get("plan_word", "planned")
        out.append({
            "stage": name, "actual_rate": round(actual, 4),
            "plan_rate": round(plan, 4), "base": base,
            "clients": round(clients, 2),
            "cash": round(clients * (cash_per_client or 0), 2),
            "rough": base < 12,
            "direction": "ahead" if clients > 0 else "behind",
            "sentence": (
                f"Your biggest gap is {name}: {actual*100:.0f}% against "
                f"{plan*100:.0f}% {word}. Closing it would be worth about "
                f"{abs(clients):.0f} client{'s' if round(abs(clients)) != 1 else ''} "
                f"and ${abs(clients) * (cash_per_client or 0):,.0f} this window."
                if clients < 0 else
                f"{name.capitalize()} is running ahead: {actual*100:.0f}% "
                f"against {plan*100:.0f}% {word} — worth about "
                f"{abs(clients):.0f} extra client"
                f"{'s' if round(abs(clients)) != 1 else ''}.")})
    out.sort(key=lambda g: g["clients"])
    return out


def _gap_finder(win, cmp_, counts, rates_verified, rates_status,
                cash_per_client, unconfirmed: int) -> dict:
    """A1: the gap ranking depends on which shows you believe. It is run on
    BOTH bases — confirmed attendance, and attendance including the consults
    nobody marked either way. When the top gap differs between them, that is
    said in one sentence: the month's conclusion hangs on those consults."""
    verified = _gap_chain(cmp_, counts, rates_verified, cash_per_client)
    status = _gap_chain(cmp_, {**counts, "showed": counts.get("showed_status",
                                                              counts["showed"])},
                        rates_status, cash_per_client)
    top_v = verified[0]["stage"] if verified else None
    top_s = status[0]["stage"] if status else None
    flip = None
    if unconfirmed and top_v and top_s and top_v != top_s:
        flip = (f"This depends on {unconfirmed} consult"
                f"{'s' if unconfirmed != 1 else ''} nobody marked either way. "
                f"If they turned up, your biggest gap is {top_s}; if they "
                f"didn't, it's {top_v}.")
    elif unconfirmed and top_v:
        flip = (f"{unconfirmed} consult{'s' if unconfirmed != 1 else ''} "
                f"nobody marked either way sit behind this — the ranking "
                f"holds either way.")
    return {"ranked": verified, "on_status_basis": status,
            "top_verified": top_v, "top_status": top_s, "flip": flip,
            "basis": "confirmed attendance"}


def _cross_checks(leads, ap, sh, cl, cash) -> list[dict]:
    """One line per stage: agreement, or the disagreement with both values.
    Authority decides the counted value; nothing is silently reconciled."""
    checks = []
    gap = (kv_store.get("gap:state") or {}).get("gap") or {}
    gap_note = (f"the tracker's outcome columns have been unfilled since "
                f"{gap.get('start')} (still open) — a difference here is that "
                f"gap, not a data error" if gap.get("open") else "")
    tracker_sets = sum(1 for l in leads if l.get("set"))
    checks.append({
        "stage": "Consults booked",
        "agree": abs(len(ap["booked"]) - tracker_sets) <= max(2, 0.15 * max(tracker_sets, 1)),
        "sources": {"calendar (counted)": len(ap["booked"]),
                   "tracker set flag": tracker_sets},
        "note": "the tracker's set-date column is empty, so the calendar leads "
                "this stage; the tracker's set flag is the cross-check"})
    tracker_shows = sum(1 for l in leads if l.get("show"))
    checks.append({
        "stage": "Showed",
        "agree": abs(len(sh["all"]) - tracker_shows) <= max(2, 0.2 * max(tracker_shows, 1)),
        "sources": {"calendar + call records (counted)": len(sh["all"]),
                   "tracker outcomes": tracker_shows},
        "note": (gap_note or "")})
    tracker_wins = sum(1 for l in leads if l.get("won"))
    checks.append({
        "stage": "Closed",
        "agree": abs(cl["count"] - tracker_wins) <= 1,
        "sources": {"counted (tracker, plus the calendar inside the gap window)": cl["count"],
                   "tracker wins on window leads": tracker_wins},
        "note": ("leads that arrived earlier can close in this window, so "
                 "these differ legitimately. " + (gap_note or "")).strip()})
    tracker_cash = round(sum(float(l.get("cash") or 0) for l in leads if l.get("won")), 2)
    checks.append({
        "stage": "Cash",
        "agree": abs(cash["cohort"] - tracker_cash) <= max(500.0, 0.1 * max(tracker_cash, 1)),
        "sources": {"Stripe (counted)": cash["cohort"],
                   "tracker cash column": tracker_cash},
        "note": ("cash is only ever taken from Stripe; the tracker column is "
                 "the team's logging and lags. " + (gap_note or "")).strip()})
    return checks


def _verdict(stages, gaps, proj_closed, cmp_, win) -> str:
    """A2: lead with the outcome that matters — clients — then diagnose the
    rate. A stage can be on course for more clients than planned while its
    rate is half of plan; the sentence says both without contradicting
    itself."""
    by = {s["id"]: s for s in stages}
    closed = by.get("closed") or {}
    outcome = closed.get("outcome_status") or {}
    bits = []
    if outcome.get("detail"):
        lead_in = {"on course to beat plan": "On course to beat the client plan",
                   "short of plan": "Short of the client plan",
                   "on course": "On course for the client plan"}.get(
                       outcome.get("word"), "On the client plan")
        bits.append(f"{lead_in}, {outcome['detail']}")
    else:
        bits.append(f"Projected {proj_closed:.0f} client"
                    f"{'s' if proj_closed >= 2 else ''} by the end of the window")
    # why: the rate diagnosis, named as a rate
    rate_bits = []
    for sid in ("close", "showed", "booked"):
        st = by.get(sid if sid != "close" else "closed") or {}
        rs = st.get("status") or {}
        if rs.get("tone") in ("behind", "under") and rs.get("detail"):
            friendly = {"Showed": "show", "Closed": "close",
                        "Consults booked": "booking"}.get(st["name"],
                                                          st["name"].lower())
            rate_bits.append(f"{friendly} rate is {rs['detail']}")
            break
    volume = by.get("leads", {}).get("status") or {}
    if volume.get("tone") == "ahead":
        bits.append(f"volume is above plan ({volume['word']})")
    if rate_bits:
        bits.append(rate_bits[0])
    tail = "; ".join(bits[1:])
    return bits[0] + "." + (" " + tail[0].upper() + tail[1:] + "." if tail else "")


def _read(stages, gaps, proj_closed, cmp_, win, qual, n_leads,
          gaps_both=None, show_bases=None) -> dict:
    """EDITH's 4–6 sentences. Every NUMBER is template-filled from the engine
    (a test matches each one back to the rendered values). She leads with the
    outcome, diagnoses the rate separately (A2), and — where the month's
    conclusion hangs on unconfirmed consults — says so (A1)."""
    by_id = {s["id"]: s for s in stages}
    numbers = {}
    sents = [_verdict(stages, gaps, proj_closed, cmp_, win)]
    numbers["projected_closed"] = round(proj_closed, 0)

    # A1 — the honesty sentence about attendance, before any gap claim
    sb = show_bases or {}
    if sb.get("unconfirmed"):
        sents.append(f"{sb['confirmed']} of {sb['due']} consults are confirmed "
                     f"attended; {sb['unconfirmed']} nobody marked either way, "
                     f"so the show rate reads "
                     f"{(sb['rate_confirmed'] or 0)*100:.0f}% confirmed and up "
                     f"to {(sb['rate_upper'] or 0)*100:.0f}% at best.")
        numbers["confirmed_shows"] = sb["confirmed"]
        numbers["unconfirmed_shows"] = sb["unconfirmed"]

    if gaps and gaps[0]["clients"] < 0:
        g = gaps[0]
        sents.append(g["sentence"] + (" That figure is rough — the sample is "
                                      "still small." if g["rough"] else ""))
        numbers["gap_clients"] = abs(round(g["clients"]))
        numbers["gap_cash"] = abs(round(g["cash"]))
    if gaps_both and gaps_both.get("flip"):
        sents.append(gaps_both["flip"])

    spend = by_id.get("spend", {})
    if spend.get("projection"):
        sents.append(f"At the current daily rate, ad spend lands near "
                     f"{spend['projection_text']} for the window.")
        numbers["projected_spend"] = round(spend["projection"], 0)

    unk = len(qual["unknown"])
    if unk and n_leads:
        sents.append(f"{unk} of {n_leads} leads have no tracker context yet, so "
                     f"they sit in unknown rather than counting against "
                     f"qualified.")
        numbers["unknown"] = unk

    lever = None
    try:
        run = (kv_store.get("compass:base_run") or {}).get("run") or {}
        row = (run.get("months") or [None])[0]
        if row and row.get("binding_constraint"):
            lever = row["binding_constraint"]["name"]
            sents.append(f"The constraint the model names for this month is "
                         f"{lever.lower()}.")
    except Exception:
        pass
    return {"sentences": sents[:6], "numbers": numbers, "lever": lever,
            "note": "the numbers here are the engine's — this paragraph only "
                    "arranges them"}


# ── actions: re-model, save, history ────────────────────────────────────────

def remodel_inputs(window: str = "mtd", start=None, end=None) -> dict:
    """"Re-model from actuals" — this window's ACTUAL rates as simulator
    inputs, each with its sample size and confidence word, labelled."""
    import compass_engine as CE
    data = build(window=window, compare="usual", start=start, end=end)
    r = data["actual_rates"]
    s = r["samples"]
    return {
        "inputs": {k: v for k, v in {
            "cpl0": r["cpl"], "set_rate": r["set_rate"],
            "show_rate": r["show_rate"], "close_rate": r["close_rate"]}.items()
            if v is not None},
        "confidence": {"set_rate": CE.confidence_word(s["leads"]),
                       "show_rate": CE.confidence_word(s["due"]),
                       "close_rate": CE.confidence_word(s["showed"])},
        "samples": s,
        "label": "if this window's rates hold",
    }


def save_check(actor: str, window: str = "mtd", compare: str = "scenario",
               scenario: dict | None = None) -> dict:
    """A dated, journaled travel report (owner-only). Its own store — it can
    never touch actuals."""
    data = build(window=window, compare=compare, scenario=scenario)
    rec = {
        "at": now_sydney().isoformat(), "by": actor,
        "window": data["window"]["label"], "compare": data["compare"]["label"],
        "verdict": data["verdict"],
        "stages": {s["id"]: {"actual": s.get("actual"),
                             "projection": s.get("projection"),
                             "status": s["status"]["word"]}
                   for s in data["stages"]},
        "top_gap": (data["gaps"][0]["stage"] if data["gaps"] else None),
    }
    log = kv_store.get(K_SAVED) or []
    log.append(rec)
    kv_store.put(K_SAVED, log[-40:])
    return {"ok": True, "saved": rec["at"], "count": len(log)}


def history(n: int = 8) -> dict:
    log = kv_store.get(K_SAVED) or []
    return {"checks": log[-n:][::-1], "total": len(log)}


def weekly_tick() -> dict:
    """The sentinel saves one check each Monday (kv-stamped)."""
    t = today_sydney()
    if t.weekday() != 0:
        return {"skipped": "not Monday"}
    stamp = f"travelling:weekly:{t.isocalendar()[0]}-{t.isocalendar()[1]}"
    if not kv_store.put_if_absent(stamp, {"at": now_sydney().isoformat()}):
        return {"skipped": "already saved this week"}
    return save_check("sentinel", window="mtd", compare="usual")


# ── EDITH drill ─────────────────────────────────────────────────────────────

import re as _re

_TRAVEL_RE = _re.compile(
    r"how (are|r) we travell?ing|how'?s? the month going|"
    r"how are we (doing|tracking) (this|the) month", _re.I)


def handle_travelling_command(text: str):
    if not _TRAVEL_RE.search(text or ""):
        return None, False
    try:
        d = build(window="mtd", compare="usual")
    except Exception as e:  # noqa: BLE001
        return f"I couldn't read the month's numbers just now: {str(e)[:100]}", True
    lines = [d["verdict"]]
    if d["gaps"]:
        lines.append(d["gaps"][0]["sentence"])
    lines.append("Open the compass and press Show how we're travelling for the "
                 "stage-by-stage view.")
    return " ".join(lines), True


# ── THE ONE SHOW-BASIS RULE ─────────────────────────────────────────────────
# Phase 0 of the finish line caught the landing's pulse tile reading
# "Show rate (verified) · 100%" while this view read 70% for the same window.
# The A1 fix (#157) landed here and never reached the compass pulse, which
# was still dividing status-only shows by sets and calling it verified.
#
# So the rule lives in ONE place now, exactly as the qualification rule did
# after #157, and every surface asks this function. Two answers to one
# question is a defect, not a difference of opinion.

def show_basis(w0: dt.date, w1: dt.date) -> dict:
    """Shows for a window, on the CONFIRMED basis, with the honest range.

    confirmed  — a call record of real length, a recorded outcome, or a close
    unconfirmed— the consult happened and nobody marked it either way
    noshow     — marked a no-show

    rate       = confirmed ÷ due          (what projections must use)
    rate_upper = (confirmed + unconfirmed) ÷ due   (if every unmarked consult
                 turned up — an upper bound, never the headline)
    """
    _inw, leads_all = _lead_rows(w0, w1)
    ap = _appointments(w0, w1)
    sh = _shows(leads_all, ap["due"], w0, w1)
    confirmed = len(sh["verified"]) + len(sh["by_close"])
    unconfirmed = len(sh["unverified"])
    noshow = len(sh["noshow"])
    due = confirmed + unconfirmed + noshow
    rate = round(confirmed / due, 4) if due else None
    upper = round((confirmed + unconfirmed) / due, 4) if due else None
    return {
        "confirmed": confirmed, "unconfirmed": unconfirmed,
        "noshow": noshow, "due": due,
        "rate": rate, "rate_upper": upper,
        "basis": "confirmed — a call record, a recorded outcome, or a close",
        "range_note": (
            f"{confirmed} confirmed of {due}"
            + (f", {unconfirmed} nobody marked either way" if unconfirmed else "")
            + (f" — {rate * 100:.0f}%" if rate is not None else "")
            + (f"–{upper * 100:.0f}% if they all turned up"
               if upper is not None and upper != rate else "")),
        "window": {"start": str(w0), "end": str(w1)},
    }


def show_basis_trailing(days: int = 30) -> dict:
    """The trailing-window form the pulse strip and TODAY use."""
    t = today_sydney()
    return show_basis(t - dt.timedelta(days=days - 1), t)
