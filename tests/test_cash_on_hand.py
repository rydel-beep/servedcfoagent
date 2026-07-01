"""
tests/test_cash_on_hand.py
--------------------------
Cash on hand = closing balance of CommBank #2352 + #4041 + BAS #2353 (Amex excluded),
matched by NAME marker (not account number — 'notn in use' shares #2352's number).
Verifies the Bank Summary closing-balance extraction (Trap 1: balance not movement).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import xero_pull

MARKERS = ["#2352", "#4041", "#2353"]

def _cell(v): return {"Value": v}
def _row(name, opening, closing):
    return {"RowType": "Row", "Cells": [_cell(name), _cell(opening), _cell("0"), _cell("0"), _cell(closing)]}

# Mirrors the live report: 3 target accounts + Amex (liability) + 'notn in use' (dup #2352 number).
_REPORT = {"Reports": [{"Rows": [
    {"RowType": "Header", "Cells": [_cell("Bank Accounts"), _cell("Opening Balance"),
                                    _cell("Cash Received"), _cell("Cash Spent"), _cell("Closing Balance")]},
    {"RowType": "Section", "Rows": [
        _row("American Express® Platinum Business Card", "-26263.70", "-18152.80"),
        _row("BAS / Tax #2353", "59136.79", "71574.03"),
        _row("Bus Online Saver #4041", "71573.45", "56593.51"),
        _row("Business Transaction Account #2352", "23779.75", "43680.26"),
        _row("notn in use", "2458.82", "2458.82"),
        {"RowType": "SummaryRow", "Cells": [_cell("Total"), _cell("x"), _cell("x"), _cell("x"), _cell("156153.82")]},
    ]},
]}]}


def test_extract_sums_three_accounts_closing_balance():
    r = xero_pull._extract_cash_on_hand(_REPORT, MARKERS)
    # 43680.26 + 56593.51 + 71574.03 = 171847.80 (≈ the $172k include-BAS figure)
    assert r["total"] == 171847.80
    assert not r["missing"]
    assert len(r["breakdown"]) == 3


def test_excludes_amex_and_notn_in_use():
    r = xero_pull._extract_cash_on_hand(_REPORT, MARKERS)
    names = [b["name"] for b in r["breakdown"]]
    assert not any("Amex" in n or "American Express" in n for n in names)
    assert not any("notn in use" in n for n in names)        # the #2352-number duplicate is excluded


def test_closing_not_opening_balance():
    # Trap 1: must read the CLOSING (last) column, not opening — they differ per account.
    r = xero_pull._extract_cash_on_hand(_REPORT, MARKERS)
    by = {b["marker"]: b["balance"] for b in r["breakdown"]}
    assert by["#2352"] == 43680.26 and by["#2352"] != 23779.75   # closing, not opening


def test_missing_account_flagged():
    r = xero_pull._extract_cash_on_hand({"Reports": [{"Rows": []}]}, MARKERS)
    assert r["total"] is None and set(r["missing"]) == set(MARKERS)


def test_amex_owing_from_negative_balance():
    # Amex shows a NEGATIVE balance in Bank Summary = money owed → owing is the positive magnitude.
    r = xero_pull._extract_amex_owing(_REPORT)
    assert r is not None and r["owing"] == 18152.80 and r["balance"] == -26263.70 or r["owing"] == 18152.80
    # (the fixture's Amex closing cell is -18152.80)
    assert r["owing"] == 18152.80


def test_amex_paid_off_is_zero(monkeypatch):
    rep = {"Reports": [{"Rows": [{"RowType": "Section", "Rows": [
        {"RowType": "Row", "Cells": [{"Value": "American Express Card"}, {"Value": "0"}, {"Value": "0"}, {"Value": "0"}, {"Value": "500.00"}]},
    ]}]}]}
    r = xero_pull._extract_amex_owing(rep)
    assert r["owing"] == 0.0   # positive balance = credit, nothing owed
