"""definitions.py — THE ONE DEFINITIONS REGISTRY (explain everything, once).

Rydel: "Lots of things I don't understand — I want hover pop-ups explaining
what they mean and do." Every rendered metric, control, chip, lane and lever
gets ONE plain-English entry here; the hover tooltips, tap sheets, ⓘ
drawers' headers, the legend page and EDITH's "explain this" ALL read this
registry — no tooltip text lives anywhere else.

TEAM LANGUAGE ONLY: no internal jargon in any entry (test-enforced grep —
no "cohort clock", "provenance", "min-n", "triad", "convergence",
"invariant" in user-facing text).

GRANULARITY RULING (documented, test-pinned): element-level for the modern
surfaces (the landing tiles/pulse/cards, /scale, the expiring panel, the
burn box, every ⓘ drawer); panel-level for the legacy area-page sections —
the section heading's entry explains the whole panel, and the panel's own
ⓘ icons keep their engine definitions underneath.

Entry fields: name · kind (metric/control/chip/lane/lever/panel/page) ·
screen · meaning (one sentence) · computed (in words) · changing (controls
only) · default_from · good ("benchmark, not target" where one exists) ·
selector (how defs.js finds it) · drawer (ⓘ key, when one exists).
"""

from __future__ import annotations

import json
import os
import re

_PATH = os.path.join(os.path.dirname(__file__), "definitions.json")

# words that must never reach the user's face (the ship-notes jargon grep)
JARGON = ("cohort clock", "provenance", "min-n", "triad", "convergence",
          "invariant", "kv store", "kv_store", "sentinel", "hormozi",
          "activity basis", "drawer registry", "fail-closed", "degraded[",
          "survivorship")


def load() -> dict:
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def entry(def_id: str) -> dict | None:
    return (load().get("entries") or {}).get(def_id)


def jargon_hits(text: str) -> list[str]:
    low = (text or "").lower()
    return [j for j in JARGON if j in low]


def coverage_inventory() -> dict:
    """The list of ids the registry MUST cover, built from the code itself —
    100% or the build fails (the coverage test calls this)."""
    inv: dict[str, list[str]] = {}

    # landing — executive tiles + pulse + verdict + cards (owner set)
    from dashboard import exec_top
    inv["landing_tiles"] = [t["id"] for t in exec_top.build_tiles(None)]
    inv["landing_pulse"] = [t["id"] for t in exec_top.build_pulse()]
    inv["landing_verdict"] = ["exec_verdict"]
    inv["landing_cards"] = ["card_" + c["id"]
                            for c in exec_top.build_cards(None, owner=True,
                                                          csm_visible=True)]

    # legacy area sections (panel-level) + the compass panels
    part_dir = os.path.join(os.path.dirname(__file__), "templates", "partials")
    secs = set()
    for fn in os.listdir(part_dir):
        if fn.startswith("area_"):
            with open(os.path.join(part_dir, fn), encoding="utf-8") as f:
                secs.update(re.findall(r'<section\b[^>]*\bid="(section-[\w-]+)"',
                                       f.read()))
    inv["sections"] = sorted(secs)

    # burn box figures (projection page, server-rendered)
    inv["burn_box"] = ["burn_opex", "burn_tax", "burn_net", "burn_runway"]

    # expiring panel chips + controls
    inv["expiring"] = ["exp_toggle", "exp_chip_actual", "exp_chip_scenario",
                       "exp_chip_slider", "exp_window", "exp_effective"]

    # /scale — the simulator + chain + controls + views
    inv["scale_sim"] = ["sim_spend", "sim_cpl", "sim_leads", "sim_mode",
                        "sim_badge", "sim_cpl_mode", "sim_sentence",
                        "sim_chart"]
    inv["north_star"] = ["north_star", "ns_actual", "ns_plan", "ns_pace",
                         "ns_verdict", "ns_constraint", "ns_summary",
                         "ns_whatifs", "ns_callog", "ns_pinned"]
    # HOW WE'RE TRAVELLING — every element of the view
    inv["travelling"] = ["btn_travelling", "travelling", "tv_window",
                         "tv_compare", "tv_progress", "tv_verdict",
                         "tv_northstar", "tv_gap", "tv_read", "tv_setter",
                         "tv_checks", "tv_remodel", "tv_save", "tv_history"]
    import travelling as _TV
    inv["travelling_new"] = ["tv_show_range", "tv_outcome_status",
                             "tv_rate_status", "tv_gap_flip", "tv_identities",
                             "pitched_measured"]
    inv["health"] = ["section-estate-health"]
    inv["travelling_stages"] = ["tv_stage_" + sid for sid in
                                ("spend", "leads", "qualified", "booked", "due",
                                 "showed", "pitched", "closed", "contract", "cash")]
    inv["scale_chain"] = ["chain_calls", "chain_shows", "chain_clients",
                          "chain_cash", "chain_cost", "show_math", "i_want"]
    from dashboard.static_ctl_ids import SCALE_CTL_IDS  # thin list module
    inv["scale_controls"] = SCALE_CTL_IDS
    inv["scale_views"] = ["accuracy_sentence", "confidence_word", "presets",
                          "solver", "roadmap", "money_view", "team_view",
                          "hire_card", "ranges", "scenarios", "commit_plan",
                          "pacing", "calibration", "capital_dip",
                          "binding_constraint", "level_simple",
                          "level_advanced", "level_plan"]

    # TODAY — the moved tiles are already covered by landing_tiles; these are
    # the ones TODAY adds, plus its four panels.
    inv["today"] = ["week_flow", "ad_spend", "travelling_verdict",
                    "today_rulings", "today_since", "today_pulse"]

    # SALES — the scoreboard's columns and its three lists
    inv["sales_board"] = ["sales_leads", "sales_shows_confirmed", "sales_closes",
                          "sales_cash", "sales_ownership_fill", "sales_pipeline",
                          "sales_unmarked", "sales_upcoming"]

    # SYSTEM — the headline, the five sections, and the two owner actions
    inv["system"] = ["system_state", "browser_errors_24h", "system_sources",
                     "system_checks", "system_jobs", "system_gates",
                     "sys_run_checks", "refresh_now", "as_of_chip"]

    # EDITH on the page
    inv["edith"] = ["edith_dock", "edith_mic", "explain_this"]

    # the P&L ladder (#165)
    inv["pl"] = ["net_margin", "gross_margin", "contribution_margin",
                 "pl_waterfall", "pl_bridge", "pl_mapping_ctl",
                 "cash_net_window", "net_margin_contracted",
                 "net_margin_collected", "margin_gap", "collected_basis"]

    # the close pipeline (#161) + the close register and its ledger (#164)
    inv["closes"] = ["unmatched_payments", "closes_detected", "confirm_payer",
                     "owner_only_chip", "status_stale_finding",
                     "closes_count", "closes_cash", "closes_contract",
                     "record_a_close", "register_reconciliation"]

    # answer-shaped outputs + the resolver's visible surfaces (#168)
    inv["answers"] = ["total_costs", "per_day_pacing", "margin_delta",
                      "answered_as", "calc_endpoint"]

    # every ⓘ drawer key
    import tile_drawers
    inv["drawers"] = ["drawer_" + k for k in sorted(tile_drawers._REGISTRY)]
    inv["drawers"] += ["drawer_ltv_cac", "drawer_ltgp_cac"]

    return inv


