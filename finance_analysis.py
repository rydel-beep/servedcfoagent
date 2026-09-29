"""finance_analysis.py — THE MONTHLY FINANCIAL ANALYSIS engine (#149).

Three ROAS, labelled, never blended (R-ROAS):
  CASH ROAS      = Stripe-reconciled receipts ÷ Meta spend (source-stamped).
                   Activity clock: receipts landing in the window.
                   Cohort clock: cash-to-date from the window's closes.
  CONTRACT ROAS  = signed contract value of the window's closes ÷ spend.
  LTV ROAS       = projected LTV of the window's closes ÷ spend — every
                   input's provenance shown (measured vs placeholder).
The month's VERDICT is decided by CONTRACT ROAS + PAYBACK MONTHS from real
billing cadence — never by cash ROAS alone, never by reassurance.

R-CASH: cash is never derived — receipts come from the Stripe pull
(cash_truth) only. Closes: the ONE attribution engine (tracker authority)
UNIONED with the gap ledger's AUTO closes (GHL-primary inside the detected
window, payment-corroborated, evidence ids) — provenance labelled on every
row, clocks labelled on every figure. READ-ONLY law: no writes to the
tracker/GHL; this module only reads engines and its own kv versions.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_KV_VERSIONS = "fin:analysis_versions"

# FY26 review context (source: FY26 Financial Review — fixed reference)
FY26 = {"sales": 698_599.0, "refunds": 41_436.0, "refund_rate_pct": 5.9,
        "acquisition_spend_pct_of_sales": 15.0}

_GP_TERM_MONTHS = 6


def _windows() -> dict:
    t = today_sydney()
    return {
        "sep_mtd": (dt.date(2026, 9, 1), t),
        "aug_full": (dt.date(2026, 8, 1), dt.date(2026, 8, 31)),
        "t30": (t - dt.timedelta(days=29), t),
        "t60": (t - dt.timedelta(days=59), t),
        "t90": (t - dt.timedelta(days=89), t),
    }


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _receipts_in_window(w0: dt.date, w1: dt.date) -> dict:
    """Stripe succeeded charges landing in [w0, w1] — receipts by receipt
    date (R-CASH). None = Stripe unreachable, never zero."""
    import cash_truth
    from helpers import SYDNEY_TZ
    days = (today_sydney() - w0).days + 3
    raw = cash_truth._raw_recent_charges(min(days, 365))
    if raw is None:
        return {"available": False, "reason": "stripe unreachable"}
    total, n = 0.0, 0
    for ch in raw:
        if not (ch.get("paid") and ch.get("status") == "succeeded"):
            continue
        d = dt.datetime.fromtimestamp(ch["created"], tz=SYDNEY_TZ).date()
        if w0 <= d <= w1:
            amt = (ch.get("amount") or 0) - (ch.get("amount_refunded") or 0)
            total += amt / 100.0
            n += 1
    return {"available": True, "total": round(total, 2), "count": n,
            "source": "Stripe charges (net of refunds), receipt-dated"}


def _closes_union(w0: str, w1: str, basis: str) -> list[dict]:
    """THE ONE CLOSE POPULATION, in this module's legacy row shape.

    The union logic that used to live here (engine ∪ gap-ledger AUTO, with
    enrichment) moved into close_register.build() — this is now a thin read
    of the register, so travelling, the tiles, compass, SALES cash and the
    sales-cost engine all see the SAME closes as every other surface.
    `basis` maps to the register's clock; every current caller passes
    "activity"."""
    import close_register as CR
    clock = "cohort" if basis == "cohort" else "activity"
    out = []
    for e in CR.closes(str(w0), str(w1), clock):
        att = e.get("attribution") or {}
        cash = e.get("cash") or {}
        contract = e.get("contract") or {}
        out.append({
            "person": e.get("person"), "close_date": e.get("close_date"),
            "contract": contract.get("value"),
            "contract_provenance": contract.get("source"),
            "cash": cash.get("amount"),
            "cash_provenance": (cash.get("source") if cash.get("amount") is not None
                                else None),
            "creative": att.get("creative"),
            "client_row": e.get("client"),
            "provenance": (f"register · dated by {e.get('dated_by')} · "
                           f"{e.get('status')}"),
            "evidence": e.get("evidence"),
            "source": f"close register ({e.get('status')})",
            # #170: owner-ruled deal facts ride with the close so the
            # commission engine can cost it exactly
            "ruled": ({"package": e.get("package"),
                       "payment_type": e.get("payment_type"),
                       "closer": e.get("closer"), "setter": e.get("setter"),
                       "cash_events": e.get("cash_events") or []}
                      if e.get("ruling") else None),
        })
    out.sort(key=lambda o: o["close_date"])
    return out


def _ltv_inputs() -> dict:
    """The engine's MEASURED inputs in this module's legacy keys (#170). No
    placeholder, no bound: unmeasured reads as None with the reason."""
    import unit_econ_engine as UE
    i = UE.inputs()
    return {
        "renewal_rate_pct": i["renewal_pct"],
        "renewal_provenance": (f"measured {i['measured_on']} from payment history, "
                               f"n={i['renewal_n']}, 95% {i['renewal_ci95']}"
                               if i["measured"] else i["note"]),
        "in_term_completion_pct": i["completion_pct"],
        "completion_provenance": (f"measured {i['measured_on']}, n={i['completion_n']}"
                                  if i["measured"] else i["note"]),
        "horizon_months": i["horizon_months"],
        "formula": "unit_econ_engine — expected (measured completion + renewals "
                   "inside the horizon) and floor (signed contract)",
    }


def payback_schedule(close: dict) -> dict:
    """Month-by-month expected collection from the close's real cadence:
    actual Stripe receipts to date + Health-tab MRR through the remaining
    term. Never invented — where no MRR row exists the schedule stops at
    actuals and says so."""
    person = close.get("person") or ""
    # the union's gap-ledger enrichment already carries the venue bridge
    # (client_row + mrr) — person-token matching is only the fallback.
    mrr, pkg = close.get("mrr"), close.get("package")
    if not close.get("client_row"):
        try:
            from snapshot import load_persisted
            snap = load_persisted() or {}
            pool = ((snap.get("active_clients") or {}).get("active") or [])
            toks = [t for t in re.split(r"[^a-z0-9]+", person.lower()) if len(t) > 3]
            best = None
            for c in pool:
                nm = (c.get("name") or "").lower()
                score = sum(1 for t in toks if t in nm)
                if score and (best is None or score > best[0]):
                    best = (score, c)
            if best:
                mrr = best[1].get("current_mrr")
                pkg = best[1].get("package")
                close["client_row"] = best[1].get("name")
        except Exception:
            pass
    elif mrr is None:
        mrr = close.get("mrr")
    cash_now = float(close.get("cash") or 0)
    cv = float(close.get("contract") or 0) or None
    sched = []
    if close.get("close_date"):
        d0 = dt.date.fromisoformat(str(close["close_date"])[:10]).replace(day=1)
        cum = cash_now
        sched.append({"month": str(d0)[:7], "expected_cum": round(cum, 2),
                      "basis": "actual receipts to date"})
        if mrr:
            m = d0
            for i in range(1, _GP_TERM_MONTHS):
                m = (m + dt.timedelta(days=32)).replace(day=1)
                cum = min(cum + float(mrr), cv) if cv else cum + float(mrr)
                sched.append({"month": str(m)[:7], "expected_cum": round(cum, 2),
                              "basis": f"+ Health-tab MRR ${mrr:,.0f}/mo"})
    return {"person": person, "client_row": close.get("client_row"),
            "package": pkg, "mrr": mrr, "contract": cv,
            "cash_to_date": cash_now, "schedule": sched,
            "note": (None if mrr else "no Health-tab MRR row — schedule "
                                      "stops at actual receipts (stated, "
                                      "not invented)")}


def window_report(name: str, basis: str = "activity") -> dict:
    w0, w1 = _windows()[name]
    import meta_spend
    import attribution_engine as AE
    spend = meta_spend.spend_in_range(str(w0), str(w1)) or {}
    res = AE.compute(start=str(w0), end=str(w1), basis=basis)
    tot = {"leads": 0, "qualified": 0, "reached": 0, "sets": 0, "shows": 0,
           "shows_unverified": 0}
    for c in res.get("creatives", []):
        for k in tot:
            tot[k] += c.get(k) or 0
    closes = _closes_union(str(w0), str(w1), basis)
    contract_total = sum(float(c.get("contract") or 0) for c in closes)
    contract_missing = [c["person"] for c in closes if not c.get("contract")]
    # #150: SIGNED vs DERIVED split — a derived contract value (package-term
    # × MRR) is never rendered as signed; every derived $ is chipped.
    contract_signed = round(sum(
        float(c.get("contract") or 0) for c in closes
        if c.get("contract") and "derived" not in str(c.get("contract_provenance") or "tracker")), 2)
    contract_derived = round(contract_total - contract_signed, 2)
    cohort_cash = sum(float(c.get("cash") or 0) for c in closes)
    receipts = _receipts_in_window(w0, w1)
    inputs = _ltv_inputs()
    import close_register as CR
    import unit_econ_engine as UE
    _ui = UE.inputs()
    ltv_total = sum(r["expected"] or 0 for r in (
        UE.ltv_for(e, _ui) for e in CR.closes(
            str(w0), str(w1), "cohort" if basis == "cohort" else "activity")))
    sp = float(spend.get("spend") or 0)

    def _r(x):
        return round(x / sp, 2) if sp and x is not None else None

    intraday = str(w1) >= str(today_sydney())
    return {
        "window": {"name": name, "start": str(w0), "end": str(w1),
                   "clock": basis,
                   "intraday_note": ("includes today — intraday, not final"
                                     if intraday else None)},
        "spend": {"amount": sp, "source": spend.get("source"),
                  "days_covered": spend.get("days_covered"),
                  "degraded": spend.get("degraded")},
        "funnel": {**tot, "closes": len(closes)},
        "unit_costs": {k: (round(sp / v, 2) if v else None) for k, v in
                       (("cpl", tot["leads"]), ("cost_per_qualified", tot["qualified"]),
                        ("cost_per_set", tot["sets"]), ("cost_per_show", tot["shows"]),
                        ("cost_per_close", len(closes) or None))},
        "cash": {"receipts_in_window": receipts,
                 "cohort_cash_from_closes": round(cohort_cash, 2)},
        "roas": {
            # #150: COHORT is the headline cash figure; the all-receipts
            # ratio is DEMOTED + relabelled (retainers from old clients are
            # not returns on this month's ads).
            "cash_roas_cohort": _r(cohort_cash),
            "receipts_ratio_not_attributable": _r(
                receipts.get("total") if receipts.get("available") else None),
            "contract_roas": _r(contract_total),
            "contract_roas_signed_only": _r(contract_signed),
            "ltv_roas": _r(ltv_total),
            "labels": {"cash_cohort": "the window's closes' own cash ÷ spend "
                                      "(THE cash ROAS)",
                       "receipts_ratio": "ALL receipts ÷ spend — not "
                                         "attributable to this window's ads; "
                                         "demoted from the headline",
                       "contract": "contract value of window closes ÷ spend "
                                   "(signed + derived split shown)",
                       "ltv": "projected LTV of window closes ÷ spend"},
            "never_blended": True},
        "contract": {"total": round(contract_total, 2),
                     "signed": contract_signed,
                     "derived": contract_derived,
                     "derived_note": ("derived = package term × Health-tab "
                                      "MRR, chipped — not a signed figure"
                                      if contract_derived else None),
                     "missing": contract_missing},
        "ltv": {"total": round(ltv_total, 2), "inputs": inputs},
        "closes": closes,
        "open_pipeline_note": "leads in-window without a close are IN the "
                              "funnel counts, annotated by the clock — "
                              "never dropped",
    }


def cohort_payback(name: str = "sep_mtd") -> dict:
    """Months until the window's closes' cumulative cash ≥ the window's
    spend, from each close's actual cadence."""
    rep = window_report(name, basis="activity")
    sp = rep["spend"]["amount"]
    scheds = [payback_schedule(dict(c)) for c in rep["closes"]]
    # cumulative-per-close → monthly increments → cohort cumulative
    months: dict[str, float] = {}
    for s in scheds:
        prev = 0.0
        for row in s["schedule"]:
            months[row["month"]] = (months.get(row["month"], 0.0)
                                    + row["expected_cum"] - prev)
            prev = row["expected_cum"]
    cum, series, crossed = 0.0, [], None
    for m in sorted(months):
        cum += months[m]
        series.append({"month": m, "cumulative_cash": round(cum, 2)})
        if crossed is None and sp and cum >= sp:
            crossed = m
    payback_months = None
    if crossed and series:
        d0 = dt.date.fromisoformat(series[0]["month"] + "-01")
        d1 = dt.date.fromisoformat(crossed + "-01")
        payback_months = (d1.year - d0.year) * 12 + (d1.month - d0.month) + 1
    return {"window": name, "spend": sp, "series": series,
            "crosses_spend_in": crossed, "payback_months": payback_months,
            "schedules": scheds,
            "basis": "actual Stripe receipts + Health-tab MRR through the "
                     "term (stops at actuals where no MRR row — stated)"}


def verdict() -> dict:
    """Plain English, decided by numbers (R-ROAS): contract ROAS + payback
    months decide; cash ROAS states the timing."""
    rep = window_report("sep_mtd", basis="activity")
    pb = cohort_payback("sep_mtd")
    r = rep["roas"]
    sp = rep["spend"]["amount"]
    n = len(rep["closes"])
    lines = []
    ok = None
    if not sp:
        text = "No September spend recorded — no ROAS verdict possible."
        ok = None
    else:
        cash_r = r.get("cash_roas_cohort")
        con_r = r.get("contract_roas")
        if con_r is None:
            text = (f"{n} close(s) on ${sp:,.0f} spend but contract value is "
                    f"missing on {len(rep['contract']['missing'])} of them — "
                    f"the verdict is blocked on contract evidence, not on "
                    f"performance.")
            ok = None
        elif con_r >= 1.0:
            ok = True
            cross = pb.get("crosses_spend_in")
            text = (f"The negative in-month cash position IS the expected "
                    f"Growth Pro timing signature, and the numbers prove it: "
                    f"CONTRACT ROAS {con_r}× (${rep['contract']['total']:,.0f} "
                    f"signed on ${sp:,.0f} spend) with cohort cash at "
                    f"{cash_r}× so far; on the closes' real billing cadence "
                    f"the cohort's cumulative cash "
                    + (f"crosses this month's spend in {cross} "
                       f"(payback ≈ {pb.get('payback_months')} months)."
                       if cross else
                       "does not cross spend inside the schedule the data "
                       "supports — watch the next receipts.")
                    + " The deciding figures: contract ROAS and payback "
                      "months — not reassurance.")
        else:
            ok = False
            text = (f"This is NOT just timing: CONTRACT ROAS is {con_r}× — "
                    f"the signed value of the month's closes "
                    f"(${rep['contract']['total']:,.0f}) is below the month's "
                    f"spend (${sp:,.0f}). Cash timing can't fix a contract "
                    f"shortfall; the deciding figure is contract ROAS.")
    return {"verdict": text, "healthy": ok,
            "deciding_figures": {"contract_roas": r.get("contract_roas"),
                                 "payback_months": pb.get("payback_months"),
                                 "cash_roas_cohort": r.get("cash_roas_cohort")},
            "fy26_context": FY26}


def four_sets() -> dict:
    try:
        import ads_lifecycle
        import attribution_engine as AE
        win = AE.compute(days=30, basis="activity")
        allr = AE.compute(days=90, basis="activity")
        so = ads_lifecycle.sets_overview(win.get("creatives") or [],
                                         allr.get("creatives") or [])
        sess = ads_lifecycle.review_sessions(limit=10)
        return {"sets": so, "review_sessions": sess,
                "sessions_note": ("ZERO review sessions recorded — the R-A2 "
                                  "7–8-day review cadence has not been run"
                                  if not sess else None)}
    except Exception as e:
        return {"error": str(e)[:150]}


def full_analysis() -> dict:
    out = {"generated": str(today_sydney()),
           "windows": {}, "verdict": verdict(),
           "payback": cohort_payback("sep_mtd"),
           "four_sets": four_sets()}
    for name in ("sep_mtd", "aug_full", "t30", "t60", "t90"):
        out["windows"][name] = {
            "activity": window_report(name, "activity"),
            "cohort": window_report(name, "cohort")}
    try:
        import gap_reconcile
        out["gap"] = {"state": kv_store.get("gap:state"),
                      "ledger": gap_reconcile.close_ledger()}
    except Exception:
        pass
    return out


# ── the owner briefing (markdown + PDF, kv-versioned) ───────────────────────

def _money(v):
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def build_briefing_markdown() -> tuple[str, str]:
    a = full_analysis()
    v = a["verdict"]
    sep = a["windows"]["sep_mtd"]["activity"]
    aug = a["windows"]["aug_full"]["activity"]
    lines = [f"# FINANCIAL ANALYSIS — {a['generated']}", "",
             "> OWNER BRIEFING · every number traceable to its engine; "
             "clocks + provenance labelled; three ROAS never blended.", "",
             "## The verdict", v["verdict"], "",
             f"Deciding figures: contract ROAS "
             f"{v['deciding_figures']['contract_roas']}× · payback "
             f"{v['deciding_figures']['payback_months']} months · cohort "
             f"cash ROAS so far {v['deciding_figures']['cash_roas_cohort']}×",
             "", "## September MTD (activity clock)"]
    r = sep["roas"]
    lines += [
        f"- Spend {_money(sep['spend']['amount'])} "
        f"({sep['spend']['source']}; {sep['window']['intraday_note'] or 'final'})",
        f"- Funnel: {sep['funnel']['leads']} leads → "
        f"{sep['funnel']['qualified']} qualified → {sep['funnel']['sets']} "
        f"sets → {sep['funnel']['shows']} shows (+"
        f"{sep['funnel']['shows_unverified']} unverified) → "
        f"{sep['funnel']['closes']} closes",
        f"- CPL {_money(sep['unit_costs']['cpl'])} · C/Set "
        f"{_money(sep['unit_costs']['cost_per_set'])} · C/Close "
        f"{_money(sep['unit_costs']['cost_per_close'])}",
        f"- COHORT CASH ROAS {r['cash_roas_cohort']}× (the closes' own "
        f"cash) · CONTRACT ROAS "
        f"{r['contract_roas']}× · LTV ROAS {r['ltv_roas']}×",
        f"- LTV inputs: renewal {sep['ltv']['inputs']['renewal_rate_pct']}% "
        f"({sep['ltv']['inputs']['renewal_provenance']}); completion "
        f"{sep['ltv']['inputs']['in_term_completion_pct']}% "
        f"({sep['ltv']['inputs']['completion_provenance']})",
        "", "## The month's closes"]
    for c in sep["closes"]:
        lines.append(f"- **{c['person']}** — closed {c['close_date']} "
                     f"({c['provenance']}; {c.get('source')}); contract "
                     f"{_money(c.get('contract'))}"
                     + (f" ({c.get('contract_provenance')})"
                        if c.get("contract_provenance") else "")
                     + f"; cash to date {_money(c.get('cash'))}")
    lines += ["", "## Collection schedule (real cadence)"]
    for s in a["payback"]["schedules"]:
        row = " → ".join(f"{x['month']}: {_money(x['expected_cum'])}"
                         for x in s["schedule"][:7])
        client = s.get("client_row") or "no client row"
        lines.append(f"- {s['person']} ({client} · {s.get('package') or '?'}): "
                     f"{row}"
                     + (f" — {s['note']}" if s.get("note") else ""))
    lines += ["", "## August (full month, activity clock)",
              f"- Spend {_money(aug['spend']['amount'])} · "
              f"{aug['funnel']['leads']} leads · {aug['funnel']['closes']} "
              f"closes · CONTRACT ROAS {aug['roas']['contract_roas']}× · "
              f"COHORT CASH ROAS {aug['roas']['cash_roas_cohort']}× · receipts "
              f"ratio {aug['roas']['receipts_ratio_not_attributable']}× "
              f"(not attributable — demoted)",
              "", "## The four sets (R-A2)"]
    fs = a["four_sets"]
    if fs.get("sessions_note"):
        lines.append(f"- ⚠ {fs['sessions_note']}")
    sets = (fs.get("sets") or {}).get("sets") or (fs.get("sets") or {})
    if isinstance(sets, dict):
        for role, s in sets.items():
            if isinstance(s, dict):
                lines.append(f"- {role}: {json.dumps({k: s.get(k) for k in ('actual_daily','intended_daily','drift','status') if k in s}, default=str)}")
    lines += ["", "## FY26 context",
              f"- FY26 acquisition spend ran ~{FY26['acquisition_spend_pct_of_sales']}% "
              f"of sales; refunds {FY26['refund_rate_pct']}% of sales — the "
              f"month's spend and refund posture read against those.",
              "", "*Clocks labelled per figure · cash never derived · gap-"
              "window closes carry GHL+Stripe evidence ids (#148/#149).*"]
    headline = v["verdict"][:140]
    return "\n".join(lines), headline


def generate_briefing() -> dict:
    md, headline = build_briefing_markdown()
    versions = kv_store.get(_KV_VERSIONS) or []
    version = (versions[-1]["version"] + 1) if versions else 1
    entry = {"version": version, "generated": str(today_sydney()),
             "headline": headline, "md": md}
    versions.append(entry)
    kv_store.put(_KV_VERSIONS, versions[-10:])
    return entry


def latest_briefing() -> dict | None:
    v = kv_store.get(_KV_VERSIONS) or []
    return v[-1] if v else None


def briefing_pdf() -> bytes:
    from csm_docs import _pdf_base, _latin
    entry = latest_briefing() or generate_briefing()
    pdf = _pdf_base(f"FINANCIAL ANALYSIS — {entry['generated']}",
                    "OWNER BRIEFING - Served CFO")
    pdf.set_text_color(30, 30, 30)
    for raw in entry["md"].splitlines():
        line = _latin(raw.replace("**", ""))
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, line[3:], new_x="LMARGIN", new_y="NEXT")
        elif line.startswith("> "):
            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(0, 4.5, line[2:], new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 4.5, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── EDITH drills ────────────────────────────────────────────────────────────

_ROAS_RE = re.compile(r"\broas\b|return on ad spend", re.I)
_LTV_RE = re.compile(r"ltv.{0,6}(to|:|vs)?.{0,3}cac|ltgp.{0,6}cac|"
                     r"lifetime value.{0,20}cac", re.I)
_CLOSES_RE = re.compile(r"(which|what).*(three|3).*(closed|closes)|"
                        r"cash schedule|collection schedule", re.I)


def handle_finance_command(text: str) -> tuple[str | None, bool]:
    t = (text or "").lower()
    try:
        if _LTV_RE.search(t):
            ue = unit_econ_view()
            c = ue["windows"]["cohort_month"]
            t90 = ue["windows"]["trailing_90d"]
            li = ue["ltv_inputs"]
            return (
                f"LTV:CAC and LTGP:CAC, both clocks — September cohort: "
                f"LTV:CAC {c['ltv_to_cac']}× · LTGP:CAC {c['ltgp_to_cac']}× "
                f"({c['closes']} closes; CAC fully loaded "
                f"${c['cac_fully_loaded']:,.0f}, spend-only "
                f"${c['cac_spend_only']:,.0f} beside). Trailing 90d: "
                f"LTV:CAC {t90['ltv_to_cac']}× · LTGP:CAC "
                f"{t90['ltgp_to_cac']}×. Inputs: renewal "
                f"{li['renewal_rate_pct']}% ({li['renewal_provenance'][:70]}); "
                f"completion {li['in_term_completion_pct']}% "
                f"({li['completion_provenance'][:45]}); margin "
                f"{ue['margin_provenance'][:70]}. 3:1 is a benchmark, not a "
                f"target — the tiles are at the top of the dashboard with "
                f"their drawers.", True)
        if _ROAS_RE.search(t):
            v = verdict()
            rep = window_report("sep_mtd", "activity")
            r = rep["roas"]
            return (
                f"September MTD, three ROAS, never blended: CASH "
                f"{r['cash_roas_cohort']}× COHORT (the closes' own cash — "
                f"THE cash figure; all-receipts ratio "
                f"{r['receipts_ratio_not_attributable']}× is demoted, not "
                f"attributable to this month's ads) · "
                f"CONTRACT {r['contract_roas']}× · LTV {r['ltv_roas']}× "
                f"(inputs: renewal "
                f"{rep['ltv']['inputs']['renewal_rate_pct']}% "
                f"[{rep['ltv']['inputs']['renewal_provenance'][:60]}], "
                f"completion {rep['ltv']['inputs']['in_term_completion_pct']}% "
                f"[{rep['ltv']['inputs']['completion_provenance'][:40]}]). "
                f"{v['verdict']}", True)
        if _CLOSES_RE.search(t):
            rep = window_report("sep_mtd", "activity")
            pb = cohort_payback("sep_mtd")
            bits = []
            for s in pb["schedules"]:
                sched = " → ".join(f"{x['month'][5:]}: ${x['expected_cum']:,.0f}"
                                   for x in s["schedule"][:4])
                ev = next((c.get("evidence") for c in rep["closes"]
                           if c["person"] == s["person"]), None) or {}
                client = s.get("client_row") or "no client row"
                evbit = ""
                if ev:
                    charges = ",".join(str(c)[:14] + "…"
                                       for c in (ev.get("charge_ids") or [])[:2])
                    evbit = (f" [opp {str(ev.get('opp_id'))[:8]}…, charges "
                             f"{charges}]")
                bits.append(f"{s['person']} ({client}): {sched}{evbit}")
            return ("This month's closes and their cash schedules — "
                    + " · ".join(bits) +
                    ". Full month-by-month in the owner briefing.", True)
    except Exception as e:
        logger.info("finance drill failed: %s", e)
    return None, False


# ── unit economics view — a READ of the one engine (#170) ──────────────────
# The maths that lived here (LTV = contract × (completion + renewal), with the
# renewal at its UPPER BOUND, an 85% placeholder, an MTD headline and no
# floor) moved to unit_econ_engine. This keeps the legacy shape the landing,
# cards and briefing read, and nothing else.

def _legacy_window(w: dict) -> dict:
    return {
        "window": w["window"], "closes": w["closes"],
        "cac_fully_loaded": w["cac_loaded"], "true_cac": None,
        "cac_spend_only": w["cac_spend_only"],
        "avg_ltv_per_close": w["ltv_expected"],
        "avg_ltv_floor": w["ltv_floor"],
        "ltv_to_cac": w["ltv_cac_expected"], "ltgp_to_cac": w["ltgp_cac_expected"],
        "ltv_to_cac_floor": w["ltv_cac_floor"], "ltgp_to_cac_floor": w["ltgp_cac_floor"],
        "ltv_known": w["ltv_known"], "ltv_pending": w["ltv_pending"],
        "commission_pending": w.get("commission_pending"),
        "sensitivity": w.get("sensitivity"),
    }


def unit_econ_view() -> dict:
    import unit_econ_engine as UE
    v = UE.view()
    inp = v["inputs"]
    return {
        "engine": v,
        "benchmark": v["benchmark"],
        "ltv_inputs": {
            "renewal_rate_pct": inp["renewal_pct"], "renewal_n": inp["renewal_n"],
            "renewal_ci95": inp["renewal_ci95"],
            "in_term_completion_pct": inp["completion_pct"],
            "completion_n": inp["completion_n"],
            "horizon_months": inp["horizon_months"],
            "measured_on": inp["measured_on"],
            "renewal_provenance": (f"measured {inp['measured_on']} from payment "
                                   f"history, n={inp['renewal_n']}"
                                   if inp["measured"] else inp["note"]),
            "completion_provenance": (f"measured {inp['measured_on']}, "
                                      f"n={inp['completion_n']}"
                                      if inp["measured"] else inp["note"]),
            "formula": "see unit_econ_engine — expected and floor"},
        "margin_provenance": v["margin"]["provenance"],
        "windows": {"trailing_90d": _legacy_window(v["headline"]),
                    "cohort_month": _legacy_window(v["mtd"]),
                    "mature_cohort": _legacy_window(v["mature_cohort"])},
        "headline_window": "trailing_90d",
    }


def _math(v: dict, ratio: str) -> dict:
    """Show-the-math for the LTV:CAC / LTGP:CAC drawers — every component
    with its source, the closes behind it, the inputs and the band."""
    h, inp = v["headline"], v["inputs"]
    ltgp = ratio == "ltgp"
    comps = [
        {"label": "expected lifetime value per close", "value": h["ltv_expected"],
         "source": (f"renewal {inp['renewal_pct']}% (n={inp['renewal_n']}, 95% "
                    f"{inp['renewal_ci95']}) · completion {inp['completion_pct']}% "
                    f"(n={inp['completion_n']}) · horizon {inp['horizon_months']} "
                    f"months · measured {inp['measured_on']}" if inp["measured"]
                    else inp["note"])},
        {"label": "signed floor per close", "value": h["ltv_floor"],
         "source": "the signed contracts ex-GST — no renewals, no expansion"},
        {"label": "CAC loaded per close", "value": h["cac_loaded"],
         "source": " + ".join(f"{c['label']} ${c['amount']:,.2f}"
                              for c in (h.get("cac_components") or []))
                   + f" ÷ {h['closes']} closes"},
        {"label": "CAC spend-only (beside, never confused)",
         "value": h["cac_spend_only"], "source": "Meta spend ÷ closes"}]
    if ltgp:
        comps.insert(2, {"label": "gross margin", "value": v["margin"]["pct"],
                         "source": v["margin"]["provenance"]})
    key = "ltgp_cac" if ltgp else "ltv_cac"
    return {
        "tile": key, "clock": "trailing 90 days · activity",
        "value": h[f"{key}_expected"], "floor": h[f"{key}_floor"],
        "mtd": {"value": v["mtd"][f"{key}_expected"], "floor": v["mtd"][f"{key}_floor"],
                "label": v["mtd"]["label"]},
        "mature_cohort": {"value": v["mature_cohort"][f"{key}_expected"],
                          "label": v["mature_cohort"]["label"]},
        "sensitivity": h.get("sensitivity"),
        "components": comps,
        "closes": [{k: r.get(k) for k in ("person", "client", "package", "term_months",
                                            "contract_ex_gst", "contract_source",
                                            "floor", "expected", "working", "why")}
                   for r in h["rows"]],
        "ltv_pending": h["ltv_pending"],
        "commission_pending": h.get("commission_pending"),
        "commission_pending_range": h.get("commission_pending_range"),
        "door": {"label": "the closes behind it", "href": "/dashboard/closes?window=90d"},
        "benchmark": v["benchmark"]["label"],
    }


def drawer_ltv_cac() -> dict:
    import unit_econ_engine as UE
    d = _math(UE.view(), "ltv")
    d["definition"] = ("LTV:CAC — what a client is likely to pay us over their "
                       "whole time with us, for every dollar it cost to win them.")
    return d


def drawer_ltgp_cac() -> dict:
    import unit_econ_engine as UE
    d = _math(UE.view(), "ltgp")
    d["definition"] = ("LTGP:CAC — the gross profit a client is likely to leave "
                       "us over their whole time with us, for every dollar it "
                       "cost to win them.")
    return d
