"""tile_drawers.py — EVERY HEADLINE SHOWS ITS WORK (#150).

The law: every finance-dashboard headline tile has a drawer —
  DEFINITION (one sentence) · FORMULA · COMPONENTS (each with source + ids)
  · CLOCK · RECONCILIATION (the external truth + a delta that is $0.00 or
  explained). No tile renders a bare ambiguous word ("committed", "net",
  "cash", "revenue", "spend", "ROAS") without its qualifier — test-pinned.

THE THREE NETS (Part A2 — the "$1.6k" answer), labelled, never blended:
  · Cash net MTD (bank basis)   — receipts − banded cash outflows, anchored
    to the bank balance where history allows (delta explained otherwise).
  · Operating net MTD           — receipts − OpEx band; tax/statutory and
    personal shown BESIDE, never inside (the outflow-truth rule).
  · Expected month-end          — receipts to date + AR still due this month
    − burn remaining (a labelled projection, never cash).

One engine everywhere: this module COMPOSES existing engines (outflow
bands, cash_truth receipts, forward projection, cross-tab recon, unit
economics, receivables) — it computes nothing those engines don't already
own, and every figure carries ids.
"""

from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)


def _month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _receipts_mtd() -> dict:
    import finance_analysis
    t = today_sydney()
    return finance_analysis._receipts_in_window(_month_start(t), t)


def _bank_anchor() -> dict:
    """This month's opening bank balance: from snapshot history where it
    exists, else anchored the first day this engine ran (labelled)."""
    t = today_sydney()
    key = f"fin:bank_anchor:{str(t)[:7]}"
    anchor = kv_store.get(key)
    if anchor:
        return anchor
    # try snapshot history (survives only where the volume does — honest)
    try:
        import history_store
        for e in history_store.series("cash_position.cash_in_bank", 40):
            if str(e.get("date") or "")[:7] == str(t)[:7] and e.get("value") is not None:
                anchor = {"date": e["date"], "balance": e["value"],
                          "basis": "snapshot history"}
                break
    except Exception:
        pass
    if not anchor:
        try:
            from snapshot import load_persisted
            bal = ((load_persisted() or {}).get("cash_position") or {}).get("cash_in_bank")
            if bal is not None:
                anchor = {"date": str(t), "balance": bal,
                          "basis": f"anchored {t} (history starts here — "
                                   f"bank-basis net accrues from today)"}
        except Exception:
            pass
    if anchor:
        kv_store.put(key, anchor)
    return anchor or {}


