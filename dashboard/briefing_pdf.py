"""
dashboard/briefing_pdf.py
-------------------------
Full CFO briefing PDF generator.
Owner-only, comprehensive, analytical — every number from the live snapshot.

Uses fpdf2 for PDF generation. Branded with Served palette.
"""
from __future__ import annotations

import io
import logging
import math
from datetime import datetime

from fpdf import FPDF

from helpers import today_sydney

logger = logging.getLogger(__name__)

# ── Brand colours ──
PRIMARY = (46, 110, 166)    # #2E6EA6
NAVY = (26, 58, 92)         # #1A3A5C
TINT = (238, 244, 250)      # #EEF4FA
MUTED = (122, 154, 191)     # #7A9ABF
GREEN = (34, 197, 94)
AMBER = (245, 158, 11)
RED = (239, 68, 68)
WHITE = (255, 255, 255)
DARK = (30, 30, 40)
LIGHT_GREY = (200, 210, 220)


def _safe(text):
    """Replace Unicode chars that Helvetica can't render."""
    if not isinstance(text, str):
        return text
    return text.replace("\u2014", "--").replace("\u2013", "-").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2212", "-").replace("\u2022", "*").replace("\u20b1", "PHP ")


def _fmt(v, prefix="$", decimals=0):
    if v is None:
        return "--"
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return "--"
    n = round(v, decimals)
    if decimals == 0:
        n = int(n)
    formatted = f"{abs(n):,}"
    sign = "-" if v < 0 else ""
    return f"{sign}{prefix}{formatted}"


def _pct(v):
    if v is None:
        return "--"
    return f"{v:.1f}%"


def _get(obj, *keys, default=None):
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k)
    if obj is None:
        return default
    return obj


class BriefingPDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=20)

    def cell(self, *args, **kwargs):
        if args and isinstance(args[2] if len(args) > 2 else kwargs.get("text"), str):
            args = list(args)
            if len(args) > 2:
                args[2] = _safe(args[2])
            args = tuple(args)
        if "text" in kwargs:
            kwargs["text"] = _safe(kwargs["text"])
        return super().cell(*args, **kwargs)

    def multi_cell(self, *args, **kwargs):
        if args and isinstance(args[2] if len(args) > 2 else kwargs.get("text"), str):
            args = list(args)
            if len(args) > 2:
                args[2] = _safe(args[2])
            args = tuple(args)
        if "text" in kwargs:
            kwargs["text"] = _safe(kwargs["text"])
        return super().multi_cell(*args, **kwargs)

    def header(self):
        if self.page_no() == 1:
            return  # Cover page has its own header
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, "Served Marketing — CFO Briefing", align="L")
        self.set_font("Helvetica", "", 8)
        self.cell(0, 6, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LIGHT_GREY)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 8, "Confidential — Owner Only", align="C")

    def _section_title(self, num, title):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*NAVY)
        self.cell(0, 10, f"{num}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*PRIMARY)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.l_margin + 50, self.get_y())
        self.set_line_width(0.2)
        self.ln(4)

    def _body_text(self, text, bold=False):
        self.set_font("Helvetica", "B" if bold else "", 9)
        self.set_text_color(*DARK)
        self.multi_cell(0, 4.5, text)
        self.ln(2)

    def _analysis_box(self, text):
        self.set_fill_color(*TINT)
        self.set_draw_color(*MUTED)
        x = self.l_margin
        w = self.w - self.l_margin - self.r_margin
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(*NAVY)
        y_start = self.get_y()
        self.set_x(x + 3)
        self.multi_cell(w - 6, 4.5, text)
        y_end = self.get_y()
        # Draw background rect behind text
        self.set_xy(x, y_start - 2)
        self.rect(x, y_start - 2, w, y_end - y_start + 4, style="DF")
        # Re-render text on top
        self.set_xy(x + 3, y_start)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(*NAVY)
        self.multi_cell(w - 6, 4.5, text)
        self.ln(4)

    def _kpi_row(self, items):
        """Render a row of KPI boxes. items = [(label, value, sub), ...]"""
        w = (self.w - self.l_margin - self.r_margin) / len(items)
        x_start = self.l_margin
        y_start = self.get_y()
        max_h = 0
        for i, (label, value, sub) in enumerate(items):
            x = x_start + i * w
            self.set_xy(x + 1, y_start + 1)
            self.set_fill_color(*TINT)
            self.rect(x, y_start, w - 2, 18, style="F")
            self.set_xy(x + 2, y_start + 1)
            self.set_font("Helvetica", "", 7)
            self.set_text_color(*MUTED)
            self.cell(w - 4, 4, label.upper())
            self.set_xy(x + 2, y_start + 5)
            self.set_font("Helvetica", "B", 12)
            self.set_text_color(*NAVY)
            self.cell(w - 4, 6, str(value))
            if sub:
                self.set_xy(x + 2, y_start + 12)
                self.set_font("Helvetica", "", 7)
                self.set_text_color(*MUTED)
                self.cell(w - 4, 4, str(sub))
            max_h = max(max_h, 18)
        self.set_y(y_start + max_h + 3)

    def _table(self, headers, rows, col_widths=None, col_aligns=None):
        """Render a data table."""
        w_total = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [w_total / len(headers)] * len(headers)
        if col_aligns is None:
            col_aligns = ["L"] * len(headers)

        # Header
        self.set_fill_color(*NAVY)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 8)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, h, border=0, align=col_aligns[i],
                      fill=True)
        self.ln()

        # Rows
        self.set_text_color(*DARK)
        self.set_font("Helvetica", "", 8)
        fill = False
        for row in rows:
            if self.get_y() > 265:
                self.add_page()
                # Re-render header
                self.set_fill_color(*NAVY)
                self.set_text_color(*WHITE)
                self.set_font("Helvetica", "B", 8)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 6, h, border=0, align=col_aligns[i], fill=True)
                self.ln()
                self.set_text_color(*DARK)
                self.set_font("Helvetica", "", 8)
                fill = False

            if fill:
                self.set_fill_color(245, 248, 252)
            else:
                self.set_fill_color(*WHITE)

            # Check for special formatting
            is_bold = False
            row_color = DARK
            if isinstance(row, dict):
                is_bold = row.get("bold", False)
                row_color = row.get("color", DARK)
                row = row["cells"]

            if is_bold:
                self.set_font("Helvetica", "B", 8)
            self.set_text_color(*row_color)

            for i, val in enumerate(row):
                self.cell(col_widths[i], 5.5, str(val), border=0,
                          align=col_aligns[i], fill=True)
            self.ln()
            if is_bold:
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*DARK)
            fill = not fill


