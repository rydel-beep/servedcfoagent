/* dashboard.js v3 — Full dashboard with trend, churn risk, revenue views */
(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  let currentSnap = null;
  let historyData = null;
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

  async function fetchHistory() {
    try {
      const resp = await fetch('/dashboard/api/history?n=14');
      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) {
      console.error('History fetch failed:', e);
      return null;
    }
  }

  // ── Render ───────────────────────────────────────────────
  function render(snap) {
    if (!snap) return;
    currentSnap = snap;

    renderStatus(snap);
    renderKPIs(snap);
    renderMRRTrend(snap);
    renderRevenueViews(snap);
    renderChurnRisk(snap);
    renderClientHealth(snap);
    renderVerdicts(snap);
    renderFunnel(snap);
    renderOfferChart(snap);
    renderLeadSourceROI(snap);
    renderCommissions(snap);
    renderMetrics(snap);
    renderSetters(snap);
    renderClosers(snap);
    renderCohortRetention(snap);
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
    setKPI('val-sheet-mrr', fmt$(ch.current_mrr));
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

  // ── MRR Trend Chart ──────────────────────────────────────
  let trendChart = null;

  function renderMRRTrend(snap) {
    const ch = snap.client_health || {};
    const trend = ch.trend || [];
    const ctx = document.getElementById('chart-mrr-trend');
    if (trendChart) trendChart.destroy();

    if (trend.length === 0) {
      ctx.parentElement.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:40px 0;text-align:center;">No trend data</div>';
      return;
    }

    // Find current month index to split past/future
    const currentMonth = ch.current_month;
    const currentIdx = trend.findIndex(t => t.month === currentMonth);

    // Create gradient for past vs future
    const labels = trend.map(t => t.month);
    const values = trend.map(t => t.mrr);

    // Point styling — highlight current month
    const pointRadius = trend.map((_, i) => i === currentIdx ? 5 : 2);
    const pointBg = trend.map((_, i) => {
      if (i === currentIdx) return '#3B82F6';
      if (i < currentIdx) return 'rgba(59,130,246,0.6)';
      return 'rgba(148,163,184,0.4)';
    });

    trendChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: function(context) {
            const chart = context.chart;
            const {ctx: c, chartArea} = chart;
            if (!chartArea) return '#3B82F6';
            const gradient = c.createLinearGradient(chartArea.left, 0, chartArea.right, 0);
            const splitPct = currentIdx >= 0 ? currentIdx / (trend.length - 1) : 1;
            gradient.addColorStop(0, 'rgba(59,130,246,0.8)');
            gradient.addColorStop(Math.min(splitPct, 0.99), 'rgba(59,130,246,0.8)');
            gradient.addColorStop(Math.min(splitPct + 0.01, 1), 'rgba(148,163,184,0.35)');
            gradient.addColorStop(1, 'rgba(148,163,184,0.35)');
            return gradient;
          },
          borderWidth: 2.5,
          pointRadius: pointRadius,
          pointBackgroundColor: pointBg,
          pointBorderWidth: 0,
          fill: {
            target: 'origin',
            above: function(context) {
              const chart = context.chart;
              const {ctx: c, chartArea} = chart;
              if (!chartArea) return 'rgba(59,130,246,0.05)';
              const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
              gradient.addColorStop(0, 'rgba(59,130,246,0.12)');
              gradient.addColorStop(1, 'rgba(59,130,246,0)');
              return gradient;
            },
          },
          tension: 0.3,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) { return fmt$(ctx.parsed.y); }
            }
          }
        },
        scales: {
          x: {
            ticks: { color: 'rgba(148,163,184,0.5)', font: { size: 10 } },
            grid: { display: false },
          },
          y: {
            ticks: {
              color: 'rgba(148,163,184,0.4)',
              font: { size: 10 },
              callback: function(v) { return '$' + (v/1000).toFixed(0) + 'k'; }
            },
            grid: { color: 'rgba(255,255,255,0.03)' },
          }
        },
        interaction: { intersect: false, mode: 'index' },
      }
    });
  }

  // ── Revenue Views (Cash vs Accrual) ──────────────────────
  function renderRevenueViews(snap) {
    const container = $('#revenue-bars');
    const note = $('#revenue-note');

    const rv = snap.revenue_views || {};
    const stripeCash = rv.stripe_cash_trailing_30d;
    const xeroPL = rv.xero_pl_period;
    const sheetRecognized = rv.recognized_current_month;

    const views = [
      { label: 'Stripe Cash (30d)', value: stripeCash, cls: 'stripe', source: 'Bank' },
      { label: 'Xero P&L', value: xeroPL, cls: 'xero', source: 'Accounting' },
      { label: 'Sheet Recognized', value: sheetRecognized, cls: 'sheet', source: 'Accrual' },
    ].filter(v => v.value != null);

    if (views.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No revenue data</div>';
      note.innerHTML = '';
      return;
    }

    const maxVal = Math.max(...views.map(v => v.value), 1);

    container.innerHTML = views.map(v => {
      const pct = Math.max((v.value / maxVal) * 100, 3);
      return `
        <div class="rev-row">
          <div class="rev-row-header">
            <span class="rev-label">${v.label} <span style="color:var(--text-muted)">(${v.source})</span></span>
            <span class="rev-amount">${fmt$(v.value)}</span>
          </div>
          <div class="rev-bar-bg">
            <div class="rev-bar-fill ${v.cls}" style="width:${pct}%"></div>
          </div>
        </div>
      `;
    }).join('');

    // Reconciliation note
    const parts = [];
    if (stripeCash != null && xeroPL != null) {
      const diff = stripeCash - xeroPL;
      const dir = diff >= 0 ? '+' : '';
      parts.push(`Stripe ${dir}${fmt$(diff)} vs Xero — timing differences expected`);
    }
    if (rv.recognized_month) {
      parts.push(`Recognized: ${rv.recognized_month} (${rv.recognized_client_count || '?'} clients)`);
    }
    note.textContent = parts.join(' · ') || 'Same money, different lenses — never sum these.';
  }

  // ── Churn Risk ────────────────────────────────────────────
  function renderChurnRisk(snap) {
    const ch = snap.client_health || {};
    const atRisk = ch.at_risk || [];
    const badge = $('#churn-badge');
    const summary = $('#churn-summary');
    const list = $('#churn-list');

    if (atRisk.length === 0) {
      badge.textContent = 'Clear';
      badge.style.background = 'var(--green-dim)';
      badge.style.color = 'var(--green)';
      summary.innerHTML = '';
      list.innerHTML = '<div class="churn-empty">No contracts expiring in the next 60 days</div>';
      return;
    }

    // Badge
    badge.textContent = atRisk.length + ' at risk';
    badge.style.background = 'var(--red-dim)';
    badge.style.color = 'var(--red)';

    // Summary
    const risk30 = ch.revenue_at_risk_30d || 0;
    const risk60 = ch.revenue_at_risk_60d || 0;
    summary.innerHTML = `
      <div class="churn-stat">
        <div class="churn-stat-value" style="color:var(--red)">${fmt$(risk30)}</div>
        <div class="churn-stat-label">At risk (30d)</div>
      </div>
      <div class="churn-stat">
        <div class="churn-stat-value" style="color:var(--amber)">${fmt$(risk60)}</div>
        <div class="churn-stat-label">At risk (60d)</div>
      </div>
      <div class="churn-stat">
        <div class="churn-stat-value">${atRisk.length}</div>
        <div class="churn-stat-label">Contracts</div>
      </div>
    `;

    // List
    list.innerHTML = '';
    atRisk.forEach(c => {
      const row = document.createElement('div');
      row.className = 'churn-row ' + c.risk_level;

      let daysText;
      if (c.risk_level === 'expired') {
        daysText = 'Expired';
      } else {
        daysText = c.days_remaining + 'd left';
      }

      row.innerHTML = `
        <span class="churn-client">${esc(c.name)}</span>
        <span class="churn-days ${c.risk_level}">${daysText}</span>
        <span class="churn-revenue">${fmt$(c.monthly_revenue)}/mo</span>
      `;
      list.appendChild(row);
    });
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

    badge.textContent = ch.total_clients + ' clients';
    badge.style.background = 'var(--green-dim)';
    badge.style.color = 'var(--green)';

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
      'rgba(59,130,246,0.7)', 'rgba(34,197,94,0.7)',
      'rgba(245,158,11,0.7)', 'rgba(239,68,68,0.7)',
      'rgba(168,85,247,0.7)', 'rgba(236,72,153,0.7)',
    ];

    offersChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: offers.map(o => o.offer),
        datasets: [{
          data: offers.map(o => o.count),
          backgroundColor: offers.map((_, i) => colors[i % colors.length]),
          borderWidth: 0, spacing: 2,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
          legend: {
            position: 'right',
            labels: {
              color: 'rgba(148,163,184,0.8)', font: { size: 11 },
              padding: 10, usePointStyle: true, pointStyleWidth: 8,
            }
          }
        }
      }
    });
  }

  // ── Lead Source ROI ──────────────────────────────────────
  function renderLeadSourceROI(snap) {
    const container = $('#lead-roi-table');
    const note = $('#lead-roi-note');
    const bySrc = get(snap, 'sales.deep.lead_quality.by_source') || [];
    const adSpend = get(snap, 'xero.xero_ad_spend');

    if (bySrc.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No source data</div>';
      note.innerHTML = '';
      return;
    }

    const totalCloses = bySrc.reduce((s, r) => s + (r.closes || 0), 0);
    const totalLeads = bySrc.reduce((s, r) => s + (r.leads || 0), 0);

    // Estimate spend allocation proportional to leads (simplification)
    const hasSpend = adSpend != null && adSpend > 0;

    let html = `<div class="lead-roi-row header">
      <span>Source</span><span class="num">Leads</span><span class="num">Sets</span>
      <span class="num">Closes</span><span class="num">Close%</span>
      <span class="num">${hasSpend ? 'Cost/Close' : 'DQ%'}</span>
    </div>`;

    // Sort by closes desc
    const sorted = [...bySrc].sort((a, b) => (b.closes || 0) - (a.closes || 0));

    sorted.forEach(s => {
      let lastCol;
      if (hasSpend && totalLeads > 0) {
        const srcSpend = (s.leads / totalLeads) * adSpend;
        const costPerClose = s.closes > 0 ? srcSpend / s.closes : null;
        if (costPerClose != null) {
          const cls = costPerClose < 500 ? 'good' : costPerClose < 1000 ? 'warn' : 'bad';
          lastCol = `<span class="highlight ${cls}">${fmt$(costPerClose)}</span>`;
        } else {
          lastCol = '<span class="highlight bad">No closes</span>';
        }
      } else {
        lastCol = `<span class="num">${s.dq_rate_pct != null ? s.dq_rate_pct + '%' : '—'}</span>`;
      }

      const closeCls = s.close_rate_pct >= 15 ? 'good' : s.close_rate_pct >= 5 ? 'warn' : 'bad';

      html += `<div class="lead-roi-row">
        <span class="source">${esc(s.source)}</span>
        <span class="num">${s.leads ?? '—'}</span>
        <span class="num">${s.sets ?? '—'}</span>
        <span class="num">${s.closes ?? '—'}</span>
        <span class="highlight ${closeCls}">${s.close_rate_pct != null ? s.close_rate_pct + '%' : '—'}</span>
        ${lastCol}
      </div>`;
    });

    container.innerHTML = html;

    // Note
    const parts = [];
    if (hasSpend) parts.push(`Total ad spend: ${fmt$(adSpend)} (trailing 30d)`);
    if (totalCloses > 0 && hasSpend) parts.push(`Blended cost/close: ${fmt$(adSpend / totalCloses)}`);
    parts.push('Spend allocated proportional to lead volume by source');
    note.textContent = parts.join(' · ');
  }

  // ── Commission Tracker ──────────────────────────────────
  function renderCommissions(snap) {
    const summary = $('#commission-summary');
    const detail = $('#commission-detail');

    const closerComm = get(snap, 'costs.closer_commission');
    const setterComm = get(snap, 'costs.setter_commission');
    const payout = get(snap, 'sales.payout') || {};
    const perCloser = get(snap, 'sales.per_closer') || [];
    const perSetter = payout.per_setter || [];

    const totalComm = ((closerComm || 0) + (setterComm || 0));

    if (totalComm === 0 && perCloser.length === 0 && perSetter.length === 0) {
      summary.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No commission data</div>';
      detail.innerHTML = '';
      return;
    }

    // Summary
    summary.innerHTML = `
      <div class="comm-stat">
        <div class="comm-stat-value">${fmt$(totalComm)}</div>
        <div class="comm-stat-label">Total owed</div>
      </div>
      <div class="comm-stat">
        <div class="comm-stat-value">${fmt$(closerComm)}</div>
        <div class="comm-stat-label">Closer comm</div>
      </div>
      <div class="comm-stat">
        <div class="comm-stat-value">${fmt$(setterComm)}</div>
        <div class="comm-stat-label">Setter comm</div>
      </div>
    `;

    // Per-person breakdown
    let html = '';

    // Closers
    perCloser.forEach(c => {
      if (!c.commission_total) return;
      html += `<div class="comm-row">
        <span class="comm-name">${esc(c.name)}</span>
        <span class="comm-role closer">Closer</span>
        <span class="comm-detail">${c.closes ?? 0} closes @ ${c.close_rate_pct ?? '—'}%</span>
        <span class="comm-amount">${fmt$(c.commission_total)}</span>
      </div>`;
    });

    // Setters
    perSetter.forEach(s => {
      if (!s.owed) return;
      html += `<div class="comm-row">
        <span class="comm-name">${esc(s.name)}</span>
        <span class="comm-role">Setter</span>
        <span class="comm-detail">${s.qualified_sets ?? 0} sets @ ${fmt$(s.rate)}/set</span>
        <span class="comm-amount">${fmt$(s.owed)}</span>
      </div>`;
    });

    if (!html) html = '<div style="color:var(--text-muted);font-size:12px;">No per-person breakdown available</div>';
    detail.innerHTML = html;
  }

  // ── Sparkline helper ────────────────────────────────────
  function sparklineSVG(values, color) {
    const valid = values.filter(v => v != null);
    if (valid.length < 2) return '';
    const min = Math.min(...valid);
    const max = Math.max(...valid);
    const range = max - min || 1;
    const w = 60, h = 20, pad = 1;

    const points = valid.map((v, i) => {
      const x = pad + (i / (valid.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((v - min) / range) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');

    return `<span class="sparkline-cell"><svg viewBox="0 0 ${w} ${h}"><polyline points="${points}" stroke="${color}"/></svg></span>`;
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

    // Build sparkline data from history
    const setterHistory = {};
    if (historyData && historyData.length > 1) {
      historyData.forEach(h => {
        (h.setters || []).forEach(s => {
          if (!setterHistory[s.name]) setterHistory[s.name] = [];
          setterHistory[s.name].push(s.sets);
        });
      });
    }

    setters.forEach(s => {
      const spark = setterHistory[s.name] ? sparklineSVG(setterHistory[s.name], 'var(--accent)') : '';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${esc(s.name)}</td>
        <td>${s.dials ?? '—'}</td>
        <td>${s.sets ?? '—'}</td>
        <td>${s.dials_per_set ?? '—'}</td>
        <td>${s.show_pct != null ? s.show_pct + '%' : '—'}</td>
        <td>${spark || '<span style="color:var(--text-muted)">—</span>'}</td>
      `;
      tbody.appendChild(tr);
    });
    if (setters.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted)">No setter data</td></tr>';
    }
  }

  function renderClosers(snap) {
    const closers = get(snap, 'sales.per_closer') || [];
    const tbody = document.querySelector('#table-closers tbody');
    tbody.innerHTML = '';

    // Build sparkline data from history
    const closerHistory = {};
    if (historyData && historyData.length > 1) {
      historyData.forEach(h => {
        (h.closers || []).forEach(c => {
          if (!closerHistory[c.name]) closerHistory[c.name] = [];
          closerHistory[c.name].push(c.closes);
        });
      });
    }

    closers.forEach(c => {
      const spark = closerHistory[c.name] ? sparklineSVG(closerHistory[c.name], 'var(--green)') : '';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${esc(c.name)}</td>
        <td>${c.shows ?? '—'}</td>
        <td>${c.closes ?? '—'}</td>
        <td>${c.close_rate_pct != null ? c.close_rate_pct + '%' : '—'}</td>
        <td>${c.commission_total != null ? fmt$(c.commission_total) : '—'}</td>
        <td>${spark || '<span style="color:var(--text-muted)">—</span>'}</td>
      `;
      tbody.appendChild(tr);
    });
    if (closers.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted)">No closer data</td></tr>';
    }
  }

  // ── Cohort Retention ─────────────────────────────────────
  function renderCohortRetention(snap) {
    const container = $('#cohort-grid');
    const ch = snap.client_health;
    if (!ch || !ch.clients || ch.clients.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No client data for cohort analysis</div>';
      return;
    }

    // Group clients by sign-up month
    const cohorts = {};
    const now = new Date();
    const currentKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

    ch.clients.forEach(c => {
      let cohortKey = 'Unknown';
      if (c.contract_start) {
        const d = new Date(c.contract_start);
        if (!isNaN(d)) {
          cohortKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        }
      }
      if (!cohorts[cohortKey]) cohorts[cohortKey] = [];
      cohorts[cohortKey].push(c);
    });

    // Sort cohort keys chronologically
    const sortedKeys = Object.keys(cohorts).sort();

    // Generate month columns from oldest cohort to current month
    const monthCols = [];
    if (sortedKeys.length > 0 && sortedKeys[0] !== 'Unknown') {
      const first = sortedKeys.find(k => k !== 'Unknown') || currentKey;
      const [fy, fm] = first.split('-').map(Number);
      let y = fy, m = fm;
      const [cy, cm] = currentKey.split('-').map(Number);
      while (y < cy || (y === cy && m <= cm)) {
        monthCols.push(`${y}-${String(m).padStart(2, '0')}`);
        m++;
        if (m > 12) { m = 1; y++; }
      }
    }

    // Limit to last 12 months of columns for readability
    const displayCols = monthCols.slice(-12);

    // Format month label
    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    function fmtMonth(key) {
      if (key === 'Unknown') return 'Unknown';
      const [y, m] = key.split('-').map(Number);
      return monthNames[m - 1] + ' ' + String(y).slice(2);
    }

    // Build table
    let html = '<table class="cohort-table"><thead><tr>';
    html += '<th>Cohort</th><th>#</th>';
    displayCols.forEach(col => { html += `<th>${fmtMonth(col)}</th>`; });
    html += '</tr></thead><tbody>';

    sortedKeys.forEach(key => {
      const clients = cohorts[key];
      const total = clients.length;
      html += `<tr><td>${fmtMonth(key)} <span class="cohort-count">(${total})</span></td>`;
      html += `<td style="text-align:center">${total}</td>`;

      displayCols.forEach(col => {
        // How many from this cohort are still paying in this month?
        // A client is "paying" if their current_mrr > 0 AND the col month >= their start
        // AND (col month <= their end OR they have no end / end is past with revenue)
        if (key === 'Unknown' || col < key) {
          html += '<td><span class="cohort-cell empty">—</span></td>';
          return;
        }

        const active = clients.filter(c => {
          if ((c.current_mrr || 0) <= 0 && col === currentKey) return false;
          // For historical months, assume they were active if they started before and haven't ended
          if (c.contract_end) {
            const endKey = c.contract_end.slice(0, 7);
            // If contract ended before this column month, count as churned
            // BUT past end dates with current revenue = renewed
            if (endKey < col && col === currentKey && (c.current_mrr || 0) > 0) return true;
            if (endKey < col && col !== currentKey) return false;
          }
          return true;
        }).length;

        const pct = total > 0 ? Math.round((active / total) * 100) : 0;
        let cls = 'empty';
        if (pct >= 80) cls = 'full';
        else if (pct >= 40) cls = 'partial';
        else if (pct > 0) cls = 'churned';

        html += `<td><span class="cohort-cell ${cls}">${pct}%</span></td>`;
      });

      html += '</tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;
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
    const [snap, history] = await Promise.all([fetchSnapshot(), fetchHistory()]);
    if (history) historyData = history;
    if (snap) render(snap);
    if (historyData && historyData.length > 1) {
      $('#reps-sparkline-status').textContent = historyData.length + ' days of history';
    }
  })();

  // Auto-refresh every 10 minutes
  setInterval(async () => {
    const snap = await fetchSnapshot();
    if (snap) render(snap);
  }, 600000);

})();
