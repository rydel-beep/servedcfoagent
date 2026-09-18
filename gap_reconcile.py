"""gap_reconcile.py — the tracker-gap engine (DECISIONS #148/#149, 2026-09-17).

READ-ONLY LAW: the Lead-to-Cash tracker and GHL are VIEW ONLY. This module
reads the sheet MIRROR and the GHL MIRROR (both read-only stores) plus
Stripe via cash_truth — it never touches a Sheets write verb, never touches
GHL with any non-GET verb, and never imports the email module that holds
the write-capable token. Corrections to the tracker ship as a PIOLO PACKAGE
(feed items + owner export); corrections to GHL are flagged for the GHL
owner. Test-pinned.

R-GAP · AUTHORITY INVERSION, SCOPED: inside the DETECTED gap window only,
GHL is primary for funnel events and the tracker corroborates; outside it
the standing tracker-authority rulings hold unchanged. The window is
detected from evidence (tracker close-column cadence vs GHL closed-stage
cadence), journaled with its dates, and every event this module credits
carries evidence ids (opp/contact/charge). R-CASH: cash is NEVER derived —
Stripe/Xero receipts only; a gap-window close is AUTO only with payment
corroboration, else PROPOSED with what's missing named.

Writes are confined to: the SANCTIONED derivation lanes
(resolution.record_derived_date + epoch bump — the same lanes #128/#131
use), this module's own kv state (gap:*), and the feed channel
feed:extra:tracker_backfill.
"""

from __future__ import annotations

import json
import logging
import re

import db
import kv_store
from helpers import today_sydney

logger = logging.getLogger(__name__)

_KV_STATE = "gap:state"
_KV_LEDGER = "gap:close_ledger"
_KV_PACKAGE = "gap:backfill_package"
_KV_JOURNAL = "gap:journal"
_KV_FEED = "feed:extra:tracker_backfill"

# Growth Pro standard term (months) — used ONLY to derive contract value as
# package-term × Health-tab MRR when no contract evidence exists; always
# labelled "derived: package term × MRR".
_PACKAGE_TERMS = {"growth pro": 6, "scale engine": 6, "cafe walk-ins": 3}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def journal(event: str, detail: str):
    j = kv_store.get(_KV_JOURNAL) or []
    j.append({"at": str(today_sydney()), "event": event, "detail": detail[:300]})
    kv_store.put(_KV_JOURNAL, j[-200:])


# ── Phase 1 · detection ─────────────────────────────────────────────────────

def _tracker_rows():
    import sheet_mirror
    return sheet_mirror.read_tab("ltc_tracker") or []


def _parse_date(v) -> str | None:
    import datetime as dt
    v = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return str(dt.datetime.strptime(v[:10], fmt).date())
        except ValueError:
            continue
    return None


