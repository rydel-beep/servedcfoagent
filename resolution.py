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
