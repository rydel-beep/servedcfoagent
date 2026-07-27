"""
quarterly_pack.py
-----------------
The QUARTER DATA PACK — one window, one engine. Assembles every figure a quarterly review needs
for a single [start,end] window, drawing ONLY from the canonical deterministic engines so a PDF
number always equals the dashboard number for the same window (the one-engine rule).

HONESTY DISCIPLINE (see the work order + CLAUDE.md):
- Every figure is sourced from range_unit_economics / xero_pull / the tracker mirror / the roster.
  Nothing is invented, extrapolated, or round-drifted here. Where a source has no history for the
  window, the section is marked available:false with a plain-language reason — never faked.
- Unit economics come verbatim from range_unit_economics.unit_economics() (the same engine the
  dashboard window buttons and EDITH's spoken answers use).
- Xero revenue is P&L-RECOGNIZED (labelled), Stripe/new-deal figures are CASH (labelled). The two
  are never summed.

Calendar quarters (Rydel's call 2026-07-21): Q1 Jan–Mar, Q2 Apr–Jun, Q3 Jul–Sep, Q4 Oct–Dec.
"""
from __future__ import annotations

import calendar
import datetime as dt
import logging

from helpers import today_sydney

logger = logging.getLogger(__name__)


# ── Quarter boundaries (calendar) ────────────────────────────────────────────

def quarter_bounds(year: int, q: int) -> tuple[dt.date, dt.date]:
    """[start,end] dates for calendar quarter q of `year` (inclusive)."""
    if q not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1-4, got {q}")
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    start = dt.date(year, start_month, 1)
    end = dt.date(year, end_month, calendar.monthrange(year, end_month)[1])
    return start, end


def quarter_label(year: int, q: int) -> str:
    return f"Q{q} {year}"


def current_quarter(today: dt.date | None = None) -> tuple[int, int]:
    today = today or today_sydney()
    return today.year, (today.month - 1) // 3 + 1


def last_completed_quarter(today: dt.date | None = None) -> tuple[int, int]:
    """The most recent quarter that has fully ended (the default review period)."""
    today = today or today_sydney()
    y, q = current_quarter(today)
    q -= 1
    if q == 0:
        q, y = 4, y - 1
    return y, q


def prev_quarter(year: int, q: int) -> tuple[int, int]:
    q -= 1
    if q == 0:
        q, year = 4, year - 1
    return year, q


def _months_in_quarter(year: int, q: int) -> list[tuple[int, int]]:
    start_month = (q - 1) * 3 + 1
    return [(year, start_month + i) for i in range(3)]


# ── The pack ─────────────────────────────────────────────────────────────────

def quarter_pack(year: int, q: int) -> dict:
    """Assemble the full data pack for calendar quarter q of `year`. Window-consistent by
    construction: one (start,end) drives every engine call."""
    start, end = quarter_bounds(year, q)
    today = today_sydney()
    is_partial = end > today          # quarter not finished yet (current quarter-to-date)
    eff_end = min(end, today)
    label = quarter_label(year, q)
    days = (eff_end - start).days + 1

    pack: dict = {
        "label": label, "year": year, "quarter": q,
        "window": {"start": str(start), "end": str(eff_end), "nominal_end": str(end),
                   "days": days, "partial": is_partial},
        "generated_at": today_sydney().isoformat(),
    }

    # 1) UNIT ECONOMICS + the money view (contracted / new-deal cash / CAC / ratios) — verbatim
    #    from the canonical range engine. THIS is the source that must match the dashboard.
    ue = _unit_economics(str(start), str(eff_end))
    pack["unit_economics"] = ue
    comp = (ue or {}).get("components", {}) if isinstance(ue, dict) else {}

    # 2) REVENUE & CASH
    pack["revenue_cash"] = {
        "contracted_revenue": comp.get("contract_value_total"),
        "contracted_basis": "closes x contract value, by Close Date (tracker)",
        "new_deal_cash_collected": comp.get("cash_collected_total"),
        "cash_basis": "Stripe cash matched to in-window closes (cash-truth)",
        "avg_contract": comp.get("avg_contract"),
        "gross_margin_pct": comp.get("gross_margin_pct"),
        "xero_revenue": _xero_revenue(str(start), str(eff_end)),
        "mrr_bridge": _mrr_bridge(start, eff_end, is_partial),
    }

    # 3) SALES ENGINE — funnel + by-month velocity (cohort by lead Input Date)
    pack["sales"] = _sales(start, eff_end, year, q)

    # 4) COSTS — ad spend (labelled source), commissions (in-window), plus current burn context
    pack["costs"] = {
        "ad_spend": comp.get("ad_spend"),
        "ad_spend_source": comp.get("ad_spend_source"),
        "ad_spend_label": comp.get("ad_spend_label"),
        "closer_comm": comp.get("closer_comm"),
        "setter_comm": comp.get("setter_comm"),
        "cac_loaded": comp.get("cac_loaded"),
        "cac_breakdown": comp.get("cac_breakdown"),
        "monthly_burn_context": _burn_context(),
    }

    # 5) CHURN & RETENTION
    pack["churn"] = _churn(start, eff_end)

    # 6) EVENTS — factual timeline from the journal/archive (hires, incidents, integrations)
    pack["events"] = _events(start, eff_end)

    return pack


