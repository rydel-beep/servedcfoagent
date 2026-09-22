"""THE SYSTEM PAGE · FRESHNESS · THE EDITH DOCK.

Rydel's three asks, pinned:
  1 the System page is calm and true — no work on load, no raw streams
  2 EDITH is on every owner page, one brain, and silent until tapped
  3 data is current within a stated budget, or says how old it is
"""

import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def _code_only(src: str, js: bool = False) -> str:
    # Strip comments and docstrings. A test that greps prose fails on the very
    # comment explaining why the thing is absent — which is how these
    # assertions first "caught" their own documentation.
    out = []
    if js:
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        for line in src.splitlines():
            out.append(re.sub(r"(^|\s)//.*$", "", line))
        return "\n".join(out)
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    for line in src.splitlines():
        out.append(re.sub(r"(^|\s)#.*$", "", line))
    return "\n".join(out)


@pytest.fixture()
def client():
    os.environ.setdefault("DASHBOARD_TOKEN", "testtok-sys")
    import app as appmod
    from dashboard.auth import COOKIE_NAME
    c = appmod.app.test_client()
    c.set_cookie(COOKIE_NAME, os.environ["DASHBOARD_TOKEN"])
    return c


# ── PART 1 · THE SYSTEM PAGE ────────────────────────────────────────────────

def test_the_system_page_runs_nothing_on_load():
    """Pass-3 hunt. Loading the page must be a READ. No scan, no sync, no
    build_snapshot, no live source call."""
    src = _read("system_page.py")
    build = src[src.index("def build("):src.index("def _poll_seconds")]
    for forbidden in ("GT.run(", "ground_truth.run(", "build_snapshot",
                      "sync_all(", "sync_opportunities(", "fetch_day_live",
                      "refresh_cache(", "spend_in_range("):
        assert forbidden not in build, f"the page runs {forbidden} on load"
    # the only heavy thing it may touch is a stored result
    assert "kv_store" in src or "freshness" in src


def test_the_system_page_is_server_rendered_with_no_skeletons():
    html = _read("dashboard", "templates", "system.html")
    assert "skeleton" not in html, "a skeleton means a section fills after load"
    body = html.split("<main", 1)[1].split("</main>", 1)[0]
    # no inline fetch() inside the page body — that was the reflow
    assert "fetch(" not in body, "a section is still filled by inline fetch"
    assert "s-table" in body and "sys-sources" in body


def test_every_system_section_has_an_error_boundary():
    src = _read("system_page.py")
    assert "_guard(" in src
    html = _read("dashboard", "templates", "system.html")
    assert "s-boundary-fail" in html


def test_browser_errors_are_aggregated_never_a_raw_stream():
    """Phase 0: 81 errors in 24h were ONE problem, rendered as a dozen
    separate lines. Grouped now, with counts."""
    src = _read("system_page.py")
    fn = src[src.index("def _browser_errors"):src.index("def _gates")]
    assert "groups" in fn and "count" in fn
    assert "Counter" in _read("system_page.py")
    html = _read("dashboard", "templates", "system.html")
    assert "distinct problem" in html


def test_run_checks_is_explicit_rate_limited_and_one_at_a_time():
    import system_page as SP
    src = _read("system_page.py")
    assert "_MIN_SECONDS_BETWEEN_RUNS" in src
    assert 'st.get("running")' in src, "a second run must be refused"
    assert "threading" in src, "it must not block the request"
    st = SP.run_state()
    assert "running" in st


def test_the_system_page_publishes_metric_identities(client):
    r = client.get("/dashboard/system")
    assert r.status_code == 200
    html = r.data.decode()
    assert 'data-metric="system_state"' in html
    assert 'data-metric="source_' in html
    for attr in ("data-window=", "data-clock=", "data-basis=", "data-value="):
        assert attr in html


def test_the_poll_swaps_values_and_never_re_renders():
    js = _read("dashboard", "static", "js", "system.js")
    assert "function setText" in js
    assert "el.textContent !== String(text)" in js, "it must only touch what changed"
    assert "innerHTML" not in js, "re-rendering HTML is what made the page jump"
    assert "document.hidden" in js, "a tab nobody is looking at should not poll"


# ── PART 2 · FRESHNESS ──────────────────────────────────────────────────────

def test_every_source_has_a_stated_budget():
    import freshness as F
    for key, c in F.CONTRACT.items():
        assert c.get("budget_min") and c.get("label") and c.get("cadence"), key


