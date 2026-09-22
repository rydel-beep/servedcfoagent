"""stale_drill.py — PAUSE A SYNC, AND SEE WHETHER THE TILES ADMIT IT.

A freshness contract is only worth anything if a tile goes amber and NAMES the
source when its input stops arriving. This drill proves that without stopping a
real job and without writing a byte anywhere: it takes the live stamps, ages ONE
source past its budget in memory, and asks every registered tile what it would
then say.

Read-only by construction — it patches `freshness._source_stamps` inside this
process only. Nothing is written to kv, the tracker, GHL or Xero.

Run under `railway run` so the live stamps are the ones being aged.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import freshness                                     # noqa: E402
from helpers import now_sydney                       # noqa: E402

# One source per drill, with a tile that depends on it and one that does not.
DRILLS = [
    ("tracker_mirror", 6),      # budget 3 min  → age it 6 hours
    ("ghl_opportunities", 6),
    ("meta_today", 6),
]


def aged(real: dict, key: str, hours: int) -> dict:
    out = json.loads(json.dumps(real, default=str))
    old = (now_sydney() - timedelta(hours=hours)).isoformat()
    out.setdefault(key, {})["at"] = old
    return out


def main():
    real = freshness._source_stamps()
    baseline = freshness.sources()
    report = {"baseline": {"stale": [r["key"] for r in baseline["rows"]
                                     if r["status"] != "ok"],
                           "rows": len(baseline["rows"])},
              "drills": []}
    fails = []

    tiles = sorted(freshness.TILE_INPUTS)
    for key, hours in DRILLS:
        if key not in real:
            fails.append("source %s is not reported at all" % key)
            continue
        freshness._source_stamps = lambda k=key, h=hours: aged(real, k, h)
        try:
            src = freshness.sources()
            row = next((r for r in src["rows"] if r["key"] == key), None)
            affected, unaffected, silent = [], [], []
            for t in tiles:
                a = freshness.as_of(t, src)
                depends = key in (freshness.TILE_INPUTS.get(t) or ())
                if depends:
                    if a["state"] in ("stale", "degraded") and a.get("stale_source"):
                        affected.append({"tile": t, "says": a["why"]})
                    else:
                        silent.append({"tile": t, "state": a["state"], "says": a["why"]})
                elif a["state"] in ("stale", "degraded"):
                    unaffected.append({"tile": t, "says": a["why"]})
            report["drills"].append({
                "paused": key, "aged_hours": hours,
                "source_row_status": (row or {}).get("status"),
                "tiles_that_went_amber": affected,
                "tiles_that_stayed_silent": silent,
                "tiles_amber_without_depending_on_it": unaffected,
            })
            if (row or {}).get("status") != "stale":
                fails.append("%s aged %dh but its own row says %r"
                             % (key, hours, (row or {}).get("status")))
            if silent:
                fails.append("%s aged %dh and %d dependent tile(s) said nothing: %s"
                             % (key, hours, len(silent), [s["tile"] for s in silent]))
            if not affected:
                fails.append("%s aged %dh and no tile named it" % (key, hours))
        finally:
            freshness._source_stamps = lambda: real

    report["fails"] = fails
    out = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "stale-drill.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(json.dumps(report, indent=1, default=str)[:4000])
    print(("STALE DRILL PASS — " if not fails else "STALE DRILL FAIL — ") + path)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