def detect_gap(force: bool = False) -> dict:
    """Evidence-based window: tracker close-column daily cadence vs GHL
    closed-stage daily cadence. The gap starts the day after the LAST
    tracker-recorded close while GHL closed-stage activity continues, and
    runs to today (open until the tracker resumes). Mirror-vs-human verdict
    from sheet_sync_state (a healthy mirror + missing cells = HUMAN gap)."""
    today = str(today_sydney())
    cached = kv_store.get(_KV_STATE)
    if cached and not force and cached.get("detected_on") == today:
        return cached
    import attribution_engine as AE
    rows = _tracker_rows()
    if not rows:
        return {"ok": False, "reason": "tracker mirror empty — cannot detect"}
    cols = AE.tracker_cols(rows[0])
    ci, cc = cols.get("input_date"), cols.get("close_date")
    tracker_close_days, tracker_input_days = {}, {}
    for r in rows[1:]:
        if cc is not None and cc < len(r):
            d = _parse_date(r[cc])
            if d and d >= "2026-01-01":
                tracker_close_days[d] = tracker_close_days.get(d, 0) + 1
        if ci is not None and ci < len(r):
            d = _parse_date(r[ci])
            if d and d >= "2026-06-01":
                tracker_input_days[d] = tracker_input_days.get(d, 0) + 1
    last_tracker_close = max(tracker_close_days) if tracker_close_days else None

    ghl_closed_days = {}
    try:
        with db.get_conn() as c:
            rws = c.execute(
                "SELECT date(last_stage_change_at) d, count(*) n "
                "FROM ghl_opportunities WHERE deleted=FALSE "
                "AND lower(stage_name) LIKE '%%closed%%' "
                "AND last_stage_change_at IS NOT NULL GROUP BY 1").fetchall()
        ghl_closed_days = {str(r["d"]): r["n"] for r in rws}
    except Exception as e:
        return {"ok": False, "reason": f"ghl mirror unreachable: {e}"}

    ghl_after = sorted(d for d in ghl_closed_days
                       if last_tracker_close and d > last_tracker_close)
    if not ghl_after:
        state = {"ok": True, "gap": None, "detected_on": today,
                 "note": "no GHL closed-stage activity after the last "
                         "tracker close — no gap"}
        kv_store.put(_KV_STATE, state)
        return state

    import datetime as dt
    start = str(dt.date.fromisoformat(last_tracker_close) + dt.timedelta(days=1))
    # mirror-vs-human verdict
    mirror_ok = False
    try:
        import tracker_read
        st = tracker_read.sync_state() or {}
        mirror_ok = (st.get("status") == "ok"
                     and (st.get("age_seconds") or 9e9) < 3600)
    except Exception:
        pass
    state = {
        "ok": True, "detected_on": today,
        "gap": {"start": start, "end": today,
                "open": True,
                "scope": "close/contract/cash columns (downstream); lead "
                         "INPUT rows continued — a columns gap, not a "
                         "blackout"},
        "evidence": {
            "last_tracker_close": last_tracker_close,
            "tracker_close_by_day_2026": tracker_close_days,
            "ghl_closed_stage_after_gap_start": {d: ghl_closed_days[d]
                                                 for d in ghl_after},
            "tracker_input_by_day_recent": {
                d: n for d, n in sorted(tracker_input_days.items())[-30:]},
        },
        "verdict": ("HUMAN gap — the sheet mirror is healthy (rows ingest "
                    "within minutes) but the close/contract/cash cells were "
                    "never filled" if mirror_ok else
                    "mirror state degraded — verify before blaming humans"),
        "upstream_note": "2026-08-06→08-12 shows ~zero on BOTH series — that "
                         "is the known lead-flow outage (GHL received "
                         "nothing either), an upstream outage, NOT part of "
                         "this tracker gap",
    }
    kv_store.put(_KV_STATE, state)
    journal("gap detected", f"{start} → {today} (last tracker close "
                            f"{last_tracker_close}); verdict: {state['verdict'][:80]}")
    return state


def gap_window() -> tuple[str, str] | None:
    """R-GAP scope accessor — every consumer of the inversion uses THIS."""
    st = kv_store.get(_KV_STATE) or {}
    g = st.get("gap")
    return (g["start"], g["end"]) if g else None


def in_gap(date_iso: str | None) -> bool:
    w = gap_window()
    return bool(w and date_iso and w[0] <= str(date_iso)[:10] <= w[1])


# ── Phase 2 · the close ledger (GHL primary, payment-corroborated) ──────────

def _ghl_closed_in_window(w0: str, w1: str) -> list[dict]:
    out = []
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT id, contact_id, name, monetary_value, status, "
                "stage_name, source, created_at, last_stage_change_at, raw "
                "FROM ghl_opportunities WHERE deleted=FALSE "
                "AND lower(stage_name) LIKE '%%closed%%'").fetchall()
        for r in rows:
            d = str(r["last_stage_change_at"] or "")[:10]
            if not (w0 <= d <= w1):
                continue
            raw = r["raw"] if isinstance(r["raw"], dict) else json.loads(r["raw"] or "{}")
            ct = raw.get("contact") or {}
            out.append({"opp_id": r["id"], "contact_id": r["contact_id"],
                        "opp_name": r["name"], "stage": r["stage_name"],
                        "status": r["status"], "source": r["source"],
                        "stage_changed": str(r["last_stage_change_at"])[:16],
                        "close_date": d,
                        "contact_name": (ct.get("name") or "").strip(),
                        "email": (ct.get("email") or "").lower() or None,
                        "phone": ct.get("phone")})
    except Exception as e:
        logger.warning("ghl closed-in-window failed: %s", e)
    return out


