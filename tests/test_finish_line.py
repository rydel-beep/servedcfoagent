"""THE FINISH LINE — the shell, TODAY, SALES, and the last partials.

What these tests pin:
  · TODAY MOVES its tiles; it never recomputes one
  · the show rate has ONE rule, and the pulse uses it (the 100%-vs-70% bug)
  · "cash net MTD" is anchored to the month, not to whenever the cache warmed
  · a trend means DAYS, and says so when it hasn't got enough
  · polarity: a cost metric never reads "ahead"
  · SALES is owner-only and never leaks commissions to ad_domain
  · the required-rate solve holds upstream and flags the impossible
  · every page carries the nav; templates never touch a dict's own methods
"""

import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


@pytest.fixture()
def client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-finish")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    return c


# ── the jinja trap that has now bitten three times ──────────────────────────

def test_templates_never_read_a_dicts_own_methods():
    """`nav.items`, `today.rulings.items`, `c.values` — jinja resolves these
    to dict.items / dict.values and the page 500s at render time. Three
    separate outages came from this exact collision, so it is a test."""
    import glob
    bad = []
    # The bug is a BARE attribute used as a value — `nav.items`, with no
    # parentheses. `groups.items()` is a deliberate call on a real dict and
    # is perfectly correct, so only the paren-less form is flagged.
    pat = re.compile(r"\{[{%][^}]*?\b[a-z_][a-z_0-9]*\.(items|values|keys|copy|pop|update)\s*(?!\()")
    for fp in glob.glob(os.path.join(ROOT, "dashboard", "templates", "**", "*.html"),
                        recursive=True):
        for i, line in enumerate(open(fp, encoding="utf-8"), 1):
            m = pat.search(line)
            if not m:
                continue
            bad.append(f"{os.path.basename(fp)}:{i}: {line.strip()[:90]}")
    assert not bad, "template reads a dict's own method:\n" + "\n".join(bad)


# ── THE SHELL ───────────────────────────────────────────────────────────────

def test_every_page_carries_the_nav(client):
    from dashboard.routes import _AREAS
    pages = ["/dashboard/today", "/dashboard/sales", "/dashboard/landing",
             "/dashboard/scale", "/dashboard/scale/travelling",
             "/dashboard/definitions", "/dashboard/worklog",
             "/dashboard/bookkeeping", "/dashboard/leads",
             "/dashboard/targets", "/dashboard/data-sources", "/ads/"]
    pages += [f"/dashboard/view/{a}" for a in _AREAS]
    missing = []
    for p in pages:
        r = client.get(p)
        if r.status_code != 200:
            continue
        if 's-nav-link' not in r.data.decode():
            missing.append(p)
    assert not missing, f"pages with no nav: {missing}"


def test_landing_redirects_to_today(client):
    r = client.get("/dashboard/")
    assert r.status_code == 302
    assert "/dashboard/today" in (r.headers.get("Location") or "")


def test_nav_is_fail_closed_for_ad_domain():
    from dashboard import shell
    import app as appmod
    with appmod.app.test_request_context("/ads"):
        from flask import session
        session["actor"] = {"user": "romano", "role": "ad_domain",
                            "display": "Romano"}
        nav = shell.nav_context("ads")
        keys = {i["key"] for i in nav["links"]}
        assert keys == {"ads"}, keys
        assert not any(t["href"].startswith("/dashboard/sales")
                       for t in shell.palette_targets(False, True))


def test_palette_is_server_rendered_not_fetched():
    """⌘K opens with its targets already in the page."""
    js = _read("dashboard", "static", "js", "shell.js")
    assert "s-palette-data" in js
    assert "fetch(" not in js.split("keyboard shortcuts")[0]
    html = _read("dashboard", "templates", "partials", "shell_palette.html")
    assert "palette_json" in html


# ── TODAY ───────────────────────────────────────────────────────────────────

def test_today_moves_tiles_and_never_recomputes_them():
    """Six of the eight are the SAME objects exec_top builds. A second
    engine computing cash a second way is how the estate came to hold two
    show rates."""
    src = _read("dashboard", "today.py")
    assert "exec_top.build_tiles" in src
    # TODAY must not reach for the raw money engines itself
    for forbidden in ("tile_drawers.three_nets", "finance_analysis.unit_econ_view",
                      "receivables.build_ar", "stripe_", "xero_pull"):
        assert forbidden not in src, f"TODAY recomputes {forbidden}"


