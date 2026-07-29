"""
test_leads.py
-------------
The ONE canonical test-lead classification layer (the one-engine lesson). A test lead is one the
team created while testing forms/funnels — it must be VOIDED from every sales metric but NEVER
deleted (excluded != deleted; always auditable).

Design rules:
1. ONE classification engine here; ONE clean view (leads_clean helpers). Consumers read the clean
   view, never re-implement the filter.
2. REVIEW-FIRST: substring "test" is a false-positive trap ("Testaccio Trattoria" is a real venue).
   So classification has two strengths: STRONG (staff tokens / explicit test tag / clear test email)
   auto-voids; BORDERLINE (substring "test" in a plausible name) defaults to KEEP and goes to a
   review queue. Manual overrides outrank rules forever and survive re-syncs.

Token rule set is persisted + editable (manual-inputs pattern). Overrides persisted in kv_store.
Nothing here filters a metric — it only classifies; the clean view is what consumers repoint to,
and only AFTER Rydel confirms the first pass.
"""
from __future__ import annotations

import logging
import re

import kv_store

logger = logging.getLogger(__name__)

# Persisted, editable rule set. Staff tokens are SAFE anywhere in an email/name (internal people).
_DEFAULT_RULES = {
    "staff_tokens": ["rydel", "jaspher"],   # internal — match anywhere (email or name)
    "test_tokens": ["test"],                # test — STRONG only in test-shaped positions, else borderline
    "enabled": True,
}
_K_RULES = "testleads:rules"
_K_OVERRIDES = "testleads:overrides"        # {lead_key: {"is_test": bool, "by": user, "at": date}}


def rules() -> dict:
    r = kv_store.get(_K_RULES) or {}
    out = dict(_DEFAULT_RULES)
    out.update({k: v for k, v in r.items() if v is not None})
    return out


def set_rules(new: dict) -> None:
    kv_store.put(_K_RULES, new)


def lead_key(source: str, email: str = "", name: str = "", ext_id: str = "") -> str:
    """Stable key for overrides — prefers an external id, else source+email+name."""
    base = ext_id or f"{(email or '').strip().lower()}|{(name or '').strip().lower()}"
    return f"{source}:{base}"


def _overrides() -> dict:
    return kv_store.get(_K_OVERRIDES) or {}


def set_override(key: str, is_test: bool, by: str) -> None:
    from helpers import today_sydney
    ov = _overrides()
    ov[key] = {"is_test": bool(is_test), "by": by, "at": str(today_sydney())}
    kv_store.put(_K_OVERRIDES, ov)


def classify(email: str = "", name: str = "", business: str = "", tags="",
             source: str = "", ext_id: str = "") -> dict:
    """Return {is_test, strength, rule, source_of_truth}. A manual override wins outright."""
    r = rules()
    key = lead_key(source, email, name, ext_id)
    ov = _overrides().get(key)
    if ov is not None:
        return {"is_test": ov["is_test"], "strength": "override", "rule": f"manual ({ov['by']})",
                "source_of_truth": "override", "key": key}
    if not r.get("enabled", True):
        return {"is_test": False, "strength": None, "rule": None, "source_of_truth": "rules-disabled", "key": key}

    el = str(email or "").lower()
    loc = el.split("@", 1)[0] if "@" in el else el
    nm = str(name or "").lower().strip()
    tg = ",".join(tags).lower() if isinstance(tags, list) else str(tags or "").lower()

    # STRONG: staff tokens anywhere (internal people testing under any lead name)
    for s in r.get("staff_tokens", []):
        if s and (s in el or s in nm):
            return {"is_test": True, "strength": "strong", "rule": f"staff token '{s}'",
                    "source_of_truth": "rule", "key": key}
    # STRONG: explicit GHL test tag
    if "test" in tg:
        return {"is_test": True, "strength": "strong", "rule": "GHL test tag", "source_of_truth": "rule", "key": key}
    # STRONG: test-shaped email localpart (test@, test.x@, x+test@, test123@)
    if re.search(r"(^|[._+\-])test([._+\-]|\d|$)", loc):
        return {"is_test": True, "strength": "strong", "rule": "test-email localpart",
                "source_of_truth": "rule", "key": key}
    # STRONG: whole-word / leading "test" in the name
    if re.search(r"\btest(ing)?\b", nm) or nm in ("test", "testing") or re.match(r"^test[\s\-_]", nm):
        return {"is_test": True, "strength": "strong", "rule": "whole-word 'test' in name",
                "source_of_truth": "rule", "key": key}
    # BORDERLINE: substring "test" in a longer plausible token (Testaccio, attestation@) → KEEP, review
    hay = f"{el} {nm} {str(business or '').lower()}"
    if "test" in hay:
        return {"is_test": False, "strength": "borderline", "rule": "substring 'test' (plausible — review)",
                "source_of_truth": "rule-borderline", "key": key}
    return {"is_test": False, "strength": None, "rule": None, "source_of_truth": "clean", "key": key}