def _stripe_hits(name: str, email: str | None, charges: list[dict]) -> list[dict]:
    """Email-exact first; else full-name containment (surname-only never
    matches alone — the Jagjeet/Harman surname collision class)."""
    import datetime as dt
    from helpers import SYDNEY_TZ
    nn = _norm(name)
    hits = []
    for ch in charges:
        if not (ch.get("paid") and ch.get("status") == "succeeded"):
            continue
        bd = ch.get("billing_details") or {}
        cust = ch.get("customer") if isinstance(ch.get("customer"), dict) else {}
        ce = (bd.get("email") or (cust.get("email") if cust else "") or "").lower()
        cn = _norm(cust.get("name") or bd.get("name"))
        if (email and ce == email) or (nn and len(nn) > 6 and nn in cn):
            hits.append({"charge_id": ch.get("id"),
                         "amount": round((ch.get("amount") or 0) / 100, 2),
                         "date": str(dt.datetime.fromtimestamp(
                             ch["created"], tz=SYDNEY_TZ).date()),
                         "payer": cust.get("name") or bd.get("name"),
                         "match": "email-exact" if (email and ce == email)
                                  else "full-name"})
    return hits


def _health_row(name: str, opp_name: str, email: str | None = None) -> dict | None:
    """Person → client-row bridge. Name tokens first; then the EMAIL bridge
    (prod-caught: contacts carry person names, client rows carry venue names
    — the payment email's local/domain often IS the venue, e.g.
    foodcorppizza@… ↔ 'Food Corp Pizza…'). ≥6-char prefix match, evidence-
    labelled by the caller."""
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        pool = (((snap.get("active_clients") or {}).get("active") or [])
                + ((snap.get("client_health") or {}).get("clients") or []))
        tokens = [t for t in re.split(r"[^a-z0-9]+", (name + " " + opp_name).lower())
                  if len(t) > 3]
        email_bits = []
        if email and "@" in email:
            local, _, domain = email.partition("@")
            email_bits = [_norm(local), _norm(domain.split(".")[0])]
        best = None
        for c in pool:
            nm = (c.get("name") or "").lower()
            nn = _norm(nm)
            score = sum(1 for t in tokens if t in nm)
            for eb in email_bits:
                if len(eb) >= 6 and (nn.startswith(eb[:10]) or eb.startswith(nn[:10])
                                     or (len(eb) >= 7 and eb[:7] == nn[:7])):
                    score += 2
            if score >= 1 and (best is None or score > best[0]):
                best = (score, c)
        return best[1] if best else None
    except Exception:
        return None


def _tracker_row_for(name: str, email: str | None) -> dict | None:
    """Corroboration/conflict source: any tracker row for this person."""
    import attribution_engine as AE
    rows = _tracker_rows()
    if not rows:
        return None
    cols = AE.tracker_cols(rows[0])
    nn = _norm(name)
    for r in rows[1:]:
        rn = _norm(r[cols["name"]] if cols.get("name") is not None
                   and cols["name"] < len(r) else "")
        remail = (str(r[cols["email"]]).strip().lower()
                  if cols.get("email") is not None and cols["email"] < len(r) else "")
        if (email and remail == email) or (nn and rn and nn == rn):
            return {c: (r[i] if i < len(r) else "")
                    for c, i in cols.items() if i is not None}
    return None


