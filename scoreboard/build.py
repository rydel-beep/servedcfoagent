"""build.py — every scoreboard number, counted from the raw rows.

PURE: build(raw, window, now, decisions, settings) takes the stored records
and returns every number WITH the rows behind it. Nothing is fetched here,
nothing is written, and no old engine is called.

One number, one source:
  ad spend, Meta-reported leads ...... Meta (account level, per day)
  leads .............................. GHL contacts whose own record says "from an ad"
  calls .............................. GHL calendars, by appointment id
  closes ............................. GHL '✅ Closed Deal' stage, by opportunity id
  deal details ....................... the Closed Deal Form on the GHL contact
  cash ............................... Stripe succeeded charges (net of refunds)
                                       + Xero bank-feed client receipts, by id
  commissions ........................ the comp rulebook (+ owner deal rulings)
  the tracker ........................ reconciliation only
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from decimal import Decimal

from helpers import SYDNEY_TZ

from . import rules as R

logger = logging.getLogger(__name__)

CLOSED_WON = ("✅ Closed Deal",)
CHAIN_DAYS = 14
LTV_CAP_MONTHS = 36

# Rydel's confirmed payer → client aliases (carried over, his words)
ALIASES = {
    "sanatani rombola": "Pompoko Bar",
    "eunsung cho": "Amoroso Gelateria",
    "ozan ozsoy": "Rose Borek",
    "pottery green bakers gordon": "Pottery Green",
    "fiona fitzgerald": "62Thirty Cafe & Bar",
    "nirosha jayasekara": "Walkway to Ceylon",
}

# Rydel's own list of closes — a CROSS-CHECK on GHL, never a source.
KNOWN_CLOSES = {
    "2026-09": [("Orlando Rinaldi", "Food Corp Pizza Pasta & Ribs"),
                ("Harman Singh", "Grappino Ristorante Trattoria"),
                ("William Cooney", "Phoenix Hotel"), ("Koji", "Pompoko Bar"),
                ("Scott Cho", "Amoroso Gelateria"), ("Max", "Rocky's Italian")],
    "2026-10": [("Rose Borek", "Rose Borek")],
}

D0 = Decimal("0")


# ── shapes ──────────────────────────────────────────────────────────────────

def metric(key, label, value, unit, definition, rows=None, sum_field=None, kind="fact",
           note=None, parts=None, check=None, based_on=None):
    if isinstance(value, Decimal):
        value = R.f2(value)
    return {"key": key, "label": label, "value": value, "unit": unit, "definition": definition,
            "rows": rows if rows is not None else [], "sum_field": sum_field, "kind": kind,
            "note": note, "parts": parts, "check": check, "based_on": based_on}


def _div(a, b, places=2):
    if a is None or b in (None, 0, D0):
        return None
    return round(float(a) / float(b), places)


def _plain(o):
    if isinstance(o, Decimal):
        return R.f2(o)
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return sorted(_plain(v) for v in o)
    return o


def _fmt_syd(d: dt.datetime | None) -> str | None:
    return d.astimezone(SYDNEY_TZ).strftime("%a %-d %b %Y %-I:%M%p").replace("AM", "am").replace("PM", "pm") if d else None


# ── people (GHL users) ──────────────────────────────────────────────────────

def user_names(raw: dict, decisions: dict) -> dict:
    """GHL user id → name. The token can't list users, so a name comes only
    from Rydel (journaled) or from a personal calendar that is named for its
    owner and only holds that user's bookings."""
    names = {}
    cals = raw.get("calendar") or {}
    by_cal: dict[str, set] = {}
    for e in (raw.get("event") or {}).values():
        if e.get("assignedUserId"):
            by_cal.setdefault(e.get("calendarId"), set()).add(e["assignedUserId"])
    for cid, c in cals.items():
        nm = str(c.get("name") or "")
        if c.get("calendarType") == "personal" and nm.endswith("'s Personal Calendar") and len(by_cal.get(cid, ())) == 1:
            uid = next(iter(by_cal[cid]))
            names[uid] = {"name": nm[: -len("'s Personal Calendar")], "how": f"owner of '{nm}'"}
    for k, d in decisions.items():
        if k.startswith("user:"):
            names[k[5:]] = {"name": d["data"].get("name"), "how": f"named by {d['actor']}"}
    return names


def cname(c: dict) -> str:
    """The contact's name as typed (GHL's plain name fields are lowercased)."""
    first = c.get("firstNameRaw") or c.get("firstName") or ""
    last = c.get("lastNameRaw") or c.get("lastName") or ""
    return f"{first} {last}".strip() or c.get("contactName") or ""


def _who(uid, users) -> str:
    if not uid:
        return "nobody assigned"
    u = users.get(uid)
    return u["name"] if u else f"GHL user {uid[:8]}… (name needed)"


# ── LEADS ───────────────────────────────────────────────────────────────────

def leads(raw: dict, w: dict) -> dict:
    contacts = raw.get("contact") or {}
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys_of = {}
    for cid, c in contacts.items():
        ks = {f"e:{e}" for e in [R.norm_email(c.get("email"))] +
              [R.norm_email(x.get("email") if isinstance(x, dict) else x) for x in c.get("additionalEmails") or []] if e}
        ks |= {f"p:{p}" for p in [R.norm_phone(c.get("phone"))] if p}
        keys_of[cid] = ks
        parent.setdefault(f"c:{cid}", f"c:{cid}")
        for k in ks:
            parent.setdefault(k, k)
            union(f"c:{cid}", k)
    people: dict[str, list] = {}
    excluded = []
    fb_no_ad = []
    for cid, c in contacts.items():
        reason = R.ad_lead_reason(c)
        if not reason:
            if R.facebook_source_without_ad(c) and R.in_window(R.syd_date(c.get("dateAdded")), w):
                fb_no_ad.append({"contact_id": cid, "name": cname(c), "created_sydney": _fmt_syd(R.parse_when(c.get("dateAdded"))),
                                 "source": c.get("source"),
                                 "why": "GHL's source says Facebook, but no paid ad visit is recorded — not counted"})
            continue
        name = cname(c) or "(no name)"
        added = R.parse_when(c.get("dateAdded"))
        row = {"contact_id": cid, "name": name, "email": c.get("email"), "phone": c.get("phone"),
               "created_sydney": _fmt_syd(added), "day": R.syd_date(c.get("dateAdded")),
               "why_a_lead": reason, "source": c.get("source")}
        if R.is_test(name, c.get("email")):
            excluded.append({**row, "why": "test contact"})
            continue
        people.setdefault(find(f"c:{cid}"), []).append(row)
    rows, repeats_outside = [], []
    for _, subs in people.items():
        subs.sort(key=lambda r: (r["day"] or dt.date.max, r["contact_id"]))
        first = subs[0]
        rep = [{"contact_id": s["contact_id"], "created_sydney": s["created_sydney"], "name": s["name"]}
               for s in subs[1:]]
        if R.in_window(first["day"], w):
            rows.append({**first, "repeat_submissions": rep, "dedupe": (
                f"one person = one lead: {len(subs)} contacts share an email or phone; counted once at the first"
                if rep else "")})
        else:
            for s in subs[1:]:
                if R.in_window(s["day"], w):
                    repeats_outside.append({**s, "why": f"already a lead since {first['day']} — repeat, not counted"})
    rows.sort(key=lambda r: r["day"])
    return {"rows": rows, "excluded": excluded, "repeats_not_counted": repeats_outside, "facebook_no_ad": fb_no_ad}


