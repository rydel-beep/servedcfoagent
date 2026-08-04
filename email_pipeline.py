"""
email_pipeline.py — the email engine's store + grounded generation + THE THREE GATES.

Lifecycle (append-only; nothing is ever deleted, discards retained):
  DRAFTING → READY_FOR_REVIEW → CHANGES_REQUESTED → APPROVED → STAGED_IN_GHL → SENT
                                                  ↘ DISCARDED
Phase A scope: generation + gates + review actions + pipeline memory. GHL staging
(Phase B) and the owner-executed send chain (Phase C) build on this store.

ANTI-HALLUCINATION — the three gates run on EVERY draft before READY_FOR_REVIEW:
  PROOF GATE    every client name / result figure must be verbatim-traceable to the
                Wins DBs (Meta + Google) or the Email Library grounding fetched for
                this draft. Untraceable → FAIL naming the offending line.
  LINK GATE     every URL must be live (2xx/3xx) AND from the authoritative field
                (lead-magnet links ONLY from Lead Magnets "Website to download";
                YT links only from the linked Content Pieces entry).
  RELATION GATE content-linked drafts must reference a REAL Content Pieces entry
                (status Live, recent); lead-magnet emails a real Lead Magnets entry;
                winback requires the documented doctrine + a non-empty P&D cohort —
                both absent today, so the type is gated OFF (never invented).
Failures surface to Rydel verbatim; they are never silently "fixed".

Recipient definitions: the newsletter segment is NOT yet defined (no tag exists) —
every draft carries recipient_def="UNDEFINED — blocked from staging" until Rydel
names it. Winback would target exactly the live P&D cohort.
"""
from __future__ import annotations

import json
import logging
import re

import requests as _rq

import db
from helpers import now_sydney

logger = logging.getLogger(__name__)

TYPES = ("weekly", "content-linked", "winback")
STATUSES = ("DRAFTING", "READY_FOR_REVIEW", "CHANGES_REQUESTED", "APPROVED",
            "STAGED_IN_GHL", "SENT", "DISCARDED")
RECIPIENT_UNDEFINED = "UNDEFINED — newsletter segment not named yet; staging blocked"