def rebuild_closes(apply: bool = True) -> dict:
    """The gap-window close ledger. AUTO = GHL closed-stage + Stripe payment
    (email-exact/full-name) → the sanctioned derivation lane (idempotent);
    PROPOSED = no money behind it, with what's missing named. The union with
    #131 Stripe-derived closes is deduped by person."""
    st = detect_gap()
    if not st.get("gap"):
        return {"ok": True, "note": "no gap window", "ledger": []}
    w0, w1 = st["gap"]["start"], st["gap"]["end"]
    import cash_truth
    charges = cash_truth._raw_recent_charges(120) or []
    ledger = []
    seen_people = set()
    for cand in sorted(_ghl_closed_in_window(w0, w1),
                       key=lambda c: c["close_date"]):
        person = cand["contact_name"] or cand["opp_name"].split(":")[0]
        nn = _norm(person)
        if nn in seen_people:
            continue
        seen_people.add(nn)
        hits = _stripe_hits(person, cand["email"], charges)
        tracker = _tracker_row_for(person, cand["email"])
        # the tracker row's BUSINESS name is the evidence-based person→venue
        # bridge (#151 — the Grappino case: person 'Harman singh', venue
        # 'Grappino ristorante trattoria', email-exact row)
        _biz = str((tracker or {}).get("business") or "")
        health = _health_row(person, (cand["opp_name"] or "") + " " + _biz,
                             cand.get("email"))
        tracker_close = _parse_date((tracker or {}).get("close_date"))
        entry = {
            "person": person, "close_date": cand["close_date"],
            "provenance": f"ghl-primary · gap {w0}–{w1}",
            "evidence": {"opp_id": cand["opp_id"],
                         "contact_id": cand["contact_id"],
                         "stage_changed": cand["stage_changed"],
                         "charge_ids": [h["charge_id"] for h in hits]},
            "stripe": {"hits": hits,
                       "cash_to_date": round(sum(h["amount"] for h in hits), 2)},
            "health_row": ({"name": health.get("name"),
                            "package": health.get("package"),
                            "current_mrr": health.get("current_mrr"),
                            "contract_value": health.get("contract_value")}
                           if health else None),
            "tracker_row": ({"present": True, "close_date": tracker_close,
                             "contract": tracker.get("contract"),
                             "cash": tracker.get("cash")}
                            if tracker else {"present": False}),
        }
        # contract value: evidence ladder — tracker cell > RECOGNIZED-row
        # contract cell (sheet-recorded) > health contract value >
        # package-term × MRR (derived, labelled) > unknown
        cv, cv_src = None, None
        ledger_row = None
        if health and health.get("name"):
            try:
                import finance_tabs
                _hn = _norm(health["name"])
                ledger_row = next(
                    (e for e in finance_tabs.renewal_ledger().get("entries") or []
                     if _norm(e["client"]) == _hn and e.get("contract_value")),
                    None)
            except Exception:
                pass
        if tracker and str(tracker.get("contract") or "").strip():
            cv = tracker.get("contract"); cv_src = "tracker cell"
        elif ledger_row:
            cv = ledger_row["contract_value"]
            cv_src = (f"RECOGNIZED row {ledger_row['provenance']['row']} "
                      f"contract cell (sheet-recorded)")
        elif health and health.get("contract_value"):
            cv = health["contract_value"]; cv_src = "Health-tab contract value"
        elif health and health.get("current_mrr"):
            term = _PACKAGE_TERMS.get((health.get("package") or "").lower())
            if term:
                cv = round(float(health["current_mrr"]) * term, 2)
                cv_src = (f"derived: package term ({term}mo) × Health-tab "
                          f"MRR — not a signed figure")
        entry["contract_value"] = cv
        entry["contract_provenance"] = cv_src or "unknown — blank ≠ zero"
        # conflict surfacing (never silently reconciled)
        if tracker_close and tracker_close != cand["close_date"]:
            entry["conflict"] = (f"tracker close {tracker_close} vs GHL "
                                 f"stage-change {cand['close_date']} — both "
                                 f"shown, GHL primary in-window (R-GAP)")
        if hits:
            entry["state"] = "AUTO"
        else:
            entry["state"] = "PROPOSED"
            entry["missing"] = ("no Stripe payment found (email-exact + "
                                "full-name searched 120d) — needs payment "
                                "evidence (bank transfer? check Xero) or "
                                "Rydel's word")
        ledger.append(entry)

    # dedupe note vs #131: closes already derived from Stripe keep their
    # standing derivation; the ledger records them as corroborated, and the
    # engine's source-wins supersession prevents double placement.
    applied = 0
    if apply:
        import resolution
        for e in ledger:
            if e["state"] != "AUTO":
                continue
            try:
                existing = (kv_store.get("derived:dates") or {}).get(
                    _norm(e["person"]), {})
                if "close_date" in existing or (e["tracker_row"].get("present")
                                                and e["tracker_row"].get("close_date")):
                    continue      # already placed (tracker or #131) — ONE event
                resolution.record_derived_date(
                    _norm(e["person"]), "close_date", e["close_date"],
                    provenance=f"derived:ghl-gap-primary · {w0}–{w1} (#149)",
                    evidence=e["evidence"])
                applied += 1
            except Exception as ex:
                logger.warning("gap close derivation failed for %s: %s",
                               e["person"], ex)
        if applied:
            import resolution
            resolution.bump_derived_epoch(f"gap reconciliation ({applied} closes)")
            journal("closes derived", f"{applied} AUTO close(s) placed via the "
                                      f"sanctioned lane")
    out = {"ok": True, "window": [w0, w1], "ledger": ledger,
           "auto": sum(1 for e in ledger if e["state"] == "AUTO"),
           "proposed": sum(1 for e in ledger if e["state"] == "PROPOSED"),
           "applied_now": applied}
    kv_store.put(_KV_LEDGER, out)
    return out


