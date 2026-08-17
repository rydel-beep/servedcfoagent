"""csm_baselines.py — Gate-0 baselines B1–B5 (placeholders → measurements).

Every figure carries {value, label: "measured {date}" | "placeholder" |
"partial", method, confidence, edge_cases}. Nothing is fabricated: a metric
the local stores can't support says so and keeps the source placeholder.

OWNER-ONLY consumer surface (/csm). Nothing here writes to any shared feed,
worklog, or snapshot key. No director comp figures exist in this module.

Sources (read-only): snapshot.load_persisted() (client_health +
active_clients + sales), client_overrides declarations, mrr_snapshots,
cash_truth Stripe refunds, xero_pull P&L line totals, timeline_adapter
bridge (DQS proxy inputs), kv (book ledger + tiers).
"""

from __future__ import annotations

import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_KV_LEDGER = "csm:book_ledger"
_KV_TIERS = "csm:tiers"
_KV_BASELINE_CACHE = "csm:baseline_cache"

# Package → default term months (used ONLY when the sheet has no dates;
# labelled "derived term" wherever it fires).
_PACKAGE_TERMS = {"growth pro": 6, "scale engine": 6, "cafe walk-ins": 3,
                  "cafe walkins": 3, "walk-in": 3, "web sub": 1}

# Source placeholders (the model's own, restated here for labelling)
PLACEHOLDERS = {"renewal_rate_pct": 40.0, "in_term_completion_pct": 85.0}


def _snap():
    try:
        from snapshot import load_persisted
        return load_persisted() or {}
    except Exception:
        return {}


def _known_churned() -> set:
    try:
        import active_clients
        return {c.lower() for c in active_clients.KNOWN_CHURNED}
    except Exception:
        return set()


def _term_months(client: dict) -> tuple[int | None, str]:
    """(months, basis). Sheet dates win; else package default (labelled)."""
    cs, ce = client.get("contract_start"), client.get("contract_end")
    if cs and ce:
        try:
            import datetime as dt
            d0 = dt.date.fromisoformat(str(cs)[:10])
            d1 = dt.date.fromisoformat(str(ce)[:10])
            return max(1, round((d1 - d0).days / 30.44)), "sheet dates"
        except ValueError:
            pass
    pkg = (client.get("package") or client.get("offer") or "").strip().lower()
    if pkg in _PACKAGE_TERMS:
        return _PACKAGE_TERMS[pkg], "derived term (package default)"
    return None, "unknown"


# ── B1 · renewal rate + in-term completion ──────────────────────────────────

