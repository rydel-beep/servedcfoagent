"""sales_scoreboard.py — SALES: the team's scoreboard (the finish line, Part 3).

Per setter and per closer, for a chosen window: leads worked, consults
booked, shows on the confirmed basis with the range beside them, pitched,
closes, close rate, cash collected from their closes, and the commission
those same events accrued. Plus the pipeline by current CRM stage, the
consults in the next seven days, and — the accountability surface — every
consult whose time has passed that nobody has marked either way.

Rules this module is built on:

· ONE PARSER. Ownership (setter, closer) now comes out of
  `attribution_engine.parse_tracker`, so this is not a second reader of the
  tracker. One qualification rule, one show-basis rule, one parser.

· THE CONFIRMED BASIS. Shows come from `travelling.show_basis` — the same
  rule travelling and the pulse use. A status-only show rate is never the
  headline, and the unmarked consults behind it are named, per person.

· SMALL n IS SAID OUT LOUD. A close rate off four consults is not a close
  rate; every person's rates carry their n and a confidence word.

· R-CASH. Cash is Stripe-receipted money only. The tracker's Cash Collected
  column is shown as the tracker's own figure and labelled as such — it is
  never silently promoted to cash truth.

· READ-ONLY. Tracker and CRM are read. Nothing here writes anywhere.

· NO RULING IS ENCODED. Who marks attendance, and whether the tracker gains
  a Pitched column, are Rydel's to decide. The unmarked list simply shows
  the consult's assigned closer so that either answer works.
"""

from __future__ import annotations

import datetime as dt
import logging

from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

# Outcome words that have been typed into the ownership columns. They are not
# people and must never become a row on a scoreboard (Phase 0, DATA-QUALITY).
NOT_A_PERSON = {"showed", "cancelled", "no show", "noshow", "0", "-", "n/a",
                "na", "none", "tbc", "pending", "rebooked", "dq"}

MIN_N_CONFIDENT = 15      # below this a rate is indicative, not decisive
MIN_N_INDICATIVE = 5      # below this it is barely a signal at all


def _is_person(name: str) -> bool:
    n = (name or "").strip().lower()
    return bool(n) and n not in NOT_A_PERSON and not n.isdigit()


def confidence(n: int) -> str:
    if n >= MIN_N_CONFIDENT:
        return "enough to read"
    if n >= MIN_N_INDICATIVE:
        return "indicative only"
    return "too few to read"


def resolve_window(window: str = "mtd", start: str | None = None,
                   end: str | None = None) -> dict:
    """The same window vocabulary travelling uses, so the two agree."""
    import travelling
    return travelling.resolve_window(window, start, end)


def _rate(hits: int, n: int) -> dict:
    return {"value": (round(hits / n, 4) if n else None), "n": n,
            "hits": hits, "confidence": confidence(n),
            "text": (f"{hits / n * 100:.0f}%" if n else "—")}


