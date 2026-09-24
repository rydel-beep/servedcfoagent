"""pl_mapping.py — EVERY XERO ACCOUNT, MAPPED TO A LADDER LINE, OWNER-RULED (#165).

The Hormozi ladder needs every dollar of cost on exactly one rung:

  DELIVERY (COGS)   what it costs to serve a client who already exists
  ACQUISITION       what it costs to get the next one (ads, commissions,
                    sales tooling and labour)
  OVERHEAD          the cost of the company existing at all
  CONTRA-REVENUE    refunds and rebates — shown against revenue, never inside
                    costs
  TAX & STATUTORY   income tax accrual only; GST/PAYG/BAS are pass-through
                    and never enter the ladder
  EXCLUDED          personal, transfers — not the business's operating story

The draft below comes from the FY26 review's categories and this org's own
chart (enumerated from the live books — never assumed standard codes). The
owner confirms or moves any code on the mapping page; every change is
journaled and versioned. An account the mapping has never seen is NEVER
silently binned: it lands in "needs your call" and the engine carries it as
an unmapped line in plain sight.

Wages are split delivery vs overhead by config (`PL_WAGES_DELIVERY_PCT`,
default 0 — the FY26 review costed delivery as contractors + tools, with
wages in overhead; the config exists so the owner can move a share with a
role-list reason). One mapping serves BOTH the management and recognised
bases — the bases differ in timing, never in what a cost is.
"""
from __future__ import annotations

import logging
import os
import re

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

K_OVERRIDES = "pl:mapping:overrides"
K_JOURNAL = "pl:mapping:journal"

LINES = ("revenue", "contra_revenue", "delivery", "acquisition", "overhead",
         "tax_statutory", "excluded")

LINE_LABELS = {
    "revenue": "Revenue",
    "contra_revenue": "Refunds & rebates (against revenue)",
    "delivery": "Delivery cost",
    "acquisition": "Acquisition cost",
    "overhead": "Overhead",
    "tax_statutory": "Tax & statutory",
    "excluded": "Excluded (not operating)",
}

# THIS ORG'S CHART → ladder line. Drafted from the FY26 review + the
# enumerated live accounts (outflow_bands). The owner's overrides win.
DEFAULT_MAPPING: dict[str, str] = {
    # revenue side
    "sales": "revenue",
    "interest income": "excluded",          # not operating revenue; shown, not laddered
    "refunds and rebates expense": "contra_revenue",
    # delivery — the FY26 review's basis: contractors + client tools
    "contractors no gst": "delivery",
    "contractors with gst remittly": "delivery",
    "client reporting tools": "delivery",
    # acquisition
    "advertising": "acquisition",
    "closer commission": "acquisition",
    "setter commission": "acquisition",
    # overhead
    "bank fees": "overhead",
    "stripe fees": "overhead",
    "consulting & accounting": "overhead",
    "subscriptions": "overhead",
    "superannuation": "overhead",
    "telephone & internet": "overhead",
    "travel - national": "overhead",
    "travel - international": "overhead",
    "wages and salaries": "overhead",       # split by PL_WAGES_DELIVERY_PCT
    "rent": "overhead",
    "insurance": "overhead",
    "office expenses": "overhead",
    "printing & stationery": "overhead",
    "general expenses": "overhead",
    "repairs and maintenance": "overhead",
    "light, power, heating": "overhead",
    "motor vehicle expenses": "overhead",
    "entertainment": "overhead",
    "freight & courier": "overhead",
    "depreciation": "overhead",
    # tax & statutory / excluded
    "income tax expense": "tax_statutory",
    "personal expense": "excluded",
}

_TAX_NAME_RE = re.compile(r"\b(gst|payg|bas|ato|income tax|instalment)\b", re.I)


def _key(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip().lower())


def overrides() -> dict:
    return kv_store.get(K_OVERRIDES) or {}


