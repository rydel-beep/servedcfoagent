"""
client_overrides.py
-------------------
Chat-driven CHURN / DOWNGRADE overrides for the client roster — a READ-LAYER on top of the
mirror, NOT a write to the Google Sheet. Rydel tells EDITH a client churned or downgraded;
EDITH records it here (Postgres) with a confirmation loop; the dashboard applies it (count +
MRR + churn recompute); and a "For Piolo" queue lists exactly what to change on the real sheet.

Design (Rydel-confirmed 2026-07-03):
- NO Google write access. The Health SHEET is untouched; EDITH overrides the DISPLAY.
- churn   → status Churned, MRR 0, exit date; the client's last MRR is kept in the audit.
- downgrade → status stays Active, MRR set to the new lower value, effective date.
- Every write is confirmed against the exact matched row first; ambiguous name → ask, never guess.
- One-command undo; full audit trail; auto-reconcile once the sheet catches up (raw == override).
"""
from __future__ import annotations

import logging
import re

import db
from helpers import today_sydney

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS client_overrides (
  id             BIGSERIAL PRIMARY KEY,
  client_name    TEXT NOT NULL,
  change_type    TEXT NOT NULL,          -- 'churn' | 'downgrade'
  old_status     TEXT,
  new_status     TEXT,
  old_mrr        REAL,
  new_mrr        REAL,
  effective_date DATE,
  reason         TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     TEXT NOT NULL DEFAULT 'Rydel',
  active         BOOLEAN NOT NULL DEFAULT TRUE,     -- FALSE = undone
  reconciled     BOOLEAN NOT NULL DEFAULT FALSE     -- TRUE = the sheet caught up
);
CREATE TABLE IF NOT EXISTS client_override_pending (
  token       TEXT PRIMARY KEY,
  payload     JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_PENDING_TTL = 600  # seconds


def migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
        return True
    except Exception as e:
        logger.warning("client_overrides migrate failed: %s", e)
        return False


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ── Store ────────────────────────────────────────────────────────────────────

def active_overrides() -> list[dict]:
    """All in-effect overrides (active, not undone, not yet reconciled to the sheet)."""
    if not db.db_configured():
        return []
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT * FROM client_overrides WHERE active AND NOT reconciled ORDER BY created_at"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("created_at",):
                if d.get(k) is not None:
                    d[k] = d[k].isoformat()
            if d.get("effective_date") is not None:
                d["effective_date"] = str(d["effective_date"])
            out.append(d)
        return out
    except Exception as e:
        logger.info("active_overrides failed: %s", e)
        return []


def active_map() -> dict[str, dict]:
    """{normalized client name: override} for fast lookup in the roster apply step."""
    return {_norm(o["client_name"]): o for o in active_overrides()}


def _add(o: dict) -> int | None:
    migrate()
    try:
        with db.get_conn() as c:
            cur = c.execute(
                """INSERT INTO client_overrides
                     (client_name, change_type, old_status, new_status, old_mrr, new_mrr,
                      effective_date, reason, created_by)
                   VALUES (%(client_name)s,%(change_type)s,%(old_status)s,%(new_status)s,
                           %(old_mrr)s,%(new_mrr)s,%(effective_date)s,%(reason)s,%(created_by)s)
                   RETURNING id""", o)
            return cur.fetchone()["id"]
    except Exception as e:
        logger.warning("client_overrides add failed: %s", e)
        return None


def undo_last() -> dict | None:
    """Reverse the most recent active override. Returns the reversed row or None."""
    if not db.db_configured():
        return None
    try:
        with db.get_conn() as c:
            row = c.execute(
                "SELECT * FROM client_overrides WHERE active AND NOT reconciled "
                "ORDER BY created_at DESC LIMIT 1").fetchone()
            if not row:
                return None
            c.execute("UPDATE client_overrides SET active=FALSE WHERE id=%s", (row["id"],))
            return dict(row)
    except Exception as e:
        logger.warning("undo_last failed: %s", e)
        return None


def undo_client(name: str) -> dict | None:
    if not db.db_configured():
        return None
    try:
        with db.get_conn() as c:
            row = c.execute(
                "SELECT * FROM client_overrides WHERE active AND NOT reconciled "
                "AND lower(client_name)=lower(%s) ORDER BY created_at DESC LIMIT 1", (name,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE client_overrides SET active=FALSE WHERE id=%s", (row["id"],))
            return dict(row)
    except Exception as e:
        logger.warning("undo_client failed: %s", e)
        return None


def audit_log(limit: int = 20) -> list[dict]:
    if not db.db_configured():
        return []
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT client_name, change_type, old_status, new_status, old_mrr, new_mrr, "
                "effective_date, created_at, active, reconciled FROM client_overrides "
                "ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Apply to the roster (dashboard reflects count + MRR + churn) ──────────────

def apply_to_clients(clients: list[dict]) -> tuple[list[dict], float, int]:
    """Given the raw active-client list (name + current_mrr), apply overrides.
    Returns (adjusted_clients, mrr_delta, active_delta). Churn removes the client (and its MRR);
    downgrade lowers its MRR. Used by the roster pull so count/MRR/churn recompute."""
    omap = active_map()
    if not omap:
        return clients, 0.0, 0
    out, mrr_delta, active_delta = [], 0.0, 0
    for c in clients:
        o = omap.get(_norm(c.get("name", "")))
        if not o:
            out.append(c)
            continue
        cur_mrr = c.get("current_mrr") or 0
        if o["change_type"] == "churn":
            mrr_delta -= cur_mrr
            active_delta -= 1
            # dropped from the active list entirely (a churned client is not active)
        else:  # downgrade
            new = o.get("new_mrr") or 0
            mrr_delta += (new - cur_mrr)
            c = {**c, "current_mrr": new, "override": "downgrade"}
            out.append(c)
    return out, round(mrr_delta, 2), active_delta


# ── Roster read + matching ────────────────────────────────────────────────────

def _roster() -> list[dict]:
    """Current active clients (name + current_mrr + status) from the snapshot roster."""
    try:
        from snapshot import load_persisted
        ch = (load_persisted() or {}).get("client_health") or {}
        return ch.get("clients") or []
    except Exception:
        return []


def _match(name_query: str) -> list[dict]:
    """Match a named client against the roster. Exact-ish first, then substring. Deterministic."""
    roster = _roster()
    q = _norm(name_query)
    if not q:
        return []
    exact = [c for c in roster if _norm(c.get("name", "")) == q]
    if exact:
        return exact
    # substring both ways (handles "Hono" vs "Hono Grill", apostrophes)
    return [c for c in roster if _norm(c.get("name", "")) in q or q in _norm(c.get("name", ""))]


# ── Pending confirmation (Postgres, worker-safe, TTL'd) ──────────────────────

import json as _json


def _get_pending(token: str) -> dict | None:
    if not db.db_configured():
        return None
    try:
        with db.get_conn() as c:
            r = c.execute(
                "SELECT payload, EXTRACT(EPOCH FROM (now()-created_at)) AS age "
                "FROM client_override_pending WHERE token=%s", (token,)).fetchone()
        if not r or r["age"] > _PENDING_TTL:
            return None
        return r["payload"]
    except Exception:
        return None


def _set_pending(token: str, payload: dict) -> None:
    migrate()
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO client_override_pending (token, payload) VALUES (%s,%s) "
                      "ON CONFLICT (token) DO UPDATE SET payload=EXCLUDED.payload, created_at=now()",
                      (token, _json.dumps(payload)))
    except Exception as e:
        logger.warning("set_pending failed: %s", e)


def _clear_pending(token: str) -> None:
    if not db.db_configured():
        return
    try:
        with db.get_conn() as c:
            c.execute("DELETE FROM client_override_pending WHERE token=%s", (token,))
    except Exception:
        pass


def _money(s) -> float | None:
    s = str(s or "").replace("$", "").replace(",", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*[kK]\b", s)
    if m:
        return float(m.group(1)) * 1000
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


_AFFIRM = re.compile(r"^\s*(yes|yep|yeah|yup|confirm(ed)?|do it|go|correct|right|sure|ok(ay)?)\b", re.I)
_DENY = re.compile(r"^\s*(no|nope|nah|cancel|stop|leave it|don'?t|wrong|never ?mind)\b", re.I)
_CHURN_RE = re.compile(r"\b(churn(ed)?|cancel(l?ed)?|left us|dropped us|gone|we lost|mark .* (as )?churn)\b", re.I)
_DOWNGRADE_RE = re.compile(r"\bdowngrad(e|ed|ing)\b|\bdropped? (down )?to\b|\breduc(e|ed).*to\b|\blower(ed)? .* to\b", re.I)


def reconcile_churned() -> int:
    """Once Piolo updates the sheet (a churned client becomes non-Active in raw Health), mark that
    override reconciled so it drops off his queue. Churn only (status-based, unambiguous)."""
    if not db.db_configured():
        return 0
    try:
        import sheet_mirror
        rows = sheet_mirror.read_by_gid(1407663952) or []
    except Exception:
        rows = []
    if not rows:
        return 0
    raw_status = {}
    for r in rows[1:]:
        if len(r) > 1 and (r[0] or "").strip():
            raw_status[_norm(r[0])] = (r[1] or "").strip().lower()
    n = 0
    try:
        with db.get_conn() as c:
            for o in active_overrides():
                if o["change_type"] != "churn":
                    continue
                st = raw_status.get(_norm(o["client_name"]))
                if st is not None and st not in ("active", ""):
                    c.execute("UPDATE client_overrides SET reconciled=TRUE WHERE id=%s", (o["id"],))
                    n += 1
    except Exception as e:
        logger.info("reconcile_churned failed: %s", e)
    return n


def _do_resync():
    try:
        import sheet_mirror
        sheet_mirror.sync_all()
        reconcile_churned()
        from snapshot import build_snapshot
        snap = build_snapshot()
        import app as _app
        _app._current_snapshot = snap
    except Exception as e:
        logger.warning("client_override resync failed: %s", e)


def handle_client_writeback_command(text: str, token: str) -> tuple[str | None, bool]:
    """Churn/downgrade a client via override, with a confirmation loop. Writes NOTHING to the sheet."""
    if not text:
        return None, False
    t = text.strip()

    # 1) Pending confirmation?
    pend = _get_pending(token)
    if pend:
        if _AFFIRM.match(t):
            _clear_pending(token)
            oid = _add({
                "client_name": pend["client_name"], "change_type": pend["change_type"],
                "old_status": pend.get("old_status"), "new_status": pend.get("new_status"),
                "old_mrr": pend.get("old_mrr"), "new_mrr": pend.get("new_mrr"),
                "effective_date": pend.get("effective_date"), "reason": pend.get("reason"),
                "created_by": "Rydel",
            })
            if oid is None:
                return "Something went wrong saving that — the change didn't record. Try again?", True
            _do_resync()
            nm = pend["client_name"]
            # Attribute the action + flag it to Rydel (his call: he's told when Piolo does things).
            try:
                import collab
                from dashboard.auth import current_actor
                collab.record_action(current_actor(),
                    f"marked {nm} {pend['change_type']}" +
                    (f" (MRR → ${pend['new_mrr']:,.0f})" if pend.get("new_mrr") else ""),
                    link_type="client", link_ref=nm)
            except Exception:
                pass
            if pend["change_type"] == "churn":
                return (f"Done — {nm} marked churned (dashboard only; the Health sheet is unchanged). "
                        f"It's on Piolo's manual-update list. Say “undo that” to reverse."), True
            return (f"Done — {nm} downgraded to ${pend['new_mrr']:,.0f} MRR (dashboard only; sheet "
                    f"unchanged). On Piolo's list. Say “undo that” to reverse."), True
        if _DENY.match(t):
            _clear_pending(token)
            return "Okay — cancelled, nothing changed.", True
        _clear_pending(token)  # a fresh command supersedes a stale pending

    low = t.lower()
    is_churn = bool(_CHURN_RE.search(low))
    is_down = bool(_DOWNGRADE_RE.search(low))
    if not (is_churn or is_down):
        return None, False
    # A STRATEGIC churn question ("should I hire or fix churn", "how do I reduce churn", "our churn
    # rate") is analysis, not a write command — defer to the capacity/constraint engine + model.
    if re.search(r"\b(should i|hire or|or (fix|hire)|how (do|can|should)|why|worth|instead of|"
                 r"reduce|cut|lower|fix (the )?churn|churn rate|our churn|churn is|about churn|"
                 r"what if|forecast|project(ion)?|scenario|doubl|tripl|halv|best case|worst case)\b", low):
        return None, False

    # 2) Identify the client — strip command words, match the roster.
    stripped = re.sub(r"\b(mark|set|make|as|the|client|has|have|is|was|to|down|our|please|"
                      r"churn(ed)?|cancel(l?ed)?|downgrad(e|ed|ing)|dropped?|reduce[d]?|lower(ed)?)\b",
                      " ", low)
    stripped = re.sub(r"[\$,\d]+k?", " ", stripped).strip()
    matches = _match(stripped) if stripped else []
    if not matches:
        return ("I couldn't match that to a client in the roster — who exactly? "
                "(name it as it appears in the client list).", True)
    if len(matches) > 1:
        names = ", ".join(c.get("name", "?") for c in matches[:6])
        return (f"Which one — I see {len(matches)} possible matches: {names}. Name the exact client.", True)

    c = matches[0]
    nm = c.get("name", "?")
    cur_mrr = c.get("current_mrr") or 0
    today = str(today_sydney())

    if is_down:
        new_mrr = _money(t)
        if new_mrr is None:
            return (f"Downgrade {nm} to what MRR? Give me the new monthly figure.", True)
        if new_mrr >= cur_mrr:
            return (f"{nm} is at ${cur_mrr:,.0f} MRR now — ${new_mrr:,.0f} isn't lower. "
                    f"Did you mean a smaller number, or a churn?", True)
        _set_pending(token, {"client_name": nm, "change_type": "downgrade",
                             "old_status": "Active", "new_status": "Active",
                             "old_mrr": cur_mrr, "new_mrr": new_mrr, "effective_date": today})
        return (f"Downgrading {nm} from ${cur_mrr:,.0f} to ${new_mrr:,.0f} MRR, effective {today}, "
                f"keeping Active — confirm? (yes/no)", True)

    # churn
    _set_pending(token, {"client_name": nm, "change_type": "churn",
                         "old_status": "Active", "new_status": "Churned",
                         "old_mrr": cur_mrr, "new_mrr": 0, "effective_date": today})
    return (f"Marking {nm} (currently Active, ${cur_mrr:,.0f} MRR) as CHURNED, exit date {today} "
            f"— confirm? (yes/no)", True)


def handle_undo_command(text: str, token: str) -> tuple[str | None, bool]:
    if not text or not re.search(r"\bundo\b|revert|mark .* active again|bring back .* (client|account)|"
                                 r"un-?churn|reverse (that|the last)", text, re.I):
        return None, False
    m = re.search(r"(?:mark|bring back)\s+(.+?)\s+active", text, re.I)
    row = undo_client(m.group(1)) if m else undo_last()
    if not row:
        return "Nothing to undo — no active client changes on record.", True
    _do_resync()
    return (f"Reversed — {row['client_name']} restored (was marked {row['change_type']}). "
            f"Dashboard and Piolo's list updated."), True


def handle_pending_updates_query(text: str, token: str = "") -> tuple[str | None, bool]:
    """'What does Piolo need to update?' → the manual sheet-edit queue."""
    if not text or not re.search(
            r"(what|which).*(piolo|manual|sheet).*(update|change|edit|do)|"
            r"(piolo|manual|pending).*(update|change|list|queue)|what needs updating", text, re.I):
        return None, False
    ov = active_overrides()
    if not ov:
        return "Nothing pending — Piolo's client sheet is up to date with the dashboard.", True
    lines = []
    for o in ov:
        if o["change_type"] == "churn":
            lines.append(f"• {o['client_name']}: Status → Churned, End Date → {o['effective_date']}, "
                         f"MRR → 0 (was ${o.get('old_mrr') or 0:,.0f})")
        else:
            lines.append(f"• {o['client_name']}: MRR → ${o.get('new_mrr') or 0:,.0f} "
                         f"(was ${o.get('old_mrr') or 0:,.0f}), keep Active")
    return ("For Piolo — update these on the Health client sheet (dashboard already reflects them):\n"
            + "\n".join(lines)), True


def handle_client_changes_query(text: str) -> tuple[str | None, bool]:
    if not text or not re.search(r"(what|which).*(client).*(change|churn|downgrad)|"
                                 r"client changes.*(made|log)|history of client", text, re.I):
        return None, False
    log = audit_log(10)
    if not log:
        return "No client changes recorded yet.", True
    lines = []
    for r in log:
        tag = "" if r["active"] and not r["reconciled"] else (" [undone]" if not r["active"] else " [in sheet]")
        chg = ("→ churned" if r["change_type"] == "churn"
               else f"→ ${r.get('new_mrr') or 0:,.0f} MRR")
        lines.append(f"• {r['client_name']} {chg} ({str(r['created_at'])[:10]}){tag}")
    return "Client changes:\n" + "\n".join(lines), True