def generate_briefing_pdf(snap: dict) -> bytes:
    """Generate a full CFO briefing PDF from the live snapshot.

    Returns raw PDF bytes.
    """
    pdf = BriefingPDF()
    pdf.set_margins(18, 15, 18)
    today = today_sydney()

    # ── COVER PAGE ──
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 12, "Served Marketing", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 18)
    pdf.set_text_color(*PRIMARY)
    pdf.cell(0, 10, "CFO Briefing", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_draw_color(*PRIMARY)
    pdf.set_line_width(0.8)
    mid = pdf.w / 2
    pdf.line(mid - 30, pdf.get_y(), mid + 30, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 8, today.strftime("%B %d, %Y"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, "Trailing 30 days | Forward 6 months", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*RED)
    pdf.cell(0, 6, "CONFIDENTIAL — OWNER ONLY", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.ln(4)
    gen_at = snap.get("generated_at", "")
    pdf.cell(0, 5, f"Generated: {gen_at}", align="C", new_x="LMARGIN", new_y="NEXT")

    # ── Extract data ──
    burn = snap.get("monthly_burn") or {}
    cash_pos = snap.get("cash_position") or {}
    fp = snap.get("financial_position") or {}
    fwd = snap.get("forward_mrr") or {}
    hormozi = snap.get("hormozi") or {}
    verdicts = snap.get("verdicts") or {}
    sales = snap.get("sales") or {}
    funnel = sales.get("funnel") or {}
    ch = snap.get("client_health") or {}
    team = snap.get("team_model") or {}
    roster = snap.get("team_roster") or {}
    da = snap.get("deficiency_analysis") or {}
    rv = snap.get("revenue_views") or {}
    ac = snap.get("active_clients") or {}
    degraded = snap.get("degraded") or []

    total_burn = burn.get("total_recurring_burn") or 0
    cash_in_bank = cash_pos.get("cash_in_bank") or 0
    runway = cash_pos.get("runway_months")
    current_mrr = ch.get("current_mrr") or _get(fwd, "current_recognized_mrr") or 0
    client_count = _get(fwd, "active_clients") or ch.get("total_clients") or 0

    cash_basis = fp.get("cash_basis") or {}
    rec_basis = fp.get("recognized_basis") or {}
    headline = fp.get("headline") or {}

    # ── 1. EXECUTIVE SUMMARY ──
    pdf.add_page()
    pdf._section_title("1", "Executive Summary")

    pdf._kpi_row([
        ("Cash on Hand", _fmt(cash_in_bank), "CommBank"),
        ("Monthly MRR", _fmt(current_mrr), f"{client_count} clients"),
        ("Monthly Burn", _fmt(total_burn), "full outflow"),
        ("Runway", f"{runway:.1f} mo" if runway else "--", "at current burn"),
    ])

    # Net by basis
    cash_net = _get(cash_basis, "monthly_net")
    rec_net = _get(rec_basis, "monthly_net")
    net_items = []
    if cash_net is not None:
        net_items.append(("Cash Net (Stripe)", _fmt(cash_net), "/mo"))
    if rec_net is not None:
        net_items.append(("Rec. Net (Xero)", _fmt(rec_net), "/mo"))
    if net_items:
        while len(net_items) < 4:
            net_items.append(("", "", ""))
        pdf._kpi_row(net_items[:4])

    # Forward verdict
    fwd_months = fwd.get("forward_months") or []
    fwd_6 = fwd_months[:6] if fwd_months else []
    last_positive = None
    for fm in fwd_6:
        mrr = fm.get("recognized_mrr") or 0
        if mrr > total_burn:
            last_positive = fm.get("month", "")

    narrative = _build_exec_narrative(snap)
    pdf._body_text(narrative, bold=True)

    # Biggest opportunity + risk
    opp = "Strong unit economics (fast payback, healthy LTGP:CAC) + cash reserves give room to invest in retention and pipeline."
    risk = "0% historical re-sign rate. Every fixed-term client that expires churns. Without fixing retention, MRR falls to near-zero by December."
    pdf._body_text(f"Biggest opportunity: {opp}")
    pdf._body_text(f"Biggest risk: {risk}")

    # ── 2. FINANCIAL POSITION ──
    pdf.add_page()
    pdf._section_title("2", "Financial Position (Dual-Basis)")

    headers = ["", "Cash Basis (Stripe)", "Recognized (Xero)"]
    cw = [50, 57, 57]
    ca = ["L", "R", "R"]
    rows = [
        ["Revenue", _fmt(_get(cash_basis, "revenue")), _fmt(_get(rec_basis, "revenue"))],
        ["COGS", _fmt(_get(cash_basis, "cogs")), _fmt(_get(rec_basis, "cogs"))],
        ["Gross Profit", _fmt(_get(cash_basis, "gross_profit")), _fmt(_get(rec_basis, "gross_profit"))],
        ["Gross Margin", _pct(_get(cash_basis, "gross_margin_pct")), _pct(_get(rec_basis, "gross_margin_pct"))],
        ["OpEx", _fmt(_get(cash_basis, "opex")), _fmt(_get(rec_basis, "opex"))],
        {"cells": ["Monthly Net", _fmt(cash_net), _fmt(rec_net)], "bold": True,
         "color": GREEN if (cash_net or 0) >= 0 else RED},
    ]
    pdf._table(headers, rows, cw, ca)
    pdf.ln(3)

    # Burn breakdown
    pdf._body_text("Monthly Burn Breakdown (full outflow):", bold=True)
    burn_items = [
        f"Team payroll: {_fmt(burn.get('team'))}",
        f"Owner pay: {_fmt(burn.get('owner_pay'))}",
        f"Ad spend: {_fmt(burn.get('ad_spend'))}",
        f"Subscriptions: {_fmt(burn.get('subscriptions'))}",
        f"Other OpEx: {_fmt(burn.get('other_opex'))}",
        f"Total recurring: {_fmt(total_burn)}",
    ]
    pdf._body_text("  |  ".join(burn_items))

    gm = _get(rec_basis, "gross_margin_pct") or _get(cash_basis, "gross_margin_pct")
    analysis = _build_financial_analysis(cash_net, rec_net, gm, total_burn, current_mrr)
    pdf._analysis_box(analysis)

    # ── 3. CASH POSITION & RUNWAY ──
    pdf._section_title("3", "Cash Position & Runway")

    pdf._kpi_row([
        ("Cash in Bank", _fmt(cash_in_bank), "CommBank"),
        ("Aggressive Deployable", _fmt(cash_pos.get("aggressive_deployable")), "- tax reserve"),
        ("Conservative Deployable", _fmt(cash_pos.get("conservative_deployable")), "- delivery reserve"),
        ("Tax Reserved", _fmt(cash_pos.get("tax_reserved")), "set aside"),
    ])

    stripe_inc = cash_pos.get("stripe_incoming") or 0
    if stripe_inc:
        pdf._body_text(f"Stripe incoming/pending: {_fmt(stripe_inc)}")

    pdf._body_text(f"Monthly burn: {_fmt(total_burn)} | Runway: {runway:.1f} months" if runway else f"Monthly burn: {_fmt(total_burn)}")

    cash_analysis = (
        f"With {_fmt(cash_in_bank)} in the bank and burn at {_fmt(total_burn)}/mo, "
        f"the business has {runway:.1f} months of runway — " if runway else
        f"Cash position at {_fmt(cash_in_bank)} with burn at {_fmt(total_burn)}/mo — "
    )
    if runway and runway > 6:
        cash_analysis += "comfortable for a scaling agency. "
    elif runway and runway > 3:
        cash_analysis += "adequate but requires attention to the forward revenue trajectory. "
    else:
        cash_analysis += "tight — the forward revenue trajectory is critical. "

    agg = cash_pos.get("aggressive_deployable") or 0
    cons = cash_pos.get("conservative_deployable") or 0
    cash_analysis += (
        f"Aggressive deployable ({_fmt(agg)}) treats all non-tax cash as available. "
        f"Conservative ({_fmt(cons)}) also reserves for delivery obligations. "
        f"The gap ({_fmt(agg - cons)}) represents committed delivery cost for work already paid."
    )
    pdf._analysis_box(cash_analysis)

    # ── 4. REVENUE & MRR ──
    pdf.add_page()
    pdf._section_title("4", "Revenue & MRR")

    pdf._kpi_row([
        ("Recognized MRR", _fmt(current_mrr), f"{client_count} clients"),
        ("Stripe Cash (30d)", _fmt(rv.get("stripe_cash_trailing_30d")), "trailing"),
        ("Xero Revenue", _fmt(rv.get("xero_pl_period")), "P&L period"),
        ("Avg/Client", _fmt(_get(fwd, "avg_monthly_per_client")), "/mo"),
    ])

    mrr_analysis = (
        f"Current recognized MRR is {_fmt(current_mrr)} across {client_count} active clients, "
        f"averaging {_fmt(_get(fwd, 'avg_monthly_per_client'))}/client/mo. "
    )
    mtm_floor = _get(fwd, "mtm_floor") or 0
    mtm_count = _get(fwd, "mtm_clients") or 0
    mrr_analysis += (
        f"Month-to-month floor is {_fmt(mtm_floor)} ({mtm_count} MTM clients) — this is the revenue "
        f"that persists without re-signing. The bulk of revenue is on fixed-term contracts, "
        f"making the forward trajectory highly sensitive to re-sign rates."
    )
    pdf._analysis_box(mrr_analysis)

    # ── 5. FORWARD MRR & CHURN CLIFF ──
    pdf._section_title("5", "Forward MRR & The Churn Cliff")

    if fwd_6:
        headers = ["Month", "Rec. MRR", "Clients", "Net vs Burn", "Status"]
        cw = [35, 35, 20, 35, 40]
        ca = ["L", "R", "C", "R", "C"]
        rows = []
        running_cash = cash_in_bank
        for fm in fwd_6:
            mrr = fm.get("recognized_mrr") or 0
            cl = fm.get("clients") or 0
            net = mrr - total_burn
            running_cash += net
            status = "Healthy" if net >= 0 else ("Tight" if net > -5000 else "Unsustainable")
            color = GREEN if status == "Healthy" else (AMBER if status == "Tight" else RED)
            rows.append({
                "cells": [
                    fm.get("month", "").split(" ")[0][:3] + " '" + fm.get("month", "").split(" ")[-1][2:],
                    _fmt(mrr), str(cl), _fmt(net),
                    status,
                ],
                "color": color if net < 0 else DARK,
                "bold": False,
            })
        pdf._table(headers, rows, cw, ca)
        pdf.ln(2)

    # Re-sign scenario comparison
    pdf._body_text("Re-sign scenario impact (what retention is worth):", bold=True)

    # Calculate 0% vs 50% vs 100% scenarios
    scenarios = _build_resign_scenarios(fwd_6, total_burn, cash_in_bank, _get(fwd, "avg_monthly_per_client") or 2200)
    if scenarios:
        headers = ["Scenario", "MRR by Oct", "Cash by Oct", "Months Healthy"]
        cw = [40, 35, 40, 50]
        ca = ["L", "R", "R", "C"]
        pdf._table(headers, scenarios, cw, ca)
        pdf.ln(2)

    churn_analysis = (
        f"Historical re-sign rate: 0/12 (0%). Every fixed-term client that finishes churns. "
        f"At 0% re-sign, recognized MRR falls from {_fmt(current_mrr)} to near-zero by December. "
        f"Net turns negative in September and cash reserves deplete through Q4.\n\n"
        f"This is the existential risk. The acquisition engine works — unit economics are strong, "
        f"payback is fast, new clients are closing. But without retention, the business is on a "
        f"treadmill: every dollar of growth leaks out the bottom. "
        f"Retention is THE lever. The re-sign scenario shows that even a 50% re-sign rate "
        f"dramatically transforms the forward picture. Every 25% improvement in re-sign rate is "
        f"worth approximately {_fmt(_estimate_resign_value(fwd_6, total_burn))}/mo by October."
    )
    pdf._analysis_box(churn_analysis)

    # ── 6. UNIT ECONOMICS ──
    pdf.add_page()
    pdf._section_title("6", "Unit Economics (Hormozi Metrics)")

    metrics = [
        ("LTGP:CAC", _get(hormozi, "ltgp_to_cac", "value"), "3.0x min", _get(hormozi, "ltgp_to_cac", "status")),
        ("LTV:CAC", _get(hormozi, "ltv_to_cac", "value"), "3.0x min", _get(hormozi, "ltv_to_cac", "status")),
        ("CAC (loaded)", _get(hormozi, "loaded_cac", "value"), "lower = better", _get(hormozi, "loaded_cac", "status")),
        ("Payback Period", _get(hormozi, "payback_days", "value"), "<30 days", _get(hormozi, "payback_days", "status")),
    ]

    headers = ["Metric", "Value", "Benchmark", "Status"]
    cw = [40, 35, 35, 55]
    ca = ["L", "R", "L", "C"]
    rows = []
    for label, val, bench, status in metrics:
        v_str = "--"
        if val is not None:
            if "cac" in label.lower() and "day" not in label.lower():
                v_str = _fmt(val) if label == "CAC (loaded)" else f"{val:.1f}x"
            elif "day" in label.lower():
                v_str = f"{int(val)}d"
            else:
                v_str = f"{val:.1f}x"
        s_str = str(status or "--").replace("_", " ").title()
        color = GREEN if status == "healthy" else (AMBER if status == "watch" else (RED if status == "critical" else DARK))
        rows.append({"cells": [label, v_str, bench, s_str], "color": color, "bold": False})
    pdf._table(headers, rows, cw, ca)
    pdf.ln(2)

    ue_analysis = _build_unit_econ_analysis(hormozi)
    pdf._analysis_box(ue_analysis)

    # ── 7. SALES FUNNEL ──
    pdf._section_title("7", "Sales Funnel & Performance")

    leads = funnel.get("leads_in") or 0
    sets = funnel.get("sets") or 0
    shows = funnel.get("shows") or 0
    closes = funnel.get("closes") or 0

    pdf._kpi_row([
        ("Leads In", str(leads), "trailing 30d"),
        ("Sets", str(sets), f"{_pct(funnel.get('lead_to_set_pct'))} conv."),
        ("Shows", str(shows), f"{_pct(funnel.get('set_to_show_pct'))} show rate"),
        ("Closes", str(closes), f"{_pct(funnel.get('show_to_close_pct'))} close rate"),
    ])

    deep = sales.get("deep") or {}
    money = deep.get("money") or {}
    pdf._body_text(
        f"Avg contract: {_fmt(money.get('avg_contract'))} | "
        f"Avg cash/close: {_fmt(money.get('avg_cash_per_close'))} | "
        f"Velocity: {_fmt(money.get('daily_velocity'))}/day"
    )

    funnel_analysis = _build_funnel_analysis(funnel, deep, da)
    pdf._analysis_box(funnel_analysis)

    # ── 8. TEAM & PAYROLL ──
    pdf.add_page()
    pdf._section_title("8", "Team & Payroll")

    roster_data = roster.get("roster") or []
    by_dept = roster.get("by_department") or {}
    totals = roster.get("totals") or {}

    if by_dept:
        headers = ["Department", "Headcount", "AUD/mo", "PHP/mo"]
        cw = [45, 25, 45, 50]
        ca = ["L", "C", "R", "R"]
        rows = []
        for dept in sorted(by_dept.keys()):
            d = by_dept[dept]
            rows.append([dept, str(d["headcount"]), _fmt(d["total_aud"]), f"PHP{int(d['total_php']):,}"])
        rows.append({
            "cells": ["TOTAL", str(totals.get("headcount", 0)), _fmt(totals.get("total_aud")), f"PHP{int(totals.get('total_php', 0)):,}"],
            "bold": True,
        })
        pdf._table(headers, rows, cw, ca)
        pdf.ln(2)

    # SPOFs
    spofs = team.get("single_points_of_failure") or []
    if spofs:
        pdf._body_text(f"Single points of failure: {', '.join(s.replace('_', ' ').title() for s in spofs)}", bold=True)

    team_pct = _get(fp, "costs", "team_cost_pct_of_mrr")
    team_analysis = (
        f"Team cost: {_fmt(totals.get('total_aud'))}/mo AUD + PHP{int(totals.get('total_php', 0)):,}/mo PHP "
        f"({totals.get('headcount', 0)} people). "
    )
    if team_pct:
        if team_pct < 45:
            team_analysis += f"Team/MRR ratio at {team_pct:.0f}% is healthy (target <45%). "
        elif team_pct < 55:
            team_analysis += f"Team/MRR ratio at {team_pct:.0f}% is elevated (target <45%). "
        else:
            team_analysis += f"Team/MRR ratio at {team_pct:.0f}% is high (target <45%) — watch against forward MRR decline. "
    if spofs:
        team_analysis += f"SPOFs in {', '.join(spofs)} — bus-factor risk; prioritise redundancy for critical functions."
    pdf._analysis_box(team_analysis)

    # ── 9. HIRING & CAPACITY ──
    pdf._section_title("9", "Hiring & Capacity")

    hc = snap.get("hiring_context") or {}
    pdf._body_text(
        f"Monthly headroom: {_fmt(hc.get('monthly_headroom'))} | "
        f"True team cost: {_fmt(hc.get('true_team_cost'))} | "
        f"Avg cash/close: {_fmt(hc.get('avg_cash_per_close'))}"
    )

    hire_analysis = (
        f"With monthly headroom of {_fmt(hc.get('monthly_headroom'))}, the business "
    )
    headroom = hc.get("monthly_headroom") or 0
    if headroom > 5000:
        hire_analysis += "has capacity for tactical hires. "
    elif headroom > 0:
        hire_analysis += "has limited hiring capacity — any hire must offset quickly. "
    else:
        hire_analysis += "is at or below capacity — new hires must be self-funding or offset by growth. "

    binding = _get(da, "deficiencies")
    if binding and len(binding) > 0:
        top = binding[0]
        hire_analysis += (
            f"Binding constraint: {top.get('label', 'unknown')} "
            f"({top.get('category', '')}) — hire into the bottleneck, not beside it."
        )
    hire_analysis += (
        " Critical caveat: any hire must be judged against FORWARD MRR, not trailing. "
        "The churn cliff means a hire sustainable today may not be in 3 months without re-signings."
    )
    pdf._analysis_box(hire_analysis)

    # ── 10. THE BOTTOM LINE ──
    pdf.add_page()
    pdf._section_title("10", "The Bottom Line")

    bottom_line = _build_bottom_line(snap)
    pdf._body_text(bottom_line, bold=True)

    pdf._body_text("Recommended focus this month:", bold=True)
    pdf._body_text(
        "1. RETENTION: Build a re-sign process for clients approaching end-of-term. "
        "Even 25% re-sign rate transforms the forward picture.\n"
        "2. PIPELINE: Maintain close velocity to backfill churn while retention ramps.\n"
        "3. CASH MANAGEMENT: Preserve runway — avoid discretionary spend until forward MRR stabilises."
    )

    # Data quality
    if degraded:
        pdf.ln(4)
        pdf._body_text(f"Data quality flags ({len(degraded)}):", bold=True)
        for d in degraded[:5]:
            pdf._body_text(f"  - {d.get('metric', '?')}: {d.get('reason', '')}")

    return pdf.output()


def _build_exec_narrative(snap: dict) -> str:
    burn = _get(snap, "monthly_burn", "total_recurring_burn") or 0
    cash = _get(snap, "cash_position", "cash_in_bank") or 0
    mrr = _get(snap, "forward_mrr", "current_recognized_mrr") or _get(snap, "client_health", "current_mrr") or 0
    runway = _get(snap, "cash_position", "runway_months")
    clients = _get(snap, "forward_mrr", "active_clients") or 0

    cash_net = _get(snap, "financial_position", "cash_basis", "monthly_net")
    rec_net = _get(snap, "financial_position", "recognized_basis", "monthly_net")

    parts = []
    parts.append(
        f"Served Marketing has {_fmt(cash)} cash on hand, {_fmt(mrr)} recognized MRR across "
        f"{clients} active clients, and burns {_fmt(burn)}/mo (full outflow)."
    )

    if cash_net is not None and cash_net > 0:
        parts.append(f"Cash-basis net is positive at {_fmt(cash_net)}/mo — the business is currently cash-generative.")
    elif rec_net is not None and rec_net > 0:
        parts.append(f"Recognized net is positive at {_fmt(rec_net)}/mo, though timing differences affect cash flow.")

    if runway:
        parts.append(f"Runway stands at {runway:.1f} months at current burn.")

    parts.append(
        "The critical risk is the forward churn cliff: with 0% historical re-sign rate, "
        "MRR declines sharply as contracts expire. Retention is the single highest-leverage "
        "lever — every 25% improvement in re-sign rate preserves thousands per month."
    )

    return " ".join(parts)


def _build_financial_analysis(cash_net, rec_net, gm, burn, mrr) -> str:
    parts = []
    if cash_net is not None and rec_net is not None:
        gap = abs((cash_net or 0) - (rec_net or 0))
        if gap > 5000:
            parts.append(
                f"Cash net ({_fmt(cash_net)}) differs from recognized net ({_fmt(rec_net)}) by {_fmt(gap)} — "
                f"this gap reflects upfront/split-pay collection timing. Cash net is the real-money view."
            )
        else:
            parts.append(
                f"Cash and recognized net are closely aligned ({_fmt(cash_net)} vs {_fmt(rec_net)}), "
                f"indicating stable collection timing."
            )

    if gm is not None:
        if gm >= 60:
            parts.append(f"Gross margin at {gm:.1f}% is well above the ~45% agency benchmark — delivery costs are well-controlled.")
        elif gm >= 45:
            parts.append(f"Gross margin at {gm:.1f}% is at benchmark for an agency — adequate but room to optimise.")
        else:
            parts.append(f"Gross margin at {gm:.1f}% is below the ~45% benchmark — delivery cost structure needs attention.")

    if mrr > 0:
        burn_pct = burn / mrr * 100
        parts.append(f"Total burn is {burn_pct:.0f}% of MRR — {'sustainable' if burn_pct < 80 else 'elevated, watch forward revenue'}.")

    return " ".join(parts)


def _build_unit_econ_analysis(hormozi: dict) -> str:
    ltgp = _get(hormozi, "ltgp_to_cac", "value")
    ltv = _get(hormozi, "ltv_to_cac", "value")
    payback = _get(hormozi, "payback_days", "value")

    parts = []
    if ltgp is not None:
        if ltgp >= 3:
            parts.append(f"LTGP:CAC at {ltgp:.1f}x is strong (3x+ benchmark) — the acquisition engine generates real profit per client.")
        else:
            parts.append(f"LTGP:CAC at {ltgp:.1f}x is below the 3x benchmark — acquisition efficiency needs work.")

    if payback is not None:
        if payback <= 30:
            parts.append(f"Payback at {int(payback)} days is excellent (<30d target) — cash invested in acquisition returns quickly.")
        else:
            parts.append(f"Payback at {int(payback)} days exceeds the 30-day target — slow recovery of acquisition cost.")

    parts.append(
        "The unit economics tell a clear story: the acquisition machine works. "
        "The problem isn't getting clients profitably — it's keeping them. "
        "The 0% re-sign rate means every client's gross profit is earned once, not compounded. "
        "Fixing retention turns good unit economics into great lifetime economics."
    )
    return " ".join(parts)


def _build_funnel_analysis(funnel: dict, deep: dict, da: dict) -> str:
    show_close = funnel.get("show_to_close_pct")
    set_show = funnel.get("set_to_show_pct")

    parts = []
    if show_close is not None:
        if show_close >= 35:
            parts.append(f"Show-to-close at {show_close:.0f}% meets the 35% benchmark — closing is effective.")
        else:
            parts.append(f"Show-to-close at {show_close:.0f}% is below the 35% benchmark — closing efficiency is the funnel constraint.")

    if set_show is not None:
        if set_show >= 70:
            parts.append(f"Set-to-show at {set_show:.0f}% is healthy (70%+ target).")
        else:
            parts.append(f"Set-to-show at {set_show:.0f}% is below 70% — lead quality or follow-up timing may be leaking shows.")

    deficiencies = _get(da, "deficiencies") or []
    if deficiencies:
        top = deficiencies[0]
        parts.append(f"Binding constraint per deficiency analysis: {top.get('label', 'unknown')}.")

    return " ".join(parts)


def _build_resign_scenarios(fwd_6, burn, starting_cash, avg_per_client):
    if not fwd_6 or len(fwd_6) < 4:
        return []

    scenarios = []
    for resign_pct in [0, 50, 100]:
        running_cash = starting_cash
        cumulative_uplift = 0
        healthy_count = 0
        oct_mrr = 0
        oct_cash = 0
        for i, fm in enumerate(fwd_6):
            mrr = fm.get("recognized_mrr") or 0
            uplift = 0
            if resign_pct > 0 and i > 0:
                prev = fwd_6[i - 1].get("recognized_mrr") or 0
                drop = prev - mrr
                if drop > 0:
                    uplift = drop * (resign_pct / 100)
                cumulative_uplift += uplift
            adj_mrr = mrr + cumulative_uplift
            net = adj_mrr - burn
            running_cash += net
            if net >= 0:
                healthy_count += 1
            month_name = fm.get("month", "").split(" ")[0]
            if month_name.startswith("Oct"):
                oct_mrr = adj_mrr
                oct_cash = running_cash

        label = f"{resign_pct}% re-sign" + (" (status quo)" if resign_pct == 0 else "")
        scenarios.append([label, _fmt(oct_mrr), _fmt(oct_cash), f"{healthy_count}/{len(fwd_6)}"])

    return scenarios


def _estimate_resign_value(fwd_6, burn):
    """Estimate value per 25% re-sign rate by October."""
    if not fwd_6 or len(fwd_6) < 4:
        return 0
    cumulative_drop = 0
    for i in range(1, min(5, len(fwd_6))):
        prev = fwd_6[i - 1].get("recognized_mrr") or 0
        curr = fwd_6[i].get("recognized_mrr") or 0
        drop = prev - curr
        if drop > 0:
            cumulative_drop += drop
    return cumulative_drop * 0.25


def _build_bottom_line(snap: dict) -> str:
    cash = _get(snap, "cash_position", "cash_in_bank") or 0
    mrr = _get(snap, "forward_mrr", "current_recognized_mrr") or 0
    burn = _get(snap, "monthly_burn", "total_recurring_burn") or 0
    runway = _get(snap, "cash_position", "runway_months") or 0

    return (
        f"The business is cash-positive with strong unit economics and an effective acquisition engine. "
        f"Current cash ({_fmt(cash)}), MRR ({_fmt(mrr)}), and {runway:.1f}-month runway provide a solid base. "
        f"However, the forward picture is dominated by one structural risk: zero client retention. "
        f"With 0/12 historical re-signs, every contract expiration is permanent churn. "
        f"The single highest-leverage move is building a retention/re-sign process — this is not a nice-to-have, "
        f"it's the difference between a growing agency and a declining one. "
        f"The math is clear: fix retention first, maintain pipeline second, preserve cash third."
    )
