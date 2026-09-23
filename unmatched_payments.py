"""unmatched_payments.py — MONEY THAT LANDED AND ISN'T ATTACHED TO ANYONE.

Cash that has arrived but has no client against it is an anomaly, not a
background card. Koji's payment came in under the payer name "Sanatani
Rombola" and sat there: the money counted (R-CASH reads Stripe, so the bank
figure was right) while the CLIENT it belonged to had no close, no contract
value, and no line in the unit economics.

This module is the panel that makes that state impossible to miss, and the
one place a payer alias is confirmed:

  · SCAN       every succeeded charge in the window, through the ONE matcher
               (stripe_reconcile._match_payment). Identity resolves it —
               alias, exact email, exact name. A resemblance is a proposal.
  · PANEL      payer, amount, date, charge id, the best guess and what the
               guess is based on, for the home dashboard.
  · CONFIRM    the owner's one click: write the alias, journal it with who
               said so and which charge proved it, re-run the match, and
               invalidate the engine blocks so the numbers move now.

The alias store is the one that already exists (`stripe:payer_aliases`), so
a confirmation here is the same memory the reconciler and the gap ledger
read. Nothing is written to Stripe, the tracker or the CRM.
"""
from __future__ import annotations

import logging

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_STATE = "payments:unmatched"
K_JOURNAL = "payments:alias_journal"
LOOKBACK_DAYS = 60


def _charges(days: int) -> list[dict]:
    """Succeeded charges, newest first. Read-only Stripe key, the same reader
    cash_truth uses — never a second source of cash truth."""
    try:
        from cash_truth import _recent_charges
        return _recent_charges(days) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("unmatched: charge read failed: %s", e)
        return []


def _index():
    import stripe_reconcile as SR
    headers, rows = SR._fetch_tracker_rows()
    if not headers:
        return None, None
    return SR._build_identity_index(headers, rows), SR._roster_index()


def scan(days: int = LOOKBACK_DAYS) -> dict:
    """Every charge in the window, split into matched and not."""
    import stripe_reconcile as SR
    idx, roster = _index()
    out = {"at": now_sydney().isoformat(), "days": days,
           "rows": [], "matched": [], "total_unmatched": 0.0,
           "available": idx is not None}
    if idx is None:
        out["note"] = ("the tracker mirror could not be read, so no payment "
                       "can be attached to a client right now")
        kv_store.put(K_STATE, out)
        return out
    for ch in _charges(days):
        m = SR._match_payment(ch.get("customer_name") or "", (ch.get("_email") or "").lower(),
                              ch.get("amount"), idx, roster)
        row = {"payer": ch.get("customer_name") or "(unnamed Stripe customer)",
               "amount": ch.get("amount"), "date": str(ch.get("date")),
               "charge_id": ch.get("id")}
        if m.get("business"):
            out["matched"].append({**row, "client": m["business"],
                                   "basis": m.get("basis")})
            continue
        row["category"] = m.get("category")
        row["suggested"] = m.get("suggested") or []
        row["why"] = m.get("why") or ("no client matched this payer on an "
                                      "alias, an email or an exact name")
        out["rows"].append(row)
        out["total_unmatched"] += float(ch.get("amount") or 0)
    out["total_unmatched"] = round(out["total_unmatched"], 2)
    out["count"] = len(out["rows"])
    kv_store.put(K_STATE, out)
    return out


def latest() -> dict:
    return kv_store.get(K_STATE) or {"rows": [], "count": 0,
                                     "total_unmatched": 0.0, "available": False}


def panel() -> dict:
    """What the home dashboard renders. Stored results only — the panel never
    calls Stripe on a page load."""
    st = latest()
    return {
        "count": st.get("count") or 0,
        "total": st.get("total_unmatched") or 0.0,
        "rows": (st.get("rows") or [])[:8],
        "as_of": st.get("at"),
        "available": st.get("available", False),
        "note": st.get("note") or ("cash that has landed but isn't attached "
                                   "to a client — each one needs a name"),
    }


def matched_without_close() -> list[dict]:
    """Payments that DID match a client which has no close on file — the
    other half of the same problem: the money is attributed, the deal is
    invisible. Used by close_detect as a candidate source, never as proof."""
    st = latest()
    if not st.get("matched"):
        return []
    import re

    def _key(v):
        return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()

    have = set()
    try:
        import close_detect
        for e in (close_detect.latest().get("entries") or []):
            have.add(_key(e.get("person")))
    except Exception as ex:  # noqa: BLE001
        logger.info("unmatched: close ledger unreadable: %s", ex)
    return [m for m in st["matched"] if _key(m.get("client")) not in have]


# ── the owner's confirmation ────────────────────────────────────────────────

def confirm(payer: str, client: str, actor: str = "rydel",
            charge_id: str | None = None) -> dict:
    """Write the alias, journal it, re-match, and move the numbers.

    The journal records WHO said so and WHICH charge proved it, because an
    alias is a ruling about whose money this is — it should never be
    reconstructable only as "the system decided"."""
    import stripe_reconcile as SR
    if not (payer or "").strip() or not (client or "").strip():
        return {"ok": False, "error": "both a payer name and a client are needed"}
    ok = SR.learn_alias(payer, client)
    rec = {"at": now_sydney().isoformat(), "payer": payer, "client": client,
           "by": actor, "charge_id": charge_id, "ok": bool(ok)}
    journal = kv_store.get(K_JOURNAL) or []
    journal.append(rec)
    kv_store.put(K_JOURNAL, journal[-500:])
    res = {"ok": bool(ok), "alias": rec}
    if ok:
        res["rescan"] = {k: v for k, v in scan().items()
                         if k in ("count", "total_unmatched")}
        try:
            import close_detect
            res["invalidated"] = close_detect.invalidate_now(
                f"payer alias confirmed: {payer} → {client}")
        except Exception as e:  # noqa: BLE001
            res["invalidate_error"] = str(e)[:120]
    return res


def journal() -> list[dict]:
    return kv_store.get(K_JOURNAL) or []


def aliases() -> dict:
    import stripe_reconcile as SR
    return SR._aliases()
