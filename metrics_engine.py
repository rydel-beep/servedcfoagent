"""
metrics_engine.py
-----------------
Single source of truth for every headline metric the dashboard displays.

Two jobs:

1. build_canonical_metrics(snapshot) — one canonical entry per metric, each
   tagged with its kind (FLOW = per-period, BALANCE = point-in-time), window,
   and the snapshot field it is sourced from. Every consumer (dashboard JS,
   Jarvis chat, briefing PDF, exports) should display these values, never
   recompute their own.

2. check_consistency(snapshot) — internal-arithmetic invariants. These only
   break if code is wrong (the same concept computed two ways), never because
   source data disagrees. Source-data disagreements belong in degraded[],
   not here. A failure here raises ConsistencyError at build time: the build
   fails loudly instead of shipping a contradiction.
"""
from __future__ import annotations

import math
from typing import Any


class ConsistencyError(Exception):
    """Two surfaces would display different values for the same metric."""


def _get(d: dict | None, *path, default=None):
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


def _close(a: float | None, b: float | None, tol: float = 0.51) -> bool:
    """Equality with rounding tolerance (values are rounded to 2dp or 0dp upstream)."""
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


# ── Canonical metrics ────────────────────────────────────────────────────────

def build_canonical_metrics(snapshot: dict) -> dict:
    """One canonical, labelled entry per headline metric.

    kind: FLOW (sums over a window) vs BALANCE (point-in-time level).
    FLOW and BALANCE values must never be summed with each other.
    """
    cp = snapshot.get("cash_position") or {}
    burn = snapshot.get("monthly_burn") or {}
    ch = snapshot.get("client_health") or {}
    ac = snapshot.get("active_clients") or {}
    fwd = snapshot.get("forward_mrr") or {}
    stripe = snapshot.get("stripe") or {}
    xero = snapshot.get("xero") or {}
    costs = snapshot.get("costs") or {}
    funnel = _get(snapshot, "sales", "funnel", default={}) or {}
    meta = snapshot.get("meta_spend") or {}
    ad_res = snapshot.get("ad_spend_resolved") or {}
    hz = snapshot.get("hormozi") or {}

    def m(value, kind, source, window=None, definition=None):
        out = {"value": value, "kind": kind, "source": source}
        if window:
            out["window"] = window
        if definition:
            out["definition"] = definition
        return out

    return {
        "cash_in_bank": m(
            cp.get("cash_in_bank"), "BALANCE", "cash_position.cash_in_bank",
            definition="Landed in bank (Xero/owner-confirmed). Point-in-time.",
        ),
        "cash_in_transit": m(
            cp.get("stripe_incoming"), "BALANCE", "cash_position.stripe_incoming",
            definition="Stripe balance + pending payout — collected but not yet banked.",
        ),
        "true_near_term_cash": m(
            cp.get("total_available"), "BALANCE", "cash_position.total_available",
            definition="Bank (landed) + Stripe in-transit. Both balances; never includes period flows.",
        ),
        "total_monthly_burn": m(
            cp.get("total_monthly_burn"), "FLOW", "monthly_burn.total_recurring_burn",
            window="monthly", definition="Full-outflow recurring burn (team + owner + ads + subs + opex).",
        ),
        "runway_months": m(
            cp.get("runway_months"), "BALANCE", "cash_position.runway_months",
            definition="cash_in_bank / total_monthly_burn. Static; ignores future revenue.",
        ),
        "current_mrr": m(
            ch.get("current_mrr"), "FLOW", "client_health.current_mrr",
            window="monthly", definition="Health tab confirmed MRR (primary).",
        ),
        "projected_mrr_optimistic": m(
            ac.get("projected_mrr"), "FLOW", "active_clients.projected_mrr",
            window="monthly",
            definition="Confirmed + estimated new-signing MRR (contract/6). Optimistic: ignores churn cliff.",
        ),
        "forward_mrr_next_month": m(
            ch.get("next_mrr"), "FLOW", "client_health.next_mrr",
            window="monthly", definition="Next-month recognized MRR (churn-adjusted).",
        ),
        "active_client_count": (lambda v: (
            {**v, "stale": True,
             "stale_reason": ac.get("roster_source_reason")
                 or "Health tab unavailable — roster not confirmed this refresh.",
             "stale_since": ac.get("roster_stale_since")}
            if ac.get("roster_source_down") else v
        ))(m(
            ac.get("active_count"), "BALANCE", "active_clients.active_count",
            definition="Derived: Health tab + LTC Won cross-reference, churned excluded. The only count to display.",
        )),
        "stripe_cash_collected_30d": m(
            _get(stripe, "revenue", "current", "total_aud"), "FLOW",
            "stripe.revenue.current.total_aud", window="trailing 30d",
            definition="GROSS charges collected via Stripe (before Stripe fees).",
        ),
        "stripe_payouts_banked_30d": m(
            _get(stripe, "payouts", "total_paid_out"), "FLOW",
            "stripe.payouts.total_paid_out", window="trailing 30d",
            definition="Payouts landed in bank (net of fees; lags collection). Matches Stripe's payout view.",
        ),
        "gross_margin_pct": m(
            xero.get("gross_margin_pct"), "FLOW", "xero.gross_margin_pct",
            window=xero.get("period"), definition="Xero P&L recognized basis (primary margin).",
        ),
        "true_team_cost": m(
            _get(snapshot, "profit", "payroll", "true_team_cost", "true_team_cost_monthly"),
            "FLOW", "profit.payroll.true_team_cost.true_team_cost_monthly",
            window="monthly", definition="SALARY tab team + owner gross + super.",
        ),
        "closer_commission": m(
            costs.get("closer_commission"), "FLOW", "costs.closer_commission",
            window="sheet period", definition="Sheet actuals, Commission Closer col.",
        ),
        "setter_commission": m(
            costs.get("setter_commission"), "FLOW", "costs.setter_commission",
            window="sheet period", definition="Sheet actuals, Commission Setter col.",
        ),
        "funnel_closes": m(
            funnel.get("closes"), "FLOW", "sales.funnel.closes",
            window=funnel.get("window_label") or "scorecard window",
            definition="Team Scorecard closes (primary funnel source).",
        ),
        "avg_monthly_per_client": m(
            fwd.get("avg_monthly_per_client"), "FLOW", "forward_mrr.avg_monthly_per_client",
            window="monthly",
            definition="Recognized MRR / active clients (RECOGNIZED tab). Use for unit economics.",
        ),
        "ad_spend": m(
            ad_res.get("value"), "FLOW", "ad_spend_resolved.value",
            window=f"trailing {ad_res.get('window_days')}d" if ad_res.get("window_days") else None,
            definition=(f"Resolved ad spend ({ad_res.get('source') or 'none'}). "
                        "Meta live (primary) → Xero Advertising (fallback). Feeds CAC/ROAS."),
        ),
        "meta_spend_30d": m(
            _get(meta, "windows", f"{30}d", "spend"), "FLOW", "meta_spend.windows.30d.spend",
            window="trailing 30d",
            definition="Live Meta ad spend, trailing 30d, agency-wide (read-only Insights).",
        ),
        "roas_meta": m(
            _get(hz, "roas", "value"), "FLOW", "hormozi.roas.value", window="funnel window",
            definition="New contracted revenue / ad spend, window-consistent. Meta-based.",
        ),
    }


