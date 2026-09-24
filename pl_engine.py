"""pl_engine.py — NET PROFIT, TRUTHFULLY: THE LADDER, THREE BASES, THE BRIDGE (#165).

One engine computes the Hormozi ladder and nothing else improvises it:

  REVENUE − contra (refunds)
  − DELIVERY  = GROSS PROFIT      (gross margin %)
  − ACQUISITION = CONTRIBUTION    (contribution margin %)
  − OVERHEAD  = OPERATING (PBT)   (operating margin %)
  − TAX ACCRUAL (25% base-rate, a labelled planning estimate — the
                 accountant lodges) = NET PROFIT (net margin %)

THREE BASES, all live, all labelled, never blended:
  RECOGNISED  Xero P&L, CALENDAR months, mapped by pl_mapping. The books'
              own story: a hybrid of invoices (accrual) and Stripe payouts
              coded to Sales on the day they bank (proved in PL_DIAGNOSIS).
  MANAGEMENT  revenue from CONTRACTS — each active client's Monthly
              Recognized Revenue (the Health tab's own column, which is
              already contract ÷ term, so a PIF spreads over its term)
              pro-rated by days of service in the month; commissions accrued
              by the rulebook, not when paid; configured normalisations
              spread lumpy costs; one-offs flagged in the open; tax accrued
              monthly. The run-rate view.
  CASH        Stripe receipts ex-GST − the outflow bands. The runway view —
              lumpy by nature and never called a "margin" without its label.

Every window is a NAMED CALENDAR window. The rolling mid-month read that
produced "6.9%" is not computable here and is retired as a citable source.
All figures ex-GST (Stripe gross ÷ 1.1; Xero reports are already ex-GST).
GST and PAYG never enter the ladder — pass-through, not expenses.
"""
from __future__ import annotations

import calendar
import datetime as dt
import logging
import re

import kv_store
import pl_mapping
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_XERO_MONTH = "pl:xero:{m}"          # parsed calendar-month P&L, closed = forever
K_CUR_STAMP = "pl:xero:cur_stamp"
K_NORMALISATIONS = "pl:normalisations"  # [{account, monthly, note, by}]
_CUR_REFRESH_MIN = 30                  # the token chain is single-use; be gentle

FY26 = {"net": 11.5, "pbt": 15.3, "contribution": 42.9, "gross": 63.8,
        "delivery_pct": 36.2, "refunds_pct": 5.9,
        "note": "FY26 review baselines; gross = 1 − delivery $252,750 / $698,599"}
TAX_RATE = 0.25                        # base-rate entity — planning estimate


# ── months and windows ──────────────────────────────────────────────────────

def month_bounds(mkey: str) -> tuple[str, str]:
    y, m = int(mkey[:4]), int(mkey[5:7])
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def months_back(n: int, include_current: bool = False) -> list[str]:
    t = today_sydney()
    y, m = t.year, t.month
    if not include_current:
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _cur_month() -> str:
    t = today_sydney()
    return f"{t.year}-{t.month:02d}"


# ── the Xero calendar month (recognised raw) ────────────────────────────────

def xero_month(mkey: str, force: bool = False) -> dict:
    """Parsed Xero P&L for one CALENDAR month. Closed months cache forever (a
    closed P&L month is stable); the current month re-pulls at most every 30
    minutes — the refresh chain is single-use and deserves respect."""
    key = K_XERO_MONTH.format(m=mkey)
    cached = kv_store.get(key)
    cur = mkey == _cur_month()
    if cached and not force and not cur:
        return cached
    if cached and cur and not force:
        stamp = kv_store.get(K_CUR_STAMP) or {}
        age = _age_min(stamp.get("at"))
        if age is not None and age < _CUR_REFRESH_MIN:
            return cached
    import xero_pull
    start, end = month_bounds(mkey)
    if cur:
        end = str(today_sydney())
    pl = xero_pull.pull_pl_range(start, end)
    if not pl.get("ok"):
        if cached:
            return {**cached, "stale_note": pl.get("reason")}
        return {"ok": False, "month": mkey, "reason": pl.get("reason")}
    out = {"ok": True, "month": mkey, "window": {"start": start, "end": end},
           "revenue": pl.get("revenue"), "opex_line_items": pl.get("opex_line_items") or [],
           "cogs_line_items": pl.get("cogs_line_items") or [],
           "pulled_at": now_sydney().isoformat()}
    kv_store.put(key, out)
    if cur:
        kv_store.put(K_CUR_STAMP, {"at": out["pulled_at"]})
    return out


def _age_min(iso) -> float | None:
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(str(iso))
        return (now_sydney() - d).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        return None


# ── the ladder arithmetic (shared by every basis) ───────────────────────────

def _rungs(revenue: float, contra: float, delivery: float, acquisition: float,
           overhead: float, tax: float, tax_note: str) -> dict:
    net_rev = round(revenue - contra, 2)
    gross = round(net_rev - delivery, 2)
    contribution = round(gross - acquisition, 2)
    operating = round(contribution - overhead, 2)
    net = round(operating - tax, 2)

    def pct(x):
        return round(x / net_rev * 100, 1) if net_rev else None
    return {
        "revenue": round(revenue, 2), "contra_revenue": round(contra, 2),
        "net_revenue": net_rev,
        "delivery": round(delivery, 2), "gross_profit": gross,
        "gross_margin_pct": pct(gross),
        "acquisition": round(acquisition, 2), "contribution": contribution,
        "contribution_margin_pct": pct(contribution),
        "overhead": round(overhead, 2), "operating_profit": operating,
        "operating_margin_pct": pct(operating),
        "tax_accrual": round(tax, 2), "tax_note": tax_note,
        "net_profit": net, "net_margin_pct": pct(net),
    }