# ── Section builders (each degrades honestly) ────────────────────────────────

def _unit_economics(start: str, end: str) -> dict:
    try:
        import range_unit_economics
        return range_unit_economics.unit_economics(start, end)
    except Exception as e:
        logger.exception("quarter_pack unit_economics failed")
        return {"available": False, "reason": f"unit-economics engine error: {e}"}


def _xero_revenue(start: str, end: str) -> dict:
    try:
        import xero_pull
        r = xero_pull.pull_pl_range(start, end)
        if not r.get("ok"):
            return {"available": False, "reason": r.get("reason", "Xero range unavailable"),
                    "basis": "P&L recognized (Xero)"}
        return {"available": True, "revenue": r.get("revenue"), "cogs": r.get("cogs"),
                "gross_profit": r.get("gross_profit"), "gross_margin_pct": r.get("gross_margin_pct"),
                "operating_expenses": r.get("operating_expenses"), "net_profit": r.get("net_profit"),
                "opex_line_items": r.get("opex_line_items") or [],   # per-line, for the opex bridge (G2)
                "basis": "P&L recognized (Xero), not cash"}
    except Exception as e:
        logger.exception("quarter_pack xero revenue failed")
        return {"available": False, "reason": f"Xero pull error: {e}", "basis": "P&L recognized (Xero)"}


def _mrr_bridge(start: dt.date, end: dt.date, is_partial: bool) -> dict:
    """Opening + new + expansion - churn = closing. Closing MRR is only truly known for the
    just-ended (or current) quarter via the live roster; historical opening MRR is not snapshotted,
    so for older quarters the bridge is marked partial. New MRR is derived from closes-in-window
    cross-referenced to the roster's per-client MRR. No fabrication — unknown legs are stated."""
    try:
        import closes_view
        from snapshot import load_persisted
        snap = load_persisted() or {}
        health = (snap.get("client_health") or {})
        roster = health.get("clients") or []
        closing_mrr = health.get("current_mrr")

        # roster name -> current mrr (best-effort join for new-MRR attribution)
        by_name = {}
        for c in roster:
            nm = str(c.get("name") or c.get("business") or "").strip().lower()
            if nm:
                by_name[nm] = c.get("current_mrr") or c.get("mrr")

        closes = closes_view.count_closes(start, end)
        new_mrr = 0.0
        matched = 0
        for d in (closes_view._won_deals() if hasattr(closes_view, "_won_deals") else []):
            cd = d.get("close_date")
            try:
                cdd = dt.date.fromisoformat(str(cd)[:10])
            except Exception:
                continue
            if not (start <= cdd <= end):
                continue
            nm = str(d.get("business") or d.get("name") or "").strip().lower()
            m = by_name.get(nm)
            if m:
                new_mrr += float(m); matched += 1

        # churn MRR from the forward-MRR engine (clients recognized as churning)
        churn_mrr = None
        try:
            fm = snap.get("forward_mrr") or {}
            churn_mrr = fm.get("churn_mrr")
        except Exception:
            pass

        # Only claim a fully-reconciled bridge when closing is trustworthy (current/just-ended Q)
        recent = (today_sydney() - end).days <= 100
        return {
            "available": True,
            "closing_mrr": closing_mrr if recent else None,
            "closing_basis": "live roster current MRR" if recent else None,
            "new_mrr_added": round(new_mrr, 2) if matched else None,
            "new_mrr_matched_deals": matched,
            "new_mrr_total_closes": closes,
            "churn_mrr": churn_mrr,
            "partial": (not recent) or (matched < closes),
            "note": ("New MRR is the sum of roster MRR for in-window closes matched by name "
                     f"({matched}/{closes} closes matched). Opening MRR is not snapshotted "
                     "historically, so the full opening->closing bridge is shown where the "
                     "quarter is recent; older quarters show the derivable legs only."),
        }
    except Exception as e:
        logger.exception("quarter_pack mrr bridge failed")
        return {"available": False, "reason": f"MRR bridge error: {e}"}


