"""trend.py — THIRTY DAYS, HONESTLY (the finish line, Part 2).

TODAY puts a 30-day trend and a vs-plan delta on every tile. Both are easy to
fake and neither is allowed to be:

· The trend is built from DAY-LEVEL history — one point per calendar day,
  the last reading of that day. The trap this module exists to avoid is
  `history_store.series(field, 30)`, which returns the last 30 ENTRIES; the
  snapshot loop appends roughly every two hours, so that is about two and a
  half days wearing a thirty-day label. Phase 0 found this had already
  silently broken the month-opening bank anchor.

· Where there is not enough history to draw a trend, the tile says so in
  words. A flat line drawn from one repeated value is a lie with a nice
  shape.

· The delta compares against the COMMITTED PLAN when one exists, and against
  the prior period when one does not — and it always says which. Polarity is
  respected: spending more than planned is never "ahead" (#157, A3).
"""

from __future__ import annotations

import datetime as dt
import logging

logger = logging.getLogger(__name__)

MIN_POINTS = 5          # fewer than this is not a trend, it's a rumour


def daily_series(field_path: str, days: int = 30) -> list[dict]:
    """[{date, value}] — one point per calendar day, oldest first.

    The LAST reading of each day wins (it is the most settled). Days with no
    reading are simply absent; they are never interpolated, because an
    invented point is indistinguishable from a real one once it is drawn.
    """
    try:
        import history_store
        entries = history_store.last_n_days(days) or []
    except Exception as e:  # noqa: BLE001
        logger.info("trend: history unavailable: %s", e)
        return []
    by_day: dict = {}
    for e in entries:
        day = e.get("date")
        snap = e.get("snapshot") or {}
        val = snap
        for part in field_path.split("."):
            val = val.get(part) if isinstance(val, dict) else None
            if val is None:
                break
        if day and isinstance(val, (int, float)):
            by_day[day] = float(val)      # later entries overwrite earlier
    return [{"date": d, "value": by_day[d]} for d in sorted(by_day)]


def sparkline(field_path: str, days: int = 30) -> dict:
    """What a tile needs: the points, and — when there aren't enough, or they
    never move — the sentence to print instead of a chart."""
    pts = daily_series(field_path, days)
    vals = [p["value"] for p in pts]
    if len(vals) < MIN_POINTS:
        return {"points": [], "days": len(vals), "note":
                (f"{len(vals)} day{'s' if len(vals) != 1 else ''} of history — "
                 f"a {days}-day trend needs more")}
    if len(set(vals)) == 1:
        return {"points": [], "days": len(vals),
                "note": f"unchanged across {len(vals)} days of history"}
    first, last = vals[0], vals[-1]
    change = last - first
    return {
        "points": vals, "days": len(vals),
        "first": first, "last": last, "change": round(change, 2),
        "change_pct": (round(change / abs(first) * 100, 1) if first else None),
        "note": "",
        "span": f"{pts[0]['date']} → {pts[-1]['date']}",
    }


def _plan_for_month(month: str) -> dict | None:
    """The committed plan's row for a month, or None when nothing is
    committed. Plan is plan — it never touches actuals."""
    try:
        import kv_store
        plan = kv_store.get("compass:plan2027")
        if not plan:
            return None
        for row in plan.get("roadmap") or []:
            if row.get("month") == month:
                return {**row, "_version": plan.get("version"),
                        "_name": plan.get("name")}
    except Exception as e:  # noqa: BLE001
        logger.info("trend: plan unreadable: %s", e)
    return None


def delta(actual, field_path: str = "", plan_key: str = "",
          polarity: str = "gain", unit: str = "money",
          days: int = 30) -> dict:
    """vs the committed plan if there is one, else vs the prior period.

    polarity: "gain"  — more is better (cash, MRR, leads) → ahead / behind
              "cost"  — more is worse  (spend, AR)        → over / under plan
    A cost metric NEVER reads "ahead" (#157, A3).
    """
    out = {"state": "flat", "word": "", "basis": "", "value": None}
    if actual is None:
        return {**out, "word": "no figure to compare", "basis": "none"}

    ref, basis = None, ""
    month = str(dt.date.today())[:7]
    row = _plan_for_month(month) if plan_key else None
    if row and row.get(plan_key) is not None:
        ref = row[plan_key]
        basis = f"the committed plan (v{row.get('_version')})"
    elif field_path:
        pts = daily_series(field_path, days * 2)
        if len(pts) >= 2:
            # the reading `days` ago, or the oldest we have — named either way
            target = str(dt.date.today() - dt.timedelta(days=days))
            older = [p for p in pts if p["date"] <= target] or pts[:1]
            ref = older[-1]["value"]
            basis = f"where it stood on {older[-1]['date']}"
    if ref is None:
        return {**out, "word": "nothing to compare against yet",
                "basis": "no plan committed and not enough history"}

    diff = actual - ref
    out["value"] = round(diff, 2)
    out["basis"] = basis
    if unit == "money":
        mag = f"${abs(diff):,.0f}"
    elif unit == "ratio":
        mag = f"{abs(diff):.2f}×"
    elif unit == "pct":
        mag = f"{abs(diff) * 100:.0f} points"
    else:
        mag = f"{abs(diff):,.0f}"

    near = abs(diff) < (abs(ref) * 0.005 if ref else 0.005)
    if near:
        return {**out, "state": "flat", "word": f"level with {basis}"}
    if polarity == "cost":
        # spending more than planned is never "ahead"
        out["state"] = "bad" if diff > 0 else "good"
        out["word"] = f"{mag} {'over' if diff > 0 else 'under'} {basis}"
    else:
        out["state"] = "good" if diff > 0 else "bad"
        out["word"] = f"{mag} {'above' if diff > 0 else 'below'} {basis}"
    return out
