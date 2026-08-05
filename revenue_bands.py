"""
revenue_bands.py
----------------
The tracker/GHL revenue-band picklist, parsed exactly (LTC Scoreboard Part 1;
LTC_SCOREBOARD_REPORT Phase 0). NOT a fuzzy parser: the field is a 5-value picklist in
both the sheet ("Revenue Range") and the GHL form (field xaOeqdkAxtwj6W8hsVgV) — values
map to monthly-AUD bands or they are UNKNOWN. Unknown is a first-class visible state:
never 0, never guessed, always counted. A NOVEL value (someone edits the picklist)
parses to unknown AND raises a data-quality flag string so it's surfaced, not swallowed.

Source precedence (Rydel-confirmed): the tracker cell wins when filled (setter-verified);
the GHL form answer fills the gap. Measured effect: unknown 64.1% → 4.1% of lead rows.
"""
from __future__ import annotations

import re

# normalized picklist value → (low, high) monthly AUD; high=None = open-ended
BANDS: dict[str, tuple[int, int | None]] = {
    "under $20k": (0, 20_000),
    "$20k-50k": (20_000, 50_000),
    "$50k-100k": (50_000, 100_000),
    "$100k- $200k": (100_000, 200_000),   # the sheet's literal spacing
    "$100k-$200k": (100_000, 200_000),
    "$200k +": (200_000, None),
    "$200k+": (200_000, None),
}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def parse_band(tracker_value, ghl_value=None) -> dict:
    """→ {state: 'parsed'|'unknown', band, low, high, source: 'tracker'|'ghl_form'|None,
         flag: str|None}. flag is set ONLY for a novel non-empty value (data-quality)."""
    flag = None
    for source, raw in (("tracker", tracker_value), ("ghl_form", ghl_value)):
        v = _norm(raw)
        if not v:
            continue
        if v in BANDS:
            low, high = BANDS[v]
            return {"state": "parsed", "band": v, "low": low, "high": high,
                    "source": source, "flag": flag}
        # novel non-empty value: keep looking at the next source but remember the flag
        flag = (f"novel revenue value {str(raw)!r} in {source} — parsed as UNKNOWN, "
                f"picklist may have changed")
    return {"state": "unknown", "band": None, "low": None, "high": None,
            "source": None, "flag": flag}


def meets_floor(parsed: dict, floor_monthly: float) -> bool | None:
    """Band lower bound ≥ floor. None when unknown (never coerced)."""
    if parsed.get("state") != "parsed":
        return None
    return parsed["low"] >= floor_monthly
