"""csm_plan.py — the CSM-investment domain hub (OWNER-ONLY, DECISIONS #146).

One engine behind every surface: the /csm page, the dashboard card, EDITH
drills (both surfaces), the D4 briefing and D5 exports all read THIS module,
which composes csm_model (pure math) + csm_baselines (Gate-0 measurements)
+ the declaration store (money truth) + mrr_snapshots (NRR windows).

═══ CONFIDENTIALITY LAW ═══
Everything here is owner-scope. The module NEVER writes to: collab worklog/
digest (the announce-to-Piolo path), action_feed or any feed:extra channel,
salience/greeting/brief facts, memory_facts, snapshot_state, or the shared
sentinel feed. Director comp figures exist ONLY as owner-entered kv config
values — no defaults, masked in the config journal, absent from every doc,
log and export. EDITH answers fall through SILENTLY for non-owners (never a
refusal that confirms the domain exists).
"""

from __future__ import annotations

import logging
import re

import kv_store
from helpers import today_sydney

import csm_model
import csm_baselines

logger = logging.getLogger(__name__)

_KV_CONFIG = "csm:config"
_KV_JOURNAL = "csm:journal"
_KV_GATES = "csm:gates"
_KV_RISKS = "csm:risks"
_KV_SENTINEL = "csm:sentinel"
_JOURNAL_CAP = 300

# director figures: OWNER-ENTERED ONLY — no defaults anywhere in code.
_DIRECTOR_KEYS = ("director_current_annual", "director_proposed_low",
                  "director_proposed_high")

def _default_sg():
    try:
        from xero_wages_categoriser import SG_RATE
        return SG_RATE
    except Exception:
        return 0.12


CONFIG_DEFAULTS = {
    "start_date": "2026-12-01",          # phase plan ≈ late Nov/Dec 2026
    "employment_form": "employee",       # or "contractor"
    "sg_rate": None,                     # None → the SG_RATE authority
    "on_costs_annual": 0.0,
    "tools_annual": 0.0,
    "variable_floor_quarters": 0,
    "variable_floor_quarterly": 0.0,
    "director_current_annual": None,     # owner config — masked in journal
    "director_proposed_low": None,
    "director_proposed_high": None,
    "offset_start_date": None,           # default = start_date
    "structural_refund_split": None,     # None → source placeholder 0.5
    "expected_new_clients_per_month": 2.0,   # labelled assumption (M2)
    "grace_days": 30,
    "floor_share": 0.5,
    "tier1_cycle_hours": 2.5,
    "tier2_cycle_hours": 1.0,
    "csm_capacity_hours": 120.0,
    "book_size_mode": "live_book",       # or "source_30"
    "scenario_publish": False,           # M8 — labelled what-if overlay
}

_NUMERIC_BOUNDS = {
    "on_costs_annual": (0, 50_000), "tools_annual": (0, 20_000),
    "sg_rate": (0.0, 0.25), "variable_floor_quarters": (0, 4),
    "variable_floor_quarterly": (0, 20_000),
    "director_current_annual": (0, 500_000),
    "director_proposed_low": (0, 500_000),
    "director_proposed_high": (0, 500_000),
    "structural_refund_split": (0.0, 1.0),
    "expected_new_clients_per_month": (0, 20),
    "grace_days": (0, 120), "floor_share": (0.0, 1.0),
    "tier1_cycle_hours": (0.0, 40.0), "tier2_cycle_hours": (0.0, 40.0),
    "csm_capacity_hours": (1.0, 400.0),
}


def config() -> dict:
    cur = dict(CONFIG_DEFAULTS)
    cur.update(kv_store.get(_KV_CONFIG) or {})
    return cur


def journal(entry: dict):
    j = kv_store.get(_KV_JOURNAL) or []
    j.append({**entry, "at": str(today_sydney())})
    kv_store.put(_KV_JOURNAL, j[-_JOURNAL_CAP:])


def journal_entries(limit: int = 40) -> list:
    return (kv_store.get(_KV_JOURNAL) or [])[-limit:]


def set_config(actor: dict, updates: dict) -> tuple[dict | None, str | None]:
    """Owner config write — journaled {who, key, old→new}; DIRECTOR figures
    are journaled as '(set)'/'(updated)'/'(cleared)' — never the values."""
    cur = config()
    who = (actor or {}).get("user", "rydel")
    for k, v in (updates or {}).items():
        if k not in CONFIG_DEFAULTS:
            return None, f"unknown config key '{k}'"
        if k in ("start_date", "offset_start_date"):
            if v is not None:
                import datetime as dt
                try:
                    dt.date.fromisoformat(str(v))
                except ValueError:
                    return None, f"{k} must be an ISO date"
        elif k == "employment_form":
            if v not in ("employee", "contractor"):
                return None, "employment_form must be employee|contractor"
        elif k == "book_size_mode":
            if v not in ("live_book", "source_30"):
                return None, "book_size_mode must be live_book|source_30"
        elif k == "scenario_publish":
            v = bool(v)
        elif v is not None:
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None, f"{k} must be numeric"
            lo, hi = _NUMERIC_BOUNDS.get(k, (None, None))
            if lo is not None and not (lo <= v <= hi):
                return None, f"{k} out of bounds [{lo}, {hi}]"
        old = cur.get(k)
        cur[k] = v
        if k in _DIRECTOR_KEYS:
            masked = ("(cleared)" if v is None
                      else "(updated)" if old is not None else "(set)")
            journal({"who": who, "key": k, "change": masked})
        else:
            journal({"who": who, "key": k, "old": old, "new": v})
    kv_store.put(_KV_CONFIG, {k: v for k, v in cur.items()
                              if v != CONFIG_DEFAULTS.get(k)})
    return cur, None


