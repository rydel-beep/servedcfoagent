"""HOW WE'RE TRAVELLING — the verification battery.

I17 (count == roster) · the three-way lead split · no linear line on a
lagged stage · no red on a small sample · pitched evidenced or absent ·
cash from Stripe only · projections and gaps reproduce by hand · the
narrative's numbers match the rendered ones · read-only.
"""

import datetime as dt
import os
import re

import pytest

import kv_store
import travelling as TV

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ── windows ─────────────────────────────────────────────────────────────────

def test_windows_and_progress():
    w = TV.resolve_window("mtd")
    assert w["days_elapsed"] <= w["days_total"]
    assert w["progress"].startswith("Day ")
    assert 0 < w["elapsed_share"] <= 1
    d21 = TV.resolve_window("d21")
    assert d21["days_total"] == 21 and (d21["end"] - d21["start"]).days == 20
    cust = TV.resolve_window("custom", "2026-08-01", "2026-08-31")
    assert cust["days_total"] == 31 and cust["label"].endswith("2026-08-31")


# ── the lead split ──────────────────────────────────────────────────────────

def test_three_way_split_sums_and_unknown_is_its_own_bucket():
    leads = [
        {"revenue_raw": "$50k - $100k", "finalised": True},      # qualified
        {"revenue_raw": "Under $20k", "finalised": True},        # below floor
        {"setter_outcome": "dq", "finalised": False,
         "dq_reason": "Wrong number", "revenue_raw": "$20k - $50k"},
        {},                                                       # NO context
        {},
    ]
    out = TV._qualify(leads)
    assert len(out["qualified"]) + len(out["unqualified"]) + len(out["unknown"]) == len(leads)
    assert len(out["unknown"]) == 2
    # the two context-less rows must NOT be in unqualified
    assert all(l for l in out["unqualified"])
    assert out["reasons"]["disqualified"] == 1
    assert out["reasons"]["revenue below floor"] == 1


def test_qualify_never_counts_unknown_as_unqualified():
    src = _read("travelling.py")
    assert "never counted as unqualified" in src
    out = TV._qualify([{}] * 7)
    assert len(out["unknown"]) == 7 and not out["unqualified"]


# ── status words ────────────────────────────────────────────────────────────

def test_flow_status_band_and_words():
    assert TV._flow_status(100, 100, "leads")["word"] == "on track"
    assert TV._flow_status(105, 100, "leads")["word"] == "on track"    # inside ±10%
    s = TV._flow_status(80, 100, "leads")
    assert s["word"] == "20 leads behind" and s["tone"] == "behind"
    s2 = TV._flow_status(7000, 5000, "$")
    assert "$2,000 ahead" == s2["word"] and s2["tone"] == "ahead"
    assert TV._flow_status(10, None, "leads")["word"] == "no comparison"


def test_small_sample_never_reads_red():
    """3 of 4 shows against a 90% plan is a miss on paper — but the sample is
    tiny, so it must read 'too early to tell', never behind."""
    s = TV._rate_status(3, 4, 0.9)
    assert s["word"] == "too early to tell" and s["tone"] == "neutral"
    # a real sample with a real miss does read behind
    s2 = TV._rate_status(60, 100, 0.9)
    assert s2["word"] == "behind" and "60% against 90% planned" in s2["detail"]
    # nothing at the stage yet
    assert TV._rate_status(0, 0, 0.9)["word"] == "too early to tell"


def test_no_linear_to_date_line_on_lagged_stages():
    """Lagged stages (showed, closed, cash) must not carry a plan-to-date
    marker — only flow stages do."""
    src = _read("travelling.py")
    assert 'if s["kind"] == "flow":' in src          # bars/markers gated on flow
    tmpl = _read("dashboard", "templates", "travelling.html")
    assert "{% if s.bar %}" in tmpl                   # no bar → no marker


# ── projections + gaps reproduce by hand ────────────────────────────────────