def meta_days(raw: dict, w: dict, today: dt.date) -> dict:
    acct = raw.get("account_day") or {}
    ads = raw.get("ad_day") or {}
    rows, missing = [], []
    by_day_ads: dict[str, Decimal] = {}
    for k, a in ads.items():
        by_day_ads[a["date_start"]] = by_day_ads.get(a["date_start"], D0) + R.money(a.get("spend"))
    d = w["start"]
    while d <= w["end"]:
        a = acct.get(str(d))
        if not a:
            missing.append(str(d))
        else:
            leads_n = sum(int(float(x.get("value") or 0)) for x in a.get("actions") or [] if x.get("action_type") == "lead")
            sp = R.money(a.get("spend"))
            ad_sum = by_day_ads.get(str(d))
            rows.append({"day": str(d), "spend": sp, "impressions": int(float(a.get("impressions") or 0)),
                         "clicks": int(float(a.get("clicks") or 0)), "meta_leads": leads_n,
                         "final": bool(a.get("_final")) and d < today,
                         "status": "closed day (final)" if a.get("_final") and d < today else
                                   ("today so far — not final" if d == today else "not yet re-read as final"),
                         "ad_level_sum": ad_sum,
                         "ad_level_matches": (None if ad_sum is None else ad_sum == sp)})
        d += dt.timedelta(days=1)
    return {"rows": rows, "missing_days": missing}


# ── CALLS ───────────────────────────────────────────────────────────────────

def calendar_kind(c: dict, decisions: dict) -> str:
    dec = decisions.get(f"calendar:{c.get('id')}")
    if dec:
        return "consult" if dec["data"].get("counts") else "not a sales call"
    n = str(c.get("name") or "").lower()
    if "test" in n:
        return "test"
    if "onboarding" in n:
        return "onboarding"
    if c.get("calendarType") == "personal":
        return "personal"
    return "consult"


def calls(raw: dict, w: dict, now: dt.datetime, users: dict, decisions: dict) -> dict:
    cals = raw.get("calendar") or {}
    kinds = {cid: calendar_kind(c, decisions) for cid, c in cals.items()}
    contacts = raw.get("contact") or {}
    evs = []
    other = []
    for eid, e in (raw.get("event") or {}).items():
        start = R.parse_when(e.get("startTime"))
        if not start:
            continue
        cid = e.get("contactId")
        c = contacts.get(cid) or {}
        tz = e.get("_calendarTimezone") or (cals.get(e.get("calendarId")) or {}).get("timezone") or "Australia/Sydney"
        try:
            from zoneinfo import ZoneInfo
            local = start.astimezone(ZoneInfo(tz)).strftime("%a %-d %b %-I:%M%p").replace("AM", "am").replace("PM", "pm") + f" ({tz})"
        except Exception:  # noqa: BLE001
            local = None
        status = str(e.get("appointmentStatus") or e.get("appoinmentStatus") or "").lower()
        row = {"appointment_id": eid, "contact_id": cid,
               "contact": cname(c) or (e.get("title") or "").split(":")[0] or "(no contact)",
               "calendar": e.get("_calendarName") or (cals.get(e.get("calendarId")) or {}).get("name"),
               "calendar_id": e.get("calendarId"), "kind": kinds.get(e.get("calendarId"), "consult"),
               "assigned_to": _who(e.get("assignedUserId"), users), "assigned_user_id": e.get("assignedUserId"),
               "when_sydney": _fmt_syd(start), "when_calendar_tz": local, "day": start.astimezone(SYDNEY_TZ).date(),
               "_ts": start, "status_in_ghl": status or "(blank)", "booked_at": _fmt_syd(R.parse_when(e.get("dateAdded"))),
               "gone": bool(e.get("_gone")) or bool(e.get("deleted"))}
        if row["kind"] != "consult":
            other.append(row)
        else:
            evs.append(row)
    # reschedule chains: the same person on the same calendar again within 14
    # days, the earlier booking never marked (not showed / no-show) and not
    # cancelled → one call, counted at the FINAL time; the earlier is listed.
    live = [r for r in evs if not r["gone"] and r["status_in_ghl"] not in ("cancelled", "invalid")]
    live.sort(key=lambda r: r["_ts"])
    collapsed = {}
    by_person: dict[str, list] = {}
    for r in live:
        by_person.setdefault(r["contact_id"] or r["appointment_id"], []).append(r)
    for _, rs in by_person.items():
        for a, b in zip(rs, rs[1:]):
            if (a["calendar_id"] == b["calendar_id"] and (b["_ts"] - a["_ts"]).total_seconds() <= CHAIN_DAYS * 86400
                    and a["status_in_ghl"] not in ("showed", "noshow")):
                collapsed[a["appointment_id"]] = b
    # follow chains to their final booking
    def final_of(r):
        seen = set()
        while r["appointment_id"] in collapsed and r["appointment_id"] not in seen:
            seen.add(r["appointment_id"]); r = collapsed[r["appointment_id"]]
        return r
    booked, cancelled, removed, invalid = [], [], [], []
    for r in evs:
        if not R.in_window(r["day"], w) and not (r["appointment_id"] in collapsed and R.in_window(final_of(r)["day"], w)):
            continue
        if r["gone"]:
            continue
        if r["status_in_ghl"] == "cancelled":
            if R.in_window(r["day"], w):
                cancelled.append({**r, "why": "cancelled — never counts as booked"})
            continue
        if r["status_in_ghl"] == "invalid":
            if R.in_window(r["day"], w):
                invalid.append({**r, "why": "marked invalid in GHL — not counted"})
            continue
        if r["appointment_id"] in collapsed:
            f = final_of(r)
            removed.append({**r, "why": f"rescheduled — counted once at its final time {f['when_sydney']} "
                                        f"(appointment {f['appointment_id']})"})
            continue
        if not R.in_window(r["day"], w):
            continue
        if r["status_in_ghl"] == "showed":
            r["outcome"] = "held"
        elif r["status_in_ghl"] == "noshow":
            r["outcome"] = "no-show"
        elif r["_ts"] <= now:
            r["outcome"] = "unmarked"
            r["age_days"] = (now.date() - r["day"]).days
        else:
            r["outcome"] = "still to come"
        booked.append(r)
    for coll in (booked, cancelled, removed, invalid, other):
        coll.sort(key=lambda r: r["_ts"])
    other_in_w = [r for r in other if R.in_window(r["day"], w) and not r["gone"]]
    return {"booked": booked, "cancelled": cancelled, "rescheduled_removed": removed, "invalid": invalid,
            "other_calendars": other_in_w,
            "calendar_kinds": [{"calendar_id": k, "name": (cals.get(k) or {}).get("name"), "kind": v,
                                "counted": v == "consult"} for k, v in sorted(kinds.items(), key=lambda kv: kv[1])]}


# ── CLOSES + DEAL DETAILS ───────────────────────────────────────────────────

def _stage_names(raw):
    out = {}
    for p in (raw.get("pipeline") or {}).values():
        for s in p.get("stages") or []:
            out[s["id"]] = (p.get("name"), s.get("name"))
    return out