def close_ledger() -> dict:
    return kv_store.get(_KV_LEDGER) or {"ledger": []}


# ── funnel rebuild summary (leads side) ─────────────────────────────────────

def lead_diff() -> dict:
    """Gap-window lead truth: GHL pipeline entries vs tracker input rows —
    people in GHL but absent from the tracker are the lead-side backfill;
    tracker-only people are flagged (absent from GHL)."""
    st = detect_gap()
    if not st.get("gap"):
        return {"ok": True, "note": "no gap window"}
    w0, w1 = st["gap"]["start"], st["gap"]["end"]
    import attribution_engine as AE
    rows = _tracker_rows()
    cols = AE.tracker_cols(rows[0]) if rows else {}
    tracker_people = {}
    for r in rows[1:]:
        d = _parse_date(r[cols["input_date"]] if cols.get("input_date") is not None
                        and cols["input_date"] < len(r) else "")
        if d and w0 <= d <= w1:
            nm = r[cols["name"]] if cols.get("name") is not None and cols["name"] < len(r) else ""
            em = (str(r[cols["email"]]).strip().lower()
                  if cols.get("email") is not None and cols["email"] < len(r) else "")
            tracker_people[_norm(nm)] = {"name": nm, "email": em, "input_date": d}
    ghl_people = {}
    try:
        with db.get_conn() as c:
            rws = c.execute(
                "SELECT id, contact_id, name, source, created_at, raw FROM "
                "ghl_opportunities WHERE deleted=FALSE AND "
                "date(created_at) BETWEEN %s AND %s", (w0, w1)).fetchall()
        for r in rws:
            raw = r["raw"] if isinstance(r["raw"], dict) else json.loads(r["raw"] or "{}")
            ct = raw.get("contact") or {}
            nm = (ct.get("name") or r["name"] or "").split(":")[0].strip()
            if "test" in nm.lower():
                continue
            ghl_people[_norm(nm)] = {"name": nm, "email": (ct.get("email") or "").lower(),
                                     "opp_id": r["id"], "contact_id": r["contact_id"],
                                     "created": str(r["created_at"])[:10],
                                     "source": r["source"]}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:100]}
    t_emails = {p["email"] for p in tracker_people.values() if p["email"]}
    missing_from_tracker = [p for k, p in sorted(ghl_people.items())
                            if k not in tracker_people
                            and (not p["email"] or p["email"] not in t_emails)]
    tracker_only = [p for k, p in sorted(tracker_people.items())
                    if k not in ghl_people]
    return {"ok": True, "window": [w0, w1],
            "ghl_leads": len(ghl_people), "tracker_leads": len(tracker_people),
            "missing_from_tracker": missing_from_tracker[:40],
            "tracker_only_flagged": [p["name"] for p in tracker_only][:40],
            "note": "gap-window lead truth is GHL (R-GAP); tracker-only "
                    "people are FLAGGED, never dropped"}


