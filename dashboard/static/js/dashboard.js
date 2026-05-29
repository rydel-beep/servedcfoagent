/* dashboard.js — Data fetching, rendering, auto-refresh */
(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  let currentSnap = null;
  let refreshCooldown = false;

  // ── Helpers ──────────────────────────────────────────────────────
  function fmt$(v) {
    if (v == null) return '—';
    const n = Number(v);
    if (isNaN(n)) return '—';
    if (Math.abs(n) >= 1000) return '$' + n.toLocaleString('en-AU', {maximumFractionDigits: 0});
    return '$' + n.toLocaleString('en-AU', {maximumFractionDigits: 2});
  }
  function fmtPct(v) { return v != null ? v + '%' : '—'; }
  function fmtX(v) { return v != null ? v + '\u00d7' : '—'; }
  function fmtDays(v) { return v != null ? Math.round(v) + 'd' : '—'; }

  function statusClass(status) {
    if (status === 'healthy') return 'healthy';
    if (status === 'watch') return 'watch';
    if (status === 'critical') return 'critical';
    return '';
  }

  function get(obj, path) {
    for (const p of path.split('.')) {
      if (!obj || typeof obj !== 'object') return null;
      obj = obj[p];
    }
    return obj ?? null;
  }

  function timeAgo(iso) {
    if (!iso) return 'unknown';
    const then = new Date(iso);
    const mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.round(mins / 60);
    return hrs + 'h ago';
  }

  // ── Fetch & Render ──────────────────────────────────────────────
  async function fetchSnapshot() {
    try {
      const resp = await fetch('/dashboard/api/snapshot');
      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) {
      console.error('Fetch failed:', e);
      return null;
    }
  }

  function render(snap) {
    if (!snap) return;
    currentSnap = snap;

    // Status
    const genAt = snap.generated_at;
    const mins = genAt ? Math.round((Date.now() - new Date(genAt)) / 60000) : 999;
    const dot = $('#status-dot');
    const txt = $('#status-text');
    if (mins > 120) {
      dot.className = 'status-dot stale';
      txt.textContent = 'Snapshot ' + timeAgo(genAt);
    } else {
      dot.className = 'status-dot';
      txt.textContent = 'Fresh as of ' + timeAgo(genAt);
    }

    // Money section
    const h = snap.hormozi || {};
    setVal('val-mrr', fmt$(get(snap, 'stripe.mrr')));
    setVal('val-cash', fmt$(get(snap, 'sheets.cash_collected')));

    const margin = get(h, 'gross_margin.value');
    setVal('val-margin', fmtPct(margin), statusClass(get(h, 'gross_margin.status')));

    const opeff = get(h, 'op_efficiency.value');
    setVal('val-opeff', fmtX(opeff), statusClass(get(h, 'op_efficiency.status')));

    setVal('val-revenue', fmt$(get(snap, 'xero.revenue')));
    setVal('val-netprofit', fmt$(get(snap, 'xero.net_profit')));

    const payback = get(h, 'payback_days.value');
    setVal('val-payback', fmtDays(payback), statusClass(get(h, 'payback_days.status')));

    const ltgp = get(h, 'ltgp_cac.value');
    setVal('val-ltgpcac', fmtX(ltgp), statusClass(get(h, 'ltgp_cac.status')));

    // Verdicts
    const v = snap.verdicts || {};
    $('#verdict-headline').textContent = v.headline || 'No verdict data';

    const leaksList = $('#leaks-list');
    leaksList.innerHTML = '';
    (v.top_leaks || []).forEach(l => {
      const card = document.createElement('div');
      card.className = 'leak-card';
      card.innerHTML = `
        <div class="leak-rank">#${l.rank}</div>
        <div class="leak-body">
          <div class="leak-name">${esc(l.name)}</div>
          <div class="leak-read">${esc(l.read)}</div>
          <div class="leak-bench">${esc(l.current)} vs ${esc(l.benchmark)}</div>
        </div>
        <div class="leak-impact">${fmt$(l.dollar_impact_monthly)}/mo</div>
      `;
      leaksList.appendChild(card);
    });

    const winsRow = $('#wins-row');
    winsRow.innerHTML = '';
    (v.wins || []).forEach(w => {
      const chip = document.createElement('span');
      chip.className = 'win-chip';
      chip.textContent = w.name.replace('Hormozi ', '') + ': ' + (w.value || '');
      winsRow.appendChild(chip);
    });

    // Funnel
    renderFunnel(snap);

    // Tables
    renderSetters(snap);
    renderClosers(snap);

    // Charts
    renderCharts(snap);

    // Data quality
    renderQuality(snap);

    // Chat context
    if (genAt) {
      $('#chat-context').textContent = 'Snapshot: ' + timeAgo(genAt);
    }
  }

  function setVal(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'card-value' + (cls ? ' ' + cls : '');
  }

  function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  // ── Funnel ──────────────────────────────────────────────────────
  function renderFunnel(snap) {
    const f = get(snap, 'sales.funnel') || {};
    const stages = [
      { label: 'Leads', count: f.leads_in, pct: null },
      { label: 'Sets', count: f.sets, pct: f.lead_to_set_pct },
      { label: 'Shows', count: f.shows, pct: f.set_to_show_pct },
      { label: 'Closes', count: f.closes, pct: f.show_to_close_pct },
    ];
    const maxCount = Math.max(...stages.map(s => s.count || 0), 1);

    const container = $('#funnel-bars');
    container.innerHTML = '';
    stages.forEach(s => {
      const pctWidth = Math.max(((s.count || 0) / maxCount) * 100, 2);
      const row = document.createElement('div');
      row.className = 'funnel-bar-row';
      row.innerHTML = `
        <div class="funnel-label">${s.label}</div>
        <div class="funnel-bar-wrap">
          <div class="funnel-bar" style="width: ${pctWidth}%"></div>
          <div class="funnel-count">${s.count ?? '—'}</div>
        </div>
        <div class="funnel-pct">${s.pct != null ? s.pct + '%' : ''}</div>
      `;
      container.appendChild(row);
    });
  }

  // ── Tables ──────────────────────────────────────────────────────
  function renderSetters(snap) {
    const setters = get(snap, 'sales.deep.setter_performance') || get(snap, 'sales.per_setter') || [];
    const tbody = document.querySelector('#table-setters tbody');
    tbody.innerHTML = '';
    setters.forEach(s => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${esc(s.name)}</td>
        <td>${s.dials ?? '—'}</td>
        <td>${s.sets ?? '—'}</td>
        <td>${s.dials_per_set ?? '—'}</td>
        <td>${s.speed_to_lead_pct != null ? s.speed_to_lead_pct + '%' : '—'}</td>
        <td>${s.show_pct != null ? s.show_pct + '%' : '—'}</td>
        <td>${s.close_pct != null ? s.close_pct + '%' : '—'}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function renderClosers(snap) {
    const closers = get(snap, 'sales.per_closer') || [];
    const tbody = document.querySelector('#table-closers tbody');
    tbody.innerHTML = '';
    closers.forEach(c => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${esc(c.name)}</td>
        <td>${c.shows ?? '—'}</td>
        <td>${c.closes ?? '—'}</td>
        <td>${c.close_rate_pct != null ? c.close_rate_pct + '%' : '—'}</td>
        <td>${c.commission_total != null ? fmt$(c.commission_total) : '—'}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // ── Charts ──────────────────────────────────────────────────────
  let funnelChart = null;
  let offersChart = null;

  function renderCharts(snap) {
    const f = get(snap, 'sales.funnel') || {};
    const funnelData = [f.leads_in || 0, f.sets || 0, f.shows || 0, f.closes || 0];

    // Funnel bar chart
    const fCtx = document.getElementById('chart-funnel');
    if (funnelChart) funnelChart.destroy();
    funnelChart = new Chart(fCtx, {
      type: 'bar',
      data: {
        labels: ['Leads', 'Sets', 'Shows', 'Closes'],
        datasets: [{
          data: funnelData,
          backgroundColor: ['rgba(46,110,166,0.6)', 'rgba(46,110,166,0.5)', 'rgba(46,110,166,0.4)', 'rgba(74,222,128,0.6)'],
          borderRadius: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: 'rgba(238,244,250,0.5)', font: { size: 11 } }, grid: { display: false } },
          y: { ticks: { color: 'rgba(238,244,250,0.3)', font: { size: 10 } }, grid: { color: 'rgba(46,110,166,0.1)' } },
        }
      }
    });

    // Offer mix doughnut
    const offers = get(snap, 'sales.deep.money.offer_mix') || [];
    const oCtx = document.getElementById('chart-offers');
    if (offersChart) offersChart.destroy();
    if (offers.length > 0) {
      const colors = ['rgba(46,110,166,0.7)', 'rgba(74,222,128,0.6)', 'rgba(251,191,36,0.6)', 'rgba(248,113,113,0.6)', 'rgba(168,85,247,0.6)'];
      offersChart = new Chart(oCtx, {
        type: 'doughnut',
        data: {
          labels: offers.map(o => o.offer),
          datasets: [{
            data: offers.map(o => o.count),
            backgroundColor: offers.map((_, i) => colors[i % colors.length]),
            borderWidth: 0,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { color: 'rgba(238,244,250,0.6)', font: { size: 11 }, padding: 12 } }
          }
        }
      });
    }
  }

  // ── Data Quality ────────────────────────────────────────────────
  function renderQuality(snap) {
    const degraded = snap.degraded || [];
    const list = $('#degraded-list');
    list.innerHTML = '';
    if (degraded.length === 0) {
      list.innerHTML = '<div style="font-size:12px;color:rgba(74,222,128,0.8);">All sources healthy</div>';
    } else {
      degraded.forEach(d => {
        const div = document.createElement('div');
        div.className = 'degraded-item';
        div.textContent = (d.metric || d.source || '?') + ': ' + d.reason;
        list.appendChild(div);
      });
    }

    const meta = $('#quality-meta');
    meta.innerHTML = `
      <div class="quality-meta">
        Last refresh: ${snap.generated_at || '—'}<br>
        Status: ${snap.ok ? 'All sources OK' : degraded.length + ' degraded source(s)'}
      </div>
    `;
  }

  // ── Refresh Button ──────────────────────────────────────────────
  $('#btn-refresh').addEventListener('click', async function() {
    if (refreshCooldown) return;
    const btn = this;
    btn.disabled = true;
    btn.classList.add('loading');
    refreshCooldown = true;

    try {
      const resp = await fetch('/dashboard/api/refresh', { method: 'POST' });
      if (resp.ok) {
        // Re-fetch snapshot after refresh
        const snap = await fetchSnapshot();
        if (snap) render(snap);
      }
    } catch (e) {
      console.error('Refresh failed:', e);
    } finally {
      btn.classList.remove('loading');
      setTimeout(() => { btn.disabled = false; refreshCooldown = false; }, 10000);
    }
  });

  // ── Collapsible ─────────────────────────────────────────────────
  $('#toggle-quality').addEventListener('click', function() {
    const body = $('#quality-body');
    const icon = this.querySelector('.collapse-icon');
    if (body.style.display === 'none') {
      body.style.display = 'block';
      icon.textContent = '\u2212';
    } else {
      body.style.display = 'none';
      icon.textContent = '+';
    }
  });

  // ── Init ────────────────────────────────────────────────────────
  (async function init() {
    const snap = await fetchSnapshot();
    if (snap) render(snap);
  })();

  // Auto-refresh every 10 minutes
  setInterval(async () => {
    const snap = await fetchSnapshot();
    if (snap) render(snap);
  }, 600000);

})();
