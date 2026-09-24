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


def window(basis: str, name: str) -> dict:
    """The ladder for a NAMED calendar window. Multi-month windows sum the
    months; every output names its months in words."""
    fn = {"management": management, "recognised": recognised, "cash": cash}[basis]
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
    return {"management_mtd": _slim(mtd), "recognised_last_month": _slim(lm),
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
