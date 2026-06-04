"""
opex_pull.py
------------
Categorised monthly burn breakdown from Xero P&L line items.

MODULAR INTERFACE: consumers call `get_monthly_burn(xero_data, true_team_cost,
salary_baseline)` and get a structured breakdown. The source (currently Xero P&L)
can be swapped to a Google Sheet later without changing consumers — just replace
the internals of this module.

Categories:
- team: owner pay + core team payroll + super (from SALARY tab, not Xero)
- ad_spend: Xero Advertising account
- cogs_delivery: non-team COGS (subcontractors, client tools, videog/photog)
- subscriptions: subscriptions + telecom
- other_opex: consulting, bank fees, office, etc (recurring only)
- commissions: closer + setter (excluded from burn, in CAC layer)
- one_off: travel, one-off consulting, lumpy super (excluded from forward burn)
"""
from __future__ import annotations


# ── Line-item classification ──────────────────────────────────────────────
# Maps Xero account labels (lowercased) to burn categories.
# "exclude" = already in team cost or is a commission (don't double-count).
# "one_off" = exclude from recurring forward burn.

_OPEX_CATEGORY = {
    # Team cost (already counted via SALARY tab)
    "wages and salaries": "team_already_counted",
    "superannuation": "team_already_counted",
    # Commissions (variable, in CAC layer)
    "closer commission": "commission",
    "setter commission": "commission",
    # Ad spend
    "advertising": "ad_spend",
    # Subscriptions & tools
    "subscriptions": "subscriptions",
    "telephone & internet": "subscriptions",
    # One-offs (exclude from forward burn)
    "travel - international": "one_off",
    "travel - national": "one_off",
    # Recurring opex
    "consulting & accounting": "other_opex",
    "bank fees": "other_opex",
    "office expenses": "other_opex",
    "general expenses": "other_opex",
    "motor vehicle expenses": "other_opex",
    # Contractors WITH GST = videog/photog = delivery COGS
    "contractors with gst remittly": "cogs_delivery",
}

# One-off overrides: for accounts where only part of the Xero value is recurring.
# {label_lower: recurring_monthly_amount}. The rest is treated as one-off.
_RECURRING_OVERRIDE = {
    "consulting & accounting": 179.0,  # Rydel confirmed $179/mo recurring
}

_COGS_CATEGORY = {
    "client reporting tools": "cogs_delivery",
    "contractors no gst": "cogs_mixed",  # contains team Wise payments + subcontractors
}

# COGS lines where only part is recurring (rest is one-off investment).
# {label_lower: recurring_monthly_amount}
_COGS_RECURRING_OVERRIDE = {
    # $1,500/mo recurring (email platform) + ~$1,669 other client tools.
    # The $4,600 one-off email platform setup is excluded from forward burn.
    "client reporting tools": 3169.0,  # $7,769 - $4,600 one-off = $3,169 recurring
}