# ── Refresh health classifier (pill green/red logic) ─────────────────────────
# A snapshot ALWAYS carries degraded entries (Xero + GHL are unconfigured by
# design, the Stripe MCP has permanent limitations, and bookkeeping data-quality
# flags are normal). The old pill turned RED on `len(degraded) > 0`, so it could
# never be green. This classifier separates a GENUINE core-source refresh failure
# (a pull that should have worked didn't) from those known/optional degradations.
#
# RED  → at least one core-source failure (the refresh genuinely failed).
# GREEN → no core failures (optional/known degradations are fine; surfaced as a
#         muted count and in the Data Quality panel, never as a red pill).
#
# Entries are classified by: explicit `severity` on the entry ("core"/"optional"),
# else membership in OPTIONAL_DEGRADED_METRICS, else default to CORE (a genuine,
# unclassified failure must be visible — better a loud red than a silent miss).

OPTIONAL_DEGRADED_METRICS = {
    # Integrations unconfigured by design (absence is not a refresh failure).
    "xero", "ghl", "ghl_pipeline",
    # Stripe MCP permanent limitations (the MCP service, not this refresh).
    "customer_count", "revenue_previous", "stripe_mrr_subs_mismatch",
    # Bookkeeping / data-quality flags — source data quirks, not pull failures.
    "closer_commission", "setter_commission", "won_but_unlogged",
    "payroll_baseline_mismatch", "funnel_cross_check", "client_reconciliation",
    "zero_mrr_active_clients", "cash_override_stale", "owner_pay_excess",
    "integrity_check", "recognized_range_check", "recognized_row_count",
    "recognized_footer_mismatch",
    # Meta ad spend is an additive enhancement; its absence/quirks don't fail a refresh.
    "meta_spend", "meta_spend_currency",
}