# ── RECOGNISED ──────────────────────────────────────────────────────────────

def recognised(mkey: str) -> dict:
    xm = xero_month(mkey)
    if not xm.get("ok"):
        return {"ok": False, "basis": "recognised", "month": mkey,
                "reason": xm.get("reason")}
    unmapped: list = []
    lines = pl_mapping.ladder_lines(
        (xm.get("cogs_line_items") or []) + (xm.get("opex_line_items") or []),
        xm.get("revenue"), unmapped_sink=unmapped)
    tax = lines["tax_statutory"]["total"]
    tax_note = ("Xero's own income-tax line" if tax else
                "no income tax booked in Xero this month — the accountant "
                "lodges annually; see the management basis for the accrual")
    out = {"ok": True, "basis": "recognised", "month": mkey,
           "window": xm.get("window"),
           **_rungs(lines["revenue"]["total"], lines["contra_revenue"]["total"],
                    lines["delivery"]["total"], lines["acquisition"]["total"],
                    lines["overhead"]["total"], tax, tax_note),
           "lines": lines, "unmapped_accounts": sorted(set(unmapped)),
           "provenance": "Xero P&L, calendar month, pl_mapping ladder",
           "as_of": xm.get("pulled_at")}
    if lines["unmapped"]["total"]:
        out["unmapped_note"] = (f"${lines['unmapped']['total']:,.2f} across "
                                f"{len(out['unmapped_accounts'])} unmapped "
                                f"account(s) — carried in plain sight, not binned")
    return out


# ── MANAGEMENT ──────────────────────────────────────────────────────────────

def _roster_rows() -> list[dict]:
    """Health-tab rows with name, status, start, end, MRR — header-named."""
    import sheet_mirror
    from config import FINANCE_SHEET_CONFIG
    rows = sheet_mirror.read_by_gid(1407663952) or \
        sheet_mirror._live_fetch(FINANCE_SHEET_CONFIG["sheet_id"],
                                 "Health (roster)", gid=1407663952)
    if not rows:
        return []
    header = [str(h or "").strip().lower() for h in rows[0]]

    def col(name):
        for i, h in enumerate(header):
            if name in h:
                return i
        return None

    i_start, i_end = col("start date"), col("end date")
    i_mrr, i_status = col("monthly recognized"), 1
    out = []
    for r in rows[1:]:
        if not (r and (r[0] or "").strip()):
            continue
        out.append({
            "name": (r[0] or "").strip(),
            "status": (r[i_status] if i_status < len(r) else "") or "",
            "start": _us_date(r[i_start]) if i_start is not None and i_start < len(r) else None,
            "end": _us_date(r[i_end]) if i_end is not None and i_end < len(r) else None,
            "mrr": _money(r[i_mrr]) if i_mrr is not None and i_mrr < len(r) else None,
        })
    return out


