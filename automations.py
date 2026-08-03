"""
automations.py — Universal advisor Phase 3: the automation-health registry.

One declarative registry of every scheduled automation across the ecosystem EDITH
can currently see evidence for, each with its expected cadence and WHERE its
last-run/last-success evidence lives:

  • Timeline service jobs — the APScheduler listener writes `job:<id>` rows into
    the durable integrationstatus table (ran ok / missed / error), read here via
    the token-gated /bridge/data/automation-status endpoint (timeline_adapter).
  • EDITH's own loops — snapshot refresh (snapshot_state generated_at), the sheet
    mirror (Postgres sheet_sync_state), the GHL mirror (ghl_sync_state), the daily
    MRR snapshot (mrr_snapshots).

Health states: RUNNING (last success within cadence × grace) · STALE (window
missed) · FAILING (evidence says error) · UNKNOWN (evidence unreachable — an
unreachable check is NEVER reported green; silence must not be ambiguous).

Salience: failures/staleness emit watermarked events (re-fire only when the
day-bucket changes); a weekly POSITIVE confirmation event ("all N automations
green") makes silence unambiguous the other way too. Registry truth is also
conversational: "are the automations healthy?" / "did the sync run today?".

Read-only everywhere — this module evaluates evidence; it never triggers anything.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re

from helpers import now_sydney

logger = logging.getLogger(__name__)

# id, label, cadence_hours (expected max gap between successes), evidence source
TIMELINE_JOBS = [
    ("tl:daily_sync",       "Timeline Asana sync (6am)",          26),
    ("tl:daily_scoreboard", "Scoreboard GHL sync (6:15am)",       26),
    ("tl:daily_reconcile",  "Cache↔Asana reconciliation (6:30am)", 26),
    ("tl:renewal_sync",     "Renewal command sync (6:45am)",      26),
    ("tl:daily_pulse",      "Lark daily pulse (8am Mon–Sat)",     50),   # skips Sunday
    ("tl:event_alerts",     "Client-event countdown alerts (8:30am)", 26),
    ("tl:mvp_integrity",    "MVP integrity (5am)",                26),
    ("tl:eow_integrity",    "EOW integrity (5:15am)",             26),
    ("tl:purge_signal_images", "Signal image purge (3:30am)",     26),
    ("tl:relay_tick",       "Reel Launch Relay tick",              2),
    ("tl:weekly_summary",   "Lark weekly summary (Sun 6pm)",     192),
    ("tl:eow_reset",        "EOW weekly reset (Mon 6am)",        192),
    ("tl:mvp_monday",       "MVP Monday card",                   192),
    ("tl:eow_friday",       "EOW Friday reminder",               192),
    ("tl:mvp_friday",       "MVP Friday reminder",               192),
]
GRACE = 1.25   # cadence × grace before a job is called STALE


def _parse_dt(s):
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=now_sydney().tzinfo)
        return d
    except ValueError:
        return None


def _hours_since(s) -> float | None:
    d = _parse_dt(s)
    return None if d is None else (now_sydney() - d).total_seconds() / 3600.0


def _entry(aid, label, state, detail):
    return {"id": aid, "label": label, "state": state, "detail": detail}


def _eval_gap(aid, label, hours, cadence, err=None):
    if err:
        return _entry(aid, label, "FAILING", err)
    if hours is None:
        return _entry(aid, label, "UNKNOWN", "no run evidence found")
    if hours <= cadence * GRACE:
        return _entry(aid, label, "RUNNING", "last success %.1fh ago" % hours)
    return _entry(aid, label, "STALE", "last success %.1fh ago (expected every %dh)" % (hours, cadence))


def _timeline_health() -> list[dict]:
    import timeline_adapter
    if not timeline_adapter.configured():
        return [_entry("tl:*", "Timeline jobs", "UNKNOWN", "bridge not configured")]
    data = timeline_adapter.automation_status()
    if data is None:
        return [_entry("tl:*", "Timeline jobs", "UNKNOWN",
                       "bridge unreachable — cannot verify, NOT assuming green")]
    integ = data.get("integrations") or {}
    out = []
    for aid, label, cadence in TIMELINE_JOBS:
        job = integ.get("job:" + aid.split(":", 1)[1]) or {}
        ok, detail = job.get("ok"), (job.get("detail") or "")
        last_ok_h = _hours_since(job.get("last_ok_at"))
        if job and ok is False:
            # a failed attempt is FAILING even if an older success exists
            out.append(_entry(aid, label, "FAILING", "last error: %s" % (detail[:120] or "unknown")))
            continue
        out.append(_eval_gap(aid, label, last_ok_h, cadence))
    fr = data.get("freshness") or {}
    if fr.get("stale"):
        out.append(_entry("tl:cache", "Timeline task cache", "STALE",
                          "last sync %.1fh ago" % (fr.get("hours_since_sync") or -1)))
    return out


def _edith_health() -> list[dict]:
    out = []
    # snapshot refresh loop (expected every REFRESH_INTERVAL_HOURS, default 2h)
    try:
        from snapshot import load_persisted
        import os
        cad = max(2, int(os.environ.get("REFRESH_INTERVAL_HOURS", "2"))) * 2  # loop only rebuilds when stale
        snap = load_persisted() or {}
        out.append(_eval_gap("cfo:snapshot", "CFO snapshot refresh",
                             _hours_since(snap.get("generated_at")), cad))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("cfo:snapshot", "CFO snapshot refresh", "UNKNOWN", str(e)[:80]))
    # sheet mirror (90s loop — call it stale after 30 min)
    try:
        from sheet_mirror import get_sources
        srcs = get_sources() or []
        if not srcs:
            out.append(_entry("cfo:sheet_mirror", "Sheet mirror sync", "UNKNOWN", "no sync_state rows"))
        else:
            failed = [s for s in srcs if s.get("last_sync_status") != "ok"]
            oldest = max((_hours_since(s.get("last_sync_at")) or 999) for s in srcs)
            if failed:
                out.append(_entry("cfo:sheet_mirror", "Sheet mirror sync", "FAILING",
                                  "%d tab(s) failing: %s" % (len(failed),
                                  ", ".join(s.get("tab_name") or s.get("tab", "?") for s in failed[:3]))))
            else:
                out.append(_eval_gap("cfo:sheet_mirror", "Sheet mirror sync", oldest, 0.5))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("cfo:sheet_mirror", "Sheet mirror sync", "UNKNOWN", str(e)[:80]))
    # GHL mirror (15-min loop — stale after 2h) + daily MRR snapshot
    try:
        import db
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT last_sync_at, ok, error FROM ghl_sync_state "
                        "ORDER BY last_sync_at DESC NULLS LAST LIMIT 1")
            row = cur.fetchone()
        if not row:
            out.append(_entry("cfo:ghl_mirror", "GHL mirror sync", "UNKNOWN", "no sync_state row"))
        elif row.get("ok") is False:
            out.append(_entry("cfo:ghl_mirror", "GHL mirror sync", "FAILING",
                              "last error: %s" % ((row.get("error") or "unknown")[:100])))
        else:
            out.append(_eval_gap("cfo:ghl_mirror", "GHL mirror sync",
                                 _hours_since(row.get("last_sync_at")), 2))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("cfo:ghl_mirror", "GHL mirror sync", "UNKNOWN", str(e)[:80]))
    try:
        import db
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT MAX(snap_date) AS d FROM mrr_snapshots")
            row = cur.fetchone()
        d = row and row.get("d")
        h = None if d is None else (now_sydney().date() - d).days * 24.0
        out.append(_eval_gap("cfo:mrr_snapshot", "Daily MRR snapshot", h, 30))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("cfo:mrr_snapshot", "Daily MRR snapshot", "UNKNOWN", str(e)[:80]))
    return out


def health() -> dict:
    """The full registry evaluation. {generated_at, automations:[...], counts:{...}}"""
    rows = _timeline_health() + _edith_health()
    counts = {"RUNNING": 0, "STALE": 0, "FAILING": 0, "UNKNOWN": 0}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {"generated_at": now_sydney().isoformat(timespec="seconds"),
            "automations": rows, "counts": counts, "total": len(rows)}


# ── salience wiring (watermarked; see salience.collect) ───────────────────────
def salience_events() -> list[dict]:
    """Failure/stale events (day-bucketed ids → re-fire daily while broken) plus a
    weekly positive confirmation when EVERYTHING is green. UNKNOWN is surfaced as
    its own event — an unverifiable automation is never silently counted green."""
    try:
        h = health()
    except Exception as e:  # noqa: BLE001
        logger.warning("automation health failed: %s", e)
        return []
    day = now_sydney().date().isoformat()
    week = now_sydney().date().isocalendar()
    events = []
    bad = [r for r in h["automations"] if r["state"] in ("FAILING", "STALE")]
    unknown = [r for r in h["automations"] if r["state"] == "UNKNOWN"]
    for r in bad:
        events.append({"id": "auto:%s:%s:%s" % (r["id"], r["state"].lower(), day),
                       "type": "automation_" + r["state"].lower(), "salience": 75, "ago": 0,
                       "spoken": "%s is %s — %s." % (r["label"], r["state"], r["detail"])})
    if unknown and not bad:
        events.append({"id": "auto:unknown:%s" % day, "type": "automation_unknown",
                       "salience": 40, "ago": 0,
                       "spoken": "%d automation check(s) unverifiable right now (%s) — not assuming green."
                                 % (len(unknown), ", ".join(r["label"] for r in unknown[:3]))})
    if not bad and not unknown:
        events.append({"id": "auto:allgreen:%s-w%s" % (week[0], week[1]),
                       "type": "automation_all_green", "salience": 35, "ago": 0,
                       "spoken": "All %d automations green this week — every scheduled job ran on time."
                                 % h["total"]})
    return events


# ── conversational handler (tier 2) ──────────────────────────────────────────
_HEALTH_RE = re.compile(r"\b(automations?|scheduled jobs?|cron)\b.{0,30}\b(healthy|health|green|running|ok|okay|status)\b"
                        r"|\b(are|is)\b.{0,20}\b(automations?|jobs?|syncs?)\b.{0,20}\b(healthy|running|green|ok)\b"
                        r"|\bdid\b.{0,30}\b(sync|nudges?|pulse|alerts?|backstop|relay tick|reconcil\w+)\b.{0,20}\brun\b", re.I)


def handle_automation_health(msg: str) -> tuple[str | None, bool]:
    if not msg or not _HEALTH_RE.search(msg):
        return None, False
    h = health()
    c = h["counts"]
    # specific job asked? ("did the sync run today")
    m = re.search(r"\bdid\b.{0,30}\b(sync|nudges?|pulse|alerts?|backstop|relay tick|reconcil\w+)\b", msg, re.I)
    if m:
        word = m.group(1).lower()
        want = {"sync": "tl:daily_sync", "pulse": "tl:daily_pulse", "alert": "tl:event_alerts",
                "alerts": "tl:event_alerts", "reconcil": "tl:daily_reconcile",
                "relay tick": "tl:relay_tick", "backstop": "tl:daily_sync",
                "nudge": "tl:relay_tick", "nudges": "tl:relay_tick"}.get(
                    word if not word.startswith("reconcil") else "reconcil")
        row = next((r for r in h["automations"] if r["id"] == want), None)
        if row:
            extra = (" (the relay stall nudges ride on this tick)" if word.startswith("nudge") else
                     " (the forgotten-button backstop rides inside the daily sync)" if word == "backstop" else "")
        # fall through to the full readout if we couldn't map the word
            return "%s: %s — %s%s." % (row["label"], row["state"], row["detail"], extra), True
    bad = [r for r in h["automations"] if r["state"] in ("FAILING", "STALE")]
    unknown = [r for r in h["automations"] if r["state"] == "UNKNOWN"]
    if not bad and not unknown:
        return ("All %d automations are green — every scheduled job on the Timeline and my own "
                "sync loops ran inside their expected windows." % h["total"]), True
    bits = []
    if bad:
        bits.append("; ".join("%s: %s (%s)" % (r["label"], r["state"], r["detail"]) for r in bad[:5]))
    if unknown:
        bits.append("%d unverifiable right now: %s — I'm not counting those as green"
                    % (len(unknown), ", ".join(r["label"] for r in unknown[:3])))
    return ("%d of %d automations green. %s." % (c["RUNNING"], h["total"], ". ".join(bits))), True
