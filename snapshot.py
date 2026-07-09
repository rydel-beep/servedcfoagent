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
from stripe_reconcile import reconcile_stripe_tracker
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


def _resolve_ad_spend(meta_block: dict | None, xero_ad_spend: float | None) -> dict:
    """THE one ad-spend resolution for the whole dashboard (30d window).

    Meta live (primary) → Meta last-known (labelled) → Xero Advertising line
    (labelled) → None. Never the old hardcoded $8,002. Every consumer — burn,
    waterfall, financial_position, CAC/ROAS, verdicts — reads this single value.
    """
    if meta_block and meta_block.get("primary_spend") is not None:
        live = meta_block.get("fetch_ok") is not False
        wd = meta_block.get("primary_window_days") or 30
        return {
            "value": meta_block["primary_spend"],
            "source": "meta_live" if live else "meta_last_known",
            "window_days": wd,
            "currency": meta_block.get("currency"),
            "as_of": meta_block.get("last_fetched"),
            "label": f"Meta spend ({'live' if live else 'last-known'}, trailing {wd}d)",
            "note": ("Meta Marketing API — agency-wide. Excludes Google (future)." if live
                     else "Meta fetch failed — last-known value; reconfirm."),
            "xero_ref": xero_ad_spend,
        }
    if xero_ad_spend is not None:
        return {
            "value": xero_ad_spend, "source": "xero_advertising", "window_days": 30,
            "currency": "AUD", "as_of": None,
            "label": "Ad spend (Xero Advertising line)",
            "note": "Fallback — Meta live spend unavailable.", "xero_ref": xero_ad_spend,
        }
    return {"value": None, "source": None, "window_days": None, "currency": None,
            "as_of": None, "label": "Ad spend unavailable", "note": None, "xero_ref": None}


