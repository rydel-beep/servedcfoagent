"""
tests/test_csm_declarations.py
------------------------------
CSM wave: DOWNSELL/CONTINUITY + EXPANSION join the ONE declaration flow.
Preview validation, normalisation via THE one function, sheet-reflection
semantics, Piolo edit text, and projection integration for the new kinds.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import datetime as dt

import client_overrides as co
import renewal_loop as rl

_ROSTER = [
    {"name": "Hono Grill", "current_mrr": 3050, "status": "Active",
     "contract_end": "2026-10-01"},
    {"name": "Naan Sense", "current_mrr": 2400, "status": "Active",
     "contract_end": "2026-09-15"},
]


def _rig(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: [dict(c) for c in _ROSTER])


# ── kinds enum ───────────────────────────────────────────────────────────────

def test_kinds_enum_has_new_types():
    assert "downsell" in co.DECLARATION_KINDS
    assert "expansion" in co.DECLARATION_KINDS
    assert set(co.EXPANSION_SUBTYPES) == {
        "stepup", "sprint", "ordering", "reservations", "photo_day",
        "market_intel", "second_venue", "referral"}


def test_unknown_kind_still_rejected(monkeypatch):
    _rig(monkeypatch)
    prev, err = co.preview_declaration("Hono Grill", "sidegrade")
    assert prev is None and "unknown declaration kind" in err


# ── downsell / continuity ────────────────────────────────────────────────────

def test_downsell_preview_normalises_and_validates(monkeypatch):
    _rig(monkeypatch)
    prev, err = co.preview_declaration("Hono Grill", "downsell",
                                       amount=499, cadence="monthly",
                                       reason="renewal no — floor save")
    assert err is None
    p = prev["payload"]
    assert p["change_type"] == "downsell" and p["subtype"] == "continuity"
    assert p["new_mrr"] == 499 and p["new_status"] == "Active"
    assert "CONTINUITY" in prev["preview"] and "SAVED vs churn-to-zero" in prev["preview"]
    assert prev["mrr_delta"] == 499 - 3050


def test_downsell_rejects_zero_and_above_current(monkeypatch):
    _rig(monkeypatch)
    _, err = co.preview_declaration("Hono Grill", "downsell", new_mrr=0)
    assert "above zero" in err
    _, err2 = co.preview_declaration("Hono Grill", "downsell", new_mrr=5000)
    assert "must be below" in err2
    _, err3 = co.preview_declaration("Hono Grill", "downsell",
                                     amount=499, cadence="one_off")
    assert "recurring" in err3


def test_downsell_sheet_reflection_like_downgrade():
    ov = {"change_type": "downsell", "client_name": "Hono Grill",
          "new_mrr": 499, "old_end": "2026-10-01"}
    ok, _ = rl._sheet_reflects(ov, {"monthly_recognized": 499, "status": "Active"})
    assert ok
    ok2, _ = rl._sheet_reflects(ov, {"monthly_recognized": 3050, "status": "Active"})
    assert not ok2


def test_downsell_piolo_text_names_continuity():
    ov = {"change_type": "downsell", "client_name": "Hono Grill",
          "new_mrr": 499, "amount": 499, "cadence": "monthly"}
    txt = rl.piolo_edit_text(ov)
    assert "CONTINUITY" in txt and "$499" in txt and "keep Active" in txt


# ── expansion ────────────────────────────────────────────────────────────────

def test_expansion_requires_subtype_and_amount(monkeypatch):
    _rig(monkeypatch)
    _, err = co.preview_declaration("Naan Sense", "expansion", amount=800)
    assert "subtype" in err
    _, err2 = co.preview_declaration("Naan Sense", "expansion", subtype="stepup")
    assert "amount" in err2
    _, err3 = co.preview_declaration("Naan Sense", "expansion",
                                     subtype="upsell", amount=800)
    assert "subtype" in err3


def test_expansion_recurring_adds_on_top(monkeypatch):
    _rig(monkeypatch)
    prev, err = co.preview_declaration(
        "Naan Sense", "expansion", subtype="ordering", amount=249,
        cadence="monthly", term_months=6, start_date="2026-09-01")
    assert err is None
    p = prev["payload"]
    assert p["new_mrr"] == 2400 + 249          # additive, never replacing
    assert p["subtype"] == "ordering"
    assert p["first6_value"] == 249 * 6         # derived honestly
    assert p["effective_date"] == "2027-03-01"  # start + term
    assert prev["mrr_delta"] == 249


def test_expansion_one_off_default_cadence_and_cash(monkeypatch):
    _rig(monkeypatch)
    prev, err = co.preview_declaration(
        "Naan Sense", "expansion", subtype="photo_day", amount=1200,
        start_date="2026-09-01")
    assert err is None
    p = prev["payload"]
    assert p["cadence"] == "one_off"           # natural default by subtype
    assert p["new_mrr"] == 2400                # MRR untouched
    assert p["first6_value"] == 1200
    assert "NOT recurring MRR" in prev["preview"]
    assert prev["mrr_delta"] == 0


def test_expansion_first6_value_explicit_wins(monkeypatch):
    _rig(monkeypatch)
    prev, _ = co.preview_declaration(
        "Naan Sense", "expansion", subtype="stepup", amount=500,
        cadence="monthly", term_months=12, first6_value=2750)
    assert prev["payload"]["first6_value"] == 2750


def test_expansion_sheet_reflection():
    # recurring: converges when Monthly Recognized lands on the new total
    ov = {"change_type": "expansion", "client_name": "Naan Sense",
          "new_mrr": 2649, "cadence": "monthly", "old_end": "2026-09-15"}
    ok, _ = rl._sheet_reflects(ov, {"monthly_recognized": 2649})
    assert ok
    ok2, _ = rl._sheet_reflects(ov, {"monthly_recognized": 2400})
    assert not ok2
    # one-off: converged by definition (cash event, tracker is the record)
    ov1 = {"change_type": "expansion", "client_name": "Naan Sense",
           "cadence": "one_off", "old_end": "2026-09-15"}
    ok3, _ = rl._sheet_reflects(ov1, {"monthly_recognized": 2400})
    assert ok3


def test_expansion_piolo_text_by_cadence():
    rec = rl.piolo_edit_text({"change_type": "expansion", "client_name": "N",
                              "subtype": "ordering", "amount": 249,
                              "cadence": "monthly", "term_months": 6,
                              "new_mrr": 2649, "start_date": "2026-09-01"})
    assert "EXPANSION" in rec and "ordering" in rec and "$2,649" in rec
    one = rl.piolo_edit_text({"change_type": "expansion", "client_name": "N",
                              "subtype": "sprint", "amount": 3000,
                              "cadence": "one_off", "start_date": "2026-09-01"})
    assert "one-off sprint" in one and "tracker" in one.lower()


def test_unknown_kind_piolo_text_is_loud_not_wrong():
    txt = rl.piolo_edit_text({"change_type": "mystery", "client_name": "N"})
    assert "UNRECOGNISED" in txt and "downgrade" not in txt


# ── projection integration ───────────────────────────────────────────────────

def _proj_with(monkeypatch, overrides, sheet_clients):
    import forward_projection as fp
    import forward_mrr
    monkeypatch.setattr(forward_mrr, "per_client_recognition",
                        lambda: {"clients": sheet_clients, "degraded": []})
    monkeypatch.setattr(co, "active_overrides", lambda: overrides)
    import kv_store
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: default)
    return fp.project()


def _labels():
    import forward_projection as fp
    from helpers import today_sydney
    return fp._horizon_labels(today_sydney(), 12)


def test_projection_downsell_caps_committed(monkeypatch):
    labels = _labels()
    sheet = {"Hono Grill": {"monthly": {labels[0]: 3050, labels[1]: 3050,
                                        labels[2]: 3050},
                            "monthly_value": 3050}}
    from helpers import today_sydney
    ov = [{"client_name": "Hono Grill", "change_type": "downsell",
           "new_mrr": 499, "effective_date": str(today_sydney()),
           "start_date": None, "amount": 499, "cadence": "monthly",
           "term_months": None, "id": 1, "created_at": "2026-08-17"}]
    out = _proj_with(monkeypatch, ov, sheet)
    assert out["committed"][0] == 499          # floor caps the sheet months
    assert out["committed"][1] == 499
    assert out["reconciliation"]["declarations_touching_month0"] == ["Hono Grill"]


def test_projection_expansion_recurring_is_additive(monkeypatch):
    labels = _labels()
    sheet = {"Naan Sense": {"monthly": {labels[0]: 2400, labels[1]: 2400},
                            "monthly_value": 2400}}
    from helpers import today_sydney
    today = today_sydney()
    ov = [{"client_name": "Naan Sense", "change_type": "expansion",
           "subtype": "ordering", "amount": 249, "cadence": "monthly",
           "term_months": 6, "start_date": str(today),
           "effective_date": str(co._add_months(today, 6)),
           "new_mrr": 2649, "id": 2, "created_at": "2026-08-17"}]
    out = _proj_with(monkeypatch, ov, sheet)
    assert out["committed"][0] == 2400 + 249   # additive on top of the sheet
    assert out["committed"][1] == 2400 + 249
    # after the sheet's committed months, only the expansion stream remains
    assert out["committed"][2] == 249
    assert out["oneoff_cash"][0] == 0


def test_projection_expansion_one_off_is_cash_never_mrr(monkeypatch):
    labels = _labels()
    sheet = {"Naan Sense": {"monthly": {labels[0]: 2400}, "monthly_value": 2400}}
    from helpers import today_sydney
    today = today_sydney()
    ov = [{"client_name": "Naan Sense", "change_type": "expansion",
           "subtype": "sprint", "amount": 3000, "cadence": "one_off",
           "term_months": 1, "start_date": str(today),
           "effective_date": str(co._add_months(today, 1)),
           "new_mrr": 2400, "id": 3, "created_at": "2026-08-17"}]
    out = _proj_with(monkeypatch, ov, sheet)
    assert out["oneoff_cash"][0] == 3000
    assert out["committed"][0] == 2400         # MRR untouched
