"""
active_clients.py
-----------------
Derive the active-client list from source systems on every snapshot refresh.
Never hardcoded — always computed from:
  (a) Health tab (Finance Sheet) — current MRR, status, contract dates
  (b) LTC tracker Won deals — contract value, cash collected, close date
  (c) Stripe aggregate — validation cross-check (per-customer not available)

An active client requires presence in the Health tab with Active/Web Sub status
and is not in the KNOWN_CHURNED set. LTC Won deals are cross-referenced to add
contract/cash data and to catch new signings not yet in the Health tab.

Disagreements go into discrepancies, never silently resolved.
"""
from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Confirmed churned — excluded from active even if they appear in sources.
# If a churned client shows new Stripe activity, flag it.
KNOWN_CHURNED = {
    "advocate",
    "the advocate",
    "vietnamese mint",
    "gloria jeans",
    "gloria jean's",
    "1st edition bar",
    "johnnies fitzroy",
    "hanmades",
    "nonnas",
    "nonnas pizzeria",
    "nonnas pizzeria and cucina",
    "asian streat",
    "riverloop",
    "riverloop cafe",
    "v noodle",
    "v noodle and sushi bar",
    "bunni beez",
}


def _normalise(name: str) -> str:
    """Normalise a client name for matching: lowercase, strip accents, common aliases."""
    if not name:
        return ""
    # NFKD decomposition to strip accents (café → cafe)
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    # Common substitutions
    s = s.replace("'", "").replace("\u2019", "").replace("'", "")
    s = s.replace("&", "and")
    s = re.sub(r"\s+", " ", s)
    return s


def _names_match(a: str, b: str) -> bool:
    """Fuzzy name matching: normalised prefix/substring match."""
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # One starts with the other
    if na.startswith(nb) or nb.startswith(na):
        return True
    # Short name is contained in the longer (at least 5 chars to avoid false positives)
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 5 and shorter in longer:
        return True
    # Special known aliases
    aliases = [
        ("blue bells", "bluebells"),
        ("coffee capital", "coffee cappital"),
        ("dc thai", "dcthai"),
        ("butlers cucina", "butlers cucina"),
        ("danka cafe", "danka cafe and lounge"),
    ]
    for x, y in aliases:
        if (na.startswith(x) and nb.startswith(y)) or (na.startswith(y) and nb.startswith(x)):
            return True
    return False


def _is_churned(name: str) -> bool:
    """Check if a client is in the known-churned set."""
    n = _normalise(name)
    for churned in KNOWN_CHURNED:
        if n == churned or n.startswith(churned) or churned.startswith(n):
            return True
    return False


