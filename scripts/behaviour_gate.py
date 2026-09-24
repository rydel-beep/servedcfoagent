#!/usr/bin/env python3
"""behaviour_gate.py — THE BEHAVIOUR GATE (render gate ≠ behaviour gate).

Playwright INTERACTION tests on the production /scale simulator, owner
session: set spend → leads must move to spend÷CPL · change CPL → leads must
move · drag the chart → spend+leads follow · target mode ("40 calls") →
spend becomes the solved answer, sentence inverts · elasticity toggle →
effective CPL shown, leads bend · reset → measured defaults restored ·
zero console errors throughout. FAIL = NO DEPLOY. Three passes
(cold / warm / post-rebuild-tick optional). On PASS it posts to
/api/scale/behaviour-verified so the "LOGIC VERIFIED" badge updates.
Artefacts → dashboard/evidence/behaviour-<commit>/.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PW = os.environ.get("GATE_OWNER_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
LEGACY_TOKEN = os.environ.get("GATE_LEGACY_TOKEN")
PASSES = int(os.environ.get("BEHAVIOUR_PASSES", "3"))
ROOT = os.path.join(os.path.dirname(__file__), "..")

FAILS: list[str] = []
REPORT: dict = {"base": BASE, "passes": [], "fails": FAILS}


def fail(msg):
    FAILS.append(msg)
    print("BEHAVIOUR FAIL:", msg, file=sys.stderr)


def commit_of():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "unknown")[:12]
    except Exception:
        return "unknown"


def login(page):
    if LEGACY_TOKEN:
        page.goto(BASE + "/dashboard/?t=" + LEGACY_TOKEN, wait_until="domcontentloaded")
        return
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', PW)
    page.click('button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


def state(page):
    return page.evaluate("""() => ({
      spend: +(document.getElementById('sim-spend')?.value || 0),
      cpl: +(document.getElementById('sim-cpl')?.value || 0),
      leads: +((document.getElementById('sim-leads')?.innerText || '0').replace(/,/g, '')),
      sentence: (document.getElementById('sim-sentence')?.innerText || ''),
      chart_point: +(document.getElementById('sim-chart')?.dataset.point || -1),
      cpl_disabled: !!document.getElementById('sim-cpl')?.disabled,
      spend_disabled: !!document.getElementById('sim-spend')?.disabled,
      cpl_note: (document.getElementById('sim-cpl-note')?.innerText || ''),
      calls: chainCount('chain-calls-v'),
      shows: chainCount('chain-shows-v'),
      clients: chainCount('chain-clients-v'),
      rate_close: +(document.getElementById('rate-close')?.value || 0),
      req_clients: (document.getElementById('req-clients')?.innerText || ''),
      req_clients_cls: (document.getElementById('req-clients')?.className || ''),
    })""".replace('chainCount(', 'window.__cc('))


def _install_reader(page):
    """The stage counts became editable inputs when the required-rate solve
    shipped, so the gate reads .value rather than text."""
    page.evaluate("""() => {
      window.__cc = function (id) {
        var el = document.getElementById(id);
        if (!el) return '';
        return ('value' in el ? el.value : el.innerText) || '';
      };
    }""")


def type_into(page, sel, value):
    page.fill(sel, str(value))
    page.dispatch_event(sel, "input")
    time.sleep(0.35)


def run_pass(page, name, evd, shots):
    steps = {}
    page.goto(BASE + "/dashboard/scale", wait_until="load")
    time.sleep(3)
    _install_reader(page)
    page.evaluate("document.querySelector('#defs-tour [data-t=skip]')?.click()")
    time.sleep(0.3)
    s0 = state(page)
    steps["initial"] = s0
    if not s0["leads"]:
        fail(f"{name}: leads output empty at load")
        return steps

    # 1 · SET SPEND → leads == spend ÷ CPL, chain moves
    type_into(page, "#sim-spend", 15000)
    s1 = state(page)
    steps["after_spend_15000"] = s1
    expect = 15000 / s1["cpl"]
    if abs(s1["leads"] - expect) > 2:
        fail(f"{name}: spend edit — leads {s1['leads']} ≠ 15000÷{s1['cpl']}={expect:.0f}")
    if s1["calls"] == s0["calls"]:
        fail(f"{name}: spend edit — the chain did not move")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-1-spend.png"))

    # 2 · CHANGE CPL → leads move (RYDEL'S EXACT COMPLAINT)
    type_into(page, "#sim-cpl", 120)
    s2 = state(page)
    steps["after_cpl_120"] = s2
    if abs(s2["cpl"] - 120) > 0.01:
        fail(f"{name}: CPL edit was not kept (field reads {s2['cpl']})")
    if abs(s2["leads"] - 15000 / 120) > 2:
        fail(f"{name}: CPL edit — leads {s2['leads']} ≠ 15000÷120=125")
    if "$120" not in s2["sentence"] and "120.00" not in s2["sentence"]:
        fail(f"{name}: sentence still shows the old CPL: {s2['sentence'][:80]}")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-2-cpl.png"))

    # 3 · chart point == fields (a view, not a second calculation)
    if s2["chart_point"] >= 0 and abs(s2["chart_point"] - s2["leads"]) > 2:
        fail(f"{name}: chart point {s2['chart_point']} ≠ leads {s2['leads']}")

    # 4 · DRAG the chart → spend + leads follow (scroll it into the
    # viewport first — mouse events off-viewport dispatch nowhere)
    page.locator("#sim-chart").scroll_into_view_if_needed()
    time.sleep(0.3)
    box = page.evaluate("""() => { const r = document.getElementById('sim-chart').getBoundingClientRect();
                                   return {x: r.left, y: r.top, w: r.width, h: r.height}; }""")
    page.mouse.move(box["x"] + box["w"] * 0.8, box["y"] + box["h"] * 0.5)
    page.mouse.down()
    page.mouse.move(box["x"] + box["w"] * 0.85, box["y"] + box["h"] * 0.5)
    page.mouse.up()
    time.sleep(0.4)
    s4 = state(page)
    steps["after_drag"] = s4
    if abs(s4["spend"] - s2["spend"]) < 500:
        fail(f"{name}: chart drag did not move spend ({s2['spend']} → {s4['spend']})")
    if abs(s4["leads"] - s4["spend"] / s4["cpl"]) > 3:
        fail(f"{name}: after drag leads {s4['leads']} ≠ spend÷CPL")

    # 5 · TARGET MODE: I want 40 calls → spend becomes the answer
    page.select_option("#iwant-kind", "calls")
    page.fill("#iwant-value", "40")
    page.click("#btn-iwant")
    time.sleep(0.6)
    s5 = state(page)
    steps["after_target_40calls"] = s5
    if not s5["spend_disabled"]:
        fail(f"{name}: target mode — spend field should be visibly the answer (disabled)")
    if "you need $" not in s5["sentence"] and "To get 40" not in s5["sentence"]:
        fail(f"{name}: target sentence did not invert: {s5['sentence'][:90]}")
    # calls must read ~40
    try:
        if abs(float(s5["calls"]) - 40) > 1:
            fail(f"{name}: target 40 calls — chain reads {s5['calls']}")
    except ValueError:
        fail(f"{name}: calls not numeric in target mode: {s5['calls']!r}")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-5-target.png"))

    # 6 · back to FORWARD; ELASTICITY toggle → effective CPL shown, leads bend
    page.check("#mode-forward")
    time.sleep(0.3)
    type_into(page, "#sim-spend", 30000)
    before = state(page)
    page.check("#sim-cpl-mode")
    time.sleep(0.4)
    s6 = state(page)
    steps["after_elasticity_on"] = s6
    if not s6["cpl_disabled"]:
        fail(f"{name}: elasticity ON — the CPL field must be read-only-derived")
    if "effective CPL" not in s6["cpl_note"]:
        fail(f"{name}: elasticity ON — no effective-CPL explanation shown")
    if not (s6["leads"] < before["leads"]):
        fail(f"{name}: elasticity ON at high spend must bend leads down "
             f"({before['leads']} → {s6['leads']})")
    page.uncheck("#sim-cpl-mode")
    time.sleep(0.3)
    s6b = state(page)
    if s6b["cpl_disabled"]:
        fail(f"{name}: elasticity OFF — CPL must be editable again")

    # 7 · RESET to measured
    page.click(".sim-preset[data-preset='measured']")
    time.sleep(0.4)
    s7 = state(page)
    steps["after_reset"] = s7
    if abs(s7["spend"] - steps["initial"]["spend"]) > max(steps["initial"]["spend"] * 0.02, 100):
        fail(f"{name}: reset did not restore measured spend "
             f"({steps['initial']['spend']} vs {s7['spend']})")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-7-reset.png"))
    return steps




def run_cost_card(page, name, evd, shots):
    """THE COST CARD, MADE TRUE: change the closer mix toward Coby → the
    cost per client FALLS (the junior rate is the company's total); change
    the qualified rate → the bounty line moves; the headcount line appears
    at scaled volume and CAC carries it."""
    steps = {}
    page.goto(BASE + "/dashboard/scale", wait_until="load")
    time.sleep(3)
    page.evaluate("document.querySelector('#defs-tour [data-t=skip]')?.click()")
    page.evaluate("document.getElementById('level-advanced')?.setAttribute('open','')")
    try:
        page.wait_for_selector("[data-closer-mix]", timeout=20000)
    except Exception:
        fail(f"{name}: closer-mix control missing from the advanced inputs")
        return steps

    def card():
        return page.evaluate("""() => ({
          cac: (document.getElementById('chain-cac-v')?.innerText || ''),
          cac_n: +((document.getElementById('chain-cac-v')?.dataset.value) || 0),
          card: Array.from(document.querySelectorAll('#cost-card li')).map(li => li.innerText.replace(/\\n/g, ' ')),
          note: (document.getElementById('cost-card-note')?.innerText || ''),
          ratios: (document.getElementById('cost-ratios')?.innerText || ''),
        })""")

    s0 = card()
    steps["initial"] = s0
    if "rulebook" not in s0["note"]:
        fail(f"{name}: cost-card footnote does not name the rulebook")
    if "never the source" not in s0["note"]:
        fail(f"{name}: the FY26 reference is not labelled reference-only")
    if "LTV:CAC" not in s0["ratios"] or "LTGP:CAC" not in s0["ratios"]:
        fail(f"{name}: the ratios are not named on the card")
    if not any("headcount" in li for li in s0["card"]):
        fail(f"{name}: no headcount line on the cost card")
    cac0 = page.evaluate("() => +(document.getElementById('chain-cac-v')?.innerText || '').replace(/[$,]/g, '')")

    # shift the closer mix toward Coby → cost per client falls
    type_into(page, "[data-closer-mix='coby']", 0.5)
    kalin_el = page.query_selector("[data-closer-mix='kalin']")
    if kalin_el:
        type_into(page, "[data-closer-mix='kalin']", 0.5)
    time.sleep(1.5)          # debounce + engine round-trip
    s1 = card()
    steps["after_coby_50"] = s1
    cac1 = page.evaluate("() => +(document.getElementById('chain-cac-v')?.innerText || '').replace(/[$,]/g, '')")
    if not (cac1 < cac0):
        fail(f"{name}: closer mix toward Coby did not lower CAC ({cac0} → {cac1})")

    # qualified rate down → bounty line falls
    def bounty():
        return page.evaluate("""() => { const li = Array.from(document.querySelectorAll('#cost-card li'))
          .find(x => x.innerText.includes('bounties'));
          return li ? +(li.innerText.match(/\\$([\\d,]+)/) || [0,'0'])[1].replace(/,/g, '') : null; }""")
    b0 = bounty()
    type_into(page, "[data-ctl='qualified_rate']", 0.5)
    time.sleep(1.5)
    b1 = bounty()
    steps["bounty_move"] = {"before": b0, "after": b1}
    if b0 is None or b1 is None or not (b1 < b0):
        fail(f"{name}: qualified rate 0.5 did not lower bounties ({b0} → {b1})")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-8-costcard.png"))
    return steps


def run_travelling(page, evd, shots):
    """HOW WE'RE TRAVELLING — the interaction contract: the button lands
    here with the scenario as the comparison; switching the window changes
    the numbers AND they equal the engine; switching the comparator changes
    the plan side; the two actions do what they say; refresh keeps state."""
    steps = {}
    page.goto(BASE + "/dashboard/scale", wait_until="load")
    time.sleep(2.5)
    page.evaluate("document.querySelector('#defs-tour [data-t=skip]')?.click()")
    btn = page.query_selector("#btn-travelling")
    if not btn:
        fail("travelling: the 'Show how we're travelling' button is missing from the compass")
        return steps
    btn.click()
    page.wait_for_load_state("load")
    time.sleep(2.5)

    def tv_state(_retry=True):
        # Changing the comparator NAVIGATES. If the navigation is still
        # settling, evaluate() dies with "execution context was destroyed" —
        # which reads like a broken page and is really just a race. Settle,
        # then read; retry once.
        #
        # And WAIT FOR THE STAGES. Reading before the page has painted them
        # reported "leads on screen 0 ≠ engine 175" against a page that
        # renders 175 perfectly well — a gate that races is a gate that lies.
        try:
            page.wait_for_load_state("load", timeout=20000)
            page.wait_for_selector(".tv-stage", timeout=20000)
        except Exception:
            pass
        try:
            return page.evaluate("""() => ({
          url: location.pathname + location.search,
          stages: document.querySelectorAll('.tv-stage').length,
          verdict: (document.querySelector('.tv-verdict')?.innerText || '').trim(),
          compare: (document.querySelector('[data-def=tv_compare] select')?.value || ''),
          window: (document.querySelector('[data-def=tv_window] select')?.value || ''),
          progress: (document.querySelector('[data-def=tv_progress]')?.innerText || '').trim(),
          leads: (document.querySelector('#stage-leads .tv-actual')?.innerText || '').trim(),
          closed: (document.querySelector('#stage-closed .tv-actual')?.innerText || '').trim(),
          bars: document.querySelectorAll('.tv-bar-actual').length,
          read: (document.querySelector('[data-def=tv_read] p')?.innerText || '').trim().length,
          gap: (document.querySelector('[data-def=tv_gap]')?.innerText || '').trim(),
        })""")
        except Exception:
            if not _retry:
                raise
            time.sleep(1.5)
            return tv_state(_retry=False)

    s1 = tv_state()
    steps["opened"] = s1
    if "/dashboard/scale/travelling" not in s1["url"]:
        fail(f"travelling: the button did not land on the view ({s1['url']})")
    if s1["stages"] != 10:
        fail(f"travelling: {s1['stages']} stages rendered, expected 10")
    if not s1["verdict"]:
        fail("travelling: no one-line verdict")
    if s1["compare"] != "scenario":
        fail(f"travelling: opened with comparator '{s1['compare']}', expected the scenario")
    if not s1["read"]:
        fail("travelling: the read is empty")
    if not s1["bars"]:
        fail("travelling: the funnel drew no bars")
    if shots:
        page.screenshot(path=os.path.join(evd, "travelling-1-opened.png"), full_page=True)

    # 2 · switch the window → numbers change AND match the engine
    page.select_option("[data-def=tv_window] select", "d21")
    page.wait_for_load_state("load")
    time.sleep(2.5)
    s2 = tv_state()
    steps["window_d21"] = s2
    if s2["window"] != "d21":
        fail("travelling: the window control did not switch")
    if "Day 21 of 21" not in s2["progress"]:
        fail(f"travelling: the 21-day window shows progress '{s2['progress']}'")
    engine = page.evaluate(
        """async () => { const r = await fetch('/dashboard/api/travelling?window=d21&compare=usual');
             return r.ok ? await r.json() : null; }""")
    if engine:
        eng_leads = next((x["actual"] for x in engine["stages"] if x["id"] == "leads"), None)
        shown = int((s2["leads"] or "0").replace(",", "") or 0)
        if eng_leads is not None and abs(eng_leads - shown) > 0:
            fail(f"travelling: leads on screen {shown} ≠ engine {eng_leads}")
        steps["engine_match"] = {"screen": shown, "engine": eng_leads}

    # 3 · switch the comparator → the plan side changes
    before_url = page.url
    page.select_option("[data-def=tv_compare] select", "usual")
    try:
        page.wait_for_url(lambda u: u != before_url, timeout=15000)
    except Exception:
        pass
    page.wait_for_load_state("load")
    time.sleep(1.0)
    s3 = tv_state()
    steps["compare_usual"] = s3
    if s3["compare"] != "usual":
        fail("travelling: the comparator control did not switch")

    # 4 · refresh keeps state (URL-driven)
    page.reload(wait_until="load")
    time.sleep(2)
    s4 = tv_state()
    if s4["window"] != "d21" or s4["compare"] != "usual":
        fail("travelling: a refresh lost the window/comparator state")
    steps["after_refresh"] = s4

    # 5 · the people behind a number
    page.click("#stage-leads .tv-door")
    time.sleep(0.8)
    roster = page.evaluate(
        "() => ({open: document.getElementById('tv-roster')?.style.display !== 'none',"
        " rows: document.querySelectorAll('#tv-roster-body tr').length})")
    steps["roster"] = roster
    if not roster["open"] or not roster["rows"]:
        fail(f"travelling: the people drawer did not open with rows ({roster})")
    page.click("#tv-roster-close")
    time.sleep(0.3)

    # 6 · the two actions
    clear_text(page, "tv-action-out")
    page.click("#tv-remodel")
    out = wait_for_text(page, "tv-action-out", "Loaded into the compass")
    steps["remodel"] = out
    if "Loaded into the compass" not in out:
        fail(f"travelling: re-model from actuals did not report back ({out[:80]})")
    if "rate" not in out.lower():
        fail("travelling: re-model did not name the rates it loaded")
    clear_text(page, "tv-action-out")      # never read the last reply as this one
    page.click("#tv-save")
    out2 = wait_for_text(page, "tv-action-out", "Saved")
    steps["save"] = out2
    if "Saved" not in out2:
        fail(f"travelling: save this check did not confirm ({out2[:80]})")
    if shots:
        page.screenshot(path=os.path.join(evd, "travelling-2-actions.png"), full_page=True)
    return steps



def wait_for_text(page, el_id, needle, timeout=15.0):
    """Wait for an element to actually SAY something, rather than sleeping a
    fixed 2.5s and hoping. A gate that flakes on latency teaches nothing —
    and worse, a late reply can land in the output just as the NEXT
    assertion reads it, so one slow call makes two checks lie. (This is the
    stale-response class #155 fixed in the simulator; the gate had it too.)"""
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        last = page.evaluate(
            "(id) => (document.getElementById(id)?.innerText || '').trim()", el_id)
        if needle.lower() in (last or "").lower():
            return last
        time.sleep(0.25)
    return last


def clear_text(page, el_id):
    """Empty an output element before triggering the next action, so a late
    reply from the PREVIOUS one can never be mistaken for this one's."""
    page.evaluate("(id) => { const e = document.getElementById(id); if (e) e.innerText = ''; }",
                  el_id)


def run_required_rate(page, name, evd, shots):
    """5.1 — TYPE A COUNT, GET THE RATE IT WOULD TAKE.

    The three things that must be true, checked by typing into the live
    page rather than by reading the code:
      · upstream does not move (the consults you already have stay put)
      · downstream becomes exactly what was asked for
      · an impossible ask is flagged as impossible, not quietly accepted
    """
    out = {}
    page.goto(BASE + "/dashboard/scale", wait_until="load")
    time.sleep(2.5)
    _install_reader(page)
    page.evaluate("document.querySelector('#defs-tour [data-t=skip]')?.click()")
    time.sleep(0.3)
    s0 = state(page)
    out["before"] = s0
    if not s0.get("shows"):
        fail(f"{name}: required-rate — no shows count to solve against")
        return out

    # ── a REACHABLE ask: one more client than the model gives ──
    want = max(round(float(s0["clients"] or 0)) + 1, 1)
    type_into(page, "#chain-clients-v", want)
    s1 = state(page)
    out["after_reachable"] = {"wanted": want, **s1}
    if abs(float(s1["shows"] or 0) - float(s0["shows"] or 0)) > 0.51:
        fail(f"{name}: required-rate — UPSTREAM MOVED: shows "
             f"{s0['shows']} → {s1['shows']} (it must be held)")
    if abs(float(s1["clients"] or 0) - want) > 0.05:
        fail(f"{name}: required-rate — downstream did not become the ask: "
             f"{s1['clients']} vs {want}")
    if "required" not in (s1["req_clients"] or "").lower():
        fail(f"{name}: required-rate — no readout: {s1['req_clients']!r}")
    if "measured" not in (s1["req_clients"] or "").lower():
        fail(f"{name}: required-rate — the readout never names the measured rate")
    if abs(s1["rate_close"] - s0["rate_close"]) < 0.5:
        fail(f"{name}: required-rate — the close rate field did not take the "
             f"solved value ({s0['rate_close']} → {s1['rate_close']})")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-req-reachable.png"))

    # ── an IMPOSSIBLE ask: more clients than there are consults ──
    absurd = round(float(s0["shows"] or 0)) + 50
    type_into(page, "#chain-clients-v", absurd)
    s2 = state(page)
    out["after_impossible"] = {"wanted": absurd, **s2}
    if "is-impossible" not in (s2["req_clients_cls"] or ""):
        fail(f"{name}: required-rate — {absurd} clients from "
             f"{s0['shows']} consults was not flagged impossible "
             f"(class {s2['req_clients_cls']!r})")
    if "not achievable" not in (s2["req_clients"] or "").lower():
        fail(f"{name}: required-rate — the impossible note is missing: "
             f"{s2['req_clients']!r}")
    if shots:
        page.screenshot(path=os.path.join(evd, f"{name}-req-impossible.png"))

    # ── CLEARING returns the stage to derived ──
    type_into(page, "#chain-clients-v", "")
    time.sleep(0.4)
    s3 = state(page)
    out["after_clear"] = s3
    if s3["req_clients"].strip():
        fail(f"{name}: required-rate — clearing the count left the readout up: "
             f"{s3['req_clients']!r}")
    return out


def main():
    if not PW and not LEGACY_TOKEN:
        print("GATE_OWNER_PASSWORD not in env", file=sys.stderr)
        sys.exit(2)
    commit = commit_of()
    evd = os.path.join(ROOT, "dashboard", "evidence", f"behaviour-{commit}")
    os.makedirs(evd, exist_ok=True)
    REPORT["commit"] = commit
    REPORT["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        console_errors = []
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)[:200]))
        page.on("console", lambda m: console_errors.append("console: " + m.text[:200])
                if m.type == "error" else None)
        login(page)
        names = ["cold", "warm", "third"][:PASSES]
        for i, name in enumerate(names):
            steps = run_pass(page, name, evd, shots=(i == 0))
            steps["travelling"] = run_travelling(page, evd, shots=(i == 0))
            steps["required_rate"] = run_required_rate(page, name, evd,
                                                       shots=(i == 0))
            steps["cost_card"] = run_cost_card(page, name, evd,
                                               shots=(i == 0))
            REPORT["passes"].append({"name": name, "steps": steps})
        REPORT["console_errors"] = console_errors
        for e in console_errors:
            fail("console: " + e)

        ok = not FAILS
        # post the result so the badge updates (owner session held)
        try:
            page.evaluate(
                """async (body) => { await fetch('/dashboard/api/scale/behaviour-verified', {
                     method: 'POST', headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify(body)}); }""",
                {"ok": ok, "commit": commit, "passes": len(names),
                 "reason": "; ".join(FAILS[:3])})
        except Exception as e:  # noqa: BLE001
            print("badge post failed:", e, file=sys.stderr)
        browser.close()
    REPORT["ok"] = not FAILS
    out = os.path.join(evd, "report.json")
    with open(out, "w") as f:
        json.dump(REPORT, f, indent=1)
    print(("BEHAVIOUR PASS — " if not FAILS else "BEHAVIOUR FAIL — ") + out)
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
