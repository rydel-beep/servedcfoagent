"""
capital_allocation.py
---------------------
THE DECIDING LAYER. EDITH senses cash; this module helps Rydel DEPLOY it. Two jobs:

1. Make idle cash visible as a BLEEDING COST — the opportunity cost of surplus sitting above the
   survival buffer, earning nothing. That invisible loss is what drives the hoarding, so we
   manufacture the missing P&L line and show it as a loss, not a safe pile.
2. Force every dollar above the buffer to have a named job — a recurring allocation ritual that
   refuses to commit until "Unassigned" hits $0.

Mental model encoded here:
- THE WALL = a fixed survival buffer. Set once, held sacred, then IGNORED. Structural, like rent.
- deployable_surplus = cash - wall.
- idle surplus is a BLEEDING position, not a safe one.
- every dollar above the wall must be assigned; Unassigned = the loss, made visible.

SOURCING (non-negotiable): cash is REAL (Xero, via the snapshot's cash_in_bank). The buffer + cadence
are real config Rydel sets. assumed_annual_return_pct is an ASSUMPTION and is labelled as such
everywhere. If a required input is unset, we say what's missing and prompt — we never invent a
default and present it as real.

Money is NUMERIC(14,2) in Postgres and computed with Decimal here — exact AUD math, no float drift.
All timestamps use today_sydney()/now_sydney().
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

import db
import kv_store
from helpers import today_sydney, now_sydney

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")

# ── Schema (idempotent — matches the repo's per-module migrate() convention) ──
_DDL = """
CREATE TABLE IF NOT EXISTS capital_settings (
    id                        INTEGER PRIMARY KEY DEFAULT 1,
    survival_buffer_aud       NUMERIC(14,2),
    assumed_annual_return_pct NUMERIC(6,3),
    review_cadence            TEXT NOT NULL DEFAULT 'quarterly',
    last_review_at            TIMESTAMPTZ,
    updated_at                TIMESTAMPTZ,
    CONSTRAINT capital_settings_singleton CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS allocation_buckets (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    is_locked   BOOLEAN NOT NULL DEFAULT FALSE,
    target_type TEXT,                         -- 'fixed' | 'pct' | NULL
    target_value NUMERIC(14,2),
    note        TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS allocation_reviews (
    id                SERIAL PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL,
    cash_snapshot_aud NUMERIC(14,2),
    wall_aud          NUMERIC(14,2),
    surplus_aud       NUMERIC(14,2),
    status            TEXT NOT NULL DEFAULT 'draft'   -- 'draft' | 'committed'
);

CREATE TABLE IF NOT EXISTS allocation_lines (
    id           SERIAL PRIMARY KEY,
    review_id    INTEGER NOT NULL REFERENCES allocation_reviews(id) ON DELETE CASCADE,
    bucket_id    INTEGER NOT NULL REFERENCES allocation_buckets(id),
    assigned_aud NUMERIC(14,2) NOT NULL DEFAULT 0,
    note         TEXT,
    UNIQUE (review_id, bucket_id)
);

CREATE TABLE IF NOT EXISTS bucket_deployments (
    id          SERIAL PRIMARY KEY,
    bucket_id   INTEGER NOT NULL REFERENCES allocation_buckets(id),
    review_id   INTEGER REFERENCES allocation_reviews(id) ON DELETE SET NULL,
    amount_aud  NUMERIC(14,2) NOT NULL,
    deployed_at TIMESTAMPTZ NOT NULL,
    note        TEXT
);
"""

# Default buckets (idempotent seed — ON CONFLICT DO NOTHING). Order = deploy priority.
_SEED_BUCKETS = [
    ("Survival", True, "The Wall. Displayed, never allocatable.", 0),
    ("Owner Comp", False, "Salary top-up + distributions to Rydel. Currently underpaid for the seat.", 1),
    ("Constraint Reinvestment", False, "Retention / delivery / renewal machine — the binding constraint. Feed here first.", 2),
    ("Growth Bets", False, "US expansion tranches. The acquisition-side bet that justifies real capital.", 3),
    ("Dry Powder", False, "Opportunistic hiring line.", 4),
    ("Distribution", False, "Personal diversification out of the business.", 5),
]


def migrate() -> bool:
    if not db.db_configured():
        return False
    try:
        with db.get_conn() as c:
            c.execute(_DDL)
            # seed the singleton settings row (values NULL until Rydel sets them — never invented)
            c.execute("INSERT INTO capital_settings (id, review_cadence, updated_at) "
                      "VALUES (1, 'quarterly', %s) ON CONFLICT (id) DO NOTHING", (now_sydney(),))
            for name, locked, note, order in _SEED_BUCKETS:
                c.execute("INSERT INTO allocation_buckets (name, is_locked, note, sort_order) "
                          "VALUES (%s,%s,%s,%s) ON CONFLICT (name) DO NOTHING", (name, locked, note, order))
        return True
    except Exception as e:
        logger.warning("capital_allocation migrate failed: %s", e)
        return False


# ── Money helpers ────────────────────────────────────────────────────────────

def _dec(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _money(d: Decimal | None) -> float | None:
    if d is None:
        return None
    return float(d.quantize(_CENT, rounding=ROUND_HALF_UP))


# ── Cash (REAL — from the Xero-backed snapshot; freshness surfaced) ───────────

def get_cash() -> dict:
    """Cash-at-bank from the canonical snapshot key (live Xero closing balances, or last-known +
    a degraded flag). Never estimated; freshness is labelled so stale never reads as live."""
    try:
        from snapshot import load_persisted
        snap = load_persisted() or {}
        cp = snap.get("cash_position") or {}
        cash = cp.get("cash_in_bank")
        degraded = any("cash_on_hand" in str((d or {}).get("metric", ""))
                       for d in (snap.get("degraded") or []))
        return {"available": cash is not None, "cash_aud": _money(_dec(cash)),
                "stale": degraded, "note": cp.get("cash_in_bank_note"),
                "as_of": snap.get("generated_at")}
    except Exception as e:
        logger.info("get_cash failed: %s", e)
        return {"available": False, "cash_aud": None, "stale": True, "note": None}


# ── Settings ─────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    if not db.db_configured():
        return {"configured": False}
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT * FROM capital_settings WHERE id=1").fetchone()
        if not r:
            return {"configured": False}
        d = dict(r)
        return {
            "survival_buffer_aud": _money(_dec(d.get("survival_buffer_aud"))),
            "assumed_annual_return_pct": (float(d["assumed_annual_return_pct"])
                                          if d.get("assumed_annual_return_pct") is not None else None),
            "review_cadence": d.get("review_cadence"),
            "last_review_at": d["last_review_at"].isoformat() if d.get("last_review_at") else None,
            "buffer_set": d.get("survival_buffer_aud") is not None,
            "return_set": d.get("assumed_annual_return_pct") is not None,
        }
    except Exception as e:
        logger.info("get_settings failed: %s", e)
        return {"configured": False}


def set_setting(field: str, value) -> dict:
    """field ∈ {survival_buffer_aud, assumed_annual_return_pct, review_cadence}."""
    if field not in ("survival_buffer_aud", "assumed_annual_return_pct", "review_cadence"):
        return {"ok": False, "error": "unknown setting"}
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO capital_settings (id, review_cadence, updated_at) VALUES (1,'quarterly',%s) "
                      "ON CONFLICT (id) DO NOTHING", (now_sydney(),))
            c.execute(f"UPDATE capital_settings SET {field}=%s, updated_at=%s WHERE id=1", (value, now_sydney()))
        return {"ok": True, "field": field, "value": value}
    except Exception as e:
        logger.warning("set_setting failed: %s", e)
        return {"ok": False, "error": str(e)}


# ── Reviews / lines / deployments ────────────────────────────────────────────

def _buckets() -> list[dict]:
    with db.get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM allocation_buckets ORDER BY sort_order, id").fetchall()]


def _current_review(status: str) -> dict | None:
    with db.get_conn() as c:
        r = c.execute("SELECT * FROM allocation_reviews WHERE status=%s ORDER BY id DESC LIMIT 1",
                      (status,)).fetchone()
        return dict(r) if r else None


def _lines(review_id: int) -> dict:
    with db.get_conn() as c:
        return {row["bucket_id"]: dict(row) for row in c.execute(
            "SELECT * FROM allocation_lines WHERE review_id=%s", (review_id,)).fetchall()}


def _deployed_sum(review_id: int) -> Decimal:
    with db.get_conn() as c:
        r = c.execute("SELECT COALESCE(SUM(amount_aud),0) s FROM bucket_deployments WHERE review_id=%s",
                      (review_id,)).fetchone()
        return _dec(r["s"]) or Decimal(0)


# ── The compute (all figures derive here — one testable place) ───────────────

def compute_state() -> dict:
    """The full capital-allocation state: cash, wall, surplus, idle, the bleed, the ritual number.
    ALL DB reads share ONE connection (settings + buckets + reviews + lines + deployed) — no
    per-query connection churn that could pressure the pool under the dashboard's concurrent load."""
    cash = get_cash()          # no DB (reads the persisted snapshot)
    cash_d = _dec(cash.get("cash_aud"))

    st = {"configured": False}
    buckets = []
    committed = draft = None
    deployed = Decimal(0)
    draft_lines = {}
    if db.db_configured():
        try:
            with db.get_conn() as c:
                sr = c.execute("SELECT * FROM capital_settings WHERE id=1").fetchone()
                if sr:
                    sd = dict(sr)
                    st = {
                        "survival_buffer_aud": _money(_dec(sd.get("survival_buffer_aud"))),
                        "assumed_annual_return_pct": (float(sd["assumed_annual_return_pct"])
                                                      if sd.get("assumed_annual_return_pct") is not None else None),
                        "review_cadence": sd.get("review_cadence"),
                        "last_review_at": sd["last_review_at"].isoformat() if sd.get("last_review_at") else None,
                        "buffer_set": sd.get("survival_buffer_aud") is not None,
                        "return_set": sd.get("assumed_annual_return_pct") is not None,
                    }
                buckets = [dict(b) for b in c.execute(
                    "SELECT * FROM allocation_buckets ORDER BY sort_order, id").fetchall()]
                cr = c.execute("SELECT * FROM allocation_reviews WHERE status='committed' ORDER BY id DESC LIMIT 1").fetchone()
                committed = dict(cr) if cr else None
                if committed:
                    dr = c.execute("SELECT COALESCE(SUM(amount_aud),0) s FROM bucket_deployments WHERE review_id=%s",
                                   (committed["id"],)).fetchone()
                    deployed = _dec(dr["s"]) or Decimal(0)
                drr = c.execute("SELECT * FROM allocation_reviews WHERE status='draft' ORDER BY id DESC LIMIT 1").fetchone()
                draft = dict(drr) if drr else None
                if draft:
                    draft_lines = {row["bucket_id"]: dict(row) for row in c.execute(
                        "SELECT * FROM allocation_lines WHERE review_id=%s", (draft["id"],)).fetchall()}
        except Exception as e:
            logger.info("compute_state DB read failed: %s", e)

    wall_d = _dec(st.get("survival_buffer_aud"))
    ret = st.get("assumed_annual_return_pct")

    out = {
        "cash": cash,
        "settings": st,
        "buckets": [{"id": b["id"], "name": b["name"], "is_locked": b["is_locked"],
                     "note": b.get("note"), "sort_order": b["sort_order"],
                     "target_type": b.get("target_type"),
                     "target_value": _money(_dec(b.get("target_value")))} for b in buckets],
        "config_missing": [],
    }
    if not st.get("buffer_set"):
        out["config_missing"].append("survival_buffer_aud")
    if not st.get("return_set"):
        out["config_missing"].append("assumed_annual_return_pct")

    # Can't compute surplus/bleed without cash + wall — say what's missing, invent nothing.
    if cash_d is None or wall_d is None:
        out.update({"state": "not_configured", "below_buffer": None,
                    "deployable_surplus_aud": None, "idle_surplus_aud": None,
                    "opportunity_cost_monthly_aud": None, "opportunity_cost_annualised_aud": None,
                    "unassigned_aud": None})
        return out

    below_buffer = cash_d < wall_d
    surplus = max(Decimal(0), cash_d - wall_d)
    idle = max(Decimal(0), surplus - deployed)

    # Opportunity cost is a MODELLED figure — only with a POSITIVE return assumption, and $0 below
    # buffer. A non-positive return can't model a bleed (would be $0/negative presented as real).
    opp_m = opp_a = None
    if ret is not None and ret > 0 and not below_buffer:
        r = Decimal(str(ret)) / Decimal(100)
        opp_a = idle * r
        opp_m = opp_a / Decimal(12)

    # Ritual-time number: unassigned against the current DRAFT review's lines (already loaded above).
    unassigned = None
    draft_block = None
    if draft:
        assigned = sum((_dec(l.get("assigned_aud")) or Decimal(0) for l in draft_lines.values()), Decimal(0))
        draft_surplus = _dec(draft.get("surplus_aud")) or surplus
        unassigned = draft_surplus - assigned
        draft_block = {"review_id": draft["id"], "created_at": draft["created_at"].isoformat(),
                       "surplus_aud": _money(draft_surplus), "assigned_total_aud": _money(assigned),
                       "lines": [{"bucket_id": bid, "assigned_aud": _money(_dec(l.get("assigned_aud"))),
                                  "note": l.get("note")} for bid, l in draft_lines.items()]}

    out.update({
        "state": "below_buffer" if below_buffer else "ok",
        "below_buffer": below_buffer,
        "deployable_surplus_aud": _money(surplus),
        "deployed_this_period_aud": _money(deployed),
        "idle_surplus_aud": _money(idle if not below_buffer else Decimal(0)),
        "opportunity_cost_monthly_aud": _money(opp_m) if opp_m is not None else None,
        "opportunity_cost_annualised_aud": _money(opp_a) if opp_a is not None else None,
        "opportunity_cost_is_modelled": True,
        "assumed_return_pct": ret,
        "committed_review_id": committed["id"] if committed else None,
        "draft_review": draft_block,
        "unassigned_aud": _money(unassigned) if unassigned is not None else None,
    })
    return out


def run_review() -> dict:
    """Open (or return the existing) DRAFT review — snapshots cash + locks the wall for it."""
    existing = _current_review("draft")
    if existing:
        return {"ok": True, "review_id": existing["id"], "reused": True}
    cash = get_cash()
    st = get_settings()
    if cash.get("cash_aud") is None or not st.get("buffer_set"):
        return {"ok": False, "error": "cash or survival buffer not available/configured"}
    cash_d = _dec(cash["cash_aud"]); wall_d = _dec(st["survival_buffer_aud"])
    surplus = max(Decimal(0), cash_d - wall_d)
    if surplus <= 0:
        return {"ok": False, "error": "below buffer — no surplus to allocate; rebuild the wall first"}
    with db.get_conn() as c:
        r = c.execute("INSERT INTO allocation_reviews (created_at, cash_snapshot_aud, wall_aud, surplus_aud, status) "
                      "VALUES (%s,%s,%s,%s,'draft') RETURNING id",
                      (now_sydney(), cash_d, wall_d, surplus)).fetchone()
    return {"ok": True, "review_id": r["id"], "reused": False, "surplus_aud": _money(surplus)}


def set_line(review_id: int, bucket_id: int, assigned_aud, note: str | None = None) -> dict:
    amt = _dec(assigned_aud) or Decimal(0)
    if amt < 0:
        amt = Decimal(0)   # a bucket can't hold a negative job
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO allocation_lines (review_id, bucket_id, assigned_aud, note) "
                      "VALUES (%s,%s,%s,%s) ON CONFLICT (review_id, bucket_id) DO UPDATE SET "
                      "assigned_aud=EXCLUDED.assigned_aud, note=EXCLUDED.note",
                      (review_id, bucket_id, amt, note))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def commit_review(review_id: int) -> dict:
    """Commit ONLY when Unassigned == $0 — the forcing function. Refuses otherwise."""
    with db.get_conn() as c:
        rev = c.execute("SELECT * FROM allocation_reviews WHERE id=%s AND status='draft'", (review_id,)).fetchone()
        if not rev:
            return {"ok": False, "error": "no draft review with that id"}
        surplus = _dec(rev["surplus_aud"]) or Decimal(0)
        s = c.execute("SELECT COALESCE(SUM(assigned_aud),0) a FROM allocation_lines WHERE review_id=%s",
                      (review_id,)).fetchone()
        assigned = _dec(s["a"]) or Decimal(0)
        unassigned = (surplus - assigned).quantize(_CENT, rounding=ROUND_HALF_UP)
        if unassigned != Decimal("0.00"):
            return {"ok": False, "error": "unassigned is not zero — every dollar needs a job",
                    "unassigned_aud": _money(unassigned)}
        c.execute("UPDATE allocation_reviews SET status='committed' WHERE id=%s", (review_id,))
        c.execute("UPDATE capital_settings SET last_review_at=%s, updated_at=%s WHERE id=1",
                  (now_sydney(), now_sydney()))
    return {"ok": True, "review_id": review_id, "committed": True}


def mark_deployed(bucket_id: int, amount_aud, note: str | None = None, review_id: int | None = None) -> dict:
    if review_id is None:
        committed = _current_review("committed")
        review_id = committed["id"] if committed else None
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO bucket_deployments (bucket_id, review_id, amount_aud, deployed_at, note) "
                      "VALUES (%s,%s,%s,%s,%s)", (bucket_id, review_id, _dec(amount_aud) or Decimal(0),
                                                  now_sydney(), note))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Voice / text intents (wired into the existing three-tier router) ─────────

