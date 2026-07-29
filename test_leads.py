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


def load_ctx() -> tuple[dict, dict]:
    """Load (rules, overrides) ONCE — pass to classify() in loops so bulk classification does not hit
    the DB per row (the clean views classify 1000s of rows)."""
    return rules(), _overrides()


def classify(email: str = "", name: str = "", business: str = "", tags="",
             source: str = "", ext_id: str = "", ctx: tuple | None = None) -> dict:
    """Return {is_test, strength, rule, source_of_truth}. A manual override wins outright. Pass
    ctx=load_ctx() in bulk loops to avoid a per-row DB read."""
    r, ov_all = ctx if ctx else load_ctx()
    key = lead_key(source, email, name, ext_id)
    ov = ov_all.get(key)
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


# ── THE CLEAN VIEWS (the only thing consumers may read for metrics) ──────────

def is_test_contact(contact: dict | None, source: str = "ghl", ctx: tuple | None = None) -> bool:
    """Is this GHL contact a test lead? (email/name/tags via the one engine + overrides). Pass ctx in
    bulk loops."""
    if not contact:
        return False
    name = " ".join(x for x in [contact.get("first_name"), contact.get("last_name")] if x) or ""
    return classify(email=contact.get("email") or "", name=name, tags=contact.get("tags") or [],
                    source=source, ext_id=contact.get("id") or "", ctx=ctx).get("is_test", False)


def _tracker_cols(rows: list) -> tuple[int, int, int, int]:
    hi = next((i for i, rr in enumerate(rows[:8]) if any("lead name" in (c or "").lower() for c in rr)), 0)
    hdr = [(c or "").lower() for c in rows[hi]]
    def col(*names):
        for nm in names:
            for i, h in enumerate(hdr):
                if nm in h:
                    return i
        return None
    return hi, col("email"), col("lead name"), col("business name", "business")


def clean_tracker_rows(rows: list | None) -> list:
    """Return the tracker rows with test-lead DATA rows removed (header preserved). THE clean tracker
    view — leads_view and range_unit_economics repoint here. Non-destructive: the mirror keeps all
    rows; this only filters what metrics see."""
    if not rows:
        return rows or []
    try:
        ctx = load_ctx()   # load rules+overrides ONCE (not per row)
        hi, ce, cn, cb = _tracker_cols(rows)
        out = list(rows[:hi + 1])   # keep everything up to + including the header
        for rr in rows[hi + 1:]:
            def g(i):
                return rr[i].strip() if (i is not None and i < len(rr)) else ""
            name = g(cn)
            if name and classify(email=g(ce), name=name, business=g(cb), source="tracker", ctx=ctx).get("is_test"):
                continue   # void the test row from the clean view
            out.append(rr)
        return out
    except Exception as e:
        logger.info("clean_tracker_rows failed (returning raw): %s", e)
        return rows


def confirm_first_pass(by: str = "rydel") -> None:
    """Record that Rydel confirmed the first classification pass (enables consumer repoints)."""
    from helpers import today_sydney
    kv_store.put("testleads:confirmed", {"by": by, "at": str(today_sydney())})


def is_confirmed() -> bool:
    return bool(kv_store.get("testleads:confirmed"))


def _mask(e: str) -> str:
    e = str(e or "")
    if "@" in e:
        u, d = e.split("@", 1)
        return (u[:3] + "***@" + d)
    return (e[:3] + "***") if len(e) > 3 else e


# ── EDITH commands: "what's excluded as test?" / "mark X as test|real" / "add token" ──
import re as _re

_WHATS_EXCLUDED = _re.compile(r"\b(what'?s|which leads?|show).{0,20}\b(excluded|voided|test leads?)\b"
                              r"|\btest[- ]?leads?\b.{0,15}\b(excluded|list|audit)\b", _re.I)
_MARK = _re.compile(r"\bmark\s+(.+?)\s+as\s+(a\s+)?(test|real|genuine)\b", _re.I)
_ADD_TOKEN = _re.compile(r"\badd\s+['\"]?([a-z0-9]+)['\"]?\s+(?:to\s+)?(?:the\s+)?test[- ]?(?:lead\s+)?tokens?\b", _re.I)


