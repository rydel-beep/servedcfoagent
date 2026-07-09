"""
capacity_engine.py
------------------
The who/when/what-can-we-afford engine. Turns signing velocity + payroll + Rydel's capacity
benchmarks into concrete, priced, constraint-aware hiring/raise reads. Every figure is deterministic
(one-engine: MRR from client_health, payroll from true_team_cost, velocity from unit_economics,
churn from the roster). Benchmarks are Rydel's judgment inputs (kv_store, "set by you", voice-tunable).

HORMOZI SYNTHESIS (locked):
1. CONSTRAINT FIRST — churn is the binding constraint; the engine can say "don't hire, fix the leak".
2. HIRE AHEAD OF THE BREAKPOINT — trigger on PROJECTED load at (now + hiring lead time).
3. AFFORDABILITY — payroll:MRR < 40% hard gate; live hiring budget = MRR×40% − payroll.
4. KEEP A-PLAYERS — raise SIGNALS (tenure/load/affordability), never performance verdicts.

HONEST BOUNDARIES: department-level load only (no client→person assignment data — per-person is
phase-2); raises are signals+pricing, never merit rankings; morale is never claimed as measured;
salaries are owner-only, never in memory/logs.
"""
from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_K_BENCH = "capacity:benchmarks"

# Rydel-locked defaults (2026-07-09). Stored/overridable via kv_store; labelled "set by you".
DEFAULT_BENCHMARKS = {
    "smm_full_time": 7,       # clients one full-time SMM handles well
    "smm_part_time": 4.5,     # part-time SMM (Rydel: 4–5, midpoint)
    "ads_per_head": 10,       # accounts one ads manager runs well
    "threshold_pct": 85,      # load % that flags "start hiring"
    "lead_time_weeks": 5,     # hiring lead time
    "churn_gate_per_month": 2,  # >this/mo → recommendations lead with retention math
    "payroll_ratio_ceiling_pct": 40,  # hard affordability gate
    "php_per_aud": 43,        # labelled FX for PHP salary pricing
}

# Which SALARY-tab departments scale with client count (capacity-modelled). Others = overhead.
_CAPACITY_DEPTS = {"smm": ["smm"], "ads": ["paid ads", "ads"]}


def benchmarks() -> dict:
    b = dict(DEFAULT_BENCHMARKS)
    b.update(kv_store.get(_K_BENCH) or {})
    return b


def set_benchmark(key: str, value) -> bool:
    if key not in DEFAULT_BENCHMARKS:
        return False
    cur = kv_store.get(_K_BENCH) or {}
    cur[key] = value
    kv_store.put(_K_BENCH, cur)
    return True


# ── Inputs from the one engines ──────────────────────────────────────────────

def _team() -> list[dict]:
    try:
        import salary_view
        return (salary_view.read_salaries() or {}).get("people") or []
    except Exception:
        return []


def _active_clients(snap: dict) -> int | None:
    ac = (snap.get("active_clients") or {}).get("active_count")
    if ac is None:
        ac = (snap.get("client_health") or {}).get("active_count")
    return ac


def _mrr(snap: dict) -> float | None:
    return (snap.get("client_health") or {}).get("current_mrr")


def _true_team_cost(snap: dict) -> float | None:
    oe = (snap.get("hormozi") or {}).get("op_efficiency") or snap.get("op_efficiency") or {}
    v = (oe.get("inputs_used") or {}).get("true_team_cost")
    if v is not None:
        return v
    tm = snap.get("team_model") or {}
    return tm.get("total_with_owner")


def _owner_gross(snap: dict) -> float:
    return (snap.get("team_model") or {}).get("owner_gross_monthly") or 0.0


def _status(p: dict) -> str:
    s = (p.get("status") or "").strip().lower()
    if "part" in s:
        return "part_time"
    if "full" in s:
        return "full_time"
    return "other"   # External / contractor — excluded from capacity headcount


# ── Phase 1: department capacity/load ────────────────────────────────────────