@pytest.fixture()
def fixture_build(monkeypatch):
    """A whole month on fixture data — every figure hand-checkable."""
    day = 10
    monkeypatch.setattr(TV, "resolve_window", lambda *a, **k: {
        "key": "mtd", "start": dt.date(2026, 9, 1), "end": dt.date(2026, 9, day),
        "label": "Month to date", "days_total": 30, "days_elapsed": day,
        "days_remaining": 20, "elapsed_share": day / 30,
        "progress": f"Day {day} of 30"})
    leads = [{"name": f"L{i}", "revenue_raw": "$50k - $100k", "finalised": True,
              "input_date": dt.date(2026, 9, 2), "contact_id": f"c{i}"}
             for i in range(100)]
    monkeypatch.setattr(TV, "_lead_rows", lambda w0, w1: (leads, leads))
    booked = [{"contact_id": f"c{i}", "status": "confirmed",
               "booked_at": "2026-09-03", "when": "2026-09-05T10:00:00",
               "when_text": "September 5, 2026, 10:00 AM"} for i in range(10)]
    upcoming = [{"contact_id": f"c{50+i}", "status": "confirmed",
                 "booked_at": "2026-09-09", "when": "2026-09-25T10:00:00",
                 "when_text": "September 25, 2026, 10:00 AM"} for i in range(4)]
    monkeypatch.setattr(TV, "_appointments", lambda w0, w1: {
        "booked": booked + upcoming, "cancelled": [], "due": booked,
        "upcoming": upcoming})
    monkeypatch.setattr(TV, "_shows", lambda la, due, w0, w1: {
        "verified": booked[:8], "unverified": [], "by_close": [],
        "noshow": booked[8:], "all": booked[:8]})
    monkeypatch.setattr(TV, "_pitched", lambda ids, w0, w1: {
        "rows": [], "count": 0, "lower_bound": True, "note": "n", "package_line": "p"})
    monkeypatch.setattr(TV, "_closes", lambda w0, w1: {
        "rows": [{"person": "A", "contract": 18300.0, "cash": 6000.0,
                  "close_date": "2026-09-06"},
                 {"person": "B", "contract": 18300.0, "cash": 6000.0,
                  "close_date": "2026-09-08"}],
        "count": 2, "contract": 36600.0, "contract_signed": 36600.0,
        "contract_derived": 0.0, "gap_open": False})
    monkeypatch.setattr(TV, "_cash_from_closes", lambda rows, w0, w1: {
        "cohort": 12000.0, "all_receipts": 40000.0, "source": "Stripe",
        "context_note": "x"})
    monkeypatch.setattr(TV, "_setter_activity", lambda leads: {
        "call_records": 5, "conversations": 2, "coverage_pct": 10.0,
        "covered": 10, "of": 100, "note": "n"})
    monkeypatch.setattr(TV, "_cross_checks", lambda *a: [])
    # pin the in-month lag share so this fixture is deterministic whatever
    # another suite left in the shared cache
    import compass_engine as CE
    monkeypatch.setattr(CE, "measured_defaults",
                        lambda force=False: {"items": {
                            "lag_curve": {"value": [0.7, 0.2, 0.1]}}})
    import meta_spend
    monkeypatch.setattr(meta_spend, "spend_in_range",
                        lambda a, b: {"spend": 5000.0} if a != b else {"spend": 500.0})
    monkeypatch.setattr(TV, "_comparator", lambda c, s, w: {
        "key": "usual", "label": "your usual rates", "from_usual": [],
        "plan_word": "usually",
        "usual": {}, "cpl": 50.0, "set_rate": 0.10, "show_rate": 0.90,
        "close_rate": 0.30, "spend_month": 15000.0, "leads_month": 300.0,
        "cash_per_client": 6000.0, "mrr_per_client": 3050.0})
    return TV.build(window="mtd", compare="usual")


def test_projections_reproduce_by_hand(fixture_build):
    d = fixture_build
    by = {s["id"]: s for s in d["stages"]}
    # spend: 5,000 actual + 500/day × 20 remaining = 15,000
    assert abs(by["spend"]["projection"] - 15000.0) < 1
    # leads: 100 + (500/50 per day × 20 days) = 100 + 200 = 300
    assert abs(by["leads"]["projection"] - 300.0) < 1
    # booked: 14 actual + 200 expected leads × booking rate (14/100) = 42
    assert abs(by["booked"]["projection"] - (14 + 200 * 0.14)) < 0.5
    # showed: 8 actual + 4 upcoming × show rate (8/10) = 11.2
    assert abs(by["showed"]["projection"] - 11.2) < 0.1
    # plan-to-date on flow stages = plan × elapsed share (10/30)
    assert abs(by["spend"]["plan_to_date"] - 5000.0) < 1
    assert abs(by["leads"]["plan_to_date"] - 100.0) < 1


