"""
manual_targets.py
-----------------
Rydel-set TARGETS / BENCHMARKS / GOALPOSTS / ASSUMPTIONS / NOTES — values with NO
live source. Rydel is the source of truth, so they are freely editable and
authoritative. This module owns the store, the defaults, and the natural-language
update flow (set / query / reset / note) with a confirmation loop.

OUT OF SCOPE (never touched here): live-sourced metrics (active clients, ad spend,
MRR, cash, ...) and Sheets write-back. There is no live source to mask and no
refresh conflict — a snapshot rebuild just reads this store and layers it on top.

Persistence: a JSON file on the Railway volume (/data), so a redeploy never wipes a
set target. Confirmation state ALSO lives in that file (keyed by auth token, TTL'd) —
gunicorn runs multiple workers, so a "yes" may hit a different worker than the "set".
All writes are auth-gated by the caller (dashboard auth).
"""
from __future__ import annotations

import json
import logging
import os
import re

from config import MANUAL_TARGETS_STORE
from helpers import now_sydney

logger = logging.getLogger(__name__)


# ── Defaults registry — documented defaults, units, and the metric each drives ──
# unit: "x" (ratio ×), "pct" (percent points, e.g. 45 = 45%), "days", "months",
#       "aud" ($), "note" (free text). value stored in the metric's NATIVE unit so
#       hormozi/consumers read it directly (gross margin in percent points, etc.).
DEFAULTS: dict[str, dict] = {
    "ltgp_cac_target":      {"default": 3.0,  "type": "target",    "unit": "x",   "label": "LTGP:CAC target"},
    "roas_target":          {"default": 3.0,  "type": "target",    "unit": "x",   "label": "ROAS target"},
    "payback_target":       {"default": 30,   "type": "target",    "unit": "days","label": "Payback target"},
    "gross_margin_floor":   {"default": 45.0, "type": "benchmark", "unit": "pct", "label": "Gross margin benchmark"},
    "gross_margin_target":  {"default": 50.0, "type": "target",    "unit": "pct", "label": "Gross margin healthy target"},
    "op_efficiency_target": {"default": 1.5,  "type": "target",    "unit": "x",   "label": "Operating efficiency target"},
    "speed_to_lead_target": {"default": 50.0, "type": "target",    "unit": "pct", "label": "Speed-to-lead target"},
    "qualified_revenue_floor": {"default": 20000.0, "type": "benchmark", "unit": "aud",
                                "label": "Qualified revenue floor (monthly, band lower bound)"},
    # Ad-dashboard flag thresholds (AD_DASHBOARD_REPORT Phase 0) — adjustable by voice.
    "ad_flag_spend_no_leads":  {"default": 150.0, "type": "benchmark", "unit": "aud", "label": "Ad flag: spend with zero leads"},
    "ad_flag_leads_no_sets":   {"default": 8,     "type": "benchmark", "unit": "x",   "label": "Ad flag: leads with zero sets"},
    "ad_flag_show_floor_pct":  {"default": 40.0,  "type": "benchmark", "unit": "pct", "label": "Ad flag: show-rate floor"},
    "ad_flag_qual_dev_pts":    {"default": 25.0,  "type": "benchmark", "unit": "pct", "label": "Ad flag: qualified%% deviation"},
    "ad_flag_cpl_mult":        {"default": 2.0,   "type": "benchmark", "unit": "x",   "label": "Ad flag: CPL outlier multiple"},
    "ad_flag_attr_drop_pts":   {"default": 10.0,  "type": "benchmark", "unit": "pct", "label": "Ad flag: attribution-rate drop"},
    "ad_flag_unknown_rev_pct": {"default": 20.0,  "type": "benchmark", "unit": "pct", "label": "Ad flag: revenue-unknown share"},
    "ad_flag_reach_floor_pct": {"default": 40.0,  "type": "benchmark", "unit": "pct", "label": "Ad flag: qualified reach-rate floor"},
    "reached_call_seconds":    {"default": 60,    "type": "benchmark", "unit": "x",   "label": "Reached: connected-call seconds"},
    "set_call_seconds":        {"default": 120,   "type": "benchmark", "unit": "x",   "label": "Spine T3: conversation-call seconds"},
    "set_to_show_target":   {"default": 70.0, "type": "target",    "unit": "pct", "label": "Set→Show target"},
    "show_to_close_target": {"default": 35.0, "type": "target",    "unit": "pct", "label": "Show→Close target"},
    # Goalposts that may not be consumed by a metric yet — still settable + shown.
    "runway_goal":          {"default": None, "type": "goalpost",  "unit": "months","label": "Runway goal"},
    "mrr_goal":             {"default": None, "type": "goalpost",  "unit": "aud", "label": "MRR goal"},
    "cac_ceiling":          {"default": None, "type": "goalpost",  "unit": "aud", "label": "CAC ceiling"},
    "growth_assumption":    {"default": None, "type": "assumption","unit": "pct", "label": "Monthly growth assumption"},
}

