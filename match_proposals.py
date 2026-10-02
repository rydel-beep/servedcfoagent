"""match_proposals.py — PAYMENT-MATCH CONFIRMATIONS, IN THE DASHBOARD (#171, Phase 1.4).

MATCH_PROPOSALS_2026-09-29.md listed 22 unmatched Stripe payers (103 charges,
$226,928.20) and 12 bank-transfer clients (Xero contacts) with the evidence
for each and a proposed client. They sat in a markdown file for Rydel to
answer by reply. This module makes them CARDS: evidence shown, three buttons
— Confirm · Reject · "this is someone else" — and, on confirm, the option to
record the package, start date and contract value in the same step.

PROPOSALS ONLY until a human decides. Nothing here is applied by the agent:
  · confirming a Stripe payer   → unmatched_payments.confirm (the alias store
                                  the matcher already reads), journaled
  · confirming a Xero contact   → client_receipts.confirm_contact, journaled
  · package + start + contract  → close_register.rule_deal_terms (an owner
                                  ruling, the contract rung), journaled
  · reject / someone else       → journaled; "someone else" confirms the name
                                  typed instead of the proposal
  · after any confirm           → the renewal/completion measurement is asked
                                  to re-run (unit_econ_engine.request_remeasure)

The three rulings Rydel already gave on 29 Sep (Norvin Acabo → Asian Streat,
Kin Fun Keng Wong → Noodle Asia, Warners At The Bay → photography, excluded)
are seeded as DECIDED so they do not come back as questions.

READ-ONLY LAW (#148): the tracker, GHL and Xero are never written. The alias
store, the contact map and the register's ruling store are this repo's kv.
"""
from __future__ import annotations

import logging
import re

import kv_store
from helpers import now_sydney, today_sydney

logger = logging.getLogger(__name__)

K_STATE = "payments:match_proposals"      # {id: {...proposal, status, decision}}
K_JOURNAL = "payments:match_proposals_journal"
SEED_VERSION = 1


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# ── the seed: MATCH_PROPOSALS_2026-09-29.md, structured ─────────────────────
# kind: "stripe" (payer alias) | "xero" (contact map). proposed=None means
# "needs your name". strength is the document's own word.

_STRIPE = [
    ("norvin Acabo", 28, 30800.00, "Apr 25 → Apr 26",
     "Xero invoices to 'Norvin Acabo' (same person); no business named", "Asian Streat", "ruled 29 Sep"),
    ("Adrian Sheather", 10, 27500.00, "Apr 25 → Jan 26", "email @risingsunworkshop.com", "Rising Sun Workshop", "strong (domain)"),
    ("Prashant Sharma", 4, 19505.40, "Oct → Dec 25", "gmail, 'Subscription update' only", None, "—"),
    ("(unnamed Stripe customer)", 7, 15165.00, "Oct 25 → Jan 26", "no name, no email", None, "—"),
    ("Thuong Tran", 2, 13750.00, "Mar → Apr 26", "email @ourtook.com", "the business behind ourtook.com", "medium (domain, name unknown)"),
    ("Xuan Hieo Nguyen", 3, 13747.80, "Aug → Oct 25",
     "matcher: TRITON SEAFOOD MARKET on first name only; that tracker row isn't won", None, "weak"),
    ("Hannah Tamayo", 6, 13200.00, "Oct 25 → Mar 26",
     "email @hanmadesbakehouse.com — the matcher's 'John Tamayo' (surname) is wrong", "Hanmades", "strong (domain)"),
    ("Dexter Mahinay", 4, 11550.00, "Jul → Sep 25", "gmail only", None, "—"),
    ("Siwakorn Momwong", 3, 11550.00, "Jun → Aug 25", "gmail; Xero invoice, same person", None, "—"),
    ("Anna Webb", 8, 11000.00, "Apr → Jul 25", "gmail; Xero invoices, same person", None, "—"),
    ("Nirav Patel", 3, 9900.00, "Apr → Jun 25", "gmail; Xero invoices, same person", None, "—"),
    ("kranthi pasham", 1, 8305.00, "May 26", "description 'Isht - 6m Scale Engine x2'", "Isht", "strong (description)"),
    ("Khanh Phan", 5, 7012.50, "Sep → Nov 25", "gmail only", None, "—"),
    ("Thi Kim Chi Bui", 1, 6490.00, "May 25", "@andi.melbourne + 'An Di 3 Months Custom Marketing Package'", "An Di", "strong"),
    ("Ronny Herrmann", 1, 5775.00, "Aug 25",
     "@rhe24.com + '6 Month Split Pay Angkor Cafe'; Xero 'RHE24 Pty Ltd' $11,550; tracker won 'Neri Roth Herrmann' (Custom, $10,500)",
     "Angkor Cafe", "strong for Angkor; the tracker link needs you"),
    ("Ami Geertsma", 5, 5500.00, "Apr → Aug 25", "gmail; Xero invoices, same person", None, "—"),
    ("John Elsley", 3, 4950.00, "Apr → Jun 25", "email @thewhistler.com.au", "The Whistler", "strong (domain)"),
    ("Clement Peter", 4, 4537.50, "Jun → Sep 25", "email @petersfusionkitchen.com.au", "Peter's Fusion Kitchen", "strong (domain)"),
    ("Jeni Arul Pragasam", 2, 2550.00, "Jul 26", "tracker won row 'Jeni' / Gone Burger (Custom, $18,000); first name + amount", "Gone Burger", "medium"),
    ("Manpreet Sekhon", 1, 2310.00, "Sep 25", "'Musty Custom Package $2100 6 Months Growth Pro'", "Musty", "strong (description)"),
    ("Jagjeet Singh", 1, 1500.00, "Jun 26", "'Butler's Cucina Final Pay'; tracker won row 'Butlers cucina' (contact Vipin)", "Butlers cucina", "strong (description)"),
    ("M Shahinur Hasan", 1, 330.00, "Aug 25", "'Down Payment Yo Momma Pizza'", "Yo Momma Pizza", "strong (description)"),
]

