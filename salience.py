"""
salience.py
-----------
What's genuinely NEW and IMPORTANT since EDITH last greeted Rydel — a deterministic event feed she
leads with, instead of the same fixed stat litany. Every event comes from a real source with a
timestamp (never invented — the deterministic-recall discipline applies to greetings too), is ranked
by importance × recency, and is WATERMARKED so known news is never re-announced.

Event types (importance):
  failed payment / past-due (money at risk)  100/95  — from Stripe
  deal CLOSED                                 80     — from the mirror (won rows)
  payout LANDED                               60     — from Stripe (count increased)
  notable NEW LEAD(s)                         40     — from the mirror (batched if many)
  metric THRESHOLD crossing (runway)          30     — from the engines

State (kv_store, durable): last_greeted_at, told[event ids], last_payout_count, last_runway.
"""
from __future__ import annotations

import re

import kv_store
from helpers import today_sydney

_K_STATE = "salience:state"
_RECENCY_DAYS = 2          # date-based events (close/lead) only surface if within N days
_TOLD_CAP = 300


def _state() -> dict:
    s = kv_store.get(_K_STATE) or {}
    s.setdefault("told", [])
    return s


def _save(s: dict) -> None:
    if len(s.get("told", [])) > _TOLD_CAP:
        s["told"] = s["told"][-_TOLD_CAP:]
    kv_store.put(_K_STATE, s)


def _norm(x) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x or "").lower())


def _days_ago(datestr: str) -> int | None:
    try:
        import datetime as dt
        d = dt.date.fromisoformat(str(datestr)[:10])
        return (today_sydney() - d).days
    except Exception:
        return None


# ── Collect ──────────────────────────────────────────────────────────────────

def collect(snap: dict | None = None) -> list[dict]:
    """All UNTOLD salient events, ranked (most important+recent first). Deterministic; read-only —
    call mark_told() to watermark what a greeting actually surfaced."""
    from snapshot import load_persisted
    snap = snap or load_persisted() or {}
    told = set(_state().get("told", []))
    events: list[dict] = []

    # 1) Deals closed (mirror) — recent + untold
    try:
        import closes_view
        for d in (closes_view.recent_closes(15).get("closes") or []):
            ago = _days_ago(d.get("close_date"))
            if ago is None or ago > _RECENCY_DAYS:
                continue
            eid = f"close:{_norm(d.get('business'))}:{d.get('close_date')}"
            if eid in told:
                continue
            val = d.get("contract") or 0
            events.append({"id": eid, "type": "close", "salience": 80, "ago": ago,
                           "spoken": f"{d.get('business')} closed — ${val:,.0f}"
                                     + (f" ({d.get('offer')})" if d.get("offer") else "")})
    except Exception:
        pass

    # 2) Money at risk (Stripe) — failed charges + past-due subscriptions.
    # RELIABILITY GATE (F2): the Stripe MCP sometimes miscounts (e.g. 1 active sub reported against
    # $67k MRR). When the snapshot flags that mismatch, failed_charges_count from the SAME source is
    # unreliable — don't blast it as a top alert. Suppress rather than cry wolf daily.
    st = (snap or {}).get("stripe") or {}
    _stripe_unreliable = any("stripe_mrr_subs_mismatch" in str((d or {}).get("metric", ""))
                             for d in ((snap or {}).get("degraded") or []))
    fc = st.get("failed_charges_count")
    if fc and not _stripe_unreliable:
        eid = f"failed:{fc}:{today_sydney()}"
        if eid not in told:
            events.append({"id": eid, "type": "failed", "salience": 100, "ago": 0,
                           "spoken": f"{fc} charge{'s' if fc != 1 else ''} failed today — worth a look"})
    pd = ((st.get("subscriptions") or {}).get("past_due"))
    if pd and not _stripe_unreliable:   # same unreliable subscriptions block → gate it too
        eid = f"pastdue:{pd}"
        if eid not in told:
            events.append({"id": eid, "type": "past_due", "salience": 95, "ago": 0,
                           "spoken": f"{pd} subscription{'s' if pd != 1 else ''} past due"})

    # 3) Payout landed (Stripe) — count increased since last seen
    payouts = st.get("payouts") or {}
    pc = payouts.get("payout_count")
    last_pc = _state().get("last_payout_count")
    if pc is not None and last_pc is not None and pc > last_pc:
        amt = payouts.get("total_paid_out") or 0
        eid = f"payout:{pc}"
        if eid not in told:
            events.append({"id": eid, "type": "payout", "salience": 60, "ago": 0,
                           "spoken": f"a payout landed — ${amt:,.0f} banked recently"})

    # 4) New leads (mirror) — batched if several
    try:
        import leads_view
        fresh = []
        for L in (leads_view.recent_leads(25).get("leads") or []):
            ago = _days_ago(L.get("date"))
            if ago is None or ago > _RECENCY_DAYS:
                continue
            eid = f"lead:{_norm(L.get('business'))}:{L.get('date')}:{_norm(L.get('time'))}"
            if eid in told:
                continue
            fresh.append((eid, L))
        if len(fresh) == 1:
            _, L = fresh[0]
            src = L.get("source") or "new"
            biz = L.get("business") or ""
            events.append({"id": fresh[0][0], "type": "lead", "salience": 40, "ago": 0,
                           "spoken": f"a fresh {src} lead" + (f" — {biz}" if biz else "")})
        elif len(fresh) > 1:
            events.append({"id": f"leadbatch:{len(fresh)}:{today_sydney()}",
                           "_ids": [e for e, _ in fresh], "type": "lead", "salience": 45, "ago": 0,
                           "spoken": f"{len(fresh)} new leads in"})
    except Exception:
        pass

    # 4b) Paid-but-unlogged (cash_truth) — Stripe money ahead of the tracker cash cell.
    # Greeting-worthy: real cash landed that the team hasn't logged yet. Watermarked per
    # business+gap so a growing gap re-surfaces but a known one never repeats.
    try:
        for n in ((snap or {}).get("cash_truth") or {}).get("needs_logging") or []:
            eid = f"unlogged:{_norm(n.get('business'))}:{int(n.get('gap') or 0)}"
            if eid in told:
                continue
            events.append({"id": eid, "type": "unlogged", "salience": 85, "ago": 0,
                           "spoken": (f"{n.get('business')} has ${n.get('gap'):,.0f} landed in "
                                      f"Stripe that isn't logged in the tracker yet")})
    except Exception:
        pass

    # 5) Runway threshold crossing (engine) — crossed BELOW a floor since last seen
    rw = ((snap or {}).get("cash_position") or {}).get("runway_months")
    last_rw = _state().get("last_runway")
    if isinstance(rw, (int, float)) and isinstance(last_rw, (int, float)):
        for floor in (3, 6, 12):
            if last_rw >= floor > rw:
                eid = f"runway_below:{floor}"
                if eid not in told:
                    events.append({"id": eid, "type": "threshold", "salience": 55, "ago": 0,
                                   "spoken": f"runway dipped below {floor} months ({rw:.1f} now)"})
                break

    # 6) A hiring trigger firing — capacity crossed the threshold (watermarked like the rest).
    try:
        import capacity_engine
        for t in (capacity_engine.hire_trigger(snap).get("triggers") or []):
            if t.get("fired"):
                eid = f"hiretrigger:{_norm(t['dept'])}"
                if eid not in told:
                    events.append({"id": eid, "type": "hire_trigger", "salience": 50, "ago": 0,
                                   "spoken": f"{t['dept']} is at {t['current_load_pct']}% capacity — "
                                             "a hire trigger just fired"})
    except Exception:
        pass

    events.sort(key=lambda e: (e["salience"], -e["ago"]), reverse=True)
    return events