# Field-name aliases → canonical key. Matched against the user's phrase.
_FIELD_ALIASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ltgp[ :/-]*cac|ltgp\s*to\s*cac|gross profit.*cac", re.I), "ltgp_cac_target"),
    (re.compile(r"\broas\b|return on ad spend", re.I), "roas_target"),
    (re.compile(r"payback", re.I), "payback_target"),
    (re.compile(r"gross margin (healthy|target)|healthy (gross )?margin", re.I), "gross_margin_target"),
    (re.compile(r"gross margin( benchmark| floor)?|\bmargin\b", re.I), "gross_margin_floor"),
    (re.compile(r"op(erating)? efficiency|revenue per .*cost", re.I), "op_efficiency_target"),
    (re.compile(r"speed[ -]?to[ -]?lead|5[ -]?min", re.I), "speed_to_lead_target"),
    (re.compile(r"set[ -]?to[ -]?show", re.I), "set_to_show_target"),
    (re.compile(r"show[ -]?to[ -]?close|close rate", re.I), "show_to_close_target"),
    (re.compile(r"runway", re.I), "runway_goal"),
    (re.compile(r"mrr (goal|target)|monthly recurring", re.I), "mrr_goal"),
    (re.compile(r"cac (ceiling|max|cap)", re.I), "cac_ceiling"),
    (re.compile(r"growth", re.I), "growth_assumption"),
]

_AFFIRM = re.compile(r"^\s*(yes|yep|yeah|yup|confirm(ed)?|do it|go|go ahead|sure|ok(ay)?|correct|right)\b", re.I)
_DENY = re.compile(r"^\s*(no|nope|nah|cancel|stop|leave it|don'?t|never ?mind|forget it)\b", re.I)

# A genuine QUESTION never triggers a set-command, even if it contains a metric + a number
# ("can we afford to change our LTGP:CAC to 3?" is analysis, not target-setting).
_QUESTION_RE = re.compile(
    r"\b(can (we|i|you)|could (we|i)|should (we|i)|would (it|we)|what if|what would|"
    r"how (much|many|do|would|will|about|long|is|are)|do (we|i)|are we|is (it|that|this)|"
    r"afford|worth (it)?|makes sense|thoughts on|feasible)\b", re.I)
# An explicit target-noun signals target-setting intent (vs a cost/salary "raise").
_TARGET_NOUN = re.compile(r"\b(target|benchmark|ceiling|goalpost|floor|assumption|\bgoal\b)\b", re.I)
# Explicit SET verbs — deliberately EXCLUDES bump/raise/lower/push (those are cost/salary verbs
# that appear in affordability questions, not target-setting).
_SET_VERB = re.compile(r"\b(set|change|update|move|put|adjust|lock (in )?|make .* (the )?(target|benchmark|ceiling))\b", re.I)


# ── Store I/O ────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if os.path.exists(MANUAL_TARGETS_STORE):
            with open(MANUAL_TARGETS_STORE) as f:
                d = json.load(f)
                if isinstance(d, dict):
                    d.setdefault("values", {})
                    d.setdefault("history", [])
                    d.setdefault("pending", {})
                    return d
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("manual_targets store unreadable: %s", e)
    return {"values": {}, "history": [], "pending": {}}


# Confirmation state lives in the STORE (a shared file), not in process memory —
# gunicorn runs multiple workers, so a "yes" can land on a different worker than the
# "set". A pending change older than this many seconds is treated as expired.
_PENDING_TTL_SECONDS = 600


