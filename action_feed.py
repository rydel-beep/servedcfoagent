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
            sev = {"failed": "S1", "past_due": "S1", "hire_trigger": "S2",
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

    # 3) Paid-but-unlogged (Stripe reconciliation) — real money not on the tracker
    sr = snap.get("stripe_reconciliation") or {}
    for p in (sr.get("paid_missing_from_tracker") or [])[:10]:
        items.append({"severity": "S2", "category": "reconciliation",
                      "title": f"Stripe payment not on the tracker: {str(p)[:80]}",
                      "action": "Log this payment against its deal in the tracker."})

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
