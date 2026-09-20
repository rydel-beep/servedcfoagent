/* defs.js — EXPLAIN EVERYTHING (one registry, no ad-hoc tooltip text).
   Reads window.__DEFS__ (server-injected registry). Provides:
   · hover tooltips (300ms, desktop) + keyboard focus tooltips
   · long-press tap sheets (mobile)
   · the "?" mode: outline everything explainable, click to read
   · the first-run tour (dismissable; reopen from the "?" menu)
   Enhancement lane — every handler guarded; failure never touches the page. */
(function () {
  'use strict';
  var REG = (window.__DEFS__ && window.__DEFS__.entries) || {};
  if (!Object.keys(REG).length) return;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // compiled (selector, id) list for hover matching
  var SELS = [];
  Object.keys(REG).forEach(function (id) {
    if (REG[id].selector) SELS.push([REG[id].selector, id]);
  });

  function entryFor(el) {
    var direct = el.closest && el.closest('[data-def]');
    if (direct && REG[direct.dataset.def]) return [REG[direct.dataset.def], direct];
    var node = el;
    for (var depth = 0; node && depth < 8; depth++, node = node.parentElement) {
      if (!node.matches) continue;
      for (var i = 0; i < SELS.length; i++) {
        try { if (node.matches(SELS[i][0])) return [REG[SELS[i][1]], node]; }
        catch (e) { /* bad selector never breaks the page */ }
      }
    }
    return null;
  }

  // ── tooltip element ──
  var tip = document.createElement('div');
  tip.id = 'defs-tip';
  tip.setAttribute('role', 'tooltip');
  document.addEventListener('DOMContentLoaded', function () { document.body.appendChild(tip); });
  if (document.body) document.body.appendChild(tip);

  function tipHtml(e) {
    var h = '<div class="dt-name">' + esc(e.name) + '</div>' +
            '<div class="dt-meaning">' + esc(e.meaning) + '</div>';
    if (e.computed) h += '<div class="dt-row"><b>How it’s worked out:</b> ' + esc(e.computed) + '</div>';
    if (e.changing) h += '<div class="dt-row"><b>If you change it:</b> ' + esc(e.changing) + '</div>';
    if (e.default_from) h += '<div class="dt-row"><b>Where it comes from:</b> ' + esc(e.default_from) + '</div>';
    if (e.good) h += '<div class="dt-row"><b>What good looks like:</b> ' + esc(e.good) + '</div>';
    if (e.drawer) h += '<div class="dt-row dt-hint">ⓘ opens the full working with the live numbers</div>';
    return h;
  }

  function showTip(e, el) {
    tip.innerHTML = tipHtml(e);
    tip.style.display = 'block';
    var r = el.getBoundingClientRect();
    var top = r.bottom + 8;
    if (top + 220 > window.innerHeight) top = Math.max(8, r.top - tip.offsetHeight - 8);
    tip.style.top = top + 'px';
    tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 360)) + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }

  var hoverTimer = null;
  document.addEventListener('mouseover', function (ev) {
    try {
      clearTimeout(hoverTimer);
      var hit = entryFor(ev.target);
      if (!hit) { hideTip(); return; }
      hoverTimer = setTimeout(function () { showTip(hit[0], hit[1]); }, 300);
    } catch (e) { /* never break the page */ }
  });
  document.addEventListener('mouseout', function () { clearTimeout(hoverTimer); hideTip(); });
  document.addEventListener('focusin', function (ev) {
    try { var hit = entryFor(ev.target); if (hit) showTip(hit[0], hit[1]); } catch (e) {}
  });
  document.addEventListener('focusout', hideTip);
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') { hideTip(); setMode(false); closeSheet(); }
  });

  // ── mobile tap sheet (long-press, or any tap in "?" mode) ──
  var sheet = document.createElement('div');
  sheet.id = 'defs-sheet';
  sheet.innerHTML = '<div class="ds-body"></div><button class="ds-close">close</button>';
  if (document.body) document.body.appendChild(sheet);
  sheet.querySelector('.ds-close').addEventListener('click', closeSheet);
  function openSheet(e) {
    sheet.querySelector('.ds-body').innerHTML = tipHtml(e);
    sheet.classList.add('open');
  }
  function closeSheet() { sheet.classList.remove('open'); }
  var pressTimer = null;
  document.addEventListener('touchstart', function (ev) {
    try {
      var hit = entryFor(ev.target);
      if (!hit) return;
      pressTimer = setTimeout(function () { openSheet(hit[0]); }, 500);
    } catch (e) {}
  }, { passive: true });
  document.addEventListener('touchend', function () { clearTimeout(pressTimer); }, { passive: true });

  // ── the "?" mode ──
  var mode = false;
  function setMode(on) {
    mode = !!on;
    document.body.classList.toggle('defs-mode', mode);
    var b = document.getElementById('defs-help-btn');
    if (b) b.classList.toggle('active', mode);
  }
  document.addEventListener('click', function (ev) {
    try {
      if (ev.target.closest && ev.target.closest('#defs-help-btn')) {
        ev.preventDefault();
        openMenu();
        return;
      }
      if (!mode) return;
      var hit = entryFor(ev.target);
      if (hit) { ev.preventDefault(); ev.stopPropagation(); openSheet(hit[0]); }
    } catch (e) {}
  }, true);

  // tag matched elements periodically so the "?" outline + keyboard focus work
  function tagPass() {
    try {
      SELS.forEach(function (pair) {
        document.querySelectorAll(pair[0]).forEach(function (el) {
          if (!el.dataset.def) el.dataset.def = pair[1];
          if (!el.hasAttribute('tabindex') &&
              !/^(a|button|input|select|textarea)$/i.test(el.tagName)) {
            el.setAttribute('tabindex', '0');
          }
        });
      });
    } catch (e) {}
  }
  tagPass();
  setInterval(tagPass, 3000);   // JS-rendered panels get tagged as they appear

  // ── "?" menu: legend link · tour · mode toggle ──
  var menu = null;
  function openMenu() {
    if (menu) { menu.remove(); menu = null; return; }
    menu = document.createElement('div');
    menu.id = 'defs-menu';
    menu.innerHTML =
      '<button data-act="mode">' + (mode ? 'Exit' : 'Start') + ' “what is this?” mode</button>' +
      '<button data-act="tour">Take the tour of this page</button>' +
      '<a href="/dashboard/definitions">Open the full definitions page</a>';
    document.body.appendChild(menu);
    var btn = document.getElementById('defs-help-btn');
    if (btn) {
      var r = btn.getBoundingClientRect();
      menu.style.top = (r.bottom + 6) + 'px';
      menu.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
    }
    menu.addEventListener('click', function (ev) {
      var act = ev.target.dataset && ev.target.dataset.act;
      if (act === 'mode') { setMode(!mode); }
      if (act === 'tour') { startTour(true); }
      if (act) { menu.remove(); menu = null; }
    });
  }

  // ── first-run tour ──
  var TOURS = {
    landing: ['cash_on_hand', 'committed_mrr', 'ltv_cac', 'exec_verdict',
              'pulse_booked_calls', 'card_scale', 'card_system'],
    scale: ['sim_spend', 'sim_cpl_mode', 'chain_clients', 'show_math',
            'i_want', 'accuracy_sentence', 'level_advanced', 'level_plan']
  };
  function pageKey() { return document.body.dataset.page === 'scale' ? 'scale' : 'landing'; }
  var tourEl = null;
  function startTour(force) {
    var key = pageKey();
    var steps = (TOURS[key] || []).filter(function (id) { return REG[id]; });
    if (!steps.length) return;
    try {
      if (!force && localStorage.getItem('defs-tour-' + key) === 'done') return;
    } catch (e) {}
    var i = 0;
    function step() {
      if (tourEl) tourEl.remove();
      if (i >= steps.length) { finish(); return; }
      var e = REG[steps[i]];
      var target = null;
      try { target = e.selector && document.querySelector(e.selector); } catch (x) {}
      tourEl = document.createElement('div');
      tourEl.id = 'defs-tour';
      tourEl.innerHTML = '<div class="dt-name">' + (i + 1) + ' / ' + steps.length +
        ' · ' + esc(e.name) + '</div><div class="dt-meaning">' + esc(e.meaning) + '</div>' +
        (e.changing ? '<div class="dt-row">' + esc(e.changing) + '</div>' : '') +
        '<div class="tour-btns"><button data-t="skip">skip the tour</button>' +
        '<button data-t="next" class="primary">' + (i === steps.length - 1 ? 'done' : 'next →') + '</button></div>';
      document.body.appendChild(tourEl);
      document.querySelectorAll('.tour-focus').forEach(function (n) { n.classList.remove('tour-focus'); });
      if (target) {
        target.classList.add('tour-focus');
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        var r = target.getBoundingClientRect();
        tourEl.style.top = Math.min(window.innerHeight - 200, r.bottom + 10) + 'px';
        tourEl.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 380)) + 'px';
      } else {
        tourEl.style.top = '80px'; tourEl.style.left = '50%';
      }
      tourEl.addEventListener('click', function (ev) {
        var t = ev.target.dataset && ev.target.dataset.t;
        if (t === 'next') { i++; step(); }
        if (t === 'skip') finish();
      });
    }
    function finish() {
      if (tourEl) tourEl.remove();
      document.querySelectorAll('.tour-focus').forEach(function (n) { n.classList.remove('tour-focus'); });
      try { localStorage.setItem('defs-tour-' + key, 'done'); } catch (e) {}
    }
    step();
  }
  window.addEventListener('load', function () { setTimeout(function () { startTour(false); }, 1200); });
})();
