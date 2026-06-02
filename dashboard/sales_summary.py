"""
dashboard/sales_summary.py
--------------------------
Builds a sales-team-safe markdown summary for a given trailing window.

PRIVACY BOUNDARY: This module ONLY reads from sales/funnel/deep blocks.
It NEVER accesses: stripe, xero, profit, costs, revenue_views, hormozi,
active_clients, payroll, or any financial data.
"""
from __future__ import annotations

from helpers import today_sydney


def _get(d: dict, path: str):
    obj = d
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def _gap(actual, target):
    """Return gap in percentage points, or None."""
    if actual is None or target is None:
        return None
    return round(actual - target, 1)


def build_sales_summary(snap: dict, window_days: int = 30) -> str:
    """Build the sales-team markdown summary for the given window.

    Uses sales.windows[] for non-30d, sales.funnel/deep for 30d.
    """
    today = today_sydney()
    sales = snap.get("sales") or {}
    windows = sales.get("windows") or []

    # Pick the right window data
    if window_days != 30 and windows:
        w = next((w for w in windows if w.get("window_days") == window_days), None)
    else:
        w = None

    # For 30d, use the primary funnel; for other windows use window data
    if w:
        leads = w.get("leads", 0)
        sets = w.get("sets", 0)
        shows = w.get("shows", 0)
        closes = w.get("closes", 0)
        dqs = w.get("dqs", 0)
        l2s = w.get("lead_to_set_pct")
        s2sh = w.get("set_to_show_pct")
        sh2c = w.get("show_to_close_pct")
        l2c = w.get("lead_to_close_pct")
        dq_rate = w.get("dq_rate_pct")
        median_days = w.get("median_days_to_close")
        per_setter = w.get("per_setter") or []
        per_closer = w.get("per_closer") or []
        window_available = True
    else:
        funnel = sales.get("funnel") or {}
        leads = funnel.get("leads_in", 0)
        sets = funnel.get("sets", 0)
        shows = funnel.get("shows", 0)
        closes = funnel.get("closes", 0)
        dqs = funnel.get("dqs", 0)
        l2s = funnel.get("lead_to_set_pct")
        s2sh = funnel.get("set_to_show_pct")
        sh2c = funnel.get("show_to_close_pct")
        l2c = funnel.get("lead_to_close_pct")
        dq_rate = funnel.get("dq_rate_pct")
        velocity = sales.get("velocity") or {}
        median_days = velocity.get("days_lead_to_cash_median")
        per_setter = _get(snap, "sales.deep.setter_performance") or sales.get("per_setter") or []
        per_closer = sales.get("per_closer") or []
        window_available = window_days == 30

    # Deep analytics (only available for 30d)
    deep = sales.get("deep") or {}
    leak_flags = deep.get("leak_flags") or []
    lead_quality = deep.get("lead_quality") or {}
    loss = deep.get("loss") or {}
    speed_to_lead = sales.get("setter_activity") or []
    speed_aggregate = _get(snap, "sales.setter_deep_dive") or {}

    # Benchmarks
    TARGET_S2SH = 70.0
    TARGET_SH2C = 35.0
    TARGET_STL = 50.0

    lines = []
    lines.append("# Served Marketing — Sales Performance Summary")
    lines.append(f"**Period:** Trailing {window_days} days (as of {today})")
    if not window_available and window_days != 30:
        lines.append(f"\n> **Note:** {window_days}-day window data not available in current snapshot. Showing 30-day data.")
    lines.append("")

    # ── Funnel Overview ──
    lines.append("## Funnel Overview")
    lines.append(f"- Leads: **{leads}**")

    def _rate_line(label, count, rate, target, target_label):
        parts = [f"- {label}: **{count}**"]
        if rate is not None:
            parts.append(f"({rate}%")
            if target is not None:
                gap = _gap(rate, target)
                if gap is not None and gap < 0:
                    parts.append(f"— target {target}%, gap: {gap}pts")
                elif gap is not None and gap >= 0:
                    parts.append(f"— target {target}%, **above target**")
            parts.append(")")
        return " ".join(parts)

    lines.append(_rate_line("Sets", sets, l2s, None, "Lead→Set"))
    lines.append(_rate_line("Shows", shows, s2sh, TARGET_S2SH, "Set→Show"))
    lines.append(_rate_line("Closes", closes, sh2c, TARGET_SH2C, "Show→Close"))
    if l2c is not None:
        lines.append(f"- Overall Lead→Close: **{l2c}%**")
    if dq_rate is not None:
        lines.append(f"- DQ Rate: {dq_rate}% ({dqs} leads disqualified)")
    if median_days is not None:
        lines.append(f"- Median lead-to-close: **{int(median_days)} days**")
    lines.append("")

    # ── The Three Biggest Problems ──
    problems = []

    # Show→Close gap
    if sh2c is not None and sh2c < TARGET_SH2C and shows > 0:
        at_target = round(shows * TARGET_SH2C / 100)
        missed = at_target - closes
        if missed > 0:
            problems.append(
                f"**Show→Close at {sh2c}%** (target {TARGET_SH2C}%): "
                f"{shows} shows but only {closes} closes — at target you'd close "
                f"**{missed} more** deals"
            )

    # Set→Show gap
    if s2sh is not None and s2sh < TARGET_S2SH and sets > 0:
        at_target = round(sets * TARGET_S2SH / 100)
        missed = at_target - shows
        if missed > 0:
            problems.append(
                f"**Set→Show at {s2sh}%** (target {TARGET_S2SH}%): "
                f"{missed} booked meetings not showing up"
            )

    # Speed-to-lead
    stl_pct = speed_aggregate.get("five_min_rate_pct") if speed_aggregate else None
    stl_calls = speed_aggregate.get("calls_within_5_min") if speed_aggregate else None
    stl_total = speed_aggregate.get("total_dials") if speed_aggregate else None
    if stl_pct is not None and stl_pct < TARGET_STL:
        problems.append(
            f"**Speed-to-lead at {stl_pct}%** (target {TARGET_STL}%): "
            f"only {stl_calls or '?'}/{stl_total or '?'} leads contacted within 5 minutes"
        )

    # No-show rate
    no_show_pct = loss.get("no_show_pct")
    if no_show_pct is not None and no_show_pct > 15.0:
        problems.append(
            f"**No-show rate at {no_show_pct}%** (max 15%): "
            f"{loss.get('no_shows', 0)} no-shows out of {loss.get('total_sets', 0)} sets"
        )

    # Wasted lead sources
    by_source = lead_quality.get("by_source") or []
    wasted = [s for s in by_source if s.get("leads", 0) >= 3 and s.get("close_rate_pct", 100) == 0]
    if wasted and len(problems) < 3:
        names = ", ".join(s["source"] for s in wasted[:3])
        total_wasted = sum(s["leads"] for s in wasted)
        problems.append(
            f"**Wasted lead sources**: {names} — {total_wasted} leads, 0 closes. "
            f"Reps spending time on leads that don't convert"
        )

    # Add remaining leak flags if we have room
    for flag in leak_flags:
        if len(problems) >= 3:
            break
        # Skip flags we've already covered
        if any(kw in flag.lower() for kw in ("show→close", "set→show", "speed-to-lead")):
            continue
        problems.append(f"**{flag}**")

    if problems:
        lines.append("## The Three Biggest Problems")
        for i, p in enumerate(problems[:3], 1):
            lines.append(f"{i}. {p}")
        lines.append("")

    # ── Speed-to-Lead ──
    lines.append("## Speed-to-Lead (the #1 lever)")
    if stl_pct is not None:
        lines.append(f"- **{stl_pct}%** of leads contacted within 5 minutes (target: {TARGET_STL}%)")
    else:
        lines.append("- Speed-to-lead data not available in current snapshot")

    # Per-setter speed from deep analytics
    deep_setters = deep.get("setter_performance") or []
    stl_entries = [s for s in deep_setters if s.get("speed_to_lead_pct") is not None]
    if stl_entries:
        for s in stl_entries:
            lines.append(f"- {s['name']}: {s['speed_to_lead_pct']}% within 5 min")
    lines.append("")

    # ── Lead Quality by Source ──
    if by_source:
        lines.append("## Lead Quality by Source")
        sorted_sources = sorted(by_source, key=lambda s: s.get("leads", 0), reverse=True)
        for s in sorted_sources:
            line = f"- **{s['source']}**: {s['leads']} leads"
            if s.get("sets"):
                line += f", {s['sets']} sets"
            line += f", {s.get('close_rate_pct', 0)}% close rate"
            if s.get("dq_rate_pct", 0) > 20:
                line += f" (DQ rate: {s['dq_rate_pct']}%)"
            lines.append(line)
        lines.append("")

    # ── Rep Performance ──
    lines.append("## Rep Performance")

    if per_setter:
        lines.append("### Setters")
        for s in per_setter:
            parts = [f"- **{s.get('name', '?')}**:"]
            if s.get("dials") is not None:
                parts.append(f"{s['dials']} dials,")
            if s.get("sets") is not None:
                parts.append(f"{s['sets']} sets,")
            if s.get("dials_per_set") is not None:
                parts.append(f"{s['dials_per_set']} dials/set,")
            if s.get("speed_to_lead_pct") is not None:
                parts.append(f"{s['speed_to_lead_pct']}% speed-to-lead,")
            if s.get("show_pct") is not None:
                parts.append(f"{s['show_pct']}% show rate,")
            if s.get("close_pct") is not None:
                parts.append(f"{s['close_pct']}% close rate")
            elif s.get("close_rate_pct") is not None:
                parts.append(f"{s['close_rate_pct']}% close rate")
            line = " ".join(parts).rstrip(",")
            if s.get("avg_quality") is not None:
                line += f", quality: {s['avg_quality']}/5"
            lines.append(line)

    if per_closer:
        lines.append("### Closers")
        for c in per_closer:
            parts = [f"- **{c.get('name', '?')}**:"]
            if c.get("shows") is not None:
                parts.append(f"{c['shows']} shows,")
            if c.get("closes") is not None:
                parts.append(f"{c['closes']} closes,")
            if c.get("close_rate_pct") is not None:
                parts.append(f"{c['close_rate_pct']}% close rate")
            lines.append(" ".join(parts).rstrip(","))
    lines.append("")

    # ── DQ & Loss Intelligence ──
    dq_reasons = loss.get("dq_reasons") or []
    if dq_reasons:
        lines.append("## Top DQ Reasons")
        for r in dq_reasons[:5]:
            lines.append(f"- {r['reason']}: {r['count']} ({r['pct']}%)")
        lines.append("")

    loss_reasons = loss.get("loss_reasons") or []
    if loss_reasons:
        lines.append("## Loss Reasons (shows that didn't close)")
        for r in loss_reasons[:5]:
            lines.append(f"- {r['reason']}: {r['count']} ({r['pct']}%)")
        lines.append("")

    # Per-setter no-show
    per_setter_ns = loss.get("per_setter_noshow") or []
    if per_setter_ns and any(s.get("no_show_pct", 0) > 10 for s in per_setter_ns):
        lines.append("## No-Show by Setter")
        for s in per_setter_ns:
            if s.get("no_show_pct", 0) > 0:
                lines.append(f"- {s['name']}: {s['no_shows']}/{s['sets']} no-shows ({s['no_show_pct']}%)")
        lines.append("")

    # ── Setter Deep-Dive Funnel ──
    dd = sales.get("setter_deep_dive") or {}
    if dd.get("dials") is not None:
        lines.append("## Setter Activity Funnel")
        lines.append(f"- Dials: **{dd['dials']}**")
        if dd.get("connects") is not None:
            lines.append(f"- Connects: **{dd['connects']}** ({dd.get('connect_rate_pct', '?')}%)")
        if dd.get("sets_booked") is not None:
            lines.append(f"- Sets booked: **{dd['sets_booked']}** ({dd.get('sets_from_connects_pct', '?')}%)")
        if dd.get("showed") is not None:
            lines.append(f"- Showed: **{dd['showed']}** ({dd.get('show_rate_pct', '?')}%)")
        if dd.get("closed") is not None:
            lines.append(f"- Closed: **{dd['closed']}** ({dd.get('close_from_show_pct', '?')}%)")
        lines.append("")

    # ── What This Means ──
    lines.append("## What This Means for the Team")
    coaching = []
    if sh2c is not None and sh2c < TARGET_SH2C:
        coaching.append(
            f"Close rate is at {sh2c}% — every point toward {TARGET_SH2C}% "
            f"means more wins from the same pipeline. Focus on objection handling and follow-up."
        )
    if s2sh is not None and s2sh < TARGET_S2SH:
        coaching.append(
            f"Show rate at {s2sh}% means we're losing booked meetings. "
            f"Confirmation sequences and day-of reminders are the fix."
        )
    if stl_pct is not None and stl_pct < TARGET_STL:
        coaching.append(
            f"Speed-to-lead at {stl_pct}% — getting to leads faster is the single biggest "
            f"lever. First rep to call wins."
        )
    if not coaching:
        coaching.append("Funnel rates are tracking to target — maintain the pace and watch for regression.")

    for c in coaching[:3]:
        lines.append(f"- {c}")
    lines.append("")

    lines.append(f"— Generated from live dashboard data, {today}, {window_days}-day window. "
                 f"Paste into Claude to build the team deck.")

    return "\n".join(lines)