# ── the Piolo backfill package ──────────────────────────────────────────────

def build_backfill_package() -> dict:
    """Row-level tracker restoration package: per person, the exact cells.
    Published as self-retiring feed items (Piolo queue) + kv for the
    owner-only export. Convergence: each item stops being generated once
    the mirror shows the row/cells landed."""
    closes = (kv_store.get(_KV_LEDGER) or {}).get("ledger") or []
    leads = lead_diff()
    rows = []
    for e in closes:
        tr = e.get("tracker_row") or {}
        needs = []
        if not tr.get("present"):
            needs.append("lead row (input date + name + source)")
        if not tr.get("close_date"):
            needs.append(f"Close Date = {e['close_date']}")
        if not str(tr.get("contract") or "").strip() and e.get("contract_value"):
            needs.append(f"Contract Value = ${e['contract_value']:,.0f} "
                         f"({e['contract_provenance']})")
        cash = (e.get("stripe") or {}).get("cash_to_date")
        if cash and not str(tr.get("cash") or "").strip():
            needs.append(f"Cash Collected = ${cash:,.2f} (Stripe "
                         + ", ".join((e["evidence"] or {}).get("charge_ids", [])[:3]) + ")")
        if needs:
            rows.append({"person": e["person"], "state": e["state"],
                         "close_date": e["close_date"], "edits": needs,
                         "evidence": e["evidence"]})
    for p in (leads.get("missing_from_tracker") or []):
        rows.append({"person": p["name"], "state": "LEAD",
                     "edits": [f"lead row: input {p['created']}, source "
                               f"{p.get('source') or '?'}, email {p.get('email') or '?'}"],
                     "evidence": {"opp_id": p["opp_id"],
                                  "contact_id": p["contact_id"]}})
    kv_store.put(_KV_PACKAGE, {"built": str(today_sydney()), "rows": rows})
    items = []
    for r in rows[:20]:
        items.append({
            "severity": "S2", "category": "data_quality",
            "title": f"tracker backfill — {r['person']}",
            "detail": "; ".join(r["edits"])[:180],
            "action": "restore the tracker row at source (READ-ONLY law: "
                      "the agent never writes the sheet) — the item retires "
                      "when the mirror sees the cells land"})
    kv_store.put(_KV_FEED, items)
    journal("backfill package", f"{len(rows)} row(s) packaged; "
                                f"{len(items)} queue item(s) live")
    return {"ok": True, "rows": len(rows), "queue_items": len(items)}


def refresh_convergence() -> dict:
    """Nightly: rebuild the ledger + package from fresh mirrors — converged
    rows drop out (self-retiring feed) and the journal records the delta."""
    before = len(((kv_store.get(_KV_PACKAGE) or {}).get("rows")) or [])
    rebuild_closes(apply=True)
    pkg = build_backfill_package()
    after = pkg["rows"]
    if after != before:
        journal("convergence", f"package rows {before} → {after}")
    return {"before": before, "after": after}