def test_as_of_comes_from_inputs_never_render_time():
    """Pass-3 hunt. A page drawn in a millisecond can still be showing you
    yesterday."""
    src = _read("freshness.py")
    fn = src[src.index("def as_of("):src.index("def blocks_need_rebuild")]
    assert "now_sydney()" not in fn, "as-of must not be computed from now"
    assert "oldest" in fn and "TILE_INPUTS" in fn


def test_a_tile_is_only_as_fresh_as_its_oldest_input(monkeypatch):
    import freshness as F
    fake = {"rows": [
        {"key": "xero", "label": "Xero", "age_minutes": 30.0, "age_words": "30 minutes ago",
         "status": "ok", "at": "x", "budget_minutes": 1440, "budget_words": "1 day"},
        {"key": "engine_blocks", "label": "Engine blocks", "age_minutes": 200.0,
         "age_words": "3.3 hours ago", "status": "stale", "at": "y",
         "budget_minutes": 10, "budget_words": "10 minutes"},
    ], "stale": ["engine_blocks"]}
    monkeypatch.setitem(F.TILE_INPUTS, "t", ("xero", "engine_blocks"))
    a = F.as_of("t", fake)
    assert a["state"] == "stale"
    assert a["oldest_input"] == "engine_blocks"
    assert "Engine blocks" in a["stale_source"]
    assert "past its 10-minute budget" in a["why"]


def test_a_degraded_source_beats_a_merely_stale_one(monkeypatch):
    import freshness as F
    fake = {"rows": [
        {"key": "stripe", "label": "Stripe", "age_minutes": 5.0, "age_words": "5 minutes ago",
         "status": "degraded", "reason": "the endpoint failed", "at": "x",
         "budget_minutes": 20, "budget_words": "20 minutes"},
    ], "stale": []}
    monkeypatch.setitem(F.TILE_INPUTS, "t2", ("stripe",))
    a = F.as_of("t2", fake)
    assert a["state"] == "degraded" and "Stripe" in a["why"]


def test_refresh_now_rebuilds_the_blocks_not_just_the_snapshot():
    """The whole reason 'Refresh now' never refreshed: both old buttons
    rebuilt the snapshot and left every cache the tiles read untouched."""
    src = _read("freshness.py")
    fn = src[src.index("def refresh_now("):]
    assert "_block_builders()" in fn, "it must rebuild what the tiles read"
    assert "build_snapshot" not in fn, "the heavy pull is not the refresh button"


def test_refresh_now_never_force_pulls_xero():
    """Pass-3 hunt. Xero's refresh token is single-use; a forced pull risks
    the chain for every Xero read on the estate."""
    src = _read("freshness.py")
    fn = src[src.index("def refresh_now("):src.index("def _next_xero_words")]
    for forbidden in ("xero_pull", "_refresh_access_token", "_fetch_pnl"):
        assert forbidden not in fn, f"refresh_now touches {forbidden}"
    assert '"pulled": False' in fn
    assert "single-use" in fn


def test_refresh_now_is_rate_limited_and_journaled():
    src = _read("freshness.py")
    assert "_MIN_SECONDS_BETWEEN" in src
    assert "journal" in src


def test_the_tick_rebuilds_only_when_inputs_moved():
    import freshness as F
    src = _read("freshness.py")
    fn = src[src.index("def blocks_need_rebuild"):src.index("def tick(")]
    assert "newer" in fn and "budget" in fn
    # and the tick never pulls externally
    t = _code_only(src[src.index("def _block_builders"):src.index("def last_tick")])
    assert "build_snapshot" not in t


def test_meta_today_can_actually_refresh():
    """backfill_history is idempotent — a day already archived is never
    re-fetched, which is right for closed days and wrong for today."""
    src = _read("meta_spend.py")
    assert "def refresh_today(" in src
    fn = src[src.index("def refresh_today("):src.index("def fetch_day_live(")]
    assert "_save_store(store)" in fn
    # fetch_day_live stays read-only — the estate scan depends on it
    live = src[src.index("def fetch_day_live("):src.index("def fetch_day_live(") + 1400]
    assert "_save_store" not in live


# ── PART 3 · THE EDITH DOCK ─────────────────────────────────────────────────

def test_nothing_is_audible_or_recording_on_load():
    """Pass-3 hunt: audio before a tap, or a mic request before a tap."""
    js = _code_only(_read("dashboard", "static", "js", "edith_dock.js"), js=True)
    # every audio/mic entry point sits inside a click handler
    for call in ("new Audio(", "SpeechRecognition", "getUserMedia"):
        for m in re.finditer(re.escape(call), js):
            before = js[:m.start()]
            assert "addEventListener('click'" in before or "function speak" in before \
                or "var SR = window.SpeechRecognition" in before, \
                f"{call} may run before a tap"
    assert "autoplay" not in js.lower()
    assert "recog.start()" in js
    # …and recog.start is only reached from the mic click handler
    i = js.index("recog.start()")
    assert "mic.addEventListener('click'" in js[:i]


