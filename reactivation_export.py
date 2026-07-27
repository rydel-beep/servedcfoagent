"""
reactivation_export.py
----------------------
The reactivation PRODUCT (Phase 4, export-first per Rydel): a CSV (full fields for GHL smart-list
work) and a formatted REACTIVATION BRIEF PDF (ranked top-N leads with the grounded "where it left
off" + suggested angle) — the artifact Kalin's team works from top to bottom.

These outputs contain contact PII (name/email/phone) BY DESIGN — the team needs it to reach the
lead. Generation is a deliberate, auth-gated, audit-logged action (never auto, never in memory/logs).
"""
from __future__ import annotations

import csv
import io
import logging

import reactivation
import ghl_mirror
from helpers import today_sydney

logger = logging.getLogger(__name__)

_CSV_FIELDS = ["rank", "name", "business", "email", "phone", "stage", "bucket", "value",
               "days_stale", "days_since_touch", "warmth", "notes_count", "tracker_match",
               "tracker_status", "where_it_left_off", "reactivation_angle"]


def _contact_fields(lead: dict) -> dict:
    c = ghl_mirror.read_contact(lead.get("contact_id")) if lead.get("contact_id") else None
    if not c:
        return {"name": lead.get("name"), "email": "", "phone": ""}
    nm = " ".join(x for x in [c.get("first_name"), c.get("last_name")] if x) or lead.get("name")
    return {"name": nm, "email": c.get("email") or "", "phone": c.get("phone") or ""}


def build_rows(leads: list[dict], with_summaries: bool = True, cap: int | None = None) -> list[dict]:
    """Enrich ranked leads with contact fields + grounded summaries (cached)."""
    leads = leads[:cap] if cap else leads
    summed = {}
    if with_summaries:
        try:
            import ghl_notes_summary
            for s in ghl_notes_summary.summarize_batch(leads, cap=cap or len(leads)):
                summed[s["opp_id"]] = s.get("summary", {})
        except Exception as e:
            logger.info("brief summaries unavailable: %s", e)
    rows = []
    for i, l in enumerate(leads, 1):
        cf = _contact_fields(l)
        s = summed.get(l["opp_id"], {})
        tr = l.get("tracker")
        rows.append({
            "rank": i, "name": cf["name"], "business": (tr or {}).get("business", ""),
            "email": cf["email"], "phone": cf["phone"], "stage": l.get("stage"),
            "bucket": l.get("bucket"), "value": l.get("value"), "days_stale": l.get("age_days"),
            "days_since_touch": l.get("days_since_touch"), "warmth": l.get("warmth"),
            "notes_count": l.get("notes_count"),
            "tracker_match": (tr or {}).get("match", ""), "tracker_status": (tr or {}).get("outcome", ""),
            "where_it_left_off": (s.get("where_it_left_off") or "").replace("\n", " "),
            "reactivation_angle": (s.get("reactivation_angle") or "").replace("\n", " "),
        })
    return rows


def build_csv(leads: list[dict], cap: int | None = None) -> str:
    rows = build_rows(leads, with_summaries=True, cap=cap)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def build_brief_pdf(leads: list[dict], top_n: int = 40) -> bytes:
    """Branded reactivation brief — ranked top-N with grounded summaries + angles. fpdf2."""
    from fpdf import FPDF
    from dashboard.briefing_pdf import _safe, _fmt, NAVY, PRIMARY, TINT, MUTED, WHITE, DARK, GREEN, AMBER, LIGHT_GREY

    rows = build_rows(leads, with_summaries=True, cap=top_n)
    totals = reactivation.summary_totals()
    hygiene = reactivation.notes_hygiene()

    pdf = FPDF("P", "mm", "A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    # header band
    pdf.set_fill_color(*NAVY); pdf.rect(0, 0, pdf.w, 34, style="F")
    pdf.set_xy(12, 9); pdf.set_font("Helvetica", "B", 18); pdf.set_text_color(*WHITE)
    pdf.cell(0, 9, "Lead Reactivation Brief", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(12); pdf.set_font("Helvetica", "", 10); pdf.set_text_color(*TINT)
    pdf.cell(0, 6, _safe(f"Served Marketing  ·  generated {today_sydney()}  ·  top {min(top_n, len(rows))} of "
                         f"{totals['reactivation_pool']} reactivation leads (${totals['reactivation_value']:,.0f} pipeline)"))
    pdf.set_y(40)
    pdf.set_font("Helvetica", "I", 9); pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.5, _safe(
        "Ranked by warmth (stage reached x value x recency). Every 'where it left off' is written "
        "strictly from the lead's real CRM notes; leads with none are marked 'no notes logged'. "
        + hygiene["finding"]))
    pdf.ln(2)

    for r in rows:
        if pdf.get_y() > 250:
            pdf.add_page()
        # card
        y0 = pdf.get_y()
        pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*NAVY)
        title = f"{r['rank']}. {r['name']}" + (f"  ·  {r['business']}" if r['business'] else "")
        pdf.cell(0, 6, _safe(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(*DARK)
        meta = (f"{r['stage']}  |  {_fmt(r['value'])}  |  {r['bucket']}  |  "
                f"{r['days_stale']}d old, {r['days_since_touch']}d since touch  |  warmth {r['warmth']}  |  "
                f"{r['notes_count']} note(s)")
        pdf.cell(0, 5, _safe(meta), new_x="LMARGIN", new_y="NEXT")
        contact = "  ".join(x for x in [r["email"], r["phone"]] if x)
        if contact:
            pdf.set_text_color(*MUTED); pdf.cell(0, 4.5, _safe(contact), new_x="LMARGIN", new_y="NEXT")
        # where it left off + angle
        pdf.set_text_color(*DARK); pdf.set_font("Helvetica", "", 8.5)
        wlo = r["where_it_left_off"] or "(summary unavailable)"
        pdf.multi_cell(0, 4.4, _safe("Where it left off: " + wlo))
        if r["reactivation_angle"]:
            pdf.set_font("Helvetica", "B", 8.5); pdf.set_text_color(*PRIMARY)
            pdf.multi_cell(0, 4.4, _safe("Angle: " + r["reactivation_angle"]))
        if r["tracker_match"]:
            pdf.set_font("Helvetica", "I", 7.5); pdf.set_text_color(*MUTED)
            pdf.cell(0, 4, _safe(f"(tracker match by {r['tracker_match']}"
                                 + (f" — {r['tracker_status']}" if r['tracker_status'] else "") + ")"),
                     new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*LIGHT_GREY); pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
        pdf.ln(3)

    return bytes(pdf.output())
