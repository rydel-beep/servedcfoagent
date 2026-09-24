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
    # DAY-LEVEL history, earliest day of THIS month.
    #
    # This used to read history_store.series(field, 40) — the last 40
    # ENTRIES. Snapshots append about every two hours, so 40 entries reach
    # back roughly three days: on the day the anchor was first computed, the
    # earliest September reading it could see was the 15th, and that got
    # cached as "the month's opening balance". "Cash net MTD (bank basis)"
    # then measured six days while clocked as the month ($2,869.53 against a
    # true $1,118.84). Found by the Phase 0 real-seat audit.
    #
    # A cached anchor is KEPT only while it is still the earliest day we hold
    # for the month; when older history arrives, it is re-anchored.
    try:
        import trend
        pts = trend.daily_series("cash_position.cash_in_bank", 62)
        month_pts = [p for p in pts if str(p["date"])[:7] == str(t)[:7]]
        if month_pts:
            earliest = month_pts[0]
            if not anchor or str(anchor.get("date") or "9999") > earliest["date"]:
                anchor = {"date": earliest["date"], "balance": earliest["value"],
                          "basis": "snapshot history (earliest day this month)"}
                kv_store.put(key, anchor)
            return anchor
    except Exception as e:  # noqa: BLE001
        logger.info("bank anchor: day-level history unavailable: %s", e)
    if anchor:
        return anchor
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


def _drawer_cash_on_hand() -> dict:
    """Per-account Xero bank balances behind the exec-top Cash-on-hand tile
    (dashboard-hardening wave: server-rendered headline, drawer = the work)."""
    from snapshot import load_persisted
    snap = load_persisted() or {}
    cp = snap.get("cash_position") or {}
    breakdown = cp.get("cash_in_bank_breakdown") or []
    comps = [{"label": b.get("name") or b.get("marker"),
              "value": b.get("balance"),
              "source": f"Xero Bank Summary closing balance · as of {cp.get('cash_as_of')}"}
             for b in breakdown]
    total = cp.get("cash_in_bank")
    comp_sum = round(sum(c["value"] or 0 for c in comps), 2)
    return {
        "tile": "cash_on_hand",
        "definition": "Cash on hand: the closing balances of the CommBank "
                      "transaction + online saver + BAS/tax accounts from "
                      "Xero's Bank Summary. A point-in-time BALANCE — never "
                      "summed with period flows.",
        "formula": "Σ per-account Xero closing balances (Amex excluded — "
                   "it's a liability)",
        "clock": f"point-in-time · as of {cp.get('cash_as_of') or 'unknown'} "
                 f"· snapshot {snap.get('generated_at', '')[:16]}",
        "value": total,
        "components": comps,
        "invariant": {"ok": total is not None and comps
                            and abs((total or 0) - comp_sum) < 0.01,
                      "tile": total, "component_sum": comp_sum},
        "reconciliation": {
            "external": "CommBank via Xero bank feeds",
            "delta_note": "Xero bank feeds lag the bank by up to a day — "
                          "the honest limit, stated on the tile",
            "stripe_beside": {
                "available": cp.get("stripe_available"),
                "incoming_settling": cp.get("stripe_incoming"),
                "in_transit_to_bank": cp.get("stripe_in_transit_to_bank"),
                "note": "Stripe money states BESIDE bank cash, never inside"}},
        "degraded": ("live Xero read failed — LAST-KNOWN fallback shown"
                     if "fallback" in (cp.get("cash_in_bank_note") or "").lower()
                     else None),
    }


def _drawer_burn_ex_tax() -> dict:
    """COMPASS 1.2: the projection page's burn line — OpEx ex-tax ex-
    acquisition (measured band), tax accrual BESIDE, net burn, runway."""
    import kv_store as _kv
    d = (_kv.get("compass:defaults") or {}).get("items") or {}
    opex = (d.get("opex_monthly_ex_tax") or {})
    from snapshot import load_persisted
    snap = load_persisted() or {}
    cp = snap.get("cash_position") or {}
    mrr = (snap.get("client_health") or {}).get("current_mrr")
    net_burn = round((opex.get("value") or 0) - (mrr or 0), 2) \
        if opex.get("value") is not None else None
    cash_ex = round((cp.get("cash_in_bank") or 0) - (cp.get("tax_reserved") or 0), 2)
    runway = (round(cash_ex / -net_burn, 1)
              if net_burn is not None and net_burn < 0 else None)
    return {
        "tile": "burn_ex_tax",
        "definition": "Monthly burn = OpEx ex-tax, ex-acquisition (spend + "
                      "commissions modelled separately). The tax accrual is "
                      "BESIDE, never inside (outflow-truth law).",
        "formula": "outflow-truth OpEx band − advertising − commissions "
                   "(both explicit elsewhere); net burn = OpEx − committed "
                   "MRR recognised; runway = cash ex tax set-aside ÷ net burn",
        "clock": "trailing full months · measured",
        "value": opex.get("value"),
        "components": [
            {"label": "OpEx ex-tax ex-acquisition", "value": opex.get("value"),
             "source": opex.get("provenance")},
            {"label": "committed MRR (revenue) recognised", "value": mrr,
             "source": "Health-tab committed layer"},
            {"label": "net burn (negative = the book covers OpEx)",
             "value": net_burn, "source": "derived above"},
            {"label": "cash ex tax set-aside", "value": cash_ex,
             "source": "Xero bank balances − set-aside"}],
        "reconciliation": {
            "external": "BAS set-aside logic (tax accrual, quarterly settle)",
            "delta_note": "tax never appears inside any burn figure — a BAS "
                          "accrual month leaves OpEx unchanged (drilled)"},
    }