def test_closed_projection_is_pipeline_aware_not_linear(fixture_build):
    d = fixture_build
    by = {s["id"]: s for s in d["stages"]}
    closed = by["closed"]
    assert closed.get("plan_to_date") is None       # never a to-date line
    # 2 actual + 6 awaiting × 0.25 + 4 upcoming × 0.8 × 0.25 + new-lead chain
    close_rate = 2 / 8
    expected = (2 + 6 * close_rate + 4 * 0.8 * close_rate
                + 200 * 0.14 * 0.8 * close_rate * 0.7)
    assert abs(closed["projection"] - expected) < 0.75


def test_gap_finder_reproduces_by_hand(fixture_build):
    d = fixture_build
    g = {x["stage"]: x for x in d["gaps"]}
    # show rate: actual 8/10 = 0.80 vs plan 0.90 → (0.8-0.9) × 10 due × 0.30 close
    sr = g["show rate"]
    assert abs(sr["clients"] - (-0.1 * 10 * 0.30)) < 0.01
    assert abs(sr["cash"] - sr["clients"] * 6000.0) < 1
    # ranked most-negative first
    assert d["gaps"][0]["clients"] <= d["gaps"][-1]["clients"]


def test_i17_count_equals_roster_on_every_stage():
    """Every rendered count is the length of the people behind it."""
    d = TV.build(window="mtd", compare="usual")
    for s in d["stages"]:
        if s["id"] in ("spend", "contract", "cash"):
            continue                       # money stages roster their closes
        assert s["actual"] == len(s["roster"]), f"{s['id']}: {s['actual']} vs {len(s['roster'])}"


def test_qualified_plus_unqualified_plus_unknown_equals_leads():
    d = TV.build(window="mtd", compare="usual")
    by = {s["id"]: s for s in d["stages"]}
    q = by["qualified"]
    extra = q.get("extra_rosters") or {}
    total = (len(q["roster"]) + len(extra.get("unqualified") or [])
             + len(extra.get("unknown") or []))
    assert total == by["leads"]["actual"]


# ── the laws ────────────────────────────────────────────────────────────────

def test_pitched_is_evidenced_or_absent_never_inferred():
    src = _read("travelling.py")
    assert "Never inferred from 'showed'" in src
    assert "lower_bound" in src
    out = TV._pitched(set(), dt.date(2026, 9, 1), dt.date(2026, 9, 21))
    assert out["count"] == 0
    assert out["package_line"] and "never writes" in out["package_line"]
    # the rendered text for an empty stage
    d = TV.build(window="mtd", compare="usual")
    p = next(s for s in d["stages"] if s["id"] == "pitched")
    assert p["actual_text"].startswith("at least") or p["actual_text"] == "not recorded yet"


def test_cash_only_from_stripe():
    src = _read("travelling.py")
    i = src.index("def _cash_from_closes")
    block = src[i:i + 900]
    assert "_receipts_in_window" in block
    assert "tracker" not in block.lower() or "never" in block.lower()
    d = TV.build(window="mtd", compare="usual")
    cash = next(s for s in d["stages"] if s["id"] == "cash")
    assert "Stripe" in (cash["math"] or "")


def test_read_only_no_writes_anywhere():
    src = _read("travelling.py")
    assert "GHL_EMAIL_TOKEN" not in src
    assert not re.search(r"requests\.(post|put|patch|delete)\(|batchUpdate|"
                         r"values:append|values:update", src)
    # the only kv key it writes is its own journal
    writes = re.findall(r"kv_store\.put\(([^,)]+)", src)
    allowed = ("K_SAVED", "travelling:", "feed:extra:picklist_drift")
    assert all(any(a in w for a in allowed) for w in writes), writes


