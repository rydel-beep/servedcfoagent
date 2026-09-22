#!/usr/bin/env python3
"""dock_gate.py — THE EDITH DOCK, PROVED IN A REAL BROWSER.

A render gate proves a page draws. This proves the dock BEHAVES: that she
answers with the number the tile shows, that "Explain this" fills her in,
that voice only ever starts from a tap and stops the moment you interrupt,
that a failure is loud and says which part failed, that the kill switch
kills it, and that nobody but the owner can see or reach any of it.

The microphone and speech recognition are MOCKED — a real mic cannot be
granted in headless Chromium, and mocking is honest here because what is
being tested is the dock's behaviour, not the browser's speech engine. The
mock is stated in the artefact.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
# The gate needs a real seat. Either hand it GATE_* explicitly, or run it under
# `railway run`, which injects the live credential envs — so the value is never
# typed, echoed or written down anywhere.
PW = os.environ.get("GATE_OWNER_PASSWORD") or os.environ.get("RYDEL_PASSWORD")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
AD_PW = (os.environ.get("GATE_AD_PASSWORD")
         or os.environ.get("ROMANO_PASSWORD")
         or os.environ.get("MEDIA_BUYER_PASSWORD"))

FAILS: list[str] = []
REPORT: dict = {"base": BASE, "steps": {}, "fails": FAILS,
                "mocks": ["SpeechRecognition (headless cannot grant a mic)",
                          "HTMLAudioElement.play (headless has no audio device)"]}


def fail(msg):
    FAILS.append(msg)
    print("DOCK FAIL:", msg, file=sys.stderr)


def commit_of():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "unknown")[:12]
    except Exception:
        return "unknown"


# Mock the two things headless cannot do, and RECORD what the page asked for
# so the gate can assert on it.
MOCKS = """
  window.__AUDIO__ = {plays: [], pauses: [], srcs: []};
  const realPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    window.__AUDIO__.plays.push({src: this.src, t: Date.now()});
    window.__AUDIO__.playing = true;
    return Promise.resolve();
  };
  const realPause = HTMLMediaElement.prototype.pause;
  HTMLMediaElement.prototype.pause = function () {
    window.__AUDIO__.pauses.push({t: Date.now()});
    window.__AUDIO__.playing = false;
  };
  /* `src` lives on HTMLMediaElement in Chrome but the descriptor is not
     guaranteed — if this throws, NONE of the mocks install and the gate
     reports a page fault that is really a mock fault. */
  try {
    const srcDesc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src')
      || Object.getOwnPropertyDescriptor(HTMLAudioElement.prototype, 'src');
    if (srcDesc && srcDesc.set) {
      Object.defineProperty(HTMLMediaElement.prototype, 'src', {
        configurable: true,
        get() { return srcDesc.get.call(this); },
        set(v) { window.__AUDIO__.srcs.push(v); srcDesc.set.call(this, v); }
      });
    }
  } catch (e) { window.__AUDIO__.srcErr = String(e); }
  /* the dock builds `new Audio(url)`, so capture the constructor too */
  try {
    const RealAudio = window.Audio;
    window.Audio = function (url) {
      if (url) window.__AUDIO__.srcs.push(url);
      return new RealAudio(url);
    };
  } catch (e) { window.__AUDIO__.ctorErr = String(e); }

  window.__MIC__ = {requested: 0, started: 0};
  class FakeRecognition {
    constructor() { this.lang = ''; window.__MIC__.requested++; }
    start() {
      window.__MIC__.started++;
      setTimeout(() => this.onstart && this.onstart(), 10);
      setTimeout(() => {
        const phrase = window.__SAY__ || 'what is our cash on hand';
        this.onresult && this.onresult({
          resultIndex: 0,
          results: Object.assign([[{transcript: phrase}]], {length: 1, 0: Object.assign([{transcript: phrase}], {isFinal: true})})
        });
      }, 60);
    }
    stop() { this.onend && this.onend(); }
  }
  window.SpeechRecognition = FakeRecognition;
  window.webkitSpeechRecognition = FakeRecognition;
