"""
attribution_audit.py — EDITH Phase 0: THE ATTRIBUTION TRUTH AUDIT (read-only)

What it does (GET requests only; no writes anywhere):
  1. Lists ALL GHL contacts (paginated) and, where the list payload lacks attribution,
     fetches each contact individually (throttled) to read attributionSource /
     lastAttributionSource.
  2. Classifies every contact: AD-level / CAMPAIGN-level / SOURCE-only / NONE,
     split by recency (dateAdded within 90d vs older).
  3. Fetches the Meta account's ads (id, name, adset, campaign, url_tags) and proves
     the join on a sample of ad-level contacts (contact → exact ad creative).
  4. Diagnoses capture gaps: url_tags on active ads, attribution url domains
     (landing pages), lead-form vs manual entry shapes.

Output:
  - Aggregate report printed to stdout (PII masked: emails/names truncated).
  - Raw dump (JSON, contains PII) written to --raw-out path (keep OUT of the repo).

Run:  railway run python scripts/attribution_audit.py --raw-out /path/raw.json [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import (
    GHL_BASE, GHL_API_KEY, GHL_LOCATION_ID,
    META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_API_VERSION, HTTP_TIMEOUT,
)

THROTTLE = 0.12  # ~8 req/s, same discipline as ghl_mirror
MAX_LIST_PAGES = 60  # 60 * 100 = 6,000 contacts — cap flagged if hit, never silent


def _ghl_headers():
    return {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28"}


def _get(url, params=None, headers=None, retries=3):
    backoff = 2.0
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=(5, HTTP_TIMEOUT))
        except requests.RequestException as e:
            if attempt == retries:
                return None, f"request failed: {e}"
            time.sleep(backoff); backoff *= 2; continue
        if r.status_code == 200:
            return r.json(), None
        if r.status_code in (429, 500, 502, 503, 529) and attempt < retries:
            time.sleep(backoff); backoff *= 2; continue
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    return None, "unreachable"


# ---------------------------------------------------------------- GHL contacts

def list_all_contacts():
    """Paginate GET /contacts/ for the location. Returns (contacts, complete, reason)."""
    out, seen = [], set()
    params = {"locationId": GHL_LOCATION_ID, "limit": 100}
    page = 0
    while page < MAX_LIST_PAGES:
        page += 1
        data, err = _get(f"{GHL_BASE}/contacts/", params=dict(params), headers=_ghl_headers())
        if err:
            return out, False, f"page {page}: {err}"
        batch = data.get("contacts", [])
        for c in batch:
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid); out.append(c)
        meta = data.get("meta", {})
        nxt = meta.get("startAfterId") or meta.get("nextPageUrl")
        if not batch or not nxt:
            return out, True, None
        if meta.get("startAfterId"):
            params["startAfterId"] = meta["startAfterId"]
            if meta.get("startAfter"):
                params["startAfter"] = meta["startAfter"]
        else:
            return out, True, None
        time.sleep(THROTTLE)
    return out, False, f"hit MAX_LIST_PAGES={MAX_LIST_PAGES}"


def fetch_contact_detail(cid):
    data, err = _get(f"{GHL_BASE}/contacts/{cid}", headers=_ghl_headers())
    if err:
        return None, err
    return data.get("contact", data), None


# ------------------------------------------------------------- classification

AD_ID_RE = re.compile(r"^\d{10,20}$")  # Meta ad/adset/campaign ids are long digit strings


def extract_attr(contact):
    """Return the attribution dicts present on a contact, first- and last-touch."""
    first = contact.get("attributionSource") or {}
    last = contact.get("lastAttributionSource") or {}
    # some payloads carry a list under 'attributions'
    attrs = contact.get("attributions") or []
    if not first and attrs:
        first = attrs[0] or {}
    if not last and len(attrs) > 1:
        last = attrs[-1] or {}
    return first, last


def classify(first, last):
    """AD / CAMPAIGN / SOURCE / NONE, using the richer of the two touches."""
    def level(a):
        if not a:
            return "NONE"
        utm_content = str(a.get("utmContent") or "")
        ad_id = str(a.get("adId") or a.get("utmAdId") or "")
        if AD_ID_RE.match(utm_content) or AD_ID_RE.match(ad_id) or (utm_content.strip() != ""):
            return "AD"
        camp = str(a.get("campaignId") or a.get("utmCampaign") or a.get("campaign") or "")
        if camp.strip():
            return "CAMPAIGN"
        src = str(a.get("sessionSource") or a.get("utmSource") or a.get("medium")
                  or a.get("referrer") or a.get("url") or "")
        if src.strip():
            return "SOURCE"
        if a.get("fbclid") or a.get("fbc") or a.get("fbp") or a.get("gclid"):
            return "SOURCE"  # click identity, but not ad-resolvable retroactively
        return "NONE"
    order = {"AD": 0, "CAMPAIGN": 1, "SOURCE": 2, "NONE": 3}
    lf, ll = level(first), level(last)
    return lf if order[lf] <= order[ll] else ll


def has_fbclid(first, last):
    return bool((first or {}).get("fbclid") or (last or {}).get("fbclid")
                or (first or {}).get("fbc") or (last or {}).get("fbc"))


def parse_date_added(contact):
    raw = contact.get("dateAdded") or contact.get("createdAt") or ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.strptime(raw, fmt)
            return d.replace(tzinfo=d.tzinfo or timezone.utc)
        except ValueError:
            continue
    return None


# -------------------------------------------------------------------- Meta ads

def fetch_meta_ads():
    """All ads on the account: id, name, adset, campaign, status, creative url_tags."""
    acct = (META_AD_ACCOUNT_ID or "").strip()
    if acct and not acct.startswith("act_"):
        acct = f"act_{acct}"
    ads, url = [], f"https://graph.facebook.com/{META_API_VERSION}/{acct}/ads"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "fields": "id,name,status,effective_status,created_time,"
                  "adset{id,name},campaign{id,name},creative{id,url_tags,object_story_spec}",
        "limit": 100,
    }
    pages = 0
    while url and pages < 30:
        pages += 1
        data, err = _get(url, params=params)
        if err:
            return ads, err
        ads.extend(data.get("data", []))
        url = (data.get("paging") or {}).get("next")
        params = None  # cursor url carries everything
        time.sleep(0.3)
    return ads, None


# ------------------------------------------------------------------------ main

def mask(s, keep=3):
    s = str(s or "")
    return s[:keep] + "…" if len(s) > keep else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="cap individual contact fetches (smoke test)")
    args = ap.parse_args()

    print("== PHASE A: list all contacts ==", flush=True)
    contacts, complete, reason = list_all_contacts()
    print(f"contacts listed: {len(contacts)} complete={complete} reason={reason}", flush=True)
    if not contacts:
        sys.exit("no contacts — token/location problem, stopping")

    # Does the LIST payload already carry attribution?
    probe = contacts[0]
    list_has_attr = any(k in probe for k in ("attributionSource", "lastAttributionSource", "attributions"))
    print(f"list payload carries attribution fields: {list_has_attr}")
    print(f"sample list-payload keys: {sorted(probe.keys())}")

    # PHASE B: individual fetches if needed
    detailed = []
    todo = contacts if not args.limit else contacts[: args.limit]
    if list_has_attr:
        detailed = todo
    else:
        print(f"== PHASE B: fetching {len(todo)} contacts individually (throttled) ==", flush=True)
        errs = 0
        for i, c in enumerate(todo):
            d, err = fetch_contact_detail(c["id"])
            if d:
                detailed.append(d)
            else:
                errs += 1
            if (i + 1) % 250 == 0:
                print(f"  {i+1}/{len(todo)} fetched ({errs} errors)", flush=True)
            time.sleep(THROTTLE)
        print(f"detail fetch done: {len(detailed)} ok, {errs} errors", flush=True)

    # PHASE C: classify
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)
    dist = Counter(); dist_recent = Counter(); dist_old = Counter()
    fbclid_only = 0
    ad_level_contacts = []
    source_values = Counter()
    url_domains = Counter()
    medium_values = Counter()
    for c in detailed:
        first, last = extract_attr(c)
        cls = classify(first, last)
        dist[cls] += 1
        da = parse_date_added(c)
        (dist_recent if (da and da >= cutoff) else dist_old)[cls] += 1
        if cls != "AD" and has_fbclid(first, last):
            fbclid_only += 1
        if cls == "AD":
            ad_level_contacts.append(c)
        for a in (first, last):
            if not a:
                continue
            if a.get("sessionSource"):
                source_values[str(a["sessionSource"])] += 1
            if a.get("medium"):
                medium_values[str(a["medium"])] += 1
            u = str(a.get("url") or "")
            m = re.match(r"https?://([^/]+)", u)
            if m:
                url_domains[m.group(1)] += 1

    total = len(detailed) or 1
    print("\n== ATTRIBUTION DISTRIBUTION ==")
    for k in ("AD", "CAMPAIGN", "SOURCE", "NONE"):
        print(f"  {k:9s}: {dist[k]:5d}  ({100*dist[k]/total:.1f}%)   "
              f"recent90d={dist_recent[k]}  older={dist_old[k]}")
    print(f"  fbclid present but NOT ad-resolvable: {fbclid_only}")
    print(f"\n  top sessionSource values: {source_values.most_common(12)}")
    print(f"  top medium values: {medium_values.most_common(12)}")
    print(f"  top attribution url domains: {url_domains.most_common(12)}")

    # PHASE D: Meta ads + resolution test
    print("\n== PHASE D: Meta ads fetch ==", flush=True)
    ads, err = fetch_meta_ads()
    print(f"ads fetched: {len(ads)} err={err}")
    by_id = {a["id"]: a for a in ads}
    by_name = defaultdict(list)
    for a in ads:
        by_name[a.get("name", "").strip().lower()].append(a)

    active_ads = [a for a in ads if a.get("effective_status") == "ACTIVE"]
    tagged = [a for a in active_ads if (a.get("creative") or {}).get("url_tags")]
    print(f"ACTIVE ads: {len(active_ads)}; with url_tags: {len(tagged)}")
    for a in active_ads[:15]:
        ut = (a.get("creative") or {}).get("url_tags") or "(none)"
        print(f"  ACTIVE ad {a['id']} '{a.get('name','')[:60]}' url_tags: {ut[:120]}")

    print("\n== RESOLUTION TEST (contact → creative) ==")
    resolved, examples = 0, []
    for c in ad_level_contacts:
        first, last = extract_attr(c)
        a = first if classify(first, {}) == "AD" else last
        uc = str(a.get("utmContent") or a.get("adId") or a.get("utmAdId") or "").strip()
        hit, how = None, None
        if uc in by_id:
            hit, how = by_id[uc], "by ad id"
        elif uc.lower() in by_name:
            cands = by_name[uc.lower()]
            hit, how = cands[0], f"by ad NAME ({len(cands)} candidates)"
        if hit:
            resolved += 1
            if len(examples) < 10:
                examples.append({
                    "contact": f"{mask(c.get('firstName'))} {mask(c.get('lastName'))} <{mask(c.get('email'), 4)}>",
                    "utm_content": uc[:80], "how": how,
                    "ad": f"{hit['id']} '{hit.get('name','')[:70]}'",
                    "campaign": (hit.get("campaign") or {}).get("name", "")[:60],
                })
    print(f"ad-level contacts: {len(ad_level_contacts)}; resolved to a Meta ad: {resolved}")
    for e in examples:
        print(f"  {e['contact']}  utm_content={e['utm_content']}  → {e['how']} → {e['ad']}  [{e['campaign']}]")

    raw = {
        "generated_at": now.isoformat(),
        "counts": {"listed": len(contacts), "detailed": len(detailed)},
        "distribution": dict(dist), "recent": dict(dist_recent), "older": dict(dist_old),
        "fbclid_only": fbclid_only,
        "session_sources": dict(source_values), "mediums": dict(medium_values),
        "url_domains": dict(url_domains),
        "meta_ads_count": len(ads), "active_ads": len(active_ads), "active_tagged": len(tagged),
        "resolution": {"ad_level": len(ad_level_contacts), "resolved": resolved, "examples": examples},
        "contacts_raw": detailed,   # PII — scratchpad only
        "ads_raw": ads,
    }
    Path(args.raw_out).write_text(json.dumps(raw, default=str))
    print(f"\nraw dump → {args.raw_out}")


if __name__ == "__main__":
    main()