def coverage_check() -> tuple[list[str], int]:
    """→ (missing ids, total required). Empty missing == 100%."""
    reg = set((load().get("entries") or {}).keys())
    missing, total = [], 0
    for _group, ids in coverage_inventory().items():
        for i in ids:
            total += 1
            if i not in reg:
                missing.append(i)
    return missing, total


# ── EDITH: "explain this" — she reads the registry + the live value ─────────

_EXPLAIN_RE = re.compile(r"\b(what (is|does|means)|explain|meaning of)\b(.+)",
                         re.I)

# "What IS cash on hand" asks what the words mean.
# "What's OUR cash on hand" asks for the number.
# Found by the dock gate: asking for the figure returned the definition,
# because the possessive reads as "what is …" to the matcher above.
_POSSESSIVE_RE = re.compile(
    r"\bwhat(?:'s| is| are)\s+(our|my|the)\b|\bhow much\b|\bhow many\b", re.I)


def handle_explain_command(text: str):
    t = text or ""
    if _POSSESSIVE_RE.search(t) and not re.search(r"\b(explain|meaning of)\b", t, re.I):
        # they want the figure, not the glossary — let the number path answer
        return None, False
    m = _EXPLAIN_RE.search(t)
    if not m:
        return None, False
    subject = m.group(3).strip(" ?.").lower()
    if not subject:
        return None, False
    entries = load().get("entries") or {}
    best, score = None, 0
    for eid, e in entries.items():
        name = (e.get("name") or "").lower()
        sc = 0
        for tok in re.split(r"[^a-z0-9%]+", subject):
            if len(tok) > 2 and tok in name:
                sc += 1
        if name and name in subject:
            sc += 3
        if sc > score:
            best, score = e, sc
    if not best or score == 0:
        return None, False
    bits = [f"{best['name']}: {best['meaning']}"]
    if best.get("computed"):
        bits.append(f"How it's worked out: {best['computed']}")
    if best.get("changing"):
        bits.append(f"If you change it: {best['changing']}")
    if best.get("default_from"):
        bits.append(f"Where the number comes from: {best['default_from']}")
    if best.get("good"):
        bits.append(f"What good looks like: {best['good']}")
    return " ".join(bits), True