def department_load(snap: dict) -> list[dict]:
    """Per capacity department: headcount, capacity (from benchmarks), clients carried, load %,
    headroom. Department-level only (no per-person assignment data)."""
    b = benchmarks()
    active = _active_clients(snap) or 0
    team = _team()
    out = []

    # SMM — capacity is per-status (Rydel's model). Clients served = all active (every package
    # includes social); labelled assumption, flips to per-client once assignment data exists.
    smm = [p for p in team if (p.get("dept") or "").strip().lower() in _CAPACITY_DEPTS["smm"]]
    ft = sum(1 for p in smm if _status(p) == "full_time")
    pt = sum(1 for p in smm if _status(p) == "part_time")
    smm_cap = ft * b["smm_full_time"] + pt * b["smm_part_time"]
    if smm:
        load = round(active / smm_cap * 100, 1) if smm_cap else None
        out.append({
            "dept": "SMM (delivery)", "headcount": len(smm), "full_time": ft, "part_time": pt,
            "capacity": smm_cap, "clients_carried": active, "load_pct": load,
            "headroom_clients": round(smm_cap - active, 1) if smm_cap else None,
            "benchmark": f"FT {b['smm_full_time']} / PT {b['smm_part_time']} clients (set by you)",
            "assumption": "SMM services all active clients (every package includes social)",
        })

    # Ads — per-head benchmark. Every client runs ads (Rydel-confirmed 2026-07-09), so ads-client
    # count = active clients; this is a real load signal, not an upper-bound estimate.
    ads = [p for p in team if (p.get("dept") or "").strip().lower() in _CAPACITY_DEPTS["ads"]]
    if ads:
        ads_cap = len(ads) * b["ads_per_head"]
        load = round(active / ads_cap * 100, 1) if ads_cap else None
        out.append({
            "dept": "Paid Ads", "headcount": len(ads), "capacity": ads_cap,
            "clients_carried": active, "load_pct": load,
            "headroom_clients": round(ads_cap - active, 1) if ads_cap else None,
            "benchmark": f"{b['ads_per_head']} accounts per manager (set by you)",
            "assumption": "every client runs ads (Rydel-confirmed) — ads clients = active clients",
        })
    return out


# ── Phase 2: net velocity + hire trigger ─────────────────────────────────────

def churn_in_window(days: int, snap: dict | None = None) -> int:
    """Clients whose roster End Date falls in the last `days` (+ chat churn overrides). Deterministic."""
    n = 0
    try:
        import sheet_mirror
        from config import FINANCE_SHEET_CONFIG
        rows = sheet_mirror.read_by_gid(1407663952)
        if not rows:
            rows = sheet_mirror._live_fetch(FINANCE_SHEET_CONFIG["sheet_id"], "Health (roster)", gid=1407663952)
        today = today_sydney()
        cutoff = today - dt.timedelta(days=days - 1)
        for r in (rows or [])[1:]:
            if len(r) > 5:
                ed = _parse_date(r[5])
                if ed and cutoff <= ed <= today:
                    n += 1
    except Exception as e:  # F4: log — a swallowed error must not read as "0 churn" silently
        logger.warning("churn_in_window roster read failed (%dd) — churn may be understated: %s", days, e)
    try:
        import client_overrides
        for o in client_overrides.active_overrides():
            if o.get("change_type") == "churn":
                ed = _parse_date(str(o.get("effective_date") or ""))
                if ed and (today_sydney() - ed).days < days:
                    n += 1
    except Exception as e:
        logger.info("churn_in_window override read failed (%dd): %s", days, e)
    return n


def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def net_velocity(snap: dict | None = None) -> dict:
    """closes − churn per 30/60/90d, monthly-normalised. Flags small-sample volatility."""
    from snapshot import load_persisted
    snap = snap or load_persisted() or {}
    import range_unit_economics as rue
    today = today_sydney()
    windows = {}
    for d in (30, 60, 90):
        r = rue.unit_economics(str(today - dt.timedelta(days=d - 1)), str(today))
        closes = (r.get("components") or {}).get("closes") or 0
        churn = churn_in_window(d, snap)
        per_month = (closes - churn) / (d / 30.0)
        windows[f"{d}d"] = {"closes": closes, "churn": churn,
                            "net": closes - churn, "net_per_month": round(per_month, 1),
                            "noisy": closes < 3}
    return windows


