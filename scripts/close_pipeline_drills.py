"""close_pipeline_drills.py — SEED IT, WATCH IT, MEASURE IT.

Six drills the brief asks for, each one a thing that should happen and a
measurement of whether it did. They run against an in-memory store with
seeded evidence — no Stripe, no CRM, no tracker — so they can run anywhere
and prove the LOGIC. The live confirmation is a separate pass.

  1 a closed-won transition with no tracker row  → the close appears, with
    "stage recorder" provenance and a feed item naming what is missing
  2 a payment under an unknown payer             → it lands in the panel
  3 the owner confirms it                        → alias saved + journalled,
    the row clears, and the blocks rebuild
  4 the same payer pays again later              → attached automatically
  5 a surname-only resemblance                   → NEVER auto-assigned
  6 evidence → on screen                         → measured, in milliseconds

Everything it prints is what actually happened; nothing is asserted twice.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kv_store                                   # noqa: E402
from helpers import today_sydney                  # noqa: E402

RESULTS: list[dict] = []


# Each drill swaps module functions for seeded ones. Without restoring them
# the NEXT drill inherits the last one's stubs — which is exactly how drill 6
# first "failed": it was measuring drill 3's no-op stand-in for the rebuild.
_ORIGINALS: list[tuple] = []


def swap(mod, attr, value):
    _ORIGINALS.append((mod, attr, getattr(mod, attr)))
    setattr(mod, attr, value)


def restore():
    while _ORIGINALS:
        mod, attr, value = _ORIGINALS.pop()
        setattr(mod, attr, value)


def drill(name):
    def wrap(fn):
        def run():
            t0 = time.time()
            try:
                detail = fn() or {}
                ok = detail.pop("ok", True)
            except Exception as e:  # noqa: BLE001
                ok, detail = False, {"error": f"{type(e).__name__}: {e}"}
            restore()
            ms = round((time.time() - t0) * 1000)
            RESULTS.append({"drill": name, "ok": bool(ok), "ms": ms, **detail})
            print(f"[{'PASS' if ok else 'FAIL'}] {name} ({ms}ms) "
                  f"{json.dumps(detail, default=str)[:220]}")
            return ok
        run.__name__ = fn.__name__
        return run
    return wrap


def _reset():
    kv_store._MEM.clear()


def _seed_close_sources(monkey_targets, entries):
    """Point close_detect's four readers at seeded rows."""
    import close_detect
    for attr in ("_from_tracker", "_from_ghl", "_from_stage_recorder",
                 "_from_payments"):
        swap(close_detect, attr, lambda rows=entries.get(attr, []): list(rows))
    return close_detect


@drill("1 · a closed-won transition with no tracker row becomes visible")
def drill_stage_only():
    _reset()
    d = str(today_sydney())
    cd = _seed_close_sources(None, {"_from_stage_recorder": [{
        "person": "Drill Venue", "close_date": d, "source": "stage recorder",
        "provenance": "recorded move into 'Closed Deal' (watching since 2026-09-21)",
        "evidence": {"opp_id": "opp-drill", "contact_id": "c-drill"},
        "email": None}]})
    res = cd.scan()
    e = (res["entries"] or [{}])[0]
    pkg = cd.piolo_package()
    feed = kv_store.get(cd.K_FEED) or []
    return {"ok": (e.get("person") == "Drill Venue"
                   and e.get("state") == "DETECTED"
                   and "stage recorder" in e["sources"][0]["source"]
                   and "tracker" in (e.get("corroboration_pending") or [])
                   and len(feed) == 1),
            "state": e.get("state"),
            "provenance": e["sources"][0]["provenance"] if e.get("sources") else None,
            "missing": e.get("missing"),
            "feed_title": feed[0]["title"] if feed else None,
            "package_rows": pkg.get("rows")}


@drill("2 · a payment under an unknown payer lands in the panel")
def drill_unknown_payer():
    _reset()
    import unmatched_payments as UP
    import stripe_reconcile as SR
    swap(UP, "_index", lambda: (
        {"by_email": {}, "contacts": [], "by_business": {}, "surname_map": {}},
        {"active": set(), "amounts": {}}))
    swap(UP, "_charges", lambda days: [{
        "id": "ch_drill", "date": str(today_sydney()), "amount": 3050.0,
        "customer_name": "Unknown Payer", "_email": "someone@elsewhere.com"}])
    res = UP.scan(30)
    panel = UP.panel()
    return {"ok": (res["count"] == 1 and panel["count"] == 1
                   and panel["rows"][0]["charge_id"] == "ch_drill"),
            "count": panel["count"], "total": panel["total"],
            "row": panel["rows"][0] if panel["rows"] else None}