def _get_pending(token: str):
    store = _load()
    pend = store.get("pending", {}).get(token)
    if not pend:
        return None
    at = pend.get("at")
    if at:
        try:
            from datetime import datetime
            age = (now_sydney() - datetime.fromisoformat(at)).total_seconds()
            if age > _PENDING_TTL_SECONDS:
                _clear_pending(token)
                return None
        except (ValueError, TypeError):
            pass
    return pend


def _set_pending(token: str, pend: dict) -> None:
    store = _load()
    pend = {**pend, "at": now_sydney().isoformat()}
    store.setdefault("pending", {})[token] = pend
    _save(store)


def _clear_pending(token: str) -> None:
    store = _load()
    if token in store.get("pending", {}):
        del store["pending"][token]
        _save(store)


def _save(store: dict) -> None:
    try:
        os.makedirs(os.path.dirname(MANUAL_TARGETS_STORE) or ".", exist_ok=True)
        with open(MANUAL_TARGETS_STORE, "w") as f:
            json.dump(store, f, indent=2)
    except OSError as e:
        logger.error("manual_targets not persisted: %s", e)


# ── Resolution (defaults + overrides) ────────────────────────────────────────

def get_resolved() -> dict:
    """{key: value} with Rydel's overrides on top of defaults. For hormozi etc.

    None-valued (unset, no default) keys are omitted so consumers keep their own
    benchmark only when nothing is set.
    """
    store = _load()
    out = {}
    for key, meta in DEFAULTS.items():
        val = store["values"].get(key, {}).get("value", meta["default"])
        if val is not None:
            out[key] = val
    return out


def get_all() -> dict:
    """Full view for the dashboard/settings panel: value, default, set_by, set_at,
    type, unit, label, and whether it's user-set."""
    store = _load()
    out = {}
    for key, meta in DEFAULTS.items():
        rec = store["values"].get(key, {})
        is_set = "value" in rec
        out[key] = {
            "value": rec.get("value", meta["default"]),
            "default": meta["default"],
            "type": meta["type"],
            "unit": meta["unit"],
            "label": meta["label"],
            "is_user_set": is_set,
            "set_by": rec.get("set_by"),
            "set_at": rec.get("set_at"),
        }
    # Notes are free-form, stored under a reserved key list.
    out["_notes"] = store["values"].get("_notes", {}).get("items", [])
    return out


def history(limit: int = 50) -> list:
    return _load()["history"][-limit:][::-1]


# ── Formatting + parsing helpers ─────────────────────────────────────────────

def fmt_value(key: str, value) -> str:
    if value is None:
        return "unset"
    unit = DEFAULTS.get(key, {}).get("unit", "")
    if unit == "x":
        return f"{value:g}×"
    if unit == "pct":
        return f"{value:g}%"
    if unit == "days":
        return f"{value:g} days"
    if unit == "months":
        return f"{value:g} months"
    if unit == "aud":
        return f"${value:,.0f}"
    return str(value)


def _resolve_field(text: str) -> str | None:
    for pat, key in _FIELD_ALIASES:
        if pat.search(text):
            return key
    return None


def _parse_value(text: str, unit: str):
    """Parse a numeric value from the phrase in the field's native unit.

    50% / 50 percent → 50.0 (pct).  3.5 / 3.5x → 3.5 (x).  $4,000 / 4k → 4000 (aud).
    6 months → 6 (months).  Returns None if no number found.
    """
    t = text.replace(",", "")
    # k-suffix money: "4k", "100k"
    mk = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*k\b", t, re.I)
    if mk and unit == "aud":
        return float(mk.group(1)) * 1000
    m = re.search(r"(-?\d+(?:\.\d+)?)", t)
    if not m:
        return None
    val = float(m.group(1))
    return val


# ── The update flow (set / query / reset / note) with confirmation ───────────



