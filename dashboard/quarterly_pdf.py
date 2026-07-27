"""
dashboard/quarterly_pdf.py
--------------------------
The QUARTERLY FINANCIAL REVIEW PDF. Branded (Served palette, fpdf2 — same engine as the briefing
PDF, no new system deps). Renders a review object from quarterly_review.build_review():
  cover -> exec summary -> quarter scorecard -> QoQ + YoY (honest) -> MRR bridge + velocity charts
  -> the 3x model (targets, both funnel paths, spend, capacity, churn, requirements, binding
  constraint) -> "a model, not a forecast" close.

VERBATIM-NUMBER GUARANTEE (honesty rule): every DOLLAR figure printed in the PDF must trace to a
number already present in the review pack. validate_verbatim() scans the composed text and fails
LOUDLY if any $-figure is not in the allowed set (the adversarial test injects a fake and expects a
raise). The narrative is composed deterministically from pack figures — the model never introduces,
rounds-drifts, or extrapolates a number.
"""
from __future__ import annotations

import logging
import re

from dashboard.briefing_pdf import BriefingPDF, _safe, _fmt, _pct, PRIMARY, NAVY, TINT, MUTED, GREEN, AMBER, RED, WHITE, DARK, LIGHT_GREY
from quarterly_format import fmt_metric, fmt_delta
from helpers import today_sydney

logger = logging.getLogger(__name__)

_FLAG_COLOR = {"plausible": GREEN, "stretch": AMBER, "out-of-trend": RED, "unknown": MUTED}
_MONEY_RE = re.compile(r"\$\s?(-?[\d,]+(?:\.\d+)?)")


# ── Verbatim validation ──────────────────────────────────────────────────────

