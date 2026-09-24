"""close_register.py — ONE CLOSE POPULATION. EVERY SURFACE READS IT.

Rydel opened /ads on 24 Sep and it said 1 closed deal in the last 30 days.
There were four. Not one bug — one PATTERN: every surface built its own
close list from whichever source it happened to read. The ads engine read
the tracker (empty since 24 Jul, so Harman and William could never appear
there at any window on any clock); SALES filtered tracker rows inline (1);
EDITH's voice path had a third private tracker reader (1); travelling, the
tiles and compass read the engine∪gap-ledger union (4, correct, by luck of
having been unified earlier). Three surfaces said "1" for three DIFFERENT
reasons.

This module ends the pattern. It is the register:

  · DETECTION is evidence-first (#161's four sources, all-time): whichever
    source moves first creates the record; the others are listed as
    corroboration-pending. A close with no evidence cannot exist here.
  · ENRICHMENT attaches what each store already knows, with provenance:
    contract value on the gap ledger's evidence ladder (chipped signed vs
    derived), cash from MATCHED STRIPE CHARGES ONLY (R-CASH — the tracker's
    cash cell rides beside as corroboration, never as the figure), the
    closer and setter from the tracker row, the GHL owner as evidence, and
    ad attribution from the attribution engine with the WHY in words.
  · CLOCK PLACEMENTS are explicit per record: activity = the close date;
    cohort = the lead's arrival date, or null with the reason in words.
  · STATUS is earned: `confirmed` needs the tracker (the standing
    authority) or two independent sources; anything on one non-authority
    source is `proposed-needs-evidence` and is COUNTED SEPARATELY.

Surfaces call closes()/totals() — nothing else. finance_analysis'
_closes_union delegates here; the SALES board, /ads' close population,
EDITH's close answers and the ledger page all read this one store. A test
(tests/test_one_close_population.py) fails the build if a parallel close
list reappears.

READ-ONLY LAW (#148): this module never writes the tracker, GHL or Xero.
Its stores are kv. Corrections are journaled, never silent.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_REGISTER = "register:closes"          # the standing canonical population
K_JOURNAL = "register:journal"          # corrections + owner declarations
K_RECON = "register:reconciliation"     # the nightly reconciliation's findings
K_LAST_BUILD = "register:last_build"

ALL_TIME_DAYS = 3650

# who gets to say WHEN it closed (close_detect's ranking, kept identical)
_DATE_RANK = {"tracker": 0, "ghl stage": 1, "stage recorder": 2, "payment": 3}
_AUTHORITY = "tracker"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


# ── detection: the four sources, all-time ───────────────────────────────────

def _detect(days: int) -> dict[str, dict]:
    """close_detect's four sources merged by person — the SAME source readers
    (one implementation), without the 60-day cap the fast tick uses."""
    import close_detect as CD
    cutoff = str(today_sydney() - dt.timedelta(days=days))
    found: dict[str, dict] = {}
    for fn, label in ((CD._from_tracker, "tracker"), (CD._from_ghl, "ghl stage"),
                      (CD._from_stage_recorder, "stage recorder"),
                      (CD._from_payments, "payment")):
        try:
            rows = fn() or []
        except Exception as e:  # noqa: BLE001
            logger.warning("register source %s failed: %s", label, e)
            rows = []
        for row in rows:
            if not row.get("close_date") or row["close_date"] < cutoff:
                continue
            key = _norm(row.get("person")) or _norm(
                (row.get("evidence") or {}).get("contact_id"))
            if not key:
                continue
            e = found.setdefault(key, {
                "person": row.get("person") or "", "close_date": row["close_date"],
                "dated_by": row["source"], "sources": [], "evidence": {},
                "email": row.get("email"), "client": row.get("client"),
                "owner_id": row.get("owner_id")})
            if row.get("person") and not e["person"]:
                e["person"] = row["person"]
            e["email"] = e["email"] or row.get("email")
            e["client"] = e["client"] or row.get("client")
            e["owner_id"] = e["owner_id"] or row.get("owner_id")
            e["sources"].append({"source": row["source"],
                                 "provenance": row["provenance"],
                                 "close_date": row["close_date"]})
            for k, v in (row.get("evidence") or {}).items():
                if k == "charge_ids":
                    e["evidence"].setdefault("charge_ids", [])
                    for cid in v or []:
                        if cid and cid not in e["evidence"]["charge_ids"]:
                            e["evidence"]["charge_ids"].append(cid)
                elif v not in (None, ""):
                    e["evidence"].setdefault(k, v)
            if _DATE_RANK[row["source"]] < _DATE_RANK[e["dated_by"]]:
                e["close_date"] = row["close_date"]
                e["dated_by"] = row["source"]
            elif (row["source"] == e["dated_by"]
                  and row["close_date"] < e["close_date"]):
                e["close_date"] = row["close_date"]
    return found


# ── enrichment inputs (each one an existing store — no new API traffic) ─────

def _tracker_leads() -> dict[str, dict]:
    """name_norm → the engine-parsed tracker lead row (clean view, deduped)."""
    try:
        import attribution_engine as AE
        rows = AE._tracker_rows_clean()
        leads, _ = AE.parse_tracker(rows)
        leads, _flags = AE.dedupe_won(leads)
        return {l["name_norm"]: l for l in leads}
    except Exception as e:  # noqa: BLE001
        logger.warning("register: tracker leads unavailable: %s", e)
        return {}


def _gap_ledger() -> dict[str, dict]:
    try:
        import gap_reconcile
        return {_norm(e.get("person")): e
                for e in (gap_reconcile.close_ledger().get("ledger") or [])}
    except Exception as e:  # noqa: BLE001
        logger.info("register: gap ledger unavailable: %s", e)
        return {}


def _matched_charges() -> dict[str, list[dict]]:
    """client_norm → matched charges, from the standing unmatched-payments
    scan (the ONE matcher). Never re-derives; never invents."""
    out: dict[str, list[dict]] = {}
    try:
        import unmatched_payments as UP
        for m in (UP.latest().get("matched") or []):
            out.setdefault(_norm(m.get("client")), []).append(m)
    except Exception as e:  # noqa: BLE001
        logger.info("register: matched-charge store unavailable: %s", e)
    return out


def _attribution_index() -> tuple[dict[str, dict], str | None]:
    """name_norm → {tier, creative_key, label, input_date} from the engine's
    all-time activity view. The engine stays the authority on WHICH ad a
    LEAD came from; the register is the authority on WHAT CLOSED."""
    idx: dict[str, dict] = {}
    try:
        import attribution_engine as AE
        res = AE.compute(days=ALL_TIME_DAYS, basis="activity")
        for c in res.get("creatives") or []:
            for d in c.get("deals") or []:
                idx[_norm(d.get("name"))] = {
                    "tier": c.get("tier"), "creative_key": c.get("creative_key"),
                    "label": c.get("label"), "input_date": d.get("input_date")}
        return idx, None
    except Exception as e:  # noqa: BLE001
        logger.warning("register: attribution index unavailable: %s", e)
        return idx, str(e)[:160]


FORM_NOTE = ("Kalin's closed-deal form is not in the mirrored custom fields "
             "(#161) — the form chip reads ✗ until the mirror carries it; "
             "absent ≠ zero")


def _form_entries() -> dict[str, dict]:
    """contact_id → closed-deal-form values. The mirror only carries the
    three qualification form fields today (attr_contacts), NOT the
    closed-deal form — proved in #161. This reads a future
    `ghl_mirror.read_contact_form_fields` if one ever exists, and returns
    {} honestly until then rather than inventing a chip."""
    try:
        import ghl_mirror
        fn = getattr(ghl_mirror, "read_contact_form_fields", None)
        if fn:
            return fn("closed") or {}
    except Exception as e:  # noqa: BLE001
        logger.info("register: closed-deal form read failed: %s", e)
    return {}


# ── the WHY, in words ───────────────────────────────────────────────────────

def _attribution_why(rec: dict, att: dict | None, lead: dict | None) -> tuple[str, str]:
    """(tier, why). Never a bare tier — the reason renders on the row."""
    if att:
        t = att.get("tier")
        if t == "ad":
            return "ad", f"id-exact to {att.get('label')}"
        if t == "ambiguous":
            return "ambiguous", "two or more creatives match the ad stamp — quarantined, never assigned to one"
        if t == "ig_dm":
            return "ig_dm", "came through the IG DM channel — a channel, not a creative"
        return "unattributed", "lead is on the tracker but carries no ad stamp"
    if lead is not None:
        return "unattributed", "lead is on the tracker but carries no ad stamp"
    return "unattributed", ("no tracker lead row exists for this person — there is "
                            "no ad stamp to read (lead predates capture or was "
                            "never logged)")


# ── the build ───────────────────────────────────────────────────────────────

def build(days: int = ALL_TIME_DAYS) -> dict:
    """Rebuild the canonical register from evidence. Deterministic from its
    input stores; persisted; journaled corrections and owner declarations
    are re-applied on top (they carry evidence, so they survive rebuilds)."""
    detected = _detect(days)
    leads = _tracker_leads()
    ledger = _gap_ledger()
    charges_by_client = _matched_charges()
    att_idx, att_err = _attribution_index()
    forms = _form_entries()

    entries = []
    for key, det in detected.items():
        lead = leads.get(key)
        le = ledger.get(key)
        ev = dict(det.get("evidence") or {})
        sources = {s["source"] for s in det["sources"]}

        # the gap ledger's payment corroboration counts as payment evidence —
        # Orlando sat DETECTED in the fast ledger while his charges were on
        # file in the gap ledger the whole time
        if le:
            for cid in ((le.get("evidence") or {}).get("charge_ids") or []):
                ev.setdefault("charge_ids", [])
                if cid not in ev["charge_ids"]:
                    ev["charge_ids"].append(cid)
            ev.setdefault("opp_id", (le.get("evidence") or {}).get("opp_id"))
            ev.setdefault("contact_id", (le.get("evidence") or {}).get("contact_id"))

        # client/venue: tracker business cell > gap-ledger health row > payment client
        client = ((lead or {}).get("business")
                  or ((le or {}).get("health_row") or {}).get("name")
                  or det.get("client") or "")

        # CASH — matched Stripe charges only (R-CASH). The tracker cell is
        # corroboration beside the figure, never the figure. A matched charge
        # IS payment evidence: it joins evidence.charge_ids, so the Stripe
        # chip and the "missing" line agree with the cash beside them (found
        # live: Koji read "missing: a matched payment" with $1,650 attached).
        seen_charge = set(ev.get("charge_ids") or [])
        matched = list(charges_by_client.get(_norm(client)) or [])
        for m in matched:
            if m.get("charge_id") and m["charge_id"] not in seen_charge:
                seen_charge.add(m["charge_id"])
                ev.setdefault("charge_ids", [])
                ev["charge_ids"].append(m["charge_id"])
        cash_amount = None
        if matched:
            cash_amount = round(sum(float(m.get("amount") or 0) for m in matched), 2)
        elif le and (le.get("stripe") or {}).get("cash_to_date"):
            cash_amount = le["stripe"]["cash_to_date"]
        cash = {"amount": cash_amount,
                "charge_ids": sorted(seen_charge),
                "source": ("matched Stripe charges" if cash_amount is not None
                           else "no matched Stripe/Xero payment on file"),
                "tracker_cell": (lead or {}).get("cash")}

        # CONTRACT — the evidence ladder, chipped signed vs derived
        contract_val, contract_src, signed = None, None, False
        form = forms.get(ev.get("contact_id"))
        if lead and lead.get("contract") is not None:
            contract_val, contract_src, signed = lead["contract"], "tracker contract cell", True
        elif form:
            fv = next((_money_like(v) for v in form.values() if _money_like(v)), None)
            if fv:
                contract_val, contract_src, signed = fv, "closed-deal form (GHL custom field)", True
        if contract_val is None and le and le.get("contract_value") is not None:
            contract_val = le["contract_value"]
            contract_src = le.get("contract_provenance") or "gap-ledger evidence ladder"
            signed = "derived" not in str(contract_src)
        contract = {"value": contract_val,
                    "source": contract_src or "unknown — blank ≠ zero",
                    "signed": signed if contract_val is not None else None}

        # ATTRIBUTION + the cohort clock placement
        att = att_idx.get(key)
        tier, why = _attribution_why(det, att, lead)
        input_date = None
        if lead and lead.get("input_date"):
            input_date = str(lead["input_date"])
        elif att and att.get("input_date"):
            input_date = att["input_date"]
        cohort_why = None if input_date else (
            "no lead arrival date — this close cannot be placed on the cohort "
            "clock (no tracker lead row)" if not lead else
            "the lead row has no Input Date — cohort placement needs one")

        # STATUS — authority or two independent sources; charge evidence from
        # the ledger counts (it is a Stripe fact, not an inference)
        eff_sources = set(sources)
        if ev.get("charge_ids"):
            eff_sources.add("payment")
        status = ("confirmed" if (_AUTHORITY in eff_sources or len(eff_sources) >= 2)
                  else "proposed-needs-evidence")

        missing = []
        if not (lead and lead.get("close_date")):
            missing.append("tracker close row")
        if contract_val is None:
            missing.append("contract value")
        if not ev.get("charge_ids"):
            missing.append("a matched payment")
        if not ev.get("opp_id") and not ev.get("contact_id"):
            missing.append("the CRM record")
        if not forms.get(ev.get("contact_id")):
            missing.append("closed-deal form entry")

        entries.append({
            "id": f"cr:{key}",
            "key": key,
            "person": det["person"] or (lead or {}).get("name") or "",
            "client": client or None,
            "email": det.get("email") or (lead or {}).get("email"),
            "contact_id": ev.get("contact_id"),
            "opp_id": ev.get("opp_id"),
            "close_date": det["close_date"],
            "dated_by": det["dated_by"],
            "sources": det["sources"],
            "corroboration_pending": sorted(
                {"tracker", "ghl stage", "payment"} - eff_sources),
            "status": status,
            "contract": contract,
            "cash": cash,
            "closer": (lead or {}).get("closer") or None,
            "closer_ghl_owner_id": det.get("owner_id"),
            "setter": (lead or {}).get("setter") or None,
            "closer_commission_cell": (lead or {}).get("closer_commission"),
            "setter_commission_cell": (lead or {}).get("setter_commission"),
            "offer": (lead or {}).get("offer") or None,
            "lead": ({"input_date": input_date,
                      "lead_source": (lead or {}).get("lead_source"),
                      "tracker_row": bool(lead)} if (lead or input_date)
                     else {"tracker_row": False}),
            "attribution": {"tier": tier, "why": why,
                            "creative_key": (att or {}).get("creative_key"),
                            "creative": (att or {}).get("label")},
            "clocks": {"activity": det["close_date"],
                       "cohort": input_date, "cohort_why": cohort_why},
            "evidence": ev,
            "chips": {"tracker_row": bool(lead and lead.get("close_date")),
                      "ghl_opp": bool(ev.get("opp_id")),
                      "stripe": bool(ev.get("charge_ids")),
                      "form": bool(forms.get(ev.get("contact_id")))},
            "missing": missing,
        })

    # owner declarations (record-a-close) — evidence-backed, journaled; they
    # flow through the register like any other close
    for decl in _declarations():
        key = decl["key"]
        if any(e["key"] == key for e in entries):
            for e in entries:
                if e["key"] == key:
                    e["sources"].append({"source": "owner declaration",
                                         "provenance": decl["provenance"],
                                         "close_date": decl["close_date"]})
            continue
        entries.append(decl["entry"])

    entries.sort(key=lambda e: e["close_date"], reverse=True)
    out = {
        "at": now_sydney().isoformat(),
        "window_days": days,
        "entries": entries,
        "confirmed": sum(1 for e in entries if e["status"] == "confirmed"),
        "proposed": sum(1 for e in entries
                        if e["status"] == "proposed-needs-evidence"),
        "degraded": ([{"input": "attribution index", "reason": att_err}]
                     if att_err else []),
        "note": ("one close population — every surface reads this register; "
                 "detection is evidence-first, cash is matched Stripe charges "
                 "only, nothing here is invented"),
    }
    kv_store.put(K_REGISTER, out)
    kv_store.put(K_LAST_BUILD, {"at": out["at"], "entries": len(entries),
                                "confirmed": out["confirmed"],
                                "proposed": out["proposed"]})
    return out


def _money_like(v) -> float | None:
    s = re.sub(r"[^0-9.]", "", str(v or ""))
    try:
        f = float(s)
        return f if f >= 100 else None
    except ValueError:
        return None


def latest(build_if_empty: bool = False) -> dict:
    """The persisted register. READS NEVER BUILD: a build runs the all-time
    attribution pass and the four source readers — minutes on a cold box —
    so it belongs to the 5-minute tick, the invalidation path and the owner
    button, never to a page load or a voice answer. A cold register is an
    honest empty state that the next tick fills."""
    reg = kv_store.get(K_REGISTER)
    if reg is None and build_if_empty:
        try:
            reg = build()
        except Exception as e:  # noqa: BLE001
            logger.warning("register build-on-demand failed: %s", e)
            reg = {"entries": [], "degraded": [{"input": "register",
                                                "reason": str(e)[:160]}]}
    return reg or {"entries": [],
                   "note": "register not built yet — the next freshness "
                           "tick builds it"}


# ── THE READ — the single call site every surface uses ─────────────────────

def closes(w0: str | dt.date, w1: str | dt.date, clock: str = "activity",
           include_proposed: bool = False) -> list[dict]:
    """Register records whose CLOCK date falls in [w0, w1].

    activity → placed by close date. cohort → placed by the lead's arrival
    date; records with no cohort placement are EXCLUDED here and carried in
    totals() as unplaceable — never silently dropped."""
    if clock not in ("activity", "cohort"):
        raise ValueError(f"clock must be 'activity' or 'cohort', got {clock!r}")
    w0, w1 = str(w0), str(w1)
    out = []
    for e in latest().get("entries") or []:
        if not include_proposed and e["status"] != "confirmed":
            continue
        d = e["clocks"].get(clock)
        if d and w0 <= d <= w1:
            out.append(e)
    out.sort(key=lambda e: e["close_date"])
    return out


def totals(w0, w1, clock: str = "activity") -> dict:
    """The headline numbers for a window on ONE stated clock: total count,
    the tier breakdown, cash (matched Stripe only), contract, plus the
    proposed count and (on cohort) the closes the clock cannot place."""
    rows = closes(w0, w1, clock)
    tiers: dict[str, int] = {}
    for e in rows:
        t = e["attribution"]["tier"]
        tiers[t] = tiers.get(t, 0) + 1
    proposed = [e for e in latest().get("entries") or []
                if e["status"] == "proposed-needs-evidence"
                and e["clocks"]["activity"] and str(w0) <= e["clocks"]["activity"] <= str(w1)]
    unplaceable = []
    if clock == "cohort":
        unplaceable = [e for e in latest().get("entries") or []
                       if e["status"] == "confirmed" and not e["clocks"]["cohort"]
                       and str(w0) <= e["clocks"]["activity"] <= str(w1)]
    return {
        "window": [str(w0), str(w1)], "clock": clock,
        "count": len(rows),
        "tiers": tiers,
        "cash": round(sum(e["cash"]["amount"] or 0 for e in rows), 2),
        "contract": round(sum(e["contract"]["value"] or 0 for e in rows), 2),
        "contract_missing": sum(1 for e in rows if e["contract"]["value"] is None),
        "proposed": len(proposed),
        "proposed_people": [e["person"] for e in proposed],
        "cohort_unplaceable": len(unplaceable),
        "cohort_unplaceable_people": [e["person"] for e in unplaceable],
    }


# tier → the channel row that carries a close with no creative row on the grid
TIER_CHANNEL = {"ig_dm": "__ig_dm__", "ambiguous": "__ambiguous__",
                "unattributed": "__unattributed__"}


def scoreboard_overlay(w0, w1, clock: str, engine_keys: set,
                       rows_meta: dict) -> dict:
    """THE GRID'S CLOSE COLUMNS, COMPUTED HERE (I13: the ads blueprint
    assigns, it never does funnel arithmetic). For the /ads window on the
    grid's clock: per-row closes / cash (matched Stripe — R-CASH) / contract
    / recomputed spend ratios, with register closes that have no engine deal
    landed on their tier's channel row carrying their WHY.

    rows_meta: {creative_key: {"tier","spend","cost_basis"}} for the rows the
    scoreboard is about to render; engine_keys: name_norms of the engine's
    own deals in window."""
    reg_rows = closes(str(w0), str(w1), clock)
    per_row: dict = {}
    tiers_count: dict = {}
    tiers_cash: dict = {}
    tiers_contract: dict = {}
    contract_missing = 0
    added_total = 0
    for e in reg_rows:
        att = e.get("attribution") or {}
        tier = att.get("tier") or "unattributed"
        ck = att.get("creative_key")
        key = (ck if tier == "ad" and ck in rows_meta
               else TIER_CHANNEL.get(tier, "__unattributed__"))
        d = per_row.setdefault(key, {"closes": 0, "cash": 0.0, "contract": 0.0,
                                     "added": [], "whys": []})
        cash_amt = float((e.get("cash") or {}).get("amount") or 0)
        contract_val = (e.get("contract") or {}).get("value")
        d["closes"] += 1
        d["cash"] = round(d["cash"] + cash_amt, 2)
        d["contract"] = round(d["contract"] + float(contract_val or 0), 2)
        d["whys"].append({"person": e.get("person"), "why": att.get("why")})
        row_tier = (rows_meta.get(key) or {}).get("tier") or tier
        tiers_count[row_tier] = tiers_count.get(row_tier, 0) + 1
        tiers_cash[row_tier] = round(tiers_cash.get(row_tier, 0) + cash_amt, 2)
        tiers_contract[row_tier] = round(
            tiers_contract.get(row_tier, 0) + float(contract_val or 0), 2)
        if contract_val is None:
            contract_missing += 1
        if e["key"] not in engine_keys:
            added_total += 1
            d["added"].append({"person": e.get("person"), "client": e.get("client"),
                               "close_date": e.get("close_date"),
                               "cash": (e.get("cash") or {}).get("amount"),
                               "contract": contract_val,
                               "why": att.get("why"), "status": e.get("status"),
                               "missing": e.get("missing") or []})
    # spend ratios recomputed for real creative rows (channel rows carry none)
    for key, d in per_row.items():
        meta = rows_meta.get(key) or {}
        spend = float(meta.get("spend") or 0)
        if meta.get("cost_basis"):
            d["cost_per_close"] = (round(spend / d["closes"], 2)
                                   if d["closes"] else None)
            d["roas_cash"] = round(d["cash"] / spend, 2) if spend else None
            d["roas_contracted"] = (round(d["contract"] / spend, 2)
                                    if spend else None)
    return {
        "per_row": per_row,
        "headline": {
            "closes_total": len(reg_rows),
            "closes_tiers": tiers_count,
            "cash_total": round(sum(float((e.get("cash") or {}).get("amount") or 0)
                                    for e in reg_rows), 2),
            "cash_tiers": tiers_cash,
            "contract_total": round(sum(float((e.get("contract") or {}).get("value") or 0)
                                        for e in reg_rows), 2),
            "contract_tiers": tiers_contract,
            "contract_missing": contract_missing,
            "population": "close register",
        },
        "register_closes": len(reg_rows),
        "added_outside_engine": added_total,
        "clock": clock,
    }


def record(key_or_id: str) -> dict | None:
    k = key_or_id.replace("cr:", "")
    return next((e for e in latest().get("entries") or []
                 if e["key"] == k or e["id"] == key_or_id), None)


# ── the journal: corrections + owner declarations ───────────────────────────

def journal(kind: str, detail: str, actor: str, evidence: dict | None = None):
    j = kv_store.get(K_JOURNAL) or []
    j.append({"at": now_sydney().isoformat(), "kind": kind, "detail": detail,
              "actor": actor, "evidence": evidence or {}})
    kv_store.put(K_JOURNAL, j[-1000:])


def journal_entries() -> list[dict]:
    return kv_store.get(K_JOURNAL) or []


K_DECLARED = "register:declared"


def _declarations() -> list[dict]:
    return kv_store.get(K_DECLARED) or []


def declare_close(person: str, close_date: str, evidence_kind: str,
                  evidence_id: str, actor: str = "rydel",
                  client: str | None = None) -> dict:
    """RECORD A CLOSE — the owner path for when a human knows something the
    system doesn't. It only accepts REAL evidence: a GHL opportunity id, a
    Stripe charge id, or a closed-deal form contact id, VERIFIED against the
    store it names. Free text alone is rejected."""
    kinds = ("ghl_opportunity", "stripe_charge", "closed_deal_form")
    if evidence_kind not in kinds:
        return {"ok": False, "error": f"evidence_kind must be one of {kinds}"}
    if not str(evidence_id or "").strip():
        return {"ok": False, "error": "an evidence id is required — free text "
                                      "alone does not create a close"}
    check = _verify_evidence(evidence_kind, evidence_id)
    if not check.get("ok"):
        return {"ok": False, "error": f"the named evidence could not be found: "
                                      f"{check.get('why')}"}
    if not re.match(r"\d{4}-\d{2}-\d{2}$", str(close_date or "")):
        return {"ok": False, "error": "close_date must be YYYY-MM-DD"}
    key = _norm(person)
    if not key:
        return {"ok": False, "error": "a person is required"}
    ev = {evidence_kind: evidence_id, **(check.get("evidence") or {})}
    entry = {
        "id": f"cr:{key}", "key": key, "person": person, "client": client,
        "email": None, "contact_id": ev.get("contact_id"),
        "opp_id": ev.get("opp_id"),
        "close_date": close_date, "dated_by": "owner declaration",
        "sources": [{"source": "owner declaration",
                     "provenance": f"declared by {actor} on {str(today_sydney())} "
                                   f"with {evidence_kind} {evidence_id}",
                     "close_date": close_date}],
        "corroboration_pending": ["tracker", "ghl stage", "payment"],
        "status": "confirmed",
        "contract": {"value": None, "source": "unknown — blank ≠ zero",
                     "signed": None},
        "cash": {"amount": check.get("amount"),
                 "charge_ids": ([evidence_id] if evidence_kind == "stripe_charge"
                                else []),
                 "source": ("matched Stripe charges"
                            if evidence_kind == "stripe_charge"
                            else "no matched Stripe/Xero payment on file"),
                 "tracker_cell": None},
        "closer": None, "closer_ghl_owner_id": None, "setter": None,
        "offer": None,
        "lead": {"tracker_row": False},
        "attribution": {"tier": "unattributed",
                        "why": "owner-declared close — no lead row to read an "
                               "ad stamp from",
                        "creative_key": None, "creative": None},
        "clocks": {"activity": close_date, "cohort": None,
                   "cohort_why": "owner-declared — no lead arrival date"},
        "evidence": ev,
        "chips": {"tracker_row": False,
                  "ghl_opp": evidence_kind == "ghl_opportunity",
                  "stripe": evidence_kind == "stripe_charge",
                  "form": evidence_kind == "closed_deal_form"},
        "missing": ["tracker close row", "contract value"],
        "declared": True,
    }
    decls = _declarations()
    decls = [d for d in decls if d["key"] != key]
    decls.append({"key": key, "close_date": close_date,
                  "provenance": entry["sources"][0]["provenance"],
                  "entry": entry})
    kv_store.put(K_DECLARED, decls[-200:])
    journal("owner_declaration",
            f"close recorded for {person} ({close_date}) on {evidence_kind} "
            f"{evidence_id}", actor, ev)
    # ONE invalidation path: it rebuilds the register first, then the blocks
    try:
        import close_detect
        close_detect.invalidate_now(f"owner recorded a close: {person}")
    except Exception as e:  # noqa: BLE001
        logger.warning("register: invalidation after declaration failed: %s", e)
        build()
    return {"ok": True, "entry": record(key),
            "register_entries": len(latest().get("entries") or [])}


def _verify_evidence(kind: str, eid: str) -> dict:
    """The evidence must exist in the store it names. Read-only lookups."""
    try:
        if kind == "ghl_opportunity":
            import db
            with db.get_conn() as c:
                r = c.execute("SELECT id, contact_id, stage_name FROM "
                              "ghl_opportunities WHERE id=%s AND deleted=FALSE",
                              (eid,)).fetchone()
            if r:
                return {"ok": True, "evidence": {"opp_id": r["id"],
                                                 "contact_id": r["contact_id"],
                                                 "stage": r["stage_name"]}}
            return {"ok": False, "why": "no GHL opportunity with that id in the mirror"}
        if kind == "stripe_charge":
            import unmatched_payments as UP
            st = UP.latest()
            for m in (st.get("matched") or []) + (st.get("rows") or []):
                if m.get("charge_id") == eid:
                    return {"ok": True, "amount": m.get("amount"),
                            "evidence": {"charge_ids": [eid],
                                         "payer": m.get("payer")}}
            return {"ok": False, "why": "no charge with that id in the scanned "
                                        "window — run the payments scan first"}
        if kind == "closed_deal_form":
            forms = _form_entries()
            if eid in forms:
                return {"ok": True, "evidence": {"contact_id": eid,
                                                 "form": forms[eid]}}
            return {"ok": False, "why": "no closed-deal form values on that "
                                        "contact in the mirror"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": str(e)[:160]}
    return {"ok": False, "why": "unknown evidence kind"}


# ── evidence-picker feeds for the RECORD A CLOSE dialog ─────────────────────

def evidence_options(q: str = "") -> dict:
    """Searchable REAL evidence the dialog offers — never free text."""
    qn = _norm(q)

    def hit(*vals):
        return not qn or any(qn in _norm(v) for v in vals)
    opts = {"ghl_opportunities": [], "stripe_charges": [], "closed_deal_forms": []}
    try:
        import db
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT id, name, stage_name, last_stage_change_at FROM "
                "ghl_opportunities WHERE deleted=FALSE "
                "ORDER BY last_stage_change_at DESC NULLS LAST LIMIT 200").fetchall()
        for r in rows:
            if hit(r["name"], r["stage_name"]):
                opts["ghl_opportunities"].append(
                    {"id": r["id"], "label": f"{r['name']} · {r['stage_name']} · "
                     f"{str(r['last_stage_change_at'] or '')[:10]}"})
    except Exception as e:  # noqa: BLE001
        logger.info("register: opp options unavailable: %s", e)
    try:
        import unmatched_payments as UP
        st = UP.latest()
        for m in (st.get("matched") or []) + (st.get("rows") or []):
            if hit(m.get("payer"), m.get("client")):
                opts["stripe_charges"].append(
                    {"id": m.get("charge_id"),
                     "label": f"{m.get('payer')} · ${m.get('amount')} · {m.get('date')}"})
    except Exception as e:  # noqa: BLE001
        logger.info("register: charge options unavailable: %s", e)
    try:
        for cid, form in _form_entries().items():
            if hit(cid, json.dumps(form)):
                opts["closed_deal_forms"].append(
                    {"id": cid, "label": f"contact {cid} · "
                     f"{list(form.keys())[0] if form else ''}"})
    except Exception as e:  # noqa: BLE001
        logger.info("register: form options unavailable: %s", e)
    for k in opts:
        opts[k] = opts[k][:25]
    return opts


# ── the Piolo package: what to type, per gap ────────────────────────────────

def piolo_lines() -> list[dict]:
    """Exact-cell instructions per register gap. The tracker stays view-only —
    these are what to type, not writes."""
    out = []
    for e in latest().get("entries") or []:
        edits = []
        if "tracker close row" in e["missing"]:
            edits.append(f"lead row + Close Date = {e['close_date']}")
        if "contract value" in e["missing"]:
            edits.append("Contract Value = (from the closed-deal form — never "
                         "inferred from the payment)")
        if "a matched payment" in e["missing"]:
            edits.append("Cash Collected = (once a payment is matched — check "
                         "the payer name against Stripe)")
        if edits:
            out.append({"person": e["person"], "client": e["client"],
                        "close_date": e["close_date"], "status": e["status"],
                        "edits": edits})
    return out


# ── the daily reconciliation (sentinel) ─────────────────────────────────────

def reconcile() -> dict:
    """Each raw source vs the register, both directions. Anything a source
    knows that the register lacks is a LOUD finding naming the deal and the
    source; a register entry uncorroborated after N days is flagged too."""
    N_DAYS_UNCORROBORATED = 7
    reg = latest()
    reg_keys = {e["key"] for e in reg.get("entries") or []}
    findings = []
    import close_detect as CD
    for fn, label in ((CD._from_tracker, "tracker"), (CD._from_ghl, "GHL closed stage"),
                      (CD._from_payments, "matched payment")):
        try:
            for row in fn() or []:
                k = _norm(row.get("person"))
                if k and k not in reg_keys and row.get("close_date"):
                    findings.append({
                        "kind": "known_to_source_missing_from_register",
                        "severity": "S1",
                        "person": row.get("person"), "source": label,
                        "close_date": row["close_date"],
                        "detail": f"{label} shows a close for {row.get('person')} "
                                  f"({row['close_date']}) that the register does "
                                  f"not hold"})
        except Exception as e:  # noqa: BLE001
            findings.append({"kind": "source_unreadable", "severity": "S2",
                             "source": label, "detail": str(e)[:160]})
    today = today_sydney()
    for e in reg.get("entries") or []:
        if e["status"] != "proposed-needs-evidence":
            continue
        try:
            age = (today - dt.date.fromisoformat(e["close_date"])).days
        except ValueError:
            continue
        if age >= N_DAYS_UNCORROBORATED:
            findings.append({
                "kind": "uncorroborated_after_n_days", "severity": "S2",
                "person": e["person"], "close_date": e["close_date"],
                "detail": f"{e['person']} has sat on one source "
                          f"({e['dated_by']}) for {age} days — still missing: "
                          f"{', '.join(e['missing'])}"})
    out = {"at": now_sydney().isoformat(), "findings": findings,
           "ok": not any(f["severity"] == "S1" for f in findings),
           "register_entries": len(reg.get("entries") or []),
           "note": f"uncorroborated threshold: {N_DAYS_UNCORROBORATED} days"}
    kv_store.put(K_RECON, out)
    try:
        import kv_store as _kv
        _kv.put("feed:extra:close_register", [
            {"kind": "close_register_reconciliation", "severity": f["severity"],
             "title": f"closes reconciliation: {f['kind'].replace('_', ' ')}",
             "detail": f["detail"]}
            for f in findings[:10]])
    except Exception:  # noqa: BLE001
        pass
    return out


def reconciliation_latest() -> dict | None:
    return kv_store.get(K_RECON)


K_DAILY = "register:daily_tick"


def daily_tick() -> bool:
    """Once a day — or immediately when the register is COLD (fresh deploy,
    new store): rebuild + reconcile. Rides the 5-minute freshness loop;
    reads never build, so this is the path that fills a cold register."""
    stamp = kv_store.get(K_DAILY)
    today = str(today_sydney())
    if stamp == today and kv_store.get(K_REGISTER) is not None:
        return False
    try:
        build()
        reconcile()
        kv_store.put(K_DAILY, today)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("register daily tick failed: %s", e)
        return False