def _us_date(v) -> dt.date | None:
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", str(v or "").strip())
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(v or "").strip())
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _money(v) -> float | None:
    s = re.sub(r"[^0-9.]", "", str(v or ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def contract_revenue(mkey: str) -> dict:
    """Revenue from contracts for one calendar month: each client's Monthly
    Recognized Revenue (already contract ÷ term at source — a PIF spreads)
    pro-rated by days of service inside the month."""
    start_s, end_s = month_bounds(mkey)
    m0, m1 = dt.date.fromisoformat(start_s), dt.date.fromisoformat(end_s)
    days = (m1 - m0).days + 1
    clients, total = [], 0.0
    for r in _roster_rows():
        if r["mrr"] is None:
            continue
        s = r["start"] or m0
        e = r["end"] or m1
        lo, hi = max(s, m0), min(e, m1)
        if lo > hi:
            continue
        frac = ((hi - lo).days + 1) / days
        amt = round(r["mrr"] * frac, 2)
        total += amt
        clients.append({"client": r["name"], "mrr": r["mrr"],
                        "fraction": round(frac, 3), "amount": amt})
    return {"month": mkey, "total": round(total, 2), "clients": clients,
            "provenance": ("Health-tab Monthly Recognized Revenue "
                           "(contract ÷ term) × days of service in the month")}


def normalisations() -> list[dict]:
    return kv_store.get(K_NORMALISATIONS) or []


def set_normalisation(account: str, monthly: float, actor: str,
                      note: str = "") -> dict:
    ns = [n for n in normalisations()
          if pl_mapping._key(n.get("account")) != pl_mapping._key(account)]
    ns.append({"account": account, "monthly": round(float(monthly), 2),
               "note": note, "by": actor, "at": now_sydney().isoformat()})
    kv_store.put(K_NORMALISATIONS, ns)
    return {"ok": True, "normalisations": ns}


def management(mkey: str) -> dict:
    """The run-rate view. Contract revenue; costs from the recognised month,
    with commissions replaced by the rulebook's accrual, configured
    normalisations applied, one-offs flagged in the open, and tax accrued at
    25% of PBT (planning estimate — the accountant lodges)."""
    rec = recognised(mkey)
    if not rec.get("ok"):
        return {"ok": False, "basis": "management", "month": mkey,
                "reason": rec.get("reason")}
    rev = contract_revenue(mkey)
    # MTD: contract revenue pro-rates to TODAY, or the month-to-date margin
    # compares a full month of revenue against a part-month of costs and
    # flatters itself (caught live: 37.8% MTD vs a 27.8% projection).
    if mkey == _cur_month():
        t = today_sydney()
        days_in = calendar.monthrange(t.year, t.month)[1]
        frac = t.day / days_in
        rev = {**rev, "total": round(rev["total"] * frac, 2),
               "provenance": rev["provenance"]
               + f" · pro-rated to day {t.day} of {days_in}"}
    contra = rec["contra_revenue"]          # refunds recognised when issued

    adjustments: list[dict] = []

    # commissions: the rulebook's accrual for the month, never Xero's paid
    start_s, end_s = month_bounds(mkey)
    comm_booked = sum(i["amount"] for i in rec["lines"]["acquisition"]["items"]
                      if "commission" in i["account"].lower())
    comm_accrued, comm_note = comm_booked, "rulebook accrual unavailable — Xero's booked figure kept"
    try:
        import sales_cost
        sc = sales_cost.build(start_s, end_s)
        c = sc.get("commissions") or {}
        pieces = [c.get("total"), (sc.get("bounties") or {}).get("total"),
                  (sc.get("retainer") or {}).get("amount")]
        if c.get("total") is not None:
            comm_accrued = round(sum(p for p in pieces if p), 2)
            comm_note = "rulebook accrual (commissions + set bounties + manager retainer)"
    except Exception as e:  # noqa: BLE001
        logger.info("pl: sales_cost unavailable for %s: %s", mkey, e)
    if round(comm_accrued - comm_booked, 2):
        adjustments.append({"label": "commissions: accrued vs booked",
                            "amount": round(comm_accrued - comm_booked, 2),
                            "why": comm_note})
    acquisition = round(rec["acquisition"] - comm_booked + comm_accrued, 2)

    # configured normalisations (annual/quarterly costs spread monthly)
    delivery, overhead = rec["delivery"], rec["overhead"]
    for n in normalisations():
        akey = pl_mapping._key(n["account"])
        line = pl_mapping.classify(n["account"])["line"]
        if line not in ("delivery", "overhead"):
            continue
        booked = sum(i["amount"] for i in rec["lines"][line]["items"]
                     if pl_mapping._key(i["account"]).startswith(akey))
        delta = round(n["monthly"] - booked, 2)
        if delta:
            adjustments.append({"label": f"{n['account']}: normalised to "
                                         f"${n['monthly']:,.0f}/mo",
                                "amount": delta, "why": n.get("note") or "spread evenly"})
            if line == "delivery":
                delivery = round(delivery + delta, 2)
            else:
                overhead = round(overhead + delta, 2)

    # one-offs flagged in the open (kept in the totals, never hidden)
    flagged = _flag_one_offs(mkey, rec)

    # revenue basis delta, for the bridge
    rev_delta = round(rec["revenue"] - rev["total"], 2)

    pbt_rev = rev["total"]
    rungs = _rungs(pbt_rev, contra, delivery, acquisition, overhead, 0.0, "")
    pbt = rungs["operating_profit"]
    tax = round(max(pbt, 0.0) * TAX_RATE, 2)
    out = {"ok": True, "basis": "management", "month": mkey,
           "window": {"start": start_s, "end": end_s},
           **_rungs(pbt_rev, contra, delivery, acquisition, overhead, tax,
                    "25% base-rate accrual on operating profit — a planning "
                    "estimate; the accountant lodges"),
           "contract_revenue": rev,
           "adjustments": adjustments, "one_offs_flagged": flagged,
           "revenue_basis_delta": {
               "amount": rev_delta,
               "why": ("Xero recognised minus contract-based: invoiced "
                       "one-offs, AR raised in-month, and payout-lag coding "
                       "(see the bridge)")},
           "provenance": ("contract revenue (Health MRR × service days) · "
                          "rulebook commissions · configured normalisations · "
                          "25% tax accrual"),
           "as_of": rec.get("as_of")}
    return out


def _flag_one_offs(mkey: str, rec: dict) -> list[dict]:
    """A line well above its own recent run is FLAGGED, never silently
    smoothed: shown beside the ladder so 'why is this month heavy' has an
    answer with a name on it."""
    flags = []
    prior = [m for m in months_back(4) if m < mkey][:3]
    if not prior:
        return flags
    baseline: dict[str, list[float]] = {}
    for pm in prior:
        pr = kv_store.get(K_XERO_MONTH.format(m=pm))
        if not (pr or {}).get("ok"):
            continue
        for li in pr.get("opex_line_items") or []:
            baseline.setdefault(pl_mapping._key(li["label"]), []).append(
                float(li["amount"] or 0))
    for ln in ("delivery", "overhead", "acquisition"):
        for i in rec["lines"][ln]["items"]:
            hist = baseline.get(pl_mapping._key(i["account"]))
            if not hist:
                continue
            med = sorted(hist)[len(hist) // 2]
            if med > 0 and i["amount"] > max(2.5 * med, med + 1500):
                flags.append({"account": i["account"], "amount": i["amount"],
                              "usual": round(med, 2), "line": ln,
                              "note": "well above its 3-month median — a "
                                      "one-off, shown, not smoothed"})
    return flags


# ── CASH ────────────────────────────────────────────────────────────────────

def cash(mkey: str) -> dict:
    """Bank receipts − outflows. The runway view — labelled, never a margin."""
    start_s, end_s = month_bounds(mkey)
    receipts, n = None, 0
    try:
        import cash_truth
        charges = cash_truth._recent_charges(120) or []
        ins = [c for c in charges if start_s <= str(c["date"]) <= end_s]
        n = len(ins)
        receipts = round(sum(c["amount"] for c in ins) / 1.1, 2)
    except Exception as e:  # noqa: BLE001
        logger.info("pl cash: stripe unavailable: %s", e)
    bands = (kv_store.get("outflow:month_bands") or {}).get(mkey) or {}
    opex = bands.get("opex")
    taxes = bands.get("tax_statutory")
    net = (round(receipts - (opex or 0) - (taxes or 0), 2)
           if receipts is not None and opex is not None else None)
    return {"ok": receipts is not None, "basis": "cash", "month": mkey,
            "window": {"start": start_s, "end": end_s},
            "receipts_ex_gst": receipts, "receipt_count": n,
            "outflows": {"opex": opex, "tax_statutory": taxes},
            "net_cash": net,
            "label": ("bank receipts (Stripe, ex-GST) minus the outflow "
                      "bands — the runway view, not a margin"),
            "note": (None if receipts is not None else
                     "Stripe charges only reach back ~120 days — older "
                     "months have no cash basis here")}


# ── THE BRIDGE ──────────────────────────────────────────────────────────────

def bridge(mkey: str) -> dict:
    """Why the three bases differ for one month — every timing item in
    dollars, so 'why is this month different from the run-rate' is one
    table."""
    mg, rc, ca = management(mkey), recognised(mkey), cash(mkey)
    items = []
    if mg.get("ok") and rc.get("ok"):
        items.append({"between": "management → recognised",
                      "label": "revenue basis (contracts vs the books)",
                      "amount": round(rc["revenue"] - mg["revenue"], 2),
                      "why": mg["revenue_basis_delta"]["why"]})
        for a in mg.get("adjustments") or []:
            items.append({"between": "management → recognised",
                          "label": a["label"], "amount": -a["amount"],
                          "why": a["why"]})
        items.append({"between": "management → recognised",
                      "label": "income tax accrual (management only)",
                      "amount": round(mg["tax_accrual"] - rc["tax_accrual"], 2),
                      "why": "management accrues 25% monthly; Xero books tax "
                             "when the accountant does"})
        for f in mg.get("one_offs_flagged") or []:
            items.append({"between": "both", "label": f"one-off: {f['account']}",
                          "amount": round(f["amount"] - f["usual"], 2),
                          "why": f["note"]})
    if rc.get("ok") and ca.get("ok"):
        items.append({"between": "recognised → cash",
                      "label": "recognised revenue vs bank receipts",
                      "amount": round((ca.get("receipts_ex_gst") or 0)
                                      - rc["revenue"], 2),
                      "why": "AR raised but unpaid, bank-transfer receipts, "
                             "and Stripe payout lag"})
    return {"month": mkey, "items": items,
            "nets": {"management": mg.get("net_profit"),
                     "recognised": rc.get("net_profit"),
                     "cash": ca.get("net_cash")},
            "note": "every line is a timing or basis difference with a name — "
                    "the business is the same underneath"}


# ── NAMED WINDOWS ───────────────────────────────────────────────────────────

WINDOWS = ("mtd", "last_month", "t3", "t12", "fytd", "same_month_ly")


def _fy_start() -> str:
    t = today_sydney()
    y = t.year if t.month >= 7 else t.year - 1
    return f"{y}-07"


def collected_month(mkey: str) -> dict:
    """The ladder on WHAT LANDED for one calendar month — the management
    month's own costs (same basis, only collection differs)."""
    mg = management(mkey)
    if not mg.get("ok"):
        return {"ok": False, "basis": "collected", "month": mkey,
                "reason": mg.get("reason")}
    w0, w1 = month_bounds(mkey)
    if mkey == _cur_month():
        w1 = str(today_sydney())
    coll = collected_revenue(w0, w1)
    r = _rungs(coll["total"], mg["contra_revenue"], mg["delivery"],
               mg["acquisition"], mg["overhead"], 0.0, "")
    tax = round(max(r["operating_profit"], 0.0) * TAX_RATE, 2)
    out = {"ok": True, "basis": "collected", "month": mkey,
           "window": {"start": w0, "end": w1},
           **_rungs(coll["total"], mg["contra_revenue"], mg["delivery"],
                    mg["acquisition"], mg["overhead"], tax,
                    "25% accrual on this panel's own operating profit"),
           "collected": coll, "as_of": coll["as_of"],
           "provenance": ("collected revenue (Stripe receipts ex-GST) over "
                          "the management month's own costs — one cost "
                          "basis, only collection differs")}
    if not coll.get("reach_note", "").startswith("Stripe charges reach"):
        out["reach_warning"] = coll.get("reach_note")
    return out


def window(basis: str, name: str) -> dict:
    """The ladder for a NAMED calendar window. Multi-month windows sum the
    months; every output names its months in words."""
    fn = {"management": management, "recognised": recognised, "cash": cash,
          "collected": collected_month}[basis]
    cur = _cur_month()
    if name == "mtd":
        r = fn(cur)
        if r.get("ok") and basis == "management":
            r["projection"] = _project_month_end(r)
        r["window_words"] = f"{_mword(cur)} (month to date)"
        return r
    if name == "last_month":
        m = months_back(1)[0]
        r = fn(m)
        r["window_words"] = _mword(m)
        return r
    if name == "same_month_ly":
        ly = f"{int(cur[:4]) - 1}-{cur[5:7]}"
        r = fn(ly)
        r["window_words"] = _mword(ly) + " (same month last year)"
        return r
    months = {"t3": months_back(3), "t12": months_back(12),
              "fytd": [m for m in months_back(15) if m >= _fy_start()]}[name]
    return _sum_months(basis, fn, months, name)


def _mword(mkey: str) -> str:
    return dt.date.fromisoformat(mkey + "-01").strftime("%B %Y")


def _sum_months(basis, fn, months, name) -> dict:
    parts = [fn(m) for m in months]
    good = [p for p in parts if p.get("ok")]
    if not good:
        return {"ok": False, "basis": basis, "window": name,
                "reason": "; ".join(str(p.get("reason") or p.get("note"))
                                    for p in parts[:2])}
    if basis == "cash":
        rec = round(sum(p["receipts_ex_gst"] or 0 for p in good), 2)
        net = round(sum(p["net_cash"] or 0 for p in good if p["net_cash"] is not None), 2)
        return {"ok": True, "basis": basis, "window": name,
                "months": [p["month"] for p in good],
                "window_words": f"{_mword(good[-1]['month'])} → {_mword(good[0]['month'])}",
                "receipts_ex_gst": rec, "net_cash": net,
                "label": good[0]["label"],
                "missing_months": [p.get("month") for p in parts if not p.get("ok")]}
    keys = ("revenue", "contra_revenue", "delivery", "acquisition", "overhead",
            "tax_accrual")
    agg = {k: round(sum(p[k] for p in good), 2) for k in keys}
    out = {"ok": True, "basis": basis, "window": name,
           "months": [p["month"] for p in good],
           "window_words": f"{_mword(good[-1]['month'])} → {_mword(good[0]['month'])}",
           **_rungs(agg["revenue"], agg["contra_revenue"], agg["delivery"],
                    agg["acquisition"], agg["overhead"], agg["tax_accrual"],
                    good[0].get("tax_note", "")),
           "missing_months": [p.get("month") for p in parts if not p.get("ok")]}
    return out


def _project_month_end(mtd: dict) -> dict:
    """Month-end projection: revenue = the FULL month's contract schedule;
    costs = the trailing-3 average per rung. A projection, and it says so."""
    m = mtd["month"]
    full_rev = contract_revenue(m)["total"]
    t3 = window("management", "t3")
    if not t3.get("ok") or not t3.get("months"):
        return {"available": False, "note": "no trailing months to project costs from"}
    n = len(t3["months"])
    delivery = round(t3["delivery"] / n, 2)
    acquisition = round(t3["acquisition"] / n, 2)
    overhead = round(t3["overhead"] / n, 2)
    contra = round(t3["contra_revenue"] / n, 2)
    r = _rungs(full_rev, contra, delivery, acquisition, overhead, 0.0, "")
    tax = round(max(r["operating_profit"], 0.0) * TAX_RATE, 2)
    r = _rungs(full_rev, contra, delivery, acquisition, overhead, tax,
               "25% accrual on projected PBT")
    return {"available": True, **{k: r[k] for k in
            ("revenue", "net_profit", "net_margin_pct", "gross_margin_pct",
             "operating_profit")},
            "how": ("full-month contract revenue + trailing-3 average costs "
                    "per rung — a projection, labelled")}


# ── the margin the estate quotes ────────────────────────────────────────────

def gross_margin_for_ltgp() -> dict:
    """The Hormozi LTGP margin: GROSS (delivery only), never contribution.
    Trailing-3 management basis where computable; the FY26 63.8% is the
    labelled fallback."""
    try:
        t3 = window("management", "t3")
        gm = t3.get("gross_margin_pct")
        if t3.get("ok") and gm is not None and 20 <= gm <= 95:
            return {"pct": gm, "provenance":
                    f"management-basis gross margin, {t3['window_words']}"}
    except Exception as e:  # noqa: BLE001
        logger.info("ltgp margin: engine unavailable: %s", e)
    return {"pct": FY26["gross"], "provenance":
            "FY26 gross margin 63.8% (labelled fallback — delivery cost "
            "$252,750 of $698,599; contribution margin is NOT used: it "
            "already subtracts acquisition)"}


def summary() -> dict:
    """The Today tile + EDITH's P&L context: management MTD with projection,
    recognised last full month, the trailing-3 run-rate, FY26 beside."""
    mtd = window("management", "mtd")
    lm = window("recognised", "last_month")
    t3 = window("management", "t3")
    try:
        cvc = contracted_vs_collected()
    except Exception as e:  # noqa: BLE001
        logger.warning("contracted-vs-collected failed: %s", e)
        cvc = {"ok": False, "reason": str(e)[:120]}
    return {"management_mtd": _slim(mtd), "recognised_last_month": _slim(lm),
            "contracted_vs_collected": cvc,
            "run_rate_t3": _slim(t3), "fy26_baseline": FY26,
            "as_of": now_sydney().isoformat(),
            "bridge_last_month": bridge(months_back(1)[0]),
            "note": ("three bases, never blended: management = the run-rate "
                     "truth, recognised = the books, cash = the bank")}


def _slim(r: dict) -> dict:
    keys = ("ok", "basis", "month", "window", "window_words", "months",
            "revenue", "net_revenue", "gross_profit", "gross_margin_pct",
            "contribution", "contribution_margin_pct", "operating_profit",
            "operating_margin_pct", "tax_accrual", "net_profit",
            "net_margin_pct", "projection", "reason", "as_of")
    return {k: r[k] for k in keys if k in r}


# ── the cached summary the surfaces read (never computed on a page load) ────

K_SUMMARY = "pl:summary:cache"


def refresh_summary() -> dict:
    """Compute the summary on the LOOP and store it. A page load reads kv
    only — this function is the only thing that may pull Xero for the tile."""
    try:
        out = {"computed_at": now_sydney().isoformat(), "data": summary(),
               "error": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("pl summary refresh failed: %s", e)
        out = {"computed_at": now_sydney().isoformat(), "data": None,
               "error": str(e)[:160]}
    kv_store.put(K_SUMMARY, out)
    return out


def cached_summary() -> dict:
    return kv_store.get(K_SUMMARY) or {"data": None,
                                       "error": "not computed yet — first "
                                                "refresh pending"}


# ── EDITH: deterministic answers, template-filled from the engine ───────────

_MARGIN_RE = re.compile(
    r"\bnet (?:profit )?margin\b|\bprofit margin\b|\bgross margin\b|"
    r"\bhow profitable\b|\bnet profit\b(?!.*margin)", re.I)
_BRIDGE_RE = re.compile(
    r"why (?:is|was) (?:this|the|last) month (?:below|above|different|off|"
    r"under|over).{0,20}(run.?rate|usual|normal)|"
    r"\bexplain the bridge\b|\bbridge for\b", re.I)
_NOT_COMPUTED_RE = re.compile(
    r"\bebitda\b|\bby state\b|\bby city\b|\bper region\b|"
    r"\bebit\b|\bnpat by\b", re.I)


def _fmt_basis(r: dict, name: str) -> str:
    if not (r or {}).get("ok"):
        return f"{name}: unavailable ({(r or {}).get('reason') or 'not computed'})"
    words = r.get("window_words") or r.get("month") or ""
    line = (f"{name} ({words}): net "
            f"${r['net_profit']:,.0f} on ${r['net_revenue']:,.0f} = "
            f"{r['net_margin_pct']}% · gross {r['gross_margin_pct']}% · "
            f"operating {r['operating_margin_pct']}%")
    proj = r.get("projection")
    if proj and proj.get("available"):
        line += (f" · projected month-end net ${proj['net_profit']:,.0f} "
                 f"({proj['net_margin_pct']}%)")
    return line


def handle_margin_query(text: str):
    """'what's our net profit margin' → the three-basis answer, periods and
    as-of named, every number the engine's own. The travelling-read pattern:
    template-filled, never model-composed."""
    t = text or ""
    if _NOT_COMPUTED_RE.search(t):
        return ("That isn't a metric the engine computes — I won't improvise "
                "it. What I can give you: net, gross, operating and "
                "contribution margin on the management, recognised and cash "
                "bases, for any named calendar window."), True
    if not _MARGIN_RE.search(t):
        return None, False
    c = cached_summary()
    d = c.get("data")
    if not d:
        return ("The P&L engine hasn't computed a summary yet"
                + (f" ({c.get('error')})" if c.get("error") else "")
                + " — ask me again after the next refresh."), True
    lines = [
        _fmt_basis(d.get("management_mtd") or {}, "Management"),
        _fmt_basis(d.get("recognised_last_month") or {}, "Recognised"),
        _fmt_basis(d.get("run_rate_t3") or {}, "Run-rate"),
    ]
    fy = d.get("fy26_baseline") or {}
    lines.append(f"FY26 baseline: net {fy.get('net')}% · gross {fy.get('gross')}%.")
    lines.append(f"As of {str(d.get('as_of'))[:16]}. Bases are never blended — "
                 f"management is the run-rate truth, recognised is the books, "
                 f"cash is the bank.")
    return " ".join(lines), True


def handle_bridge_query(text: str):
    if not _BRIDGE_RE.search(text or ""):
        return None, False
    d = (cached_summary() or {}).get("data") or {}
    br = d.get("bridge_last_month") or {}
    items = br.get("items") or []
    if not items:
        return ("I don't have a computed bridge yet — ask again after the "
                "next refresh."), True
    nets = br.get("nets") or {}
    parts = [f"{i['label']}: ${i['amount']:,.0f} ({i['why']})" for i in items[:6]]
    return (f"The bridge for {_mword(br['month'])}: management net "
            f"${(nets.get('management') or 0):,.0f} vs recognised "
            f"${(nets.get('recognised') or 0):,.0f} vs cash "
            f"${(nets.get('cash') or 0):,.0f}. The differences, named: "
            + "; ".join(parts) + "."), True


# ── IF EVERYONE PAYS vs WHAT ACTUALLY LANDED (#166) ─────────────────────────
# Rydel: "the gap between them is the money owed." Two panels, ONE cost
# basis — the management-basis normalised costs for the window — so the only
# thing that differs is collection.

def collected_revenue(w0: str, w1: str, charges: list | None = None) -> dict:
    """Client cash landed in [w0, w1], ex-GST. Stripe succeeded charges net
    of refunds (the reader nets them and drops fully-refunded charges);
    transfers and non-client bank movements never appear in the charge list.
    R-CASH: receipts only, never derived. Pass `charges` to share one pull
    across several windows — the two-panel computation reads five windows
    and one pull serves them all."""
    if charges is None:
        import cash_truth
        charges = cash_truth._recent_charges(120) or []
    ins = [c for c in charges if w0 <= str(c["date"]) <= w1]
    gross = round(sum(c["amount"] for c in ins), 2)
    stamp = (kv_store.get("stripe:last_pull") or {}).get("at")
    return {"window": {"start": w0, "end": w1},
            "window_words": f"{_dword(w0)} → {_dword(w1)}",
            "gross": gross, "total": round(gross / 1.1, 2), "count": len(ins),
            "as_of": stamp,
            "provenance": ("Stripe succeeded charges net of refunds, "
                           "receipt-dated, ÷ 1.1 to ex-GST — client payments "
                           "only; transfers and refunds never count"),
            "reach_note": ("Stripe charges reach back ~120 days"
                           if w0 >= str(today_sydney() - dt.timedelta(days=120))
                           else "window is beyond Stripe's 120-day reach — partial")}


def _dword(iso: str) -> str:
    return dt.date.fromisoformat(str(iso)[:10]).strftime("%-d %b")


def _t3_avg_costs() -> dict | None:
    t3 = window("management", "t3")
    if not t3.get("ok") or not t3.get("months"):
        return None
    n = len(t3["months"])
    return {k: round(t3[k] / n, 2) for k in
            ("contra_revenue", "delivery", "acquisition", "overhead")}


def contracted_vs_collected() -> dict:
    """The two panels, the gap, the reconciliation, the two projections."""
    cur = _cur_month()
    start_s, _end_s = month_bounds(cur)
    t = today_sydney()

    # PANEL A — IF EVERYONE PAYS: the management MTD ladder (contracted
    # revenue pro-rated to today; costs booked-to-date, normalised)
    mg = management(cur)
    if not mg.get("ok"):
        return {"ok": False, "reason": mg.get("reason")}
    full_contract = contract_revenue(cur)["total"]

    # PANEL B — WHAT ACTUALLY LANDED, on the SAME costs (one Stripe pull
    # serves every window below)
    import cash_truth
    _charges = cash_truth._recent_charges(120) or []
    coll_mtd = collected_revenue(start_s, str(t), charges=_charges)
    costs = {k: mg[k] for k in ("contra_revenue", "delivery", "acquisition",
                                "overhead")}
    b_mtd = _rungs(coll_mtd["total"], costs["contra_revenue"],
                   costs["delivery"], costs["acquisition"], costs["overhead"],
                   0.0, "")
    tax_b = round(max(b_mtd["operating_profit"], 0.0) * TAX_RATE, 2)
    b_mtd = _rungs(coll_mtd["total"], costs["contra_revenue"],
                   costs["delivery"], costs["acquisition"], costs["overhead"],
                   tax_b, "25% accrual on this panel's own operating profit")
    b_mtd["window_words"] = f"{_mword(cur)} (month to date, collected)"
    b_mtd["as_of"] = coll_mtd["as_of"]
    b_mtd["collected"] = coll_mtd

    # last 30 days, dated — run-rate costs, assumption stated
    w30_0 = str(t - dt.timedelta(days=29))
    coll_30 = collected_revenue(w30_0, str(t), charges=_charges)
    avg = _t3_avg_costs()
    b_30 = None
    if avg:
        r = _rungs(coll_30["total"], avg["contra_revenue"], avg["delivery"],
                   avg["acquisition"], avg["overhead"], 0.0, "")
        tax30 = round(max(r["operating_profit"], 0.0) * TAX_RATE, 2)
        b_30 = _rungs(coll_30["total"], avg["contra_revenue"], avg["delivery"],
                      avg["acquisition"], avg["overhead"], tax30,
                      "25% accrual on this panel's own operating profit")
        b_30["window_words"] = coll_30["window_words"]
        b_30["as_of"] = coll_30["as_of"]
        b_30["collected"] = coll_30
        b_30["cost_note"] = ("costs are the trailing-3 monthly average — a "
                             "dated 30-day window has no booked month of its "
                             "own; the assumption is stated, not hidden")

    # THE GAP — the money owed for this month so far
    gap = round(mg["revenue"] - coll_mtd["total"], 2)
    pct_collected = (round(coll_mtd["total"] / mg["revenue"] * 100, 1)
                     if mg["revenue"] else None)

    # reconciliation to AR
    recon = _reconcile_gap_to_ar(gap)

    # PROJECTIONS
    proj_a = mg.get("projection") or _project_month_end(mg)
    proj_a = {**proj_a, "label": "optimistic — assumes every contracted "
                                 "dollar is paid by month end"}
    proj_b = _realistic_projection(full_contract, coll_mtd["total"], cur,
                                   charges=_charges)

    # collected margin on the CONTRACTED denominator (drawer comparability)
    on_contracted = (round(b_mtd["net_profit"] / mg["revenue"] * 100, 1)
                     if mg["revenue"] else None)

    return {"ok": True,
            "contracted": {**_slim(mg),
                           "window_words": f"{_mword(cur)} (month to date)",
                           "full_month_contracted": full_contract},
            "collected_mtd": {k: b_mtd[k] for k in
                              ("revenue", "net_profit", "net_margin_pct",
                               "gross_margin_pct", "operating_profit",
                               "tax_accrual", "window_words", "as_of",
                               "collected")},
            "collected_30d": (None if not b_30 else
                              {k: b_30[k] for k in
                               ("revenue", "net_profit", "net_margin_pct",
                                "gross_margin_pct", "operating_profit",
                                "tax_accrual", "window_words", "as_of",
                                "collected", "cost_note")}),
            "same_cost_basis": costs,
            "gap": {"amount": gap, "pct_collected": pct_collected,
                    "line": (f"Collected so far this month: "
                             f"${coll_mtd['total']:,.0f} of "
                             f"${mg['revenue']:,.0f} contracted "
                             f"({pct_collected}%)" if pct_collected is not None
                             else "gap not computable"),
                    "meaning": "contracted minus collected — the money owed"},
            "ar_reconciliation": recon,
            "projections": {"optimistic": proj_a, "realistic": proj_b},
            "inputs_as_of": {
                "contracted": {"roster": _roster_stamp(), "xero": mg.get("as_of")},
                "collected": {"stripe": coll_mtd["as_of"]}},
            "fy26_baseline_net_pct": FY26["net"]}


def _roster_stamp():
    try:
        import sheet_mirror
        rows = sheet_mirror.get_sources() or []
        return max((r.get("last_sync_at") for r in rows
                    if r.get("last_sync_at")), default=None)
    except Exception:  # noqa: BLE001
        return None


def _reconcile_gap_to_ar(gap: float) -> dict:
    """The gap should be the AR — reconciled, with the residual NAMED."""
    try:
        import receivables
        ar = receivables.build_ar()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": f"AR unavailable: {str(e)[:80]}"}
    total_ar = ar.get("total_outstanding")
    rows = sorted((r for r in ar.get("rows") or []
                   if (r.get("outstanding") or 0) > 0),
                  key=lambda r: -(r.get("outstanding") or 0))
    top = [{"client": r.get("client"), "outstanding": r.get("outstanding"),
            "days_overdue": r.get("days_overdue")} for r in rows[:5]]
    residual = round((total_ar or 0) - gap, 2) if total_ar is not None else None
    return {"ok": True, "ar_outstanding": total_ar, "gap": gap,
            "residual": residual,
            "residual_note": ("AR includes months BEFORE this one and "
                              "bank-transfer clients whose receipts don't "
                              "flow through Stripe; the gap is this month's "
                              "contracted-vs-collected only — the two agree "
                              "when both effects are counted"),
            "top_unpaid": top,
            "door": "/dashboard/view/receivables"}


def _realistic_projection(full_contract: float, collected_so_far: float,
                          cur: str, charges: list | None = None) -> dict:
    """Month-end margin if collections continue at the trailing pace: the
    trailing-3 collection rate applied to the whole contracted schedule,
    floored at what has already landed."""
    rates = []
    for m in months_back(3):
        w0, w1 = month_bounds(m)
        c = collected_revenue(w0, w1, charges=charges)
        k = contract_revenue(m)["total"]
        if k and c.get("reach_note", "").startswith("Stripe charges reach"):
            rates.append(min(c["total"] / k, 1.5))
    if not rates:
        return {"available": False,
                "note": "no trailing months inside Stripe's reach"}
    rate = round(sum(rates) / len(rates), 3)
    projected_collected = round(max(collected_so_far, rate * full_contract), 2)
    avg = _t3_avg_costs()
    if not avg:
        return {"available": False, "note": "no trailing costs to project"}
    r = _rungs(projected_collected, avg["contra_revenue"], avg["delivery"],
               avg["acquisition"], avg["overhead"], 0.0, "")
    tax = round(max(r["operating_profit"], 0.0) * TAX_RATE, 2)
    r = _rungs(projected_collected, avg["contra_revenue"], avg["delivery"],
               avg["acquisition"], avg["overhead"], tax, "25% accrual")
    return {"available": True, "revenue": projected_collected,
            "net_profit": r["net_profit"], "net_margin_pct": r["net_margin_pct"],
            "collection_rate": rate,
            "label": (f"realistic — collections continue at the trailing-3 "
                      f"pace ({rate * 100:.0f}% of contracted), trailing-3 "
                      f"average costs")}


_CVC_RE = re.compile(
    r"if everyone pays|actually landed|collected margin|margin.{0,20}"
    r"(vs|versus).{0,20}(landed|collected|paid)|what.{0,10}landed.{0,25}margin|"
    r"money (?:we'?re|we are|you'?re) owed", re.I)


def handle_cvc_query(text: str):
    """'what's our margin if everyone pays vs what's landed' → both numbers,
    both windows, the gap, the top unpaid clients — every figure the
    engine's own."""
    if not _CVC_RE.search(text or ""):
        return None, False
    d = (cached_summary() or {}).get("data") or {}
    cvc = d.get("contracted_vs_collected") or {}
    if not cvc.get("ok"):
        return ("The contracted-vs-collected read isn't computed yet"
                + (f" ({cvc.get('reason')})" if cvc.get("reason") else "")
                + " — ask me again after the next refresh."), True
    mg = cvc.get("contracted") or {}
    b = cvc.get("collected_mtd") or {}
    b30 = cvc.get("collected_30d") or {}
    gap = cvc.get("gap") or {}
    recon = cvc.get("ar_reconciliation") or {}
    proj = cvc.get("projections") or {}
    parts = [
        (f"If everyone pays ({mg.get('window_words')}): net margin "
         f"{mg.get('net_margin_pct')}% on ${mg.get('revenue'):,.0f} "
         f"contracted."),
        (f"What actually landed ({b.get('window_words')}): "
         f"{b.get('net_margin_pct')}% on ${b.get('revenue'):,.0f} collected"
         + (f"; last 30 days ({b30.get('window_words')}): "
            f"{b30.get('net_margin_pct')}%" if b30 else "") + "."),
        gap.get("line", "") + " — the gap is the money owed.",
    ]
    top = recon.get("top_unpaid") or []
    if top:
        parts.append("Top unpaid: " + "; ".join(
            f"{u['client']} ${u['outstanding']:,.0f}"
            + (f" ({u['days_overdue']}d overdue)" if u.get("days_overdue") else "")
            for u in top[:3]) + ".")
    pa, pb = proj.get("optimistic") or {}, proj.get("realistic") or {}
    if pa.get("available") or pb.get("available"):
        parts.append(
            "Month-end: "
            + (f"{pa.get('net_margin_pct')}% optimistic (all contracted paid)"
               if pa.get("available") else "")
            + (" · " if pa.get("available") and pb.get("available") else "")
            + (f"{pb.get('net_margin_pct')}% realistic (trailing collection "
               f"pace {int((pb.get('collection_rate') or 0) * 100)}%)"
               if pb.get("available") else "") + ".")
    parts.append("Same costs on both panels — only collection differs.")
    return " ".join(p for p in parts if p), True
