"""client_receipts.py — bank-transfer clients: who a Xero contact IS (#170).

Stripe payers resolve through the alias store (unmatched_payments.confirm).
Clients who pay by bank transfer appear only as Xero contacts — this is the
same ruling for them: a Xero contact → a client, Rydel's word, journaled,
never inferred from a name that looks close.

A mapping can also say the money is NOT a marketing retainer (e.g. Warners At
The Bay — photography work): the cash stays attached to the client, and the
client is EXCLUDED from the renewal and completion measurement.

The agent's own Xero token carries report scopes only (invoice reads 401 —
DECISIONS #161), so the agent cannot yet read these receipts itself; the
mappings are stored now so they apply the moment an invoice-read scope
exists, and a session read through the Xero connector can use them today.
"""
from __future__ import annotations

import re

import kv_store
from helpers import now_sydney

K_MAP = "payments:xero_contact_map"
K_JOURNAL = "payments:xero_contact_journal"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def mappings() -> dict:
    return kv_store.get(K_MAP) or {}


def confirm_contact(contact: str, client: str, words: str, actor: str = "rydel",
                    exclude_from_measurement: bool = False,
                    kind: str | None = None) -> dict:
    if not (contact or "").strip() or not (client or "").strip():
        return {"ok": False, "error": "both a Xero contact and a client are needed"}
    if not (words or "").strip():
        return {"ok": False, "error": "the ruling's own words are required"}
    rec = {"contact": contact, "client": client, "kind": kind,
           "exclude_from_measurement": bool(exclude_from_measurement),
           "words": words, "by": actor, "at": now_sydney().isoformat()}
    m = mappings()
    prior = m.get(_norm(contact))
    m[_norm(contact)] = rec
    kv_store.put(K_MAP, m)
    j = kv_store.get(K_JOURNAL) or []
    j.append({**rec, "prior": prior})
    kv_store.put(K_JOURNAL, j[-500:])
    return {"ok": True, "mapping": rec}


def client_for(contact: str) -> dict | None:
    return mappings().get(_norm(contact))


def excluded_clients() -> set[str]:
    """Clients a ruling has taken OUT of the renewal/completion measurement."""
    return {_norm(r["client"]) for r in mappings().values()
            if r.get("exclude_from_measurement")}