def measure_renewal_rate(grace_days: int = 30, floor_share: float = 0.5) -> dict:
    """Term-length-aware trailing-12-month renewal rate. Cohort = clients
    whose term ENDED in the window; RENEWED = still in paid engagement within
    the grace window at >= floor_share of prior MRR (a renewal declaration
    counts as ID-exact evidence). Ambiguous → flagged, excluded, counted."""
    import datetime as dt
    today = today_sydney()
    w0 = today - dt.timedelta(days=365)
    snap = _snap()
    roster = ((snap.get("client_health") or {}).get("clients") or [])
    actives = ((snap.get("active_clients") or {}).get("active") or [])
    churned = _known_churned()
    active_names = {(c.get("name") or "").lower() for c in actives}

    # declarations are ID-exact evidence
    decls = {}
    try:
        import client_overrides
        for ov in client_overrides.active_overrides():
            decls.setdefault(client_overrides._norm(ov["client_name"]), []).append(ov)
        for nm, ov in (client_overrides.reconciled_recent(365) or {}).items():
            decls.setdefault(nm, []).append(ov)
    except Exception:
        pass

    # candidate universe: current roster + won-deal roster + KNOWN CHURNED.
    # The churned list is the anti-survivorship leg: without it every cohort
    # member is a survivor and the rate reads 100% — the first local run
    # caught exactly that.
    by_name: dict[str, dict] = {}
    won = ((snap.get("sales") or {}).get("won_businesses") or [])
    for c in actives + roster + [w for w in won if isinstance(w, dict)]:
        nm = (c.get("name") or "").strip()
        if nm:
            by_name.setdefault(nm.lower(), {}).update(
                {k: v for k, v in c.items() if v is not None})
    churned_undated = []
    for nm in sorted(churned):
        if nm in by_name:
            continue
        # churned client absent from every dated store — real non-renewals
        # whose term end can't be placed in the window. They bound the rate.
        churned_undated.append(nm)

    cohort, renewed, not_renewed, ambiguous = [], [], [], []
    for key, c in sorted(by_name.items()):
        term, basis = _term_months(c)
        end = c.get("contract_end")
        end_d = None
        if end:
            try:
                end_d = dt.date.fromisoformat(str(end)[:10])
            except ValueError:
                pass
        if end_d is None and c.get("close_date") and term:
            try:
                start = dt.date.fromisoformat(str(c["close_date"])[:10])
                import client_overrides as _co
                end_d = _co._add_months(start, term)
                basis += " + close_date start"
            except Exception:
                pass
        if end_d is None:
            ambiguous.append({"client": c.get("name"),
                              "why": "no term end derivable (no sheet dates, "
                                     "no close date + package term)"})
            continue
        if not (w0 <= end_d <= today):
            continue          # term didn't end in the window
        entry = {"client": c.get("name"), "term_end": str(end_d),
                 "term_months": term, "term_basis": basis}
        cohort.append(entry)
        nrm = "".join(ch for ch in key if ch.isalnum())
        client_decls = decls.get(nrm, [])
        kinds = {d.get("change_type") for d in client_decls}
        if "renewal" in kinds:
            entry["evidence"] = "renewal declaration (id-exact)"
            renewed.append(entry)
        elif "churn" in kinds or key in churned:
            entry["evidence"] = ("churn declaration" if "churn" in kinds
                                 else "known-churned list")
            not_renewed.append(entry)
        elif key in active_names:
            # still active past term end: renewed IF at >= floor share of MRR.
            # Prior MRR history isn't in the local stores → current-vs-current
            # is the proxy; a downsell declaration marks the floor case.
            if "downsell" in kinds:
                entry["evidence"] = "continuity declaration — NOT a renewal "
                entry["evidence"] += "(floor share rule)"
                not_renewed.append(entry)
            else:
                entry["evidence"] = ("still Active past term end (grace "
                                     f"{grace_days}d; floor-share check limited "
                                     "— prior-MRR history not stored)")
                renewed.append(entry)
        else:
            entry["why"] = "term ended, client absent from roster, no declaration"
            ambiguous.append(entry)

    n = len(renewed) + len(not_renewed)
    rate = round(100.0 * len(renewed) / n, 1) if n else None
    # SURVIVORSHIP BOUND: churned clients with no derivable term dates are
    # real non-renewals that can't be window-placed — the lower bound puts
    # them all in the trailing-12mo denominator, the upper bound none.
    n_low = n + len(churned_undated)
    rate_low = round(100.0 * len(renewed) / n_low, 1) if n_low else None
    # binomial-ish confidence half-width at 95% (honest about small n)
    half = round(196.0 * ((rate / 100 * (1 - rate / 100) / n) ** 0.5), 1) if n and rate is not None and 0 < rate < 100 else None
    return {
        "metric": "renewal_rate_pct",
        "value": rate,
        "lower_bound": rate_low,
        "bound_note": (f"{len(churned_undated)} known-churned clients have no "
                       "derivable term dates in the local stores — the true "
                       "trailing-12mo rate sits BETWEEN the bounds; treat the "
                       "point value as an upper estimate"
                       if churned_undated else None),
        "churned_undated": churned_undated[:20],
        "confidence_pm": half,
        "n_decided": n,
        "n_renewed": len(renewed),
        "n_not_renewed": len(not_renewed),
        "n_ambiguous": len(ambiguous),
        "label": (f"measured {today}"
                  + (" (bounded — survivorship-limited)" if churned_undated else "")
                  if rate is not None else "placeholder"),
        "placeholder": PLACEHOLDERS["renewal_rate_pct"],
        "method": ("term-length-aware: cohort = terms ended in trailing 12mo "
                   "(sheet dates; else close_date + package term, labelled); "
                   "renewed = declaration or still-Active past end within "
                   f"grace {grace_days}d at >= {int(floor_share*100)}% MRR "
                   "share (share check limited — prior-MRR history not "
                   "stored; downsell declarations excluded per the rule); "
                   "ambiguous flagged, excluded, counted"),
        "edge_cases": ambiguous[:20],
        "cohort": cohort[:60],
        "gaps": ["GHL opportunity-history cross-check not wired (the PDF's "
                 "full method) — registered dependency",
                 "historic per-client MRR pre-snapshot era unavailable"],
    }


