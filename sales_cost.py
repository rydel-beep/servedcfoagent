"""sales_cost.py — WHAT SALES COSTS, AND THEREFORE WHAT A CLIENT COSTS.

Rydel's question: "accurate setter and closer commissions — at least as an
average — so as we scale we have a clear picture of CAC and what it costs us
apart from ad spend."

TRUE CAC = ad spend + commissions + bonuses + the manager retainer + sales
tooling, over the closes in the window. Spend-only CAC rides beside it so
the two are never confused (#150's rule, kept).

Every commission comes from ONE place — `commission_engine`, applying the
rulebook in force on each deal's own close date. Nothing here re-derives a
rate.

WHERE THE FACTS RUN OUT. The tracker has recorded no won deal since
2026-07-20, so the gap-window closes carry no package and no closer. Those
deals are costed at the BLENDED AVERAGE of the deals that do have facts, and
say so on their face — Rydel asked for "at least as an average", and an
average that admits what it is beats a per-deal number that was invented.
A decision card names exactly what would make them exact.
"""

from __future__ import annotations

import datetime as dt
import logging

import comp_rulebook as RB
import commission_engine as CE

logger = logging.getLogger(__name__)


def _tracker_deals() -> list[dict]:
    """Every won row the tracker HAS recorded, shaped for the engine."""
    import attribution_engine as AE
    try:
        rows = AE._tracker_rows_clean()
        leads, _ = AE.parse_tracker(rows)
        leads, _d = AE.dedupe_won(leads)
    except Exception as e:  # noqa: BLE001
        logger.warning("sales_cost: tracker unavailable: %s", e)
        return []
    out = []
    for l in leads:
        if not (l.get("won") and l.get("close_date")):
            continue
        v = RB.version_for(l["close_date"])
        out.append({
            "name": l.get("name"), "close_date": l["close_date"],
            "offer": l.get("offer"), "payment_type": l.get("payment_type") or "",
            "contract": l.get("contract"),
            "closer": l.get("closer"), "setter": l.get("setter"),
            "cash_events": [{"when": str(l["close_date"]),
                             "amount": l.get("cash"),
                             "inclusive": bool(v.get("cash_is_gst_inclusive", True))}],
            "recorded_closer_commission": l.get("closer_commission") or None,
            "recorded_setter_commission": l.get("setter_commission") or None,
            "facts": "tracker",
        })
    return out


def _union_deals(w0: dt.date, w1: dt.date) -> list[dict]:
    """The closes the ONE close engine counts — including the gap-window
    ones the tracker has not recorded."""
    import finance_analysis as FA
    try:
        return FA._closes_union(str(w0), str(w1), "activity") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("sales_cost: closes union unavailable: %s", e)
        return []


def _blended_average(costed: list[dict]) -> dict:
    """The average commission per close across deals whose facts we have."""
    if not costed:
        return {"available": False,
                "note": "no deal in this window has the facts to cost exactly"}
    closer = round(sum(d["counted"]["closer"] for d in costed) / len(costed), 2)
    setter = round(sum(d["counted"]["setter"] for d in costed) / len(costed), 2)
    return {"available": True, "closer": closer, "setter": setter,
            "total": round(closer + setter, 2), "n": len(costed),
            "note": f"the average across {len(costed)} deals that carry their facts"}


