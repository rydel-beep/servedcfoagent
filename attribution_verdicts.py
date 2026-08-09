"""
attribution_verdicts.py
-----------------------
Phase 3 of the ad attribution engine: the Hormozi verdict layer — DOUBLE DOWN / KILL /
WATCH per creative, stage diagnostics naming WHERE a creative wins/loses, and the
constraint check ("is creative selection even the bottleneck?").

RULES (Rydel's Phase-0 confirmations + DECISIONS #111/#113):
  - Ranking metric: LTGP:CAC vs the registry floor (manual_targets ltgp_cac_target, 3.0x).
  - DOUBLE DOWN: ≥ floor WITH MARGIN (≥ floor×1.1) at ≥3 closes.
  - KILL: below floor×0.9 AND n ≥ 30 attributed leads — closes alone never justify a
    kill. A sufficient-lead creative with zero closes kills ONLY when the funnel shows
    the failure is the creative's own output (leads that never set); if its leads set at
    or above the account rate, the verdict names the sales handoff instead — "cheap leads
    that never set" is a qualification problem, "sets that never close" is a handoff
    question; the verdict names the stage so Romano fixes the right thing.
  - WATCH: insufficient n, or borderline (floor×0.9..×1.1), or below-floor without the
    30-lead bar — always with the honest reason and the n printed.
  - Every verdict is MATH-FLAGGED: the driver sentence carries the actual figures.
  - Analysis for humans only: nothing here (or anywhere in v1) can touch Meta — no write
    capability exists, structurally.

Channel rows (IG-DM / Unattributed) carry no verdict — they are coverage, not creatives.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DOUBLE_DOWN = "DOUBLE DOWN"
KILL = "KILL"
WATCH = "WATCH"

_MARGIN = 1.10        # "with margin" band above the floor
_BORDER = 0.90        # borderline band below the floor

# funnel stages measured cohort-basis (by lead Input Date), in order
_STAGES = [("lead_to_qualified", "leads", "qualified"),
           ("qualified_to_set", "qualified", "sets"),
           ("set_to_show", "sets", "shows"),
           ("show_to_close_cohort", "shows", "closes_cohort")]
_STAGE_LABEL = {"lead_to_qualified": "lead→qualified", "qualified_to_set": "qualified→set",
                "set_to_show": "set→show", "show_to_close_cohort": "show→close"}
_MIN_DENOM = 3        # a rate on fewer than this many is noise, not a diagnostic


def _rates(row: dict) -> dict:
    """Per-stage cohort rates for one row. _STAGES tuples are (key, den_field, num_field)."""
    out = {}
    for key, den_field, num_field in _STAGES:
        den = row.get(den_field) or 0
        num = row.get(num_field) or 0
        out[key] = {"den": den, "num": num,
                    "rate": round(num / den, 3) if den else None}
    return out


def baselines(rows: list[dict]) -> dict:
    """Account-wide attributed-cohort stage rates — the comparison line for diagnostics."""
    agg = {k: {"den": 0, "num": 0} for k, _, _ in _STAGES}
    for r in rows:
        if r.get("tier") != "ad":
            continue
        for key, den_field, num_field in _STAGES:
            agg[key]["den"] += r.get(den_field) or 0
            agg[key]["num"] += r.get(num_field) or 0
    return {k: {"rate": round(v["num"] / v["den"], 3) if v["den"] else None, **v}
            for k, v in agg.items()}


def stage_diagnostics(row: dict, base: dict) -> dict:
    """WHERE this creative wins/loses vs the account baseline. Only stages with a
    denominator ≥ _MIN_DENOM are judged — small denominators are shown, never judged."""
    rates = _rates(row)
    wins, loses, shortfalls = [], [], []
    for key, _d, _n in _STAGES:
        r, b = rates[key], base.get(key) or {}
        if r["rate"] is None or b.get("rate") in (None, 0) or r["den"] < _MIN_DENOM:
            continue
        rel = r["rate"] / b["rate"] if b["rate"] else None
        if rel is None:
            continue
        if rel >= 1.0:
            wins.append(_STAGE_LABEL[key])
        elif rel < 0.75:
            loses.append(_STAGE_LABEL[key])
            shortfalls.append((rel, key))
    worst = min(shortfalls)[1] if shortfalls else None
    read = None
    if worst:
        r, b = _rates(row)[worst], base[worst]
        read = (f"loses at {_STAGE_LABEL[worst]}: {r['num']}/{r['den']} "
                f"({100 * (r['rate'] or 0):.0f}%) vs account {100 * (b['rate'] or 0):.0f}%")
        if worst == "lead_to_qualified":
            read += " — lead quality IS the creative's output"
        elif worst == "qualified_to_set":
            read += " — a qualification/setter problem, not automatically a creative-kill"
        elif worst in ("set_to_show", "show_to_close_cohort"):
            read += " — a sales handoff question, not a creative problem on this evidence"
    return {"rates": {k: v["rate"] for k, v in _rates(row).items()},
            "wins_at": wins, "loses_at": loses, "worst_stage": worst, "read": read}


def _sets_at_or_above_baseline(row: dict, base: dict) -> bool | None:
    """Did this creative's leads SET at/above the account rate? (lead→set compound.)
    None when the sample is too small to say."""
    leads = row.get("leads") or 0
    if leads < _MIN_DENOM:
        return None
    b_leads = base["lead_to_qualified"]["den"] or 0
    b_sets = base["qualified_to_set"]["num"] or 0
    if not b_leads or not b_sets:
        return None
    return ((row.get("sets") or 0) / leads) >= (b_sets / b_leads)


def verdict_for_row(row: dict, floor: float, base: dict) -> dict:
    """The deterministic verdict for one creative row (engine output shape).
    Returns {verdict, driver, math} — driver always carries the figures."""
    if row.get("tier") != "ad":
        return {"verdict": None, "driver": "channel row — coverage, not a creative"}
    g = row.get("gates") or {}
    n_leads, n_closes = g.get("n_leads", 0), g.get("n_closes", 0)
    spend = row.get("spend") or 0.0
    lc = row.get("ltgp_cac")
    diag = stage_diagnostics(row, base)
    math = {"ltgp_cac": lc, "floor": floor, "ltgp": row.get("ltgp"),
            "loaded_cost_per_close": row.get("cost_per_close_loaded"),
            "n_leads": n_leads, "n_closes": n_closes, "spend": spend}

    def out(v, driver):
        return {"verdict": v, "driver": driver, "math": math, "stage": diag}

    if not (g.get("sufficient_for_scale") or g.get("sufficient_for_kill")):
        return out(WATCH, f"insufficient data (n={n_leads} leads, {n_closes} closes) — "
                          f"no verdict below 30 leads or 3 closes")
    if lc is not None:
        if lc >= floor * _MARGIN and n_closes >= 3:
            per_dollar = round(lc, 2)
            return out(DOUBLE_DOWN,
                       f"scale spend; every $1 here returns ${per_dollar:.2f} of LTGP "
                       f"({n_closes} closes, LTGP ${(row.get('ltgp') or 0):,.0f} vs loaded "
                       f"${(row.get('cost_per_close_loaded') or 0):,.0f}/close, floor {floor}x)")
        if lc >= floor * _MARGIN:  # above floor with margin but <3 closes (30-lead path in)
            return out(WATCH, f"reads {lc}x above the floor but only {n_closes} close(s) — "
                              f"scale requires 3; watch")
        if floor * _BORDER <= lc < floor * _MARGIN:
            return out(WATCH, f"borderline at the floor ({lc}x vs {floor}x, n={n_leads} "
                              f"leads/{n_closes} closes) — hold; the next closes decide")
        # below the border band
        if n_leads >= 30:
            return out(KILL, f"below the floor at n={n_leads} leads: each close costs "
                             f"${row.get('cost_per_close_loaded') or row.get('cost_per_close') or 0:,.0f} "
                             f"loaded vs ${(row.get('ltgp') or 0):,.0f} LTGP ({lc}x < {floor}x)"
                             + (f"; {diag['read']}" if diag.get("read") else ""))
        return out(WATCH, f"reads {lc}x below the floor but only n={n_leads} leads — "
                          f"KILL requires 30; watch")
    # no LTGP:CAC (zero closes, or margin unavailable)
    if row.get("closes"):
        return out(WATCH, f"{n_closes} close(s) but LTGP:CAC unavailable (margin input "
                          f"missing) — figures shown, verdict withheld, never guessed")
    if n_leads >= 30 and spend > 0:
        sets_ok = _sets_at_or_above_baseline(row, base)
        if sets_ok:
            return out(WATCH, f"sales handoff question — n={n_leads} leads set at/above "
                              f"the account rate but zero closes on ${spend:,.0f}; fix the "
                              f"handoff, not the creative"
                              + (f"; {diag['read']}" if diag.get("read") else ""))
        return out(KILL, f"n={n_leads} leads, ${spend:,.0f} spend, zero closes and sets "
                         f"below the account rate — lead quality is the creative's output"
                         + (f"; {diag['read']}" if diag.get("read") else ""))
    if spend > 0:
        return out(WATCH, f"${spend:,.0f} spend, {n_leads} leads, no closes yet — "
                          f"insufficient for any verdict")
    return out(WATCH, "no spend in this window — funnel shown for reference")


def constraint_check(rows: list[dict], floor: float, capacity_note: str | None = None) -> dict:
    """The Hormozi discipline: the tool must be able to conclude the tool isn't the
    bottleneck. If ALL sufficient-n creatives clear the floor → creative selection is
    NOT the constraint; volume/capacity is."""
    sufficient = [r for r in rows if r.get("tier") == "ad" and r.get("verdict")
                  and ((r.get("gates") or {}).get("sufficient_for_scale")
                       or (r.get("gates") or {}).get("sufficient_for_kill"))]
    if not sufficient:
        biggest = max((r for r in rows if r.get("tier") == "ad"),
                      key=lambda r: (r.get("gates") or {}).get("n_leads", 0), default=None)
        n = (biggest.get("gates") or {}).get("n_leads", 0) if biggest else 0
        return {"creatives_are_constraint": None,
                "read": f"insufficient data account-wide — no creative has reached the "
                        f"verdict bars yet (largest n={n} leads); the constraint can't be "
                        f"named from this window"}
    kills = [r for r in sufficient if r["verdict"] == KILL]
    below = [r for r in sufficient if (r.get("ltgp_cac") is not None
                                       and r["ltgp_cac"] < floor)]
    measurable = [r for r in sufficient if r.get("ltgp_cac") is not None]
    if not kills and not measurable:
        # sufficient-n creatives exist but none has a computable LTGP:CAC (e.g. margin
        # input missing) — indeterminate must NEVER read as "clears the floor".
        return {"creatives_are_constraint": None,
                "read": f"{len(sufficient)} verdict-eligible creative(s) but LTGP:CAC is "
                        f"unavailable on all of them (margin/close inputs missing) — the "
                        f"constraint can't be called; nothing is assumed to clear the floor"}
    if not kills and not below:
        read = ("creative selection isn't the constraint; volume/capacity is — every "
                f"sufficient-n creative clears the {floor}x floor")
        if capacity_note:
            read += f". Capacity read: {capacity_note}"
        return {"creatives_are_constraint": False, "read": read,
                "capacity_note": capacity_note}
    return {"creatives_are_constraint": True,
            "read": f"{len(kills)} kill(s) / {len(below)} below-floor at sufficient n — "
                    f"budget is leaking into creatives under the {floor}x floor; "
                    f"reallocate before scaling volume",
            "kills": [r["label"] for r in kills]}


def apply(result: dict, floor: float, capacity_note: str | None = None) -> dict:
    """Enrich an attribution_engine result in place: per-row verdicts + the constraint
    check. Pure — no I/O; the engine wrapper supplies floor + capacity."""
    rows = result.get("creatives") or []
    base = baselines(rows)
    for r in rows:
        v = verdict_for_row(r, floor, base)
        r["verdict"] = v["verdict"]
        r["verdict_driver"] = v["driver"]
        r["verdict_math"] = v.get("math")
        r["stage_diagnostics"] = v.get("stage")
        if r.get("tier") == "ad":
            p = provisional_for_row(r, floor, base)
            if p:
                r["provisional"] = p
    result["verdict_layer"] = {
        "floor": floor, "floor_source": "manual_targets ltgp_cac_target",
        "bands": {"double_down_at": round(floor * _MARGIN, 2),
                  "kill_below": round(floor * _BORDER, 2)},
        "rules": "KILL requires 30 attributed leads; scale may fire on 3 closes; "
                 "borderline holds; verdicts are analysis for humans — nothing auto-pauses",
        "baselines": base,
        "constraint_check": constraint_check(rows, floor, capacity_note),
    }
    return result


# ── Phase 4 (CLOSE_INTEGRITY_AND_SIGNAL_REPORT): useful before certainty ─────
# PROVISIONAL SIGNAL below min-n (labelled, never a decision), PROGRESS TO VERDICT,
# and the AGGREGATION LADDER (batch → campaign → account) — the same engine numbers
# rolled up; levels that clear min-n earn REAL verdicts with the SAME thresholds.

import re as _re

# THE one source for the min-n bars (gate-integrity: these are the engine's constants,
# imported — not redefined — so the thresholds cannot silently fork).
from attribution_engine import MIN_N_LEADS_KILL, MIN_N_CLOSES_SCALE

_BATCH_RE = _re.compile(r"^([A-Z]\d{3})[_ ]")


def provisional_for_row(row: dict, floor: float, base: dict) -> dict | None:
    """Direction below min-n — deterministic, from figures the engine already computed.
    NEVER phrased as a decision; visually distinct client-side. None when a real verdict
    exists or there is nothing to read."""
    g = row.get("gates") or {}
    if g.get("sufficient_for_scale") or g.get("sufficient_for_kill"):
        return None
    n_leads, n_closes = g.get("n_leads", 0), g.get("n_closes", 0)
    if not (row.get("spend") or n_leads):
        return None
    lc = row.get("ltgp_cac")
    trend, why = "early", "not enough signal either way yet"
    if lc is not None:
        trend = "strong" if lc >= floor else "weak"
        why = f"provisional LTGP:CAC {lc}x vs the {floor}x floor"
    elif n_leads >= 3:
        b_leads = (base.get("lead_to_qualified") or {}).get("den") or 0
        b_qual = (base.get("lead_to_qualified") or {}).get("num") or 0
        if b_leads:
            acct_q = b_qual / b_leads
            q = (row.get("qualified") or 0) / n_leads
            if q >= acct_q and (row.get("sets") or 0) > 0:
                trend, why = "strong", (f"qualified rate {100*q:.0f}% ≥ account "
                                        f"{100*acct_q:.0f}% with sets behind it")
            elif q < acct_q * 0.5:
                trend, why = "weak", (f"qualified rate {100*q:.0f}% vs account "
                                      f"{100*acct_q:.0f}%")
    need_leads = max(0, MIN_N_LEADS_KILL - n_leads)
    need_closes = max(0, MIN_N_CLOSES_SCALE - n_closes)
    progress = (f"{need_leads} more lead{'s' if need_leads != 1 else ''} or "
                f"{need_closes} more close{'s' if need_closes != 1 else ''} to a verdict")
    label = {"strong": f"TRENDING STRONG (provisional, {n_leads}/{MIN_N_LEADS_KILL} leads)",
             "weak": f"TRENDING WEAK (provisional, {n_leads}/{MIN_N_LEADS_KILL} leads)",
             "early": f"EARLY (provisional, {n_leads}/{MIN_N_LEADS_KILL} leads)"}[trend]
    return {"trend": trend, "label": label, "why": why, "progress": progress}


def _aggregate(rows: list[dict], key: str, label: str) -> dict:
    """Union of member creatives — sums only (roll-up sums == component sums is
    test-enforced); loaded/LTGP derived from member fields the engine already computed."""
    agg = {"creative_key": key, "label": label, "tier": "ad", "members": len(rows),
           "member_keys": [r["creative_key"] for r in rows]}
    # TAB PARITY (DECISIONS #128, the Reached "—" fix): every grid metric flows
    # through this ONE aggregation — a field missing here renders "—" on the
    # ladder tabs while the Ads tab computes it (the D3 bug class, test-locked).
    for k in ("leads", "qualified", "reached", "sets", "shows", "closes_cohort",
              "closes", "revenue_unknown", "impressions", "clicks",
              "earlier_closes", "earlier_sets", "earlier_shows", "undated_sets",
              "shows_unverified"):
        agg[k] = sum(r.get(k) or 0 for r in rows)
    for k in ("cash", "contract", "spend"):
        agg[k] = round(sum(r.get(k) or 0 for r in rows), 2)
    spend, closes = agg["spend"], agg["closes"]
    agg["cost_per_lead"] = round(spend / agg["leads"], 2) if agg["leads"] else None
    agg["cost_per_qualified"] = round(spend / agg["qualified"], 2) if agg["qualified"] else None
    agg["cost_per_set"] = round(spend / agg["sets"], 2) if agg["sets"] else None
    agg["cost_per_close"] = round(spend / closes, 2) if closes else None
    # loaded at the union grain: every member's spend + the closing members' comms share
    ltgp = sum(r.get("ltgp") or 0 for r in rows)
    loaded_total = sum((r.get("cost_per_close_loaded") or 0) * (r.get("closes") or 0)
                       for r in rows)
    loaded_total += sum((r.get("spend") or 0) for r in rows if not r.get("closes"))
    if closes and loaded_total:
        agg["cost_per_close_loaded"] = round(loaded_total / closes, 2)
        if ltgp:
            agg["ltgp"] = round(ltgp, 2)
            agg["ltgp_cac"] = round(ltgp / loaded_total, 2)
    # LAUNCH LINEAGE (#133) at the group grain: engine-side union over member
    # ad ids (earliest member launch; active days = union of delivery days) —
    # the group-name hover reads THIS field, never client math (I16).
    try:
        import launch_lineage
        agg["lineage"] = launch_lineage.aggregate_rows(rows)
    except Exception:
        agg["lineage"] = None
    agg["gates"] = {
        "n_leads": agg["leads"], "n_closes": closes,
        "sufficient_for_scale": closes >= MIN_N_CLOSES_SCALE,
        "sufficient_for_kill": agg["leads"] >= MIN_N_LEADS_KILL,
        "gate": ("ok" if (closes >= MIN_N_CLOSES_SCALE or agg["leads"] >= MIN_N_LEADS_KILL)
                 else f"watch — insufficient data (n={agg['leads']} leads, {closes} closes)"),
    }
    return agg


def ladder_groups(result: dict) -> dict:
    """THE one grouping path for every ladder level. Returns
    {level: {group_key: [member creative rows]}} keyed by the SAME group keys the
    rendered ladder rows carry. ladder() consumes this; so does the roster engine —
    a ladder-cell roster is the concat of its member creatives' rosters, which
    equals the cell because _aggregate() sums the same members (I17)."""
    ads = [r for r in (result.get("creatives") or []) if r.get("tier") == "ad"
           and (r.get("spend") or r.get("leads") or r.get("closes"))]
    names: dict = {}
    for r in ads:
        k = r.get("name_norm") or "UNNAMED"
        names.setdefault(k if k != "UNNAMED" else "MIXED/AMBIGUOUS", []).append(r)
    batches: dict = {}
    for r in ads:
        m = _BATCH_RE.match(r.get("label") or "")
        batches.setdefault(m.group(1) if m else "UNBATCHED", []).append(r)
    camps: dict = {}
    for r in ads:
        cs = r.get("campaigns") or []
        key = cs[0] if len(cs) == 1 else ("MIXED/AMBIGUOUS" if cs or r.get("leads")
                                          else "NO CAMPAIGN DATA")
        camps.setdefault(key, []).append(r)
    return {"name": names, "batch": batches, "campaign": camps,
            "account": {"__account__": ads}}


def ladder(result: dict, floor: float) -> dict:
    """batch (B008…) → campaign → account, each with the SAME verdict rules. The
    scorecard defaults to the highest level holding a confirmed verdict."""
    groups = ladder_groups(result)
    ads = groups["account"]["__account__"]
    base = baselines(result.get("creatives") or [])

    _MIXED_KEYS = {"UNBATCHED", "MIXED/AMBIGUOUS", "NO CAMPAIGN DATA"}

    def verd(rows_agg):
        for a in rows_agg:
            # a grab-bag of unrelated creatives is COVERAGE, not an angle — it can never
            # carry a verdict (killing "everything unbatched" as one unit is a category
            # error caught live: 32 mixed leads earned a KILL). Sums stay visible.
            if a["creative_key"] in _MIXED_KEYS:
                a["verdict"] = None
                a["verdict_driver"] = ("mixed group — no shared angle; drill to the "
                                       "creatives for judgement")
                continue
            v = verdict_for_row(a, floor, base)
            a["verdict"], a["verdict_driver"] = v["verdict"], v["driver"]
            p = provisional_for_row(a, floor, base)
            if p:
                a["provisional"] = p
        rows_agg.sort(key=lambda a: (-(a.get("spend") or 0)))
        return rows_agg

    # NAME level — the DELIBERATE cross-campaign view of one creative (hybrid keying:
    # the base rows are ad ids; grouping by name here is a choice, not an accident)
    name_rows = verd([_aggregate(v, k,
                                 (v[0].get("label") or k).split(" [")[0] +
                                 (f" (all campaigns, {len(v)} ads)" if len(v) > 1 else ""))
                      for k, v in groups["name"].items()])

    batch_rows = verd([_aggregate(v, k, f"Batch {k}" if k != "UNBATCHED" else
                                  "Unbatched creatives")
                       for k, v in groups["batch"].items()])

    camp_rows = verd([_aggregate(v, k, k) for k, v in groups["campaign"].items()])

    account = _aggregate(ads, "__account__", "Attributed ads (account)")
    account["note"] = ("ad-attributed rows only — the banner totals carry the WHOLE "
                       "account incl. IG-DM and unattributed closes")
    v = verdict_for_row(account, floor, base)
    account["verdict"], account["verdict_driver"] = v["verdict"], v["driver"]

    def has_confirmed(rows_):
        return any(a.get("verdict") in (DOUBLE_DOWN, KILL) or
                   (a.get("verdict") and (a.get("gates") or {}).get("gate") == "ok")
                   for a in rows_)
    default_level = ("creative" if has_confirmed(result.get("creatives") or []) else
                     "name" if has_confirmed(name_rows) else
                     "batch" if has_confirmed(batch_rows) else
                     "campaign" if has_confirmed(camp_rows) else "account")
    return {"name": name_rows, "batch": batch_rows, "campaign": camp_rows, "account": account,
            "default_level": default_level,
            "note": "same engine, same thresholds — a level earns a verdict only when "
                    "ITS n clears the bars"}