def hire_trigger(snap: dict) -> dict:
    """Fire when PROJECTED load at (now + lead time) ≥ threshold, using net velocity. Ahead of breakpoint."""
    b = benchmarks()
    depts = department_load(snap)
    vel = net_velocity(snap)
    lead_weeks = b["lead_time_weeks"]
    lead_months = lead_weeks / 4.345
    # Use the steadier 90d velocity as primary; show 30d for sensitivity.
    v90 = vel["90d"]["net_per_month"]
    v30 = vel["30d"]["net_per_month"]
    triggers = []
    for d in depts:
        cap = d.get("capacity")
        carried = d.get("clients_carried")
        if not cap or carried is None:
            continue
        projected = carried + v90 * lead_months
        proj_load = round(projected / cap * 100, 1)
        fired = proj_load >= b["threshold_pct"] or (d.get("load_pct") or 0) >= b["threshold_pct"]
        # weeks until threshold crossing at v90 (if positive velocity)
        weeks_to = None
        if v90 > 0:
            clients_to_threshold = cap * b["threshold_pct"] / 100 - carried
            weeks_to = round(max(clients_to_threshold, 0) / v90 * 4.345, 1)
        triggers.append({
            "dept": d["dept"], "current_load_pct": d.get("load_pct"),
            "projected_load_pct": proj_load, "fired": fired,
            "weeks_to_threshold": weeks_to, "net_per_month_90d": v90, "net_per_month_30d": v30,
            "noisy": vel["90d"]["noisy"] or vel["30d"]["noisy"],
        })
    triggers.sort(key=lambda t: t.get("current_load_pct") or 0, reverse=True)  # most urgent first
    return {"lead_time_weeks": lead_weeks, "threshold_pct": b["threshold_pct"], "triggers": triggers}


# ── Phase 3: affordability + hiring budget ───────────────────────────────────

def hiring_budget(snap: dict) -> dict:
    """(MRR × ceiling) − payroll = $/mo of salary you can add and stay under the ratio."""
    b = benchmarks()
    mrr = _mrr(snap)
    payroll = _true_team_cost(snap)
    ceiling = b["payroll_ratio_ceiling_pct"] / 100
    if mrr is None or payroll is None:
        return {"available": False, "reason": "MRR or payroll unavailable"}
    budget = round(mrr * ceiling - payroll, 2)
    ratio = round(payroll / mrr * 100, 1) if mrr else None
    owner = _owner_gross(snap)
    team_only = payroll - owner
    return {
        "available": True, "mrr": mrr, "payroll": payroll, "payroll_ratio_pct": ratio,
        "ceiling_pct": b["payroll_ratio_ceiling_pct"], "budget_monthly": budget,
        "over_ceiling": budget < 0,
        "team_only_payroll": round(team_only, 2),
        "team_only_ratio_pct": round(team_only / mrr * 100, 1) if mrr else None,
        "owner_gross": owner,
        "mrr_needed_for_ceiling": round(payroll / ceiling, 2),
    }


def price_hire(role_label: str, salary_aud_month: float, snap: dict) -> dict:
    """Price a proposed hire: new ratio, budget fit, MRR gap if over, marginal SMM capacity it buys."""
    b = benchmarks()
    hb = hiring_budget(snap)
    if not hb.get("available"):
        return {"available": False}
    new_payroll = hb["payroll"] + salary_aud_month
    mrr = hb["mrr"]
    new_ratio = round(new_payroll / mrr * 100, 1) if mrr else None
    fits = salary_aud_month <= hb["budget_monthly"]
    mrr_gap = None
    if not fits:
        mrr_needed = round(new_payroll / (b["payroll_ratio_ceiling_pct"] / 100), 2)
        mrr_gap = round(mrr_needed - mrr, 2)
    return {
        "available": True, "role": role_label, "salary_aud_month": round(salary_aud_month, 2),
        "new_payroll": round(new_payroll, 2), "new_ratio_pct": new_ratio,
        "fits_budget": fits, "budget_monthly": hb["budget_monthly"],
        "mrr_gap_to_afford": mrr_gap, "current_ratio_pct": hb["payroll_ratio_pct"],
    }


# ── Phase 4: the constraint check (the engine that can say "don't hire") ──────

def constraint_check(snap: dict) -> dict:
    """Churn vs hire — the binding-constraint lens. Every hire read carries the retention math; when
    churn is elevated it LEADS with it. Ranked levers (fix retention / hire / both), priced."""
    b = benchmarks()
    vel = net_velocity(snap)
    active = _active_clients(snap) or 0
    mrr = _mrr(snap) or 0
    churn_90 = vel["90d"]["churn"]
    churn_per_month = round(churn_90 / 3.0, 1)
    avg_mrr = round(mrr / active, 2) if active else 0
    mrr_lost_per_month = round(churn_per_month * avg_mrr, 2)
    gate = b["churn_gate_per_month"]
    elevated = churn_per_month > gate

    levers = []
    if elevated:
        halved_saves = round(mrr_lost_per_month / 2, 2)
        levers.append({
            "lever": "fix retention", "priority": 1,
            "read": (f"You're churning ~{churn_per_month} clients/mo (≈${mrr_lost_per_month:,.0f}/mo MRR). "
                     f"Cutting that in half recovers ~${halved_saves:,.0f}/mo AND frees delivery "
                     "capacity — cheaper than buying more. Churn is your binding constraint.")})
        levers.append({"lever": "hire delivery", "priority": 2,
                       "read": "Still valid if load stays high after retention improves — but not first."})
    else:
        levers.append({"lever": "hire when triggered", "priority": 1,
                       "read": (f"Churn is contained (~{churn_per_month}/mo, ≤ your {gate}/mo gate) — "
                                "capacity/velocity drives the hiring call, not retention.")})
    return {
        "churn_per_month": churn_per_month, "churn_gate_per_month": gate, "elevated": elevated,
        "avg_mrr_per_client": avg_mrr, "mrr_lost_per_month": mrr_lost_per_month,
        "levers": levers,
    }