def test_the_dock_is_interruptible():
    js = _read("dashboard", "static", "js", "edith_dock.js")
    assert "function stopAudio" in js
    assert "dock.addEventListener('pointerdown'" in js, "a tap must stop her"
    assert "barge-in" in js, "the mic tap must stop any audio first"


def test_a_voice_failure_is_loud_and_classified():
    js = _read("dashboard", "static", "js", "edith_dock.js")
    assert "function fail(" in js
    for kind in ("'chat'", "'voice'"):
        assert f"fail({kind}" in js
    assert "owner-only" in js       # the 403 case is named, not silent


def test_there_is_only_one_edith_and_one_voice_pipeline():
    """Pass-3 hunt: a second brain or a second voice path."""
    js = _code_only(_read("dashboard", "static", "js", "edith_dock.js"), js=True)
    assert "/dashboard/api/chat-stream" in js, "it must use the existing brain"
    assert "/dashboard/api/tts" in js, "it must use the existing proxy"
    assert "elevenlabs" not in js.lower(), "the key must never reach the browser"
    assert "channel: 'dashboard'" in js, "its own thread on shared memory"
    routes = _read("dashboard", "routes.py")
    assert 'requested == "dashboard" and is_owner()' in routes


def test_the_dock_loads_after_first_paint_in_its_own_boundary():
    html = _read("dashboard", "templates", "partials", "edith_dock.html")
    assert "window.addEventListener('load'" in html
    assert "s.onerror" in html, "a blocked script must say so, not fail silently"
    assert "EDITH unavailable" in html


def test_the_dock_has_a_kill_switch_and_is_owner_only():
    routes = _read("dashboard", "routes.py")
    assert 'os.environ.get("EDITH_DOCK", "on")' in routes
    assert 'nav.get("owner")' in routes
    html = _read("dashboard", "templates", "partials", "edith_dock.html")
    assert "{% if nav.owner and edith_dock and edith_dock.enabled %}" in html


def test_discreet_mode_collapses_the_dock_and_says_so():
    html = _read("dashboard", "templates", "partials", "edith_dock.html")
    assert "ed-discreet" in html
    assert "confidential" in html.lower()
    routes = _read("dashboard", "routes.py")
    assert 'dock["discreet"] = bool(session.get(_CSM_DISCREET_KEY))' in routes


def test_a_non_owner_gets_no_dock(client):
    import app as appmod
    for role, user in (("coo", "piolo"), ("ad_domain", "romano"), ("sales", "kalin")):
        c = appmod.app.test_client()
        with c.session_transaction() as s:
            s["actor"] = {"user": user, "role": role, "display": user}
        r = c.get("/dashboard/today")
        if r.status_code == 200:
            body = r.data.decode()
            # the RENDERED dock, not the word: the definitions registry is
            # injected on every page and names "#ed-pill" as a selector
            assert 'id="ed-pill"' not in body, f"{role} can see the dock"
            assert 'id="ed-dock"' not in body, f"{role} can see the dock"
    anon = appmod.app.test_client()
    ra = anon.get("/dashboard/today")
    assert ra.status_code in (302, 401, 403)


def test_run_checks_and_refresh_are_owner_only(client):
    import app as appmod
    for role, user in (("coo", "piolo"), ("ad_domain", "romano")):
        c = appmod.app.test_client()
        with c.session_transaction() as s:
            s["actor"] = {"user": user, "role": role, "display": user}
        for path, method in (("/dashboard/api/system/run-checks", "post"),
                             ("/dashboard/api/refresh-now", "post")):
            r = getattr(c, method)(path)
            assert r.status_code in (302, 401, 403), (role, path, r.status_code)


def test_the_dock_carries_the_page_context():
    js = _read("dashboard", "static", "js", "edith_dock.js")
    assert "function pageContext" in js
    assert "data-metric][data-value" in js, "she should see the numbers on screen"
    assert "ui: pageContext()" in js
    assert "Explain " in js, "Explain this must pre-fill the dock"


# ── the stale drill's findings, locked in ────────────────────────────────────

def _row(key, label, age, budget, status):
    return {"key": key, "label": label, "at": "2026-09-22T10:00:00+10:00",
            "age_minutes": age, "age_words": f"{age} minutes ago",
            "budget_minutes": budget, "status": status, "reason": ""}


