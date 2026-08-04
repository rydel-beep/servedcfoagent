"""
ghl_email.py — THE ONE GHL module for the email engine. Every GHL call for email
marketing lives here and nowhere else.

BOUNDARY (the amendment, DECISIONS #110):
  • Token: GHL_EMAIL_TOKEN — a dedicated integration Rydel created with email +
    location scopes. The sales key (GHL_SALES_API_KEY) is never used here and
    stays read-only elsewhere.
  • Location: PINNED to Served Marketing by construction. _request() hard-checks
    every call's locationId against SERVED_LOCATION_ID (verified by API 2026-08-04:
    name "Served Marketing", rydel@servedmarketing.com.au). A call addressed to any
    other location raises and logs — client sub-accounts are structurally
    unreachable from this module.
  • v1 WRITE SURFACE: create/update email DRAFTS only (Phase B). The send call
    (Phase C) requires a chain confirmation token minted by the owner-executed
    send flow — send_email() refuses without it. NO scheduler calls anything here.
"""
from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

SERVED_LOCATION_ID = "8nmZRSNCIslNgLwJSt3h"   # Served Marketing — pinned, verified by API
_BASE = "https://services.leadconnectorhq.com"
_VER = "2021-07-28"


class LocationViolation(RuntimeError):
    """A call tried to address a non-Served location. Never caught-and-continued."""


def _token() -> str:
    return os.environ.get("GHL_EMAIL_TOKEN", "")


def configured() -> bool:
    return bool(_token())


def _request(method: str, path: str, *, params: dict | None = None,
             json_body: dict | None = None, location_id: str | None = None):
    """Single choke point. Hard-checks the pinned location on EVERY call; retries 429."""
    loc = location_id or SERVED_LOCATION_ID
    if loc != SERVED_LOCATION_ID:
        logger.error("ghl_email: REFUSED call to non-Served location %r (%s %s)", loc, method, path)
        raise LocationViolation("ghl_email only ever addresses the Served sub-account")
    for blob in (params, json_body):
        for k, v in (blob or {}).items():
            if "location" in k.lower() and isinstance(v, str) and v and v != SERVED_LOCATION_ID:
                logger.error("ghl_email: REFUSED %s=%r in %s %s", k, v, method, path)
                raise LocationViolation("ghl_email only ever addresses the Served sub-account")
    if not configured():
        return None
    hdr = {"Authorization": "Bearer " + _token(), "Version": _VER, "Content-Type": "application/json"}
    for attempt in range(4):
        try:
            r = requests.request(method, _BASE + path, headers=hdr, params=params,
                                 json=json_body, timeout=20)
        except requests.RequestException as e:
            logger.warning("ghl_email %s %s failed: %s", method, path, e)
            time.sleep(1.5)
            continue
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "3")) + 1)
            continue
        if r.status_code >= 400:
            logger.warning("ghl_email %s %s -> %s %s", method, path, r.status_code, r.text[:180])
            return {"_error": r.status_code, "_text": r.text[:300]}
        return r.json() if r.text else {}
    return None


# ── reads (Phase A) ───────────────────────────────────────────────────────────
def tags() -> list | None:
    d = _request("GET", "/locations/%s/tags" % SERVED_LOCATION_ID)
    return (d or {}).get("tags") if isinstance(d, dict) and "_error" not in (d or {}) else None


def contacts_count_by_tag(tag: str) -> int | None:
    d = _request("GET", "/contacts/", params={"locationId": SERVED_LOCATION_ID,
                                              "query": "", "limit": 1, "tag": tag})
    if isinstance(d, dict) and "_error" not in d:
        return (d.get("meta") or {}).get("total")
    return None


def pd_cohort(pipeline_id: str = "JJQLCr1fl7OHyrpRwSJp",
              stage_id: str = "e6113e09-5f65-438e-bd46-5fc94464392a") -> list | None:
    """The live Pitched & Drifted opportunities (empty today; winback idles until used)."""
    d = _request("GET", "/opportunities/search",
                 params={"location_id": SERVED_LOCATION_ID, "pipeline_id": pipeline_id,
                         "pipeline_stage_id": stage_id, "limit": 100})
    if isinstance(d, dict) and "_error" not in d:
        return d.get("opportunities") or []
    return None


# ── writes (Phase B — draft staging ONLY; nothing here sends) ─────────────────
def create_email_draft(subject: str, html: str, name: str) -> dict | None:
    """Create an INERT email draft in the Served sub-account (Phase B wires this to
    APPROVED drafts; read-back verification happens in email_pipeline.stage_draft)."""
    return _request("POST", "/emails/builder",
                    json_body={"locationId": SERVED_LOCATION_ID, "type": "html",
                               "title": name, "subject": subject, "html": html})


def find_email_draft(builder_id: str = "", name: str = "") -> dict | None:
    """Read-back via the LIST endpoint (GHL offers no per-id GET for builders; the
    list carries metadata only — id, name, previewUrl — so content-level verification
    is NOT available from the API; callers must surface that honestly)."""
    d = _request("GET", "/emails/builder",
                 params={"locationId": SERVED_LOCATION_ID, "limit": 100})
    if not isinstance(d, dict) or d.get("_error"):
        return None
    for b in d.get("builders", []):
        bid = b.get("id") or b.get("_id")
        if (builder_id and bid == builder_id) or (name and b.get("name") == name):
            return b
    return {}   # reachable but not found (vs None = list call failed)


# ── the send call (Phase C ONLY — refuses without the owner chain token) ──────
def send_email(schedule_payload: dict, chain_token: str | None = None) -> dict:
    """The ONLY function that can ever trigger a send — and it refuses unless the
    owner-executed send chain (Phase C) minted a valid chain confirmation token.
    v1: Phase C is not built; every call refuses. No scheduler imports this module."""
    from email_pipeline import verify_chain_token   # late import; Phase C owns minting
    if not chain_token or not verify_chain_token(chain_token):
        logger.error("ghl_email.send_email REFUSED: no valid owner chain token")
        return {"_refused": "owner send chain token required — autonomous sends are impossible"}
    raise NotImplementedError("Phase C (owner-executed send) is not built yet")
