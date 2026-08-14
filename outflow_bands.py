"""
outflow_bands.py
----------------
THE OUTFLOW BAND CLASSIFIER (outflow-truth wave, 2026-08-13).

Splits P&L outflows into labelled bands — OPEX (the managed number) ·
TAX/STATUTORY (BAS/GST/PAYG/income-tax — flagged, visible, never blended) ·
PERSONAL · FLAGGED (unknown accounts — surfaced for review, owner-assignable,
journaled, reversible). Total outflow still sums to reality: the partition
invariant I-OUTFLOW (sum of bands == Total Operating Expenses) is asserted in
every payload and watched nightly.

THE CLASSIFIER LESSON (encoded — the estate's own 97% misclassification
incident): the LEDGER'S OWN ACCOUNT (the Xero chart-of-accounts name the line
belongs to) is the PRIMARY signal. Payee/description keywords are never
consulted here at all — this module classifies ACCOUNTS, not transactions.
An account that matches no rule lands in FLAGGED — surfaced, never silently
assigned to either band. Owner assignments become deterministic rules
(kv, journaled) — never fuzzy drift.

TWO HONEST VIEWS: ACCRUAL (OpEx + the month's accrued ATO share from the
existing bas_engine set-aside math, labelled "accrued — planning estimate")
and CASH (the real tax events flagged in their months). Neither pretends to
be the other. ESTIMATES-NOT-ADVICE stands; lodged-period BAS doctrine
(export wins) untouched.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KV_RULES = "outflow:band_rules"          # {account_key: band} — owner-taught
_KV_JOURNAL = "outflow:band_journal"      # who/when/account old→new (cap 200)
_KV_MONTH_CACHE = "outflow:month_bands"   # {YYYY-MM: {bands..., total}} closed months

BANDS = ("opex", "tax_statutory", "personal", "flagged")

# THIS ORG'S CHART (enumerated from the live books, dashboard/OUTFLOW_DIAGNOSIS.md
# — never assumed standard codes). The account NAME is the ledger signal.
_ACCOUNT_BAND = {
    # TAX/STATUTORY — settling statutory positions, not operating cost
    "income tax expense": "tax_statutory",
    # PERSONAL — the books carry an explicit personal account
    "personal expense": "personal",
    # OPEX — the real operating cost accounts
    "advertising": "opex",
    "bank fees": "opex",
    "client reporting tools": "opex",
    "closer commission": "opex",
    "consulting & accounting": "opex",
    "contractors no gst": "opex",
    "contractors with gst remittly": "opex",
    "depreciation": "opex",
    "entertainment": "opex",
    "freight & courier": "opex",
    "general expenses": "opex",
    "insurance": "opex",
    "light, power, heating": "opex",
    "motor vehicle expenses": "opex",
    "office expenses": "opex",
    "printing & stationery": "opex",
    "refunds and rebates expense": "opex",
    "rent": "opex",
    "repairs and maintenance": "opex",
    "setter commission": "opex",
    "stripe fees": "opex",
    "subscriptions": "opex",
    # SUPER: the chart codes employer super as an operating expense — it IS a
    # real payroll cost, NOT tax (PAYG withholding is the tax; super is
    # remuneration). Classified OPEX from the books; flagged in the report
    # for Rydel's veto.
    "superannuation": "opex",
    "telephone & internet": "opex",
    "travel - international": "opex",
    "travel - national": "opex",
    "wages and salaries": "opex",
}

# account-NAME tax tokens (still the ledger's own account name — never a payee/
# description): an unmapped account whose NAME says tax goes to the tax band.
_TAX_NAME_RE = re.compile(r"\b(gst|payg|bas|ato|income tax|instalment|"
                          r"integrated client)\b", re.I)


def _key(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip().lower())


def _rules() -> dict:
    try:
        import kv_store
        r = kv_store.get(_KV_RULES)
        return r if isinstance(r, dict) else {}
    except Exception:
        return {}


def classify_account(label: str) -> tuple[str, str]:
    """(band, basis) for a LEDGER ACCOUNT name. Owner-taught rules first
    (deterministic), then the enumerated org chart, then the tax-name rule;
    anything unknown → FLAGGED (surfaced, never silently assigned)."""
    k = _key(label)
    taught = _rules().get(k)
    if taught in BANDS:
        return taught, "owner-assigned rule (journaled)"
    if k in _ACCOUNT_BAND:
        return _ACCOUNT_BAND[k], "org chart of accounts"
    if _TAX_NAME_RE.search(k):
        return "tax_statutory", "account name carries a tax token"
    return "flagged", "unknown account — needs review (never silently assigned)"


def band_line_items(lines: list[dict]) -> dict:
    """Band a P&L expense-section line list. Returns {bands: {band: total},
    items: [{label, amount, band, basis}], partition: {total, sum, ok}}."""
    bands = {b: 0.0 for b in BANDS}
    items = []
    for line in lines or []:
        label = line.get("label") or ""
        amount = abs(float(line.get("amount") or 0))
        band, basis = classify_account(label)
        bands[band] = round(bands[band] + amount, 2)
        items.append({"label": label, "amount": round(amount, 2),
                      "band": band, "basis": basis})
    total = round(sum(abs(float(l.get("amount") or 0)) for l in lines or []), 2)
    ssum = round(sum(bands.values()), 2)
    return {"bands": {b: round(v, 2) for b, v in bands.items()},
            "items": items,
            "partition": {"total": total, "sum": ssum,
                          "ok": abs(total - ssum) < 0.05,
                          "invariant": "I-OUTFLOW: total outflow == sum of bands"}}


def assign(actor: dict, account: str, band: str) -> tuple[dict | None, str | None]:
    """Owner one-click assignment of a FLAGGED account → a deterministic rule.
    Journaled {who, when, account, old→new}; reversible (re-assign or clear
    with band='flagged'). Teaching is rules-only — never fuzzy drift."""
    if band not in BANDS:
        return None, f"band must be one of {', '.join(BANDS)}"
    k = _key(account)
    if not k:
        return None, "account required"
    import kv_store
    from helpers import now_sydney
    rules = _rules()
    old = rules.get(k) or classify_account(account)[0]
    if band == "flagged":
        rules.pop(k, None)           # clearing the rule returns it to review
    else:
        rules[k] = band
    kv_store.put(_KV_RULES, rules)
    j = kv_store.get(_KV_JOURNAL) or []
    j.append({"at": now_sydney().strftime("%Y-%m-%d %H:%M"),
              "who": (actor or {}).get("user") or "unknown",
              "account": k, "old": old, "new": band})
    kv_store.put(_KV_JOURNAL, j[-200:])
    kv_store.delete(_KV_MONTH_CACHE)     # restatement: months re-band next read
    return {"account": k, "band": band, "journal": j[-1]}, None


def journal_entries(limit: int = 50) -> list:
    try:
        import kv_store
        return (kv_store.get(_KV_JOURNAL) or [])[-limit:]
    except Exception:
        return []


# ── the restated trailing months (the payoff exhibit) ────────────────────────

def _month_windows(n: int) -> list[tuple[str, str, str]]:
    import calendar
    import datetime as dt
    from helpers import today_sydney
    today = today_sydney()
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        last = calendar.monthrange(y, m)[1]
        out.append((f"{y}-{m:02d}", f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}"))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def monthly_bands(months: int = 6) -> dict:
    """Trailing months restated by band — a CLASSIFICATION over the same P&L
    (journaled as such, never a data change). Closed months cache permanently
    (a closed P&L month is stable); the current month refreshes per call.
    ACCRUAL leg: the month's accrued ATO share from the existing bas_engine
    set-aside math, labelled a planning estimate."""
    import kv_store
    import xero_pull
    from helpers import today_sydney
    cache = kv_store.get(_KV_MONTH_CACHE) or {}
    cur_key = f"{today_sydney().year}-{today_sydney().month:02d}"
    rows = []
    degraded = []
    changed = False
    for mkey, start, end in _month_windows(months):
        if mkey in cache and mkey != cur_key:
            rows.append(cache[mkey])
            continue
        pl = xero_pull.pull_pl_range(start, end)
        if not pl.get("ok"):
            degraded.append({"metric": "outflow_bands",
                             "reason": f"{mkey}: {pl.get('reason')}"})
            rows.append({"month": mkey, "unavailable": pl.get("reason")})
            continue
        banded = band_line_items(pl.get("opex_line_items") or [])
        row = {"month": mkey,
               "blended_total": pl.get("operating_expenses"),
               **{b: banded["bands"][b] for b in BANDS},
               "partition_ok": banded["partition"]["ok"],
               "tax_items": [i for i in banded["items"]
                             if i["band"] == "tax_statutory"],
               "flagged_items": [i for i in banded["items"]
                                 if i["band"] == "flagged"]}
        rows.append(row)
        if mkey != cur_key:
            cache[mkey] = row
            changed = True
    if changed:
        kv_store.put(_KV_MONTH_CACHE, cache)

    # ACCRUAL leg — the EXISTING bas_engine estimate (kv-read, no new math):
    # the modelled full-quarter obligation spread over its 3 months + the
    # accrued-to-date figure. Labelled planning estimate, never advice.
    accrual = {"available": False}
    try:
        import bas_engine
        est = bas_engine.estimate() or {}
        cur = est.get("current_obligation") or {}
        q_amount = cur.get("amount")
        accrual = {
            "available": q_amount is not None or cur.get("accrued_so_far") is not None,
            "quarter_label": cur.get("label"),
            "quarter_obligation": q_amount,
            "accrued_qtd": cur.get("accrued_so_far"),
            "monthly_accrued_share": (round(float(q_amount) / 3, 2)
                                      if q_amount is not None else None),
            "label": "accrued — planning estimate (the bas_engine set-aside "
                     "math, quarter obligation ÷ 3; export/official figures "
                     "win for lodged periods)"}
    except Exception as e:
        accrual = {"available": False, "reason": str(e)[:100]}

    return {"months": rows, "accrual": accrual,
            "views": {"cash": "the real tax events flagged in their months "
                              "(lumpy — the truth of when money left)",
                      "accrual": "OpEx + the monthly accrued ATO share "
                                 "(smooth — labelled planning estimate)"},
            "super_note": "Superannuation classified OPEX (a real payroll "
                          "cost per the books) — flag for Rydel's veto",
            "invariant": "I-OUTFLOW: blended_total == opex + tax_statutory + "
                         "personal + flagged, per month",
            "degraded": degraded}


# ── EDITH (read-only) ────────────────────────────────────────────────────────

_EXPENSE_RE = re.compile(
    r"(real|actual|true|monthly)\s+(monthly\s+)?(expens|opex|operating cost)|"
    r"what.{0,20}(spend|expens).{0,20}(month|monthly)|opex.{0,15}(really|actual)", re.I)


def handle_expense_query(text: str) -> tuple[str | None, bool]:
    """'What are our real monthly expenses' → OpEx + the tax band stated
    separately — never the blended number."""
    if not _EXPENSE_RE.search(text or ""):
        return None, False
    data = monthly_bands(3)
    rows = [r for r in data["months"] if not r.get("unavailable")]
    if not rows:
        return ("The banded expense view is unavailable right now (Xero P&L "
                "unreachable) — no blended guess offered.", True)
    lines = ["Real monthly expenses (OpEx band — tax stated separately, never blended):"]
    for r in rows[-3:]:
        tax_bit = (f" · tax/statutory ${r['tax_statutory']:,.0f} (flagged — "
                   f"statutory settlement, not operating cost)"
                   if r.get("tax_statutory") else "")
        pers = f" · personal ${r['personal']:,.0f}" if r.get("personal") else ""
        lines.append(f"· {r['month']}: OpEx ${r['opex']:,.0f}{tax_bit}{pers} "
                     f"(blended P&L total ${r['blended_total']:,.0f})")
    acc = data.get("accrual") or {}
    if acc.get("monthly_accrued_share"):
        lines.append(f"Accrual view: + ~${acc['monthly_accrued_share']:,.0f}/mo "
                     f"accrued ATO share — planning estimate, not advice.")
    return ("\n".join(lines), True)


# ── sentinel (nightly I-OUTFLOW) ─────────────────────────────────────────────

def sentinel_watch() -> dict:
    """Partition invariant over the trailing months + flagged-lane size."""
    out = {}
    try:
        data = monthly_bands(6)
        bad = [r["month"] for r in data["months"]
               if not r.get("unavailable") and not r.get("partition_ok")]
        flagged = sum(len(r.get("flagged_items") or []) for r in data["months"]
                      if not r.get("unavailable"))
        out = {"partition_violations": bad, "flagged_accounts": flagged,
               "ok": not bad}
        if bad:
            _feed(f"I-OUTFLOW violated: band sums ≠ total OpEx for {bad} — "
                  "the partition is the invariant", loud=True)
        if flagged:
            _feed(f"{flagged} unclassified outflow account(s) in the FLAGGED "
                  "lane — review + assign on the outflow panel")
    except Exception as e:
        out = {"error": str(e)[:100]}
    return out


def _feed(msg: str, loud: bool = False) -> None:
    try:
        import ad_sentinel
        ad_sentinel._feed(msg, loud=loud)
    except Exception:
        pass
