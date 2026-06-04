"""
tests/test_team_roster.py
-------------------------
Tests for the SALARY sheet team roster pull.
"""
from unittest.mock import patch

from team_roster import pull_team_roster, _DEPT_OVERRIDE, DEFAULT_FX_RATE


SAMPLE_ROWS = [
    ["Last", "First", "Role", "Department", "Status", "AUD", "PHP"],
    ["Borebor", "Tristan", "Developer", "C-LEVEL", "Active", "2000", "0"],
    ["Dulay", "Ryan Piolo", "VA", "C-LEVEL", "Active", "0", "50000"],
    ["Garces", "KC", "Media Buyer", "C-LEVEL", "Active", "1500", "0"],
    ["Smith", "John", "Closer", "SALES", "Active", "3000", "0"],
    ["Doe", "Jane", "Designer", "MEDIA", "Active", "0", "80000"],
]


@patch("team_roster._fetch_tab")
def test_basic_roster_pull(mock_fetch):
    mock_fetch.return_value = SAMPLE_ROWS
    result = pull_team_roster()
    assert result["roster"] is not None
    assert len(result["roster"]) == 5
    assert result["degraded"] == []


@patch("team_roster._fetch_tab")
def test_department_overrides_applied(mock_fetch):
    mock_fetch.return_value = SAMPLE_ROWS
    result = pull_team_roster()
    roster = result["roster"]
    tristan = [p for p in roster if p["last_name"] == "Borebor"][0]
    piolo = [p for p in roster if p["last_name"] == "Dulay"][0]
    kc = [p for p in roster if p["last_name"] == "Garces"][0]
    assert tristan["department"] == "TECH"
    assert tristan["sheet_department"] == "C-LEVEL"
    assert piolo["department"] == "ADMIN"
    assert kc["department"] == "MEDIA"


@patch("team_roster._fetch_tab")
def test_non_overridden_keeps_sheet_dept(mock_fetch):
    mock_fetch.return_value = SAMPLE_ROWS
    result = pull_team_roster()
    roster = result["roster"]
    john = [p for p in roster if p["last_name"] == "Smith"][0]
    assert john["department"] == "SALES"


@patch("team_roster._fetch_tab")
def test_by_department_grouping(mock_fetch):
    mock_fetch.return_value = SAMPLE_ROWS
    result = pull_team_roster()
    by_dept = result["by_department"]
    assert "TECH" in by_dept
    assert "ADMIN" in by_dept
    assert "MEDIA" in by_dept
    assert "SALES" in by_dept
    assert by_dept["TECH"]["headcount"] == 1
    assert by_dept["MEDIA"]["headcount"] == 2  # KC + Jane


@patch("team_roster._fetch_tab")
def test_totals_computed(mock_fetch):
    mock_fetch.return_value = SAMPLE_ROWS
    result = pull_team_roster()
    totals = result["totals"]
    assert totals["headcount"] == 5
    assert totals["total_aud"] == 6500.0
    assert totals["total_php"] == 130000.0


@patch("team_roster._fetch_tab")
def test_empty_sheet_returns_degraded(mock_fetch):
    mock_fetch.return_value = []
    result = pull_team_roster()
    assert result["roster"] is None
    assert len(result["degraded"]) > 0


@patch("team_roster._fetch_tab")
def test_skips_total_rows(mock_fetch):
    rows = SAMPLE_ROWS + [["TOTAL", "", "", "", "", "6500", "130000"]]
    mock_fetch.return_value = rows
    result = pull_team_roster()
    assert len(result["roster"]) == 5  # TOTAL row excluded
