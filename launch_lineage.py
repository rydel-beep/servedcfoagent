"""
launch_lineage.py
-----------------
THE launch + active-days engine (DECISIONS #133). ONE source, consumed by the
hover card, the creative dossier, and any launch/runtime sort — never computed
twice (hover == dossier == sort key is test-enforced).

CONVENTION (#133, veto-able): "launched" = the FIRST-DELIVERY date — the first
day insights records impressions for the ad. NOT created_time (the object's
birthday; shown as secondary when it differs) and NEVER the ad set's start_time
(ad sets are reused here — probe showed start_times up to a year before the ad
existed; context label only). "Days running" = the count of ACTIVE DELIVERY
DAYS (days with impressions/spend), never calendar days since launch — probe
proved a live 30-active/36-calendar ad (B008_A04, 6-day pause).

MECHANICS (probe-proven, dashboard/LAUNCH_DATE_DIAGNOSIS.md D1):
- The per-ad daily spend store only reaches back 90 days; an ad whose earliest
  store day == the store's oldest day is CENSORED — its true launch predates the
  store (15/25 sampled ads, off by 5–52 days). For those, a one-time lifetime
  probe (monthly `date_preset=maximum` sweep → daily zoom in the first active
  month → daily backfill to the store edge) pins the exact day. 2–3 GETs per ad,
  once ever — a launch date never changes after it is observed.
- Delivery days accumulate here durably (the spend store forgets after 90 days;
  this store never does). Days are AD-ACCOUNT-TIMEZONE days (Sydney for this
  account), matching Ads Manager.

HONESTY: Meta-sourced end to end. Not configured / probe failed → the ad's
lineage is DEGRADED with the reason (never a plausible guess); an unprobed
censored ad reports launch_pending_probe=True and its earliest KNOWN day,
labelled "on or before". Read-only: GETs only, ads_read scope.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, timedelta

logger = logging.getLogger(__name__)

LINEAGE_STORE = os.getenv("META_LAUNCH_LINEAGE_STORE", "state/launch_lineage.json")
_PROBE_CAP_PER_REFRESH = int(os.getenv("LAUNCH_PROBE_CAP", "20"))

_mem_cache: dict = {}   # {"mtime": float, "data": dict} — cheap re-reads in-process


_KV_KEY = "launch:lineage"   # durable mirror — Railway local files die on redeploy


def _load() -> dict:
    try:
        mt = os.path.getmtime(LINEAGE_STORE)
        if _mem_cache.get("mtime") == mt:
            return _mem_cache["data"]
        with open(LINEAGE_STORE) as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("ads"):
            _mem_cache.update({"mtime": mt, "data": d})
            return d
    except (OSError, ValueError):
        pass
    # fresh disk (new deploy) → seed from the kv mirror so lifetime probes and
    # pre-store delivery days survive redeploys instead of re-fetching
    try:
        import kv_store
        d = kv_store.get(_KV_KEY)
        if isinstance(d, dict) and d.get("ads"):
            _save(d, mirror=False)
            return d
    except Exception:
        pass
    return {"ads": {}, "updated_at": 0}


def _save(store: dict, mirror: bool = True) -> None:
    try:
        os.makedirs(os.path.dirname(LINEAGE_STORE) or ".", exist_ok=True)
        with open(LINEAGE_STORE, "w") as f:
            json.dump(store, f, indent=0)
        _mem_cache.update({"mtime": os.path.getmtime(LINEAGE_STORE), "data": store})
    except OSError as e:
        logger.warning("launch lineage store not persisted: %s", e)
    if mirror:
        try:
            import kv_store
            kv_store.put(_KV_KEY, store)
        except Exception as e:
            logger.info("launch lineage kv mirror failed: %s", e)


def _delivered(row: dict) -> bool:
    try:
        return float(row.get("spend") or 0) > 0 or int(float(row.get("impressions") or 0)) > 0
    except (TypeError, ValueError):
        return False


_refresh_memo: dict = {}   # spend-store mtime at last merge (range speed: the
                           # 109ms merge refires only when the buckets changed)


def refresh(max_probes: int = _PROBE_CAP_PER_REFRESH) -> dict:
    """Merge the per-ad daily spend store into the durable lineage store, then
    lifetime-probe (once, capped per refresh) any store-censored ad. Idempotent;
    zero network when nothing needs probing. Returns a summary dict."""
    import meta_entities
    try:
        _mt = (os.path.getmtime(meta_entities.AD_SPEND_STORE), LINEAGE_STORE)
    except OSError:
        _mt = None
    if _mt is not None and _refresh_memo.get("spend_mtime") == _mt \
            and not _refresh_memo.get("had_pending"):
        return _refresh_memo.get("last") or {"ads": 0, "probed": 0,
                                             "pending_probes": 0, "degraded": []}
    store = _load()
    ads = store.setdefault("ads", {})
    spend_store = meta_entities._load_json(meta_entities.AD_SPEND_STORE)
    days = spend_store.get("days") or {}
    ds = sorted(days.keys())
    store_min = ds[0] if ds else None
    changed = False
    for d in ds:
        for aid, row in (days[d] or {}).items():
            if not _delivered(row):
                continue
            rec = ads.setdefault(aid, {"first_delivery": None, "delivery_days": [],
                                       "lifetime_probed": False})
            if d not in rec["delivery_days"]:
                rec["delivery_days"].append(d)
                changed = True
    for rec in ads.values():
        rec["delivery_days"].sort()
        if not rec.get("lifetime_probed"):
            first_known = rec["delivery_days"][0] if rec["delivery_days"] else None
            # censored: earliest known day sits on the store's oldest edge — the
            # true launch may predate the store; only the lifetime probe can say.
            cens = bool(first_known and store_min and first_known <= store_min)
            fd = first_known if not cens else rec.get("first_delivery")
            if rec.get("censored") != cens or rec.get("first_delivery") != fd:
                changed = True
            rec["censored"] = cens
            if not cens:
                rec["first_delivery"] = first_known
    need = [aid for aid, r in ads.items()
            if r.get("censored") and not r.get("lifetime_probed")]
    probed = 0
    degraded = []
    if need and not meta_entities.configured():
        degraded.append({"metric": "launch_lineage",
                         "reason": f"{len(need)} ad(s) need a lifetime launch probe but "
                                   "Meta is not configured — their launch stays 'on or "
                                   "before' the store edge, never guessed"})
    elif need:
        for aid in need[:max_probes]:
            err = _lifetime_probe(aid, ads[aid], store_min)
            changed = True
            if err:
                degraded.append({"metric": "launch_lineage",
                                 "reason": f"lifetime probe failed for ad {aid}: {err}"})
            else:
                probed += 1
    if changed:
        store["updated_at"] = time.time()
        _save(store)
    pending = sum(1 for r in ads.values() if r.get("censored") and not r.get("lifetime_probed"))
    out = {"ads": len(ads), "probed": probed, "pending_probes": pending,
           "degraded": degraded}
    _refresh_memo.update({"spend_mtime": _mt, "had_pending": bool(pending or degraded),
                          "last": out})
    return out


def _lifetime_probe(ad_id: str, rec: dict, store_min: str | None) -> str | None:
    """One-time exact-launch probe: monthly lifetime sweep → daily zoom in the
    first active month → daily backfill up to the store edge. Returns error or None."""
    import meta_entities
    j, err = meta_entities._get(f"{ad_id}/insights", {
        "access_token": _token(), "fields": "impressions,spend",
        "time_increment": "monthly", "date_preset": "maximum", "limit": 100})
    if j is None:
        rec["probe_error"] = err
        return err
    months = [r for r in j.get("data", []) if _delivered(r)]
    if not months:
        rec.update({"lifetime_probed": True, "no_delivery": not rec["delivery_days"],
                    "first_delivery": rec["delivery_days"][0] if rec["delivery_days"] else None,
                    "censored": False, "probed_at": time.strftime("%Y-%m-%d")})
        rec.pop("probe_error", None)
        return None
    first_month = months[0]
    # daily backfill: first active month start → the store edge (exact day list;
    # one paginated call — months of history fit one 500-row page)
    until = store_min or time.strftime("%Y-%m-%d")
    rows, gerr = meta_entities._get_all(f"{ad_id}/insights", {
        "access_token": _token(), "fields": "impressions,spend",
        "time_increment": 1, "limit": 500,
        "time_range": json.dumps({"since": first_month["date_start"], "until": until})})
    if gerr and not rows:
        rec["probe_error"] = gerr
        return gerr
    for r in rows:
        if _delivered(r) and r.get("date_start") and r["date_start"] not in rec["delivery_days"]:
            rec["delivery_days"].append(r["date_start"])
    rec["delivery_days"].sort()
    rec.update({"lifetime_probed": True, "censored": False,
                "first_delivery": rec["delivery_days"][0] if rec["delivery_days"] else None,
                "probed_at": time.strftime("%Y-%m-%d")})
    rec.pop("probe_error", None)
    if gerr:
        logger.warning("launch probe partial for %s: %s", ad_id, gerr)
    return None


def _token() -> str:
    from config import META_ACCESS_TOKEN
    return META_ACCESS_TOKEN


def lineage_for(ad_ids: list[str], entity_store: dict | None = None,
                today: date | None = None) -> dict | None:
    """The ONE lineage read for a creative/group (its member ad ids). Scalars only
    (rollup-safe); the dossier fetches delivery_days() separately for the timeline.
    Returns None for tier rows (no ads). Never guesses: unknown → degraded reason."""
    ad_ids = [str(a) for a in (ad_ids or []) if a]
    if not ad_ids:
        return None
    from helpers import today_sydney
    today = today or today_sydney()
    store = _load()
    ads = store.get("ads") or {}
    day_union: set = set()
    cands: list = []          # (date, is_approx) — exact beats approx on a tie
    known = 0
    never = 0
    for aid in ad_ids:
        rec = ads.get(aid)
        if not rec:
            continue
        known += 1
        day_union.update(rec.get("delivery_days") or [])
        if rec.get("censored") and not rec.get("lifetime_probed"):
            # probe pending — the true launch may PREDATE the earliest known day
            if rec.get("delivery_days"):
                cands.append((rec["delivery_days"][0], True))
        elif rec.get("first_delivery"):
            cands.append((rec["first_delivery"], False))
        elif rec.get("no_delivery"):
            never += 1
    if not known:
        nk = {"launch": None, "active_days": None, "calendar_days": None,
              "status": _status(ad_ids, entity_store),
              "created_time": _created(ad_ids, entity_store),
              "scheduled_start": _sched(ad_ids, entity_store),
              "source": "meta:insights",
              "degraded": "no delivery record for this ad in Meta insights — "
                          "launch unknown (not a zero)"}
        nk.update(_preview(ad_ids, entity_store))
        return nk
    launch, launch_approx = min(cands) if cands else (None, False)
    active = len([d for d in day_union if d <= str(today)])
    cal = None
    if launch:
        try:
            cal = (today - date.fromisoformat(launch)).days + 1
        except ValueError:
            cal = None
    last = max(day_union) if day_union else None
    out = {
        "launch": launch,
        "launch_approx": launch_approx,   # True → "on or before" (probe pending)
        "never_delivered": bool(launch is None and never == known),
        "active_days": active,
        "calendar_days": cal,
        "last_delivery": last,
        "delivered_recently": bool(last and (today - date.fromisoformat(last)).days <= 2),
        "status": _status(ad_ids, entity_store),
        "created_time": _created(ad_ids, entity_store),
        "scheduled_start": _sched(ad_ids, entity_store),
        "source": "meta:insights",
        "degraded": None,
    }
    out.update(_preview(ad_ids, entity_store))
    return out


def _preview(ad_ids, entity_store) -> dict:
    """PREVIEW LINKS: {preview_link, preview_state} where state is
    'link' (live shareable link) · 'deleted' (the ad no longer exists in the
    listing — an honest chip, never a dead link) · 'pending' (listed ad whose
    link the next entity refresh will carry)."""
    listed = deleted = 0
    for a in ad_ids or []:
        e = _entity(a, entity_store)
        if not e:
            deleted += 1
            continue
        listed += 1
        if e.get("preview_link"):
            return {"preview_link": e["preview_link"], "preview_state": "link"}
    if listed:
        return {"preview_link": None, "preview_state": "pending"}
    if deleted:
        return {"preview_link": None, "preview_state": "deleted"}
    return {"preview_link": None, "preview_state": None}


def delivery_days(ad_ids: list[str], today: date | None = None) -> list[str]:
    """The exact delivery-day union for the dossier timeline. Same store the
    scalars came from — one source, full resolution."""
    from helpers import today_sydney
    today = today or today_sydney()
    store = _load()
    out: set = set()
    for aid in (ad_ids or []):
        out.update((store.get("ads") or {}).get(str(aid), {}).get("delivery_days") or [])
    return sorted(d for d in out if d <= str(today))


def _entity(aid: str, entity_store: dict | None) -> dict:
    if not entity_store:
        return {}
    return ((entity_store.get("ads") or {}).get(aid)
            or (entity_store.get("extras") or {}).get(aid) or {})


def _status(ad_ids, entity_store):
    stats = [(_entity(a, entity_store).get("effective_status")) for a in ad_ids]
    stats = [s for s in stats if s]
    if not stats:
        return None
    if any(s == "ACTIVE" for s in stats):
        return "ACTIVE"
    return stats[0]


def _created(ad_ids, entity_store):
    vals = [(_entity(a, entity_store).get("created_time") or "")[:10] for a in ad_ids]
    vals = [v for v in vals if v]
    return min(vals) if vals else None


def _sched(ad_ids, entity_store):
    vals = [(_entity(a, entity_store).get("adset_start_time") or "")[:10] for a in ad_ids]
    vals = [v for v in vals if v]
    return min(vals) if vals else None


def aggregate_rows(rows: list[dict], today: date | None = None) -> dict | None:
    """Group-level lineage for the ladder (Names/Batches/Campaigns/Account):
    engine-side union over member creatives' ad ids — the hover on a group name
    reads THIS, never client math (I16)."""
    ad_ids: list[str] = []
    for r in rows or []:
        ad_ids.extend(r.get("ad_ids") or [])
    if not ad_ids:
        return None
    return lineage_for(sorted(set(ad_ids)), entity_store=_entities_cached(), today=today)


def _entities_cached() -> dict:
    """The entity map without forcing a network refresh (file-backed; the
    engine's own refresh keeps it warm)."""
    try:
        import meta_entities
        return meta_entities._load_json(meta_entities.ENTITY_STORE)
    except Exception:
        return {}