def three_nets() -> dict:
    """The Part-A2 decomposition — three honest nets, components summing,
    tax banded OUT, each clock labelled."""
    t = today_sydney()
    receipts = _receipts_mtd()
    # banded outflows: the outflow-truth classifier over THIS month's P&L
    bands = None
    try:
        import outflow_bands
        mb = outflow_bands.monthly_bands(2)
        rows = mb.get("months") or mb.get("rows") or []
        cur = next((r for r in rows if str(r.get("month") or "")[:7] == str(t)[:7]
                    or str(t.strftime("%B")) in str(r.get("month") or "")), None)
        if cur:
            bands = {k: cur.get(k) for k in ("opex", "tax_statutory",
                                             "personal", "flagged",
                                             "blended_total") if k in cur}
    except Exception as e:
        logger.info("outflow bands unavailable for nets: %s", e)
    burn = None
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        burn = ((snap.get("monthly_burn") or {}).get("total_recurring_burn"))
        bank_now = ((snap.get("cash_position") or {}).get("cash_in_bank"))
    except Exception:
        bank_now = None
    anchor = _bank_anchor()
    rec_total = receipts.get("total") if receipts.get("available") else None

    # 1 · cash net MTD (bank basis)
    bank_net = None
    bank_note = None
    if bank_now is not None and anchor.get("balance") is not None:
        bank_net = round(bank_now - anchor["balance"], 2)
        bank_note = (f"CommBank balance {anchor['date']} "
                     f"${anchor['balance']:,.2f} → today ${bank_now:,.2f} "
                     f"({anchor.get('basis')})")
    # 2 · operating net MTD (receipts − OpEx band; tax beside)
    frac = t.day / 30.44
    opex_mtd = (round((bands or {}).get("opex", 0) * 1.0, 2)
                if bands and (bands.get("opex") is not None) else
                round((burn or 0) * frac, 2) if burn else None)
    opex_basis = ("this month's OpEx band (account-code classifier)"
                  if bands and bands.get("opex") is not None else
                  f"recurring burn ${burn:,.0f}/mo × {frac:.2f} months elapsed"
                  if burn else "unavailable")
    op_net = (round(rec_total - opex_mtd, 2)
              if rec_total is not None and opex_mtd is not None else None)
    # 3 · expected month-end
    exp = {"available": False}
    try:
        import receivables
        exp = receivables.expected_month_end()
    except Exception:
        pass
    burn_remaining = round((burn or 0) * max((30.44 - t.day) / 30.44, 0), 2) if burn else None
    month_end = None
    if op_net is not None and exp.get("available") and burn_remaining is not None:
        month_end = round(op_net + exp["outstanding_expected_this_month"]
                          - burn_remaining, 2)
    return {
        "as_of": str(t),
        "cash_net_mtd_bank": {
            "label": "Cash net MTD (bank basis)",
            "value": bank_net,
            "clock": "MTD · bank-balance delta",
            "components": [
                {"label": "Stripe receipts MTD (net of refunds)",
                 "value": rec_total, "source": receipts.get("source")},
                {"label": "bank balance movement", "value": bank_net,
                 "source": bank_note or "bank-balance history unavailable — "
                                        "anchor starts today (labelled)"}],
            "reconciliation": {
                "external": "CommBank balance via Xero Bank Summary",
                "delta_note": ("receipts − bank movement = non-Stripe flows "
                               "(outflows, transfers, direct deposits) — "
                               "itemised bank transactions need a Xero scope "
                               "the token doesn't hold (registered "
                               "dependency)")},
        },
        "operating_net_mtd": {
            "label": "Operating net MTD (receipts − OpEx; tax banded beside)",
            "value": op_net,
            "clock": "MTD · flow",
            "components": [
                {"label": "Stripe receipts MTD", "value": rec_total,
                 "source": receipts.get("source")},
                {"label": "− operating outflows", "value": opex_mtd,
                 "source": opex_basis},
                {"label": "beside (NEVER inside): tax/statutory band",
                 "value": (bands or {}).get("tax_statutory"),
                 "source": "outflow-truth classifier — settling liabilities, "
                           "not operating cost"},
                {"label": "beside: personal band",
                 "value": (bands or {}).get("personal"),
                 "source": "outflow-truth classifier"}],
        },
        "expected_month_end": {
            "label": "Expected month-end (projection — never cash)",
            "value": month_end,
            "clock": "month-end · labelled projection",
            "components": [
                {"label": "operating net so far", "value": op_net,
                 "source": "above"},
                {"label": "+ AR still due this month",
                 "value": exp.get("outstanding_expected_this_month"),
                 "source": "receivables engine (schedule vs receipts)"},
                {"label": "− burn remaining this month", "value": burn_remaining,
                 "source": "recurring burn × month fraction remaining"}],
        },
        "law": "three nets, labelled, never blended; a tax lump can never "
               "hide inside any of them (outflow-truth #banding)",
    }


# ── the drawer registry ─────────────────────────────────────────────────────

def _drawer_committed_mrr() -> dict:
    import finance_tabs
    from snapshot import load_persisted
    snap = load_persisted() or {}
    ch = snap.get("client_health") or {}
    clients = ch.get("clients") or []
    ledger = {}
    try:
        ledger = finance_tabs.sheet_renewals_for_projection() or {}
    except Exception:
        pass
    import re as _re

    def _nn(s):
        return _re.sub(r"[^a-z0-9]", "", (s or "").lower())

    comps = []
    for c in clients:
        prov = "Health-gid tab row"
        if (c.get("declared") or {}).get("kind"):
            prov = f"declared {c['declared']['kind']} ({c['declared'].get('chip')})"
        elif _nn(c.get("name")) in ledger:
            prov = ledger[_nn(c.get("name"))]["provenance"]
        comps.append({"label": c.get("name"), "value": c.get("current_mrr"),
                      "source": prov})
    recon = None
    try:
        recon = finance_tabs.cross_tab_recon()
    except Exception as e:
        recon = {"error": str(e)[:100]}
    total = ch.get("current_mrr")
    comp_sum = round(sum(c["value"] or 0 for c in comps), 2)
    return {
        "tile": "committed_mrr",
        "definition": "Committed MRR (REVENUE): the monthly recurring "
                      "revenue clients are contracted to pay us — never a "
                      "cost.",
        "formula": "Σ active clients' current-month MRR (Health-gid tab, "
                   "status-filtered, known-churned excluded, declarations + "
                   "sheet renewal ledger applied)",
        "clock": "point-in-time (current month)",
        "value": total,
        "components": comps,
        "invariant": {"ok": total is not None and abs((total or 0) - comp_sum) < 0.01,
                      "tile": total, "component_sum": comp_sum},
        "reconciliation": {
            "external": "cross-tab MRR truths (ACTUAL / RECOGNIZED / footer)",
            "table": (recon or {}).get("sums"),
            "deltas_surfaced": len((recon or {}).get("deltas") or []),
            "note": "deltas stay surfaced until source-fixed (Piolo register)"},
    }