def build(window: str = "mtd", start: str | None = None,
          end: str | None = None, comp_visible: bool = True) -> dict:
    """The whole scoreboard. Every block guarded: a failing source degrades
    its own section and is said plainly, never blanks the page.

    comp_visible=False (R-PIOLO, #161) strips per-person pay: the commission
    column goes, and so does the commission TOTAL whenever one person is the
    only contributor — because that total IS their pay."""
    win = resolve_window(window, start, end)
    w0, w1 = win["start"], win["end"]
    out = {"window": win, "generated_at": now_sydney().isoformat(),
           "degraded": []}

    def _guard(key, fn, empty):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            logger.warning("sales scoreboard %s failed: %s", key, e)
            out["degraded"].append({"block": key, "why": str(e)[:140]})
            return empty

    import attribution_engine as AE
    import travelling

    # travelling._lead_rows is the one reader that also bridges tracker rows
    # to CRM contacts by EMAIL-EXACT match — the attendance surface needs
    # that contact_id to find a consult's appointment.
    _inw, leads_all = _guard("tracker", lambda: travelling._lead_rows(w0, w1),
                             ([], []))

    in_window = [l for l in leads_all
                 if l.get("input_date") and w0 <= l["input_date"] <= w1]
    closes_in = [l for l in leads_all
                 if l.get("won") and l.get("close_date")
                 and w0 <= l["close_date"] <= w1]

    # ── the one show-basis rule, for the window as a whole ──
    shows = _guard("shows", lambda: travelling.show_basis(w0, w1),
                   {"confirmed": 0, "unconfirmed": 0, "due": 0, "rate": None,
                    "rate_upper": None, "range_note": "shows unavailable"})

    # ── per-person rows ──
    out["setters"] = _guard("setters", lambda: _setters(in_window), [])
    out["closers"] = _guard(
        "closers", lambda: _closers(leads_all, closes_in, w0, w1), [])
    out["pipeline"] = _guard("pipeline", _pipeline, {"stages": [], "note": ""})
    out["upcoming"] = _guard("upcoming", lambda: _upcoming(leads_all), {"rows": []})
    out["unmarked"] = _guard(
        "unmarked", lambda: _unmarked(leads_all, w0, w1), {"rows": [], "note": ""})
    out["speed_to_lead"] = _guard(
        "speed_to_lead", lambda: _speed_to_lead(in_window), {"available": False})
    out["targets"] = _guard("targets", _targets, {"available": False})

    out["totals"] = {
        "leads": len(in_window),
        "closes": len(closes_in),
        "shows_confirmed": shows.get("confirmed"),
        "shows_unconfirmed": shows.get("unconfirmed"),
        "shows_due": shows.get("due"),
        "show_rate": shows.get("rate"),
        "show_rate_upper": shows.get("rate_upper"),
        "show_range_note": shows.get("range_note"),
        "tracker_cash": round(sum(float(l.get("cash") or 0) for l in closes_in), 2),
        "contract": round(sum(float(l.get("contract") or 0) for l in closes_in), 2),
    }
    # ── the per-person pay carve-out ──
    out["comp_visible"] = bool(comp_visible)
    if not comp_visible:
        import role_access as RA
        out["comp_hidden_note"] = ("Per-person pay is owner-only. The TOTAL "
                                   "commission cost still sits inside CAC and "
                                   "the outflow bands.")
        for key in ("setters", "closers"):
            rows = out.get(key) or []
            out[key] = RA.scrub_person_pay(rows)
        out["comp_total_suppressed"] = (
            RA.hide_single_person_total(out.get("closers") or [], "closes")
            or RA.hide_single_person_total(out.get("setters") or [], "sets"))

    out["cash"] = _guard("cash", lambda: _cash(closes_in, w0, w1), {})
    out["ownership"] = _guard(
        "ownership", lambda: _ownership_health(leads_all, in_window), {})
    out["notes"] = [
        "Shows are on the CONFIRMED basis — a call record of real length, a "
        "recorded outcome, or a close. The range beside each one is what it "
        "would be if every unmarked consult had turned up.",
        "Cash is Stripe-receipted money (R-CASH). The tracker's own Cash "
        "Collected column is shown separately and labelled as the tracker's "
        "figure.",
        "Commission is read from the tracker's commission columns — the same "
        "events, never a second calculation.",
    ]
    return out


def _setters(in_window: list[dict]) -> list[dict]:
    """A setter's week: leads worked, sets made, and how many of those sets
    turned into a confirmed show and a close."""
    by: dict = {}
    for l in in_window:
        name = (l.get("setter") or "").strip()
        if not _is_person(name):
            continue
        r = by.setdefault(name, {"name": name, "leads": 0, "sets": 0,
                                 "shows_marked": 0, "closes": 0,
                                 "commission": 0.0, "qualified": 0})
        r["leads"] += 1
        if l.get("set"):
            r["sets"] += 1
        if l.get("show"):
            r["shows_marked"] += 1
        if l.get("won"):
            r["closes"] += 1
        r["commission"] += float(l.get("setter_commission") or 0)
    import attribution_engine as AE
    for l in in_window:
        name = (l.get("setter") or "").strip()
        if not _is_person(name) or name not in by:
            continue
        try:
            if AE.qualify_lead(l, None).get("qualified"):
                by[name]["qualified"] += 1
        except Exception:
            pass
    rows = []
    for r in by.values():
        r["set_rate"] = _rate(r["sets"], r["leads"])
        r["qualified_rate"] = _rate(r["qualified"], r["leads"])
        r["note"] = (
            f"{r['leads']} leads worked in this window · "
            f"{r['set_rate']['confidence']}")
        rows.append(r)
    rows.sort(key=lambda x: -x["leads"])
    return rows


