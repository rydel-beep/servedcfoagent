"""
cash_truth.py
-------------
Stripe-aware cash truth — the SOURCE HIERARCHY for cash questions.

THE INCIDENT: asked "what's our last cash collected", EDITH read the tracker and reported a
cash cell "genuinely blank" (on a junk row, no less). Accurate about the SHEET, wrong about
the WORLD: money may already be sitting in Stripe while the team simply hasn't typed the
cell yet. The tracker also stores cash as a CUMULATIVE per-deal figure with no payment
dates — it structurally cannot answer "when did cash last land".

THE PRINCIPLE:
  - The TRACKER is the source of truth for DEALS (who closed, offer, contract, close date).
  - STRIPE is the source of truth for CASH (payment events are ground truth regardless of
    what's typed in a cell).
"Latest cash collected" is answered from ACTUAL Stripe payment events reconciled with the
tracker; when they disagree, BOTH truths are reported and the gap is flagged for the team
to log (EDITH nudges — she never writes cash cells; logging stays a human process).

Matching (confidence recorded, per the reconciliation design):
  email exact > unambiguous normalized name > unambiguous amount+date. Anything else is
  UNMATCHED and FLAGGED — never guessed.

PII: tracker emails and Stripe emails are used in-process only and never leave this module
(asserted before return). Names/amounts/dates only in outputs.

Basis naming (one-engine discipline): figures from here are "Stripe-actual cash"; the
tracker aggregate stays "tracker-logged cash". Never the same name for both.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 30
_AMOUNT_TOL = 1.0          # AUD tolerance for amount+date matching
_AMOUNT_DATE_WINDOW = 7    # days between charge and close date for amount+date matching
_CUM_GRACE_DAYS = 7        # deposits can precede the logged close date by a few days
_LAG_KV_KEY = "cash_truth_lag_v1"
_LAG_CAP = 300


def _money(s) -> float | None:
    s = str(s or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(s) -> dt.date | None:
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(s or ""))
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\b(the|pty|ltd|co|restaurant|cafe|café|bar|kitchen|and|&)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Stripe charges (read-only, direct API — same pattern as payback_reconciliation) ──

def _recent_charges(days: int = _LOOKBACK_DAYS) -> list[dict] | None:
    """Succeeded charges in the window, newest first, with customer + balance_transaction
    expanded. None = no key / API failure (callers degrade loudly, never fabricate)."""
    from config import STRIPE_SECRET_KEY
    if not STRIPE_SECRET_KEY:
        return None
    from payback_reconciliation import _sget
    import calendar
    from helpers import today_sydney
    since = today_sydney() - dt.timedelta(days=days)
    created_gte = calendar.timegm(since.timetuple())
    out, after = [], None
    for _ in range(10):
        params = {"limit": 100, "created[gte]": created_gte,
                  "expand[]": ["data.customer", "data.balance_transaction"]}
        if after:
            params["starting_after"] = after
        r = _sget("/v1/charges", params)
        if r.get("error") is not None and not r.get("data"):
            return None
        out.extend(r.get("data") or [])
        if not r.get("has_more"):
            break
        after = out[-1]["id"]
    charges = []
    for c in out:
        if not (c.get("paid") and c.get("status") == "succeeded"):
            continue
        cust = c.get("customer") if isinstance(c.get("customer"), dict) else {}
        bd = c.get("billing_details") or {}
        bt = c.get("balance_transaction") if isinstance(c.get("balance_transaction"), dict) else {}
        avail_on = bt.get("available_on")
        charges.append({
            "id": c.get("id"),
            "date": dt.date.fromtimestamp(c["created"]),
            "amount": round((c.get("amount", 0) - c.get("amount_refunded", 0)) / 100.0, 2),
            "currency": (c.get("currency") or "aud").upper(),
            "customer_name": (cust.get("name") or bd.get("name") or "").strip(),
            "_email": ((cust.get("email") or bd.get("email")) or "").strip().lower(),  # in-process only
            "bt_status": bt.get("status"),  # pending | available
            "available_on": str(dt.date.fromtimestamp(avail_on)) if avail_on else None,
        })
    charges = [c for c in charges if c["amount"] > 0]
    charges.sort(key=lambda c: (c["date"], c["id"]), reverse=True)
    return charges


def _charge_state(ch: dict) -> str:
    """Money-state label for a succeeded charge — collected either way, banked or not."""
    if ch.get("bt_status") == "pending":
        when = f" (available {ch['available_on']})" if ch.get("available_on") else ""
        return f"collected — settling into Stripe{when}"
    return "collected — settled in Stripe balance"


# ── Tracker rows (mirror-first, fresh-read discipline via tracker_read) ─────────────

def _tracker_index() -> dict | None:
    """Header-mapped tracker rows indexed for matching. Emails stay inside this dict."""
    import tracker_read
    st = tracker_read.sync_state()
    if not st or st.get("age_seconds", 1e9) > 180:
        tracker_read.resync()
    rows = tracker_read._rows()
    if not rows:
        return None
    hi = next((i for i, r in enumerate(rows[:6])
               if any("close date" in (c or "").lower() for c in r)), 0)
    hdr = rows[hi]

    def find(*kws):
        for i, c in enumerate(hdr):
            cl = (c or "").lower()
            if all(k in cl for k in kws):
                return i
        return None

    cols = {"name": find("lead", "name"), "email": find("email"),
            "business": find("business", "name") or find("business"),
            "close": find("close", "date"), "cash": find("cash", "collect"),
            "contract": find("contract", "value") or find("contract"),
            "offer": find("offer", "sold")}
    outs = [i for i, c in enumerate(hdr) if "call outcome" in (c or "").lower()]
    if outs:
        cd = cols.get("close")
        before = [k for k in outs if cd is None or k <= cd]
        cols["outcome"] = max(before) if before else max(outs)
    if cols.get("cash") is None or cols.get("business") is None:
        return None

    def cell(r, k):
        i = cols.get(k)
        return (r[i].strip() if i is not None and i < len(r) else "")

    entries = []
    for r in rows[hi + 1:]:
        biz, nm = cell(r, "business"), cell(r, "name")
        if not (biz or nm):
            continue
        entries.append({
            "business": biz, "name": nm,
            "_email": cell(r, "email").lower(),          # never leaves the module
            "won": cell(r, "outcome").strip().lower() == "won",
            "close_date": _date(cell(r, "close")),
            "cash_cell": cell(r, "cash"),
            "cash_value": _money(cell(r, "cash")),
            "contract": cell(r, "contract"),
            "offer": cell(r, "offer"),
        })

    by_email: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        if e["_email"] and "@" in e["_email"]:
            by_email.setdefault(e["_email"], []).append(e)
        for key in (_norm(e["business"]), _norm(e["name"])):
            if key and len(key) >= 4:
                by_name.setdefault(key, []).append(e)
    return {"entries": entries, "by_email": by_email, "by_name": by_name,
            "sync_label": (tracker_read.sync_state() or {}).get("synced_at") or "live read"}


def _pick_row(cands: list[dict]) -> dict:
    """Duplicate rows per client exist — prefer the Won row with the most recent close."""
    won = [c for c in cands if c["won"] and c["close_date"]]
    if won:
        return max(won, key=lambda c: c["close_date"])
    return cands[0]


def _match_charge(ch: dict, idx: dict) -> tuple[dict | None, str | None]:
    """(tracker_entry, confidence) — email > unambiguous name > unambiguous amount+date.
    None = UNMATCHED (flagged, never guessed)."""
    em = ch.get("_email") or ""
    if em and em in idx["by_email"]:
        return _pick_row(idx["by_email"][em]), "email"
    nn = _norm(ch.get("customer_name") or "")
    if nn and len(nn) >= 4:
        cands = idx["by_name"].get(nn) or []
        # unambiguous = all candidate rows are the same client (same business label)
        labels = {(c["business"] or c["name"]) for c in cands}
        if len(labels) == 1 and cands:
            return _pick_row(cands), "name"
    # amount+date: exactly ONE won row whose cash/contract is within tolerance of the
    # charge AND whose close date is within the window. Ambiguity = no match.
    hits = []
    for e in idx["entries"]:
        if not (e["won"] and e["close_date"]):
            continue
        if abs((ch["date"] - e["close_date"]).days) > _AMOUNT_DATE_WINDOW:
            continue
        cv = e["cash_value"]
        if cv is not None and abs(cv - ch["amount"]) <= _AMOUNT_TOL:
            hits.append(e)
    if len(hits) == 1:
        return hits[0], "amount+date"
    return None, None


# ── The unified view ─────────────────────────────────────────────────────────────────

def unified_cash_view(days: int = _LOOKBACK_DAYS) -> dict:
    """Stripe payment events joined to tracker rows. The single engine behind
    latest-cash answers, the needs-logging list, and the snapshot summary."""
    charges = _recent_charges(days)
    if charges is None:
        return {"available": False,
                "degraded": [{"metric": "cash_truth",
                              "reason": "No STRIPE_SECRET_KEY / Stripe API unreachable — "
                                        "Stripe-actual cash view unavailable.",
                              "severity": "optional"}]}
    idx = _tracker_index()
    if idx is None:
        return {"available": False,
                "degraded": [{"metric": "cash_truth",
                              "reason": "Tracker unavailable — cannot reconcile Stripe payments.",
                              "severity": "optional"}]}

    payments, unmatched = [], []
    matched_rows: dict[int, dict] = {}   # id(entry) -> {"entry", "stripe_total", "last_date"}
    for ch in charges:
        entry, conf = _match_charge(ch, idx)
        p = {"date": str(ch["date"]), "amount": ch["amount"], "currency": ch["currency"],
             "customer": ch["customer_name"] or "(unnamed Stripe customer)",
             "state": _charge_state(ch),
             "matched": entry is not None, "confidence": conf,
             "business": (entry["business"] or entry["name"]) if entry else None,
             "charge_id": ch["id"]}
        if ch["currency"] != "AUD":
            p["non_aud"] = True
        payments.append(p)
        if entry is None:
            unmatched.append({"customer": p["customer"], "amount": ch["amount"],
                              "date": str(ch["date"])})
        else:
            k = id(entry)
            m = matched_rows.setdefault(k, {"entry": entry, "stripe_total": 0.0,
                                            "last_date": ch["date"], "charge_ids": []})
            grace = (entry["close_date"] - dt.timedelta(days=_CUM_GRACE_DAYS)
                     if entry["close_date"] else None)
            # cumulative comparison only counts charges belonging to THIS deal's window
            if grace is None or ch["date"] >= grace:
                m["stripe_total"] += ch["amount"]
                m["charge_ids"].append(ch["id"])
            m["last_date"] = max(m["last_date"], ch["date"])

    needs_logging = []
    for m in matched_rows.values():
        e = m["entry"]
        if not e["won"]:
            continue
        cell_val = e["cash_value"] or 0.0
        if m["stripe_total"] > cell_val + _AMOUNT_TOL:
            needs_logging.append({
                "business": e["business"] or e["name"],
                "stripe_total": round(m["stripe_total"], 2),
                "tracker_logged": e["cash_cell"] or "(blank)",
                "gap": round(m["stripe_total"] - cell_val, 2),
                "last_payment_date": str(m["last_date"]),
                "note": (f"Stripe shows ${m['stripe_total']:,.2f} since close; tracker logs "
                         f"{e['cash_cell'] or 'nothing (blank cell)'} — verify and log it."),
                "_charge_ids": m["charge_ids"],
            })
    needs_logging.sort(key=lambda x: x["gap"], reverse=True)

    lag = _update_lag_watermarks(payments, needs_logging)
    for n in needs_logging:
        n.pop("_charge_ids", None)

    out = {"available": True, "window_days": days,
           "payments": payments, "unmatched": unmatched,
           "needs_logging": needs_logging, "lag": lag,
           "sync_label": idx["sync_label"],
           "basis": "Stripe-actual cash (payment events), reconciled to tracker-logged cash",
           "degraded": ([{"metric": "cash_needs_logging",
                          "reason": f"{len(needs_logging)} deal(s) have Stripe money ahead of the "
                                    f"tracker cash cell — needs logging by the team.",
                          "severity": "optional"}] if needs_logging else [])}
    assert "@" not in str(out), "cash_truth output must not contain emails"
    return out


def _update_lag_watermarks(payments: list[dict], needs_logging: list[dict]) -> dict:
    """Observed logging lag: first time we see a charge, note it; first time its deal's cell
    covers it, close it. Observation-based (no sheet edit history) — labelled as such."""
    try:
        import kv_store
        from helpers import today_sydney
        state = kv_store.get(_LAG_KV_KEY) or {"charges": {}}
        today = str(today_sydney())
        pending_ids = {cid for n in needs_logging for cid in n.get("_charge_ids", [])}
        for p in payments:
            cid = p.get("charge_id")
            if not cid or not p.get("matched"):
                continue
            rec = state["charges"].get(cid)
            if rec is None:
                rec = state["charges"][cid] = {"date": p["date"], "first_seen": today,
                                               "logged_at": None}
            if rec["logged_at"] is None and cid not in pending_ids:
                rec["logged_at"] = today
        if len(state["charges"]) > _LAG_CAP:
            keep = sorted(state["charges"].items(), key=lambda kv: kv[1]["date"])[-_LAG_CAP:]
            state["charges"] = dict(keep)
        kv_store.put(_LAG_KV_KEY, state)
        lags = []
        for rec in state["charges"].values():
            if rec["logged_at"] and rec["first_seen"] != rec["logged_at"]:
                d0, d1 = _date(rec["date"]), _date(rec["logged_at"])
                if d0 and d1:
                    lags.append((d1 - d0).days)
        outstanding = []
        from helpers import today_sydney as _ts
        for rec in state["charges"].values():
            if rec["logged_at"] is None:
                d0 = _date(rec["date"])
                if d0:
                    outstanding.append((_ts() - d0).days)
        return {"observed_avg_days": (round(sum(lags) / len(lags), 1) if lags else None),
                "observed_count": len(lags),
                "outstanding_unlogged": len(outstanding),
                "oldest_unlogged_days": (max(outstanding) if outstanding else None),
                "method": "observed from reconciliation runs (no sheet edit history); "
                          "tracking since first run 2026-07-09"}
    except Exception as e:
        logger.info("lag watermark failed: %s", e)
        return {"observed_avg_days": None, "observed_count": 0,
                "outstanding_unlogged": None, "oldest_unlogged_days": None,
                "method": "unavailable (kv_store down)"}


def latest_cash_collected() -> dict | None:
    """The most recent ACTUAL payment event, with tracker-logging status. None = unavailable."""
    view = unified_cash_view()
    if not view.get("available") or not view.get("payments"):
        return None
    p = view["payments"][0]
    logged = not any(n["business"] == p.get("business") for n in view["needs_logging"]) \
        if p.get("matched") else None
    return {**{k: p[k] for k in ("date", "amount", "currency", "customer", "state",
                                 "matched", "confidence", "business")},
            "tracker_logged": logged, "sync_label": view["sync_label"]}


# ── Snapshot summary (PII-safe, small) ───────────────────────────────────────────────

def cash_truth_summary() -> dict:
    """For snapshot['cash_truth'] — latest payment + needs-logging + lag, compact."""
    view = unified_cash_view()
    if not view.get("available"):
        return {"cash_truth": None, "degraded": view.get("degraded", [])}
    latest = view["payments"][0] if view["payments"] else None
    summary = {
        "latest_payment": ({k: latest[k] for k in ("date", "amount", "customer", "state",
                                                   "matched", "confidence", "business")}
                           if latest else None),
        "needs_logging": view["needs_logging"][:10],
        "needs_logging_count": len(view["needs_logging"]),
        "unmatched_payments": view["unmatched"][:10],
        "unmatched_count": len(view["unmatched"]),
        "lag": view["lag"],
        "window_days": view["window_days"],
        "basis": view["basis"],
    }
    return {"cash_truth": summary, "degraded": view.get("degraded", [])}


# ── Voice / text commands ────────────────────────────────────────────────────────────

_LATEST_CASH_RE = re.compile(
    r"\b(last|latest|most recent)\b[^.?!]{0,40}\bcash\b[^.?!]{0,20}\b(collect\w*|in|landed|received)\b|"
    r"\b(last|latest|most recent)\s+(payment|cash)\b|\bwhen did (cash|money) last (land|come in|arrive)\b",
    re.I)
_LAST_DEAL_RE = re.compile(r"\b(last|latest|most recent)\b[^.?!]{0,40}\b(deal|close)\w*\b|"
                           r"\bwho\b[^.?!]{0,30}\bclos(ed|e)\b", re.I)
_NEEDS_LOG_RE = re.compile(r"\bneeds? logging\b|\bwhat needs to be logged\b|\bunlogged\b|"
                           r"\bnot (yet )?logged\b", re.I)


def _fmt_latest(latest: dict) -> str:
    who = latest["customer"]
    if latest.get("business") and _norm(latest["business"]) != _norm(who):
        who = f"{who} ({latest['business']})"
    line = (f"Last cash collected: ${latest['amount']:,.2f} from {who} on {latest['date']} — "
            f"{latest['state']}.")
    if latest.get("matched"):
        if latest.get("tracker_logged"):
            line += " Tracker: logged."
        else:
            line += " Tracker: NOT yet logged — flagged for the team."
        line += f" (matched by {latest['confidence']})"
    else:
        line += (" No matching tracker row — flagged; worth checking who this payment "
                 "belongs to.")
    return line


def handle_latest_cash_command(text: str) -> tuple[str | None, bool]:
    """'what's our last cash collected (and who was the last deal we closed)' →
    Stripe-actual latest payment + tracker status; deal question answered from the tracker."""
    if not text or not _LATEST_CASH_RE.search(text):
        return None, False
    latest = latest_cash_collected()
    if latest is None:
        return ("I can't read Stripe payment events right now, so I won't guess the latest "
                "cash. The tracker's logged figures are still available if you want those."), True
    parts = [_fmt_latest(latest)]
    if _LAST_DEAL_RE.search(text):
        try:
            import closes_view
            r = closes_view.recent_closes(limit=1)
            cl = (r.get("closes") or [None])[0]
            if cl:
                who = cl.get("business") or cl.get("name")
                val = f", ${cl['contract']:,.0f}" if cl.get("contract") else ""
                offer = f" — {cl['offer']}" if cl.get("offer") else ""
                parts.append(f"Last deal closed: {who} on {cl['close_date']}{offer}{val}.")
            else:
                parts.append("I can't see the closes in the tracker right now.")
        except Exception:
            parts.append("I can't see the closes in the tracker right now.")
    return " ".join(parts), True


def handle_needs_logging_command(text: str) -> tuple[str | None, bool]:
    """'what needs logging?' → deals with Stripe money ahead of the tracker cash cell."""
    if not text or not _NEEDS_LOG_RE.search(text):
        return None, False
    view = unified_cash_view()
    if not view.get("available"):
        return "I can't reconcile Stripe against the tracker right now, so I can't say.", True
    nl = view["needs_logging"]
    if not nl:
        msg = "Nothing needs logging — every Stripe payment I can match is reflected in the tracker."
        if view["unmatched"]:
            msg += (f" But {len(view['unmatched'])} payment(s) didn't match any tracker row — "
                    "worth a look: "
                    + "; ".join(f"${u['amount']:,.0f} from {u['customer']} on {u['date']}"
                                for u in view["unmatched"][:5]) + ".")
        return msg, True
    lines = [f"{n['business']}: Stripe ${n['stripe_total']:,.2f} vs tracker "
             f"{n['tracker_logged']} — ${n['gap']:,.2f} to log (last payment {n['last_payment_date']})"
             for n in nl[:8]]
    msg = "Needs logging — " + "; ".join(lines) + "."
    if view["unmatched"]:
        msg += (f" Plus {len(view['unmatched'])} unmatched payment(s): "
                + "; ".join(f"${u['amount']:,.0f} from {u['customer']} ({u['date']})"
                            for u in view["unmatched"][:5]) + ".")
    return msg, True
