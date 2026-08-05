"""
action_feed.py
--------------
ZONE 3 "what needs action" — ONE consolidated, prioritised feed, replacing the scattered warnings
the audit found (dq-loss, verdicts, stripe-health, actions, reconciliation all carried alerts
separately). Aggregates: salience events (money at risk, closes, hire triggers…), data-quality
flags from the snapshot's degraded[], and roster/reconciliation gaps — deduped, ranked by severity,
each with a plain-language action. Deterministic; owner-only surface (behind dashboard auth).

Written to the SKILL.md's copy guidance: name things by what Rydel controls, say what to do, never
apologise, never vague. Each item = {severity, category, title, action}.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Data-quality flags worth an action, mapped to plain-language "what to do".
_DQ_ACTIONS = {
    "client_reconciliation": "Add the won deals to the Health roster so MRR + client count include them.",
    "zero_mrr_active_clients": "Set MRR or mark churned for the Active clients showing $0.",
    "setter_commission": "Fill the blank setter-commission cells in the tracker.",
    "closer_commission": "Fill the blank closer-commission cells in the tracker.",
    "funnel_cross_check": "Funnel counts disagree between sources — verify the tracker.",
    "stripe_mrr_subs_mismatch": "Stripe subscription data looks off — verify in Stripe directly.",
}
_DQ_SEVERITY = {"client_reconciliation": "S2", "zero_mrr_active_clients": "S2",
                "setter_commission": "S3", "closer_commission": "S3",
                "funnel_cross_check": "S2", "stripe_mrr_subs_mismatch": "S2"}


def build_action_feed(snap: dict | None = None, include_owner: bool = True) -> dict:
    """The consolidated action feed — salience + data-quality + roster gaps, ranked. Deterministic."""
    from snapshot import load_persisted
    snap = snap or load_persisted() or {}
    items: list[dict] = []

    # 1) Salience events (money at risk, closes, payouts, hire triggers, leads) — already deterministic
    try:
        import salience
        for e in salience.collect(snap):
            sev = {"failed": "S1", "past_due": "S1", "hire_trigger": "S2", "unlogged": "S2",
                   "threshold": "S2", "close": "S3", "payout": "S3", "lead": "S3"}.get(e["type"], "S3")
            items.append({"severity": sev, "category": e["type"], "title": e["spoken"],
                          "action": "Review." if sev in ("S1", "S2") else None})
    except Exception as e:
        logger.info("action_feed salience failed: %s", e)

    # 2) Data-quality flags from the snapshot's degraded[] — the audit found these scattered
    for d in (snap.get("degraded") or []):
        metric = (d or {}).get("metric") or ""
        if metric in _DQ_ACTIONS:
            items.append({"severity": _DQ_SEVERITY.get(metric, "S3"), "category": "data_quality",
                          "title": (d.get("reason") or metric)[:140], "action": _DQ_ACTIONS[metric]})

    # 2b) Attribution engine data-quality flags (kv-published, zero network here) —
    # e.g. duplicate won rows in the tracker. Category data_quality → PIOLO'S QUEUE.
    # Self-retiring: the engine overwrites the list each compute; clean source = empty.
    try:
        import kv_store
        for f in (kv_store.get("attr:data_quality_flags") or []):
            items.append({"severity": "S3", "category": "data_quality",
                          "title": (f.get("reason") or f.get("metric") or "")[:140],
                          "action": "Fix the row at source in the Lead-to-Cash tracker."})
    except Exception as e:
        logger.info("action_feed attribution flags failed: %s", e)

    # 3) UNRECOGNISED Stripe payments — only genuine anomalies after multi-signal matching
    # (existing-client repeats + payer≠business auto-resolve and are NOT surfaced here).
    sr = snap.get("stripe_reconciliation") or {}
    for p in (sr.get("paid_missing_from_tracker") or [])[:10]:
        who = p.get("customer", "a payer") if isinstance(p, dict) else str(p)[:40]
        amt = p.get("amount") if isinstance(p, dict) else None
        items.append({"severity": "S2", "category": "reconciliation",
                      "title": f"Unrecognised Stripe payment: {who}" + (f" (${amt:,.0f})" if amt else ""),
                      "action": f"Tell me who they are (“{who} is <client>”) and I'll remember it."})
    for p in (sr.get("needs_review") or [])[:5]:
        sug = (p.get("suggested") or [{}])[0].get("business", "?")
        items.append({"severity": "S3", "category": "reconciliation",
                      "title": f"Confirm payer: {p.get('customer', '?')} → likely {sug}?",
                      "action": "Say “yes” or correct me and I'll link it."})

    # 3b) NEEDS LOGGING (cash_truth) — the deal row exists but its cash cell trails Stripe.
    # Persists in the feed until the team logs it (unlike the once-only salience event).
    # EDITH nudges; the TEAM logs — cash cells are never auto-written.
    ct = snap.get("cash_truth") or {}
    for n in (ct.get("needs_logging") or [])[:10]:
        items.append({"severity": "S2", "category": "needs_logging",
                      "title": (f"Needs logging: {n.get('business')} — Stripe "
                                f"${(n.get('stripe_total') or 0):,.0f} vs tracker "
                                f"{n.get('tracker_logged')} (gap ${(n.get('gap') or 0):,.0f})"),
                      "action": "Verify in Stripe and update the deal's Cash Collected cell."})

    # rank S1 > S2 > S3, dedupe by title
    order = {"S1": 0, "S2": 1, "S3": 2}
    seen, ranked = set(), []
    for it in sorted(items, key=lambda x: order.get(x["severity"], 3)):
        key = it["title"][:60]
        if key not in seen:
            seen.add(key)
            ranked.append(it)

    counts = {"S1": 0, "S2": 0, "S3": 0}
    for it in ranked:
        counts[it["severity"]] = counts.get(it["severity"], 0) + 1
    return {"available": True, "items": ranked, "counts": counts,
            "headline": _headline(counts), "generated_from": "salience + degraded + reconciliation"}


def _headline(counts: dict) -> str:
    if counts.get("S1"):
        return f"{counts['S1']} thing{'s' if counts['S1'] != 1 else ''} need attention now."
    if counts.get("S2"):
        return f"{counts['S2']} item{'s' if counts['S2'] != 1 else ''} to sort out."
    if counts.get("S3"):
        return "Nothing urgent — a few things to keep an eye on."
    return "All clear — nothing needs action."


def handle_action_feed_command(text: str) -> tuple[str | None, bool]:
    """'what needs my attention' / 'action list' / 'what's on fire' → the consolidated feed."""
    import re
    if not text or not re.search(
            r"\bwhat needs (my )?(attention|action|doing|sorting)\b|\baction (feed|list|items)\b|"
            r"\bwhat'?s on fire\b|\bwhat should i (deal with|action|fix)\b|\bmy (to.?do|action list)\b|"
            r"\banything (urgent|on fire|to action)\b", text, re.I):
        return None, False
    feed = build_action_feed()
    items = feed["items"]
    if not items:
        return "All clear — nothing needs action right now.", True
    top = [it for it in items if it["severity"] in ("S1", "S2")][:5] or items[:3]
    lines = [f"• [{it['severity']}] {it['title']}" + (f" → {it['action']}" if it.get("action") else "")
             for it in top]
    return feed["headline"] + "\n" + "\n".join(lines), True