def deals(raw: dict, users: dict, decisions: dict, rulings: dict) -> list[dict]:
    """Every opportunity in the Closed Won stage, with its deal details."""
    stages = _stage_names(raw)
    contacts = raw.get("contact") or {}
    entered = raw.get("closed_entered") or {}
    out = []
    for oid, o in (raw.get("opportunity") or {}).items():
        pipe, stage = stages.get(o.get("pipelineStageId"), (None, None))
        if stage not in CLOSED_WON:
            continue
        c = contacts.get(o.get("contactId")) or {}
        form = c.get("deal_form") or {}
        person = cname(c) or (o.get("contact") or {}).get("name") or o.get("name")
        rec = entered.get(oid) or {}
        when = R.parse_when(rec.get("entered_at") or o.get("lastStageChangeAt"))
        summary = form.get("deal_summary") or ""
        d = {"opp_id": oid, "contact_id": o.get("contactId"), "person": person,
             "business": (form.get("business_name") or "").strip() or c.get("companyName") or (o.get("contact") or {}).get("companyName") or "",
             "opportunity": o.get("name"), "pipeline": pipe, "stage": stage,
             "close_day": when.astimezone(SYDNEY_TZ).date() if when else None, "closed_sydney": _fmt_syd(when),
             "dated_by": "GHL: when the deal entered Closed Deal (recorded at first sighting)",
             "ghl_owner": _who(o.get("assignedTo"), users), "ghl_owner_id": o.get("assignedTo"),
             "emails": {R.norm_email(c.get("email")), R.norm_email((o.get("contact") or {}).get("email"))} - {None},
             "phones": {R.norm_phone(c.get("phone")), R.norm_phone((o.get("contact") or {}).get("phone"))} - {None},
             "form_present": bool(form), "deal_summary": summary,
             "package": form.get("package"), "start_date": form.get("start_date"),
             "form_amount_paid_inc": R.money(form.get("amount_paid_inc_gst")) if form.get("amount_paid_inc_gst") not in (None, "") else None,
             "is_test": R.is_test(person, o.get("name")), "missing": [], "proposals": []}
        # contract value ex-GST
        total, quote = R.stated_total_ex_gst(summary)
        dec = decisions.get(f"deal:{oid}:contract_ex")
        if dec:
            d["contract_ex"], d["contract_basis"] = R.money(dec["data"]["value"]), f"confirmed by {dec['actor']} ({dec['at'][:10]})"
        elif total is not None:
            d["contract_ex"], d["contract_basis"] = total, f"the form states it: “{quote}”"
        else:
            d["contract_ex"], d["contract_basis"] = None, quote or "the form does not state a total"
        # term
        term, tq = R.stated_term_months(summary)
        dec = decisions.get(f"deal:{oid}:term")
        if dec:
            d["term_months"], d["term_basis"] = int(dec["data"]["value"]), f"confirmed by {dec['actor']}"
        else:
            d["term_months"], d["term_basis"] = term, (f"the form states “{tq}”" if term else "not stated in the form")
        # closer / setter
        people = R.stated_closer_setter(summary)
        for role in ("closer", "setter"):
            dec = decisions.get(f"deal:{oid}:{role}")
            if dec:
                d[role], d[f"{role}_basis"] = dec["data"]["value"], f"confirmed by {dec['actor']}"
            elif people.get(role):
                d[role], d[f"{role}_basis"] = people[role], "the form states it"
            else:
                d[role], d[f"{role}_basis"] = None, "not stated in the form"
        dec = decisions.get(f"deal:{oid}:package")
        if dec:
            d["package"] = dec["data"]["value"]
        # the owner's deal-specific ruling (commission only; shown beside the form)
        d["owner_ruling"] = rulings.get(R.norm_name(person)) or rulings.get(R.norm_name(d["business"]))
        # what's missing → a human
        if not form:
            d["missing"].append("the whole Closed Deal Form")
        for f_, lab in (("package", "package"), ("term_months", "term"), ("contract_ex", "contract value ex-GST"),
                        ("closer", "closer"), ("setter", "setter")):
            if form and not d.get(f_):
                d["missing"].append(lab)
        if d["contract_ex"] is None and d["term_months"]:
            val, how = R.fee_times_term_proposal(summary, d["term_months"])
            if val is not None:
                d["proposals"].append({"key": f"deal:{oid}:contract_ex", "value": str(val), "label": how,
                                       "what": "contract value ex-GST"})
        if not d["closer"] and d["ghl_owner_id"]:
            d["proposals"].append({"key": f"deal:{oid}:closer", "value": d["ghl_owner"],
                                   "label": f"GHL lists {d['ghl_owner']} as the deal owner",
                                   "what": "closer", "needs_name": d["ghl_owner"].startswith("GHL user")})
        out.append(d)
    out.sort(key=lambda d: (d["close_day"] or dt.date.min))
    return out


# ── CASH ────────────────────────────────────────────────────────────────────

