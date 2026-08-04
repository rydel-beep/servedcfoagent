"""
segments.py — the canonical S0–S5 email segment ladder (Rydel's decision,
2026-08-04, verbatim from the served-winback / served-newsletter skill doctrine).
Do NOT invent segment logic anywhere else: staging (email_pipeline.stage_draft,
Phase B) and sending (Phase C) MUST resolve recipients through this module.

THE LADDER (encoded, not paraphrased):
  S0 DO_NOT_EMAIL   unsubscribed, bounced, complaints, dispute/termination. Never sent.
  S1 ACTIVE_CLIENT  out of all nurture; optional monthly value digest only, hard
                    content gate (no discounts, pricing, new-client offers, urgency,
                    or case study of anyone paying less). Commercial-to-actives is
                    human-only, never automated.
  S2 IN_PIPELINE    at/past Consult Call Booked in the sales pipeline: frozen from
                    all marketing. Closed → S1; lost → 14-day cool-off → S4 WARM.
  S3 CHURNED        default silence; 90-day quarantine; optional win-back max
                    4 emails/year, value only, no pitch, no case studies; 2 opens or
                    1 click → flag a human (Miguel), never auto-pitch.
  S4 NURTURE_POOL   the ONLY send list, tiered:
                      HOT  engaged ≤30d or joined <30d — full packages
                      WARM 31–90d — value emails; convert-ask only on a click trigger
                      COLD 90d+  — monthly best-of + day-120 re-engagement then → S5
  S5 DORMANT        suppressed from sends; retained as a retargeting audience only.

GLOBAL RULES (hard, enforced here):
  • frequency governor: max 3 sends/contact/week; ONE convert-ask/week list-wide
  • global discount lock: Served never discounts its own services in email —
    bonuses/value only. Staging refuses discount language outright.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from helpers import now_sydney

logger = logging.getLogger(__name__)

SEGMENTS = ("S0", "S1", "S2", "S3", "S4", "S5")
S4_TIERS = ("HOT", "WARM", "COLD")
SENDABLE = {"S4"}                      # the ONLY segment staging may target
SALES_PIPELINE_ID = "JJQLCr1fl7OHyrpRwSJp"

# stages at/past Consult Call Booked freeze a contact (S2). Matched on normalized
# stage NAME so stage-id churn in GHL can't silently unfreeze anyone.
_PIPELINE_FREEZE_RE = re.compile(r"consult|call booked|proposal|negotiat|closed|won", re.I)

MAX_SENDS_PER_CONTACT_PER_WEEK = 3
MAX_CONVERT_ASKS_PER_WEEK_LISTWIDE = 1

# The discount lock. Deliberately aggressive: a false positive is a human review;
# a false negative is Served discounting itself in writing.
_DISCOUNT_RE = re.compile(
    r"\b\d{1,2}\s?%\s?off\b|\bdiscount\w*\b|\bpromo\s?code\b|\bcoupon\b|"
    r"\bsale\s+(?:ends|price)\b|\b\$\d+\s+off\b|\bprice\s+drop\b|\bslash(?:ed)?\s+price\b",
    re.I)


def discount_lock_check(text: str) -> dict:
    """ok=False if the copy contains discount language (global lock — bonuses only)."""
    hits = [m.group(0) for m in _DISCOUNT_RE.finditer(text or "")]
    return {"ok": not hits, "hits": hits[:8]}


def _days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now_sydney()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return (now - dt).total_seconds() / 86400.0


def classify_contact(contact: dict, *, active_client_emails: set,
                     churned_emails: set, frozen_contact_ids: set) -> tuple[str, str | None]:
    """(segment, s4_tier|None) for one GHL contact dict. Deterministic, doctrine-order:
    S0 beats everything, then S1, S2, S3; survivors tier into S4 by recency; 120d+
    past COLD's re-engagement window → S5. Approximation (named, not hidden):
    per-contact email open/click recency isn't exposed by the contacts API — HOT
    'engaged ≤30d' uses lastActivity/dateUpdated as the engagement proxy until the
    Phase-B read-back wires campaign stats."""
    email = (contact.get("email") or "").strip().lower()
    cid = contact.get("id") or ""
    tags = {str(t).strip().lower() for t in (contact.get("tags") or [])}
    # S0 — hard suppression
    if (contact.get("dnd") or contact.get("dndSettings", {}).get("Email", {}).get("status") == "active"
            or tags & {"unsubscribe", "unsubscribed", "bounced", "complaint", "spam-complaint",
                       "dispute", "termination", "do-not-email"}):
        return "S0", None
    if not email:
        return "S0", None                      # unreachable = never sent
    # S1 — active clients out of nurture
    if email in active_client_emails or "active-client" in tags:
        return "S1", None
    # S2 — pipeline freeze
    if cid in frozen_contact_ids:
        return "S2", None
    # S3 — churned silence
    if email in churned_emails or "churned" in tags:
        return "S3", None
    # S4 tiers / S5
    joined_days = _days_since(contact.get("dateAdded"))
    engaged_days = _days_since(contact.get("lastActivity") or contact.get("dateUpdated"))
    recency = min(x for x in (joined_days, engaged_days) if x is not None) \
        if any(x is not None for x in (joined_days, engaged_days)) else None
    if recency is None or recency > 120:
        return "S5", None
    if recency <= 30:
        return "S4", "HOT"
    if recency <= 90:
        return "S4", "WARM"
    return "S4", "COLD"


def frozen_contact_ids_from_opps(opportunities: list) -> set:
    """Contact ids frozen by S2: any opp in the sales pipeline whose stage name is
    at/past Consult Call Booked and status is open. (Lost → cool-off handled by the
    14-day recency the classifier already applies via lastActivity.)"""
    out = set()
    for o in opportunities or []:
        stage = (o.get("pipelineStageName") or o.get("stageName") or "")
        status = (o.get("status") or "").lower()
        if _PIPELINE_FREEZE_RE.search(stage) and status not in ("lost", "abandoned"):
            cid = o.get("contactId") or (o.get("contact") or {}).get("id")
            if cid:
                out.add(cid)
    return out


def sendable_check(segment: str, tier: str | None, *, is_convert_ask: bool,
                   click_triggered: bool = False) -> dict:
    """The staging-time gate: S4 only, tier rules applied. WARM gets a convert-ask
    only on a click trigger; COLD never gets a convert-ask (monthly best-of only)."""
    if segment not in SENDABLE:
        return {"ok": False, "reason": "%s is suppressed from sends (ladder)" % segment}
    if is_convert_ask:
        if tier == "WARM" and not click_triggered:
            return {"ok": False, "reason": "WARM gets a convert-ask only on a click trigger"}
        if tier == "COLD":
            return {"ok": False, "reason": "COLD never receives convert-asks (monthly best-of only)"}
    return {"ok": True, "reason": None}