def measure_in_term_completion() -> dict:
    """Share of contracted term revenue actually billed — cash_collected /
    contract_value on clients whose term has ENDED (both fields present)."""
    import datetime as dt
    today = today_sydney()
    snap = _snap()
    actives = ((snap.get("active_clients") or {}).get("active") or [])
    rows, skipped = [], 0
    for c in actives:
        cv = c.get("contract_value")
        cash = c.get("cash_collected")
        end = c.get("contract_end")
        if not (cv and cash and end):
            skipped += 1
            continue
        try:
            if dt.date.fromisoformat(str(end)[:10]) > today:
                continue        # term still running — completion undefined
        except ValueError:
            continue
        rows.append({"client": c.get("name"),
                     "completion_pct": round(100.0 * cash / cv, 1)})
    if rows:
        val = round(sum(r["completion_pct"] for r in rows) / len(rows), 1)
        return {"metric": "in_term_completion_pct", "value": val,
                "label": f"measured {today} (n={len(rows)})", "rows": rows,
                "placeholder": PLACEHOLDERS["in_term_completion_pct"],
                "method": "cash_collected / contract_value on ended terms "
                          "(LTC tracker via active-clients derivation)",
                "skipped_missing_fields": skipped}
    return {"metric": "in_term_completion_pct", "value": None,
            "label": "placeholder", "placeholder": PLACEHOLDERS["in_term_completion_pct"],
            "method": "no ended-term clients with both contract_value and "
                      "cash_collected in the stores — placeholder retained",
            "skipped_missing_fields": skipped}


# ── B2 · refund split ────────────────────────────────────────────────────────

def measure_refund_split(days: int = 365) -> dict:
    """The refunds line split into client refund / guarantee payout / ad
    rebate. Account-code-first: the ledger has ONE refunds account (P&L line
    total). Cause evidence: Stripe refunds (per-charge, client-named).
    Whatever cash the evidence can't attribute is FLAGGED, never guessed."""
    today = today_sydney()
    out = {"metric": "refund_split", "window_days": days,
           "owners": {"guarantee_payout": "sales qualification",
                      "client_refund": "client success (the CSM lever)",
                      "ad_rebate": "neither (pass-through)"},
           "method": ("account-first: Xero 'Refunds and Rebates Expense' P&L "
                      "line = the total; Stripe refund report = per-client "
                      "cash-refund evidence; ad rebates & guarantee payouts "
                      "need transaction-level Xero (not wired — registered "
                      "dependency); unattributed remainder FLAGGED")}
    total = None
    try:
        import datetime as dt
        import xero_pull
        start = str(today - dt.timedelta(days=days))
        pl = xero_pull.pull_pl_range(start, str(today))
        for line in (pl.get("opex_line_items") or []):
            # opex_line_items rows are {label, amount} (xero_pull
            # _extract_section_lines) — the first prod probe read a wrong key
            # and got 0.0; fixed + pinned by test
            if (line.get("label") or "").lower().startswith("refunds"):
                total = float(line.get("amount") or 0)
    except Exception as e:
        out["degraded"] = [f"xero P&L unreachable: {str(e)[:80]}"]
    stripe_refunds = None
    try:
        import cash_truth
        rr = cash_truth.refund_report(days)
        if rr:  # None = Stripe unreachable (never zero)
            stripe_refunds = {
                "total": rr.get("total_refunded"),
                "count": rr.get("count"),
                "clients": [r.get("customer")
                            for r in (rr.get("refunds") or [])][:20]}
    except Exception as e:
        out.setdefault("degraded", []).append(f"stripe refunds: {str(e)[:80]}")
    out["xero_line_total"] = total
    out["stripe_client_refunds"] = stripe_refunds
    attributed = (stripe_refunds or {}).get("total") or 0
    out["split"] = {
        "client_refund": {"value": attributed or None,
                          "basis": "Stripe per-charge refunds (cash back to "
                                   "client cards)" if attributed else "no evidence"},
        "guarantee_payout": {"value": None, "basis": "flagged — needs "
                             "transaction-level Xero payee/reference read"},
        "ad_rebate": {"value": None, "basis": "flagged — needs transaction-"
                      "level Xero payee/reference read"},
        "unattributed": {"value": (round(total - attributed, 2)
                                   if total is not None else None),
                         "basis": "total minus evidenced — FLAGGED, not guessed"},
    }
    out["label"] = (f"partial — measured {today}" if total is not None
                    else "placeholder (source unreachable)")
    return out


