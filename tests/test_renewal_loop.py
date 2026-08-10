"""
tests/test_renewal_loop.py — THE RENEWAL & CHURN TRUTH LOOP (#135).

End-to-end drills on a SANDBOX sheet (CSV fixtures with the REAL header):
declare → pending item with the exact edit → "Piolo edits the sheet" →
scan → CONVERGED (item auto-clears, journaled) · sheet-first change →
SHEET-ORIGINATED with the source chip · deliberate conflict → LOUD lane,
never silently merged · reversal → MRR restored, item retired · schema
drift → loud failure, ZERO rows read · unlinked rows surfaced · idempotent
scans · owner-only 403s · MRR one-engine correctness · the no-sheet-write
boundary (grep).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import client_overrides as co
import kv_store
import renewal_loop as rl

HDR = ("Client Name,Status,Package Type,Service Term,Start Date,End Date,"
       "Contract Value,Monthly Recognized Revenue,,January 2026,February 2026")


def _sheet(*rows) -> bytes:
    return ("\n".join([HDR] + list(rows))).encode()

ROW_HONO = 'Hono Grill,Active,Growth Pro,6 Months,03-01-2026,09-01-2026,"$18,300.00","$3,050.00",,,'
ROW_NAAN = 'Naan Sense,Active,Scale Engine,6 Months,02-15-2026,08-15-2026,"$15,000.00","$2,500.00",,,'
ROW_TOTAL = 'TOTAL,,,,,,"$33,300.00","$5,550.00",,,'

_ROSTER = [
    {"name": "Hono Grill", "current_mrr": 3050, "status": "Active",
     "contract_end": "2026-09-01"},
    {"name": "Naan Sense", "current_mrr": 2500, "status": "Active",
     "contract_end": "2026-08-15"},
]


class FakeStore:
    """In-memory client_overrides store — the drills' sandbox Postgres."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, o):
        row = {"id": len(self.rows) + 1, "active": True, "reconciled": False,
               "created_at": "2026-08-10T10:00:00", "old_end": None,
               "reason": None, "new_mrr": None, **o}
        self.rows.append(row)
        return row["id"]

    def active(self):
        return [dict(r) for r in self.rows if r["active"] and not r["reconciled"]]

    def mark_reconciled(self, oid):
        for r in self.rows:
            if r["id"] == oid:
                r["reconciled"] = True
                return True
        return False

    def reverse(self, oid):
        for r in self.rows:
            if r["id"] == oid and r["active"] and not r["reconciled"]:
                r["active"] = False
                return dict(r)
        return None


def _rig(monkeypatch, store: FakeStore, sheet_bytes: bytes | None):
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: sheet_bytes)
    monkeypatch.setattr(co, "_add", store.add)
    monkeypatch.setattr(co, "active_overrides", store.active)
    monkeypatch.setattr(co, "mark_reconciled", store.mark_reconciled)
    monkeypatch.setattr(co, "_roster", lambda: [dict(c) for c in _ROSTER])
    monkeypatch.setattr(co, "_do_resync", lambda: None)
    monkeypatch.setattr(rl, "_roster_norms",
                        lambda: ({rl._norm(c["name"]) for c in _ROSTER},
                                 [c["name"] for c in _ROSTER]))
    kv_store.delete("renewal:last_scan")
    kv_store.delete("renewal:schema_drift")
    kv_store.put("renewal:journal", [])
    kv_store.put("ads_truth:flags", [])


def _declare(store, kind, client, eff, new_mrr=None, reason=None):
    prev, err = co.preview_declaration(client, kind, effective_date=eff,
                                       new_mrr=new_mrr, reason=reason)
    assert err is None, err
    oid, err = co.apply_declaration(prev["payload"], {"user": "rydel", "role": "owner"})
    assert err is None
    return prev, oid


# ── schema-drift guard (humans edit sheets — loud is the only way) ───────────

