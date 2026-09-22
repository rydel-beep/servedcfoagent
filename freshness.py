"""freshness.py — CURRENT, OR SAYING HOW OLD IT IS.

Rydel's third ask: "the dashboards need accurate, updated data." Phase 0
found the sources were fine and the CHAIN was not — the sheet mirror is
ninety seconds fresh and the GHL mirror a minute, but the engine blocks the
tiles actually read were SEVENTY MINUTES old, because they rebuild only on
the two-hour snapshot loop. And neither Refresh button touched them: both
rebuilt the snapshot and left every cache where it was.

This module owns three things:

  THE CONTRACT   a stated budget per source, on the System page, so "fresh"
                 is a number you can hold the system to rather than a vibe.
  THE TICK       a cheap loop that rebuilds the engine blocks when their
                 INPUTS are newer than they are — so a tile follows its
                 source within minutes instead of hours.
  REFRESH NOW    an explicit owner action that pulls what can safely be
                 pulled, invalidates what it touched, recomputes, and says
                 what it did. XERO IS NEVER FORCE-PULLED: its refresh chain
                 is single-use, so it rides the batched pull and the button
                 says when that is.

"As of" is always computed from a value's INPUTS, never from the moment the
page rendered. A page can be drawn in a millisecond and still be showing you
yesterday.
"""

from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

K_LAST_REFRESH = "freshness:last_refresh"     # the Refresh-now journal
K_TICK = "freshness:last_tick"

# ── THE CONTRACT ────────────────────────────────────────────────────────────
# minutes. Stated on the System page; a source past its budget goes amber and
# NAMES itself on every tile that depends on it.
CONTRACT: dict[str, dict] = {
    "tracker_mirror": {
        "label": "Lead-to-Cash tracker (mirror)", "budget_min": 3,
        "cadence": "every 90 seconds",
        "note": "the sheet mirror; the tracker itself is written by hand"},
    "ghl_opportunities": {
        "label": "CRM deals and appointments", "budget_min": 20,
        "cadence": "every 15 minutes",
        "note": "opportunities on the loop; contacts and notes incrementally"},
    "stripe": {
        "label": "Stripe receipts", "budget_min": 20,
        "cadence": "with the snapshot",
        "note": "cash is Stripe-receipted money (R-CASH)"},
    "meta_today": {
        "label": "Meta ad spend (today)", "budget_min": 60,
        "cadence": "hourly",
        "note": "today is intraday and labelled; closed days come from the archive"},
    "xero": {
        "label": "Xero (bank + P&L)", "budget_min": 24 * 60,
        "cadence": "batched",
        "note": ("bank feeds can lag the bank by up to a day — and Xero is "
                 "never force-pulled here: its refresh token is single-use, "
                 "so a forced pull risks the whole chain")},
    "mrr_snapshot": {
        "label": "MRR snapshot", "budget_min": 36 * 60,
        "cadence": "daily", "note": "one point per day"},
    "engine_blocks": {
        "label": "Engine blocks and rollups", "budget_min": 10,
        "cadence": "every 5 minutes when their inputs move",
        "note": ("the tiles read these, not the sources — this is the link "
                 "that used to lag two hours behind a ninety-second mirror")},
}


def _age_min(iso) -> float | None:
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=now_sydney().tzinfo)
        return round((now_sydney() - d).total_seconds() / 60.0, 1)
    except Exception:
        return None


def relative(iso) -> str:
    """'4 minutes ago'. Plain words — the registry's language."""
    m = _age_min(iso)
    if m is None:
        return "age unknown"
    if m < 1:
        return "just now"
    if m < 60:
        return f"{int(m)} minute{'s' if int(m) != 1 else ''} ago"
    if m < 48 * 60:
        h = m / 60
        return f"{h:.1f} hours ago"
    return f"{m / 1440:.1f} days ago"