def get_monthly_burn(
    xero_data: dict | None,
    true_team_cost: float,
    salary_baseline: float | None = None,
) -> dict:
    """Compute categorised monthly burn from Xero P&L line items.

    Parameters
    ----------
    xero_data : parsed Xero P&L dict (from xero_pull._parse_pnl)
    true_team_cost : monthly team cost from SALARY tab (source of truth)
    salary_baseline : core team payroll via Wise from SALARY tab (~$18,891)
        Used to split Contractors NO GST into team vs subcontractor portions.

    Returns
    -------
    dict with burn breakdown, totals, and line-item details.
    """
    if not xero_data:
        return {
            "available": False,
            "reason": "No Xero P&L data",
            "total_recurring_burn": true_team_cost,
            "team": true_team_cost,
        }

    opex_lines = xero_data.get("opex_line_items") or []
    cogs_lines = xero_data.get("cogs_line_items") or []

    # ── Categorise OpEx lines ──
    team_already = 0.0
    ad_spend = 0.0
    subscriptions = 0.0
    other_opex = 0.0
    commissions = 0.0
    one_off = 0.0
    cogs_from_opex = 0.0  # items in OpEx that are really COGS

    line_details = []

    for line in opex_lines:
        label = line["label"]
        amount = abs(line["amount"])
        key = label.lower()
        cat = _OPEX_CATEGORY.get(key, "other_opex")

        # Handle recurring overrides (partial one-off)
        if key in _RECURRING_OVERRIDE:
            recurring_amt = _RECURRING_OVERRIDE[key]
            one_off_amt = max(0, amount - recurring_amt)
            if one_off_amt > 0:
                line_details.append({
                    "label": label, "amount": round(recurring_amt, 2),
                    "category": cat, "note": "recurring portion",
                })
                line_details.append({
                    "label": f"{label} (one-off)", "amount": round(one_off_amt, 2),
                    "category": "one_off", "note": "excluded from forward burn",
                })
                other_opex += recurring_amt
                one_off += one_off_amt
                continue

        line_details.append({
            "label": label, "amount": round(amount, 2), "category": cat,
        })

        if cat == "team_already_counted":
            team_already += amount
        elif cat == "commission":
            commissions += amount
        elif cat == "ad_spend":
            ad_spend += amount
        elif cat == "subscriptions":
            subscriptions += amount
        elif cat == "one_off":
            one_off += amount
        elif cat == "cogs_delivery":
            cogs_from_opex += amount
        else:
            other_opex += amount

    # ── Categorise COGS lines ──
    cogs_delivery = cogs_from_opex  # start with any COGS items found in OpEx
    cogs_team_overlap = 0.0  # portion of COGS that's team payroll (avoid double-count)

    for line in cogs_lines:
        label = line["label"]
        amount = abs(line["amount"])
        key = label.lower()
        cat = _COGS_CATEGORY.get(key, "cogs_delivery")

        # Handle COGS recurring overrides (partial one-off)
        if key in _COGS_RECURRING_OVERRIDE and cat != "cogs_mixed":
            recurring_amt = _COGS_RECURRING_OVERRIDE[key]
            one_off_amt = max(0, amount - recurring_amt)
            cogs_delivery += recurring_amt
            if one_off_amt > 0:
                one_off += one_off_amt
                line_details.append({
                    "label": label, "amount": round(recurring_amt, 2),
                    "category": "cogs_delivery", "note": "recurring portion",
                })
                line_details.append({
                    "label": f"{label} (one-off)", "amount": round(one_off_amt, 2),
                    "category": "one_off", "note": "excluded from forward burn",
                })
            else:
                line_details.append({
                    "label": label, "amount": round(amount, 2), "category": cat,
                })
            continue

        if cat == "cogs_mixed":
            # Contractors NO GST: split into team Wise + subcontractors
            team_portion = salary_baseline or 18891.0
            sub_portion = max(0, amount - team_portion)
            cogs_team_overlap += min(amount, team_portion)
            cogs_delivery += sub_portion
            line_details.append({
                "label": f"{label} (team Wise portion)",
                "amount": round(min(amount, team_portion), 2),
                "category": "team_already_counted",
                "note": "in true_team_cost via SALARY tab",
            })
            if sub_portion > 0:
                line_details.append({
                    "label": f"{label} (subcontractor portion)",
                    "amount": round(sub_portion, 2),
                    "category": "cogs_delivery",
                })
        else:
            cogs_delivery += amount
            line_details.append({
                "label": label, "amount": round(amount, 2), "category": cat,
            })

    # ── Totals ──
    total_recurring_burn = (
        true_team_cost
        + ad_spend
        + cogs_delivery
        + subscriptions
        + other_opex
    )

    total_with_commissions = total_recurring_burn + commissions

    # COGS ratio for delivery-obligation reserve
    xero_revenue = xero_data.get("revenue") or 0
    total_cogs = xero_data.get("cogs") or 0
    cogs_ratio = round(total_cogs / xero_revenue * 100, 1) if xero_revenue > 0 else None

    return {
        "available": True,
        "team": round(true_team_cost, 2),
        "ad_spend": round(ad_spend, 2),
        "cogs_delivery": round(cogs_delivery, 2),
        "subscriptions": round(subscriptions, 2),
        "other_opex": round(other_opex, 2),
        "commissions": round(commissions, 2),
        "one_off_excluded": round(one_off, 2),
        "total_recurring_burn": round(total_recurring_burn, 2),
        "total_with_commissions": round(total_with_commissions, 2),
        "cogs_ratio_pct": cogs_ratio,
        "line_details": line_details,
        "source": "xero_pnl",
    }
