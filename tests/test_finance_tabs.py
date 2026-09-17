"""
tests/test_finance_tabs.py
--------------------------
#150 — every workbook tab mapped at runtime (new/unmapped tab = surfaced),
the RECOGNIZED renewal ledger with row provenance, Sheet5 conflict
surfacing (never merged), month-to-month extensions excluded from committed
coverage, cross-tab deltas caused, and the EXTENSION declaration kind.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import finance_tabs as FT
import client_overrides as co


def _kv(monkeypatch):
    import kv_store
    store = {}
    monkeypatch.setattr(kv_store, "get", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(kv_store, "put", lambda k, v: store.__setitem__(k, v))
    return store


_REC = [
    ["Client Name", "Status", "Package Type", "Service Term", "Renewal Status",
     "Renewal Date", "Renewal Status", "start", "end", "cv", "mrr", "T"],
    ["Noodle Asia", "Active", "Scale Engine", "6 Months", "Renewed",
     "08-18-2026", "BUILD TRUST", "08-18-2026", "02-18-2027",
     "$8,560.00", "$1,426.67", "With"],
    ["Bluebells Takeaway", "Active", "Growth Pro", "6 Months", "Renewed",
     "07-09-2026", "MONTH-MONTH", "07-09-2026", "9/16/2026",
     "$15,300.00", "$2,550.00", "With"],
    ["At Thai", "Active", "Growth Pro", "6 Months", "Renewed",
     "", "BUILD TRUST", "08-21-2026", "02-21-2027",
     "$12,500.00", "$2,083.33", "Potential"],
    ["Old Lost", "Finished", "Growth Pro", "6 Months", "Lost",
     "-", "LOST", "01-01-2026", "07-01-2026", "$15,000.00", "$2,500.00", "W"],
]
_S5 = [
    ["Client Name", "Status", "Package Type", "Service Term", "Renewal Status"],
    ["At Thai", "Active", "Growth Pro", "6 Months", "Pending"],   # conflicts!
    ["Noodle Asia", "Active", "Scale Engine", "6 Months", "Renewed"],
]


def _rig(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(FT, "_fetch_tab_csv",
                        lambda bid, tab: {"RECOGNIZED": _REC, "Sheet5": _S5}.get(tab))
    monkeypatch.setattr(FT, "_books", lambda: {"finance": "F", "ltc": "L"})


def test_renewal_ledger_provenance_and_parse(monkeypatch):
    _rig(monkeypatch)
    led = FT.renewal_ledger(fresh=True)
    by = {e["client"]: e for e in led["entries"]}
    na = by["Noodle Asia"]
    assert na["renewal_status"] == "Renewed"
    assert na["term_start"] == "2026-08-18" and na["term_end"] == "2027-02-18"
    assert na["contract_value"] == 8560.0 and na["mrr"] == 1426.67
    assert na["provenance"] == {"book": "finance", "tab": "RECOGNIZED", "row": 2}
    assert na["extension"] is False


def test_month_to_month_is_extension_not_term(monkeypatch):
    _rig(monkeypatch)
    led = FT.renewal_ledger(fresh=True)
    bb = next(e for e in led["entries"] if e["client"] == "Bluebells Takeaway")
    assert bb["extension"] is True
    proj = FT.sheet_renewals_for_projection()
    assert proj["bluebellstakeaway"]["until"] is None      # never term-committed
    assert proj["noodleasia"]["until"] == "2027-02-18"     # real term commits


def test_sheet5_conflict_surfaced_never_merged(monkeypatch):
    _rig(monkeypatch)
    led = FT.renewal_ledger(fresh=True)
    c = next(x for x in led["conflicts"] if x["client"] == "At Thai")
    assert c["recognized"] == "Renewed" and c["sheet5"] == "Pending"
    assert "never merged" in c["rule"]
    # the entry itself still carries RECOGNIZED's value (primary)
    at = next(e for e in led["entries"] if e["client"] == "At Thai")
    assert at["renewal_status"] == "Renewed" and "Pending" in at["conflict"]


def test_lost_clients_never_enter_projection_coverage(monkeypatch):
    _rig(monkeypatch)
    FT.renewal_ledger(fresh=True)
    proj = FT.sheet_renewals_for_projection()
    assert "oldlost" not in proj


def test_unmapped_tab_surfaced(monkeypatch):
    _kv(monkeypatch)
    monkeypatch.setattr(FT, "_books", lambda: {"finance": "F"})
    monkeypatch.setattr(FT, "_fetch_xlsx_names",
                        lambda bid: ["RECOGNIZED", "ACTUAL", "Totally New Tab"])
    tm = FT.enumerate_tabs(force=True)
    assert {"book": "finance", "tab": "Totally New Tab"} in tm["unmapped"]
    # change detection: second run with a renamed tab
    monkeypatch.setattr(FT, "_fetch_xlsx_names",
                        lambda bid: ["RECOGNIZED", "ACTUAL2"])
    tm2 = FT.enumerate_tabs(force=True)
    kinds = {(c["tab"], c["kind"]) for c in tm2["changes"]}
    assert ("ACTUAL2", "new") in kinds
    assert ("ACTUAL", "removed/renamed") in kinds


# ── EXTENSION declaration kind (#150, the one flow) ─────────────────────────

_ROSTER = [{"name": "Bluebells Takeaway", "current_mrr": 2550,
            "status": "Active", "contract_end": "2026-09-16"}]


def test_extension_declaration_preview(monkeypatch):
    monkeypatch.setattr(co, "_roster", lambda: [dict(c) for c in _ROSTER])
    prev, err = co.preview_declaration("Bluebells Takeaway", "extension",
                                       term_months=3)
    assert err is None
    p = prev["payload"]
    assert p["change_type"] == "extension"
    assert p["effective_date"] == "2026-12-16"     # end + 3 months
    assert p["new_mrr"] is None                    # unchanged unless entered
    assert "EXTEND" in prev["preview"] and "+3mo" in prev["preview"]
    _, err2 = co.preview_declaration("Bluebells Takeaway", "extension")
    assert "number of months" in err2 or "1–24" in err2


def test_extension_converges_like_renewal():
    import renewal_loop as rl
    ov = {"change_type": "extension", "client_name": "Bluebells Takeaway",
          "effective_date": "2026-12-16", "old_end": "2026-09-16",
          "new_mrr": None, "term_months": 3}
    ok, _ = rl._sheet_reflects(ov, {"end": "12-16-2026", "status": "Active",
                                    "monthly_recognized": 2550})
    assert ok
    txt = rl.piolo_edit_text(ov)
    assert "EXTENDED" in txt and "2026-12-16" in txt
