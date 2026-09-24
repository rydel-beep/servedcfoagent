"""exec_top.py — SERVER-RENDERED TRUTH (dashboard hardening wave).

The named failure this module ends: headline values used to be filled by
client JS after load; one early exception left the page blank while every
server test passed. From this wave on the EXECUTIVE TOP (≤ 8 tiles + one
verdict line) is computed SERVER-SIDE and baked into the HTML — JS enhances
(drawers, refresh), it never fills. If JS never runs, the tiles still read
correctly.

Doctrine carried in:
· one engine — every tile value comes from the existing engines' kv-cached
  blocks (refresh_cache() rides the 2h scheduled-refresh loop; the request
  path only READS — no Stripe/Xero/sheet call ever happens on page load).
· freshness stamps — every tile carries source · as-of · computed-at age;
  stale > threshold renders AMBER, a failed source renders DEGRADED with
  the reason. Never silent, never blank.
· undefined is a labelled state ("no closes in cohort window"), not a dash.
· label law — no bare "committed/net/cash/revenue/spend/ROAS".
"""

from __future__ import annotations

import datetime as dt
import logging

import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

# kv keys for the request-path caches (each: {"computed_at": iso, "data": …,
# "error": str|None}). Written ONLY by refresh_cache() on the scheduled loop.
K_NETS = "exec:cache:nets"
K_UNIT = "exec:cache:unit_econ"
K_ROAS = "exec:cache:roas"
K_VERDICT = "exec:cache:verdict"
K_DECISIONS = "exec:cache:decisions"
K_CARDS_EXTRA = "exec:cache:card_counts"

STALE_AMBER_HOURS = 6.0      # cache older than this renders AMBER "stale {n}h"
SNAP_AMBER_HOURS = 4.0       # snapshot (2h cadence) older than this is stale


# ── cache refresh (scheduled loop only — never the request path) ────────────

def _wrap(fn, label: str) -> dict:
    try:
        return {"computed_at": now_sydney().isoformat(), "data": fn(), "error": None}
    except Exception as e:  # noqa: BLE001 — a failed block is a labelled state
        logger.warning("exec_top cache %s failed: %s", label, e)
        return {"computed_at": now_sydney().isoformat(), "data": None, "error": str(e)[:160]}


def refresh_cache() -> dict:
    """Rebuild every request-path cache. Each block guarded — one engine
    failing degrades ITS tile, never the refresh. Called from the app's
    scheduled-refresh loop right after build_snapshot (same 2h cadence,
    no new external pull path — Stripe/sheet reads here are the same
    engines the drills already run)."""
    import tile_drawers
    import finance_analysis
    import receivables

    out = {}
    out["nets"] = _wrap(tile_drawers.three_nets, "nets")
    kv_store.put(K_NETS, out["nets"])

    out["unit_econ"] = _wrap(finance_analysis.unit_econ_view, "unit_econ")
    kv_store.put(K_UNIT, out["unit_econ"])

    def _roas():
        rep = finance_analysis.window_report("sep_mtd") or {}
        roas = rep.get("roas") or {}
        return {
            "cash_roas_cohort": roas.get("cash_roas_cohort"),
            "contract_roas": roas.get("contract_roas"),
            "closes": len(rep.get("closes") or []),
            "spend": (rep.get("spend") or {}).get("amount"),
        }
    out["roas"] = _wrap(_roas, "roas")
    kv_store.put(K_ROAS, out["roas"])

    def _verdict():
        v = finance_analysis.verdict() or {}
        return {"line": v.get("verdict"), "healthy": v.get("healthy")}
    out["verdict"] = _wrap(_verdict, "verdict")
    kv_store.put(K_VERDICT, out["verdict"])

    def _ar():
        ar = receivables.build_ar(fresh=True)   # also refreshes kv ar:state
        return {"ok": ar.get("ok"), "total": ar.get("total_outstanding")}
    out["ar"] = _wrap(_ar, "ar")
    kv_store.put("exec:cache:ar_meta",
                 {"computed_at": out["ar"]["computed_at"],
                  "error": out["ar"]["error"]})

    def _decisions():
        import decision_cards
        cards = decision_cards.build_cards() or {}
        items = cards.get("cards") or []
        def _why(c):
            for k in ("action", "missing", "known"):
                v = c.get(k)
                if isinstance(v, str) and v.strip():
                    return v[:110]
            return ""
        return {"count": len(items),
                "top": (items[0].get("title") if items else None),
                # TODAY names the top three; building the cards is an engine
                # call, so it happens HERE on the loop, never on a page load.
                "top3": [{"title": c.get("title"), "why": _why(c)}
                         for c in items[:3]]}
    out["decisions"] = _wrap(_decisions, "decisions")
    kv_store.put(K_DECISIONS, out["decisions"])

    def _extras():
        ex = {}
        try:
            import forward_projection
            proj = forward_projection.project()
            committed = proj.get("committed") or []
            ex["projection_m0"] = committed[0] if committed else None
        except Exception:
            ex["projection_m0"] = None
        return ex
    out["extras"] = _wrap(_extras, "extras")
    kv_store.put(K_CARDS_EXTRA, out["extras"])

    logger.info("exec_top caches refreshed: %s",
                {k: ("err" if v.get("error") else "ok") for k, v in out.items()})
    return out


