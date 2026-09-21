"""commission_engine.py — ONE ENGINE FOR WHAT SALES COSTS.

Phase 0 found four paths computing a commission, three of them returning $0
because the tracker has recorded no won deal since 2026-07-20, and one
returning a percentage of cash that contradicted itself across two surfaces.
This replaces all of them.

THREE LAYERS, never confused:

  ACCRUED   what the RULES say is owed, computed from the rulebook in force
            on the deal's own close date × the facts of the deal. Event-level:
            a set bounty is owed when the set happens, a closer's flat is owed
            at the close, the manager's 3% is owed as the junior's cash lands.
  RECORDED  what the tracker / payout log actually says, where filled.
  PAID      what Xero actually paid, by month, from the two commission
            accounts.

  COUNTED   = RECORDED where present, else ACCRUED — and it always says
            which. A BLANK CELL IS NEVER $0. That single rule is the whole
            reason September's CAC was missing every dollar of commission.

THE INVARIANT (tested): the company's total commission on a junior-closed
deal equals the junior rate. Kalin's 3% is funded OUT of Coby's commission —
it moves money between people, it never adds company cost. If a deduction
would exceed the commission on an event it is capped there and a decision
card is raised; it never goes negative.

Read-only: tracker, payout log and Xero are read, never written.
"""

from __future__ import annotations

import datetime as dt
import logging

import comp_rulebook as RB

logger = logging.getLogger(__name__)

K_CARDS = "comp:decision_cards"


# ── one event of commission ─────────────────────────────────────────────────

def _event(when, who, role, kind, amount, basis, version, deal=None,
           funded_by=None, note=""):
    return {"when": str(when) if when else None, "who": who, "role": role,
            "kind": kind, "amount": round(float(amount), 2), "basis": basis,
            "rule_version": version, "deal": deal,
            "funded_by": funded_by, "note": note}


def _cash_ex_gst(amount, inclusive: bool) -> float:
    return RB.ex_gst(amount, inclusive) or 0.0


def _raise_card(card: dict) -> None:
    try:
        import kv_store
        from helpers import now_sydney
        cards = kv_store.get(K_CARDS) or []
        card = {**card, "at": now_sydney().isoformat()}
        if not any(c.get("id") == card.get("id") for c in cards):
            cards.append(card)
            kv_store.put(K_CARDS, cards[-200:])
    except Exception as e:  # noqa: BLE001
        logger.info("comp decision card not stored: %s", e)


def decision_cards() -> list[dict]:
    try:
        import kv_store
        return kv_store.get(K_CARDS) or []
    except Exception:
        return []


# ── ACCRUAL — rules in force × the facts ────────────────────────────────────

