"""
quarterly_review.py
-------------------
Orchestrator: assemble a full quarterly review (current pack + prior-quarter pack + same-quarter-
prior-year pack + QoQ/YoY comparisons + the 3x model) for one quarter. Shared by the JSON endpoint
(chat answers, "how did Q1 compare to last year?") and the PDF generator — so both read identical
numbers. Pure assembly over the deterministic engines; no fabrication.
"""
from __future__ import annotations

import logging

import quarterly_pack as qp
import quarterly_compare as qc
import three_x_model

logger = logging.getLogger(__name__)


def build_review(year: int, q: int, assumptions: dict | None = None) -> dict:
    """The complete review object for calendar quarter q of `year`."""
    current = qp.quarter_pack(year, q)

    py, pq = qp.prev_quarter(year, q)
    try:
        prior_q = qp.quarter_pack(py, pq)
    except Exception as e:
        logger.info("prior-quarter pack failed: %s", e)
        prior_q = None

    # same quarter, previous year (YoY)
    try:
        prior_y = qp.quarter_pack(year - 1, q)
    except Exception as e:
        logger.info("prior-year pack failed: %s", e)
        prior_y = None

    qoq = qc.compare(current, prior_q, "QoQ")
    yoy = qc.compare(current, prior_y, "YoY")

    threex = three_x_model.build_3x(current, assumptions)

    # Marketing roadmap (G5) — the scaling plan built on the 3x model.
    review_partial = {"current": current, "three_x": threex}
    try:
        import quarterly_roadmap
        roadmap = quarterly_roadmap.build_roadmap(review_partial, assumptions)
    except Exception as e:
        logger.info("roadmap build failed: %s", e)
        roadmap = {"available": False, "reason": str(e)}

    # Self-improvement loop: grade the PRIOR quarter's saved model against this quarter's actuals,
    # and persist THIS quarter's model for next quarter to grade.
    grading = None
    try:
        import quarterly_model_store
        grading = quarterly_model_store.grade_prior_quarter(qp.quarter_label(py, pq), current)
        quarterly_model_store.save_model(qp.quarter_label(year, q), threex,
                                         actuals={"leads": (current.get("sales") or {}).get("funnel", {}).get("leads_in"),
                                                  "closes": (current.get("unit_economics") or {}).get("components", {}).get("closes"),
                                                  "ad_spend": (current.get("unit_economics") or {}).get("components", {}).get("ad_spend")})
    except Exception as e:
        logger.info("model grading/persist failed: %s", e)

    return {
        "quarter": {"year": year, "q": q, "label": qp.quarter_label(year, q)},
        "current": current,
        "prior_quarter": prior_q,
        "prior_year": prior_y,
        "comparisons": {"qoq": qoq, "yoy": yoy},
        "three_x": threex,
        "roadmap": roadmap,
        "model_grading": grading,
        "generated_at": current.get("generated_at"),
        "convention": "calendar",
    }


def default_review(assumptions: dict | None = None) -> dict:
    """The last completed calendar quarter — the default the button generates."""
    y, q = qp.last_completed_quarter()
    return build_review(y, q, assumptions)


# ── Voice / chat ─────────────────────────────────────────────────────────────

import re as _re

# Intent-gated: fire only on an actual quarterly-review request, never on a bare quarter mention
# inside another query (e.g. "LTGP:CAC in Q2 2026" belongs to the unit-econ handler).
_TRIGGER = _re.compile(
    r"\bquarterly\b"
    r"|\bhow did (the )?q[1-4]\b"
    r"|\bquarter(?:ly)?\s+(review|report|summary|compare|comparison|numbers|pack|breakdown)\b"
    r"|\b(compare|comparison|vs\.?)\b[^?]*\bquarter\b"
    r"|\b3x (the|our|next|overall)\b"
    r"|\bwhat would (it|need|have) .{0,40}3x\b", _re.I)
_GENERATE = _re.compile(r"\b(generate|create|make|build|produce|download|export|send)\b.*\b(quarter|review|pdf)\b"
                        r"|\bquarterly (review|report) pdf\b", _re.I)
_YOY = _re.compile(r"\b(last year|a year ago|year[- ]on[- ]year|yoy|prior (financial )?year|vs .*20\d\d)\b", _re.I)
_QREF = _re.compile(r"\bq([1-4])\b(?:\s*(20\d\d))?", _re.I)


def _target_quarter(text: str) -> tuple[int, int]:
    """Resolve which quarter the user means: explicit 'Q3 2025', 'this quarter', 'last quarter',
    else the last completed quarter."""
    t = (text or "").lower()
    m = _QREF.search(t)
    if m:
        q = int(m.group(1))
        y = int(m.group(2)) if m.group(2) else qp.current_quarter()[0]
        return y, q
    if "this quarter" in t:
        return qp.current_quarter()
    if "last quarter" in t or "previous quarter" in t:
        return qp.last_completed_quarter()
    return qp.last_completed_quarter()


