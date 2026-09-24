"""pl_reconcile.py — THREE REVENUE STORIES, RECONCILED NIGHTLY (#165).

For each recent calendar month: Xero recognised revenue vs Stripe receipts
(ex-GST) vs contract-based recognised — with the deltas NAMED, because
August proved what the gaps are made of: invoices raised for bank-transfer
clients (some unpaid — that's the AR), Stripe payout-lag at the month
boundary, and one-offs that contracts don't carry.

Cost side: Xero's mapped ladder lines vs the outflow bands' month totals.
A delta beyond tolerance is LOUD: a finding with a Piolo package line for
the Xero-side fix (Xero stays read-only — the agent never writes it).
"""
from __future__ import annotations

import logging

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

K_STATE = "pl:reconciliation"
K_FEED = "feed:extra:pl_reconcile"      # one publisher, replaced wholesale
TOLERANCE = 500.0                        # dollars a month may drift unnamed


def run(months: int = 3) -> dict:
    import pl_engine
    out = {"at": now_sydney().isoformat(), "months": [], "findings": []}
    for mkey in pl_engine.months_back(months):
        row = {"month": mkey}
        rec = pl_engine.recognised(mkey)
        ca = pl_engine.cash(mkey)
        cr = pl_engine.contract_revenue(mkey)
        row["xero_recognised"] = rec.get("revenue") if rec.get("ok") else None
        row["stripe_ex_gst"] = ca.get("receipts_ex_gst")
        row["contract_based"] = cr.get("total")
        if row["xero_recognised"] is None:
            row["note"] = rec.get("reason")
            out["months"].append(row)
            continue
        deltas = []
        if row["stripe_ex_gst"] is not None:
            d = round(row["xero_recognised"] - row["stripe_ex_gst"], 2)
            deltas.append({"between": "Xero − Stripe", "amount": d,
                           "why": ("invoiced revenue (bank-transfer clients, "
                                   "incl. AR raised but unpaid) + payout-lag "
                                   "coding at the month boundary")})
        d2 = round(row["xero_recognised"] - row["contract_based"], 2)
        deltas.append({"between": "Xero − contracts", "amount": d2,
                       "why": ("one-off invoices and setup fees contracts "
                               "don't carry; AR raised in-month; PIF booked "
                               "whole where the contract spreads it")})
        row["deltas"] = deltas
        # cost side: mapped ladder costs vs the outflow band total
        bands = (kv_store.get("outflow:month_bands") or {}).get(mkey) or {}
        mapped = round((rec.get("delivery") or 0) + (rec.get("acquisition") or 0)
                       + (rec.get("overhead") or 0), 2)
        band_opex = bands.get("opex")
        if band_opex is not None:
            cd = round(mapped - band_opex, 2)
            row["cost_delta"] = {"mapped_ladder": mapped, "outflow_band": band_opex,
                                 "delta": cd}
            if abs(cd) > TOLERANCE:
                out["findings"].append({
                    "month": mkey, "kind": "cost",
                    "title": f"{mkey}: ladder costs vs outflow band differ by ${cd:,.0f}",
                    "detail": (f"mapped delivery+acquisition+overhead ${mapped:,.0f} "
                               f"vs band ${band_opex:,.0f} — check contra-revenue "
                               f"and excluded lines in the mapping")})
        # unrecognised Stripe sales: receipts well ABOVE what the books saw
        if (row["stripe_ex_gst"] is not None
                and row["stripe_ex_gst"] - row["xero_recognised"] > TOLERANCE):
            out["findings"].append({
                "month": mkey, "kind": "revenue",
                "title": (f"{mkey}: ${row['stripe_ex_gst'] - row['xero_recognised']:,.0f} "
                          f"of Stripe receipts not visible in Xero revenue"),
                "detail": ("payouts may be sitting unreconciled or coded to a "
                           "clearing account — a Xero-side fix (the agent "
                           "never writes Xero)")})
        out["months"].append(row)

    items = []
    for f in out["findings"][:8]:
        items.append({"severity": "S2", "category": "data_quality",
                      "title": f["title"][:160],
                      "detail": f["detail"][:200],
                      "action": ("fix at source in Xero (read-only law: the "
                                 "agent never writes it) — this item retires "
                                 "when the next nightly pass reconciles")})
    kv_store.put(K_FEED, items)
    kv_store.put(K_STATE, out)
    return out


def latest() -> dict:
    return kv_store.get(K_STATE) or {"months": [], "findings": []}