def _source_stamps() -> dict:
    """The last success per source, read from where each job already records
    it. Nothing new is written to learn this."""
    out: dict = {}
    try:
        import sheet_mirror
        rows = sheet_mirror.get_sources() or []
        newest = max((r.get("last_sync_at") for r in rows if r.get("last_sync_at")),
                     default=None)
        bad = [r.get("tab") for r in rows if r.get("last_sync_status") not in ("ok", None)]
        out["tracker_mirror"] = {"at": newest, "tabs": len(rows), "failing": bad}
    except Exception as e:  # noqa: BLE001
        out["tracker_mirror"] = {"at": None, "error": str(e)[:120]}
    try:
        import ghl_mirror
        rows = ghl_mirror.get_sources() or []
        opp = next((r for r in rows if "opportunit" in str(r.get("source", ""))), None)
        out["ghl_opportunities"] = {"at": (opp or {}).get("last_sync_at"),
                                    "ok": (opp or {}).get("ok"),
                                    "rows": (opp or {}).get("row_count")}
        notes = next((r for r in rows if "note" in str(r.get("source", ""))), None)
        if notes:
            out["ghl_contacts_notes"] = {"at": notes.get("last_sync_at"),
                                         "ok": notes.get("ok")}
    except Exception as e:  # noqa: BLE001
        out["ghl_opportunities"] = {"at": None, "error": str(e)[:120]}
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        out["stripe"] = {"at": snap.get("generated_at"),
                         "note": "arrives with the snapshot"}
        out["xero"] = {"at": (snap.get("cash_position") or {}).get("cash_as_of")
                       or snap.get("generated_at")}
        out["mrr_snapshot"] = {"at": (kv_store.get("mrr:last_snapshot") or {}).get("at")
                               or snap.get("generated_at")}
    except Exception as e:  # noqa: BLE001
        out["stripe"] = {"at": None, "error": str(e)[:120]}
    try:
        # the Meta archive is keyed BY DAY; today's entry carries when it was
        # last fetched, which is the freshness that matters for an intraday
        # number.
        import meta_spend
        from helpers import today_sydney
        st = meta_spend._load_store() or {}
        today_row = st.get(str(today_sydney())) or {}
        out["meta_today"] = {"at": today_row.get("last_fetched"),
                             "spend_today": today_row.get("spend"),
                             "days_stored": len(st)}
        if not today_row:
            out["meta_today"]["note"] = ("no entry for today yet — spend is "
                                         "intraday and arrives on the hour")
    except Exception as e:  # noqa: BLE001
        out["meta_today"] = {"at": None, "error": str(e)[:120]}
    # the engine blocks the tiles actually read
    oldest, which = None, None
    for key in ("exec:cache:nets", "exec:cache:unit_econ", "exec:cache:roas",
                "compass:pulse", "today:cache:week", "today:cache:spend",
                "today:cache:travelling"):
        at = (kv_store.get(key) or {}).get("computed_at")
        a = _age_min(at)
        if a is not None and (oldest is None or a > oldest):
            oldest, which = a, key
    out["engine_blocks"] = {"at": None if which is None else
                            (kv_store.get(which) or {}).get("computed_at"),
                            "oldest_block": which}
    return out


def sources() -> dict:
    """Every source: last success, age against its budget, next scheduled,
    status and the reason. This is what the System page renders — from
    STORED stamps, never by calling the source."""
    stamps = _source_stamps()
    rows = []
    stale = []
    for key, c in CONTRACT.items():
        st = stamps.get(key) or {}
        at = st.get("at")
        age = _age_min(at)
        if st.get("error"):
            status, reason = "degraded", st["error"]
        elif age is None:
            status, reason = "unknown", "no successful run recorded"
        elif age > c["budget_min"]:
            status = "stale"
            reason = (f"last success {relative(at)}, past its "
                      f"{_budget_words(c['budget_min'], possessive=True)} budget")
            stale.append(key)
        else:
            status, reason = "ok", f"last success {relative(at)}"
        if st.get("failing"):
            status = "degraded"
            reason = f"failing: {', '.join(str(x) for x in st['failing'][:3])}"
        rows.append({
            "key": key, "label": c["label"], "at": at,
            "age_minutes": age, "age_words": relative(at),
            "budget_minutes": c["budget_min"],
            "budget_words": _budget_words(c["budget_min"]),
            "cadence": c["cadence"], "note": c["note"],
            "status": status, "reason": reason,
            "detail": {k: v for k, v in st.items() if k != "at"},
        })
    return {"rows": rows, "stale": stale,
            "ok": not stale and not any(r["status"] == "degraded" for r in rows),
            "as_of": now_sydney().isoformat(),
            "contract_note": ("every source carries a stated budget. Past it, "
                              "the source goes amber and names itself on every "
                              "tile that depends on it.")}