def _fmt_money(v) -> str:
    if v is None:
        return "n/a"
    return f"${abs(v):,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def handle_quarterly_command(text: str, actor: dict | None = None) -> tuple[str | None, bool]:
    """Chat entry point. 'generate the quarterly review' -> build + archive the PDF and return the
    download link (flagged to Rydel). Otherwise answer the quarter/comparison/3x question from the
    packs in text, WITHOUT generating a PDF. Numbers are verbatim from the engines."""
    if not text or not _TRIGGER.search(text):
        return None, False
    year, q = _target_quarter(text)

    # generation request → build, validate+archive via the same path the button uses
    if _GENERATE.search(text):
        try:
            review = build_review(year, q)
            from dashboard.quarterly_pdf import generate_quarterly_pdf
            pdf = generate_quarterly_pdf(review)  # validates verbatim; raises on fabrication
        except Exception as e:
            return (f"I couldn't generate the {qp.quarter_label(year, q)} review: {e}. "
                    "The figures must all trace to the engines — I won't emit a document otherwise."), True
        label = qp.quarter_label(year, q)
        # archive + flag (best-effort; the download link is the deliverable)
        try:
            import collab, os
            from helpers import today_sydney
            fn = f"served-cfo-quarterly-{label.replace(' ', '-')}-{today_sydney()}.pdf"
            adir = os.path.join(os.path.dirname(__file__), "dashboard", "archive_exports")
            os.makedirs(adir, exist_ok=True)
            with open(os.path.join(adir, fn), "wb") as fh:
                fh.write(pdf)
            who = (actor or {}).get("user", "rydel")
            collab.add_entry(who, "done", f"Quarterly Review generated: {label} ({fn})",
                             link_type="quarterly_pdf", link_ref=label)
            collab.record_action(actor or {"user": who}, f"generated the Quarterly Review PDF for {label}",
                                 link_type="quarterly_pdf", link_ref=label)
        except Exception:
            pass
        return (f"{label} Quarterly Review is generated and archived ({len(pdf):,} bytes). "
                f"Download it from the header button, or open /dashboard/api/quarterly-review"
                f"?year={year}&q={q}."), True

    # otherwise: answer from the packs in text
    try:
        review = build_review(year, q)
    except Exception as e:
        return f"I couldn't assemble the {qp.quarter_label(year, q)} pack: {e}.", True
    cur = review["current"]; rc = cur["revenue_cash"]; ue = cur.get("unit_economics", {})
    comp = ue.get("components", {}) if isinstance(ue, dict) else {}
    label = review["quarter"]["label"]
    parts = [f"{label}: {comp.get('closes','?')} closes, {_fmt_money(rc.get('contracted_revenue'))} "
             f"contracted, {_fmt_money(rc.get('new_deal_cash_collected'))} new-deal cash, "
             f"LTGP:CAC {ue.get('ltgp_cac','?')}x on CAC {_fmt_money(comp.get('cac_loaded'))}."]

    if _YOY.search(text):
        yoy = review["comparisons"]["yoy"]
        if yoy.get("prior_pre_tracker"):
            xr = rc.get("xero_revenue", {})
            py = review.get("prior_year", {}) or {}
            pxr = (py.get("revenue_cash", {}) or {}).get("xero_revenue", {}) if py else {}
            parts.append(f"Year-on-year, the sales/unit-economics can't be compared honestly — the "
                         f"tracker was nascent in {yoy.get('prior_label')} (too few closes to be a "
                         f"real basis). On the deep-history sources: Xero revenue "
                         f"{_fmt_money(xr.get('revenue'))} vs {_fmt_money(pxr.get('revenue'))}, and "
                         f"Meta ad spend {_fmt_money(comp.get('ad_spend'))} vs "
                         f"{_fmt_money(((py.get('unit_economics',{}) or {}).get('components',{}) or {}).get('ad_spend'))}.")
        else:
            parts.append(_compare_line(yoy))
    else:
        parts.append(_compare_line(review["comparisons"]["qoq"]))

    binding = review["three_x"].get("binding_constraint", {})
    if binding.get("lever"):
        parts.append(f"To 3x overall growth next quarter, the binding constraint is "
                     f"{binding['lever']} ({binding.get('flag')}) — the fundable levers hold, the "
                     f"wall is operational. Say 'generate the quarterly review' for the full PDF.")
    return " ".join(parts), True


def _compare_line(cmp: dict) -> str:
    if not cmp or not cmp.get("available"):
        return (cmp or {}).get("note", "No comparable prior period.")
    picks = []
    for r in cmp.get("rows", []):
        if r.get("available") and r.get("pct") is not None and r["metric"] in (
                "Contracted revenue", "New-deal cash collected", "Closes", "Xero revenue (P&L)"):
            picks.append(f"{r['metric']} {r['pct']:+.0f}%")
    head = f"Vs {cmp.get('prior_label')}: " + ("; ".join(picks) if picks else "see the report")
    return head + "."
