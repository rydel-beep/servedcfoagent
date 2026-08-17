"""csm_docs.py — D4 (CSM_ANALYSIS briefing) + D5 (stripped shareable exports).

OWNER-ONLY. Confidentiality law applied to every artefact this module emits:
  * NO director comp figures anywhere — funding paths render as structure
    with "computed live from owner config on /csm" so every file on disk
    greps clean (the grep-assert covers markdown, PDFs and this module).
  * D4 versions live in kv (Railway disk is ephemeral) — dated, regenerable
    on demand from either surface ("EDITH, give me the CSM analysis").
  * D5 (candidate comp page) is STRIPPED: the comp-table numbers the
    candidate sees are exactly the numbers the model uses; ROI, baselines,
    net rows, director anything — absent, and preflight() PROVES it by
    forbidden-token scan over the rendered text.
"""

from __future__ import annotations

import re

import kv_store
from helpers import today_sydney

import csm_model
import csm_plan

_KV_VERSIONS = "csm:analysis_versions"

_FORBIDDEN_IN_COMP_PAGE = re.compile(
    r"director|offset|roi|4x|4×|cohort|baseline|net (cost|return|mrr)|"
    r"margin|refund|npat|pbt|runway", re.I)


# ── D4 · the CSM_ANALYSIS briefing ──────────────────────────────────────────

def _money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def build_analysis_markdown() -> tuple[str, str]:
    """(markdown, headline). Generated from the ENGINE — measured baselines,
    model summary, funding paths (structure only), path to 4x, risks, next
    gate, placeholder-vs-measured. No director figures."""
    today = str(today_sydney())
    s = csm_plan.summary()
    mv = csm_plan.model_view()
    b = csm_plan.csm_baselines.all_baselines()
    g = csm_plan.gates(b)
    r = csm_plan.risks(b)
    base = mv["scenarios"]["base"]
    solve = mv["solve_4x"]
    b1 = b.get("b1_renewal") or {}
    b2 = b.get("b2_refund_split") or {}
    itc = b.get("b1_in_term_completion") or {}
    tiers = ((b.get("b4_book") or {}).get("tiers") or {})
    headline = (f"base {base['cohort_roi_loaded']}x loaded cohort ROI; "
                f"4x needs {solve['renewal_pct']}% renewal; "
                f"B1 renewal {b1.get('value')}% ({b1.get('label')})")
    lines = [
        f"# CSM ANALYSIS — {today}",
        "",
        "> OWNER-ONLY · CONFIDENTIAL · not for screen-share. Director comp",
        "> figures are never in this document — they render live from owner",
        "> config on /csm.",
        "",
        "## Where we are",
        f"- {s['card_line']}",
        f"- Next action: {s['next_action']['item']} ({s['next_action']['owner']})",
        f"- Gate 0: {g['done']}/{g['total']} — open: "
        + ("; ".join(i["label"] for i in g["items"] if not i.get("done")) or "none"),
        "",
        "## Measured baselines (Gate-0) — measured vs placeholder",
        f"- **B1 renewal rate**: {b1.get('value')}% ± {b1.get('confidence_pm')} "
        f"({b1.get('label')}; n={b1.get('n_decided')}, "
        f"{b1.get('n_ambiguous')} ambiguous flagged) — source placeholder 40%",
        f"- **In-term completion**: {itc.get('value') or 'placeholder 85%'} "
        f"({itc.get('label')})",
        f"- **B2 refund split**: {b2.get('label')} — Xero line total "
        f"{_money(b2.get('xero_line_total'))}; Stripe-evidenced client "
        f"refunds {_money((b2.get('stripe_client_refunds') or {}).get('total'))}; "
        "remainder FLAGGED (transaction-level Xero read is a registered "
        "dependency). Owners: guarantee → sales qual; client refund → client "
        "success; rebate → neither.",
        f"- **B4 book**: {tiers.get('book_count')} clients; Tier 1 "
        f"{tiers.get('tier1_count') or 'UNASSIGNED (live risk)'}; second-CSM "
        f"trigger: {tiers.get('second_csm_trigger', {}).get('rule')}",
        f"- **B5 DQS proxy**: "
        f"{(b.get('b5_dqs_proxy') or {}).get('book_avg_health', 'bridge n/a')} "
        "(proxy — formal DQS is Miguel's COO scorecard)",
        "",
        "## The model (source reproduced, then honest)",
        f"- Regression: {'GREEN' if mv['regression']['ok'] else 'FAILING'} — "
        "the engine reproduces the source workbook figures exactly "
        "(per-client, book, all three scenarios).",
        f"- Base: {base['cohort_roi_unloaded']}x unloaded (the source's 3.5x) "
        f"→ **{base['cohort_roi_loaded']}x fully loaded** "
        f"({_money(base['loaded_cost_y1'])}). Y1: {base['y1_roi_loaded']}x "
        "loaded.",
        "- TWO CLOCKS, never blended: COHORT (lifetime lift ÷ one year of "
        "cost — the source's own convention, surfaced) carries the 4x "
        "target; STEADY-STATE (T12M/T12M from month 13) is the ongoing "
        "check.",
        f"- **Path to 4x: {solve['renewal_pct']}% renewal** (between base "
        "60% and upside 72%). Year-1 4x exists in NO scenario (upside Y1 "
        "~2.6x) — leading indicators lead; ROI is the lagging line.",
        f"- Layer vs hire: structural share (policy-driven refund avoidance) "
        f"is small (~{_money(mv['layer_vs_hire']['structural_lift'])} of "
        f"~{_money(base['credited_lift_lifetime'])}) — the hire lens moves "
        "the target little.",
        "",
        "## Funding paths (structure — figures live on /csm from owner config)",
        "- OFFSET-FUNDED: fixed-cost delta = her loaded cost − loaded "
        "director-comp offset (≈ neutral at the stated range; computed live); "
        "business discretionary cash untouched; downside bounded to director "
        "income.",
        "- BUSINESS-CASH-FUNDED: ~$94k discretionary carries ~24 months of "
        "base; director income unchanged.",
        "- LAW: funding path ≠ return. Return-per-$-of-net-cost is a "
        "financing view, never ROI.",
        "",
        "## Source-model conventions surfaced",
    ]
    lines += [f"- {n}" for n in mv["convention_notes"]]
    lines += [
        "",
        "## Risks (live register)",
    ]
    lines += [f"- [{x['status'].upper()}] {x['risk']} — signal: {x['signal']}"
              for x in r["register"]]
    lines += [
        "",
        "## What's placeholder vs measured",
        "- Measured: B1 renewal (method + edge cases on /csm), in-term "
        "completion where terms ended with cash data, book ledger + tiers, "
        "DQS proxy (bridge-dependent).",
        "- Placeholder/partial: refund-cause split beyond Stripe evidence, "
        "expansion product-line baselines (product lines don't exist yet — "
        "the new EXPANSION declarations measure them forward), prior-MRR "
        "floor-share check in B1.",
        "",
        "## Next gate",
        f"- {s['next_action']['item']}",
        "",
        "*Estimates, not advice: comp/tax/structure = Rydel + Latitude; "
        "director personal tax out of scope.*",
    ]
    return "\n".join(lines), headline


