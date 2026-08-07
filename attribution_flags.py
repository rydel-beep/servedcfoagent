"""
attribution_flags.py
--------------------
The INTELLIGENCE SCORECARD for the dedicated ad dashboard (AD_DASHBOARD_REPORT Phase 0/4):
LEADERS (most qualified / most closes / best LTGP:CAC at sufficient n / most cash) and
deterministic OUTLIER FLAGS with stated, adjustable thresholds (manual_targets keys).

ZERO NEW MATH: every number is read off the attribution engine's result — this module
compares fields the engine already computed against thresholds. min-n respected: a flag
whose rule needs a sample never fires below it. New flags feed salience once (kv pending
list, watermarked by the greeting's told-set, same as verdict crossings).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULTS = {
    "ad_flag_spend_no_leads": 150.0,
    "ad_flag_leads_no_sets": 8,
    "ad_flag_show_floor_pct": 40.0,
    "ad_flag_qual_dev_pts": 25.0,
    "ad_flag_cpl_mult": 2.0,
    "ad_flag_attr_drop_pts": 10.0,
    "ad_flag_unknown_rev_pct": 20.0,
    "ad_flag_reach_floor_pct": 40.0,   # Gate 2: qualified reach-rate below this flags
}


def thresholds() -> dict:
    t = dict(DEFAULTS)
    try:
        import manual_targets
        resolved = manual_targets.get_resolved() or {}
        for k in t:
            if resolved.get(k) is not None:
                t[k] = float(resolved[k])
    except Exception as e:
        logger.info("flag thresholds fallback to defaults: %s", e)
    return t


def _ads(result: dict) -> list[dict]:
    return [c for c in (result.get("creatives") or []) if c.get("tier") == "ad"]


def leaders(result: dict) -> list[dict]:
    """The leaders row — each card names the creative, the number, one plain line."""
    ads = _ads(result)
    days = (result.get("window") or {}).get("days")
    out = []

    def card(title, row, value_str, line):
        out.append({"title": title, "creative": row["label"], "value": value_str,
                    "window_days": days, "line": line})

    by_q = max(ads, key=lambda c: c["qualified"], default=None)
    if by_q and by_q["qualified"]:
        card("Most Qualified Leads", by_q, str(by_q["qualified"]),
             f"{by_q['label'][:38]} — {by_q['qualified']} qualified of {by_q['leads']} "
             f"leads, {by_q['sets']} sets behind it")
    by_c = max(ads, key=lambda c: c["closes"], default=None)
    if by_c and by_c["closes"]:
        card("Top Closing Creative", by_c, str(by_c["closes"]),
             f"{by_c['label'][:38]} — {by_c['closes']} of the window's closes, "
             f"${by_c['cash']:,.0f} cash (the WINDOW TOTAL is the headline tile)")
    eligible = [c for c in ads if c.get("ltgp_cac") is not None
                and ((c.get("gates") or {}).get("sufficient_for_scale")
                     or (c.get("gates") or {}).get("sufficient_for_kill"))]
    by_l = max(eligible, key=lambda c: c["ltgp_cac"], default=None)
    if by_l:
        card("Best LTGP:CAC (sufficient n)", by_l, f"{by_l['ltgp_cac']}x",
             f"{by_l['label'][:38]} — every $1 returns ${by_l['ltgp_cac']:.2f} LTGP "
             f"({by_l['closes']} closes)")
    by_cash = max(ads, key=lambda c: c["cash"], default=None)
    if by_cash and by_cash["cash"]:
        card("Most Cash", by_cash, f"${by_cash['cash']:,.0f}",
             f"{by_cash['label'][:38]} — ${by_cash['cash']:,.0f} collected on "
             f"${by_cash['spend']:,.0f} spend")
    return out


def flags(result: dict, trailing_attr_rate: float | None = None,
          th: dict | None = None) -> list[dict]:
    """Deterministic outlier flags, severity-sorted. Every card: rule, numbers, the
    implied question. Sample floors (min-n) are part of each rule — never noise."""
    th = th or thresholds()
    ads = _ads(result)
    t = result.get("totals") or {}
    out = []

    def flag(severity, kind, creative, headline, question):
        out.append({"severity": severity, "kind": kind, "creative": creative,
                    "headline": headline, "question": question,
                    "id": f"adflag:{kind}:{(creative or 'account').lower()[:40]}:"
                          f"{(result.get('window') or {}).get('days')}d"})

    for c in ads:
        # KILL CANDIDATE: spend, zero leads
        if c["spend"] >= th["ad_flag_spend_no_leads"] and c["leads"] == 0:
            flag(1, "spend_no_leads", c["label"],
                 f"${c['spend']:,.0f} spent, 0 leads in the window",
                 "kill candidate — why is this still running?")
        # FUNNEL BREAK: leads, zero sets
        if c["leads"] >= th["ad_flag_leads_no_sets"] and c["sets"] == 0:
            flag(2, "leads_no_sets", c["label"],
                 f"{c['leads']} leads, 0 sets",
                 "the creative attracts, the funnel drops — check speed-to-lead")
        # UNREACHABLE QUALIFIED (Gate 2 Option A): fit stays ruled; reach-rate is
        # the flag signal — an ad whose qualified leads systematically can't be
        # reached gets called out without corrupting the fit definition.
        if c["qualified"] >= th["ad_flag_leads_no_sets"]:
            reach_rate = 100.0 * (c.get("reached") or 0) / c["qualified"]
            if reach_rate < th.get("ad_flag_reach_floor_pct", 40.0):
                flag(2, "qualified_unreachable", c["label"],
                     f"reach rate {reach_rate:.0f}% ({c.get('reached') or 0}/"
                     f"{c['qualified']} qualified reached)",
                     "qualified but unreachable — audience fit real, contact rate broken "
                     "(number quality / speed-to-lead / channel)")
        # SHOW-UP PROBLEM — rate computed on VERIFIED shows (#129: unverified
        # attendance never launders a show-rate; the unverified count rides beside)
        if c["sets"] >= 5:
            shows_v = c["shows"] - (c.get("shows_unverified") or 0)
            rate = 100.0 * shows_v / c["sets"]
            if rate < th["ad_flag_show_floor_pct"]:
                flag(2, "sets_no_shows", c["label"],
                     f"show rate {rate:.0f}% ({c['shows']}/{c['sets']} sets)",
                     "a show-up problem — confirm reminders/booking flow")
        # WRONG AUDIENCE: qualified% deviation
        if c["leads"] >= 8 and t.get("leads"):
            acct_q = 100.0 * sum(x["qualified"] for x in ads) / max(1, sum(x["leads"] for x in ads))
            q = 100.0 * c["qualified"] / c["leads"]
            if abs(q - acct_q) > th["ad_flag_qual_dev_pts"] and q < acct_q:
                flag(2, "qualified_outlier", c["label"],
                     f"qualified {q:.0f}% vs account {acct_q:.0f}% (n={c['leads']})",
                     "wrong-audience flag — the targeting or the hook")
        # CPL OUTLIER
        if c["leads"] >= 5 and c["spend"] >= 100 and c.get("cost_per_lead") is not None:
            spends = sum(x["spend"] for x in ads)
            leads_n = sum(x["leads"] for x in ads)
            if leads_n and spends:
                acct_cpl = spends / leads_n
                if c["cost_per_lead"] > th["ad_flag_cpl_mult"] * acct_cpl:
                    flag(3, "cpl_outlier", c["label"],
                         f"CPL ${c['cost_per_lead']:,.0f} vs account ${acct_cpl:,.0f}",
                         "paying a premium for these leads — is the audience saturated?")

    # CAPTURE REGRESSION (account-level)
    rate = t.get("attribution_rate_pct")
    if rate is not None and trailing_attr_rate is not None and \
            rate < trailing_attr_rate - th["ad_flag_attr_drop_pts"]:
        flag(1, "attribution_drop", None,
             f"attribution rate {rate}% this window vs {trailing_attr_rate}% trailing",
             "capture may have regressed — check the lead-form integration/UTMs")

    # DATA INTEGRITY
    dupes = [f for f in (result.get("flags") or []) if f.get("kind") == "duplicate_won_row"]
    if dupes:
        flag(2, "duplicate_rows", None,
             f"{len(dupes)} duplicate-suspect won row(s) (engine counts once)",
             "fix at source in the tracker — the explicit-duplicates term retires")
    if t.get("leads"):
        unknown = sum(c.get("revenue_unknown", 0) for c in (result.get("creatives") or []))
        pct = 100.0 * unknown / t["leads"]
        if pct > th["ad_flag_unknown_rev_pct"]:
            flag(3, "revenue_unknown_spike", None,
                 f"revenue unknown on {unknown} of {t['leads']} leads ({pct:.0f}%)",
                 "setters/GHL form not capturing revenue — check the form mapping")

    out.sort(key=lambda f: f["severity"])
    return out


def scorecard(result: dict, trailing_attr_rate: float | None = None) -> dict:
    th = thresholds()
    fl = flags(result, trailing_attr_rate=trailing_attr_rate, th=th)
    vl = result.get("verdict_layer") or {}
    return {
        "leaders": leaders(result),
        "flags": fl,
        "constraint_line": (vl.get("constraint_check") or {}).get("read"),
        "thresholds": th,
        "window": result.get("window"),
        "trailing_attribution_rate_pct": trailing_attr_rate,
    }


def record_flag_salience(fl: list[dict]) -> None:
    """New flag ids → the pending list salience reads (announced once, watermarked by
    the greeting's told-set — the ids are stable per kind+creative+window)."""
    try:
        import kv_store
        pending = kv_store.get("attr:flag_pending") or []
        known = {p.get("id") for p in pending}
        for f in fl:
            if f["severity"] <= 2 and f["id"] not in known:
                pending.append({"id": f["id"], "headline": f["headline"],
                                "creative": f.get("creative"), "question": f["question"]})
        kv_store.put("attr:flag_pending", pending[-30:])
    except Exception as e:
        logger.info("flag salience record failed: %s", e)


def identity_health(result: dict, trailing_result: dict | None = None) -> dict:
    """THE IDENTITY HEALTH read (CREATIVE_IDENTITY_REPORT Phase 3): the resolution-path
    census, each join hop's measured rate, and degradation vs trailing. Everything from
    fields the engine already emitted — the join quality is a WATCHED number."""
    census: dict = {}
    for c in (result.get("creatives") or []):
        for basis, n in (c.get("first_touch_basis") or {}).items():
            census[basis] = census.get(basis, 0) + n
    t = result.get("totals") or {}
    attributed = t.get("attributed_leads") or 0
    exact = census.get("id", 0)
    exact_rate = round(100.0 * exact / attributed, 1) if attributed else None
    rows = result.get("rows") or []
    hop2_join = sum(1 for r in rows if r.get("joined_via"))
    hop2_email = sum(1 for r in rows if r.get("joined_via") == "email")
    out = {
        "census": census,
        "attribution_rate_pct": t.get("attribution_rate_pct"),
        "exact_id_rate_pct": exact_rate,
        "ambiguous_leads": t.get("ambiguous_leads", 0),
        "unattributed_leads": (t.get("leads") or 0) - attributed
                              - (t.get("ambiguous_leads") or 0),
        "hops": {
            "hop1_ad_to_contact": {"primary": "utmAdId (exact id)",
                                   "exact_id_rate_pct": exact_rate,
                                   "ambiguous": t.get("ambiguous_leads", 0)},
            "hop2_contact_to_tracker": {
                "primary": "email (normalized)",
                "match_rate_pct": round(100.0 * hop2_join / len(rows), 1) if rows else None,
                "email_share_pct": round(100.0 * hop2_email / max(1, hop2_join), 1) if hop2_join else None},
            "hop3_tracker_to_stripe": "the existing payment matcher — rates in the hygiene panel",
            "hop4_tracker_funnel": "the tracker's own dated fields (the close-integrity authority)",
        },
    }
    if trailing_result is not None:
        tc: dict = {}
        for c in (trailing_result.get("creatives") or []):
            for basis, n in (c.get("first_touch_basis") or {}).items():
                tc[basis] = tc.get(basis, 0) + n
        t_attr = (trailing_result.get("totals") or {}).get("attributed_leads") or 0
        t_exact = round(100.0 * tc.get("id", 0) / t_attr, 1) if t_attr else None
        out["trailing_exact_id_rate_pct"] = t_exact
        if exact_rate is not None and t_exact is not None and exact_rate < t_exact - 15:
            out["degradation_flag"] = {
                "severity": 1, "kind": "exact_id_rate_drop",
                "id": f"adflag:exact_id_drop:{(result.get('window') or {}).get('days')}d",
                "creative": None,
                "headline": f"exact-id resolution {exact_rate}% this window vs "
                            f"{t_exact}% trailing",
                "question": "capture regression — check the lead-form integration/UTMs"}
    return out
