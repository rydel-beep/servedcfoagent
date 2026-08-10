"""
meta_entities.py
----------------
Meta AD ENTITIES (id ↔ name ↔ adset/campaign) + PER-AD daily spend — READ-ONLY (ads_read).

Why this exists: the attribution engine joins GHL contacts to the exact creative that
produced them. Phase 0 proved three realities this module is built around:
  1. The default /ads listing is INCOMPLETE (several live paused ads referenced by real
     contacts were absent) → the listing here filters for ALL effective statuses incl.
     ARCHIVED, and any id still missing gets a direct Graph lookup (cached, incl. negative).
  2. 114 of 338 ad names are duplicated across campaigns → name resolution returns ALL
     candidates and the join keys creatives by NORMALIZED NAME (creative identity), with
     member ad ids listed.
  3. Deleted/renamed historical ads are recoverable via insights-by-name ("Retargeting NEW
     VSL" → ad id + $4,821.74 of 2025 spend) → recover_by_name() learns kv aliases the same
     way the Stripe payer aliases are learned.

Per-ad spend mirrors meta_spend.py's ACCURACY CORE: Meta restates recent days (~72h), so
every refresh re-fetches a trailing series and overwrites — never frozen. The account-level
meta_spend engine stays the canonical total; reconcile_spend() proves Σ(per-ad) against it.

READ-ONLY structurally: every Graph call in this module goes through _get() (HTTP GET).
There is no POST/DELETE anywhere here — v1 has no Meta write capability.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, timedelta

import requests

from config import (
    META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_API_VERSION, HTTP_TIMEOUT,
)
from helpers import today_sydney

logger = logging.getLogger(__name__)

ENTITY_STORE = os.getenv("META_ENTITY_STORE", "state/meta_ad_entities.json")
AD_SPEND_STORE = os.getenv("META_AD_SPEND_STORE", "state/meta_ad_spend_daily.json")
_ENTITY_TTL_S = int(os.getenv("META_ENTITY_TTL_S", str(12 * 3600)))
_SERIES_DAYS = 90            # same widest window as meta_spend
_BACKFILL_DAYS = 7           # trailing days re-fetched every refresh (attribution firms up)
_ALIAS_KEY = "attr:ad_aliases"          # normalized old name -> ad_id (learned, durable)
_NEG_KEY = "attr:ad_lookup_misses"      # ids that 404'd on direct lookup (don't re-hammer)

_RETRY_CODES = {1, 2, 4, 17, 613, 80004}
_MAX_RETRIES = 3
_MAX_PAGES = 40

_ALL_STATUSES = ["ACTIVE", "PAUSED", "PENDING_REVIEW", "DISAPPROVED", "PREAPPROVED",
                 "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "ARCHIVED", "ADSET_PAUSED",
                 "IN_PROCESS", "WITH_ISSUES"]


def _account_id() -> str:
    a = (META_AD_ACCOUNT_ID or "").strip()
    if not a:
        return ""
    return a if a.startswith("act_") else f"act_{a}"


def configured() -> bool:
    return bool(META_ACCESS_TOKEN and _account_id())


def norm_name(s: str) -> str:
    """Creative-identity key: lowercased, whitespace collapsed. Keeps punctuation —
    'Graphic 3' vs 'Graphic 3 - Copy' are DIFFERENT creatives; only case/spacing noise dies."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _get(url: str, params: dict | None) -> tuple[dict | None, str | None]:
    """One Graph GET with backoff. Never raises; token never logged. GET only — this
    module has no write path to Meta by construction."""
    if not url.startswith("http"):
        url = f"https://graph.facebook.com/{META_API_VERSION}/{url}"
    backoff = 2.0
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=(5, HTTP_TIMEOUT))
        except requests.RequestException as e:
            last_err = f"request failed: {e}"
        else:
            if resp.status_code == 200:
                return resp.json(), None
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            code = err.get("code")
            last_err = f"HTTP {resp.status_code} code={code}: {err.get('message', '')[:160]}"
            if not (resp.status_code in (500, 502, 503, 529) or code in _RETRY_CODES):
                return None, last_err
        if attempt < _MAX_RETRIES:
            time.sleep(backoff)
            backoff *= 2
    return None, last_err


