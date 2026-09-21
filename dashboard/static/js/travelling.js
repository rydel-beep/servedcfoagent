/* travelling.js — the view's small enhancement lane.
   The whole comparison is SERVER-RENDERED; this file only opens the roster
   drawers and runs the two actions. Every handler guarded — a failure here
   can never blank a number. Nothing here writes to any source of truth. */
(function () {
  'use strict';
  var DATA = window.__TRAVELLING__ || {};
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function $(id) { return document.getElementById(id); }
  function guard(name, fn) {
    try { return fn(); } catch (e) {
      console.error('[travelling]', name, e);
      try { window.__reportClientError && window.__reportClientError({
        kind: 'panel_boundary', detail: 'travelling:' + name + ': ' + String(e && e.message || e).slice(0, 250) }); } catch (t) {}
    }
  }

  // ── the people behind a number ──
  function openRoster(stageId) {
    var box = $('tv-roster'), body = $('tv-roster-body'), ov = $('tv-roster-overlay');
    if (!box || !body) return;
    var block = DATA[stageId] || {};
    var groups = [['', block.roster || []]];
    Object.keys(block.extra || {}).forEach(function (k) {
      groups.push([k, block.extra[k] || []]);
    });
    $('tv-roster-title').textContent = (block.name || stageId) + ' — the people';
    var html = '';
    groups.forEach(function (g) {
      var rows = g[1];
      if (!rows.length) return;
      if (g[0]) html += '<div class="fd-sec">' + esc(g[0]) + '</div>';
      html += '<table class="tv-roster-table">';
      rows.forEach(function (r) {
        var cells = Object.keys(r).filter(function (k) {
          return k !== 'contact_id' && r[k] !== null && r[k] !== '';
        });
        html += '<tr><td>' + esc(r.person || r.client || '—') + '</td><td>' +
          cells.filter(function (k) { return k !== 'person'; }).map(function (k) {
            return '<span style="opacity:.75">' + esc(k.replace(/_/g, ' ')) + ':</span> ' + esc(r[k]);
          }).join(' · ') + '</td></tr>';
      });
      html += '</table>';
    });
    if (!html) html = '<p>No one is at this stage in this window yet.</p>';
    if (block.note) html += '<p class="tv-note">' + esc(block.note) + '</p>';
    body.innerHTML = html;
    box.style.display = ''; ov.style.display = '';
  }
  function closeRoster() {
    var box = $('tv-roster'), ov = $('tv-roster-overlay');
    if (box) box.style.display = 'none';
    if (ov) ov.style.display = 'none';
  }

  document.addEventListener('click', function (e) {
    var d = e.target.closest && e.target.closest('.tv-door');
    if (d && !d.disabled) { guard('roster', function () { openRoster(d.dataset.roster); }); return; }
    if (e.target.id === 'tv-roster-close' || e.target.id === 'tv-roster-overlay') closeRoster();
    if (e.target.id === 'tv-remodel') guard('remodel', remodel);
    if (e.target.id === 'tv-save') guard('save', saveCheck);
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeRoster(); });

  // ── actions ──
  function params() {
    var u = new URLSearchParams(location.search);
    return { window: u.get('window') || 'mtd', compare: u.get('compare') || 'scenario',
             start: u.get('start'), end: u.get('end'), s: u.get('s') };
  }
  async function remodel() {
    var out = $('tv-action-out');
    out.textContent = 'reading this window’s rates…';
    var p = params();
    var r = await fetch('/dashboard/api/travelling/remodel?window=' + encodeURIComponent(p.window) +
      (p.start ? '&start=' + p.start + '&end=' + p.end : ''));
    if (!r.ok) { out.textContent = 'could not read the rates (' + r.status + ')'; return; }
    var d = await r.json();
    try { sessionStorage.setItem('scale-remodel', JSON.stringify(d)); } catch (e) {}
    var bits = Object.keys(d.inputs || {}).map(function (k) {
      var pretty = { cpl0: 'cost per lead', set_rate: 'booking rate',
                     show_rate: 'turn-up rate', close_rate: 'close rate' }[k] || k;
      var v = d.inputs[k];
      return pretty + ' ' + (k === 'cpl0' ? '$' + Number(v).toFixed(2) : (v * 100).toFixed(1) + '%') +
        (d.confidence && d.confidence[k] ? ' (' + d.confidence[k] + ')' : '');
    });
    out.innerHTML = 'Loaded into the compass — ' + esc(bits.join(', ')) +
      '. <a href="/dashboard/scale?remodel=1">Open the compass</a> to see where the month lands ' +
      '<span style="opacity:.7">(' + esc(d.label) + ')</span>';
  }
  async function saveCheck() {
    var out = $('tv-action-out');
    out.textContent = 'saving…';
    var p = params();
    var r = await fetch('/dashboard/api/travelling/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ window: p.window, compare: p.compare, s: p.s }) });
    var d = await r.json();
    out.textContent = d.error ? d.error :
      'Saved. This check is now in the history below (refresh to see it).';
  }
})();
