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
            {"cells": ["Loaded CAC", _fmt(comp.get("cac_loaded")), _safe(comp.get("cac_breakdown", "") or "")[:52]]},
            {"cells": ["LTGP:CAC", f"{ue.get('ltgp_cac','--')}x", f"floor {tx.get('assumptions',{}).get('ltgp_cac_floor','3.0')}x"]},
            {"cells": ["ROAS", f"{ue.get('roas','--')}x", "contracted / ad spend"]},
            {"cells": ["Ad spend", _fmt(comp.get("ad_spend")), _safe(comp.get("ad_spend_source", "") or "")]},
        ],
        col_widths=[50, 40, 80],
    )

    # ── MRR bridge + velocity ──
    _mrr_and_velocity(pdf, review)

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

    # ── verbatim guard ──
    audit_text = "\n".join(pdf._audit)
    violations = validate_verbatim(audit_text, review)
    if violations:
        raise ValueError(f"Verbatim-number check FAILED — {len(violations)} $-figure(s) not traceable "
                         f"to the pack: {violations[:8]}")

    out = pdf.output()
    return bytes(out)


# ── narrative + section builders (deterministic; numbers via _fmt of pack values) ──

def _exec_narrative(pdf, review):
    cur = review["current"]; rc = cur["revenue_cash"]; ue = cur.get("unit_economics", {})
    comp = ue.get("components", {}) if isinstance(ue, dict) else {}
    tx = review.get("three_x", {})
    binding = tx.get("binding_constraint", {})
    qoq = review.get("comparisons", {}).get("qoq", {})
    contracted = rc.get("contracted_revenue"); closes = comp.get("closes")
    ltgp = ue.get("ltgp_cac") if isinstance(ue, dict) else None
    parts = []
    if contracted is not None and closes is not None:
        parts.append(f"{review['quarter']['label']} closed {closes} deals for {_fmt(contracted)} in "
                     f"contracted revenue and {_fmt(rc.get('new_deal_cash_collected'))} in new-deal cash.")
    if ltgp is not None:
        parts.append(f"Unit economics held at {ltgp}x LTGP:CAC on a loaded CAC of {_fmt(comp.get('cac_loaded'))}"
                     f" — {'above' if (ltgp and ltgp>=3) else 'below'} the 3x line.")
    if qoq and qoq.get("available"):
        parts.append(f"Versus {qoq.get('prior_label')}, {qoq.get('comparable_fields')} of "
                     f"{qoq.get('total_fields')} metrics were like-basis comparable (see section 3).")
    pdf.emit(" ".join(parts))
    if binding.get("lever"):
        pdf.emit_box(f"To 3x overall growth next quarter, the binding constraint is "
                     f"{binding.get('lever')} ({_flag_badge(pdf, binding.get('flag'))}). "
                     "The fundable levers (leads, ad spend) hold because unit economics stay above the "
                     "floor at scale; the wall is operational. Full model in section 4.")


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
        # format: money-ish metrics via _fmt, ratios/counts raw
        money = any(k in r["metric"] for k in ("revenue", "cash", "CAC", "spend", "contract", "profit"))
        fmt = _fmt if money else (lambda x: f"{x}")
        rows.append({"cells": [r["metric"], fmt(cur_v), fmt(pr),
                               f"{'+' if (d or 0)>=0 else ''}{fmt(d)}" + (f" ({pct:+.0f}%)" if pct is not None else "")]})
    pdf.table([kind, "Current", "Prior", "Delta"], rows, col_widths=[54, 38, 38, 40])
    pdf.emit(_safe(cmp.get("note", "") or ""))


def _three_x_section(pdf, tx):
    if not tx:
        pdf.emit("3x model unavailable.")
        return
    M = tx.get("multiple", 3.0)
    targets = tx.get("targets", {})
    pdf.emit_box(tx.get("framing", ""))
    pdf.emit(f"The targets ({M:.0f}x this quarter's actuals)", bold=True)
    pdf.table(["Target metric", "This quarter", f"{M:.0f}x target"],
              [
                  {"cells": ["Contracted revenue", "", _fmt(targets.get("contracted_revenue"))]},
                  {"cells": ["New-deal cash collected", "", _fmt(targets.get("new_deal_cash_collected"))]},
                  {"cells": ["Closes", "", str(targets.get("closes", "--"))]},
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

    # Churn
    cm = tx.get("churn", {})
    if cm.get("available"):
        pdf.ln(1)
        pdf.emit("Churn math", bold=True)
        pdf.emit(_safe(cm.get("note", "")))

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
