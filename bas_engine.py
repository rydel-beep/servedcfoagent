"""
bas_engine.py
-------------
THE ONE BAS/PAYG ESTIMATION ENGINE (BAS_PAYG_REPORT, Rydel-confirmed 2026-08-06).
Every surface — the dashboard card, the set-aside split, the forecast outflows,
salience, EDITH — reads THIS module's estimate. No second BAS math anywhere.

> THE STANDING LINE (non-negotiable, on every payload and every spoken answer):
> estimates for cash planning — the accountant/BAS agent lodges the official
> statement. Never lodgement figures, never tax advice.

CONFIG (provenance recorded, never assumed):
  · GST basis CASH, period QUARTERLY — read from Xero Organisation settings live.
  · Lodgement: BAS AGENT (extended due dates) — Rydel 2026-08-06.
  · PAYGW: Rydel's own wage only, $541/wk withheld — Rydel 2026-08-06 (+ CLAUDE.md).
  · PAYG instalments: EXIST, amount pending Rydel's ATO notice — "set PAYG
    instalment to $X" records it; the line renders amount-pending until then.

SOURCE PATH (probed 2026-08-06): the official Activity Statement has NO public API
endpoint — the LEDGER-DERIVED path is the path: Balance Sheet GST / PAYG
Withholdings Payable / Income Tax Payable balances (point-in-time), cross-checked
against a P&L 10%-of-flows band. Line-level 1A/1B needs accounting.transactions.read
(not granted — noted as the optional scope addition, never assumed).

Xero reads are READ-ONLY and happen only inside refresh() (daily tick / manual),
persisted to kv `bas:estimate`; request paths never touch Xero.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

logger = logging.getLogger(__name__)

_KV_ESTIMATE = "bas:estimate"
_KV_CONFIG = "bas:config"
_KV_HISTORY = "bas:history"        # {quarter_end_iso: tax_lines} — fetched once, kept
_KV_PNL_HIST = "bas:pnl_history"   # {quarter_start_iso: {revenue, credits_band}} — for deltas
_KV_TICK = "bas:daily_tick"
_KV_CALIBRATION = "bas:calibration"
_KV_LODGED = "bas:lodged"          # {quarter_start_iso: official lodged lines + provenance}
                                   # THE TRUTH for lodged periods (BAS_CALIBRATION_REPORT,
                                   # calibrated against the official Activity Statement
                                   # export 2026-08-06). Ledger-derived figures for those
                                   # periods are calibration comparison ONLY, never shown
                                   # as the obligation.

DISCLAIMER = ("Estimate for planning — your accountant/BAS agent lodges the official "
              "statement.")

# Rydel-confirmed config defaults (provenance in each entry; overridable via kv)
_DEFAULT_CONFIG = {
    "lodgement": "agent",            # Rydel 2026-08-06: BAS agent, extended dates
    "paygw_weekly": 541.0,           # Rydel 2026-08-06: own wage only ($541/wk withheld)
    "instalments_active": True,      # Rydel 2026-08-06: on PAYG instalments
    "instalment_amount": None,       # pending his ATO notice — set via chat, never invented
    "gst_rate": 0.10,
}

# Quarterly BAS due dates keyed by quarter START month. Standard: 28 Oct / 28 Feb /
# 28 Apr / 28 Jul. Agent program: ~25 Nov / 28 Feb / 26 May / 25 Aug.
_DUE_STANDARD = {7: (10, 28), 10: (2, 28), 1: (4, 28), 4: (7, 28)}
_DUE_AGENT = {7: (11, 25), 10: (2, 28), 1: (5, 26), 4: (8, 25)}

# Opex/COGS line → GST-credit treatment for the cross-estimate band. Deterministic:
# NONE lines never carry credits; CERTAIN lines carry 10% in both bounds; MAYBE lines
# carry 10% only in the high-credits bound (overseas SaaS / unregistered contractors
# unknowable without line-level tax — the stated limit of current scopes).
_CREDIT_NONE = re.compile(r"no gst|wages|salaries|superannuation|bank fees|"
                          r"travel - international|personal", re.I)
_CREDIT_CERTAIN = re.compile(r"advertising|consulting|accounting|office|telephone|"
                             r"internet|insurance|travel - national|with gst", re.I)


def config() -> dict:
    import kv_store
    c = dict(_DEFAULT_CONFIG)
    c.update(kv_store.get(_KV_CONFIG) or {})
    return c


def set_config(key: str, value, set_by: str = "Rydel") -> dict:
    import kv_store
    from helpers import today_sydney
    cur = kv_store.get(_KV_CONFIG) or {}
    cur[key] = value
    cur[f"{key}_provenance"] = {"set_by": set_by, "date": str(today_sydney())}
    kv_store.put(_KV_CONFIG, cur)
    return cur


# ── The BAS calendar (exact quarters, never conflated) ───────────────────────

def quarter_bounds(d: dt.date) -> tuple[dt.date, dt.date]:
    qm = ((d.month - 1) // 3) * 3 + 1
    start = d.replace(month=qm, day=1)
    end = (start.replace(month=qm + 2, day=1) + dt.timedelta(days=31)).replace(day=1) \
        - dt.timedelta(days=1)
    return start, end


def quarter_label(start: dt.date) -> str:
    names = {1: "Jan–Mar", 4: "Apr–Jun", 7: "Jul–Sep", 10: "Oct–Dec"}
    return f"{names[start.month]} {start.year}"


def due_date(qstart: dt.date, lodgement: str | None = None) -> dt.date:
    table = _DUE_AGENT if (lodgement or config()["lodgement"]) == "agent" else _DUE_STANDARD
    m, day = table[qstart.month]
    year = qstart.year + (1 if m < qstart.month else 0)
    return dt.date(year, m, day)


def prev_quarter_start(qstart: dt.date) -> dt.date:
    return quarter_bounds(qstart - dt.timedelta(days=1))[0]


# ── Lodged periods: the official record (ground truth over every estimate) ───

def lodged_records() -> dict:
    import kv_store
    return kv_store.get(_KV_LODGED) or {}


def ingest_lodged(qstart_iso: str, lines: dict, source: str, set_by: str = "Rydel") -> dict:
    """Record a LODGED activity statement's official figures for a quarter. `lines`
    carries what the lodgement proved (missing keys stay absent, never invented):
    {g1, one_a, one_b, net_gst, w1, paygw, instalment, total, due}. Recomputes the
    honesty score for that quarter against whatever the estimator had."""
    import kv_store
    from helpers import today_sydney
    rec = {k: lines[k] for k in ("g1", "one_a", "one_b", "net_gst", "w1", "paygw",
                                 "instalment", "total", "due") if lines.get(k) is not None}
    rec["source"] = source
    rec["ingested"] = {"by": set_by, "date": str(today_sydney())}
    all_rec = kv_store.get(_KV_LODGED) or {}
    all_rec[qstart_iso] = {**(all_rec.get(qstart_iso) or {}), **rec}
    kv_store.put(_KV_LODGED, all_rec)
    _score_lodged_quarter(qstart_iso, all_rec[qstart_iso])
    return all_rec[qstart_iso]


def mark_lodged_paid(qstart_iso: str, evidence: str, paid_date: str | None = None) -> dict | None:
    """Payment evidence for a lodged quarter (auto-detected from the ledger drop, or
    told by Rydel). The outstanding leg of the ATO position drops; salience resolves."""
    import kv_store
    from helpers import today_sydney
    all_rec = kv_store.get(_KV_LODGED) or {}
    rec = all_rec.get(qstart_iso)
    if not rec:
        return None
    rec["paid"] = {"date": paid_date or str(today_sydney()), "evidence": evidence}
    kv_store.put(_KV_LODGED, all_rec)
    return rec


def _score_lodged_quarter(qstart_iso: str, rec: dict) -> None:
    """The honesty score: estimator vs official, per component, kept forever."""
    import kv_store
    qstart = dt.date.fromisoformat(qstart_iso)
    label = quarter_label(qstart)
    cal = kv_store.get(_KV_CALIBRATION) or {}
    entry = cal.get(label) or {}
    hist = kv_store.get(_KV_HISTORY) or {}
    qend_lines = hist.get(str(quarter_bounds(qstart)[1])) or {}
    ledger_close = qend_lines.get("GST")
    comp = {}
    if rec.get("total") is not None and ledger_close is not None:
        comp["total"] = {"official": rec["total"], "estimator_ledger_close": ledger_close,
                         "error_pct": round((ledger_close - rec["total"]) / rec["total"] * 100, 2)}
    if rec.get("paygw") is not None:
        modelled = round(config()["paygw_weekly"] * 13, 2)
        comp["paygw"] = {"official": rec["paygw"], "modelled": modelled,
                         "error_pct": round((modelled - rec["paygw"]) / rec["paygw"] * 100, 2),
                         "note": "the $541/wk model sees recurring pay only — one-off "
                                 "payroll runs (e.g. Apr 2026's $13,789 withholding) are "
                                 "invisible to it until the ledger shows them"}
    entry["official"] = {k: rec.get(k) for k in ("g1", "one_a", "one_b", "net_gst",
                                                 "w1", "paygw", "instalment", "total")}
    entry["vs_official"] = comp
    entry["source"] = rec.get("source")
    cal[label] = entry
    kv_store.put(_KV_CALIBRATION, cal)


def honesty_score() -> dict:
    """Per-quarter estimator accuracy against REAL lodged figures — public, verbatim."""
    import kv_store
    cal = kv_store.get(_KV_CALIBRATION) or {}
    return {q: {"vs_official": e.get("vs_official"), "official": e.get("official"),
                "source": e.get("source")}
            for q, e in cal.items() if e.get("vs_official")}


# ── The credits band (the honest 1B without line-level tax) ──────────────────

def credits_band(lines: list[dict], gst_rate: float = 0.10) -> dict:
    """(low, high) input-credit estimate from named P&L lines. Deterministic rules,
    the uncertainty stated: MAYBE lines only enter the high bound."""
    certain = maybe = 0.0
    for ln in lines or []:
        label, amt = (ln.get("label") or ""), abs(ln.get("amount") or 0)
        if _CREDIT_NONE.search(label):
            continue
        if _CREDIT_CERTAIN.search(label):
            certain += amt * gst_rate
        else:
            maybe += amt * gst_rate
    return {"low": round(certain, 2), "high": round(certain + maybe, 2)}


# ── The estimate (compute inside refresh; surfaces read kv) ──────────────────

def _compute(inputs: dict, today: dt.date) -> dict:
    cfg = config()
    qstart, qend = quarter_bounds(today)
    opening_key, today_key = str(qstart - dt.timedelta(days=1)), str(today)
    tl = inputs.get("tax_lines") or {}

    def acct(lines: dict, *keys) -> float | None:
        for name, v in (lines or {}).items():
            low = name.lower()
            if any(k in low for k in keys) and "#" not in name:
                return v
        return None

    # A fetched Balance Sheet OMITS zero-balance accounts (probe-verified: PAYGW absent
    # at 30 Jun when it was 0) — a missing line on a PRESENT report means 0, not unknown.
    open_lines, now_lines = tl.get(opening_key), tl.get(today_key)

    def read(lines, *keys):
        if lines is None:            # the report itself was unreadable → unknown
            return None
        v = acct(lines, *keys)
        return v if v is not None else 0.0

    gst_open = read(open_lines, "gst")
    gst_now = read(now_lines, "gst")
    paygw_open = read(open_lines, "payg withhold") or 0.0
    paygw_now = read(now_lines, "payg withhold")
    income_tax_now = read(now_lines, "income tax")

    days_total = (qend - qstart).days + 1
    days_elapsed = (today - qstart).days + 1
    weeks_elapsed = days_elapsed / 7.0

    # GST QTD off the ledger: movement + the payment-drop adjustment (the agent paying
    # the PRIOR quarter's BAS drops the account by ~the opening balance — derived,
    # flagged, never silent).
    gst = {"available": gst_now is not None and gst_open is not None}
    if gst["available"]:
        movement = gst_now - gst_open
        assumed_paid = 0.0
        if gst_open > 0 and gst_now < gst_open and (gst_open - gst_now) > 0.5 * gst_open:
            assumed_paid = gst_open
        qtd = movement + assumed_paid
        gst.update({
            "opening_balance": round(gst_open, 2), "current_balance": round(gst_now, 2),
            "qtd_net": round(qtd, 2),
            "payment_adjustment": round(assumed_paid, 2),
            "payment_adjustment_note": (f"the GST account dropped ≥50% below its "
                                        f"opening balance — read as the prior BAS being "
                                        f"paid (~${assumed_paid:,.0f}); QTD accrual "
                                        f"adjusted accordingly (assumption, flagged)"
                                        if assumed_paid else None),
            "projected_full_quarter": round(qtd / days_elapsed * days_total, 2),
        })

    # The P&L cross-estimate band (the second way — drift beyond tolerance flags)
    pnl_key = f"{qstart}..{today}"
    p = (inputs.get("pnl") or {}).get(pnl_key) or {}
    cross = None
    if p and p.get("revenue") is not None:
        one_a = (p["revenue"] or 0) * cfg["gst_rate"]
        band = credits_band((p.get("opex_line_items") or []) + (p.get("cogs_line_items") or []))
        cross = {"one_a_estimate": round(one_a, 2), "credits_band": band,
                 "net_low": round(one_a - band["high"], 2),
                 "net_high": round(one_a - band["low"], 2)}
    drift_flag = None
    if cross and gst.get("available") and gst.get("qtd_net") is not None:
        lo, hi = cross["net_low"], cross["net_high"]
        tol = max(1500.0, 0.25 * max(abs(gst["qtd_net"]), 1))
        if not (lo - tol <= gst["qtd_net"] <= hi + tol):
            drift_flag = (f"ledger QTD ${gst['qtd_net']:,.0f} sits outside the P&L "
                          f"cross-estimate band ${lo:,.0f}–${hi:,.0f} (+tolerance) — "
                          f"check tax coding with the accountant")

    # PAYGW: the ledger balance when readable; the $541/wk model as fallback (labelled)
    if paygw_now is not None:
        paygw_qtd, paygw_src = paygw_now - (paygw_open or 0.0), "ledger (PAYG Withholdings Payable)"
    else:
        paygw_qtd, paygw_src = cfg["paygw_weekly"] * weeks_elapsed, "modelled ($541/wk × weeks)"
    paygw = {"qtd": round(paygw_qtd, 2), "source": paygw_src,
             "weekly": cfg["paygw_weekly"],
             "projected_full_quarter": round(cfg["paygw_weekly"] * 13, 2)}

    # PAYG instalment: EXISTS (Rydel), amount pending until his ATO notice is set
    instalment = {"active": bool(cfg["instalments_active"]),
                  "amount": cfg["instalment_amount"],
                  "note": (None if cfg["instalment_amount"] is not None else
                           "amount pending — say “set PAYG instalment to $X” from your "
                           "ATO notice; excluded from totals until set")}

    # The prior-quarter obligation: LODGED figures when we have them (the official
    # record wins over any ledger proxy — calibrated 2026-08-06: the ledger's clearing
    # balance sat $381 off the lodged total via offsetting composition errors), else
    # the ledger-derived fallback, labelled as such.
    prior = None
    pq = prev_quarter_start(qstart)
    lodged = lodged_records().get(str(pq))
    if lodged and lodged.get("total") is not None:
        paid = lodged.get("paid")
        # payment auto-detection: the GST clearing dropping ≥50% below its opening
        # balance this quarter is the prior BAS being paid (same signal, now evidenced)
        if not paid and gst.get("payment_adjustment"):
            paid = mark_lodged_paid(str(pq),
                                    evidence=(f"GST clearing account dropped by "
                                              f"~${gst['payment_adjustment']:,.0f} — read as "
                                              f"the BAS payment leaving the books"))
            paid = paid.get("paid") if paid else None
        residual = (round(gst["opening_balance"] - lodged["total"], 2)
                    if gst.get("available") else None)
        prior = {"label": f"{quarter_label(pq)} BAS (lodged)",
                 "amount": lodged["total"],
                 "due": lodged.get("due") or str(due_date(pq)),
                 "status": (f"PAID {paid['date']} — {paid['evidence']}" if paid
                            else "OUTSTANDING — no payment in the ledger yet"),
                 "paid": bool(paid),
                 "basis": f"official lodged figures ({lodged.get('source', 'lodged BAS')})",
                 "components": {k: lodged.get(k) for k in
                                ("net_gst", "paygw", "instalment") if lodged.get(k) is not None},
                 "ledger_residual": residual,
                 "ledger_residual_note": (
                     None if residual is None else
                     f"the ledger clearing balance at quarter close was "
                     f"${gst['opening_balance']:,.2f} — ${abs(residual):,.2f} "
                     f"{'above' if residual > 0 else 'below'} the lodged total; splitting "
                     f"that residual line-by-line needs accounting.transactions.read "
                     f"(not granted) or the accountant's journal — official figure shown")}
    elif gst.get("available") and gst["opening_balance"] > 0 and not gst["payment_adjustment"]:
        prior = {"label": f"{quarter_label(pq)} BAS (with the agent)",
                 "amount": round(gst["opening_balance"] + paygw_open, 2),
                 "due": str(due_date(pq)), "status": "with the agent — not yet paid per the ledger",
                 "paid": False,
                 "basis": "GST + PAYGW account balances at quarter close (ledger estimate — "
                          "drop the lodged statement in to replace with official figures)"}
    # PAYGW projection band: the model vs the last LODGED actual (evidence that one-off
    # payroll runs can ~3× the recurring model — shown, never silently absorbed)
    if lodged and lodged.get("paygw") is not None:
        paygw["last_lodged_actual"] = lodged["paygw"]
        paygw["band_note"] = (f"last lodged quarter's actual PAYGW was "
                              f"${lodged['paygw']:,.0f} vs ${paygw['projected_full_quarter']:,.0f} "
                              f"modelled — one-off payroll runs land above the model; the "
                              f"ledger QTD picks them up as they post")

    # THE SET-ASIDE: spoken-for = the ATO-related book balances TODAY (they already
    # include prior unpaid + QTD accrual); vs the physical BAS #2353 account.
    spoken_for = None
    if gst_now is not None:
        spoken_for = round(gst_now + (paygw_now or 0.0) + (income_tax_now or 0.0), 2)
    bas_bank = inputs.get("bas_account_balance")
    set_aside = {"spoken_for": spoken_for,
                 "components": {"gst_balance": gst_now, "paygw_balance": paygw_now,
                                "income_tax_payable": income_tax_now},
                 "bas_account_balance": bas_bank,
                 "covered": (bas_bank is not None and spoken_for is not None
                             and bas_bank >= spoken_for),
                 "buffer": (round(bas_bank - spoken_for, 2)
                            if bas_bank is not None and spoken_for is not None else None)}

    # This quarter's obligation as a dated cash event
    cur_amount = None
    if gst.get("available"):
        cur_amount = round(gst["projected_full_quarter"] + paygw["projected_full_quarter"]
                           + (cfg["instalment_amount"] or 0), 2)
    current_obligation = {
        "label": f"{quarter_label(qstart)} BAS", "due": str(due_date(qstart)),
        "amount": cur_amount, "confidence": "modelled (run-rate projection)",
        "accrued_so_far": (round(gst.get("qtd_net", 0) + paygw["qtd"], 2)
                           if gst.get("available") else None)}

    # THE ATO POSITION — the sharpened "what we owe": (a) lodged-but-unpaid +
    # (b) accrued this quarter + (c) projected remainder (labelled projection).
    a_amt = prior["amount"] if (prior and not prior.get("paid")) else 0.0
    b_amt = (round(gst.get("qtd_net", 0) + paygw["qtd"], 2)
             if gst.get("available") else None)
    c_amt = None
    if cur_amount is not None and b_amt is not None:
        c_amt = round(max(cur_amount - b_amt, 0.0), 2)
    position = {
        "owed_now": (round(a_amt + b_amt, 2) if b_amt is not None else
                     (a_amt if a_amt else None)),
        "a_outstanding_lodged": ({"amount": a_amt, "label": prior["label"],
                                  "due": prior["due"], "basis": prior["basis"]}
                                 if a_amt else None),
        "b_current_accrued": ({"amount": b_amt,
                               "label": f"{quarter_label(qstart)} accrued to {today}"}
                              if b_amt is not None else None),
        "c_projected_remainder": ({"amount": c_amt,
                                   "label": f"projected further by {qend} (PROJECTION)",
                                   "due": str(due_date(qstart))}
                                  if c_amt is not None else None),
        "note": "owed now = lodged-but-unpaid + accrued this quarter; the projection "
                "rides separately · " + DISCLAIMER}

    # Set-aside carries the position: spoken-for = (a) official outstanding + (b) accrued
    # (+ the income-tax provision on the books — separate ATO money, labelled). Falls back
    # to raw book balances when the position can't be built (never invented).
    if position["owed_now"] is not None:
        sf = round(position["owed_now"] + (income_tax_now or 0.0), 2)
        set_aside.update({
            "spoken_for": sf,
            "components": {"outstanding_lodged": a_amt or None,
                           "current_accrued": b_amt,
                           "income_tax_payable": income_tax_now,
                           "gst_balance": gst_now, "paygw_balance": paygw_now},
            "basis": "ATO position (a)+(b) + income-tax provision",
            "covered": (bas_bank is not None and bas_bank >= sf),
            "buffer": (round(bas_bank - sf, 2) if bas_bank is not None else None)})

    return {"as_of": str(today), "disclaimer": DISCLAIMER,
            "quarter": {"label": quarter_label(qstart), "start": str(qstart),
                        "end": str(qend), "due": str(due_date(qstart)),
                        "days_elapsed": days_elapsed, "days_total": days_total,
                        "convention": "BAS quarter (Jul–Sep / Oct–Dec / Jan–Mar / Apr–Jun)"},
            "gst_basis": "CASH (Xero Organisation setting)",
            "lodgement": cfg["lodgement"],
            "gst": gst, "cross_estimate": cross, "drift_flag": drift_flag,
            "paygw": paygw, "instalment": instalment,
            "prior_obligation": prior, "current_obligation": current_obligation,
            "position": position, "set_aside": set_aside}


def refresh() -> dict | None:
    """Pull inputs (ONE Xero refresh, read-only), compute, persist. Failure keeps the
    last estimate (staleness visible via as_of); never fabricates."""
    import kv_store
    from helpers import today_sydney
    from xero_pull import pull_bas_inputs
    today = today_sydney()
    qstart, _ = quarter_bounds(today)
    inputs = pull_bas_inputs(
        bs_dates=[str(qstart - dt.timedelta(days=1)), str(today)],
        pnl_windows=[(str(qstart), str(today))])
    if not inputs.get("ok"):
        logger.warning("bas refresh: xero unavailable: %s", inputs.get("reason"))
        return None
    est = _compute(inputs, today)
    # history: keep each quarter-end's tax lines once (calibration + sparkline)
    hist = kv_store.get(_KV_HISTORY) or {}
    open_key = str(qstart - dt.timedelta(days=1))
    if open_key not in hist and (inputs.get("tax_lines") or {}).get(open_key):
        hist[open_key] = inputs["tax_lines"][open_key]
        kv_store.put(_KV_HISTORY, hist)
    est["history"] = [{"date": k, "gst": v.get("GST"),
                       "paygw": next((x for n, x in v.items() if "PAYG" in n), None)}
                      for k, v in sorted(hist.items())]
    est["decomposition"] = _decompose(est)
    est["calibration_flags"] = _calibration_flags()
    kv_store.put(_KV_ESTIMATE, est)
    _record_calibration(est)
    return est


def _calibration_flags() -> list[str]:
    """Official-vs-estimate divergence beyond the observed-error tolerance, component
    named — the hygiene surface. Tolerance = 2× the median observed |total error|,
    floor 5% (set FROM the calibration record, not assumed)."""
    hs = honesty_score()
    if not hs:
        return []
    total_errs = [abs((e["vs_official"].get("total") or {}).get("error_pct", 0))
                  for e in hs.values() if (e.get("vs_official") or {}).get("total")]
    tol = max(5.0, 2 * (sorted(total_errs)[len(total_errs) // 2] if total_errs else 0))
    flags = []
    for q, e in sorted(hs.items()):
        for comp, v in (e.get("vs_official") or {}).items():
            err = v.get("error_pct")
            if err is not None and abs(err) > tol:
                flags.append(f"{q} {comp}: estimator {err:+.0f}% vs official "
                             f"(tolerance ±{tol:.0f}%) — "
                             + (v.get("note") or "check the model input with the accountant"))
    return flags


def _decompose(est: dict) -> dict | None:
    """Deterministic delta vs the prior quarter's net GST (its closing balance — the
    EOFY-journal caveat stated when it applies). Parts SUM EXACTLY: residual is the
    balancer, named 'timing/one-offs', never hidden."""
    hist = est.get("history") or []
    gst = est.get("gst") or {}
    cross = est.get("cross_estimate") or {}
    if not gst.get("available") or len(hist) < 1:
        return None
    prev_net = hist[-1].get("gst")   # prior quarter's closing GST balance (its net, caveat below)
    if prev_net is None:
        return None
    cur_proj = gst["projected_full_quarter"]
    delta = round(cur_proj - prev_net, 2)
    one_a_proj = None
    if cross:
        q = est["quarter"]
        one_a_proj = round(cross["one_a_estimate"] / q["days_elapsed"] * q["days_total"], 2)
    parts = {"delta_net": delta,
             "projected_1a_full_quarter": one_a_proj,
             "prior_quarter_net": prev_net,
             "caveat": ("the prior figure is the ledger's quarter-close balance — EOFY "
                        "journals (30 Jun) can inflate it; the accountant's lodged figure "
                        "is the authority" if str(est["quarter"]["start"]).endswith("07-01")
                        else None)}
    # residual = the delta not explained by the revenue-side estimate (spend mix + timing)
    if one_a_proj is not None:
        prev_1a_unknown = None  # line-level history not readable at current scopes
        parts["explained"] = ("decomposition to 1A/1B per quarter needs line-level tax "
                              "(accounting.transactions.read not granted) — the split "
                              "shown is revenue-side estimate vs residual")
        parts["residual_spend_mix_and_timing"] = round(delta, 2)
    return parts


def _record_calibration(est: dict) -> None:
    """Each quarter close: how close was the projection? The estimator's own honesty
    score, kept forever. Also stores today's two-way agreement."""
    import kv_store
    cal = kv_store.get(_KV_CALIBRATION) or {}
    q = est["quarter"]["label"]
    entry = cal.get(q) or {}
    entry["last_projection"] = (est.get("gst") or {}).get("projected_full_quarter")
    entry["as_of"] = est["as_of"]
    cross = est.get("cross_estimate") or {}
    if cross and (est.get("gst") or {}).get("qtd_net") is not None:
        entry["two_way_agreement"] = {
            "ledger_qtd": est["gst"]["qtd_net"],
            "cross_band": [cross["net_low"], cross["net_high"]],
            "agrees": cross["net_low"] - 1500 <= est["gst"]["qtd_net"] <= cross["net_high"] + 1500}
    cal[q] = entry
    kv_store.put(_KV_CALIBRATION, cal)


