# QUARTERLY REVIEW PDF — report

**Date:** 2026-07-21 (Sydney). One owner-visible button that generates a branded Quarterly
Financial Review PDF from the same deterministic engines that power the dashboard: how the quarter
went, how it compares (QoQ + honest YoY), and a constraint-first model of what would need to be true
to 3x overall growth next quarter. Every generated PDF is dated into the forever archive.

Acceptance authority = the rendered PDF (screenshotted for Rydel) + live consistency proof, not test
counts.

---

## Phase 0 — conventions chosen (Rydel's gate, 2026-07-21)
- **Quarter convention: CALENDAR** (Q1 Jan–Mar … Q4 Oct–Dec). Default review = last completed
  calendar quarter (Q2 2026 = Apr–Jun). *(For this period AU-FY and calendar resolve to identical
  windows anyway; only the label differs.)*
- **3x metric: EVERYTHING** — 3x cash collected AND contracted revenue AND new MRR together, i.e. 3x
  overall QoQ company growth, not one lever. The 3x section models all three targets and reports
  every lever's requirement, ending in the binding constraint.
- **Access: Rydel + Piolo both** (full-visibility mandate) → gated `require_auth`, not
  `require_owner`. Every generation is flagged to Rydel via `collab.record_action` (Piolo's lands as
  `kind=action` and surfaces in the owner digest).
- **PDF engine: fpdf2** (already deployed, pure-Python, no cairo/pango) — reuses the branded
  `BriefingPDF` class. No Railway change, no weasyprint risk.

## The pack (Phase 1) — one window, one engine
`quarterly_pack.quarter_pack(year, q)` assembles a window-consistent pack from the canonical engines
so a PDF number always equals the dashboard number for the same window:
- **Unit economics** verbatim from `range_unit_economics.unit_economics(start,end)` — the same engine
  the dashboard window buttons and EDITH's answers use.
- **Revenue & cash**: contracted (closes × value) and new-deal cash from the engine; **Xero P&L
  revenue** via a new `xero_pull.pull_pl_range(start,end)` (Xero keeps full GL history — verified
  live back to 2025). Stripe-cash and Xero-revenue are labelled and never summed.
- **MRR bridge**: closing (live roster) + new MRR (in-window closes matched to roster) + churn
  (forward-MRR engine); legs that aren't snapshotted historically are stated, not faked.
- **Sales**: cohort funnel + by-month velocity. **Costs**: ad spend (source-labelled), commissions,
  loaded CAC, current burn context. **Churn & events**: roster + the append-only journal timeline.
- Prior packs (previous quarter; same quarter prior year) computed the same way.

## Comparisons (Phase 2) — honest by construction
- **QoQ (Q2 2026 vs Q1 2026): 12/12 fields comparable** — like-for-like.
- **YoY (Q2 2026 vs Q2 2025): only the deep-history sources compared** (Xero revenue/net-profit, Meta
  ad spend). The tracker was **nascent** in Q2 2025 (0–1 closes), so every tracker-dependent field
  (closes, contracted, cash, CAC, LTGP:CAC, ROAS, leads, close-rate) is marked **"not computable"**
  rather than showing a fabricated "$0 → $253,200" delta. This is the exact honesty line promised at
  the Phase 0 gate. The suppression fires when the prior quarter has < 3 closes (the engine's own
  "small sample" volatility threshold).

## The 3x model (Phase 3) — constraint-first
`three_x_model.build_3x(pack)` walks the machine backwards from the quarter's actuals × 3:
- **Targets**: contracted $253,200 → $759,600; new-deal cash $98,255 → $294,765; 16 → 48 closes.
- **Funnel** — both paths: **volume** (same 6% close rate, ~3× the leads/sets/shows) and
  **efficiency** (same leads, close rate → the required %). 
- **Spend**: leads at held CPL → required ad spend; CAC held constant (stated assumption, not a
  claim); checks LTGP:CAC stays above the 3.0 floor at scale.
- **Capacity**: 3× clients → hires needed (lead-time-aware) and the 40% payroll:MRR gate.
- **Churn**: the churn level at which 3× gross erodes to 2× net.
- **Fundability-aware flags + binding constraint**: fundable levers (leads, spend) flag *plausible*
  because unit economics stay above the floor at scale; the **binding constraint** is the operational
  wall — for Q2 2026 that's **Delivery hires**. Assumptions are listed and adjustable
  (`?multiple=`, `?close_rate_target=` …; "what if close rate hits 55%?" recomputes via the same
  engine). Framed explicitly as **"a model of what must be true, not a forecast."**

## The PDF, button, archive (Phase 4)
- **Branded fpdf2 PDF**: cover → exec summary (KPI tiles + binding-constraint callout) → the quarter
  (revenue/cash/unit-econ tables, MRR bridge, monthly velocity bar charts) → comparisons (QoQ + YoY)
  → the 3x model (targets, both paths, spend/capacity/churn, requirements table with flag colours,
  binding-constraint verdict).
- **Button**: header "Generate Quarterly Review" (both roles) → downloads the PDF; the file is dated
  into `dashboard/archive_exports/` and a record is written to the forever archive; the generation is
  flagged to Rydel.
- **Chat/voice**: "generate the quarterly review" builds + archives + returns the link; "how did Q2
  compare to last year?" / "what would need to be true to 3x next quarter?" answer from the packs in
  text (verbatim numbers, YoY-honest). Intent-gated so unit-econ/cash queries are untouched.

## Verbatim-number guarantee
`validate_verbatim()` scans every composed money-bearing string in the PDF; each `$`-figure must
trace to a number already present in the pack (allowing display rounding). **Generation fails loudly**
otherwise. The narrative is composed deterministically from pack figures — the model never
introduces, round-drifts, or extrapolates a number.

## Live verification (all green)
- **Consistency (same-moment):** every pack figure equals the dashboard `/api/unit-economics` value
  for the identical window — LTGP:CAC 4.74, CAC $2,718.13, closes 16, contracted $253,200, cash
  $98,255, ad spend $24,382.88 — all exact. The PDF can't disagree with the dashboard.
- **Verbatim guard:** clean text passes; an injected `$9,999,999` is caught and generation refuses
  (adversarial test PASS). *(It also caught a real bug — a truncated engine breakdown string — during
  the build; fixed by composing CAC detail from numeric fields.)*
- **YoY honesty:** Q2 2025 sales/unit-econ correctly reads "not computable"; only Xero + Meta compare.
- **MRR bridge** legs reconcile / are labelled where a leg isn't historically snapshotted.
- **Button, both roles:** Rydel → 200 + valid PDF; Piolo → 200 + valid PDF; both archived and flagged
  to Rydel (Piolo's as `kind=action`).
- **Chat:** all three phrasings answered correctly, YoY-honest, with the binding constraint.

## Non-regression
Additive only — new modules (`quarterly_pack`, `quarterly_compare`, `three_x_model`,
`quarterly_review`, `dashboard/quarterly_pdf`) + a range function in `xero_pull` + new routes/button.
No existing engine, cash-truth, matching, collaboration, archive, sheet-mirror, or responsive code
was modified. `today_sydney()` throughout; Xero/Stripe read-only.