def test_narrative_numbers_match_the_rendered_values():
    """Every number in EDITH's paragraph must be a number the page shows."""
    d = TV.build(window="mtd", compare="usual")
    text = " ".join(d["read"]["sentences"])
    rendered = set()
    for s in d["stages"]:
        for key in ("actual_text", "projection_text", "sub", "plan_text",
                    "range_text", "rate_note"):
            for n in re.findall(r"[\d,]+(?:\.\d+)?", str(s.get(key) or "")):
                rendered.add(n.replace(",", ""))
        if s.get("actual") is not None:
            rendered.add(f"{s['actual']:.0f}")
            rendered.add(f"{round(s['actual'])}")
        for stat in (s.get("status") or {}, s.get("outcome_status") or {}):
            for key in ("word", "detail"):
                for n in re.findall(r"[\d,]+(?:\.\d+)?", str(stat.get(key) or "")):
                    rendered.add(n.replace(",", ""))
    for g in d["gaps"]:
        rendered.add(f"{abs(g['clients']):.0f}")
        rendered.add(f"{abs(g['cash']):,.0f}".replace(",", ""))
        rendered.add(f"{g['actual_rate']*100:.0f}")
        rendered.add(f"{g['plan_rate']*100:.0f}")
    for v in d["read"]["numbers"].values():
        rendered.add(f"{v:.0f}")
    missing = []
    for n in re.findall(r"\$?([\d,]+(?:\.\d+)?)", text):
        clean = n.replace(",", "")
        if clean in ("0",) or len(clean) < 2:
            continue
        if clean not in rendered:
            missing.append(clean)
    assert not missing, f"narrative numbers not on the page: {missing}"


def test_remodel_carries_samples_and_label():
    out = TV.remodel_inputs(window="mtd")
    assert out["label"] == "if this window's rates hold"
    assert set(out["confidence"]) >= {"set_rate", "show_rate", "close_rate"}
    for word in out["confidence"].values():
        assert word in ("solid", "fair", "rough")


def test_save_check_journals_only_its_own_store():
    kv_store.put(TV.K_SAVED, [])
    import client_overrides
    before = len(client_overrides.active_overrides() or [])
    out = TV.save_check("tester", window="mtd", compare="usual")
    assert out["ok"]
    log = kv_store.get(TV.K_SAVED)
    assert len(log) == 1 and log[0]["by"] == "tester"
    assert len(client_overrides.active_overrides() or []) == before
    assert TV.history(5)["checks"][0]["by"] == "tester"


def test_edith_drill():
    reply, handled = TV.handle_travelling_command("how are we travelling this month")
    assert handled and reply
    assert TV.handle_travelling_command("what's the weather")[1] is False


# ── the page ────────────────────────────────────────────────────────────────

def test_page_server_renders_the_whole_comparison():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-tv")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    r = c.get("/dashboard/scale/travelling?window=mtd&compare=usual")
    assert r.status_code == 200
    h = r.data.decode()
    assert len(re.findall(r'class="tv-stage ', h)) == 10     # every stage rendered
    assert 'data-def="tv_verdict"' in h and 'data-def="tv_read"' in h
    assert "tv-bar-actual" in h                              # the funnel is server-drawn
    # the button lives on the compass and the levers table is GONE from it
    scale = c.get("/dashboard/scale").data.decode()
    assert 'id="btn-travelling"' in scale
    assert 'id="ns-levers"' not in scale                     # one plan-vs-actual surface
    # anon refused
    c2 = appmod.app.test_client()
    assert c2.get("/dashboard/scale/travelling").status_code in (302, 401, 403)
    assert c2.get("/dashboard/api/travelling").status_code in (302, 401, 403)


def test_copy_follows_the_design_direction():
    tmpl = _read("dashboard", "templates", "travelling.html")
    # buttons say what they do, no appended arrows, no all-caps labels
    assert "Re-model from actuals" in tmpl and "Save this check" in tmpl
    assert "→</button>" not in tmpl
    for shout in ("ACTUAL", "PLAN TO DATE", "MONTH END", "STATUS"):
        assert f">{shout}<" not in tmpl
    # one motion moment, and it respects the setting
    css = _read("dashboard", "static", "css", "travelling.css")
    assert "prefers-reduced-motion" in css and "animation: none" in css


def test_registry_covers_every_new_element():
    from dashboard import definitions as D
    missing, total = D.coverage_check()
    assert not missing, missing[:10]
    for eid in ("travelling", "tv_window", "tv_compare", "tv_verdict", "tv_gap",
                "tv_read", "tv_setter", "tv_checks", "tv_remodel", "tv_save",
                "tv_history", "tv_northstar", "btn_travelling",
                "tv_stage_pitched", "tv_stage_qualified"):
        assert D.entry(eid), eid
    hits = [(i, f) for i, e in D.load()["entries"].items()
            for f in ("meaning", "computed", "changing")
            if D.jargon_hits(e.get(f) or "")]
    assert not hits, hits[:5]