def _closers(leads_all: list[dict], closes_in: list[dict],
             w0: dt.date, w1: dt.date) -> list[dict]:
    """A closer's window: the consults that were theirs, how many are
    confirmed attended, how many closed, and what that earned.

    THE CONSULT, NOT THE SET DATE. The tracker's Set Date column has been
    empty since April (the same diagnosis travelling carries), so keying a
    closer's workload on it returns nothing at all. The consults counted
    here are the GHL appointments DUE in this window — the same source and
    the same clock travelling uses — joined to their tracker row for the
    ownership.

    A consult whose tracker row names no closer is counted under
    "unassigned" rather than dropped: the work happened, and a scoreboard
    that hides it would flatter the column that has stopped being filled.
    """
    import travelling
    calls = travelling._call_cache()
    by: dict = {}
    by_contact = {l["contact_id"]: l for l in leads_all if l.get("contact_id")}

    def row(name):
        return by.setdefault(name, {
            "name": name, "consults": 0, "confirmed": 0, "unconfirmed": 0,
            "noshow": 0, "closes": 0, "commission": 0.0, "tracker_cash": 0.0,
            "contract": 0.0, "pitched_lower_bound": 0})

    ap = travelling._appointments(w0, w1)
    for appt in ap["due"]:
        l = by_contact.get(appt.get("contact_id")) or {}
        raw = (l.get("closer") or "").strip()
        name = raw if _is_person(raw) else "unassigned"
        r = row(name)
        r["consults"] += 1
        outcome = (l.get("closer_outcome") or "").lower()
        if appt.get("status") == "noshow" or outcome in ("no show", "noshow"):
            r["noshow"] += 1
        elif l.get("won") or l.get("show") or outcome:
            r["confirmed"] += 1
        elif any((c.get("duration") or 0) >= travelling.REACHED_SECONDS
                 for c in ((calls.get(appt.get("contact_id")) or {}).get("calls") or [])):
            r["confirmed"] += 1
        else:
            r["unconfirmed"] += 1

    for l in closes_in:
        raw = (l.get("closer") or "").strip()
        name = raw if _is_person(raw) else "unassigned"
        r = row(name)
        r["closes"] += 1
        r["commission"] += float(l.get("closer_commission") or 0)
        r["tracker_cash"] += float(l.get("cash") or 0)
        r["contract"] += float(l.get("contract") or 0)

    # PITCHED — measured where the recorder has watched, a labelled lower
    # bound before that. No ruling is encoded here either way.
    measured_since = None
    try:
        import stage_history
        measured_since = stage_history.started_at()
    except Exception:
        pass

    rows = []
    for r in by.values():
        r["close_rate"] = _rate(r["closes"], r["confirmed"])
        r["show_rate"] = _rate(r["confirmed"], max(
            r["confirmed"] + r["unconfirmed"] + r["noshow"], 0))
        upper = r["confirmed"] + r["unconfirmed"]
        denom = upper + r["noshow"]
        r["show_range"] = (
            f"{r['confirmed']} of {denom} confirmed"
            + (f", {r['unconfirmed']} nobody marked" if r["unconfirmed"] else "")
            + (f" — {r['confirmed'] / denom * 100:.0f}%–{upper / denom * 100:.0f}%"
               if denom else ""))
        r["commission"] = round(r["commission"], 2)
        r["tracker_cash"] = round(r["tracker_cash"], 2)
        r["contract"] = round(r["contract"], 2)
        r["pitched_note"] = (
            f"measured from {measured_since}" if measured_since
            else "a lower bound — the CRM keeps only a deal's current stage")
        r["note"] = (f"{r['confirmed']} confirmed consults · "
                     f"{r['close_rate']['confidence']}")
        rows.append(r)
    rows.sort(key=lambda x: -x["consults"])
    return rows