@drill("3 · the owner confirms it — alias saved, row clears, blocks rebuild")
def drill_confirm():
    _reset()
    import unmatched_payments as UP
    import stripe_reconcile as SR
    import close_detect
    rebuilt = {"n": 0}
    swap(close_detect, "invalidate_now", lambda reason: (
        rebuilt.__setitem__("n", rebuilt["n"] + 1)
        or {"reason": reason, "rebuilt": ["exec_top", "today", "sales_pulse"]}))
    swap(UP, "_index", lambda: (
        {"by_email": {}, "contacts": [], "by_business": {}, "surname_map": {}},
        {"active": set(), "amounts": {}}))
    charges = [{"id": "ch_drill", "date": str(today_sydney()), "amount": 3050.0,
                "customer_name": "Unknown Payer", "_email": "someone@elsewhere.com"}]
    swap(UP, "_charges", lambda days: charges)
    before = UP.scan(30)["count"]
    res = UP.confirm("Unknown Payer", "Drill Venue", actor="rydel",
                     charge_id="ch_drill")
    after = UP.latest()["count"]
    j = UP.journal()[-1] if UP.journal() else {}
    return {"ok": (res["ok"] and before == 1 and after == 0
                   and rebuilt["n"] == 1 and j.get("by") == "rydel"
                   and j.get("charge_id") == "ch_drill"),
            "before": before, "after": after,
            "journal": j, "invalidations": rebuilt["n"]}


@drill("4 · the same payer pays again later — attached on its own")
def drill_alias_reuse():
    _reset()
    import stripe_reconcile as SR
    SR.learn_alias("Unknown Payer", "Drill Venue")
    idx = {"by_email": {}, "contacts": [], "by_business": {}, "surname_map": {}}
    m = SR._match_payment("Unknown Payer", "", 3050.0, idx,
                          {"active": set(), "amounts": {}})
    import gap_reconcile as GR
    hits = GR._stripe_hits("Somebody Else", "other@venue.com", [{
        "id": "ch_next", "paid": True, "status": "succeeded", "amount": 305000,
        "created": 1758500000,
        "customer": {"name": "Unknown Payer", "email": "p@x.com"},
        "billing_details": {}}], client="Drill Venue")
    return {"ok": (m.get("business") == "Drill Venue"
                   and m.get("basis") == "confirmed alias"
                   and len(hits) == 1 and hits[0]["match"] == "confirmed alias"),
            "match": m.get("basis"),
            "counts_as_payment_evidence": bool(hits)}


@drill("5 · a surname-only resemblance is never auto-assigned")
def drill_no_fuzzy():
    _reset()
    import stripe_reconcile as SR
    idx = {"by_email": {}, "contacts": [({"glen", "fitzgerald"},
                                         "62Thirty Cafe & Bar", "fitzgerald")],
           "by_business": {}, "surname_map": {"fitzgerald": {"62Thirty Cafe & Bar"}}}
    m = SR._match_payment("Fiona Fitzgerald", "", 5500, idx,
                          {"active": set(), "amounts": {}})
    return {"ok": (m["category"] == "needs_review" and "business" not in m
                   and (m.get("suggested") or [{}])[0].get("business")
                   == "62Thirty Cafe & Bar"),
            "category": m["category"],
            "offered": (m.get("suggested") or [{}])[0].get("business"),
            "basis": (m.get("suggested") or [{}])[0].get("basis")}


@drill("6 · evidence → on screen: the invalidation is immediate")
def drill_latency():
    _reset()
    import close_detect
    import freshness
    built = []
    swap(freshness, "_block_builders", lambda: tuple(
        (n, (lambda name=n: built.append(name))) for n in
        ("exec_top", "today", "sales_pulse")))
    import resolution
    swap(resolution, "bump_derived_epoch", lambda reason: 1)
    d = str(today_sydney())
    _seed_close_sources(None, {"_from_ghl": [{
        "person": "Latency Venue", "close_date": d, "source": "ghl stage",
        "provenance": "GHL opportunity in stage 'Closed Deal'",
        "evidence": {"opp_id": "opp-lat"}, "email": None}]})
    t0 = time.time()
    res = close_detect.tick()
    ms = round((time.time() - t0) * 1000)
    again = close_detect.tick()
    return {"ok": (bool(res.get("new")) and built == ["exec_top", "today",
                                                      "sales_pulse"]
                   and not again.get("new")),
            "detect_to_rebuild_ms": ms, "blocks_rebuilt": built,
            "second_tick_refires": bool(again.get("new"))}


def main():
    for fn in (drill_stage_only, drill_unknown_payer, drill_confirm,
               drill_alias_reuse, drill_no_fuzzy, drill_latency):
        fn()
    failed = [r for r in RESULTS if not r["ok"]]
    out = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "close-pipeline-drills.json")
    with open(path, "w") as f:
        json.dump({"drills": RESULTS, "failed": len(failed)}, f, indent=1,
                  default=str)
    print(("\nDRILLS PASS — " if not failed else
           f"\nDRILLS FAIL ({len(failed)}) — ") + path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