def _comp_overrides(cfg: dict) -> dict:
    return {"sg_rate": cfg["sg_rate"] if cfg["sg_rate"] is not None else _default_sg(),
            "on_costs_annual": cfg["on_costs_annual"],
            "tools_annual": cfg["tools_annual"],
            "employment_form": cfg["employment_form"],
            "variable_floor_quarters": cfg["variable_floor_quarters"],
            "variable_floor_quarterly": cfg["variable_floor_quarterly"]}


# ── phases + gates ──────────────────────────────────────────────────────────

GATE0_ITEMS = [
    {"id": "floor_test", "type": "human",
     "label": "Continuity floor tested on live no's"},
    {"id": "rate_card", "type": "human",
     "label": "Four rungs priced on the rate card (ladder price column)"},
    {"id": "miguel_reframe", "type": "human",
     "label": "Miguel reframe delivered IN PERSON + team told"},
    {"id": "interface_agreement", "type": "human",
     "label": "Interface agreement written by Miguel"},
    {"id": "scorecard_writing", "type": "human",
     "label": "Scorecard, decision rights, tiering in writing"},
    {"id": "baselines_measured", "type": "data",
     "label": "B1 renewal + B2 refund split measured from data"},
    {"id": "book_tiered", "type": "data",
     "label": "Book tiered (Tier 1/2 assigned)"},
]


def gates(baselines: dict | None = None) -> dict:
    """Gate-0 checklist: data items auto-tick WITH evidence; human items
    owner-ticked (journaled). who-ticks shown."""
    state = kv_store.get(_KV_GATES) or {}
    b = baselines or csm_baselines.all_baselines()
    items = []
    for it in GATE0_ITEMS:
        row = dict(it)
        if it["type"] == "data":
            if it["id"] == "baselines_measured":
                b1 = (b.get("b1_renewal") or {}).get("label", "")
                b2 = (b.get("b2_refund_split") or {}).get("label", "")
                done = b1.startswith("measured") and ("measured" in b2)
                row["done"] = done
                row["evidence"] = f"B1: {b1} · B2: {b2}"
            elif it["id"] == "book_tiered":
                t = ((b.get("b4_book") or {}).get("tiers") or {})
                row["done"] = bool(t.get("tier1_count"))
                row["evidence"] = (f"Tier 1 = {t.get('tier1_count')} clients "
                                   f"(assigned {t.get('assigned_at')})"
                                   if t.get("tier1_count") else "book untiered")
            row["ticks"] = "auto (data)"
        else:
            s = state.get(it["id"]) or {}
            row["done"] = bool(s.get("done"))
            row["ticked_by"] = s.get("who")
            row["ticked_at"] = s.get("at")
            row["ticks"] = "owner"
        items.append(row)
    done_n = sum(1 for i in items if i.get("done"))
    return {"items": items, "done": done_n, "total": len(items)}


def tick_gate(actor: dict, gate_id: str, done: bool) -> tuple[dict | None, str | None]:
    ids = {g["id"] for g in GATE0_ITEMS if g["type"] == "human"}
    if gate_id not in ids:
        return None, f"'{gate_id}' is not an owner-tickable gate item"
    state = kv_store.get(_KV_GATES) or {}
    who = (actor or {}).get("user", "rydel")
    state[gate_id] = {"done": bool(done), "who": who, "at": str(today_sydney())}
    kv_store.put(_KV_GATES, state)
    journal({"who": who, "gate": gate_id, "done": bool(done)})
    return state[gate_id], None


def phase_strip(cfg: dict | None = None) -> dict:
    import datetime as dt
    cfg = cfg or config()
    today = today_sydney()
    start = dt.date.fromisoformat(cfg["start_date"])
    marks = [
        {"key": "phase0", "label": "Phase 0 — restructure + hire prep",
         "date": None},
        {"key": "start", "label": "CSM start", "date": str(start)},
        {"key": "d30", "label": "Day 30 — diagnosis delivered",
         "date": str(start + dt.timedelta(days=30))},
        {"key": "d60", "label": "Day 60 — 100% health + first recovery",
         "date": str(start + dt.timedelta(days=60))},
        {"key": "d90", "label": "DAY-90 GATE (keep&expand / keep&correct / exit)",
         "date": str(start + dt.timedelta(days=90))},
        {"key": "m6", "label": "Month-6 checkpoint",
         "date": str(start + dt.timedelta(days=182))},
    ]
    phase = "pre-start"
    days_in = (today - start).days
    if days_in >= 0:
        phase = ("ramp (D1–60)" if days_in <= 60 else
                 "day-90 window" if days_in <= 90 else
                 "run (post-D90)" if days_in <= 182 else "post-M6")
    nxt = next((m for m in marks if m["date"] and m["date"] > str(today)), None)
    return {"today": str(today), "phase": phase, "marks": marks,
            "days_to_start": max(-days_in, 0),
            "next_gate": ({"name": nxt["label"],
                           "in_days": (dt.date.fromisoformat(nxt["date"]) - today).days}
                          if nxt else None)}


# ── risk register (pre-mortem, reconstructed from the plan — owner-editable) ─