def test_button_carries_the_modelled_scenario():
    """The button must lay the month against WHAT'S ON SCREEN — the gate
    caught it opening on 'your usual' because nothing was encoded."""
    js = _read("dashboard", "static", "js", "scale.js")
    assert "updateTravellingLink" in js
    assert "compare=scenario" in js and "&s=" in js
    # the route decodes base64url with or without padding
    import base64, json as _json
    payload = {"spend_path": {"shape": "flat", "start": 12345.0}, "cpl0": 77.0,
               "set_rate": 0.2, "show_rate": 0.8, "close_rate": 0.3}
    raw = base64.urlsafe_b64encode(_json.dumps(payload).encode()).decode().rstrip("=")
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-tv")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    r = c.get("/dashboard/scale/travelling?compare=scenario&window=mtd&s=" + raw)
    assert r.status_code == 200
    h = r.data.decode()
    assert "the scenario on screen" in h


# ══ PART A — the six defects, each pinned ═══════════════════════════════════

def test_a1_show_rate_primary_is_confirmed_not_status_only(fixture_build, monkeypatch):
    """A1: 'nobody marked a no-show' is not attendance. The headline rate is
    the confirmed one; the status-only consults set the upper end."""
    d = fixture_build
    sb = d["show_bases"]
    assert sb["confirmed"] <= sb["upper"]
    showed = next(s for s in d["stages"] if s["id"] == "showed")
    assert showed["rate"] == sb["rate_confirmed"]
    assert showed["rate_upper"] == sb["rate_upper"]
    assert "NOT counted as attendance" in showed["math"]


def test_a1_status_only_shows_can_never_read_ahead():
    """A run where every consult is status-only must not produce 'ahead' —
    the confirmed rate is 0."""
    s = TV._rate_status(0, 10, 0.9, "gain", "planned")
    assert s["tone"] in ("behind", "neutral") and s["tone"] != "ahead"


def test_a1_gap_finder_runs_both_bases_and_says_when_it_flips():
    cmp_ = {"set_rate": 0.15, "show_rate": 0.90, "close_rate": 0.28,
            "plan_word": "planned"}
    counts = {"leads": 174, "due": 22, "showed": 14, "showed_status": 22}
    verified = {"book": 0.20, "show": 14 / 22, "close": 3 / 14}
    status = {"book": 0.20, "show": 22 / 22, "close": 3 / 22}
    out = TV._gap_finder({}, cmp_, counts, verified, status, 5500.0, 8)
    assert out["top_verified"] and out["top_status"]
    assert out["basis"] == "confirmed attendance"
    # on these numbers the conclusion flips — and it must say so
    if out["top_verified"] != out["top_status"]:
        assert "8 consults nobody marked either way" in out["flip"]
        assert out["top_status"] in out["flip"] and out["top_verified"] in out["flip"]
    else:
        assert "holds either way" in out["flip"]


def test_a2_outcome_and_rate_are_separate_and_never_contradict(fixture_build):
    """A2: a stage may be on course to beat the client plan while its rate is
    under plan. Both render — in different fields — and no single sentence
    carries contradictory status words."""
    d = fixture_build
    closed = next(s for s in d["stages"] if s["id"] == "closed")
    assert "outcome_status" in closed and "status" in closed
    contradictory = [("ahead", "behind"), ("on course to beat plan", "short of plan")]
    for sentence in d["read"]["sentences"] + [d["verdict"]]:
        low = sentence.lower()
        for a, b in contradictory:
            assert not (a in low and b in low), sentence


def test_a3_cost_metrics_never_read_ahead(fixture_build):
    """A3: spending more than planned is 'over plan', never 'ahead'."""
    over = TV._flow_status(7000, 5000, "$", "cost")
    assert over["word"] == "$2,000 over plan" and over["tone"] == "over"
    under = TV._flow_status(4000, 5000, "$", "cost")
    assert under["word"] == "$1,000 under plan"
    assert TV._flow_status(5100, 5000, "$", "cost")["word"] == "on budget"
    # and no cost stage on a real build is ever labelled ahead
    d = fixture_build
    for s in d["stages"]:
        if s.get("polarity") == "cost":
            assert "ahead" not in s["status"]["word"], s["id"]


def test_a4_three_way_status_band():
    """A4: outside the interval → ahead/behind; inside and tight → on track;
    inside and wide → too early to tell."""
    assert TV._rate_status(60, 100, 0.90)["word"] == "behind"      # outside
    big = TV._rate_status(88, 173, 0.49)                            # inside, tight
    assert big["word"] == "on track"
    small = TV._rate_status(3, 5, 0.49)                             # inside, wide
    assert small["word"] == "too early to tell"