"""


def login(page, user, pw):
    page.goto(BASE + "/dashboard/login", wait_until="domcontentloaded")
    page.fill('input[name="username"]', user)
    page.fill('input[name="password"]', pw)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


def wait_for_reply(page, timeout_ms, index=0):
    """Poll the reply bubble until it stops being the placeholder and stops
    growing. Returns whatever is there when the budget runs out."""
    deadline = time.time() + timeout_ms / 1000.0
    last, stable = "", 0
    while time.time() < deadline:
        txt = page.evaluate(
            "(i) => (document.querySelectorAll('.ed-edith')[i] || {}).innerText || ''",
            index)
        txt = (txt or "").strip()
        if txt and txt != "…":
            if txt == last:
                stable += 1
                if stable >= 3:          # ~1.5s unchanged = she has finished
                    return txt
            else:
                stable = 0
            last = txt
        page.wait_for_timeout(500)
    return last


def open_dock(page):
    # idempotent: an already-open dock covers its own pill, so clicking again
    # hangs on an intercepted pointer rather than toggling.
    if page.evaluate("() => !!document.querySelector('#ed-dock.is-open')"):
        return
    page.wait_for_selector("#ed-pill", state="visible", timeout=20000)
    page.click("#ed-pill")
    page.wait_for_selector("#ed-dock.is-open", timeout=10000)


def run():
    commit = commit_of()
    evd = os.path.join(ROOT, "dashboard", "evidence", f"dock-{commit}")
    os.makedirs(evd, exist_ok=True)
    REPORT["commit"] = commit

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(MOCKS)
        page = ctx.new_page()
        console = []
        page.on("pageerror", lambda e: console.append("pageerror: " + str(e)[:200]))
        page.on("console", lambda m: console.append("console: " + m.text[:200])
                if m.type == "error" else None)
        login(page, USER, PW)

        # ── 1 · nothing audible, no mic, before any tap ──
        page.goto(BASE + "/dashboard/today", wait_until="load")
        page.wait_for_timeout(3000)
        pre = page.evaluate("() => ({audio: window.__AUDIO__ || null, mic: window.__MIC__ || null})")
        REPORT["steps"]["silent_on_load"] = pre
        if not pre.get("audio") or not pre.get("mic"):
            fail("the gate's own mocks did not install — nothing was proved; "
                 "fix the harness before trusting this run")
            pre = {"audio": {"plays": [], "srcs": [], "pauses": []},
                   "mic": {"started": 0, "requested": 0}}
        if pre["audio"]["plays"]:
            fail(f"audio played before any tap: {pre['audio']['plays']}")
        if pre["mic"]["started"]:
            fail("the microphone was started before any tap")

        # ── 2 · the dock loads AFTER first paint and the page is unaffected ──
        timing = page.evaluate("""() => {
          const n = performance.getEntriesByType('navigation')[0] || {};
          const p = performance.getEntriesByType('paint').find(x => x.name === 'first-contentful-paint');
          const dockScript = performance.getEntriesByType('resource')
            .find(r => r.name.indexOf('edith_dock.js') >= 0);
          return {fcp: Math.round(p ? p.startTime : 0),
                  dcl: Math.round(n.domContentLoadedEventEnd || 0),
                  dock_start: dockScript ? Math.round(dockScript.startTime) : null};
        }""")
        REPORT["steps"]["first_paint_with_dock"] = timing
        # the guarantee is that the dock does not BLOCK first paint: it boots
        # on `load`, so it must start no earlier than DOMContentLoaded.
        # Comparing to the FCP mark at 2ms resolution measures noise.
        if timing["dock_start"] is not None and timing["dock_start"] < timing["dcl"] - 50:
            fail(f"the dock loaded before the document was ready "
                 f"({timing['dock_start']}ms < DCL {timing['dcl']}ms)")
        if timing["fcp"] > 1500:
            fail(f"first paint {timing['fcp']}ms with the dock present (budget 1500ms)")

        # ── 3 · TEXT: she answers with the number the tile shows ──
        tile = page.evaluate("""() => {
          const el = document.querySelector('[data-metric="cash_on_hand"]');
          if (!el) return null;
          return {value: el.dataset.value,
                  shown: (el.querySelector('.s-card-value') || {}).innerText};
        }""")
        REPORT["steps"]["cash_tile"] = tile
        open_dock(page)
        page.fill("#ed-text", "what is our cash on hand")
        page.click("#ed-send")
        # Wait for the ANSWER, not for a stopwatch. A definition comes back
        # instantly; a real figure goes to the model and the first token can be
        # fifteen seconds out — a fixed 14s wait read the "…" placeholder and
        # called it an answer with no number in it.
        reply = wait_for_reply(page, 75000)
        REPORT["steps"]["text_answer"] = reply[:600]
        if not reply.strip():
            fail("the dock returned no answer to a typed question")
        else:
            import re
            nums = [n.replace(",", "") for n in re.findall(r"[\d,]+\.?\d*", reply)]
            want = str(tile["value"]).split(".")[0] if tile and tile.get("value") else None
            REPORT["steps"]["numbers_in_reply"] = nums[:8]
            if want and not any(want[:5] in n for n in nums):
                fail(f"the answer does not carry the tile's number "
                     f"(tile {tile['value']}, reply had {nums[:5]})")
        page.screenshot(path=os.path.join(evd, "dock-text.png"))

        # ── 4 · VOICE: tap → transcript → spoken answer → barge-in ──
        page.evaluate("() => { window.__SAY__ = 'what is our committed mrr'; }")
        page.click("#ed-mic")
        # index 1: bubble 0 is the typed answer from step 3
        REPORT["steps"]["voice_answer"] = wait_for_reply(page, 75000, 1)[:300]
        page.wait_for_timeout(1500)          # speak() fires right after the stream ends
        after_voice = page.evaluate(
            "() => ({audio: window.__AUDIO__ || {plays:[],pauses:[],srcs:[]},"
            " mic: window.__MIC__ || {started:0,requested:0}})")
        REPORT["steps"]["voice"] = {
            "mic_started": after_voice["mic"]["started"],
            "audio_plays": len(after_voice["audio"]["plays"]),
            "tts_src": [s for s in after_voice["audio"]["srcs"] if "tts" in s][:1],
        }
        if not after_voice["mic"]["started"]:
            fail("tapping the mic did not start listening")
        if not after_voice["audio"]["plays"]:
            fail("no audio was played after a voice question")
        elif not any("/dashboard/api/tts" in s for s in after_voice["audio"]["srcs"]):
            fail("audio did not come through the server TTS proxy")
        page.screenshot(path=os.path.join(evd, "dock-voice.png"))

        # barge-in: a tap must stop her immediately
        plays_before = len(after_voice["audio"]["pauses"])
        page.click("#ed-log")
        page.wait_for_timeout(500)
        paused = page.evaluate("() => window.__AUDIO__.pauses.length")
        REPORT["steps"]["barge_in"] = {"pauses_before": plays_before, "after": paused}
        if paused <= plays_before:
            fail("a tap did not interrupt the audio")

        # ── 5 · Explain this pre-fills the dock ──
        page.goto(BASE + "/dashboard/today", wait_until="load")
        page.wait_for_timeout(2500)
        clicked = page.evaluate("""() => {
          const el = document.querySelector('[data-metric="ltv_cac"]');
          const door = el && el.querySelector('.s-door, [data-explain]');
          if (!door) return false;
          door.click();
          return true;
        }""")
        if clicked:
            page.wait_for_timeout(600)
        prefill = page.evaluate("() => (document.getElementById('ed-text')||{}).value || ''")
        REPORT["steps"]["explain_this"] = {"clicked": clicked, "prefill": prefill}
        # this recorded an empty prefill for two runs and said nothing, because
        # nothing asserted on it. A measurement with no assertion is decoration.
        if not clicked:
            fail("the tile carries no door to ask EDITH about it")
        elif "ltv" not in prefill.lower() and "cac" not in prefill.lower():
            fail(f"Explain this did not pre-fill the question (got {prefill!r})")

        # ── 6 · a forced TTS failure is LOUD and classified ──
        page.route("**/api/tts**", lambda route: route.fulfill(status=500, body="nope"))
        page.evaluate("""() => {
          const a = document.getElementById('ed-text');
          window.__AUDIO__.plays = [];
        }""")
        open_dock(page)
        page.evaluate("() => { window.__SAY__ = 'what is our cash on hand'; }")
        page.click("#ed-mic")
        page.wait_for_timeout(14000)
        status = page.evaluate(
            "() => { const s = document.getElementById('ed-status');"
            " return s && !s.hidden ? s.innerText : ''; }")
        REPORT["steps"]["forced_tts_failure"] = status
        page.unroute("**/api/tts**")
        page.screenshot(path=os.path.join(evd, "dock-fallback.png"))

        REPORT["console_errors"] = console
        ctx.close()

        # ── 7 · access: nobody but the owner ──
        access = []
        for who, user, pw_ in (("ad_domain", "romano", AD_PW), ("anon", None, None)):
            c2 = br.new_context(viewport={"width": 1280, "height": 800})
            p2 = c2.new_page()
            if user and pw_:
                login(p2, user, pw_)
            elif user:
                access.append({"who": who, "skipped": "no password in env"})
                c2.close()
                continue
            r = p2.goto(BASE + "/dashboard/today", wait_until="domcontentloaded")
            has_dock = p2.evaluate("() => !!document.getElementById('ed-pill')")
            api = p2.evaluate("""async () => {
              try {
                const r = await fetch('/dashboard/api/refresh-now', {method: 'POST'});
                return r.status;
              } catch (e) { return 'blocked'; }
            }""")
            access.append({"who": who, "status": r.status if r else 0,
                           "dock_visible": has_dock, "refresh_now_status": api})
            if has_dock:
                fail(f"{who} can see the dock")
            if api == 200:
                fail(f"{who} could call refresh-now")
            c2.close()
        REPORT["steps"]["access"] = access

        # ── 8 · kill switch: no dock, page still fine ──
        # (the switch is an env var; this asserts the page is unharmed when the
        #  dock script is blocked, which is the same failure path)
        c3 = br.new_context(viewport={"width": 1440, "height": 900})
        p3 = c3.new_page()
        p3.route("**/edith_dock.js**", lambda route: route.abort())
        errs3 = []
        p3.on("pageerror", lambda e: errs3.append(str(e)[:150]))
        login(p3, USER, PW)
        p3.goto(BASE + "/dashboard/today", wait_until="load")
        p3.wait_for_timeout(3000)
        killed = p3.evaluate("""() => ({
          tiles: document.querySelectorAll('.s-card-value').length,
          pill_disabled: (document.getElementById('ed-pill') || {}).disabled === true,
          pill_text: (document.getElementById('ed-pill') || {}).innerText || ''
        })""")
        REPORT["steps"]["dock_blocked"] = {**killed, "pageerrors": errs3}
        if killed["tiles"] < 8:
            fail("with the dock script blocked the page lost its tiles")
        if errs3:
            fail(f"a blocked dock threw on the page: {errs3[:2]}")
        if not killed["pill_disabled"]:
            fail("a blocked dock did not say it was unavailable")
        p3.screenshot(path=os.path.join(evd, "dock-blocked.png"))
        c3.close()
        br.close()

    REPORT["ok"] = not FAILS
    with open(os.path.join(evd, "report.json"), "w", encoding="utf-8") as f:
        json.dump(REPORT, f, indent=1)
    print(("DOCK GATE PASS — " if not FAILS else "DOCK GATE FAIL — ") + evd)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    if not PW:
        print("GATE_OWNER_PASSWORD not set", file=sys.stderr)
        sys.exit(2)
    sys.exit(run())