def build(window_start: str, window_end: str,
          average_pool_days: int = 180) -> dict:
    """The whole sales-cost picture for a window."""
    w0, w1 = dt.date.fromisoformat(window_start), dt.date.fromisoformat(window_end)
    out: dict = {"window": {"start": str(w0), "end": str(w1),
                            "days": (w1 - w0).days + 1},
                 "degraded": [], "needs_your_number": []}

    tracker = _tracker_deals()
    by_name = {(d.get("name") or "").strip().lower(): d for d in tracker}

    # the POOL the average is drawn from: recent deals that carry their facts
    pool_from = w1 - dt.timedelta(days=average_pool_days)
    pool = []
    for d in tracker:
        if not (pool_from <= d["close_date"] <= w1):
            continue
        acc = CE.accrue_close(d)
        if acc["needs_your_number"]:
            continue
        pool.append({**d, "counted": CE.counted_for(d)})
    avg = _blended_average(pool)

    # the deals IN the window — from the one close engine
    union = _union_deals(w0, w1)
    deals: list[dict] = []
    unmapped_owner = 0
    for u in union:
        nm = str(u.get("person") or u.get("name") or "").strip()
        known = by_name.get(nm.lower())
        if known:
            counted = CE.counted_for(known)
            deals.append({
                "name": nm, "close_date": str(known["close_date"]),
                "package": CE.accrue_close(known)["package"],
                "closer": known.get("closer"), "setter": known.get("setter"),
                "contract": known.get("contract"), "cash": u.get("cash"),
                "closer_cost": counted["closer"], "setter_cost": counted["setter"],
                "total": counted["total"], "basis": counted["chip"],
                "exact": True,
            })
            continue
        # the gap-window class: a real close with no package and no owner
        unmapped_owner += 1
        if avg.get("available"):
            deals.append({
                "name": nm, "close_date": str(u.get("close_date")),
                "package": None, "closer": None, "setter": None,
                "contract": u.get("contract"), "cash": u.get("cash"),
                "closer_cost": avg["closer"], "setter_cost": avg["setter"],
                "total": avg["total"],
                "basis": ("average — the tracker has not recorded this deal's "
                          "package or closer"),
                "exact": False,
            })
        else:
            deals.append({
                "name": nm, "close_date": str(u.get("close_date")),
                "package": None, "closer": None, "setter": None,
                "contract": u.get("contract"), "cash": u.get("cash"),
                "closer_cost": None, "setter_cost": None, "total": None,
                "basis": "needs your number — no facts and no pool to average",
                "exact": False})

    if unmapped_owner:
        out["needs_your_number"].append({
            "what": f"{unmapped_owner} close(s) in this window have no package "
                    "and no closer recorded",
            "why": ("the tracker has recorded no won deal since 2026-07-20, so "
                    "these are costed at the blended average rather than "
                    "exactly"),
            "fix": ("record the package and closer on the tracker — or tell me "
                    "which GHL user each owner id is and the CRM can supply it")})
        CE._raise_card({
            "id": f"comp_unmapped_{w0}_{w1}",
            "title": f"{unmapped_owner} close(s) costed at an average, not exactly",
            "detail": ("no package or closer is recorded for them; the CRM has "
                       "owner ids but they are not mapped to people"),
            "action": "record the package and closer, or map the GHL user ids"})

    # ── the setter bounty: per SET, not per close ──
    sets = _sets_in_window(w0, w1)
    v = RB.version_for(w1)
    per_set = (v.get("setter") or {}).get("per_set") or 0.0
    if not sets.get("count"):
        # The payout log dates only a minority of its rows, so a window can
        # hold real sets and no dated payout row. Reading that as "no bounty
        # was earned" would understate setter cost exactly the way a blank
        # tracker cell understated commission. Count the sets the one
        # attribution engine saw, and label it.
        est = _sets_from_engine(w0, w1)
        if est is not None:
            sets = {"count": est, "by_setter": {}, "estimated": True,
                    "basis": (f"{est} sets from the one attribution engine — "
                              "the payout log has no dated row in this window, "
                              "so the bounty is estimated from the sets that "
                              "actually happened")}
    bounty_total = round((sets.get("count") or 0) * per_set, 2)

    closes = len(deals)
    commissions = round(sum(d["total"] or 0 for d in deals), 2)
    retainer = CE.manager_retainer(str(w1)[:7])
    retainer_share = round(retainer["amount"] * out["window"]["days"] / 30.44, 2)

    ad_spend = _ad_spend(w0, w1)
    tooling = _tooling(out["window"]["days"])

    total_acq = round((ad_spend or 0) + commissions + bounty_total
                      + retainer_share + tooling, 2)
    out["deals"] = deals
    out["closes"] = closes
    out["average"] = avg
    out["sets"] = sets
    out["bounties"] = {"count": sets["count"], "per_set": per_set,
                       "total": bounty_total, "basis": sets["basis"]}
    out["retainer"] = {**retainer, "window_share": retainer_share}
    out["commissions"] = {
        "closer": round(sum(d["closer_cost"] or 0 for d in deals), 2),
        "setter_on_closes": round(sum(d["setter_cost"] or 0 for d in deals), 2),
        "bounties": bounty_total,
        "total": round(commissions + bounty_total, 2),
        "exact_deals": sum(1 for d in deals if d["exact"]),
        "averaged_deals": sum(1 for d in deals if not d["exact"]),
    }
    out["true_cac"] = {
        "ad_spend": ad_spend, "commissions": commissions,
        "bounties": bounty_total, "retainer": retainer_share,
        "tooling": tooling, "total": total_acq,
        "per_close": round(total_acq / closes, 2) if closes else None,
        "components": [
            {"label": "ad spend", "amount": ad_spend or 0},
            {"label": "commissions on closes", "amount": commissions},
            {"label": "set bounties", "amount": bounty_total},
            {"label": "manager retainer", "amount": retainer_share},
            {"label": "sales tooling", "amount": tooling},
        ],
    }
    out["cac_spend_only"] = (round((ad_spend or 0) / closes, 2) if closes else None)
    out["ratios"] = _ratios(deals, out["true_cac"]["per_close"])
    out["fy26_reference"] = _fy26_reference(commissions + bounty_total)
    out["rule_version"] = {"version": v["version"], "name": v["name"],
                           "confidence": v.get("confidence")}
    return out