def _mask(e: str) -> str:
    e = str(e or "")
    if "@" in e:
        u, d = e.split("@", 1)
        return (u[:3] + "***@" + d)
    return (e[:3] + "***") if len(e) > 3 else e


def scan() -> dict:
    """Read-only classification over BOTH mirrors → candidate lists (strong + borderline) + impact
    preview. Filters nothing; this is the Phase-0 review artifact."""
    ghl_strong, ghl_border = [], []
    tr_strong, tr_border = [], []

    # ── GHL mirror (contacts joined to opps for names/stage) ──
    try:
        import ghl_mirror
        contacts = ghl_mirror.read_all_contacts()
        opps = ghl_mirror.read_opportunities(open_only=False)
        # index one opp name/stage per contact for display
        by_contact = {}
        for o in opps:
            cid = o.get("contact_id")
            if cid and cid not in by_contact:
                by_contact[cid] = o
        for cid, c in contacts.items():
            email = c.get("email") or ""
            name = " ".join(x for x in [c.get("first_name"), c.get("last_name")] if x) or ""
            tags = c.get("tags") or []
            r = classify(email=email, name=name, business="", tags=tags, source="ghl", ext_id=cid)
            if r["strength"] in ("strong", "override") and r["is_test"]:
                ghl_strong.append({"name": name or "(no name)", "email": _mask(email),
                                   "stage": (by_contact.get(cid) or {}).get("stage_name"),
                                   "rule": r["rule"], "key": r["key"]})
            elif r["strength"] == "borderline":
                ghl_border.append({"name": name or "(no name)", "email": _mask(email),
                                   "stage": (by_contact.get(cid) or {}).get("stage_name"),
                                   "rule": r["rule"], "key": r["key"]})
    except Exception as e:
        logger.info("scan GHL failed: %s", e)

    # ── Tracker mirror (Lead-to-Cash rows) ──
    tracker_total = 0
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name("Lead-to-Cash Tracker") or []
        if rows:
            hi = next((i for i, rr in enumerate(rows[:8]) if any("lead name" in (c or "").lower() for c in rr)), 0)
            hdr = [(c or "").lower() for c in rows[hi]]
            def col(*names):
                for nm in names:
                    for i, h in enumerate(hdr):
                        if nm in h:
                            return i
                return None
            ce, cn, cb, cdt = col("email"), col("lead name"), col("business name", "business"), col("input date")
            for rr in rows[hi + 1:]:
                def g(i):
                    return rr[i].strip() if (i is not None and i < len(rr)) else ""
                nm = g(cn)
                if not nm:
                    continue
                tracker_total += 1
                r = classify(email=g(ce), name=nm, business=g(cb), source="tracker")
                rec = {"name": nm, "business": g(cb), "email": _mask(g(ce)), "date": g(cdt),
                       "rule": r["rule"], "key": r["key"]}
                if r["strength"] in ("strong", "override") and r["is_test"]:
                    tr_strong.append(rec)
                elif r["strength"] == "borderline":
                    tr_border.append(rec)
    except Exception as e:
        logger.info("scan tracker failed: %s", e)

    return {
        "rules": rules(),
        "ghl": {"strong": ghl_strong, "borderline": ghl_border, "total_contacts": len(ghl_strong) + len(ghl_border)},
        "tracker": {"strong": tr_strong, "borderline": tr_border, "total_leads": tracker_total},
        "summary": {"ghl_strong": len(ghl_strong), "ghl_borderline": len(ghl_border),
                    "tracker_strong": len(tr_strong), "tracker_borderline": len(tr_border),
                    "tracker_total": tracker_total},
    }
