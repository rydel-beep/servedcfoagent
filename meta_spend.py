"""
meta_spend.py
-------------
Live Meta (Facebook) ad spend from the Marketing API Insights edge — READ-ONLY.

Why this exists: CAC / LTGP:CAC / ROAS are only as accurate as the spend input. The
agent previously used the Xero Advertising line (or a hardcoded fallback) — stale.
This pulls real spend per day and rolls it into the dashboard's windows.

ACCURACY CORE — retroactive refresh: Meta's spend numbers CHANGE after the fact
(attribution firms up over ~72h). A number pulled once and frozen WILL drift from
Ads Manager. So every refresh re-fetches a trailing daily series and OVERWRITES the
stored days — recent spend is never frozen. The trailing META_BACKFILL_DAYS are
flagged provisional so a nudging number is understood, not mistaken for a bug.

Read-only: only the Insights GET edge is used. No ads_management / write scopes.
Token is server-side only (config/env), never logged or returned to the client.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

import requests

from config import (
    META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_API_VERSION,
    META_BACKFILL_DAYS, META_SPEND_WINDOWS, META_PRIMARY_WINDOW,
    META_SPEND_STORE, HTTP_TIMEOUT,
)
from helpers import today_sydney

logger = logging.getLogger(__name__)

# Meta error codes that mean "rate-limited / transient — back off and retry".
_RETRY_CODES = {1, 2, 4, 17, 613, 80004}  # 17/80004/613 = user/app/account rate limits
_MAX_RETRIES = 3
# Fetch a daily series long enough to cover the widest window.
_SERIES_DAYS = max(META_SPEND_WINDOWS) if META_SPEND_WINDOWS else 90


def _account_id() -> str:
    a = (META_AD_ACCOUNT_ID or "").strip()
    if not a:
        return ""
    return a if a.startswith("act_") else f"act_{a}"


_MAX_PAGES = 12  # safety cap; 90 daily rows / ~25 per page → ~4 pages


def _graph_request(url: str, params: dict | None) -> tuple[dict | None, str | None]:
    """One GET (full url, or path resolved against the API base) with backoff.

    Returns (json, error_string). Never raises. Token (in params or the url's
    query for a paging cursor) is never logged.
    """
    if not url.startswith("http"):
        url = f"https://graph.facebook.com/{META_API_VERSION}/{url}"
    backoff = 2.0
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=(5, HTTP_TIMEOUT))
        except requests.RequestException as e:
            last_err = f"request failed: {e}"
            logger.warning("Meta Graph attempt %d: %s", attempt, last_err)
        else:
            if resp.status_code == 200:
                return resp.json(), None
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            code = err.get("code")
            msg = err.get("message", resp.text[:160])
            last_err = f"HTTP {resp.status_code} code={code}: {msg}"
            transient = resp.status_code in (500, 502, 503, 529) or code in _RETRY_CODES
            if not transient:
                return None, last_err
            logger.warning("Meta Graph attempt %d transient: %s", attempt, last_err)
        if attempt < _MAX_RETRIES:
            try:
                import time
                time.sleep(backoff)
            except Exception:
                pass
            backoff *= 2
    return None, last_err


def _graph_get(path: str, params: dict) -> tuple[dict | None, str | None]:
    """Single-object GET (no pagination) — for the account meta call."""
    return _graph_request(path, params)


def _graph_get_all(path: str, params: dict) -> tuple[list | None, str | None]:
    """Paginated GET — follows paging.next until exhausted. Returns ALL data rows.

    Meta's Insights endpoint paginates (default ~25 rows/page, oldest-first). A
    single GET silently truncates to the oldest page, leaving recent windows at $0.
    This follows the cursor so every day in the range is summed.
    """
    first, err = _graph_request(path, params)
    if first is None:
        return None, err
    rows = list(first.get("data", []))
    next_url = (first.get("paging") or {}).get("next")
    pages = 1
    while next_url and pages < _MAX_PAGES:
        # paging.next is a full URL carrying the cursor + access token already.
        nxt, err = _graph_request(next_url, None)
        if nxt is None:
            # Partial result — surface loudly rather than silently truncating.
            return rows, f"pagination stopped early at page {pages}: {err}"
        rows.extend(nxt.get("data", []))
        next_url = (nxt.get("paging") or {}).get("next")
        pages += 1
    if next_url:
        return rows, f"pagination hit page cap ({_MAX_PAGES}) — range may be incomplete"
    return rows, None


def _load_store() -> dict:
    """Load the persisted per-day spend store: {date: {spend, impressions, clicks, last_fetched}}."""
    try:
        if os.path.exists(META_SPEND_STORE):
            with open(META_SPEND_STORE) as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Meta spend store unreadable: %s", e)
    return {}


def _save_store(store: dict) -> None:
    try:
        os.makedirs(os.path.dirname(META_SPEND_STORE) or ".", exist_ok=True)
        with open(META_SPEND_STORE, "w") as f:
            json.dump(store, f, indent=0)
    except OSError as e:
        logger.warning("Meta spend store not persisted: %s", e)


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def spend_in_range(start: str, end: str) -> dict:
    """Meta ad spend for an arbitrary [start, end] window (ISO dates, inclusive).

    Uses the persisted daily store when it fully covers the range (fast); otherwise
    fetches that exact range live from Insights (one call). For the range-aware engine.
    Returns {spend, days_covered, source, degraded}.
    """
    import datetime as _dt
    degraded = []
    try:
        s = _dt.date.fromisoformat(start)
        e = _dt.date.fromisoformat(end)
    except (TypeError, ValueError):
        return {"spend": None, "source": None,
                "degraded": [{"metric": "meta_spend_range", "reason": "bad dates", "severity": "optional"}]}

    store = _load_store()
    dates = []
    for ds in store:
        try:
            dates.append(_dt.date.fromisoformat(ds))
        except ValueError:
            pass
    covers = dates and min(dates) <= s and max(dates) >= e
    if covers:
        total = 0.0
        n = 0
        for ds, row in store.items():
            try:
                d = _dt.date.fromisoformat(ds)
            except ValueError:
                continue
            if s <= d <= e:
                total += _f(row.get("spend"))
                n += 1
        return {"spend": round(total, 2), "days_covered": n, "source": "meta_daily_store",
                "degraded": degraded}

    # Out of the store's coverage → fetch this exact range live (one Insights call).
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        return {"spend": None, "source": None,
                "degraded": [{"metric": "meta_spend_range",
                              "reason": "range outside daily store and no Meta key", "severity": "optional"}]}
    acct = _account_id()
    rows, err = _graph_get_all(f"{acct}/insights", {
        "fields": "spend", "level": "account", "time_increment": 1, "limit": 90,
        "time_range": json.dumps({"since": start, "until": end}),
        "access_token": META_ACCESS_TOKEN,
    })
    if rows is None:
        return {"spend": None, "source": "meta_live_range",
                "degraded": [{"metric": "meta_spend_range",
                              "reason": f"live range fetch failed ({err})", "severity": "optional"}]}
    total = sum(_f(r.get("spend")) for r in rows)
    return {"spend": round(total, 2), "days_covered": len(rows), "source": "meta_live_range",
            "degraded": degraded}


def _window_sum(store: dict, today, days: int) -> dict:
    """Sum the daily store over the trailing `days` calendar days ending today (inclusive)."""
    start = today - timedelta(days=days - 1)
    spend = impressions = clicks = 0.0
    covered = 0
    for ds, row in store.items():
        try:
            from datetime import date
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if start <= d <= today:
            spend += _f(row.get("spend"))
            impressions += _f(row.get("impressions"))
            clicks += _f(row.get("clicks"))
            covered += 1
    return {
        "spend": round(spend, 2),
        "impressions": int(impressions),
        "clicks": int(clicks),
        "days_covered": covered,
        "window_days": days,
        "window_start": str(start),
        "window_end": str(today),
    }


def pull_meta_spend() -> dict:
    """Pull live Meta ad spend (daily series → windowed totals). Read-only.

    Returns {"meta_spend": {...} | None, "degraded": [...]}.
    """
    degraded = []
    token = META_ACCESS_TOKEN
    acct = _account_id()

    if not token or not acct:
        degraded.append({
            "metric": "meta_spend",
            "reason": ("Meta ad spend not configured — set META_ACCESS_TOKEN + "
                       "META_AD_ACCOUNT_ID (read-only ads_read) on the server."),
            "severity": "optional",
        })
        return {"meta_spend": None, "degraded": degraded}

    today = today_sydney()
    since = today - timedelta(days=_SERIES_DAYS - 1)

    # Account currency + timezone (one light call) — never trust spend without currency.
    currency = None
    tz_name = None
    acct_json, acct_err = _graph_get(acct, {
        "fields": "currency,timezone_name,name",
        "access_token": token,
    })
    if acct_json:
        currency = acct_json.get("currency")
        tz_name = acct_json.get("timezone_name")

    # Daily insights series (time_increment=1 → per-day rows). PAGINATED — Meta
    # returns ~25 days/page oldest-first; we follow the cursor for the full range.
    ins_rows, ins_err = _graph_get_all(f"{acct}/insights", {
        "fields": "spend,impressions,clicks",
        "level": "account",
        "time_increment": 1,
        "limit": 90,
        "time_range": json.dumps({"since": str(since), "until": str(today)}),
        "access_token": token,
    })

    store = _load_store()

    if ins_rows is None:
        # Live fetch failed — keep last-good store, surface loudly, never fabricate.
        degraded.append({
            "metric": "meta_spend",
            "reason": f"Meta Insights fetch failed ({ins_err}). Showing last-known spend.",
            "severity": "optional",
        })
        if not store:
            return {"meta_spend": None, "degraded": degraded}
        meta = _assemble(store, today, currency, tz_name, acct, fetch_ok=False)
        return {"meta_spend": meta, "degraded": degraded}

    # ins_rows non-None but ins_err set = partial pagination — use what we got, flag loudly.
    if ins_err:
        degraded.append({
            "metric": "meta_spend",
            "reason": f"Meta Insights returned a partial series ({ins_err}). Recent windows may understate.",
            "severity": "optional",
        })

    # Merge fetched days into the store — OVERWRITE (retroactive; never freeze).
    now_iso = today_sydney().isoformat()
    fetched_days = 0
    for row in ins_rows:
        ds = row.get("date_start")
        if not ds:
            continue
        store[ds] = {
            "spend": round(_f(row.get("spend")), 2),
            "impressions": int(_f(row.get("impressions"))),
            "clicks": int(_f(row.get("clicks"))),
            "last_fetched": now_iso,
        }
        fetched_days += 1
    _save_store(store)

    if currency and currency != "AUD":
        degraded.append({
            "metric": "meta_spend_currency",
            "reason": (f"Meta ad account currency is {currency}, not AUD — spend shown in "
                       f"{currency}; no FX conversion applied. Confirm or add conversion."),
            "severity": "optional",
        })

    meta = _assemble(store, today, currency, tz_name, acct, fetch_ok=True,
                     fetched_days=fetched_days)
    return {"meta_spend": meta, "degraded": degraded}


def _assemble(store: dict, today, currency, tz_name, acct, fetch_ok: bool,
              fetched_days: int = 0) -> dict:
    """Build the meta_spend block: windowed totals + provisional flagging + freshness."""
    windows = {}
    for n in META_SPEND_WINDOWS:
        windows[f"{n}d"] = _window_sum(store, today, n)

    # Current calendar month (Sydney)
    month_start = today.replace(day=1)
    month_spend = month_imps = month_clicks = 0.0
    for ds, row in store.items():
        try:
            from datetime import date
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if month_start <= d <= today:
            month_spend += _f(row.get("spend"))
            month_imps += _f(row.get("impressions"))
            month_clicks += _f(row.get("clicks"))
    windows["month"] = {
        "spend": round(month_spend, 2),
        "impressions": int(month_imps),
        "clicks": int(month_clicks),
        "window_start": str(month_start),
        "window_end": str(today),
        "window_days": (today - month_start).days + 1,
    }

    # Trailing provisional window (attribution still firming up).
    provisional_since = today - timedelta(days=META_BACKFILL_DAYS - 1)

    # Last-fetched freshness (max over stored days).
    last_fetched = None
    for row in store.values():
        lf = row.get("last_fetched")
        if lf and (last_fetched is None or lf > last_fetched):
            last_fetched = lf

    # Compact daily series (sorted) for the UI / attribution.
    daily = []
    for ds in sorted(store.keys()):
        row = store[ds]
        try:
            from datetime import date
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if d < today - timedelta(days=_SERIES_DAYS - 1):
            continue
        daily.append({
            "date": ds,
            "spend": round(_f(row.get("spend")), 2),
            "provisional": d >= provisional_since,
        })

    primary = windows.get(f"{META_PRIMARY_WINDOW}d", {})
    return {
        "account_id": acct,
        "currency": currency,
        "account_timezone": tz_name,
        "windows": windows,
        "primary_window_days": META_PRIMARY_WINDOW,
        "primary_spend": primary.get("spend"),
        "daily": daily,
        "provisional_since": str(provisional_since),
        "provisional_days": META_BACKFILL_DAYS,
        "provisional_note": (
            f"Last {META_BACKFILL_DAYS} days are provisional — Meta attribution firms up "
            f"over ~72h; these re-fetch and may nudge."
        ),
        "last_fetched": last_fetched,
        "fetch_ok": fetch_ok,
        "fetched_days_this_refresh": fetched_days,
        "source": "Meta Marketing API Insights (level=account, read-only)",
        "basis": "GROSS ad spend — FLOW (per period). Agency-wide (single ad account).",
    }