def test_schema_drift_fails_loud_zero_rows(monkeypatch):
    store = FakeStore()
    bad = _sheet(ROW_HONO).replace(b"End Date", b"Finish Date")   # a renamed column
    _rig(monkeypatch, store, bad)
    r = rl.scan()
    assert r["ok"] is False
    assert "End Date" in r["schema_drift"] and "layout changed" in r["schema_drift"]
    assert r["degraded"]
    assert kv_store.get("renewal:schema_drift")           # tripped
    assert kv_store.get("renewal:last_scan") is None      # ZERO rows recorded
    items = rl.feed_items()
    assert any(i["severity"] == "S1" and "layout changed" in i["title"] for i in items)
    # a clean scan clears the trip
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    assert rl.scan()["ok"] is True
    assert kv_store.get("renewal:schema_drift") is None


def test_parse_skips_totals_and_blank_rows(monkeypatch):
    parsed, err = rl.parse_sheet(_sheet(ROW_HONO, "", ROW_TOTAL, ROW_NAAN))
    assert err is None
    assert set(parsed["rows"]) == {"honogrill", "naansense"}
    hono = parsed["rows"]["honogrill"]
    assert hono["monthly_recognized"] == 3050.0 and hono["end"] == "09-01-2026"


# ── scan freshness + idempotence ─────────────────────────────────────────────

