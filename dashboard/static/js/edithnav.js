/* edithnav.js — the navigation ACTION handler (schema v1, nav_registry.py).
   EDITH's replies can carry `nav` SSE events; this executes them: smooth-scroll a
   section, open a page, set the global window, drive the ad board. Unknown/malformed
   actions are ignored gracefully — never a broken page. A subtle flash acknowledges
   every executed action. The Timeline widget adopts this same handler in Part 2. */
(function () {
  'use strict';

  var ANCHORS = {
    adlink: 'section-adlink', brief: 'section-brief',
    cash: 'section-cash-position', forward: 'section-forward', mrr: 'section-trend',
    churn: 'section-churn', economics: 'section-month-perf', pnl: 'section-waterfall',
    funnel: 'section-funnel', clients: 'section-health', team: 'section-team',
    pipeline: 'section-pipeline', reps: 'section-reps', dq: 'section-quality',
    action_feed: 'section-action-feed', capital: 'section-capital',
  };
  var PAGES = {
    leads_page: '/dashboard/leads', targets_page: '/dashboard/targets',
    data_sources: '/dashboard/data-sources',
  };
  // the dedicated ad dashboard: NEW TAB, params ride the URL (?window=&verdict=&creative=)
  function openAds(p) {
    var qs = [];
    if (p.window) qs.push('window=' + String(p.window).replace(/\D/g, ''));
    if (p.verdict) qs.push('verdict=' + encodeURIComponent(p.verdict));
    if (p.creative) qs.push('creative=' + encodeURIComponent(p.creative));
    window.open('/ads' + (qs.length ? '?' + qs.join('&') : ''), '_blank', 'noopener');
  }

  var lastSection = null;

  function flash(el) {
    if (!el) return;
    el.classList.add('ltcv-flash');
    setTimeout(function () { el.classList.remove('ltcv-flash'); }, 900);
  }

  function scrollToSection(id) {
    var el = document.getElementById(id);
    if (!el) return false;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    flash(el);
    // late-loading panels above can reflow and push the target away — re-assert
    // until the layout SETTLES (stable for 3 consecutive checks) or 15s, whichever
    // first. Instant re-scrolls; no animation fight.
    var tries = 0, stable = 0;
    var keep = setInterval(function () {
      tries++;
      var top = el.getBoundingClientRect().top;
      if (Math.abs(top) > 80) { el.scrollIntoView({ block: 'start' }); stable = 0; }
      else stable++;
      if (stable >= 3 || tries >= 20) clearInterval(keep);
    }, 750);
    return true;
  }

  function handle(action) {
    try {
      if (!action || action.v !== 1 || !action.type) return;
      var p = action.params || {};
      if (action.type === 'set_window') {
        var btn = document.querySelector('.global-window-btn[data-window="' + (+p.days) + '"]');
        if (btn) { btn.click(); flash(document.getElementById('global-window-bar')); }
        return;
      }
      if (action.type === 'navigate') {
        if (action.target === 'ad_tracking') { openAds(p); return; }   // its own dashboard
        if (PAGES[action.target]) { window.location.href = PAGES[action.target]; return; }
        var id = ANCHORS[action.target];
        if (!id) return;                          // unknown target — ignore, never break
        if (scrollToSection(id)) lastSection = action.target;
        return;
      }
      if (action.type === 'filter' && action.target === 'ad_tracking') {
        openAds(p);                               // filters travel as URL params
        return;
      }
    } catch (e) { /* an action must never break the page */ }
  }

  function state() {
    // the CURRENT view, sent with each chat turn so relative commands compose
    var s = { section: lastSection };
    try {
      var active = document.querySelector('.nav-link.active');
      if (!s.section && active) {
        var href = (active.getAttribute('href') || '').slice(1);
        Object.keys(ANCHORS).forEach(function (k) { if (ANCHORS[k] === href) s.section = k; });
      }
      if (window.AdTrack) {
        var a = window.AdTrack.state();
        if (s.section === 'ad_tracking') { s.window = a.days + 'd'; s.creative = a.creative; }
      }
    } catch (e) {}
    return s;
  }

  window.EdithNav = { handle: handle, state: state };
})();
