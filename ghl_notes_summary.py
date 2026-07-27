"""
ghl_notes_summary.py
--------------------
GROUNDED "where it left off" summaries (Phase 3). For a reactivation candidate, the model reads
THAT LEAD'S ACTUAL NOTES (from the mirror) + its stage/dates and writes a 2-3 sentence recap, the
last meaningful interaction, and one suggested reactivation angle — using ONLY what the notes say.

HARD GROUNDING RULES:
- No notes → deterministic "no notes logged — cold reactivation" WITHOUT calling the model (a lead
  with no history cannot be given a backstory). It's also counted in the notes-hygiene stat.
- With notes → the model is instructed to use only facts present in the notes, reference note dates,
  and invent nothing. The composer wraps provided facts (the greeting-composer discipline).
- Cached per lead keyed on a hash of its notes; regenerated only when the notes change (cost-aware).

PII: note bodies live only in the auth-gated mirror; summaries are stored in Postgres (auth-gated),
never in memory_facts, never logged plaintext.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

import db
import ghl_mirror
from config import CHAT_MODEL

logger = logging.getLogger(__name__)

import os
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_MAX_NOTE_CHARS = 9000     # cap per lead (most-recent-first) — cost-aware

_DDL = """
CREATE TABLE IF NOT EXISTS ghl_lead_summaries (
    contact_id      TEXT PRIMARY KEY,
    notes_hash      TEXT,
    no_notes        BOOLEAN NOT NULL DEFAULT FALSE,
    where_left_off  TEXT,
    last_interaction TEXT,
    angle           TEXT,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("ghl_notes_summary migrate failed: %s", e)
        return False


def _notes_hash(notes: list[dict]) -> str:
    h = hashlib.sha1()
    for n in notes:
        h.update((n.get("body_hash") or hashlib.sha1((n.get("body") or "").encode()).hexdigest()).encode())
    return h.hexdigest()


def _cached(contact_id: str, notes_hash: str) -> dict | None:
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT * FROM ghl_lead_summaries WHERE contact_id=%s", (contact_id,)).fetchone()
            if r and r["notes_hash"] == notes_hash:
                return dict(r)
    except Exception as e:
        logger.info("summary cache read failed: %s", e)
    return None


def _store(contact_id: str, notes_hash: str, no_notes: bool, wlo: str, last: str, angle: str) -> None:
    try:
        with db.get_conn() as c:
            c.execute(
                """INSERT INTO ghl_lead_summaries (contact_id, notes_hash, no_notes, where_left_off, last_interaction, angle, generated_at)
                   VALUES (%s,%s,%s,%s,%s,%s, now())
                   ON CONFLICT (contact_id) DO UPDATE SET
                     notes_hash=EXCLUDED.notes_hash, no_notes=EXCLUDED.no_notes,
                     where_left_off=EXCLUDED.where_left_off, last_interaction=EXCLUDED.last_interaction,
                     angle=EXCLUDED.angle, generated_at=now()""",
                (contact_id, notes_hash, no_notes, wlo, last, angle))
    except Exception as e:
        logger.info("summary store failed: %s", e)


_SYSTEM = (
    "You summarize a sales lead's history for a reactivation brief. You are given ONLY that lead's "
    "real CRM notes plus its pipeline stage and dates. Absolute rules:\n"
    "- Use ONLY facts written in the notes. Never invent names, events, dates, numbers, or sentiment "
    "that are not in the notes.\n"
    "- Reference the note dates where relevant. If the notes don't establish something, do not claim it.\n"
    "- Be concrete and specific to THIS lead — no generic filler.\n"
    "Return STRICT JSON: {\"where_it_left_off\": \"2-3 sentences\", \"last_interaction\": "
    "\"date + what happened\", \"reactivation_angle\": \"one specific, grounded next move\"}."
)


def _compose(lead: dict, notes: list[dict]) -> dict | None:
    """Call the model with the lead's real notes. Returns parsed dict or None on failure."""
    if not ANTHROPIC_API_KEY:
        return None
    # most-recent-first, capped
    ordered = sorted(notes, key=lambda n: str(n.get("date_added") or ""), reverse=True)
    buf, total = [], 0
    for n in ordered:
        body = (n.get("body") or "").strip()
        if not body:
            continue
        chunk = f"[{str(n.get('date_added'))[:10]}] {body}"
        if total + len(chunk) > _MAX_NOTE_CHARS:
            chunk = chunk[: max(0, _MAX_NOTE_CHARS - total)]
        buf.append(chunk)
        total += len(chunk)
        if total >= _MAX_NOTE_CHARS:
            break
    notes_block = "\n\n".join(buf) if buf else "(no notes)"
    user = (f"Lead stage: {lead.get('stage')}\nValue: ${lead.get('value')}\n"
            f"Created: {lead.get('created')}\nLast touch: {lead.get('last_touch')}\n\n"
            f"NOTES (most recent first):\n{notes_block}")
    for attempt in range(3):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(model=CHAT_MODEL, max_tokens=400, temperature=0.2,
                                           system=_SYSTEM, messages=[{"role": "user", "content": user}])
            txt = resp.content[0].text if resp.content else ""
            s = txt.find("{"); e = txt.rfind("}")
            if s >= 0 and e > s:
                return json.loads(txt[s:e + 1])
            return None
        except Exception as ex:
            if "529" in str(ex) or "overloaded" in str(ex).lower():
                time.sleep(1.5 * (attempt + 1)); continue
            logger.info("notes summary compose failed: %s", ex)
            return None
    return None


def summarize_lead(lead: dict, force: bool = False) -> dict:
    """Grounded summary for one lead (cached; regenerated only when notes change). `lead` needs
    contact_id + stage/value/created/last_touch."""
    migrate()
    cid = lead.get("contact_id")
    notes = ghl_mirror.read_notes_for_contact(cid) if cid else []
    # NO NOTES → deterministic, no model, no backstory possible
    if not notes:
        out = {"contact_id": cid, "no_notes": True,
               "where_it_left_off": "No notes logged — cold reactivation (no recorded history).",
               "last_interaction": None, "reactivation_angle": None, "cached": False}
        if cid:
            _store(cid, "NONOTES", True, out["where_it_left_off"], None, None)
        return out

    nh = _notes_hash(notes)
    if not force and cid:
        c = _cached(cid, nh)
        if c:
            return {"contact_id": cid, "no_notes": c["no_notes"],
                    "where_it_left_off": c["where_left_off"], "last_interaction": c["last_interaction"],
                    "reactivation_angle": c["angle"], "cached": True}

    parsed = _compose(lead, notes)
    if not parsed:
        # honest degradation — never fabricate; report that a summary couldn't be produced
        return {"contact_id": cid, "no_notes": False,
                "where_it_left_off": f"{len(notes)} note(s) on file — summary unavailable right now "
                                     "(model/timeout). The notes are in the mirror; retry generation.",
                "last_interaction": str(notes[-1].get("date_added"))[:10] if notes else None,
                "reactivation_angle": None, "cached": False, "degraded": True}
    wlo = parsed.get("where_it_left_off"); last = parsed.get("last_interaction"); angle = parsed.get("reactivation_angle")
    if cid:
        _store(cid, nh, False, wlo, last, angle)
    return {"contact_id": cid, "no_notes": False, "where_it_left_off": wlo,
            "last_interaction": last, "reactivation_angle": angle, "cached": False}


def summarize_batch(leads: list[dict], cap: int = 60) -> list[dict]:
    """Grounded summaries for up to `cap` leads (top of the ranked list). Cached ones are free."""
    out = []
    for lead in leads[:cap]:
        s = summarize_lead(lead)
        out.append({**lead, "summary": s})
    return out
