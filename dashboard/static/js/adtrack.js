/* adtrack.js — the AD TRACKING section: scoreboard + live tracker.
   RENDER ONLY: every figure comes from /cfo/attribution/scoreboard + /rows (cookie-
   authed, the same reconciled engine the dashboard quotes). No math beyond display
   formatting. Exposes window.AdTrack for EdithNav (voice-driven navigation). */
(function () {
  'use strict';

  var state = {
    days: 30, sort: 'spend', sortDir: -1, verdict: null, creative: null, q: '',
    scoreboard: null, rows: [], shown: 0, loading: false,
  };
  var PAGE = 150; // incremental render size for the 1,200+ row tracker

  function $(sel) { return document.querySelector(sel); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function money(v) { return v == null ? '—' : '$' + Math.round(v).toLocaleString(); }
  function num(v) { return v == null ? '—' : String(v); }

  var COLS = [
    { k: 'creative', label: 'Creative', txt: true },
    { k: 'verdict', label: 'Verdict', txt: true },
    { k: 'leads', label: 'Leads' },
    { k: 'qualified', label: 'Qualified' },
    { k: 'sets', label: 'Sets' },
    { k: 'shows', label: 'Shows' },
    { k: 'closes', label: 'Closes' },
    { k: 'cash', label: 'Cash', money: true },
    { k: 'spend', label: 'Spend', money: true },
    { k: 'cost_per_lead', label: 'CPL', money: true },
    { k: 'cost_per_qualified', label: 'C/Qual', money: true },
    { k: 'cost_per_set', label: 'C/Set', money: true },
    { k: 'cost_per_close', label: 'C/Close (ad)', money: true },
    { k: 'cost_per_close_loaded', label: 'C/Close (loaded)', money: true },
    { k: 'ltgp_cac', label: 'LTGP:CAC' },
  ];

  function badge(row) {
    var v = row.verdict;
    var n = row.n || {};
    if (v === 'DOUBLE DOWN') return '<span class="adv-badge adv-dd" title="' + esc(row.verdict_driver || '') + '">DOUBLE DOWN</span>';
    if (v === 'KILL') return '<span class="adv-badge adv-kill" title="' + esc(row.verdict_driver || '') + '">KILL</span>';
    if (v === 'WATCH') return '<span class="adv-badge adv-watch" title="' + esc(row.verdict_driver || '') + '">WATCH <span class="adv-n">n=' + (n.leads || 0) + '/' + (n.closes || 0) + '</span></span>';
    return '<span class="adv-badge adv-none">—</span>';
  }

  function sortRows(rows) {
    var k = state.sort, dir = state.sortDir;
    return rows.slice().sort(function (a, b) {
      // honest rows (channel tiers) pin to the bottom regardless of sort
      var at = a.tier !== 'ad' ? 1 : 0, bt = b.tier !== 'ad' ? 1 : 0;
      if (at !== bt) return at - bt;
      var av = a[k], bv = b[k];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av < bv ? dir : av > bv ? -dir : 0;
    });
  }

  function renderScoreboard() {
    var sb = state.scoreboard;
    if (!sb) return;
    var thead = $('#adtrack-scoreboard thead');
    var tbody = $('#adtrack-scoreboard tbody');
    thead.innerHTML = '<tr>' + COLS.map(function (c) {
      var cls = c.k === state.sort ? (state.sortDir === -1 ? 'sorted desc' : 'sorted asc') : '';
      return '<th data-sort="' + c.k + '" class="' + cls + '">' + c.label + '</th>';
    }).join('') + '</tr>';

    var rows = sb.rows.filter(function (r) {
      if (r.tier !== 'ad') return true;                       // honest rows always
      if (state.verdict && r.verdict !== state.verdict) return false;
      if (!(r.spend || r.leads || r.closes)) return false;    // zero rows collapse
      return true;
    });
    rows = sortRows(rows);
    tbody.innerHTML = rows.map(function (r) {
      var name = r.tier === 'ad' ? esc(r.creative)
        : '<em>' + esc(r.creative) + '</em>';
      var cls = 'adv-tier-' + r.tier + (state.creative === r.creative_key ? ' adv-selected' : '');
      return '<tr class="' + cls + '" data-key="' + esc(r.creative_key) + '" data-tier="' + r.tier + '">' +
        '<td class="adv-name">' + name + '</td>' +
        '<td>' + (r.tier === 'ad' ? badge(r) : '—') + '</td>' +
        COLS.slice(2).map(function (c) {
          var v = r[c.k];
          return '<td>' + (c.money ? money(v) : num(v)) + '</td>';
        }).join('') + '</tr>';
    }).join('');

    var b = sb.banner || {};
    var fresh = (b.freshness || {});
    var qr = sb.qualified_rule || {};
    $('#adtrack-banner').innerHTML =
      '<strong>' + (b.attribution_rate_pct != null ? b.attribution_rate_pct + '%' : '—') +
      '</strong> of window leads ad-attributed (' + (b.attributed_leads || 0) + '/' + (b.leads || 0) + ')' +
      ' · qualified = ≠DQ + revenue ≥ $' + Math.round((qr.floor_monthly || 20000) / 1000) + 'k/mo + form answered' +
      ' · contacts synced ' + esc(String(fresh.contacts_synced || '').slice(11, 16) || '—') +
      ' · spend: ' + esc(fresh.spend_source || '—');
    var cl = $('#adtrack-constraint');
    if (sb.constraint_line) { cl.textContent = sb.constraint_line; cl.style.display = ''; }
    else { cl.style.display = 'none'; }
  }

  function rowMatches(r) {
    if (state.creative && r.creative.key !== state.creative) return false;
    if (state.q) {
      var q = state.q.toLowerCase();
      if ((r.name || '').toLowerCase().indexOf(q) < 0 &&
          (r.business || '').toLowerCase().indexOf(q) < 0) return false;
    }
    return true;
  }

  function renderRows(reset) {
    var thead = $('#adtrack-rows thead');
    var tbody = $('#adtrack-rows tbody');
    thead.innerHTML = '<tr><th>Lead</th><th>Business</th><th>In</th><th>Revenue</th>' +
      '<th>Setter</th><th>Set</th><th>Show</th><th>Close</th><th>Cash</th><th>Creative</th></tr>';
    var rows = state.rows.filter(rowMatches);
    if (reset) state.shown = 0;
    state.shown = Math.min(rows.length, state.shown + PAGE);
    tbody.innerHTML = rows.slice(0, state.shown).map(function (r) {
      var h = r.highlights || {};
      var cls = ['adv-row'];
      if (h.close) cls.push('adv-row-close');
      if (h.threshold_met === true) cls.push('adv-row-met');
      if (h.revenue_unknown) cls.push('adv-row-unknown');
      cls.push('adv-tint-' + (r.creative.tier || 'unattributed'));
      var rev = r.revenue || {};
      var revCell = rev.state === 'unknown'
        ? '<span class="adv-rev-unknown">revenue?</span>'
        : esc(rev.band || '—') + (rev.source === 'ghl_form' ? '<span class="adv-rev-src" title="from the GHL form answer">ᵍ</span>' : '');
      return '<tr class="' + cls.join(' ') + '">' +
        '<td class="adv-name">' + esc(r.name) + (r.qualified ? ' <span class="adv-q" title="qualified">Q</span>' : '') + '</td>' +
        '<td>' + esc(r.business || '') + '</td>' +
        '<td>' + esc(r.input_date) + '</td>' +
        '<td>' + revCell + '</td>' +
        '<td>' + esc(r.setter_outcome || '—') + '</td>' +
        '<td>' + esc(r.set_date || '—') + '</td>' +
        '<td>' + (r.show ? '✓' : '—') + '</td>' +
        '<td>' + (r.close_date ? esc(r.close_date) : '—') + '</td>' +
        '<td class="adv-cash">' + (r.cash != null ? money(r.cash) : '—') + '</td>' +
        '<td class="adv-cr">' + esc((r.creative.label || '').slice(0, 42)) + '</td>' +
        '</tr>';
    }).join('');
    var more = $('#adtrack-more');
    more.style.display = state.shown < rows.length ? '' : 'none';
    more.textContent = 'show more rows (' + (rows.length - state.shown) + ' remaining)';
    $('#adtrack-rows-title').textContent = 'Live tracker — ' + rows.length + ' row(s)' +
      (state.creative ? ' · filtered to a creative' : '') +
      (state.q ? ' · search “' + state.q + '”' : '');
  }

  function renderDrill() {
    var box = $('#adtrack-drill');
    if (!state.creative || !state.scoreboard) { box.style.display = 'none'; return; }
    var r = null;
    state.scoreboard.rows.forEach(function (x) { if (x.creative_key === state.creative) r = x; });
    if (!r) { box.style.display = 'none'; return; }
    box.style.display = '';
    box.innerHTML =
      '<div class="adv-drill-head"><strong>' + esc(r.creative) + '</strong> ' +
      (r.tier === 'ad' ? badge(r) : '') +
      '<button class="adv-drill-close" id="adtrack-drill-close">✕ clear</button></div>' +
      '<div class="adv-drill-line">' + r.leads + ' leads → ' + r.qualified + ' qualified → ' +
      r.sets + ' sets → ' + r.shows + ' shows → ' + r.closes + ' closes · ' +
      money(r.cash) + ' cash on ' + money(r.spend) + ' spend' +
      (r.ltgp_cac != null ? ' · LTGP:CAC ' + r.ltgp_cac + 'x' : '') + '</div>' +
      (r.verdict_driver ? '<div class="adv-drill-driver">' + esc(r.verdict_driver) + '</div>' : '');
    var btn = $('#adtrack-drill-close');
    if (btn) btn.onclick = function () { setCreative(null); };
  }

  function fetchAll() {
    if (state.loading) return Promise.resolve();
    state.loading = true;
    $('#adtrack-banner').textContent = 'Loading ' + state.days + 'd window…';
    var qs = '?days=' + state.days;
    return Promise.all([
      fetch('/cfo/attribution/scoreboard' + qs, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }),
      fetch('/cfo/attribution/rows' + qs, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }),
    ]).then(function (res) {
      state.loading = false;
      if (!res[0] || !res[1]) {
        $('#adtrack-banner').textContent = 'Attribution engine unreachable — the section stays honest and shows nothing rather than stale guesses.';
        return;
      }
      state.scoreboard = res[0];
      state.rows = res[1].rows || [];
      renderScoreboard(); renderDrill(); renderRows(true);
    }).catch(function () {
      state.loading = false;
      $('#adtrack-banner').textContent = 'Attribution fetch failed — retry with the window buttons.';
    });
  }

  function setWindow(days) {
    if ([30, 60, 90].indexOf(days) < 0) return;
    state.days = days;
    document.querySelectorAll('.adtrack-win').forEach(function (b) {
      b.classList.toggle('active', +b.dataset.days === days);
    });
    fetchAll();
    flash();
  }
  function setCreative(key) {
    state.creative = key || null;
    renderScoreboard(); renderDrill(); renderRows(true);
    flash();
  }
  function setVerdict(v) { state.verdict = v || null; renderScoreboard(); flash(); }
  function setSort(k) {
    if (state.sort === k) state.sortDir = -state.sortDir; else { state.sort = k; state.sortDir = -1; }
    renderScoreboard();
  }
  function flash() {
    var el = $('#section-ad-tracking');
    if (!el) return;
    el.classList.add('adv-flash');
    setTimeout(function () { el.classList.remove('adv-flash'); }, 900);
  }

  function init() {
    var sec = $('#section-ad-tracking');
    if (!sec) return;
    document.querySelectorAll('.adtrack-win').forEach(function (b) {
      b.addEventListener('click', function () { setWindow(+b.dataset.days); });
    });
    $('#adtrack-scoreboard').addEventListener('click', function (e) {
      var th = e.target.closest('th[data-sort]');
      if (th) { setSort(th.dataset.sort); return; }
      var tr = e.target.closest('tr[data-key]');
      if (tr && tr.dataset.tier === 'ad') {
        setCreative(state.creative === tr.dataset.key ? null : tr.dataset.key);
      }
    });
    var search = $('#adtrack-search');
    var deb = null;
    search.addEventListener('input', function () {
      clearTimeout(deb);
      deb = setTimeout(function () { state.q = search.value.trim(); renderRows(true); }, 200);
    });
    $('#adtrack-more').addEventListener('click', function () { renderRows(false); });
    fetchAll();
  }

  window.AdTrack = {
    setWindow: setWindow, setCreative: setCreative, setVerdict: setVerdict,
    setSort: function (k) { state.sort = k; state.sortDir = -1; renderScoreboard(); flash(); },
    state: function () { return { days: state.days, creative: state.creative, verdict: state.verdict }; },
    refresh: fetchAll,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