def set_override(account: str, line: str, actor: str, note: str = "") -> dict:
    """The owner's ruling on one code. Journaled; reversible by re-ruling."""
    if line not in LINES:
        return {"ok": False, "error": f"unknown ladder line {line!r}"}
    key = _key(account)
    ov = overrides()
    prev = (ov.get(key) or {}).get("line") or DEFAULT_MAPPING.get(key)
    ov[key] = {"line": line, "by": actor, "at": now_sydney().isoformat(),
               "note": note}
    kv_store.put(K_OVERRIDES, ov)
    journal = kv_store.get(K_JOURNAL) or []
    journal.append({"at": now_sydney().isoformat(), "account": account,
                    "from": prev, "to": line, "by": actor, "note": note})
    kv_store.put(K_JOURNAL, journal[-500:])
    return {"ok": True, "account": account, "line": line, "was": prev}


def classify(account: str) -> dict:
    """→ {line, source, needs_call}. Never silently bins: an unknown code
    whose name says tax goes to tax_statutory (flagged); anything else is
    'needs your call' and stays VISIBLE as unmapped."""
    key = _key(account)
    ov = overrides().get(key)
    if ov:
        return {"line": ov["line"], "source": f"owner ({ov['by']})",
                "needs_call": False}
    if key in DEFAULT_MAPPING:
        return {"line": DEFAULT_MAPPING[key], "source": "draft (FY26 basis)",
                "needs_call": False}
    if _TAX_NAME_RE.search(key):
        return {"line": "tax_statutory", "source": "name says tax — confirm",
                "needs_call": True}
    return {"line": "unmapped", "source": "never seen — needs your call",
            "needs_call": True}


def wages_delivery_pct() -> float:
    """Share of Wages and Salaries treated as delivery labour. Config, with
    the FY26 default of 0 (delivery = contractors + tools)."""
    try:
        return max(0.0, min(100.0, float(os.environ.get("PL_WAGES_DELIVERY_PCT", "0"))))
    except ValueError:
        return 0.0


def mapping_page() -> dict:
    """Everything the owner-only mapping page renders: each known account,
    its line, its source, and anything needing a call."""
    rows = []
    seen = set(DEFAULT_MAPPING) | set(overrides())
    for key in sorted(seen):
        c = classify(key)
        rows.append({"account": key, **c})
    return {"rows": rows, "lines": LINES, "line_labels": LINE_LABELS,
            "wages_delivery_pct": wages_delivery_pct(),
            "journal": (kv_store.get(K_JOURNAL) or [])[-20:],
            "needs_call": [r for r in rows if r["needs_call"]],
            "note": ("one mapping serves both the management and recognised "
                     "bases — the bases differ in timing, never in what a "
                     "cost is")}


def ladder_lines(pnl_lines: list[dict], revenue: float | None,
                 unmapped_sink: list | None = None) -> dict:
    """Map a parsed Xero P&L (revenue + expense line items) onto the ladder.

    Returns per-line totals and the per-account detail behind each. An
    unmapped account is carried VISIBLY under 'unmapped', never dropped."""
    out = {ln: {"total": 0.0, "items": []} for ln in LINES}
    out["unmapped"] = {"total": 0.0, "items": []}
    if revenue is not None:
        out["revenue"]["total"] = round(float(revenue), 2)
        out["revenue"]["items"].append({"account": "sales (Xero)", "amount": revenue})
    wpct = wages_delivery_pct() / 100.0
    for li in pnl_lines or []:
        label = li.get("label") or ""
        amt = float(li.get("amount") or 0)
        c = classify(label)
        line = c["line"]
        if _key(label) == "wages and salaries" and wpct > 0:
            d, o = round(amt * wpct, 2), round(amt * (1 - wpct), 2)
            out["delivery"]["items"].append({"account": label + " (delivery share)",
                                             "amount": d, "source": "config split"})
            out["delivery"]["total"] += d
            out["overhead"]["items"].append({"account": label + " (overhead share)",
                                             "amount": o, "source": "config split"})
            out["overhead"]["total"] += o
            continue
        sink = out.get(line) or out["unmapped"]
        sink["items"].append({"account": label, "amount": amt,
                              "source": c["source"]})
        sink["total"] = round(sink["total"] + amt, 2)
        if line == "unmapped" and unmapped_sink is not None:
            unmapped_sink.append(label)
    for ln in out:
        out[ln]["total"] = round(out[ln]["total"], 2)
    return out