# ── B3 · expansion baselines ────────────────────────────────────────────────

def measure_expansion_baselines() -> dict:
    """Today's step-up / sprint / ordering / second-venue / referral rates.
    Product lines 'ordering'/'reservations'/'photo day' don't exist in any
    store yet → unmeasured, placeholder retained. Step-up/second-deal signal:
    repeated business names in the won-deals roster."""
    today = today_sydney()
    snap = _snap()
    won = ((snap.get("sales") or {}).get("won_businesses") or [])
    names = [str((w.get("business") or w.get("name"))
                 if isinstance(w, dict) else w).strip().lower()
             for w in won]
    # prod-caught: literal 'none'/blank tracker rows counted as repeat deals
    _junk = {"", "none", "null", "n/a", "-"}
    names = [n for n in names if n not in _junk]
    dupes = sorted({n for n in names if names.count(n) > 1})
    n_won = len(names)
    stepup_rate = round(100.0 * len(dupes) / n_won, 1) if n_won else None
    return {
        "metric": "expansion_baselines",
        "stepup_repeat_deal_rate_pct": {
            "value": stepup_rate,
            "label": (f"measured {today} (proxy: repeat business names in "
                      f"won window, n={n_won})" if stepup_rate is not None
                      else "placeholder"),
            "placeholder": 10.0, "repeat_businesses": dupes[:10]},
        "sprints": {"value": None, "label": "unmeasured, placeholder retained",
                    "placeholder": 20.0,
                    "why": "sprint is not a distinguishable tracker offer value"},
        "ordering": {"value": None, "label": "unmeasured, placeholder retained",
                     "placeholder": 0.0,
                     "why": "product line does not exist in any store yet"},
        "second_venue": {"value": None, "label": "unmeasured — no baseline in source",
                         "why": "no venue-count field; declarations will measure it"},
        "referrals": {"value": None, "label": "unmeasured — no baseline in source",
                      "why": "tracker lead-source referral join not yet wired "
                             "(registered dependency); declarations will measure it"},
        "method": "tracker won-deals roster (window-limited); the new "
                  "EXPANSION declarations become the forward measurement",
    }


# ── B4 · the book (dated membership ledger + tiers + workload) ──────────────

