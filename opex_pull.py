"""
opex_pull.py
------------
Categorised monthly burn breakdown.

MODULAR INTERFACE: consumers call `get_monthly_burn(xero_data, true_team_cost,
salary_baseline)` and get a structured breakdown. The source (currently Xero P&L
+ hardcoded overrides) can be swapped to a Google Sheet later without changing
consumers — just replace the internals of this module.

Categories:
- team: owner pay + core team payroll + super (from SALARY tab, not Xero)
- ad_spend: Xero Advertising account
- subscriptions: hardcoded $3,867/mo (Xero miscodes across accounts)
- other_opex: consulting, bank fees, office, etc (recurring only)
- commissions: closer + setter (excluded from burn, in CAC layer)
- variable_cogs: videog/photog, subcontractors (excluded — scales with work)
- one_off: travel, one-off consulting, lumpy items (excluded from forward burn)
"""
from __future__ import annotations


# ── Owner pay for burn (cash leaving bank monthly, not gross) ──────────────
# Take-home: $1,700/wk × 4 = $6,800/mo. PAYG ($2,164/mo) and super ($1,076/mo)
# are lumpy quarterly payments, excluded from monthly burn.
OWNER_TAKEHOME_MONTHLY = 6800.0

# ── Hardcoded subscriptions/tools (Rydel-confirmed, 2026-06-04) ────────────
# Xero splits these across Client Reporting Tools, Subscriptions, and other
# accounts depending on how AMEX transactions are coded. Until Piolo recodes
# to a single account, we use the confirmed total.
#
# A-Leads $1,500 · GHL ~$580 · Google Workspace ~$442 · SoWork $307 ·
# Anthropic $181 · ChatGPT $145 · Notion $122 · Make.com ~$110 · Xero $105 ·
# Asana $81 · Higgsfield $42 · Canva $40 · ManyChat $39 · Atlassian $29 ·
# Fathom $26 · Adobe $24 · GoDaddy $24 · Dropbox $19 · Google One $15 ·
# Instantly $13 · ElevenLabs $9 · Railway $8 · CapCut $6
SUBSCRIPTIONS_OVERRIDE = 3867.0

# ── Fallback values when Xero is unavailable ────────────────────────────
# Last known from Xero P&L. Used ONLY when Xero is down so the dashboard
# and PDF aren't blank. Updated when Xero values change materially.
AD_SPEND_FALLBACK = 8002.0       # Xero Advertising account (trailing 30d avg)
OTHER_OPEX_FALLBACK = 817.0      # Consulting + bank fees + office (recurring)

# ── Line-item classification ──────────────────────────────────────────────
_OPEX_CATEGORY = {
    # Team cost (already counted via SALARY tab)
    "wages and salaries": "team_already_counted",
    "superannuation": "team_already_counted",
    # Commissions (variable, in CAC layer)
    "closer commission": "commission",
    "setter commission": "commission",
    # Ad spend
    "advertising": "ad_spend",
    # Subscriptions — absorbed into SUBSCRIPTIONS_OVERRIDE, don't double-count
    "subscriptions": "subs_already_counted",
    "telephone & internet": "subs_already_counted",
    # One-offs (exclude from forward burn)
    "travel - international": "one_off",
    "travel - national": "one_off",
    # Recurring opex
    "consulting & accounting": "other_opex",
    "bank fees": "other_opex",
    "office expenses": "other_opex",
    "general expenses": "other_opex",
    "motor vehicle expenses": "other_opex",
    # Contractors WITH GST = videog/photog = variable COGS (not fixed burn)
    "contractors with gst remittly": "variable_cogs",
}

_RECURRING_OVERRIDE = {
    "consulting & accounting": 179.0,  # Rydel confirmed $179/mo recurring
}

