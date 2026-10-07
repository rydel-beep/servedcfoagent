"""sync.py — copy each source into the scoreboard's raw tables, on a cadence.

  ghl         every 15 min  pipelines, calendars, appointments, opportunities,
                            contacts (cut down — fetch.safe_contact), and the
                            stage recorder (when each deal entered Closed Won)
  stripe      every 15 min  charges, refunds, payouts
  meta_today  hourly        today + yesterday, account and ad level
  meta_final  nightly 3am   yesterday and the day before, marked final
  xero        daily         bank transactions + sales invoices (needs the
                            reconnect), monthly P&L (for gross margin)
  tracker     hourly        the Lead-to-Cash tracker rows — cross-check only

The first successful run of each job backfills history; after that each run
re-reads a recent stretch so late edits (a status marked, a refund) land.
Every run records its outcome in sb_sync — the page's freshness line.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from helpers import SYDNEY_TZ, now_sydney

from . import fetch, store

logger = logging.getLogger(__name__)

CLOSED_WON_STAGE_NAMES = ("✅ Closed Deal",)
GHL_EVENTS_FROM = dt.date(2026, 1, 1)
STRIPE_FROM = dt.date(2024, 7, 1)
META_ACCOUNT_FROM = dt.date(2025, 7, 1)
META_AD_FROM = dt.date(2026, 6, 1)
XERO_FROM = dt.date(2026, 1, 1)

CADENCE_S = {"ghl": 15 * 60, "stripe": 15 * 60, "meta_today": 60 * 60, "tracker": 60 * 60,
             "xero": 24 * 3600, "meta_final": 24 * 3600}


def _syd(d: dt.date, end: bool = False) -> dt.datetime:
    t = dt.time(23, 59, 59) if end else dt.time(0, 0)
    return dt.datetime.combine(d, t, tzinfo=SYDNEY_TZ)


def _backfilled(job: str) -> bool:
    return (store.sync_state().get(job) or {}).get("note") == "backfilled"


def _months(a: dt.date, b: dt.date):
    cur = a.replace(day=1)
    while cur <= b:
        nxt = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield max(cur, a), min(nxt - dt.timedelta(days=1), b)
        cur = nxt


# ── GHL ─────────────────────────────────────────────────────────────────────

def sync_ghl() -> dict:
    today = now_sydney().date()
    pipelines = fetch.ghl_pipelines()
    store.upsert("ghl", "pipeline", {p["id"]: p for p in pipelines})
    cals = fetch.ghl_calendars()
    store.upsert("ghl", "calendar", {c["id"]: c for c in cals})

    full = not _backfilled("ghl")
    start = GHL_EVENTS_FROM if full else today - dt.timedelta(days=45)
    end = today + dt.timedelta(days=60)
    seen, n_events = set(), 0
    for c in cals:
        for a, b in _months(start, end):
            evs = fetch.ghl_events(c["id"], _syd(a), _syd(b, end=True))
            recs = {}
            for e in evs:
                e["_calendarName"] = c.get("name")
                e["_calendarTimezone"] = c.get("timezone")
                recs[e["id"]] = e
                seen.add(e["id"])
            n_events += store.upsert("ghl", "event", recs)
    # an appointment GHL no longer returns for a range we re-read was deleted
    # in GHL: keep the row (history), mark it gone so it is never counted
    gone = {}
    lo, hi = _syd(start).isoformat(), _syd(end, end=True).isoformat()
    for eid, e in store.read("ghl", "event").items():
        st = str(e.get("startTime") or "")
        if eid not in seen and not e.get("_gone") and _in_range(st, lo, hi):
            gone[eid] = {**e, "_gone": now_sydney().isoformat()}
    store.upsert("ghl", "event", gone)

    opps = fetch.ghl_opportunities()
    store.upsert("ghl", "opportunity", {o["id"]: o for o in opps})
    won = {s["id"] for p in pipelines for s in p.get("stages") or []
           if s.get("name") in CLOSED_WON_STAGE_NAMES}
    for o in opps:
        if o.get("pipelineStageId") in won:
            # first sighting wins: a later edit to the deal can't move its close date
            store.insert_if_absent("ghl", "closed_entered", o["id"], {
                "stage_id": o["pipelineStageId"], "entered_at": o.get("lastStageChangeAt"),
                "first_seen": now_sydney().isoformat()})

    contacts = fetch.ghl_contacts()
    store.upsert("ghl", "contact", {c["id"]: c for c in contacts if c.get("id")})
    return {"rows": len(opps) + len(contacts) + n_events,
            "detail": f"{len(opps)} opportunities · {len(contacts)} contacts · {n_events} appointments read"
                      f" · {len(gone)} appointments gone from GHL"}


def _in_range(iso: str, lo: str, hi: str) -> bool:
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=SYDNEY_TZ)
        return dt.datetime.fromisoformat(lo) <= t <= dt.datetime.fromisoformat(hi)
    except ValueError:
        return False


# ── Stripe ──────────────────────────────────────────────────────────────────

def sync_stripe() -> dict:
    today = now_sydney().date()
    since = STRIPE_FROM if not _backfilled("stripe") else today - dt.timedelta(days=10)
    ch = fetch.stripe_charges(_syd(since))
    store.upsert("stripe", "charge", {c["id"]: c for c in ch})
    rf = fetch.stripe_refunds(_syd(STRIPE_FROM if not _backfilled("stripe") else today - dt.timedelta(days=120)))
    store.upsert("stripe", "refund", {r["id"]: r for r in rf})
    po = fetch.stripe_payouts(_syd(STRIPE_FROM if not _backfilled("stripe") else today - dt.timedelta(days=120)))
    store.upsert("stripe", "payout", {p["id"]: p for p in po})
    return {"rows": len(ch) + len(rf) + len(po),
            "detail": f"{len(ch)} charges · {len(rf)} refunds · {len(po)} payouts read"}


# ── Meta ────────────────────────────────────────────────────────────────────

def _meta_store(since: dt.date, until: dt.date, final: bool) -> int:
    n = 0
    acct = fetch.meta_insights("account", str(since), str(until))
    recs = {r["date_start"]: {**r, "_final": final, "_read_at": now_sydney().isoformat()} for r in acct}
    # a day with no delivery returns no row: record it as $0 so the day is known, not missing
    d = since
    while d <= until:
        recs.setdefault(str(d), {"date_start": str(d), "spend": "0", "impressions": "0", "clicks": "0",
                                 "actions": [], "_final": final, "_no_delivery": True,
                                 "_read_at": now_sydney().isoformat()})
        d += dt.timedelta(days=1)
    n += store.upsert("meta", "account_day", recs)
    if until >= META_AD_FROM:
        ads = fetch.meta_insights("ad", str(max(since, META_AD_FROM)), str(until))
        n += store.upsert("meta", "ad_day", {f"{r['date_start']}:{r['ad_id']}": {**r, "_final": final}
                                             for r in ads})
    return n


def sync_meta_today() -> dict:
    today = now_sydney().date()
    n = _meta_store(today - dt.timedelta(days=1), today, final=False)
    return {"rows": n, "detail": "today and yesterday (not final)"}


def sync_meta_final() -> dict:
    today = now_sydney().date()
    n = 0
    if not _backfilled("meta_final"):
        failed = []
        for a, b in _months(META_ACCOUNT_FROM, today - dt.timedelta(days=1)):
            try:
                n += _meta_store(a, b, final=True)
            except fetch.SourceError as e:
                failed.append(f"{a:%b %Y}: {e}")
        if failed:
            raise fetch.SourceError(f"{len(failed)} month(s) not read, will retry: " + "; ".join(failed[:3]))
    else:
        n += _meta_store(today - dt.timedelta(days=3), today - dt.timedelta(days=1), final=True)
    return {"rows": n, "detail": "closed days re-read and marked final"}


# ── Xero ────────────────────────────────────────────────────────────────────

def sync_xero() -> dict:
    today = now_sydney().date()
    notes = []
    rows = 0
    # monthly P&L (the existing report scope works today)
    for k in range(1, 7):
        first = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        m0 = first
        for _ in range(k - 1):
            m0 = (m0 - dt.timedelta(days=1)).replace(day=1)
        m1 = (m0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        p = fetch.xero_pnl_month(str(m0), str(m1))
        if p.get("ok"):
            store.upsert("xero", "pnl_month", {str(m0)[:7]: {k2: p.get(k2) for k2 in (
                "revenue", "cogs", "gross_profit", "gross_margin_pct", "operating_expenses",
                "net_profit", "window", "basis")}})
            rows += 1
        else:
            notes.append(f"P&L {str(m0)[:7]}: {p.get('reason')}")
    # bank feed + invoices (needs the reconnect)
    try:
        bi = fetch.xero_bank_and_invoices(XERO_FROM)
        store.upsert("xero", "bank_txn", {b["BankTransactionID"]: b for b in bi["bank"]})
        store.upsert("xero", "invoice", {i["InvoiceID"]: i for i in bi["invoices"]})
        rows += len(bi["bank"]) + len(bi["invoices"])
    except fetch.SourceError as e:
        raise fetch.SourceError(f"{e} (monthly P&L: {rows} months read)") from e
    return {"rows": rows, "detail": "; ".join(notes) or "bank feed, invoices and P&L read"}


# ── tracker ─────────────────────────────────────────────────────────────────

def sync_tracker() -> dict:
    rows = fetch.tracker_rows()
    store.upsert("tracker", "sheet", {"ltc": {"rows": rows, "read_at": now_sydney().isoformat()}})
    return {"rows": len(rows), "detail": f"{len(rows)} tracker rows (cross-check only)"}


JOBS = {"ghl": sync_ghl, "stripe": sync_stripe, "meta_today": sync_meta_today,
        "meta_final": sync_meta_final, "xero": sync_xero, "tracker": sync_tracker}


def run(job: str) -> dict:
    """Run one job now; record the outcome. Never raises."""
    t0 = time.time()
    try:
        out = JOBS[job]()
        first = not _backfilled(job)
        store.mark(job, True, rows=out.get("rows"), note="backfilled")
        logger.info("scoreboard sync %s ok in %.1fs%s: %s", job, time.time() - t0,
                    " (first run: history backfilled)" if first else "", out.get("detail"))
        return {"ok": True, **out}
    except Exception as e:  # noqa: BLE001
        store.mark(job, False, error=str(e))
        logger.warning("scoreboard sync %s failed: %s", job, e)
        return {"ok": False, "error": str(e)}
    finally:
        try:
            from . import build
            build.invalidate()
        except Exception:  # noqa: BLE001
            pass


def _due(job: str, state: dict) -> bool:
    s = state.get(job) or {}
    last = s.get("last_try")
    if job == "meta_final":
        # once a day, after 3am Sydney (Meta has closed yesterday by then)
        now = now_sydney()
        if now.hour < 3:
            return False
        if last:
            lt = dt.datetime.fromisoformat(str(last)).astimezone(SYDNEY_TZ)
            if lt.date() == now.date() and lt.hour >= 3 and s.get("last_ok") == last:
                return False
            if lt > now - dt.timedelta(minutes=30):
                return False
        return True
    if not last:
        return True
    lt = dt.datetime.fromisoformat(str(last))
    if lt.tzinfo is None:
        lt = lt.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - lt).total_seconds() >= CADENCE_S[job]


def tick() -> list[str]:
    ran = []
    state = store.sync_state()
    for job in JOBS:
        if _due(job, state) and store.claim(job, min(CADENCE_S[job], 3600) - 30):
            run(job)
            ran.append(job)
    return ran


_started = False
_start_lock = threading.Lock()


def start_loop() -> bool:
    global _started
    with _start_lock:
        if _started or not store.use_db():
            return False
        _started = True

    def _loop():
        time.sleep(45)
        while True:
            try:
                tick()
            except Exception as e:  # noqa: BLE001
                logger.warning("scoreboard tick failed: %s", e)
            time.sleep(60)

    threading.Thread(target=_loop, daemon=True, name="scoreboard-sync").start()
    return True