def _drawer_spend() -> dict:
    import meta_spend
    t = today_sydney()
    sp = meta_spend.spend_in_range(str(_month_start(t)), str(t)) or {}
    return {
        "tile": "meta_spend_mtd",
        "definition": "Meta ad spend, September MTD — GROSS ad spend, "
                      "archive-authoritative, intraday days provisional.",
        "formula": "Σ per-day archived Meta account spend in window "
                   "(+live fetch for missing in-window days)",
        "clock": "MTD · flow · intraday provisional",
        "value": sp.get("spend"),
        "components": [{"label": f"days covered", "value": sp.get("days_covered"),
                        "source": sp.get("source")}],
        "reconciliation": {"external": "Meta Marketing API Insights "
                                       "(read-only)",
                           "delta_note": "nightly cent-exact archive check "
                                         "(ground-truth sweep class)"},
        "degraded": sp.get("degraded"),
    }


def _drawer_cash_collected() -> dict:
    rec = _receipts_mtd()
    from snapshot import load_persisted
    snap = load_persisted() or {}
    tracker_cash = (snap.get("sheets") or {}).get("cash_collected")
    return {
        "tile": "cash_collected",
        "definition": "Two DIFFERENT cash figures exist — labelled apart: "
                      "Stripe receipts (bank truth) vs tracker cash cells "
                      "(the team's logging).",
        "formula": "receipts = Σ succeeded Stripe charges (net of refunds), "
                   "receipt-dated · tracker = Σ 'Cash Collected' cells",
        "clock": "MTD receipts · tracker 30d window",
        "value": rec.get("total"),
        "components": [
            {"label": "Stripe receipts MTD (net)", "value": rec.get("total"),
             "source": rec.get("source")},
            {"label": "tracker cash cells (30d, team-logged)",
             "value": tracker_cash,
             "source": "Lead-to-Cash tracker 'Cash Collected' column — lags "
                       "Stripe (the 7 cash-needs-logging deals are the gap)"}],
        "reconciliation": {"external": "Stripe (bank truth)",
                           "delta_note": "tracker-vs-Stripe gaps are the "
                                         "cash-needs-logging Piolo queue"},
    }


def _drawer_ar() -> dict:
    import receivables
    ar = receivables.build_ar()
    if not ar.get("ok"):
        return {"tile": "ar_outstanding", "value": None,
                "degraded": ar.get("reason")}
    return {
        "tile": "ar_outstanding",
        "definition": "Accounts receivable: expected payments not yet "
                      "received — NEVER counted as cash (R-CASH).",
        "formula": "Σ per-client (expected-to-date − received-to-date), "
                   "expected from the RECOGNIZED grid + renewal ledger, "
                   "received from Stripe receipts",
        "clock": f"trailing {ar['window_months']} months incl. current",
        "value": ar["total_outstanding"],
        "components": [{"label": r["client"], "value": r["outstanding"],
                        "source": f"{r['status']}"
                                  + (f" · {r['days_overdue']}d overdue"
                                     if r["days_overdue"] else "")}
                       for r in ar["rows"] if r["outstanding"] > 0.01][:20],
        "invariant": {"ok": abs(sum(ar["aging"].values())
                                - ar["total_outstanding"]) < 0.01,
                      "aging_buckets": ar["aging"]},
        "reconciliation": {"external": "Xero Balance-Sheet Accounts "
                                       "Receivable line",
                           "anchor": ar.get("xero_ar_anchor"),
                           "delta": ar.get("anchor_delta"),
                           "explained": ar.get("anchor_note")},
    }


