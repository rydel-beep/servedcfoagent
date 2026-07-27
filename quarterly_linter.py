"""
quarterly_linter.py
-------------------
The REPORT LINTER — a post-generation gate that runs AFTER the pack renders and BEFORE the PDF
finalises. The verbatim validator proved the numbers are REAL; the linter proves they make SENSE.
Each audited defect (D1-D5) is a regression rule; reintroducing any defect trips the linter.

- UNIT CONSISTENCY (D1): a ratio metric never renders with '$'; no '$Nx' hybrids.
- COMPLETENESS (D2): the 3x targets carry current AND target values (no blank cells).
- CONTRADICTIONS (D3): a lever's flag is identical everywhere it appears (one flag engine).
- BOUNDS / DEGENERACY (D4): sanity ranges — 3x target > current, rates 0-100, CAC>0, ratios sane,
  churn < total MRR; a violation must render "not computable", never a degenerate number.
- LANGUAGE (D5): no sentence fragments / orphaned subjects / dangling template tokens.

Hard-fail (raises LintError) for the data classes D1-D4. Language (D5) is flag-and-log (warnings).
Findings are returned for the generation log + the self-improvement linter-trend.
"""
from __future__ import annotations

import re

from quarterly_format import type_of

RATIO_METRICS = ("LTGP:CAC", "LTV:CAC", "ROAS")


class LintError(Exception):
    pass


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("$", "").replace("x", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def lint(audit_lines: list[str], review: dict) -> dict:
    """Run all rules. Returns {ok, hard_failures[], warnings[], summary}. Raises LintError if any
    hard (data) rule fails."""
    hard: list[str] = []
    warn: list[str] = []
    text = "\n".join(audit_lines or [])
    tx = (review or {}).get("three_x", {}) or {}

    # ── D1: unit consistency ──
    for line in audit_lines or []:
        for rm in RATIO_METRICS:
            if line.startswith(rm) or f" {rm} " in f" {line} ":
                # the ratio metric's value on this line must not be a dollar figure
                if re.search(r"\$\s?\d", line):
                    hard.append(f"D1 unit: ratio metric '{rm}' rendered with '$' → {line[:80]!r}")
    if re.search(r"\$\s?[\d,]+(?:\.\d+)?x", text):
        hard.append("D1 unit: found a '$Nx' currency/ratio hybrid token")

    # ── D2: completeness (3x targets carry both current and target) ──
    tc = tx.get("targets_current") or {}
    tt = tx.get("targets") or {}
    if tt:  # only when a 3x model exists
        for k in ("contracted_revenue", "new_deal_cash_collected", "closes"):
            if tt.get(k) is not None and tc.get(k) is None:
                hard.append(f"D2 completeness: target '{k}' present but current value missing (blank cell)")

    # ── D3: contradiction (volume-path flag == lead-volume lever flag) ──
    vpf = ((tx.get("funnel") or {}).get("volume_path") or {}).get("flag")
    lever_flags = {lv.get("lever"): lv.get("flag") for lv in tx.get("requirements_table", [])}
    lvf = lever_flags.get("Lead volume (volume path)")
    if vpf is not None and lvf is not None and vpf != lvf:
        hard.append(f"D3 contradiction: volume-path flag '{vpf}' != lever flag '{lvf}' (two flag engines)")

    # ── D4: bounds / degeneracy ──
    for k in ("contracted_revenue", "new_deal_cash_collected", "closes"):
        c, t = tc.get(k), tt.get(k)
        if c is not None and t is not None and t < c:
            hard.append(f"D4 bounds: 3x target for '{k}' ({t}) is smaller than current ({c})")
    ue = (review.get("current") or {}).get("unit_economics") or {}
    comp = ue.get("components", {}) if isinstance(ue, dict) else {}
    for label, v in (("LTGP:CAC", ue.get("ltgp_cac")), ("ROAS", ue.get("roas"))):
        if isinstance(v, (int, float)) and not (0 < v < 100):
            hard.append(f"D4 bounds: {label} out of sane range: {v}")
    cac = comp.get("cac_loaded")
    if isinstance(cac, (int, float)) and cac <= 0:
        hard.append(f"D4 bounds: loaded CAC not positive: {cac}")
    churn = tx.get("churn") or {}
    base = churn.get("current_closing_mrr")
    cm = churn.get("current_churn_mrr")
    if isinstance(cm, (int, float)) and isinstance(base, (int, float)) and base and cm >= base:
        hard.append(f"D4 degenerate: churn MRR ({cm}) >= total MRR ({base}) — the old degenerate case")
    cr = churn.get("current_churn_rate_pct")
    if isinstance(cr, (int, float)) and not (0 <= cr <= 100):
        hard.append(f"D4 bounds: churn rate out of 0-100%: {cr}")

    # ── D5: language (fragments / orphan subjects / dangling tokens) — warnings ──
    for line in audit_lines or []:
        if re.search(r"\{[a-zA-Z_]+\}", line) or "None" in line.split() or "$None" in line or "nan" in line.lower():
            warn.append(f"D5 language: dangling token / None / nan → {line[:80]!r}")
        # orphaned subject: a sentence that begins mid-clause with a bare verb+value
        if re.search(r"(?:^|\. )\s*held constant at \$", line):
            warn.append(f"D5 language: 'held constant at $…' with no subject → {line[:80]!r}")
        if re.search(r"\s--\s*$", line) or line.strip().endswith("--"):
            warn.append(f"D5 language: dangling em-dash fragment → {line[:80]!r}")

    summary = {"hard": len(hard), "warn": len(warn), "rules": ["D1", "D2", "D3", "D4", "D5"]}
    if hard:
        raise LintError("Report linter FAILED (data defects): " + " | ".join(hard[:8]))
    return {"ok": True, "hard_failures": hard, "warnings": warn, "summary": summary}