def top(snap: dict | None = None, n: int = 3) -> list[dict]:
    return collect(snap)[:n]


def mark_told(events: list[dict]) -> None:
    """Watermark the events a greeting surfaced so they're never re-announced."""
    s = _state()
    told = s.get("told", [])
    for e in events:
        told.extend(e.get("_ids") or [e["id"]])
    s["told"] = told
    _save(s)


def note_greeted(snap: dict | None = None) -> None:
    """Advance the watermark + baseline the movement counters after a greeting is issued."""
    from snapshot import load_persisted
    snap = snap or load_persisted() or {}
    s = _state()
    s["last_greeted_at"] = str(today_sydney())
    st = (snap or {}).get("stripe") or {}
    if (st.get("payouts") or {}).get("payout_count") is not None:
        s["last_payout_count"] = st["payouts"]["payout_count"]
    rw = ((snap or {}).get("cash_position") or {}).get("runway_months")
    if isinstance(rw, (int, float)):
        s["last_runway"] = rw
    _save(s)


_WHATS_NEW_RE = re.compile(r"\bwhat'?s new\b|\banything new\b|\bany(thing)? (updates?|news)\b|"
                           r"\bwhat did i miss\b|\bcatch me up\b|\bwhat happened\b", re.I)


def handle_whats_new(text: str) -> tuple[str | None, bool]:
    """'What's new?' mid-session → the salience list (same feed the greeting uses). Marks told."""
    if not text or not _WHATS_NEW_RE.search(text):
        return None, False
    events = top(None, 3)
    if not events:
        return "Nothing new since we last spoke.", True
    reply = "Here's what's new: " + summary_line(events)
    mark_told(events)
    return reply, True


def summary_line(events: list[dict]) -> str:
    """Deterministic fallback phrasing (composer-independent) — used if the model composer fails."""
    if not events:
        return "Nothing new since we last spoke."
    return "; ".join(e["spoken"] for e in events[:3]) + "."
