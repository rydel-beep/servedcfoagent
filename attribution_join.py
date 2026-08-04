"""
attribution_join.py
-------------------
GHL contact ATTRIBUTION capture + the contact → Meta creative JOIN (Phase 1 of the
ad attribution engine).

What Phase 0 proved and this module encodes:
  - The GHL contacts LIST endpoint carries `attributions` in the payload — the full CRM
    (3,527 contacts) syncs in ~36 paginated GETs, no per-contact fetches, no new tokens.
  - GHL's FB lead-form integration stamps utmAdId (the REAL ad id) + utmCampaignId →
    resolution is id-first: utmAdId → id-style utm_content → unique name → learned alias.
    Names are the fallback, never the preference (114/338 names are duplicated).
  - Tiers (Rydel's Phase-0 confirmation): 'ad' (ad-level identity) / 'ig_dm' (Instagram
    DM channel — no click UTMs exist for these) / 'other' (source-only) / 'none'.
    Whether an ig_dm contact is a LEAD (entered the tracker) or a non-lead inquiry is
    decided by the ENGINE against tracker rows — not here.

Storage: attr_contacts (auth-gated mirror table, same PII discipline as ghl_contacts —
names/emails live only here, never in memory_facts, never logged plaintext). This is a
raw-capture table, NOT a parallel matcher: identity matching stays with the existing
smart/payment matchers; creative resolution reuses meta_entities.

FIRST-TOUCH is the default for creative credit; last-touch is stored and resolved
alongside, labelled, never blended (DECISIONS #111).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

import requests

import db
from config import GHL_BASE, GHL_API_KEY, GHL_LOCATION_ID, HTTP_TIMEOUT
from helpers import now_sydney

logger = logging.getLogger(__name__)

_THROTTLE = 0.12                 # same discipline as ghl_mirror (~8 req/s)
_MAX_LIST_PAGES = 120            # 12k contacts — cap flagged, never silent
_SYNC_TTL_S = 6 * 3600           # contact attribution changes slowly; 6h is plenty
_sync_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS attr_contacts (
    id            TEXT PRIMARY KEY,
    email         TEXT,
    name          TEXT,
    date_added    TIMESTAMPTZ,
    source        TEXT,
    tags          JSONB,
    medium        TEXT,
    tier          TEXT,
    first_touch   JSONB,
    last_touch    JSONB,
    ft_ad_ref     TEXT,
    ft_ref_kind   TEXT,
    lt_ad_ref     TEXT,
    lt_ref_kind   TEXT,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted       BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_attr_contacts_email ON attr_contacts (lower(email));
CREATE INDEX IF NOT EXISTS idx_attr_contacts_tier ON attr_contacts (tier);
"""

_ID_RE = re.compile(r"^\d{10,20}$")


def migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("attr_contacts migrate failed: %s", e)
        return False


# ── Pure classification (unit-testable, no I/O) ──────────────────────────────

def extract_touches(contact: dict) -> tuple[dict, dict]:
    """(first_touch, last_touch) attribution dicts from a GHL contact payload.
    Detail payloads carry attributionSource/lastAttributionSource; list payloads carry
    the `attributions` array (isFirst/isLast flags)."""
    first = contact.get("attributionSource") or {}
    last = contact.get("lastAttributionSource") or {}
    attrs = [a for a in (contact.get("attributions") or []) if isinstance(a, dict)]
    if not first:
        first = next((a for a in attrs if str(a.get("isFirst")).lower() == "true"),
                     attrs[0] if attrs else {})
    if not last:
        last = next((a for a in attrs if str(a.get("isLast")).lower() == "true"),
                    attrs[-1] if len(attrs) > 1 else {})
    return first or {}, last or {}


def ad_ref_from_touch(touch: dict) -> tuple[str | None, str | None]:
    """The strongest ad reference in one touch: (ref, kind).
    kind ∈ 'id' (utmAdId or id-style utm_content — exact) | 'name' (utm_content text).
    Preference order is THE Phase-0 finding: ids first, names only as fallback."""
    if not touch:
        return None, None
    ad_id = str(touch.get("utmAdId") or touch.get("adId") or "").strip()
    if _ID_RE.match(ad_id):
        return ad_id, "id"
    uc = str(touch.get("utmContent") or "").strip()
    if _ID_RE.match(uc):
        return uc, "id"
    if uc:
        return uc, "name"
    return None, None