import re as _re

_ASSUMPTION_TAG = "at your assumed {r}% (an assumption, not a guarantee)"
_DEPLOY_RE = _re.compile(r"\bhow much (can|could) (i|we) (deploy|invest|put to work)\b|\bdeployable (surplus|cash)\b|\bhow much (is )?(deployable|free to deploy)\b", _re.I)
_BLEED_RE = _re.compile(r"\b(opportunity cost|what am i leaking|what'?s (my )?(bleed|leak)|how much (am i|is) (leaking|bleeding)|idle cash cost)\b", _re.I)
_REVIEW_RE = _re.compile(r"\brun (my |the )?allocation review\b|\bstart (my |the )?(allocation|capital) review\b|\ballocation ritual\b", _re.I)
_UNASSIGNED_RE = _re.compile(r"\bwhat'?s (unassigned|left to assign)\b|\bhow much (is )?unassigned\b|\bunassigned\b", _re.I)
_SET_BUFFER_RE = _re.compile(r"\bset (my |the )?(survival )?(buffer|wall)\b.*?\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?", _re.I)
_SET_RETURN_RE = _re.compile(r"\bset (my |the )?(assumed )?return\b.*?([\d.]+)\s*%?", _re.I)
_AFFIRM_RE = _re.compile(r"^\s*(yes|yep|yeah|yup|confirm(ed)?|do it|go ahead|correct)\b", _re.I)
_PENDING_K = "capital:pending:"