def handle_turn(text: str, token: str, set_by: str = "Rydel") -> tuple[str | None, bool]:
    """Parse a manual-target command from a chat/voice turn.

    Returns (reply, handled). handled=False → not a target command; the caller
    falls through to the model. handled=True with a reply → short-circuit (no model).
    Confirmation loop: a SET/RESET stashes a pending change and echoes it; the next
    affirmative turn commits, a negative cancels.
    """
    if not text or not text.strip():
        return None, False
    t = text.strip()

    # 1) Resolve a pending confirmation first.
    pend = _get_pending(token)
    if pend:
        if _AFFIRM.match(t):
            _commit(pend, set_by)
            _clear_pending(token)
            if pend["action"] == "reset":
                return (f"Done — {pend['label']} reset to its default "
                        f"({fmt_value(pend['key'], pend['new'])}).", True)
            if pend["action"] == "note":
                return (f"Noted: “{pend['new']}”", True)
            return (f"Done — {pend['label']} is now {fmt_value(pend['key'], pend['new'])} "
                    f"(was {fmt_value(pend['key'], pend['old'])}).", True)
        if _DENY.match(t):
            _clear_pending(token)
            return (f"Okay — leaving {pend['label']} at "
                    f"{fmt_value(pend['key'], pend['old'])}.", True)
        # Neither yes nor no while a change is pending. Only re-ask if the turn is a bare/short
        # ambiguous reply; anything that reads as a fresh question or command SUPERSEDES the pending
        # (drop it, fall through) so a real question is never hijacked by a stale confirmation.
        looks_fresh = bool(_QUESTION_RE.search(t)) or len(t.split()) > 4 or \
            re.search(r"\b(target|benchmark|goal|set|note|reset|change|update)\b", t, re.I)
        if not looks_fresh:
            return (f"I still have {pend['label']} → {fmt_value(pend['key'], pend['new'])} "
                    f"waiting — yes to confirm, or no to cancel.", True)
        _clear_pending(token)  # a fresh question/command supersedes the pending confirmation

    low = t.lower()

    # 2) NOTE: "note: ..." / "add a note ..." / "note on the brief ..."
    mnote = re.match(r"\s*(?:add a |make a )?note(?:\s+on[\w \-]*)?\s*[:\-]\s*(.+)", t, re.I)
    if mnote:
        note_text = mnote.group(1).strip()
        _set_pending(token, {"action": "note", "key": "_notes", "label": "note",
                           "old": None, "new": note_text})
        return (f"Add this note — “{note_text}”? (yes/no)", True)

    # 3) QUERY: "what's my LTGP:CAC target" / "what targets have I set"
    if re.search(r"\b(what(?:'s| is| are)?|show|list|tell me)\b", low) and \
       re.search(r"\b(target|targets|benchmark|benchmarks|goal|goalpost|assumption|set)\b", low):
        if re.search(r"\b(all|targets|benchmarks|everything|set so far|have i set)\b", low) and not _resolve_field(t):
            return _summary_reply(), True
        key = _resolve_field(t)
        if key:
            cur = get_resolved().get(key, DEFAULTS[key]["default"])
            allv = get_all()[key]
            tag = (f"set by {allv['set_by']}" if allv["is_user_set"] else "default")
            return (f"{DEFAULTS[key]['label']} is {fmt_value(key, cur)} ({tag}).", True)
        return ("Which one — LTGP:CAC, ROAS, gross margin, payback, op-efficiency, "
                "speed-to-lead, runway, MRR goal, or CAC ceiling?", True)

    # 4) RESET: "reset the gross margin benchmark to default"
    if re.search(r"\breset\b|back to default|to default", low):
        key = _resolve_field(t)
        if not key:
            return ("Reset which one? Name the target or benchmark "
                    "(e.g. “reset the gross margin benchmark”).", True)
        old = get_resolved().get(key, DEFAULTS[key]["default"])
        _set_pending(token, {"action": "reset", "key": key, "label": DEFAULTS[key]["label"],
                           "old": old, "new": DEFAULTS[key]["default"]})
        return (f"Reset {DEFAULTS[key]['label']} to default "
                f"({fmt_value(key, DEFAULTS[key]['default'])})? (yes/no)", True)

    # 5) SET: "set the LTGP:CAC target to 3.5" / "move the gross margin benchmark to 50%".
    # Fires ONLY on explicit target-setting: a KNOWN dashboard-target metric (the strongest gate —
    # salary/cost/person questions name no metric) + a number + (a target-noun OR an explicit set
    # verb), and NOT phrased as a question. This keeps genuine financial questions with numbers
    # ("can we afford to bump SMM to 35k, push Gabie to 40k") OUT of the command path.
    # Fire on a target-noun (explicit target-setting, even if the metric is unnamed → we ask which),
    # OR an explicit set-verb applied to a KNOWN metric. A bare set-verb with NO target-noun and NO
    # known metric ("change SMM salary to 35k") is NOT target-setting → falls through to analysis.
    if (not _QUESTION_RE.search(low)) and re.search(r"\d", t) and \
       (_TARGET_NOUN.search(low) or (_SET_VERB.search(low) and _resolve_field(t))):
        key = _resolve_field(t)
        if not key:
            return ("Which target? Say e.g. “set the LTGP:CAC target to 3.5”, "
                    "“gross margin benchmark to 50%”, or “CAC ceiling to 4000”.", True)
        unit = DEFAULTS[key]["unit"]
        val = _parse_value(t, unit)
        if val is None:
            return (f"What value for the {DEFAULTS[key]['label']}? I didn't catch a number.", True)
        old = get_resolved().get(key, DEFAULTS[key]["default"])
        _set_pending(token, {"action": "set", "key": key, "label": DEFAULTS[key]["label"],
                           "old": old, "new": val})
        old_str = fmt_value(key, old) if old is not None else "unset"
        return (f"Setting {DEFAULTS[key]['label']} from {old_str} to {fmt_value(key, val)} "
                f"— confirm? (yes/no)", True)

    # 6) "assume 8% monthly growth" (no explicit "set")
    if re.search(r"\bassum\w*\b", low) and re.search(r"\d", t):
        key = "growth_assumption"
        val = _parse_value(t, "pct")
        if val is not None:
            old = get_resolved().get(key, DEFAULTS[key]["default"])
            _set_pending(token, {"action": "set", "key": key, "label": DEFAULTS[key]["label"],
                               "old": old, "new": val})
            old_str = fmt_value(key, old) if old is not None else "unset"
            return (f"Setting {DEFAULTS[key]['label']} from {old_str} to {fmt_value(key, val)} "
                    f"— confirm? (yes/no)", True)

    return None, False