def estimate() -> dict | None:
    """What every surface reads. kv only — no Xero on the request path."""
    import kv_store
    return kv_store.get(_KV_ESTIMATE)


def daily_tick() -> bool:
    import kv_store
    from helpers import today_sydney
    if kv_store.get(_KV_TICK) == str(today_sydney()):
        return False
    try:
        refresh()
        kv_store.put(_KV_TICK, str(today_sydney()))
        return True
    except Exception as e:
        logger.warning("bas daily tick failed: %s", e)
        return False


# ── Interfaces the rest of the system consumes (the ONE engine) ──────────────

def scheduled_obligations() -> list[dict]:
    """Dated ATO cash events for the forecast: [{label, due, amount, confidence}].
    Amount-pending instalments are excluded (never invented) — noted on the card."""
    est = estimate()
    if not est:
        return []
    out = []
    p = est.get("prior_obligation")
    if p and not p.get("paid"):
        out.append({"label": p["label"], "due": p["due"], "amount": p["amount"],
                    "confidence": ("lodged figure (official)" if "lodged" in p.get("basis", "")
                                   else "ledger balance (high)"), "kind": "bas_prior"})
    c = est.get("current_obligation") or {}
    if c.get("amount") is not None:
        out.append({"label": c["label"], "due": c["due"], "amount": c["amount"],
                    "confidence": c["confidence"], "kind": "bas_current"})
    return out