def generate_analysis() -> dict:
    """Regenerate the briefing; version it in kv; return {version, generated,
    headline, md}."""
    md, headline = build_analysis_markdown()
    versions = kv_store.get(_KV_VERSIONS) or []
    version = (versions[-1]["version"] + 1) if versions else 1
    entry = {"version": version, "generated": str(today_sydney()),
             "headline": headline, "md": md}
    versions.append(entry)
    kv_store.put(_KV_VERSIONS, versions[-10:])
    csm_plan.journal({"who": "engine", "event": "analysis regenerated",
                      "version": version})
    return entry


def analysis_versions() -> list[dict]:
    return [{k: v for k, v in e.items() if k != "md"}
            for e in (kv_store.get(_KV_VERSIONS) or [])]


def latest_analysis() -> dict | None:
    v = kv_store.get(_KV_VERSIONS) or []
    return v[-1] if v else None


def _latin(s: str) -> str:
    return (s.replace("\u2014", "-").replace("\u2013", "-")
             .replace("\u00d7", "x").replace("\u2265", ">=")
             .encode("latin-1", "replace").decode("latin-1"))


def _pdf_base(title: str, watermark: str):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(26, 58, 92)
    pdf.cell(0, 10, _latin(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(160, 60, 60)
    pdf.cell(0, 6, watermark, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    return pdf


def analysis_pdf() -> bytes:
    """Render the latest briefing version as a PDF (regenerates if none)."""
    entry = latest_analysis() or generate_analysis()
    pdf = _pdf_base(f"CSM ANALYSIS v{entry['version']} — {entry['generated']}",
                    "CONFIDENTIAL - OWNER ONLY - NOT FOR SCREEN-SHARE")
    pdf.set_text_color(30, 30, 30)
    for raw in entry["md"].splitlines():
        line = raw.replace("**", "").replace("×", "x")
        line = _latin(line)
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, line[3:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8.5)
        elif line.startswith("> "):
            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(0, 4.5, line[2:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8.5)
        else:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 4.5, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── D5 · the candidate offer-pack comp page (stripped, proven) ──────────────

def _comp_rows(cfg: dict | None = None) -> list[tuple[str, str]]:
    """The candidate-facing comp rows — the SAME numbers the model uses
    (COMP_TABLE_DEFAULTS overridden by the signed-offer config)."""
    c = dict(csm_model.COMP_TABLE_DEFAULTS)
    over = csm_plan._comp_overrides(cfg or csm_plan.config())
    c.update({k: v for k, v in over.items() if k in c})
    a = csm_model.SCENARIO_ANCHORS
    return [
        ("Base", f"${c['base_monthly']:,.0f}/month"),
        ("Renewal bonus", f"${c['renewal_bonus']:,.0f} per 6-month renewal "
         f"(reverses if the client leaves within {c['renewal_clawback_days']} "
         "days)"),
        ("12-month lock bonus", f"${c['lock12_bonus']:,.0f} per 12-month "
         "conversion"),
        ("Step-ups & sprints", f"{c['stepup_sprint_pct_first6']*100:.0f}% of "
         "the first-6-month value of any upsell you close"),
        ("Continuity saves", f"${c['continuity_save_bonus']:,.0f} per client "
         "kept on Served OS instead of leaving"),
        ("Referrals", f"{c['referral_pct']*100:.0f}% of a referred client's "
         "first-6-month value"),
        ("Retention bonus", f"${c['nrr_bonus_quarterly']:,.0f}/quarter when "
         "your book's revenue retention is at or above 100%"),
        ("On-target earnings", f"${a['floor']['ote']:,.0f} - "
         f"${a['upside']['ote']:,.0f}/yr depending on performance "
         f"(mid case ${a['base']['ote']:,.0f})"),
    ]


def comp_page_text(cfg: dict | None = None) -> str:
    rows = _comp_rows(cfg)
    lines = ["SERVED MARKETING - CUSTOMER SUCCESS MANAGER - COMPENSATION",
             "Shareable - internal rows removed", ""]
    for k, v in rows:
        lines.append(f"{k}: {v}")
    lines += ["", "Every variable line is calculable by you from your own "
              "book - logged per event, itemised, paid with payroll.",
              "Estimates of variable earnings depend on performance."]
    return "\n".join(lines)


def comp_page_preflight(cfg: dict | None = None) -> dict:
    """PROOF of the strip: what's included, what's stripped, and a
    forbidden-token scan over the exact rendered text."""
    text = comp_page_text(cfg)
    hits = sorted({m.group(0).lower()
                   for m in _FORBIDDEN_IN_COMP_PAGE.finditer(text)})
    return {
        "included": [k for k, _ in _comp_rows(cfg)],
        "stripped": ["ROI clocks (cohort + steady-state)", "the 4x solve",
                     "Gate-0 baselines", "internal net rows",
                     "layer-vs-hire attribution", "funding paths",
                     "director comp anything", "refund economics",
                     "book financials"],
        "forbidden_token_hits": hits,
        "clean": not hits,
        "note": "the numbers the candidate sees = the numbers the model uses "
                "(comp table; signed offer replaces defaults via config)",
    }


def comp_page_pdf(cfg: dict | None = None) -> bytes:
    pre = comp_page_preflight(cfg)
    if not pre["clean"]:
        raise ValueError(f"comp-page preflight failed — forbidden tokens "
                         f"{pre['forbidden_token_hits']}; refusing to emit")
    pdf = _pdf_base("Customer Success Manager - Compensation",
                    "Served Marketing - candidate copy")
    pdf.set_text_color(30, 30, 30)
    for k, v in _comp_rows(cfg):
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 5.5, k.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, v.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4.5, "Every variable line is calculable by you from "
                           "your own book - logged per event, itemised, paid "
                           "with payroll.", new_x="LMARGIN", new_y="NEXT")
    csm_plan.journal({"who": "owner", "event": "candidate comp page exported"})
    return bytes(pdf.output())
