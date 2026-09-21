"""comp_rulebook.py — THE SALES COMP RULEBOOK (versioned, effective-dated).

What a commission costs is a RULE, not a cell somebody remembered to fill.
Phase 0 found the estate reading four different answers, three of them $0,
because the tracker has recorded no won deal since 2026-07-20. So the rules
live here, versioned and effective-dated, and one engine applies them.

THE CURRENT RULES (Rydel, 2026-09-22 — DECISIONS #159)

  R-SET        setters: $50 per qualified set, paid whether or not it closes,
               + 5% of the cash collected in the deal's INITIAL MONTH on
               deals that close (a PIF's initial month is the whole
               prepayment).
  R-KALIN-CLOSE Kalin on his own deals: $750 Growth Pro · $1,500 Scale Engine.
  R-KALIN-MGR  Kalin as sales manager: $500 fixed per month, plus 3% of the
               cash collected on deals COBY closes — FUNDED OUT OF COBY'S
               COMMISSION, never an extra company cost.
  R-COBY       Coby as junior closer: the COMPANY'S TOTAL on a Coby-closed
               deal is his junior rate ($550 GP · $1,000 SE PIF · $1,000 SE
               split, $500 per collection). Kalin's 3% is DEDUCTED from that
               total; Coby nets the remainder.
  R-GST        every % basis is EX-GST. Cash from Stripe/Xero is GST-
               inclusive and is divided by 1.1 before any rate is applied.

THE INVARIANT, tested: the company's total commission on any Coby-closed
deal equals his junior rate. The override moves money from Coby to Kalin; it
never adds cost. If a deduction would exceed the commission on an event, it
is capped there and a decision card is raised — it never goes negative.

HISTORY. These are the CURRENT rules. A deal closed in March is costed at
the rules in force in March. Earlier regimes are reconstructed from evidence
(the recorded tracker cells and the payout log) and carry that evidence with
them. Where no evidence pins an older rule, the deal is labelled "estimated
under current rules" and says so on its face.

NOTHING IS INVENTED. A package nobody has ruled on returns "needs your
number" — never a guess, never a zero.
"""

from __future__ import annotations

import datetime as dt
import logging

logger = logging.getLogger(__name__)

GST_DIVISOR = 1.1          # AU GST: inclusive → ex-GST
K_OVERRIDES = "comp:rulebook:overrides"     # owner edits, journaled

# Who is what. Roles drive which rule applies, never a name spelled in code
# at the point of calculation.
SETTERS = ("coby", "maran", "akila")
JUNIOR_CLOSERS = ("coby",)
MANAGER = "kalin"

# Package keys — the tracker's offer strings normalise onto these.
PKG_GROWTH_PRO = "growth_pro"
PKG_SCALE_ENGINE = "scale_engine"
PKG_SCALE_SPLIT = "scale_engine_split"
PKG_MULTI_VENUE = "scale_engine_multi_venue"
PKG_CUSTOM = "custom"
PKG_CONTENT_SCALE = "content_scale"
PKG_DWY = "dwy"


def normalise_package(offer: str | None) -> str | None:
    """The tracker's offer text → a package key. Unrecognised → None, which
    renders 'needs your number' rather than defaulting to anything."""
    s = (offer or "").strip().lower()
    if not s:
        return None
    # ORDER MATTERS. "Content Scale" contains "scale": matched loosely it was
    # silently costed as a Scale Engine at $1,500 — an invented rate on a
    # package nobody has ruled. The specific names are tested first.
    if "content" in s:
        return PKG_CONTENT_SCALE
    if "multi" in s:
        return PKG_MULTI_VENUE
    if "split" in s:
        return PKG_SCALE_SPLIT
    if "scale" in s:
        return PKG_SCALE_ENGINE
    if "growth" in s:
        return PKG_GROWTH_PRO
    if "dwy" in s or "walk" in s:
        return PKG_DWY
    if "custom" in s:
        return PKG_CUSTOM
    return None