def _get_all(path: str, params: dict) -> tuple[list, str | None]:
    """Paginated GET following paging.next. Partial results surface an error string."""
    first, err = _get(path, params)
    if first is None:
        return [], err
    rows = list(first.get("data", []))
    next_url = (first.get("paging") or {}).get("next")
    pages = 1
    while next_url and pages < _MAX_PAGES:
        nxt, err = _get(next_url, None)
        if nxt is None:
            return rows, f"pagination stopped early at page {pages}: {err}"
        rows.extend(nxt.get("data", []))
        next_url = (nxt.get("paging") or {}).get("next")
        pages += 1
    if next_url:
        return rows, f"pagination hit page cap ({_MAX_PAGES})"
    return rows, None


# ── Entity map (id → ad/adset/campaign), ALL statuses incl. archived ─────────

_json_memo: dict = {}   # {path: (mtime, obj)} — RANGE SPEED: store re-reads were
                        # 370–405ms PER compute; an mtime-keyed memo makes them ~0.
                        # Callers get the SAME object — mutate only on the
                        # refresh paths that _save_json() right after (which
                        # re-stamps the memo), never casually.


def _load_json(path: str) -> dict:
    try:
        if os.path.exists(path):
            mt = os.path.getmtime(path)
            hit = _json_memo.get(path)
            if hit and hit[0] == mt:
                return hit[1]
            with open(path) as f:
                d = json.load(f)
            if isinstance(d, dict):
                _json_memo[path] = (mt, d)
                return d
            return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("store unreadable %s: %s", path, e)
    return {}


def _save_json(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=0)
        _json_memo[path] = (os.path.getmtime(path), data)
    except OSError as e:
        logger.warning("store not persisted %s: %s", path, e)


def refresh_entity_map(force: bool = False) -> dict:
    """Fetch/refresh the full ad entity map. Returns the store dict:
    {"fetched_at": epoch, "ads": {ad_id: {...}}, "degraded": [...]}.
    RANGE SPEED: a TTL lapse no longer blocks the interactive path (4.2s
    measured) — stale-but-present serves the stamped store and refreshes in
    the background; only an EMPTY map (first boot) or force=True fetches inline."""
    store = _load_json(ENTITY_STORE)
    if (not force and store.get("ads")
            and time.time() - float(store.get("fetched_at") or 0) < _ENTITY_TTL_S):
        return store
    if not force and store.get("ads"):
        _kick_bg("entity_map", lambda: refresh_entity_map(force=True))
        return store
    if not configured():
        return {"fetched_at": 0, "ads": store.get("ads") or {},
                "degraded": [{"metric": "meta_entities", "reason": "Meta not configured"}]}
    rows, err = _get_all(f"{_account_id()}/ads", {
        "access_token": META_ACCESS_TOKEN,
        "fields": "id,name,status,effective_status,created_time,"
                  "preview_shareable_link,"
                  "adset{id,name,start_time},campaign{id,name}",
        "filtering": json.dumps([{"field": "ad.effective_status",
                                  "operator": "IN", "value": _ALL_STATUSES}]),
        "limit": 200,
    })
    degraded = []
    if err:
        degraded.append({"metric": "meta_entities", "reason": err})
    if not rows and store.get("ads"):
        # keep the last good map rather than wiping it on a bad fetch
        store.setdefault("degraded", []).extend(degraded)
        return store
    ads = {}
    for a in rows:
        ads[a["id"]] = {
            "name": a.get("name") or "",
            "name_norm": norm_name(a.get("name")),
            "effective_status": a.get("effective_status"),
            # LAUNCH LINEAGE (#133): created_time was REQUESTED but dropped here
            # before 2026-08-09 — the dossier's "created" line silently never
            # rendered. Kept now, with the ad set's (reused!) scheduled start.
            "created_time": a.get("created_time"),
            # PREVIEW LINKS: refreshed with every entity cycle — an ad that
            # leaves the listing loses its link, so rot self-heals to the chip
            "preview_link": a.get("preview_shareable_link"),
            "adset_id": (a.get("adset") or {}).get("id"),
            "adset_name": (a.get("adset") or {}).get("name"),
            "adset_start_time": (a.get("adset") or {}).get("start_time"),
            "campaign_id": (a.get("campaign") or {}).get("id"),
            "campaign_name": (a.get("campaign") or {}).get("name"),
        }
    new_store = {"fetched_at": time.time(), "ads": ads, "degraded": degraded}
    # direct-lookup extras learned earlier survive refreshes (deleted ads never re-list)
    for aid, meta in (store.get("extras") or {}).items():
        new_store.setdefault("extras", {})[aid] = meta
    _save_json(ENTITY_STORE, new_store)
    logger.info("meta entity map refreshed: %d ads (%s)", len(ads), err or "complete")
    return new_store