def classify_tier(first: dict, last: dict, ft_ref: str | None, lt_ref: str | None) -> str:
    """'ad' | 'ig_dm' | 'other' | 'none'. IG-DM is the channel-level tier Rydel confirmed:
    Instagram-medium contacts with no ad identity (click UTMs never existed for DMs)."""
    if ft_ref or lt_ref:
        return "ad"
    medium = str((first.get("medium") or last.get("medium") or "")).lower()
    if medium == "instagram":
        return "ig_dm"
    signal = any((first.get(k) or last.get(k)) for k in
                 ("medium", "sessionSource", "utmSessionSource", "referrer", "url",
                  "fbclid", "fbc", "fbp", "gclid"))
    return "other" if signal else "none"


def classify_contact(contact: dict) -> dict:
    """Full pure classification of one GHL contact payload → the attr_contacts row shape."""
    first, last = extract_touches(contact)
    ft_ref, ft_kind = ad_ref_from_touch(first)
    lt_ref, lt_kind = ad_ref_from_touch(last)
    name = (contact.get("contactName")
            or f"{contact.get('firstName') or ''} {contact.get('lastName') or ''}").strip()
    return {
        "id": contact.get("id"),
        "email": (contact.get("email") or "").strip().lower() or None,
        "name": name or None,
        "date_added": contact.get("dateAdded") or contact.get("createdAt"),
        "source": contact.get("source"),
        "tags": contact.get("tags") or [],
        "medium": (first.get("medium") or last.get("medium") or None),
        "tier": classify_tier(first, last, ft_ref, lt_ref),
        "first_touch": first,
        "last_touch": last,
        "ft_ad_ref": ft_ref, "ft_ref_kind": ft_kind,
        "lt_ad_ref": lt_ref, "lt_ref_kind": lt_kind,
    }


# ── Creative resolution (id-first; reuses meta_entities; never guesses) ──────

def resolve_ref(ref: str | None, kind: str | None, entity_store: dict | None = None,
                allow_recovery: bool = False) -> dict:
    """Resolve one ad reference to a creative identity. Returns:
      {basis: 'id'|'name_unique'|'name_ambiguous'|'alias'|'unresolved',
       creative_key, ad_ids: [...], ad_name, adset_id, campaign_id, campaign_name}
    creative_key = the per-creative grouping key: normalized ad NAME when known (creative
    identity — DECISIONS #111), else 'id:<ad_id>' when a name can't be learned."""
    import meta_entities
    if not ref:
        return {"basis": "unresolved", "creative_key": None, "ad_ids": []}
    if kind == "id":
        hit = meta_entities.lookup_ad_id(ref, store=entity_store)
        if hit:
            key = hit.get("name_norm") or f"id:{ref}"
            return {"basis": "id", "creative_key": key, "ad_ids": [ref],
                    "ad_name": hit.get("name"), "adset_id": hit.get("adset_id"),
                    "campaign_id": hit.get("campaign_id"),
                    "campaign_name": hit.get("campaign_name")}
        # an exact id we can't dereference is still an exact identity — keep it
        return {"basis": "id", "creative_key": f"id:{ref}", "ad_ids": [ref],
                "ad_name": None, "adset_id": None, "campaign_id": None,
                "campaign_name": None}
    cands = meta_entities.candidates_by_name(ref, store=entity_store)
    if len(cands) == 1:
        c = cands[0]
        return {"basis": "name_unique", "creative_key": c.get("name_norm"),
                "ad_ids": [c["ad_id"]], "ad_name": c.get("name"),
                "adset_id": c.get("adset_id"), "campaign_id": c.get("campaign_id"),
                "campaign_name": c.get("campaign_name")}
    if len(cands) > 1:
        # SAME creative re-launched across campaigns: creative-level identity is the name;
        # adset/campaign stay None (ambiguous — never guessed).
        return {"basis": "name_ambiguous", "creative_key": meta_entities.norm_name(ref),
                "ad_ids": sorted(c["ad_id"] for c in cands),
                "ad_name": cands[0].get("name"), "adset_id": None,
                "campaign_id": None, "campaign_name": "ambiguous"}
    if allow_recovery:
        rec = meta_entities.recover_by_name(ref)
        if rec:
            return {"basis": "alias", "creative_key": rec.get("name_norm") or meta_entities.norm_name(ref),
                    "ad_ids": [rec["ad_id"]], "ad_name": rec.get("name") or ref,
                    "adset_id": rec.get("adset_id"), "campaign_id": rec.get("campaign_id"),
                    "campaign_name": rec.get("campaign_name")}
    return {"basis": "unresolved", "creative_key": None, "ad_ids": [],
            "ad_name": ref}


# ── The GHL sweep (list endpoint; attributions ride the payload) ─────────────

