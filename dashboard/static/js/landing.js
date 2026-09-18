/* landing.js — ENHANCEMENT ONLY (dashboard hardening).
   The landing page's values are SERVER-RENDERED into the HTML before this
   file ever runs. This script adds: the show-your-work drawer modal, the
   refresh button (a reload — values re-render server-side), and the
   briefing-PDF button. If this file never executes, the page still reads
   correctly — that is the design, not a fallback. Every handler is guarded;
   a failure here can never blank a tile. */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function $(id) { return document.getElementById(id); }

  // ── show-your-work drawer ──────────────────────────────────────────────
  async function openDrawer(tile) {
    var overlay = $('fin-drawer-overlay'), box = $('fin-drawer'),
        body = $('fin-drawer-body'), title = $('fin-drawer-title');
    if (!overlay || !box || !body) return;
    overlay.style.display = ''; box.style.display = '';
    title.textContent = tile + ' — show your work';
    body.innerHTML = 'loading the work…';
    try {
      var r = await fetch('/dashboard/api/drawer/' + encodeURIComponent(tile));
      var d = r.ok ? await r.json() : { error: 'drawer fetch failed (' + r.status + ')' };
      if (d.error) { body.innerHTML = '<b>drawer unavailable:</b> ' + esc(d.error); return; }
      var comps = (d.components || []).map(function (c) {
        var v = c.value != null
          ? (typeof c.value === 'number' ? '$' + Math.round(c.value).toLocaleString() : esc(String(c.value)))
          : '—';
        return '<tr><td>' + esc(c.label) + '</td><td style="text-align:right">' + v +
               '</td><td style="opacity:.7;font-size:11px">' + esc(c.source || '') + '</td></tr>';
      }).join('');
      var recon = d.reconciliation
        ? '<div class="fd-sec">Reconciliation</div><div>' + esc(d.reconciliation.external || '') +
          (d.reconciliation.delta != null ? ' · delta $' + Number(d.reconciliation.delta).toLocaleString() : '') +
          '<div style="opacity:.75">' + esc(d.reconciliation.explained || d.reconciliation.delta_note || d.reconciliation.note || '') + '</div></div>'
        : '';
      var inv = d.invariant
        ? '<div style="font-size:11px;opacity:.85;margin-top:6px">invariant: ' +
          (d.invariant.ok ? '✓ components sum to the tile' : '⚠ MISMATCH — do not trust the tile') + '</div>'
        : '';
      var degraded = d.degraded
        ? '<div style="color:var(--amber);margin-top:6px">⚠ ' + esc(String(d.degraded)) + '</div>' : '';
      body.innerHTML =
        '<div class="fd-def"><b>' + esc(d.tile || tile) + '</b>' +
        (d.value != null ? ' · $' + Math.round(d.value).toLocaleString() : '') + '<br>' +
        esc(d.definition || '') + '</div>' +
        '<div style="font-size:11px;opacity:.7">FORMULA: ' + esc(d.formula || '') +
        ' · CLOCK: ' + esc(d.clock || '') + '</div>' +
        '<table style="margin-top:8px">' + comps + '</table>' + inv + recon + degraded;
    } catch (e) {
      body.innerHTML = 'drawer failed: ' + esc(String(e));
    }
  }
  function closeDrawer() {
    var overlay = $('fin-drawer-overlay'), box = $('fin-drawer');
    if (overlay) overlay.style.display = 'none';
    if (box) box.style.display = 'none';
  }
  document.addEventListener('click', function (e) {
    try {
      var b = e.target.closest('.fin-door[data-findrawer]');
      if (b) { e.preventDefault(); openDrawer(b.dataset.findrawer); return; }
      if (e.target.id === 'fin-drawer-close' || e.target.id === 'fin-drawer-overlay') closeDrawer();
    } catch (err) { /* enhancement lane — never break the page */ }
  });

  // ── header buttons ─────────────────────────────────────────────────────
  var refresh = $('btn-refresh');
  if (refresh) refresh.addEventListener('click', function () {
    refresh.disabled = true;
    location.reload();   // values are server-rendered at request time
  });
  var pdf = $('btn-briefing-pdf');
  if (pdf) pdf.addEventListener('click', function () {
    try { window.open('/dashboard/api/briefing-pdf', '_blank'); } catch (e) {}
  });
})();