def book_ledger(seed_if_empty: bool = True) -> dict:
    """Dated membership ledger. Seeded once from the current derived roster
    (join = close_date/contract_start where known, else the seed date,
    labelled); thereafter the nightly watch appends join/leave events from
    roster diffs and declarations. Tier changes are dated owner edits."""
    today = str(today_sydney())
    ledger = kv_store.get(_KV_LEDGER)
    snap = _snap()
    actives = ((snap.get("active_clients") or {}).get("active") or [])
    roster_names = sorted({(c.get("name") or "").strip() for c in actives if c.get("name")})
    if not ledger and seed_if_empty and roster_names:
        members = []
        for c in actives:
            nm = (c.get("name") or "").strip()
            if not nm:
                continue
            join = c.get("close_date") or c.get("contract_start")
            members.append({"client": nm,
                            "joined": str(join)[:10] if join else today,
                            "join_basis": ("close_date" if c.get("close_date")
                                           else "contract_start" if c.get("contract_start")
                                           else f"seeded {today} (no date on file)"),
                            "left": None, "events": []})
        ledger = {"seeded": today, "members": members, "events": []}
        kv_store.put(_KV_LEDGER, ledger)
    ledger = ledger or {"seeded": None, "members": [], "events": []}

    # reconcile vs today's roster (append-only events; never silent)
    known = {m["client"] for m in ledger["members"]}
    current = set(roster_names)
    changed = False
    for nm in sorted(current - known):
        c = next((x for x in actives if (x.get("name") or "").strip() == nm), {})
        join = c.get("close_date") or c.get("contract_start") or today
        ledger["members"].append({"client": nm, "joined": str(join)[:10],
                                  "join_basis": "roster join (nightly diff)",
                                  "left": None, "events": []})
        ledger["events"].append({"at": today, "kind": "join", "client": nm})
        changed = True
    for m in ledger["members"]:
        if m["left"] is None and m["client"] not in current:
            m["left"] = today
            ledger["events"].append({"at": today, "kind": "leave",
                                     "client": m["client"]})
            changed = True
        elif m["left"] is not None and m["client"] in current:
            ledger["events"].append({"at": today, "kind": "rejoin",
                                     "client": m["client"]})
            m["left"] = None
            changed = True
    if changed:
        kv_store.put(_KV_LEDGER, ledger)
    return ledger


def tiers(cfg: dict | None = None) -> dict:
    """Owner-editable tier map (kv). Default SUGGESTION (labelled, not a
    tier): top 20–25 by revenue — churn-risk half of the source rule needs
    the health score (Phase 5)."""
    t = kv_store.get(_KV_TIERS) or {}
    snap = _snap()
    actives = ((snap.get("active_clients") or {}).get("active") or [])
    by_mrr = sorted(actives, key=lambda c: -(c.get("current_mrr") or 0))
    suggestion = [c.get("name") for c in by_mrr[:22] if c.get("name")]
    assigned = t.get("assignments") or {}
    tier1 = [n for n, v in assigned.items() if v == 1]
    book_n = len([c for c in actives if c.get("name")])
    return {
        "assignments": assigned,
        "assigned_at": t.get("assigned_at"),
        "tier1_count": len(tier1),
        "book_count": book_n,
        "suggestion_top_by_mrr": suggestion,
        "suggestion_note": "top-22 by MRR — a SUGGESTION until owner-tiered "
                           "(the source rule is revenue × churn risk; churn "
                           "risk needs the Phase-5 health score)",
        "second_csm_trigger": {"fires": len(tier1) > 30 or book_n > 55,
                               "rule": "Tier 1 > 30 or book > 55",
                               "tier1": len(tier1), "book": book_n},
    }


def set_tier(actor: dict, client: str, tier: int | None) -> tuple[dict | None, str | None]:
    """Owner tier edit — dated, journaled (csm journal, owner-only lane)."""
    if tier not in (1, 2, None):
        return None, "tier must be 1, 2, or null (clear)"
    t = kv_store.get(_KV_TIERS) or {"assignments": {}, "history": []}
    old = (t.get("assignments") or {}).get(client)
    if tier is None:
        t["assignments"].pop(client, None)
    else:
        t.setdefault("assignments", {})[client] = tier
    t["assigned_at"] = str(today_sydney())
    t.setdefault("history", []).append(
        {"at": str(today_sydney()), "who": (actor or {}).get("user", "rydel"),
         "client": client, "old": old, "new": tier})
    t["history"] = t["history"][-200:]
    kv_store.put(_KV_TIERS, t)
    return {"client": client, "tier": tier}, None


