"""fetch.py — READ-ONLY pulls from the sources of truth. HTTP GET only.

Every outbound call goes through _get(). There is no POST/PUT/PATCH/DELETE in
this package (a test greps for it). The one exception is outside this file:
the existing Xero connection refreshes its own access token
(xero_pull._refresh_access_token) — that is how the existing read-only
connection already works; nothing here creates a new credential.

GHL CONTACTS ARE CUT DOWN BEFORE THEY ARE KEPT. Closed clients' contact
records also hold their onboarding answers, which include website, social and
booking-system passwords (found 7 Oct 2026). Only CONTACT_KEYS and the
Closed Deal Form fields in DEAL_FORM_FIELDS survive; every other custom field
is dropped here, before storage, and never printed.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

import requests

from config import (GHL_API_KEY, GHL_BASE, GHL_LOCATION_ID, META_ACCESS_TOKEN,
                    META_API_VERSION, STRIPE_SECRET_KEY)

logger = logging.getLogger(__name__)

META_ACCOUNT = "act_1071149830652711"     # Rydel's ruling: the one ad account
TIMEOUT = 45

# The Closed Deal Form, as GHL stores it on the contact (field ids — the
# token cannot read field names, so the meaning was read off the values).
DEAL_FORM_FIELDS = {
    "mRyGnKerOZtM9qAF8WGM": "package",
    "uH8enZO5VBorbbYboyD7": "deal_summary",
    "7Yc1pJGyR1S6Ya1j3iCF": "amount_paid_inc_gst",
    "cMayws8oAro2NobiGDWE": "start_date",
    "dJ4mFvKk23qPs9F9j6Dl": "business_name",
}
CONTACT_KEYS = ("id", "firstName", "lastName", "firstNameRaw", "lastNameRaw", "contactName", "companyName", "email",
                "phone", "additionalEmails", "additionalPhones", "source", "dateAdded",
                "dateUpdated", "tags", "timezone", "type", "attributions",
                "attributionSource", "lastAttributionSource")
OPP_KEYS = ("id", "name", "pipelineId", "pipelineStageId", "status", "source",
            "assignedTo", "monetaryValue", "contactId", "createdAt", "updatedAt",
            "lastStageChangeAt", "lastStatusChangeAt", "attributions")


def _ms(d: dt.datetime) -> int:
    return int(d.timestamp() * 1000)


def _get(url: str, params: dict | None = None, headers: dict | None = None,
         auth=None) -> tuple[int, dict]:
    """The ONLY outbound call in the scoreboard. GET, retried on 429/5xx."""
    last = (0, {})
    for i in range(4):
        try:
            r = requests.get(url, params=params or {}, headers=headers or {}, auth=auth, timeout=TIMEOUT)
        except requests.RequestException as e:
            last = (0, {"_error": str(e)[:200]})
            time.sleep(1 + i * 2)
            continue
        transient = False
        if r.status_code == 400:
            try:
                transient = bool((r.json().get("error") or {}).get("is_transient"))
            except ValueError:
                transient = False
        if r.status_code == 429 or r.status_code >= 500 or transient:
            last = (r.status_code, {})
            time.sleep(2 + i * 3)
            continue
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"_text": r.text[:200]}
    return last


class SourceError(Exception):
    pass


# ── GHL ─────────────────────────────────────────────────────────────────────

def _ghl(path: str, params: dict | None = None) -> dict:
    s, d = _get(GHL_BASE + path, params,
                {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28",
                 "Accept": "application/json"})
    if s != 200:
        raise SourceError(f"GHL {path} → HTTP {s}")
    return d


def safe_contact(c: dict) -> dict:
    """Keep only the allowed keys and the Closed Deal Form fields."""
    out = {k: c.get(k) for k in CONTACT_KEYS if c.get(k) is not None}
    form = {}
    for cf in c.get("customFields") or []:
        name = DEAL_FORM_FIELDS.get(cf.get("id"))
        if name:
            form[name] = cf.get("value")
    out["deal_form"] = form
    return out


def ghl_pipelines() -> list[dict]:
    return _ghl("/opportunities/pipelines", {"locationId": GHL_LOCATION_ID}).get("pipelines") or []


def ghl_calendars() -> list[dict]:
    return _ghl("/calendars/", {"locationId": GHL_LOCATION_ID}).get("calendars") or []


def ghl_events(calendar_id: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    d = _ghl("/calendars/events", {"locationId": GHL_LOCATION_ID, "calendarId": calendar_id,
                                   "startTime": _ms(start), "endTime": _ms(end)})
    return d.get("events") or []


def ghl_opportunities() -> list[dict]:
    out, page = [], 1
    while page <= 200:
        d = _ghl("/opportunities/search", {"location_id": GHL_LOCATION_ID, "limit": 100, "page": page})
        batch = d.get("opportunities") or []
        for o in batch:
            keep = {k: o.get(k) for k in OPP_KEYS}
            c = o.get("contact") or {}
            keep["contact"] = {k: c.get(k) for k in ("id", "name", "companyName", "email", "phone")}
            out.append(keep)
        if len(batch) < 100:
            break
        page += 1
    return out


def ghl_contacts() -> list[dict]:
    out, params = [], {"locationId": GHL_LOCATION_ID, "limit": 100}
    for _ in range(400):
        d = _ghl("/contacts/", params)
        batch = d.get("contacts") or []
        out.extend(safe_contact(c) for c in batch)
        meta = d.get("meta") or {}
        if len(batch) < 100 or not meta.get("startAfterId"):
            break
        params = {"locationId": GHL_LOCATION_ID, "limit": 100,
                  "startAfter": meta.get("startAfter"), "startAfterId": meta.get("startAfterId")}
    return out


def ghl_contact(contact_id: str) -> dict:
    return safe_contact(_ghl(f"/contacts/{contact_id}").get("contact") or {})


# ── Stripe ──────────────────────────────────────────────────────────────────

def _stripe_list(obj: str, created_gte: int, extra: dict | None = None) -> list[dict]:
    if not STRIPE_SECRET_KEY:
        raise SourceError("no Stripe key on the server")
    out, after = [], None
    for _ in range(500):
        params = {"limit": 100, "created[gte]": created_gte, **(extra or {})}
        if after:
            params["starting_after"] = after
        s, d = _get(f"https://api.stripe.com/v1/{obj}", params, auth=(STRIPE_SECRET_KEY, ""))
        if s != 200:
            raise SourceError(f"Stripe {obj} → HTTP {s}: {(d.get('error') or {}).get('message', '')[:120]}")
        data = d.get("data") or []
        out.extend(data)
        if not d.get("has_more") or not data:
            break
        after = data[-1]["id"]
    return out


def stripe_charges(since: dt.datetime) -> list[dict]:
    rows = _stripe_list("charges", int(since.timestamp()), {"expand[]": "data.customer"})
    keep = ("id", "amount", "amount_captured", "amount_refunded", "currency", "created", "status",
            "paid", "refunded", "description", "receipt_email", "payment_intent", "invoice",
            "statement_descriptor", "calculated_statement_descriptor", "metadata")
    out = []
    for c in rows:
        k = {x: c.get(x) for x in keep}
        bd = c.get("billing_details") or {}
        k["billing_name"], k["billing_email"], k["billing_phone"] = bd.get("name"), bd.get("email"), bd.get("phone")
        cu = c.get("customer")
        if isinstance(cu, dict):
            k["customer_id"], k["customer_email"], k["customer_name"], k["customer_phone"] = (
                cu.get("id"), cu.get("email"), cu.get("name"), cu.get("phone"))
        else:
            k["customer_id"] = cu
        out.append(k)
    return out


def stripe_refunds(since: dt.datetime) -> list[dict]:
    return [{x: r.get(x) for x in ("id", "amount", "charge", "created", "status", "reason", "currency")}
            for r in _stripe_list("refunds", int(since.timestamp()))]


def stripe_payouts(since: dt.datetime) -> list[dict]:
    return [{x: p.get(x) for x in ("id", "amount", "arrival_date", "created", "status", "currency",
                                   "description", "statement_descriptor")}
            for p in _stripe_list("payouts", int(since.timestamp()))]


# ── Meta ────────────────────────────────────────────────────────────────────

def meta_insights(level: str, since: str, until: str) -> list[dict]:
    """Daily insights, exactly as the API returns them (spend kept as the
    API's own string so a closed day reconciles to the cent). Ad-level
    detail is read a week at a time — Meta refuses long ad-level ranges."""
    if level == "ad":
        out, a, z = [], dt.date.fromisoformat(since), dt.date.fromisoformat(until)
        while a <= z:
            b = min(z, a + dt.timedelta(days=6))
            out.extend(_meta_insights(level, str(a), str(b)))
            a = b + dt.timedelta(days=1)
        return out
    return _meta_insights(level, since, until)


def _meta_insights(level: str, since: str, until: str) -> list[dict]:
    if not META_ACCESS_TOKEN:
        raise SourceError("no Meta token on the server")
    fields = "spend,impressions,clicks,actions,date_start,date_stop"
    if level == "ad":
        fields += ",campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name"
    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_ACCOUNT}/insights"
    params = {"level": level, "time_increment": 1, "limit": 500, "fields": fields,
              "time_range": json.dumps({"since": since, "until": until}),
              "access_token": META_ACCESS_TOKEN}
    out = []
    for _ in range(200):
        s, d = _get(url, params)
        if s != 200:
            raise SourceError(f"Meta insights → HTTP {s}: {str((d.get('error') or {}).get('message', ''))[:120]}")
        out.extend(d.get("data") or [])
        nxt = (d.get("paging") or {}).get("next")
        if not nxt:
            break
        url, params = nxt, None
    return out


# ── Xero (the existing connection) ──────────────────────────────────────────

def _xero_session() -> tuple[str, str]:
    import xero_pull
    stored = xero_pull._load_tokens()
    if not stored or not stored.get("refresh_token") or not stored.get("tenant_id"):
        raise SourceError("no Xero connection on the server — connect Xero first")
    tok = xero_pull._refresh_access_token(stored)
    if not tok or not tok.get("access_token"):
        raise SourceError("the Xero connection could not refresh")
    return tok["access_token"], tok["tenant_id"]


def _xero_list(path: str, where: str, key: str, session) -> list[dict]:
    access, tenant = session
    out = []
    for page in range(1, 200):
        s, d = _get(f"https://api.xero.com/api.xro/2.0/{path}", {"where": where, "page": page},
                    {"Authorization": f"Bearer {access}", "xero-tenant-id": tenant,
                     "Accept": "application/json"})
        if s in (401, 403):
            raise SourceError(f"Xero {path} → HTTP {s}: the Xero connection does not have permission to "
                              "read this yet (reconnect Xero with bank-transaction and invoice read access)")
        if s != 200:
            raise SourceError(f"Xero {path} → HTTP {s}")
        rows = d.get(key) or []
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def xero_bank_and_invoices(since: dt.date) -> dict:
    sess = _xero_session()
    w = f"Date>=DateTime({since.year},{since.month},{since.day})"
    bank = _xero_list("BankTransactions", w, "BankTransactions", sess)
    inv = _xero_list("Invoices", w + ' AND Type=="ACCREC"', "Invoices", sess)
    return {"bank": bank, "invoices": inv}


def xero_pnl_month(start: str, end: str) -> dict:
    import xero_pull
    return xero_pull.pull_pl_range(start, end)


# ── the tracker (cross-check only) ──────────────────────────────────────────

def tracker_rows() -> list[list[str]]:
    import sheet_mirror
    m = sheet_mirror.MIRRORED_TABS.get("ltc_tracker") or {}
    rows = sheet_mirror._live_fetch(m.get("book"), m.get("tab") or "Lead-to-Cash Tracker")
    if not rows:
        raise SourceError("the tracker returned no rows")
    return rows