def accrue_close(deal: dict) -> dict:
    """Every commission event a CLOSE creates.

    deal: {name, close_date, package|offer, payment_type, contract,
           cash_events: [{when, amount, inclusive}], setter, closer}

    `cash_events` is the money as it actually lands. A monthly plan's first
    element is the initial month; a PIF has one element, the whole
    prepayment; a split has one per collection.
    """
    close_date = deal.get("close_date")
    v = RB.version_for(close_date)
    pkg = deal.get("package") or RB.normalise_package(deal.get("offer"))
    closer = (deal.get("closer") or "").strip().lower()
    setter = (deal.get("setter") or "").strip().lower()
    events: list[dict] = []
    needs: list[str] = []

    inclusive_default = bool(v.get("cash_is_gst_inclusive", True))
    cash_events = deal.get("cash_events") or []
    initial = cash_events[0] if cash_events else None
    initial_ex = _cash_ex_gst(
        (initial or {}).get("amount"),
        (initial or {}).get("inclusive", inclusive_default)) if initial else 0.0

    # ── the SETTER's share of a close (the bounty is NOT here — it is owed
    # per set, whether or not the deal closes; see accrue_set) ──
    s_rules = v.get("setter") or {}
    if s_rules.get("per_won_flat"):
        events.append(_event(close_date, setter or "unattributed", "setter",
                             "setter flat on a won deal", s_rules["per_won_flat"],
                             "flat per won deal (the rules of the day)",
                             v["version"], deal.get("name")))
    pct = s_rules.get("pct_of_initial_cash") or 0.0
    if pct and initial_ex:
        events.append(_event(
            (initial or {}).get("when") or close_date,
            setter or "unattributed", "setter", "setter % of initial-month cash",
            initial_ex * pct,
            f"{pct * 100:.0f}% of ${initial_ex:,.2f} ex-GST"
            + (" (PIF — the initial month is the whole prepayment)"
               if str(deal.get("payment_type", "")).upper() == "PIF" else ""),
            v["version"], deal.get("name")))

    # ── the CLOSER ──
    is_junior = closer in RB.JUNIOR_CLOSERS and bool(v.get("junior_closer_flat"))
    table = v["junior_closer_flat"] if is_junior else v["closer_flat"]
    if pkg is None:
        needs.append("package not recognised — needs your number")
    elif pkg not in table:
        needs.append(f"no rate ruled for {pkg.replace('_', ' ')} — needs your number")
    else:
        total = float(table[pkg])
        # how the company's total is spread across the cash events
        shares = _commission_shares(total, deal, cash_events)
        mgr = v.get("manager") or {}
        mpct = mgr.get("pct_of_junior_cash") or 0.0
        for i, (when, share, ev_cash_ex) in enumerate(shares):
            if is_junior and mpct:
                cut = round(ev_cash_ex * mpct, 2)
                capped = False
                if cut > share:
                    cut, capped = share, True
                    _raise_card({
                        "id": f"comp_cap_{deal.get('name')}_{i}",
                        "title": (f"The manager's {mpct * 100:.0f}% would exceed "
                                  f"{closer.title()}'s commission on "
                                  f"{deal.get('name')}"),
                        "detail": (f"event cash ${ev_cash_ex:,.2f} ex-GST × "
                                   f"{mpct * 100:.0f}% = more than the "
                                   f"${share:,.2f} owed on this event. Capped "
                                   f"at ${share:,.2f}; it never goes negative."),
                        "action": "confirm the rate for this package"})
                events.append(_event(when, RB.MANAGER, "manager",
                                     "manager override on a junior close", cut,
                                     f"{mpct * 100:.0f}% of ${ev_cash_ex:,.2f} ex-GST"
                                     + (" (CAPPED)" if capped else ""),
                                     v["version"], deal.get("name"),
                                     funded_by=closer))
                events.append(_event(when, closer, "closer",
                                     "junior closer, net of the override",
                                     round(share - cut, 2),
                                     f"${share:,.2f} junior rate − ${cut:,.2f} override",
                                     v["version"], deal.get("name")))
            else:
                events.append(_event(when, closer or "unattributed", "closer",
                                     "closer flat", share,
                                     f"${total:,.2f} for {pkg.replace('_', ' ')}"
                                     + (f", this collection" if len(shares) > 1 else ""),
                                     v["version"], deal.get("name")))

    company_total = round(sum(e["amount"] for e in events), 2)
    return {
        "deal": deal.get("name"), "close_date": str(close_date) if close_date else None,
        "package": pkg, "closer": closer, "setter": setter,
        "rule_version": v["version"], "rule_name": v["name"],
        "rule_confidence": v.get("confidence"),
        "events": events,
        "company_total": company_total,
        "by_person": _by_person(events),
        "needs_your_number": needs,
    }


def _commission_shares(total: float, deal: dict, cash_events: list) -> list:
    """How the company's total is owed across the cash events.

    A split pays pro-rata across its collections (the July policy: $500 per
    collection on a $1,000 Scale Engine split). Everything else is owed in
    full at the close, against the initial cash.
    """
    v = RB.version_for(deal.get("close_date"))
    inclusive_default = bool(v.get("cash_is_gst_inclusive", True))
    ptype = str(deal.get("payment_type") or "").strip().lower()
    is_split = "split" in ptype or (deal.get("package") == RB.PKG_SCALE_SPLIT
                                    and len(cash_events) > 1)
    if is_split and len(cash_events) > 1:
        n = len(cash_events)
        out = []
        for ce in cash_events:
            out.append((ce.get("when") or deal.get("close_date"),
                        round(total / n, 2),
                        _cash_ex_gst(ce.get("amount"),
                                     ce.get("inclusive", inclusive_default))))
        return out
    first = cash_events[0] if cash_events else {}
    return [(first.get("when") or deal.get("close_date"), round(total, 2),
             _cash_ex_gst(first.get("amount"),
                          first.get("inclusive", inclusive_default)))]


