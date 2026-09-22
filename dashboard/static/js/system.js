/* system.js — THE CALM LAYER.
 *
 * The page is already rendered when this runs. This does exactly two things:
 * a gentle poll that swaps values IN PLACE (never re-rendering the page, so
 * nothing shifts), and the Run-checks-now button.
 *
 * Phase 0's glitch was the opposite of this: two sections replaced a skeleton
 * after load, and the whole page inherited a ten-minute render() of every
 * panel. Neither happens here — no skeletons, no re-render, no request storm.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var POLL_MS = 60000;
  var inFlight = false;

  function boundary(name, fn) {
    try { fn(); } catch (e) {
      try { console.error('[system:' + name + ']', e); } catch (_) {}
    }
  }

  /* Swap a cell's text only if it CHANGED — touching the DOM when nothing
     moved is what makes a page feel restless. */
  function setText(el, text) {
    if (el && text != null && el.textContent !== String(text)) {
      el.textContent = String(text);
    }
  }

  function applySources(rows) {
    (rows || []).forEach(function (r) {
      var tr = document.querySelector('[data-metric="source_' + r.key + '"]');
      if (!tr) return;
      tr.setAttribute('data-value',
        r.age_minutes === null || r.age_minutes === undefined ? '' : r.age_minutes);
      var tds = tr.getElementsByTagName('td');
      if (tds.length >= 6) {
        setText(tds[1], r.age_words);
        tds[1].title = r.at || 'never';
        setText(tds[5], r.reason);
      }
    });
  }

  function poll() {
    if (inFlight || document.hidden) return;
    inFlight = true;
    fetch('/dashboard/api/system', { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        inFlight = false;
        if (!d) return;
        boundary('headline', function () {
          var h = $('sys-headline');
          if (h && d.headline) {
            setText(h, d.headline.line);
            h.setAttribute('data-value', d.headline.state);
            h.classList.toggle('is-degraded',
              d.headline.state === 'degraded' || d.headline.state === 'stale');
          }
        });
        boundary('sources', function () {
          applySources(((d.sections || {}).sources || {}).rows);
        });
        boundary('run-state', function () { applyRunState(d.run_state); });
      })
      .catch(function () { inFlight = false; });
  }

  function applyRunState(st) {
    var btn = $('sys-run-checks');
    var note = $('sys-run-note');
    if (!btn || !st) return;
    if (st.running) {
      btn.disabled = true;
      setText(btn, 'Running…');
      setText(note, st.step ? ('now: ' + st.step) : 'running');
    } else {
      btn.disabled = false;
      setText(btn, 'Run checks now');
      if (st.last_result) {
        setText(note, st.last_result.ok
          ? ('last run passed — ' + (st.last_result.passed || 0) + ' checks agreed')
          : ('last run found something — ' + (st.last_result.failed || 0) + ' differed'));
      }
    }
  }

  boundary('run-button', function () {
    var btn = $('sys-run-checks');
    if (!btn) return;
    btn.addEventListener('click', function () {
      btn.disabled = true;
      setText(btn, 'Starting…');
      fetch('/dashboard/api/system/run-checks', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) {
            btn.disabled = false;
            setText(btn, 'Run checks now');
            setText($('sys-run-note'), d.why || 'could not start');
            return;
          }
          applyRunState(d.state);
          // while a run is going, look a little more often — then settle back
          var fast = setInterval(function () {
            fetch('/dashboard/api/system/run-checks')
              .then(function (r) { return r.json(); })
              .then(function (s) {
                applyRunState(s);
                if (!s.running) { clearInterval(fast); poll(); }
              })
              .catch(function () { clearInterval(fast); });
          }, 3000);
        })
        .catch(function () {
          btn.disabled = false;
          setText(btn, 'Run checks now');
        });
    });
  });

  boundary('poll', function () {
    var el = document.querySelector('[data-poll-seconds]');
    if (el) POLL_MS = Math.max(parseInt(el.getAttribute('data-poll-seconds'), 10) || 60, 15) * 1000;
    setInterval(poll, POLL_MS);
    // and stop polling a tab nobody is looking at
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) poll();
    });
  });
})();