def free_cash_view(cash_on_hand: float | None) -> dict | None:
    """The set-aside split for wherever headline cash renders: cash − spoken-for =
    yours. Estimate-labelled; None when either side is unknown (never invented)."""
    est = estimate()
    if not est or cash_on_hand is None:
        return None
    sf = (est.get("set_aside") or {}).get("spoken_for")
    if sf is None:
        return None
    return {"cash": round(cash_on_hand, 2), "spoken_for": sf,
            "free": round(cash_on_hand - sf, 2),
            "note": f"spoken for = GST + PAYGW + income-tax balances on the books · {DISCLAIMER}"}


def salience_events() -> list[dict]:
    """T-14 / T-3 due-date approaches + the pace anomaly — watermark-stable ids,
    kv-only (salience.collect calls this; no Xero)."""
    from helpers import today_sydney
    est = estimate()
    if not est:
        return []
    today = today_sydney()
    events = []
    for ob in scheduled_obligations():
        try:
            d = dt.date.fromisoformat(ob["due"])
        except ValueError:
            continue
        left = (d - today).days
        for t in (3, 14):        # tightest band wins (T-3 outranks T-14)
            if 0 <= left <= t:
                sa = est.get("set_aside") or {}
                covered = sa.get("covered")
                tail = ("set-aside covers it" if covered
                        else "set-aside does NOT cover it — move cash" if covered is False
                        else "set-aside coverage unknown")
                events.append({"id": f"bas_due:{ob['label']}:{t}", "type": "bas_due",
                               "salience": 88 if t == 3 else 76, "ago": 0,
                               "spoken": (f"{ob['label']} due in {left} day(s) — "
                                          f"~${ob['amount']:,.0f} (estimate) · {tail}")})
                break
    # An OUTSTANDING lodged amount is a STANDING high-materiality item — it never ages
    # out silently; it resolves only when payment evidence lands (then says so once).
    p = est.get("prior_obligation")
    if p and "lodged" in (p.get("basis") or ""):
        if not p.get("paid"):
            overdue = None
            try:
                overdue = (today - dt.date.fromisoformat(p["due"])).days
            except ValueError:
                pass
            events.append({"id": f"bas_outstanding:{p['label']}", "type": "bas_outstanding",
                           "salience": 92, "ago": 0,
                           "spoken": (f"{p['label']}: ${p['amount']:,.0f} OUTSTANDING — "
                                      + (f"{overdue} day(s) OVERDUE"
                                         if overdue is not None and overdue > 0 else
                                         f"due {p['due']}")
                                      + " · lodged figure, unpaid per the ledger")})
        else:
            events.append({"id": f"bas_paid_resolved:{p['label']}", "type": "bas_outstanding",
                           "salience": 55, "ago": 0,
                           "spoken": f"{p['label']} is PAID — {p['status']}"})
    gst = est.get("gst") or {}
    if est.get("drift_flag"):
        events.append({"id": f"bas_drift:{est['quarter']['label']}", "type": "bas_anomaly",
                       "salience": 62, "ago": 0, "spoken": f"BAS estimate: {est['drift_flag']}"})
    if gst.get("payment_adjustment"):
        events.append({"id": f"bas_paid:{est['quarter']['label']}", "type": "bas_anomaly",
                       "salience": 58, "ago": 0,
                       "spoken": (f"the prior BAS looks PAID this quarter "
                                  f"(~${gst['payment_adjustment']:,.0f} left the GST "
                                  f"account) — QTD accrual adjusted, assumption flagged")})
    return events