# ── Phase 5: raise signals (signals + pricing, NEVER verdicts) ───────────────

def _last_raise(name: str) -> str | None:
    return (kv_store.get("capacity:last_raise") or {}).get(name)


def set_last_raise(name: str, date_str: str) -> None:
    d = kv_store.get("capacity:last_raise") or {}
    d[name] = date_str
    kv_store.put("capacity:last_raise", d)


def raise_signals(snap: dict) -> dict:
    """Per-person SIGNALS: tenure-since-raise (if seeded), department load, affordability headroom.
    Priced options (5/10/15%). NEVER a merit verdict — performance is Rydel's call. Owner-only."""
    b = benchmarks()
    hb = hiring_budget(snap)
    depts = {d["dept"]: d for d in department_load(snap)}
    team = _team()
    today = today_sydney()
    signals = []
    for p in team:
        dept = (p.get("dept") or "").strip().lower()
        aud = p.get("aud")
        if aud is None or _status(p) == "other":
            continue
        # department load context
        dl = None
        if dept in _CAPACITY_DEPTS["smm"]:
            dl = depts.get("SMM (delivery)", {}).get("load_pct")
        elif dept in _CAPACITY_DEPTS["ads"]:
            dl = depts.get("Paid Ads", {}).get("load_pct")
        lr = _last_raise(p.get("name", ""))
        months_since = None
        if lr:
            d = _parse_date(lr)
            if d:
                months_since = round((today - d).days / 30.4, 1)
        # a signal fires on: long tenure-since-raise OR sustained high dept load
        flagged = (months_since is not None and months_since >= 12) or (dl is not None and dl >= b["threshold_pct"])
        if not flagged and months_since is None and dl is None:
            continue
        options = {f"{pct}%": round(aud * pct / 100, 2) for pct in (5, 10, 15)}
        signals.append({
            "name": p.get("name"), "role": p.get("role"), "dept": p.get("dept"),
            "current_aud": aud, "months_since_raise": months_since,
            "dept_load_pct": dl, "flagged": flagged,
            "raise_options_aud_month": options,
            "last_raise_known": lr is not None,
        })
    return {"signals": signals,
            "framing": "These are SIGNALS for your judgment — performance is your call; I never rank "
                       "people by merit or say anyone 'deserves' a raise.",
            "budget_note": (f"Hiring/raise budget: ${hb['budget_monthly']:,.0f}/mo before the "
                            f"{hb['ceiling_pct']}% ceiling." if hb.get("available") else None),
            "missing_last_raise": [s["name"] for s in signals if not s["last_raise_known"]]}


# ── Assembled block ──────────────────────────────────────────────────────────

def build_capacity(snap: dict) -> dict:
    """The whole Team & Capacity block for the snapshot/dashboard. Deterministic; owner-only surface."""
    try:
        return {
            "available": True,
            "benchmarks": benchmarks(),
            "department_load": department_load(snap),
            "net_velocity": net_velocity(snap),
            "hire_trigger": hire_trigger(snap),
            "hiring_budget": hiring_budget(snap),
            "constraint": constraint_check(snap),
        }
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}


# ── Conversational handlers (TIER 2, deterministic — figures verbatim) ────────

import re as _re


def _snap():
    from snapshot import load_persisted
    return load_persisted() or {}