def _safe_result(future, name: str) -> dict:
    """Resolve a source future without letting its exception abort the whole snapshot. On failure,
    return a minimal degraded dict so downstream .get()s see 'this source is down' (labelled) rather
    than the build crashing. One dependency down must never take the dashboard down."""
    try:
        return future.result()
    except Exception as e:  # noqa: BLE001 — deliberately catch-all: no source may crash the build
        logger.error("snapshot source %r crashed (degrading it): %s", name, e, exc_info=True)
        return {"degraded": [{"metric": name,
                              "reason": f"{name} pull crashed: {type(e).__name__}: {e}"}]}


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
        f_reconcile = pool.submit(reconcile_stripe_tracker)

    # FAIL-SOFT: a source that RAISES degrades ITSELF (labelled), never takes the whole snapshot
    # down. This is what turned one bad scorecard cell into a total dashboard outage — a single
    # dependency failing must never = the dashboard failing.
    stripe_result = _safe_result(f_stripe, "stripe")
    ghl_result = _safe_result(f_ghl, "ghl")
    sheets_result = _safe_result(f_sheets, "sheets")
    xero_result = _safe_result(f_xero, "xero")
    salary_result = _safe_result(f_salary, "salary")
    recognized_result = _safe_result(f_recognized, "recognized_revenue")
    sales_result = _safe_result(f_sales, "sales_analytics")
    health_result = _safe_result(f_health, "client_health")
    roster_result = _safe_result(f_roster, "team_roster")
    meta_result = _safe_result(f_meta, "meta_spend")
    reconcile_result = _safe_result(f_reconcile, "stripe_reconcile")

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
        + reconcile_result.get("degraded", [])
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

    # ── Resolve THE one ad-spend (Meta live → Xero line → None) BEFORE burn ──
    # Computed here so burn, financial_position, waterfall, CAC/ROAS and verdicts
    # all read the identical figure. Never the old hardcoded $8,002.
    meta_block = meta_result.get("meta_spend")
    ad_spend_resolved = _resolve_ad_spend(meta_block, (xero_data or {}).get("xero_ad_spend"))

    # ── Full-outflow monthly burn breakdown ─────────────────────────────────
    burn = get_monthly_burn(
        xero_data=xero_data,
        true_team_cost=true_team_cost,
        salary_baseline=payroll_baseline,
        ad_spend_override=ad_spend_resolved["value"],
        ad_spend_source=ad_spend_resolved["source"],
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
        "stripe_reconciliation": reconcile_result.get("stripe_reconciliation"),
        "degraded": degraded if degraded else [],
        "ok": len(degraded) == 0,
    }

    # Single resolved ad-spend (computed before burn) — the dashboard-wide source.
    snapshot["ad_spend_resolved"] = ad_spend_resolved

    # Manual targets/benchmarks/goalposts (Rydel-set, no live source). Read on every
    # rebuild and layered on top — a rebuild NEVER wipes a set target. compute_hormozi
    # uses these so healthy/below-target classification reflects Rydel's goalposts.
    try:
        import manual_targets
        snapshot["targets"] = manual_targets.get_all()
        resolved_targets = manual_targets.get_resolved()
    except Exception as e:
        logger.error("manual_targets load failed (non-critical): %s", e)
        snapshot["targets"] = {}
        resolved_targets = {}

    # Fully-loaded CAC: real setter commission ($50/set + 5% cash) read actual from the
    # SETTER PAYOUT LOG (by name; the gid 400s), window-matched to the sales window. Replaces
    # the scorecard $50/set-only figure CAC used. Closer comm already actual-from-sheet.
    try:
        from loaded_cac import read_setter_comp
        _sales_block = sales_result.get("sales") or {}
        loaded_setter = read_setter_comp(_sales_block.get("window_start"),
                                         _sales_block.get("window_end"))
        snapshot["loaded_cac"] = loaded_setter
        degraded.extend(loaded_setter.get("degraded", []))
    except Exception as e:
        logger.error("loaded_cac setter read failed (non-critical): %s", e)
        snapshot["loaded_cac"] = {"setter_comm": None}

    # Hormozi metrics + verdict layer (computed AFTER snapshot assembled)
    hormozi = compute_hormozi(snapshot, true_team_cost=true_team_cost,
                              targets=resolved_targets)
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
        ad_spend=ad_spend_resolved["value"],
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

    # ── Real Stripe money states (balance + payouts, read-only) ──────────────
    # Replaces the aggregate "$18,000 pending" guess with the true three states.
    # Sequential (not in the pool) to stay clear of a parallel edit to the pool block.
    from stripe_balance import read_stripe_money_states
    stripe_money_res = read_stripe_money_states()
    stripe_money = stripe_money_res.get("stripe_money")
    snapshot["stripe_money"] = stripe_money
    degraded.extend(stripe_money_res.get("degraded", []))

    # ── Cash-on-hand — LIVE from Xero (Bank Summary closing balances) ─────────
    # CommBank Transaction #2352 + Online Saver #4041 + BAS/Tax #2353 (include-BAS,
    # Rydel-confirmed 2026-06-29); Amex excluded. Closing balance (point-in-time), NOT
    # period movement. Loud fallback to last-known if the live read fails — never silent stale.
    from config import (CASH_ON_HAND_LAST_KNOWN, CASH_STRIPE_INCOMING,
                        CASH_DEPLOYABLE_BUFFER, CASH_TAX_RESERVED)

    xero_cash = (xero_data or {}).get("cash_on_hand")
    if xero_cash and xero_cash.get("cash_on_hand") is not None and not xero_cash.get("missing_accounts"):
        cash_in_bank = xero_cash["cash_on_hand"]
        cash_source = "xero_live"
        cash_as_of = xero_cash.get("as_of")
        cash_breakdown = xero_cash.get("breakdown")
        cash_in_bank_note = (f"BALANCE — live Xero closing balances ({xero_cash.get('accounts')}), "
                             f"as of {cash_as_of}.")
    else:
        cash_in_bank = CASH_ON_HAND_LAST_KNOWN
        cash_source = "last_known_fallback"
        cash_as_of = None
        cash_breakdown = None
        cash_in_bank_note = (f"⚠ Cash on hand — XERO UNAVAILABLE; showing LAST-KNOWN "
                             f"${CASH_ON_HAND_LAST_KNOWN:,.0f}. Live read failed — verify/reconnect Xero.")
        degraded.append({
            "metric": "cash_on_hand_xero",
            "reason": "Live Xero cash read unavailable — using last-known fallback (loud, not silent stale)",
        })

    tax_reserved = CASH_TAX_RESERVED
    total_burn = burn.get("total_recurring_burn") or true_team_cost
    cogs_ratio = burn.get("cogs_ratio_pct")

    # ── Stripe money states feed the cash card ───────────────────────────────
    # Live (key present): real balance.available / balance.pending / in-transit payouts.
    # No key: fall back to the manual CASH_STRIPE_INCOMING, clearly labelled an estimate.
    if stripe_money:
        stripe_available = stripe_money.get("available")          # state 1: settled in Stripe
        stripe_incoming = stripe_money.get("pending_incoming")    # state 2: settling into Stripe
        stripe_in_transit = stripe_money.get("in_transit_to_bank")  # state 3: left Stripe → bank
        stripe_money_source = "stripe_live"
        stripe_incoming_note = (
            f"BALANCE — Stripe balance.pending (collected, settling into Stripe). "
            f"Live read as of {stripe_money.get('as_of', '')[:16]}."
        )
    else:
        stripe_available = None
        stripe_incoming = CASH_STRIPE_INCOMING
        stripe_in_transit = None
        stripe_money_source = "manual_estimate"
        stripe_incoming_note = (
            "BALANCE — MANUAL ESTIMATE (no Stripe key). Add a read-only STRIPE_SECRET_KEY "
            "for the real balance.pending. Reconfirm."
        )

    # Conservative: delivery-obligation reserve = incoming × COGS ratio
    incoming_for_reserve = stripe_incoming or 0
    delivery_reserve = 0.0
    if cogs_ratio and incoming_for_reserve > 0:
        delivery_reserve = round(incoming_for_reserve * (cogs_ratio / 100), 2)

    # Dual deployable cash
    aggressive_deployable = round(cash_in_bank - tax_reserved, 2)
    conservative_deployable = round(aggressive_deployable - delivery_reserve, 2)

    # Runway on total burn
    runway_months = round(cash_in_bank / total_burn, 1) if total_burn > 0 else None

    # True near-term cash = bank (landed) + Stripe settled-available + Stripe settling-incoming
    # + in-transit-to-bank. No double-count: recently_paid (arrival passed) is assumed already
    # in the bank balance, so it is NOT added here.
    total_available = round(
        cash_in_bank + (stripe_available or 0) + (stripe_incoming or 0) + (stripe_in_transit or 0), 2
    )

    snapshot["cash_position"] = {
        # BALANCES (point-in-time levels) — never sum these with period flows.
        "cash_in_bank": cash_in_bank,
        "cash_in_bank_note": cash_in_bank_note,
        "cash_in_bank_breakdown": cash_breakdown,
        "cash_as_of": cash_as_of,
        # Three distinct Stripe money states (live read when key present).
        "stripe_available": stripe_available,
        "stripe_available_note": "BALANCE — settled in Stripe, payable now (balance.available).",
        "stripe_incoming": stripe_incoming,
        "stripe_incoming_note": stripe_incoming_note,
        "stripe_in_transit_to_bank": stripe_in_transit,
        "stripe_in_transit_note": (
            "BALANCE — left Stripe (recent payouts pending/in_transit/paid-not-yet-arrived), "
            "not yet settled in CommBank (1–3 day lag)."
        ),
        "stripe_money_source": stripe_money_source,
        "tax_reserved": tax_reserved,
        "total_available": total_available,
        "total_available_note": (
            "True near-term cash = CommBank (landed) + Stripe available + Stripe incoming "
            "+ in-transit-to-bank. All balances; recently-paid (already in bank) not double-counted."
        ),
        "aggressive_deployable": aggressive_deployable,
        "aggressive_note": "Cash minus tax reserve — treats all upfront cash as available",
        "conservative_deployable": conservative_deployable,
        "conservative_note": "Also excludes delivery-obligation reserve (cost to deliver work already paid for)",
        "delivery_reserve": delivery_reserve,
        "delivery_reserve_note": f"Stripe incoming ${incoming_for_reserve:,.0f} x COGS ratio {cogs_ratio}%"
            if cogs_ratio else "COGS ratio unavailable",
        "cogs_ratio_pct": cogs_ratio,
        # FLOW (per-period)
        "total_monthly_burn": round(total_burn, 2),
        "runway_months": runway_months,
        "source": cash_source,
        "cash_as_of": cash_as_of,
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
            "stripe_money": bool(stripe_money),
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
