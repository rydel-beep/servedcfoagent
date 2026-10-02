"""truth_tables.py — GROUND TRUTH FIRST: RAW ROWS, COUNTED DIRECTLY FROM RULED SOURCES (#172).

Rydel, 2 Oct: "Everything is wrong. Look at duplicates. Use the GHL calendars
for appointments and the closed-deal pipeline for closes. Check Stripe and
the tracker." This module replaces derivation with direct counting:

  APPOINTMENTS / SHOWS → GHL calendars, by appointment id. One consult per
      id; cancelled never counts; a rescheduled chain (same contact, same
      consult calendar, within 14 days, both not cancelled) counts ONCE at
      its final time and is FLAGGED for confirmation; test and onboarding
      calendars and personal-calendar follow-ups are reported separately.
      Shows come from the appointment status only: showed / noshow /
      unmarked. Nothing is assumed.
  CLOSES → the GHL "✅ Closed Deal" stage, by opportunity id, dated by the
      stage recorder where it has the move, else GHL's own last-stage-change
      time (said which) — plus Rydel's explicit rulings for deals not yet
      staged, marked "owner ruling".
  CASH → Stripe succeeded charges + Xero bank-feed client receipts, ex-GST,
      each counted once by id; Stripe payouts in the bank feed are NOT
      receipts.
  LEADS → GHL opportunities created in the window (pipeline entry), with
      the tracker's row count beside as a cross-check, never the source.
  TRACKER → cross-check and Piolo's record only.
  WINDOW → this month by default; last 7 / last 30 days as options.

Names are GHL contact names exactly as GHL holds them — never joined with
tracker names. Times show the contact's own timezone and Sydney.

build() is PURE: it takes the raw rows (a dict) and returns the tables, so
the same arithmetic runs on a saved pull, in a test, or on a live pull.
Nothing here writes to the tracker, GHL, Stripe or Xero (READ-ONLY LAW #148).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from zoneinfo import ZoneInfo

import kv_store
from helpers import SYDNEY_TZ, now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_LATEST = "truth:tables:latest"
CLOSED_STAGE_NAME = "✅ Closed Deal"
CHAIN_DAYS = 14
GST = 1.1

# ── the known GHL user ids. The token cannot list users (401), so a name
# here is only what a calendar or a ruling has proved; everything else shows
# the id and asks to be named.
KNOWN_USERS = {
    "6S3Qmfoh1X1geMDKFfVN": "Kalin Long (owner of 'Kalin Long's Personal Calendar')",
}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _when(iso: str | None):
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def _syd(d):
    return d.astimezone(SYDNEY_TZ) if d else None


def _in_window(d, w0: dt.date, w1: dt.date) -> bool:
    s = _syd(d)
    return bool(s) and w0 <= s.date() <= w1


def _contact_name(contacts: dict, cid: str | None, fallback: str = "") -> str:
    c = (contacts or {}).get(cid or "") or {}
    nm = c.get("name") or f"{c.get('firstName') or ''} {c.get('lastName') or ''}".strip()
    return nm or fallback or "(no contact name in GHL)"


def _user(uid: str | None) -> str:
    if not uid:
        return "unassigned"
    return KNOWN_USERS.get(uid) or f"GHL user {uid[:8]}… (name needed)"


def _cal_kind(name: str, ctype: str | None) -> str:
    n = (name or "").lower()
    if "test" in n:
        return "test"
    if "onboarding" in n:
        return "onboarding"
    if (ctype or "") == "personal" or "personal calendar" in n:
        return "personal"
    return "consult"


# ── APPOINTMENTS + SHOWS ────────────────────────────────────────────────────

def appointments(raw: dict, w0: dt.date, w1: dt.date) -> dict:
    contacts = raw.get("contacts_by_id") or {}
    cal_kind = {c["id"]: _cal_kind(c.get("name"), c.get("calendarType")) for c in raw.get("calendars") or []}
    rows, excluded, flags = [], [], []
    for e in raw.get("events") or []:
        if e.get("_error"):
            flags.append({"kind": "calendar unreadable", "detail": f"calendar {e.get('calendarId')}: HTTP {e['_error']}"})
            continue
        start = _when(e.get("startTime"))
        if not _in_window(start, w0, w1):
            continue
        kind = cal_kind.get(e.get("_calendarId") or e.get("calendarId"), "consult")
        status = str(e.get("appointmentStatus") or "unknown").lower()
        cid = e.get("contactId")
        c = contacts.get(cid) or {}
        tz = c.get("timezone") or "Australia/Sydney"
        try:
            local = start.astimezone(ZoneInfo(tz))
        except Exception:  # noqa: BLE001
            local, tz = _syd(start), "Australia/Sydney"
        syd = _syd(start)
        row = {
            "appointment_id": e.get("id"), "contact_id": cid,
            "contact_name": _contact_name(contacts, cid, e.get("title") or ""),
            "title": (e.get("title") or "").strip(),
            "calendar": e.get("_calendarName"), "calendar_kind": kind,
            "assigned_user": _user(e.get("assignedUserId")), "assigned_user_id": e.get("assignedUserId"),
            "start_sydney": syd.strftime("%a %d %b %Y %H:%M") if syd else None,
            "start_local": local.strftime("%a %d %b %Y %H:%M") if local else None,
            "contact_timezone": tz, "day_sydney": str(syd.date()) if syd else None,
            "_ts": start.timestamp(),
            "status": status, "rescheduled_marker": bool(e.get("rescheduledAt")),
            "created_by": _user((e.get("createdBy") or {}).get("userId")) if (e.get("createdBy") or {}).get("userId") else ((e.get("createdBy") or {}).get("source") or ""),
            "notes": (e.get("notes") or "")[:160],
        }
        if kind != "consult":
            excluded.append({**row, "why": f"{kind} calendar — not a consult"})
            continue
        if status in ("cancelled", "invalid"):
            excluded.append({**row, "why": "cancelled — never counts"})
            continue
        if syd and (syd.hour < 7 or syd.hour >= 21):
            flags.append({"kind": "outside 7am–9pm Sydney", "appointment_id": row["appointment_id"],
                          "detail": f"{row['contact_name']}: {row['start_sydney']} Sydney = "
                                    f"{row['start_local']} {tz} — likely a US lead; check which is meant"})
        if not e.get("assignedUserId"):
            flags.append({"kind": "no assigned user", "appointment_id": row["appointment_id"],
                          "detail": f"{row['contact_name']}: {row['start_sydney']}"})
        rows.append(row)
    # RESCHEDULED CHAINS: same contact, same consult calendar, within 14 days,
    # both not cancelled → ONE consult at the final time; the earlier one is
    # removed and LISTED. Flagged for Rydel either way.
    # one consult per appointment id — a row GHL returns twice is one row
    seen_ids: set = set()
    uniq = []
    for r in rows:
        if r["appointment_id"] in seen_ids:
            continue
        seen_ids.add(r["appointment_id"]); uniq.append(r)
    rows = uniq
    rows.sort(key=lambda r: r["_ts"])
    removed = []
    by_contact: dict[str, list] = {}
    for r in rows:
        by_contact.setdefault(r["contact_id"] or r["contact_name"], []).append(r)
    keep_ids = {r["appointment_id"] for r in rows}
    for cid, es in by_contact.items():
        for a, b in zip(es, es[1:]):
            same_cal = a["calendar"] == b["calendar"]
            gap = (b["_ts"] - a["_ts"]) / 86400
            if same_cal and gap <= CHAIN_DAYS and a["appointment_id"] in keep_ids:
                keep_ids.discard(a["appointment_id"])
                removed.append({**a, "why": f"rescheduled chain — counted once at {b['start_sydney']} "
                                            f"(appointment {b['appointment_id']})"})
                flags.append({"kind": "rescheduled chain (confirm)", "appointment_id": a["appointment_id"],
                              "detail": f"{a['contact_name']}: {a['start_sydney']} → {b['start_sydney']} "
                                        f"on {a['calendar']} — counted once; say if these were two consults"})
    kept = [r for r in rows if r["appointment_id"] in keep_ids]
    today = today_sydney()
    for r in kept:
        past = r["day_sydney"] and r["day_sydney"] <= str(today)
        if r["status"] in ("showed", "show"):
            r["show"] = "showed"
        elif r["status"] in ("noshow", "no-show", "no_show"):
            r["show"] = "no-show"
        elif past:
            r["show"] = "unmarked"       # 'confirmed' / 'booked' says nothing about attendance
        else:
            r["show"] = "upcoming"
    shows = {k: sum(1 for r in kept if r.get("show") == k) for k in ("showed", "no-show", "unmarked", "upcoming")}
    for r in kept + removed + excluded:
        r.pop("_ts", None)
    return {"rows": kept, "count": len(kept), "removed_duplicates": removed, "excluded": excluded,
            "flags": flags, "shows": shows,
            "note": ("one consult per GHL appointment id on the consult calendars; cancelled never "
                     "counts; a same-calendar rescheduled chain within 14 days counts once at its final "
                     "time (listed under removed); test/onboarding/personal calendars are excluded and listed")}


# ── CLOSES ──────────────────────────────────────────────────────────────────

def closes(raw: dict, w0: dt.date, w1: dt.date) -> dict:
    contacts = raw.get("contacts_by_id") or {}
    stage_names = raw.get("stages") or {}
    closed_ids = {sid for sid, nm in stage_names.items() if nm == CLOSED_STAGE_NAME}
    for p in raw.get("pipelines") or []:
        for s in p.get("stages") or []:
            if s.get("name") == CLOSED_STAGE_NAME:
                closed_ids.add(s["id"])
    recorder = {}
    for t in raw.get("stage_transitions") or []:
        if t.get("opportunity_id") and CLOSED_STAGE_NAME.split()[-1].lower() in str(t.get("to") or t.get("stage") or "").lower():
            recorder[t["opportunity_id"]] = t.get("at") or t.get("seen_at")
    rows = []
    opps = list(raw.get("opportunities") or [])
    for name, extra in (raw.get("other_pipelines") or {}).items():
        if isinstance(extra, list):
            for o in extra:
                o = dict(o); o["_pipeline"] = name
                opps.append(o)
    for o in opps:
        if o.get("pipelineStageId") not in closed_ids:
            continue
        moved_iso, dated_by = recorder.get(o.get("id")), "stage recorder"
        if not moved_iso:
            moved_iso, dated_by = o.get("lastStageChangeAt"), "GHL last stage change"
        moved = _when(moved_iso)
        if not _in_window(moved, w0, w1):
            continue
        cid = o.get("contactId")
        c = contacts.get(cid) or {}
        rows.append({
            "opportunity_id": o.get("id"), "contact_id": cid,
            "contact_name": _contact_name(contacts, cid, o.get("name") or ""),
            "business": c.get("companyName") or "(no company on the GHL contact)",
            "opportunity_name": (o.get("name") or "")[:80],
            "pipeline": o.get("_pipeline") or "1 SERVED Client Acquisition",
            "stage": CLOSED_STAGE_NAME, "moved_sydney": _syd(moved).strftime("%a %d %b %Y %H:%M"),
            "day_sydney": str(_syd(moved).date()), "dated_by": dated_by,
            "closer": _user(o.get("assignedTo")), "closer_user_id": o.get("assignedTo"),
            "ghl_value": o.get("monetaryValue"),
            "package": next((cf.get("fieldValueString") for cf in (o.get("customFields") or [])
                             if "package" in str(cf.get("id") or cf.get("key") or "").lower()), None) or "not stated in GHL",
            "source": "GHL ✅ Closed Deal",
        })
    for r in raw.get("rulings") or []:
        d = dt.date.fromisoformat(str(r["close_date"])[:10])
        if w0 <= d <= w1:
            rows.append({"opportunity_id": None, "contact_id": None, "contact_name": r.get("person"),
                         "business": r.get("client") or "(not given)", "opportunity_name": "",
                         "pipeline": "—", "stage": "owner ruling — not yet in GHL",
                         "moved_sydney": str(d), "day_sydney": str(d), "dated_by": "Rydel's ruling",
                         "closer": r.get("closer") or "not given", "closer_user_id": None,
                         "ghl_value": None, "package": r.get("package"),
                         "contract_ex_gst": r.get("contract_ex_gst"), "source": "owner ruling",
                         "note": r.get("note")})
    rows.sort(key=lambda r: r["day_sydney"])
    return {"rows": rows, "count": len(rows),
            "note": (f"every opportunity in the '{CLOSED_STAGE_NAME}' stage whose move falls in the "
                     "window, dated by the stage recorder where it saw the move, else GHL's last stage "
                     "change (each row says which); plus Rydel's rulings for deals not yet staged")}


# ── CASH ────────────────────────────────────────────────────────────────────

def cash(raw: dict, w0: dt.date, w1: dt.date) -> dict:
    rows = []
    for c in raw.get("stripe_matched") or []:
        if not (str(w0) <= c["date"] <= str(w1)):
            continue
        rows.append({"id": c["id"], "source": "Stripe", "date": c["date"], "payer": c["payer"],
                     "amount_inc": c["amount_inc"], "amount_ex": round(c["amount_inc"] / GST, 2),
                     "description": c.get("description") or "", "client": c.get("client") or "UNMATCHED",
                     "basis": c.get("basis") or ""})
    for x in raw.get("xero_receipts") or []:
        if not (str(w0) <= x["date"] <= str(w1)):
            continue
        rows.append({"id": x["id"], "source": "Xero bank feed", "date": x["date"], "payer": x["payer"],
                     "amount_inc": x["amount_inc"], "amount_ex": round(x["amount_inc"] / GST, 2),
                     "description": x.get("description") or "", "client": x.get("client") or "UNMATCHED",
                     "basis": x.get("basis") or "", "unconfirmed": x.get("unconfirmed", False)})
    seen, deduped = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"]); deduped.append(r)
    deduped.sort(key=lambda r: (r["date"], r["source"]))
    by_client: dict[str, dict] = {}
    for r in deduped:
        b = by_client.setdefault(r["client"], {"client": r["client"], "n": 0, "inc": 0.0, "ex": 0.0, "sources": set()})
        b["n"] += 1; b["inc"] = round(b["inc"] + r["amount_inc"], 2); b["ex"] = round(b["ex"] + r["amount_ex"], 2)
        b["sources"].add(r["source"])
    for b in by_client.values():
        b["sources"] = sorted(b["sources"])
    return {"rows": deduped, "count": len(deduped),
            "total_inc": round(sum(r["amount_inc"] for r in deduped), 2),
            "total_ex": round(sum(r["amount_ex"] for r in deduped), 2),
            "unmatched": [r for r in deduped if r["client"] == "UNMATCHED"],
            "by_client": sorted(by_client.values(), key=lambda b: -b["ex"]),
            "not_receipts": raw.get("xero_not_receipts") or [],
            "note": ("every Stripe succeeded charge and every Xero bank-feed client receipt in the "
                     "window, each counted once by id, ex-GST = inc ÷ 1.1; Stripe payouts landing in the "
                     "bank ('SALES') are NOT receipts and are listed separately")}


# ── LEADS ───────────────────────────────────────────────────────────────────

def leads(raw: dict, w0: dt.date, w1: dt.date) -> dict:
    rows = []
    for o in raw.get("opportunities") or []:
        created = _when(o.get("createdAt"))
        if not _in_window(created, w0, w1):
            continue
        contacts = raw.get("contacts_by_id") or {}
        rows.append({"opportunity_id": o.get("id"), "contact_id": o.get("contactId"),
                     "name": _contact_name(contacts, o.get("contactId"), (o.get("name") or "").split(":")[0]),
                     "created_sydney": _syd(created).strftime("%d %b %H:%M"), "day_sydney": str(_syd(created).date()),
                     "source": o.get("source") or "(none)",
                     "ad_tag": next((cf.get("fieldValueString") for cf in (o.get("customFields") or [])
                                     if cf.get("fieldValueString")), None),
                     "stage_now": (raw.get("stages") or {}).get(o.get("pipelineStageId"), o.get("pipelineStageId"))})
    rows.sort(key=lambda r: r["day_sydney"])
    contacts_created = [c for c in raw.get("contacts") or [] if _in_window(_when(c.get("dateAdded")), w0, w1)]
    tracker_n = (sum(1 for d in (raw.get("tracker_lead_dates") or []) if str(w0) <= str(d)[:10] <= str(w1))
                 if raw.get("tracker_lead_dates") is not None else None)
    srcs: dict[str, int] = {}
    for r in rows:
        srcs[r["source"]] = srcs.get(r["source"], 0) + 1
    return {"rows": rows, "count": len(rows), "by_source": srcs,
            "contacts_created": len(contacts_created),
            "tracker_rows": tracker_n,
            "difference": (None if tracker_n is None else len(rows) - tracker_n),
            "note": ("GHL opportunities created in the sales pipeline in the window = pipeline entry; "
                     "GHL contacts created beside it (includes payment-link and onboarding contacts, so "
                     "it is larger); the tracker's lead rows for the window as the cross-check")}


# ── THE BUILD ───────────────────────────────────────────────────────────────

def window(key: str, today: dt.date | None = None):
    t = today or today_sydney()
    if key == "last7":
        return t - dt.timedelta(days=6), t, "Last 7 days"
    if key == "last30":
        return t - dt.timedelta(days=29), t, "Last 30 days"
    if key == "sep":
        return dt.date(2026, 9, 1), dt.date(2026, 9, 30), "September 2026"
    if key == "since_sep":
        return dt.date(2026, 9, 1), t, f"1 Sep → {t:%d %b %Y}"
    return t.replace(day=1), t, f"This month ({t:%B %Y}) to date"


def build(raw: dict, window_key: str = "month", today: dt.date | None = None) -> dict:
    w0, w1, label = window(window_key, today)
    a = appointments(raw, w0, w1)
    c = closes(raw, w0, w1)
    m = cash(raw, w0, w1)
    l = leads(raw, w0, w1)
    return {"window": {"key": window_key, "label": label, "start": str(w0), "end": str(w1)},
            "appointments": a, "shows": a["shows"], "closes": c, "cash": m, "leads": l,
            "headline": {"appointments": a["count"], "showed": a["shows"]["showed"],
                         "no_show": a["shows"]["no-show"], "unmarked": a["shows"]["unmarked"],
                         "closes": c["count"], "cash_ex_gst": m["total_ex"], "leads": l["count"]},
            "pulled_at": raw.get("pulled_at"), "built_at": now_sydney().isoformat(),
            "sources": raw.get("sources_note") or {}}


def build_all(raw: dict, today: dt.date | None = None) -> dict:
    out = {"windows": {k: build(raw, k, today) for k in ("month", "sep", "since_sep", "last7", "last30")},
           "built_at": now_sydney().isoformat(), "pulled_at": raw.get("pulled_at"),
           "confirmation": raw.get("confirmation") or {"status": "unconfirmed",
                                                        "note": "Rydel has not yet confirmed these tables"}}
    return out


def latest() -> dict | None:
    st = kv_store.get(K_LATEST)
    if st:
        return st
    # a saved build committed with the repo (owner-only evidence folder)
    root = os.path.join(os.path.dirname(__file__), "dashboard", "evidence")
    try:
        dirs = sorted(d for d in os.listdir(root) if d.startswith("truth-"))
    except OSError:
        return None
    for d in reversed(dirs):
        p = os.path.join(root, d, "tables.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return None


# ── THE MARKDOWN ────────────────────────────────────────────────────────────

def _md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str("" if v is None else v).replace("|", "/") for v in r) + " |")
    return "\n".join(out)


def to_markdown(all_tables: dict, raw_flags: dict | None = None) -> str:
    L = []
    L.append("# TRUTH TABLES — 2026-10-02 (Part A, read-only)\n")
    L.append("**Status: UNCONFIRMED — awaiting Rydel.** Nothing on the dashboard changes until each table "
             "is confirmed or corrected. Sources: GHL calendars (appointments), GHL '✅ Closed Deal' stage "
             "(closes), Stripe + Xero bank feed (cash), GHL opportunities created (leads); the tracker is "
             "a cross-check only.\n")
    for key in ("sep", "month", "since_sep"):
        t = all_tables["windows"][key]
        h = t["headline"]
        L.append(f"## {t['window']['label']} — {t['window']['start']} → {t['window']['end']}\n")
        L.append(f"**Headline:** consults {h['appointments']} · showed {h['showed']} · no-show {h['no_show']} · "
                 f"unmarked {h['unmarked']} · closes {h['closes']} · cash ${h['cash_ex_gst']:,.2f} ex-GST · "
                 f"leads {h['leads']}\n")
        if key == "since_sep":
            a = t["appointments"]
            L.append("### A1 · Appointments (deduped — these COUNT)\n")
            L.append(_md_table(["Sydney time", "Contact's own time", "Contact (as GHL holds it)", "Calendar",
                                "Assigned user", "Status", "Show", "Appointment id"],
                               [[r["start_sydney"], f"{r['start_local']} {r['contact_timezone']}", r["contact_name"],
                                 r["calendar"], r["assigned_user"], r["status"], r.get("show"), r["appointment_id"]]
                                for r in a["rows"]]))
            L.append("\n### A1 · Removed as duplicates (rescheduled chains — counted once at the final time)\n")
            L.append(_md_table(["Sydney time", "Contact", "Why"], [[r["start_sydney"], r["contact_name"], r["why"]] for r in a["removed_duplicates"]]) if a["removed_duplicates"] else "_none_")
            L.append("\n### A1 · Excluded (cancelled / not a consult calendar)\n")
            L.append(_md_table(["Sydney time", "Contact", "Calendar", "Status", "Why"],
                               [[r["start_sydney"], r["contact_name"], r["calendar"], r["status"], r["why"]] for r in a["excluded"]]))
            L.append("\n### A1 · Flags for Rydel\n")
            L.append("\n".join(f"- **{f['kind']}** — {f['detail']}" for f in a["flags"]) or "_none_")
            L.append(f"\n### A2 · Shows\n\nFrom the appointment status only: showed **{a['shows']['showed']}**, "
                     f"no-show **{a['shows']['no-show']}**, unmarked **{a['shows']['unmarked']}**, upcoming "
                     f"{a['shows']['upcoming']}. GHL's 'confirmed' means the booking was confirmed, not that "
                     "the person turned up — so every past 'confirmed' consult is UNMARKED until someone marks it.\n")
            c = t["closes"]
            L.append("### A3 · Closes\n")
            L.append(_md_table(["Moved (Sydney)", "Dated by", "Contact (GHL)", "Business (GHL company)", "Opportunity name",
                                "Closer (GHL owner)", "GHL $ value", "Package", "Source", "Opportunity id"],
                               [[r["moved_sydney"], r["dated_by"], r["contact_name"], r["business"], r["opportunity_name"],
                                 r["closer"], r["ghl_value"], r.get("package"), r["source"], r["opportunity_id"]] for r in c["rows"]]))
            m = t["cash"]
            L.append(f"\n### A4 · Cash — {m['count']} receipts · ${m['total_inc']:,.2f} inc GST · **${m['total_ex']:,.2f} ex-GST**\n")
            L.append(_md_table(["Date", "Source", "Payer", "Inc GST", "Ex GST", "Matched client", "Basis", "Description", "Id"],
                               [[r["date"], r["source"], r["payer"], f"{r['amount_inc']:,.2f}", f"{r['amount_ex']:,.2f}",
                                 r["client"] + (" (unconfirmed)" if r.get("unconfirmed") else ""), r["basis"], r["description"][:50], r["id"]]
                                for r in m["rows"]]))
            L.append("\n**Cash by client (ex-GST)**\n")
            L.append(_md_table(["Client", "Receipts", "Inc GST", "Ex GST", "Via"],
                               [[b["client"], b["n"], f"{b['inc']:,.2f}", f"{b['ex']:,.2f}", ", ".join(b["sources"])] for b in m["by_client"]]))
            L.append("\n**Bank lines that are NOT receipts (not counted)**\n")
            L.append(_md_table(["Date", "Line", "Amount", "Why not counted"],
                               [[x["date"], x["payer"], f"{x['amount_inc']:,.2f}", x["why"]] for x in m["not_receipts"]]) if m["not_receipts"] else "_none_")
            l = t["leads"]
            L.append(f"\n### A5 · Leads — {l['count']} opportunities created · {l['contacts_created']} GHL contacts created · "
                     f"tracker rows {l['tracker_rows']} (difference {l['difference']})\n")
            L.append("By source: " + ", ".join(f"{k} {v}" for k, v in sorted(l["by_source"].items(), key=lambda kv: -kv[1])) + "\n")
            L.append(_md_table(["Created (Sydney)", "Contact (GHL)", "Source", "Ad tag", "Stage now", "Opportunity id"],
                               [[r["created_sydney"], r["name"], r["source"], r.get("ad_tag"), r["stage_now"], r["opportunity_id"]] for r in l["rows"]]))
    if raw_flags:
        L.append("\n## Items for Rydel to confirm or correct\n")
        for k, v in raw_flags.items():
            L.append(f"- **{k}** — {v}")
    L.append("\n---\n_Read-only throughout: nothing was written to the tracker, GHL, Stripe or Xero._\n")
    return "\n".join(L)