def _drawer_forecast_net() -> dict:
    nets = three_nets()
    try:
        import forecasting_engine
        from snapshot import load_persisted
        cf = forecasting_engine.cash_flow_13wk(load_persisted() or {})
        fc_net = round(cf.get("net_weekly", 0) * 52 / 12, 2)
        inputs = {k: cf.get(k) for k in ("net_weekly", "starting_cash")
                  if k in cf}
    except Exception as e:
        fc_net, inputs = None, {"error": str(e)[:80]}
    return {
        "tile": "forecast_net",
        "definition": "Forecast net (PROJECTION): the 13-week model's "
                      "monthly net — an assumption-driven curve, not this "
                      "month's actual.",
        "formula": "(weekly inflow + weekly new-client cash − weekly "
                   "outflow) × 52/12 — forecasting_engine assumptions",
        "clock": "projection · labelled",
        "value": fc_net,
        "components": [{"label": k, "value": v, "source": "forecasting_engine "
                        "assumptions (voice-adjustable)"}
                       for k, v in inputs.items()],
        "reconciliation": {
            "external": "the three ACTUAL nets (this drawer's sibling)",
            "three_nets": {k: v.get("value") for k, v in nets.items()
                           if isinstance(v, dict)},
            "delta_note": "a projection never reconciles to the cent — the "
                          "three actual nets are the truth it must track"},
    }


_REGISTRY = {
    "committed_mrr": _drawer_committed_mrr,
    "meta_spend_mtd": _drawer_spend,
    "cash_collected": _drawer_cash_collected,
    "ar_outstanding": _drawer_ar,
    "forecast_net": _drawer_forecast_net,
    "three_nets": three_nets,
}


def drawer(tile: str) -> dict:
    fn = _REGISTRY.get(tile)
    if not fn:
        return {"error": f"unknown tile '{tile}'",
                "known": sorted(_REGISTRY)}
    try:
        return fn()
    except Exception as e:
        logger.warning("drawer %s failed: %s", tile, e)
        return {"tile": tile, "error": str(e)[:150],
                "note": "the drawer failed honestly — the tile's number "
                        "should not be trusted until this resolves"}


# ── EDITH drill: "what's my real net this month" ────────────────────────────

import re as _re2

_NET_RE = _re2.compile(r"(real|actual|my) net|net this month|net mtd", _re2.I)
_COMMITTED_RE = _re2.compile(r"what('s| is) committed|committed mrr|"
                             r"committed to (a )?monthly", _re2.I)


def handle_net_command(text: str) -> tuple[str | None, bool]:
    t = text or ""
    try:
        if _COMMITTED_RE.search(t):
            d = _drawer_committed_mrr()
            return (f"Committed MRR is REVENUE, never a cost: "
                    f"${d['value']:,.2f}/mo across {len(d['components'])} "
                    f"active clients — the monthly amount clients are "
                    f"contracted to pay us (Health tab + declarations + the "
                    f"sheet renewal ledger). The drawer on the tile lists "
                    f"all rows with provenance; cross-tab deltas "
                    f"({d['reconciliation']['deltas_surfaced']}) are "
                    f"surfaced until Piolo fixes them at source.", True)
        if _NET_RE.search(t):
            n = three_nets()
            b = n["cash_net_mtd_bank"]
            o = n["operating_net_mtd"]
            e = n["expected_month_end"]

            def f(v):
                return f"${v:,.0f}" if v is not None else "unavailable"
            return (f"Three nets, labelled, never blended — "
                    f"CASH NET MTD (bank basis): {f(b['value'])} · "
                    f"OPERATING NET MTD (receipts − OpEx, tax banded "
                    f"BESIDE): {f(o['value'])} (receipts "
                    f"{f(o['components'][0]['value'])} − operating "
                    f"{f(o['components'][1]['value'])}; tax/statutory "
                    f"{f(o['components'][2]['value'])} beside, never "
                    f"inside) · EXPECTED MONTH-END (projection, never "
                    f"cash): {f(e['value'])} incl. "
                    f"{f(e['components'][1]['value'])} AR still due. "
                    f"Every component and its source is in the tile "
                    f"drawer.", True)
    except Exception as ex:
        logger.info("net drill failed: %s", ex)
    return None, False