def _remember_extra(store: dict, ad: dict) -> None:
    """Persist a direct-lookup hit (deleted/unlisted ad) into the store's extras."""
    store.setdefault("extras", {})[ad["id"]] = {
        "name": ad.get("name") or "",
        "name_norm": norm_name(ad.get("name")),
        "effective_status": ad.get("effective_status"),
        "created_time": ad.get("created_time"),
        "preview_link": ad.get("preview_shareable_link"),
        "adset_id": (ad.get("adset") or {}).get("id"),
        "adset_name": (ad.get("adset") or {}).get("name"),
        "adset_start_time": (ad.get("adset") or {}).get("start_time"),
        "campaign_id": (ad.get("campaign") or {}).get("id"),
        "campaign_name": (ad.get("campaign") or {}).get("name"),
    }
    _save_json(ENTITY_STORE, store)


def lookup_ad_id(ad_id: str, store: dict | None = None) -> dict | None:
    """Resolve one ad id: entity map → learned extras → direct Graph lookup (cached,
    incl. negative results so dead ids aren't re-fetched every run)."""
    ad_id = str(ad_id or "").strip()
    if not re.match(r"^\d{10,20}$", ad_id):
        return None
    store = store if store is not None else refresh_entity_map()
    hit = (store.get("ads") or {}).get(ad_id) or (store.get("extras") or {}).get(ad_id)
    if hit:
        return {"ad_id": ad_id, **hit}
    import kv_store
    misses = kv_store.get(_NEG_KEY) or {}
    if ad_id in misses:
        return None
    if not configured():
        return None
    j, err = _get(ad_id, {"access_token": META_ACCESS_TOKEN,
                          "fields": "id,name,effective_status,created_time,"
                                    "preview_shareable_link,"
                                    "adset{id,name,start_time},campaign{id,name}"})
    if j and j.get("id"):
        _remember_extra(store, j)
        return {"ad_id": j["id"], **(store.get("extras") or {}).get(j["id"], {})}
    misses[ad_id] = time.time()
    kv_store.put(_NEG_KEY, misses)
    return None


def candidates_by_name(name: str, store: dict | None = None) -> list[dict]:
    """All ads (listed + extras) whose normalized name matches. May be >1 — the caller
    decides how to treat ambiguity; nothing here guesses."""
    store = store if store is not None else refresh_entity_map()
    key = norm_name(name)
    if not key:
        return []
    out = []
    for src in ("ads", "extras"):
        for aid, meta in (store.get(src) or {}).items():
            if meta.get("name_norm") == key:
                out.append({"ad_id": aid, **meta})
    return out


_NAME_MISS_KEY = "attr:name_recover_misses"   # {name_norm: ts} — RANGE SPEED:
_NAME_MISS_TTL_S = 7 * 86400                  # profiled 12.8s/serve — 3 unresolvable
                                              # name-refs re-swept up to 3 YEARLY
                                              # insights chunks on EVERY fresh
                                              # compute (the dominant term of the
                                              # old F1 cold path). Misses now
                                              # negative-cache for 7 days, same
                                              # discipline as _NEG_KEY id misses.