def test_a5_unmodelled_stages_say_usually_not_planned(fixture_build):
    d = fixture_build
    q = next(s for s in d["stages"] if s["id"] == "qualified")
    assert q["plan_word"] == "usually"
    assert "planned" not in q["actual_text"]
    assert "usually" in q["actual_text"] or q["rate"] is None


def test_a5_comparator_names_itself_honestly():
    """A modelled comparison says 'planned'; a measured one says 'usually'."""
    for key, word in (("scenario", "planned"), ("usual", "usually"),
                      ("last_month", "last month")):
        c = TV._comparator(key, {"cpl0": 90.0}, TV.resolve_window("mtd"))
        assert c["plan_word"] == word, key


def test_a6_identities_hold_and_denominators_are_named(fixture_build):
    d = fixture_build
    assert d["identities"] and all(i["holds"] for i in d["identities"]), d["identities"]
    names = [i["name"] for i in d["identities"]]
    assert any("booked = due + upcoming" in n for n in names)
    assert any("qualified + unqualified + unknown" in n for n in names)
    showed = next(s for s in d["stages"] if s["id"] == "showed")
    assert "of" in showed["sub"] and "consults" in showed["sub"]


def test_a6_every_coverage_figure_names_its_denominator():
    """~86% of WHAT? Every coverage number says what it is a share of."""
    out = TV._setter_activity([{"contact_id": "x"}, {"contact_id": "y"}])
    assert f"of {out['of']} leads" in out["note"]
    assert out["coverage_pct"] is not None and out["of"] == 2


# ══ PART B — one qualification rule + the drift guard ══════════════════════

def test_b1_exactly_one_qualification_call_site():
    """#157: the rule lives in attribution_engine.qualify_lead and NOWHERE
    else. Two rules meant two 'qualified' numbers from the same rows."""
    import glob
    offenders = []
    for path in glob.glob(os.path.join(ROOT, "*.py")) + \
            glob.glob(os.path.join(ROOT, "dashboard", "*.py")):
        name = os.path.basename(path)
        if name in ("attribution_engine.py", "revenue_bands.py"):
            continue
        src = open(path, encoding="utf-8").read()
        if "meets_floor(" in src:
            offenders.append(name)
    assert not offenders, f"a second qualification path exists in {offenders}"
    ae = _read("attribution_engine.py")
    assert ae.count("def qualify_lead(") == 1
    assert "lead[\"qualified\"] = _q[\"qualified\"]" in ae


def test_b1_one_rule_gives_one_answer():
    """The same row must qualify identically through either caller."""
    import attribution_engine as AE
    lead = {"revenue_raw": "$50k - $100k", "finalised": True,
            "setter_outcome": "set"}
    direct = AE.qualify_lead(lead)
    via_view = TV._qualify([lead])
    assert direct["state"] == "qualified"
    assert len(via_view["qualified"]) == 1


def test_b1_unrecognised_value_is_unknown_not_below_floor():
    """THE BUG: an unreadable picklist value used to read as 'below floor'."""
    import attribution_engine as AE
    res = AE.qualify_lead({"revenue_raw": "$500k-$1m squillion",
                           "finalised": True, "setter_outcome": "set"})
    assert res["state"] == "unknown"
    assert res["reason"] == "revenue value not recognised"
    out = TV._qualify([{"revenue_raw": "$500k-$1m squillion", "finalised": True,
                        "setter_outcome": "set"}])
    assert len(out["unknown"]) == 1 and not out["unqualified"]


def test_b3_picklist_drift_fires_loudly():
    """A new spelling is a schema change, named — never a silent unknown."""
    kv_store.put("feed:extra:picklist_drift", [])
    TV._qualify([{"revenue_raw": "$77k to $99k", "finalised": True,
                  "setter_outcome": "set"}] * 3)
    items = kv_store.get("feed:extra:picklist_drift") or []
    assert items, "no drift finding was raised"
    assert "picklist changed" in items[0]["title"]
    assert "$77k to $99k" in items[0]["action"]
    assert "feed:extra:picklist_drift" in _read("action_feed.py")


def test_b_current_picklist_spellings_all_parse():
    """Every spelling seen in the live tracker must parse."""
    import revenue_bands as RB
    for v in ("$50k - $100k", "$20k - $50k", "Under $20k", "$100k - $200k",
              "$200k +", "$50k-100k", "$20k-50k"):
        assert RB.parse_band(v)["state"] == "parsed", v