def ex_gst(amount: float | None, inclusive: bool = True) -> float | None:
    """R-GST. Cash that arrives GST-inclusive is converted before any rate
    touches it. $3,355 → $3,050."""
    if amount is None:
        return None
    return round(float(amount) / GST_DIVISOR, 2) if inclusive else round(float(amount), 2)


# ── THE VERSIONS ────────────────────────────────────────────────────────────
# Each version: effective from (inclusive) → to (exclusive; None = current).
# `closer_flat`: package → dollars the COMPANY pays on a close.
# `junior_closer_flat`: package → the company's TOTAL when a junior closes.
# Evidence is carried so a reader can check the rule against the record.

VERSIONS: list[dict] = [
    {
        "version": 1,
        "name": "Flat setter bounty era",
        "from": "2025-09-01", "to": "2026-01-01",
        "confidence": "reconstructed",
        "evidence": (
            "Nine deals Oct–Dec 2025 carry a flat $100 setter commission; "
            "closer cells show $1,400–$1,500 on Scale Engine and $2,800 on a "
            "multi-venue, consistent with a $1,400/$1,500 Scale Engine rate."),
        "setter": {"per_set": 0.0, "per_won_flat": 100.0, "pct_of_initial_cash": 0.0},
        "closer_flat": {PKG_SCALE_ENGINE: 1400.0, PKG_MULTI_VENUE: 2800.0},
        "junior_closer_flat": {},
        "manager": {"monthly_retainer": 0.0, "pct_of_junior_cash": 0.0},
        "cash_is_gst_inclusive": False,
    },
    {
        "version": 2,
        "name": "$50 + 5% setter era, Growth Pro at $700",
        "from": "2026-01-01", "to": "2026-05-01",
        "confidence": "reconstructed",
        "evidence": (
            "Setter cells fit $50 + 5% of the recorded (ex-GST) cash on "
            "several deals — $202.50 on $3,050, $362.50 on $6,250, $375 on "
            "$6,500, $675 on $12,500. Closer cells show Growth Pro $700 "
            "(2026-01-08, 01-12, 03-06, 03-10 ×2, 02-16) and Scale Engine "
            "$1,400–$1,500. Cash in this era is recorded EX-GST "
            "($3,050 first month on an $18,300 contract)."),
        "setter": {"per_set": 50.0, "per_won_flat": 0.0, "pct_of_initial_cash": 0.05},
        "closer_flat": {PKG_GROWTH_PRO: 700.0, PKG_SCALE_ENGINE: 1500.0,
                        PKG_SCALE_SPLIT: 1500.0, PKG_MULTI_VENUE: 3000.0},
        "junior_closer_flat": {},
        "manager": {"monthly_retainer": 0.0, "pct_of_junior_cash": 0.0},
        "cash_is_gst_inclusive": False,
    },
    {
        "version": 3,
        "name": "Growth Pro at $900 (the override that never reverted)",
        "from": "2026-05-01", "to": "2026-09-22",
        "confidence": "reconstructed",
        "evidence": (
            "config documents CLOSER_GP_MAY_OVERRIDE_AUD = 900 as a MAY-ONLY "
            "override reverting to $750. The tracker shows $900 paid on every "
            "Growth Pro close in June AND July (06-04, 06-05, 06-24, 06-30, "
            "07-17, 07-20) — the override did not revert in practice. Scale "
            "Engine stays $1,500. Coby's closes in this era are recorded at "
            "the FULL rate ($900 GP, $1,500 SE), not a junior rate. The "
            "tracker's cash column is GST-INCLUSIVE here ($3,355 first month "
            "on the same $18,300 contract), and the payout log's 5% is "
            "computed on the ex-GST figure."),
        "setter": {"per_set": 50.0, "per_won_flat": 0.0, "pct_of_initial_cash": 0.05},
        "closer_flat": {PKG_GROWTH_PRO: 900.0, PKG_SCALE_ENGINE: 1500.0,
                        PKG_SCALE_SPLIT: 1500.0, PKG_MULTI_VENUE: 3000.0},
        "junior_closer_flat": {},
        "manager": {"monthly_retainer": 0.0, "pct_of_junior_cash": 0.0},
        "cash_is_gst_inclusive": True,
        "open_item": (
            "config says Growth Pro reverted to $750 after May; the record "
            "says $900 was paid through July. Which was right?"),
    },
    {
        "version": 4,
        "name": "Current — junior closer with the manager override",
        "from": "2026-09-22", "to": None,
        "confidence": "ruled",
        "evidence": "Rydel, 2026-09-22 (DECISIONS #159). R-SET · R-KALIN-CLOSE "
                    "· R-KALIN-MGR · R-COBY · R-GST.",
        "setter": {"per_set": 50.0, "per_won_flat": 0.0,
                   "pct_of_initial_cash": 0.05,
                   "set_fee_basis": "qualified"},     # or "showed" — switchable
        "closer_flat": {PKG_GROWTH_PRO: 750.0, PKG_SCALE_ENGINE: 1500.0,
                        PKG_SCALE_SPLIT: 1500.0},
        "junior_closer_flat": {PKG_GROWTH_PRO: 550.0, PKG_SCALE_ENGINE: 1000.0,
                               PKG_SCALE_SPLIT: 1000.0},
        "manager": {"monthly_retainer": 500.0, "pct_of_junior_cash": 0.03},
        "cash_is_gst_inclusive": True,
        "junior_extras": {
            "fast_win_bonus": {"amount": 1000.0, "at_lifetime_closes": 10},
            "monthly_kpi_bonus": {"amount": 350.0,
                                  "gate": "a production floor — needs your number"},
            "clawback": "fault-based; 60 days from sale for PIF, per instalment for plans",
        },
    },
]

