"""
tests/test_salary_view.py
-------------------------
Deterministic salary lookup: verbatim AUD+PHP from the SALARY tab; pure lookups answered,
affordability/change questions NOT hijacked (they get salary_context injected instead).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import salary_view as sv

_HDR = ["LAST NAME","FIRST NAME","ROLE","DEPARTMENT","STATUS","","","","","VALUES AS OF:","06/19/2026"]
_ROWS = [_HDR,
    ["De Leon","Gabie","SMM Full time","SMM","Full Time","$831.00","₱35,000.00"],
    ["Dimayuga","Chloie","SMM Full time","SMM","Full Time","$689.00","₱29,000.00"],
    ["Delmendo","Miguel","COO","C-LEVEL","Full Time","$1,185.00","₱50,000.00"],
]

def _mock(monkeypatch):
    import sheet_mirror
    monkeypatch.setattr(sheet_mirror, "read_by_name", lambda n: _ROWS if n == "SALARY" else None)


def test_read_salaries_verbatim(monkeypatch):
    _mock(monkeypatch)
    d = sv.read_salaries()
    assert d["headcount"] == 3 and d["total_aud"] == 2705.0 and d["as_of"] == "06/19/2026"
    gabie = next(p for p in d["people"] if p["first"] == "Gabie")
    assert gabie["aud"] == 831.0 and gabie["php"] == 35000.0


def test_pure_lookup(monkeypatch):
    _mock(monkeypatch)
    reply, handled = sv.handle_salary_command("what do we pay Gabie?")
    assert handled and "Gabie De Leon" in reply and "$831/mo" in reply and "₱35,000" in reply
    assert "$2,705/mo" in sv.handle_salary_command("total payroll")[0]


def test_affordability_not_hijacked(monkeypatch):
    _mock(monkeypatch)
    # a salary-CHANGE / affordability question must NOT be answered with a bare figure
    assert sv.handle_salary_command("can we afford to bump SMM salary to 35k, push Gabie to 40k")[1] is False
    assert sv.handle_salary_command("should we raise Gabie to 40k")[1] is False


def test_salary_context_grounds_model(monkeypatch):
    _mock(monkeypatch)
    ctx = sv.salary_context("can we afford to bump SMM to 35k, push Gabie to 40k")
    assert "VERIFIED CURRENT SALARIES" in ctx and "Gabie De Leon" in ctx and "₱35,000" in ctx
    assert sv.salary_context("how's the weather") == ""   # not salary-related → no injection