RISK_DEFAULTS = [
    {"id": "comfort_hire", "risk": "Comfort hire — nicer face on the same "
     "numbers", "signal": "no attributable lift by month 6 (the keep/kill "
     "line)", "owner": "Rydel", "kind": "data-post-start"},
    {"id": "routing_around", "risk": "Clients keep routing to Kalin",
     "signal": "owner-assessed at M6 (the outcome test: clients stop "
     "emailing Kalin)", "owner": "Rydel", "kind": "human"},
    {"id": "no_expansion_m4", "risk": "No expansion by month 4",
     "signal": "zero EXPANSION declarations in months 1–4",
     "owner": "CSM", "kind": "data-post-start"},
    {"id": "decision_rights", "risk": "Decision rights not widened at day 90",
     "signal": "day-90 gate item unticked", "owner": "Rydel", "kind": "human"},
    {"id": "book_untiered", "risk": "Book untiered — Tier-1 focus never set",
     "signal": "tiers unassigned (live check)", "owner": "Rydel",
     "kind": "data-now"},
    {"id": "miguel_interface", "risk": "Miguel reads the shift as demotion / "
     "interface breaks", "signal": "interface-agreement gate item + "
     "escalation friction", "owner": "Rydel + Miguel", "kind": "human"},
    {"id": "delivery_sucked", "risk": "CSM absorbed into delivery instead of "
     "revenue", "signal": "offer log empty while touch cadence high "
     "(needs Phase-5 GHL ingestion)", "owner": "Rydel", "kind": "phase5"},
    {"id": "single_point", "risk": "CSM becomes a single point of failure",
     "signal": "second-CSM-onboardable milestone (month 9) unmet",
     "owner": "CSM", "kind": "milestone"},
    {"id": "plan_leak", "risk": "Plan leaks before the in-person Miguel "
     "conversation", "signal": "weekly security replay + leak probes "
     "(sentinel)", "owner": "system", "kind": "sentinel"},
]


def risks(baselines: dict | None = None) -> dict:
    state = kv_store.get(_KV_RISKS) or {}
    b = baselines or csm_baselines.all_baselines()
    tiers = ((b.get("b4_book") or {}).get("tiers") or {})
    sent = kv_store.get(_KV_SENTINEL) or {}
    out = []
    for r in RISK_DEFAULTS:
        row = dict(r)
        s = state.get(r["id"]) or {}
        row["status"] = s.get("status", "watch")
        row["note"] = s.get("note")
        # live signals where data allows
        if r["id"] == "book_untiered":
            row["status"] = "ok" if tiers.get("tier1_count") else "fire"
            row["live"] = True
        if r["id"] == "plan_leak":
            probe = sent.get("leak_probe") or {}
            row["status"] = ("ok" if probe.get("ok") else
                             "fire" if probe.get("ok") is False else "watch")
            row["live"] = True
            row["last_probe"] = probe.get("at")
        out.append(row)
    return {"register": out,
            "note": "reconstructed from the plan's keep/kill + pre-mortem — "
                    "statuses owner-editable"}


def set_risk(actor: dict, risk_id: str, status: str,
             note: str | None = None) -> tuple[dict | None, str | None]:
    if status not in ("ok", "watch", "fire"):
        return None, "status must be ok|watch|fire"
    if risk_id not in {r["id"] for r in RISK_DEFAULTS}:
        return None, f"unknown risk '{risk_id}'"
    state = kv_store.get(_KV_RISKS) or {}
    who = (actor or {}).get("user", "rydel")
    state[risk_id] = {"status": status, "note": (note or "")[:200],
                      "who": who, "at": str(today_sydney())}
    kv_store.put(_KV_RISKS, state)
    journal({"who": who, "risk": risk_id, "status": status})
    return state[risk_id], None


# ── ladder calendar ─────────────────────────────────────────────────────────

_LADDER_RUNGS = [
    ("day0", 0, "12-month term offer (onboarding call)"),
    ("day14_30", 14, "Google Ads add-on — capture the demand"),
    ("month1_2", 45, "Served Ordering"),
    ("month2_3", 75, "Served Reservations"),
    ("month3", 90, "Referral ask + photo/content day (the win moment)"),
    ("month3_4", 105, "Market Intel / Famous-For session"),
    ("month4_lock", 120, "MONTH-4 LOCK — 12-month locked rate offer"),
    ("month5_renewal", 150, "Renewal conversation"),
]


def ladder_calendar() -> dict:
    """Per client: term start/end, month-4 lock date, renewal date, the rung
    due this week/month, tier — the CSM's Phase-7 operating calendar,
    previewing her workload NOW from real terms."""
    import datetime as dt
    today = today_sydney()
    b = csm_baselines.all_baselines()
    tiers = ((b.get("b4_book") or {}).get("tiers") or {}).get("assignments") or {}
    try:
        from snapshot import load_persisted
        actives = ((load_persisted() or {}).get("active_clients") or {}).get("active") or []
    except Exception:
        actives = []
    rows, undated = [], []
    for c in actives:
        nm = (c.get("name") or "").strip()
        if not nm:
            continue
        start_s = c.get("contract_start") or c.get("close_date")
        if not start_s:
            undated.append(nm)
            continue
        try:
            start = dt.date.fromisoformat(str(start_s)[:10])
        except ValueError:
            undated.append(nm)
            continue
        term, basis = csm_baselines._term_months(c)
        end_s = c.get("contract_end")
        end = None
        if end_s:
            try:
                end = dt.date.fromisoformat(str(end_s)[:10])
            except ValueError:
                pass
        if end is None and term:
            import client_overrides as _co
            end = _co._add_months(start, term)
            basis += " (end derived)"
        lock = start + dt.timedelta(days=120)
        renew = (end - dt.timedelta(days=30)) if end else start + dt.timedelta(days=150)
        due_week, due_month = [], []
        for key, offset, label in _LADDER_RUNGS:
            d = start + dt.timedelta(days=offset)
            delta = (d - today).days
            if 0 <= delta <= 7:
                due_week.append(label)
            elif 7 < delta <= 31:
                due_month.append(label)
        rows.append({"client": nm, "tier": tiers.get(nm),
                     "term_start": str(start),
                     "term_end": str(end) if end else None,
                     "term_months": term, "term_basis": basis,
                     "month4_lock_date": str(lock),
                     "renewal_date": str(renew) if renew else None,
                     "rungs_due_this_week": due_week,
                     "rungs_due_this_month": due_month})
    rows.sort(key=lambda r: (r["renewal_date"] or "9999"))
    return {"clients": rows, "undated": undated,
            "rungs": [{"key": k, "day_offset": o, "label": l}
                      for k, o, l in _LADDER_RUNGS],
            "note": "term dates from the sheet/tracker; package-default "
                    "terms labelled 'derived'"}


