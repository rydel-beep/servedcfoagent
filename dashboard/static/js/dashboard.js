/* dashboard.js v2 — Data fetching, rendering, auto-refresh */
(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  let currentSnap = null;
  let refreshCooldown = false;

  // ── Helpers ──────────────────────────────────────────────
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
    const mins = Math.round((Date.now() - new Date(iso)) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    return Math.round(mins / 60) + 'h ago';
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  // ── Fetch ────────────────────────────────────────────────
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

  // ── Render ───────────────────────────────────────────────
  function render(snap) {
    if (!snap) return;
    currentSnap = snap;

    renderStatus(snap);
    renderKPIs(snap);
    renderClientHealth(snap);
    renderVerdicts(snap);
    renderFunnel(snap);
    renderOfferChart(snap);
    renderMetrics(snap);
    renderSetters(snap);
    renderClosers(snap);
    renderQuality(snap);

    if (snap.generated_at) {
      $('#chat-context').textContent = timeAgo(snap.generated_at);
    }
  }

  // ── Status bar ───────────────────────────────────────────
  function renderStatus(snap) {
    const genAt = snap.generated_at;
    const mins = genAt ? Math.round((Date.now() - new Date(genAt)) / 60000) : 999;
    const dot = $('#status-dot');
    const txt = $('#status-text');
    if (mins > 120) {
      dot.className = 'status-dot stale';
      txt.textContent = timeAgo(genAt);
    } else {
      dot.className = 'status-dot';
      txt.textContent = timeAgo(genAt);
    }
  }

  // ── KPI Strip ────────────────────────────────────────────
  function renderKPIs(snap) {
    const h = snap.hormozi || {};
    const ch = snap.client_health || {};

    // Sheet MRR
    const sheetMrr = ch.current_mrr;
    setKPI('val-sheet-mrr', fmt$(sheetMrr));
    const delta = ch.mrr_delta;
    if (delta != null && delta !== 0) {
      const dir = delta > 0 ? '+' : '';
      $('#sub-sheet-mrr').textContent = dir + fmt$(delta) + ' next month';
      $('#sub-sheet-mrr').style.color = delta >= 0 ? 'var(--green)' : 'var(--red)';
    } else {
      $('#sub-sheet-mrr').textContent = ch.current_month || '';
    }

    // Stripe MRR
    setKPI('val-stripe-mrr', fmt$(get(snap, 'stripe.mrr')));
    $('#sub-stripe-mrr').textContent = 'recurring';

    // Cash
    setKPI('val-cash', fmt$(get(snap, 'sheets.cash_collected')));

    // Gross Margin
    const margin = get(h, 'gross_margin.value');
    const marginEl = document.getElementById('val-margin');
    setKPI('val-margin', fmtPct(margin), statusClass(get(h, 'gross_margin.status')));
    $('#sub-margin').textContent = margin != null ? 'benchmark: 45%' : '';

    // Op Efficiency
    const opeff = get(h, 'op_efficiency.value');
    setKPI('val-opeff', fmtX(opeff), statusClass(get(h, 'op_efficiency.status')));
    $('#sub-opeff').textContent = opeff != null ? 'target: 1.5\u00d7' : '';

    // Active Clients
    const total = ch.total_clients;
    setKPI('val-clients', total != null ? total : '—');
    if (ch.active_count != null) {
      const parts = [];
      if (ch.active_count) parts.push(ch.active_count + ' active');
      if (ch.web_sub_count) parts.push(ch.web_sub_count + ' web');
      $('#sub-clients').textContent = parts.join(', ');
    }
  }

  function setKPI(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'kpi-value' + (cls ? ' ' + cls : '');
  }

  // ── Client Health ────────────────────────────────────────
  function renderClientHealth(snap) {
    const ch = snap.client_health;
    const summary = $('#health-summary');
    const list = $('#client-list');
    const badge = $('#health-badge');

    if (!ch || !ch.clients) {
      summary.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No client health data</div>';
      list.innerHTML = '';
      return;
    }

    // Badge
    badge.textContent = ch.total_clients + ' clients';
    badge.style.background = 'var(--green-dim)';
    badge.style.color = 'var(--green)';

    // Summary stats
    summary.innerHTML = `
      <div class="health-stat">
        <div class="health-stat-value" style="color:var(--text)">${fmt$(ch.current_mrr)}</div>
        <div class="health-stat-label">This month</div>
      </div>
      <div class="health-stat">
        <div class="health-stat-value" style="color:${ch.mrr_delta >= 0 ? 'var(--green)' : 'var(--red)'}">${fmt$(ch.next_mrr)}</div>
        <div class="health-stat-label">Next month</div>
      </div>
      <div class="health-stat">
        <div class="health-stat-value" style="color:${ch.mrr_delta >= 0 ? 'var(--green)' : 'var(--red)'}">${ch.mrr_delta >= 0 ? '+' : ''}${fmt$(ch.mrr_delta)}</div>
        <div class="health-stat-label">MRR delta</div>
      </div>
    `;

    // Client rows — sorted by current_mrr descending
    const sorted = [...ch.clients].sort((a, b) => (b.current_mrr || 0) - (a.current_mrr || 0));
    list.innerHTML = '';
    sorted.forEach(c => {
      const row = document.createElement('div');
      row.className = 'client-row';

      const badgeCls = c.status === 'Active' ? 'active' : 'websub';
      const delta = (c.next_mrr || 0) - (c.current_mrr || 0);
      let deltaHtml = '';
      if (delta > 0) deltaHtml = `<span class="client-delta up">+${fmt$(delta)}</span>`;
      else if (delta < 0) deltaHtml = `<span class="client-delta down">${fmt$(delta)}</span>`;

      row.innerHTML = `
        <span class="client-name">${esc(c.name)}</span>
        <span class="client-badge ${badgeCls}">${c.status === 'Active' ? 'Active' : 'Web'}</span>
        <span class="client-mrr">${fmt$(c.current_mrr)}</span>
        ${deltaHtml}
      `;
      list.appendChild(row);
    });
  }

  // ── Verdicts ─────────────────────────────────────────────
  function renderVerdicts(snap) {
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
      chip.textContent = w.name.replace('Hormozi ', '') + (w.value ? ': ' + w.value : '');
      winsRow.appendChild(chip);
    });
  }

  // ── Funnel ───────────────────────────────────────────────
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
    stages.forEach((s, i) => {
      const pctWidth = Math.max(((s.count || 0) / maxCount) * 100, 3);
      const row = document.createElement('div');
      row.className = 'funnel-row';
      const isCloses = i === 3;
      row.innerHTML = `
        <div class="funnel-label">${s.label}</div>
        <div class="funnel-bar-bg">
          <div class="funnel-bar-fill${isCloses ? ' closes' : ''}" style="width:${pctWidth}%"></div>
          <div class="funnel-num">${s.count ?? '—'}</div>
        </div>
        <div class="funnel-pct">${s.pct != null ? s.pct + '%' : ''}</div>
      `;
      container.appendChild(row);
    });

    // Stats row
    const stats = $('#funnel-stats');
    const parts = [];
    if (f.lead_to_close_pct != null) parts.push(`<span class="funnel-stat">Lead-to-close: <strong>${f.lead_to_close_pct}%</strong></span>`);
    if (f.closes != null && f.leads_in) parts.push(`<span class="funnel-stat">${f.closes}/${f.leads_in} converted</span>`);
    stats.innerHTML = parts.join('');
  }

  // ── Offer Mix Chart ──────────────────────────────────────
  let offersChart = null;

  function renderOfferChart(snap) {
    const offers = get(snap, 'sales.deep.money.offer_mix') || [];
    const ctx = document.getElementById('chart-offers');
    if (offersChart) offersChart.destroy();

    if (offers.length === 0) {
      ctx.parentElement.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:40px 0;text-align:center;">No offer data</div>';
      return;
    }

    const colors = [
      'rgba(59,130,246,0.7)',
      'rgba(34,197,94,0.7)',
      'rgba(245,158,11,0.7)',
      'rgba(239,68,68,0.7)',
      'rgba(168,85,247,0.7)',
      'rgba(236,72,153,0.7)',
    ];

    offersChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: offers.map(o => o.offer),
        datasets: [{
          data: offers.map(o => o.count),
          backgroundColor: offers.map((_, i) => colors[i % colors.length]),
          borderWidth: 0,
          spacing: 2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
          legend: {
            position: 'right',
            labels: {
              color: 'rgba(148,163,184,0.8)',
              font: { size: 11 },
              padding: 10,
              usePointStyle: true,
              pointStyleWidth: 8,
            }
          }
        }
      }
    });
  }

  // ── Metrics ──────────────────────────────────────────────
  function renderMetrics(snap) {
    const h = snap.hormozi || {};

    setMetric('val-revenue', fmt$(get(snap, 'xero.revenue')));
    setMetric('val-netprofit', fmt$(get(snap, 'xero.net_profit')),
      get(snap, 'xero.net_profit') > 0 ? 'healthy' : get(snap, 'xero.net_profit') < 0 ? 'critical' : '');

    const payback = get(h, 'payback_days.value');
    setMetric('val-payback', fmtDays(payback), statusClass(get(h, 'payback_days.status')));

    const ltgp = get(h, 'ltgp_cac.value');
    setMetric('val-ltgpcac', fmtX(ltgp), statusClass(get(h, 'ltgp_cac.status')));

    const velocity = get(h, 'sales_velocity.value');
    setMetric('val-velocity', velocity != null ? '$' + Math.round(velocity) + '/day' : '—');

    const cac = get(h, 'cac_loaded.value');
    setMetric('val-cac', fmt$(cac), statusClass(get(h, 'cac_loaded.status')));
  }

  function setMetric(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'metric-value' + (cls ? ' ' + cls : '');
  }

  // ── Tables ───────────────────────────────────────────────
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
        <td>${s.show_pct != null ? s.show_pct + '%' : '—'}</td>
      `;
      tbody.appendChild(tr);
    });
    if (setters.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted)">No setter data</td></tr>';
    }
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
    if (closers.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted)">No closer data</td></tr>';
    }
  }

  // ── Data Quality ─────────────────────────────────────────
  function renderQuality(snap) {
    const degraded = snap.degraded || [];
    const list = $('#degraded-list');
    list.innerHTML = '';
    if (degraded.length === 0) {
      list.innerHTML = '<div style="font-size:12px;color:var(--green);">All sources healthy</div>';
    } else {
      degraded.forEach(d => {
        const div = document.createElement('div');
        div.className = 'degraded-item';
        div.textContent = (d.metric || d.source || '?') + ': ' + d.reason;
        list.appendChild(div);
      });
    }
    $('#quality-meta').innerHTML = `
      <div class="quality-meta">
        Last refresh: ${snap.generated_at || '—'}<br>
        Status: ${snap.ok ? 'All sources OK' : degraded.length + ' degraded source(s)'}
      </div>
    `;
  }

  // ── Refresh ──────────────────────────────────────────────
  $('#btn-refresh').addEventListener('click', async function() {
    if (refreshCooldown) return;
    const btn = this;
    btn.disabled = true;
    btn.classList.add('loading');
    refreshCooldown = true;
    try {
      const resp = await fetch('/dashboard/api/refresh', { method: 'POST' });
      if (resp.ok) {
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

  // ── Collapsible ──────────────────────────────────────────
  $('#toggle-quality').addEventListener('click', function() {
    const body = $('#quality-body');
    const icon = $('#collapse-icon');
    if (body.style.display === 'none') {
      body.style.display = 'block';
      icon.textContent = '\u2212';
    } else {
      body.style.display = 'none';
      icon.textContent = '+';
    }
  });

  // ── Init ─────────────────────────────────────────────────
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
