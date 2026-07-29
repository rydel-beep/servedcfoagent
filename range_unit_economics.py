"""
range_unit_economics.py
-----------------------
LTGP:CAC, ROAS, LTV:CAC for ANY date range — window-consistent BY CONSTRUCTION.

A single (range_start, range_end) drives every input, so mixing windows (the #1 CAC
failure mode) is structurally impossible. Reads from the Postgres mirror (DB-speed).

Locked definitions (Rydel-confirmed):
- CAC (loaded) = (Meta ad spend + closer comms + setter comms) / closes — all in-window.
- LTGP = avg CONTRACT VALUE × gross margin %.   LTGP:CAC = LTGP / CAC.
- ROAS = CASH COLLECTED in-window / Meta ad spend (ad-spend-only; revenue basis = cash).
- LTV  = full contract value (no margin).        LTV:CAC = avg contract value / CAC.
- Attribution = SPEND-IN-WINDOW (Meta spend that occurred in the window).

Date columns (mirror):
- closes/contract/cash/closer-comm: Lead-to-Cash Tracker, windowed by Close Date.
- setter comms: SETTER PAYOUT LOG, windowed by payout date (no close-date in the log).
- ad spend: Meta daily store / live, by spend date.
Gross margin is a P&L rate (Xero), applied to the window's contract value.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

logger = logging.getLogger(__name__)

# SETTER PAYOUT LOG positional columns (by-name layout, from the loaded-CAC build).
_PL_SETTER, _PL_CASH, _PL_FEE, _PL_BONUS, _PL_NOTES = 2, 4, 5, 6, 9
_SETTERS = {"coby", "maran", "unattributed"}


def _money(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "").replace("₱", "")
    if not s or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


_MONTH_NAMES = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"]) if i}
_MONTH_NAMES.update({m[:3]: i for m, i in list(_MONTH_NAMES.items())})


def _date(s) -> dt.date | None:
    """Parse a date in any of the tracker's formats: '6/24/2026', '2026-06-24',
    '06/23/2026 payout', or the Set Date text form '29 June 26' / '4 June 2026'."""
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(s))
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))  # M/D/Y
        except ValueError:
            return None
    m = re.match(r"\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})", str(s))  # '29 June 26'
    if m and m.group(2).lower() in _MONTH_NAMES:
        try:
            y = int(m.group(3))
            return dt.date(y + 2000 if y < 100 else y, _MONTH_NAMES[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    return None


def _ltc_col_map(header: list[str]) -> dict:
    """Resolve Lead-to-Cash Tracker column indices by header name (robust to reordering)."""
    idx = {}
    outcome_cols = []  # the sheet has TWO "Call Outcome" cols: setter (early) + closer (later)
    for k, c in enumerate(header):
        cl = (c or "").lower()
        if "input date" in cl and "input_date" not in idx:
            idx["input_date"] = k
        elif "close date" in cl and "close_date" not in idx:
            idx["close_date"] = k
        elif "contract value" in cl and "contract" not in idx:
            idx["contract"] = k
        elif "cash collected" in cl and "cash" not in idx:
            idx["cash"] = k
        elif "commission closer" in cl and "closer" not in idx:
            idx["closer"] = k
        elif "set date" in cl and "set_date" not in idx:
            idx["set_date"] = k
        elif "show status" in cl and "show_status" not in idx:
            idx["show_status"] = k
        elif "call outcome" in cl:
            outcome_cols.append(k)
        elif "offer sold" in cl and "offer" not in idx:
            idx["offer"] = k
        elif "lead name" in cl and "name" not in idx:
            idx["name"] = k
    # The CLOSER's Call Outcome (which carries "won") is in the closer funnel — the last
    # Call Outcome at/before Close Date, NOT the setter's earlier "SET/DQ" one (col 16).
    if outcome_cols:
        cd = idx.get("close_date")
        before = [k for k in outcome_cols if cd is None or k < cd]
        idx["outcome"] = max(before) if before else max(outcome_cols)
        idx["setter_outcome"] = min(outcome_cols)  # the early setter "SET/DQ" one
    return idx


def _read_ltc_clean():
    """Lead-to-Cash rows via the mirror (live fallback), REPOINTED to the clean view (test leads
    voided) — the one classification engine, so unit-econ never counts test rows."""
    import sheet_mirror
    rows = sheet_mirror.read_by_name("Lead-to-Cash Tracker")
    if rows is None:
        from sales_analytics_pull import _fetch_tab
        rows = _fetch_tab("Lead-to-Cash Tracker")
    try:
        import test_leads
        return test_leads.clean_tracker_rows(rows)
    except Exception:
        return rows


def _ltc_in_window(w0: dt.date, w1: dt.date) -> dict:
    """Won deals closed in [w0,w1] from the mirror: count + contract + cash + closer comms."""
    rows = _read_ltc_clean()
    out = {"closes": 0, "contract": 0.0, "cash": 0.0, "closer_comm": 0.0, "deals": []}
    if not rows:
        return out
    hi = next((i for i, r in enumerate(rows[:8]) if any("close date" in (c or "").lower() for c in r)), 0)
    cm = _ltc_col_map(rows[hi])
    if "close_date" not in cm:
        return out
    for r in rows[hi + 1:]:
        cd = _date(r[cm["close_date"]]) if cm["close_date"] < len(r) else None
        if cd is None or not (w0 <= cd <= w1):
            continue
        # A close = Call Outcome == "won" (the canonical definition used across the agent),
        # NOT merely "has a contract value". Keeps the count transparent + per-deal.
        outcome = (r[cm["outcome"]].strip().lower() if cm.get("outcome", 99) < len(r) else "")
        if outcome != "won":
            continue
        contract = _money(r[cm["contract"]]) if cm.get("contract", 99) < len(r) else None
        cash = _money(r[cm["cash"]]) if cm.get("cash", 99) < len(r) else None
        closer = _money(r[cm["closer"]]) if cm.get("closer", 99) < len(r) else None
        name = (r[cm["name"]].strip() if cm.get("name", 99) < len(r) else "")
        out["closes"] += 1
        out["contract"] += contract or 0.0
        out["cash"] += cash or 0.0
        out["closer_comm"] += closer or 0.0
        out["deals"].append({"name": name, "close_date": str(cd),
                             "contract": contract or 0.0, "cash": cash or 0.0})
    out["contract"] = round(out["contract"], 2)
    out["cash"] = round(out["cash"], 2)
    out["closer_comm"] = round(out["closer_comm"], 2)
    return out


def _setter_comm_in_window(w0: dt.date, w1: dt.date) -> float:
    """Setter comms ($50/set + 5% cash) from the SETTER PAYOUT LOG, windowed by payout date."""
    import sheet_mirror
    rows = sheet_mirror.read_by_name("SETTER PAYOUT LOG")
    if rows is None:
        try:
            from loaded_cac import _TAB_NAME  # noqa
            import csv, io, requests
            from config import SHEET_CONFIG, HTTP_TIMEOUT
            sid = SHEET_CONFIG["sheet_id"]
            rows = list(csv.reader(io.StringIO(requests.get(
                f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=SETTER%20PAYOUT%20LOG",
                timeout=(5, HTTP_TIMEOUT)).text)))
        except Exception:
            rows = None
    if not rows:
        return 0.0
    total = 0.0
    for r in rows:
        if len(r) <= _PL_NOTES:
            continue
        if (r[_PL_SETTER].strip().lower() if len(r) > _PL_SETTER else "") not in _SETTERS:
            continue
        fee = _money(r[_PL_FEE]) or 0.0
        bonus = _money(r[_PL_BONUS]) or 0.0
        if fee == 0 and bonus == 0:
            continue
        d = _date(r[_PL_NOTES])
        if d is not None and w0 <= d <= w1:
            total += fee + bonus
    return round(total, 2)


def _gross_margin() -> float | None:
    from snapshot import load_persisted
    snap = load_persisted() or {}
    return (snap.get("xero") or {}).get("gross_margin_pct")


def cohort_funnel(w0: dt.date, w1: dt.date) -> dict:
    """The COHORT view: of the leads whose Input Date fell in [w0,w1], how many got set,
    showed, and closed (won) — and the lead→close conversion.

    This is a DIFFERENT lens to the money view: it asks "how is this window's lead flow
    converting?" (counted by lead Input Date), where unit_economics asks "what closed in
    this window and what did it cost?" (counted by Close Date). The two legitimately differ
    — e.g. a deal closed this month was usually generated by an earlier lead cohort.
    Matches the Team Scorecard's lead→close basis (its 27→…→4 week = 14.8%).
    """
    rows = _read_ltc_clean()   # clean view — test leads voided from the funnel
    out = {"leads_in": 0, "sets": 0, "shows": 0, "closes": 0,
           "lead_to_set_pct": None, "set_to_show_pct": None, "show_to_close_pct": None,
           "lead_to_close_pct": None,
           "basis": "by lead Input Date (cohort) — 'how is this window's lead flow converting?'"}
    if not rows:
        return out
    hi = next((i for i, r in enumerate(rows[:8]) if any("close date" in (c or "").lower() for c in r)), 0)
    cm = _ltc_col_map(rows[hi])
    if "input_date" not in cm:
        return out
    for r in rows[hi + 1:]:
        idate = _date(r[cm["input_date"]]) if cm["input_date"] < len(r) else None
        if idate is None or not (w0 <= idate <= w1):
            continue
        out["leads_in"] += 1
        if cm.get("setter_outcome", 99) < len(r) and r[cm["setter_outcome"]].strip().upper() == "SET":
            out["sets"] += 1
        if cm.get("show_status", 99) < len(r) and r[cm["show_status"]].strip().lower() == "showed":
            out["shows"] += 1
        if cm.get("outcome", 99) < len(r) and r[cm["outcome"]].strip().lower() == "won":
            out["closes"] += 1
    li, st, sh, cl = out["leads_in"], out["sets"], out["shows"], out["closes"]
    if li:
        out["lead_to_set_pct"] = round(100 * st / li, 1)
        out["lead_to_close_pct"] = round(100 * cl / li, 1)
    if st:
        out["set_to_show_pct"] = round(100 * sh / st, 1)
    if sh:
        out["show_to_close_pct"] = round(100 * cl / sh, 1)
    return out


def unit_economics(range_start: str, range_end: str) -> dict:
    """LTGP:CAC, ROAS, LTV:CAC for [range_start, range_end] (ISO, inclusive). One window, every input.

    Returns ratios + full component breakdown + caveats. Never divides by zero.
    """
    try:
        w0 = dt.date.fromisoformat(range_start)
        w1 = dt.date.fromisoformat(range_end)
    except (TypeError, ValueError):
        return {"error": "invalid range"}

    import meta_spend
    ltc = _ltc_in_window(w0, w1)
    setter_comm = _setter_comm_in_window(w0, w1)
    meta = meta_spend.spend_in_range(range_start, range_end)
    ad_spend = meta.get("spend")
    margin = _gross_margin()

    closes = ltc["closes"]
    contract_total = ltc["contract"]
    cash_total = ltc["cash"]
    closer_comm = ltc["closer_comm"]
    days = (w1 - w0).days + 1

    caveats = []
    if closes == 0:
        caveats.append("No closes in this window — CAC / LTGP:CAC / LTV:CAC are undefined.")
    if closes and closes < 3:
        caveats.append(f"Only {closes} close(s) — small sample, the ratios are volatile.")
    if ad_spend is None:
        caveats.append("Meta ad spend unavailable for this window — CAC/ROAS incomplete.")
    elif ad_spend == 0 and closes:
        caveats.append("Spend reads $0 in this window — verify the Meta range.")
    if days < 7:
        caveats.append(f"Short window ({days}d) — treat as indicative.")

    comp = {
        "window": {"start": range_start, "end": range_end, "days": days},
        "closes": closes,
        "ad_spend": ad_spend, "ad_spend_source": meta.get("source"),
        "closer_comm": closer_comm, "setter_comm": setter_comm,
        "contract_value_total": contract_total,
        "avg_contract": round(contract_total / closes, 2) if closes else None,
        "cash_collected_total": cash_total,
        "gross_margin_pct": margin,
        "attribution": "spend-in-window", "roas_revenue_basis": "contracted",
        "new_deal_cash": cash_total,  # cash from won deals in-window ("cash collected" per Rydel)
        "ad_spend_label": "Meta-only (Google not yet integrated)",
        "as_of": (load_persisted_as_of()),
    }

    cac = ltgp_cac = roas = ltv_cac = None
    if closes:
        total_acq = (ad_spend or 0) + closer_comm + setter_comm
        cac = round(total_acq / closes, 2)
        comp["cac_loaded"] = cac
        comp["cac_breakdown"] = (f"ad ${ad_spend or 0:,.0f} + closer ${closer_comm:,.0f} + "
                                 f"setter ${setter_comm:,.0f} = ${total_acq:,.0f} ÷ {closes} closes")
        if margin is not None and comp["avg_contract"]:
            ltgp = comp["avg_contract"] * (margin / 100)
            comp["ltgp"] = round(ltgp, 2)
            if cac > 0:
                ltgp_cac = round(ltgp / cac, 2)
                ltv_cac = round(comp["avg_contract"] / cac, 2)
        if ad_spend and ad_spend > 0:
            # ROAS = CONTRACTED revenue ÷ Meta spend (Rydel-locked 2026-07-03; the single ROAS).
            roas = round(contract_total / ad_spend, 2)
            comp["roas_breakdown"] = (f"${contract_total:,.0f} contracted ÷ ${ad_spend:,.0f} Meta spend")

    return {
        "ltgp_cac": ltgp_cac,
        "roas": roas,
        "ltv_cac": ltv_cac,
        "cac_loaded": cac,
        "components": comp,
        "cohort": cohort_funnel(w0, w1),  # the lead-Input-Date conversion view, alongside the money view
        "caveats": caveats,
        "degraded": meta.get("degraded", []),
    }


def load_persisted_as_of():
    try:
        from snapshot import load_persisted
        return (load_persisted() or {}).get("generated_at")
    except Exception:
        return None


# ── Natural-language range parsing (voice + text) ────────────────────────────

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"]) if i}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})


def _month_range(year: int, month: int, today: dt.date) -> tuple[dt.date, dt.date, str]:
    start = dt.date(year, month, 1)
    end = dt.date(year + (month // 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    end = min(end, today)  # cap a current/partial month at today
    label = start.strftime("%B %Y")
    return start, end, label


def parse_range(text: str, today: dt.date) -> tuple[dt.date, dt.date, str] | None:
    """Parse ONE date range from natural language. Returns (start, end, label) or None."""
    t = (text or "").lower().strip()

    m = re.search(r"between\s+(\d{4}-\d{1,2}-\d{1,2})\s+and\s+(\d{4}-\d{1,2}-\d{1,2})", t)
    if not m:
        m = re.search(r"from\s+(\d{4}-\d{1,2}-\d{1,2})\s+to\s+(\d{4}-\d{1,2}-\d{1,2})", t)
    if m:
        s, e = _date(m.group(1)), _date(m.group(2))
        if s and e:
            return s, e, f"{s} to {e}"

    if re.search(r"\b(ytd|year[\s-]?to[\s-]?date)\b", t):
        return dt.date(today.year, 1, 1), today, f"YTD {today.year}"

    mm = re.search(r"last\s+(\d+)\s*(day|week|month)s?", t)
    if mm:
        n = int(mm.group(1)); unit = mm.group(2)
        days = n * (7 if unit == "week" else 30 if unit == "month" else 1)
        return today - dt.timedelta(days=days - 1), today, f"last {n} {unit}{'s' if n > 1 else ''}"
    if re.search(r"\b(last|past|trailing)\s+30\s*days?\b", t):
        return today - dt.timedelta(days=29), today, "last 30 days"

    if re.search(r"\bthis month\b", t):
        return _month_range(today.year, today.month, today)
    if re.search(r"\blast month\b", t):
        pm = today.month - 1 or 12
        py = today.year if today.month > 1 else today.year - 1
        return _month_range(py, pm, today)
    if re.search(r"\bthis week\b", t):
        s = today - dt.timedelta(days=today.weekday())
        return s, today, "this week"
    if re.search(r"\blast week\b", t):
        s = today - dt.timedelta(days=today.weekday() + 7)
        return s, s + dt.timedelta(days=6), "last week"
    if re.search(r"\b(today)\b", t):
        return today, today, "today"
    if re.search(r"\byesterday\b", t):
        y = today - dt.timedelta(days=1)
        return y, y, "yesterday"

    mq = re.search(r"\bq([1-4])(?:\s+(\d{4}))?\b", t) or (re.search(r"\b(this|last) quarter\b", t) and None)
    if mq:
        q = int(mq.group(1)); yr = int(mq.group(2)) if mq.group(2) else today.year
        sm = (q - 1) * 3 + 1
        s = dt.date(yr, sm, 1)
        e = dt.date(yr + (sm + 2) // 12, ((sm + 2) % 12) + 1, 1) - dt.timedelta(days=1)
        return s, min(e, today), f"Q{q} {yr}"

    # "in May" / "May 2026" / bare month name
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            ym = re.search(rf"{name}\s+(\d{{4}})", t)
            yr = int(ym.group(1)) if ym else today.year
            # if the month is in the future for this year, assume last year
            if not ym and num > today.month:
                yr -= 1
            return _month_range(yr, num, today)
    return None


_METRIC_RE = re.compile(
    r"(ltgp[\s:/-]*cac|ltgp[\s-]*to[\s-]*cac|ltv[\s:/-]*cac|roas|return on ad spend|"
    r"\bcac\b|loaded cac|unit econ\w*|economics)", re.I)
_COMPARE_RE = re.compile(r"\b(vs\.?|versus|compared? to|compare)\b", re.I)
_COHORT_RE = re.compile(
    r"(cohort|converting|conversion rate|lead[\s-]*flow|lead[\s-]*to[\s-]*close|"
    r"how (are|were|is).*(lead|leads).*(convert|doing))", re.I)


def _cohort_reply(cf: dict, label: str) -> str:
    li = cf.get("leads_in", 0)
    if not li:
        return f"No leads with an Input Date in {label} — nothing to convert yet."
    pct = cf.get("lead_to_close_pct")
    return (f"Cohort for {label} (by lead Input Date): {li} leads in → {cf.get('sets', 0)} set → "
            f"{cf.get('shows', 0)} showed → {cf.get('closes', 0)} closed. "
            f"Lead→close {pct}%. (This is conversion of the window's NEW leads — distinct from the "
            f"money view, which counts deals that CLOSED in the window.)")


def _fmt_x(v):
    return f"{v}×" if v is not None else "n/a"


def _one_line(metric: str, res: dict, label: str) -> str:
    c = res["components"]
    if metric == "roas":
        v = res["roas"]
        if v is None:
            return f"ROAS for {label}: n/a ({'; '.join(res['caveats']) or 'no spend'})."
        return (f"ROAS for {label}: {v}× — ${c['contract_value_total']:,.0f} contracted revenue ÷ "
                f"${c['ad_spend'] or 0:,.0f} Meta spend (contracted basis).")
    if metric.startswith("ltv"):
        v = res["ltv_cac"]
        if v is None:
            return f"LTV:CAC for {label}: n/a ({'; '.join(res['caveats']) or 'no closes'})."
        return (f"LTV:CAC for {label}: {v}× — avg contract ${c['avg_contract']:,.0f} ÷ "
                f"CAC ${c['cac_loaded']:,.0f}.")
    if metric == "cac":
        v = res["cac_loaded"]
        return (f"Loaded CAC for {label}: ${v:,.0f} — {c.get('cac_breakdown', 'n/a')}." if v is not None
                else f"CAC for {label}: n/a ({'; '.join(res['caveats'])}).")
    # default LTGP:CAC (or 'economics' → lead with it)
    v = res["ltgp_cac"]
    if v is None:
        return f"LTGP:CAC for {label}: n/a ({'; '.join(res['caveats']) or 'no closes'})."
    return (f"LTGP:CAC for {label}: {v}× — LTGP ${c['ltgp']:,.0f} ÷ CAC ${c['cac_loaded']:,.0f} "
            f"({c['cac_breakdown']}).")


def _which_metric(t: str) -> str:
    tl = t.lower()
    if re.search(r"roas|return on ad spend", tl):
        return "roas"
    if re.search(r"ltv", tl):
        return "ltv"
    if re.search(r"ltgp", tl):
        return "ltgp"
    if re.search(r"\bcac\b|loaded cac", tl):
        return "cac"
    return "ltgp"  # "unit economics" / "economics" → lead with LTGP:CAC


def handle_unit_econ_command(text: str) -> tuple[str | None, bool]:
    """Answer 'LTGP:CAC in May', 'ROAS last 3 weeks', 'this month vs last month', etc.

    Returns (reply, handled). handled=False → not a unit-economics question.
    """
    is_cohort = bool(text and _COHORT_RE.search(text))
    if not text or not (_METRIC_RE.search(text) or is_cohort):
        return None, False
    from helpers import today_sydney
    today = today_sydney()

    # Cohort-conversion view ("how's this month's lead flow converting?", "lead-to-close in May").
    if is_cohort and not _METRIC_RE.search(text):
        rng = parse_range(text, today) or (today - dt.timedelta(days=29), today, "the last 30 days")
        cf = cohort_funnel(rng[0] if isinstance(rng[0], dt.date) else dt.date.fromisoformat(str(rng[0])),
                           rng[1] if isinstance(rng[1], dt.date) else dt.date.fromisoformat(str(rng[1])))
        return _cohort_reply(cf, rng[2]), True

    metric = _which_metric(text)

    # Comparison? ("this month vs last month", "compare Q1 and Q2")
    if _COMPARE_RE.search(text):
        parts = _COMPARE_RE.split(text, maxsplit=1)
        left = parse_range(parts[0], today)
        right = parse_range(parts[-1], today) if len(parts) > 1 else None
        if left and right:
            rl = unit_economics(str(left[0]), str(left[1]))
            rr = unit_economics(str(right[0]), str(right[1]))
            return _compare_reply(metric, left[2], rl, right[2], rr), True

    rng = parse_range(text, today)
    if not rng:
        # default to trailing 30d (the dashboard window) and say so
        rng = (today - dt.timedelta(days=29), today, "the last 30 days (default)")
    res = unit_economics(str(rng[0]), str(rng[1]))
    if "error" in res:
        return f"I couldn't read that range — try 'LTGP:CAC in May' or 'ROAS last 3 weeks'.", True
    reply = _one_line(metric, res, rng[2])
    extra = [c for c in res.get("caveats", []) if c not in reply]
    if extra:
        reply += " " + " ".join(extra)
    return reply, True


def _compare_reply(metric: str, la: str, ra: dict, lb: str, rb: dict) -> str:
    key = {"roas": "roas", "ltv": "ltv_cac", "cac": "cac_loaded"}.get(metric, "ltgp_cac")
    va, vb = ra.get(key), rb.get(key)
    name = {"roas": "ROAS", "ltv": "LTV:CAC", "cac": "loaded CAC"}.get(metric, "LTGP:CAC")
    ca, cb = ra["components"], rb["components"]
    def f(v):
        if v is None:
            return "n/a"
        return f"${v:,.0f}" if metric == "cac" else f"{v}×"
    head = f"{name}: {la} {f(va)} vs {lb} {f(vb)}."
    # Driver attribution (which lever moved)
    drivers = []
    for lab, k in [("spend", "ad_spend"), ("closes", "closes"),
                   ("contract value", "contract_value_total"), ("cash", "cash_collected_total")]:
        a, b = ca.get(k), cb.get(k)
        if a is not None and b is not None and a != b:
            arrow = "up" if b > a else "down"
            drivers.append(f"{lab} {arrow} {f'${a:,.0f}→${b:,.0f}' if k != 'closes' else f'{a}→{b}'}")
    if drivers:
        head += " Drivers: " + "; ".join(drivers) + "."
    return head

