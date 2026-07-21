"""
quarterly_compare.py
--------------------
Honest QoQ + YoY comparison between quarter packs. Compares ONLY like-basis figures; where the
prior period's section is unavailable (e.g. the tracker had ~0 closes in mid-2025, so unit-economics
YoY is not computable), the comparison states it plainly rather than inventing a delta. No
cherry-picking: the pack defines the field list wholesale.
"""
from __future__ import annotations


def _delta(cur, prev) -> dict:
    if cur is None or prev is None:
        return {"current": cur, "prior": prev, "delta": None, "pct": None,
                "available": False}
    d = cur - prev
    pct = (d / prev * 100) if prev else None
    return {"current": cur, "prior": prev, "delta": round(d, 2),
            "pct": round(pct, 1) if pct is not None else None, "available": True}


# (label, path-into-pack) — the wholesale field list compared across quarters.
_FIELDS = [
    ("Contracted revenue", ["revenue_cash", "contracted_revenue"]),
    ("New-deal cash collected", ["revenue_cash", "new_deal_cash_collected"]),
    ("Avg contract value", ["revenue_cash", "avg_contract"]),
    ("Closes", ["unit_economics", "components", "closes"]),
    ("Loaded CAC", ["unit_economics", "components", "cac_loaded"]),
    ("LTGP:CAC", ["unit_economics", "ltgp_cac"]),
    ("ROAS", ["unit_economics", "roas"]),
    ("Ad spend", ["unit_economics", "components", "ad_spend"]),
    ("Leads (cohort)", ["sales", "funnel", "leads_in"]),
    ("Lead->close %", ["sales", "funnel", "lead_to_close_pct"]),
    ("Xero revenue (P&L)", ["revenue_cash", "xero_revenue", "revenue"]),
    ("Xero net profit", ["revenue_cash", "xero_revenue", "net_profit"]),
]


def _dig(pack: dict, path: list[str]):
    o = pack
    for k in path:
        if not isinstance(o, dict):
            return None
        o = o.get(k)
    return o


def compare(current: dict, prior: dict | None, kind: str) -> dict:
    """kind: 'QoQ' or 'YoY'. Returns per-field deltas with availability + a basis note."""
    rows = []
    if not prior:
        return {"kind": kind, "available": False,
                "note": f"{kind} comparison unavailable — no prior-period pack.", "rows": []}
    for label, path in _FIELDS:
        cur = _dig(current, path)
        prev = _dig(prior, path)
        row = {"metric": label, **_delta(cur, prev)}
        rows.append(row)
    # count how much was genuinely comparable
    comparable = sum(1 for r in rows if r.get("available"))
    return {
        "kind": kind,
        "current_label": current.get("label"),
        "prior_label": prior.get("label"),
        "available": comparable > 0,
        "comparable_fields": comparable,
        "total_fields": len(rows),
        "rows": rows,
        "note": (f"{comparable}/{len(rows)} fields were like-basis comparable. Fields showing "
                 "unavailable had no prior-period data (stated, never fabricated)."),
    }