# ── request-path build (reads only) ─────────────────────────────────────────

def _age_h(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=now_sydney().tzinfo)
        return round((now_sydney() - d).total_seconds() / 3600.0, 1)
    except Exception:
        return None


def _fmt_money(v, cents: bool = True) -> str:
    if v is None:
        return "—"
    try:
        return f"${v:,.2f}" if cents else f"${v:,.0f}"
    except Exception:
        return "—"


def _fmt_age(h: float | None) -> str:
    if h is None:
        return "age unknown"
    if h < 1:
        return f"{int(h * 60)}m ago"
    if h < 48:
        return f"{h:.1f}h ago"
    return f"{h / 24:.1f}d ago"


def _tile(tid, label, value, sub="", stamp="", state="ok", drawer=None,
          sr_note="", raw=None):
    """raw = the unformatted number, published as data-value so the
    consistency scan compares numbers rather than parsing prose."""
    return {"id": tid, "label": label, "value": value, "sub": sub,
            "stamp": stamp, "state": state, "drawer": drawer,
            "sr_note": sr_note, "raw": raw}


def _cache(key) -> tuple[dict | None, float | None, str | None]:
    """→ (data, age_hours, error). data None + error None = never computed."""
    c = kv_store.get(key) or {}
    return c.get("data"), _age_h(c.get("computed_at")), c.get("error")


def _state_for(age_h: float | None, error: str | None,
               threshold: float = STALE_AMBER_HOURS) -> str:
    if error:
        return "degraded"
    if age_h is None or age_h > threshold:
        return "amber"
    return "ok"


