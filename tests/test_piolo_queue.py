"""
tests/test_piolo_queue.py — PIOLO QUEUE FIX (2026-08-10): mark-done that
sticks (evidence-signature dismissals) + relevance gating (active vs aged).

The diagnosed bug was (B) RESURRECTION: identity = slug(category+title) with
live numbers inside, so metric drift re-opened resolved items (prod evidence:
mrr-72,275 resolved → mrr-59,316 open; "1 won deal…Butlers" resolved →
"2 won deal…Butlers, Il Ritrovo" open) and resolved items never left the
render. These tests re-run the witnessed failures against the fix.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import collab
import kv_store


# ── an in-memory Postgres double for the two queue tables ────────────────────

class FakeDB:
    def __init__(self):
        self.queue: dict[str, dict] = {}        # flag_id → row
        self.state: dict[str, dict] = {}        # signature → row

    class _Cur:
        def __init__(self, rows=None, row=None):
            self._rows, self._row = rows or [], row
        def fetchall(self):
            return self._rows
        def fetchone(self):
            return self._row

    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("CREATE") or s.startswith("ALTER"):
            return FakeDB._Cur()
        if "FROM collab_queue WHERE flag_id" in s:
            return FakeDB._Cur(row=self.queue.get(params[0]))
        if "SELECT flag_id FROM collab_queue WHERE signature" in s:
            hit = next((r for r in self.queue.values()
                        if r.get("signature") == params[0]), None)
            return FakeDB._Cur(row={"flag_id": hit["flag_id"]} if hit else None)
        if s.startswith("SELECT * FROM collab_queue"):
            return FakeDB._Cur(rows=[dict(r) for r in self.queue.values()])
        if s.startswith("SELECT * FROM collab_item_state"):
            return FakeDB._Cur(rows=[dict(r) for r in self.state.values()])
        if s.startswith("INSERT INTO collab_queue"):
            fid = params[0]
            row = self.queue.get(fid, {"flag_id": fid})
            if "resolved_by" in s:      # the resolve upsert
                row.update({"title": params[1], "status": "resolved",
                            "resolution": params[2], "resolved_by": params[3],
                            "signature": params[4], "verification": params[5],
                            "lane_override": None})
            else:                       # the restore sig-row insert
                row.update({"title": params[1], "status": "open",
                            "signature": params[2], "lane_override": "active"})
            self.queue[fid] = row
            return FakeDB._Cur()
        if s.startswith("UPDATE collab_queue SET signature="):
            self.queue.setdefault(params[1], {"flag_id": params[1]})["signature"] = params[0]
            return FakeDB._Cur()
        if s.startswith("UPDATE collab_queue SET status='verified'"):
            r = self.queue.get(params[1])
            if r:
                r.update({"status": "verified", "verification": params[0]})
            return FakeDB._Cur()
        if s.startswith("UPDATE collab_queue SET status='open'"):
            r = self.queue.get(params[0])
            if r:
                r.update({"status": "open", "verification": None})
            return FakeDB._Cur()
        if s.startswith("UPDATE collab_queue SET lane_override='active'"):
            for r in self.queue.values():
                if r.get("signature") == params[0]:
                    r["lane_override"] = "active"
            return FakeDB._Cur()
        if s.startswith("INSERT INTO collab_item_state"):
            self.state.setdefault(params[0], {"signature": params[0],
                                              "first_seen": params[1],
                                              "last_lane": None})
            return FakeDB._Cur()
        if s.startswith("UPDATE collab_item_state SET last_lane"):
            if len(params) == 1:        # literal lane in SQL (restore_to_active)
                sig, lane = params[0], "active"
            else:
                lane, sig = params[0], params[1]
            if sig in self.state:
                self.state[sig]["last_lane"] = lane
            return FakeDB._Cur()
        return FakeDB._Cur()


def _rig(monkeypatch, flags):
    fdb = FakeDB()
    monkeypatch.setattr(collab.db, "db_configured", lambda: True)
    monkeypatch.setattr(collab.db, "get_conn", lambda: fdb)
    monkeypatch.setattr(collab, "migrate", lambda: True)
    actions = []
    monkeypatch.setattr(collab, "record_action",
                        lambda actor, desc, **kw: actions.append(desc))
    holder = {"flags": flags}
    monkeypatch.setattr(collab, "_live_flags", lambda snap=None: [
        {"flag_id": collab._flag_id(f), "title": f["title"],
         "detail": f.get("action"), "category": f["category"]}
        for f in holder["flags"]])
    monkeypatch.setattr(collab, "_churned_subjects", lambda: {})
    return fdb, holder, actions


def _item(title, category="data_quality", action=""):
    return {"severity": "S2", "category": category, "title": title, "action": action}


MRR_OLD = _item("MRR $72,275 with only 1 active sub(s) implies $72,275/sub — Stripe MCP may be miscounting")
MRR_NEW = _item("MRR $59,316 with only 1 active sub(s) implies $59,316/sub — Stripe MCP may be miscounting")
DEALS_1 = _item("1 won deal(s) not on Health tab: Butlers cucina — MRR may be understated")
DEALS_2 = _item("2 won deal(s) not on Health tab: Butlers cucina, Il Ritrovo — MRR may be understated")


# ── the signature scheme (prod-evidenced cases) ──────────────────────────────

def test_signature_survives_metric_drift():
    # the EXACT prod resurrection case: MRR figure drifted → same problem-state
    assert collab.flag_signature(MRR_OLD) == collab.flag_signature(MRR_NEW)


def test_signature_rearms_on_new_state():
    # the EXACT prod case the other way: Il Ritrovo JOINING is a new state
    assert collab.flag_signature(DEALS_1) != collab.flag_signature(DEALS_2)


def test_signature_stable_across_age_and_contract_gain():
    a = _item("Hono: won but Close Date blank (contract —) — invisible")
    b = _item("Hono: won but Close Date blank (contract 12500.0) — invisible")
    assert collab.flag_signature(a) == collab.flag_signature(b)
    p1 = _item("Sheet edit needed: Hono (churn declared) — pending 3d")
    p2 = _item("Sheet edit needed: Hono (churn declared) — pending 11d")
    assert collab.flag_signature(p1) == collab.flag_signature(p2)


# ── THE WITNESSED FAILURE, RE-RUN: mark done → clears → STAYS cleared ────────

def test_mark_done_clears_and_sticks_across_reloads(monkeypatch):
    fdb, holder, _ = _rig(monkeypatch, [MRR_OLD, DEALS_1])
    fid = collab._flag_id(MRR_OLD)
    q0 = collab.queue()
    assert sum(1 for i in q0 if i["lane"] == "active") == 2
    r = collab.resolve_item(fid, "known Stripe MCP quirk — confirmed with Rydel",
                            {"user": "piolo"})
    assert r["ok"] and r["suppressed"] is True
    for _reload in range(3):                     # N reloads — the generator rebuilds
        q = collab.queue()
        active = [i for i in q if i["lane"] == "active"]
        done = [i for i in q if i["lane"] == "done"]
        assert not any("stripe-mcp" in i["flag_id"] for i in active)   # GONE from active
        assert any("stripe-mcp" in i["flag_id"] for i in done)         # visible in Done
    # metric drift: MRR moves to $59,316 → NEW flag_id, SAME signature → still done
    holder["flags"] = [MRR_NEW, DEALS_1]
    q = collab.queue()
    active = [i for i in q if i["lane"] == "active"]
    assert not any("stripe-mcp" in i["flag_id"] for i in active)   # dismissal STICKS
    assert collab.queue_count() == 1                              # only DEALS_1


def test_changed_state_rearms_with_new_reason(monkeypatch):
    fdb, holder, _ = _rig(monkeypatch, [DEALS_1])
    collab.resolve_item(collab._flag_id(DEALS_1), "added Butlers to Health",
                        {"user": "piolo"})
    assert collab.queue_count() == 0
    # Il Ritrovo joins → genuinely new state → re-arms as ACTIVE (new signature)
    holder["flags"] = [DEALS_2]
    q = collab.queue()
    active = [i for i in q if i["lane"] == "active"]
    assert len(active) == 1 and "il-ritrovo" in active[0]["flag_id"]
    # and the OLD dismissal auto-verifies as resolved-at-source in the Done view
    done = [i for i in q if i["lane"] == "done"]
    assert any(i.get("lane_reason") == "resolved at source (auto-verified)"
               for i in done)


def test_undismiss_restores_to_active(monkeypatch):
    fdb, holder, _ = _rig(monkeypatch, [MRR_OLD])
    fid = collab._flag_id(MRR_OLD)
    collab.resolve_item(fid, "handled", {"user": "piolo"})
    assert collab.queue_count() == 0
    assert collab.un_dismiss(fid, {"user": "rydel"})["ok"]
    assert collab.queue_count() == 1                              # back in active


# ── relevance gating ─────────────────────────────────────────────────────────

def test_churned_client_demotes_to_aged_with_reason(monkeypatch):
    ghost = _item("Vietnamese Mint: won but Close Date blank (contract 9800.0) — invisible")
    live = _item("Hono Grill: won but Close Date blank (contract 12500.0) — invisible")
    fdb, holder, _ = _rig(monkeypatch, [ghost, live])
    monkeypatch.setattr(collab, "_churned_subjects",
                        lambda: {"vietnamesemint": "known churned client"})
    q = collab.queue()
    aged = [i for i in q if i["lane"] == "aged"]
    active = [i for i in q if i["lane"] == "active"]
    assert len(aged) == 1 and "vietnamese" in aged[0]["flag_id"]
    assert "churned" in aged[0]["lane_reason"] and "archaeology" in aged[0]["lane_reason"]
    assert len(active) == 1 and "hono" in active[0]["flag_id"]    # live deal stays LOUD
    assert collab.queue_count() == 1                              # aged never counted


def test_stale_immaterial_ages_but_material_never_does(monkeypatch):
    small = _item("Setter note formatting looks off in 3 rows", action="tidy the cells")
    big = _item("Tong Ou: won but Close Date blank (contract 18000.0) — invisible")
    fdb, holder, _ = _rig(monkeypatch, [small, big])
    old = dt.date.today() - dt.timedelta(days=120)
    for f in (small, big):
        sig = collab.flag_signature(
            {"flag_id": "", "title": f["title"], "detail": f.get("action"),
             "category": f["category"]})
        fdb.state[sig] = {"signature": sig, "first_seen": old, "last_lane": None}
    q = collab.queue()
    lanes = {i["flag_id"]: i for i in q}
    small_it = next(i for i in q if "formatting" in i["flag_id"])
    big_it = next(i for i in q if "tong-ou" in i["flag_id"])
    assert small_it["lane"] == "aged" and "materiality floor" in small_it["lane_reason"]
    assert big_it["lane"] == "active"                             # MATERIALITY GUARD
    assert "MATERIAL" in (big_it["lane_reason"] or "")
    assert big_it["age_days"] >= 120                              # real persisted age


def test_restore_to_active_overrides_demotion(monkeypatch):
    ghost = _item("Vietnamese Mint: won but Close Date blank (contract 9800.0) — invisible")
    fdb, holder, _ = _rig(monkeypatch, [ghost])
    monkeypatch.setattr(collab, "_churned_subjects",
                        lambda: {"vietnamesemint": "known churned client"})
    q = collab.queue()
    sig = q[0]["signature"]
    assert q[0]["lane"] == "aged"
    assert collab.restore_to_active(sig, {"user": "rydel"})["ok"]
    q2 = collab.queue()
    assert q2[0]["lane"] == "active" and q2[0]["lane_reason"] == "restored by owner"
    assert collab.queue_count() == 1


# ── excluded ≠ deleted + journaling + idempotence ────────────────────────────

def test_nothing_deleted_and_transitions_journaled_once(monkeypatch):
    fdb, holder, actions = _rig(monkeypatch, [MRR_OLD, DEALS_1])
    monkeypatch.setattr(collab, "_churned_subjects", lambda: {})
    collab.resolve_item(collab._flag_id(MRR_OLD), "done", {"user": "piolo"})
    collab.queue(); collab.queue(); collab.queue()
    # the dismissal row still exists (retrievable), never deleted
    assert any(r.get("status") == "resolved" for r in fdb.queue.values())
    # lane transition journaled ONCE, not once per build
    lane_actions = [a for a in actions if "→ done" in a]
    assert len(lane_actions) == 1
    # idempotent: same item count every build, no dupes
    ns = [len(collab.queue()) for _ in range(3)]
    assert len(set(ns)) == 1


def test_counts_reflect_active_only(monkeypatch):
    ghost = _item("Vietnamese Mint: old flag (contract 9800.0)")
    fdb, holder, _ = _rig(monkeypatch, [MRR_OLD, ghost])
    monkeypatch.setattr(collab, "_churned_subjects",
                        lambda: {"vietnamesemint": "known churned client"})
    collab.resolve_item(collab._flag_id(MRR_OLD), "done", {"user": "piolo"})
    lanes = collab.queue_lanes()
    assert len(lanes["active"]) == 0
    assert len(lanes["aged"]) == 1 and len(lanes["done"]) == 1
    assert collab.queue_count() == 0
    # EDITH's answer names active only + the aged count separately
    reply, handled = collab.handle_collab_command("what's in Piolo's queue?",
                                                  {"user": "rydel"})
    assert handled and "clear" in reply.lower() and "1 aged" in reply


def test_sentinel_watch_reports_lanes(monkeypatch):
    fdb, holder, _ = _rig(monkeypatch, [MRR_OLD])
    kv_store.delete("collab:queue_watch")
    w = collab.sentinel_watch()
    assert w["active"] == 1 and w["aged"] == 0 and w["done"] == 0


# ── route gating: queue admin (un-dismiss / restore) is owner-side ───────────

def test_queue_admin_routes_owner_only(monkeypatch):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    monkeypatch.setenv("RYDEL_PASSWORD", "rp")
    monkeypatch.setenv("PIOLO_PASSWORD", "pp")
    from app import app
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/dashboard/login",
                  data={"username": "piolo", "password": "pp"}).status_code == 302
    assert c.post("/dashboard/api/collab/undismiss",
                  json={"flag_id": "x"}).status_code == 403
    assert c.post("/dashboard/api/collab/restore",
                  json={"signature": "x"}).status_code == 403
    # Piolo can still RESOLVE (it's his queue) — never 403'd from resolving
    r = c.post("/dashboard/api/collab/resolve", json={"flag_id": "nope", "note": "n"})
    assert r.status_code != 403          # (500 here = no test DB, not a gate)


def test_legacy_partial_rows_suppress_and_verified_history_shows(monkeypatch):
    """Pre-fix rows: 'partial' (resolved, source unchanged, nagged) must
    suppress like a dismissal; dead 'verified' rows stay viewable in Done."""
    fdb, holder, _ = _rig(monkeypatch, [MRR_OLD])
    fid = collab._flag_id(MRR_OLD)
    fdb.queue[fid] = {"flag_id": fid, "title": MRR_OLD["title"], "status": "partial",
                      "resolution": "pre-fix done", "resolved_by": "piolo",
                      "signature": None, "lane_override": None}
    fdb.queue["old-verified"] = {"flag_id": "old-verified", "title": "an old fixed thing",
                                 "status": "verified", "resolution": "fixed",
                                 "resolved_by": "piolo",
                                 "signature": "deadbeefdeadbeef", "lane_override": None}
    q = collab.queue()
    lanes = {i["flag_id"]: i["lane"] for i in q}
    assert lanes[fid] == "done"                      # legacy partial suppresses
    assert lanes.get("old-verified") == "done"       # history viewable in Done
    assert collab.queue_count() == 0