def payments(raw: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """(receipts, refunds, not_receipts). Each payment once, by its id."""
    out, refunds, not_receipts = [], [], []
    for cid, c in (raw.get("charge") or {}).items():
        if c.get("status") != "succeeded" or not c.get("paid"):
            continue
        inc = (Decimal(int(c.get("amount") or 0)) / 100).quantize(R.CENT)
        when = R.parse_when(c.get("created"))
        out.append({"id": cid, "source": "Stripe", "day": when.astimezone(SYDNEY_TZ).date(),
                    "when_sydney": _fmt_syd(when), "amount_inc": inc, "amount_ex": R.ex_gst(inc),
                    "gst_basis": "Stripe amount ÷ 1.1",
                    "payer": c.get("billing_name") or c.get("customer_name") or "(no name on the charge)",
                    "emails": {R.norm_email(c.get(k)) for k in ("billing_email", "receipt_email", "customer_email")} - {None},
                    "phones": {R.norm_phone(c.get(k)) for k in ("billing_phone", "customer_phone")} - {None},
                    "description": c.get("description") or "", "currency": c.get("currency")})
    for rid, r in (raw.get("refund") or {}).items():
        if r.get("status") not in ("succeeded", "pending"):
            continue
        inc = (Decimal(int(r.get("amount") or 0)) / 100).quantize(R.CENT)
        when = R.parse_when(r.get("created"))
        refunds.append({"id": rid, "source": "Stripe refund", "charge": r.get("charge"),
                        "day": when.astimezone(SYDNEY_TZ).date(), "when_sydney": _fmt_syd(when),
                        "amount_inc": -inc, "amount_ex": -R.ex_gst(inc), "status": r.get("status")})
    for tid, t in (raw.get("bank_txn") or {}).items():
        typ = t.get("Type")
        if t.get("Status") == "DELETED" or typ not in ("RECEIVE", "RECEIVE-TRANSFER", "RECEIVE-OVERPAYMENT", "RECEIVE-PREPAYMENT"):
            continue
        contact = (t.get("Contact") or {}).get("Name") or ""
        ref = " ".join(str(t.get(k) or "") for k in ("Reference",)) + " " + " ".join(
            str(li.get("Description") or "") for li in t.get("LineItems") or [])
        day = R.syd_date(t.get("DateString") or t.get("Date"))
        total, sub = R.money(t.get("Total")), R.money(t.get("SubTotal") if t.get("SubTotal") is not None else t.get("Total"))
        row = {"id": tid, "source": "Xero bank feed", "day": day, "when_sydney": str(day), "amount_inc": total,
               "amount_ex": sub, "gst_basis": "Xero's own ex-GST subtotal", "payer": contact or "(no contact)",
               "emails": set(), "phones": set(), "description": ref.strip()[:120],
               "bank_account": (t.get("BankAccount") or {}).get("Name"), "reconciled": t.get("IsReconciled")}
        if typ == "RECEIVE-TRANSFER":
            not_receipts.append({**row, "why": "a transfer between our own accounts"})
        elif "stripe" in (contact + " " + ref).lower():
            not_receipts.append({**row, "why": "a Stripe payout — the charges inside it are already counted from Stripe"})
        else:
            out.append(row)
    out.sort(key=lambda p: (p["day"], p["id"]))
    return out, refunds, not_receipts


def link_payments(pays: list[dict], deal_list: list[dict], raw: dict, decisions: dict) -> None:
    """Exact ids/emails/phones only. Anything weaker is a PROPOSAL."""
    contacts = raw.get("contact") or {}
    by_email, by_phone = {}, {}
    for cid, c in contacts.items():
        for e in [R.norm_email(c.get("email"))]:
            if e:
                by_email.setdefault(e, set()).add(cid)
        p = R.norm_phone(c.get("phone"))
        if p:
            by_phone.setdefault(p, set()).add(cid)
    deal_by_contact = {}
    for d in deal_list:
        deal_by_contact.setdefault(d["contact_id"], d)
    labels = {}
    for d in deal_list:
        for lab in (d["business"], d["person"]):
            if R.norm_name(lab):
                labels.setdefault(R.norm_name(lab), d)
    for p in pays:
        p["link"], p["proposal"] = None, None
        dec = decisions.get(f"link:{p['id']}")
        if dec:
            data = dec["data"]
            d = next((x for x in deal_list if x["opp_id"] == data.get("opp_id")), None)
            p["link"] = {"opp_id": data.get("opp_id"), "client": (d or {}).get("business") or data.get("client"),
                         "contact_id": (d or {}).get("contact_id"), "not_client": bool(data.get("not_client")),
                         "how": f"confirmed by {dec['actor']} ({dec['at'][:10]})"}
            continue
        cids = set()
        for e in p["emails"]:
            cids |= by_email.get(e, set())
        how = "same email as the GHL contact"
        if not cids:
            for ph in p["phones"]:
                cids |= by_phone.get(ph, set())
            how = "same phone as the GHL contact"
        email_link = None
        if len(cids) == 1:
            cid = next(iter(cids))
            d = deal_by_contact.get(cid)
            c = contacts.get(cid) or {}
            email_link = {"contact_id": cid, "opp_id": d["opp_id"] if d else None,
                          "client": (d or {}).get("business") or c.get("companyName") or cname(c), "how": how}
            if d:
                p["link"] = email_link
                continue
        alias = ALIASES.get(R.norm_name(p["payer"]))
        if alias:
            d = labels.get(R.norm_name(alias))
            if d:
                p["link"] = {"contact_id": d["contact_id"], "opp_id": d["opp_id"], "client": d["business"],
                             "how": f"Rydel's alias: {p['payer']} → {alias}"}
                continue
            p["link"] = email_link or {"contact_id": None, "opp_id": None, "client": alias, "how": ""}
            p["link"]["client"] = alias
            p["link"]["how"] = (f"Rydel's alias: {p['payer']} → {alias} (no GHL deal carries this exact name)"
                                + (f"; {email_link['how']}" if email_link else ""))
            first = R.norm_name(alias).split()[0]
            cand = next((x for x in deal_list if first in R.norm_name(x["business"]).split()), None)
            if cand:
                p["proposal"] = {"key": f"link:{p['id']}", "opp_id": cand["opp_id"],
                                 "label": f"Rydel's alias says {alias}; the GHL deal's business is “{cand['business']}” "
                                          f"({cand['person']}). Same client?"}
            continue
        if email_link:
            p["link"] = email_link
        nm = R.norm_name(p["payer"])
        d = labels.get(nm)
        if d:
            p["proposal"] = {"key": f"link:{p['id']}", "opp_id": d["opp_id"],
                             "label": f"payer name “{p['payer']}” matches the GHL deal for {d['person']} "
                                      f"({d['business']}) by name only — same client?"}


# ── COSTS (the comp rulebook) ───────────────────────────────────────────────

def _prorated_monthly(amount_for_day, w: dict) -> Decimal:
    total = D0
    d = w["start"]
    while d <= w["end"]:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        dim = (nxt - d.replace(day=1)).days
        total += Decimal(str(amount_for_day(d))) / dim
        d += dt.timedelta(days=1)
    return total.quantize(R.CENT)


def commission(d: dict, initial_cash_ex: Decimal) -> dict:
    import comp_rulebook as RB
    v = RB.version_for(d["close_day"])
    pkg = RB.normalise_package(d.get("package"))
    out = {"rulebook_version": f"v{v.get('version')} — {v.get('name')}", "package_key": pkg,
           "closer_amount": None, "setter_amount": None, "missing": [], "basis": []}
    rul = d.get("owner_ruling") or {}
    closer = (d.get("closer") or "").lower()
    if rul.get("closer_commission") is not None:
        out["closer_amount"] = R.money(rul["closer_commission"])
        out["basis"].append(f"closer: owner ruling for this deal (${rul['closer_commission']:,.2f})")
    elif not closer:
        out["missing"].append("closer not recorded")
    elif pkg is None:
        out["missing"].append(f"package “{d.get('package')}” has no rulebook rate")
    else:
        junior = closer in RB.JUNIOR_CLOSERS and v.get("junior_closer_flat")
        rate = (v.get("junior_closer_flat") or {}).get(pkg) if junior else (v.get("closer_flat") or {}).get(pkg)
        if rate is None:
            out["missing"].append(f"no rulebook closer rate for {pkg} in {out['rulebook_version']}")
        else:
            out["closer_amount"] = R.money(rate)
            out["basis"].append(f"closer {d['closer']}: ${rate:,.2f} "
                                f"({'junior rate — the company total' if junior else 'closer rate'}) for {pkg}")
    setter = (d.get("setter") or "").lower()
    if not setter:
        out["missing"].append("setter not recorded")
    else:
        s = v.get("setter") or {}
        amt = R.money(s.get("per_won_flat") or 0) + (R.money(initial_cash_ex) * Decimal(str(s.get("pct_of_initial_cash") or 0))).quantize(R.CENT)
        out["setter_amount"] = amt
        out["basis"].append(f"setter {d['setter']}: {float(s.get('pct_of_initial_cash') or 0):.0%} of "
                            f"${R.f2(initial_cash_ex):,.2f} initial-month cash ex-GST"
                            + (f" + ${s.get('per_won_flat'):,.0f} per close" if s.get("per_won_flat") else ""))
    out["total"] = sum((x for x in (out["closer_amount"], out["setter_amount"]) if x is not None), D0)
    return out


# ── the reconciliation helpers ──────────────────────────────────────────────

def tracker_closes(raw: dict, w: dict) -> list[dict] | None:
    sheet = (raw.get("sheet") or {}).get("ltc")
    if not sheet:
        return None
    try:
        import tracker_read
        from closes_view import _date, _money
    except Exception:  # noqa: BLE001
        return None
    rows = sheet.get("rows") or []
    for hi in range(min(10, len(rows))):
        cols = tracker_read._cols(rows[hi])
        if cols.get("business") is not None and cols.get("close") is not None:
            break
    else:
        return None
    out = []
    for i, r in enumerate(rows[hi + 1:], start=hi + 2):
        def cell(k):
            j = cols.get(k)
            return r[j] if j is not None and j < len(r) else ""
        day = _date(cell("close"))
        if day and R.in_window(day, w):
            out.append({"sheet_row": i, "business": cell("business"), "close_day": day, "offer": cell("offer"),
                        "contract": _money(cell("contract")), "cash": _money(cell("cash"))})
    return out


def _wilson(k: int, n: int):
    if n == 0:
        return None, None
    z = 1.96
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - m) / den, 3), round((c + m) / den, 3)


