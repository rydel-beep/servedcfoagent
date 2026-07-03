"""
salary_view.py
--------------
Deterministic per-person salary lookup from the Finance SALARY tab — so affordability reads
and "what do we pay X" are built on VERIFIED figures, never the model's memory.

SALARY tab layout (by name, via the mirror): col0 LAST, col1 FIRST, col2 ROLE, col3 DEPARTMENT,
col4 STATUS, col5 AUD monthly ($), col6 PHP monthly (₱). Header row carries "VALUES AS OF: <date>".

Figures come VERBATIM from the tab (both AUD and PHP, so no silent FX). Names/salaries are surfaced
only on the auth-locked chat surface. Never invented; a missing person → "I don't have them".
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_TAB = "SALARY"
_C_LAST, _C_FIRST, _C_ROLE, _C_DEPT, _C_STATUS, _C_AUD, _C_PHP = 0, 1, 2, 3, 4, 5, 6


def _money(s) -> float | None:
    s = str(s or "").replace("$", "").replace("₱", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows():
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name(_TAB)
    except Exception:
        rows = None
    if rows is None:
        from finance_sheets_pull import _fetch_tab
        rows = _fetch_tab(_TAB)
    return rows or []


def read_salaries() -> dict:
    """All staff with AUD + PHP monthly salary, totals, FX, and the 'values as of' date."""
    rows = _rows()
    if not rows:
        return {"people": [], "degraded": [{"metric": "salaries", "reason": "SALARY tab unavailable"}]}
    as_of = None
    for c in rows[0]:
        m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", c or "")
        if m:
            as_of = m.group(1)
            break
    people = []
    for r in rows[1:]:
        if len(r) <= _C_PHP:
            continue
        first = (r[_C_FIRST] or "").strip()
        last = (r[_C_LAST] or "").strip()
        if not (first or last):
            continue
        aud = _money(r[_C_AUD])
        php = _money(r[_C_PHP])
        if aud is None and php is None:
            continue
        people.append({
            "name": f"{first} {last}".strip(),
            "first": first, "last": last,
            "role": (r[_C_ROLE] or "").strip(),
            "dept": (r[_C_DEPT] or "").strip(),
            "status": (r[_C_STATUS] or "").strip(),
            "aud": aud, "php": php,
        })
    tot_aud = round(sum(p["aud"] for p in people if p["aud"]), 2)
    tot_php = round(sum(p["php"] for p in people if p["php"]), 2)
    fx = round(tot_php / tot_aud, 1) if tot_aud else None  # implied PHP per AUD
    return {"people": people, "total_aud": tot_aud, "total_php": tot_php,
            "implied_fx_php_per_aud": fx, "as_of": as_of, "headcount": len(people)}


def find_people(query: str) -> list[dict]:
    """Match staff by first/last name or role fragment (case-insensitive). Deterministic."""
    q = query.lower()
    data = read_salaries()
    hits = []
    for p in data.get("people", []):
        if p["first"] and p["first"].lower() in q:
            hits.append(p)
        elif p["last"] and p["last"].lower() in q:
            hits.append(p)
    return hits


# ── Voice / text command ─────────────────────────────────────────────────────

# Explicit pay phrasing only. The old `(what|how much).*(…|on)` used a greedy bridge that matched
# ANY utterance with "what" and "on" (e.g. "what we do… the angle is more on…") → the Romano misfire.
# Now the pay verb must sit within a few words of the interrogative — no cross-ramble bridging.
_PAY_RE = re.compile(
    r"\b(salary|salaries|payroll|wages?)\b|"
    r"\bwhat do we pay\b|"
    r"\bhow much (do|does|is|are|'?s) .{0,25}\b(pay|paid|earn|earning|make|making|get|getting|on)\b|"
    r"\bwhat('?s| is| are) .{0,20}\b(salary|pay|paid|earning|wage)\b|"
    r"\bpay (for|him|her|them)\b", re.I)
# A salary-CHANGE / affordability question is ANALYSIS, not a lookup — it must go to the model
# (grounded by salary_context), never be answered with a bare current figure.
_CHANGE_Q = re.compile(
    r"\bafford\b|\b(can|could|should) (we|i)\b|what if|"
    r"\b(bump|raise|push|increase|move|change|lift|up)\b.*\bto\b.*\d", re.I)


def salary_context(text: str) -> str:
    """For any pay/salary/affordability question, a compact VERIFIED salary roster to inject into
    the model's context so its math is built on real figures, not memory. '' if not relevant."""
    if not text or not (_PAY_RE.search(text) or _CHANGE_Q.search(text)):
        return ""
    data = read_salaries()
    people = data.get("people") or []
    if not people:
        return ""
    lines = [f"- {p['name']} ({p['role']}, {p['dept']}): ${p['aud']:,.0f}/mo"
             + (f" = ₱{p['php']:,.0f}" if p.get("php") else "") for p in people if p.get("aud") is not None]
    fx = data.get("implied_fx_php_per_aud")
    return ("VERIFIED CURRENT SALARIES (from the Finance SALARY tab, as of "
            f"{data.get('as_of', '?')}; use THESE exact figures for any salary/affordability math, "
            f"never estimate — implied FX ₱{fx:,.0f} per A$1):\n" + "\n".join(lines)
            + f"\nTeam payroll total: ${data.get('total_aud', 0):,.0f}/mo across {data['headcount']} people.")


def _fmt(p: dict) -> str:
    aud = f"${p['aud']:,.0f}/mo" if p.get("aud") is not None else "?"
    php = f" (₱{p['php']:,.0f})" if p.get("php") is not None else ""
    role = f", {p['role']}" if p.get("role") else ""
    return f"{p['name']}{role}: {aud}{php}"


def handle_salary_command(text: str) -> tuple[str | None, bool]:
    """'What do we pay Gabie?' / 'team salaries' / 'total payroll' → verbatim SALARY-tab figures."""
    if not text or not _PAY_RE.search(text):
        return None, False
    if _CHANGE_Q.search(text):
        return None, False  # affordability/change question → model (grounded by salary_context)
    data = read_salaries()
    if not data.get("people"):
        return "I can't read the SALARY tab right now.", True
    asof = f" (as of {data['as_of']})" if data.get("as_of") else ""
    # A specific person?
    hits = find_people(text)
    if hits:
        return "; ".join(_fmt(p) for p in hits[:5]) + asof + ".", True
    # A department (e.g. "SMM salaries")?
    md = re.search(r"\b(smm|ads|paid ads|pr|media|tech|creative|admin|c-level|leadership)\b", text, re.I)
    if md:
        dep = md.group(1).lower()
        grp = [p for p in data["people"] if dep in (p["dept"] + " " + p["role"]).lower()]
        if grp:
            t = round(sum(p["aud"] for p in grp if p["aud"]), 0)
            return (f"{md.group(1).upper()} team ({len(grp)}): ${t:,.0f}/mo total{asof}. "
                    + "; ".join(_fmt(p) for p in grp) + "."), True
    # Total payroll / team salaries.
    if re.search(r"\b(total|payroll|team|whole|everyone|all|bill|monthly)\b", text, re.I):
        return (f"Team payroll: ${data['total_aud']:,.0f}/mo (₱{data['total_php']:,.0f}) across "
                f"{data['headcount']} people{asof}. Implied FX ₱{data['implied_fx_php_per_aud']:,.0f}/A$1."), True
    # Salary question but no clear person/dept — ask.
    return ("Whose salary — name a person (e.g. “what do we pay Gabie?”), a team (“SMM salaries”), "
            "or “total payroll”?"), True