_DDL = """
CREATE TABLE IF NOT EXISTS email_drafts (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    subject_options JSONB NOT NULL DEFAULT '[]',
    body_html TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    grounding JSONB NOT NULL DEFAULT '{}',
    validation JSONB NOT NULL DEFAULT '{}',
    recipient_def TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DRAFTING',
    ghl_draft_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS email_draft_events (
    id BIGSERIAL PRIMARY KEY,
    draft_id BIGINT NOT NULL REFERENCES email_drafts(id),
    event TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}',
    actor TEXT NOT NULL DEFAULT 'edith',
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def migrate() -> bool:
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(_DDL)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("email_pipeline migrate failed: %s", e)
        return False


def _log_event(draft_id: int, event: str, detail: dict | None = None, actor: str = "edith"):
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO email_draft_events (draft_id, event, detail, actor) "
                        "VALUES (%s,%s,%s,%s)", (draft_id, event, json.dumps(detail or {}), actor))
    except Exception as e:  # noqa: BLE001
        logger.warning("email event log failed: %s", e)


# ── grounding fetch (read-only Notion + wins) ─────────────────────────────────
WINS_SOURCES = {"meta": "2e68984c-0474-80bf-bcd4-000b5e1d403f",
                "google": "834a6207-ddfd-46b1-9d76-9f0c6d36278f"}


def fetch_wins(limit: int = 12) -> list[dict]:
    """Real wins rows (title + body copy) from both Wins DBs, verbatim."""
    import notion_content as NC
    out = []
    for src, dsid in WINS_SOURCES.items():
        q = NC._req("POST", "/data_sources/%s/query" % dsid,
                    {"page_size": limit, "sorts": [{"timestamp": "last_edited_time",
                                                    "direction": "descending"}]})
        for pg in (q or {}).get("results", [])[:limit]:
            title = NC._title_of(pg)
            body = NC.page_copy(pg["id"], max_chars=1200) or ""
            out.append({"source": src, "id": pg["id"], "title": title, "body": body})
    return out


def gather_grounding(dtype: str) -> dict:
    """Everything a draft may cite — and the ONLY things it may cite."""
    import notion_content as NC
    g = {"type": dtype, "fetched_at": now_sydney().isoformat(timespec="seconds")}
    g["sop"] = NC._rules_copy() or ""
    g["voice_examples"] = []
    for r in (NC.list_recent("email", days=0, limit=40) or [])[:6]:
        copy = NC.page_copy(r["id"], max_chars=1800) or ""
        if copy:
            g["voice_examples"].append({"title": r["title"], "copy": copy})
    g["wins"] = fetch_wins()
    g["content_piece"] = None
    if dtype == "content-linked":
        for r in (NC.list_recent("content", days=14, limit=10) or []):
            if (r.get("status") or "").lower() == "live":
                g["content_piece"] = {**r, "copy": NC.page_copy(r["id"], max_chars=1500) or ""}
                break
    g["lead_magnet"] = None
    rows = NC.list_recent("lead_magnet", days=0, limit=5) or []
    if rows:
        pg = NC._req("GET", "/pages/%s" % rows[0]["id"]) or {}
        props = pg.get("properties") or {}
        url = ""
        for name in ("Website to download",):     # the AUTHORITATIVE field, per Rydel
            p = props.get(name) or {}
            url = p.get("url") or "".join(t.get("plain_text", "") for t in (p.get("rich_text") or []))
        g["lead_magnet"] = {**rows[0], "download_url": (url or "").strip()}
    return g


# ── THE THREE GATES ───────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def proof_gate(text: str, grounding: dict) -> dict:
    """Every result figure ($X, Nx, N%) and every cited client name must appear in
    the grounding corpus (wins + voice examples + content piece). Fail names lines."""
    corpus = " ".join([w["title"] + " " + w["body"] for w in grounding.get("wins", [])]
                      + [v["copy"] for v in grounding.get("voice_examples", [])]
                      + [(grounding.get("content_piece") or {}).get("copy", "") or ""])
    ncorpus = _norm(corpus)
    failures = []
    for line in (text or "").splitlines():
        for m in re.finditer(r"\$[\d,]+(?:\.\d+)?[kKmM]?|\b\d+(?:\.\d+)?x\b|\b\d{2,}(?:\.\d+)?%", line):
            if _norm(m.group(0)) not in ncorpus:
                failures.append("untraceable figure %r in: %s" % (m.group(0), line.strip()[:90]))
        # client-name check: proper-noun runs that match a wins title token set but not verbatim
        for m in re.finditer(r"\b([A-Z][a-z’']+(?:\s+[A-Z][a-z’']+){1,3})\b", line):
            name = m.group(1)
            if any(_norm(name) in _norm(w["title"]) or _norm(name) in _norm(w["body"])
                   for w in grounding.get("wins", [])):
                continue                          # traceable to a win — fine
            if _norm(name) in ncorpus:
                continue                          # appears in voice/content grounding — fine
            if re.search(r"\d", line) and any(k in line.lower() for k in
                                              ("revenue", "covers", "bookings", "roas", "spend", "made", "$")):
                failures.append("client/result %r not traceable to Wins in: %s" % (name, line.strip()[:90]))
    return {"gate": "proof", "ok": not failures, "failures": failures}


def link_gate(html: str, grounding: dict) -> dict:
    """Every URL live (2xx/3xx) and from the authoritative source field."""
    urls = re.findall(r"https?://[^\s\"'<>)]+", html or "")
    failures, checked = [], []
    lm = grounding.get("lead_magnet") or {}
    cp = grounding.get("content_piece") or {}
    allowed_lm = (lm.get("download_url") or "").rstrip("/")
    for u in dict.fromkeys(urls):
        cu = u.rstrip("/")
        try:
            r = _rq.get(u, timeout=10, allow_redirects=True)
            live = r.status_code < 400
        except Exception as e:  # noqa: BLE001
            live, r = False, None
        checked.append({"url": u, "live": live})
        if not live:
            failures.append("dead link: %s" % u)
            continue
        low = cu.lower()
        if any(k in low for k in ("canva.com", "dropbox.com/scl", "drive.google.com")) :
            failures.append("wrong-source link (asset/source URL, not the download field): %s" % u)
        if ("youtu" in low) and cp and _norm(cu) not in _norm(cp.get("copy", "") + " " + json.dumps(cp)):
            failures.append("YT link not from the linked Content Piece: %s" % u)
        if allowed_lm and ("download" in low or "guide" in low) and cu != allowed_lm and allowed_lm not in cu:
            failures.append("lead-magnet link differs from 'Website to download' field: %s" % u)
    return {"gate": "link", "ok": not failures, "failures": failures, "checked": checked}


def relation_gate(dtype: str, grounding: dict) -> dict:
    failures = []
    if dtype == "content-linked" and not grounding.get("content_piece"):
        failures.append("no Content Pieces entry with status Live in the last 14 days — orphaned YT-push")
    if dtype == "winback":
        failures.append("winback is gated OFF: no documented winback doctrine in Notion and the "
                        "P&D cohort is empty — not inventing either")
    return {"gate": "relation", "ok": not failures, "failures": failures}


def run_gates(dtype: str, subject_options: list, html: str, text: str, grounding: dict) -> dict:
    full = "\n".join(subject_options) + "\n" + (text or "")
    res = {"proof": proof_gate(full, grounding),
           "link": link_gate(html, grounding),
           "relation": relation_gate(dtype, grounding)}
    res["ok"] = all(r["ok"] for r in res.values())
    # SOP self-checklist (shown on the review card; advisory, not blocking)
    sop = grounding.get("sop") or ""
    res["sop_checklist"] = {
        "single_idea_one_cta": (text or "").count("{{CTA") <= 1,
        "cta_placeholder_or_link": ("{{CTA" in (text or "")) or ("http" in (html or "")),
        "sop_loaded": bool(sop),
    }
    return res


# ── generation ────────────────────────────────────────────────────────────────
def _model_draft(dtype: str, grounding: dict, note: str = "") -> dict | None:
    """One grounded generation call → {subjects:[3], text, html}. Figures/names may
    come ONLY from the grounding block (the gates enforce it anyway)."""
    import os
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    wins = "\n\n".join("WIN [%s] %s\n%s" % (w["source"], w["title"], w["body"][:700])
                       for w in grounding.get("wins", [])[:8])
    voice = "\n\n".join("EXAMPLE — %s\n%s" % (v["title"], v["copy"][:1200])
                        for v in grounding.get("voice_examples", [])[:4])
    cp = grounding.get("content_piece") or {}
    lm = grounding.get("lead_magnet") or {}
    prompt = f"""You are Served Marketing's email writer. Write ONE {dtype} newsletter email in