def _sets_in_window(w0: dt.date, w1: dt.date) -> dict:
    """How many sets the bounty is owed on.

    TODAY the bounty is one row in the SETTER PAYOUT LOG — 194 rows, every
    one a flat $50, 127 of them on deals that never closed. The log carries
    NO qualification flag, so 'qualified' is the payer's judgement when the
    row is added. That is said, not dressed up as a rule the data supports.
    """
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name("SETTER PAYOUT LOG") or []
    except Exception as e:  # noqa: BLE001
        return {"count": None, "basis": f"payout log unavailable ({str(e)[:60]})",
                "by_setter": {}}
    import re
    n, by_setter, dated = 0, {}, 0
    for r in rows[7:]:
        if len(r) <= 9:
            continue
        setter = (r[2] or "").strip()
        if not setter:
            continue
        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", r[9] or "")
        if m:
            d = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            dated += 1
            if not (w0 <= d <= w1):
                continue
        else:
            continue          # undated rows can't be placed in a window
        n += 1
        by_setter[setter] = by_setter.get(setter, 0) + 1
    return {"count": n, "by_setter": by_setter, "dated_rows": dated,
            "basis": ("one row per set in the SETTER PAYOUT LOG, windowed by "
                      "its payout date. The log records no qualification flag — "
                      "'qualified' is the judgement made when the row is added. "
                      "Rows with no payout date cannot be placed in a window "
                      "and are not counted here.")}


def _sets_from_engine(w0: dt.date, w1: dt.date):
    """Sets the one attribution engine counted in a window — the fallback
    basis for the bounty when the payout log has no dated row here."""
    try:
        import attribution_engine as AE
        res = AE.compute(start=str(w0), end=str(w1), basis="activity")
        return sum(c.get("sets") or 0 for c in res.get("creatives", []))
    except Exception as e:  # noqa: BLE001
        logger.info("sales_cost: set count unavailable: %s", e)
        return None


def _ad_spend(w0: dt.date, w1: dt.date):
    try:
        import meta_spend
        return (meta_spend.spend_in_range(str(w0), str(w1)) or {}).get("spend")
    except Exception as e:  # noqa: BLE001
        logger.warning("sales_cost: ad spend unavailable: %s", e)
        return None


def _tooling(days: int) -> float:
    try:
        from config import SALES_TOOLING_MONTHLY
        return round(SALES_TOOLING_MONTHLY * days / 30.44, 2)
    except Exception:
        return 0.0


