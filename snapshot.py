"""
snapshot.py
-----------
Orchestrates data pulls and assembles the CFO snapshot.
Persists the last good snapshot to disk so a Railway restart preserves it.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from config import SNAPSHOT_FILE, FINANCE_SHEET_CONFIG
from helpers import now_sydney
from stripe_pull import pull_stripe
from ghl_pull import pull_ghl
from sheets_pull import pull_sheets
from xero_pull import pull_xero
from finance_sheets_pull import pull_salary_baseline, pull_recognized_revenue, pull_client_health
from sales_analytics_pull import pull_sales_analytics
from hormozi_metrics import compute_all as compute_hormozi
from verdicts import build_verdicts
from active_clients import derive_active_clients
from xero_wages_categoriser import (
    compute_true_team_cost,
    compute_owner_pay_breakdown,
    categorise_contractors_account,
    OWNER_RECURRING_GROSS_MONTHLY,
)
from team_model import build_team_model
from deficiency_analysis import build_deficiency_analysis
from hiring_model import compute_hiring_analysis
from opex_pull import get_monthly_burn
from team_roster import pull_team_roster
from meta_spend import pull_meta_spend
import history_store

logger = logging.getLogger(__name__)


def _reconcile_clients(sales: dict | None, client_health: dict | None) -> dict:
    """
    Cross-reference won deals from Lead-to-Cash tracker against Health tab.
    Flags:
    - Won deals whose business name is NOT on the Health tab
    - Active clients on Health tab with $0 MRR (likely churned)
    """
    result = {
        "missing_from_health": [],
        "zero_mrr_active": [],
        "prepaid_active": [],
        "estimated_missing_mrr": 0,
        "health_client_count": 0,
        "won_business_count": 0,
    }

    if not sales or not client_health:
        return result

    won_businesses = sales.get("won_businesses") or []
    health_clients = client_health.get("clients") or []

    result["won_business_count"] = len(won_businesses)
    result["health_client_count"] = len(health_clients)

    # Normalise health client names for fuzzy matching
    health_names = set()
    for c in health_clients:
        name = c.get("name", "").strip().lower()
        if name:
            health_names.add(name)

    # Check which won businesses are NOT on the Health tab
    for wb in won_businesses:
        wb_name = wb.get("name", "").strip()
        if not wb_name:
            continue
        normalised = wb_name.lower()
        # Try exact match, then substring match (handles "Butlers cucina" vs "Butler's Cucina")
        matched = False
        for hn in health_names:
            if normalised == hn:
                matched = True
                break
            # Substring: if either contains the other (handles apostrophes, abbreviations)
            clean_wb = normalised.replace("'", "").replace("'", "")
            clean_hn = hn.replace("'", "").replace("'", "")
            if clean_wb in clean_hn or clean_hn in clean_wb:
                matched = True
                break
        if not matched:
            result["missing_from_health"].append({
                "name": wb_name,
                "close_date": wb.get("close_date"),
                "offer": wb.get("offer"),
                "contract_value": wb.get("contract_value"),
            })

    # Estimate missing MRR: contract_value / 6 months (typical contract length)
    for m in result["missing_from_health"]:
        cv = m.get("contract_value")
        if cv and cv > 0:
            result["estimated_missing_mrr"] += cv / 6

    result["estimated_missing_mrr"] = round(result["estimated_missing_mrr"], 2)

    # Find Active clients with $0 MRR — separate prepaid from potential churn
    for c in health_clients:
        if c.get("status") == "Active" and (c.get("current_mrr") or 0) == 0:
            if c.get("prepaid_flag") == "prepaid_active":
                # Prepaid client with active contract — not churn
                result["prepaid_active"].append({
                    "name": c.get("name", "Unknown"),
                    "contract_end": c.get("contract_end"),
                    "contract_value": c.get("contract_value"),
                })
            else:
                result["zero_mrr_active"].append(c.get("name", "Unknown"))

    return result


def _run_integrity_checks(snap: dict, hormozi: dict) -> list[str]:
    """Run cross-source sanity checks. Returns list of warning strings."""
    warnings = []

    # Gross margin in valid range
    gm = (snap.get("xero") or {}).get("gross_margin_pct")
    if gm is not None and (gm < 0 or gm > 100):
        warnings.append(f"Gross margin {gm}% outside valid range (0-100%)")

    # Projection growth rate sanity
    proj = ((snap.get("client_health") or {}).get("projection") or {})
    growth_avg = proj.get("growth_rate_3mo_avg")
    if growth_avg is not None and abs(growth_avg) > 50:
        warnings.append(
            f"MRR projection growth rate {growth_avg}%/mo exceeds 50% — "
            f"likely a calc artifact or early-stage noise"
        )

    # Commission ≤ cash collected
    costs = snap.get("costs") or {}
    sales = snap.get("sales") or {}
    deep_money = (sales.get("deep") or {}).get("money") or {}
    total_cash = deep_money.get("total_cash_collected", 0) or 0
    closer_comm = costs.get("closer_commission") or 0
    setter_comm = costs.get("setter_commission") or 0
    if total_cash > 0 and (closer_comm + setter_comm) > total_cash:
        warnings.append(
            f"Total commissions (${closer_comm + setter_comm:,.0f}) exceed "
            f"total cash collected (${total_cash:,.0f})"
        )

    # No negative MRR
    ch = snap.get("client_health") or {}
    mrr = ch.get("current_mrr")
    if mrr is not None and mrr < 0:
        warnings.append(f"Negative MRR (${mrr:,.0f}) — impossible, check source")

    # Hormozi ratios sanity
    for key, m in hormozi.items():
        val = m.get("value")
        if val is not None:
            if key in ("ltgp_cac", "ltgp_to_cac", "ltv_to_cac") and val > 100:
                warnings.append(f"Hormozi {key} = {val}x — implausibly high, verify inputs")
            if key == "payback_days" and val < 0:
                warnings.append(f"Hormozi payback_days = {val} — negative, impossible")

    return warnings


def build_snapshot() -> dict:
    """Pull all sources in parallel and assemble a single snapshot dict."""
    ts = now_sydney()

    with ThreadPoolExecutor(max_workers=8) as pool:
        f_stripe = pool.submit(pull_stripe)
        f_ghl = pool.submit(pull_ghl)
        f_sheets = pool.submit(pull_sheets)
        f_xero = pool.submit(pull_xero)
        f_salary = pool.submit(pull_salary_baseline)
        f_recognized = pool.submit(pull_recognized_revenue)
        f_sales = pool.submit(pull_sales_analytics)
        f_health = pool.submit(pull_client_health)
        f_roster = pool.submit(pull_team_roster)
        f_meta = pool.submit(pull_meta_spend)

    stripe_result = f_stripe.result()
    ghl_result = f_ghl.result()
    sheets_result = f_sheets.result()
    xero_result = f_xero.result()
    salary_result = f_salary.result()
    recognized_result = f_recognized.result()
    sales_result = f_sales.result()
    health_result = f_health.result()
    roster_result = f_roster.result()
    meta_result = f_meta.result()

    # Merge degraded lists
    degraded = (
        stripe_result.get("degraded", [])
        + ghl_result.get("degraded", [])
        + sheets_result.get("degraded", [])
        + xero_result.get("degraded", [])
        + salary_result.get("degraded", [])
        + recognized_result.get("degraded", [])
        + sales_result.get("degraded", [])
        + health_result.get("degraded", [])
        + roster_result.get("degraded", [])
        + meta_result.get("degraded", [])
    )

    # Build costs block from actual sheet commission values
    sheets_data = sheets_result.get("sheets")
    costs = None
    if sheets_data:
        costs = {
            "closer_commission": sheets_data.get("closer_commission_total"),
            "setter_commission": sheets_data.get("setter_commission_total"),
            "source": "sheet actuals (Commission Closer #20, Commission Setter #19)",
        }

    # Build profit block from Xero P&L data
    xero_data = xero_result.get("xero")
    profit = None
    if xero_data:
        profit = {
            "revenue": xero_data.get("revenue"),
            "cogs": xero_data.get("cogs"),
            "gross_profit": xero_data.get("gross_profit"),
            "gross_margin_pct": xero_data.get("gross_margin_pct"),
            "other_income": xero_data.get("other_income"),
            "operating_expenses": xero_data.get("operating_expenses"),
            "net_profit": xero_data.get("net_profit"),
            "period": xero_data.get("period"),
            "source": "Xero P&L report",
        }

    # Build categorised payroll block using true_team_cost
    payroll_baseline = salary_result.get("payroll_baseline")
    true_team = compute_true_team_cost(salary_tab_baseline=payroll_baseline)
    true_team_cost = true_team["true_team_cost_monthly"]

    # Owner pay breakdown (compares Xero Wages and Salaries against expected)
    xero_wages = xero_data.get("xero_wages") if xero_data else None
    owner_breakdown = compute_owner_pay_breakdown(xero_wages)

    # Contractors split (team payroll vs subcontractor COGS)
    contractors_total = xero_data.get("xero_contractors") if xero_data else None
    contractors_split = categorise_contractors_account(contractors_total, payroll_baseline)

    payroll = {
        "true_team_cost": true_team,
        "owner_pay_breakdown": owner_breakdown,
        "contractors_split": contractors_split,
    }

    # Flag excess in owner pay as a data-quality issue
    if owner_breakdown.get("excess_flag"):
        degraded.append({
            "metric": "owner_pay_excess",
            "reason": owner_breakdown["excess_flag"],
        })

    if profit:
        profit["payroll"] = payroll

    # ── Full-outflow monthly burn breakdown ─────────────────────────────────
    burn = get_monthly_burn(
        xero_data=xero_data,
        true_team_cost=true_team_cost,
        salary_baseline=payroll_baseline,
    )

    # Build revenue views cross-reference
    stripe_data = stripe_result.get("stripe")
    stripe_rev = None
    if stripe_data and stripe_data.get("revenue"):
        stripe_rev = stripe_data["revenue"]["current"].get("total_aud")

    recognized = recognized_result.get("recognized_revenue")
    recognized_validation = recognized_result.get("recognized_validation", {})

    # CHECK 3: Cross-source range check (recognized vs Xero revenue)
    xero_rev = xero_data.get("revenue") if xero_data else None
    if recognized is not None and xero_rev is not None and xero_rev > 0:
        ratio = round(recognized / xero_rev, 2)
        recognized_validation["cross_source_ratio"] = ratio
        recognized_validation["range_ok"] = 0.5 <= ratio <= 1.8
        if not recognized_validation["range_ok"]:
            degraded.append({
                "metric": "recognized_range_check",
                "reason": (
                    f"Recognized revenue ${recognized:,.2f} is {ratio}x Xero revenue"
                    f" ${xero_rev:,.2f} — outside expected range (0.5x–1.8x), verify"
                ),
            })
    else:
        recognized_validation["cross_source_ratio"] = None
        recognized_validation["range_ok"] = None

    revenue_views = {
        "stripe_cash_trailing_30d": stripe_rev,
        "xero_pl_period": xero_rev,
        "recognized_current_month": recognized,
        "recognized_month": recognized_result.get("recognized_month"),
        "recognized_client_count": recognized_result.get("recognized_client_count"),
        "recognized_validation": recognized_validation,
    }

    # ── Client reconciliation: cross-reference LTC won deals vs Health tab ──
    reconciliation = _reconcile_clients(
        sales_result.get("sales"),
        health_result.get("client_health"),
    )
    if reconciliation.get("missing_from_health"):
        degraded.append({
            "metric": "client_reconciliation",
            "reason": (
                f"{len(reconciliation['missing_from_health'])} won deal(s) not on Health tab: "
                + ", ".join(c["name"] for c in reconciliation["missing_from_health"])
                + f" — MRR may be understated by ~${reconciliation.get('estimated_missing_mrr', 0):,.0f}/mo"
            ),
        })
    if reconciliation.get("zero_mrr_active"):
        degraded.append({
            "metric": "zero_mrr_active_clients",
            "reason": (
                f"{len(reconciliation['zero_mrr_active'])} Active client(s) with $0 MRR: "
                + ", ".join(reconciliation["zero_mrr_active"])
                + " — may be churned, update Health tab status"
            ),
        })

    # ── Derived active clients ──────────────────────────────────────────────
    sales_data = sales_result.get("sales") or {}
    won_businesses_raw = sales_data.get("won_businesses") or []
    # Build won_deals list for active_clients module
    won_deals_for_derivation = []
    for wb in won_businesses_raw:
        if wb.get("name"):
            won_deals_for_derivation.append({
                "business": wb["name"],
                "close_date": wb.get("close_date"),
                "contract": wb.get("contract_value"),
                "cash": wb.get("cash_collected"),
                "offer": wb.get("offer"),
            })

    # The Health tab IS the authoritative roster. If its pull failed (e.g. the Finance sheet
    # 401s), client_health is None — the derivation must NOT silently fall back to the LTC
    # Won-deal count and present it as the active-client headline.
    health_source_ok = health_result.get("client_health") is not None
    health_clients_list = (health_result.get("client_health") or {}).get("clients") or []
    stripe_mrr_val = stripe_data.get("mrr") if stripe_data else None
    stripe_subs_active = None
    if stripe_data and stripe_data.get("subscriptions"):
        stripe_subs_active = stripe_data["subscriptions"].get("active")

    derived_clients = derive_active_clients(
        health_clients=health_clients_list,
        won_deals=won_deals_for_derivation,
        stripe_mrr=stripe_mrr_val,
        stripe_active_subs=stripe_subs_active,
        health_source_ok=health_source_ok,
    )

    # Roster-source-down handling: substitute the last-good roster (labelled stale) so the
    # dashboard never shows the bogus LTC-Won-only headline. Loud degraded entry + flags.
    if not health_source_ok:
        degraded.append({
            "metric": "client_roster_source",
            "reason": (
                "Health tab (authoritative client roster) unavailable — active-client count "
                "cannot be confirmed. Check the Finance sheet is shared/readable. Showing "
                "last-good roster, labelled stale."
            ),
            "severity": "core",
        })
        bogus_live_count = derived_clients.get("active_count")
        prior = load_persisted()
        prior_ac = (prior or {}).get("active_clients") or {}
        if prior_ac.get("active_count") and not prior_ac.get("roster_source_down"):
            # Carry the last-good roster forward, clearly labelled stale.
            derived_clients = {
                **prior_ac,
                "roster_source_down": True,
                "roster_stale": True,
                "roster_stale_since": (prior or {}).get("generated_at"),
                "active_count_live_unavailable": bogus_live_count,
                "confidence": "low",
                "roster_source_reason": (
                    "Health tab unavailable this refresh — showing the last confirmed roster "
                    f"from {(prior or {}).get('generated_at')}, labelled stale. The live LTC-only "
                    f"fallback ({bogus_live_count}) is suppressed as unreliable."
                ),
            }
        # else: no clean last-good — keep the flagged (roster_source_down) derivation; the UI
        # renders it as "roster source down — count unconfirmed", never as a confident headline.

    snapshot = {
        "generated_at": ts.isoformat(),
        "timezone": "Australia/Sydney",
        "currency": "AUD",
        "stripe": stripe_data,
        "ghl": ghl_result.get("ghl"),
        "sheets": sheets_data,
        "xero": xero_data,
        "sales": sales_result.get("sales"),
        "client_health": health_result.get("client_health"),
        "costs": costs,
        "profit": profit,
        "revenue_views": revenue_views,
        "client_reconciliation": reconciliation,
        "active_clients": derived_clients,
        "team_roster": roster_result,
        "monthly_burn": burn,
        "meta_spend": meta_result.get("meta_spend"),
        "degraded": degraded if degraded else [],
        "ok": len(degraded) == 0,
    }

    # ── Resolve the authoritative ad-spend for unit economics ─────────────────
    # Meta live spend (primary) → Xero Advertising line (fallback) → None. One value,
    # window-consistent with the funnel's trailing-30d, every consumer reads this.
    meta_block = meta_result.get("meta_spend")
    xero_ad = (xero_data or {}).get("xero_ad_spend")
    if meta_block and meta_block.get("primary_spend") is not None:
        snapshot["ad_spend_resolved"] = {
            "value": meta_block["primary_spend"],
            "source": "meta_live",
            "window_days": meta_block.get("primary_window_days"),
            "currency": meta_block.get("currency"),
            "as_of": meta_block.get("last_fetched"),
            "label": f"Meta spend (live, trailing {meta_block.get('primary_window_days')}d)",
            "note": "Meta Marketing API — agency-wide. Excludes Google (future).",
        }
    elif xero_ad is not None:
        snapshot["ad_spend_resolved"] = {
            "value": xero_ad, "source": "xero_advertising", "window_days": 30,
            "currency": "AUD", "as_of": None,
            "label": "Ad spend (Xero Advertising line)",
            "note": "Fallback — Meta live spend unavailable.",
        }
    else:
        snapshot["ad_spend_resolved"] = {
            "value": None, "source": None, "window_days": None, "currency": None,
            "as_of": None, "label": "Ad spend unavailable", "note": None,
        }

    # Hormozi metrics + verdict layer (computed AFTER snapshot assembled)
    hormozi = compute_hormozi(snapshot, true_team_cost=true_team_cost)
    verdicts = build_verdicts(snapshot, hormozi)
    snapshot["hormozi"] = hormozi
    snapshot["verdicts"] = verdicts

    # ── Team model + strategic layer ────────────────────────────────────
    team = build_team_model()
    snapshot["team_model"] = team

    deficiency = build_deficiency_analysis(
        snapshot, team, hormozi, true_team_cost,
    )
    snapshot["deficiency_analysis"] = deficiency

    # ── Dual-basis financial position (single source of truth) ───────────
    from financial_position import build_financial_position

    current_mrr = (health_result.get("client_health") or {}).get("current_mrr") or 0
    xero_d = xero_result.get("xero") or {}

    fin_pos = build_financial_position(
        stripe_cash_30d=stripe_rev,
        xero_revenue=xero_d.get("revenue"),
        xero_cogs=xero_d.get("cogs"),
        xero_gross_profit=xero_d.get("gross_profit"),
        xero_gross_margin_pct=xero_d.get("gross_margin_pct"),
        xero_opex=xero_d.get("operating_expenses"),
        xero_net_profit=xero_d.get("net_profit"),
        true_team_cost=true_team_cost,
        ad_spend=snapshot["ad_spend_resolved"].get("value"),
        current_mrr=current_mrr,
        total_burn=burn.get("total_recurring_burn"),
    )
    snapshot["financial_position"] = fin_pos

    # ── Forward recognized MRR (churn-adjusted, from RECOGNIZED tab) ────────
    try:
        from forward_mrr import build_forward_mrr
        fwd = build_forward_mrr()
        fwd_degraded = fwd.pop("degraded", [])
        snapshot["forward_mrr"] = fwd
        degraded.extend(fwd_degraded)
    except Exception as e:
        logger.error("Forward MRR build failed: %s", e)
        snapshot["forward_mrr"] = None
        degraded.append({"metric": "forward_mrr", "reason": f"Build failed: {e}"})

    # ── Cash-on-hand (Rydel-confirmed override or Xero-derived) ───────────────
    from config import (CASH_ON_HAND_OVERRIDE, CASH_STRIPE_INCOMING,
                        CASH_DEPLOYABLE_BUFFER, CASH_TAX_RESERVED,
                        CASH_CONFIRMED_DATE)

    cash_in_bank = CASH_ON_HAND_OVERRIDE
    tax_reserved = CASH_TAX_RESERVED
    total_burn = burn.get("total_recurring_burn") or true_team_cost
    cogs_ratio = burn.get("cogs_ratio_pct")

    # Staleness of the manually confirmed cash figures
    cash_confirmed_age_days = None
    try:
        from datetime import date
        confirmed = date.fromisoformat(CASH_CONFIRMED_DATE)
        cash_confirmed_age_days = (ts.date() - confirmed).days
        if cash_confirmed_age_days > 7:
            degraded.append({
                "metric": "cash_override_stale",
                "reason": (
                    f"Cash-on-hand override last confirmed {CASH_CONFIRMED_DATE} "
                    f"({cash_confirmed_age_days}d ago) — reconfirm bank balance and Stripe "
                    f"in-transit, then update CASH_CONFIRMED_DATE"
                ),
            })
    except ValueError:
        logger.warning("CASH_CONFIRMED_DATE %r is not YYYY-MM-DD", CASH_CONFIRMED_DATE)

    # Dual deployable cash
    aggressive_deployable = round(cash_in_bank - tax_reserved, 2)

    # Conservative: also subtract delivery-obligation reserve
    # = upfront cash for undelivered work × COGS ratio
    # Approximation: use Stripe incoming as proxy for cash committed to delivery
    delivery_reserve = 0.0
    if cogs_ratio and CASH_STRIPE_INCOMING > 0:
        delivery_reserve = round(CASH_STRIPE_INCOMING * (cogs_ratio / 100), 2)

    conservative_deployable = round(aggressive_deployable - delivery_reserve, 2)

    # Runway on total burn
    runway_months = round(cash_in_bank / total_burn, 1) if total_burn > 0 else None

    snapshot["cash_position"] = {
        # BALANCES (point-in-time levels) — never sum these with period flows.
        "cash_in_bank": cash_in_bank,
        "cash_in_bank_note": "BALANCE — landed in bank. Owner-confirmed override.",
        "stripe_incoming": CASH_STRIPE_INCOMING,
        "stripe_incoming_note": (
            "BALANCE — in transit: Stripe balance + pending payout, collected but "
            "not yet banked. Manually confirmed (no balance feed from Stripe MCP)."
        ),
        "tax_reserved": tax_reserved,
        "total_available": round(cash_in_bank + CASH_STRIPE_INCOMING, 2),
        "total_available_note": "True near-term cash = bank (landed) + Stripe in-transit. Both balances.",
        "aggressive_deployable": aggressive_deployable,
        "aggressive_note": "Cash minus tax reserve — treats all upfront cash as available",
        "conservative_deployable": conservative_deployable,
        "conservative_note": "Also excludes delivery-obligation reserve (cost to deliver work already paid for)",
        "delivery_reserve": delivery_reserve,
        "delivery_reserve_note": f"Stripe incoming ${CASH_STRIPE_INCOMING:,.0f} x COGS ratio {cogs_ratio}%"
            if cogs_ratio else "COGS ratio unavailable",
        "cogs_ratio_pct": cogs_ratio,
        # FLOW (per-period)
        "total_monthly_burn": round(total_burn, 2),
        "runway_months": runway_months,
        "source": "override" if CASH_ON_HAND_OVERRIDE > 0 else "xero",
        "confirmed_date": CASH_CONFIRMED_DATE,
        "confirmed_age_days": cash_confirmed_age_days,
    }

    # Hiring context — derives from financial_position (no double-count)
    headline_net = (fin_pos.get("headline") or {}).get("monthly_net") or 0
    avg_cash_per_close = None
    deep_money = ((sales_result.get("sales") or {}).get("deep") or {}).get("money") or {}
    avg_cash_per_close = deep_money.get("avg_cash_per_close")

    snapshot["hiring_context"] = {
        "monthly_net_income": round(headline_net, 2) if headline_net else 0,
        "monthly_headroom": round(headline_net, 2) if headline_net else 0,
        "true_team_cost": true_team_cost,
        "current_mrr": current_mrr,
        "avg_contract_value": deep_money.get("avg_contract"),
        "close_rate_pct": ((sales_result.get("sales") or {}).get("funnel") or {}).get("show_to_close_pct"),
        "avg_cash_per_close": avg_cash_per_close,
        "gross_margin_pct": xero_d.get("gross_margin_pct"),
        "monthly_revenue": (fin_pos.get("headline") or {}).get("monthly_net"),
        "note": "Headroom = net profit (costs already deducted). No double-count.",
    }

    # ── Data integrity sanity checks ──────────────────────────────────────
    integrity_warnings = _run_integrity_checks(snapshot, hormozi)
    if integrity_warnings:
        for w in integrity_warnings:
            degraded.append({"metric": "integrity_check", "reason": w})
        snapshot["degraded"] = degraded
        snapshot["ok"] = False

    # ── Per-source freshness (all pulled at build time; None = pull failed) ──
    snapshot["source_freshness"] = {
        name: (ts.isoformat() if ok_flag else None)
        for name, ok_flag in {
            "stripe": bool(stripe_data),
            "ghl": bool(ghl_result.get("ghl")),
            "sheets": bool(sheets_data),
            "xero": bool(xero_data),
            "sales": bool(sales_result.get("sales")),
            "client_health": bool(health_result.get("client_health")),
            "team_roster": bool(roster_result.get("roster")),
            "meta_spend": bool(meta_result.get("meta_spend")),
        }.items()
    }

    # ── Canonical metrics + cross-surface consistency gate ────────────────
    # One labelled value per headline metric; every consumer displays these.
    # assert_consistency fails the build LOUDLY rather than shipping numbers
    # that contradict each other across panels.
    from metrics_engine import build_canonical_metrics, assert_consistency, classify_refresh_health
    snapshot["metrics"] = build_canonical_metrics(snapshot)
    snapshot["degraded"] = degraded if degraded else []
    snapshot["ok"] = len(degraded) == 0
    # refresh_health drives the header pill: RED only on a genuine core-source failure,
    # GREEN when core sources are healthy (optional/known degradations don't block green).
    snapshot["refresh_health"] = classify_refresh_health(snapshot["degraded"])
    assert_consistency(snapshot)

    _persist(snapshot)

    # History logging — non-critical, must never fail the snapshot
    try:
        history_store.append(snapshot)
    except Exception as e:
        logger.error("History store write failed (non-critical): %s", e)

    return snapshot


def _persist(snapshot: dict) -> None:
    """Write snapshot to disk so it survives process restarts."""
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(snapshot, f, indent=2)
        logger.info("Snapshot persisted to %s", SNAPSHOT_FILE)
    except OSError as e:
        logger.error("Failed to persist snapshot: %s", e)


def load_persisted() -> dict | None:
    """Load the last persisted snapshot from disk, if it exists."""
    if not os.path.exists(SNAPSHOT_FILE):
        return None
    try:
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load persisted snapshot: %s", e)
        return None