def _budget_words(minutes: int, possessive: bool = False) -> str:
    """'10 minutes' standing alone; '10-minute' before the word budget."""
    if minutes < 60:
        n, unit = minutes, "minute"
    elif minutes < 24 * 60:
        n, unit = minutes // 60, "hour"
    else:
        n, unit = minutes // (24 * 60), "day"
    if possessive:
        return f"{n}-{unit}"
    return f"{n} {unit}" + ("s" if n != 1 else "")


# ── AS-OF, from a value's INPUTS ────────────────────────────────────────────

# tile → the sources it actually depends on. A tile is only as fresh as its
# OLDEST input, and it names that input when it goes amber.
TILE_INPUTS: dict[str, tuple] = {
    "cash_on_hand": ("xero",),
    "committed_mrr": ("tracker_mirror", "xero"),
    "ar_outstanding": ("tracker_mirror", "stripe"),
    "cash_net_mtd": ("stripe", "xero", "engine_blocks"),
    "operating_net_mtd": ("stripe", "xero", "engine_blocks"),
    "ltv_cac": ("tracker_mirror", "meta_today", "engine_blocks"),
    "ltgp_cac": ("tracker_mirror", "meta_today", "engine_blocks"),
    "cohort_cash_roas": ("tracker_mirror", "meta_today", "engine_blocks"),
    "week_flow": ("tracker_mirror", "ghl_opportunities", "engine_blocks"),
    "ad_spend": ("meta_today", "engine_blocks"),
    "pulse_show_rate": ("tracker_mirror", "ghl_opportunities", "engine_blocks"),
    "pulse_close_rate": ("tracker_mirror", "ghl_opportunities", "engine_blocks"),
    "pulse_booked_calls": ("ghl_opportunities",),
}


def as_of(tile_id: str, src: dict | None = None) -> dict:
    """A tile's freshness, computed from its INPUTS — never from render time.

    Returns the oldest input's timestamp, words for it, whether it is past
    budget, and WHICH source is the laggard, so the tile can say so."""
    s = src or sources()
    by_key = {r["key"]: r for r in s["rows"]}
    inputs = TILE_INPUTS.get(tile_id) or ()
    rows = [by_key[k] for k in inputs if k in by_key]
    if not rows:
        return {"at": None, "words": "age unknown", "state": "unknown",
                "inputs": list(inputs),
                "why": "this tile's inputs are not registered"}
    dated = [r for r in rows if r["age_minutes"] is not None]
    if not dated:
        return {"at": None, "words": "age unknown", "state": "unknown",
                "inputs": list(inputs), "why": "no input has a recorded time"}
    oldest = max(dated, key=lambda r: r["age_minutes"])
    degraded = [r for r in rows if r["status"] == "degraded"]
    if degraded:
        return {"at": oldest["at"], "words": oldest["age_words"],
                "state": "degraded", "inputs": list(inputs),
                "stale_source": degraded[0]["label"],
                "why": f"{degraded[0]['label']}: {degraded[0]['reason']}"}

    # THE LAGGARD IS THE ONE PAST ITS BUDGET, NOT THE ONE WITH THE BIGGEST
    # NUMBER. Found by the stale drill: committed MRR reads the tracker and
    # Xero; pausing the tracker for six hours left the tile calm and talking
    # about Xero, because Xero's 19 hours is a bigger number — and entirely
    # within its 24-hour budget. Rank by how far past budget a source is;
    # only when nothing is late does the oldest input speak for the tile.
    late = [r for r in dated if r["status"] == "stale"]
    if late:
        worst = max(late, key=lambda r: r["age_minutes"] / (r.get("budget_minutes") or 1))
        return {
            "at": worst["at"], "words": worst["age_words"], "state": "stale",
            "inputs": list(inputs), "oldest_input": oldest["key"],
            "stale_source": worst["label"],
            "why": (f"{worst['label']} {worst['age_words']} — past its "
                    f"{_budget_words(worst['budget_minutes'], True)} budget"),
        }
    return {
        "at": oldest["at"], "words": oldest["age_words"], "state": "ok",
        "inputs": list(inputs), "oldest_input": oldest["key"],
        "stale_source": None,
        "why": f"{oldest['label']} {oldest['age_words']}",
    }