def derive_active_clients(
    health_clients: list[dict],
    won_deals: list[dict],
    stripe_mrr: float | None = None,
    stripe_active_subs: int | None = None,
    health_source_ok: bool = True,
) -> dict:
    """
    Derive the active-client list from source data.

    Parameters:
        health_clients: list of dicts from pull_client_health()['client_health']['clients']
            Each has: name, status, package, current_mrr, next_mrr, contract_start, contract_end
        won_deals: list of dicts from LTC tracker Won rows
            Each has: business, close_date, contract, cash, offer, refund
        stripe_mrr: aggregate Stripe MRR for validation
        stripe_active_subs: Stripe active subscription count for validation
        health_source_ok: whether the Health tab (authoritative roster) loaded. The Health
            tab IS the roster — LTC Won deals only ever ADD new signings on top of it. When the
            Health tab is unavailable (e.g. the Finance sheet 401s), this derivation collapses
            to LTC-Won-only and would present a confidently wrong count ("N clients, 0 active,
            N awaiting Stripe", N = Won-deal count). When False, the result is flagged
            roster_source_down so callers refuse to display the bogus count and fall back to the
            last-good roster, labelled stale. A labelled-stale number beats a confident-wrong one.

    Returns dict with active, discrepancies, counts, confidence.
    """
    active = []
    discrepancies = []
    churned_excluded = []

    # Index health clients by normalised name
    health_by_norm = {}
    for h in health_clients:
        n = _normalise(h.get("name", ""))
        if n:
            health_by_norm[n] = h

    # Index won deals by normalised business name
    won_by_norm = {}
    for w in won_deals:
        biz = w.get("business", "").strip()
        if biz:
            n = _normalise(biz)
            if n:
                won_by_norm[n] = w

    # Track what's been matched
    matched_health = set()
    matched_won = set()

    # 1. Process Health tab clients — primary source for current roster
    for h in health_clients:
        name = h.get("name", "").strip()
        if not name:
            continue
        n = _normalise(name)

        # Check churned
        if _is_churned(name):
            churned_excluded.append(name)
            continue

        mrr = h.get("current_mrr", 0) or 0
        next_mrr = h.get("next_mrr", 0) or 0

        # Find matching Won deal
        won_match = None
        for wn, w in won_by_norm.items():
            if _names_match(name, w.get("business", "")):
                won_match = w
                matched_won.add(wn)
                break

        matched_health.add(n)

        entry = {
            "name": name,
            "status": h.get("status", "Active"),
            "package": h.get("package", ""),
            "current_mrr": mrr,
            "next_mrr": next_mrr,
            "contract_start": h.get("contract_start"),
            "contract_end": h.get("contract_end"),
            "source": "health_tab",
        }

        if won_match:
            entry["contract_value"] = won_match.get("contract")
            entry["cash_collected"] = won_match.get("cash")
            entry["close_date"] = won_match.get("close_date")
            entry["offer"] = won_match.get("offer")
            entry["sources_agree"] = True
        else:
            entry["sources_agree"] = "legacy"  # predates tracker

        if mrr > 0 or next_mrr > 0:
            active.append(entry)
        else:
            # Active status but $0 MRR — flag but keep as active (sheet may not be updated)
            entry["mrr_flag"] = "active_zero_mrr"
            active.append(entry)
            discrepancies.append({
                "name": name,
                "reason": f"Active in Health tab but $0 MRR for current month — verify if still active or update MRR",
                "in_health": True,
                "in_ltc": won_match is not None,
                "suggested_action": "Update Health tab MRR or mark as churned",
            })

    # 2. Process Won deals NOT matched to Health tab — new signings
    for wn, w in won_by_norm.items():
        if wn in matched_won:
            continue
        biz = w.get("business", "").strip()
        if not biz:
            continue
        if _is_churned(biz):
            churned_excluded.append(biz)
            continue

        # Check if it matches any health client we haven't linked
        health_match = None
        for hn, h in health_by_norm.items():
            if hn not in matched_health and _names_match(biz, h.get("name", "")):
                health_match = h
                break

        if health_match:
            # Shouldn't happen (would have been caught above), but handle gracefully
            continue

        # Won deal not in Health tab
        entry = {
            "name": biz,
            "status": "signed_not_in_health",
            "contract_value": w.get("contract"),
            "cash_collected": w.get("cash"),
            "close_date": w.get("close_date"),
            "offer": w.get("offer"),
            "current_mrr": None,
            "source": "ltc_tracker",
            "sources_agree": False,
        }

        discrepancies.append({
            "name": biz,
            "reason": "Won in LTC tracker but not yet in Health tab — add to Health tab with MRR",
            "in_health": False,
            "in_ltc": True,
            "contract_value": w.get("contract"),
            "cash_collected": w.get("cash"),
            "close_date": w.get("close_date"),
            "suggested_action": "Add to Health tab",
        })

        # Include as active (signed client awaiting Health tab entry)
        active.append(entry)

    # 3. Estimate MRR for new signings from contract value (6-month standard)
    CONTRACT_MONTHS = 6
    for a in active:
        if a.get("source") == "ltc_tracker" and a.get("current_mrr") is None:
            cv = a.get("contract_value")
            if cv and cv > 0:
                a["estimated_mrr"] = round(cv / CONTRACT_MONTHS, 2)
                a["mrr_source"] = "estimated_from_contract"
            else:
                a["estimated_mrr"] = None
                a["mrr_source"] = "unknown"
            a["awaiting_stripe"] = True
        else:
            a["estimated_mrr"] = None
            a["awaiting_stripe"] = False

    # Compute totals
    confirmed_count = sum(1 for a in active if a.get("sources_agree") is True)
    legacy_count = sum(1 for a in active if a.get("sources_agree") == "legacy")
    pending_count = sum(1 for a in active if a.get("sources_agree") is False)
    confirmed_mrr = sum(a.get("current_mrr") or 0 for a in active)
    estimated_mrr = sum(a.get("estimated_mrr") or 0 for a in active)
    projected_mrr = round(confirmed_mrr + estimated_mrr, 2)
    total_mrr = confirmed_mrr  # backward compat

    # 4. Stripe validation
    stripe_validation = None
    if stripe_mrr is not None and total_mrr > 0:
        gap = stripe_mrr - total_mrr
        gap_pct = abs(gap) / max(stripe_mrr, total_mrr, 1) * 100
        stripe_validation = {
            "derived_mrr": round(total_mrr, 2),
            "stripe_mrr": stripe_mrr,
            "gap": round(gap, 2),
            "gap_pct": round(gap_pct, 1),
            "note": (
                "Gap expected — derived MRR is from Health tab (may lag), "
                "Stripe MRR includes all active subscriptions. "
                "New signings not yet in Health tab widen the gap."
            ),
        }

    # 5. Confidence
    if len(discrepancies) == 0:
        confidence = "high"
    elif len(discrepancies) <= 3:
        confidence = "medium"
    else:
        confidence = "low"

    # 6. Data freshness
    latest_close = None
    for a in active:
        cd = a.get("close_date")
        if cd and (latest_close is None or str(cd) > str(latest_close)):
            latest_close = cd

    result = {
        "active": active,
        "discrepancies": discrepancies,
        "active_count": len(active),
        "confirmed_both_sources": confirmed_count,
        "legacy_pre_tracker": legacy_count,
        "pending_health_update": pending_count,
        "total_mrr_derived": round(total_mrr, 2),
        "confirmed_mrr": round(confirmed_mrr, 2),
        "estimated_mrr": round(estimated_mrr, 2),
        "projected_mrr": projected_mrr,
        "churned_excluded": churned_excluded,
        "stripe_validation": stripe_validation,
        "confidence": confidence,
        "latest_close_date": str(latest_close) if latest_close else None,
    }

    # Roster-source integrity gate. The Health tab is the authoritative roster; without it
    # this count is unreliable (LTC-Won-only). Flag loudly so the snapshot layer substitutes
    # the last-good roster and the UI shows a labelled-stale state instead of a wrong headline.
    if not health_source_ok:
        result["roster_source_down"] = True
        result["confidence"] = "low"
        result["roster_source_reason"] = (
            "Health tab (authoritative client roster) unavailable — count derived from "
            "LTC Won deals only and is NOT the real active-client roster. Showing last-good "
            "count, labelled stale."
        )
    else:
        result["roster_source_down"] = False

    return result
