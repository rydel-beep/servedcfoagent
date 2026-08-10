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
                   "threshold": "S2", "close": "S3", "payout": "S3", "lead": "S3",
                   "bas_due": "S1", "bas_anomaly": "S2"}.get(e["type"], "S3")
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
        # the ads-truth sweep's own channel (rebuilt per run → self-retiring):
        # close-level/≥$1k findings are DECISIONS; the rest is tracker hygiene
        for f in (kv_store.get("ads_truth:flags") or []):
            if f.get("metric") in ("ads_truth_action", "ads_truth_sweep_down"):
                items.append({"severity": "S1", "category": "ads_truth",
                              "title": (f.get("reason") or "")[:140],
                              "action": "Review — a close-level fact failed the truth sweep."})
            else:
                items.append({"severity": "S3", "category": "data_quality",
                              "title": (f.get("reason") or f.get("metric") or "")[:140],
                              "action": "Fix at source in the Lead-to-Cash tracker."})
    except Exception as e:
        logger.info("action_feed attribution flags failed: %s", e)

    # 2c) Close-integrity disagreements (kv matrix, daily) — data_quality → PIOLO'S QUEUE.
    # Self-retiring: the matrix recomputes daily; fixed rows drop off.
    try:
        import kv_store
        mx = kv_store.get("integrity:matrix") or {}
        for d in (mx.get("disagreements") or [])[:20]:
            item = {"severity": f"S{d.get('severity', 3)}", "category": "data_quality",
                    "title": (d.get("detail") or "")[:140],
                    "action": (d.get("fix") or "")[:140]}
            # FEED↔TABLE LOOP: object-referencing items deep-link to the deal panel
            if d.get("deal_name"):
                item["link"] = "/ads?deal=" + __import__("urllib.parse", fromlist=["quote"]).quote(d["deal_name"])
            items.append(item)
    except Exception as e:
        logger.info("action_feed integrity items failed: %s", e)

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

    # PENDING-SHEET declarations + renewal-loop findings (#135): these ARE the
    # Piolo queue items (category data_quality → collab.queue) carrying the
    # EXACT sheet edit; they self-retire when a scan finds the sheet matching.
    try:
        import renewal_loop
        items.extend(renewal_loop.feed_items())
    except Exception as e:
        logger.info("renewal feed items unavailable: %s", e)

    # EXTRA-CHANNEL REGISTRY: fixed kv channels other modules publish through
    # (each key is owned by exactly ONE publisher, replaced wholesale per
    # publish — self-retiring per channel, no read-modify-write races).
    _EXTRA_CHANNELS = ("feed:extra:ads_discussion", "feed:extra:voice")
    try:
        import kv_store
        for ch_key in _EXTRA_CHANNELS:
            for it in (kv_store.get(ch_key) or []):
                if isinstance(it, dict) and it.get("title"):
                    items.append({"severity": it.get("severity", "S3"),
                                  "category": it.get("category", "info"),
                                  "title": str(it["title"])[:160],
                                  "action": str(it.get("action") or "")[:240]})
    except Exception as e:
        logger.info("extra feed channels unavailable: %s", e)

    # rank S1 > S2 > S3, dedupe by FACT KEY (prefix-stripped — kills the
    # data_quality/data_integrity double-emit that flooded the zone to 72 lines)
    import triage
    order = {"S1": 0, "S2": 1, "S3": 2}
    seen, ranked = set(), []
    for it in sorted(items, key=lambda x: order.get(x["severity"], 3)):
        key = triage.fact_key(it["title"])
        if key not in seen:
            seen.add(key)
            it["key"] = key
            ranked.append(it)

    counts = {"S1": 0, "S2": 0, "S3": 0}
    for it in ranked:
        counts[it["severity"]] = counts.get(it["severity"], 0) + 1

    # THE FIVE LANES (ACTION_TRIAGE_REPORT, Rydel-confirmed): the zone renders
    # lanes; `items` stays the full raw ranked list (compat + the audit trail).
    routed = triage.route(ranked)
    lanes = routed["lanes"]
    return {"available": True, "items": ranked, "counts": counts,
            "lanes": lanes, "cap": routed["cap"], "floor": routed["floor"],
            "suppressed_count": routed["suppressed_count"],
            "routed_count": routed["routed_count"],
            "headline": _headline_lanes(lanes),
            "generated_from": "salience + degraded + reconciliation → five-lane triage"}


def _headline_lanes(lanes: dict) -> str:
    n = len(lanes.get("action") or [])
    d = len(lanes.get("delegated") or [])
    if n:
        return (f"{n} decision{'s' if n != 1 else ''} for you"
                + (f" · {d} with the team" if d else "") + ".")
    if d:
        return f"Nothing for you to decide — {d} item{'s' if d != 1 else ''} with the team."
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
    lanes = feed.get("lanes") or {}
    acts = lanes.get("action") or []
    dels = lanes.get("delegated") or []
    if not acts and not dels:
        return "All clear — nothing needs your decision right now.", True
    lines = [feed["headline"]]
    for it in acts[:feed.get("cap", 7)]:
        why = it.get("why")
        lines.append(f"• {it['title']}" + (f" — {why}" if why and why != it["title"] else ""))
    for r in dels[:3]:
        lines.append(f"◦ [with {r.get('owner', 'team')}] {r['title']}")
    if feed.get("suppressed_count") or feed.get("routed_count"):
        lines.append(f"({feed.get('routed_count', 0)} item(s) routed off this list — "
                     f"ask me to show you what I suppressed.)")
    return "\n".join(lines), True