# ── NRR + scoreboard ────────────────────────────────────────────────────────

def nrr_rolling(days: int = 90) -> dict:
    """NRR on the book, rolling window, STARTING COHORT ONLY (mid-window
    joins excluded by convention — stated). From mrr_snapshots per_client."""
    import datetime as dt
    import mrr_snapshot
    today = today_sydney()
    s0 = mrr_snapshot.snapshot_on_date(today - dt.timedelta(days=days))
    s1 = mrr_snapshot.snapshot_on_date(today)
    if not s0 or not s1 or not s0.get("per_client"):
        first = mrr_snapshot.first_snapshot_date()
        return {"available": False,
                "reason": (f"snapshot history starts {first} — a {days}d "
                           "window isn't covered yet" if first
                           else "no MRR snapshots")}
    start_map = s0["per_client"] or {}
    end_map = s1["per_client"] or {}
    start = sum(float(v or 0) for v in start_map.values())
    if start <= 0:
        return {"available": False, "reason": "zero start-of-window MRR"}
    expansion = contraction = churn = 0.0
    for k, v0 in start_map.items():
        v0 = float(v0 or 0)
        v1 = float(end_map.get(k) or 0)
        if k not in end_map or v1 == 0:
            churn += v0
        elif v1 > v0:
            expansion += v1 - v0
        elif v1 < v0:
            contraction += v0 - v1
    nrr = (start + expansion - contraction - churn) / start
    return {"available": True, "window_days": days,
            "window": [str(s0.get("snap_date")), str(s1.get("snap_date"))],
            "start_mrr": round(start, 2), "expansion": round(expansion, 2),
            "contraction": round(contraction, 2), "churn": round(churn, 2),
            "nrr_pct": round(100.0 * nrr, 1),
            "convention": "starting cohort only — mid-window joins excluded"}


def _declarations_since(start_iso: str | None) -> list[dict]:
    try:
        import client_overrides
        rows = client_overrides.active_overrides()
        rows += list((client_overrides.reconciled_recent(365) or {}).values())
        if start_iso:
            rows = [r for r in rows
                    if str(r.get("created_at") or "")[:10] >= start_iso]
        return rows
    except Exception:
        return []


def comp_accrual(cfg: dict | None = None) -> dict:
    """Model-accrued variable comp from DECLARATION events since start —
    itemised, clawback-aware — beside Xero-PAID (payroll truth; activates
    once she's on payroll)."""
    cfg = cfg or config()
    start = cfg["start_date"]
    today = str(today_sydney())
    if today < start:
        return {"state": "activates at start",
                "start_date": start, "lines": [], "total_accrued": 0.0,
                "xero_paid": None,
                "note": "no comp accrues before her start date"}
    events = []
    for ov in _declarations_since(start):
        kind = ov.get("change_type")
        if kind == "renewal":
            events.append({"type": "renewal", "client": ov.get("client_name"),
                           "evidence_id": ov.get("id")})
            if (ov.get("term_months") or 0) >= 12:
                events.append({"type": "lock12", "client": ov.get("client_name"),
                               "evidence_id": ov.get("id")})
        elif kind == "downsell":
            events.append({"type": "continuity_save",
                           "client": ov.get("client_name"),
                           "evidence_id": ov.get("id")})
        elif kind == "expansion":
            sub = ov.get("subtype")
            if sub == "referral":
                events.append({"type": "referral",
                               "amount": ov.get("first6_value") or ov.get("amount") or 0,
                               "client": ov.get("client_name"),
                               "evidence_id": ov.get("id")})
            else:
                events.append({"type": "stepup",
                               "first6_value": ov.get("first6_value") or 0,
                               "client": ov.get("client_name"),
                               "evidence_id": ov.get("id")})
    acc = csm_model.accrue_comp(events, _comp_overrides(cfg))
    acc["state"] = "live"
    acc["xero_paid"] = None
    acc["xero_note"] = ("Xero-paid comparison activates when the CSM appears "
                        "on payroll — payroll truth = Xero; drift surfaced")
    return acc