def _ratios(deals: list[dict], cac_per_close) -> dict:
    """LTV:CAC, LTGP:CAC and payback on TRUE CAC."""
    contracts = [d["contract"] for d in deals if d.get("contract")]
    avg_contract = round(sum(contracts) / len(contracts), 2) if contracts else None
    # THE SAME margin rule the standing engine uses — a 100% Xero read is
    # COGS timing, not truth, and falls to the labelled FY26 rate. Two
    # engines disagreeing about margin would put two LTGP:CAC numbers on the
    # estate, which is the whole failure this wave exists to end.
    margin, margin_prov = _margin()
    if not (cac_per_close and avg_contract):
        return {"ltv_to_cac": None, "ltgp_to_cac": None, "avg_contract": avg_contract,
                "margin_pct": margin, "margin_provenance": margin_prov,
                "note": "not enough to compute on true CAC"}
    ltv_cac = round(avg_contract / cac_per_close, 2)
    # margin arrives as a PERCENT (42.9), not a fraction — the standing
    # engine divides by 100 and so must this one, or LTGP:CAC comes out a
    # hundred times too big.
    ltgp_cac = (round(avg_contract * (margin / 100.0) / cac_per_close, 2)
                if margin else None)
    return {"ltv_to_cac": ltv_cac, "ltgp_to_cac": ltgp_cac,
            "avg_contract": avg_contract, "margin_pct": margin,
            "margin_provenance": margin_prov,
            "basis": "on TRUE CAC — ad spend + commissions + bounties + retainer + tooling"}


def _margin():
    """(percent, provenance) — the standing engine's rule, not a second one."""
    try:
        from snapshot import load_persisted
        m = ((load_persisted() or {}).get("xero") or {}).get("gross_margin_pct")
    except Exception:
        m = None
    if m is None or m >= 95:
        return 42.9, (f"FY26 contribution margin 42.9% (labelled fallback — "
                      f"Xero read {'unavailable' if m is None else f'{m}% (COGS timing, implausible)'})")
    return m, f"Xero P&L gross margin {m}%"


def _fy26_reference(commissions: float) -> dict:
    """The FY26 anchor, shown BESIDE as a reference — never substituted."""
    try:
        from config import FY26_COMMISSIONS_PCT_OF_SALES as pct
    except Exception:
        pct = None
    return {"fy26_pct_of_sales": pct,
            "label": (f"FY26 actuals: commissions were {pct}% of sales"
                      if pct else "FY26 reference unavailable"),
            "use": "a reference to sanity-check against, never a substitute"}


# ── the averages Rydel asked for ────────────────────────────────────────────

def averages(days: int = 90, end: str | None = None) -> dict:
    """Per close, by package and by closer — the table that answers
    'what does it cost us apart from ad spend'."""
    w1 = dt.date.fromisoformat(end) if end else _today()
    w0 = w1 - dt.timedelta(days=days - 1)
    picture = build(str(w0), str(w1))
    deals = picture["deals"]
    exact = [d for d in deals if d["exact"]]

    def _agg(rows):
        if not rows:
            return None
        n = len(rows)
        return {"n": n,
                "closer": round(sum(r["closer_cost"] or 0 for r in rows) / n, 2),
                "setter": round(sum(r["setter_cost"] or 0 for r in rows) / n, 2),
                "total": round(sum(r["total"] or 0 for r in rows) / n, 2)}

    by_package, by_closer = {}, {}
    for d in exact:
        if d.get("package"):
            by_package.setdefault(d["package"], []).append(d)
        if d.get("closer"):
            by_closer.setdefault(str(d["closer"]).lower(), []).append(d)

    contracts = [d["contract"] for d in exact if d.get("contract")]
    cash = [d["cash"] for d in deals if d.get("cash")]
    comm_total = picture["commissions"]["total"]
    return {
        "window": picture["window"], "closes": picture["closes"],
        "per_close": _agg(deals),
        "per_close_exact_only": _agg(exact),
        "by_package": {k: _agg(v) for k, v in by_package.items()},
        "by_closer": {k: _agg(v) for k, v in by_closer.items()},
        "setter_cost": {
            "bounties": picture["bounties"],
            "per_set": picture["bounties"]["per_set"],
            "per_close": (round(picture["commissions"]["setter_on_closes"]
                                / picture["closes"], 2) if picture["closes"] else None),
            "why_they_differ": (
                "the bounty is owed on every set, whether or not it closes — so "
                "the setter cost PER CLOSE moves with the close rate, while the "
                "cost per set does not"),
        },
        "as_pct": {
            "of_contract": (round(comm_total / sum(contracts) * 100, 1)
                            if contracts else None),
            "of_cash_collected": (round(comm_total / sum(cash) * 100, 1)
                                  if cash else None),
            "fy26_reference": picture["fy26_reference"],
        },
        "true_cac": picture["true_cac"], "ratios": picture["ratios"],
        "needs_your_number": picture["needs_your_number"],
    }