def test_a_tile_names_the_source_past_its_budget_not_the_oldest_one():
    """Found by the stale drill: committed MRR reads the tracker AND Xero.
    Pausing the tracker for six hours left the tile calm, because Xero's
    nineteen hours is a bigger number — and well inside its 24-hour budget."""
    import freshness as F
    src = {"rows": [_row("tracker_mirror", "Lead-to-Cash tracker (mirror)",
                         360, 3, "stale"),
                    _row("xero", "Xero (bank + P&L)", 1146, 1440, "ok")]}
    a = F.as_of("committed_mrr", src)
    assert a["state"] == "stale"
    assert a["stale_source"] == "Lead-to-Cash tracker (mirror)"
    assert "past its" in a["why"]


def test_a_tile_with_nothing_late_reports_its_oldest_input_and_stays_calm():
    import freshness as F
    src = {"rows": [_row("tracker_mirror", "Lead-to-Cash tracker (mirror)",
                         1, 3, "ok"),
                    _row("xero", "Xero (bank + P&L)", 1146, 1440, "ok")]}
    a = F.as_of("committed_mrr", src)
    assert a["state"] == "ok"
    assert a["stale_source"] is None
    assert a["oldest_input"] == "xero"
    assert "past its" not in a["why"]


# ── the SDK outage: EDITH's brain, and something watching it ─────────────────

def test_the_model_call_never_hardcodes_a_kwarg_the_sdk_may_not_take():
    """anthropic 1.7.0 dropped `temperature` from messages.create/stream. A
    floating requirement resolved to it and every business answer became
    'unexpected keyword argument' — with nothing on screen saying so."""
    for mod in ("dashboard/chat.py", "ghl_notes_summary.py"):
        code = _code_only(_read(*mod.split("/")))
        assert "temperature=" not in code, mod
        assert "llm_compat.temp(" in code, mod


def test_llm_compat_passes_temperature_only_where_it_is_accepted():
    import llm_compat
    def takes_it(model=None, temperature=None):
        pass
    def does_not(model=None):
        pass
    assert llm_compat.temp(takes_it, 0.5) == {"temperature": 0.5}
    assert llm_compat.temp(does_not, 0.5) == {}


def test_a_failing_brain_leaves_a_mark_the_system_page_reads():
    chat = _code_only(_read("dashboard", "chat.py"))
    assert "def note_brain(" in chat
    assert "edith:last_chat" in chat
    assert chat.count("note_brain(") >= 4, "both paths, success and failure"
    sysp = _code_only(_read("system_page.py"))
    assert "edith:last_chat" in sysp, "the System page must show the brain's pulse"


def test_the_freshness_tick_never_runs_inside_a_test_process():
    """It woke 45 seconds into a six-minute suite, rebuilt the engine blocks,
    bumped the derivation epoch and failed an unrelated cache test. A
    background thread must not edit the world the tests are measuring."""
    src = _read("app.py")
    fn = src[src.index("def _freshness_loop"):src.index("def _email_cadence_loop")]
    code = _code_only(fn)
    assert '"pytest" in _sys.modules' in code
    assert code.index('"pytest" in _sys.modules') < code.index("while True")


def test_the_brain_pulse_is_recorded_before_the_stream_ends():
    """A generator's code after `yield ("done", …)` never runs once the
    client stops reading — the first version recorded nothing at all."""
    src = _read("dashboard", "chat.py")
    fn = src[src.index("def chat_stream("):]
    code = _code_only(fn)
    done = code.index('yield ("done"')
    mark = code.index("note_brain(True)")
    assert mark < done, "the success mark must land before the final yield"


def test_the_brain_pulse_uses_the_kv_api_that_exists():
    """note_brain swallows its own exceptions so a failed write can never
    break a reply — which also means a typo'd call is silent. It called
    kv_store.set(); the module only has put()."""
    import kv_store
    code = _code_only(_read("dashboard", "chat.py"))
    fn = code[code.index("def note_brain("):]
    fn = fn[:fn.index("\ndef ")]
    for call in re.findall(r"kv_store\.(\w+)\(", fn):
        assert hasattr(kv_store, call), f"kv_store has no {call}()"


def test_todays_ad_spend_is_refreshed_on_every_tick_not_only_rebuild_ticks():
    """The Meta check sat INSIDE the rebuild branch, so on a quiet tick —
    blocks fresh, nothing to rebuild — the intraday number drifted past its
    hour and nobody refreshed it. Caught live: 'meta_today' stale again the
    day it was fixed."""
    src = _read("freshness.py")
    fn = src[src.index("def tick("):src.index("def _block_builders")]
    code = _code_only(fn)
    meta = code.index("refresh_today()")
    decide = code.index("blocks_need_rebuild()")
    assert meta < decide, "Meta must be checked before the rebuild decision"