def _drawer_booked_calls() -> dict:
    """Pulse tile door: the consult roster for the next 7 days (read-only)."""
    import compass_engine
    bc = compass_engine.booked_calls_next_7d()
    return {
        "tile": "booked_calls",
        "definition": "Consults scheduled in the next 7 days — GHL kept "
                      "appointments (cancelled never counts). READ-ONLY.",
        "formula": "count of kept GHL appointments with startTime in "
                   "[now, now+7d] from the appointment cache",
        "clock": "next 7 days · point-in-time",
        "value": bc.get("count"),
        "components": [{"label": c.get("formatted") or c.get("when"),
                        "value": None,
                        "source": f"status: {c.get('status') or 'kept'}"}
                       for c in (bc.get("consults") or [])],
        "reconciliation": {"external": bc.get("source"),
                           "delta_note": "the roster page carries the same "
                                         "cache — one source"},
    }


def _drawer_net_margin() -> dict:
    """#166: both panels' math, the AR reconciliation, and the two labelled
    projections — everything the two headline numbers rest on."""
    import pl_engine
    d = (pl_engine.cached_summary() or {}).get("data") or {}
    cvc = d.get("contracted_vs_collected") or {}
    mg = cvc.get("contracted") or {}
    b = cvc.get("collected_mtd") or {}
    b30 = cvc.get("collected_30d") or {}
    gap = cvc.get("gap") or {}
    recon = cvc.get("ar_reconciliation") or {}
    proj = cvc.get("projections") or {}
    costs = cvc.get("same_cost_basis") or {}
    stamps = cvc.get("inputs_as_of") or {}
    comps = [
        {"label": "IF EVERYONE PAYS — contracted revenue "
                  f"({mg.get('window_words') or 'MTD'})",
         "value": mg.get("revenue"),
         "source": "active clients × MRR pro-rata + PIF spread (Health tab)"},
        {"label": "WHAT LANDED — collected revenue (same window)",
         "value": b.get("revenue"),
         "source": (b.get("collected") or {}).get("provenance")},
        {"label": "collected, last 30 days "
                  f"({(b30.get('window_words') or 'unavailable')})",
         "value": (b30 or {}).get("revenue"),
         "source": (b30 or {}).get("cost_note") or ""},
        {"label": "SAME costs on both panels — delivery",
         "value": costs.get("delivery"), "source": "management basis, normalised"},
        {"label": "… acquisition (rulebook commissions in)",
         "value": costs.get("acquisition"), "source": "management basis"},
        {"label": "… overhead", "value": costs.get("overhead"),
         "source": "management basis"},
        {"label": "collected net margin ON THE CONTRACTED denominator",
         "value": None,
         "source": "so the two panels compare on one denominator — see the "
                   "gap line for the dollars"},
    ]
    pa, pb = proj.get("optimistic") or {}, proj.get("realistic") or {}
    return {
        "tile": "net_margin",
        "definition": ("Two margins, one cost base: what the month earns if "
                       "every contracted dollar arrives, and what it has "
                       "earned on the money that actually landed. The gap "
                       "is the money you're owed."),
        "formula": ("net = revenue − refunds − delivery − acquisition − "
                    "overhead − 25% tax accrual; the ONLY difference between "
                    "the panels is which revenue goes in"),
        "clock": (f"contracted as of roster {str((stamps.get('contracted') or {}).get('roster'))[:16]} "
                  f"· collected as of Stripe {str((stamps.get('collected') or {}).get('stripe'))[:16]}"),
        "value": mg.get("net_margin_pct"),
        "components": comps,
        "gap": gap,
        "projections": {
            "optimistic": {**pa} if pa else None,
            "realistic": {**pb} if pb else None,
            "note": "every projection carries its assumption — optimistic "
                    "assumes full payment; realistic applies the trailing "
                    "collection pace"},
        "reconciliation": {
            "external": f"AR outstanding ${recon.get('ar_outstanding') or 0:,.0f}",
            "delta_note": recon.get("residual_note"),
            "top_unpaid": recon.get("top_unpaid"),
            "door": recon.get("door")},
        "baseline": f"FY26 net margin {cvc.get('fy26_baseline_net_pct')}%",
    }


_REGISTRY = {
    "net_margin": _drawer_net_margin,
    "cash_on_hand": _drawer_cash_on_hand,
    "burn_ex_tax": _drawer_burn_ex_tax,
    "booked_calls": _drawer_booked_calls,
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