def recover_by_name(name: str) -> dict | None:
    """Historical name → ad id via insights (works for DELETED ads). On a UNIQUE hit the
    alias is learned in kv (like Stripe payer aliases) so the next run is a lookup, not a
    fetch. Ambiguous/no hits → None (never guesses) — and the miss is negative-cached
    (7d) so it never re-sweeps insights history on the interactive path."""
    key = norm_name(name)
    if not key or not configured():
        return None
    import kv_store
    aliases = kv_store.get(_ALIAS_KEY) or {}
    if key in aliases:
        return lookup_ad_id(aliases[key]) or {"ad_id": aliases[key], "name": name,
                                              "name_norm": key, "basis": "alias"}
    misses = kv_store.get(_NAME_MISS_KEY) or {}
    miss_ts = misses.get(key)
    if miss_ts and time.time() - float(miss_ts) < _NAME_MISS_TTL_S:
        return None
    import meta_range
    today = today_sydney()
    floor = meta_range.api_floor(today)
    hits = {}
    for years_back in range(0, 3):     # sweep up to 3 yearly chunks of insights history
        until = date(today.year - years_back, 12, 31)
        since = date(today.year - years_back, 1, 1)
        if until > today:
            until = today
        if until < floor:              # the whole year is past the API floor — stop
            break                      # (the oldest year is exactly what #3018'd here)
        # the builder clamps `since` to the floor so the oldest in-range year never #3018s
        res = meta_range.insights(
            f"{_account_id()}/insights",
            {"access_token": META_ACCESS_TOKEN, "level": "ad",
             "fields": "ad_id,ad_name", "limit": 500},
            str(since), str(until), _get_all, source="meta_name_recovery")
        for r in res["rows"]:
            if norm_name(r.get("ad_name")) == key:
                hits[r["ad_id"]] = r.get("ad_name")
        if hits:
            break
    if len(hits) == 1:
        aid = next(iter(hits))
        aliases[key] = aid
        kv_store.put(_ALIAS_KEY, aliases)
        logger.info("ad alias learned: '%s' -> %s", key[:60], aid)
        return lookup_ad_id(aid) or {"ad_id": aid, "name": hits[aid], "name_norm": key,
                                     "basis": "alias"}
    # no unique hit — negative-cache so the sweep never re-fires interactively;
    # expiry (7d) keeps the door open for genuinely new historical resolutions
    misses[key] = time.time()
    kv_store.put(_NAME_MISS_KEY, dict(list(misses.items())[-200:]))
    return None


# ── Per-ad daily spend (level=ad insights; retroactive-backfill discipline) ──

_AD_SPEND_TTL_S = int(os.getenv("META_AD_SPEND_TTL_S", "1800"))
_RETAIN_DAYS = int(os.getenv("META_AD_SPEND_RETAIN_DAYS", "800"))
_bg_running: set = set()


def _kick_bg(key: str, fn) -> None:
    """Single-flight background refresh — Meta network NEVER blocks the
    interactive compute path (RANGE SPEED D1: the trailing backfill fired on
    EVERY compute with no TTL — 2–7s of Meta latency per range change)."""
    if key in _bg_running:
        return
    _bg_running.add(key)

    def _run():
        try:
            fn()
        except Exception as e:
            logger.warning("background refresh %s failed: %s", key, e)
        finally:
            _bg_running.discard(key)
    import threading
    threading.Thread(target=_run, daemon=True, name=f"meta-bg-{key}").start()


_KV_AD_SPEND = "meta:ad_spend_daily"   # durable mirror — Railway files die per deploy;
                                       # without this the history backfill would too,
                                       # and every deploy's first compute paid a full
                                       # 90d inline fetch


def _load_spend_store() -> dict:
    store = _load_json(AD_SPEND_STORE)
    if store.get("days"):
        return store
    try:
        import kv_store
        mirrored = kv_store.get(_KV_AD_SPEND)
        if isinstance(mirrored, dict) and mirrored.get("days"):
            _save_json(AD_SPEND_STORE, mirrored)     # reseed the fast local file
            return mirrored
    except Exception as e:
        logger.info("ad-spend kv seed failed: %s", e)
    return store


def _save_spend_store(store: dict) -> None:
    _save_json(AD_SPEND_STORE, store)
    try:
        import kv_store
        kv_store.put(_KV_AD_SPEND, store)
    except Exception as e:
        logger.info("ad-spend kv mirror failed: %s", e)


def refresh_ad_spend_daily(force: bool = False) -> dict:
    """The per-ad daily store {date: {ad_id: {name, spend, impressions, clicks}}} —
    THE Sydney-day spend buckets. TTL-guarded: within _AD_SPEND_TTL_S the store
    serves as-is (refreshed_at = the freshness stamp, carried to payloads);
    stale-but-present kicks a BACKGROUND refresh and serves the stamped store
    (trailing _BACKFILL_DAYS stay provisional by doctrine — Meta restates ~72h);
    only an EMPTY store (first boot) blocks. force=True refreshes inline."""
    store = _load_spend_store()
    if not configured():
        return {"days": store.get("days") or {},
                "degraded": [{"metric": "meta_ad_spend", "reason": "Meta not configured"}]}
    import time as _t
    age = _t.time() - float(store.get("refreshed_at") or 0)
    if store.get("days") and not force:
        if age < _AD_SPEND_TTL_S:
            return store
        _kick_bg("ad_spend", _refresh_ad_spend_sync)
        return store
    return _refresh_ad_spend_sync()


