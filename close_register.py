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
    return _merge_same_email(found)


def _merge_same_email(found: dict) -> dict:
    """#170: one person, one close. The tracker wrote "HOANG PHUOC PHAM",
    the CRM "HOANG PHUOC PHAM (Max)" — two keys, two closes, the same email.
    Records sharing an identical email on the SAME close date merge into
    the one the tracker (the authority) carries; sources and evidence
    union. Different dates stay separate (a second deal is real)."""
    by_email: dict[tuple, list[str]] = {}
    for key, e in found.items():
        em = (e.get("email") or "").strip().lower()
        if em:
            by_email.setdefault((em, e["close_date"]), []).append(key)
    for (_em, _d), keys in by_email.items():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: (not any(s["source"] == _AUTHORITY
                                         for s in found[k]["sources"]), k))
        keep = found[keys[0]]
        for k in keys[1:]:
            other = found.pop(k)
            keep["sources"].extend(other["sources"])
            for ek, ev in (other.get("evidence") or {}).items():
                if ek == "charge_ids":
                    for cid in ev or []:
                        keep["evidence"].setdefault("charge_ids", [])
                        if cid not in keep["evidence"]["charge_ids"]:
                            keep["evidence"]["charge_ids"].append(cid)
                elif ev not in (None, ""):
                    keep["evidence"].setdefault(ek, ev)
            for fk in ("client", "owner_id"):
                keep[fk] = keep.get(fk) or other.get(fk)
            keep.setdefault("merged_from", []).append(other["person"])
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
            fv, why = _form_contract(form)
            if fv:
                contract_val, contract_src, signed = fv, "closed-deal form (GHL custom field)", True
            elif why:
                contract_src = f"closed-deal form: {why} — needs your number"
        if contract_val is None and le and le.get("contract_value") is not None:
            # defensive (#170): a text cell once reached here and broke every tile
            contract_val = _money_like(le["contract_value"])
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

    # owner deal-terms rulings (#170) — the contract rung, and a close of
    # their own when no system has recorded one yet
    for key, t in deal_terms().items():
        e = next((x for x in entries if x["key"] == key), None)
        if e is None:
            e = _ruling_entry(t)
            entries.append(e)
        else:
            e["sources"].append({"source": "owner ruling",
                                 "provenance": f"deal terms ruled by {t['by']} "
                                               f"on {t['at'][:10]}",
                                 "close_date": t["close_date"]})
        _apply_terms(e, t)

    # #171: THE COMPLETE CLOSE — every entry names exactly which of its
    # fields is still missing, with who can fill it. Confirmed or proposed.
    for e in entries:
        e["gaps"] = gaps(e)
        e["complete"] = not e["gaps"]

    entries.sort(key=lambda e: e["close_date"], reverse=True)
    out = {
        "at": now_sydney().isoformat(),
        "window_days": days,
        "entries": entries,
        "incomplete": sum(1 for e in entries if e["gaps"]),
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


# #170 (Rydel, 29 Sep): the form's contract value comes from its NAMED field
# only. The first dollar-looking field could be the upfront payment, a
# setup fee or a monthly — never read by position or by shape.
_FORM_CONTRACT_FIELDS = ("contract value", "total contract value",
                         "contract value ex gst", "contract_value")


def _form_contract(form: dict) -> tuple[float | None, str | None]:
    """(value, None) from exactly one named field; (None, why) otherwise."""
    hits = {}
    for k, v in (form or {}).items():
        kn = re.sub(r"[^a-z ]", "", str(k).lower().replace("_", " ")).strip()
        if kn in _FORM_CONTRACT_FIELDS and _money_like(v) is not None:
            hits[k] = _money_like(v)
    vals = set(hits.values())
    if len(vals) == 1:
        return vals.pop(), None
    if len(vals) > 1:
        return None, f"ambiguous — {len(vals)} contract fields disagree"
    return None, "no named contract-value field"


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


def proposed_note(w0, w1, window_key: str) -> dict | None:
    """#170 (Rydel, 29 Sep): every tile that counts only CONFIRMED closes says
    how many proposed ones it left out, with a door to them. One helper, so
    every surface uses the same words and the same link."""
    try:
        n = totals(w0, w1, "activity")["proposed"]
    except Exception:  # noqa: BLE001
        return None
    if not n:
        return None
    return {"n": n, "label": f"+{n} proposed, not counted",
            "href": f"/dashboard/closes?window={window_key}"}


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


# ── OWNER DEAL-TERMS RULINGS (#170) ─────────────────────────────────────────
# What a human signed that no system recorded: package, term, contract ex-GST,
# the payment schedule, closer, setter. Rydel's word, VERBATIM, journaled —
# it is the contract rung of the evidence ladder (above the tracker cell: the
# owner ruled it explicitly). Cash is NEVER taken from the ruling: a payment
# counts only when its bank-feed or Stripe evidence id is attached, and a
# payment into a personal account is never business cash.

K_TERMS = "register:deal_terms"
_ACCOUNTS = ("business", "personal")


def deal_terms() -> dict:
    return kv_store.get(K_TERMS) or {}


def rule_deal_terms(person: str, client: str, close_date: str, package: str,
                    term_months: int, contract_ex_gst: float,
                    schedule: list[dict], words: str, actor: str = "rydel",
                    closer: str | None = None, setter: str | None = None,
                    payment_type: str | None = None,
                    contact: str | None = None,
                    closer_commission: float | None = None) -> dict:
    """schedule: [{"n", "amount", "gst": "inc"|"ex", "due",
                   "received": date|None, "channel": "bank transfer"|"stripe",
                   "account": "business"|"personal"|None,
                   "evidence_id": bank-feed txn id | charge id | None}]"""
    import comp_rulebook as RB
    if not (words or "").strip():
        return {"ok": False, "error": "the ruling's own words are required — "
                                      "they are the evidence"}
    if not re.match(r"\d{4}-\d{2}-\d{2}$", str(close_date or "")):
        return {"ok": False, "error": "close_date must be YYYY-MM-DD"}
    pkg = RB.normalise_package(package)
    if pkg is None:
        return {"ok": False, "error": f"package {package!r} is not one the "
                                      "rulebook recognises — name it exactly"}
    if not (contract_ex_gst and float(contract_ex_gst) > 0):
        return {"ok": False, "error": "contract value ex-GST is required"}
    for p in schedule or []:
        if p.get("gst") not in ("inc", "ex"):
            return {"ok": False, "error": f"payment {p.get('n')}: say whether "
                                          "the amount is inc or ex GST"}
        if p.get("received") and p.get("account") not in _ACCOUNTS:
            return {"ok": False, "error": f"payment {p.get('n')}: a received "
                                          "payment needs its account "
                                          "(business or personal)"}
    key = _norm(person)
    rec = {"key": key, "person": person, "client": client, "contact": contact,
           "close_date": close_date, "package": pkg, "package_words": package,
           "term_months": int(term_months), "payment_type": payment_type,
           "contract_ex_gst": round(float(contract_ex_gst), 2),
           "schedule": schedule or [], "closer": closer, "setter": setter,
           # a DEAL-SPECIFIC closer commission (Rydel's word) — counted as
           # recorded for this deal only; the rulebook is untouched
           "closer_commission": (round(float(closer_commission), 2)
                                 if closer_commission is not None else None),
           "words": words, "by": actor, "at": now_sydney().isoformat()}
    terms = deal_terms()
    prior = terms.get(key)
    terms[key] = rec
    kv_store.put(K_TERMS, terms)
    journal("owner_ruling",
            f"deal terms ruled for {person} ({client}): {package}, "
            f"{term_months} months, ${float(contract_ex_gst):,.2f} ex-GST"
            + (" — supersedes an earlier ruling" if prior else ""),
            actor, {"words": words, "prior": prior})
    try:
        import close_detect
        close_detect.invalidate_now(f"owner ruled deal terms: {person}")
    except Exception as e:  # noqa: BLE001
        logger.warning("register: invalidation after ruling failed: %s", e)
        build()
    return {"ok": True, "ruling": rec}


def _ex(amount, gst: str) -> float:
    return round(float(amount) / 1.1, 2) if gst == "inc" else round(float(amount), 2)


def _apply_terms(e: dict, t: dict) -> None:
    """The ruling onto a register entry: contract, package, schedule, and the
    cash states — counted / pending bank feed / outside business accounts /
    receivable. Never invents a received payment."""
    src = f"owner ruling — {t['by']}, {t['at'][:10]}, journaled"
    tracker_cv = (e.get("contract") or {}).get("value")
    e["contract"] = {"value": t["contract_ex_gst"], "source": src, "signed": True,
                     "gst": "ex"}
    if tracker_cv is not None and abs(float(tracker_cv) - t["contract_ex_gst"]) > 0.5:
        e["contract"]["conflict"] = (f"the tracker says ${float(tracker_cv):,.2f} "
                                     "— the ruling is used; fix one of them")
    e["package"], e["term_months"] = t["package"], t["term_months"]
    e["payment_type"] = t.get("payment_type")
    e["client"] = e.get("client") or t.get("client")
    if t.get("closer"):
        e["closer"] = t["closer"]
    if t.get("setter"):
        e["setter"] = t["setter"]
    e["closer_commission_ruled"] = t.get("closer_commission")
    e["package_words"] = t.get("package_words")
    counted, pending, outside, receivable, events = [], [], [], [], []
    for p in t.get("schedule") or []:
        row = {"n": p.get("n"), "amount": p.get("amount"), "gst": p.get("gst"),
               "ex_gst": _ex(p["amount"], p["gst"]), "due": p.get("due"),
               "received": p.get("received"), "channel": p.get("channel"),
               "evidence_id": p.get("evidence_id")}
        events.append({"when": p.get("received") or p.get("due") or t["close_date"],
                       "amount": p["amount"], "inclusive": p["gst"] == "inc"})
        if not p.get("received"):
            receivable.append(row)
        elif p.get("account") == "personal":
            outside.append({**row, "state": "cash received outside business "
                                             "accounts — not business cash"})
        elif p.get("evidence_id"):
            counted.append({**row, "state": "counted — evidence on file"})
        else:
            pending.append({**row, "state": "cash pending bank feed"})
    e["ruled_cash"] = {"counted": counted, "pending_bank_feed": pending,
                       "outside_business_accounts": outside,
                       "receivable": receivable}
    e["cash_events"] = events
    # the register's cash is GST-INCLUSIVE (Stripe's basis) — a ruled amount
    # given ex-GST is converted before it joins, never mixed
    ruled_cash = sum((float(r["amount"]) if r["gst"] == "inc" else float(r["amount"]) * 1.1)
                     for r in counted
                     if r["evidence_id"] not in ((e.get("cash") or {}).get("charge_ids") or []))
    if ruled_cash:
        cash = e.setdefault("cash", {"amount": None, "charge_ids": []})
        cash["amount"] = round(float(cash.get("amount") or 0) + ruled_cash, 2)
        cash["source"] = "matched Stripe charges + owner-matched bank-feed deposits"
    e["ruling"] = {"words": t["words"], "by": t["by"], "at": t["at"]}
    e["missing"] = [m for m in (e.get("missing") or []) if m != "contract value"]


def _ruling_entry(t: dict) -> dict:
    """A close that exists ONLY as the owner's word — labelled as such."""
    return {
        "id": f"cr:{t['key']}", "key": t["key"], "person": t["person"],
        "client": t.get("client"), "email": None, "contact_id": None,
        "opp_id": None, "close_date": t["close_date"],
        "dated_by": "owner ruling",
        "sources": [{"source": "owner ruling",
                     "provenance": f"ruled by {t['by']} on {t['at'][:10]} — "
                                   "owner-recorded, awaiting GHL/Xero evidence",
                     "close_date": t["close_date"]}],
        "label": "owner-recorded — awaiting GHL/Xero evidence",
        "corroboration_pending": ["tracker", "ghl stage", "payment"],
        "status": "confirmed",
        "contract": {}, "cash": {"amount": None, "charge_ids": [],
                                 "source": "no matched Stripe/Xero payment on file",
                                 "tracker_cell": None},
        "closer": None, "setter": None, "offer": t.get("package_words"),
        "lead": {"tracker_row": False},
        "attribution": {"tier": "unattributed",
                        "why": "owner-ruled close — no lead row to read an ad stamp from",
                        "creative_key": None, "creative": None},
        "clocks": {"activity": t["close_date"], "cohort": None,
                   "cohort_why": "owner-ruled — no lead arrival date"},
        "evidence": {"owner_ruling": t["at"]},
        "chips": {"tracker_row": False, "ghl_opp": False, "stripe": False,
                  "form": False, "ruling": True},
        "missing": ["tracker close row", "the CRM record"],
        "declared": True,
    }


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
        # #171: a ruling's facts are what to type — the tracker gets fixed at
        # source from the same submission that fixed the register
        if e.get("ruling"):
            edits.append(f"Offer = {e.get('package_words') or e.get('package')}"
                         + (f"; Contract Value = ${float(e['contract']['value']):,.2f} ex-GST"
                            if (e.get("contract") or {}).get("value") is not None else "")
                         + (f"; Closer = {e['closer']}" if e.get("closer") else "")
                         + (f"; Setter = {e['setter']}" if e.get("setter") else ""))
        for row in ((e.get("ruled_cash") or {}).get("outside_business_accounts") or []):
            edits.append(f"payment {row.get('n')} (${float(row.get('amount') or 0):,.2f}) "
                         "went to a PERSONAL account — not business cash; it counts "
                         "only once it appears in Xero on a business account")
        if edits:
            out.append({"person": e["person"], "client": e["client"],
                        "close_date": e["close_date"], "status": e["status"],
                        "edits": edits})
    return out


# ── the daily reconciliation (sentinel) ─────────────────────────────────────

def reconcile() -> dict:
    """THE FOUR-SOURCE CROSS-CHECK (#171, Phase 3; nightly and on every event).

    GHL (closed-won stages + the stage recorder), Stripe (matched charges),
    Xero (bank-feed receipts through the contact map, where readable) and the
    tracker (won rows), each against the register, both directions:
      · a close any source knows that the register doesn't → loud, by name
      · a payment not attached to any close → the matching queue, counted
      · amount / date / package disagreements between sources → both values
      · a register close with no corroboration after 3 days → finding
      · a close missing its daily-habit items after 24 h → an internal
        reminder naming who owns the gap (Kalin / Piolo) — never client-facing
    Results land on the System page and the Today feed in plain words."""
    N_DAYS_UNCORROBORATED = 3
    HABIT_HOURS = 24
    reg = latest()
    entries = reg.get("entries") or []
    reg_keys = {e["key"] for e in entries}
    by_key = {e["key"]: e for e in entries}
    findings = []
    sources_checked = []
    import close_detect as CD
    for fn, label in ((CD._from_tracker, "tracker"), (CD._from_ghl, "GHL closed stage"),
                      (CD._from_stage_recorder, "GHL stage recorder"),
                      (CD._from_payments, "matched payment")):
        try:
            rows = fn() or []
            sources_checked.append({"source": label, "rows": len(rows)})
            for row in rows:
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
                elif k in by_key and row.get("close_date") and label in ("GHL closed stage",):
                    # DATE DISAGREEMENT: the register's date vs this source's
                    e = by_key[k]
                    try:
                        d_reg = dt.date.fromisoformat(str(e["close_date"])[:10])
                        d_src = dt.date.fromisoformat(str(row["close_date"])[:10])
                        if abs((d_reg - d_src).days) > 3 and e.get("dated_by") != label:
                            findings.append({
                                "kind": "date_disagreement", "severity": "S2",
                                "person": e["person"],
                                "detail": f"{e.get('client') or e['person']}: the register dates the "
                                          f"close {d_reg} (by {e.get('dated_by')}) but {label} says "
                                          f"{d_src} — {abs((d_reg - d_src).days)} days apart"})
                    except (ValueError, TypeError):
                        pass
        except Exception as e:  # noqa: BLE001
            findings.append({"kind": "source_unreadable", "severity": "S2",
                             "source": label, "detail": f"{label} could not be read: {str(e)[:120]}"})
    # XERO — bank-feed receipts via the contact map (the agent's token has no
    # invoice-read scope, DECISIONS #161 — said plainly, never faked)
    try:
        import client_receipts as CRx
        maps = CRx.mappings()
        sources_checked.append({"source": "Xero contact map", "rows": len(maps)})
        xero_unreadable = True
        try:
            import xero_pull
            xero_unreadable = not hasattr(xero_pull, "read_receipts")
        except Exception:  # noqa: BLE001
            pass
        if xero_unreadable:
            findings.append({"kind": "source_limited", "severity": "S3", "source": "Xero",
                             "detail": "Xero bank-feed receipts cannot be read by the agent's "
                                       "token (no invoice/bank scope) — the Xero leg uses the "
                                       f"{len(maps)} ruled contact mapping(s) and the owner's "
                                       "ruled payment schedules only"})
    except Exception as e:  # noqa: BLE001
        findings.append({"kind": "source_unreadable", "severity": "S2", "source": "Xero",
                         "detail": str(e)[:120]})

    # AMOUNT / PACKAGE DISAGREEMENTS inside the register (tracker vs ruling vs Stripe)
    for e in entries:
        c = e.get("contract") or {}
        if c.get("conflict"):
            findings.append({"kind": "amount_disagreement", "severity": "S2", "person": e["person"],
                             "detail": f"{e.get('client') or e['person']}: contract — ruling "
                                       f"${float(c.get('value') or 0):,.2f} ex-GST; {c['conflict']}"})
        cash = e.get("cash") or {}
        cell = cash.get("tracker_cell")
        try:
            cell_v = float(str(cell).replace("$", "").replace(",", "")) if cell not in (None, "") else None
        except ValueError:
            cell_v = None
        if cell_v is not None and cash.get("amount") is not None and abs(cell_v - float(cash["amount"])) > 1.0:
            findings.append({"kind": "amount_disagreement", "severity": "S2", "person": e["person"],
                             "detail": f"{e.get('client') or e['person']}: cash — the tracker cell says "
                                       f"${cell_v:,.2f}, matched Stripe charges total "
                                       f"${float(cash['amount']):,.2f}"})
        if e.get("ruling") and e.get("offer") and e.get("package"):
            try:
                import comp_rulebook as RB
                if RB.normalise_package(e["offer"]) not in (None, e["package"]):
                    findings.append({"kind": "package_disagreement", "severity": "S2",
                                     "person": e["person"],
                                     "detail": f"{e.get('client') or e['person']}: package — the tracker "
                                               f"says '{e['offer']}', the ruling says "
                                               f"'{e.get('package_words') or e['package']}'"})
            except Exception:  # noqa: BLE001
                pass

    # PAYMENTS NOT ATTACHED TO ANY CLOSE → the matching queue
    try:
        import unmatched_payments as UP
        st = UP.latest()
        n_un = len(st.get("rows") or [])
        if n_un:
            findings.append({"kind": "payments_unattached", "severity": "S2",
                             "detail": f"{n_un} payment(s) totalling ${float(st.get('total_unmatched') or 0):,.2f} "
                                       "are not attached to any close — in the matching queue"})
        try:
            import match_proposals as MP
            mc = MP.cards()
            if mc.get("pending_count"):
                findings.append({"kind": "match_proposals_pending", "severity": "S3",
                                 "detail": f"{mc['pending_count']} proposed payer/contact match(es) are "
                                           "waiting for a decision on the match cards"})
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        findings.append({"kind": "source_unreadable", "severity": "S3", "source": "payments scan",
                         "detail": str(e)[:120]})

    today = today_sydney()
    now = now_sydney()
    reminders = []
    for e in entries:
        try:
            age_days = (today - dt.date.fromisoformat(str(e["close_date"])[:10])).days
        except (ValueError, TypeError):
            continue
        if e["status"] == "proposed-needs-evidence" and age_days >= N_DAYS_UNCORROBORATED:
            findings.append({
                "kind": "uncorroborated_after_n_days", "severity": "S2",
                "person": e["person"], "close_date": e["close_date"],
                "detail": f"{e.get('client') or e['person']} has sat on one source "
                          f"({e['dated_by']}) for {age_days} days — still missing: "
                          f"{', '.join(e.get('missing') or [])}"})
        # DAILY-HABIT ITEMS after 24 h — internal reminders naming the owner
        if age_days * 24 >= HABIT_HOURS:
            chips = e.get("chips") or {}
            who = e.get("client") or e["person"]
            if not chips.get("ghl_opp") and not e.get("opp_id"):
                reminders.append({"owner": "Kalin", "person": e["person"],
                                  "detail": f"{who}: move the GHL opportunity to Closed Won"})
            if not chips.get("form"):
                reminders.append({"owner": "Kalin", "person": e["person"],
                                  "detail": f"{who}: submit the Closed Deal Form"})
            if not chips.get("tracker_row"):
                reminders.append({"owner": "Piolo", "person": e["person"],
                                  "detail": f"{who}: add the tracker close row (date {e['close_date']})"})
            rc = e.get("ruled_cash") or {}
            if not ((e.get("cash") or {}).get("charge_ids") or rc.get("counted")):
                reminders.append({"owner": "Piolo", "person": e["person"],
                                  "detail": f"{who}: raise/confirm the Xero invoice and match the receipt "
                                            "(the agent cannot read invoices — confirm by hand)"})
    out = {"at": now.isoformat(), "findings": findings,
           "reminders": reminders[:60],
           "sources_checked": sources_checked,
           "ok": not any(f["severity"] == "S1" for f in findings),
           "register_entries": len(entries),
           "note": (f"four sources vs the register, both directions · uncorroborated threshold "
                    f"{N_DAYS_UNCORROBORATED} days · daily-habit reminders after {HABIT_HOURS} hours "
                    "(internal — Kalin / Piolo)")}
    kv_store.put(K_RECON, out)
    try:
        kv_store.put("feed:extra:close_register", [
            {"kind": "close_register_reconciliation", "severity": f["severity"],
             "title": f"closes cross-check: {f['kind'].replace('_', ' ')}",
             "detail": f["detail"]}
            for f in findings if f["severity"] in ("S1", "S2")][:10])
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


# ═══════════════════════════════════════════════════════════════════════════
# #171 — THE COMPLETE CLOSE, THE QUEUE, THE FILL-IN FORM
# ═══════════════════════════════════════════════════════════════════════════
# A close is the atomic unit of truth. These are its fields; each gap names
# who can close it. "Confirmed" says the close HAPPENED; "complete" says we
# know everything about it that the unit economics need.

GAP_OWNERS = {
    "client or venue name": "Rydel / Piolo (fill-in form)",
    "package": "Rydel / Piolo (fill-in form)",
    "term (months)": "Rydel / Piolo (fill-in form)",
    "contract value ex-GST": "Rydel / Piolo (fill-in form)",
    "payment schedule": "Rydel / Piolo (fill-in form)",
    "a matched payment (Stripe or Xero bank feed)": "Piolo (match the payment)",
    "closer": "Rydel / Piolo (fill-in form)",
    "setter": "Rydel / Piolo (fill-in form)",
    "CRM Closed Won stage": "Kalin (GHL)",
    "closed-deal form": "Kalin (GHL form)",
    "tracker close row": "Piolo (tracker)",
    "lead row (for ad attribution)": "Piolo (tracker)",
}


def gaps(e: dict) -> list[str]:
    """Exactly which complete-close fields this entry lacks — plain words."""
    out = []
    if not e.get("client"):
        out.append("client or venue name")
    pkg = e.get("package")
    if not pkg:
        try:
            import comp_rulebook as RB
            pkg = RB.normalise_package(e.get("offer"))
        except Exception:  # noqa: BLE001
            pkg = None
    if not pkg:
        out.append("package")
    term = e.get("term_months")
    if not term and pkg:
        try:
            from config import PACKAGE_TERMS
            import csm_baselines as B
            k = B._pkg_key(e.get("offer") or e.get("package"))
            term = PACKAGE_TERMS.get(k) if k else None
        except Exception:  # noqa: BLE001
            term = None
    if not term:
        out.append("term (months)")
    if (e.get("contract") or {}).get("value") is None:
        out.append("contract value ex-GST")
    rc = e.get("ruled_cash") or {}
    has_schedule = any(rc.get(k) for k in ("counted", "pending_bank_feed",
                                            "outside_business_accounts", "receivable"))
    if not has_schedule:
        out.append("payment schedule")
    if not ((e.get("cash") or {}).get("charge_ids") or rc.get("counted")):
        out.append("a matched payment (Stripe or Xero bank feed)")
    if not e.get("closer"):
        out.append("closer")
    if not e.get("setter"):
        out.append("setter")
    chips = e.get("chips") or {}
    if not chips.get("ghl_opp") and not e.get("opp_id"):
        out.append("CRM Closed Won stage")
    if not chips.get("form"):
        out.append("closed-deal form")
    if not chips.get("tracker_row"):
        out.append("tracker close row")
    if not (e.get("lead") or {}).get("tracker_row"):
        out.append("lead row (for ad attribution)")
    return out


def missing_details_queue(limit: int | None = None, days: int | None = None) -> dict:
    """DEALS MISSING DETAILS — every close (confirmed or proposed) with any
    gap, oldest first, naming the gaps and who fills each. Reads the
    persisted register only (never builds)."""
    reg = latest()
    rows = []
    cutoff = (str(today_sydney() - dt.timedelta(days=days)) if days else None)
    for e in reg.get("entries") or []:
        g = e.get("gaps")
        if g is None:
            g = gaps(e)
        if not g:
            continue
        if cutoff and e.get("close_date", "") < cutoff:
            continue
        rows.append({
            "key": e["key"], "person": e.get("person"), "client": e.get("client"),
            "close_date": e.get("close_date"), "status": e.get("status"),
            "label": e.get("label"),
            "gaps": g, "owners": sorted({GAP_OWNERS.get(x, "Rydel") for x in g}),
            "known": {
                "package": e.get("package_words") or e.get("package") or e.get("offer"),
                "term_months": e.get("term_months"),
                "contract_ex_gst": (e.get("contract") or {}).get("value"),
                "cash_inc_gst": (e.get("cash") or {}).get("amount"),
                "closer": e.get("closer"), "setter": e.get("setter"),
                "contact_id": e.get("contact_id"), "opp_id": e.get("opp_id"),
            },
            "ruled": bool(e.get("ruling")),
        })
    rows.sort(key=lambda r: r["close_date"] or "")
    total = len(rows)
    if limit:
        rows = rows[:limit]
    return {"rows": rows, "total": total, "shown": len(rows),
            "register_entries": len(reg.get("entries") or []),
            "built_at": reg.get("at"),
            "note": ("every close with any missing field, oldest first — "
                     "each gap names who can fill it; the form below is a ruling, "
                     "journaled and reversible")}


def rate_card() -> list[dict]:
    """The packages the fill-in form offers — the rulebook's names and the
    configured terms. 'Custom' is always offered; nothing is inferred."""
    from config import PACKAGE_TERMS
    return [
        {"key": "growth_pro", "label": "Growth Pro", "term_months": PACKAGE_TERMS.get("growth pro", 6),
         "retainer": True},
        {"key": "scale_engine", "label": "Scale Engine", "term_months": PACKAGE_TERMS.get("scale engine", 6),
         "retainer": True},
        {"key": "scale_engine_split", "label": "Scale Engine (split pay)",
         "term_months": PACKAGE_TERMS.get("se_split", 6), "retainer": True},
        {"key": "scale_engine_multi_venue", "label": "Scale Engine (multi-venue)",
         "term_months": None, "retainer": True},
        {"key": "content_scale", "label": "Content Scale",
         "term_months": PACKAGE_TERMS.get("content scale", 6), "retainer": False},
        {"key": "dwy", "label": "Walk-In Engine (done with you)",
         "term_months": PACKAGE_TERMS.get("walk-in", 3), "retainer": False},
        {"key": "custom", "label": "Custom package", "term_months": None, "retainer": False},
    ]


def fill_in(key_or_person: str, body: dict, actor: str) -> dict:
    """THE FILL-IN FORM's submission = an owner/finance ruling (#171). It
    completes a register close — package, term, contract ex-GST, schedule
    rows (each with its account: business/personal), closer, setter, notes —
    journaled with who/when, reversible, recomputed immediately, and it
    emits the Piolo line so the tracker is fixed at source. A PERSONAL-
    account payment is recorded as received outside business accounts and
    is never business cash."""
    e = record(key_or_person) or record(_norm(key_or_person))
    person = (e or {}).get("person") or str(body.get("person") or key_or_person)
    client = str(body.get("client") or (e or {}).get("client") or "").strip()
    close_date = str(body.get("close_date") or (e or {}).get("close_date") or "")
    package = str(body.get("package") or "").strip()
    if package.lower() in ("custom", "custom package") or body.get("package_custom"):
        package = f"Custom — {body.get('package_custom') or 'as agreed'}".strip()
    try:
        term = int(body.get("term_months"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "the term in months is required (a whole number)"}
    try:
        cv = float(str(body.get("contract_ex_gst")).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return {"ok": False, "error": "the contract value ex-GST is required"}
    schedule = []
    for i, row in enumerate(body.get("schedule") or [], start=1):
        try:
            amt = float(str(row.get("amount")).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            return {"ok": False, "error": f"payment {i}: an amount is required"}
        acct = (row.get("account") or "").strip().lower() or None
        if acct and acct not in _ACCOUNTS:
            return {"ok": False, "error": f"payment {i}: account must be business or personal"}
        schedule.append({"n": i, "amount": amt, "gst": row.get("gst") or "inc",
                         "due": row.get("due") or None,
                         "received": row.get("received") or None,
                         "channel": row.get("channel") or None,
                         "account": acct if row.get("received") else None,
                         "evidence_id": (row.get("evidence_id") or None)})
    notes = str(body.get("notes") or "").strip()
    words = (f"{client or person} — {package}, {term} months, ${cv:,.2f} ex-GST"
             + (f"; closer {body.get('closer')}" if body.get("closer") else "")
             + (f"; setter {body.get('setter')}" if body.get("setter") else "")
             + (f". Notes: {notes}" if notes else "")
             + f" — filled in by {actor} on the deals-missing-details form")
    res = rule_deal_terms(person, client, close_date, package, term, cv, schedule, words,
                          actor=actor, closer=(body.get("closer") or None),
                          setter=(body.get("setter") or None),
                          payment_type=(body.get("payment_type") or None),
                          contact=(body.get("contact") or None))
    if not res.get("ok"):
        return res
    key = _norm(person)
    after = record(key) or {}
    personal = ((after.get("ruled_cash") or {}).get("outside_business_accounts") or [])
    if personal:
        # a Piolo item — the money must appear in Xero on a business account
        _raise_feed_item("personal_account_payment", "S2",
                         f"{client or person}: a payment went to a personal account",
                         f"{len(personal)} payment(s) recorded as received outside business "
                         f"accounts — not business cash until they appear in Xero (Piolo)")
    piolo = next((p for p in piolo_lines() if p["person"] == after.get("person")), None)
    return {"ok": True, "ruling": res["ruling"], "entry": after,
            "gaps_left": after.get("gaps") or gaps(after),
            "piolo_line": piolo, "personal_account_payments": len(personal)}


def revoke_deal_terms(key_or_person: str, actor: str) -> dict:
    """Reverse a fill-in / ruling: the register recomputes without it. The
    ruling stays in the journal (nothing is deleted from history)."""
    key = _norm(key_or_person.replace("cr:", ""))
    terms = deal_terms()
    if key not in terms:
        return {"ok": False, "error": "no ruling on file for that close"}
    prior = terms.pop(key)
    kv_store.put(K_TERMS, terms)
    journal("owner_ruling_revoked",
            f"deal terms ruling for {prior.get('person')} ({prior.get('client')}) "
            f"reversed by {actor}", actor, {"prior": prior})
    try:
        import close_detect
        close_detect.invalidate_now(f"ruling reversed: {prior.get('person')}")
    except Exception as e:  # noqa: BLE001
        logger.warning("register: invalidation after revoke failed: %s", e)
        build()
    return {"ok": True, "reversed": prior, "entry": record(key)}


def _raise_feed_item(kind: str, severity: str, title: str, detail: str) -> None:
    try:
        items = kv_store.get("feed:extra:close_register_fill") or []
        items = [i for i in items if i.get("title") != title]
        items.append({"kind": kind, "severity": severity, "title": title, "detail": detail,
                      "at": now_sydney().isoformat()})
        kv_store.put("feed:extra:close_register_fill", items[-20:])
    except Exception:  # noqa: BLE001
        pass