def _sales(start: dt.date, end: dt.date, year: int, q: int) -> dict:
    out: dict = {"available": True}
    try:
        import range_unit_economics
        funnel = range_unit_economics.cohort_funnel(start, end)
        out["funnel"] = funnel
    except Exception as e:
        out["funnel"] = {"available": False, "reason": str(e)}
    try:
        import closes_view
        import leads_view
        out["closes"] = closes_view.count_closes(start, end)
        lc = leads_view.count_leads(start, end)
        out["leads"] = lc.get("count") if isinstance(lc, dict) else lc
    except Exception as e:
        out["closes_leads_error"] = str(e)
    # by-month velocity within the quarter
    months = []
    try:
        import closes_view
        import leads_view
        for (my, mm) in _months_in_quarter(year, q):
            ms = dt.date(my, mm, 1)
            me = dt.date(my, mm, calendar.monthrange(my, mm)[1])
            today = today_sydney()
            if ms > today:
                continue
            me = min(me, today)
            lc = leads_view.count_leads(ms, me)
            months.append({
                "month": ms.strftime("%b %Y"),
                "leads": lc.get("count") if isinstance(lc, dict) else lc,
                "closes": closes_view.count_closes(ms, me),
            })
    except Exception as e:
        out["by_month_error"] = str(e)
    out["by_month"] = months
    # LEAD-LAG signal (G4): closes trail leads by ~1-2 months, so month-end lead velocity is a
    # LEADING indicator. If the last in-quarter month's leads fell materially MoM, flag next-quarter
    # close-risk automatically.
    out["lead_lag"] = _lead_lag_signal(months)
    return out


def _lead_lag_signal(months: list[dict]) -> dict:
    """Leading-indicator warning: a MoM drop in the final month's lead volume foreshadows a
    close-rate dip 1-2 months out (into the next quarter)."""
    vol = [(m.get("month"), m.get("leads")) for m in (months or []) if isinstance(m.get("leads"), int)]
    if len(vol) < 2:
        return {"warning": False, "reason": "need >=2 months of lead velocity"}
    (pm, pv), (lm, lv) = vol[-2], vol[-1]
    if not pv:
        return {"warning": False}
    mom = round((lv - pv) / pv * 100, 1)
    warn = mom <= -10
    return {"warning": warn, "last_month": lm, "last_leads": lv, "prev_month": pm, "prev_leads": pv,
            "mom_pct": mom, "basis": "closes trail leads ~1-2 months",
            "message": (f"Leading-indicator warning: {lm} leads {lv} ({mom:+.0f}% MoM vs {pm}'s {pv}) — "
                        "closes trail leads by 1-2 months, so this foreshadows next-quarter close risk. "
                        "Refill the top of funnel now." if warn else
                        f"{lm} lead velocity {lv} ({mom:+.0f}% MoM) — no leading-indicator warning.")}


def _burn_context() -> dict:
    """Current monthly burn (context only — burn is a run-rate, not a windowed total). Labelled
    as current-snapshot so it's never mistaken for a quarter sum."""
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        mb = snap.get("monthly_burn") or {}
        return {
            "available": True,
            "as_of": "current snapshot (run-rate, not a quarter total)",
            "total_recurring_burn_monthly": mb.get("total_recurring_burn"),
            "team": mb.get("team"), "owner_pay": mb.get("owner_pay"),
            "ad_spend_monthly": mb.get("ad_spend"), "subscriptions": mb.get("subscriptions"),
            "other_opex": mb.get("other_opex"),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}


def _churn(start: dt.date, end: dt.date) -> dict:
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        ac = snap.get("active_clients") or {}
        fm = snap.get("forward_mrr") or {}
        return {
            "available": True,
            "active_clients_current": ac.get("active_count"),
            "churn_clients_forward": fm.get("churn_clients"),
            "churn_mrr_forward": fm.get("churn_mrr"),
            "basis": ("active-client count is the current derived roster; churn is the forward-MRR "
                      "engine's recognized churn. Per-quarter start->end client delta needs "
                      "historical roster snapshots (stated where unavailable)."),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}


def _events(start: dt.date, end: dt.date) -> list[dict]:
    """Factual quarter timeline from the collaboration journal + incident log (append-only)."""
    events: list[dict] = []
    try:
        import collab
        rows = collab.journal(start=str(start), end=str(end), role="owner", limit=200)
        for r in (rows or []):
            events.append({"date": str(r.get("at") or "")[:10],
                           "source": r.get("source"), "who": r.get("who"),
                           "text": (r.get("text") or "")[:200]})
    except Exception as e:
        logger.info("quarter_pack events (journal) unavailable: %s", e)
    return events[:40]