def _money_aud(text: str, snap: dict) -> tuple[float | None, str]:
    """Parse a salary from text → AUD/month + a label. Handles 'k', '$', and 'PHP'/'peso'."""
    b = benchmarks()
    m = _re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(k|php|peso|₱|aud|\$)?", text, _re.I)
    if not m:
        return None, ""
    val = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if "k" in unit:
        val *= 1000
    is_php = ("php" in text.lower() or "peso" in text.lower() or "₱" in text or unit in ("php", "peso", "₱"))
    if is_php:
        return round(val / b["php_per_aud"], 2), f"₱{val:,.0f} (≈A${val / b['php_per_aud']:,.0f}/mo at ₱{b['php_per_aud']}/A$1)"
    return val, f"A${val:,.0f}/mo"


def _fmt_trigger(hb_t: dict) -> str:
    b = benchmarks()
    lines = []
    for t in hb_t["triggers"]:
        base = f"{t['dept']}: {t['current_load_pct']}% load now"
        if t["fired"]:
            wk = t.get("weeks_to_threshold")
            when = "already at/over threshold" if (t["current_load_pct"] or 0) >= b["threshold_pct"] else (
                f"crosses {b['threshold_pct']}% in ~{wk} weeks" if wk is not None else "projected to cross soon")
            base += (f" → at net +{t['net_per_month_90d']}/mo you {when}. Lead time is "
                     f"{b['lead_time_weeks']} weeks — START HIRING.")
        else:
            base += f" → net +{t['net_per_month_90d']}/mo, projected {t['projected_load_pct']}% at +{b['lead_time_weeks']}wks. Headroom remains."
        if t.get("noisy"):
            base += " (few closes — projection is noisy.)"
        if t['net_per_month_30d'] != t['net_per_month_90d']:
            base += f" [30d velocity reads +{t['net_per_month_30d']}/mo — {'steadier on 90d' if t.get('noisy') else 'watch the gap'}.]"
        lines.append(base)
    return " ".join(lines)