def _by_person(events: list) -> dict:
    out: dict = {}
    for e in events:
        out[e["who"]] = round(out.get(e["who"], 0.0) + e["amount"], 2)
    return out


def accrue_set(when, setter: str, qualified: bool = True) -> dict:
    """The bounty. Owed when the SET happens, whether or not it ever closes —
    which is why setter cost per CLOSE moves with the close rate."""
    v = RB.version_for(when)
    fee = (v.get("setter") or {}).get("per_set") or 0.0
    basis = RB.set_fee_basis(when)
    if not fee or (basis == "qualified" and not qualified):
        return {"events": [], "amount": 0.0, "basis": basis}
    e = _event(when, (setter or "unattributed").lower(), "setter",
               "set bounty", fee, f"flat per {basis} set", v["version"])
    return {"events": [e], "amount": fee, "basis": basis}


def company_total_for(deal: dict) -> float:
    """THE INVARIANT's subject: what the company pays on this deal, all
    people together."""
    return accrue_close(deal)["company_total"]


# ── the monthly fixed cost ──────────────────────────────────────────────────

def manager_retainer(month: str) -> dict:
    """R-KALIN-MGR's fixed half — a monthly sales cost, not a per-deal one."""
    import calendar
    y, mo = int(month[:4]), int(month[5:7])
    last = dt.date(y, mo, calendar.monthrange(y, mo)[1])
    v = RB.version_for(last)          # the rules in force at month end
    amt = (v.get("manager") or {}).get("monthly_retainer") or 0.0
    started = RB._d(v.get("from"))
    partial = bool(amt and started and started.year == y and started.month == mo
                   and started.day > 1)
    return {"month": month, "amount": round(amt, 2), "who": RB.MANAGER,
            "role": "manager", "kind": "manager retainer",
            "rule_version": v["version"],
            "partial_month": partial,
            "basis": ("fixed per month, regardless of deals"
                      + (f" — the rule started {started} so this month is "
                         "part-served; the full retainer is shown, not "
                         "pro-rated, until you say otherwise" if partial else ""))}


# ── RECORDED — what the sources actually say ────────────────────────────────

def recorded_for(deal: dict) -> dict:
    """The tracker's own cells. `None` means BLANK — never zero."""
    c = deal.get("recorded_closer_commission")
    s = deal.get("recorded_setter_commission")
    return {"closer": c if (c or 0) > 0 else None,
            "setter": s if (s or 0) > 0 else None}


def counted_for(deal: dict) -> dict:
    """COUNTED = recorded where present, else accrued — and it says which."""
    acc = accrue_close(deal)
    rec = recorded_for(deal)
    acc_closer = round(sum(e["amount"] for e in acc["events"]
                           if e["role"] in ("closer", "manager")), 2)
    acc_setter = round(sum(e["amount"] for e in acc["events"]
                           if e["role"] == "setter"), 2)
    closer_src = "recorded" if rec["closer"] is not None else "accrued"
    setter_src = "recorded" if rec["setter"] is not None else "accrued"
    return {
        "closer": rec["closer"] if rec["closer"] is not None else acc_closer,
        "setter": rec["setter"] if rec["setter"] is not None else acc_setter,
        "closer_source": closer_src, "setter_source": setter_src,
        "chip": ("worked out from your rules"
                 if "accrued" in (closer_src, setter_src) else "recorded"),
        "accrued": acc, "recorded": rec,
        "total": round((rec["closer"] if rec["closer"] is not None else acc_closer)
                       + (rec["setter"] if rec["setter"] is not None else acc_setter), 2),
    }


# ── PAID — Xero, by month ───────────────────────────────────────────────────