def test_today_request_path_makes_no_external_call():
    src = _read("dashboard", "today.py")
    build = src[src.index("def build("):src.index("def _rulings")]
    for forbidden in ("meta_spend.", "spend_in_range", "travelling.build",
                      "_lead_rows", "requests."):
        assert forbidden not in build, f"request path calls {forbidden}"
    # …those all live in the refresh loop instead
    refresh = src[src.index("def refresh_cache"):src.index("# ── the request path")]
    assert "meta_spend" in refresh and "travelling.build" in refresh


def test_today_has_at_most_nine_tiles_and_the_named_ones(client):
    """Was eight; #165 added the net-margin tile to TODAY by name —
    profitability joined the ten-second question."""
    r = client.get("/dashboard/today")
    assert r.status_code == 200
    html = r.data.decode()
    ids = re.findall(r'id="tile-([a-z_]+)"', html)
    tiles = [i for i in ids if not i.startswith("pulse_")]
    assert len(tiles) <= 9, tiles
    for want in ("cash_on_hand", "committed_mrr", "ar_outstanding",
                 "cash_net_mtd", "net_margin", "ltv_cac", "ltgp_cac",
                 "week_flow", "ad_spend"):
        assert want in tiles, f"{want} missing from TODAY"


def test_today_is_server_rendered(client):
    """Every headline is in the HTML before a script could run."""
    html = client.get("/dashboard/today").data.decode()
    body = html.split("<main", 1)[1].split("</main>", 1)[0]
    assert "<script" not in body, "TODAY fills a value with inline script"
    assert len(re.findall(r'class="s-card-value"', body)) >= 8


def test_today_publishes_the_metric_contract(client):
    html = client.get("/dashboard/today").data.decode()
    for attr in ("data-metric=", "data-window=", "data-clock=",
                 "data-basis=", "data-value="):
        assert attr in html, attr


def test_today_carries_nothing_beyond_the_spec(client):
    """TODAY is ten seconds. Anything else belongs on another page."""
    html = client.get("/dashboard/today").data.decode()
    heads = re.findall(r'class="s-panel-title"[^>]*>([^<]+)', html)
    # #161 added two, and both earn their place: money that has landed with
    # no client against it is an anomaly, and a close only one source can see
    # is the thing that made Koji invisible for a day.
    allowed = {"Needs your ruling", "Since you last looked", "Sales pulse",
               "Money received, not yet attached to a client",
               "New closes detected"}
    for h in heads:
        clean = re.sub(r"\s+", " ", h.strip())
        clean = re.sub(r"\s*\([^)]*\)\s*$", "", clean)
        assert clean in allowed, f"TODAY grew a panel: {clean}"


# ── THE ONE SHOW-BASIS RULE (the 100% vs 70% defect) ────────────────────────

def test_exactly_one_show_basis_rule():
    """The pulse used to divide status-only shows by sets and call it
    verified; travelling used the confirmed basis. Two answers, one
    question. One rule now, and the pulse asks it."""
    ce = _read("compass_engine.py")
    pulse = ce[ce.index("def sales_pulse"):ce.index("def booked_calls_next_7d")]
    assert "travelling.show_basis" in pulse
    assert 'c.get("shows")' not in pulse and "shows_n / sets_n" not in pulse
    tv = _read("travelling.py")
    assert "def show_basis(" in tv


def test_show_basis_reports_confirmed_and_the_range(monkeypatch):
    import travelling as T
    monkeypatch.setattr(T, "_lead_rows", lambda w0, w1: ([], []))
    monkeypatch.setattr(T, "_appointments", lambda w0, w1: {"due": [1] * 23})
    monkeypatch.setattr(T, "_shows", lambda a, b, c, d: {
        "verified": [1] * 14, "by_close": [1] * 2, "unverified": [1] * 7,
        "noshow": [], "all": []})
    import datetime as dt
    out = T.show_basis(dt.date(2026, 9, 1), dt.date(2026, 9, 21))
    assert out["confirmed"] == 16 and out["unconfirmed"] == 7 and out["due"] == 23
    assert round(out["rate"], 2) == 0.70
    assert out["rate_upper"] == 1.0
    assert "16 confirmed of 23" in out["range_note"]
    assert "100%" in out["range_note"]      # the upper bound is SAID