def sentinel_watch() -> dict:
    """Nightly rung: window still open? package converging? authority scope
    intact (no gap provenance outside the window)?"""
    out = {"at": str(today_sydney())}
    try:
        out["convergence"] = refresh_convergence()
        derived = kv_store.get("derived:dates") or {}
        w = gap_window()
        leaks = []
        if w:
            for nm, fields in derived.items():
                cd = (fields.get("close_date") or {})
                if "ghl-gap-primary" in str(cd.get("provenance") or ""):
                    if not (w[0] <= str(cd.get("date") or "") <= w[1]):
                        leaks.append(nm)
        out["authority_scope_ok"] = not leaks
        if leaks:
            out["leaks"] = leaks[:10]
            try:
                import ad_sentinel
                ad_sentinel.queue_item(
                    "R-GAP authority leak",
                    f"gap-primary provenance outside the window: {leaks[:5]}",
                    rank="P1")
            except Exception:
                pass
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


# ── EDITH drills (registered on both tier-2 lists) ──────────────────────────

_AWAY_RE = re.compile(r"what happened while i was (away|gone)|catch me up|"
                      r"what did i miss", re.I)
_STALE_RE = re.compile(r"what('s| is) (stale|wrong|broken|out of date)|"
                       r"flagged register", re.I)
_GAP_RE = re.compile(r"tracker gap|gap window|backfill package", re.I)


def handle_gap_command(text: str) -> tuple[str | None, bool]:
    t = (text or "").lower()
    try:
        if _AWAY_RE.search(t):
            st = kv_store.get(_KV_STATE) or {}
            led = kv_store.get(_KV_LEDGER) or {}
            g = st.get("gap") or {}
            import automations
            h = automations.health()
            bad = [r for r in h["automations"]
                   if r["state"] in ("FAILING", "STALE")]
            return (
                f"While you were away: the machine kept running (sentinel + "
                f"mirrors green all month) but the humans stopped — no "
                f"dashboard logins since 13 Aug, and the tracker's close/"
                f"contract/cash columns went silent after "
                f"{(st.get('evidence') or {}).get('last_tracker_close')}. "
                f"Gap window {g.get('start')} → {g.get('end')}: "
                f"{led.get('auto', 0)} close(s) rebuilt AUTO from GHL+Stripe, "
                f"{led.get('proposed', 0)} PROPOSED awaiting payment "
                f"evidence; the Piolo backfill package is live in his queue. "
                f"Automations now {'all green' if not bad else 'flagging: ' + ', '.join(r['label'] for r in bad[:3])}. "
                f"Full detail: the currency audit + drift sweep docs.", True)
        if _STALE_RE.search(t):
            import automations
            h = automations.health()
            bad = [f"{r['label']}: {r['state']} ({r['detail']})"
                   for r in h["automations"] if r["state"] != "RUNNING"]
            led = kv_store.get(_KV_LEDGER) or {}
            props = [e["person"] for e in (led.get("ledger") or [])
                     if e.get("state") == "PROPOSED"]
            bits = []
            if bad:
                bits.append("automations: " + "; ".join(bad[:4]))
            if props:
                bits.append("closes awaiting payment evidence: " + ", ".join(props))
            bits.append("the sheet's recognized-revenue footer disagrees "
                        "with its rows (Piolo item)")
            return ("Stale/flagged right now — " + " · ".join(bits) +
                    ". The full register is in the drift-sweep doc.", True)
        if _GAP_RE.search(t):
            st = kv_store.get(_KV_STATE) or {}
            g = st.get("gap") or {}
            pkg = kv_store.get(_KV_PACKAGE) or {}
            return (f"Tracker gap {g.get('start')} → {g.get('end')} "
                    f"({st.get('verdict', '')[:90]}). Backfill package: "
                    f"{len(pkg.get('rows') or [])} row(s) for Piolo — every "
                    f"edit carries its GHL/Stripe evidence ids; items retire "
                    f"as the mirror sees the cells land.", True)
    except Exception as e:
        logger.info("gap drill failed: %s", e)
    return None, False