def per_close_cost_table() -> dict:
    """What each package costs to sell, Kalin-closed vs Coby-closed, and who
    receives what on a Coby close. Computed from the rulebook, not typed."""
    rows = []
    specs = [
        ("Growth Pro", RB.PKG_GROWTH_PRO, "Monthly", 3355.0, True, 18300.0),
        ("Scale Engine (PIF)", RB.PKG_SCALE_ENGINE, "PIF", 14500.0, False, 14500.0),
        ("Scale Engine (split)", RB.PKG_SCALE_SPLIT, "Split", 6750.0, False, 13500.0),
    ]
    for label, pkg, ptype, cash, inclusive, contract in specs:
        cash_events = ([{"when": "2026-09-25", "amount": cash, "inclusive": inclusive}]
                       * (2 if ptype == "Split" else 1))
        row = {"package": label}
        for closer in ("kalin", "coby"):
            deal = {"name": f"{label} {closer}", "close_date": dt.date(2026, 9, 25),
                    "package": pkg, "payment_type": ptype, "contract": contract,
                    "closer": closer, "setter": "maran",
                    "cash_events": [dict(c) for c in cash_events]}
            acc = CE.accrue_close(deal)
            row[closer] = {
                "company_total": acc["company_total"],
                "closer_side": round(sum(e["amount"] for e in acc["events"]
                                         if e["role"] in ("closer", "manager")), 2),
                "setter_side": round(sum(e["amount"] for e in acc["events"]
                                         if e["role"] == "setter"), 2),
                "by_person": acc["by_person"],
            }
        row["coby_close_split"] = {
            "kalin_override": row["coby"]["by_person"].get("kalin", 0.0),
            "coby_nets": row["coby"]["by_person"].get("coby", 0.0),
        }
        row["cheaper_closer"] = ("coby" if row["coby"]["closer_side"]
                                 < row["kalin"]["closer_side"] else "kalin")
        rows.append(row)
    return {"rows": rows,
            "note": ("the setter side here is the 5% of initial-month cash only "
                     "— the $50 bounty is owed on the SET, not the close, so it "
                     "is counted per set and not per deal. Shifting closes from Kalin to "
                     "Coby LOWERS the company's cost per client, because the "
                     "junior rate is the company's total."),
            "rule_version": RB.current_version()["version"]}


def _today():
    from helpers import today_sydney
    return today_sydney()


