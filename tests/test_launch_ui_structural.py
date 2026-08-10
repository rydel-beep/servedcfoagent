"""
tests/test_launch_ui_structural.py — #133 structural asserts on the UI layer.

The client is render-only (I16), so these are grep-level pins on the shipped
JS/HTML: sourcing honesty (no Meta-sourced column renders unlabelled), the
hover card reads the ONE engine lineage field, the date control declares its
clock, and every drill fetch inherits the box + clock via the one query
builder.
"""
from __future__ import annotations

import os
import re

_REPO = os.path.join(os.path.dirname(__file__), "..")
_JS = open(os.path.join(_REPO, "dashboard", "static", "js", "adsapp.js")).read()
_HTML = open(os.path.join(_REPO, "dashboard", "templates", "ads.html")).read()
_CSS = open(os.path.join(_REPO, "dashboard", "static", "css", "adsapp.css")).read()


def test_meta_and_hybrid_columns_are_labelled_not_plain():
    """§2.4: no range view renders a Meta-sourced metric as an unlabelled plain
    number — every money/hybrid column key is covered by a source chip map and
    the header render applies srcChip to every column."""
    assert "SRC_META" in _JS and "SRC_HYBRID" in _JS
    assert "adx-src-meta" in _JS and "adx-src-hybrid" in _JS
    assert "+ srcChip(c.k) +" in _JS          # applied in the thead render
    # every spend-derived column in the grid is in a source map
    for col in ("spend", "cost_per_lead", "cost_per_qualified", "cost_per_set",
                "cost_per_close", "cost_per_close_loaded", "ltgp_cac"):
        assert re.search(r"SRC_(META|HYBRID) = \{[^}]*\b" + col + r": 1", _JS), \
            f"{col} is not source-labelled"
    # the hybrid chip states the degradation contract
    assert "EITHER side degrades" in _JS


def test_hover_card_reads_engine_lineage_only():
    """The hover card is fed from the board payload's row.lineage — zero fetch
    (the <150ms budget is structural) and no client-side launch computation."""
    assert "function lineageCard" in _JS
    assert "r.lineage" in _JS
    # the card never invents: degraded and channel rows have explicit copy
    assert "DEGRADED: " in _JS
    assert "no launch date exists" in _JS
    # created_time renders as SECONDARY with the not-first-delivery label
    assert "not first delivery" in _JS
    # no fetch inside the hover path (the card is memory-fed) — the segment ends
    # where the hover helpers do (the discussion block after it fetches by design)
    hover_src = _JS.split("function lineageCard")[1].split("var hoverTimer")[0]
    assert "fetch(" not in hover_src


def test_hover_dom_exists_and_is_fixed_position():
    assert 'id="adx-hover"' in _HTML
    assert "position: fixed" in _CSS.split(".adx-hover {")[1].split("}")[0]


def test_date_control_declares_its_clock():
    """#134: ONE control, in the Ads card header — Meta-familiar presets +
    Maximum + custom; the clock toggle beside it; presets default to activity,
    the ruled standard windows (30/60/90/Maximum) to cohort; URL-stated."""
    assert 'id="adx-range-preset"' in _HTML
    assert 'id="adx-range-custom"' in _HTML
    for preset in ("today", "yesterday", "7d", "14d", "30d", "60d", "90d",
                   "thismonth", "lastmonth", "max", "custom"):
        assert f'value="{preset}"' in _HTML, preset
    assert "state.basis = 'activity'" in _JS          # the box default
    assert "state.basis = 'cohort'" in _JS            # the ruled standard-window default
    assert "clockChosen" in _JS                       # explicit picks always win
    assert "'?range=' + state.range" in _JS           # URL-stated
    assert "'&clock=' + state.basis" in _JS
    # Sydney days, not browser-local days
    assert "Australia/Sydney" in _JS
    # the resolved state is ALWAYS rendered: "{Clock} · {label} · {start} → {end}"
    assert "function headerLine" in _JS
    assert "headerLine()" in _JS


def test_the_unbind_one_table_one_control():
    """#134 THE UNBIND: the page-top window/range controls are GONE — the ONE
    date control lives inside the table card header; nothing else governs the
    ads table. The main dashboard never touched /ads (cross-page assert)."""
    head = _HTML.split('<main class="adx-main">')[0]
    assert 'adx-win"' not in head                    # the 30/60/90/All buttons are gone
    assert 'id="adx-range"' not in head              # no picker in the page top either
    card = _HTML.split('<div class="adx-table-head">')[1].split("</section>")[0]
    assert 'id="adx-range-preset"' in card           # the control lives IN the card
    assert 'id="adx-bases"' in card                  # the clock toggle beside it
    assert _HTML.count('id="adx-range-preset"') == 1  # exactly one control, ever
    # no leftover top-bar wiring in the JS
    assert "'.adx-win'" not in _JS and '".adx-win"' not in _JS
    # the main dashboard has no binding to the ads table at all
    dj = open(os.path.join(_REPO, "dashboard", "static", "js", "dashboard.js")).read()
    assert "/ads/api" not in dj


def test_every_drill_fetch_inherits_box_and_clock():
    """Drills inherit the exact box + clock: every engine fetch goes through the
    ONE windowQS() builder — no fetch hand-builds days/basis anymore."""
    assert _JS.count("windowQS()") >= 5               # board + roster + dossier + anomaly + person
    assert "'/ads/api/board?' + windowQS()" in _JS
    assert "'/ads/api/dossier?' + windowQS()" in _JS
    # no residual hand-built window query on engine endpoints
    assert "api/roster?days=" not in _JS
    assert "api/dossier?days=" not in _JS
    assert "api/board?days=" not in _JS


def test_dossier_distinguishes_three_dates_and_never_fakes_the_curve():
    assert "function lineageSection" in _JS
    assert "first delivery" in _JS
    assert "birthday" in _JS                          # created = the object's birthday
    assert "NOT this ad" in _JS                       # ad-set schedule disclaimed
    assert "never interpolated" in _JS                # the timeline honesty rule
    # a range before launch renders the honest empty note from the server
    assert "lineage_window_note" in _JS


def test_launch_sorts_read_the_engine_field():
    assert 'value="launch.desc"' in _HTML
    assert 'value="active_days.desc"' in _HTML
    assert "a.lineage || {}" in _JS                   # sort key IS the engine field


def test_cohort_maturity_note_present():
    assert "cohortIsYoung" in _JS
    assert "still maturing" in _JS