def paid_by_month(months: list[str]) -> dict:
    """The two commission accounts from the Xero P&L, per month. Read-only,
    via the existing report scopes — no new token."""
    import calendar
    out: dict = {}
    try:
        import xero_pull as X
        tok = X._refresh_access_token(X._load_tokens())
        if not tok:
            return {"available": False, "reason": "Xero token refresh failed"}
        for m in months:
            y, mo = int(m[:4]), int(m[5:7])
            last = calendar.monthrange(y, mo)[1]
            d = X._fetch_pnl_range(tok["access_token"], tok["tenant_id"],
                                   f"{m}-01", f"{m}-{last:02d}")
            li = (X._parse_pnl(d) or {}).get("opex_line_items") or [] if d else []
            out[m] = {
                "closer": next((x["amount"] for x in li
                                if "closer" in x["label"].lower()), 0.0),
                "setter": next((x["amount"] for x in li
                                if "setter" in x["label"].lower()), 0.0),
            }
        return {"available": True, "months": out,
                "source": "Xero P&L — Closer Commission + Setter Commission accounts"}
    except Exception as e:  # noqa: BLE001
        logger.warning("paid_by_month failed: %s", e)
        return {"available": False, "reason": str(e)[:140]}


# ── the fit check: do the rules explain what was recorded? ──────────────────

def fit_check(deals: list[dict]) -> dict:
    """Rule-derived vs recorded, for every deal that HAS a recorded value.
    A mismatch is reported with its reason — never reconciled away."""
    rows, matched, mismatched = [], 0, 0
    for d in deals:
        rec = recorded_for(d)
        if rec["closer"] is None:
            continue
        acc = accrue_close(d)
        derived = round(sum(e["amount"] for e in acc["events"]
                            if e["role"] in ("closer", "manager")), 2)
        delta = round(rec["closer"] - derived, 2)
        ok = abs(delta) < 0.51
        matched += 1 if ok else 0
        mismatched += 0 if ok else 1
        rows.append({"deal": d.get("name"), "close_date": str(d.get("close_date")),
                     "package": acc["package"], "closer": acc["closer"],
                     "rule_version": acc["rule_version"],
                     "recorded": rec["closer"], "derived": derived,
                     "delta": delta, "ok": ok,
                     "why": "" if ok else _explain(acc, rec, delta)})
    n = matched + mismatched
    # Three different things get called a "mismatch", and lumping them
    # together would hide the one that matters. A package nobody has ruled a
    # rate for is not the rulebook being wrong — it is a question for Rydel.
    unruled = [r for r in rows if not r["ok"] and r["derived"] == 0.0]
    differs = [r for r in rows if not r["ok"] and r["derived"] != 0.0]
    return {"rows": rows, "matched": matched, "mismatched": mismatched,
            "n": n, "fit_rate": (round(matched / n * 100, 1) if n else None),
            "unruled_package": len(unruled), "rate_differs": len(differs),
            "fit_rate_where_a_rate_exists": (
                round(matched / (matched + len(differs)) * 100, 1)
                if (matched + len(differs)) else None),
            "note": ("rule-derived vs the tracker's own cell, for every deal "
                     "that has one. Mismatches are explained, never forced — "
                     "and the COUNTED figure still uses the recorded value, "
                     "so the fit rate measures the reconstruction, never a "
                     "number anyone reads.")}


def _explain(acc: dict, rec: dict, delta: float) -> str:
    if acc["closer"] in RB.JUNIOR_CLOSERS:
        return ("recorded at the full rate; the junior rate + manager override "
                "was not applied to this deal at the time")
    if acc["package"] is None:
        return "package not recognised — no rate to derive"
    if acc["package"] not in (RB.version_for(acc["close_date"])["closer_flat"] or {}):
        return f"no rate ruled for {acc['package']} in this era"
    pkg = acc["package"]
    if pkg == RB.PKG_SCALE_ENGINE:
        return ("Scale Engine cells alternate between $1,400 and $1,500 "
                "within the same months, so no single rate fits that era — "
                "the recorded value is what counts")
    if pkg == RB.PKG_GROWTH_PRO:
        return ("Growth Pro cells vary ($595–$700) inside the reconstructed "
                "era — the recorded value is what counts")
    return (f"recorded ${rec['closer']:,.2f} against ${rec['closer'] - delta:,.2f} "
            f"derived — outside the reconstructed era's rate")