def build_tiles(snap: dict | None) -> list[dict]:
    """The ≤ 8 executive tiles, server-side, every path guarded. snap =
    load_persisted() (the caller owns loading it once)."""
    tiles = []
    snap = snap or {}
    snap_age = _age_h(snap.get("generated_at"))

    # 1 · Cash on hand — Xero closing balances (rides the 2h snapshot pull)
    try:
        cp = snap.get("cash_position") or {}
        bal = cp.get("cash_in_bank")
        as_of = cp.get("cash_as_of")
        src = cp.get("stripe_money_source") and cp.get("cash_in_bank_note") or ""
        degraded = "fallback" in (cp.get("cash_in_bank_note") or "").lower() \
                   or "unavailable" in (cp.get("cash_in_bank_note") or "").lower()
        n_acct = len(cp.get("cash_in_bank_breakdown") or []) or None
        state = "degraded" if degraded or bal is None else \
                ("amber" if (snap_age if snap_age is not None else 99) > SNAP_AMBER_HOURS else "ok")
        tiles.append(_tile(
            "cash_on_hand", "Cash on hand (Xero bank balances)",
            _fmt_money(bal),
            (f"{n_acct} accounts · " if n_acct else "") +
            "Xero bank feeds can lag the bank by up to a day",
            f"Xero closing balances · as of {as_of or 'unknown'} · pulled {_fmt_age(snap_age)}",
            state, drawer="cash_on_hand", raw=bal,
            sr_note="LAST-KNOWN fallback — live Xero read failed" if degraded else ""))
    except Exception as e:  # noqa: BLE001
        tiles.append(_tile("cash_on_hand", "Cash on hand (Xero bank balances)",
                           "—", str(e)[:80], "", "degraded"))

    # 2 · Committed MRR (revenue)
    try:
        ch = snap.get("client_health") or {}
        mrr = ch.get("current_mrr")
        n = ch.get("active_count") or len(ch.get("clients") or []) or None
        tiles.append(_tile(
            "committed_mrr", "Committed MRR (revenue)",
            _fmt_money(mrr),
            f"{n} active clients · contracted monthly revenue — never a cost" if n else
            "contracted monthly revenue — never a cost",
            f"Finance-sheet Health tab + declarations + renewal ledger · pulled {_fmt_age(snap_age)}",
            "degraded" if mrr is None else
            ("amber" if (snap_age if snap_age is not None else 99) > SNAP_AMBER_HOURS else "ok"),
            drawer="committed_mrr", raw=mrr))
    except Exception as e:  # noqa: BLE001
        tiles.append(_tile("committed_mrr", "Committed MRR (revenue)", "—",
                           str(e)[:80], "", "degraded"))

    # 3 · AR outstanding (internal visibility only — the system never chases)
    try:
        ar = kv_store.get("ar:state") or {}
        tot = ar.get("total_outstanding")
        n_owing = len([r for r in (ar.get("rows") or [])
                       if (r.get("outstanding") or 0) > 0.01]) or None
        ar_meta = kv_store.get("exec:cache:ar_meta") or {}
        ar_age = _age_h(ar_meta.get("computed_at"))
        tiles.append(_tile(
            "ar_outstanding", "AR outstanding (internal)",
            _fmt_money(tot),
            (f"{n_owing} clients owing · " if n_owing else "") +
            "pending is never cash · internal visibility only",
            f"expected (RECOGNIZED grid + renewal ledger) − received (Stripe) · built {_fmt_age(ar_age)}",
            "degraded" if tot is None else _state_for(ar_age, None),
            drawer="ar_outstanding", raw=tot))
    except Exception as e:  # noqa: BLE001
        tiles.append(_tile("ar_outstanding", "AR outstanding (internal)", "—",
                           str(e)[:80], "", "degraded"))

    # 4+5 · The two actual nets (three-nets engine; tax banded BESIDE)
    nets, nets_age, nets_err = _cache(K_NETS)
    for key, tid, label in (("cash_net_mtd_bank", "cash_net_mtd",
                             "Cash net MTD (bank basis)"),
                            ("operating_net_mtd", "operating_net_mtd",
                             "Operating net MTD")):
        try:
            block = (nets or {}).get(key) or {}
            v = block.get("value")
            if tid == "operating_net_mtd":
                tax = next((c.get("value") for c in (block.get("components") or [])
                            if "tax/statutory" in str(c.get("label", ""))), None)
                sub = (f"tax banded beside: {_fmt_money(tax)} — never inside"
                       if tax is not None else
                       "tax/statutory banded beside, never inside")
            else:
                sub = block.get("clock") or "MTD · bank-balance delta"
            tiles.append(_tile(
                tid, label, _fmt_money(v), sub,
                f"three-nets engine (Stripe receipts − banded outflows) · computed {_fmt_age(nets_age)}",
                "degraded" if (nets_err or v is None) else _state_for(nets_age, nets_err),
                drawer="three_nets", raw=v,
                sr_note=(nets_err or ("not yet computed — first refresh pending"
                                      if nets is None else ""))))
        except Exception as e:  # noqa: BLE001
            tiles.append(_tile(tid, label, "—", str(e)[:80], "", "degraded"))

    # 6+7 · LTV:CAC · LTGP:CAC — the honest engine, cohort window
    unit, unit_age, unit_err = _cache(K_UNIT)
    try:
        coh = ((unit or {}).get("windows") or {}).get("cohort_month") or {}
        margin_prov = (unit or {}).get("margin_provenance") or "labelled"
        for tid, label, vk in (("ltv_cac", "LTV : CAC", "ltv_to_cac"),
                               ("ltgp_cac", "LTGP : CAC", "ltgp_to_cac")):
            v = coh.get(vk)
            if v is not None:
                val = f"{v:.2f}×"
                if tid == "ltgp_cac":
                    sub = f"margin: {margin_prov} · 3:1 = benchmark, not target"
                else:
                    sub = (f"Sep cohort · {coh.get('closes', '?')} closes · "
                           f"CAC loaded {_fmt_money(coh.get('cac_fully_loaded'), cents=False)}"
                           f" · spend-only {_fmt_money(coh.get('cac_spend_only'), cents=False)}")
                state = _state_for(unit_age, unit_err)
            else:
                val = "—"
                sub = unit_err or (
                    "no closes in cohort window — ratio undefined "
                    "(labelled, not blank)" if unit is not None else
                    "not yet computed — first refresh pending")
                state = "degraded" if (unit_err or unit is None) else "ok"
            tiles.append(_tile(
                tid, label, val, sub,
                f"honest unit-econ engine · cohort clock · computed {_fmt_age(unit_age)}",
                state, drawer=tid, raw=v,
                sr_note=(unit_err or "")))
    except Exception as e:  # noqa: BLE001
        for tid, label in (("ltv_cac", "LTV : CAC"), ("ltgp_cac", "LTGP : CAC")):
            tiles.append(_tile(tid, label, "—", str(e)[:80], "", "degraded"))

    # 8 · Cohort cash ROAS (September MTD, cohort clock — never blended)
    roas, roas_age, roas_err = _cache(K_ROAS)
    try:
        v = (roas or {}).get("cash_roas_cohort")
        val = f"{v:.2f}×" if v is not None else "—"
        sub = ("cohort clock — cash from this window's closes ÷ this window's ad spend"
               if v is not None else
               (roas_err or "not yet computed — first refresh pending"))
        tiles.append(_tile(
            "cohort_cash_roas", "Cohort cash ROAS (Sep MTD)",
            val, sub,
            f"finance-analysis engine · computed {_fmt_age(roas_age)}",
            "degraded" if (roas_err or v is None and roas is None) else _state_for(roas_age, roas_err),
            drawer=None, raw=v, sr_note=roas_err or ""))
    except Exception as e:  # noqa: BLE001
        tiles.append(_tile("cohort_cash_roas", "Cohort cash ROAS (Sep MTD)",
                           "—", str(e)[:80], "", "degraded"))

    return tiles[:8]


