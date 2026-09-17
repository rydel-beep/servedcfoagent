"""
tests/test_scrutiny.py
----------------------
#150 — the label law (no bare ambiguous tile labels), the drawers, the
three nets (tax banded beside, never inside), the AR engine (pending is
never cash; aging sums; alias proposals never auto-assign), the honest
CAC pair (loaded vs spend-only both present and different), the ROAS panel
fixes (cohort headline, receipts demoted, derived chipped), and the
sheet-renewal projection lane's no-double-count rule.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import datetime as dt

import receivables as R
import tile_drawers as TD

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _kv(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    return store


# ── the label law ───────────────────────────────────────────────────────────

def test_no_bare_ambiguous_labels_rendered():
    """The bare labels Rydel misread must be gone; the qualified forms must
    exist. Greps the RENDERED label strings in JS + HTML."""
    js = open(os.path.join(_ROOT, "dashboard/static/js/dashboard.js")).read()
    html = open(os.path.join(_ROOT, "dashboard/templates/dashboard.html")).read()
    # dead bare labels
    for bare in ('>Net Cash Flow<', '"fc-line">Net <strong>',
                 ">Cash Collected <", '>Cash Net<', '>Recognized Net<',
                 "' committed</strong>'"):
        assert bare not in js and bare not in html, f"bare label survives: {bare}"
    # qualified forms present
    for good in ("Cash net (30d flow)", "Forecast net (projection)",
                 "committed MRR (revenue)", "Cash collected (tracker cells)",
                 "Cash net (receipts − banded OpEx)",
                 "Recognized net (Xero P&L)",
                 "tax-blended — Xero's line",
                 "Operating net (tax/statutory + personal banded beside)"):
        assert good in js or good in html, f"qualified label missing: {good}"


def test_headline_tiles_have_doors():
    js = open(os.path.join(_ROOT, "dashboard/static/js/dashboard.js")).read()
    html = open(os.path.join(_ROOT, "dashboard/templates/dashboard.html")).read()
    for tile in ("committed_mrr", "three_nets", "forecast_net",
                 "ar_outstanding"):
        assert f'data-findrawer="{tile}"' in js or f'data-findrawer="{tile}"' in html, tile
    assert "closest('.fin-door[data-findrawer]')" in js


def test_drawer_registry_unknown_tile_honest():
    out = TD.drawer("nonsense_tile")
    assert "unknown tile" in out["error"] and "committed_mrr" in out["known"]


# ── three nets ──────────────────────────────────────────────────────────────

def test_three_nets_tax_banded_beside_never_inside(monkeypatch):
    _kv(monkeypatch)
    import finance_analysis
    monkeypatch.setattr(finance_analysis, "_receipts_in_window",
                        lambda w0, w1: {"available": True, "total": 30000.0,
                                        "source": "stripe test"})
    import outflow_bands
    from helpers import today_sydney
    cur = str(today_sydney())[:7]
    monkeypatch.setattr(outflow_bands, "monthly_bands", lambda n: {
        "months": [{"month": cur, "opex": 20000.0, "tax_statutory": 26553.75,
                    "personal": 129.0, "flagged": 0.0,
                    "blended_total": 46682.75}]})
    import snapshot
    monkeypatch.setattr(snapshot, "load_persisted", lambda: {
        "monthly_burn": {"total_recurring_burn": 33000.0},
        "cash_position": {"cash_in_bank": 150000.0}})
    import tile_drawers
    monkeypatch.setattr(tile_drawers, "_bank_anchor",
                        lambda: {"date": "2026-09-01", "balance": 140000.0,
                                 "basis": "test"})
    monkeypatch.setattr(R, "expected_month_end",
                        lambda: {"available": True,
                                 "outstanding_expected_this_month": 9000.0})
    nets = tile_drawers.three_nets()
    op = nets["operating_net_mtd"]
    # receipts 30,000 − OpEx band 20,000 = 10,000 — the tax lump NEVER inside
    assert op["value"] == 10000.0
    tax_comp = next(c for c in op["components"] if "tax/statutory" in c["label"])
    assert tax_comp["value"] == 26553.75
    assert "NEVER inside" in tax_comp["label"]
    bank = nets["cash_net_mtd_bank"]
    assert bank["value"] == 10000.0            # 150k − 140k anchor
    exp = nets["expected_month_end"]
    assert "projection" in exp["label"].lower()
    assert "never cash" in exp["label"].lower() or "never cash" in nets["law"]


# ── AR ──────────────────────────────────────────────────────────────────────

def _ar_rig(monkeypatch, charges, clients):
    _kv(monkeypatch)
    import forward_mrr
    monkeypatch.setattr(forward_mrr, "per_client_recognition",
                        lambda: {"clients": clients, "degraded": []})
    import finance_tabs
    monkeypatch.setattr(finance_tabs, "sheet_renewals_for_projection", lambda: {})
    import cash_truth
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda d: charges)


def _charge(email, name, amount, date):
    from helpers import SYDNEY_TZ
    t = dt.datetime.combine(date, dt.time(12), tzinfo=SYDNEY_TZ)
    return {"paid": True, "status": "succeeded", "amount": int(amount * 100),
            "amount_refunded": 0, "created": int(t.timestamp()),
            "billing_details": {"email": email, "name": name}}


def test_ar_pending_never_cash_and_aging_sums(monkeypatch):
    from helpers import today_sydney
    t = today_sydney()
    lbl = t.strftime("%B %Y")
    prev = (t.replace(day=1) - dt.timedelta(days=1)).strftime("%B %Y")
    clients = {
        "Bar Elvina": {"monthly": {prev: 2350.0, lbl: 2350.0}},
        "Paid Cafe": {"monthly": {lbl: 3000.0}},
    }
    charges = [_charge("paid@cafe.com", "Paid Cafe", 3000.0, t.replace(day=2))]
    _ar_rig(monkeypatch, charges, clients)
    ar = R.build_ar(fresh=True)
    assert ar["ok"]
    by = {r["client"]: r for r in ar["rows"]}
    assert by["Bar Elvina"]["outstanding"] == 4700.0     # two months unpaid
    assert by["Bar Elvina"]["status"] in ("overdue", "pending")
    assert by["Bar Elvina"]["days_overdue"] > 0          # prev month aged
    assert by["Paid Cafe"]["outstanding"] == 0.0
    assert by["Paid Cafe"]["status"] == "paid"
    # aging buckets sum to total outstanding
    assert abs(sum(ar["aging"].values()) - ar["total_outstanding"]) < 0.01
    # pending is NEVER cash: the law rides the payload
    assert "never" in ar["law"].lower()


def test_ar_unmatched_becomes_proposal_never_assigned(monkeypatch):
    from helpers import today_sydney
    t = today_sydney()
    lbl = t.strftime("%B %Y")
    clients = {"Glen Fitzgerald Cafe": {"monthly": {lbl: 5500.0}}}
    charges = [_charge("fiona@x.com", "Fiona FITZGERALD", 5500.0,
                       t.replace(day=9))]
    _ar_rig(monkeypatch, charges, clients)
    ar = R.build_ar(fresh=True)
    assert ar["ok"]
    # the payer didn't match the client (different name) → proposal, and the
    # client still shows outstanding (never auto-assigned)
    by = {r["client"]: r for r in ar["rows"]}
    assert by["Glen Fitzgerald Cafe"]["outstanding"] == 5500.0
    props = ar["unmatched_receipts"]
    assert props and props[0]["payer"] == "Fiona FITZGERALD"
    assert "PROPOSED" in props[0]["state"]


def test_ar_alias_store_matches(monkeypatch):
    from helpers import today_sydney
    t = today_sydney()
    lbl = t.strftime("%B %Y")
    clients = {"Tony Thai Cafe": {"monthly": {lbl: 3355.0}}}
    charges = [_charge("a@x.com", "Allan Thai", 3355.0, t.replace(day=3))]
    _ar_rig(monkeypatch, charges, clients)
    import kv_store
    kv_store.put("stripe:payer_aliases", {"Allan Thai": "Tony Thai Cafe"})
    ar = R.build_ar(fresh=True)
    by = {r["client"]: r for r in ar["rows"]}
    assert by["Tony Thai Cafe"]["outstanding"] == 0.0    # alias resolved


def test_ar_stripe_unreachable_never_zero(monkeypatch):
    _ar_rig(monkeypatch, None, {"X": {"monthly": {}}})
    import cash_truth
    monkeypatch.setattr(cash_truth, "_raw_recent_charges", lambda d: None)
    ar = R.build_ar(fresh=True)
    assert ar["ok"] is False and "never fabricated" in ar["reason"]


# ── honest CAC pair + ROAS panel ────────────────────────────────────────────

def test_loaded_and_spend_only_cac_both_present_and_different():
    src = open(os.path.join(_ROOT, "range_unit_economics.py")).read()
    assert "cac_fully_loaded" in src and "cac_spend_only" in src
    assert "never confuse" in src.lower() or "never confused" in src.lower()
    assert "commission-only" in src            # sales labour $0, stated


def test_roas_panel_cohort_headline_receipts_demoted():
    src = open(os.path.join(_ROOT, "finance_analysis.py")).read()
    assert "receipts_ratio_not_attributable" in src
    assert "cash_roas_activity" not in src     # the blended-clock key is dead
    assert "contract_roas_signed_only" in src
    js = open(os.path.join(_ROOT, "dashboard/static/js/dashboard.js")).read()
    assert "Cohort cash ROAS" in js
    assert "not attributable" in js
    assert "derived⚑" in js                    # derived contract chip


def test_ltv_cac_ungated_from_margin(monkeypatch):
    """Xero margin down must not null LTV:CAC (it needs no margin)."""
    src = open(os.path.join(_ROOT, "range_unit_economics.py")).read()
    i_ltv = src.index("ltv_cac = round(comp[\"avg_contract\"] / cac, 2)")
    i_margin = src.index("if margin is not None and comp[\"avg_contract\"]:")
    assert i_ltv < i_margin                    # assigned BEFORE the margin gate


# ── projection ledger lane: no double count ────────────────────────────────

def test_ledger_lane_never_double_counts_grid_months(monkeypatch):
    _kv(monkeypatch)
    import forward_projection as fp
    import forward_mrr
    import finance_tabs
    from helpers import today_sydney
    labels = fp._horizon_labels(today_sydney(), 12)
    sheet = {"Noodle Asia": {"monthly": {labels[0]: 1426.67},
                             "monthly_value": 1426.67}}
    monkeypatch.setattr(forward_mrr, "per_client_recognition",
                        lambda: {"clients": sheet, "degraded": []})
    import client_overrides
    monkeypatch.setattr(client_overrides, "active_overrides", lambda: [])
    monkeypatch.setattr(finance_tabs, "sheet_renewals_for_projection",
                        lambda: {"noodleasia": {
                            "client": "Noodle Asia", "mrr": 1426.67,
                            "from": "2026-08-18", "until": "2027-02-18",
                            "extension": False,
                            "provenance": "sheet renewal ledger (row 42)"}})
    out = fp.project()
    # month 0: the GRID value wins (no +ledger double count)
    assert out["committed"][0] == 1426.67
    # later in-term months: the ledger extends coverage where the grid is blank
    assert out["committed"][2] == 1426.67
    assert out["reconciliation"]["ledger_touching_month0"] == ["Noodle Asia"]
    pc = out["per_client"]["Noodle Asia"]
    assert pc["source"] in ("sheet renewal ledger", "sheet")


# ── #151 · visibility + R-AR-INTERNAL + R-PAID ─────────────────────────────

def test_ratio_tiles_top_section_always_rendered():
    """The shipped-≠-visible fix: the two ratios are TOP-SECTION tiles
    (first in Zone 1), rendered from the honest engine, and a degraded
    input labels the tile instead of hiding it."""
    js = open(os.path.join(_ROOT, "dashboard/static/js/dashboard.js")).read()
    html = open(os.path.join(_ROOT, "dashboard/templates/dashboard.html")).read()
    assert 'id="section-ratio-tiles"' in html
    assert "'section-ratio-tiles'" in js
    # FIRST in the Zone-1 ids array (the top of the top section)
    assert "ids: ['section-ratio-tiles'," in js
    assert "renderRatioTiles()" in js
    assert "unit-econ-honest" in js
    # ALWAYS rendered: the failure paths render text, never hide the section
    assert "the tile stays, the number does not pretend" in js
    assert "ratio tiles failed honestly" in js
    assert "benchmark, not target" in html or "benchmark, not target" in js
    # windows selector present
    assert 'id="ratio-window"' in html
    for opt in ("cohort_month", "trailing_90d", "by_package"):
        assert opt in html


def test_ar_internal_only_no_chase_verbs():
    """R-AR-INTERNAL: the AR module + templates carry no chase/reminder/
    outbound verbs and no GHL calls; 'collections' framing is banned."""
    import re as _re
    chase = _re.compile(r"\b(chase|chasing|remind(er)?s?\b|dunn(ing)?|"
                        r"collections?\b|send_(email|sms|message)|"
                        r"notify_client|outbound)", _re.I)
    for path in ("receivables.py", "dashboard/templates/dashboard.html"):
        src = open(os.path.join(_ROOT, path)).read()
        hits = [m.group(0) for m in chase.finditer(src)]
        assert not hits, f"{path}: chase framing {hits}"
    src = open(os.path.join(_ROOT, "receivables.py")).read()
    assert "leadconnector" not in src.lower()
    assert "ghl_" not in src           # no GHL client import at all
    assert "never chases" in src or "never counts a pending cent" in src


def test_paid_current_override_scoped_and_expiring(monkeypatch):
    """R-PAID: an owner-confirmed current entry renders CURRENT until its
    expiry; unlisted clients untouched; expired entries revert."""
    from helpers import today_sydney
    t = today_sydney()
    lbl = t.strftime("%B %Y")
    clients = {"Phoenix Hotel": {"monthly": {lbl: 3050.0}},
               "Untouched Cafe": {"monthly": {lbl: 2000.0}}}
    charges = [_charge("w@phoenixsydney.com.au", "William Cooney", 2227.5,
                       t.replace(day=11))]
    _ar_rig(monkeypatch, charges, clients)
    import kv_store
    kv_store.put("stripe:payer_aliases", {"William Cooney": "Phoenix Hotel"})
    nxt = str((t.replace(day=1) + dt.timedelta(days=32)).replace(day=1))
    kv_store.put("ar:paid_current", {
        "phoenixhotel": {"until": nxt, "reason": "first-month cadence — "
                         "deposit + proration (owner word)",
                         "charge_ids": ["ch_3UAjyf", "ch_3UEMaa"],
                         "who": "rydel"}})
    ar = R.build_ar(fresh=True)
    by = {r["client"]: r for r in ar["rows"]}
    assert by["Phoenix Hotel"]["status"] == "current"
    assert by["Phoenix Hotel"]["outstanding"] == 0.0
    assert by["Phoenix Hotel"]["owner_confirmed"]["charge_ids"]
    assert by["Untouched Cafe"]["status"] in ("pending", "overdue")   # untouched
    assert by["Untouched Cafe"]["outstanding"] == 2000.0
    # expiry: a past 'until' reverts to the schedule truth
    kv_store.put("ar:paid_current", {
        "phoenixhotel": {"until": str(t - dt.timedelta(days=1)),
                         "reason": "expired", "charge_ids": []}})
    ar2 = R.build_ar(fresh=True)
    by2 = {r["client"]: r for r in ar2["rows"]}
    assert by2["Phoenix Hotel"]["status"] != "current"