def _fmt_aud(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "n/a"


def handle_command(text: str, actor: dict | None = None) -> tuple[str | None, bool]:
    """Capital-allocation voice/text intents. Writes go through a mandatory confirmation loop."""
    if not text:
        return None, False
    who = (actor or {}).get("user", "rydel")
    pk = _PENDING_K + who

    # confirmation of a pending set
    if _AFFIRM_RE.match(text):
        pend = kv_store.get(pk)
        if pend:
            kv_store.delete(pk)
            set_setting(pend["field"], pend["value"])
            label = "survival buffer" if pend["field"] == "survival_buffer_aud" else "assumed annual return"
            val = _fmt_aud(pend["value"]) if pend["field"] == "survival_buffer_aud" else f"{pend['value']}%"
            return f"Done — {label} set to {val}. It's locked in.", True
        return None, False

    m = _SET_BUFFER_RE.search(text)
    if m:
        amt = float(m.group(3).replace(",", "")) * (1000 if m.group(4) else 1)
        kv_store.put(pk, {"field": "survival_buffer_aud", "value": amt})
        return (f"Set your survival buffer (the Wall) to {_fmt_aud(amt)}? This is the sacred floor — "
                "funded once, then ignored. Say 'yes' to confirm."), True

    m = _SET_RETURN_RE.search(text)
    if m:
        pct = float(m.group(3))
        kv_store.put(pk, {"field": "assumed_annual_return_pct", "value": pct})
        return (f"Set your assumed annual return to {pct}%? Note this is an ASSUMPTION used to model the "
                "opportunity cost of idle cash — not a guarantee. Say 'yes' to confirm."), True

    s = compute_state()
    # missing-config guard — say what's missing, never invent
    if _DEPLOY_RE.search(text) or _BLEED_RE.search(text) or _UNASSIGNED_RE.search(text) or _REVIEW_RE.search(text):
        if s.get("state") == "not_configured":
            miss = " and ".join("survival buffer" if x == "survival_buffer_aud" else "assumed return"
                                for x in s.get("config_missing", []))
            return f"I can't compute that yet — your {miss} isn't set. Say 'set my buffer to X' / 'set my assumed return to Y%'.", True
        if s.get("below_buffer"):
            return (f"You're BELOW your survival buffer right now — cash {_fmt_aud(s['cash']['cash_aud'])} vs "
                    f"wall {_fmt_aud(s['settings']['survival_buffer_aud'])}. Rebuild the wall before deploying; "
                    "there's no surplus and no opportunity cost until it's covered."), True

    if _DEPLOY_RE.search(text):
        return (f"You can deploy {_fmt_aud(s['deployable_surplus_aud'])} — that's cash "
                f"{_fmt_aud(s['cash']['cash_aud'])} minus your {_fmt_aud(s['settings']['survival_buffer_aud'])} wall."
                + (" (cash is last-known — Xero was unavailable)" if s['cash'].get("stale") else "")), True

    if _BLEED_RE.search(text):
        r = s.get("assumed_return_pct")
        if r is None:
            return "Set your assumed return first ('set my assumed return to X%') — I won't invent one.", True
        return (f"You're leaking {_fmt_aud(s['opportunity_cost_monthly_aud'])}/mo "
                f"({_fmt_aud(s['opportunity_cost_annualised_aud'])}/yr) — {_fmt_aud(s['idle_surplus_aud'])} idle above "
                f"the wall, {_ASSUMPTION_TAG.format(r=r)}. That's a modelled cost, not a fact I know — but it's real, "
                "and it stops the moment you deploy."), True

    if _UNASSIGNED_RE.search(text):
        if not s.get("draft_review"):
            return (f"No open review right now. {_fmt_aud(s['deployable_surplus_aud'])} is deployable — say "
                    "'run my allocation review' to start assigning it."), True
        u = s.get("unassigned_aud")
        return (f"{_fmt_aud(u)} still unassigned in the open review — every dollar needs a job before it commits."
                if u and u > 0 else "Nothing unassigned — the review's ready to commit."), True

    if _REVIEW_RE.search(text):
        rv = run_review()
        if not rv.get("ok"):
            return f"Couldn't start the review: {rv.get('error')}.", True
        s2 = compute_state()
        return (f"Allocation review open. {_fmt_aud(s2['deployable_surplus_aud'])} deployable above your "
                f"{_fmt_aud(s2['settings']['survival_buffer_aud'])} wall — assign it across your buckets until "
                "Unassigned hits $0. Open the Capital Allocation panel to work through it."), True

    return None, False


def review_history(limit: int = 12) -> list[dict]:
    """Past committed reviews with assigned vs actually deployed per bucket (hoarding-creep view)."""
    if not db.db_configured():
        return []
    try:
        with db.get_conn() as c:
            revs = [dict(r) for r in c.execute(
                "SELECT * FROM allocation_reviews WHERE status='committed' ORDER BY id DESC LIMIT %s",
                (limit,)).fetchall()]
            bnames = {b["id"]: b["name"] for b in c.execute(
                "SELECT id, name FROM allocation_buckets").fetchall()}
            out = []
            for rev in revs:
                lines = c.execute("SELECT bucket_id, assigned_aud FROM allocation_lines WHERE review_id=%s",
                                  (rev["id"],)).fetchall()
                deps = c.execute("SELECT bucket_id, COALESCE(SUM(amount_aud),0) d FROM bucket_deployments "
                                 "WHERE review_id=%s GROUP BY bucket_id", (rev["id"],)).fetchall()
                dmap = {r["bucket_id"]: _dec(r["d"]) for r in deps}
                rows = [{"bucket": bnames.get(l["bucket_id"], "?"),
                         "assigned_aud": _money(_dec(l["assigned_aud"])),
                         "deployed_aud": _money(dmap.get(l["bucket_id"], Decimal(0)))}
                        for l in lines]
                out.append({"review_id": rev["id"], "created_at": rev["created_at"].isoformat(),
                            "cash_snapshot_aud": _money(_dec(rev["cash_snapshot_aud"])),
                            "surplus_aud": _money(_dec(rev["surplus_aud"])), "rows": rows})
            return out
    except Exception as e:
        logger.info("review_history failed: %s", e)
        return []