def scoreboard() -> dict:
    """K1–K6 + refunds by cause + DQS beside NRR + comp accrual + milestones
    + the day-90 gate. Pre-start tiles say 'activates at start' — the
    baseline versions render now."""
    cfg = config()
    b = csm_baselines.all_baselines()
    today = str(today_sydney())
    pre_start = today < cfg["start_date"]
    start = cfg["start_date"]
    decls = _declarations_since(start if not pre_start else None)
    downsells = [d for d in decls if d.get("change_type") == "downsell"]
    churns = [d for d in decls if d.get("change_type") == "churn"]
    expansions = [d for d in decls if d.get("change_type") == "expansion"]
    exp_by_type = {}
    for d in expansions:
        exp_by_type.setdefault(d.get("subtype") or "unknown", []).append(
            {"client": d.get("client_name"), "amount": d.get("amount"),
             "first6_value": d.get("first6_value"), "id": d.get("id")})
    non_renewers = len(downsells) + len(churns)
    nrr = nrr_rolling(90)
    import datetime as dt
    milestones = []
    sd = dt.date.fromisoformat(start)
    for key, days, label, target in [
            ("d30", 30, "Day-30 diagnosis delivered", "owner-assessed"),
            ("d60", 60, "Day-60: 100% health visibility + first recovery",
             "K5 + owner"),
            ("d90", 90, "Day-90: first expansion + first floor-save + first lock",
             "declarations"),
            ("m6", 182, "Month-6 checkpoint: renewal up vs baseline · refunds "
             "down · >= $6.5k net MRR attributable (~$9.5k margin-adjusted) · "
             "routing-around gone", "the keep/kill line")]:
        milestones.append({"key": key, "date": str(sd + dt.timedelta(days=days)),
                           "label": label, "measured_by": target})
    return {
        "state": "pre-start (baselines live; her lanes activate at start)"
                 if pre_start else "live",
        "k1_retention": {
            "nrr": nrr if nrr.get("available") else
                   {**nrr, "note": "activates with snapshot history"},
            "one_number_note": ("THE ONE NUMBER — pre-start this is the "
                                "book's own baseline NRR, not hers"
                                if pre_start else "THE ONE NUMBER"),
            "renewal_rate_vs_b1": {
                "baseline": b.get("b1_renewal"),
                "targets": {"floor": 48, "base": 60, "upside": 72}},
        },
        "k2_continuity": {
            "downsells": len(downsells), "non_renewers": non_renewers,
            "capture_pct": (round(100.0 * len(downsells) / non_renewers, 1)
                            if non_renewers else None),
            "target_pct": 50,
            "window": ("since start" if not pre_start
                       else "all declarations (pre-start baseline)")},
        "k3_expansion": {
            "by_type": exp_by_type,
            "total_first6_value": round(sum(
                float(d.get("first6_value") or 0) for d in expansions), 2),
            "baselines_vs_targets": {
                "stepup": {"baseline_pct": 10, "target_pct": 33},
                "sprints": {"baseline_pct": 20, "target_pct": 50},
                "ordering": {"baseline_pct": 0, "target_pct": 40}},
            "referrals_note": "tracker lead-source join is a registered "
                              "dependency; referral DECLARATIONS measure it "
                              "forward (ID-exact to the referring client)"},
        "k4_onboarding": {
            "recoup_in_30": {"state": "partial — cash_collected vs retainer "
                             "per new client needs first-30d Stripe/Xero "
                             "read; declarations + tracker corroborate"},
            "exit_interview_set": {"state": "activates at start "
                                   "(checkbox per onboarding)"}},
        "k5_health_visibility": {
            "proxy": b.get("b5_dqs_proxy"),
            "no_contact_14d": "not exposed — Phase-5 item (no last-touch "
                              "field on the bridge)"},
        "k6_systemisation": {
            "motion_documented_v1": "human milestone — day 90",
            "second_csm_onboardable": "human milestone — month 9"},
        "refunds_by_cause": b.get("b2_refund_split"),
        "refunds_lever_note": "FY26: $41,436 refunds = 52% of NPAT — the "
                              "single biggest controllable lever",
        "dqs_beside_nrr": {
            "nrr_owner": "CSM (hers)", "dqs_owner": "Miguel (COO scorecard)",
            "proxy": {"book_avg_health":
                      (b.get("b5_dqs_proxy") or {}).get("book_avg_health"),
                      "label": (b.get("b5_dqs_proxy") or {}).get("label")},
            "read": "a retention drop reads as delivery vs relationship"},
        "comp_accrual": comp_accrual(cfg),
        "milestones": milestones,
        "day90_gate": {
            "decision": "keep & expand / keep & correct / exit",
            "criteria": ["first expansion declared", "first floor-save",
                         "first 12-month lock", "health visibility 100%",
                         "decision rights widened (owner tick)"],
            "evidence": {"expansions": len(expansions),
                         "floor_saves": len(downsells),
                         "locks": len([d for d in decls
                                       if d.get("change_type") == "renewal"
                                       and (d.get("term_months") or 0) >= 12])}},
    }


# ── the model view (M1–M8) ──────────────────────────────────────────────────

def model_view(custom: dict | None = None) -> dict:
    """Everything the MODEL tab renders: regression proof, scenarios with
    both ROI clocks (loaded beside unloaded), layer-vs-hire, funding paths,
    monthly curves, the 4x solve, book scaling, conventions."""
    cfg = config()
    comp = _comp_overrides(cfg)
    b = csm_baselines.all_baselines()
    scenarios = {k: csm_model.scenario_roi(k, comp) for k in ("floor", "base", "upside")}
    curve = csm_model.monthly_curve("base", comp)
    split = cfg["structural_refund_split"]
    book_n = ((b.get("b4_book") or {}).get("tiers") or {}).get("book_count") or 0
    scale = round(book_n / csm_model.SOURCE["book_size"], 2) if book_n else None
    solve = csm_model.solve_renewal_for_cohort_roi(4.0, comp)
    frontier = []
    r = 44.0
    while r <= 80.0:
        ote = csm_model.ote_at(r)
        loaded = csm_model.loaded_cost_annual(ote, comp)
        frontier.append({"renewal_pct": r,
                         "cohort_roi_loaded": round(
                             csm_model.credited_lift_lifetime_at(r) / loaded, 3)})
        r += 2.0
    out = {
        "regression": csm_model.regression_check(),
        "frontier": frontier,
        "scenarios": scenarios,
        "monthly_curve_base": curve,
        "steady_state": csm_model.steady_state_roi(curve),
        "layer_vs_hire": csm_model.layer_vs_hire("base", split, comp),
        "solve_4x": solve,
        "book_scaling": {
            "mode": cfg["book_size_mode"], "source_book": 30,
            "live_book": book_n, "scale_factor": scale,
            "note": "source model is a 30-client book; live-book mode scales "
                    "the headline lift by the factor, LABELLED — the "
                    "regression always runs on the source's own 30",
            "growth_assumption": {
                "expected_new_clients_per_month":
                    cfg["expected_new_clients_per_month"],
                "label": "labelled assumption — new clients enter the book "
                         "and receive the ladder"}},
        "funding_paths": funding_view(cfg),
        "actuals_overlay": actuals_overlay(cfg),
        "comp_defaults": {**csm_model.COMP_TABLE_DEFAULTS, **comp,
                          "note": "PDF defaults; the SIGNED OFFER replaces "
                                  "them via owner config"},
        "convention_notes": csm_model.CONVENTION_NOTES,
        "scenario_publish": {"enabled": bool(cfg["scenario_publish"]),
                             "label": "include CSM hire plan — what-if "
                                      "(labelled until her costs are Xero "
                                      "actuals)"},
    }
    if custom and custom.get("renewal_pct"):
        try:
            r = float(custom["renewal_pct"])
            ote = csm_model.ote_at(r)
            loaded = csm_model.loaded_cost_annual(ote, comp)
            lift = csm_model.credited_lift_lifetime_at(r)
            out["custom"] = {"renewal_pct": r, "ote": round(ote, 0),
                             "loaded_cost": round(loaded, 0),
                             "credited_lift_lifetime": round(lift, 0),
                             "cohort_roi_loaded": round(lift / loaded, 2),
                             "label": "what-if — actuals untouched",
                             "other_sliders_note": "expansion/continuity/"
                             "completion are bundled in the source's scenario "
                             "axis — independent decomposition awaits the "
                             "workbook internals (stated, not faked)"}
        except (TypeError, ValueError):
            pass
    return out