def _ownership_health(leads_all: list[dict], in_window: list[dict]) -> dict:
    """Is the tracker's Closer column still being filled?

    All-time it names Kalin and Coby on 145 rows, so it WAS filled. If this
    window is mostly blank, the scoreboard cannot attribute consults to
    anyone — and that is a finding about the source, not a gap to paper
    over with a guess.
    """
    named_all = sum(1 for l in leads_all if _is_person((l.get("closer") or "").strip()))
    named_win = sum(1 for l in in_window if _is_person((l.get("closer") or "").strip()))
    n = len(in_window)
    bad = [((l.get("closer") or "").strip()) for l in leads_all
           if (l.get("closer") or "").strip()
           and not _is_person((l.get("closer") or "").strip())]
    pct = round(named_win / n * 100, 1) if n else None
    return {
        "named_in_window": named_win, "of": n, "pct": pct,
        "named_all_time": named_all,
        "outcome_words_in_column": sorted(set(bad)),
        "healthy": bool(pct is not None and pct >= 50),
        "note": (
            f"the tracker's Closer column names someone on {named_win} of "
            f"{n} leads in this window ({pct}%), against {named_all_time_txt(named_all)} "
            f"all time. Consults whose row names nobody are counted under "
            f"'unassigned' — they happened, so hiding them would flatter the "
            f"column rather than the team."),
        "setter_note": (
            "the tracker's Set Date column has been empty since April, so a "
            "closer's consults are counted from the CRM appointments instead "
            "— the same source and clock travelling uses."),
    }


def named_all_time_txt(n: int) -> str:
    return f"{n} rows"


def _pipeline() -> dict:
    """What is open right now, by current CRM stage, with values. A snapshot
    of the present — never a window."""
    import ghl_mirror
    opps = ghl_mirror.read_opportunities(open_only=False) or []
    stages: dict = {}
    for o in opps:
        st = (o.get("stage_name") or "unstaged").strip()
        s = stages.setdefault(st, {"stage": st, "count": 0, "value": 0.0})
        s["count"] += 1
        try:
            s["value"] += float(o.get("monetary_value") or 0)
        except (TypeError, ValueError):
            pass
    rows = sorted(stages.values(), key=lambda x: -x["count"])
    for r in rows:
        r["value"] = round(r["value"], 2)
    return {"stages": rows, "total": len(opps),
            "note": ("every opportunity in the CRM mirror by its CURRENT "
                     "stage — a snapshot of now, not of this window")}


def _crm_names() -> dict:
    """contact_id → the person's name, from the CRM mirror. A raw id is not
    a name, and showing one on a scoreboard helps nobody."""
    try:
        import ghl_mirror
        out = {}
        for cid, c in (ghl_mirror.read_all_contacts() or {}).items():
            nm = " ".join(str(x) for x in (c.get("first_name"), c.get("last_name"))
                          if x).strip() or c.get("name") or c.get("email")
            if nm:
                out[cid] = nm
        return out
    except Exception as e:  # noqa: BLE001
        logger.info("sales: CRM names unavailable: %s", e)
        return {}