def _collect_numbers(obj, acc: set) -> None:
    """Recursively gather every int/float in the review into an allowed set (int + 2dp forms)."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        try:
            acc.add(int(round(obj)))
            acc.add(round(float(obj), 2))
        except Exception:
            pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, acc)


def validate_verbatim(text: str, review: dict) -> list[str]:
    """Return a list of $-figures printed in the PDF that do NOT trace to a pack number. Empty list
    = clean. Dollar-figures are the fabrication risk for financials; each must match a pack value
    (allowing display rounding to whole dollars)."""
    allowed: set = set()
    _collect_numbers(review, allowed)
    violations = []
    for m in _MONEY_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        iv = int(round(val))
        if iv in allowed or round(val, 2) in allowed or -iv in allowed:
            continue
        # tolerance: display rounding of a pack value to the nearest whole dollar
        if any(abs(a - val) < 1.0 for a in allowed if isinstance(a, (int, float))):
            continue
        violations.append(f"${m.group(1)}")
    return violations


# ── PDF ──────────────────────────────────────────────────────────────────────

class QuarterlyPDF(BriefingPDF):
    def __init__(self, quarter_label: str):
        super().__init__()
        self._q_label = quarter_label
        self._audit: list[str] = []      # every composed money-bearing string, for verbatim check

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Served Marketing — Quarterly Review — {self._q_label}", align="L")
        self.set_font("Helvetica", "", 8)
        self.cell(0, 6, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LIGHT_GREY)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    # audit-aware emitters (record composed strings so validate_verbatim can scan them)
    def emit(self, text, bold=False):
        self._audit.append(text)
        self._body_text(text, bold=bold)

    def emit_box(self, text):
        self._audit.append(text)
        self._analysis_box(text)

    def kpi_row(self, items):
        for (label, value, sub) in items:
            self._audit.append(f"{value} {sub or ''}")
        self._kpi_row(items)

    def table(self, headers, rows, col_widths=None, col_aligns=None):
        for r in rows:
            cells = r["cells"] if isinstance(r, dict) else r
            self._audit.append(" ".join(str(c) for c in cells))
        self._table(headers, rows, col_widths=col_widths, col_aligns=col_aligns)

    def bar_chart(self, title, series, unit=""):
        """Simple horizontal bar chart drawn with rects (no chart lib). series = [(label, value)]."""
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 6, _safe(title), new_x="LMARGIN", new_y="NEXT")
        vals = [v for _, v in series if isinstance(v, (int, float))]
        mx = max(vals) if vals else 0
        x0 = self.l_margin + 34
        full = self.w - self.r_margin - x0 - 22
        for label, v in series:
            y = self.get_y()
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*DARK)
            self.set_xy(self.l_margin, y)
            self.cell(32, 6, _safe(str(label)), align="L")
            w = (full * (v / mx)) if (mx and isinstance(v, (int, float))) else 0
            self.set_fill_color(*PRIMARY)
            self.rect(x0, y + 1, max(w, 0.4), 4, style="F")
            self.set_xy(x0 + max(w, 0.4) + 2, y)
            self.set_text_color(*MUTED)
            self.cell(20, 6, _safe(f"{int(v):,}{unit}" if isinstance(v, (int, float)) else "--"))
            self.ln(6.5)
        self.ln(2)


def _flag_badge(pdf, flag):
    return {"plausible": "PLAUSIBLE", "stretch": "STRETCH",
            "out-of-trend": "OUT-OF-TREND", "unknown": "n/a"}.get(flag, "n/a")


def generate_quarterly_pdf(review: dict) -> bytes:
    """Render the review to PDF bytes. Raises ValueError if any $-figure fails the verbatim check."""
    q = review.get("quarter", {})
    label = q.get("label", "Quarter")
    cur = review.get("current", {})
    rc = cur.get("revenue_cash", {})
    ue = cur.get("unit_economics", {})
    comp = ue.get("components", {}) if isinstance(ue, dict) else {}
    sales = cur.get("sales", {})
    funnel = sales.get("funnel", {}) or {}
    costs = cur.get("costs", {})
    churn = cur.get("churn", {})
    tx = review.get("three_x", {})
    comps = review.get("comparisons", {})

    pdf = QuarterlyPDF(label)
    pdf.set_title(f"Served CFO — Quarterly Review — {label}")

    # ── COVER ──
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, 80, style="F")
    pdf.set_xy(pdf.l_margin, 26)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, "Quarterly Financial Review", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 15)
    pdf.set_text_color(*TINT)
    pdf.cell(0, 10, f"{label}  —  Served Marketing", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(90)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    win = cur.get("window", {})
    partial = " (quarter-to-date — not yet complete)" if win.get("partial") else ""
    pdf.cell(0, 6, _safe(f"Window: {win.get('start')} to {win.get('end')}{partial}  ·  "
                         f"Generated {str(today_sydney())}  ·  Calendar quarters"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.emit_box("Every figure in this document is drawn verbatim from the same deterministic engines "
                 "that power the live dashboard — a number here equals the dashboard number for the "
                 "same window. Comparisons are shown only where like-basis history exists; gaps are "
                 "stated, never estimated. The 3x section is a model of what must be true, not a forecast.")

    # ── 1. EXECUTIVE SUMMARY ──
    pdf.add_page()
    pdf._section_title(1, "Executive summary")
    xr = rc.get("xero_revenue", {})
    pdf.kpi_row([
        ("Contracted", _fmt(rc.get("contracted_revenue")), f"{comp.get('closes','--')} closes"),
        ("New-deal cash", _fmt(rc.get("new_deal_cash_collected")), "cash-truth"),
        ("LTGP:CAC", f"{ue.get('ltgp_cac','--')}x" if isinstance(ue, dict) else "--", f"CAC {_fmt(comp.get('cac_loaded'))}"),
    ])
    pdf.kpi_row([
        ("Xero revenue", _fmt(xr.get("revenue")) if xr.get("available") else "n/a", "P&L recognized"),
        ("Xero net profit", _fmt(xr.get("net_profit")) if xr.get("available") else "n/a",
         _pct(xr.get("gross_margin_pct")) + " GM" if xr.get("available") else ""),
        ("Active clients", str(churn.get("active_clients_current", "--")), "current roster"),
    ])
    pdf.ln(1)
    _exec_narrative(pdf, review)

    # ── 2. THE QUARTER ──
    pdf.add_page()
    pdf._section_title(2, f"The quarter — {label}")
    pdf.emit("Revenue & cash", bold=True)
    pdf.table(
        ["Metric", "Value", "Basis"],
        [
            {"cells": ["Contracted revenue", _fmt(rc.get("contracted_revenue")), "closes x contract value (tracker)"]},
            {"cells": ["New-deal cash collected", _fmt(rc.get("new_deal_cash_collected")), "Stripe cash matched to closes"]},
            {"cells": ["Avg contract value", _fmt(rc.get("avg_contract")), "per close"]},
            {"cells": ["Xero revenue", _fmt(xr.get("revenue")) if xr.get("available") else "n/a", "P&L recognized (not cash)"]},
            {"cells": ["Xero gross profit", _fmt(xr.get("gross_profit")) if xr.get("available") else "n/a", _pct(xr.get("gross_margin_pct")) + " margin" if xr.get("available") else "--"]},
            {"cells": ["Xero operating expenses", _fmt(xr.get("operating_expenses")) if xr.get("available") else "n/a", "P&L"]},
            {"cells": ["Xero net profit", _fmt(xr.get("net_profit")) if xr.get("available") else "n/a", "P&L"]},
        ],
        col_widths=[62, 45, 63],
    )
    pdf.emit_box("Stripe cash and Xero revenue are the same money seen two ways (cash vs P&L-recognized) "
                 "and are never summed — they are shown separately and labelled.")

    pdf.ln(1)
    pdf.emit("Unit economics (window-consistent)", bold=True)
    pdf.table(
        ["Metric", "Value", "Detail"],
        [
            {"cells": ["Closes", str(comp.get("closes", "--")), "by Close Date"]},
            {"cells": ["Loaded CAC", _fmt(comp.get("cac_loaded")),
                       f"ad {_fmt(comp.get('ad_spend'))} + closer {_fmt(comp.get('closer_comm'))} + setter {_fmt(comp.get('setter_comm'))}"]},
            {"cells": ["LTGP:CAC", f"{ue.get('ltgp_cac','--')}x", f"floor {tx.get('assumptions',{}).get('ltgp_cac_floor','3.0')}x"]},
            {"cells": ["ROAS", f"{ue.get('roas','--')}x", "contracted / ad spend"]},
            {"cells": ["Ad spend", _fmt(comp.get("ad_spend")), _safe(comp.get("ad_spend_source", "") or "")]},
        ],
        col_widths=[50, 40, 80],
    )

    # ── MRR bridge + velocity + the lead-lag warning ──
    _mrr_and_velocity(pdf, review)
    _lead_lag_warning(pdf, review)

    # ── OPEX BRIDGE — where the profit went (G2) ──
    _opex_bridge(pdf, review)

    # ── 3. COMPARISONS ──
    pdf.add_page()
    pdf._section_title(3, "How it compares")
    _comparison_table(pdf, comps.get("qoq"))
    pdf.ln(2)
    _comparison_table(pdf, comps.get("yoy"))

    # ── 4. THE 3X MODEL ──
    pdf.add_page()
    pdf._section_title(4, f"What would need to be true to 3x — {label} - next quarter")
    _three_x_section(pdf, tx)

    # ── 5. THE MARKETING ROADMAP (G5) ──
    pdf.add_page()
    pdf._section_title(5, "Marketing roadmap — the scaling plan")
    _roadmap_section(pdf, review.get("roadmap") or {})

    # ── 6. MODEL GRADING (self-improvement — renders once there's a prior model) ──
    _grading_section(pdf, review.get("model_grading"))

    # ── verbatim guard (numbers are REAL) ──
    audit_text = "\n".join(pdf._audit)
    violations = validate_verbatim(audit_text, review)
    if violations:
        raise ValueError(f"Verbatim-number check FAILED — {len(violations)} $-figure(s) not traceable "
                         f"to the pack: {violations[:8]}")

    # ── report linter (numbers make SENSE — D1-D5 regression gate) ──
    from quarterly_linter import lint, LintError
    lint_result = lint(pdf._audit, review)          # raises LintError on hard data defects (D1-D4)
    review.setdefault("_generation_log", {})["linter"] = lint_result
    if lint_result.get("warnings"):
        logger.warning("quarterly linter language warnings: %s", lint_result["warnings"][:5])
    try:
        import quarterly_model_store
        quarterly_model_store.record_linter(review.get("quarter", {}).get("label", "?"), lint_result)
    except Exception as e:
        logger.info("linter-trend log skipped: %s", e)

    out = pdf.output()
    return bytes(out)


# ── narrative + section builders (deterministic; numbers via _fmt of pack values) ──

def _qoq_pct(review, metric):
    for r in ((review.get("comparisons", {}).get("qoq") or {}).get("rows") or []):
        if r.get("metric") == metric and r.get("available"):
            return r.get("pct")
    return None


def _exec_narrative(pdf, review):
    """G1: name the net result plainly AND reconcile the central tension (unit economics healthy YET
    P&L negative) — the whole story, good and bad."""
    cur = review["current"]; rc = cur["revenue_cash"]; ue = cur.get("unit_economics", {})
    comp = ue.get("components", {}) if isinstance(ue, dict) else {}
    tx = review.get("three_x", {})
    binding = tx.get("binding_constraint", {})
    xr = rc.get("xero_revenue", {}) or {}
    ltgp = ue.get("ltgp_cac") if isinstance(ue, dict) else None
    contracted = rc.get("contracted_revenue"); closes = comp.get("closes")

    parts = []
    if contracted is not None and closes is not None:
        parts.append(f"{review['quarter']['label']} closed {fmt_metric('Closes', closes)} deals for "
                     f"{fmt_metric('Contracted revenue', contracted)} contracted and "
                     f"{fmt_metric('New-deal cash collected', rc.get('new_deal_cash_collected'))} new-deal cash.")
    # NAME THE NET RESULT (good or bad)
    net = xr.get("net_profit") if xr.get("available") else None
    net_pct = _qoq_pct(review, "Xero net profit")
    if net is not None:
        swing = f" — a {net_pct:+.0f}% swing QoQ" if net_pct is not None else ""
        parts.append(f"But the P&L landed at {fmt_metric('Xero net profit', net)} net"
                     f"{' (a loss)' if net < 0 else ''}{swing}.")
    # RECONCILE THE TENSION: strong unit economics yet negative P&L
    if ltgp is not None:
        ad_pct = _qoq_pct(review, "Ad spend"); cac_pct = _qoq_pct(review, "Loaded CAC")
        roas_pct = _qoq_pct(review, "ROAS")
        drivers = []
        if ad_pct is not None: drivers.append(f"ad spend {ad_pct:+.0f}%")
        if cac_pct is not None: drivers.append(f"CAC {cac_pct:+.0f}%")
        if roas_pct is not None: drivers.append(f"ROAS {roas_pct:+.0f}%")
        tension = (f"The tension: unit economics stayed healthy at {fmt_metric('LTGP:CAC', ltgp)} LTGP:CAC, "
                   f"yet the quarter ran a loss — because efficiency degraded with scale ("
                   + ", ".join(drivers) + ") on top of opex growth. Acquisition still pays back; "
                   "the quarter's spend simply ran ahead of the cash it will return.") if drivers else \
                  (f"Unit economics held at {fmt_metric('LTGP:CAC', ltgp)} LTGP:CAC despite the P&L result.")
        parts.append(tension)
    pdf.emit(" ".join(parts))

    if binding.get("lever"):
        pdf.emit_box(f"To 3x overall growth next quarter, the binding constraint is "
                     f"{binding.get('lever')} ({_flag_badge(pdf, binding.get('flag'))}). "
                     "The fundable levers (leads, ad spend) hold because unit economics stay above the "
                     "floor at scale; the wall is operational. Full model in section 4, and the "
                     "scaling plan in the Marketing Roadmap.")


def _lead_lag_warning(pdf, review):
    """G4: surface the automatic leading-indicator warning when month-end lead velocity turns down."""
    lag = ((review.get("current") or {}).get("sales") or {}).get("lead_lag") or {}
    if not lag.get("message"):
        return
    pdf.ln(1)
    if lag.get("warning"):
        pdf.emit_box(_safe("[!] " + lag["message"]))
    else:
        pdf.emit(_safe(lag["message"]))


def _opex_bridge(pdf, review):
    """G2: decompose operating expenses and show the QoQ movement per line — 'where did the profit
    go'. Uses Xero per-line opex for this quarter vs the prior quarter; falls back to the current
    burn decomposition (labelled run-rate) when per-line history is unavailable."""
    cur = review["current"]; rc = cur["revenue_cash"]
    xr = rc.get("xero_revenue", {}) or {}
    prior = review.get("prior_quarter") or {}
    pxr = ((prior.get("revenue_cash") or {}).get("xero_revenue") or {}) if prior else {}
    pdf.ln(2)
    pdf.emit("Where the profit went — operating-expense bridge (QoQ)", bold=True)
    if not xr.get("available"):
        pdf.emit("Xero P&L unavailable for this window — opex bridge not computable.")
        return

    cur_lines = {li.get("label", "?"): abs(li.get("amount") or 0) for li in (xr.get("opex_line_items") or [])}
    prior_lines = {li.get("label", "?"): abs(li.get("amount") or 0) for li in (pxr.get("opex_line_items") or [])} if pxr.get("available") else {}
    # headline swing
    net = xr.get("net_profit"); pnet = pxr.get("net_profit") if pxr.get("available") else None
    if net is not None and pnet is not None:
        pdf.emit(_safe(f"Net profit moved {fmt_metric('Xero net profit', pnet)} -> {fmt_metric('Xero net profit', net)} "
                       f"({fmt_delta('Xero net profit', net - pnet)}). The opex + margin movement below accounts for it."))
    if cur_lines:
        names = sorted(set(cur_lines) | set(prior_lines), key=lambda n: -cur_lines.get(n, 0))[:12]
        rows = []
        for n in names:
            c = cur_lines.get(n); p = prior_lines.get(n)
            delta = (c - p) if (c is not None and p is not None) else None
            rows.append({"cells": [n[:34], _fmt(c) if c is not None else "n/a",
                                   _fmt(p) if p is not None else "n/a",
                                   fmt_delta("opex", delta) if delta is not None else "new/na"]})
        pdf.table(["Operating expense line", review["quarter"]["label"],
                   prior.get("label", "prior"), "QoQ delta"], rows, col_widths=[74, 34, 34, 28])
        if not prior_lines:
            pdf.emit("Prior-quarter per-line opex wasn't captured, so QoQ deltas show where available; "
                     "the totals reconcile the swing.")
    else:
        # fallback: current burn run-rate decomposition
        burn = (cur.get("costs") or {}).get("monthly_burn_context") or {}
        if burn.get("available"):
            pdf.emit("Per-line Xero opex wasn't itemised for this window; current monthly burn "
                     "decomposition (run-rate, not a quarter total):")
            pdf.table(["Burn line (monthly run-rate)", "Amount"],
                      [{"cells": ["Team payroll", _fmt(burn.get("team"))]},
                       {"cells": ["Owner pay", _fmt(burn.get("owner_pay"))]},
                       {"cells": ["Ad spend", _fmt(burn.get("ad_spend_monthly"))]},
                       {"cells": ["Subscriptions", _fmt(burn.get("subscriptions"))]},
                       {"cells": ["Other opex", _fmt(burn.get("other_opex"))]}],
                      col_widths=[110, 60])


def _mrr_and_velocity(pdf, review):
    cur = review["current"]; rc = cur["revenue_cash"]; sales = cur.get("sales", {})
    bridge = rc.get("mrr_bridge", {})
    pdf.ln(1)
    pdf.emit("MRR bridge", bold=True)
    if bridge.get("available"):
        rows = []
        if bridge.get("closing_mrr") is not None:
            rows.append({"cells": ["Closing MRR", _fmt(bridge.get("closing_mrr")), bridge.get("closing_basis", "") or ""]})
        if bridge.get("new_mrr_added") is not None:
            rows.append({"cells": ["New MRR added", _fmt(bridge.get("new_mrr_added")),
                                   f"{bridge.get('new_mrr_matched_deals')}/{bridge.get('new_mrr_total_closes')} closes matched"]})
        if bridge.get("churn_mrr") is not None:
            rows.append({"cells": ["Churn MRR", _fmt(bridge.get("churn_mrr")), "forward-MRR engine"]})
        if rows:
            pdf.table(["Leg", "Value", "Basis"], rows, col_widths=[55, 45, 70])
        pdf.emit(_safe(bridge.get("note", "") or ""))
    else:
        pdf.emit(f"MRR bridge unavailable: {bridge.get('reason','no data')}.")

    months = sales.get("by_month", [])
    if months:
        pdf.ln(1)
        pdf.bar_chart("Monthly velocity — leads", [(m["month"], m.get("leads") or 0) for m in months])
        pdf.bar_chart("Monthly velocity — closes", [(m["month"], m.get("closes") or 0) for m in months])


def _comparison_table(pdf, cmp):
    if not cmp:
        return
    kind = cmp.get("kind", "")
    title = f"{kind}: {cmp.get('current_label','')} vs {cmp.get('prior_label','')}"
    pdf.emit(title, bold=True)
    if not cmp.get("available"):
        pdf.emit(_safe(cmp.get("note", f"{kind} not available.")))
        return
    rows = []
    for r in cmp.get("rows", []):
        if not r.get("available"):
            rows.append({"cells": [r["metric"], "n/a", "n/a", "not computable"], "color": MUTED})
            continue
        cur_v = r.get("current"); pr = r.get("prior"); d = r.get("delta"); pct = r.get("pct")
        # TYPE-AWARE (D1): every metric formats per its declared type — a ratio never renders as $.
        from quarterly_format import fmt_metric, fmt_delta
        m = r["metric"]
        rows.append({"cells": [m, fmt_metric(m, cur_v), fmt_metric(m, pr), fmt_delta(m, d, pct)]})
    pdf.table([kind, "Current", "Prior", "Delta"], rows, col_widths=[54, 38, 38, 40])
    pdf.emit(_safe(cmp.get("note", "") or ""))


def _roadmap_section(pdf, rm):
    """G5: channel mix, monthly ramp + spend schedule, CPL-drift band, creative cadence, weekly
    checkpoints, and the sequenced dated action list."""
    if not rm.get("available"):
        pdf.emit(f"Roadmap not computable — {rm.get('reason','missing lead/CPL data')}.")
        return
    pdf.emit_box(rm.get("framing", ""))

    # Channel decomposition
    cm = rm.get("channel_mix") or {}
    pdf.emit("Channel decomposition (current lead mix)", bold=True)
    if cm.get("available"):
        rows = [{"cells": [c["source"], fmt_metric("Leads", c["leads"]), f"{c['share_pct']}%"]}
                for c in cm.get("mix", [])]
        pdf.table(["Source", "Open leads", "Share"], rows, col_widths=[90, 45, 35])
        pdf.emit(_safe(cm.get("fill_note", "")))
    else:
        pdf.emit("Channel mix unavailable.")

    # The ramp + spend schedule
    pdf.ln(1)
    pdf.emit(f"The lead ramp — {rm.get('current_leads')} this quarter -> {rm.get('target_leads')} next "
             f"({rm.get('multiple'):.0f}x), graduated monthly (not flat)", bold=True)
    rows = [{"cells": [r["month"], fmt_metric("Leads", r["leads"]),
                       _fmt(r.get("spend")) if r.get("spend") is not None else "n/a"]} for r in rm.get("ramp", [])]
    pdf.table(["Month", "Leads target", "Ad spend at current CPL"], rows, col_widths=[60, 55, 55])

    # CPL-drift band
    band = rm.get("cpl_drift_band") or []
    if band:
        pdf.ln(1)
        pdf.emit("CPL-drift band — CPL is NOT held flat silently; the consequence of drift at 3x spend", bold=True)
        rows = []
        for b in band:
            rows.append({"cells": [f"+{b['cpl_drift_pct']}%", _fmt(b["cpl"]), _fmt(b["quarter_ad_spend"]),
                                   _fmt(b["cac_at_scale"]), fmt_metric("LTGP:CAC", b["ltgp_cac_at_scale"]),
                                   "yes" if b["stays_above_floor"] else "NO"],
                         "color": (GREEN if b["stays_above_floor"] else RED)})
        pdf.table(["CPL drift", "CPL", "Qtr ad spend", "CAC@scale", "LTGP:CAC", "Above floor?"],
                  rows, col_widths=[24, 26, 34, 30, 28, 28])

    # Creative cadence
    cr = rm.get("creative") or {}
    if cr.get("implication"):
        pdf.ln(1)
        pdf.emit("Creative cadence implication", bold=True)
        pdf.emit(_safe(cr["implication"]))

    # Weekly checkpoints
    cps = rm.get("checkpoints") or []
    if cps:
        pdf.ln(1)
        pdf.emit("Weekly checkpoints during the ramp", bold=True)
        rows = [{"cells": [c["metric"], c["on_track"], c["why"]]} for c in cps]
        pdf.table(["Watch weekly", "On-track threshold", "Why"], rows, col_widths=[52, 52, 66])

    # Sequenced actions
    acts = rm.get("actions") or []
    if acts:
        pdf.ln(1)
        pdf.emit("Sequenced Q3 actions (owners for you to assign)", bold=True)
        rows = [{"cells": [a["when"], a["action"]]} for a in acts]
        pdf.table(["When", "Action"], rows, col_widths=[34, 136])


def _grading_section(pdf, grading):
    """Self-improvement: last quarter's 3x model vs what actually happened. Renders only when a prior
    model was saved (so it appears from the second generation onward)."""
    if not grading or not grading.get("rows"):
        return
    pdf.ln(2)
    pdf.emit(f"Model track record — {grading.get('prior_label')}'s plan vs what happened", bold=True)
    rows = []
    for r in grading["rows"]:
        rows.append({"cells": [r["lever"], _fmt(r["required"]) if r["required"] else str(r["required"]),
                               _fmt(r["delivered"]) if r["delivered"] else str(r["delivered"]),
                               f"{r['achieved_pct']:.0f}%" if r.get("achieved_pct") is not None else "n/a"]})
    pdf.table(["Lever", "Modelled", "Delivered", "Achieved"], rows, col_widths=[60, 40, 40, 30])
    pdf.emit(_safe(grading.get("note", "")))


def _three_x_section(pdf, tx):
    if not tx:
        pdf.emit("3x model unavailable.")
        return
    from quarterly_format import fmt_metric
    M = tx.get("multiple", 3.0)
    targets = tx.get("targets", {})
    cur = tx.get("targets_current", {})   # D2: current values now bound (was blank)
    pdf.emit_box(tx.get("framing", ""))
    pdf.emit(f"The targets ({M:.0f}x this quarter's actuals)", bold=True)
    pdf.table(["Target metric", "This quarter", f"{M:.0f}x target"],
              [
                  {"cells": ["Contracted revenue", fmt_metric("Contracted revenue", cur.get("contracted_revenue")),
                             fmt_metric("Contracted revenue", targets.get("contracted_revenue"))]},
                  {"cells": ["New-deal cash collected", fmt_metric("New-deal cash collected", cur.get("new_deal_cash_collected")),
                             fmt_metric("New-deal cash collected", targets.get("new_deal_cash_collected"))]},
                  {"cells": ["Closes", fmt_metric("Closes", cur.get("closes")),
                             fmt_metric("Closes", targets.get("closes"))]},
              ], col_widths=[70, 40, 60])

    # Funnel — both paths
    fn = tx.get("funnel", {})
    vp = fn.get("volume_path") or {}; ep = fn.get("efficiency_path") or {}
    pdf.ln(1)
    pdf.emit("Funnel math — two paths to the required closes", bold=True)
    if vp:
        pdf.emit(_safe(f"Volume path: {vp.get('desc','')}  Needs ~{vp.get('leads_required')} leads, "
                       f"{vp.get('sets_required')} sets, {vp.get('shows_required')} shows "
                       f"[{_flag_badge(pdf, vp.get('flag'))}]."))
    if ep:
        pdf.emit(_safe(f"Efficiency path: {ep.get('desc','')}  [{_flag_badge(pdf, ep.get('flag'))}]"))

    # Spend
    sp = tx.get("spend", {})
    pdf.ln(1)
    pdf.emit("Spend math", bold=True)
    pdf.emit(_safe(f"At the current cost-per-lead of {_fmt(sp.get('cost_per_lead_current'))}, the volume "
                   f"path needs about {_fmt(sp.get('ad_spend_required'))} in ad spend (vs "
                   f"{_fmt(sp.get('ad_spend_current'))} this quarter). {sp.get('cac_assumption','')}. "
                   f"LTGP:CAC is {sp.get('ltgp_cac_current')}x and "
                   f"{'stays above' if sp.get('ltgp_cac_stays_above_floor') else 'falls below'} the "
                   f"{sp.get('floor')}x floor at that scale."))

    # Capacity
    cap = tx.get("capacity", {})
    if cap.get("available"):
        pdf.ln(1)
        pdf.emit("Capacity math", bold=True)
        pdf.emit(_safe(f"3x clients means {cap.get('current_active_clients')} -> "
                       f"{cap.get('target_clients')} active. At ~{cap.get('clients_per_delivery_hire')} "
                       f"clients per delivery hire, that's about {cap.get('hires_needed')} hires "
                       f"(~{cap.get('hire_lead_time_weeks')}wk lead time each) "
                       f"[{_flag_badge(pdf, cap.get('flag'))}]. {cap.get('gate_note','')}"))
        pdf.emit(_safe("Benchmark provenance: clients-per-hire (12) and hire lead time (4wk) set by "
                       "Rydel 2026-07-27; payroll:MRR gate 40% and LTGP:CAC floor 3.0x are Served "
                       "standing thresholds."))

    # Churn — always shown; when not computable, the reason prints (never a degenerate figure — D4)
    cm = tx.get("churn", {})
    pdf.ln(1)
    pdf.emit("Churn math", bold=True)
    pdf.emit(_safe(cm.get("note", "Not computable for this window.")))

    # Requirements table
    pdf.ln(1)
    pdf.emit("Requirements — required vs current, flagged", bold=True)
    rows = []
    for lv in tx.get("requirements_table", []):
        cur_v = lv.get("current"); req = lv.get("required")
        money = lv.get("unit", "").startswith("$")
        fmt = _fmt if money else (lambda x: f"{x}" if x is not None else "--")
        rows.append({"cells": [lv.get("lever"), fmt(cur_v), fmt(req), _flag_badge(pdf, lv.get("flag"))],
                     "color": _FLAG_COLOR.get(lv.get("flag"), DARK)})
    pdf.table(["Lever", "Current", "Required", "Flag"], rows, col_widths=[70, 33, 33, 34])

    # Binding constraint
    binding = tx.get("binding_constraint", {})
    pdf.ln(2)
    pdf.emit("The binding constraint", bold=True)
    pdf.emit_box(_safe(binding.get("verdict", "No single binding constraint could be named on the "
                                              "current data.")))
    notes = tx.get("notes", [])
    if notes:
        pdf.emit(_safe(" ".join(notes)))
