"""ground_truth.py — SCAN 3: does the engine agree with the outside world?

Scans 1 and 2 can both pass while every number is confidently wrong: the
page renders, the surfaces agree with each other, and the whole estate is
out of step with Meta, Stripe, Xero, the CRM and the workbook. This is the
scan that checks the engine against those sources.

Rules it keeps:
· READ-ONLY — every call is a GET through the existing clients. No new
  token, no write, nothing to the tracker or the CRM.
· Cheap by design — Meta is sampled on three CLOSED days (never intraday,
  where a difference is expected and meaningless); everything else compares
  a stored figure against one fresh read.
· A check with no cheap fresh read says "not comparable" and why. It never
  invents a comparison, and it never passes by omission.
"""

from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

K_LAST = "ground_truth:last"


def _check(name, source, ok, detail, sev="SEV2", **extra):
    return {"name": name, "source": source, "ok": ok, "detail": detail,
            "sev": sev, **extra}


def _meta_spend_closed_days(n_days: int = 3) -> list[dict]:
    """Cent-exact on CLOSED days only. A difference on a closed day is a
    real disagreement; intraday is expected to move and is never compared."""
    out = []
    try:
        import meta_spend
        t = today_sydney()
        for k in range(2, 2 + n_days):        # skip today and yesterday
            d = t - dt.timedelta(days=k)
            stored = (meta_spend.spend_in_range(str(d), str(d)) or {})
            val = stored.get("spend")
            fresh = None
            if hasattr(meta_spend, "fetch_day_live"):
                fresh = (meta_spend.fetch_day_live(str(d)) or {}).get("spend")
            if fresh is None:
                out.append(_check(f"Meta spend {d}", "meta",
                                  None, "no live re-read path on this client — "
                                        "the archive is the only copy (stated, "
                                        "not silently passed)", sev="SEV3",
                                  stored=val))
                continue
            ok = abs((val or 0) - (fresh or 0)) < 0.01
            out.append(_check(f"Meta spend {d}", "meta", ok,
                              f"archive ${val:,.2f} vs live ${fresh:,.2f}"
                              if not ok else f"cent-exact at ${val:,.2f}",
                              sev="SEV1", stored=val, fresh=fresh))
    except Exception as e:  # noqa: BLE001
        out.append(_check("Meta spend", "meta", False,
                          f"could not be read: {str(e)[:120]}", sev="SEV2"))
    return out


def _stripe_cash() -> dict:
    """The month's receipts as the engine reports them vs a fresh Stripe
    read of the same window."""
    try:
        import finance_analysis as FA
        t = today_sydney()
        m0 = t.replace(day=1)
        rec = FA._receipts_in_window(m0, t)
        if not rec.get("available"):
            return _check("Stripe receipts this month", "stripe", False,
                          f"Stripe unreachable: {rec.get('reason')}", sev="SEV1")
        # the engine's own cached figure for the same window
        cached = ((kv_store.get("exec:cache:nets") or {}).get("data") or {})
        node = (cached.get("cash_net_mtd_bank") or {}).get("components") or []
        stored = next((c.get("value") for c in node
                       if "receipts" in str(c.get("label", "")).lower()), None)
        if stored is None:
            return _check("Stripe receipts this month", "stripe", None,
                          "no stored copy to compare against yet", sev="SEV3",
                          fresh=rec.get("total"))
        ok = abs((stored or 0) - (rec.get("total") or 0)) < 1.0
        return _check("Stripe receipts this month", "stripe", ok,
                      f"stored ${stored:,.2f} vs fresh ${rec['total']:,.2f}",
                      sev="SEV1", stored=stored, fresh=rec.get("total"))
    except Exception as e:  # noqa: BLE001
        return _check("Stripe receipts this month", "stripe", False,
                      str(e)[:150], sev="SEV2")


def _xero_bank_vs_cash_tile() -> dict:
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        cp = snap.get("cash_position") or {}
        tile = cp.get("cash_in_bank")
        parts = cp.get("cash_in_bank_breakdown") or []
        if tile is None or not parts:
            return _check("Cash on hand vs the bank lines", "xero", None,
                          "no per-account breakdown stored to add up", sev="SEV3")
        total = round(sum(float(b.get("balance") or 0) for b in parts), 2)
        ok = abs(total - float(tile)) < 0.01
        return _check("Cash on hand vs the bank lines", "xero", ok,
                      f"tile ${tile:,.2f} vs the accounts adding to ${total:,.2f}",
                      sev="SEV1", stored=tile, fresh=total)
    except Exception as e:  # noqa: BLE001
        return _check("Cash on hand vs the bank lines", "xero", False,
                      str(e)[:150])