def _upcoming(leads_all: list[dict]) -> dict:
    """Consults in the next seven days, with datetime and the closer they
    belong to. Reads the CALENDAR-LEVEL source (#162); the per-contact cache
    showed only tracker-lead contacts — 3 of the 12 booked."""
    import appointments
    if (appointments.store() or {}).get("events"):
        up = appointments.upcoming(7)
        by_contact = {l["contact_id"]: l for l in leads_all if l.get("contact_id")}
        crm = _crm_names()
        rows = []
        now_iso = now_sydney().isoformat()
        for e in up["rows"]:
            l = by_contact.get(e.get("contact_id")) or {}
            rows.append({
                "when": e["when"],
                "when_text": appointments.format_when(e["when"]),
                "person": (l.get("name") or l.get("business")
                           or crm.get(e.get("contact_id"))
                           or (e.get("title") or "").split(" Served")[0].strip()
                           or "name not on file"),
                "business": l.get("business") or "",
                "closer": ((l.get("closer") or "").strip()
                           or (e.get("owner") if not str(e.get("owner", "")).endswith("…")
                               else "") or "unassigned"),
                "contact_id": e.get("contact_id"),
                "follow_up": e.get("follow_up"),
                "in_days": round((dt.datetime.fromisoformat(e["when"])
                                  - dt.datetime.fromisoformat(now_iso)
                                  ).total_seconds() / 86400, 1) if e.get("when") else None})
        return {"rows": rows, "count": len(rows),
                "window_words": up["window_words"],
                "cancelled_count": up["cancelled_count"],
                "note": ("every calendar in the CRM, read directly ("
                         + up["window_words"] + ") — cancelled bookings are "
                         "counted beside, never inside. The closer is the "
                         "tracker's assignment, else the calendar's owner.")}
    import consult_schedule as CS
    cache = CS._cache() or {}
    now = now_sydney()
    horizon = now + dt.timedelta(days=7)
    by_contact = {l["contact_id"]: l for l in leads_all if l.get("contact_id")}
    crm = _crm_names()
    rows = []
    for cid, hit in cache.items():
        for a in ((hit or {}).get("appts") or []):
            status = str(a.get("appointmentStatus") or a.get("status") or "").lower()
            if status in ("cancelled", "invalid"):
                continue
            start = CS.parse_appt_dt(a.get("startTime"))
            if not start or not (now <= start <= horizon):
                continue
            l = by_contact.get(cid) or {}
            rows.append({
                "when": start.isoformat(),
                "when_text": CS.format_consult(start),
                "person": (l.get("name") or l.get("business")
                           or crm.get(cid) or "name not on file"),
                "business": l.get("business") or "",
                "closer": (l.get("closer") or "").strip() or "unassigned",
                "contact_id": cid,
                "in_days": round((start - now).total_seconds() / 86400, 1)})
    rows.sort(key=lambda r: r["when"])
    return {"rows": rows, "count": len(rows),
            "note": ("kept appointments from the CRM cache — cancelled never "
                     "counts. The closer is the tracker's own assignment.")}


def _unmarked(leads_all: list[dict], w0: dt.date, w1: dt.date) -> dict:
    """THE ACCOUNTABILITY SURFACE: consults whose time has passed that nobody
    marked showed or no-show, per closer, with age in days.

    This is the list that decides whether a month's show rate is 70% or
    100%. It does NOT encode who should mark them — it shows the consult's
    assigned closer so that whichever way Rydel rules, the list already says
    who it sits with.
    """
    import consult_schedule as CS
    import travelling
    cache = CS._cache() or {}
    calls = travelling._call_cache()
    now = now_sydney()
    today = today_sydney()
    by_contact = {l["contact_id"]: l for l in leads_all if l.get("contact_id")}
    crm = _crm_names()
    rows = []
    for cid, hit in cache.items():
        for a in ((hit or {}).get("appts") or []):
            status = str(a.get("appointmentStatus") or a.get("status") or "").lower()
            if status in ("cancelled", "invalid"):
                continue
            start = CS.parse_appt_dt(a.get("startTime"))
            if not start or start > now:
                continue
            if not (w0 <= start.date() <= w1):
                continue
            l = by_contact.get(cid) or {}
            if l.get("won") or l.get("show") or (l.get("closer_outcome") or ""):
                continue                      # somebody marked it
            if any((c.get("duration") or 0) >= travelling.REACHED_SECONDS
                   for c in ((calls.get(cid) or {}).get("calls") or [])):
                continue                      # a call record confirms it
            rows.append({
                "when": start.isoformat(), "when_text": CS.format_consult(start),
                "person": (l.get("name") or l.get("business")
                           or crm.get(cid) or "name not on file"),
                "closer": (l.get("closer") or "").strip() or "unassigned",
                "contact_id": cid,
                "age_days": (today - start.date()).days})
    rows.sort(key=lambda r: -r["age_days"])
    by_closer: dict = {}
    for r in rows:
        c = by_closer.setdefault(r["closer"], {"closer": r["closer"], "count": 0,
                                               "oldest_days": 0})
        c["count"] += 1
        c["oldest_days"] = max(c["oldest_days"], r["age_days"])
    return {"rows": rows, "count": len(rows),
            "by_closer": sorted(by_closer.values(), key=lambda x: -x["count"]),
            "note": ("the consult happened and nobody marked it either way. "
                     "These are the consults the month's show rate turns on.")}


