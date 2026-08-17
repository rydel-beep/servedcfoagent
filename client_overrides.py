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
  change_type    TEXT NOT NULL,          -- 'churn' | 'downgrade' | 'renewal' (#135)
  old_status     TEXT,
  new_status     TEXT,
  old_mrr        REAL,
  new_mrr        REAL,
  effective_date DATE,                   -- churn: exit date · renewal: NEW contract end
  reason         TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     TEXT NOT NULL DEFAULT 'Rydel',
  active         BOOLEAN NOT NULL DEFAULT TRUE,     -- FALSE = undone
  reconciled     BOOLEAN NOT NULL DEFAULT FALSE     -- TRUE = the sheet caught up
);
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS old_end DATE;
-- FORWARD MRR wave (2026-08-13): the RICHER resign declaration — amount per
-- billing period, term length, cadence, term start. Additive; old rows keep
-- NULLs and behave exactly as before.
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS amount REAL;
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS term_months INTEGER;
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS cadence TEXT;
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS start_date DATE;
-- CSM wave (2026-08-17): DOWNSELL/CONTINUITY + EXPANSION join the ONE flow.
-- Additive; old rows keep NULLs and behave exactly as before.
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS subtype TEXT;
ALTER TABLE client_overrides ADD COLUMN IF NOT EXISTS first6_value REAL;
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
            if d.get("start_date") is not None:
                d["start_date"] = str(d["start_date"])
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
    o = {"old_end": None, "reason": None, "amount": None, "term_months": None,
         "cadence": None, "start_date": None, "subtype": None,
         "first6_value": None, **o}
    try:
        with db.get_conn() as c:
            cur = c.execute(
                """INSERT INTO client_overrides
                     (client_name, change_type, old_status, new_status, old_mrr, new_mrr,
                      effective_date, reason, created_by, old_end,
                      amount, term_months, cadence, start_date, subtype, first6_value)
                   VALUES (%(client_name)s,%(change_type)s,%(old_status)s,%(new_status)s,
                           %(old_mrr)s,%(new_mrr)s,%(effective_date)s,%(reason)s,
                           %(created_by)s,%(old_end)s,
                           %(amount)s,%(term_months)s,%(cadence)s,%(start_date)s,
                           %(subtype)s,%(first6_value)s)
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


# ── THE DECLARE FLOW (#135 — dashboard routes call these; EXTENDS the chat
# write-back, same tables, same confirmation contract, same no-sheet-write line) ──

CADENCES = ("monthly", "quarterly", "annual", "one_off")
_CADENCE_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}

# THE kinds enum (CSM wave adds downsell/continuity + expansion to the one
# flow — every consumer references THIS, never a re-typed tuple).
DECLARATION_KINDS = ("churn", "renewal", "downgrade", "downsell", "expansion")
EXPANSION_SUBTYPES = ("stepup", "sprint", "ordering", "reservations",
                      "photo_day", "market_intel", "second_venue", "referral")
# subtypes whose natural shape is a one-off payment (default cadence)
_ONE_OFF_SUBTYPES = ("sprint", "photo_day", "market_intel", "referral")


def normalize_mrr(amount: float, cadence: str) -> float | None:
    """THE cadence→MRR normalisation (one function; the dialog, the engine,
    the journal and EDITH all read this). one_off → None: a one-off payment
    is committed CASH for its month, NEVER recurring MRR."""
    if cadence == "one_off":
        return None
    return round(float(amount) / _CADENCE_MONTHS[cadence], 2)


def _add_months(d, n: int):
    """Calendar-safe month add (clamped day)."""
    import calendar
    import datetime as dt
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def preview_declaration(client_name: str, kind: str, effective_date: str | None = None,
                        new_mrr: float | None = None,
                        reason: str | None = None,
                        amount: float | None = None,
                        term_months: int | None = None,
                        cadence: str | None = None,
                        start_date: str | None = None,
                        subtype: str | None = None,
                        first6_value: float | None = None) -> tuple[dict | None, str | None]:
    """Stage 1: bind the EXACT roster client (IDs-are-truth: the type-ahead sends
    a roster name verbatim; anything not matching exactly one roster entry is
    'not a known client' — NO phantom clients, ever) and build the impact
    preview. Returns (payload+preview, None) or (None, honest_error)."""
    if kind not in DECLARATION_KINDS:
        return None, f"unknown declaration kind '{kind}'"
    roster = _roster()
    exact = [c for c in roster if _norm(c.get("name", "")) == _norm(client_name)]
    if not exact:
        return None, (f"'{client_name}' is not a known client — pick from the "
                      f"current client list (no phantom clients)")
    if len(exact) > 1:
        return None, (f"'{client_name}' matches {len(exact)} roster entries — "
                      f"ambiguous, quarantined; fix the roster duplicate first")
    c = exact[0]
    nm = c.get("name")
    cur_mrr = float(c.get("current_mrr") or 0)
    old_end = c.get("contract_end")
    eff = effective_date or str(today_sydney())
    payload = {"client_name": nm, "change_type": kind, "old_status": "Active",
               "old_mrr": cur_mrr, "effective_date": eff, "reason": reason,
               "old_end": old_end, "created_by": "Rydel"}
    if kind == "churn":
        payload.update({"new_status": "Churned", "new_mrr": 0})
        preview = (f"CHURN {nm}: removes ${cur_mrr:,.0f}/mo from MRR effective {eff}"
                   + (f" — reason: {reason}" if reason else ""))
    elif kind == "renewal":
        # THE RICHER RESIGN (forward-MRR wave): amount · term · cadence ·
        # start — normalised to MRR live; effective_date (the sheet's End
        # Date, the convergence key) is DERIVED = start + term. The legacy
        # shape (explicit end date, optional new_mrr) still works unchanged.
        if amount is not None or term_months is not None or cadence is not None:
            if amount is None or float(amount) <= 0:
                return None, "a resign needs the amount (per billing period)"
            cadence = (cadence or "monthly").strip().lower()
            if cadence not in CADENCES:
                return None, f"cadence must be one of {', '.join(CADENCES)}"
            try:
                term_months = int(term_months or (1 if cadence == "one_off" else 0))
            except (TypeError, ValueError):
                return None, "term must be a number of months"
            if cadence != "one_off" and not (1 <= term_months <= 60):
                return None, "term must be 1–60 months"
            import datetime as _dt
            try:
                start = (_dt.date.fromisoformat(str(start_date))
                         if start_date else today_sydney())
            except ValueError:
                return None, "bad start date"
            end = _add_months(start, term_months if cadence != "one_off" else 1)
            norm = normalize_mrr(float(amount), cadence)
            eff = str(end)
            payload.update({"new_status": "Active", "new_mrr": norm,
                            "effective_date": eff,
                            "amount": float(amount), "term_months": term_months,
                            "cadence": cadence, "start_date": str(start)})
            if cadence == "one_off":
                preview = (f"RESIGN {nm} (ONE-OFF): ${float(amount):,.0f} counted as "
                           f"committed CASH in {start.strftime('%B %Y')} — NOT "
                           f"recurring MRR (the MRR line is untouched); clears the "
                           f"renewal warning")
            else:
                per_label = {"monthly": "monthly", "quarterly": "quarterly",
                             "annual": "annual"}[cadence]
                norm_line = (f"${float(amount):,.0f} {per_label} = ${norm:,.2f}/mo"
                             if cadence != "monthly" else f"${norm:,.2f}/mo")
                preview = (f"RESIGN {nm}: {norm_line} × {term_months}mo from {start} "
                           f"— adds ${norm:,.2f}/mo COMMITTED through "
                           f"{end.strftime('%B %Y')}; clears the renewal warning; "
                           f"re-enters the watch as {end} approaches"
                           + (f"; MRR {'up' if norm > cur_mrr else 'down'} "
                              f"${abs(norm - cur_mrr):,.0f}/mo (${cur_mrr:,.0f} → "
                              f"${norm:,.0f})" if abs(norm - cur_mrr) > 0.005 else ""))
            new_mrr = norm     # the delta math below reads it
        else:
            if not effective_date:
                return None, "a renewal needs the NEW renewal/term end date"
            payload.update({"new_status": "Active",
                            "new_mrr": float(new_mrr) if new_mrr is not None else None})
            delta = ""
            if new_mrr is not None and abs(float(new_mrr) - cur_mrr) > 0.005:
                word = "up" if float(new_mrr) > cur_mrr else "down"
                delta = (f", MRR {word} ${abs(float(new_mrr) - cur_mrr):,.0f}/mo "
                         f"(${cur_mrr:,.0f} → ${float(new_mrr):,.0f})")
            preview = (f"RENEW {nm}: contract end {old_end or '(none on file)'} → {eff}"
                       f"{delta or ', MRR unchanged'} — clears the renewal warning; "
                       f"re-enters the watch as {eff} approaches")
    elif kind == "downsell":
        # CONTINUITY (CSM wave): a non-renewal walked down to the Served OS
        # floor instead of churn-to-zero. Amount+cadence normalise via THE one
        # function; a direct new_mrr also works. Must be below current MRR
        # and above zero (zero would be a churn, not a continuity capture).
        if amount is not None:
            cadence = (cadence or "monthly").strip().lower()
            if cadence not in CADENCES or cadence == "one_off":
                return None, "continuity floor is recurring — monthly/quarterly/annual"
            floor_mrr = normalize_mrr(float(amount), cadence)
        elif new_mrr is not None:
            floor_mrr = float(new_mrr)
        else:
            return None, "a continuity downsell needs the floor amount"
        if floor_mrr is None or floor_mrr <= 0:
            return None, "a continuity downsell needs a figure above zero"
        if floor_mrr >= cur_mrr and cur_mrr > 0:
            return None, (f"{nm} is at ${cur_mrr:,.0f}/mo — the continuity floor "
                          f"must be below that (otherwise declare a renewal)")
        payload.update({"new_status": "Active", "new_mrr": floor_mrr,
                        "subtype": "continuity",
                        "amount": float(amount) if amount is not None else None,
                        "cadence": cadence if amount is not None else None})
        saved = floor_mrr
        preview = (f"CONTINUITY {nm}: ${cur_mrr:,.0f} → ${floor_mrr:,.0f}/mo floor "
                   f"effective {eff} (−${cur_mrr - floor_mrr:,.0f}/mo vs the full "
                   f"retainer; ${saved:,.0f}/mo SAVED vs churn-to-zero) — clears "
                   f"the renewal warning as a decided outcome")
        new_mrr = floor_mrr
    elif kind == "expansion":
        # EXPANSION (CSM wave): step-up / sprint / ordering / reservations /
        # photo day / market intel / second venue / referral. Recurring adds a
        # committed stream on TOP of the client's base; one-off is committed
        # CASH for its month, never MRR. first6_value feeds comp + the model;
        # derived honestly when not supplied.
        subtype = (subtype or "").strip().lower()
        if subtype not in EXPANSION_SUBTYPES:
            return None, (f"expansion needs a subtype: "
                          f"{', '.join(EXPANSION_SUBTYPES)}")
        if amount is None or float(amount) <= 0:
            return None, "an expansion needs the amount (per billing period)"
        cadence = ((cadence or "").strip().lower()
                   or ("one_off" if subtype in _ONE_OFF_SUBTYPES else "monthly"))
        if cadence not in CADENCES:
            return None, f"cadence must be one of {', '.join(CADENCES)}"
        import datetime as _dt
        try:
            start = (_dt.date.fromisoformat(str(start_date))
                     if start_date else today_sydney())
        except ValueError:
            return None, "bad start date"
        if cadence == "one_off":
            term_months = 1
            end = _add_months(start, 1)
            norm = None
            f6 = float(first6_value) if first6_value is not None else float(amount)
            payload.update({"new_status": "Active", "new_mrr": cur_mrr,
                            "effective_date": str(end),
                            "amount": float(amount), "term_months": term_months,
                            "cadence": cadence, "start_date": str(start),
                            "subtype": subtype, "first6_value": round(f6, 2)})
            preview = (f"EXPANSION {nm} ({subtype}, ONE-OFF): ${float(amount):,.0f} "
                       f"counted as committed CASH in {start.strftime('%B %Y')} — "
                       f"NOT recurring MRR; first-6-month value ${f6:,.0f}")
            new_mrr = cur_mrr
        else:
            try:
                term_months = int(term_months or 6)
            except (TypeError, ValueError):
                return None, "term must be a number of months"
            if not (1 <= term_months <= 60):
                return None, "term must be 1–60 months"
            end = _add_months(start, term_months)
            norm = normalize_mrr(float(amount), cadence)
            f6 = (float(first6_value) if first6_value is not None
                  else norm * min(6, term_months))
            payload.update({"new_status": "Active", "new_mrr": cur_mrr + norm,
                            "effective_date": str(end),
                            "amount": float(amount), "term_months": term_months,
                            "cadence": cadence, "start_date": str(start),
                            "subtype": subtype, "first6_value": round(f6, 2)})
            preview = (f"EXPANSION {nm} ({subtype}): +${norm:,.2f}/mo × "
                       f"{term_months}mo from {start} — MRR ${cur_mrr:,.0f} → "
                       f"${cur_mrr + norm:,.0f}/mo committed through "
                       f"{end.strftime('%B %Y')}; first-6-month value ${f6:,.0f}")
            new_mrr = cur_mrr + norm
    else:  # downgrade
        if new_mrr is None or float(new_mrr) >= cur_mrr:
            return None, (f"{nm} is at ${cur_mrr:,.0f}/mo — a downgrade needs a "
                          f"lower figure")
        payload.update({"new_status": "Active", "new_mrr": float(new_mrr)})
        preview = (f"DOWNGRADE {nm}: ${cur_mrr:,.0f} → ${float(new_mrr):,.0f}/mo "
                   f"effective {eff} (−${cur_mrr - float(new_mrr):,.0f}/mo MRR)")
    mrr_delta = ((0 - cur_mrr) if kind == "churn"
                 else (float(new_mrr) - cur_mrr) if new_mrr is not None else 0.0)
    return {"payload": payload, "preview": preview,
            "mrr_delta": round(mrr_delta, 2), "current_mrr": cur_mrr,
            "old_end": old_end}, None


def apply_declaration(payload: dict, actor: dict | None = None) -> tuple[int | None, str | None]:
    """Stage 2 (post-confirm): record → journal → resync the one engine →
    today's MRR snapshot refreshes → the Piolo feed item generates. Returns
    (override_id, error)."""
    oid = _add(payload)
    if oid is None:
        return None, "the declaration didn't record (db) — nothing changed"
    try:
        import renewal_loop
        renewal_loop.journal(
            f"declared ({payload['change_type']})",
            f"{payload['client_name']}: {payload['change_type']}"
            + (f"/{payload.get('subtype')}" if payload.get("subtype") else "")
            + f" effective {payload.get('effective_date')}"
            + (f", MRR → ${float(payload['new_mrr']):,.0f}"
               if payload.get("new_mrr") is not None else "")
            + (f" [{payload.get('cadence')} ${float(payload.get('amount') or 0):,.0f}"
               f" × {payload.get('term_months')}mo from {payload.get('start_date')}]"
               if payload.get("cadence") else "")
            + f" — by {(actor or {}).get('user', 'rydel')} (owner declaration, "
              f"pending sheet)")
    except Exception:
        pass
    try:
        import collab
        collab.record_action(actor or {"user": "rydel", "role": "owner"},
                             f"declared {payload['client_name']} "
                             f"{payload['change_type']}",
                             link_type="client", link_ref=payload["client_name"])
    except Exception:
        pass
    _do_resync()
    try:
        import mrr_snapshot
        mrr_snapshot.take_snapshot(force=True)   # today's row carries it NOW
    except Exception as e:
        logger.info("mrr snapshot refresh after declaration failed: %s", e)
    return oid, None


def reverse_declaration(override_id: int, actor: dict | None = None) -> tuple[dict | None, str | None]:
    """Journaled reversal by id (EXCLUDED ≠ DELETED: the row stays, active=FALSE;
    its Piolo feed item retires because it stops generating). Confirmation is
    the caller's job (the routes gate it)."""
    if not db.db_configured():
        return None, "db unavailable"
    try:
        with db.get_conn() as c:
            row = c.execute("SELECT * FROM client_overrides WHERE id=%s AND active "
                            "AND NOT reconciled", (override_id,)).fetchone()
            if not row:
                return None, ("no active un-reconciled declaration with that id — "
                              "already reversed, converged, or never existed")
            c.execute("UPDATE client_overrides SET active=FALSE WHERE id=%s",
                      (override_id,))
        try:
            import renewal_loop
            renewal_loop.journal(
                "declaration reversed",
                f"{row['client_name']}: {row['change_type']} (id {override_id}) "
                f"reversed by {(actor or {}).get('user', 'rydel')} — MRR/status "
                f"restored; Piolo item retired (reason: reversal)")
        except Exception:
            pass
        _do_resync()
        try:
            import mrr_snapshot
            mrr_snapshot.take_snapshot(force=True)
        except Exception:
            pass
        return dict(row), None
    except Exception as e:
        logger.warning("reverse_declaration failed: %s", e)
        return None, str(e)[:120]


def mark_reconciled(override_id: int) -> bool:
    """The convergence write: the sheet now reflects this declaration."""
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute("UPDATE client_overrides SET reconciled=TRUE WHERE id=%s",
                      (override_id,))
        return True
    except Exception as e:
        logger.warning("mark_reconciled(%s) failed: %s", override_id, e)
        return False


def reconciled_recent(days: int = 14) -> dict[str, dict]:
    """{norm name: override} for declarations the sheet has caught up on
    recently — the 'declared ✓ sheet' chip window."""
    if not db.db_configured():
        return {}
    try:
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT * FROM client_overrides WHERE active AND reconciled "
                "AND created_at > now() - make_interval(days => %s)", (days,)).fetchall()
        return {_norm(r["client_name"]): dict(r) for r in rows}
    except Exception:
        return {}


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
        elif o["change_type"] == "renewal":
            mrr_bit = (f", Monthly Recognized → ${o.get('new_mrr') or 0:,.0f}"
                       if o.get("new_mrr") is not None else "")
            lines.append(f"• {o['client_name']}: End Date → {o['effective_date']} "
                         f"(renewal){mrr_bit}, keep Active")
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