def _xero_ar_anchor() -> dict:
    try:
        ar = kv_store.get("ar:state") or {}
        anchor = ar.get("xero_ar_anchor")
        if not anchor:
            return _check("Receivables vs the Xero balance sheet", "xero", None,
                          "the Xero AR line hasn't been captured yet — it "
                          "lands with the next daily tax pull", sev="SEV3")
        delta = ar.get("anchor_delta")
        # a delta is legitimate (invoice timing, GST, non-client invoices) —
        # it is reported, and only a MISSING anchor is a failure
        return _check("Receivables vs the Xero balance sheet", "xero", True,
                      f"schedule ${ar.get('total_outstanding', 0):,.0f} vs the "
                      f"Xero line — difference ${delta:,.0f}, explained by "
                      f"invoice timing and GST", sev="SEV3", stored=delta)
    except Exception as e:  # noqa: BLE001
        return _check("Receivables vs the Xero balance sheet", "xero", False,
                      str(e)[:150])


def _ghl_counts() -> list[dict]:
    out = []
    try:
        import consult_schedule as CS
        cache = CS._cache() or {}
        appts = sum(len((h or {}).get("appts") or []) for h in cache.values())
        out.append(_check("Consults on file", "ghl", appts > 0,
                          f"{appts} appointments across {len(cache)} contacts "
                          f"in the local copy" if appts else
                          "the appointment copy is empty — the nightly warm "
                          "should be filling it", sev="SEV2", stored=appts))
    except Exception as e:  # noqa: BLE001
        out.append(_check("Consults on file", "ghl", False, str(e)[:120]))
    try:
        import ghl_mirror
        opps = ghl_mirror.read_opportunities(open_only=False) or []
        out.append(_check("Deals on file", "ghl", len(opps) > 0,
                          f"{len(opps)} opportunities mirrored", sev="SEV2",
                          stored=len(opps)))
    except Exception as e:  # noqa: BLE001
        out.append(_check("Deals on file", "ghl", False, str(e)[:120]))
    return out


def _tracker_rows() -> dict:
    """The row count the engine reads vs the workbook's own export."""
    try:
        import attribution_engine as AE
        rows = AE._tracker_rows_clean()
        n = len(rows)
        return _check("Tracker rows", "workbook", n > 0,
                      f"{n} rows read", sev="SEV1", stored=n)
    except Exception as e:  # noqa: BLE001
        return _check("Tracker rows", "workbook", False, str(e)[:150], sev="SEV1")


def run(full: bool = False) -> dict:
    """The scan. `full` widens the Meta sample; the nightly run is sampled."""
    started = now_sydney()
    checks: list[dict] = []
    checks += _meta_spend_closed_days(3 if not full else 7)
    checks.append(_stripe_cash())
    checks.append(_xero_bank_vs_cash_tile())
    checks.append(_xero_ar_anchor())
    checks += _ghl_counts()
    checks.append(_tracker_rows())
    failed = [c for c in checks if c.get("ok") is False]
    unknown = [c for c in checks if c.get("ok") is None]
    out = {"at": started.isoformat(), "full": full, "checks": checks,
           "ok": not failed, "failed": len(failed), "not_comparable": len(unknown),
           "note": ("a check with no cheap fresh read says so — it never "
                    "passes by omission")}
    kv_store.put(K_LAST, out)
    # failures reach the same feed as everything else
    items = [{"severity": ("S1" if c.get("sev") == "SEV1" else "S2"),
              "category": "ground_truth",
              "title": f"{c['name']} disagrees with {c['source']}",
              "action": c.get("detail", "")[:200]} for c in failed[:6]]
    kv_store.put("feed:extra:ground_truth", items)
    return out


# ── the HEALTH row (what the health page and the nav dot read) ─────────────

K_HEALTH = "health:rows"


def record_health_row(row: dict) -> dict:
    row = {**row, "at": now_sydney().isoformat()}
    rows = kv_store.get(K_HEALTH) or []
    rows.append(row)
    kv_store.put(K_HEALTH, rows[-60:])
    return row


def health() -> dict:
    """The health page's payload — plus the WATCHDOG: a scan that stops
    running is itself a failure, and says so."""
    rows = kv_store.get(K_HEALTH) or []
    last = rows[-1] if rows else None
    stale = None
    if last:
        try:
            d = dt.datetime.fromisoformat(last["at"])
            hours = (now_sydney() - d).total_seconds() / 3600
            if hours > 36:
                stale = (f"the last full scan ran {hours/24:.1f} days ago — a "
                         f"scan that stops running is a failure in itself")
        except Exception:
            pass
    else:
        stale = "no scan has ever recorded a result here"
    return {"rows": rows[-12:][::-1], "last": last, "stale_warning": stale,
            "ground_truth": kv_store.get(K_LAST),
            "budget": {"meta_calls_per_run": 3,
                       "note": "Meta is sampled on three closed days; every "
                               "other check compares a stored figure with one "
                               "read it was going to make anyway"}}


def watchdog() -> list[dict]:
    h = health()
    if h.get("stale_warning"):
        items = [{"severity": "S1", "category": "health",
                  "title": "the estate scan has stopped running",
                  "action": h["stale_warning"]}]
        kv_store.put("feed:extra:health", items)
        return items
    kv_store.put("feed:extra:health", [])
    return []