def test_pulse_tile_never_calls_a_status_only_rate_verified():
    src = _read("dashboard", "exec_top.py")
    assert 'Show rate (confirmed)' in src
    assert 'Show rate (verified)' not in src


# ── THE MONTH-TO-DATE ANCHOR (SEV1 from Phase 0) ────────────────────────────

def test_bank_anchor_uses_days_not_entries():
    src = _read("tile_drawers.py")
    anchor = src[src.index("def _bank_anchor"):src.index("def _bank_anchor") + 2200]
    assert "trend.daily_series" in anchor
    code = "\n".join(l for l in anchor.splitlines()
                      if not l.strip().startswith("#"))
    assert "history_store.series(" not in code, \
        "series() counts ENTRIES — about 2.5 days at a 2h cadence"
    assert "earliest" in anchor


def test_bank_anchor_re_anchors_when_older_history_appears(monkeypatch):
    import kv_store
    import tile_drawers
    import trend
    from helpers import today_sydney
    t = today_sydney()
    key = f"fin:bank_anchor:{str(t)[:7]}"
    kv_store.put(key, {"date": f"{str(t)[:7]}-15", "balance": 185603.85,
                       "basis": "snapshot history"})
    monkeypatch.setattr(trend, "daily_series", lambda f, d=30: [
        {"date": f"{str(t)[:7]}-01", "value": 187354.54},
        {"date": f"{str(t)[:7]}-15", "value": 185603.85},
    ])
    a = tile_drawers._bank_anchor()
    assert a["date"].endswith("-01"), a
    assert a["balance"] == 187354.54


# ── TRENDS AND DELTAS ───────────────────────────────────────────────────────

def test_a_trend_means_days_and_says_so_when_it_cannot(monkeypatch):
    import trend
    monkeypatch.setattr(trend, "daily_series", lambda f, d=30: [
        {"date": "2026-09-20", "value": 1.0}, {"date": "2026-09-21", "value": 2.0}])
    s = trend.sparkline("x")
    assert s["points"] == []
    assert "2 days of history" in s["note"]


def test_a_flat_repeated_value_is_never_drawn_as_a_trend(monkeypatch):
    import trend
    monkeypatch.setattr(trend, "daily_series", lambda f, d=30: [
        {"date": f"2026-09-{i:02d}", "value": 5.0} for i in range(1, 12)])
    s = trend.sparkline("x")
    assert s["points"] == [] and "unchanged" in s["note"]


def test_daily_series_takes_the_last_reading_of_each_day(monkeypatch):
    import history_store
    import trend
    monkeypatch.setattr(history_store, "last_n_days", lambda n: [
        {"date": "2026-09-01", "snapshot": {"a": {"b": 1}}},
        {"date": "2026-09-01", "snapshot": {"a": {"b": 9}}},   # later wins
        {"date": "2026-09-02", "snapshot": {"a": {"b": 4}}},
    ])
    out = trend.daily_series("a.b", 30)
    assert out == [{"date": "2026-09-01", "value": 9.0},
                   {"date": "2026-09-02", "value": 4.0}]


def test_a_cost_metric_never_reads_ahead():
    """Polarity (#157, A3) carried into TODAY's deltas."""
    import trend
    d = trend.delta(12000, "", "", polarity="cost", unit="money")
    # no plan and no history → it says so rather than inventing a comparison
    assert "nothing to compare" in d["word"]

    class _T:
        pass
    import types
    fake = types.SimpleNamespace(
        _plan_for_month=lambda m: {"spend": 10000, "_version": 1})
    orig = trend._plan_for_month
    trend._plan_for_month = lambda m: {"spend": 10000, "_version": 1}
    try:
        d = trend.delta(12000, "", "spend", polarity="cost", unit="money")
        assert d["state"] == "bad"
        assert "over" in d["word"] and "ahead" not in d["word"]
        g = trend.delta(12000, "", "spend", polarity="gain", unit="money")
        assert "above" in g["word"]
    finally:
        trend._plan_for_month = orig