def classify_refresh_health(degraded: list[dict] | None) -> dict:
    """Split degraded[] into genuine core failures vs known/optional degradations.

    Returns {status: 'green'|'red', core_failures: [...], optional_degraded: [...]}.
    """
    core: list[str] = []
    optional: list[str] = []
    for d in (degraded or []):
        metric = (d or {}).get("metric", "") or "unknown"
        severity = (d or {}).get("severity")
        if severity == "core":
            core.append(metric)
        elif severity == "optional" or metric in OPTIONAL_DEGRADED_METRICS:
            optional.append(metric)
        else:
            core.append(metric)  # unclassified → treat as a genuine failure (visible)
    return {
        "status": "red" if core else "green",
        "core_failures": core,
        "optional_degraded": optional,
    }


# ── Consistency invariants ───────────────────────────────────────────────────

def _walk_json_unsafe(obj, path="$") -> list[str]:
    """Find NaN/Infinity anywhere in the snapshot — these break JSON consumers."""
    bad = []
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            bad.append(f"{path} = {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad.extend(_walk_json_unsafe(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_walk_json_unsafe(v, f"{path}[{i}]"))
    return bad


def check_consistency(snapshot: dict) -> list[str]:
    """Internal-arithmetic invariants. Returns list of violations (empty = clean)."""
    errors: list[str] = []
    cp = snapshot.get("cash_position") or {}
    burn = snapshot.get("monthly_burn") or {}

    # 1. The burn shown on the cash card must BE the burn engine's number.
    cash_burn = cp.get("total_monthly_burn")
    engine_burn = burn.get("total_recurring_burn")
    if engine_burn is not None and not _close(cash_burn, engine_burn):
        errors.append(
            f"cash_position.total_monthly_burn ({cash_burn}) != "
            f"monthly_burn.total_recurring_burn ({engine_burn})"
        )

    # 2. Runway must recompute from the displayed inputs.
    cash = cp.get("cash_in_bank")
    runway = cp.get("runway_months")
    if cash is not None and cash_burn and runway is not None:
        expected = round(cash / cash_burn, 1)
        if abs(expected - runway) > 0.05:
            errors.append(f"runway_months {runway} != cash/burn {expected}")

    # 3. Cash card internal arithmetic.
    tax = cp.get("tax_reserved")
    agg = cp.get("aggressive_deployable")
    if cash is not None and tax is not None and agg is not None and not _close(agg, cash - tax):
        errors.append(f"aggressive_deployable {agg} != cash {cash} - tax {tax}")
    res = cp.get("delivery_reserve")
    con = cp.get("conservative_deployable")
    if agg is not None and res is not None and con is not None and not _close(con, agg - res):
        errors.append(f"conservative_deployable {con} != aggressive {agg} - reserve {res}")
    transit = cp.get("stripe_incoming")
    total = cp.get("total_available")
    if cash is not None and transit is not None and total is not None and not _close(total, cash + transit):
        errors.append(f"total_available {total} != bank {cash} + in-transit {transit}")

    # 4. Commissions: the costs block must equal the sheet totals it claims to be.
    sheets = snapshot.get("sheets") or {}
    costs = snapshot.get("costs") or {}
    for key, sheet_key in (("closer_commission", "closer_commission_total"),
                           ("setter_commission", "setter_commission_total")):
        a, b = costs.get(key), sheets.get(sheet_key)
        if a is not None and b is not None and not _close(a, b):
            errors.append(f"costs.{key} ({a}) != sheets.{sheet_key} ({b})")

    # 5. Hormozi gross margin must be the Xero margin, not a recompute.
    xm = _get(snapshot, "xero", "gross_margin_pct")
    hm = _get(snapshot, "hormozi", "gross_margin", "value")
    if xm is not None and hm is not None and not _close(xm, hm, tol=0.06):
        errors.append(f"hormozi.gross_margin.value ({hm}) != xero.gross_margin_pct ({xm})")

    # 6. Revenue views must mirror their sources verbatim.
    rv = snapshot.get("revenue_views") or {}
    stripe_rev = _get(snapshot, "stripe", "revenue", "current", "total_aud")
    if rv.get("stripe_cash_trailing_30d") is not None and stripe_rev is not None \
            and not _close(rv["stripe_cash_trailing_30d"], stripe_rev):
        errors.append("revenue_views.stripe_cash_trailing_30d != stripe.revenue.current.total_aud")
    xero_rev = _get(snapshot, "xero", "revenue")
    if rv.get("xero_pl_period") is not None and xero_rev is not None \
            and not _close(rv["xero_pl_period"], xero_rev):
        errors.append("revenue_views.xero_pl_period != xero.revenue")

    # 7. No NaN / Infinity anywhere.
    errors.extend(_walk_json_unsafe(snapshot))

    return errors


def assert_consistency(snapshot: dict) -> None:
    errors = check_consistency(snapshot)
    if errors:
        raise ConsistencyError(
            "Snapshot would display contradictory numbers:\n  - " + "\n  - ".join(errors)
        )
