"""change_ledger.py — "SINCE YOUR LAST LOOK: X → Y, BECAUSE …" (#171, Phase 4).

A number that moves without a stated reason is a number nobody trusts; a
number that stays put without a reason is worse ("is it stuck?"). Every
headline ratio tile's drawer now carries one of two sentences:

  · "Since your last look: 3.52× → 3.61× because …" with the top causes in
    plain words and in ×, OR
  · "Unchanged because …" naming what is still pending (e.g. "Rocky's
    Italian has no contract value yet").

HOW THE CAUSES SUM TO THE CHANGE. The ratio is  R = L ÷ C  where L is the
average expected lifetime value per close (closes with a contract) and C is
the loaded acquisition cost per close. The change decomposes EXACTLY:

    ΔR = (L₁ − L₀) ÷ C₀            ← the lifetime-value side
       + L₁ × (1 ÷ C₁ − 1 ÷ C₀)     ← the cost side

so the two sides always sum to the actual ΔR (test_change_ledger pins it to
0.01×). Inside each side the dollar movements are listed by name: closes
that entered or left the window, contract values that appeared or changed,
and each acquisition-cost component (ad spend, commissions, …).

The ledger stores a compact state on every engine refresh (exec_top's
cache) — last 90 — and `since(user)` picks the state at or before that
user's previous visit stamp (today.py keeps it).
"""
from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

K_HISTORY = "change_ledger:unit_econ"      # [state, ...] newest last
KEEP = 90


def _compact(view: dict) -> dict:
    out = {"at": view.get("as_of") or now_sydney().isoformat(), "windows": {}}
    for wk in ("headline", "mtd"):
        w = view.get(wk) or {}
        out["windows"][wk] = {
            "ltv_cac_expected": w.get("ltv_cac_expected"),
            "ltgp_cac_expected": w.get("ltgp_cac_expected"),
            "ltv_cac_floor": w.get("ltv_cac_floor"),
            "ltgp_cac_floor": w.get("ltgp_cac_floor"),
            "ltv_expected": w.get("ltv_expected"),
            "ltv_floor": w.get("ltv_floor"),
            "cac_loaded": w.get("cac_loaded"),
            "acquisition_total": w.get("acquisition_total"),
            "closes": w.get("closes"),
            "ltv_known": w.get("ltv_known"),
            "components": {c.get("label"): round(float(c.get("amount") or 0), 2)
                           for c in (w.get("cac_components") or [])},
            "rows": {r.get("person"): {"client": r.get("client"),
                                       "expected": r.get("expected"),
                                       "floor": r.get("floor"),
                                       "contract": r.get("contract_ex_gst")}
                     for r in (w.get("rows") or []) if r.get("person")},
            "ltv_pending": list(w.get("ltv_pending") or []),
            "commission_pending": w.get("commission_pending"),
        }
    out["margin_pct"] = (view.get("margin") or {}).get("pct")
    return out


def record(view: dict) -> dict:
    """Store this refresh's compact state. Called by exec_top.refresh_cache."""
    st = _compact(view)
    hist = kv_store.get(K_HISTORY) or []
    hist.append(st)
    kv_store.put(K_HISTORY, hist[-KEEP:])
    return st


def history() -> list[dict]:
    return kv_store.get(K_HISTORY) or []


def state_at_or_before(when_iso: str | None) -> dict | None:
    hist = history()
    if not hist:
        return None
    if not when_iso:
        return hist[0]
    try:
        when = dt.datetime.fromisoformat(str(when_iso))
    except ValueError:
        return hist[0]
    best = None
    for st in hist:
        try:
            at = dt.datetime.fromisoformat(str(st["at"]))
        except (ValueError, KeyError):
            continue
        if at <= when:
            best = st
        else:
            break
    return best or hist[0]


def _money(v) -> str:
    return f"${float(v):,.0f}"