def handle_command(text: str, actor: dict | None = None) -> tuple[str | None, bool]:
    if not text:
        return None, False
    who = (actor or {}).get("user", "rydel")

    if _WHATS_EXCLUDED.search(text):
        s = scan()
        n = s["summary"]["ghl_strong"] + s["summary"]["tracker_strong"]
        names = [x["name"] for x in s["tracker"]["strong"][:8]] + [x["name"] for x in s["ghl"]["strong"][:4]]
        b = s["summary"]["ghl_borderline"] + s["summary"]["tracker_borderline"]
        return (f"{n} test leads are excluded from all sales metrics (e.g. {', '.join(n for n in names if n)[:180]}). "
                + (f"{b} borderline awaiting review. " if b else "")
                + "They're voided, not deleted — still in the audit view."), True

    m = _MARK.search(text)
    if m:
        name = m.group(1).strip(); verdict = m.group(3).lower()
        is_test = verdict == "test"
        # find the lead in either mirror to key the override
        key = _find_key_by_name(name)
        if not key:
            return f"I couldn't find a lead matching \"{name}\" to mark. Try their exact name.", True
        set_override(key, is_test, who)
        return (f"Marked \"{name}\" as {'a test entry — voided from metrics' if is_test else 'real — counted again'}. "
                "This override is remembered and survives re-syncs."), True

    mt = _ADD_TOKEN.search(text)
    if mt:
        tok = mt.group(1).lower()
        r = rules(); toks = list(r.get("test_tokens", []))
        if tok in toks or tok in r.get("staff_tokens", []):
            return f"'{tok}' is already a test token.", True
        # staff-looking names go to staff_tokens (match anywhere); else test_tokens
        return (f"Add '{tok}' as a test token? Say 'confirm add {tok}' — I'll apply it and re-scan. "
                "(Rule changes are confirmed, never auto-applied.)"), True
    if _re.search(r"\bconfirm add\s+([a-z0-9]+)\b", text, _re.I):
        tok = _re.search(r"\bconfirm add\s+([a-z0-9]+)\b", text, _re.I).group(1).lower()
        r = rules(); r.setdefault("staff_tokens", []).append(tok); set_rules(r)
        return f"Added '{tok}' to the staff test tokens. New/changed leads matching it will auto-void; re-scan to apply.", True

    return None, False


def _find_key_by_name(name: str) -> str | None:
    q = _re.sub(r"[^a-z0-9]", "", (name or "").lower())
    if not q:
        return None
    try:
        import ghl_mirror
        for cid, c in ghl_mirror.read_all_contacts().items():
            nm = _re.sub(r"[^a-z0-9]", "", ((c.get("first_name") or "") + (c.get("last_name") or "")).lower())
            if nm and q in nm:
                return lead_key("ghl", c.get("email") or "", nm, cid)
    except Exception:
        pass
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_name("Lead-to-Cash Tracker") or []
        hi, ce, cn, cb = _tracker_cols(rows)
        for rr in rows[hi + 1:]:
            nm = rr[cn].strip() if (cn is not None and cn < len(rr)) else ""
            if nm and q in _re.sub(r"[^a-z0-9]", "", nm.lower()):
                em = rr[ce].strip() if (ce is not None and ce < len(rr)) else ""
                return lead_key("tracker", em, nm)
    except Exception:
        pass
    return None


def scan() -> dict:
    """Read-only classification over BOTH mirrors → candidate lists (strong + borderline) + impact
    preview. Filters nothing; this is the Phase-0 review artifact."""
    ghl_strong, ghl_border = [], []
    tr_strong, tr_border = [], []
    ctx = load_ctx()   # one DB read for the whole scan

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
            r = classify(email=email, name=name, business="", tags=tags, source="ghl", ext_id=cid, ctx=ctx)
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
                r = classify(email=g(ce), name=nm, business=g(cb), source="tracker", ctx=ctx)
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