def workload_preview(tier1_cycle_hours: float = 2.5,
                     tier2_cycle_hours: float = 1.0,
                     capacity_hours: float = 120.0) -> dict:
    """Tier-1 monthly cycle hours vs capacity (config; stated assumptions)."""
    t = tiers()
    n1 = t["tier1_count"] or 0
    n_book = t["book_count"] or 0
    n2 = max(n_book - n1, 0)
    if n1 == 0:
        # untiered: preview on the suggestion, labelled
        n1 = len(t["suggestion_top_by_mrr"])
        n2 = max(n_book - n1, 0)
        basis = "suggestion tiers (book untiered — a live risk-register item)"
    else:
        basis = "owner tiers"
    hours = round(n1 * tier1_cycle_hours + n2 * tier2_cycle_hours, 1)
    return {"basis": basis, "tier1": n1, "tier2": n2,
            "cycle_hours_month": hours, "capacity_hours_month": capacity_hours,
            "utilisation_pct": round(100.0 * hours / capacity_hours, 1) if capacity_hours else None,
            "assumptions": {"tier1_cycle_hours": tier1_cycle_hours,
                            "tier2_cycle_hours": tier2_cycle_hours}}


# ── B5 · DQS proxy ──────────────────────────────────────────────────────────

def dqs_proxy() -> dict:
    """Delivery-quality proxy from the Timeline bridge: per-client health
    score, overdue deliverables, complaint recency, stale accounts. Labelled
    'proxy — formal DQS is Miguel's COO scorecard'. Bridge unreachable →
    honest degraded, never zeros."""
    today = str(today_sydney())
    label = "proxy — formal DQS is Miguel's COO scorecard"
    try:
        import timeline_adapter
        if not timeline_adapter.configured():
            return {"metric": "dqs_proxy", "label": label, "available": False,
                    "reason": "bridge not configured"}
        ov = timeline_adapter.overview()
        risk = timeline_adapter.risk()
        if ov is None:
            return {"metric": "dqs_proxy", "label": label, "available": False,
                    "reason": "bridge unreachable (None = unreachable, never zero)"}
        clients = ov.get("clients") or []
        rows = [{"client": c.get("client_name") or c.get("client_key"),
                 "health_score": c.get("health_score"),
                 "overdue": c.get("overdue"),
                 "real_breaches": c.get("real_breaches"),
                 "open_tasks": c.get("open_tasks")} for c in clients]
        scored = [r for r in rows if r.get("health_score") is not None]
        stale = ((risk or {}).get("stale") or {})
        return {
            "metric": "dqs_proxy", "label": label, "available": True,
            "measured": today,
            "book_avg_health": (round(sum(r["health_score"] for r in scored)
                                      / len(scored), 1) if scored else None),
            "pct_with_score": (round(100.0 * len(scored) / len(rows), 1)
                               if rows else None),
            "overdue_total": sum(r.get("overdue") or 0 for r in rows),
            "stale_accounts": stale.get("total") or stale.get("count"),
            "clients": rows,
            "last_touch_note": "no last-touch field on the bridge — "
                               "'>14d without substantive contact' is a "
                               "Phase-5 item, not faked",
        }
    except Exception as e:
        return {"metric": "dqs_proxy", "label": label, "available": False,
                "reason": str(e)[:100]}


# ── the bundle ───────────────────────────────────────────────────────────────

def all_baselines(fresh: bool = False) -> dict:
    """B1–B5 in one payload (cached daily — B2 hits Xero + Stripe)."""
    today = str(today_sydney())
    cached = kv_store.get(_KV_BASELINE_CACHE)
    if cached and not fresh and cached.get("date") == today:
        return cached["payload"]
    payload = {
        "b1_renewal": measure_renewal_rate(),
        "b1_in_term_completion": measure_in_term_completion(),
        "b2_refund_split": measure_refund_split(),
        "b3_expansion": measure_expansion_baselines(),
        "b4_book": {"ledger": book_ledger(), "tiers": tiers(),
                    "workload": workload_preview()},
        "b5_dqs_proxy": dqs_proxy(),
        "generated": today,
    }
    kv_store.put(_KV_BASELINE_CACHE, {"date": today, "payload": payload})
    return payload