def decompose(before: dict | None, now: dict, window: str = "headline",
              ratio: str = "ltv_cac") -> dict:
    """The two-sided exact decomposition + named dollar movements, for one
    ratio in one window. Returns {changed, from, to, delta, sides, causes,
    sentence}."""
    w1 = (now or {}).get("windows", {}).get(window) or {}
    w0 = (before or {}).get("windows", {}).get(window) or {}
    key = f"{ratio}_expected"
    r0, r1 = w0.get(key), w1.get(key)
    name = "LTGP:CAC" if ratio == "ltgp_cac" else "LTV:CAC"
    margin = (now.get("margin_pct") or 100.0) / 100.0 if ratio == "ltgp_cac" else 1.0
    out = {"ratio": name, "window": window, "from": r0, "to": r1,
           "delta": (round(r1 - r0, 2) if r0 is not None and r1 is not None else None),
           "causes": [], "sides": {}}

    pending = []
    for p in w1.get("ltv_pending") or []:
        client = ((w1.get("rows") or {}).get(p) or {}).get("client")
        pending.append(f"{client or p} has no contract value yet")
    if w1.get("commission_pending"):
        pending.append(f"commission is still pending on {w1['commission_pending']} close(s)")

    if r0 is None or r1 is None:
        out["changed"] = r0 != r1
        out["sentence"] = (f"{name}: no earlier value to compare with"
                           if before is None else
                           f"{name} is {('now ' + str(r1) + '×') if r1 is not None else 'undefined'}"
                           + (f" (was {r0}×)" if r0 is not None else ""))
        if pending:
            out["sentence"] += " — " + "; ".join(pending[:3])
        return out

    L0, L1 = (w0.get("ltv_expected") or 0.0) * margin, (w1.get("ltv_expected") or 0.0) * margin
    C0, C1 = w0.get("cac_loaded"), w1.get("cac_loaded")
    if not C0 or not C1:
        out["changed"] = abs(r1 - r0) >= 0.005
        out["sentence"] = f"{name} {r0}× → {r1}× (acquisition cost per close unavailable on one side)"
        return out
    ltv_side = (L1 - L0) / C0
    cost_side = L1 * (1.0 / C1 - 1.0 / C0)
    out["sides"] = {"lifetime_value": round(ltv_side, 2), "acquisition_cost": round(cost_side, 2),
                    "sum": round(ltv_side + cost_side, 2)}

    # named movements — lifetime-value side
    rows0, rows1 = w0.get("rows") or {}, w1.get("rows") or {}
    for p, r in rows1.items():
        if p not in rows0:
            who = r.get("client") or p
            if r.get("expected") is not None:
                out["causes"].append({"side": "lifetime_value", "what": f"{who} entered the window",
                                      "amount": r["expected"]})
            else:
                out["causes"].append({"side": "lifetime_value",
                                      "what": f"{who} entered the window with no contract value yet",
                                      "amount": None})
        else:
            e0, e1 = rows0[p].get("expected"), r.get("expected")
            if e0 is None and e1 is not None:
                out["causes"].append({"side": "lifetime_value",
                                      "what": f"{r.get('client') or p} gained a contract value "
                                              f"({_money(r.get('contract') or 0)} ex-GST)",
                                      "amount": e1})
            elif e0 is not None and e1 is not None and abs(e1 - e0) > 0.5:
                out["causes"].append({"side": "lifetime_value",
                                      "what": f"{r.get('client') or p}'s expected lifetime value moved",
                                      "amount": round(e1 - e0, 2)})
    for p, r in rows0.items():
        if p not in rows1:
            out["causes"].append({"side": "lifetime_value",
                                  "what": f"{r.get('client') or p} left the window",
                                  "amount": -(r.get("expected") or 0) if r.get("expected") is not None else None})
    # cost side — by component
    c0, c1 = w0.get("components") or {}, w1.get("components") or {}
    for label in sorted(set(c0) | set(c1)):
        d = round((c1.get(label) or 0) - (c0.get(label) or 0), 2)
        if abs(d) >= 1:
            out["causes"].append({"side": "acquisition_cost",
                                  "what": f"{label} {'rose' if d > 0 else 'fell'} {_money(abs(d))}",
                                  "amount": d})
    if (w1.get("closes") or 0) != (w0.get("closes") or 0):
        out["causes"].append({"side": "acquisition_cost",
                              "what": f"closes in the window {w0.get('closes')} → {w1.get('closes')} "
                                      "(cost per close spreads over them)", "amount": None})

    out["changed"] = abs(r1 - r0) >= 0.005
    if out["changed"]:
        bits = []
        if abs(ltv_side) >= 0.005:
            bits.append(f"lifetime value side {ltv_side:+.2f}×")
        if abs(cost_side) >= 0.005:
            bits.append(f"acquisition cost side {cost_side:+.2f}×")
        named = [c["what"] for c in out["causes"]][:4]
        out["sentence"] = (f"Since your last look: {name} {r0:.2f}× → {r1:.2f}× "
                           f"({r1 - r0:+.2f}×) because " + ", ".join(bits)
                           + (" — " + "; ".join(named) if named else "") + ".")
    else:
        why = pending[:2] or ["no close entered or left the window and no cost line moved"]
        out["sentence"] = f"Unchanged at {r1:.2f}× because " + "; ".join(why) + "."
    return out


def since(user_last_seen_iso: str | None, view: dict | None = None) -> dict:
    """What the drawer renders: one sentence per ratio for the headline and
    month to date, against the state at the user's previous visit."""
    hist = history()
    if not hist:
        return {"available": False, "note": "no history yet — the ledger starts recording "
                                            "on the next engine refresh"}
    now = _compact(view) if view else hist[-1]
    before = state_at_or_before(user_last_seen_iso)
    out = {"available": True, "compared_to": (before or {}).get("at"),
           "last_seen": user_last_seen_iso, "items": {}}
    for wk in ("headline", "mtd"):
        for ratio in ("ltv_cac", "ltgp_cac"):
            out["items"][f"{wk}:{ratio}"] = decompose(before, now, wk, ratio)
    return out


def previous_visit(user: str) -> str | None:
    """today.py keeps {user: now, user+':prev': the visit before}."""
    marks = kv_store.get("today:last_seen") or {}
    return marks.get(f"{user}:prev") or marks.get(user)