def _months_between(a: dt.date, b: dt.date) -> float:
    return (b - a).days / 30.4375


# ── THE BUILD ───────────────────────────────────────────────────────────────

def build(raw: dict, w: dict, now: dt.datetime, decisions: dict | None = None,
          settings: dict | None = None) -> dict:
    decisions = decisions or {}
    settings = settings or {}
    rulings = settings.get("rulings") or {}
    today = now.astimezone(SYDNEY_TZ).date()
    users = user_names(raw, decisions)

    # ── sources ──
    L = leads(raw, w)
    M = meta_days(raw, w, today)
    C = calls(raw, w, now, users, decisions)
    all_deals = deals(raw, users, decisions, rulings)
    tests = [d for d in all_deals if d["is_test"]]
    real = [d for d in all_deals if not d["is_test"]]
    pays, refunds, not_receipts = payments(raw)
    link_payments(pays, real, raw, decisions)
    refunded_by_charge: dict[str, Decimal] = {}
    for r in refunds:
        refunded_by_charge[r["charge"]] = refunded_by_charge.get(r["charge"], D0) + r["amount_ex"]

    closes_w = [d for d in real if R.in_window(d["close_day"], w)]
    close_ids_w = {d["opp_id"] for d in closes_w}

    # per-deal cash (all time) and the 30-day cash
    for d in real:
        mine = [p for p in pays if (p.get("link") or {}).get("opp_id") == d["opp_id"]]
        d["payments"] = [{"id": p["id"], "source": p["source"], "day": p["day"], "amount_ex": p["amount_ex"],
                          "refunded_ex": refunded_by_charge.get(p["id"], D0)} for p in mine]
        d["cash_to_date_ex"] = sum((p["amount_ex"] + refunded_by_charge.get(p["id"], D0) for p in mine), D0)
        if d["close_day"]:
            cutoff = d["close_day"] + dt.timedelta(days=30)
            d30 = [p for p in mine if p["day"] <= cutoff]
            d["cash_30d_ex"] = sum((p["amount_ex"] + refunded_by_charge.get(p["id"], D0) for p in d30), D0)
            d["cash_30d_so_far"] = today < cutoff
            d["cash_30d_rows"] = [p["id"] for p in d30]
        d["commission"] = commission(d, d.get("cash_30d_ex", D0))

    # ── ROW 1 · THE FUNNEL ──
    spend_known = not M["missing_days"]
    spend = sum((r["spend"] for r in M["rows"]), D0) if spend_known else None
    meta_leads = sum(r["meta_leads"] for r in M["rows"])
    booked = C["booked"]
    held = [r for r in booked if r["outcome"] == "held"]
    noshow = [r for r in booked if r["outcome"] == "no-show"]
    unmarked = [r for r in booked if r["outcome"] == "unmarked"]
    upcoming = [r for r in booked if r["outcome"] == "still to come"]
    happened = len(held) + len(noshow) + len(unmarked)
    new_cash_rows = []
    for p in pays:
        if (p.get("link") or {}).get("opp_id") in close_ids_w and R.in_window(p["day"], w):
            new_cash_rows.append({**p, "client": p["link"]["client"]})
    for r in refunds:
        src = next((p for p in pays if p["id"] == r["charge"]), None)
        if src and (src.get("link") or {}).get("opp_id") in close_ids_w and R.in_window(r["day"], w):
            new_cash_rows.append({**r, "client": src["link"]["client"], "payer": src["payer"]})
    new_cash = sum((r["amount_ex"] for r in new_cash_rows), D0)
    with_contract = [d for d in closes_w if d["contract_ex"] is not None]
    contract_total = sum((d["contract_ex"] for d in with_contract), D0)

    funnel = [
        metric("ad_spend", "Ad spend", spend, "money",
               "What Meta charged on the ad account, day by day, as Ads Manager shows it.",
               rows=M["rows"], sum_field="spend",
               note=("Includes today so far (not final)." if any(r["status"].startswith("today") for r in M["rows"]) else None)
                    if not M["missing_days"] else f"{len(M['missing_days'])} day(s) not yet read from Meta: {', '.join(M['missing_days'][:5])}"),
        metric("leads", "Leads", len(L["rows"]), "count",
               "People who came in from an ad, counted from GHL contacts. One person = one lead, even if they filled the form twice.",
               rows=L["rows"], parts={"meta_reported": meta_leads,
                                      "meta_note": "Meta's own lead count (includes website pixel leads) — shown beside, not used",
                                      "facebook_source_no_ad": len(L["facebook_no_ad"])}),
        metric("calls_booked", "Calls booked", len(booked), "count",
               "Sales calls on the consult calendars with a time in this window. Cancelled never counts; a rescheduled call counts once, at its final time.",
               rows=booked, parts={"still_to_come": len(upcoming), "cancelled": len(C["cancelled"]),
                                   "rescheduled_removed": len(C["rescheduled_removed"])}),
        metric("calls_held", "Calls held", len(held), "count",
               "Calls marked 'showed' in GHL. A call nobody marked is NOT assumed held — it is listed as unmarked.",
               rows=held, parts={"no_show": len(noshow), "unmarked": len(unmarked),
                                 "show_rate": _div(len(held), happened, 3),
                                 "show_rate_note": f"held ÷ booked calls whose time has passed ({happened}); "
                                                   f"{len(unmarked)} of those are unmarked"}),
        metric("closes", "Closes", len(closes_w), "count",
               "Deals that entered the ✅ Closed Deal stage in GHL in this window, by opportunity.",
               rows=closes_w, parts={"close_rate": _div(len(closes_w), len(held), 3),
                                     "close_rate_note": f"closes ÷ calls held ({len(held)})"
                                                        + (" — can't be worked out: no call is marked held" if not held else "")}),
        metric("new_client_cash", "Cash collected from new clients", new_cash, "money",
               "Money received in this window (ex-GST, refunds taken off) from clients whose deal closed in this window. Stripe + Xero bank feed, each payment once.",
               rows=new_cash_rows, sum_field="amount_ex"),
        metric("contract_value", "Contract value signed", contract_total, "money",
               "The contract value (ex-GST) the Closed Deal Form states for each close in this window.",
               rows=with_contract, sum_field="contract_ex",
               based_on=f"{len(with_contract)} of {len(closes_w)} closes state a contract value"),
    ]

    # ── ROW 2 · COST ──
    import comp_rulebook as RB
    comm_rows, comm_missing = [], []
    for d in closes_w:
        cm = d["commission"]
        comm_rows.append({"opp_id": d["opp_id"], "client": d["business"], "person": d["person"],
                          "rulebook": cm["rulebook_version"], "closer_amount": cm["closer_amount"],
                          "setter_amount": cm["setter_amount"], "amount": cm["total"],
                          "basis": "; ".join(cm["basis"]), "missing": ", ".join(cm["missing"])})
        if cm["missing"]:
            comm_missing.append(d)
    comm_total = sum((r["amount"] for r in comm_rows), D0)
    retainer = _prorated_monthly(lambda day: (RB.version_for(day).get("manager") or {}).get("monthly_retainer") or 0, w)
    try:
        from config import SALES_TOOLING_MONTHLY
    except Exception:  # noqa: BLE001
        SALES_TOOLING_MONTHLY = 0.0
    tools = _prorated_monthly(lambda day: SALES_TOOLING_MONTHLY, w)
    loaded_total = (spend + comm_total + retainer + tools) if spend is not None else None
    n_close = len(closes_w)
    cac_ads = (spend / n_close).quantize(R.CENT) if n_close and spend is not None else None
    cac_loaded = (loaded_total / n_close).quantize(R.CENT) if n_close and loaded_total is not None else None
    loaded_parts = [
        {"part": "Ad spend", "amount": spend if spend is not None else D0,
         "source": "Meta" if spend is not None else "Meta — NOT READ for every day, so CAC is withheld"},
        {"part": "Commissions on these closes", "amount": comm_total,
         "source": "the comp rulebook" + (f" — {len(comm_missing)} close(s) can't be costed yet" if comm_missing else "")},
        {"part": "Sales manager retainer", "amount": retainer, "source": "the comp rulebook ($/month, by day in the window)"},
        {"part": "Bonuses", "amount": D0, "source": "none triggered on record (the fast-win bonus needs Coby's lifetime close count, which GHL doesn't record)"},
        {"part": "Sales tools", "amount": tools, "source": f"configured ${SALES_TOOLING_MONTHLY:,.0f}/month — not yet read from Xero (Phase 2)"},
    ]
    cost = [
        metric("cpl", "Cost per lead", _div(spend, len(L["rows"])), "money", "Ad spend ÷ leads.",
               parts={"numerator": "ad_spend", "denominator": "leads"}),
        metric("cost_per_booked", "Cost per call booked", _div(spend, len(booked)), "money", "Ad spend ÷ calls booked.",
               parts={"numerator": "ad_spend", "denominator": "calls_booked"}),
        metric("cost_per_held", "Cost per call held", _div(spend, len(held)), "money", "Ad spend ÷ calls held.",
               parts={"numerator": "ad_spend", "denominator": "calls_held"},
               note=None if held else "Can't be worked out — no call in this window is marked held in GHL."),
        metric("cac_ads", "CAC (ads only)", cac_ads, "money", "Ad spend ÷ closes.",
               parts={"numerator": "ad_spend", "denominator": "closes"}),
        metric("cac_loaded", "CAC (fully loaded)", cac_loaded, "money",
               "Ads + commissions + sales manager retainer + bonuses + sales tools, ÷ closes.",
               rows=loaded_parts, sum_field="amount",
               note=("At least this much: " if comm_missing else "") +
                    (f"{len(comm_missing)} close(s) are missing the closer, setter or a rulebook rate, so their commission isn't in yet."
                     if comm_missing else "") or None,
               parts={"commission_rows": comm_rows, "total": R.f2(loaded_total) if loaded_total is not None else None}),
    ]

    # ── ROW 3 · RETURN, FACTS ──
    c30 = [d for d in closes_w if d.get("cash_30d_ex") is not None]
    cash30_total = sum((d["cash_30d_ex"] for d in c30), D0)
    cash30_avg = (cash30_total / len(c30)).quantize(R.CENT) if c30 else None
    so_far = sum(1 for d in c30 if d.get("cash_30d_so_far"))
    avg_contract = (contract_total / len(with_contract)).quantize(R.CENT) if with_contract else None
    ret_rows = [{"opp_id": d["opp_id"], "client": d["business"], "person": d["person"], "closed": str(d["close_day"]),
                 "cash_30d_ex": d["cash_30d_ex"], "so_far": d["cash_30d_so_far"], "payments": d["cash_30d_rows"]} for d in c30]
    returns = [
        metric("cash30_per_client", "30-day cash per new client", cash30_avg, "money",
               "Cash received (ex-GST) by day 30 after each close, averaged over the closes in this window. Deposits taken before the close count.",
               rows=ret_rows, sum_field="cash_30d_ex",
               note=f"{so_far} of {len(c30)} closes are under 30 days old — their figure is 'so far'." if so_far else None),
        metric("cash30_to_cac", "30-day cash : CAC", _div(cash30_avg, cac_loaded), "ratio",
               "30-day cash per new client ÷ fully loaded CAC. 1.0 or more = acquiring a client pays for itself within a month.",
               parts={"vs_ads_only": _div(cash30_avg, cac_ads), "numerator": "cash30_per_client", "denominator": "cac_loaded"},
               note=("CAC is a floor while commissions are missing, so this ratio is a ceiling." if comm_missing else None)),
        metric("contract_to_cac", "Contract value : CAC", _div(avg_contract, cac_loaded), "ratio",
               "Average contract value (ex-GST) ÷ fully loaded CAC.",
               parts={"vs_ads_only": _div(avg_contract, cac_ads)},
               based_on=f"{len(with_contract)} of {len(closes_w)} closes state a contract value"),
    ]

    # ── ROW 4 · RETURN, ESTIMATES ──
    est = estimates(real, closes_w, raw, today, cac_loaded, settings)

    # ── NEEDS A HUMAN ──
    nah = needs_a_human(w, today, C, closes_w, real, pays, users, raw, decisions)

    # ── RECONCILIATION ──
    rec = reconciliation(w, closes_w, real, pays, raw, M, C, refunds)

    return _plain({
        "window": w, "built_at": now.isoformat(),
        "funnel": funnel, "cost": cost, "returns": returns, "estimates": est,
        "needs_a_human": nah, "reconciliation": rec,
        "detail": {"leads_excluded": L["excluded"], "leads_facebook_no_ad": L["facebook_no_ad"], "lead_repeats_not_counted": L["repeats_not_counted"],
                   "calls_cancelled": C["cancelled"], "calls_rescheduled_removed": C["rescheduled_removed"],
                   "calls_invalid": C["invalid"], "calls_other_calendars": C["other_calendars"],
                   "calendar_kinds": C["calendar_kinds"], "calls_no_show": noshow, "calls_unmarked": unmarked,
                   "calls_upcoming": upcoming, "test_deals": tests, "not_receipts": not_receipts,
                   "refunds": [r for r in refunds if R.in_window(r["day"], w)],
                   "deals_in_window": closes_w, "users": users},
    })