def handle_capacity_command(text: str) -> tuple[str | None, bool]:
    """Routes the capacity/hiring/raise questions. Deterministic; owner-only (auth already enforced)."""
    if not text:
        return None, False
    low = text.lower()

    # set a benchmark by voice: "set SMM capacity to 6", "set the hiring threshold to 80"
    ms = _re.search(r"\bset (the )?(smm|ads|part[- ]?time|full[- ]?time|hiring )?\s*(capacity|threshold|"
                    r"lead time|churn gate)\b.*?(\d+(?:\.\d+)?)", low)
    if ms:
        val = float(ms.group(4))
        kind, target = ms.group(2) or "", ms.group(3)
        key = None
        if "threshold" in target:
            key = "threshold_pct"
        elif "lead" in target:
            key = "lead_time_weeks"
        elif "churn" in target:
            key = "churn_gate_per_month"
        elif "capacity" in target:
            key = ("smm_part_time" if "part" in kind else "smm_full_time" if ("smm" in kind or "full" in kind)
                   else "ads_per_head" if "ads" in kind else "smm_full_time")
        if key and set_benchmark(key, val):
            return f"Set — {key.replace('_', ' ')} is now {val} (your input; I'll compute from it).", True

    snap = _snap()

    # affordability: "can we afford a new SMM at 35k PHP" / "afford a hire at $1200"
    if _re.search(r"\b(afford|can we (hire|add)|priced?|price a hire|cost to hire)\b", low) or \
       (_re.search(r"\bhire\b", low) and _re.search(r"\d", low) and _re.search(r"\b(at|for)\b", low)):
        sal, lbl = _money_aud(text, snap)
        role = "new hire"
        rm = _re.search(r"\b(smm|ads|setter|closer|designer|editor|creative|manager|developer)\b", low)
        if rm:
            role = f"new {rm.group(1).upper() if len(rm.group(1)) <= 3 else rm.group(1)}"
        if sal is None:
            hb = hiring_budget(snap)
            if hb.get("available"):
                return (f"Your hiring budget is ${hb['budget_monthly']:,.0f}/mo before the "
                        f"{hb['ceiling_pct']}% ceiling (payroll:MRR is {hb['payroll_ratio_pct']}% now). "
                        "Tell me the salary and I'll price it."), True
            return "I can't read MRR/payroll right now to price that.", True
        pr = price_hire(role, sal, snap)
        cc = constraint_check(snap)
        if not pr.get("available"):
            return "I can't read MRR/payroll right now to price that.", True
        if pr["fits_budget"]:
            base = (f"{role} at {lbl}: new payroll ratio {pr['new_ratio_pct']}% — fits under your "
                    f"{benchmarks()['payroll_ratio_ceiling_pct']}% ceiling (budget ${pr['budget_monthly']:,.0f}/mo).")
        else:
            base = (f"{role} at {lbl}: that pushes payroll:MRR to {pr['new_ratio_pct']}%, over your "
                    f"{benchmarks()['payroll_ratio_ceiling_pct']}% ceiling. You're ${abs(pr['budget_monthly']):,.0f}/mo "
                    f"over already — you'd need +${pr['mrr_gap_to_afford']:,.0f} MRR first "
                    f"(≈{_closes_for(pr['mrr_gap_to_afford'], snap)} closes).")
        if cc["elevated"]:
            base += " " + cc["levers"][0]["read"]
        return base, True

    # hiring budget
    if _re.search(r"\b(hiring budget|salary budget|how much.*(salary|hire|spend on (the )?team)|"
                  r"room (to|for) hire|can we spend)\b", low):
        hb = hiring_budget(snap)
        if not hb.get("available"):
            return "I can't read MRR/payroll right now.", True
        if hb["over_ceiling"]:
            return (f"No headroom — payroll:MRR is {hb['payroll_ratio_pct']}% (incl. your gross; "
                    f"{hb['team_only_ratio_pct']}% team-only), already over the {hb['ceiling_pct']}% "
                    f"ceiling. You'd need MRR at ${hb['mrr_needed_for_ceiling']:,.0f} (vs ${hb['mrr']:,.0f} "
                    f"now) to add a salary and stay under."), True
        return (f"Hiring budget: ${hb['budget_monthly']:,.0f}/mo of salary before you hit the "
                f"{hb['ceiling_pct']}% ceiling (payroll:MRR is {hb['payroll_ratio_pct']}% now)."), True

    # when to hire / next hire
    if _re.search(r"\bwhen.*(hire|need.*(someone|help)|next hire)\b|\bnext hire\b|\bdo i need to hire\b|"
                  r"\btime to hire\b", low):
        ht = hire_trigger(snap)
        cc = constraint_check(snap)
        out = _fmt_trigger(ht)
        if cc["elevated"]:
            out = cc["levers"][0]["read"] + " " + out
        return out, True

    # hire or fix churn
    if _re.search(r"\b(hire or (fix )?churn|fix churn or hire|retention or.*hir|hire.*or.*retention)\b", low):
        cc = constraint_check(snap)
        return " ".join(f"{l['priority']}. {l['lever']} — {l['read']}" for l in cc["levers"]), True

    # who's closest to capacity / department load
    if _re.search(r"\bclosest to capacity\b|\b(department|dept) load\b|\bwho'?s (overloaded|stretched|"
                  r"at capacity|closest|drowning|swamped)\b|\bhow loaded\b|\bwhat'?s (the )?load\b|"
                  r"\b(team|department|dept) capacity\b|\bat capacity\b", low):
        depts = department_load(snap)
        if not depts:
            return "No capacity-modelled departments found in the roster.", True
        depts.sort(key=lambda d: d.get("load_pct") or 0, reverse=True)
        parts = [f"{d['dept']}: {d['load_pct']}% ({d['clients_carried']} clients ÷ {d['capacity']:.0f} "
                 f"capacity, {d['headcount']} people)" for d in depts]
        return "Department load (highest first): " + "; ".join(parts) + ".", True

    # raise signals
    if _re.search(r"\b(due for a raise|raise signals?|who.*(raise)|raises?)\b", low) and "afford" not in low:
        rs = raise_signals(snap)
        flagged = [s for s in rs["signals"] if s["flagged"]]
        if not flagged:
            miss = rs.get("missing_last_raise") or []
            base = "No raise signals firing right now (dept load below threshold)."
            if miss:
                base += " I don't have last-raise dates on file — tell me when you last raised someone and I'll track tenure."
            return base + " " + rs["framing"], True
        parts = []
        for s in flagged[:5]:
            ten = f"{s['months_since_raise']}mo since last raise" if s.get("months_since_raise") else "tenure unknown"
            opt = s["raise_options_aud_month"]["10%"]
            parts.append(f"{s['role']} ({ten}, dept load {s['dept_load_pct']}%): 10% = +${opt:,.0f}/mo")
        return ("Raise signals — " + "; ".join(parts) + ". " + rs["framing"]), True

    return None, False


def _closes_for(mrr_gap: float, snap: dict) -> int:
    """How many closes ≈ the MRR gap (avg contract/6mo as monthly)."""
    active = _active_clients(snap) or 1
    avg_mrr = (_mrr(snap) or 0) / active
    return max(1, round(mrr_gap / avg_mrr)) if avg_mrr else 0
