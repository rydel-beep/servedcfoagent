"""
stripe_health.py
----------------
STRIPE HEALTH (outflow-truth wave, Part B): the CANARY + direct-key overlays.

DIAGNOSIS (B0, evidenced in dashboard/GROUND_TRUTH probes + stripe_pull's own
2026-06-11 note): the DIRECT restricted-key path (per-charge endpoints —
cash_truth, reconciliation) is healthy; the STRIPE-MCP SERVICE's aggregates
are the broken layer — it ignores the `days` parameter, returns 'unknown'
customer counts, and miscounts subscriptions (1 active sub against a $59k
MRR → the standing stripe_mrr_subs_mismatch flag). The MCP service is a
separate Railway deploy outside this repo — its aggregates are REPLACED here
by direct reads wherever the restricted key's scopes allow, with the MCP kept
only as the labelled fallback. NO token minting: a missing/denied scope is
reported as the exact Rydel env/scope step, never worked around.

THE CANARY (the TTS-canary shape): a lightweight authenticated probe —
classified failure reasons (no_key / auth / scope / rate_limit /
service_down / contract) — run at snapshot build (on-load freshness) + the
sentinel nightly; LOUD on failure via the feed channel; state in kv
`stripe:canary` with the last-probe time. F5 stands: a genuine failure still
badges DEGRADED — nothing here softens loudness.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_KV_CANARY = "stripe:canary"
_KV_FEED = "feed:extra:stripe"


def _classify_status(status: int, body: str) -> str:
    if status == 401:
        return "auth"
    if status == 403:
        return "scope"
    if status == 429:
        return "rate_limit"
    if status in (500, 502, 503, 504):
        return "service_down"
    return "contract"


def _sget(path: str, params: dict | None = None) -> tuple[int | None, dict | None, str | None]:
    """One authenticated GET against the Stripe API (read-only). Returns
    (status, json, error). Never logs key material."""
    import requests
    from config import STRIPE_SECRET_KEY, HTTP_TIMEOUT
    if not STRIPE_SECRET_KEY:
        return None, None, "no key configured"
    try:
        r = requests.get(f"https://api.stripe.com{path}", params=params or {},
                         auth=(STRIPE_SECRET_KEY, ""), timeout=(5, HTTP_TIMEOUT))
        try:
            j = r.json()
        except ValueError:
            j = None
        return r.status_code, j, None
    except requests.RequestException as e:
        return None, None, str(e)[:140]


def canary_probe(source: str = "on_load") -> dict:
    """The lightweight authenticated probe: GET /v1/charges?limit=1.
    Classified; stored; LOUD on failure. Runs in seconds, 1 API call."""
    from helpers import now_sydney
    t0 = time.time()
    status, j, err = _sget("/v1/charges", {"limit": 1})
    out = {"at": now_sydney().strftime("%Y-%m-%d %H:%M"), "source": source,
           "runtime_ms": int((time.time() - t0) * 1000)}
    if err == "no key configured":
        out.update({"ok": False, "cls": "no_key",
                    "fix": "set STRIPE_SECRET_KEY (or STRIPE_RESTRICTED_KEY) "
                           "on Railway CFOagent — a read-only rk_ key"})
    elif err:
        out.update({"ok": False, "cls": "service_down", "detail": err,
                    "fix": "network/Stripe outage — retries next probe"})
    elif status == 200:
        out.update({"ok": True, "cls": "ok"})
    else:
        cls = _classify_status(status, "")
        msg = ((j or {}).get("error") or {}).get("message", "")[:120]
        fix = {"auth": "the key is invalid/rotated — re-set STRIPE_SECRET_KEY "
                       "on Railway CFOagent (Rydel env step; never minted here)",
               "scope": "the restricted key lacks the Charges read scope — "
                        "re-scope it in Stripe → API keys (Rydel step)",
               "rate_limit": "backing off — retries next probe",
               "contract": "Stripe API shape changed — code fix needed",
               "service_down": "Stripe 5xx — retries next probe"}[cls]
        out.update({"ok": False, "cls": cls, "status": status,
                    "detail": msg, "fix": fix})
    _store(out)
    return out


def _store(out: dict) -> None:
    try:
        import kv_store
        kv_store.put(_KV_CANARY, out)
        items = []
        if not out.get("ok"):
            items.append({
                "severity": "S1", "category": "stripe_health",
                "id": "stripe-canary",
                "title": f"STRIPE canary FAILED ({out.get('cls')}) — "
                         f"{out.get('detail') or 'probe failed'}"[:150],
                "action": out.get("fix") or "investigate the Stripe integration",
            })
        kv_store.put(_KV_FEED, items)     # self-retiring: OK probe clears it
    except Exception as e:
        logger.info("stripe canary store failed: %s", e)


def canary_state() -> dict:
    try:
        import kv_store
        return kv_store.get(_KV_CANARY) or {"ok": None, "cls": "never_run"}
    except Exception:
        return {"ok": None, "cls": "unavailable"}


# ── DIRECT overlays for the MCP's broken aggregates ─────────────────────────

def subscriptions_direct() -> dict | None:
    """Subscription counts from the DIRECT API (the MCP miscounts: 1 active
    vs $59k MRR). Three status reads, ≤3 calls. None = scope denied/no key —
    the caller keeps the MCP value with its honest degraded note."""
    out = {}
    for status_q, key in (("active", "active"), ("past_due", "past_due"),
                          ("canceled", "cancelled")):
        st, j, err = _sget("/v1/subscriptions",
                           {"status": status_q, "limit": 100})
        if st != 200 or j is None:
            logger.info("direct subs read %s → %s %s", status_q, st, err)
            return None
        n = len(j.get("data") or [])
        if j.get("has_more"):
            n = f"{n}+"          # honest: >100 — never a fabricated exact
        out[key] = n
    out["trialing"] = None
    out["source"] = "stripe_direct (restricted key, read-only)"
    return out


def failed_charges_direct(days: int = 30) -> int | None:
    """Failed-charge count for the trailing window from the DIRECT per-charge
    endpoint (the same one reconciliation trusts). None = unavailable."""
    import calendar
    import datetime as dt
    from helpers import today_sydney
    since = today_sydney() - dt.timedelta(days=days)
    created_gte = calendar.timegm(since.timetuple())
    count, after = 0, None
    for _ in range(10):
        params = {"limit": 100, "created[gte]": created_gte}
        if after:
            params["starting_after"] = after
        st, j, err = _sget("/v1/charges", params)
        if st != 200 or j is None:
            return None
        data = j.get("data") or []
        count += sum(1 for c in data if c.get("status") == "failed")
        if not j.get("has_more") or not data:
            return count
        after = data[-1]["id"]
    return count


def overlay(stripe_block: dict, degraded: list) -> None:
    """Overlay direct-key figures onto the MCP aggregates IN PLACE, labelled.
    The MCP's mismatch flag then re-evaluates against the DIRECT sub count —
    a real mismatch still flags; the miscount artifact clears."""
    subs = subscriptions_direct()
    if subs is not None:
        stripe_block["subscriptions_mcp"] = stripe_block.get("subscriptions")
        stripe_block["subscriptions"] = {k: subs.get(k) for k in
                                         ("active", "cancelled", "past_due",
                                          "trialing")}
        stripe_block["subscriptions_source"] = subs["source"]
        # retire the MCP-miscount mismatch flag if the direct count explains it
        mrr = stripe_block.get("mrr")
        active = subs.get("active")
        if isinstance(active, str):          # "100+" — enough subs, no mismatch
            active_n = 100
        else:
            active_n = active
        keep = []
        for d in degraded:
            if d.get("metric") == "stripe_mrr_subs_mismatch":
                if mrr and active_n and mrr / max(active_n, 1) <= 10000:
                    continue                 # artifact of the MCP miscount — gone
                d["reason"] = (f"MRR ${mrr:,.0f} vs {active_n} active subs "
                               f"(DIRECT count) — a real mismatch, verify in "
                               f"Stripe") if mrr and active_n is not None else d["reason"]
            keep.append(d)
        degraded[:] = keep
    failed = failed_charges_direct()
    if failed is not None:
        stripe_block["failed_charges_mcp"] = stripe_block.get("failed_charges_count")
        stripe_block["failed_charges_count"] = failed
        stripe_block["failed_charges_source"] = "stripe_direct (per-charge endpoint)"
        degraded[:] = [d for d in degraded if d.get("metric") != "failed_charges"]


# ── sentinel (nightly canary + MCP layer watch) ─────────────────────────────

def sentinel_watch() -> dict:
    """Nightly: run the canary (1 call) + record the MCP layer's known
    degradations so drift is visible."""
    out = {"canary": canary_probe(source="sentinel_nightly")}
    try:
        from stripe_pull import _call_tool
        r = _call_tool("get_stripe_revenue", {"days": 60})
        out["mcp_days_honored"] = bool(r and r.get("period_days") == 60)
        if r is None:
            out["mcp"] = "unreachable"
            _feed("Stripe MCP service unreachable (aggregates degrade to "
                  "direct-key overlays where scoped)", loud=False)
        elif not out["mcp_days_honored"]:
            out["mcp"] = (f"days param still ignored (asked 60, got "
                          f"period_days={r.get('period_days')})")
    except Exception as e:
        out["mcp"] = f"probe error: {str(e)[:80]}"
    if not out["canary"].get("ok"):
        _feed(f"STRIPE canary FAILED ({out['canary'].get('cls')}): "
              f"{out['canary'].get('fix')}", loud=True)
    return out


def _feed(msg: str, loud: bool = False) -> None:
    try:
        import ad_sentinel
        ad_sentinel._feed(msg, loud=loud)
    except Exception:
        pass