# ── THE TICK — keep the engine blocks close to their inputs ─────────────────

def blocks_need_rebuild(max_age_min: int | None = None) -> dict:
    """Are the engine blocks older than their inputs (or past budget)?

    This is the link Phase 0 found lagging: a ninety-second mirror feeding a
    two-hour cache. The tick rebuilds when the answer is yes — it does NOT
    rebuild on a timer for its own sake."""
    budget = max_age_min or CONTRACT["engine_blocks"]["budget_min"]
    stamps = _source_stamps()
    block_at = (stamps.get("engine_blocks") or {}).get("at")
    block_age = _age_min(block_at)
    if block_age is None:
        return {"rebuild": True, "why": "the engine blocks have never been built"}
    if block_age > budget:
        return {"rebuild": True,
                "why": (f"the blocks are {relative(block_at)} — past their "
                        f"{budget}-minute budget"),
                "block_age_min": block_age}
    # a source that moved AFTER the blocks were built
    newer = []
    for key in ("tracker_mirror", "ghl_opportunities"):
        a = _age_min((stamps.get(key) or {}).get("at"))
        if a is not None and a < block_age:
            newer.append(key)
    if newer:
        return {"rebuild": True,
                "why": (f"{', '.join(newer)} moved after the blocks were "
                        f"built {relative(block_at)}"),
                "block_age_min": block_age, "newer_sources": newer}
    return {"rebuild": False, "why": f"blocks built {relative(block_at)}, inputs older",
            "block_age_min": block_age}


def tick() -> dict:
    """Rides a SHORT loop. Cheap by construction: it reads stamps, decides,
    and only then rebuilds. No external pull happens here — the blocks are
    recomputed from data the sync jobs already landed."""
    out = {"at": now_sydney().isoformat(), "rebuilt": []}

    # TODAY'S META ROW AGES OUT ON ITS OWN, whatever the blocks are doing.
    # The archive is store-first, so a day already captured is never
    # re-fetched. This check used to sit INSIDE the rebuild branch, so on a
    # quiet tick — blocks fresh, nothing to rebuild — the intraday spend
    # number drifted past its hour and nobody refreshed it. Same defect as
    # the one this whole module exists to fix, one level down.
    try:
        s = sources()
        meta = next((r for r in s["rows"] if r["key"] == "meta_today"), None)
        if meta and meta["status"] in ("stale", "unknown", "degraded"):
            import meta_spend
            out["meta_today"] = meta_spend.refresh_today()
    except Exception as e:  # noqa: BLE001
        logger.info("freshness tick: meta refresh skipped: %s", e)

    decision = blocks_need_rebuild()
    out.update(decision)
    if not decision["rebuild"] and not (out.get("meta_today") or {}).get("changed"):
        kv_store.put(K_TICK, out)
        return out
    if not decision["rebuild"]:
        out["why"] = "today's ad spend moved — the tiles that read it rebuild"
    for name, fn in _block_builders():
        try:
            fn()
            out["rebuilt"].append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("freshness tick: %s failed: %s", name, e)
            out.setdefault("failed", []).append({"block": name, "why": str(e)[:120]})
    kv_store.put(K_TICK, out)
    logger.info("freshness tick: rebuilt %s (%s)", out["rebuilt"], decision["why"])
    return out