def reconcile_paid(months: list[str]) -> dict:
    """ACCRUED vs what Xero actually PAID, by month. Differences are
    surfaced with their likely cause — never forced to agree."""
    paid = CE.paid_by_month(months)
    out = {"months": [], "paid_available": paid.get("available")}
    if not paid.get("available"):
        out["reason"] = paid.get("reason")
        return out
    for m in months:
        y, mo = int(m[:4]), int(m[5:7])
        import calendar
        last = calendar.monthrange(y, mo)[1]
        pic = build(f"{m}-01", f"{m}-{last:02d}")
        p = paid["months"].get(m) or {}
        acc_closer = pic["commissions"]["closer"]
        acc_setter = round(pic["commissions"]["setter_on_closes"]
                           + pic["bounties"]["total"], 2)
        out["months"].append({
            "month": m,
            "accrued_closer": acc_closer, "paid_closer": p.get("closer"),
            "delta_closer": round((p.get("closer") or 0) - acc_closer, 2),
            "accrued_setter": acc_setter, "paid_setter": p.get("setter"),
            "delta_setter": round((p.get("setter") or 0) - acc_setter, 2),
            "why": ("commission is paid the month AFTER the close it belongs "
                    "to, so a month's paid figure mostly settles the previous "
                    "month's accrual — the two are not expected to match "
                    "inside one month"),
        })
    return out


# ── what the SIMULATOR needs: cost from the rulebook, not a flat rate ───────

DEFAULT_MIX = {
    "closer_mix": {"kalin": 1.0},        # share of closes by closer
    "package_mix": {RB.PKG_GROWTH_PRO: 0.5, RB.PKG_SCALE_ENGINE: 0.5},
    "pif_share": 0.5,                    # of Scale Engine closes, how many PIF
}


def modelled_commission(mix: dict | None = None,
                        first_month_cash_ex_gst: float = 3050.0,
                        scale_cash_ex_gst: float = 14500.0,
                        on=None) -> dict:
    """Commission per close for a MODELLED mix, straight from the rulebook.

    This is what replaces `commission_pct_of_cash` in the compass. A flat
    percentage of cash could not answer "what happens if Coby closes more of
    them", because the whole point of the junior rate is that the company's
    total changes with WHO closes. The rate could only ever move with cash.

    Returns per-close dollars for the closer side and the setter side, plus
    the monthly fixed costs, so the cost card can show ads + commissions +
    bonuses + retainer + tooling per client.
    """
    m = {**DEFAULT_MIX, **(mix or {})}
    v = RB.version_for(on)
    closer_mix = m["closer_mix"] or {"kalin": 1.0}
    pkg_mix = m["package_mix"] or {RB.PKG_GROWTH_PRO: 1.0}
    pif = float(m.get("pif_share") or 0.0)

    closer_cost = 0.0
    setter_pct_cost = 0.0
    detail = []
    cshare_total = sum(closer_mix.values()) or 1.0
    pshare_total = sum(pkg_mix.values()) or 1.0
    for pkg, pshare in pkg_mix.items():
        pw = pshare / pshare_total
        # cash at the commission event for this package
        if pkg == RB.PKG_GROWTH_PRO:
            ev_cash = first_month_cash_ex_gst
        elif pkg == RB.PKG_SCALE_SPLIT:
            ev_cash = scale_cash_ex_gst / 2.0
        else:
            ev_cash = scale_cash_ex_gst if pif else scale_cash_ex_gst / 2.0
        setter_pct_cost += pw * ev_cash * ((v.get("setter") or {}).get("pct_of_initial_cash") or 0.0)
        for who, cshare in closer_mix.items():
            cw = cshare / cshare_total
            junior = who.lower() in RB.JUNIOR_CLOSERS and bool(v.get("junior_closer_flat"))
            table = v["junior_closer_flat"] if junior else v["closer_flat"]
            rate = table.get(pkg)
            if rate is None:
                detail.append({"package": pkg, "closer": who,
                               "rate": None,
                               "note": "needs your number — no rate ruled"})
                continue
            closer_cost += pw * cw * float(rate)
            detail.append({"package": pkg, "closer": who, "rate": float(rate),
                           "weight": round(pw * cw, 4),
                           "junior": junior})

    per_set = (v.get("setter") or {}).get("per_set") or 0.0
    mgr = v.get("manager") or {}
    extras = v.get("junior_extras") or {}
    kpi = (extras.get("monthly_kpi_bonus") or {}).get("amount") or 0.0
    junior_in_mix = any(w.lower() in RB.JUNIOR_CLOSERS for w in closer_mix)
    return {
        "closer_per_close": round(closer_cost, 2),
        "setter_pct_per_close": round(setter_pct_cost, 2),
        "commission_per_close": round(closer_cost + setter_pct_cost, 2),
        "bounty_per_set": per_set,
        "monthly_fixed": {
            "manager_retainer": mgr.get("monthly_retainer") or 0.0,
            "junior_kpi_bonus": (kpi if junior_in_mix else 0.0),
            "total": round((mgr.get("monthly_retainer") or 0.0)
                           + (kpi if junior_in_mix else 0.0), 2),
        },
        "rule_version": v["version"],
        "detail": detail,
        "note": ("per close, from the rulebook — moving closes from Kalin to "
                 "a junior LOWERS this, because the junior rate is the "
                 "company's TOTAL and the manager's share comes out of it"),
        "needs_your_number": [d for d in detail if d.get("rate") is None],
    }