def _commit(pend: dict, set_by: str) -> None:
    store = _load()
    ts = now_sydney().isoformat()
    if pend["action"] == "note":
        notes = store["values"].setdefault("_notes", {"items": []})
        notes["items"].append({"text": pend["new"], "set_by": set_by, "set_at": ts})
        store["history"].append({"field": "_notes", "old": None, "new": pend["new"],
                                 "set_by": set_by, "set_at": ts, "action": "note"})
    else:
        key = pend["key"]
        store["values"][key] = {"value": pend["new"], "set_by": set_by, "set_at": ts}
        store["history"].append({"field": key, "old": pend["old"], "new": pend["new"],
                                 "set_by": set_by, "set_at": ts, "action": pend["action"]})
    _save(store)


def set_value(key: str, value, set_by: str = "Rydel") -> dict:
    """Direct programmatic set (used by the settings panel / API). No confirmation."""
    if key not in DEFAULTS:
        raise KeyError(key)
    pend = {"action": "set", "key": key, "label": DEFAULTS[key]["label"],
            "old": get_resolved().get(key, DEFAULTS[key]["default"]), "new": value}
    _commit(pend, set_by)
    return get_all()[key]


def reset_value(key: str, set_by: str = "Rydel") -> dict:
    store = _load()
    if key in store["values"]:
        old = store["values"][key].get("value")
        del store["values"][key]
        store["history"].append({"field": key, "old": old, "new": DEFAULTS[key]["default"],
                                 "set_by": set_by, "set_at": now_sydney().isoformat(),
                                 "action": "reset"})
        _save(store)
    return get_all().get(key, {})


def _summary_reply() -> str:
    allv = get_all()
    setv = [(k, v) for k, v in allv.items() if k != "_notes" and v.get("is_user_set")]
    if not setv:
        return "You haven't set any custom targets yet — everything's on defaults."
    parts = [f"{v['label']} {fmt_value(k, v['value'])}" for k, v in setv]
    return "You've set: " + "; ".join(parts) + "."