# ── SALES ───────────────────────────────────────────────────────────────────

def test_sales_is_owner_only_and_ad_domain_is_refused(client):
    import app as appmod
    c = appmod.app.test_client()
    with c.session_transaction() as s:
        s["actor"] = {"user": "romano", "role": "ad_domain", "display": "Romano"}
    r = c.get("/dashboard/sales")
    assert r.status_code in (302, 403)
    if r.status_code == 302:
        assert "/ads" in (r.headers.get("Location") or "")
    # and anonymous is refused
    anon = appmod.app.test_client()
    ra = anon.get("/dashboard/sales")
    assert ra.status_code in (302, 401, 403)


def test_sales_never_reparses_the_tracker_itself():
    src = _read("sales_scoreboard.py")
    assert "tracker_cols" not in src and "_tracker_rows_clean" not in src
    assert "travelling._lead_rows" in src      # the one reader
    assert "travelling.show_basis" in src      # the one show rule


def test_ownership_comes_from_the_one_parser():
    ae = _read("attribution_engine.py")
    assert '"setter": g("setter"), "closer": g("closer")' in ae
    assert 'idx["setter"] = k' in ae and 'idx["closer"] = k' in ae


def test_outcome_words_never_become_people():
    import sales_scoreboard as S
    for word in ("Showed", "Cancelled", "No show", "0", ""):
        assert not S._is_person(word), word
    for name in ("Kalin", "Coby", "Maran", "Akila"):
        assert S._is_person(name), name


def test_small_n_is_said_out_loud():
    import sales_scoreboard as S
    assert S.confidence(40) == "enough to read"
    assert S.confidence(7) == "indicative only"
    assert S.confidence(2) == "too few to read"
    r = S._rate(1, 3)
    assert r["confidence"] == "too few to read" and r["n"] == 3


def test_unmarked_consults_show_their_closer_and_encode_no_ruling():
    """Rydel has not ruled on who marks attendance. The list shows the
    consult's assigned closer so either ruling works — and the module must
    not decide for him."""
    src = _read("sales_scoreboard.py")
    assert '"closer": (l.get("closer") or "").strip() or "unassigned"' in src
    # read the CODE, not the prose that explains why no ruling is encoded
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            for ruling in ("must mark", "is responsible for marking"):
                assert ruling not in low, f"a ruling was encoded: {ruling}"
    # and no person is hardcoded as the owner of attendance
    assert "attendance_owner" not in src and "marked_by =" not in src


def test_targets_are_never_guessed():
    """The payout tab's KPI block has no row labels in the export. A guess
    would be worse than a gap."""
    src = _read("sales_scoreboard.py")
    t = src[src.index("def _targets"):]
    assert '"available": False' in t
    assert "without guessing" in t


def test_sales_page_publishes_the_metric_contract(client):
    html = client.get("/dashboard/sales").data.decode()
    assert 'data-metric="sales_leads"' in html
    assert 'data-basis="confirmed"' in html


# ── 5.1 REQUIRED-RATE SOLVE ─────────────────────────────────────────────────