def _block_builders():
    """The cheap caches the tiles read. Deliberately NOT build_snapshot() —
    that is the heavy two-hour job and it pulls externally."""
    def _exec():
        from dashboard import exec_top
        exec_top.refresh_cache()

    def _today():
        from dashboard import today as t
        t.refresh_cache()

    def _pulse():
        import compass_engine
        compass_engine.sales_pulse(fresh=True)

    return (("exec_top", _exec), ("today", _today), ("sales_pulse", _pulse))


def last_tick() -> dict:
    return kv_store.get(K_TICK) or {"at": None, "note": "the tick has not run yet"}


# ── REFRESH NOW ─────────────────────────────────────────────────────────────

_MIN_SECONDS_BETWEEN = 60          # rate limit


def refresh_now(actor: str = "owner", what: str = "all") -> dict:
    """The owner's explicit refresh. Pulls what can SAFELY be pulled, then
    rebuilds the blocks the tiles read — which is the half the old buttons
    never did.

    XERO IS NOT PULLED. Its refresh token is single-use and persisted; a
    forced pull risks breaking the chain for every Xero read on the estate.
    It rides the batched pull, and this says when that is.
    """
    last = kv_store.get(K_LAST_REFRESH) or {}
    since = _age_min(last.get("at"))
    if since is not None and since * 60 < _MIN_SECONDS_BETWEEN:
        return {"ok": False, "rate_limited": True,
                "why": f"a refresh ran {relative(last.get('at'))}; give it a minute",
                "last": last}

    steps: list[dict] = []

    def _step(name, fn):
        t0 = now_sydney()
        try:
            res = fn()
            steps.append({"step": name, "ok": True,
                          "ms": int((now_sydney() - t0).total_seconds() * 1000),
                          "detail": res})
        except Exception as e:  # noqa: BLE001
            logger.warning("refresh_now: %s failed: %s", name, e)
            steps.append({"step": name, "ok": False, "why": str(e)[:140],
                          "ms": int((now_sydney() - t0).total_seconds() * 1000)})

    if what in ("all", "sources"):
        def _sheets():
            import sheet_mirror
            r = sheet_mirror.sync_all()
            return {"tabs": len(r) if isinstance(r, (list, dict)) else None}
        _step("tracker mirror", _sheets)

        def _ghl():
            import ghl_mirror
            return ghl_mirror.sync_opportunities()
        _step("CRM deals", _ghl)

        def _meta():
            import meta_spend
            return meta_spend.refresh_today()
        _step("Meta spend (today)", _meta)

    # the half that was missing: rebuild what the tiles actually read
    for name, fn in _block_builders():
        _step(f"rebuild {name}", fn)

    rec = {"at": now_sydney().isoformat(), "by": actor, "what": what,
           "steps": steps,
           "ok": all(s["ok"] for s in steps),
           "xero": {"pulled": False,
                    "why": ("Xero is never force-pulled — its refresh token is "
                            "single-use, so a forced pull risks the chain"),
                    "next": _next_xero_words()}}
    journal = kv_store.get(K_LAST_REFRESH + ":journal") or []
    journal.append({k: rec[k] for k in ("at", "by", "what", "ok")})
    kv_store.put(K_LAST_REFRESH + ":journal", journal[-100:])
    kv_store.put(K_LAST_REFRESH, rec)
    return rec


def _next_xero_words() -> str:
    """When the batched pull next runs — said plainly on the button."""
    try:
        from snapshot import load_persisted
        import os
        hours = float(os.environ.get("REFRESH_INTERVAL_HOURS", "2"))
        at = (load_persisted() or {}).get("generated_at")
        age = _age_min(at)
        if age is None:
            return "with the next scheduled pull"
        left = max(hours * 60 - age, 0)
        if left < 1:
            return "with the next scheduled pull, due now"
        return (f"with the next scheduled pull, in about "
                f"{int(left)} minute{'s' if int(left) != 1 else ''}")
    except Exception:
        return "with the next scheduled pull"


def last_refresh() -> dict:
    return kv_store.get(K_LAST_REFRESH) or {"at": None,
                                            "note": "no manual refresh yet"}
