"""
scripts/diagnose_stripe.py — Part B B0/B1 probe (read-only, no writes).
Run in the container: python3 -m scripts.diagnose_stripe

Captures: the MCP layer's ACTUAL responses (the failing aggregates, verbatim)
· the direct-key ladder (canary classified) · the direct overlays · the cash
reconciliation re-proof · a 10-charge matcher sample.
"""
import json
import time


def main():
    out = {}
    # ── B0 rung 1: the credential (direct key) ───────────────────────────────
    import stripe_health as SH
    out["canary"] = SH.canary_probe(source="diagnose")

    # ── B0 rung 2: the Stripe-MCP service — actual bodies ────────────────────
    from stripe_pull import _call_tool
    mcp = {}
    for name, tool, args in (
            ("subs", "get_stripe_subscriptions", {}),
            ("revenue_days60", "get_stripe_revenue", {"days": 60}),
            ("failed", "get_stripe_failed_charges", {"days": 30}),
            ("customers", "get_stripe_customer_count", {"days": 30}),
            ("mrr", "get_stripe_mrr", {})):
        t0 = time.time()
        r = _call_tool(tool, args)
        mcp[name] = {"ms": int((time.time() - t0) * 1000), "body": r}
    out["mcp"] = mcp

    # ── B1 overlays: direct replacements ─────────────────────────────────────
    out["direct_subscriptions"] = SH.subscriptions_direct()
    out["direct_failed_30d"] = SH.failed_charges_direct(30)

    # ── the reconciliation re-proof (the standard: N charges, 0 missing) ─────
    try:
        import stripe_reconcile
        rep = stripe_reconcile.reconcile_stripe_tracker()
        if not rep or rep.get("status") not in ("ok", "issues"):
            from snapshot import load_persisted
            rep = (load_persisted() or {}).get("stripe_reconciliation") or rep
        out["reconciliation"] = {k: rep.get(k) for k in
                                 ("status", "checked_charges", "lookback_days",
                                  "paid_missing_from_tracker")} if rep else None
        matches = (rep or {}).get("recognised_repeat_payments") or []
        out["matcher_sample_10"] = [
            {"customer": m.get("customer"), "matched_to": m.get("matched_to"),
             "basis": m.get("basis"), "kind": m.get("kind")}
            for m in matches[:10]]
    except Exception as e:
        out["reconciliation"] = {"error": str(e)[:120]}

    # close-date derivation evidence intact (a Stripe-derived date resolves)
    try:
        import resolution
        dd = resolution.derived_dates() or {}
        stripe_derived = [(k, v["close_date"]["provenance"]) for k, v in dd.items()
                          if "close_date" in v
                          and "stripe" in str(v["close_date"].get("provenance", "")).lower()]
        out["stripe_derived_close_dates"] = stripe_derived[:5]
    except Exception as e:
        out["stripe_derived_close_dates"] = {"error": str(e)[:80]}

    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