def funding_view(cfg: dict | None = None) -> dict:
    """R4: two paths side by side, both range ends + custom; director figures
    read from owner config AT CALL TIME (never constants); 'what the offset
    buys' rendered from the deltas."""
    cfg = cfg or config()
    comp = _comp_overrides(cfg)
    base_ote = csm_model.SCENARIO_ANCHORS["base"]["ote"]
    loaded = csm_model.loaded_cost_annual(base_ote, comp)
    sg = comp["sg_rate"]
    cur = cfg["director_current_annual"]
    lo, hi = cfg["director_proposed_low"], cfg["director_proposed_high"]
    ends = {}
    for label, proposed in (("low_end", lo), ("high_end", hi)):
        ends[label] = csm_model.funding_paths(loaded, cur, proposed, sg)
    what_it_buys = None
    if ends["low_end"].get("configured"):
        d_lo = ends["low_end"]["offset_funded"]["fixed_cost_delta"]
        d_hi = (ends["high_end"]["offset_funded"]["fixed_cost_delta"]
                if ends["high_end"].get("configured") else None)
        what_it_buys = {
            "fy27_pbt_delta_range": [round(-d, 0) for d in
                                     ([d_lo, d_hi] if d_hi is not None else [d_lo])],
            "runway_note": "offset-funded: business discretionary cash "
                           "untouched — runway unchanged; cash-funded: "
                           "~24 months of base on ~$94k discretionary",
            "downside": "bounded to director income (the buffer, not the "
                        "funding source — the hire is funded by retention "
                        "or it isn't a good hire)"}
    return {"csm_loaded_annual": round(loaded, 2),
            "offset_start_date": cfg["offset_start_date"] or cfg["start_date"],
            "ends": ends, "what_the_offset_buys": what_it_buys,
            "law": "FUNDING PATH != RETURN — the offset finances the hire; "
                   "the hire's economics are unchanged by who pays. "
                   "return-per-$-of-NET-cost is a financing view, NEVER ROI."}


def actuals_overlay(cfg: dict | None = None) -> dict:
    """M7: credited lift accrues vs the curve post-start (R5: lift over
    baseline, evidence-linked). Pre-start: the honest empty state."""
    cfg = cfg or config()
    today = str(today_sydney())
    if today < cfg["start_date"]:
        return {"state": "activates at start", "start_date": cfg["start_date"],
                "credited_to_date": 0.0, "ledger": [],
                "note": "credited lift = actual minus Gate-0 baseline "
                        "expectation, evidence-linked (declaration id / "
                        "invoice / tracker row) — baseline-predicted "
                        "renewals credit $0"}
    b = csm_baselines.all_baselines()
    base_rate = ((b.get("b1_renewal") or {}).get("value")
                 or csm_baselines.PLACEHOLDERS["renewal_rate_pct"])
    ledger = []
    credited = 0.0
    cm = csm_model.CM_SOURCE
    decls = _declarations_since(cfg["start_date"])
    renewals = [d for d in decls if d.get("change_type") == "renewal"]
    n_renew = len(renewals)
    expected = round(base_rate / 100.0 * max(n_renew, 1), 2)
    above = max(0, n_renew - int(expected))
    for d in sorted(renewals, key=lambda x: str(x.get("created_at")))[-above:] if above else []:
        val = float(d.get("new_mrr") or 0) * (d.get("term_months") or 6) * cm
        credited += val
        ledger.append({"kind": "renewal above baseline", "client": d.get("client_name"),
                       "credited": round(val, 2), "evidence_id": d.get("id")})
    for d in decls:
        if d.get("change_type") == "downsell":
            val = float(d.get("new_mrr") or 0) * 6 * cm
            credited += val
            ledger.append({"kind": "continuity capture", "client": d.get("client_name"),
                           "credited": round(val, 2), "evidence_id": d.get("id")})
        elif d.get("change_type") == "expansion":
            val = float(d.get("first6_value") or 0) * cm
            credited += val
            ledger.append({"kind": f"expansion ({d.get('subtype')})",
                           "client": d.get("client_name"),
                           "credited": round(val, 2), "evidence_id": d.get("id")})
    comp = _comp_overrides(cfg)
    loaded = csm_model.loaded_cost_annual(csm_model.SCENARIO_ANCHORS["base"]["ote"], comp)
    return {"state": "live", "baseline_renewal_rate": base_rate,
            "renewals_declared": n_renew, "credited_to_date": round(credited, 2),
            "ledger": ledger,
            "roi_to_date_note": "early-month ROI is NEVER a verdict — "
                                "leading indicators lead; ROI is the lagging line",
            "planned_cost_monthly": round(loaded / 12.0, 2),
            "actual_cost_note": "Xero payroll actuals replace planned as they "
                                "land (activates when she's on payroll)"}