def test_required_rate_holds_upstream_and_solves_the_stage():
    import subprocess
    out = subprocess.run(
        ["node", "-e", """
        const S = require('./dashboard/static/js/sim_core.js');
        const agg={m0_share:0.5,contract_avg:12000,mrr_avg:2000,margin_avg:0.7,
                   comm_rate:0.15,tooling:500,epsilon:0.2,spend_baseline:9000};
        const rates={set:0.35,show:0.70,close:0.25};
        const base=S.chain(9000,180,rates,agg,false);
        const w=S.chainWithRate('clients',8,9000,180,rates,agg,false);
        const imp=S.requiredRate('clients',20,9000,180,rates,agg,false,{close:[0.15,0.35]});
        const ok=S.requiredRate('clients',3,9000,180,rates,agg,false,{close:[0.15,0.35]});
        console.log(JSON.stringify({
          shows_before: base.shows, shows_after: w.chained.shows,
          leads_before: base.leads, leads_after: w.chained.leads,
          clients_after: w.chained.clients,
          impossible: imp.flag, impossible_note: imp.note,
          ok_flag: ok.flag, required: w.solution.required,
          points: w.solution.points}));
        """],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    # UPSTREAM UNCHANGED
    assert abs(d["shows_before"] - d["shows_after"]) < 1e-9
    assert abs(d["leads_before"] - d["leads_after"]) < 1e-9
    # DOWNSTREAM EXACTLY WHAT WAS ASKED FOR
    assert abs(d["clients_after"] - 8) < 1e-9
    # FLAGS FIRE
    assert d["impossible"] == "impossible"
    assert "not achievable from" in d["impossible_note"]
    assert d["ok_flag"] == "ok"
    assert d["points"] > 0


def test_rates_render_as_percentages():
    html = _read("dashboard", "templates", "scale.html")
    assert 'id="rate-close" step="1" min="0" max="100"' in html
    js = _read("dashboard", "static", "js", "scale.js")
    assert "(+e.target.value || 0) / 100" in js


def test_clearing_a_count_returns_the_stage_to_derived():
    js = _read("dashboard", "static", "js", "scale.js")
    assert "function clearSolved" in js
    assert "back to derived" in _read("dashboard", "templates", "scale.html")
    assert "raw === '' || isNaN(wanted)" in js


def test_target_mode_still_exists():
    """'What would this take?' must still jump to Target mode."""
    js = _read("dashboard", "static", "js", "scale.js")
    assert "requiredSpend(" in js


# ── 5.3 / 5.4 — registered, not blind-built ─────────────────────────────────

def test_the_xero_rung_is_registered_not_built():
    """Invoice/payment reads are NOT granted; the ladder must not pretend."""
    assert "xero" not in _read("ads_truth.py").lower()
    doc = _read("DECISIONS.md")
    assert "accounting.transactions.read" in doc


def test_scan2_coverage_is_reported_not_implied():
    reg = _read("USABILITY_AUDIT.md")
    assert "metric keys" in reg


# ── what the gates caught after the first deploy ────────────────────────────

def test_closers_come_from_the_consult_not_the_set_date():
    """The tracker's Set Date column has been empty since April, so keying a
    closer's workload on it returned an empty table on live data. Consults
    come from the CRM appointments — travelling's source and clock."""
    src = _read("sales_scoreboard.py")
    fn = src[src.index("def _closers("):src.index("def _ownership_health")]
    assert "travelling._appointments" in fn
    assert 'l.get("set_date")' not in fn
    # a consult whose row names nobody is COUNTED, not dropped
    assert '"unassigned"' in fn


def test_ownership_health_is_reported_not_papered_over():
    """If the Closer column has stopped being filled, that is a finding
    about the source — the scoreboard says so rather than showing an empty
    table."""
    src = _read("sales_scoreboard.py")
    assert "def _ownership_health" in src
    fn = src[src.index("def _ownership_health"):src.index("def named_all_time_txt")]
    assert "named_in_window" in fn and "named_all_time" in fn
    assert "outcome_words_in_column" in fn


def test_a_raw_contact_id_is_never_shown_as_a_name():
    src = _read("sales_scoreboard.py")
    assert "def _crm_names" in src
    assert '"name not on file"' in src
    assert '"person": l.get("name") or l.get("business") or cid' not in src


def test_the_required_rate_readout_always_compares_to_the_measured_rate():
    """After a solve applies, the rate field holds the SOLVED value. If the
    readout then re-read it as "measured", a second keystroke would say
    "0 points above" and the comparison would vanish. The behaviour gate
    caught this on the live page."""
    js = _read("dashboard", "static", "js", "scale.js")
    assert "function measuredRate" in js
    assert "sol.measured = m;" in js
    assert "sol.points = (sol.required - m) * 100;" in js


def test_every_executive_tile_publishes_a_comparable_value():
    """Scan 2 compares NUMBERS. Five of the eight headline tiles published
    none — so the consistency matrix had been checking three of them, and
    TODAY's deltas had nothing to work with on the rest."""
    from dashboard import exec_top
    tiles = exec_top.build_tiles({})
    missing = [t["id"] for t in tiles
               if t.get("raw") is None and t.get("value") not in ("—", "", None)]
    assert not missing, f"tiles with a value but no data-value: {missing}"
    src = _read("dashboard", "exec_top.py")
    for tid in ("cash_net_mtd", "ltv_cac", "cohort_cash_roas"):
        assert tid in src
    # the pulse publishes its numbers too
    assert '"drawer": None, "raw": v}' in src


def test_the_simulator_is_published_as_a_model_not_as_actuals():
    """The simulator's numbers are a MODEL. They now carry an identity so
    the consistency scan can see them, and a SCENARIO basis so it can never
    compare them against measured actuals — scenario never contaminates
    actuals."""
    html = _read("dashboard", "templates", "scale.html")
    assert html.count('data-basis="scenario"') >= 5
    for key in ("sim_leads", "sim_calls", "sim_shows", "sim_clients",
                "sim_cash_this_month"):
        assert f'data-metric="{key}"' in html, key
    # the scan keys on (metric, window, basis, clock) — #164 joined the clock
    # so the closes keys compare like with like; a scenario row still can
    # never land in the same bucket as an engine row
    scan = _read("scripts", "triple_scan.py")
    assert 'key = (r["metric"], r["window"], r["basis"], r.get("clock") or "")' in scan


def test_shared_renderers_never_write_into_a_missing_node():
    """The IA split gave each area its own page, so a shared renderer WILL
    meet a node it does not own. Writing into it threw and killed the rest
    of the render — which is what the 7d/14d/30d/60d/90d buttons did on
    brief, ads & sales and unit economics. Guarded now, and pinned."""
    import re as _re
    js = _read("dashboard", "static", "js", "dashboard.js")
    assert "function setText" in js and "function setHTML" in js
    bad = _re.findall(
        r"\$\('#[A-Za-z0-9_-]+'\)\.(?:innerHTML|textContent|innerText)\s*=", js)
    assert not bad, f"{len(bad)} unguarded DOM writes remain"
    bad_style = _re.findall(r"(?<!\{ const e = )\$\('#[A-Za-z0-9_-]+'\)\.style\.", js)
    assert not bad_style, f"unguarded style writes: {bad_style[:3]}"


def test_the_ads_board_is_read_defensively_before_it_loads():
    """A control used before the first board fetch resolved read .scoreboard
    off a null state.board."""
    js = _read("dashboard", "static", "js", "adsapp.js")
    assert "state.board.scoreboard." not in js


def test_the_orb_never_eats_a_click():
    """#eh-stage is a fixed 240x240 decoration at --z-orb parked bottom-right.
    It sat on top of the landing's Outflows card, which could not be clicked
    at all. hud.js binds no handler to it, so the whole stage is
    click-through — the WRAPPER too, not just the rings."""
    css = _read("dashboard", "static", "css", "served.css")
    block = css[css.index("#eh-stage, #eh-orbwrap"):]
    block = block[:block.index("}") + 1]
    for el in ("#eh-stage", "#eh-orbwrap", "#eh-rings", "#eh-core"):
        assert el in block, el
    assert "pointer-events: none" in block
    js = _read("dashboard", "static", "js", "hud.js")
    assert "stage.addEventListener" not in js


def test_the_window_buttons_route_every_renderer_through_a_boundary():
    """7d/14d/30d/60d/90d re-render five shared panels. Called bare, the
    first renderer to meet a node its page does not own threw and the rest
    never ran. Each call goes through boundary(), which skips a panel that
    is not on this page and reports a real failure as telemetry."""
    js = _read("dashboard", "static", "js", "dashboard.js")
    i = js.index("// Re-render window-aware sections")
    block = js[i:i + 1600]
    for fn in ("renderPerfAnalysis", "renderFunnel", "renderSetters",
               "renderClosers", "renderCommissionDetail", "applyRangeEconomics"):
        assert f"{fn}(current" in block or f"{fn}(currentWindow)" in block, fn
        # …and none of them is called bare on its own line
        assert f"\n          {fn}(" not in block, f"{fn} is called outside a boundary"
    assert block.count("boundary(") >= 6