# ── EDITH ────────────────────────────────────────────────────────────────────

_BAS_RE = re.compile(
    r"\bbas\b|\bgst\b|activity statement|tax bill|payg|set.?aside|"
    r"how much .{0,20}(ato|tax)|when.{0,12}(bas|tax).{0,10}due", re.I)
_SET_INSTALMENT_RE = re.compile(
    r"set\s+(the\s+)?payg\s+instalment\s+(to\s+)?\$?([\d,]+(?:\.\d+)?)", re.I)


def handle_set_instalment(text: str) -> tuple[str | None, bool]:
    m = _SET_INSTALMENT_RE.search(text or "")
    if not m:
        return None, False
    amt = float(m.group(3).replace(",", ""))
    set_config("instalment_amount", amt)
    return (f"PAYG instalment recorded: ${amt:,.0f}/quarter (set by you, from the ATO "
            f"notice). It now rides every BAS obligation and the set-aside. {DISCLAIMER}"), True


def handle_bas_command(text: str) -> tuple[str | None, bool]:
    """'what's our BAS looking like' / 'when's it due' / 'how much should I set aside'
    / 'why is it higher than last quarter' — engine-verbatim, decomposition-backed."""
    if not text or not _BAS_RE.search(text):
        return None, False
    est = estimate()
    if not est:
        return ("I haven't built a BAS estimate yet — the Xero read hasn't run. "
                "Say “refresh the BAS estimate” or wait for the daily tick."), True
    q, gst, paygw = est["quarter"], est.get("gst") or {}, est.get("paygw") or {}
    sa = est.get("set_aside") or {}
    parts = []

    # "how accurate are your BAS estimates?" — the honesty score, verbatim, per quarter
    if re.search(r"how (accurate|good|close)|accuracy|honesty score", text, re.I):
        hs = honesty_score()
        if not hs:
            return ("No lodged statement has been recorded yet to score against — drop a "
                    f"BAS export in and I calibrate. {DISCLAIMER}"), True
        for qlabel, e in sorted(hs.items()):
            off, vs = e.get("official") or {}, e.get("vs_official") or {}
            t = vs.get("total") or {}
            if t:
                parts.append(f"{qlabel}: official ${off.get('total', 0):,.0f} vs my "
                             f"ledger-derived ${t.get('estimator_ledger_close', 0):,.2f} — "
                             f"{t.get('error_pct', 0):+.1f}% off.")
            pw = vs.get("paygw") or {}
            if pw:
                parts.append(f"PAYGW: official ${pw['official']:,.0f} vs ${pw['modelled']:,.0f} "
                             f"modelled ({pw['error_pct']:+.0f}% — {pw['note']}).")
            parts.append(f"Source: {e.get('source')}.")
        parts.append(DISCLAIMER)
        return " ".join(parts), True

    # "is the April–June BAS paid?" — the payment evidence, never a guess
    if re.search(r"\bpaid\b|payment (state|status)", text, re.I):
        p = est.get("prior_obligation")
        if not p:
            return (f"No prior-quarter BAS is on the books to check. {DISCLAIMER}"), True
        parts.append(f"{p['label']} — ${p['amount']:,.0f}: {p['status']}.")
        if not p.get("paid"):
            parts.append(f"Due {p['due']}. The set-aside "
                         + ("covers it." if (sa.get('covered')) else "does NOT cover it."))
        parts.append(DISCLAIMER)
        return " ".join(parts), True

    # "how much do we owe the ATO right now?" — the decomposed position
    if re.search(r"(owe|owing).{0,25}(right now|now|today|ato)|ato position", text, re.I):
        pos = est.get("position") or {}
        if pos.get("owed_now") is None:
            return (f"I can't build the ATO position — the ledger read is incomplete. "
                    f"{DISCLAIMER}"), True
        parts.append(f"You owe the ATO ${pos['owed_now']:,.0f} right now —")
        a = pos.get("a_outstanding_lodged")
        if a:
            parts.append(f"${a['amount']:,.0f} from {a['label']} (due {a['due']}, unpaid),")
        b = pos.get("b_current_accrued")
        if b:
            parts.append(f"plus ${b['amount']:,.0f} accrued this quarter;")
        cpr = pos.get("c_projected_remainder")
        if cpr:
            parts.append(f"projected ${cpr['amount']:,.0f} more by quarter end "
                         f"(PROJECTION), due {cpr['due']}.")
        parts.append(DISCLAIMER)
        return " ".join(parts), True

    if re.search(r"when.{0,20}due|due date", text, re.I):
        for ob in scheduled_obligations():
            parts.append(f"{ob['label']}: due {ob['due']}"
                         + (f" — ~${ob['amount']:,.0f} ({ob['confidence']})"
                            if ob.get("amount") is not None else ""))
        parts.append(f"Agent lodgement dates (extended). {DISCLAIMER}")
        return "\n".join(parts), True

    if re.search(r"set.?aside|how much.{0,25}(put|keep|aside|ato)", text, re.I):
        if sa.get("spoken_for") is not None:
            parts.append(f"Spoken for right now: ${sa['spoken_for']:,.0f} "
                         f"(GST ${sa['components']['gst_balance']:,.0f}"
                         + (f" + PAYGW ${sa['components']['paygw_balance']:,.0f}"
                            if sa['components'].get('paygw_balance') else "")
                         + (f" + income tax ${sa['components']['income_tax_payable']:,.0f}"
                            if sa['components'].get('income_tax_payable') else "") + ").")
            if sa.get("bas_account_balance") is not None:
                parts.append(f"The BAS #2353 account holds ${sa['bas_account_balance']:,.0f} — "
                             + ("covered, buffer ${:,.0f}.".format(sa["buffer"])
                                if sa.get("covered") else
                                f"SHORT by ${-sa['buffer']:,.0f} — move cash across."))
        parts.append(DISCLAIMER)
        return " ".join(parts), True

    if re.search(r"why.{0,30}(higher|lower|moved|changed|up|down)", text, re.I):
        d = est.get("decomposition")
        if not d:
            return ("I don't have a prior-quarter baseline yet to decompose against — "
                    f"it builds as quarters close. {DISCLAIMER}"), True
        parts.append(f"Net GST projected ${gst.get('projected_full_quarter', 0):,.0f} vs the "
                     f"prior quarter's ledger close ${d['prior_quarter_net']:,.0f} — "
                     f"Δ ${d['delta_net']:+,.0f}.")
        if d.get("projected_1a_full_quarter") is not None:
            parts.append(f"Revenue side: ~${d['projected_1a_full_quarter']:,.0f} GST on sales "
                         f"projected this quarter.")
        if d.get("caveat"):
            parts.append(d["caveat"] + ".")
        parts.append(d.get("explained") or "")
        parts.append(DISCLAIMER)
        return " ".join(p for p in parts if p), True

    # the default: the full picture
    parts.append(f"{q['label']} (BAS quarter, day {q['days_elapsed']} of {q['days_total']}), "
                 f"cash-basis GST:")
    if gst.get("available"):
        parts.append(f"• accrued so far: ${gst['qtd_net']:,.0f} net GST"
                     + (f" + ${paygw['qtd']:,.0f} PAYGW ({paygw['source']})"
                        if paygw.get("qtd") is not None else ""))
        parts.append(f"• projected full quarter (modelled, run-rate): "
                     f"${gst['projected_full_quarter']:,.0f} GST + "
                     f"${paygw['projected_full_quarter']:,.0f} PAYGW")
    inst = est.get("instalment") or {}
    if inst.get("active"):
        parts.append("• PAYG instalment: " + (f"${inst['amount']:,.0f}/quarter"
                                              if inst.get("amount") is not None
                                              else inst.get("note", "amount pending")))
    c = est.get("current_obligation") or {}
    parts.append(f"• due {c.get('due')}" + (f" — ~${c['amount']:,.0f} all in"
                                            if c.get("amount") is not None else ""))
    if est.get("prior_obligation"):
        p = est["prior_obligation"]
        parts.append(f"• PLUS {p['label']}: ${p['amount']:,.0f} — {p['status']}")
    if est.get("drift_flag"):
        parts.append(f"⚠ {est['drift_flag']}")
    parts.append(DISCLAIMER)
    return "\n".join(parts), True