def scenario_overlay() -> dict:
    """M8: the labelled 'include CSM hire plan' overlay for the MAIN forward
    projection — incremental REVENUE per month from her start, base scenario,
    scaled to the live book when configured. What-if until Xero actuals."""
    import datetime as dt
    cfg = config()
    comp = _comp_overrides(cfg)
    curve = csm_model.monthly_curve("base", comp)
    cm = csm_model.CM_SOURCE
    b = csm_baselines.all_baselines()
    book_n = ((b.get("b4_book") or {}).get("tiers") or {}).get("book_count") or 0
    scale = (book_n / csm_model.SOURCE["book_size"]
             if (cfg["book_size_mode"] == "live_book" and book_n) else 1.0)
    start = dt.date.fromisoformat(cfg["start_date"])
    today = today_sydney()
    # months offset between projection month-0 (this month) and her start
    offset = (start.year - today.year) * 12 + (start.month - today.month)
    monthly_revenue = []
    for i in range(24):          # the projection horizon is <= 12; extra safe
        j = i - offset
        if j < 0 or j >= len(curve["months"]):
            monthly_revenue.append(0.0)
        else:
            lift = curve["months"][j]["credited_lift"]
            monthly_revenue.append(round(lift / cm * scale, 2))
    return {"enabled": bool(cfg["scenario_publish"]),
            "label": "include CSM hire plan — what-if (labelled until her "
                     "costs are actuals in Xero)",
            "start_date": cfg["start_date"], "scenario": "base",
            "book_scale": round(scale, 2),
            "monthly_incremental_revenue": monthly_revenue,
            "basis": "credited contribution curve ÷ workbook margin "
                     f"({round(cm*100,1)}%) = incremental revenue; scaled "
                     "to the live book, labelled"}


# ── summary (hero + card) ───────────────────────────────────────────────────

def summary() -> dict:
    cfg = config()
    b = csm_baselines.all_baselines()
    g = gates(b)
    strip = phase_strip(cfg)
    r = risks(b)
    live_risks = [x for x in r["register"] if x["status"] == "fire"][:3] or \
                 [x for x in r["register"] if x["status"] == "watch"][:3]
    comp = _comp_overrides(cfg)
    solve = csm_model.solve_renewal_for_cohort_roi(4.0, comp)
    nrr = nrr_rolling(90)
    today = str(today_sydney())
    pre_start = today < cfg["start_date"]
    base = csm_model.scenario_roi("base", comp)
    return {
        "phase_strip": strip,
        "next_action": _next_action(g, strip),
        "one_number": (nrr if (nrr.get("available") and not pre_start)
                       else {"state": "activates at start",
                             "baseline": nrr if nrr.get("available") else None}),
        "dial_4x": {"state": "pre-start projection" if pre_start
                    else "actuals-informed",
                    "target": 4.0, "clock": "cohort (loaded)",
                    "base_cohort_roi_loaded": base["cohort_roi_loaded"],
                    "upside_cohort_roi_loaded":
                        csm_model.scenario_roi("upside", comp)["cohort_roi_loaded"],
                    "renewal_needed_pct": solve["renewal_pct"],
                    "y1_honesty": "year-1 4x exists in NO scenario"},
        "gate0": {"done": g["done"], "total": g["total"]},
        "top_risks": [{"risk": x["risk"], "status": x["status"]}
                      for x in live_risks],
        "card_line": (f"CSM · {strip['phase']} · "
                      + (f"next: {strip['next_gate']['name'][:34]} in "
                         f"{strip['next_gate']['in_days']}d · "
                         if strip.get("next_gate") else "")
                      + f"Gate 0 {g['done']}/{g['total']} · path to 4x: "
                        f"{solve['renewal_pct']}% renewal"),
    }


def _next_action(g: dict, strip: dict) -> dict:
    pending = [i for i in g["items"] if not i.get("done")]
    if pending:
        h = pending[0]
        return {"item": h["label"],
                "owner": "Rydel" if h["type"] == "human" else "data (auto)"}
    if strip.get("next_gate"):
        return {"item": strip["next_gate"]["name"], "owner": "Rydel"}
    return {"item": "run the plan", "owner": "Rydel"}


# ── EDITH (both surfaces — owner-only, silent fall-through otherwise) ───────

_CSM_RE = re.compile(
    r"\b(csm|client success (manager|layer|hire)|path to 4x|4x (solve|target|"
    r"roi)|gets? (us )?to 4x|renewal rate[^.]{0,30}4x|continuity floor|"
    r"csm analysis|the hire plan)\b", re.I)


def _deep_link() -> str:
    import os
    base = (os.environ.get("CFO_PUBLIC_URL") or "").rstrip("/")
    return (base + "/dashboard/csm") if base else "/dashboard/csm"