def _refresh_ad_spend_sync() -> dict:
    store = _load_spend_store()
    days = dict(store.get("days") or {})
    today = today_sydney()
    have = sorted(days.keys())
    if have and date.fromisoformat(have[0]) <= today - timedelta(days=_SERIES_DAYS - 1):
        since = today - timedelta(days=_BACKFILL_DAYS - 1)
    else:
        since = today - timedelta(days=_SERIES_DAYS - 1)
    import meta_range
    _res = meta_range.insights(
        f"{_account_id()}/insights",
        {"access_token": META_ACCESS_TOKEN, "level": "ad",
         "fields": "ad_id,ad_name,spend,impressions,clicks",
         "time_increment": 1, "limit": 500},
        str(since), str(today), _get_all, source="meta_ad_spend")
    rows = _res["rows"]
    err = "; ".join(d["cause"] for d in _res["degraded"]) or None
    if _res["degraded"] and not rows:
        rows = None
    degraded = [{"metric": "meta_ad_spend", "reason": err}] if err else []
    if rows or not err:
        # wipe the refetched window first: an ad with $0 today must not keep yesterday's row
        d = since
        while d <= today:
            days[str(d)] = {}
            d += timedelta(days=1)
        for r in rows:
            ds = r.get("date_start")
            aid = r.get("ad_id")
            if not ds or not aid:
                continue
            days.setdefault(ds, {})[aid] = {
                "name": r.get("ad_name") or "",
                "spend": float(r.get("spend") or 0),
                "impressions": int(float(r.get("impressions") or 0)),
                "clicks": int(float(r.get("clicks") or 0)),
            }
        # retention: FULL history within _RETAIN_DAYS (range-speed: Maximum and
        # old custom boxes are store-served — the 90d cap forced live Meta
        # calls onto the interactive path for any older box)
        cutoff = today - timedelta(days=_RETAIN_DAYS - 1)
        for ds in list(days.keys()):
            try:
                if date.fromisoformat(ds) < cutoff:
                    del days[ds]
            except ValueError:
                del days[ds]
        store = {"days": days, "refreshed_at": time.time(),
                 "history_since": store.get("history_since"),
                 "provisional_since": str(today - timedelta(days=2)), "degraded": degraded}
        _save_spend_store(store)
    else:
        store.setdefault("degraded", []).extend(degraded)
    return store


def backfill_history(since: str | None = None) -> dict:
    """Per-ad daily backfill to the retention FLOOR — the permanent archive
    (#138). `since` defaults to the API floor; earlier is clamped (nothing before
    the floor is retrievable). Routed through the ONE builder (chunked, #3018
    impossible); a failed chunk degrades only its own days. Idempotent — a day
    already in the archive is never re-fetched; captured days are source-stamped
    at the store level (`captured_since`). Closed days are stable."""
    import meta_range
    store = _load_spend_store()
    days = store.get("days") or {}
    if not configured():
        return {"error": "Meta not configured"}
    floor = meta_range.api_floor()
    s0 = max(date.fromisoformat(since), floor) if since else floor
    if store.get("history_since") and date.fromisoformat(str(store["history_since"])) <= s0:
        return {"fetched_days": 0, "note": "already covered to the floor",
                "floor": str(floor), "history_since": store["history_since"]}
    have = sorted(days.keys())
    oldest = date.fromisoformat(have[0]) if have else today_sydney()
    if oldest <= s0:
        store["history_since"] = str(s0)
        _save_spend_store(store)
        return {"fetched_days": 0, "note": "store already reaches the floor",
                "floor": str(floor)}
    res = meta_range.insights(
        f"{_account_id()}/insights",
        {"access_token": META_ACCESS_TOKEN, "level": "ad",
         "fields": "ad_id,ad_name,spend,impressions,clicks",
         "time_increment": 1, "limit": 500},
        str(s0), str(oldest - timedelta(days=1)), _get_all,
        source="meta_ad_spend_backfill")
    fetched = 0
    stamp = str(today_sydney())
    for r in res["rows"]:
        ds, aid = r.get("date_start"), r.get("ad_id")
        if not ds or not aid or (ds in days and aid in (days.get(ds) or {})):
            continue
        days.setdefault(ds, {})[aid] = {
            "name": r.get("ad_name") or "",
            "spend": float(r.get("spend") or 0),
            "impressions": int(float(r.get("impressions") or 0)),
            "clicks": int(float(r.get("clicks") or 0)),
            "captured": stamp,
        }
        fetched += 1
    store["days"] = days
    if not res["degraded"]:                 # only claim coverage when every chunk landed
        store["history_since"] = str(s0)
    _save_spend_store(store)
    return {"fetched_days": fetched, "floor": str(floor),
            "history_since": store.get("history_since"),
            "degraded_chunks": res["degraded"]}


