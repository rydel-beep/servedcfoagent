"""
resolution.py
-------------
THE RESOLUTION ENGINE (FULL_STACK_INTEGRITY_REPORT, Rydel-confirmed 2026-08-06).
Three classes of fix, one hard line:

  AUTO-FIX (A1-A5) — derives, NEVER invents; applies silently; EVERY application
    logged to kv integrity:autofix_log. A1 normalization before matching ·
    A2 exact-ad-id re-key on renames (lives in attribution_join) · A3 reuse of a
    Rydel-confirmed alias (new aliases still ask) · A4 ↤N activity-clock
    annotations (lives in attribution_engine) · A5 self-retiring hygiene flags
    (every kv flag list is overwritten per compute — fixed at source = gone).
  PROPOSED-FIX (P1-P2) — evidence cards, one-tap/one-reply confirm, NOTHING
    applied until a human acts. P1 blank Close Date with a GHL/Stripe candidate
    date · P2 high-confidence tracker↔GHL name link where the email join failed.
  HUMAN-FIX (H1-H2) — routed with a named owner: no-candidate blanks → Piolo's
    queue; ambiguous identities stay quarantined in __ambiguous__, never assigned.

THE HARD LINE: no rule here ever WRITES to the tracker, GHL, or Stripe. Cards
only PROPOSE what a human types into the source system; the engine changes only
how it reads and labels. Tracker stays the single write-point, humans the writers.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KV_AUTOFIX_LOG = "integrity:autofix_log"     # capped list of {rule, detail, ts}
_KV_PROPOSED = "integrity:proposed_fixes"     # current P1/P2 cards (rebuilt per refresh)
_KV_DERIVED_EPOCH = "derived:epoch"           # monotone counter — bumped on EVERY
                                              # derivation-class write (F6)


def derived_epoch() -> int:
    """The derivation epoch. Folded into the engine cache key + rollup records so
    a derivation write INVALIDATES every cached board/roster instantly — a
    freshness label on post-write stale data is a lie (audit F6)."""
    try:
        import kv_store
        return int(kv_store.get(_KV_DERIVED_EPOCH) or 0)
    except Exception:
        return 0


def bump_derived_epoch(reason: str) -> int:
    """Every write that changes what the engine derives calls this: derivations,
    supersessions, show-verification changes, spine events, reached evidence.
    Global by design (correctness first — a scoped key map can come later)."""
    try:
        import kv_store
        n = int(kv_store.get(_KV_DERIVED_EPOCH) or 0) + 1
        kv_store.put(_KV_DERIVED_EPOCH, n)
        logger.info("derived epoch → %s (%s)", n, reason)
        return n
    except Exception as e:
        logger.warning("derived epoch bump failed: %s", e)
        return 0

DOCTRINE = ("AUTO-FIX derives, never invents (A1 normalization, A2 id re-key, A3 "
            "confirmed-alias reuse, A4 clock annotations, A5 self-retiring flags — all "
            "logged); PROPOSED-FIX shows evidence and waits for a human; HUMAN-FIX is "
            "routed to a named owner. Nothing ever writes to the tracker, GHL, or Stripe.")


# F2 (extreme audit): THE EVIDENCE HORIZON. The 200-cap rolling log floods in
# ~2 days of sweep traffic — but derivation provenance, ruling conversions
# (charge ids), supersessions, and verifications ARE the trust chain and must
# not age out. Evidence-class entries are duplicated into a durable partition
# (`resolution:journal`, cap 1000 ≫ the total derivation population, which is
# bounded by the lead universe — durable without unbounded growth). The rolling
# log stays the recent-activity view; the partition is the evidence archive.
_KV_EVIDENCE_JOURNAL = "resolution:journal"
_EVIDENCE_CAP = 1000
EVIDENCE_RULE_PREFIXES = (
    "date derived", "date superseded", "date rederived", "ruling-conversion",
    "T2 spine derivation", "show verified", "reached derivation",
    "A3 alias learned", "heal",
)


def _is_evidence_rule(rule: str) -> bool:
    r = (rule or "").lower()
    return any(r.startswith(p.lower()) for p in EVIDENCE_RULE_PREFIXES)


def evidence_journal() -> list[dict]:
    """The durable evidence stream — survives any amount of sweep noise."""
    try:
        import kv_store
        return kv_store.get(_KV_EVIDENCE_JOURNAL) or []
    except Exception:
        return []


def log_autofix(rule: str, detail: str) -> None:
    """Every silent application is auditable — the log IS the trust.
    Evidence-class rules ALSO land in the durable partition (F2)."""
    try:
        import kv_store
        from helpers import today_sydney
        entry = {"rule": rule, "detail": detail[:160], "ts": str(today_sydney())}
        lg = kv_store.get(_KV_AUTOFIX_LOG) or []
        lg.append(entry)
        kv_store.put(_KV_AUTOFIX_LOG, lg[-200:])
        if _is_evidence_rule(rule):
            ej = kv_store.get(_KV_EVIDENCE_JOURNAL) or []
            ej.append(entry)
            kv_store.put(_KV_EVIDENCE_JOURNAL, ej[-_EVIDENCE_CAP:])
    except Exception as e:
        logger.info("autofix log failed: %s", e)


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def _ghl_won_dates() -> dict:
    """contact email → last_status_change date for won opportunities (mirror, zero API)."""
    import db
    out = {}
    if not db.db_configured():
        return out
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT o.contact_id, o.last_status_change_at, c.email, c.name "
                "FROM ghl_opportunities o LEFT JOIN attr_contacts c ON c.id = o.contact_id "
                "WHERE o.status = 'won' AND o.deleted = FALSE").fetchall()
        from helpers import sydney_day
        for r in rows:
            if r.get("last_status_change_at"):
                d = sydney_day(r["last_status_change_at"])   # F8: Sydney day, not UTC
                if r.get("email"):
                    out[_norm(r["email"])] = {"date": d, "via": "email"}
                if r.get("name"):
                    out.setdefault(_norm(r["name"]), {"date": d, "via": "name"})
    except Exception as e:
        logger.info("ghl won dates read failed: %s", e)
    return out


def _stripe_first_payment_dates(days: int = 365) -> dict:
    """payer/email norm → {date, charge_id, via} for the EARLIEST charge (read-only
    key; degrades to empty). `via` records WHICH identity matched — 'email' is
    ID-exact (payment-class AUTO under DECISIONS #131); 'name' is a label match
    and stays PROPOSED."""
    out = {}
    try:
        from cash_truth import _recent_charges
        for c in (_recent_charges(days) or []):
            for k, via in ((_norm(c.get("customer_name") or c.get("name")), "name"),
                           (_norm(c.get("_email")), "email")):
                if not k:
                    continue
                cur = out.get(k)
                if cur is None or c["date"] < cur["date"] or \
                        (c["date"] == cur["date"] and via == "email" and cur["via"] != "email"):
                    out[k] = {"date": c["date"], "charge_id": c.get("id"), "via": via}
    except Exception as e:
        logger.info("stripe first-payment read failed: %s", e)
    return out


def propose_fixes() -> list[dict]:
    """Build the current P1/P2 cards. Read-only; rebuilt per refresh (A5: a card whose
    underlying blank got filled at source simply stops being generated)."""
    import close_integrity as CI
    cards: list[dict] = []
    try:
        won = CI._tracker_won_rows()
    except Exception as e:
        logger.info("propose_fixes tracker read failed: %s", e)
        return []
    blanks = [t for t in won if t["close_date"] is None]
    if not blanks:
        return []

    # DUPLICATE-DATED GUARD at the CARD layer (triple-sweep SEV3, 2026-08-10):
    # the #131 auto-converter refuses a blank won row whose identity already has
    # a DATED won row (both keys), but the card generator kept proposing a
    # candidate for it — acting on Nirosha's card would have dated her duplicate
    # blank row and recreated the double-count. Same guard, both keys; the
    # duplicate surfaces as its own honest card kind instead (excluded ≠ deleted).
    dated_idents: set = set()
    for t in won:
        if t.get("close_date") is not None:
            for ident in (_norm(t.get("email")), _norm(t["name"])):
                if ident:
                    dated_idents.add(ident)

    ghl_dates = _ghl_won_dates()
    stripe_dates = _stripe_first_payment_dates()
    # F9: the guard runs AFTER the fresh pull — checking a previous run's marker
    # before pulling let the run in which the partial actually happened build
    # cards from the fragment (review finding 2). A partial charge list can
    # offer a WRONG "first payment" candidate — keep the persisted cards.
    try:
        import cash_truth
        if cash_truth.stripe_pull_partial():
            logger.warning("propose_fixes: stripe pull partial (F9) — keeping "
                           "existing cards, no rebuild from a fragment")
            return (latest_proposed() or {}).get("cards") or []
    except Exception:
        pass
    derived = derived_dates()

    for t in blanks:
        # A1: normalize before matching (tracker emails arrive pre-normed; re-norm is safe)
        name_n, email_n = _norm(t["name"]), _norm(t.get("email"))
        # DECISIONS #131: a close date already AUTO-derived under the payment-class
        # ruling no longer needs a card — the queue shows only what still needs a
        # human. The Piolo source-fill item persists via close_integrity; the
        # derivation is visible in the rail's Derived section with its chip.
        if (derived.get(name_n) or {}).get("close_date"):
            continue
        if (email_n and email_n in dated_idents) or name_n in dated_idents:
            cards.append({
                "kind": "duplicate_blank_won_row", "name": t["name"],
                "field": "Close Date", "contract": t.get("contract"),
                "instruction": (f"{t['name']} already has a DATED won row — this "
                                f"blank row is a duplicate. DELETE the duplicate "
                                f"row in the tracker (do NOT fill a date; that "
                                f"would double-count the deal)."),
                "id": f"pfix:dup_blank:{name_n}"})
            continue
        candidates = []
        g = ghl_dates.get(email_n) or ghl_dates.get(name_n)
        if g:
            candidates.append({"date": str(g["date"]),
                               "source": f"GHL closed-won stage move (matched by {g['via']})"})
        s = stripe_dates.get(email_n) or stripe_dates.get(name_n)
        if s:
            candidates.append({"date": str(s["date"]),
                               "source": f"Stripe first payment (matched by {s['via']})",
                               "charge_id": s.get("charge_id")})
        if candidates:
            cards.append({
                "kind": "P1_close_date_candidate", "name": t["name"],
                "field": "Close Date", "contract": t.get("contract"),
                "candidates": candidates,
                "instruction": (f"If right, type {candidates[0]['date']} into "
                                f"{t['name']}'s Close Date cell on the tracker — "
                                f"I never write it myself."),
                "id": f"pfix:close_date:{name_n}"})
        else:
            # H1: no candidate anywhere → stays in Piolo's queue (already routed
            # by close_integrity); named here only so the census is complete.
            cards.append({
                "kind": "H1_no_candidate", "name": t["name"], "field": "Close Date",
                "contract": t.get("contract"),
                "instruction": "No GHL/Stripe date candidate — needs the human who closed it.",
                "id": f"hfix:close_date:{name_n}"})

    # P2: tracker won rows whose email matched nothing in GHL but whose NAME matches
    # exactly one contact → propose the link (never auto-join).
    try:
        import db
        if db.db_configured():
            with db.get_conn() as conn:
                contacts = conn.execute(
                    "SELECT id, email, name FROM attr_contacts WHERE name IS NOT NULL").fetchall()
            by_name: dict[str, list] = {}
            for c in contacts:
                by_name.setdefault(_norm(c["name"]), []).append(c)
            emails = {_norm(c["email"]) for c in contacts if c.get("email")}
            for t in won:
                if t.get("email") and _norm(t["email"]) in emails:
                    continue
                hits = by_name.get(_norm(t["name"])) or []
                if len(hits) == 1:
                    cards.append({
                        "kind": "P2_name_link", "name": t["name"],
                        "candidates": [{"contact_id": hits[0]["id"],
                                        "source": "exact unique name match in GHL"}],
                        "instruction": ("Confirm in chat ('yes, link them') and the join "
                                        "uses it; the sources themselves stay untouched."),
                        "id": f"pfix:name_link:{_norm(t['name'])}"})
    except Exception as e:
        logger.info("propose_fixes P2 failed: %s", e)

    try:
        import kv_store
        from helpers import today_sydney
        kv_store.put(_KV_PROPOSED, {"as_of": str(today_sydney()), "cards": cards[:60]})
    except Exception as e:
        logger.info("proposed_fixes persist failed: %s", e)
    return cards


def latest_proposed() -> dict:
    import kv_store
    return kv_store.get(_KV_PROPOSED) or {}


# ── THE DATE RESOLUTION ENGINE (FUNNEL_COMPLETION, DECISIONS #128) ───────────
# One resolver per event type, evidence ladders in strict order, first UNAMBIGUOUS
# ID-exact hit wins. TRACKER IS THE AUTHORITY: a derived date makes an event
# windowable NOW, labelled; the queue item persists; a later source fill
# SUPERSEDES (journaled) and any disagreement SURFACES.
#
# ENCODED CONVENTIONS (defaults, veto-able — logged to DECISIONS #128):
#   close  = the signed/verbal deal-won event → payment/stage dates are evidence
#            NEAR the close → Stripe/GHL-stage rungs are PROPOSED, never AUTO.
#            (The Xero invoices/payments rung is a CAPABILITY GAP: current scopes
#            are report-reads only — reported, not built blind.)
#   input  = the lead's arrival → GHL contact created date, ID-exact → AUTO.
#   set    = the date the appointment was BOOKED (setter action) → AUTO on a
#            single ID-exact appointment; multiple candidates → PROPOSED.
#   show   = the appointment's SCHEDULED datetime, requiring show evidence
#            (status in the kept vocabulary) → AUTO; ambiguous status → PROPOSED.

_KV_DERIVED = "derived:dates"     # {name_norm: {field: {date, provenance, evidence, ts}}}

_APPT_KEPT_STATUSES = {"confirmed", "showed", "completed"}


def derived_dates() -> dict:
    import kv_store
    return kv_store.get(_KV_DERIVED) or {}


def _put_derived(store: dict) -> None:
    import kv_store
    kv_store.put(_KV_DERIVED, store)


def record_derived_date(name_norm: str, field: str, date_iso: str, provenance: str,
                        evidence: dict) -> bool:
    """Journaled, reversible, evidence-linked — the I12 contract. REJECTS a
    derivation without evidence links (schema-enforced, adversarially tested)."""
    if not (name_norm and field in ("input_date", "close_date", "set_date", "show_date")
            and date_iso and provenance and isinstance(evidence, dict) and evidence):
        logger.warning("derivation rejected — evidence/schema incomplete: %s %s", name_norm, field)
        return False
    from helpers import today_sydney
    store = derived_dates()
    cur = store.get(name_norm, {}).get(field)
    if cur and cur.get("date") == date_iso:
        return True   # idempotent — no re-derivation churn
    # F10 — JOURNAL-FIRST ordering (drill B14): a crash between the two writes
    # must leave a journaled-but-unapplied entry (detectable, re-runnable), never
    # an applied-but-unjournaled derivation (invisible forever). A duplicate
    # journal line on retry is noise; a silent derivation is a trust hole.
    log_autofix(f"date derived ({field})",
                f"{name_norm}: {field} = {date_iso} via {provenance} "
                f"(evidence {str(evidence)[:80]})")
    store.setdefault(name_norm, {})[field] = {
        "date": date_iso, "provenance": provenance, "evidence": evidence,
        "ts": str(today_sydney())}
    _put_derived(store)
    bump_derived_epoch(f"derived {field} for {name_norm}")   # F6: caches invalidate NOW
    return True


def supersede_derived(name_norm: str, field: str, source_date_iso: str) -> dict | None:
    """The source landed: it WINS. The derivation is retired (journaled, reversible
    via the journal); a source≠derived disagreement SURFACES, never silently resolves."""
    store = derived_dates()
    cur = (store.get(name_norm) or {}).get(field)
    if not cur:
        return None
    agree = cur.get("date") == source_date_iso
    # F10: journal-first — see record_derived_date
    log_autofix(f"date superseded ({field})",
                f"{name_norm}: source {source_date_iso} supersedes derived "
                f"{cur.get('date')} ({cur.get('provenance')}) — "
                f"{'agrees' if agree else 'DISAGREES'}")
    del store[name_norm][field]
    if not store[name_norm]:
        del store[name_norm]
    _put_derived(store)
    bump_derived_epoch(f"superseded {field} for {name_norm}")   # F6
    if not agree:
        try:
            import kv_store
            flags = kv_store.get("ads_truth:flags") or []
            flags.append({"metric": "ads_truth",
                          "reason": (f"date disagreement on {name_norm} {field}: source "
                                     f"{source_date_iso} vs derived {cur.get('date')} "
                                     f"({cur.get('provenance')}) — source now rules; verify")})
            kv_store.put("ads_truth:flags", flags[-60:])
        except Exception:
            pass
    return {"superseded": cur, "agrees": agree}


def resolve_dates() -> dict:
    """The dateless pass: AUTO rungs only (input ← GHL contact created; set/show are
    the event sweep's job in ads_truth). Close dates stay PROPOSED per the encoded
    convention (the P1 cards ARE that lane). Idempotent; supersession handled."""
    import close_integrity as CI
    out = {"input_auto": 0, "superseded": 0, "close_proposed_existing": 0}
    try:
        won = CI._tracker_won_rows()
    except Exception as e:
        return {"skipped": f"tracker unavailable: {e}"}
    contacts_by_norm = {}
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("name"):
                contacts_by_norm.setdefault(_norm(c["name"]), c)
    except Exception:
        return {"skipped": "contacts unavailable"}

    store = derived_dates()
    for t in won:
        nm = _norm(t["name"])
        # supersession: the source filled a date we had derived
        for field, src in (("input_date", t.get("input_date")),
                           ("close_date", t.get("close_date"))):
            if src and (store.get(nm) or {}).get(field):
                supersede_derived(nm, field, str(src))
                out["superseded"] += 1
        # AUTO: input date ← GHL contact created (ID-exact, single, unambiguous)
        if t.get("input_date") is None:
            c = contacts_by_norm.get(nm)
            da = c and c.get("date_added")
            if c and da:
                from helpers import sydney_day
                date_iso = str(sydney_day(da))               # F8: Sydney day, not UTC
                if record_derived_date(nm, "input_date", date_iso,
                                       "derived:ghl-contact-created",
                                       {"contact_id": c["id"]}):
                    out["input_auto"] += 1
    # DECISIONS #131: the payment-class AUTO rung runs in the same nightly pass —
    # a future dateless close with ID-exact Stripe evidence converts automatically.
    try:
        out["payment_class_ruling"] = apply_payment_class_ruling()
    except Exception as e:
        out["payment_class_ruling"] = {"error": str(e)[:80]}
    cards = (latest_proposed() or {}).get("cards") or []
    out["close_proposed_existing"] = sum(1 for c in cards
                                         if c.get("kind") == "P1_close_date_candidate")
    return out


def apply_payment_class_ruling() -> dict:
    """DECISIONS #131 — dateless-close auto-derivation (Rydel's ruling, stated
    twice; veto-able). PAYMENT-CLASS evidence at ID-exact AUTO-derives the Close
    Date where the tracker cell is BLANK:
      · Stripe first payment matched by EMAIL → AUTO (the email is the ID);
        journaled 'ruling-conversion DECISIONS #131', charge id as evidence.
      · Stripe matched by name only → stays PROPOSED (a label match, not an ID).
      · GHL payment/transaction objects → 401 scope-locked at probe (2026-08-08);
        no rung built. Xero → scopes not landed; same.
      · GHL STAGE timestamps → PROPOSED forever (the lane demonstrably lags —
        a stage move is when someone dragged a card, not when the deal closed).
    Filled tracker dates always win (this runs over blanks only); supersession +
    disagreement surfacing unchanged; the Piolo source-fill item persists.
    IDEMPOTENT: an already-derived close converts nothing twice (record_derived_
    date returns True without journal churn on an identical re-derivation, and we
    skip up front). One action-feed notice per batch that actually converted."""
    import close_integrity as CI
    out = {"converted": [], "skipped_name_only": [], "already_derived": 0,
           "cash_placed": 0.0}
    # F9: a PARTIAL Stripe pull can mis-rank "first payment" — the ruling pass
    # SKIPS the run loudly rather than derive from an incomplete charge list.
    try:
        import cash_truth
        partial = cash_truth.stripe_pull_partial()
        if partial:
            try:
                import kv_store
                flags = kv_store.get("ads_truth:flags") or []
                flags.append({"metric": "ads_truth_action",
                              "reason": (f"#131 ruling pass SKIPPED: Stripe pull partial "
                                         f"({partial.get('error')}) — deriving from an "
                                         f"incomplete charge list is refused (F9)")})
                kv_store.put("ads_truth:flags", flags[-60:])
            except Exception:
                pass
            return {"skipped": f"stripe pull partial (F9): {partial.get('error')}"}
    except Exception:
        pass
    try:
        won = CI._tracker_won_rows()
    except Exception as e:
        return {"skipped": f"tracker unavailable: {e}"}
    blanks = [t for t in won if t["close_date"] is None]
    if not blanks:
        return out
    # a blank whose identity ALSO has a DATED won row is a DUPLICATE row, not a
    # dateless close — dedupe's domain (the deal already counts once; deriving a
    # date here would double-place it). Found live 2026-08-08: Nirosha. BOTH
    # identity keys go into the set — her dated and blank rows differ on which
    # of email/name they carry.
    dated_idents: set = set()
    for t in won:
        if t["close_date"] is not None:
            for ident in (_norm(t.get("email")), _norm(t["name"])):
                if ident:
                    dated_idents.add(ident)
    out["skipped_duplicate_dated"] = []
    stripe_dates = _stripe_first_payment_dates()
    # F9 (review finding 2): re-check AFTER the fresh pull — the run in which
    # the partial happens must itself refuse to derive from the fragment.
    try:
        import cash_truth
        partial2 = cash_truth.stripe_pull_partial()
        if partial2:
            try:
                import kv_store
                flags = kv_store.get("ads_truth:flags") or []
                flags.append({"metric": "ads_truth_action",
                              "reason": (f"#131 ruling pass SKIPPED mid-run: this pull "
                                         f"came back PARTIAL ({partial2.get('error')}) "
                                         f"— deriving from a fragment is refused (F9)")})
                kv_store.put("ads_truth:flags", flags[-60:])
            except Exception:
                pass
            return {"skipped": f"stripe pull partial (F9, post-pull): "
                               f"{partial2.get('error')}"}
    except Exception:
        pass
    store = derived_dates()
    for t in blanks:
        nm, email_n = _norm(t["name"]), _norm(t.get("email"))
        if (email_n and email_n in dated_idents) or nm in dated_idents:
            out["skipped_duplicate_dated"].append(t["name"])
            continue
        if (store.get(nm) or {}).get("close_date"):
            out["already_derived"] += 1          # convert-twice = structural no-op
            continue
        s = stripe_dates.get(email_n)
        if s and s.get("via") == "email":
            ok = record_derived_date(
                nm, "close_date", str(s["date"]), "derived:stripe",
                {"charge_id": s.get("charge_id"), "matched_by": "email",
                 "ruling": "DECISIONS #131", "card": f"pfix:close_date:{nm}"})
            if ok:
                log_autofix("ruling-conversion DECISIONS #131",
                            f"{t['name']}: close_date {s['date']} derived from Stripe "
                            f"charge {s.get('charge_id')} (ID-exact email match)")
                out["converted"].append({"name": t["name"], "date": str(s["date"]),
                                         "charge_id": s.get("charge_id"),
                                         "cash": t.get("cash")})
                out["cash_placed"] += t.get("cash") or 0.0
        else:
            s2 = s or stripe_dates.get(nm)
            if s2:
                out["skipped_name_only"].append(t["name"])   # PROPOSED card persists
    out["cash_placed"] = round(out["cash_placed"], 2)
    if out["converted"]:
        try:
            import kv_store
            from helpers import today_sydney
            flags = kv_store.get("ads_truth:flags") or []
            flags.append({"metric": "ads_truth_action", "date": str(today_sydney()),
                          "reason": (f"{len(out['converted'])} close date(s) applied under "
                                     f"DECISIONS #131 (payment-class auto-derivation) — "
                                     f"${out['cash_placed']:,.0f} placed on the clocks; "
                                     f"evidence journaled per deal")})
            kv_store.put("ads_truth:flags", flags[-60:])
        except Exception:
            pass
    return out


def rederive_ghl_dates_sydney(dry_run: bool = False,
                              reason: str = "F8-sydney-day") -> dict:
    """F8 ONE-OFF (journaled, reversible): re-derive every GHL-derived date with
    the Sydney-day helper. The pre-F8 derivations sliced the UTC day — any
    appointment/contact event before ~10–11am Sydney sat on the previous day.

    Covers both derived classes:
      · set_date / show_date with provenance derived:ghl-appt (re-read from the
        appointment evidence — dateAdded booked / startTime scheduled);
      · input_date with provenance derived:ghl-contact-created (re-read from the
        contact's date_added).
    Each change journals old→new + the evidence id + reason 'F8-sydney-day';
    unchanged dates journal nothing (idempotent). Window-boundary crossings
    (30/60/90d membership flips) are called out in the return. The epoch bumps
    once at the end so every cache/rollup refreshes."""
    from helpers import sydney_day, today_sydney
    out = {"checked": 0, "changed": [], "unchanged": 0, "no_evidence": [],
           "crossed_window": [], "dry_run": dry_run}
    store = derived_dates()
    today = today_sydney()

    def _crossings(old_iso, new_iso):
        import datetime as _dt
        crossed = []
        try:
            o = _dt.date.fromisoformat(old_iso); n = _dt.date.fromisoformat(new_iso)
        except Exception:
            return crossed
        for w in (30, 60, 90):
            w0 = today - _dt.timedelta(days=w - 1)
            if (w0 <= o <= today) != (w0 <= n <= today):
                crossed.append(w)
        return crossed

    contacts_added = {}
    try:
        import attribution_join
        for c in attribution_join.load_contacts():
            if c.get("id"):
                contacts_added[c["id"]] = c.get("date_added")
    except Exception:
        pass

    changed_any = False
    for nm, fields in list(store.items()):
        for field, entry in list(fields.items()):
            prov = str(entry.get("provenance") or "")
            ev = entry.get("evidence") or {}
            new_iso = None
            ev_id = None
            if field in ("set_date", "show_date") and prov.startswith("derived:ghl-appt"):
                out["checked"] += 1
                cid, aid = ev.get("contact_id"), ev.get("appointment_id")
                ev_id = aid
                if not (cid and aid):
                    out["no_evidence"].append({"name": nm, "field": field})
                    continue
                try:
                    import ads_truth
                    appt = next((a for a in ads_truth._cached_appointments(cid)
                                 if a.get("id") == aid), None)
                except Exception:
                    appt = None
                if not appt:
                    out["no_evidence"].append({"name": nm, "field": field,
                                               "appointment_id": aid})
                    continue
                raw = appt.get("dateAdded") if field == "set_date" else appt.get("startTime")
                # #134 tz truth: the appointment endpoint's stamps are LOCATION-
                # LOCAL offset-less — source-aware day, NOT the naive=UTC path.
                # (The first run of this migration used sydney_day here and
                # moved 22 dates +1 day; rederive_appointment_local_days()
                # corrected them, journaled.)
                import consult_schedule
                new_iso = consult_schedule.appt_day(raw)
            elif field == "input_date" and prov.startswith("derived:ghl-contact-created"):
                out["checked"] += 1
                cid = ev.get("contact_id")
                ev_id = cid
                da = contacts_added.get(cid)
                if da is None:
                    out["no_evidence"].append({"name": nm, "field": field,
                                               "contact_id": cid})
                    continue
                d = sydney_day(da)
                new_iso = str(d) if d else None
            elif field == "close_date" and prov.startswith("derived:stripe") \
                    and ev.get("charge_id"):
                # review finding 3: charge epochs were sliced with the SERVER-
                # LOCAL day (UTC on Railway) — re-derive the Sydney day from the
                # charge's created epoch (read-only fetch by id, ≤ the #131
                # conversion population).
                out["checked"] += 1
                ev_id = ev["charge_id"]
                created = None
                try:
                    from payback_reconciliation import _sget
                    r = _sget(f"/v1/charges/{ev['charge_id']}", {})
                    if r.get("error") is None:
                        created = r.get("created")
                except Exception:
                    created = None
                if not created:
                    out["no_evidence"].append({"name": nm, "field": field,
                                               "charge_id": ev_id})
                    continue
                import datetime as _dt
                import pytz as _pytz
                d = sydney_day(_dt.datetime.fromtimestamp(created, tz=_pytz.utc))
                new_iso = str(d) if d else None
            else:
                continue
            if not new_iso or new_iso == entry.get("date"):
                out["unchanged"] += 1
                continue
            change = {"name": nm, "field": field, "old": entry["date"],
                      "new": new_iso, "evidence_id": ev_id,
                      "crossed_window": _crossings(entry["date"], new_iso)}
            out["changed"].append(change)
            if change["crossed_window"]:
                out["crossed_window"].append(change)
            if not dry_run:
                entry["date"] = new_iso
                entry["rederived"] = {"reason": reason, "old": change["old"],
                                      "ts": str(today)}
                changed_any = True
                log_autofix(f"date rederived ({field})",
                            f"{nm}: {change['old']} → {new_iso} via {prov} "
                            f"(evidence {ev_id}, reason {reason})")
    if changed_any:
        _put_derived(store)
        bump_derived_epoch(f"date re-derivation ({reason})")
    return out


def rederive_appointment_local_days(dry_run: bool = False) -> dict:
    """#134 CORRECTIVE MIGRATION: the F8 run treated the appointment endpoint's
    OFFSET-LESS LOCATION-LOCAL stamps as UTC and moved 22 derived set/show
    dates +1 day (peer-confirmed 266/266 offset-less; hour-distribution proof
    in DECISIONS #134). The re-derivation machinery above now parses those
    stamps source-aware (consult_schedule.appt_day), so this run reverts
    exactly the wrongly-shifted entries; contact-created and Stripe legs
    recompute identically and journal nothing. Idempotent."""
    return rederive_ghl_dates_sydney(dry_run=dry_run, reason="appt-local-tz (#134)")


_APPLY_DATE_RE = re.compile(r"apply (the )?date card (for )?(.+)", re.I)


def handle_apply_date_card(text: str) -> tuple[str | None, bool]:
    """Rydel confirms a PROPOSED close-date candidate → it becomes a journaled
    DERIVATION (no tracker write — the queue item persists until the source fills)."""
    m = _APPLY_DATE_RE.match((text or "").strip())
    if not m:
        return None, False
    frag = m.group(3).strip().lower()
    cards = (latest_proposed() or {}).get("cards") or []
    hits = [c for c in cards if c.get("kind") == "P1_close_date_candidate"
            and frag in (c.get("name") or "").lower()]
    if len(hits) != 1:
        return (f"{len(hits)} card(s) match '{frag}' — give me a fragment that matches "
                f"exactly one ('any proposed fixes?' lists them).", True)
    card = hits[0]
    cand = (card.get("candidates") or [{}])[0]
    ok = record_derived_date(_norm(card["name"]), "close_date", cand.get("date"),
                             f"derived:{'stripe' if 'Stripe' in (cand.get('source') or '') else 'ghl-stage'}"
                             f" (Rydel-confirmed)",
                             {"card": card.get("id"), "source": cand.get("source")})
    if not ok:
        return "That card has no usable candidate — nothing derived.", True
    return (f"Derived (on your confirmation): {card['name']} close date "
            f"{cand.get('date')} from {cand.get('source')}. The board can window it now, "
            f"labelled; the Piolo item stays until the tracker cell is filled — the "
            f"source will supersede.", True)


# ── EDITH ────────────────────────────────────────────────────────────────────

_PROPOSED_RE = re.compile(
    r"proposed fix(es)?|fix cards?|(any|show).{0,20}(date )?candidates?|"
    r"what (can|could) (be|we) fix(ed)?|resolution (engine|cards)", re.I)
_AUTOFIX_LOG_RE = re.compile(
    r"(auto.?fix|autofix).{0,15}(log|history|applied)|what did you (auto.?)?fix|"
    r"resolution log", re.I)


def handle_proposed_fixes_command(text: str) -> tuple[str | None, bool]:
    """'any proposed fixes?' — the P1/P2 cards with their evidence."""
    if not text or not _PROPOSED_RE.search(text):
        return None, False
    data = latest_proposed()
    cards = data.get("cards") or []
    if not cards:
        return ("No proposed-fix cards right now — nothing has a derivable candidate. "
                + DOCTRINE), True
    p1 = [c for c in cards if c["kind"] == "P1_close_date_candidate"]
    p2 = [c for c in cards if c["kind"] == "P2_name_link"]
    h1 = [c for c in cards if c["kind"] == "H1_no_candidate"]
    parts = [f"Proposed fixes (as of {data.get('as_of')}) — evidence only, a human applies:"]
    for c in p1[:8]:
        cand = c["candidates"][0]
        parts.append(f"• {c['name']}: Close Date candidate {cand['date']} "
                     f"(from {cand['source']}) — {c['instruction']}")
    if len(p1) > 8:
        parts.append(f"…and {len(p1) - 8} more date candidates.")
    for c in p2[:4]:
        parts.append(f"• {c['name']}: {c['candidates'][0]['source']} — {c['instruction']}")
    if h1:
        parts.append(f"{len(h1)} blank(s) have NO candidate anywhere — those stay with "
                     f"Piolo's queue (human-fix).")
    return "\n".join(parts), True


def handle_autofix_log_command(text: str) -> tuple[str | None, bool]:
    """'what did you auto-fix?' — the application log, the trust surface."""
    if not text or not _AUTOFIX_LOG_RE.search(text):
        return None, False
    import kv_store
    lg = kv_store.get(_KV_AUTOFIX_LOG) or []
    if not lg:
        return ("No auto-fix applications logged yet. The standing rules: " + DOCTRINE), True
    parts = [f"Auto-fix log — {len(lg)} recent application(s), newest first:"]
    for e in reversed(lg[-12:]):
        parts.append(f"• [{e['ts']}] {e['rule']}: {e['detail']}")
    ej = evidence_journal()
    if ej:
        parts.append(f"Evidence archive: {len(ej)} durable entr(ies) — derivations, "
                     f"ruling conversions, supersessions, verifications (never aged "
                     f"out by sweep noise).")
    return "\n".join(parts), True