def build_verdict() -> dict:
    v, age, err = _cache(K_VERDICT)
    line = (v or {}).get("line")
    if not line:
        line = err or "verdict not yet computed — first refresh pending (labelled, not blank)"
    return {"line": line, "age_h": age, "state": _state_for(age, err, 26.0)}


# ── summary cards (landing = tiles + verdict + cards, nothing else) ─────────
# Card list == page list == panel inventory. Owner-only cards are filtered by
# the caller (routes) via is_owner — fail-closed there, not here.

def build_cards(snap: dict | None, owner: bool,
                csm_visible: bool | None = None) -> list[dict]:
    """csm_visible: the CSM card additionally honors DISCREET MODE (#146) —
    owner AND discreet-off. Defaults to `owner` for callers without a
    session (tests, self-check); routes passes the session-aware value."""
    if csm_visible is None:
        csm_visible = owner
    csm_visible = bool(csm_visible) and owner   # never wider than owner
    snap = snap or {}
    cards = []

    def card(cid, title, href, signal, owner_only=False):
        cards.append({"id": cid, "title": title, "href": href,
                      "signal": signal, "owner_only": owner_only})

    dec, _, dec_err = _cache(K_DECISIONS)
    extras, _, _ = _cache(K_CARDS_EXTRA)
    ar = kv_store.get("ar:state") or {}
    ch = snap.get("client_health") or {}
    cp = snap.get("cash_position") or {}
    q = snap.get("degraded") or []

    roas, _, _ = _cache(K_ROAS)
    unit, _, _ = _cache(K_UNIT)
    coh = ((unit or {}).get("windows") or {}).get("cohort_month") or {}

    card("sales", "Ads & sales", "/dashboard/view/sales",
         (f"{(roas or {}).get('closes', '—')} closes Sep MTD · Meta spend "
          f"{_fmt_money((roas or {}).get('spend'), cents=False)}"))
    card("receivables", "Receivables", "/dashboard/view/receivables",
         (f"{_fmt_money(ar.get('total_outstanding'))} outstanding"
          + (f" · {ar.get('clients_owing')} owing" if ar.get("clients_owing") else ""))
         if ar else "not yet built")
    card("renewals", "Renewals & churn", "/dashboard/view/renewals",
         f"{ch.get('active_count') or len(ch.get('clients') or []) or '—'} active clients · declarations + sheet ledger")
    card("projection", "Forward projection", "/dashboard/view/projection",
         (f"month-0 committed {_fmt_money((extras or {}).get('projection_m0'), cents=False)}"
          if (extras or {}).get("projection_m0") is not None else "committed vs assumed — two layers"))
    card("outflows", "Outflows & BAS", "/dashboard/view/outflows",
         "OpEx vs tax/statutory — banded, never blended")
    card("unit_econ", "Unit economics (detail)", "/dashboard/view/unit-econ",
         (f"LTV:CAC {coh.get('ltv_to_cac'):.2f}× · LTGP:CAC {coh.get('ltgp_to_cac'):.2f}× (Sep cohort)"
          if coh.get("ltv_to_cac") is not None and coh.get("ltgp_to_cac") is not None
          else "three clocks, labelled — never blended"))
    card("cash", "Cash & capital", "/dashboard/view/cash",
         (f"runway {cp.get('runway_months')} months on recurring burn"
          if cp.get("runway_months") else "cash position · capital allocation"))
    card("team", "Team & strategy", "/dashboard/view/team",
         "team cost · hiring power · growth constraints")
    card("brief", "Morning brief (full)", "/dashboard/view/brief",
         "the long-form read · exec summary · verdicts")
    if owner:
        base_run = (kv_store.get("compass:base_run") or {}).get("run") or {}
        m = (base_run.get("months") or [{}])[0]
        bind = (m.get("binding_constraint") or {}).get("name")
        card("scale", "Scaling compass", "/dashboard/scale",
             (f"next month's binding constraint: {bind}" if bind
              else "forward + backward planning on measured rates"),
             owner_only=True)
        card("decisions", "Needs your ruling", "/dashboard/view/decisions",
             (f"{(dec or {}).get('count', '—')} need your ruling"
              if dec else (dec_err or "not yet built")), owner_only=True)
    if csm_visible:   # owner AND discreet-off (#146) — fail-closed server-side
        card("csm", "CSM", "/dashboard/csm", "owner-only cockpit", owner_only=True)
    card("worklog", "Work log", "/dashboard/worklog",
         "the collaboration log")
    card("bookkeeping", "Bookkeeping queue", "/dashboard/bookkeeping",
         "flag → resolve → verify")
    card("system", "System health", "/dashboard/view/system",
         f"{len(q)} degraded sources · render telemetry · freshness")
    return cards