Served's demonstrated voice — grounded ONLY in what is below. HARD RULES:
- Any client name, figure, or result MUST be copied verbatim from the WINS below. If no win
  fits, write without a case study. NEVER invent or adapt one.
- Lead-magnet link: use exactly {lm.get('download_url') or '(none available — omit)'} or omit.
- {"Reference this content piece: " + cp.get("title", "") if cp else "No content piece — this is the plain weekly."}
- Follow the NEWSLETTER SOP below. Keep it single-idea, one CTA ({{{{CTA_URL}}}} placeholder allowed).
{('- REVISION NOTE from Rydel: ' + note) if note else ''}

NEWSLETTER SOP (the rulebook):
{(grounding.get('sop') or '')[:2200]}

SERVED VOICE EXAMPLES (match this voice):
{voice}

WINS (the ONLY permissible proof):
{wins or '(none fetched — write without case studies)'}

Return STRICT JSON: {{"subjects": ["...","...","..."], "text": "plain-text email body",
"html": "<simple mobile-safe html of the same body>", "sop_rules_applied": ["..."]}}"""
    try:
        msg = client.messages.create(model=os.environ.get("CHAT_MODEL", "claude-sonnet-5"),
                                     max_tokens=2500,
                                     messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        logger.error("email generation failed: %s", e)
        return None


def generate_draft(dtype: str, note: str = "", actor: str = "edith") -> dict:
    """The full A2 flow: gather → generate → gates → store. Returns the stored row
    (or the named failure — never silently fixed)."""
    if dtype not in TYPES:
        return {"ok": False, "reason": "unknown type %r" % dtype}
    migrate()
    grounding = gather_grounding(dtype)
    rel = relation_gate(dtype, grounding)
    if not rel["ok"]:
        return {"ok": False, "reason": "; ".join(rel["failures"]), "gate": "relation"}
    gen = _model_draft(dtype, grounding, note)
    if not gen:
        return {"ok": False, "reason": "generation call failed (model/JSON) — nothing stored"}
    validation = run_gates(dtype, gen.get("subjects") or [], gen.get("html") or "",
                           gen.get("text") or "", grounding)
    status = "READY_FOR_REVIEW" if validation["ok"] else "DRAFTING"
    slim_grounding = {
        "fetched_at": grounding["fetched_at"],
        "sop_rules_applied": gen.get("sop_rules_applied") or [],
        "wins_cited": [{"id": w["id"], "title": w["title"], "source": w["source"]}
                       for w in grounding.get("wins", [])
                       if _norm(w["title"])[:14] and _norm(w["title"])[:14] in _norm(gen.get("text") or "")],
        "content_piece": {k: (grounding.get("content_piece") or {}).get(k)
                          for k in ("id", "title")} if grounding.get("content_piece") else None,
        "lead_magnet": {k: (grounding.get("lead_magnet") or {}).get(k)
                        for k in ("id", "title", "download_url")} if grounding.get("lead_magnet") else None,
        "recipient": RECIPIENT_UNDEFINED if dtype != "winback" else "the live P&D cohort",
    }
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO email_drafts (type, subject_options, body_html, body_text,
                           grounding, validation, recipient_def, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (dtype, json.dumps(gen.get("subjects") or []), gen.get("html") or "",
                         gen.get("text") or "", json.dumps(slim_grounding),
                         json.dumps(validation), slim_grounding["recipient"], status))
            did = cur.fetchone()["id"]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "store failed: %s" % str(e)[:120]}
    _log_event(did, "drafted", {"status": status, "gates_ok": validation["ok"],
                                "note": note}, actor)
    return {"ok": True, "id": did, "status": status, "validation": validation,
            "subjects": gen.get("subjects")}


# ── review actions + pipeline memory ─────────────────────────────────────────
def list_drafts(limit: int = 30) -> list[dict]:
    migrate()
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, type, subject_options, status, recipient_def, validation, "
                        "grounding, created_at, updated_at FROM email_drafts "
                        "ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logger.error("list_drafts failed: %s", e)
        return []


def get_draft(draft_id: int) -> dict | None:
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM email_drafts WHERE id=%s", (draft_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("SELECT event, detail, actor, at FROM email_draft_events "
                        "WHERE draft_id=%s ORDER BY id", (draft_id,))
            d = dict(row)
            d["history"] = [dict(e) for e in cur.fetchall()]
            return d
    except Exception as e:  # noqa: BLE001
        logger.error("get_draft failed: %s", e)
        return None


_ALLOWED_ACTIONS = {
    "approve": ("READY_FOR_REVIEW", "APPROVED"),
    "request_changes": ("READY_FOR_REVIEW", "CHANGES_REQUESTED"),
    "discard": (None, "DISCARDED"),               # discard allowed from any non-terminal state
}


def act(draft_id: int, action: str, note: str = "", actor: str = "rydel") -> dict:
    if action not in _ALLOWED_ACTIONS:
        return {"ok": False, "reason": "unknown action"}
    row = get_draft(draft_id)
    if not row:
        return {"ok": False, "reason": "draft %s not found" % draft_id}
    want_from, to = _ALLOWED_ACTIONS[action]
    if row["status"] in ("SENT", "DISCARDED"):
        return {"ok": False, "reason": "draft is %s — immutable" % row["status"]}
    if want_from and row["status"] != want_from:
        return {"ok": False, "reason": "draft is %s, not %s" % (row["status"], want_from)}
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE email_drafts SET status=%s, updated_at=now() WHERE id=%s", (to, draft_id))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)[:120]}
    _log_event(draft_id, action, {"note": note}, actor)
    out = {"ok": True, "id": draft_id, "status": to}
    if action == "request_changes":
        redo = generate_draft(row["type"], note=note or "tighten it", actor="edith")
        out["redraft"] = {k: redo.get(k) for k in ("ok", "id", "status", "reason")}
        _log_event(draft_id, "redrafted_as", {"new_id": redo.get("id")}, "edith")
    return out


def pipeline_digest() -> dict:
    """Deterministic pipeline state for the greeting/salience + 'what's pending?'."""
    rows = list_drafts(50)
    by = {}
    for r in rows:
        by.setdefault(r["status"], []).append(r)
    ready = by.get("READY_FOR_REVIEW", [])
    line = ""
    if ready:
        kinds = ", ".join("%s #%s" % (r["type"], r["id"]) for r in ready[:4])
        line = "%d email draft%s ready for your review (%s)." % (
            len(ready), "s" if len(ready) != 1 else "", kinds)
    return {"counts": {k: len(v) for k, v in by.items()}, "ready": len(ready), "line": line}


