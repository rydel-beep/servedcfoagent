"""
stripe_reconcile.py
-------------------
Stripe ↔ Lead-to-Cash tracker reconciliation.

Purpose: catch the exact gap that hid Lucas/Cally — a client who PAID via Stripe
but whose tracker row isn't logged (or whose money columns are blank). It flags
"paid in Stripe, no matching tracker entry" so EDITH proactively surfaces it
instead of silently missing the client.

Matching runs SERVER-SIDE only, here, because it needs the tracker's email/name
columns (cols 3/4/5) which are PII and must NEVER reach the snapshot. The output
is name/amount/date level only — no emails leave this module (asserted before return).

ACTIVATED 2026-07-09: per-charge data now comes from the Stripe API directly
(read-only restricted key, via cash_truth._recent_charges — same reads the
payback reconciliation uses). The original MCP-tool dependency is obsolete: the
aggregate-only MCP never grew a list-charges tool, but the rk_ key on Railway
reads /v1/charges fine. Without the key this still degrades cleanly to a
"pending" status with a degraded[] entry; it never fabricates matches.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, timedelta

import requests

from config import SHEET_CONFIG, HTTP_TIMEOUT
from helpers import today_sydney

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 30
_AMOUNT_TOLERANCE = 1.0  # AUD, for amount fallback matching


def _list_recent_charges(days: int) -> dict | None:
    """Succeeded charges via the read-only Stripe key (cash_truth's shared reader),
    in this module's expected shape. None = no key / API failure."""
    try:
        from cash_truth import _recent_charges
        charges = _recent_charges(days)
    except Exception as e:
        logger.error("Reconcile charge fetch failed: %s", e)
        return None
    if charges is None:
        return None
    return {"charges": [{"id": c["id"], "amount": c["amount"], "currency": c["currency"],
                         "created": str(c["date"]), "status": "succeeded",
                         "customer_name": c["customer_name"],
                         "customer_email": c["_email"]} for c in charges]}


def _norm(s: str) -> str:
    """Normalize a name/business for loose matching."""
    s = (s or "").strip().lower()
    s = re.sub(r"\b(the|pty|ltd|co|restaurant|cafe|café|bar|kitchen|and|&)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fetch_tracker_rows() -> tuple[list[str], list[list[str]]]:
    """Fetch the Lead-to-Cash tracker (full sheet, by name — no row cutoff)."""
    sid = SHEET_CONFIG["sheet_id"]
    tab = SHEET_CONFIG["tab_name"]
    url = (
        f"https://docs.google.com/spreadsheets/d/{sid}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab)}"
    )
    try:
        resp = requests.get(url, timeout=(5, HTTP_TIMEOUT))
        if resp.status_code != 200:
            return [], []
        rows = list(csv.reader(io.StringIO(resp.text)))
        if len(rows) < 2:
            return [], []
        return rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    except requests.RequestException as e:
        logger.error("Reconcile tracker fetch failed: %s", e)
        return [], []


def _cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if idx < len(row) else ""


# ── Multi-signal identity matching (tracker + roster, scored) ────────────────
# The old matcher was too literal (exact email OR exact normalized name, tracker-only),
# so it false-flagged existing clients paying again (Jeni/Nirosha/Jagjeet) and payer≠business
# cases (Fiona Fitzgerald = Glen's venue). This matches on MULTIPLE signals against BOTH the
# tracker (rich: email/contact/business for all rows) and the active roster, with confidence.

_STOP_TOKENS = {"the", "and", "cafe", "café", "bar", "kitchen", "restaurant", "pty", "ltd", "co"}


def _tokens(s: str) -> set:
    return {t for t in _norm(s).split() if len(t) >= 2 and t not in _STOP_TOKENS}


def _surname(s: str) -> str:
    parts = [t for t in re.sub(r"[^a-z ]", " ", (s or "").lower()).split() if len(t) > 2]
    return parts[-1] if parts else ""


def _build_identity_index(headers: list[str], rows: list[list[str]]) -> dict:
    """Rich identity index from the tracker (cols 3 Lead Name, 4 Email, 7 Business). Emails stay
    inside this module. Also maps surname → {businesses} to tell distinctive from common surnames."""
    by_email: dict[str, str] = {}
    contacts: list[tuple] = []          # (contact_tokens, business_label, surname)
    by_business: dict[str, str] = {}    # normalized business tokens key -> label
    surname_map: dict[str, set] = {}
    for r in rows:
        name = _cell(r, 3)
        email = _cell(r, 4).lower()
        business = _cell(r, 7)
        label = business or name
        if not label:
            continue
        if email and "@" in email:
            by_email[email] = label
        if name:
            contacts.append((_tokens(name), label, _surname(name)))
            sur = _surname(name)
            if sur:
                surname_map.setdefault(sur, set()).add(label)
        if business:
            by_business[_norm(business)] = business
    return {"by_email": by_email, "contacts": contacts,
            "by_business": by_business, "surname_map": surname_map}


def _roster_index() -> dict:
    """Active-client business names (normalized) + their MRR, for active-check + amount corroboration."""
    active, amounts = set(), {}
    try:
        import sheet_mirror
        from config import FINANCE_SHEET_CONFIG
        rows = sheet_mirror.read_by_gid(1407663952) or \
            sheet_mirror._live_fetch(FINANCE_SHEET_CONFIG["sheet_id"], "Health (roster)", gid=1407663952)
        for r in (rows or [])[1:]:
            if len(r) > 7 and (r[0] or "").strip():
                nb = _norm(r[0])
                if (r[1] or "").strip().lower() == "active":
                    active.add(nb)
                m = re.sub(r"[^0-9.]", "", r[7] or "")
                if m:
                    amounts[nb] = float(m)
    except Exception as e:
        logger.info("roster_index failed: %s", e)
    return {"active": active, "amounts": amounts}


def _aliases() -> dict:
    """Learned payer→business aliases (normalized payer name → business). Server-side, no raw email."""
    try:
        import kv_store
        return kv_store.get("stripe:payer_aliases") or {}
    except Exception:
        return {}


def learn_alias(payer_name: str, business: str) -> bool:
    try:
        import kv_store
        d = kv_store.get("stripe:payer_aliases") or {}
        d[_norm(payer_name)] = business
        kv_store.put("stripe:payer_aliases", d)
        # self-improvement loop: a confirmed fix becomes a standing rule (A3) — logged
        try:
            import resolution
            resolution.log_autofix("A3 alias learned",
                                   f"'{payer_name}' → {business} (Rydel-confirmed; "
                                   f"auto-applies on recurrence)")
        except Exception:
            pass
        return True
    except Exception:
        return False


def _amount_ok(amount, business_norm: str, amounts: dict) -> bool:
    """Does the payment amount plausibly corroborate this client (≈ MRR, or ≈ a 2-4 split of it)?"""
    mrr = amounts.get(business_norm)
    if not mrr or not amount:
        return False
    for f in (1, 2, 3, 4, 0.5):        # full MRR or common instalment fractions
        if abs(amount - mrr * f) <= max(50.0, mrr * 0.08):
            return True
    return False


def _match_payment(name: str, email: str, amount, idx: dict, roster: dict) -> dict:
    """Score a Stripe payment against tracker + roster identity signals. Returns the resolved match
    with confidence + basis, a review suggestion, or an 'unrecognised' verdict. Never forces a match."""
    aliases = _aliases()
    alias_biz = aliases.get(_norm(name))
    if alias_biz:
        return {"business": alias_biz, "confidence": "high", "basis": "confirmed alias",
                "category": "existing_client_repeat" if _norm(alias_biz) in roster["active"] else "matched_known"}

    ptoks, sur = _tokens(name), _surname(name)
    cands: list[tuple] = []             # (business, score, basis)
    if email and email in idx["by_email"]:
        cands.append((idx["by_email"][email], 100, "email"))
    for ctoks, biz, _csur in idx["contacts"]:
        if not ctoks or not ptoks:
            continue
        shared = ptoks & ctoks
        if (ptoks <= ctoks or ctoks <= ptoks) and len(shared) >= 2:
            cands.append((biz, 80, "contact name"))          # e.g. Nirosha ⊆ Nirosha Dushani
        elif len(shared) >= 2:
            cands.append((biz, 58, "contact name (partial)"))
        elif ctoks <= ptoks and len(ctoks) == 1 and len(next(iter(ctoks))) >= 4:
            cands.append((biz, 50, "first name"))            # e.g. contact "Jeni" ⊆ "Jeni Arul Pragasam"
    for bnorm, label in idx["by_business"].items():
        btoks = _tokens(label)
        if btoks and ptoks and (btoks <= ptoks or ptoks <= btoks) and (ptoks & btoks):
            cands.append((label, 68, "business name"))
    sur_biz = idx["surname_map"].get(sur, set())
    if len(sur_biz) == 1:
        cands.append((next(iter(sur_biz)), 60, "surname (unique)"))
    elif 2 <= len(sur_biz) <= 5:
        for b in sur_biz:
            cands.append((b, 26, "surname (ambiguous)"))

    # amount corroboration boost
    cands = [(b, s + (20 if _amount_ok(amount, _norm(b), roster["amounts"]) else 0),
              bs + ("+amount" if _amount_ok(amount, _norm(b), roster["amounts"]) else "")) for b, s, bs in cands]
    if not cands:
        return {"category": "unrecognised", "confidence": "none"}
    cands.sort(key=lambda x: -x[1])
    best = cands[0]
    strong = {b for b, s, _ in cands if s >= 60}
    if best[1] >= 60 and len(strong) <= 1:
        cat = "existing_client_repeat" if _norm(best[0]) in roster["active"] else "matched_known"
        return {"business": best[0], "confidence": "high", "basis": best[2], "category": cat}
    if best[1] >= 26:
        seen, sug = set(), []
        for b, s, bs in cands:
            if b not in seen:
                seen.add(b); sug.append({"business": b, "basis": bs})
        return {"category": "needs_review", "confidence": "medium", "suggested": sug[:3]}
    return {"category": "unrecognised", "confidence": "none"}


def _known_businesses() -> set:
    """Business names known to the tracker + roster — to validate a confirmed alias target."""
    names = set()
    try:
        hdrs, rows = _fetch_tracker_rows()
        for r in rows:
            b = _cell(r, 7)
            if b:
                names.add(_norm(b))
        r2 = _roster_index()
        names |= set(r2["active"])
    except Exception:
        pass
    return names


def handle_alias_confirm(text: str) -> tuple[str | None, bool]:
    """'Jagjeet Singh is Masala Factory' / 'Fiona is Glen's venue — 62Thirty' → learn a payer→client
    alias so that payer auto-matches next time. Validates the business is a known client."""
    if not text:
        return None, False
    m = re.search(r"\b([A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,3})\s+(?:is|=|pays? for|is the|belongs to|"
                  r"maps? to)\s+(.+)", text)
    if not m or not re.search(r"\b(payment|paid|stripe|charge|venue|client|match|alias|is )\b", text, re.I):
        return None, False
    # A payer is a NAME, not a question word. Without this, any capitalized question
    # ("What is overdue?", "Where is Butler's onboarding at?") was captured as
    # payer="What"/"Where" and swallowed here before the tier-2 data handlers ran
    # (surfaced live 3 Aug 2026 by the Timeline bridge questions).
    if m.group(1).split()[0].lower() in {"what", "what's", "where", "who", "whose", "when",
                                         "why", "how", "which", "that", "this", "there",
                                         "it", "is", "the"}:
        return None, False
    payer = m.group(1).strip()
    business_raw = re.sub(r"['’]s\b|\bvenue\b|\brestaurant\b|\bthe\b|[.?!]", " ", m.group(2)).strip(" -–—")
    if not payer or len(business_raw) < 3:
        return None, False
    known = _known_businesses()
    # resolve the stated business to a known client (exact or token match)
    target = None
    bn = _norm(business_raw)
    if bn in known:
        target = business_raw
    else:
        bt = _tokens(business_raw)
        for k in known:
            if bt and (_tokens(k) & bt) and (_tokens(k) <= bt or bt <= _tokens(k)):
                target = business_raw
                break
    if not target:
        return (f"I don't recognise “{business_raw}” as a client — check the spelling and I'll link "
                f"{payer}'s payments to it."), True
    learn_alias(payer, target)
    return (f"Got it — {payer}'s Stripe payments now map to {target}. I'll auto-match them from here "
            "and won't flag them again."), True


def handle_reconciliation_query(text: str) -> tuple[str | None, bool]:
    """'any unmatched payments?' / 'unrecognised stripe payments' → the genuine anomalies only."""
    if not text or not re.search(r"\b(unmatched|unrecognised|unrecognized|paid but (un)?logged|"
                                 r"stripe (payments?|reconcil)|payments? (not )?(matched|logged|in the tracker)|"
                                 r"who paid)\b", text, re.I):
        return None, False
    try:
        from snapshot import load_persisted
        res = (load_persisted() or {}).get("stripe_reconciliation") or {}
    except Exception:
        res = {}
    unrec = res.get("paid_missing_from_tracker") or []
    review = res.get("needs_review") or []
    if not unrec and not review:
        n = len(res.get("recognised_repeat_payments") or [])
        return (f"All Stripe payments reconcile — {n} matched to existing clients, none unaccounted for."), True
    parts = []
    if unrec:
        parts.append(f"{len(unrec)} unrecognised: " +
                     "; ".join(f"{u['customer']} ${u['amount']:,.0f}" for u in unrec[:5]) +
                     ". Tell me who they are (e.g. 'Jagjeet Singh is <client>') and I'll remember it.")
    if review:
        parts.append(f"{len(review)} to confirm: " +
                     "; ".join(f"{r['customer']} → likely {r['suggested'][0]['business']}?"
                               for r in review[:3] if r.get('suggested')))
    return " ".join(parts), True


def reconcile_stripe_tracker() -> dict:
    """Flag Stripe payments with no matching tracker entry.

    Returns dict for the snapshot under 'stripe_reconciliation'. PII-safe:
    only customer/business names + amounts + dates in the output, never emails.
    """
    degraded: list[dict] = []
    today = today_sydney()

    charges_res = _list_recent_charges(_LOOKBACK_DAYS)
    if not charges_res or "charges" not in charges_res:
        # No read-only Stripe key / API unreachable — honest pending state.
        degraded.append({
            "metric": "stripe_reconciliation",
            "reason": (
                "Stripe↔tracker reconciliation pending: per-charge reads unavailable "
                "(no read-only STRIPE_SECRET_KEY or API failure). Incomplete Won rows "
                "are still surfaced via the 'won_but_unlogged' flag."
            ),
        })
        return {
            "stripe_reconciliation": {
                "status": "pending_stripe_key",
                "paid_missing_from_tracker": None,
                "checked_charges": 0,
            },
            "degraded": degraded,
        }

    headers, rows = _fetch_tracker_rows()
    if not headers:
        degraded.append({
            "metric": "stripe_reconciliation",
            "reason": "Reconciliation could not read the tracker — skipped this cycle.",
        })
        return {
            "stripe_reconciliation": {"status": "tracker_unavailable",
                                      "paid_missing_from_tracker": None,
                                      "checked_charges": 0},
            "degraded": degraded,
        }

    idx = _build_identity_index(headers, rows)
    roster = _roster_index()

    recognised: list[dict] = []     # matched to an existing client (repeat/known) — informational
    review: list[dict] = []         # ambiguous — a suggested match to confirm
    unrecognised: list[dict] = []   # no match after multi-signal search — the real anomaly
    checked = 0
    for ch in charges_res["charges"]:
        if (ch.get("status") or "succeeded") != "succeeded":
            continue
        checked += 1
        email = (ch.get("customer_email") or "").lower()
        name = ch.get("customer_name") or ""
        m = _match_payment(name, email, ch.get("amount"), idx, roster)
        base = {"customer": name or "(unnamed Stripe customer)", "amount": ch.get("amount"),
                "date": ch.get("created")}   # name/amount/date only — never the email
        cat = m.get("category")
        if cat in ("existing_client_repeat", "matched_known"):
            recognised.append({**base, "matched_to": m["business"], "basis": m["basis"],
                               "kind": cat})
        elif cat == "needs_review":
            review.append({**base, "suggested": m.get("suggested", [])})
        else:
            unrecognised.append(base)

    # A3 (resolution doctrine): confirmed aliases auto-applied — logged once per run,
    # only when any applied (the log is the trust surface, not a firehose)
    alias_hits = [r for r in recognised if r.get("basis") == "confirmed alias"]
    if alias_hits:
        try:
            import resolution
            resolution.log_autofix(
                "A3 confirmed-alias reuse",
                f"{len(alias_hits)} payment(s) matched via aliases Rydel confirmed earlier: "
                + ", ".join(sorted({a['customer'] for a in alias_hits})[:5]))
        except Exception:
            pass

    result = {
        "status": "ok",
        "checked_charges": checked,
        "lookback_days": _LOOKBACK_DAYS,
        # only TRULY unknown payers — existing-client repeats + payer≠business are resolved above
        "paid_missing_from_tracker": unrecognised,
        "recognised_repeat_payments": recognised,     # informational: existing clients paying again
        "needs_review": review,                       # ambiguous — a suggested match to confirm
        "match_method": "multi-signal (email · contact/business name tokens · distinctive surname · "
                        "amount) vs tracker + active roster, confidence-scored; aliases learned",
    }
    # FLAG SEMANTICS (Phase 2): a recognised repeat payment is NORMAL, never an error. Only a
    # genuinely UNRECOGNISED payer is an action item — and it's a hygiene flag, not a core-red
    # failure (one unknown payment must not red the whole dashboard).
    if unrecognised:
        degraded.append({
            "metric": "stripe_unrecognised_payment",
            "severity": "hygiene",
            "reason": (f"{len(unrecognised)} Stripe payment(s) match no client after a multi-signal "
                       "search — verify the payer and log/associate them."),
        })

    # PII guard: assert no email slipped into the output.
    blob = str(result)
    assert "@" not in blob, "stripe_reconciliation output must not contain emails"

    return {"stripe_reconciliation": result, "degraded": degraded}