def build_pulse() -> list[dict]:
    """SALES PULSE (compass wave — the ≤8 rule amendment: 8 executive + 3
    pulse): show rate · close rate (t30) · booked calls next 7 days. Server-
    rendered from the compass kv cache; small-n honesty on the face."""
    p = kv_store.get("compass:pulse") or {}
    age = _age_h(p.get("computed_at"))
    out = []

    def rate_tile(tid, label, block, denom_word):
        block = block or {}
        v, n = block.get("value"), block.get("n")
        if v is not None:
            val = f"{v * 100:.0f}%"
            # THE CONFIRMED BASIS, WITH ITS RANGE. A status-only show rate may
            # never be the headline, and the unmarked consults behind it are
            # said out loud rather than rounded away (Phase 0, SEV1).
            if block.get("range_note"):
                sub = block["range_note"] + " · trailing 30d"
            else:
                sub = f"n={n} {denom_word} · trailing 30d"
            if (n or 0) < 15:
                sub += " · SMALL n — read with care"
            state = _state_for(age, None)
        else:
            val, sub, state = "—", (p.get("error") or
                                    "not yet computed — first refresh pending"), "degraded"
        out.append({"id": tid, "label": label, "value": val, "sub": sub,
                    "stamp": f"one attribution engine · computed {_fmt_age(age)}",
                    "state": state, "drawer": None, "raw": v})

    rate_tile("pulse_show_rate", "Show rate (confirmed)",
              p.get("show_rate"), "consults due")
    rate_tile("pulse_close_rate", "Close rate (÷ confirmed shows)",
              p.get("close_rate"), "confirmed shows")
    bc = p.get("booked_calls_7d") or {}
    n = bc.get("count")
    # the tile SAYS its window in words (#162) — "next 7 days" is a claim
    # about dates, so the dates are on it, and cancelled sits beside the
    # count, never inside it.
    window = bc.get("window_words") or "next 7 days"
    cx = bc.get("cancelled_count")
    out.append({"id": "pulse_booked_calls",
                "label": f"Booked consults · {window}",
                "value": str(n) if n is not None else "—",
                "sub": ((f"every CRM calendar, read directly"
                         + (f" · {cx} cancelled shown separately" if cx else ""))
                        if n is not None else
                        str(bc.get("error") or "calendar sync pending")),
                "stamp": f"CRM calendars · computed {_fmt_age(age)}",
                "state": "degraded" if n is None else _state_for(age, None),
                "drawer": "booked_calls", "raw": n,
                "consults": (bc.get("consults") or [])[:12]})
    return out


def build(snap: dict | None, owner: bool,
          csm_visible: bool | None = None) -> dict:
    """Everything the landing template needs, computed server-side."""
    return {
        "tiles": build_tiles(snap),
        "pulse": build_pulse(),
        "verdict": build_verdict(),
        "cards": build_cards(snap, owner, csm_visible=csm_visible),
        "generated_at": (snap or {}).get("generated_at"),
        "snapshot_age": _fmt_age(_age_h((snap or {}).get("generated_at"))),
        "today": str(today_sydney()),
    }