def estimates(real: list[dict], closes_w: list[dict], raw: dict, today: dt.date, cac_loaded, settings) -> dict:
    # measured completion: deals with a stated/confirmed contract and term,
    # closed 2026 onwards — cash in so far vs a straight-line schedule
    measured = [d for d in real if d["contract_ex"] and d["term_months"] and d["close_day"]
                and d["close_day"] >= dt.date(2026, 1, 1) and d["close_day"] < today]
    exp_sum, act_sum, comp_rows = D0, D0, []
    for d in measured:
        frac = min(1.0, max(_months_between(d["close_day"], today) / d["term_months"], 1 / d["term_months"]))
        expected = (d["contract_ex"] * Decimal(str(frac))).quantize(R.CENT)
        actual = min(d["cash_to_date_ex"], d["contract_ex"])
        exp_sum += expected; act_sum += actual
        comp_rows.append({"client": d["business"], "closed": str(d["close_day"]), "contract_ex": d["contract_ex"],
                          "expected_by_now_ex": expected, "received_ex": d["cash_to_date_ex"],
                          "ratio": _div(actual, expected, 3)})
    completion = min(1.0, float(act_sum / exp_sum)) if exp_sum else None
    ended = [d for d in measured if d["close_day"] + dt.timedelta(days=int(d["term_months"] * 30.4375)) <= today]
    renewed = [d for d in ended if any(p["day"] > d["close_day"] + dt.timedelta(days=int(d["term_months"] * 30.4375))
                                        for p in d["payments"])]
    lo, hi = _wilson(len(renewed), len(ended))
    renewal = (len(renewed) / len(ended)) if ended else None
    margin = gross_margin(raw, today)
    per = []
    for d in closes_w:
        if not (d["contract_ex"] and d["term_months"]):
            continue
        received = d["cash_to_date_ex"]
        unpaid = max(D0, d["contract_ex"] - received)
        exp_unpaid = unpaid * Decimal(str(completion)) if completion is not None else None
        renew_val = D0
        retainer = (d.get("package") or "").lower().startswith("growth")
        if retainer and renewal:
            extra_terms = max(0, LTV_CAP_MONTHS // d["term_months"] - 1)
            renew_val = d["contract_ex"] * Decimal(str(sum(renewal ** k for k in range(1, extra_terms + 1))))
        if exp_unpaid is None:
            continue
        ltv = (received + exp_unpaid + renew_val).quantize(R.CENT)
        per.append({"client": d["business"], "received_ex": received, "unpaid_ex": unpaid,
                    "expected_from_unpaid": exp_unpaid.quantize(R.CENT), "renewal_value": renew_val.quantize(R.CENT),
                    "ltv": ltv, "ltgp": (ltv * Decimal(str(margin["value"]))).quantize(R.CENT) if margin["value"] else None,
                    "monthly_gp": ((d["contract_ex"] / d["term_months"]) * Decimal(str(margin["value"]))).quantize(R.CENT)
                                  if margin["value"] else None})
    n, m = len(per), len(closes_w)
    avg = lambda k: (sum((r[k] for r in per), D0) / n).quantize(R.CENT) if n and all(r[k] is not None for r in per) else None
    ltv, ltgp, mgp = avg("ltv"), avg("ltgp"), avg("monthly_gp")
    based = f"based on {n} of {m} deals (the rest don't state a contract value and term)"
    assumptions = [
        "Cash already received counts in full.",
        f"Unpaid instalments × measured payment completion: "
        + (f"{completion:.0%} (n = {len(measured)} deals, cash in so far vs a straight-line schedule)" if completion is not None
           else "not measurable yet — no deal with a stated contract and term to measure"),
        "Renewal (retainers only) × measured renewal rate: "
        + (f"{renewal:.0%} (n = {len(ended)}, 95% range {lo:.0%}–{hi:.0%})" if renewal is not None
           else "not measurable yet — no deal with a stated term has reached its end, so renewal is left out (LTV is a floor)"),
        f"Capped at {LTV_CAP_MONTHS} months.",
        f"Gross margin: {margin['label']}",
    ]
    return {
        "kind": "estimate", "based_on": based, "assumptions": assumptions,
        "completion_rows": comp_rows, "per_client": per,
        "metrics": [
            metric("ltv", "LTV per client", ltv, "money", "Estimated lifetime cash per client (ex-GST).",
                   rows=per, kind="estimate", based_on=based),
            metric("ltgp", "LTGP per client", ltgp, "money", "LTV × gross margin.", rows=per, kind="estimate", based_on=based),
            metric("ltv_cac", "LTV : CAC", _div(ltv, cac_loaded), "ratio", "LTV ÷ fully loaded CAC.", kind="estimate", based_on=based),
            metric("ltgp_cac", "LTGP : CAC", _div(ltgp, cac_loaded), "ratio", "LTGP ÷ fully loaded CAC.", kind="estimate", based_on=based),
            metric("payback", "Payback", _div(cac_loaded, mgp, 1), "months",
                   "Fully loaded CAC ÷ monthly gross profit per client (contract ÷ term × margin).", kind="estimate", based_on=based),
        ]}


def gross_margin(raw: dict, today: dt.date) -> dict:
    months = sorted((raw.get("pnl_month") or {}).items(), reverse=True)
    full = [(k, v) for k, v in months if k < f"{today:%Y-%m}" and v.get("revenue") and v.get("cogs") is not None][:3]
    if not full:
        return {"value": None, "label": "not available — Xero's P&L has no cost-of-sales figure for the last 3 months yet, so LTGP is withheld"}
    rev = sum(float(v["revenue"]) for _, v in full)
    gp = sum(float(v["revenue"]) - abs(float(v["cogs"])) for _, v in full)
    return {"value": round(gp / rev, 4) if rev else None,
            "label": f"{gp / rev:.1%} — Xero P&L gross profit ÷ income, {full[-1][0]} to {full[0][0]} (business-wide, not per package)"}


def needs_a_human(w, today, C, closes_w, real, pays, users, raw, decisions) -> list[dict]:
    out = []
    for r in C["booked"]:
        if r["outcome"] == "unmarked":
            out.append({"kind": "Unmarked consult", "who": r["assigned_to"],
                        "what": f"Mark {r['contact']}'s call ({r['when_sydney']}) as showed or no-show in GHL",
                        "age_days": r.get("age_days"), "ids": [r["appointment_id"]]})
    for r in C["other_calendars"]:
        if r["kind"] == "personal":
            out.append({"kind": "Booking on a personal calendar", "who": "Rydel",
                        "what": f"{r['contact']} on '{r['calendar']}' ({r['when_sydney']}) — is this calendar a sales calendar?",
                        "ids": [r["appointment_id"]],
                        "proposal": {"key": f"calendar:{r['calendar_id']}", "value": True,
                                     "label": f"Count '{r['calendar']}' as a sales-call calendar"}})
    for d in closes_w:
        who = d.get("closer") or (d["ghl_owner"] if not d["ghl_owner"].startswith("GHL user") else "whoever closed it")
        if d["missing"]:
            out.append({"kind": "Close missing deal details", "who": who,
                        "what": f"{d['person']} ({d['business'] or 'no business name'}): fill in "
                                + ", ".join(d["missing"]) + " on the Closed Deal Form", "ids": [d["opp_id"]],
                        "proposals": d["proposals"]})
        if not d["payments"]:
            out.append({"kind": "Closed Won deal with no payment", "who": "Piolo",
                        "what": f"{d['person']} ({d['business']}) closed {d['close_day']} — no Stripe or Xero payment linked yet",
                        "ids": [d["opp_id"]]})
        if d["commission"]["missing"]:
            out.append({"kind": "Commission can't be costed", "who": "Rydel",
                        "what": f"{d['person']}: " + "; ".join(d["commission"]["missing"]), "ids": [d["opp_id"]]})
    for p in pays:
        if not R.in_window(p["day"], w):
            continue
        lk = p.get("link")
        if not lk:
            out.append({"kind": "Payment not linked to a client", "who": "Piolo",
                        "what": f"{p['source']} ${R.f2(p['amount_inc']):,.2f} from {p['payer']} on {p['day']}"
                                + (f" — {p['description'][:60]}" if p["description"] else ""),
                        "ids": [p["id"]], "proposal": p.get("proposal")})
        elif not lk.get("opp_id") and not lk.get("not_client"):
            out.append({"kind": "Payment with no Closed Won deal", "who": "Piolo",
                        "what": f"${R.f2(p['amount_inc']):,.2f} from {p['payer']} ({lk['client']}) on {p['day']} — "
                                f"{lk['how']}; no deal in Closed Won for this client (an existing client, or a close not moved in GHL?)",
                        "ids": [p["id"]], "proposal": p.get("proposal")})
    named = set(users)
    seen_ids = {r.get("assigned_user_id") for r in C["booked"]} | {d["ghl_owner_id"] for d in closes_w}
    for uid in sorted(x for x in seen_ids if x and x not in named):
        out.append({"kind": "GHL user with no name", "who": "Rydel",
                    "what": f"Who is GHL user {uid}? (GHL won't tell the scoreboard)", "ids": [uid],
                    "proposal": {"key": f"user:{uid}", "value": None, "label": "Type the person's name", "free_text": True}})
    return out


def _match_known(known, closes):
    pairs, unmatched = [], []
    used = set()
    for person, biz in known:
        alias = ALIASES.get(R.norm_name(person))
        hit = None
        for d in closes:
            if d["opp_id"] in used:
                continue
            names = R.norm_name(d["person"]).split()
            bwords = set(R.norm_name(d["business"]).split())
            if (set(R.norm_name(person).split()) <= set(names) or R.norm_name(biz) == R.norm_name(d["business"])
                    or (R.norm_name(biz).split()[:1] and R.norm_name(biz).split()[0] in bwords and R.norm_name(biz).split()[0] not in ("the",))
                    or (alias and R.norm_name(alias) == R.norm_name(d["business"]))):
                hit = d
                break
        if hit:
            used.add(hit["opp_id"])
            pairs.append({"rydel_says": f"{person} ({biz})", "ghl": f"{hit['person']} ({hit['business']})", "opp_id": hit["opp_id"]})
        else:
            unmatched.append(f"{person} ({biz})")
    extra = [f"{d['person']} ({d['business']})" for d in closes if d["opp_id"] not in used]
    return pairs, unmatched, extra


def reconciliation(w, closes_w, real, pays, raw, M, C, refunds) -> dict:
    out = {}
    # closes vs Rydel's own list — for a whole calendar month (or this month so far)
    m = f"{w['start']:%Y-%m}"
    if w["start"].day == 1 and f"{w['end']:%Y-%m}" == m and m in KNOWN_CLOSES:
        pairs, missing, extra = _match_known(KNOWN_CLOSES[m], closes_w)
        out["closes_vs_rydel"] = {"matched": pairs, "rydel_lists_ghl_doesnt_show": missing,
                                  "ghl_shows_rydel_didnt_list": extra}
    tr = tracker_closes(raw, w)
    if tr is not None:
        tnames = {R.norm_name(t["business"]) for t in tr}
        out["closes_vs_tracker"] = {
            "ghl": len(closes_w), "tracker": len(tr), "tracker_rows": tr,
            "in_ghl_not_tracker": [f"{d['person']} ({d['business']})" for d in closes_w
                                   if not any(R.norm_name(d["business"]).split()[:1] == n.split()[:1] for n in tnames if n)],
            "in_tracker_not_ghl": [t["business"] for t in tr
                                   if not any(R.norm_name(t["business"]).split()[:1] == R.norm_name(d["business"]).split()[:1]
                                              for d in closes_w if R.norm_name(d["business"]))]}
    else:
        out["closes_vs_tracker"] = {"note": "the tracker has not been read yet"}
    # cash: Stripe vs the deal form's "amount paid"
    rows = []
    for d in closes_w:
        first = d["payments"][0] if d["payments"] else None
        rows.append({"client": d["business"], "person": d["person"],
                     "form_amount_paid_inc": d["form_amount_paid_inc"],
                     "payments_linked": len(d["payments"]),
                     "first_payment_inc": (first["amount_ex"] * R.GST).quantize(R.CENT) if first else None,
                     "first_payment_source": first["source"] if first else None,
                     "agree": (first is not None and d["form_amount_paid_inc"] is not None
                               and abs((first["amount_ex"] * R.GST) - d["form_amount_paid_inc"]) <= Decimal("0.05"))})
    out["cash_form_vs_payments"] = rows
    out["owner_rulings_vs_form"] = [
        {"client": d["business"], "form_contract_ex": d["contract_ex"],
         "ruling_contract_ex": (d.get("owner_ruling") or {}).get("contract_ex_gst"),
         "ruling_words": (d.get("owner_ruling") or {}).get("words")}
        for d in closes_w if d.get("owner_ruling")
        and (d["contract_ex"] is None or abs(float(d["contract_ex"]) - float(d["owner_ruling"].get("contract_ex_gst") or 0)) > 0.5)]
    # Meta: account vs ad-level
    out["meta_account_vs_ad_level"] = [{"day": r["day"], "account": r["spend"], "ad_level_sum": r["ad_level_sum"]}
                                       for r in M["rows"] if r["ad_level_matches"] is False]
    return out


# ── cached entry point (the page) ───────────────────────────────────────────

_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_S = 120


def invalidate() -> None:
    with _cache_lock:
        _cache.clear()


RAW_KINDS = (("ghl", "pipeline"), ("ghl", "calendar"), ("ghl", "event"), ("ghl", "opportunity"),
             ("ghl", "contact"), ("ghl", "closed_entered"), ("stripe", "charge"), ("stripe", "refund"),
             ("stripe", "payout"), ("meta", "account_day"), ("meta", "ad_day"), ("xero", "bank_txn"),
             ("xero", "invoice"), ("xero", "pnl_month"), ("tracker", "sheet"))


def load_raw() -> dict:
    from . import store
    return {k: store.read(s, k) for s, k in RAW_KINDS}


def owner_rulings() -> dict:
    """Rydel's deal rulings, as recorded (read as data; the old engine that
    wrote them is not called)."""
    try:
        import kv_store
        return {R.norm_name(v.get("person")): v for v in (kv_store.get("register:deal_terms") or {}).values()} | \
               {R.norm_name(v.get("client")): v for v in (kv_store.get("register:deal_terms") or {}).values()}
    except Exception:  # noqa: BLE001
        return {}


def scoreboard(window_key: str = "month", start: str | None = None, end: str | None = None) -> dict:
    from helpers import now_sydney
    from . import store
    now = now_sydney()
    w = R.window(window_key, now.date(), start, end)
    ck = (w["key"], str(w["start"]), str(w["end"]))
    with _cache_lock:
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < CACHE_S:
            return hit[1]
    raw = load_raw()
    out = build(raw, w, now, store.decisions(), {"rulings": owner_rulings()})
    out["freshness"] = freshness(store.sync_state(), now)
    with _cache_lock:
        _cache[ck] = (time.time(), out)
    return out


FRESH_LABELS = {"ghl": ("GHL (leads, calls, closes, deal forms)", "every 15 minutes"),
                "stripe": ("Stripe (card payments)", "every 15 minutes"),
                "meta_today": ("Meta — today", "hourly"),
                "meta_final": ("Meta — closed days", "nightly after 3am"),
                "xero": ("Xero (bank feed, invoices, P&L)", "daily — bank feeds can lag up to a day"),
                "tracker": ("The tracker (cross-check only)", "hourly")}


def freshness(state: dict, now: dt.datetime) -> list[dict]:
    from .sync import CADENCE_S
    out = []
    for job, (label, cadence) in FRESH_LABELS.items():
        s = state.get(job) or {}
        last_ok = R.parse_when(s.get("last_ok"))
        age = (now - last_ok).total_seconds() / 60 if last_ok else None
        stale = age is None or age > 2 * CADENCE_S[job] / 60 + 10
        out.append({"job": job, "label": label, "cadence": cadence,
                    "last_ok_sydney": _fmt_syd(last_ok), "age_minutes": round(age) if age is not None else None,
                    "error": s.get("error"), "rows": s.get("rows"),
                    "status": "never synced" if not last_ok else ("check failed" if s.get("error") else
                                                                   ("stale" if stale else "fresh"))})
    return out