_COGS_CATEGORY = {
    # Client Reporting Tools: absorbed into SUBSCRIPTIONS_OVERRIDE
    "client reporting tools": "subs_already_counted",
    "contractors no gst": "cogs_mixed",  # team Wise + subcontractors (variable)
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
    true_team_cost : monthly team cost from SALARY tab (source of truth).
        NOTE: For burn purposes we use salary_baseline (team Wise) + owner
        take-home, not the full true_team_cost which includes gross pay + super.
    salary_baseline : core team payroll via Wise from SALARY tab (~$18,891)
        Used to split Contractors NO GST into team vs subcontractor portions.

    Returns
    -------
    dict with burn breakdown, totals, and line-item details.
    """
    team_wise = salary_baseline or 18891.0
    owner_pay = OWNER_TAKEHOME_MONTHLY

    if not xero_data:
        # Use hardcoded known values for burn components that don't need Xero
        subscriptions = SUBSCRIPTIONS_OVERRIDE
        ad_spend = AD_SPEND_FALLBACK
        other_opex = OTHER_OPEX_FALLBACK
        total = team_wise + owner_pay + ad_spend + subscriptions + other_opex
        return {
            "available": False,
            "reason": "No Xero P&L data -- using hardcoded burn components",
            "total_recurring_burn": round(total, 2),
            "team": round(team_wise, 2),
            "owner_pay": round(owner_pay, 2),
            "ad_spend": round(ad_spend, 2),
            "ad_spend_note": "Fallback estimate (Xero unavailable)",
            "subscriptions": round(subscriptions, 2),
            "other_opex": round(other_opex, 2),
            "source": "salary_tab + hardcoded_fallback",
        }

    opex_lines = xero_data.get("opex_line_items") or []
    cogs_lines = xero_data.get("cogs_line_items") or []

    # ── Categorise OpEx lines ──
    team_already = 0.0
    ad_spend = 0.0
    subs_already = 0.0  # Xero subs (absorbed into override, tracked for reference)
    other_opex = 0.0
    commissions = 0.0
    one_off = 0.0
    variable_cogs = 0.0  # videog/photog, subcontractors (not in fixed burn)

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
        elif cat == "subs_already_counted":
            subs_already += amount
        elif cat == "one_off":
            one_off += amount
        elif cat == "variable_cogs":
            variable_cogs += amount
        else:
            other_opex += amount

    # ── Categorise COGS lines ──
    for line in cogs_lines:
        label = line["label"]
        amount = abs(line["amount"])
        key = label.lower()
        cat = _COGS_CATEGORY.get(key, "variable_cogs")

        if cat == "cogs_mixed":
            # Contractors NO GST: team Wise (in true_team_cost) + subcontractors (variable)
            team_portion = salary_baseline or 18891.0
            sub_portion = max(0, amount - team_portion)
            variable_cogs += sub_portion
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
                    "category": "variable_cogs",
                    "note": "variable — scales with client work",
                })
        elif cat == "subs_already_counted":
            subs_already += amount
            line_details.append({
                "label": label, "amount": round(amount, 2),
                "category": "subs_already_counted",
                "note": "absorbed into subscriptions override",
            })
        else:
            variable_cogs += amount
            line_details.append({
                "label": label, "amount": round(amount, 2), "category": cat,
            })

    # ── Use hardcoded subscriptions override ──
    subscriptions = SUBSCRIPTIONS_OVERRIDE

    # ── Totals ──
    # Fixed recurring burn = cash leaving the bank every month
    # Team Wise + owner take-home (not gross — PAYG/super are lumpy quarterly)
    total_recurring_burn = (
        team_wise
        + owner_pay
        + ad_spend
        + subscriptions
        + other_opex
    )

    total_with_variable = total_recurring_burn + variable_cogs
    total_with_commissions = total_with_variable + commissions

    # COGS ratio for delivery-obligation reserve
    xero_revenue = xero_data.get("revenue") or 0
    total_cogs = xero_data.get("cogs") or 0
    cogs_ratio = round(total_cogs / xero_revenue * 100, 1) if xero_revenue > 0 else None

    return {
        "available": True,
        "team": round(team_wise, 2),
        "owner_pay": round(owner_pay, 2),
        "owner_pay_note": "Take-home $1,700/wk x 4. PAYG + super excluded (quarterly)",
        "ad_spend": round(ad_spend, 2),
        "subscriptions": round(subscriptions, 2),
        "subscriptions_note": "Hardcoded override — Xero miscodes across accounts",
        "other_opex": round(other_opex, 2),
        "variable_cogs": round(variable_cogs, 2),
        "variable_cogs_note": "Videog/photog + subcontractors — scales with work, excluded from fixed burn",
        "commissions": round(commissions, 2),
        "one_off_excluded": round(one_off, 2),
        "total_recurring_burn": round(total_recurring_burn, 2),
        "total_with_variable": round(total_with_variable, 2),
        "total_with_commissions": round(total_with_commissions, 2),
        "cogs_ratio_pct": cogs_ratio,
        "line_details": line_details,
        "source": "xero_pnl + hardcoded_subs",
    }