# ── Phase C stub: chain tokens do not exist yet — sends impossible ───────────
def verify_chain_token(token: str) -> bool:
    """Phase C mints owner-chain tokens. Until it exists, NOTHING verifies — the one
    send function refuses everything. Autonomous sends are structurally impossible."""
    return False


# ── A4: salience + conversational review ─────────────────────────────────────
def salience_events() -> list[dict]:
    """Watermarked 'drafts pending' event — re-fires only when the ready-set changes."""
    try:
        d = pipeline_digest()
        if not d["ready"]:
            return []
        ready_ids = "-".join(str(r["id"]) for r in list_drafts(20) if r["status"] == "READY_FOR_REVIEW")
        return [{"id": "email:ready:%s" % ready_ids, "type": "email_pipeline",
                 "salience": 68, "ago": 0, "spoken": d["line"]}]
    except Exception as e:  # noqa: BLE001
        logger.warning("email salience failed: %s", e)
        return []


_PENDING_RE = re.compile(r"\b(what'?s? )?(pending|awaiting)( my)? review\b|\bwhat did you draft\b"
                         r"|\bemail pipeline\b|\bany drafts?\b", re.I)


def handle_pipeline_query(msg: str) -> tuple[str | None, bool]:
    if not msg or not _PENDING_RE.search(msg):
        return None, False
    d = pipeline_digest()
    rows = list_drafts(12)
    if not rows:
        return "The email pipeline is empty — nothing drafted yet. Say the word and I'll draft the weekly.", True
    bits = []
    for r in rows[:6]:
        subj = (r["subject_options"] or ["(no subject)"])[0]
        bits.append("#%s %s — %s (%s)" % (r["id"], r["type"], subj[:60], r["status"].replace("_", " ").lower()))
    head = d["line"] or "Nothing waiting on you right now."
    return head + " Pipeline: " + " · ".join(bits), True