def _speed_to_lead(in_window: list[dict]) -> dict:
    """Only if it is measurable — and the coverage is always stated."""
    have = [l for l in in_window if l.get("called_within_5") is not None]
    marked = [l for l in in_window if l.get("called_within_5")]
    n = len(in_window)
    if not n:
        return {"available": False, "note": "no leads in this window"}
    # the column is a yes/no; a blank is not a "no", it is an unknown
    known = [l for l in in_window if str(l.get("setter_outcome") or "").strip()
             or l.get("called_within_5")]
    if not known:
        return {"available": False,
                "note": ("the tracker's 'Called Within 5 Mins?' column is "
                         "blank for every lead in this window — speed to "
                         "lead is not measurable here")}
    return {"available": True, "within_5": len(marked), "of": n,
            "rate": round(len(marked) / n, 4),
            "coverage": f"{len(known)} of {n} leads carry any setter activity",
            "note": ("read from the tracker's own 'Called Within 5 Mins?' "
                     "column. A blank is an unknown, never a no.")}


def _cash(closes_in: list[dict], w0: dt.date, w1: dt.date) -> dict:
    """R-CASH: Stripe receipts from THIS window's closes."""
    import finance_analysis as FA
    cohort = FA._closes_union(str(w0), str(w1), "activity")
    by_closer: dict = {}
    tracker_by_name = {}
    for l in closes_in:
        nm = (l.get("closer") or "").strip()
        if _is_person(nm):
            tracker_by_name[(l.get("name") or "").strip().lower()] = nm
    for c in cohort:
        nm = tracker_by_name.get((c.get("person") or c.get("name") or "").strip().lower())
        if not nm:
            continue
        by_closer[nm] = round(by_closer.get(nm, 0.0) + float(c.get("cash") or 0), 2)
    return {"by_closer": by_closer,
            "total": round(sum(by_closer.values()), 2),
            "source": "Stripe receipts, receipt-dated (R-CASH)",
            "note": ("cash from THIS window's closes. A close that collects "
                     "next month shows there, not here.")}


def _targets() -> dict:
    """Targets from the 'Closer Payout & KPI' tab.

    The tab reads fine, and its KPI block holds Value/Target pairs — but the
    ROW LABELS are not in the export (they live in merged or formatted
    cells), so no target can be attached to a metric without guessing which
    is which. Rather than guess, this reports what it found and says what is
    missing. Phase 0 raised it as a decision card.
    """
    try:
        import sheet_mirror
        from config import SHEET_CONFIG
        rows = sheet_mirror._live_fetch(SHEET_CONFIG["sheet_id"],
                                        "Closer Payout & KPI") or []
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"the payout tab did not read ({str(e)[:70]})"}
    pairs = []
    for r in rows[:40]:
        val = (r[1] if len(r) > 1 else "").strip()
        tgt = (r[2] if len(r) > 2 else "").strip()
        if val and tgt and tgt[0] in "≥≤<>":
            pairs.append({"value": val, "target": tgt})
    return {
        "available": False, "found": pairs,
        "note": ("the tab holds these value/target pairs but the export "
                 "carries no row labels for them, so none can be attached to "
                 "a metric without guessing. Label the rows and they appear "
                 "here — a guess would be worse than a gap."),
    }
