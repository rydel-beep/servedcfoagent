"""role_access.py — R-PIOLO-PARITY: FINANCE INHERITS THE OWNER (#167).

Rydel's ruling (24 Sep 2026, supersedes the #161 carve-outs): Piolo — the
CFO/bookkeeper — sees and can do EVERYTHING the owner sees and does on the
finance dashboard. Every tab, page, drawer, export and action; EDITH on his
channel answers with the same facts, chat and voice.

THE MECHANISM IS INHERITANCE, NOT AN ALLOWLIST. The #161 model kept a
per-route grant list for the coo role, which meant every new surface needed
a decision. Under parity there is nothing to grant: whatever the owner can
reach, finance reaches at the same moment. Denials exist in exactly one
place — the EXCEPTION LIST (kv, default empty), which the owner alone
edits. The shipped exception toggle is the CSM section ("Withdraw from
Piolo"), shipped ON per the ruling — i.e. NOT withdrawn — for the
Miguel-first sequencing if Rydel chooses to flip it.

THE SAFEGUARDS THAT REPLACE THE CARVE-OUTS: every action is attributed to
the session identity and journaled; the owner can reverse any action;
discreet mode remains the owner's own screen-share toggle. Truly owner-only
(require_owner_strict): the discreet toggle, credential/env management, and
this exception list.

Every OTHER role is exactly as fail-closed as before — ad_domain and sales
keep their scoped allowlists in auth.py; anonymous is refused everywhere.

The pay-scrub helpers below survive for NON-finance roles (a future role
that can read the snapshot must still never see per-person pay); for the
finance role they stand down entirely.
"""
from __future__ import annotations

import logging

import kv_store
from helpers import now_sydney

logger = logging.getLogger(__name__)

K_EXCEPTIONS = "parity:exceptions"       # ["csm", ...] — owner-managed
K_JOURNAL = "parity:journal"

# section key → the path prefixes it withdraws
SECTION_PATHS = {
    "csm": ("/dashboard/csm", "/dashboard/api/csm/"),
}


def exceptions() -> list[str]:
    return kv_store.get(K_EXCEPTIONS) or []


def set_exception(section: str, withdrawn: bool, actor: str) -> dict:
    """The owner's toggle. Journaled both ways; no deploy needed."""
    if section not in SECTION_PATHS:
        return {"ok": False, "error": f"unknown section {section!r}"}
    ex = [e for e in exceptions() if e != section]
    if withdrawn:
        ex.append(section)
    kv_store.put(K_EXCEPTIONS, ex)
    journal = kv_store.get(K_JOURNAL) or []
    journal.append({"at": now_sydney().isoformat(), "section": section,
                    "withdrawn": withdrawn, "by": actor})
    kv_store.put(K_JOURNAL, journal[-200:])
    logger.info("parity exception: %s %s by %s", section,
                "WITHDRAWN" if withdrawn else "restored", actor)
    return {"ok": True, "section": section, "withdrawn": withdrawn,
            "exceptions": ex}


def csm_withdrawn() -> bool:
    return "csm" in exceptions()


def finance_blocked(path: str) -> tuple[bool, str]:
    """The ONLY way a finance session is refused a path: the exception
    list. (The three strict items carry their own decorator and refuse at
    the route, not here.)"""
    p = path or ""
    for section in exceptions():
        for prefix in SECTION_PATHS.get(section, ()):
            if p.startswith(prefix):
                return True, (f"the {section.upper()} section is withdrawn "
                              f"from the finance role by the owner's toggle")
    return False, ""


# ── legacy shim (#161 callers) ──────────────────────────────────────────────

def coo_permitted(path: str, method: str = "GET") -> tuple[bool, str]:
    """#161's allowlist API, kept for callers/tests: under parity the answer
    is yes unless the exception list says no."""
    blocked, why = finance_blocked(path)
    return (not blocked), why


def carve_out_for(path: str):
    """#161 API: the only carve-outs left are the exception list's."""
    blocked, why = finance_blocked(path)
    return ("exception", why) if blocked else None


# ── pay scrubbing — for NON-finance roles only ──────────────────────────────
# The snapshot carries per-person pay. A finance session sees everything; a
# future non-finance role that can read it must not.

_DROP_EXACT = {
    "payout", "payout_log", "payout_status", "per_setter", "by_person",
    "kalin_override", "coby_nets", "owner_pay", "set_fees", "setter_payout",
    "commission_detail", "paid_log", "loaded_cac",
}
_DROP_SUBSTRING = ("commission", "salary", "take_home", "set_fee",
                   "setter_comm", "closer_comm", "pct_bonus")
_KEEP_EXACT = {"payouts", "payout_count", "total_paid_out"}


def _is_pay_key(key: str) -> bool:
    k = str(key).lower()
    if k in _KEEP_EXACT:
        return False
    if k in _DROP_EXACT:
        return True
    return any(t in k for t in _DROP_SUBSTRING)


def scrub_payload(obj, _depth: int = 0):
    if _depth > 12:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_pay_key(k):
                continue
            if isinstance(v, dict) and v.get("name") is not None:
                v = {kk: vv for kk, vv in v.items()
                     if kk not in ("owed", "rate", "paid", "pending")}
            out[k] = scrub_payload(v, _depth + 1)
        return out
    if isinstance(obj, list):
        return [scrub_payload(v, _depth + 1) for v in obj]
    return obj


def contributors(rows, keys=("commission_total", "owed", "commission")) -> int:
    n = 0
    for r in rows or []:
        if isinstance(r, dict) and any(float(r.get(k) or 0) > 0 for k in keys):
            n += 1
    return n


def hide_single_person_total(rows: list, value_key: str = "commission") -> bool:
    """For a non-finance viewer: a total only one person contributed to IS
    that person's pay."""
    return len([r for r in (rows or [])
                if float((r or {}).get(value_key) or 0) > 0]) == 1


def scrub_person_pay(rows: list, keys=("commission",)) -> list:
    out = []
    for r in rows or []:
        c = dict(r)
        for k in keys:
            c.pop(k, None)
        out.append(c)
    return out


def scrubbed_for(actor_role: str, payload):
    """R-PIOLO-PARITY: owner AND finance see the payload untouched; any
    other role that ever reaches it gets per-person pay removed and is told
    so."""
    if actor_role in ("owner", "coo"):
        return payload
    out = scrub_payload(payload)
    if isinstance(out, dict):
        out["comp_scope"] = "owner-only"
        out["comp_scope_note"] = ("Per-person pay is limited to the owner and "
                                  "the finance role.")
    return out