def handle_csm_command(text: str, actor: dict | None) -> tuple[str | None, bool]:
    """Tier-2 drill. NON-OWNER: (None, False) — falls through to normal
    conversation without confirming the domain exists. Registered in BOTH
    handler lists (text + streaming/voice/timeline)."""
    if (actor or {}).get("role") != "owner":
        return None, False
    t = (text or "").lower()
    if not _CSM_RE.search(t):
        return None, False
    link = _deep_link()
    try:
        if re.search(r"analysis|briefing|full (report|picture)", t):
            import csm_docs
            res = csm_docs.generate_analysis()
            return (f"CSM — analysis v{res['version']} regenerated "
                    f"({res['generated']}). Owner-only: {link}?tab=exports — "
                    f"headlines: {res['headline']}", True)
        if re.search(r"what renewal|renewal rate.*(4x|four)|path to 4x|"
                     r"gets? (us )?to 4x|4x solve", t):
            s = csm_model.solve_renewal_for_cohort_roi(
                4.0, _comp_overrides(config()))
            return (f"CSM — the 4x solve: {s['renewal_pct']}% renewal rate "
                    f"reaches 4x cohort ROI at loaded cost (base is 60%, "
                    f"upside 72% — it sits between them). Year-1 4x exists "
                    f"in no scenario; the cohort clock carries the target. "
                    f"{link}?tab=model", True)
        if re.search(r"gate (0|zero)|checklist", t):
            g = gates()
            open_items = [i["label"] for i in g["items"] if not i.get("done")]
            return (f"CSM — Gate 0 at {g['done']}/{g['total']}. Open: "
                    + ("; ".join(open_items) if open_items else "none — clear")
                    + f". {link}?tab=gates", True)
        if re.search(r"offset.*(buy|do)|what does the offset", t):
            f = funding_view()
            cfgd = f["ends"]["low_end"].get("configured")
            if not cfgd:
                return (f"CSM — the offset isn't configured yet: enter the "
                        f"director comp figures in the owner config panel on "
                        f"{link}?tab=model. The law: the offset FINANCES the "
                        f"hire; it never changes her economics.", True)
            d = f["ends"]["low_end"]["offset_funded"]["fixed_cost_delta"]
            return (f"CSM — offset-funded: fixed-cost delta "
                    f"${d:,.0f}/yr (≈ neutral); business cash untouched; "
                    f"downside bounded to director income. Cash-funded: "
                    f"~24 months of base on discretionary cash. "
                    f"Never rendered as ROI. {link}?tab=model", True)
        if re.search(r"refund.*(lever|biggest)|why refunds", t):
            return ("CSM — refunds are the biggest lever because FY26 booked "
                    "$41,436 in refunds & rebates = 52% of NPAT: halving them "
                    "adds more profit than most growth levers, and the split "
                    "(client refund vs guarantee payout vs ad rebate) names "
                    f"the owner of each dollar. {link}?tab=baselines", True)
        if re.search(r"roi status|csm roi|where are we", t):
            s = summary()
            return (f"CSM — {s['card_line']}. Next: "
                    f"{s['next_action']['item']} ({s['next_action']['owner']})."
                    f" {link}", True)
        s = summary()
        return (f"CSM — {s['card_line']}. Ask me: the 4x solve · gate 0 · "
                f"what the offset buys · the CSM analysis. {link}", True)
    except Exception as e:
        logger.info("csm drill failed: %s", e)
        return (f"CSM — the engine hit an error ({str(e)[:60]}); the page "
                f"has the honest state: {link}", True)


def csm_context(text: str, actor: dict | None) -> str:
    """Grounded-context injector for tier-3 OWNER turns that mention the
    domain. Returns '' for non-owners or unrelated turns. Any turn this
    fires on is marked sensitive by the routes (never persisted/distilled)."""
    if (actor or {}).get("role") != "owner":
        return ""
    if not _CSM_RE.search((text or "").lower()):
        return ""
    try:
        s = summary()
        cfg = config()
        return ("\n[CSM PLAN — OWNER-CONFIDENTIAL CONTEXT]\n"
                f"{s['card_line']}\n"
                f"Start date {cfg['start_date']} · next action: "
                f"{s['next_action']['item']}\n"
                "Rules: cohort vs steady-state ROI never blended; Y1 4x "
                "unattainable in every scenario; offset finances the hire, "
                "never changes her economics; director figures live in owner "
                "config only — never state them in any reply.\n"
                "[END CSM CONTEXT]\n")
    except Exception:
        return ""


# ── sentinel (owner-only lane — NEVER the shared feed) ──────────────────────

def sentinel_watch() -> dict:
    """Nightly: baseline freshness · book-ledger reconciliation · shared-store
    leak probe (memory facts sampled for CSM markers) · publish-state sanity.
    Findings land in kv csm:sentinel (rendered on /csm) + SENTINEL_QUEUE.md
    on failure — never the shared action feed."""
    out = {"at": str(today_sydney()), "checks": {}}
    problems = []
    try:
        b = csm_baselines.all_baselines()
        b1 = (b.get("b1_renewal") or {}).get("label", "")
        fresh = b1.startswith("measured")
        out["checks"]["baseline_freshness"] = {"ok": True, "b1": b1}
        if not fresh:
            problems.append("B1 renewal baseline unmeasured/stale")
        ledger = (b.get("b4_book") or {}).get("ledger") or {}
        out["checks"]["book_ledger"] = {
            "ok": bool(ledger.get("members")),
            "members": len(ledger.get("members") or [])}
    except Exception as e:
        out["checks"]["baselines"] = {"ok": False, "error": str(e)[:80]}
        problems.append(f"baseline check errored: {str(e)[:60]}")
    # leak probe: sample the SHARED memory store for CSM markers
    leak = {"ok": True, "hits": 0}
    try:
        import db
        facts = db.active_facts(limit=60) if db.db_configured() else []
        markers = re.compile(r"csm|client success manager|director comp", re.I)
        hits = [f for f in facts
                if markers.search(str(f.get("fact") or ""))]
        leak = {"ok": not hits, "hits": len(hits), "at": str(today_sydney())}
        if hits:
            problems.append(f"{len(hits)} CSM-marker facts in SHARED memory "
                            "— scrub via the memory admin")
    except Exception as e:
        leak = {"ok": None, "error": str(e)[:80], "at": str(today_sydney())}
    out["checks"]["leak_probe"] = leak
    state = kv_store.get(_KV_SENTINEL) or {}
    state.update({"last_run": out, "leak_probe": leak})
    kv_store.put(_KV_SENTINEL, state)
    if problems:
        try:
            import ad_sentinel
            ad_sentinel.queue_item("CSM sentinel findings",
                                   " · ".join(problems)[:300], rank="P2")
        except Exception:
            pass
    out["ok"] = not problems
    out["problems"] = problems
    return out


def sentinel_state() -> dict:
    return kv_store.get(_KV_SENTINEL) or {}