def spend_by_ad_in_range(start: str, end: str) -> dict:
    """Per-ad spend/impressions/clicks summed over [start, end] (ISO, inclusive).
    Store when it covers the range; otherwise one live level=ad insights call.
    Returns {ads: {ad_id: {name, spend, impressions, clicks}}, source, degraded}."""
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
    except (TypeError, ValueError):
        return {"ads": {}, "source": None,
                "degraded": [{"metric": "meta_ad_spend_range", "reason": "bad dates"}]}
    store = _load_spend_store()
    days = store.get("days") or {}
    ds_dates = []
    for ds in days:
        try:
            ds_dates.append(date.fromisoformat(ds))
        except ValueError:
            pass
    # STORE-FIRST + ARCHIVE-AUTHORITATIVE (#138): sum every archived day in the
    # request (incl. days now past Meta's API floor we captured earlier), then
    # fetch only the IN-WINDOW days the archive is still missing via the ONE
    # builder (#3018 impossible; a failed chunk degrades only its own days).
    import meta_range
    end_c = min(e, today_sydney())
    floor = meta_range.api_floor()
    out: dict = {}
    covered: set = set()

    def _add(aid, row):
        agg = out.setdefault(aid, {"name": row.get("name") or "", "spend": 0.0,
                                   "impressions": 0, "clicks": 0})
        agg["spend"] += float(row.get("spend") or 0)
        agg["impressions"] += int(float(row.get("impressions") or 0))
        agg["clicks"] += int(float(row.get("clicks") or 0))
        if row.get("name"):
            agg["name"] = row["name"]     # newest name wins (renames)

    for ds, ads in days.items():
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if s <= d <= end_c:
            covered.add(ds)
            for aid, row in ads.items():
                _add(aid, row)

    degraded: list = []
    clamped_from = None
    win_start = max(s, floor)
    if configured() and win_start <= end_c:
        missing = []
        d = win_start
        while d <= end_c:
            if str(d) not in days:
                missing.append(d)
            d += timedelta(days=1)
        if missing:
            res = meta_range.insights(
                f"{_account_id()}/insights",
                {"access_token": META_ACCESS_TOKEN, "level": "ad",
                 "fields": "ad_id,ad_name,spend,impressions,clicks", "limit": 500},
                str(min(missing)), str(max(missing)), _get_all, source="meta_ad_spend_range")
            for r in res["rows"]:
                aid = r.get("ad_id")
                rds = r.get("date_start")
                if aid and rds and rds not in covered:
                    _add(aid, r)
            for dg in res["degraded"]:
                degraded.append({"metric": "meta_ad_spend_range", "source": dg["source"],
                                 "range": dg["range"], "reason": dg["cause"]})
            if res.get("clamped_from"):
                clamped_from = res["clamped_from"]
    if s < floor:
        clamped_from = clamped_from or start
    for a in out.values():
        a["spend"] = round(a["spend"], 2)
    return {"ads": out, "source": "meta_ad_daily_store", "degraded": degraded,
            "clamped_from": clamped_from,
            "clamp_note": meta_range.clamp_note(clamped_from, str(floor)) if clamped_from else None}


def reconcile_spend(start: str, end: str, tolerance_pct: float = 1.0) -> dict:
    """THE anti-contradiction check: Σ per-ad spend vs the canonical account-level
    meta_spend total for the same window. Returns {ok, per_ad_total, account_total,
    drift_pct}. ok=False on drift beyond tolerance — callers must surface, never hide."""
    import meta_spend
    per_ad = spend_by_ad_in_range(start, end)
    acct = meta_spend.spend_in_range(start, end)
    per_ad_total = round(sum(a["spend"] for a in per_ad["ads"].values()), 2)
    account_total = acct.get("spend")
    if account_total is None:
        return {"ok": False, "per_ad_total": per_ad_total, "account_total": None,
                "drift_pct": None, "reason": "account-level spend unavailable"}
    drift = abs(per_ad_total - account_total)
    drift_pct = round(100 * drift / account_total, 2) if account_total else (0.0 if drift == 0 else 100.0)
    return {"ok": drift_pct <= tolerance_pct, "per_ad_total": per_ad_total,
            "account_total": account_total, "drift_pct": drift_pct,
            "sources": {"per_ad": per_ad.get("source"), "account": acct.get("source")}}