_XERO = [
    ("Kin Fun Keng Wong", "5 × $4,708 (Jul 25 → Jul 26)", "recurring; business name needed", "Noodle Asia", "ruled 29 Sep"),
    ("Steph Wicks", "7 invoices, $1,320–$2,530", "business name needed", None, "—"),
    ("Monty's Fusions", "5 × $2,500 (Feb → Jun 26)", "tracker won 'Monty's Fusions Café' (Custom, $15,000)", "Monty's Fusions Café", "direct"),
    ("156 Alfred Pty Ltd", "$13,750 (Apr 26)", "business name needed", None, "—"),
    ("Tanny Puth", "3 × $3,355 (Jun → Aug 26)", "business name needed", None, "—"),
    ("The Leopard Deli", "2 × $5,500 (Jun, Jul 26)", "direct", "The Leopard Deli", "direct"),
    ("Lost Sheep Cafe", "$15,950 (Jul 26)", "direct ($14,500 ex-GST)", "Lost Sheep Cafe", "direct"),
    ("Bar Elvina", "$5,170 (Jul 26)", "direct", "Bar Elvina", "direct"),
    ("Warners At The Bay", "7 × $363 weekly (Jul → Sep 26)", "photography work, not a marketing retainer", "Warners At The Bay", "ruled 29 Sep"),
    ("Johnnies Food House", "$2,000 (Sep 26)", "direct", "Johnnies Food House", "direct"),
    ("Walkway to Ceylon", "$330 (Sep 26)", "direct", "Walkway to Ceylon", "direct"),
    ("RHE24 Pty Ltd", "$11,550 (Sep 25)", "= Ronny Herrmann / Angkor Cafe (Stripe row)", "Angkor Cafe", "strong"),
]

# the 29 Sep rulings — DECIDED at seed time, never re-asked
_ALREADY_RULED = {
    "stripe:norvinacabo": ("confirm", "Asian Streat", "Rydel, 29 Sep: Norvin Acabo → Asian Street"),
    "xero:kinfunkengwong": ("confirm", "Noodle Asia", "Rydel, 29 Sep: Kin Fun Keng Wong → Noodle Asia"),
    "xero:warnersatthebay": ("confirm", "Warners At The Bay",
                             "Rydel, 29 Sep: photography work, not a marketing retainer — attached, excluded"),
}


def _seed() -> dict:
    out = {}
    for payer, n, total, span, evidence, proposed, strength in _STRIPE:
        pid = f"stripe:{_norm(payer)}"
        out[pid] = {"id": pid, "kind": "stripe", "who": payer, "charges": n,
                    "total": total, "span": span, "evidence": evidence,
                    "proposed": proposed, "strength": strength, "status": "pending",
                    "source_doc": "MATCH_PROPOSALS_2026-09-29.md"}
    for contact, invoices, note, proposed, strength in _XERO:
        pid = f"xero:{_norm(contact)}"
        out[pid] = {"id": pid, "kind": "xero", "who": contact, "invoices": invoices,
                    "evidence": note, "proposed": proposed, "strength": strength,
                    "status": "pending", "source_doc": "MATCH_PROPOSALS_2026-09-29.md"}
    for pid, (decision, client, words) in _ALREADY_RULED.items():
        if pid in out:
            out[pid].update({"status": "decided", "decision": decision, "client": client,
                             "decided_by": "rydel", "decided_at": "2026-09-29",
                             "words": words, "applied": "29 Sep (scripts/rule_*)"})
    return out


def state() -> dict:
    st = kv_store.get(K_STATE)
    if not st or st.get("seed_version") != SEED_VERSION:
        seeded = _seed()
        # keep any decisions already taken on a prior seed
        for pid, rec in ((st or {}).get("items") or {}).items():
            if pid in seeded and rec.get("status") == "decided":
                seeded[pid] = {**seeded[pid], **rec}
        st = {"seed_version": SEED_VERSION, "items": seeded,
              "seeded_at": now_sydney().isoformat()}
        kv_store.put(K_STATE, st)
    return st