def test_first_scan_baseline_then_idempotent_no_op(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    r1 = rl.scan()
    assert r1["ok"] and r1["freshness"]["first_scan"] is True
    assert "first scan" in r1["verdict"]
    r2 = rl.scan()
    assert r2["freshness"]["changed_since_last_scan"] is False
    assert "no changes" in r2["verdict"] and r2["diffs"] == []
    # journaled both times
    j = rl.journal_entries()
    assert sum(1 for e in j if e["rule"] == "scan") == 2


def test_sheet_change_diffs_and_freshness(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()
    changed = ROW_NAAN.replace('"$2,500.00"', '"$2,000.00"')
    monkeypatch.setattr(rl, "_fetch_sheet_bytes",
                        lambda: _sheet(ROW_HONO, changed))
    r = rl.scan()
    assert r["freshness"]["changed_since_last_scan"] is True
    assert any(d["kind"] == "field_changed" and d["field"] == "monthly_recognized"
               and d["client"] == "Naan Sense" for d in r["diffs"])


# ── DRILL: declare churn → exact edit → sheet catches up → CONVERGED ─────────

def test_churn_declaration_to_convergence(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()                                        # baseline
    prev, oid = _declare(store, "churn", "Hono Grill", "2026-08-10", reason="moved to in-house")
    assert prev["mrr_delta"] == -3050.0              # the impact preview
    # the Piolo item carries the EXACT edit
    items = rl.feed_items()
    edit = next(i for i in items if "Hono Grill" in i["title"])
    assert "Status=Finished" in edit["action"] and "2026-08-10" in edit["action"]
    assert edit["category"] == "data_quality"        # → collab.queue (Piolo's queue)
    # pending chip before the sheet moves
    r = rl.scan()
    assert any(p["client"] == "Hono Grill" and p["chip"] == "declared · pending sheet"
               for p in r["pending"])
    # "Piolo edits the sandbox sheet as asked"
    churned = ROW_HONO.replace("Active", "Finished")
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: _sheet(churned, ROW_NAAN))
    r2 = rl.scan()
    assert any(c["client"] == "Hono Grill" and "CONVERGED" in c["verdict"]
               for c in r2["converged"])
    assert store.rows[0]["reconciled"] is True       # the item auto-cleared…
    assert rl.feed_items() == [] or not any("Hono Grill" in i["title"]
                                            for i in rl.feed_items())   # …and stops generating
    assert any("converged" in e["rule"] for e in rl.journal_entries())  # journaled
    # idempotent: a third scan converges nothing twice
    assert rl.scan()["converged"] == []


# ── DRILL: renewal declaration (with MRR change) → convergence ───────────────

def test_renewal_declaration_to_convergence(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()
    prev, oid = _declare(store, "renewal", "Naan Sense", "2027-02-15", new_mrr=3000)
    assert prev["mrr_delta"] == 500.0                # upsell at renewal
    assert "2026-08-15 → 2027-02-15" in prev["preview"].replace("contract end ", "")
    edit = next(i for i in rl.feed_items() if "Naan Sense" in i["title"])
    assert "End Date=2027-02-15" in edit["action"] and "$3,000" in edit["action"]
    # sheet catches up: end date AND the new MRR
    renewed = ROW_NAAN.replace("08-15-2026", "02-15-2027").replace('"$2,500.00"', '"$3,000.00"')
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: _sheet(ROW_HONO, renewed))
    r = rl.scan()
    assert any(c["client"] == "Naan Sense" for c in r["converged"])


def test_renewal_mrr_mismatch_stays_pending_with_detail(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()
    _declare(store, "renewal", "Naan Sense", "2027-02-15", new_mrr=3000)
    # Piolo set the date but typo'd the MRR → NOT converged, detail says why
    partial = ROW_NAAN.replace("08-15-2026", "02-15-2027")   # MRR still 2500
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: _sheet(ROW_HONO, partial))
    r = rl.scan()
    assert r["converged"] == []
    assert any("Monthly Recognized" in (c.get("detail") or "") for c in r["conflicts"])


# ── DRILL: deliberate conflict → LOUD, never silently merged ─────────────────

def test_conflict_declared_vs_sheet_is_loud(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()
    _declare(store, "churn", "Hono Grill", "2026-08-10")
    # the sheet instead RENEWS them (end date moves, still Active) — two truths
    moved = ROW_HONO.replace("09-01-2026", "03-01-2027")
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: _sheet(moved, ROW_NAAN))
    r = rl.scan()
    cf = next(c for c in r["conflicts"] if c["client"] == "Hono Grill")
    assert "two different truths" in cf["detail"]
    assert cf["declared"]["source"].startswith("owner declaration")
    assert cf["sheet"]["source"] == "sheet (Piolo)"          # both values + provenance
    assert store.rows[0]["reconciled"] is False              # NEVER silently resolved
    assert any("CONFLICT" in e["rule"] for e in rl.journal_entries())


# ── DRILL: sheet-originated change → ingested with the source chip ───────────

def test_sheet_originated_change_gets_source_chip(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()
    churned = ROW_NAAN.replace("Active", "Finished")         # Piolo edits FIRST
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: _sheet(ROW_HONO, churned))
    r = rl.scan()
    so = next(d for d in r["sheet_originated"] if d["client"] == "Naan Sense")
    assert so["source"] == "sheet" and so["field"] == "status"
    assert any("sheet-originated" in e["rule"] for e in rl.journal_entries())
    assert r["conflicts"] == []                              # legitimate, not a conflict


# ── DRILL: unlinked rows surfaced, never swallowed ───────────────────────────

def test_unlinked_rows_surface(monkeypatch):
    store = FakeStore()
    mystery = 'Mystery Venue,Active,Growth Pro,6 Months,01-01-2026,12-01-2026,"$10,000.00","$1,666.00",,,'
    _rig(monkeypatch, store, _sheet(ROW_HONO, mystery))      # Naan Sense missing
    r = rl.scan()
    assert r["unlinked"]["sheet_rows_without_client"] == ["Mystery Venue"]
    assert r["unlinked"]["clients_without_sheet_row"] == ["Naan Sense"]


# ── DRILL: reversal → restored, item retired, auditable ──────────────────────

def test_reversal_restores_and_retires(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    # kv must NOT ride the fake Postgres conn below — dict-backed kv fake
    kvmem = {"renewal:journal": []}
    monkeypatch.setattr(kv_store, "get", lambda k, d=None: kvmem.get(k, d))
    monkeypatch.setattr(kv_store, "put", lambda k, v: kvmem.__setitem__(k, v))
    monkeypatch.setattr(kv_store, "delete", lambda k: kvmem.pop(k, None))
    monkeypatch.setattr(co.db, "db_configured", lambda: True)
    monkeypatch.setattr(co, "reverse_declaration",
                        co.reverse_declaration)  # real function, fake db below

    class _FakeConn:
        def __init__(self, s): self.s = s
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=()):
            s = self.s
            class _Cur:
                def fetchone(_self):
                    if "SELECT" in sql:
                        for r in s.rows:
                            if r["id"] == params[0] and r["active"] and not r["reconciled"]:
                                return r
                        return None
                    return None
            if "UPDATE" in sql:
                for r in s.rows:
                    if r["id"] == params[0]:
                        r["active"] = False
            return _Cur()
    monkeypatch.setattr(co.db, "get_conn", lambda: _FakeConn(store))
    _declare(store, "churn", "Hono Grill", "2026-08-10")
    row, err = co.reverse_declaration(1, {"user": "rydel"})
    assert err is None and row["client_name"] == "Hono Grill"
    assert store.rows[0]["active"] is False                  # EXCLUDED ≠ DELETED
    assert store.active() == []                              # no longer applies
    assert rl.feed_items() == []                             # Piolo item retired
    assert any("reversed" in e["rule"] for e in rl.journal_entries())


# ── IDs are truth: no phantom clients, ambiguity honest ──────────────────────

def test_unknown_client_is_honest_not_phantom(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: [dict(c) for c in _ROSTER])
    prev, err = co.preview_declaration("Totally Made Up Cafe", "churn")
    assert prev is None and "not a known client" in err


def test_renewal_requires_a_date(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: [dict(c) for c in _ROSTER])
    prev, err = co.preview_declaration("Hono Grill", "renewal")
    assert prev is None and "renewal/term end date" in err


# ── one-engine MRR correctness ───────────────────────────────────────────────

def test_renewal_override_moves_contract_end_in_the_one_engine():
    """A declared renewal changes Churn-Risk/Renewal-Watch membership via the
    SAME loop every consumer reads — no side-channel math."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "finance_sheets_pull.py")).read()
    i = src.index('change_type") == "renewal"')
    block = src[i - 200:i + 600]
    assert "contract_end = date.fromisoformat" in block
    # membership recomputes from contract_end BELOW the override — order matters
    assert src.index('change_type") == "renewal"') < src.index("days_to_end = (contract_end - today).days")


def test_declared_chip_states():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "finance_sheets_pull.py")).read()
    assert "declared · pending sheet" in src and "declared ✓ sheet" in src


# ── THE BOUNDARY: no sheet write path exists, under any framing ──────────────

def test_no_sheet_write_verbs_anywhere():
    """Grep the loop's modules for Sheets write calls — MUST be zero. The
    boundary is architectural (DECISIONS #135), not a missing feature."""
    import re as _re
    bad = _re.compile(
        r"(batchUpdate|values:append|values:update|values\.append|values\.update|"
        r"spreadsheets\.values\.(append|update)|\.post\(.{0,80}docs\.google|"
        r"\.put\(.{0,80}docs\.google|requests\.(post|put|patch|delete)\(.{0,90}"
        r"(docs\.google|sheets\.googleapis))", _re.I)
    root = os.path.join(os.path.dirname(__file__), "..")
    for fn in ("renewal_loop.py", "client_overrides.py", "finance_sheets_pull.py",
               "sheet_mirror.py", "dashboard/routes.py"):
        src = open(os.path.join(root, fn)).read()
        assert not bad.search(src), f"sheet WRITE verb found in {fn}"


# ── sentinel watches ─────────────────────────────────────────────────────────

def test_sentinel_watch_staleness_and_ageing(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    # no scan ever → stale
    w = rl.sentinel_watch()
    assert w["scan_stale"] is True
    # aged pending: declaration 8 days old
    store.add({"client_name": "Hono Grill", "change_type": "churn",
               "effective_date": "2026-08-01", "old_mrr": 3050,
               "created_at": "2026-08-02T09:00:00"})
    w2 = rl.sentinel_watch()
    assert any(p["client"] == "Hono Grill" and p["age_days"] > 5
               for p in w2["pending_aged"])
    flags = " ".join(f["reason"] for f in kv_store.get("ads_truth:flags"))
    assert "unconverged" in flags and "no sheet scan" in flags


def test_nightly_scan_flags_conflicts_loud(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, _sheet(ROW_HONO, ROW_NAAN))
    rl.scan()
    _declare(store, "churn", "Hono Grill", "2026-08-10")
    moved = ROW_HONO.replace("09-01-2026", "03-01-2027")
    monkeypatch.setattr(rl, "_fetch_sheet_bytes", lambda: _sheet(moved, ROW_NAAN))
    kv_store.put("ads_truth:flags", [])
    rl.nightly_scan()
    flags = [f for f in kv_store.get("ads_truth:flags")
             if f["metric"] == "ads_truth_action"]
    assert any("CONFLICT" in f["reason"] and "Hono Grill" in f["reason"] for f in flags)


def test_degraded_sheet_renders_degraded_never_stale_verdict(monkeypatch):
    store = FakeStore()
    _rig(monkeypatch, store, None)                   # sheet unreachable
    r = rl.scan()
    assert r["ok"] is False and r["degraded"]
    assert "verdict" not in r                        # NO verdict — F5 family


# ── route security: owner-only declare + scan (adversarial) ──────────────────

def _client_as(monkeypatch, user, password):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    monkeypatch.setenv("RYDEL_PASSWORD", "rydel-pw")
    monkeypatch.setenv("PIOLO_PASSWORD", "piolo-pw")
    from app import app
    app.config["TESTING"] = True
    c = app.test_client()
    r = c.post("/dashboard/login", data={"username": user, "password": password})
    assert r.status_code == 302
    return c


def test_non_owner_403_on_declare_and_scan(monkeypatch):
    c = _client_as(monkeypatch, "piolo", "piolo-pw")
    assert c.post("/dashboard/api/renewal/scan").status_code == 403
    assert c.post("/dashboard/api/renewal/declare",
                  json={"stage": "preview", "client": "X", "kind": "churn"}
                  ).status_code == 403
    assert c.get("/dashboard/api/renewal/clients?q=h").status_code == 403
    assert c.post("/dashboard/api/renewal/reverse",
                  json={"id": 1, "confirm": True}).status_code == 403
    # the coo still SEES the loop state (full visibility, no write authority)
    assert c.get("/dashboard/api/renewal/state").status_code == 200


def test_owner_unknown_client_400_honest(monkeypatch):
    c = _client_as(monkeypatch, "rydel", "rydel-pw")
    monkeypatch.setattr(co, "_roster", lambda: [dict(x) for x in _ROSTER])
    r = c.post("/dashboard/api/renewal/declare",
               json={"stage": "preview", "client": "Totally Made Up Cafe",
                     "kind": "churn"})
    assert r.status_code == 400
    assert "not a known client" in r.get_json()["error"]


def test_anon_gets_nothing(monkeypatch):
    import dashboard.auth as auth_mod
    auth_mod.DASHBOARD_TOKEN = "test-dash-token"
    from app import app
    app.config["TESTING"] = True
    c = app.test_client()
    for path, method in (("/dashboard/api/renewal/scan", "post"),
                         ("/dashboard/api/renewal/state", "get"),
                         ("/dashboard/api/renewal/declare", "post"),
                         ("/dashboard/api/renewal/reverse", "post")):
        resp = getattr(c, method)(path)
        assert resp.status_code in (302, 401), path


def test_sentinel_l2_extras_carry_the_renewal_scan(monkeypatch):
    src = open(os.path.join(os.path.dirname(__file__), "..", "ad_sentinel.py")).read()
    i = src.index("def nightly_extras")
    block = src[i:i + 2200]
    assert "renewal_loop" in block and "nightly_scan" in block \
        and "sentinel_watch" in block
