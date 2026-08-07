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

DOCTRINE = ("AUTO-FIX derives, never invents (A1 normalization, A2 id re-key, A3 "
            "confirmed-alias reuse, A4 clock annotations, A5 self-retiring flags — all "
            "logged); PROPOSED-FIX shows evidence and waits for a human; HUMAN-FIX is "
            "routed to a named owner. Nothing ever writes to the tracker, GHL, or Stripe.")


def log_autofix(rule: str, detail: str) -> None:
    """Every silent application is auditable — the log IS the trust."""
    try:
        import kv_store
        from helpers import today_sydney
        lg = kv_store.get(_KV_AUTOFIX_LOG) or []
        lg.append({"rule": rule, "detail": detail[:160], "ts": str(today_sydney())})
        kv_store.put(_KV_AUTOFIX_LOG, lg[-200:])
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
        for r in rows:
            if r.get("last_status_change_at"):
                d = r["last_status_change_at"].date()
                if r.get("email"):
                    out[_norm(r["email"])] = {"date": d, "via": "email"}
                if r.get("name"):
                    out.setdefault(_norm(r["name"]), {"date": d, "via": "name"})
    except Exception as e:
        logger.info("ghl won dates read failed: %s", e)
    return out


def _stripe_first_payment_dates(days: int = 365) -> dict:
    """payer/email norm → earliest charge date (read-only key; degrades to empty)."""
    out = {}
    try:
        from cash_truth import _recent_charges
        for c in (_recent_charges(days) or []):
            for k in (_norm(c.get("name")), _norm(c.get("_email"))):
                if k and (k not in out or c["date"] < out[k]):
                    out[k] = c["date"]
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

    ghl_dates = _ghl_won_dates()
    stripe_dates = _stripe_first_payment_dates()

    for t in blanks:
        # A1: normalize before matching (tracker emails arrive pre-normed; re-norm is safe)
        name_n, email_n = _norm(t["name"]), _norm(t.get("email"))
        candidates = []
        g = ghl_dates.get(email_n) or ghl_dates.get(name_n)
        if g:
            candidates.append({"date": str(g["date"]),
                               "source": f"GHL closed-won stage move (matched by {g['via']})"})
        s = stripe_dates.get(email_n) or stripe_dates.get(name_n)
        if s:
            candidates.append({"date": str(s), "source": "Stripe first payment"})
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
    store.setdefault(name_norm, {})[field] = {
        "date": date_iso, "provenance": provenance, "evidence": evidence,
        "ts": str(today_sydney())}
    _put_derived(store)
    log_autofix(f"date derived ({field})",
                f"{name_norm}: {field} = {date_iso} via {provenance} "
                f"(evidence {str(evidence)[:80]})")
    return True


def supersede_derived(name_norm: str, field: str, source_date_iso: str) -> dict | None:
    """The source landed: it WINS. The derivation is retired (journaled, reversible
    via the journal); a source≠derived disagreement SURFACES, never silently resolves."""
    store = derived_dates()
    cur = (store.get(name_norm) or {}).get(field)
    if not cur:
        return None
    del store[name_norm][field]
    if not store[name_norm]:
        del store[name_norm]
    _put_derived(store)
    agree = cur.get("date") == source_date_iso
    log_autofix(f"date superseded ({field})",
                f"{name_norm}: source {source_date_iso} supersedes derived "
                f"{cur.get('date')} ({cur.get('provenance')}) — "
                f"{'agrees' if agree else 'DISAGREES'}")
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
                date_iso = str(da.date() if hasattr(da, "date") else da)[:10]
                if record_derived_date(nm, "input_date", date_iso,
                                       "derived:ghl-contact-created",
                                       {"contact_id": c["id"]}):
                    out["input_auto"] += 1
    cards = (latest_proposed() or {}).get("cards") or []
    out["close_proposed_existing"] = sum(1 for c in cards
                                         if c.get("kind") == "P1_close_date_candidate")
    return out


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
    parts = [f"Auto-fix log — {len(lg)} application(s), newest first:"]
    for e in reversed(lg[-12:]):
        parts.append(f"• [{e['ts']}] {e['rule']}: {e['detail']}")
    return "\n".join(parts), True