def cards(include_decided: bool = False) -> dict:
    items = list(state()["items"].values())
    pending = [i for i in items if i["status"] == "pending"]
    pending.sort(key=lambda i: -(i.get("total") or 0))
    decided = [i for i in items if i["status"] != "pending"]
    return {
        "pending": pending, "pending_count": len(pending),
        "pending_stripe_total": round(sum(i.get("total") or 0 for i in pending
                                          if i["kind"] == "stripe"), 2),
        "decided": decided if include_decided else [],
        "decided_count": len(decided),
        "note": ("money that landed under a name the systems don't recognise — "
                 "each card shows the evidence; confirming is your ruling, journaled; "
                 "a resemblance alone never attaches money"),
    }


def _journal(rec: dict) -> None:
    j = kv_store.get(K_JOURNAL) or []
    j.append({**rec, "at": now_sydney().isoformat()})
    kv_store.put(K_JOURNAL, j[-500:])


def decide(pid: str, decision: str, actor: str, client: str | None = None,
           words: str | None = None, terms: dict | None = None) -> dict:
    """decision ∈ confirm | reject | someone_else. For confirm/someone_else a
    client name is required (someone_else = the typed name replaces the
    proposal). terms = optional {package, term_months, contract_ex_gst,
    start_date, closer, setter} → an owner deal-terms ruling in the same step."""
    st = state()
    item = st["items"].get(pid)
    if not item:
        return {"ok": False, "error": "no such proposal"}
    if item["status"] != "pending":
        return {"ok": False, "error": f"already decided ({item.get('decision')}) by "
                                      f"{item.get('decided_by')} on {str(item.get('decided_at'))[:10]}"}
    if decision not in ("confirm", "reject", "someone_else"):
        return {"ok": False, "error": "decision must be confirm, reject or someone_else"}
    out = {"ok": True, "id": pid, "decision": decision}
    if decision == "reject":
        item.update({"status": "decided", "decision": "reject", "decided_by": actor,
                     "decided_at": now_sydney().isoformat(), "words": words or ""})
        st["items"][pid] = item
        kv_store.put(K_STATE, st)
        _journal({"id": pid, "who": item["who"], "decision": "reject", "by": actor,
                  "words": words or ""})
        return out
    name = (client or "").strip() if decision == "someone_else" else (client or item.get("proposed") or "").strip()
    if not name:
        return {"ok": False, "error": "name the client this money belongs to"}
    ruling_words = words or f"{item['who']} → {name} — confirmed by {actor} on the match card"
    if item["kind"] == "stripe":
        import unmatched_payments as UP
        res = UP.confirm(item["who"], name, actor=actor)
        out["alias"] = res
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "the alias could not be written"}
    else:
        import client_receipts as CRx
        res = CRx.confirm_contact(item["who"], name, ruling_words, actor=actor,
                                  exclude_from_measurement=bool((terms or {}).get("exclude")),
                                  kind=(terms or {}).get("kind"))
        out["contact"] = res
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "the contact map could not be written"}
    item.update({"status": "decided", "decision": decision, "client": name,
                 "decided_by": actor, "decided_at": now_sydney().isoformat(),
                 "words": ruling_words})
    # package + start + contract in the same step → the contract rung
    t = terms or {}
    if t.get("package") and t.get("contract_ex_gst") and t.get("start_date"):
        import close_register as CR
        try:
            term = int(t.get("term_months") or 0) or None
        except (TypeError, ValueError):
            term = None
        if term is None:
            from config import PACKAGE_TERMS
            import csm_baselines as B
            k = B._pkg_key(t["package"])
            term = PACKAGE_TERMS.get(k) if k else None
        if term:
            r = CR.rule_deal_terms(
                person=str(t.get("person") or item["who"]), client=name,
                close_date=str(t["start_date"])[:10], package=str(t["package"]),
                term_months=int(term),
                contract_ex_gst=float(str(t["contract_ex_gst"]).replace(",", "").replace("$", "")),
                schedule=[], words=ruling_words + f"; {t['package']}, {term} months, "
                                                  f"${float(str(t['contract_ex_gst']).replace(',', '').replace('$', '')):,.2f} ex-GST",
                actor=actor, closer=t.get("closer"), setter=t.get("setter"))
            out["terms"] = r
            item["terms_ruled"] = bool(r.get("ok"))
        else:
            out["terms"] = {"ok": False, "error": "a term in months is needed for that package"}
    st["items"][pid] = item
    kv_store.put(K_STATE, st)
    _journal({"id": pid, "who": item["who"], "decision": decision, "client": name,
              "by": actor, "words": ruling_words, "terms": bool(out.get("terms", {}).get("ok"))})
    # a batch of confirmations changes the measured history → re-measure
    try:
        import unit_econ_engine as UE
        out["remeasure"] = UE.request_remeasure(f"match confirmed: {item['who']} → {name}")
    except Exception as e:  # noqa: BLE001
        out["remeasure"] = {"requested": False, "why": str(e)[:120]}
    return out


def journal() -> list[dict]:
    return kv_store.get(K_JOURNAL) or []