# ── EDITH ───────────────────────────────────────────────────────────────────

import re as _re

_COMM_RE = _re.compile(
    r"(what|how much).{0,30}(commission|comms)|"
    r"commission.{0,25}(cost|per client|per close|average)|"
    r"(cost|costs).{0,25}(per client|per close).{0,25}(apart from|besides|other than).{0,12}ad",
    _re.I)


def handle_commission_query(text: str):
    """'what do commissions cost us per client' → the average, its parts, the
    rule version, and how a Coby close splits.

    OWNER-ONLY: per-person figures never leave this function for a non-owner
    session; the caller's guard is checked here too, so a future route that
    forgets cannot leak it."""
    if not _COMM_RE.search(text or ""):
        return None, False
    try:
        from dashboard.auth import is_owner
        owner = is_owner()
    except Exception:
        owner = False
    if not owner:
        return ("Commission figures are owner-only — I can't share what "
                "individual people are paid."), True
    try:
        a = averages(90)
        t = per_close_cost_table()
    except Exception as e:  # noqa: BLE001
        return f"I couldn't work out the commission cost just now: {str(e)[:90]}", True
    pc = a.get("per_close") or {}
    if not pc:
        return ("No closes in the last ninety days, so there's no average to "
                "give you yet."), True
    v = RB.current_version()
    gp = next((r for r in t["rows"] if r["package"] == "Growth Pro"), None)
    lines = [
        f"Commissions run about ${pc['total']:,.0f} a close over the last "
        f"ninety days — ${pc['closer']:,.0f} to the closer and "
        f"${pc['setter']:,.0f} to the setter, across {pc['n']} closes.",
    ]
    byc = a.get("by_closer") or {}
    if len(byc) > 1:
        parts = ", ".join(f"{k.title()} ${v['total']:,.0f}" for k, v in byc.items())
        lines.append(f"By closer: {parts}.")
    if gp:
        sp = gp["coby_close_split"]
        lines.append(
            f"On today's rules a Growth Pro costs the company "
            f"${gp['kalin']['closer_side']:,.0f} when Kalin closes it and "
            f"${gp['coby']['closer_side']:,.0f} when Coby does — and that "
            f"${gp['coby']['closer_side']:,.0f} splits into "
            f"${sp['kalin_override']:,.2f} to Kalin as the manager override "
            f"and ${sp['coby_nets']:,.2f} to Coby. The override comes out of "
            f"Coby's commission; it never adds company cost.")
    tc = a.get("true_cac") or {}
    if tc.get("per_close"):
        lines.append(
            f"That puts true CAC at ${tc['per_close']:,.0f} a client — ad "
            f"spend ${tc['ad_spend']:,.0f}, commissions ${tc['commissions']:,.0f}, "
            f"bounties ${tc['bounties']:,.0f}, retainer ${tc['retainer']:,.0f} "
            f"and tooling ${tc['tooling']:,.0f}.")
    lines.append(f"Rules: version {v['version']}, {v['name'].lstrip('Current — ')}.")
    if a.get("needs_your_number"):
        lines.append(a["needs_your_number"][0]["what"] + ".")
    return " ".join(lines), True