# Packages nobody has ruled a rate for. Rendered as "needs your number" when
# a deal of that kind actually exists — never silently costed.
UNCOVERED_PACKAGES = (PKG_CONTENT_SCALE, PKG_DWY, PKG_CUSTOM, PKG_MULTI_VENUE)


def _d(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def version_for(on: dt.date | str | None) -> dict:
    """The rules IN FORCE on a date. A March deal is costed at March's rules
    — applying today's to it would silently restate history."""
    d = _d(on) if isinstance(on, str) else on
    if d is None:
        return current_version()
    for v in VERSIONS:
        f, t = _d(v["from"]), _d(v["to"])
        if f and d >= f and (t is None or d < t):
            return _with_overrides(v)
    # older than anything we have evidence for
    v = dict(current_version())
    v["confidence"] = "estimated under current rules"
    v["evidence"] = ("no evidence pins the rules for this date; costed at the "
                     "current rules and labelled as an estimate")
    return v


def current_version() -> dict:
    return _with_overrides(VERSIONS[-1])


def _with_overrides(v: dict) -> dict:
    """Owner edits, applied on top and journaled. The stored rulebook is
    never mutated in place — an edit makes a new effective value with a
    record of who changed it and when."""
    try:
        import kv_store
        ov = (kv_store.get(K_OVERRIDES) or {}).get(str(v["version"]))
    except Exception as e:  # noqa: BLE001
        logger.info("rulebook overrides unavailable: %s", e)
        ov = None
    if not ov:
        return v
    out = {k: (dict(val) if isinstance(val, dict) else val) for k, val in v.items()}
    for section, changes in (ov.get("changes") or {}).items():
        if isinstance(out.get(section), dict) and isinstance(changes, dict):
            out[section].update(changes)
        else:
            out[section] = changes
    out["edited"] = {"at": ov.get("at"), "by": ov.get("by"),
                     "note": ov.get("note"), "changes": ov.get("changes")}
    return out


def set_override(version: int, changes: dict, actor: str, note: str = "") -> dict:
    """Journaled edit. Owner-only at the route; the record is kept here."""
    import kv_store
    from helpers import now_sydney
    store = kv_store.get(K_OVERRIDES) or {}
    journal = store.get("_journal") or []
    entry = {"at": now_sydney().isoformat(), "by": actor, "version": version,
             "changes": changes, "note": note[:300]}
    journal.append(entry)
    store[str(version)] = {**entry}
    store["_journal"] = journal[-200:]
    kv_store.put(K_OVERRIDES, store)
    return {"ok": True, "entry": entry, "journal_len": len(journal)}


def journal() -> list[dict]:
    try:
        import kv_store
        return (kv_store.get(K_OVERRIDES) or {}).get("_journal") or []
    except Exception:
        return []


def set_fee_basis(on=None) -> str:
    """'qualified' (today's ruling) or 'showed' (Coby's July wording). The
    rules screen switches it; the figures recompute and the version bumps."""
    v = version_for(on)
    return (v.get("setter") or {}).get("set_fee_basis", "qualified")


def open_items() -> list[dict]:
    """What the rulebook knows it does not know. Shown on the rules screen."""
    items = [
        {"id": "set_fee_basis",
         "question": "Is the $50 set fee paid per QUALIFIED set or per SHOWED set?",
         "current": set_fee_basis(),
         "why": ("Today's ruling says qualified. Coby's July 2026 policy "
                 "worded it 'per showed set'. The two give different bounty "
                 "counts, and the bounty is most of the setter cost."),
         "action": "switch it on this screen; every figure recomputes"},
        {"id": "gp_900_vs_750",
         "question": "Growth Pro: did the $900 override really revert to $750?",
         "current": "history costed at $900 from May to 21 Sep; $750 from 22 Sep",
         "why": ("config records $900 as a MAY-ONLY override reverting to "
                 "$750, but the tracker shows $900 paid on every Growth Pro "
                 "close in June and July."),
         "action": "confirm which was right; the reconstructed era updates"},
        {"id": "coby_full_rate_history",
         "question": ("Coby's five recorded closes were paid at the FULL rate "
                      "($900/$1,500), not the junior rate. Was that intended?"),
         "current": "history shows what was paid; no restatement was made",
         "why": ("Under the current ruling those deals would total $3,650; "
                 "the tracker records $5,700."),
         "action": "tell me and the reconstructed era updates"},
    ]
    for pkg in UNCOVERED_PACKAGES:
        items.append({
            "id": f"rate_{pkg}",
            "question": f"What does a {pkg.replace('_', ' ')} close pay?",
            "current": "needs your number",
            "why": "no rate has been ruled for this package",
            "action": "give me the number and deals of this kind start costing"})
    return items


def coby_policy_flag() -> dict:
    """OWNER-ONLY. Coby's signed policy does not show the deduction."""
    v = current_version()
    jr = v["junior_closer_flat"]
    pct = v["manager"]["pct_of_junior_cash"]
    gp_first = 3050.0                       # ex-GST first month, Growth Pro
    # the Scale Engine contract value is recorded EX-GST ($14,500), so a
    # PIF prepays that figure and the 3% lands on it directly — this is
    # Rydel's worked example: 3% of $14,500 = $435.
    se_pif = 14500.0
    gp_ded = round(gp_first * pct, 2)
    se_ded = round(se_pif * pct, 2)
    return {
        "headline": ("Coby's signed July policy shows $550 / $1,000 without "
                     "the deduction — Kalin's lines were removed from his "
                     "copy. His take-home under this structure is below his "
                     "document."),
        "growth_pro": {"his_document": jr[PKG_GROWTH_PRO],
                       "deduction": gp_ded,
                       "he_nets": round(jr[PKG_GROWTH_PRO] - gp_ded, 2),
                       "deduction_share_pct": round(gp_ded / jr[PKG_GROWTH_PRO] * 100, 1)},
        "scale_engine_pif": {"his_document": jr[PKG_SCALE_ENGINE],
                             "deduction": se_ded,
                             "he_nets": round(jr[PKG_SCALE_ENGINE] - se_ded, 2),
                             "deduction_share_pct": round(se_ded / jr[PKG_SCALE_ENGINE] * 100, 1)},
        "pif_effect": ("the deduction is about "
                       f"{round(gp_ded / jr[PKG_GROWTH_PRO] * 100)}% of his Growth "
                       f"Pro commission but about "
                       f"{round(se_ded / jr[PKG_SCALE_ENGINE] * 100)}% of his Scale "
                       "Engine PIF commission — a PIF front-loads the whole "
                       "prepayment into one 3% bite"),
        "owner_only": True,
    }