def _ghl_headers() -> dict:
    return {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28"}


def fetch_all_contacts() -> tuple[list[dict], bool, str | None]:
    """Paginate GET /contacts/ for the location. (contacts, complete, reason)."""
    out, seen = [], set()
    params = {"locationId": GHL_LOCATION_ID, "limit": 100}
    page = 0
    while page < _MAX_LIST_PAGES:
        page += 1
        try:
            resp = requests.get(f"{GHL_BASE}/contacts/", headers=_ghl_headers(),
                                params=dict(params), timeout=(5, HTTP_TIMEOUT))
        except requests.RequestException as e:
            return out, False, f"page {page}: {e}"
        if resp.status_code != 200:
            return out, False, f"page {page}: HTTP {resp.status_code}"
        data = resp.json()
        batch = data.get("contacts", [])
        for c in batch:
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(c)
        meta = data.get("meta", {})
        if not batch or not meta.get("startAfterId"):
            return out, True, None
        params["startAfterId"] = meta["startAfterId"]
        if meta.get("startAfter"):
            params["startAfter"] = meta["startAfter"]
        time.sleep(_THROTTLE)
    return out, False, f"hit page cap {_MAX_LIST_PAGES}"


def sync_contacts(force: bool = False) -> dict:
    """Sweep the CRM into attr_contacts (idempotent upserts; TTL-guarded).
    Returns {synced, total, complete, skipped, reason}."""
    import kv_store
    state = kv_store.get("attr:sync_state") or {}
    if not force and state.get("at") and time.time() - state["at"] < _SYNC_TTL_S:
        return {"skipped": True, **state}
    if not (GHL_API_KEY and GHL_LOCATION_ID):
        return {"skipped": True, "reason": "GHL not configured"}
    if not migrate():
        return {"skipped": True, "reason": "DB unavailable"}
    with _sync_lock:
        contacts, complete, reason = fetch_all_contacts()
        if not contacts:
            return {"skipped": True, "reason": f"no contacts ({reason})"}
        n = 0
        try:
            with db.get_conn() as conn:
                for c in contacts:
                    row = classify_contact(c)
                    if not row["id"]:
                        continue
                    conn.execute(
                        """
                        INSERT INTO attr_contacts (id, email, name, date_added, source, tags,
                            medium, tier, first_touch, last_touch, ft_ad_ref, ft_ref_kind,
                            lt_ad_ref, lt_ref_kind, synced_at, deleted)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
                        ON CONFLICT (id) DO UPDATE SET
                            email=EXCLUDED.email, name=EXCLUDED.name,
                            date_added=EXCLUDED.date_added, source=EXCLUDED.source,
                            tags=EXCLUDED.tags, medium=EXCLUDED.medium, tier=EXCLUDED.tier,
                            first_touch=EXCLUDED.first_touch, last_touch=EXCLUDED.last_touch,
                            ft_ad_ref=EXCLUDED.ft_ad_ref, ft_ref_kind=EXCLUDED.ft_ref_kind,
                            lt_ad_ref=EXCLUDED.lt_ad_ref, lt_ref_kind=EXCLUDED.lt_ref_kind,
                            synced_at=EXCLUDED.synced_at, deleted=FALSE
                        """,
                        (row["id"], row["email"], row["name"], row["date_added"],
                         row["source"], json.dumps(row["tags"]), row["medium"], row["tier"],
                         json.dumps(row["first_touch"]), json.dumps(row["last_touch"]),
                         row["ft_ad_ref"], row["ft_ref_kind"], row["lt_ad_ref"],
                         row["lt_ref_kind"], now_sydney()))
                    n += 1
        except Exception as e:
            logger.error("attr_contacts upsert failed: %s", e)
            return {"skipped": True, "reason": f"upsert failed: {type(e).__name__}"}
        state = {"at": time.time(), "synced": n, "total": len(contacts),
                 "complete": complete, "reason": reason}
        kv_store.put("attr:sync_state", state)
        logger.info("attr_contacts synced: %d/%d complete=%s", n, len(contacts), complete)
        return {"skipped": False, **state}


def load_contacts() -> list[dict]:
    """All non-deleted attr_contacts rows (auth-gated callers only). [] if DB down."""
    if not db.db_configured():
        return []
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, email, name, date_added, source, tags, medium, tier, "
                "first_touch, last_touch, ft_ad_ref, ft_ref_kind, lt_ad_ref, lt_ref_kind, "
                "synced_at FROM attr_contacts WHERE deleted = FALSE").fetchall()
        return list(rows)
    except Exception as e:
        logger.error("load_contacts failed: %s", e)
        return []


def sync_state() -> dict:
    import kv_store
    return kv_store.get("attr:sync_state") or {}