_MARK_PAID_RE = re.compile(
    r"mark (the )?([a-z–\-]+[–\-][a-z]+ )?bas (as )?paid", re.I)


def handle_mark_paid(text: str) -> tuple[str | None, bool]:
    """'mark the Apr–Jun BAS as paid' — records Rydel's word as the payment evidence
    for the outstanding lodged quarter (the ledger detector also does this on its own
    when the clearing account drops)."""
    if not text or not _MARK_PAID_RE.search(text):
        return None, False
    est = estimate()
    p = (est or {}).get("prior_obligation")
    if not p or "lodged" not in (p.get("basis") or ""):
        return ("There's no lodged outstanding BAS on record to mark paid. "
                f"{DISCLAIMER}"), True
    if p.get("paid"):
        return (f"{p['label']} is already recorded paid: {p['status']}."), True
    from helpers import today_sydney
    qstart = prev_quarter_start(quarter_bounds(dt.date.fromisoformat(est["as_of"]))[0])
    mark_lodged_paid(str(qstart), evidence="Rydel confirmed the payment",
                     paid_date=str(today_sydney()))
    refresh()
    return (f"{p['label']} recorded PAID (your word — the next ledger read will show the "
            f"clearing drop as corroboration). The ATO position and set-aside updated."), True


_REFRESH_RE = re.compile(r"refresh (the )?bas( estimate)?|rebuild (the )?bas", re.I)


def handle_refresh_command(text: str) -> tuple[str | None, bool]:
    if not text or not _REFRESH_RE.search(text):
        return None, False
    est = refresh()
    if not est:
        return "The Xero read failed — the last estimate stands (check /debug/sources).", True
    gst = est.get("gst") or {}
    return (f"BAS estimate rebuilt as of {est['as_of']}: {est['quarter']['label']} QTD net GST "
            f"${gst.get('qtd_net', 0):,.0f}, projected ${gst.get('projected_full_quarter', 0):,.0f}. "
            f"{DISCLAIMER}"), True
