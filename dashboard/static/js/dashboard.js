/* dashboard.js v4 — Full executive dashboard with all features */
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
  function fmtK(v) {
    if (v == null) return '—';
    const n = Number(v);
    if (isNaN(n)) return '—';
    if (Math.abs(n) >= 1000) return '$' + (n/1000).toFixed(1) + 'k';
    return '$' + n.toFixed(0);
  }

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
    renderExecSummary(snap);
    renderActionItems(snap);
    renderKPIs(snap);
    renderMonthPerformance(snap);
    renderPerfAnalysis(snap);
    renderMRRTrend(snap);
    renderWaterfall(snap);
    renderCashPosition(snap);
    renderStripeHealth(snap);
    renderSpeedToLead(snap);
    renderRevenueViews(snap);
    renderChurnRisk(snap);
    renderReconciliation(snap);
    renderDerivedClients(snap);
    renderClientHealth(snap);
    renderVerdicts(snap);
    renderFunnel(snap);
    renderSetterDeepDive(snap);
    renderPipeline(snap);
    renderDQLoss(snap);
    renderOfferChart(snap);
    renderLeadSourceROI(snap);
    renderCommissions(snap);
    renderCommissionDetail(snap);
    renderMetrics(snap);
    renderSetters(snap);
    renderClosers(snap);
    renderCohortRetention(snap);
    renderDeficiency(snap);
    renderTeamModel(snap);
    renderQuality(snap);

    if (snap.generated_at) {
      $('#chat-context').textContent = timeAgo(snap.generated_at);
    }

    // Render-integrity check: detect duplicated elements
    checkRenderIntegrity();
  }

  function checkRenderIntegrity() {
    // Ensure projection summary is not duplicated
    var projSummaries = document.querySelectorAll('#mrr-projection-summary');
    if (projSummaries.length > 1) {
      console.warn('[integrity] Duplicate projection summary detected — removing extras');
      for (var i = 1; i < projSummaries.length; i++) projSummaries[i].remove();
    }
    // Check for stale data warning
    if (currentSnap && currentSnap.generated_at) {
      var ageMs = Date.now() - new Date(currentSnap.generated_at).getTime();
      if (ageMs > 24 * 3600 * 1000) {
        var dot = $('#status-dot');
        if (dot) dot.className = 'status-dot stale';
        var txt = $('#status-text');
        if (txt) txt.textContent = '⚠ stale (>24h)';
      }
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

  // ── Executive Summary ────────────────────────────────────
  function renderExecSummary(snap) {
    const body = $('#exec-body');
    const dateEl = $('#exec-date');
    dateEl.textContent = snap.generated_at ? new Date(snap.generated_at).toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) : '';

    const lines = [];
    const h = snap.hormozi || {};
    const ch = snap.client_health || {};
    const profit = snap.profit || {};
    const stripe = snap.stripe || {};
    const funnel = get(snap, 'sales.funnel') || {};
    const deep = get(snap, 'sales.deep') || {};
    const ghl = snap.ghl || {};
    const v = snap.verdicts || {};

    // Revenue & profit
    const rev = get(snap, 'xero.revenue');
    const net = get(snap, 'xero.net_profit');
    if (rev != null) {
      const netStr = net != null ? (net >= 0 ? fmt$(net) + ' profit' : fmt$(Math.abs(net)) + ' loss') : '';
      lines.push({ icon: '$', text: `<strong>${fmt$(rev)} revenue</strong> this period${netStr ? ', ' + netStr : ''}. Gross margin ${fmtPct(get(snap, 'xero.gross_margin_pct'))}.` });
    }

    // MRR
    const sheetMRR = ch.current_mrr;
    const stripeMRR = stripe.mrr;
    if (sheetMRR != null || stripeMRR != null) {
      const ac_ = snap.active_clients || {};
      const confirmedCount = (ac_.confirmed_both_sources || 0) + (ac_.legacy_pre_tracker || 0);
      const signingCount = ac_.pending_health_update || 0;
      const projectedMRR = ac_.projected_mrr;
      const estimatedMRR = ac_.estimated_mrr || 0;
      const delta = ch.mrr_delta;
      const deltaStr = delta != null && delta !== 0 ? (delta > 0 ? ' (+' + fmt$(delta) + ' next month)' : ' (' + fmt$(delta) + ' next month)') : '';
      let mrrText;
      if (estimatedMRR > 0 && projectedMRR) {
        mrrText = `MRR: <strong>${fmt$(projectedMRR)}</strong> (${fmt$(sheetMRR)} confirmed + ~${fmt$(estimatedMRR)} est. from ${signingCount} new signings)`;
        if (stripeMRR != null) mrrText += ` · Stripe ${fmt$(stripeMRR)}`;
      } else {
        const parts = [];
        if (sheetMRR != null) parts.push('Sheet ' + fmt$(sheetMRR));
        if (stripeMRR != null) parts.push('Stripe ' + fmt$(stripeMRR));
        mrrText = `MRR: ${parts.join(' / ')}`;
      }
      let clientLabel;
      if (signingCount > 0) {
        clientLabel = `<strong>${confirmedCount + signingCount} clients</strong> (${confirmedCount} active + ${signingCount} awaiting Stripe)`;
      } else {
        clientLabel = `<strong>${confirmedCount || ch.total_clients || '?'} active clients</strong>`;
      }
      lines.push({ icon: '\u2191', text: `${mrrText}${deltaStr}. ${clientLabel}.` });
    }

    // Sales funnel
    if (funnel.closes != null) {
      const cashCollected = get(snap, 'sheets.cash_collected');
      lines.push({ icon: '\u2192', text: `Sales: <strong>${funnel.leads_in || 0} leads \u2192 ${funnel.closes} closes</strong> (${fmtPct(funnel.lead_to_close_pct)} conversion). Cash collected: ${fmt$(cashCollected)}.` });
    }

    // Top leak
    if (v.top_leaks && v.top_leaks.length > 0) {
      const top = v.top_leaks[0];
      lines.push({ icon: '\u26A0', text: `Top leak: <strong>${esc(top.name)}</strong> — ${fmt$(top.dollar_impact_monthly)}/mo impact. ${esc(top.read).substring(0, 120)}...` });
    }

    // Speed-to-lead (correct path: sales.velocity.speed_to_lead_5min_pct)
    const stl = get(snap, 'sales.velocity.speed_to_lead_5min_pct');
    if (stl != null && stl < 50) {
      lines.push({ icon: '\u23F1', text: `Speed-to-lead: <strong>${stl}%</strong> under 5min (target: 50%). This is the highest-leverage fix right now.` });
    }

    // GHL pipeline
    if (ghl.total_opportunities) {
      lines.push({ icon: '\u{1F4CB}', text: `GHL pipeline: <strong>${ghl.total_opportunities} total opps</strong>, ${ghl.status?.open || 0} open, ${ghl.status?.won || 0} won, ${ghl.status?.lost || 0} lost.` });
    }

    // Stripe health
    const failed = stripe.failed_charges_count;
    if (failed != null && failed > 0) {
      lines.push({ icon: '\u{1F6A8}', text: `Stripe: <strong>${failed} failed charges</strong> in the last 30d. Check for recoverable revenue.` });
    }

    // Data quality
    const degraded = snap.degraded || [];
    if (degraded.length > 0) {
      lines.push({ icon: '\u{1F527}', text: `${degraded.length} data quality issue${degraded.length > 1 ? 's' : ''} flagged — check Data Quality section.` });
    }

    // Data freshness warning
    const ac = snap.active_clients || {};
    const latestClose = ac.latest_close_date;
    if (latestClose) {
      const daysSince = Math.round((Date.now() - new Date(latestClose)) / 86400000);
      if (daysSince > 3) {
        lines.push({ icon: '\u{1F4C5}', text: `LTC tracker last close was ${daysSince} days ago (${latestClose}). If deals have closed since, the tracker may not be updated.` });
      }
    }

    if (lines.length === 0) {
      body.innerHTML = '<div style="color:var(--text-muted)">No data available for summary.</div>';
      return;
    }

    body.innerHTML = lines.map(l =>
      `<div class="exec-line"><span class="exec-icon">${l.icon}</span><span class="exec-text">${l.text}</span></div>`
    ).join('');
  }

  // ── Action Items ─────────────────────────────────────────
  function renderActionItems(snap) {
    const section = $('#section-actions');
    const content = $('#actions-content');
    const badge = $('#actions-badge');
    const actions = [];

    // Speed-to-lead
    const stl = get(snap, 'sales.velocity.speed_to_lead_5min_pct');
    if (stl != null && stl < 50) {
      actions.push({ priority: 'critical', text: `Speed-to-lead is ${stl}% (target 50%). Coach setters on immediate callback within 5 minutes.`, owner: 'Sales Manager' });
    }

    // Failed charges
    const failed = get(snap, 'stripe.failed_charges_count');
    if (failed != null && failed > 0) {
      actions.push({ priority: 'watch', text: `${failed} failed Stripe charges. Review and retry — potential recoverable revenue.`, owner: 'Ops' });
    }

    // Past due subs
    const pastDue = get(snap, 'stripe.subscriptions.past_due');
    if (pastDue != null && pastDue > 0) {
      actions.push({ priority: 'watch', text: `${pastDue} past-due subscription${pastDue > 1 ? 's' : ''}. Reach out to retain.`, owner: 'Ops' });
    }

    // Churn risk
    const atRisk = get(snap, 'client_health.at_risk') || [];
    const critical = atRisk.filter(c => c.risk_level === 'critical');
    if (critical.length > 0) {
      const names = critical.map(c => c.name).join(', ');
      actions.push({ priority: 'critical', text: `${critical.length} client${critical.length > 1 ? 's' : ''} expiring in <30 days: ${names}. Schedule renewal calls.`, owner: 'Rydel' });
    }

    // Top leak
    const leaks = get(snap, 'verdicts.top_leaks') || [];
    if (leaks.length > 0) {
      const top = leaks[0];
      actions.push({ priority: 'watch', text: `Fix #1 leak: ${top.name} (${fmt$(top.dollar_impact_monthly)}/mo impact).`, owner: 'Rydel' });
    }

    // Reconciliation issues
    const missing = get(snap, 'client_reconciliation.missing_from_health') || [];
    if (missing.length > 0) {
      actions.push({ priority: 'watch', text: `${missing.length} won client${missing.length > 1 ? 's' : ''} missing from Health tab. Update the sheet.`, owner: 'Ops' });
    }

    if (actions.length === 0) {
      section.style.display = 'none';
      return;
    }

    section.style.display = '';
    badge.textContent = actions.length + ' item' + (actions.length > 1 ? 's' : '');
    const critCount = actions.filter(a => a.priority === 'critical').length;
    badge.style.background = critCount > 0 ? 'var(--red-dim)' : 'var(--amber-dim)';
    badge.style.color = critCount > 0 ? 'var(--red)' : 'var(--amber)';

    content.innerHTML = actions.map(a => `
      <div class="action-item ${a.priority}">
        <span class="action-priority ${a.priority}">${a.priority === 'critical' ? '!!' : '!'}</span>
        <span class="action-text">${esc(a.text)}</span>
        <span class="action-owner">${esc(a.owner)}</span>
      </div>
    `).join('');
  }

  // ── KPI Strip ────────────────────────────────────────────
  function kpiArrow(current, previous) {
    if (current == null || previous == null) return '';
    const diff = current - previous;
    if (Math.abs(diff) < 0.01) return '';
    const arrow = diff > 0 ? '\u2191' : '\u2193';
    const color = diff > 0 ? 'var(--green)' : 'var(--red)';
    return ` <span style="color:${color};font-size:11px">${arrow}</span>`;
  }

  function renderKPIs(snap) {
    const h = snap.hormozi || {};
    const ch = snap.client_health || {};

    // Get previous snapshot for WoW arrows
    const prev = (historyData && historyData.length >= 2) ? historyData[historyData.length - 2] : null;

    // Sheet MRR — show projected if new signings exist
    const acData = snap.active_clients || {};
    const projMRR = acData.projected_mrr;
    const estMRR = acData.estimated_mrr || 0;
    const signingCount = acData.pending_health_update || 0;
    const confirmedMRR = ch.current_mrr;
    const delta = ch.mrr_delta;
    if (estMRR > 0 && projMRR) {
      setKPI('val-sheet-mrr', fmt$(projMRR));
      $('#sub-sheet-mrr').innerHTML = fmt$(confirmedMRR) + ' confirmed + ~' + fmt$(estMRR) + ' est. (' + signingCount + ' new)';
      $('#sub-sheet-mrr').style.color = 'var(--purple)';
    } else {
      setKPI('val-sheet-mrr', fmt$(confirmedMRR));
      if (delta != null && delta !== 0) {
        const dir = delta > 0 ? '+' : '';
        $('#sub-sheet-mrr').textContent = dir + fmt$(delta) + ' next month';
        $('#sub-sheet-mrr').style.color = delta >= 0 ? 'var(--green)' : 'var(--red)';
      } else {
        $('#sub-sheet-mrr').textContent = ch.current_month || '';
      }
    }

    // Stripe MRR
    const stripeMRR = get(snap, 'stripe.mrr');
    const prevStripeMRR = prev ? get(prev, 'stripe.mrr') : null;
    const stripeMRREl = document.getElementById('val-stripe-mrr');
    if (stripeMRREl) stripeMRREl.innerHTML = fmt$(stripeMRR) + kpiArrow(stripeMRR, prevStripeMRR);
    // Show MRR gap context if both exist
    if (stripeMRR != null && ch.current_mrr != null) {
      const mrrGap = ch.current_mrr - stripeMRR;
      if (Math.abs(mrrGap) > 100) {
        const subEl = $('#sub-stripe-mrr');
        subEl.textContent = (mrrGap > 0 ? 'Sheet +' : 'Sheet ') + fmt$(mrrGap) + ' gap';
        subEl.title = 'Sheet includes manually-tracked clients not yet on Stripe billing';
      } else {
        $('#sub-stripe-mrr').textContent = 'reconciled';
      }
    } else {
      $('#sub-stripe-mrr').textContent = 'recurring';
    }

    // Cash
    const cash = get(snap, 'sheets.cash_collected');
    setKPI('val-cash', fmt$(cash));

    // Gross Margin
    const margin = get(h, 'gross_margin.value');
    const prevMargin = prev ? get(prev, 'hormozi.gross_margin.value') : null;
    const marginEl = document.getElementById('val-margin');
    if (marginEl) {
      marginEl.innerHTML = fmtPct(margin) + kpiArrow(margin, prevMargin);
      marginEl.className = 'kpi-value ' + statusClass(get(h, 'gross_margin.status'));
    }
    $('#sub-margin').textContent = margin != null ? 'benchmark: 45%' : '';

    // LTGP:CAC
    const ltgpcac = get(h, 'ltgp_cac.value');
    const ltgpEl = document.getElementById('val-ltgpcac-kpi');
    if (ltgpEl) {
      ltgpEl.textContent = fmtX(ltgpcac);
      ltgpEl.className = 'kpi-value ' + statusClass(get(h, 'ltgp_cac.status'));
    }
    $('#sub-ltgpcac').textContent = ltgpcac != null ? 'benchmark: 3.0\u00d7' : 'gross profit / acq cost';

    // LTV:CAC
    const ltvcac = get(h, 'ltv_to_cac.value');
    const ltvcacEl = document.getElementById('val-ltvcac');
    if (ltvcacEl) {
      ltvcacEl.textContent = fmtX(ltvcac);
      ltvcacEl.className = 'kpi-value';
    }
    $('#sub-ltvcac').textContent = ltvcac != null ? 'full revenue / acq cost' : '';

    // Active Clients — only set fallback here; renderDerivedClients overwrites with split count
    if (!snap.active_clients) {
      const total = ch.total_clients;
      setKPI('val-clients', total != null ? total : '—');
    }
    if (!snap.active_clients && ch.active_count != null) {
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

  // ── Profit Waterfall ─────────────────────────────────────
  function renderWaterfall(snap) {
    const content = $('#waterfall-content');
    const periodEl = $('#waterfall-period');
    const xero = snap.xero || {};
    const profit = snap.profit || {};
    const payroll = profit.payroll || {};

    const rev = xero.revenue;
    const cogs = xero.cogs;
    const gp = xero.gross_profit;
    const opex = xero.operating_expenses;
    const net = xero.net_profit;
    const adSpend = xero.xero_ad_spend;
    const wages = xero.xero_wages;

    if (rev == null) {
      content.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No Xero P&L data available</div>';
      return;
    }

    const period = xero.period;
    periodEl.textContent = period ? period.label : '';

    const maxVal = Math.max(rev || 0, opex || 0, 1);

    function bar(value, cls) {
      const pct = Math.max(Math.abs(value || 0) / maxVal * 100, 2);
      return `<div class="wf-bar-bg"><div class="wf-bar-fill ${cls}" style="width:${pct}%"></div></div>`;
    }

    function pctOf(part, whole) {
      if (part == null || whole == null || whole === 0) return '';
      return ` <span style="color:var(--text-muted);font-size:12px">(${Math.round(Math.abs(part) / whole * 100)}%)</span>`;
    }

    let rows = '';
    rows += `<div class="wf-row"><span class="wf-label">Revenue</span>${bar(rev, 'revenue')}<span class="wf-value" style="color:var(--accent)">${fmt$(rev)}</span></div>`;
    if (cogs != null) rows += `<div class="wf-row"><span class="wf-label">COGS${pctOf(cogs, rev)}</span>${bar(cogs, 'cost')}<span class="wf-value" style="color:var(--red)">-${fmt$(cogs)}</span></div>`;
    if (gp != null) rows += `<div class="wf-row total"><span class="wf-label">Gross Profit${pctOf(gp, rev)}</span>${bar(gp, gp >= 0 ? 'profit' : 'loss')}<span class="wf-value" style="color:${gp >= 0 ? 'var(--green)' : 'var(--red)'}">${fmt$(gp)}</span></div>`;
    if (opex != null) rows += `<div class="wf-row"><span class="wf-label">Operating Expenses${pctOf(opex, rev)}</span>${bar(opex, 'cost')}<span class="wf-value" style="color:var(--red)">-${fmt$(opex)}</span></div>`;
    if (net != null) rows += `<div class="wf-row total"><span class="wf-label">Net Profit${pctOf(net, rev)}</span>${bar(Math.abs(net), net >= 0 ? 'profit' : 'loss')}<span class="wf-value" style="color:${net >= 0 ? 'var(--green)' : 'var(--red)'}">${fmt$(net)}</span></div>`;

    // OpEx breakdown
    let breakdownHtml = '';
    const trueTeam = get(payroll, 'true_team_cost.true_team_cost_monthly');
    const closerComm = get(snap, 'costs.closer_commission');
    const setterComm = get(snap, 'costs.setter_commission');
    const totalComm = (closerComm || 0) + (setterComm || 0);

    const details = [];
    if (trueTeam != null) details.push({ label: 'Team Cost', value: fmt$(trueTeam), sub: 'payroll + owner + super' });
    if (totalComm > 0) details.push({ label: 'Commissions', value: fmt$(totalComm), sub: 'closer + setter' });
    if (adSpend != null) details.push({ label: 'Ad Spend', value: fmt$(adSpend), sub: 'Xero advertising' });

    // "Other" = opex - known items
    if (opex != null) {
      const knownOpex = (trueTeam || 0) + totalComm + (adSpend || 0);
      const other = opex - knownOpex;
      if (other > 100) details.push({ label: 'Other OpEx', value: fmt$(other), sub: 'rent, software, etc.' });
    }

    if (details.length > 0) {
      breakdownHtml = '<div class="wf-breakdown">' + details.map(d =>
        `<div class="wf-detail"><div class="wf-detail-label">${d.label}</div><div class="wf-detail-value">${d.value}</div><div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${d.sub}</div></div>`
      ).join('') + '</div>';
    }

    content.innerHTML = `<div class="waterfall-flow">${rows}</div>${breakdownHtml}`;
  }

  // ── Cash Position / Runway ───────────────────────────────
  function renderCashPosition(snap) {
    const content = $('#cash-position-content');
    const badge = $('#cash-badge');
    const stripe = snap.stripe || {};
    const xero = snap.xero || {};
    const payroll = get(snap, 'profit.payroll') || {};

    const stripeCash = get(stripe, 'revenue.current.total_aud');
    const payouts = get(stripe, 'payouts.total_paid_out');
    const trueTeam = get(payroll, 'true_team_cost.true_team_cost_monthly');
    const opex = xero.operating_expenses;
    const rev = xero.revenue;

    // Burn rate = true team cost (conservative) or full opex
    const monthlyBurn = trueTeam || opex || null;
    const cashInflow = stripeCash || rev || null;

    let html = '<div class="cash-grid">';

    // Stripe cash collected
    html += `<div class="cash-card">
      <div class="cash-card-label">Stripe Cash (30d)</div>
      <div class="cash-card-value" style="color:var(--accent)">${fmt$(stripeCash)}</div>
      <div class="cash-card-sub">collected from clients</div>
    </div>`;

    // Payouts
    html += `<div class="cash-card">
      <div class="cash-card-label">Stripe Payouts</div>
      <div class="cash-card-value">${fmt$(payouts)}</div>
      <div class="cash-card-sub">transferred to bank</div>
    </div>`;

    // Monthly burn
    html += `<div class="cash-card">
      <div class="cash-card-label">Monthly Burn</div>
      <div class="cash-card-value" style="color:var(--red)">${fmt$(monthlyBurn)}</div>
      <div class="cash-card-sub">${trueTeam ? 'team cost (fixed)' : 'total opex'}</div>
    </div>`;

    // Net cash flow
    if (cashInflow != null && monthlyBurn != null) {
      const netFlow = cashInflow - monthlyBurn;
      html += `<div class="cash-card">
        <div class="cash-card-label">Net Cash Flow</div>
        <div class="cash-card-value" style="color:${netFlow >= 0 ? 'var(--green)' : 'var(--red)'}">${netFlow >= 0 ? '+' : ''}${fmt$(netFlow)}</div>
        <div class="cash-card-sub">revenue minus burn</div>
      </div>`;
    }

    html += '</div>';

    // Runway indicator
    if (cashInflow != null && monthlyBurn != null && monthlyBurn > 0) {
      const ratio = cashInflow / monthlyBurn;
      const months = ratio;
      const barPct = Math.min(ratio / 3 * 100, 100);
      const color = ratio >= 1.5 ? 'var(--green)' : ratio >= 1 ? 'var(--amber)' : 'var(--red)';
      html += `<div class="runway-bar-bg"><div class="runway-bar-fill" style="width:${barPct}%;background:${color}"></div></div>`;
      html += `<div class="runway-note">Revenue covers <strong style="color:${color}">${months.toFixed(1)}x</strong> monthly burn. ${ratio >= 1.5 ? 'Self-funding.' : ratio >= 1 ? 'Tight — watch closely.' : 'Revenue below burn rate.'}</div>`;

      badge.textContent = months.toFixed(1) + 'x coverage';
      badge.style.background = ratio >= 1.5 ? 'var(--green-dim)' : ratio >= 1 ? 'var(--amber-dim)' : 'var(--red-dim)';
      badge.style.color = color;
    }

    content.innerHTML = html;
  }

  // ── Stripe Health ────────────────────────────────────────
  function renderStripeHealth(snap) {
    const content = $('#stripe-health-content');
    const badge = $('#stripe-badge');
    const stripe = snap.stripe || {};
    const subs = stripe.subscriptions || {};
    const failed = stripe.failed_charges_count;

    let html = '<div class="stripe-grid">';

    // Failed charges
    const failCls = failed > 0 ? 'alert' : 'ok';
    html += `<div class="stripe-card ${failCls}">
      <div class="stripe-card-label">Failed Charges</div>
      <div class="stripe-card-value" style="color:${failed > 0 ? 'var(--red)' : 'var(--green)'}">${failed ?? '—'}</div>
      <div class="stripe-card-sub">trailing 30d</div>
    </div>`;

    // Active subs
    html += `<div class="stripe-card ok">
      <div class="stripe-card-label">Active Subs</div>
      <div class="stripe-card-value">${subs.active ?? '—'}</div>
      <div class="stripe-card-sub">current</div>
    </div>`;

    // Past due
    const pastDue = subs.past_due || 0;
    html += `<div class="stripe-card ${pastDue > 0 ? 'alert' : 'ok'}">
      <div class="stripe-card-label">Past Due</div>
      <div class="stripe-card-value" style="color:${pastDue > 0 ? 'var(--amber)' : 'var(--green)'}">${pastDue}</div>
      <div class="stripe-card-sub">needs attention</div>
    </div>`;

    // Cancelled
    html += `<div class="stripe-card">
      <div class="stripe-card-label">Cancelled</div>
      <div class="stripe-card-value">${subs.cancelled ?? '—'}</div>
      <div class="stripe-card-sub">this period</div>
    </div>`;

    html += '</div>';

    // Failed charges detail
    if (failed > 0) {
      html += `<div style="font-size:12px;color:var(--text-muted);margin-top:8px;padding:8px 12px;background:var(--red-dim);border-radius:var(--radius-sm)">
        <strong style="color:var(--red)">${failed} failed charge${failed > 1 ? 's' : ''}</strong> in the last 30 days.
        Per-charge amounts and customer detail require direct Stripe dashboard access
        (Stripe &gt; Payments &gt; Failed). Recoverable amount cannot be estimated from aggregate count alone.
      </div>`;
    }

    // Past-due subscription detail
    if (pastDue > 0) {
      html += `<div style="font-size:12px;color:var(--text-muted);margin-top:8px;padding:8px 12px;background:var(--amber-dim);border-radius:var(--radius-sm)">
        <strong style="color:var(--amber)">${pastDue} past-due subscription${pastDue > 1 ? 's' : ''}</strong>.
        Customer detail requires direct Stripe dashboard access (Stripe &gt; Subscriptions &gt; Past due).
      </div>`;
    }

    // Badge
    const issues = (failed || 0) + pastDue;
    if (issues > 0) {
      badge.textContent = issues + ' issue' + (issues > 1 ? 's' : '');
      badge.style.background = 'var(--red-dim)';
      badge.style.color = 'var(--red)';
    } else {
      badge.textContent = 'Healthy';
      badge.style.background = 'var(--green-dim)';
      badge.style.color = 'var(--green)';
    }

    content.innerHTML = html;
  }

  // ── Speed-to-Lead Alert ──────────────────────────────────
  function renderSpeedToLead(snap) {
    const section = $('#section-speed-to-lead');
    const content = $('#speed-to-lead-content');
    // Correct path: sales.velocity.speed_to_lead_5min_pct
    const pct = get(snap, 'sales.velocity.speed_to_lead_5min_pct');
    const callsIn5 = get(snap, 'sales.velocity.calls_within_5_min');
    const totalDials = get(snap, 'sales.velocity.total_dials');

    if (pct == null || pct >= 50) {
      section.style.display = 'none';
      return;
    }

    section.style.display = '';
    const dialDetail = callsIn5 != null && totalDials != null ? ` (${callsIn5}/${totalDials} dials)` : '';
    content.innerHTML = `
      <div class="alert-content">
        <div class="alert-icon">\u26A1</div>
        <div class="alert-body">
          <div class="alert-title">Speed-to-Lead Below Target</div>
          <div class="alert-detail">
            Only <strong>${pct}%</strong> of leads contacted within 5 minutes${dialDetail} (target: 50%).
            Leads contacted within 5 minutes are <strong>21x more likely</strong> to qualify.
            This is the single highest-leverage improvement available.
          </div>
        </div>
        <div class="alert-metric">
          <div class="alert-metric-value">${pct}%</div>
          <div class="alert-metric-label">Under 5min</div>
        </div>
      </div>
    `;
  }

  // ── GHL Pipeline View ───────────────────────────────────
  function renderPipeline(snap) {
    const content = $('#pipeline-content');
    const badge = $('#pipeline-badge');
    const ghl = snap.ghl;

    if (!ghl) {
      content.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No GHL data available</div>';
      return;
    }

    // Badge
    badge.textContent = (ghl.total_opportunities || 0) + ' opps';
    badge.style.background = 'var(--accent-dim)';
    badge.style.color = 'var(--accent)';

    // Summary
    const status = ghl.status || {};
    let html = '<div class="pipeline-summary">';
    html += `<div class="pipeline-stat"><div class="pipeline-stat-value">${ghl.total_opportunities || 0}</div><div class="pipeline-stat-label">Total Opps</div></div>`;
    html += `<div class="pipeline-stat"><div class="pipeline-stat-value" style="color:var(--accent)">${status.open || 0}</div><div class="pipeline-stat-label">Open</div></div>`;
    html += `<div class="pipeline-stat"><div class="pipeline-stat-value" style="color:var(--green)">${status.won || 0}</div><div class="pipeline-stat-label">Won</div></div>`;
    html += `<div class="pipeline-stat"><div class="pipeline-stat-value" style="color:var(--red)">${status.lost || 0}</div><div class="pipeline-stat-label">Lost</div></div>`;
    if (ghl.conversion_rate_pct != null) {
      html += `<div class="pipeline-stat"><div class="pipeline-stat-value">${ghl.conversion_rate_pct}%</div><div class="pipeline-stat-label">Win Rate</div></div>`;
    }
    html += `<div class="pipeline-stat"><div class="pipeline-stat-value">${fmtK(ghl.total_pipeline_value)}</div><div class="pipeline-stat-label">Pipeline Value</div></div>`;
    html += '</div>';

    // Stage breakdown — collapse low-signal stages (Unresponsive, etc.) into "Other"
    const stages = ghl.stage_breakdown || {};
    const stageEntries = Object.entries(stages).sort((a, b) => b[1].count - a[1].count);
    const LOW_SIGNAL_STAGES = ['unresponsive', 'no answer', 'dead', 'invalid'];
    let otherCount = 0, otherValue = 0;
    const activeStages = [];
    stageEntries.forEach(([name, data]) => {
      if (LOW_SIGNAL_STAGES.includes(name.toLowerCase())) {
        otherCount += data.count;
        otherValue += data.value || 0;
      } else {
        activeStages.push([name, data]);
      }
    });
    if (otherCount > 0) {
      activeStages.push(['Other (unresponsive/dead)', { count: otherCount, value: otherValue }]);
    }
    const maxCount = Math.max(...activeStages.map(e => e[1].count), 1);

    if (activeStages.length > 0) {
      html += '<div class="pipeline-stages">';
      activeStages.forEach(([name, data]) => {
        const pct = Math.max(data.count / maxCount * 100, 3);
        const isOther = name.startsWith('Other (');
        html += `<div class="pipeline-stage-row">
          <span class="pipeline-stage-name" style="${isOther ? 'color:var(--text-muted)' : ''}">${esc(name)}</span>
          <div class="pipeline-stage-bar-bg"><div class="pipeline-stage-bar" style="width:${pct}%;${isOther ? 'opacity:0.4' : ''}"></div></div>
          <span class="pipeline-stage-count">${data.count}</span>
          <span class="pipeline-stage-value">${fmtK(data.value)}</span>
        </div>`;
      });
      html += '</div>';
    }

    content.innerHTML = html;
  }

  // ── DQ & Loss Intelligence ──────────────────────────────
  function renderDQLoss(snap) {
    const content = $('#dq-loss-content');
    const deep = get(snap, 'sales.deep') || {};
    const lossData = deep.loss || {};
    const leadQuality = deep.lead_quality || {};

    let html = '';

    // DQ reasons
    const dqReasons = lossData.dq_reasons || [];
    if (dqReasons.length > 0) {
      const maxDQ = Math.max(...dqReasons.map(r => r.count), 1);
      html += '<div class="dq-section">';
      html += '<div class="dq-section-title">DQ Reasons</div>';
      dqReasons.slice(0, 6).forEach(r => {
        const pct = Math.max(r.count / maxDQ * 100, 5);
        html += `<div class="dq-bar-row">
          <span class="dq-reason" title="${esc(r.reason)}">${esc(r.reason)}</span>
          <div class="dq-bar-bg"><div class="dq-bar-fill dq" style="width:${pct}%"></div></div>
          <span class="dq-count">${r.count}</span>
        </div>`;
      });
      html += '</div>';
    }

    // Loss reasons
    const lossReasons = lossData.loss_reasons || [];
    if (lossReasons.length > 0) {
      const maxLoss = Math.max(...lossReasons.map(r => r.count), 1);
      html += '<div class="dq-section">';
      html += '<div class="dq-section-title">Loss Reasons</div>';
      lossReasons.slice(0, 6).forEach(r => {
        const pct = Math.max(r.count / maxLoss * 100, 5);
        html += `<div class="dq-bar-row">
          <span class="dq-reason" title="${esc(r.reason)}">${esc(r.reason)}</span>
          <div class="dq-bar-bg"><div class="dq-bar-fill loss" style="width:${pct}%"></div></div>
          <span class="dq-count">${r.count}</span>
        </div>`;
      });
      html += '</div>';
    }

    // Revenue range targeting waste
    const byRevRange = leadQuality.by_revenue_range || [];
    const flagged = byRevRange.filter(r => r.targeting_flag);
    if (flagged.length > 0) {
      html += '<div class="dq-section">';
      html += '<div class="dq-section-title">Revenue Range Targeting</div>';
      const maxLeads = Math.max(...byRevRange.map(r => r.leads || 0), 1);
      byRevRange.forEach(r => {
        const pct = Math.max((r.leads || 0) / maxLeads * 100, 3);
        const label = r.targeting_flag ? `${esc(r.range)} (waste)` : esc(r.range);
        html += `<div class="dq-bar-row">
          <span class="dq-reason" style="${r.targeting_flag ? 'color:var(--red)' : ''}">${label}</span>
          <div class="dq-bar-bg"><div class="dq-bar-fill rev" style="width:${pct}%"></div></div>
          <span class="dq-count">${r.leads || 0}/${r.closes || 0}</span>
        </div>`;
      });

      // Insight
      if (flagged.length > 0) {
        html += `<div class="dq-insight">${flagged.map(f => esc(f.targeting_flag)).join(' ')}</div>`;
      }
      html += '</div>';
    }

    if (!html) {
      content.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No DQ/loss data available</div>';
      return;
    }

    content.innerHTML = html;
  }

  // ── Setter Deep Dive Funnel ─────────────────────────────
  function renderSetterDeepDive(snap) {
    const content = $('#setter-deep-content');
    // Use setter_deep_dive (from "Setter Deep-Dive" tab) for connects data
    const deepDive = get(snap, 'sales.setter_deep_dive') || {};
    const setterPerf = get(snap, 'sales.deep.setter_performance') || [];

    // Get dials/sets from setter_performance (raw LTC computation)
    let totalDials = 0, totalSets = 0;
    setterPerf.forEach(s => {
      totalDials += s.dials || 0;
      totalSets += s.sets || 0;
    });

    // Use deep dive tab for connects (setter_performance doesn't have connects)
    const totalConnects = deepDive.connects || 0;

    // Prefer deep dive tab numbers if setter_performance is empty
    if (totalDials === 0 && deepDive.dials) totalDials = deepDive.dials;
    if (totalSets === 0 && deepDive.sets_booked) totalSets = deepDive.sets_booked;

    const funnel = get(snap, 'sales.funnel') || {};
    const shows = deepDive.showed || funnel.shows || 0;
    const closes = deepDive.closed || funnel.closes || 0;

    if (totalDials === 0 && totalSets === 0) {
      content.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No setter deep-dive data available</div>';
      return;
    }

    const stages = [
      { label: 'Dials', count: totalDials, rate: null },
      { label: 'Connects', count: totalConnects, rate: totalDials > 0 ? (totalConnects / totalDials * 100).toFixed(1) : null },
      { label: 'Sets', count: totalSets, rate: totalConnects > 0 ? (totalSets / totalConnects * 100).toFixed(1) : null },
      { label: 'Shows', count: shows, rate: totalSets > 0 ? (shows / totalSets * 100).toFixed(1) : null },
      { label: 'Closes', count: closes, rate: shows > 0 ? (closes / shows * 100).toFixed(1) : null },
    ];

    const maxCount = Math.max(...stages.map(s => s.count || 0), 1);

    let html = '<div class="deep-funnel">';
    stages.forEach((s, i) => {
      const pct = Math.max((s.count || 0) / maxCount * 100, 3);
      const isClosed = s.label === 'Closes';
      html += `<div class="deep-stage-row">
        <span class="deep-stage-label">${s.label}</span>
        <div class="deep-stage-bar-bg"><div class="deep-stage-bar${isClosed ? ' closes' : ''}" style="width:${pct}%"></div></div>
        <span class="deep-stage-count">${s.count}</span>
        <span class="deep-stage-rate">${s.rate != null ? s.rate + '%' : ''}</span>
      </div>`;
    });
    html += '</div>';

    // Connect rate callout
    if (totalDials > 0 && totalConnects > 0) {
      const connectRate = (totalConnects / totalDials * 100).toFixed(1);
      html += `<div class="deep-connect-note">
        Connect rate: <strong>${connectRate}%</strong> (${totalConnects}/${totalDials} dials).
        ${Number(connectRate) < 20 ? 'Below 20% — check dial times, list quality, or script opening.' : 'Solid connect rate.'}
        End-to-end: ${totalDials} dials needed per close (${totalDials > 0 && closes > 0 ? Math.round(totalDials / closes) + ':1' : '—'} ratio).
      </div>`;
    }

    content.innerHTML = html;
  }

  // ── Month Performance ────────────────────────────────────
  function renderMonthPerformance(snap) {
    const h = snap.hormozi || {};
    const grid = $('#month-perf-grid');
    const reads = $('#month-perf-reads');
    const badge = $('#month-perf-badge');

    const metrics = [
      { key: 'ltgp_cac', label: 'LTGP:CAC', fmt: v => fmtX(v), bench: '3.0\u00d7' },
      { key: 'cac_loaded', label: 'CAC (Loaded)', fmt: v => fmt$(v), bench: null },
      { key: 'payback_days', label: 'Payback', fmt: v => fmtDays(v), bench: '30d' },
      { key: 'gross_margin', label: 'Gross Margin', fmt: v => fmtPct(v), bench: '45%' },
      { key: 'ltv_to_cac', label: 'LTV:CAC', fmt: v => fmtX(v), bench: null },
      { key: 'sales_velocity', label: 'Sales Velocity', fmt: v => v != null ? '$' + Math.round(v) + '/day' : '—', bench: null },
    ];

    let healthyCount = 0;
    let totalWithStatus = 0;

    let gridHtml = '';
    let readsHtml = '';

    metrics.forEach(m => {
      const data = h[m.key] || {};
      const status = data.status || 'unknown';
      const value = data.value;
      const benchmarkStr = m.bench ? `Benchmark: <strong>${m.bench}</strong>` : '';
      const confidenceStr = data.confidence ? `Confidence: ${data.confidence}` : '';

      if (status !== 'unknown') totalWithStatus++;
      if (status === 'healthy') healthyCount++;

      gridHtml += `
        <div class="mp-card ${status}">
          <div class="mp-label">${m.label}</div>
          <div class="mp-value ${status}">${m.fmt(value)}</div>
          <div class="mp-benchmark">${[benchmarkStr, confidenceStr].filter(Boolean).join(' \u00b7 ')}</div>
        </div>
      `;

      if (data.read) {
        readsHtml += `
          <div class="mp-read ${status}">
            <span class="mp-read-label">${m.label}:</span>${esc(data.read)}
          </div>
        `;
      }
    });

    grid.innerHTML = gridHtml;
    reads.innerHTML = readsHtml;

    // Badge
    if (totalWithStatus === 0) {
      badge.textContent = 'No data';
      badge.style.background = 'rgba(255,255,255,0.05)';
      badge.style.color = 'var(--text-muted)';
    } else {
      const score = Math.round((healthyCount / totalWithStatus) * 100);
      badge.textContent = score + '% healthy';
      if (score >= 80) {
        badge.style.background = 'var(--green-dim)';
        badge.style.color = 'var(--green)';
      } else if (score >= 50) {
        badge.style.background = 'var(--amber-dim)';
        badge.style.color = 'var(--amber)';
      } else {
        badge.style.background = 'var(--red-dim)';
        badge.style.color = 'var(--red)';
      }
    }
  }

  // ── Global Window State ─────────────────────────────────
  let currentWindow = 30;

  function initGlobalWindowSelector() {
    const bar = $('#global-window-bar');
    if (!bar) return;
    bar.querySelectorAll('.global-window-btn').forEach(btn => {
      btn.addEventListener('click', function() {
        currentWindow = parseInt(this.dataset.window);
        bar.querySelectorAll('.global-window-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        // Show note for non-30d windows about financial data
        const note = $('#global-window-note');
        if (currentWindow !== 30) {
          note.textContent = 'Financial data (P&L, Cash) shown for trailing 30d only';
        } else {
          note.textContent = '';
        }
        // Re-render window-aware sections
        if (currentSnap) {
          activeWindow = currentWindow;
          renderPerfAnalysis(currentSnap);
          renderFunnel(currentSnap);
          renderSetters(currentSnap);
          renderClosers(currentSnap);
          renderCommissionDetail(currentSnap);
        }
      });
    });
  }

  // ── Performance Analysis (multi-window) ─────────────────
  let activeWindow = 30;

  function renderPerfAnalysis(snap) {
    const windows = get(snap, 'sales.windows') || [];
    const tabsEl = $('#window-tabs');
    const content = $('#perf-analysis-content');

    if (windows.length === 0) {
      tabsEl.innerHTML = '';
      content.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No window data available</div>';
      return;
    }

    // Render tabs
    tabsEl.innerHTML = windows.map(w => {
      const label = w.window_days + 'd';
      const active = w.window_days === activeWindow ? ' active' : '';
      return `<button class="window-tab${active}" data-window="${w.window_days}">${label}</button>`;
    }).join('');

    // Tab click handlers — sync with global window
    tabsEl.querySelectorAll('.window-tab').forEach(btn => {
      btn.addEventListener('click', function() {
        activeWindow = parseInt(this.dataset.window);
        currentWindow = activeWindow;
        // Sync global bar
        const bar = $('#global-window-bar');
        if (bar) {
          bar.querySelectorAll('.global-window-btn').forEach(b => b.classList.toggle('active', parseInt(b.dataset.window) === currentWindow));
          const note = $('#global-window-note');
          if (note) note.textContent = currentWindow !== 30 ? 'Financial data (P&L, Cash) shown for trailing 30d only' : '';
        }
        renderPerfAnalysis(currentSnap);
        renderFunnel(currentSnap);
        renderSetters(currentSnap);
        renderClosers(currentSnap);
        renderCommissionDetail(currentSnap);
      });
    });

    // Find active window data
    const w = windows.find(x => x.window_days === activeWindow) || windows[2] || windows[0];

    // Funnel mini
    const stages = [
      { label: 'Leads', count: w.leads },
      { label: 'Sets', count: w.sets, pct: w.lead_to_set_pct },
      { label: 'Shows', count: w.shows, pct: w.set_to_show_pct },
      { label: 'Closes', count: w.closes, pct: w.show_to_close_pct },
    ];

    let funnelHtml = '<div class="perf-funnel-mini">';
    stages.forEach((s, i) => {
      if (i > 0) funnelHtml += `<span class="perf-arrow">${s.pct != null ? s.pct + '%' : '—'} \u2192</span>`;
      funnelHtml += `
        <div class="perf-stage">
          <div class="perf-stage-count">${s.count ?? '—'}</div>
          <div class="perf-stage-label">${s.label}</div>
        </div>
      `;
    });
    funnelHtml += '</div>';

    // Metric cards
    let metricsHtml = '<div class="perf-comparison">';
    const cards = [
      { label: 'Avg Contract', value: fmt$(w.avg_contract), sub: 'per won deal' },
      { label: 'Avg Cash', value: fmt$(w.avg_cash), sub: 'collected per deal' },
      { label: 'Total Cash', value: fmt$(w.total_cash), sub: `in ${w.window_days}d` },
      { label: 'Commission', value: fmt$(w.total_commission), sub: w.commission_pct != null ? w.commission_pct + '% of cash' : '' },
      { label: 'Lead\u2192Close', value: w.lead_to_close_pct != null ? w.lead_to_close_pct + '%' : '—', sub: 'conversion rate' },
      { label: 'Cycle Time', value: w.median_days_to_close != null ? Math.round(w.median_days_to_close) + ' days' : '—', sub: 'median lead to close' },
      { label: 'DQ Rate', value: w.dq_rate_pct != null ? w.dq_rate_pct + '%' : '—', sub: w.dqs + ' disqualified' },
    ];

    cards.forEach(c => {
      metricsHtml += `
        <div class="perf-metric">
          <div class="perf-metric-label">${c.label}</div>
          <div class="perf-metric-value">${c.value}</div>
          <div class="perf-metric-sub">${c.sub}</div>
        </div>
      `;
    });
    metricsHtml += '</div>';

    // Summary text
    let summaryParts = [];
    if (w.leads > 0) summaryParts.push(`${w.leads} leads entered the funnel`);
    if (w.closes > 0) summaryParts.push(`${w.closes} converted to paying clients`);
    if (w.total_cash > 0) summaryParts.push(`${fmt$(w.total_cash)} cash collected`);
    if (w.lead_to_close_pct != null) summaryParts.push(`${w.lead_to_close_pct}% overall close rate`);
    if (w.dq_rate_pct != null && w.dq_rate_pct > 15) summaryParts.push(`High DQ rate (${w.dq_rate_pct}%) — check lead quality`);

    // Window comparison hint
    const w30 = windows.find(x => x.window_days === 30);
    const w7 = windows.find(x => x.window_days === 7);
    if (w30 && w7 && w30.lead_to_close_pct != null && w7.lead_to_close_pct != null) {
      const delta = w7.lead_to_close_pct - w30.lead_to_close_pct;
      if (Math.abs(delta) >= 2) {
        const dir = delta > 0 ? 'improving' : 'declining';
        summaryParts.push(`Close rate ${dir}: 7d (${w7.lead_to_close_pct}%) vs 30d (${w30.lead_to_close_pct}%)`);
      }
    }

    let summaryHtml = summaryParts.length > 0
      ? `<div class="perf-summary-text">${summaryParts.join('. ')}.</div>`
      : '';

    content.innerHTML = funnelHtml + metricsHtml + summaryHtml;
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

    const labels = trend.map(t => t.month);
    const values = trend.map(t => t.mrr);

    const pointRadius = trend.map((_, i) => i === currentIdx ? 5 : 2);
    const pointBg = trend.map((_, i) => {
      if (i === currentIdx) return '#3B82F6';
      if (i < currentIdx) return 'rgba(59,130,246,0.6)';
      return 'rgba(148,163,184,0.4)';
    });

    // Projection data
    const projection = ch.projection;
    let projLabels = [...labels];
    let baseData = [...values];
    let optimisticData = new Array(values.length).fill(null);
    let pessimisticData = new Array(values.length).fill(null);

    if (projection && projection.months_forward && projection.months_forward.length > 0) {
      // Connect projection to last actual data point
      const lastActualIdx = currentIdx >= 0 ? currentIdx : values.length - 1;
      optimisticData[lastActualIdx] = values[lastActualIdx];
      pessimisticData[lastActualIdx] = values[lastActualIdx];
      baseData[lastActualIdx] = values[lastActualIdx];

      projection.months_forward.forEach(m => {
        if (!projLabels.includes(m.month)) {
          projLabels.push(m.month);
          values.push(null);
          pointRadius.push(0);
          pointBg.push('transparent');
        }
        const idx = projLabels.indexOf(m.month);
        while (baseData.length <= idx) baseData.push(null);
        while (optimisticData.length <= idx) optimisticData.push(null);
        while (pessimisticData.length <= idx) pessimisticData.push(null);
        baseData[idx] = m.base;
        optimisticData[idx] = m.optimistic;
        pessimisticData[idx] = m.pessimistic;
      });
    }

    trendChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: projLabels,
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
        },
        // Projection: base (dashed blue)
        ...(projection && projection.months_forward ? [{
          data: baseData,
          borderColor: 'rgba(59,130,246,0.5)',
          borderWidth: 2,
          borderDash: [6, 3],
          pointRadius: 3,
          pointBackgroundColor: 'rgba(59,130,246,0.5)',
          pointBorderWidth: 0,
          fill: false,
          tension: 0.3,
        },
        // Projection: optimistic (green)
        {
          data: optimisticData,
          borderColor: 'rgba(34,197,94,0.4)',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 2,
          pointBackgroundColor: 'rgba(34,197,94,0.4)',
          pointBorderWidth: 0,
          fill: false,
          tension: 0.3,
        },
        // Projection: pessimistic (red)
        {
          data: pessimisticData,
          borderColor: 'rgba(239,68,68,0.4)',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 2,
          pointBackgroundColor: 'rgba(239,68,68,0.4)',
          pointBorderWidth: 0,
          fill: '-1',
          backgroundColor: 'rgba(239,68,68,0.05)',
          tension: 0.3,
        }] : [])]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) { return fmt$(ctx.parsed.y); }
            },
            filter: function(item, data) {
              // Deduplicate: hide if another dataset at same index has the same value
              var val = item.parsed.y;
              if (val === null || val === undefined) return false;
              for (var i = 0; i < item.datasetIndex; i++) {
                var otherVal = data.datasets[i].data[item.dataIndex];
                if (otherVal === val) return false;
              }
              return true;
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

    // Projection summary text — use a stable element, never append
    const projSummaryId = 'mrr-projection-summary';
    let summaryDiv = document.getElementById(projSummaryId);
    if (projection && projection.months_forward && projection.months_forward.length > 0) {
      if (!summaryDiv) {
        summaryDiv = document.createElement('div');
        summaryDiv.id = projSummaryId;
        summaryDiv.style.cssText = 'font-size:12px;color:var(--text-muted);padding:12px 0 0;line-height:1.6;';
        ctx.parentElement.appendChild(summaryDiv);
      }
      const parts = [];
      const latestRate = projection.growth_rate_latest;
      const avgRate = projection.growth_rate_3mo_avg;
      if (latestRate != null && latestRate !== 0) {
        parts.push(`Latest: <strong style="color:var(--accent)">${latestRate}%/mo</strong>`);
        if (avgRate != null && avgRate !== latestRate) {
          parts.push(`3mo avg: ${avgRate}%/mo`);
        }
      } else if (avgRate != null && avgRate !== 0) {
        parts.push(`Growing <strong style="color:var(--accent)">${avgRate}%/mo</strong> (3mo avg)`);
      }
      if (projection.decelerating) {
        parts.push(`<span style="color:var(--amber)">⚠ decelerating</span>`);
      }
      const lastProj = projection.months_forward[projection.months_forward.length - 1];
      if (lastProj) {
        parts.push(`Projected <strong>${fmt$(lastProj.base)}</strong> by ${lastProj.month}`);
      }
      if (projection.churn_risk_mrr > 0) {
        parts.push(`Risk: <span style="color:var(--red)">${fmt$(projection.churn_risk_mrr)}/mo</span> from expiring contracts`);
      }
      if (projection.growth_flag) {
        parts.push(`<span style="color:var(--red)">⚠ ${projection.growth_flag}</span>`);
      }
      summaryDiv.innerHTML = parts.join(' · ');
    } else if (summaryDiv) {
      summaryDiv.remove();
    }
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

    const parts = [];
    if (stripeCash != null && xeroPL != null) {
      const diff = stripeCash - xeroPL;
      const absDiff = Math.abs(diff);
      const dir = diff >= 0 ? '+' : '-';
      const pctDiff = Math.round(absDiff / Math.max(stripeCash, xeroPL, 1) * 100);
      parts.push(`Stripe ${dir}${fmt$(absDiff)} vs Xero (${pctDiff}% gap) — Stripe = cash collected, Xero = accrual-recognised. Gap is normal: timing, Stripe fees, and recognition period differences.`);
    }
    if (rv.recognized_month) {
      parts.push(`Recognized: ${rv.recognized_month} (${rv.recognized_client_count || '?'} clients)`);
    }
    note.textContent = parts.join(' \u00b7 ') || 'Same money, different lenses — never sum these.';
  }

  // ── Churn Risk ────────────────────────────────────────────
  function renderChurnRisk(snap) {
    const ch = snap.client_health || {};
    const atRisk = ch.at_risk || [];
    const renewalWatch = ch.renewal_watch || [];
    const badge = $('#churn-badge');
    const summary = $('#churn-summary');
    const list = $('#churn-list');

    if (atRisk.length === 0 && renewalWatch.length === 0) {
      badge.textContent = 'Clear';
      badge.style.background = 'var(--green-dim)';
      badge.style.color = 'var(--green)';
      summary.innerHTML = '';
      list.innerHTML = '<div class="churn-empty">No contracts expiring in the next 60 days</div>';
      return;
    }

    const totalFlags = atRisk.length + renewalWatch.length;
    if (atRisk.length > 0) {
      badge.textContent = atRisk.length + ' at risk';
      badge.style.background = 'var(--red-dim)';
      badge.style.color = 'var(--red)';
    } else {
      badge.textContent = renewalWatch.length + ' renewal' + (renewalWatch.length > 1 ? 's' : '');
      badge.style.background = 'var(--amber-dim)';
      badge.style.color = 'var(--amber)';
    }

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

    list.innerHTML = '';
    atRisk.forEach(c => {
      const row = document.createElement('div');
      row.className = 'churn-row ' + c.risk_level;
      let daysText = c.risk_level === 'expired' ? 'Expired' : c.days_remaining + 'd left';
      row.innerHTML = `
        <span class="churn-client">${esc(c.name)}</span>
        <span class="churn-days ${c.risk_level}">${daysText}</span>
        <span class="churn-revenue">${fmt$(c.monthly_revenue)}/mo</span>
      `;
      list.appendChild(row);
    });

    // ── Renewal Watch Panel ──────────────────────────────────
    if (renewalWatch.length > 0) {
      const renewalHeader = document.createElement('div');
      renewalHeader.style.cssText = 'margin-top:1.2rem;padding:0.6rem 0;border-top:1px solid var(--border);font-weight:600;font-size:0.95rem;color:var(--amber);';
      renewalHeader.textContent = 'Renewal Watch';
      list.appendChild(renewalHeader);

      renewalWatch.forEach(c => {
        const row = document.createElement('div');
        const isUrgent = c.status === 'renewal_urgent';
        const color = isUrgent ? 'var(--red)' : 'var(--amber)';
        row.className = 'churn-row';
        row.style.borderLeft = '3px solid ' + color;
        const statusLabel = isUrgent ? 'URGENT' : 'PREP';
        row.innerHTML = `
          <span class="churn-client">${esc(c.name)}</span>
          <span class="churn-days" style="color:${color}">${c.months_elapsed}/${c.total_months} mo \u00b7 ${c.days_until_renewal}d left</span>
          <span class="churn-revenue">${fmt$(c.monthly_revenue)}/mo</span>
          <span style="font-size:0.7rem;padding:2px 6px;border-radius:4px;background:${isUrgent ? 'var(--red-dim)' : 'var(--amber-dim)'};color:${color};margin-left:0.4rem">${statusLabel}</span>
        `;
        list.appendChild(row);
      });
    }
  }

  // ── Client Reconciliation ────────────────────────────────
  function renderReconciliation(snap) {
    const recon = snap.client_reconciliation || {};
    const missing = recon.missing_from_health || [];
    const zeroMrr = recon.zero_mrr_active || [];
    const prepaid = recon.prepaid_active || [];
    const section = $('#section-reconciliation');
    const badge = $('#recon-badge');
    const content = $('#recon-content');

    const totalIssues = missing.length + zeroMrr.length;
    const hasContent = totalIssues > 0 || prepaid.length > 0;
    if (!hasContent) {
      section.style.display = 'none';
      return;
    }

    section.style.display = '';
    if (totalIssues > 0) {
      badge.textContent = totalIssues + ' issue' + (totalIssues > 1 ? 's' : '');
      badge.style.background = 'var(--red-dim)';
      badge.style.color = 'var(--red)';
    } else {
      badge.textContent = 'Clear';
      badge.style.background = 'var(--green-dim)';
      badge.style.color = 'var(--green)';
    }

    let html = '';

    if (missing.length > 0) {
      html += '<div class="recon-section">';
      html += '<div class="recon-section-title">Won deals missing from Health tab</div>';
      missing.forEach(m => {
        const details = [m.offer, m.close_date].filter(Boolean).join(' \u00b7 ');
        html += `<div class="recon-row missing">
          <span class="recon-name">${esc(m.name)}</span>
          <span class="recon-detail">${esc(details)}</span>
          <span class="recon-value" style="color:var(--red)">${m.contract_value ? fmt$(m.contract_value) : '—'}</span>
        </div>`;
      });

      const estMissing = recon.estimated_missing_mrr || 0;
      if (estMissing > 0) {
        html += `<div class="recon-impact">
          <strong>MRR is understated</strong> — these ${missing.length} client(s) represent an estimated
          <strong>${fmt$(estMissing)}/mo</strong> not reflected in the Health tab.
        </div>`;
      }
      html += '</div>';
    }

    if (zeroMrr.length > 0) {
      html += '<div class="recon-section">';
      html += '<div class="recon-section-title">Active clients with $0 MRR (may be churned)</div>';
      zeroMrr.forEach(name => {
        html += `<div class="recon-row zero">
          <span class="recon-name">${esc(name)}</span>
          <span class="recon-detail">Listed as Active but $0 revenue this month</span>
          <span class="recon-value" style="color:var(--amber)">$0</span>
        </div>`;
      });
      html += '</div>';
    }

    if (prepaid.length > 0) {
      html += '<div class="recon-section">';
      html += '<div class="recon-section-title" style="color:var(--green)">Prepaid clients (contract active, $0 monthly MRR expected)</div>';
      prepaid.forEach(p => {
        const endDate = p.contract_end || 'unknown';
        const cv = p.contract_value ? fmt$(p.contract_value) : '\u2014';
        html += `<div class="recon-row" style="border-left:3px solid var(--green)">
          <span class="recon-name">${esc(p.name)}</span>
          <span class="recon-detail">Prepaid \u2014 contract active until ${esc(endDate)}</span>
          <span class="recon-value" style="color:var(--green)">${cv}</span>
        </div>`;
      });
      html += '</div>';
    }

    content.innerHTML = html;
  }

  // ── Derived Active Clients ─────────────────────────────
  function renderDerivedClients(snap) {
    const ac = snap.active_clients;
    if (!ac) return;

    // KPI headline = total clients, sub-text shows breakdown
    const confirmedActive = (ac.confirmed_both_sources || 0) + (ac.legacy_pre_tracker || 0);
    const signing = ac.pending_health_update || 0;
    const clientKPI = document.getElementById('val-clients');
    if (clientKPI) {
      clientKPI.textContent = ac.active_count || '—';
    }
    const clientSub = $('#sub-clients');
    if (clientSub) {
      if (signing > 0) {
        clientSub.textContent = confirmedActive + ' active, ' + signing + ' awaiting Stripe';
      } else {
        clientSub.textContent = confirmedActive + ' active';
      }
    }

    // Health badge
    const healthBadge = $('#health-badge');
    if (healthBadge) {
      healthBadge.textContent = signing > 0
        ? ac.active_count + ' clients (' + signing + ' awaiting Stripe)'
        : ac.active_count + ' clients';
      const conf = ac.confidence;
      healthBadge.style.background = conf === 'high' ? 'var(--green-dim)' : conf === 'medium' ? 'var(--amber-dim)' : 'var(--red-dim)';
      healthBadge.style.color = conf === 'high' ? 'var(--green)' : conf === 'medium' ? 'var(--amber)' : 'var(--red)';
    }

    // Show discrepancies in reconciliation panel
    const discs = ac.discrepancies || [];
    if (discs.length > 0) {
      const reconSection = $('#section-reconciliation');
      if (reconSection) reconSection.style.display = '';
      const reconBadge = $('#recon-badge');
      if (reconBadge) {
        reconBadge.textContent = discs.length + ' discrepanc' + (discs.length > 1 ? 'ies' : 'y');
        reconBadge.style.background = 'var(--amber-dim)';
        reconBadge.style.color = 'var(--amber)';
      }
    }

    // Stripe MRR validation
    const sv = ac.stripe_validation;
    if (sv) {
      const mrrSub = $('#sub-sheet-mrr');
      if (mrrSub && sv.gap_pct > 5) {
        // Don't override if already showing delta
      }
    }
  }

  // ── Client Health ────────────────────────────────────────
  function renderClientHealth(snap) {
    const ch = snap.client_health;
    const ac = snap.active_clients;
    const summary = $('#health-summary');
    const list = $('#client-list');
    const badge = $('#health-badge');

    // Use derived active clients if available, fall back to health tab
    const clients = ac ? ac.active : (ch ? ch.clients : null);

    if (!clients || clients.length === 0) {
      summary.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No client health data</div>';
      list.innerHTML = '';
      return;
    }

    const confirmedMRR = ac ? ac.confirmed_mrr : (ch ? ch.current_mrr : 0);
    const estimatedMRR = ac ? ac.estimated_mrr : 0;
    const projectedMRR = ac ? ac.projected_mrr : confirmedMRR;
    const nextMRR = ch ? ch.next_mrr : null;
    const mrrDelta = ch ? ch.mrr_delta : null;
    // badge is set by renderDerivedClients — only set fallback here
    if (!ac) {
      const clientCount = ch ? ch.total_clients : clients.length;
      badge.textContent = clientCount + ' clients';
    }

    let summaryHtml = `
      <div class="health-stat">
        <div class="health-stat-value" style="color:var(--text)">${fmt$(confirmedMRR)}</div>
        <div class="health-stat-label">Confirmed MRR</div>
      </div>`;
    if (estimatedMRR > 0) {
      summaryHtml += `
      <div class="health-stat">
        <div class="health-stat-value" style="color:var(--purple)">${fmt$(projectedMRR)}</div>
        <div class="health-stat-label">Projected MRR <span style="font-size:11px;opacity:0.7">(+${fmt$(estimatedMRR)} est.)</span></div>
      </div>`;
    }
    summaryHtml += `
      <div class="health-stat">
        <div class="health-stat-value" style="color:${(mrrDelta || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${fmt$(nextMRR)}</div>
        <div class="health-stat-label">Next month</div>
      </div>
      <div class="health-stat">
        <div class="health-stat-value" style="color:${(mrrDelta || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${mrrDelta != null ? (mrrDelta >= 0 ? '+' : '') + fmt$(mrrDelta) : '—'}</div>
        <div class="health-stat-label">MRR delta</div>
      </div>`;
    summary.innerHTML = summaryHtml;

    // Sort: confirmed MRR first (descending), then estimated MRR (new signings), then $0
    const sorted = [...clients].sort((a, b) => {
      const aMRR = a.current_mrr || a.estimated_mrr || 0;
      const bMRR = b.current_mrr || b.estimated_mrr || 0;
      return bMRR - aMRR || (b.contract_value || 0) - (a.contract_value || 0);
    });

    list.innerHTML = '';
    sorted.forEach(c => {
      const row = document.createElement('div');
      row.className = 'client-row';
      const isNew = c.source === 'ltc_tracker' || c.status === 'signed_not_in_health';
      const isLegacy = c.sources_agree === 'legacy';
      const hasZeroMRR = c.mrr_flag === 'active_zero_mrr';

      let badgeText, badgeCls;
      if (isNew && c.awaiting_stripe) { badgeText = 'Awaiting Stripe'; badgeCls = 'new'; }
      else if (isNew) { badgeText = 'New'; badgeCls = 'new'; }
      else if (c.status === 'Web Sub') { badgeText = 'Web'; badgeCls = 'websub'; }
      else { badgeText = 'Active'; badgeCls = 'active'; }

      const mrr = c.current_mrr || 0;
      let mrrText;
      if (mrr > 0) {
        mrrText = fmt$(mrr);
      } else if (c.prepaid_flag === 'prepaid_active') {
        mrrText = 'Prepaid \u2014 active until ' + (c.contract_end || '?');
      } else if (isNew && c.estimated_mrr) {
        mrrText = '~' + fmt$(c.estimated_mrr) + '/mo est.';
      } else if (isNew && c.contract_value) {
        mrrText = fmt$(c.contract_value) + ' contract';
      } else {
        mrrText = '$0';
      }
      const delta = (c.next_mrr || 0) - mrr;
      let deltaHtml = '';
      if (delta > 0) deltaHtml = `<span class="client-delta up">+${fmt$(delta)}</span>`;
      else if (delta < 0) deltaHtml = `<span class="client-delta down">${fmt$(delta)}</span>`;

      row.innerHTML = `
        <span class="client-name">${esc(c.name)}</span>
        <span class="client-badge ${badgeCls}">${badgeText}</span>
        <span class="client-mrr">${mrrText}</span>
        ${deltaHtml}
      `;
      if (hasZeroMRR && c.prepaid_flag !== 'prepaid_active') row.style.opacity = '0.6';
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
    // Use window data if non-30d selected
    const windows = get(snap, 'sales.windows') || [];
    const windowData = currentWindow !== 30 ? windows.find(w => w.window_days === currentWindow) : null;
    const f = windowData || get(snap, 'sales.funnel') || {};
    const funnelLabel = $('#funnel-window-label');
    if (funnelLabel) funnelLabel.textContent = 'trailing ' + currentWindow + 'd';
    const stages = [
      { label: 'Leads', count: windowData ? f.leads : f.leads_in, pct: null },
      { label: 'Sets', count: windowData ? f.sets : f.sets, pct: windowData ? f.lead_to_set_pct : f.lead_to_set_pct },
      { label: 'Shows', count: windowData ? f.shows : f.shows, pct: windowData ? f.set_to_show_pct : f.set_to_show_pct },
      { label: 'Closes', count: windowData ? f.closes : f.closes, pct: windowData ? f.show_to_close_pct : f.show_to_close_pct },
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
    const hasSpend = adSpend != null && adSpend > 0;

    let html = `<div class="lead-roi-row header">
      <span>Source</span><span class="num">Leads</span><span class="num">Sets</span>
      <span class="num">Closes</span><span class="num">Close%</span>
      <span class="num">${hasSpend ? 'Cost/Close' : 'DQ%'}</span>
    </div>`;

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

    const parts = [];
    if (hasSpend) parts.push(`Total ad spend: ${fmt$(adSpend)} (trailing 30d)`);
    if (totalCloses > 0 && hasSpend) parts.push(`Blended cost/close: ${fmt$(adSpend / totalCloses)}`);
    parts.push('Spend allocated proportional to lead volume by source');
    note.textContent = parts.join(' \u00b7 ');
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

    let html = '';
    perCloser.forEach(c => {
      if (!c.commission_total) return;
      html += `<div class="comm-row">
        <span class="comm-name">${esc(c.name)}</span>
        <span class="comm-role closer">Closer</span>
        <span class="comm-detail">${c.closes ?? 0} closes @ ${c.close_rate_pct ?? '—'}%</span>
        <span class="comm-amount">${fmt$(c.commission_total)}</span>
      </div>`;
    });
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
    // Use per-window data if non-30d window selected
    const windows = get(snap, 'sales.windows') || [];
    const windowData = currentWindow !== 30 ? windows.find(w => w.window_days === currentWindow) : null;
    const setters = (windowData && windowData.per_setter) || get(snap, 'sales.deep.setter_performance') || get(snap, 'sales.per_setter') || [];
    const tbody = document.querySelector('#table-setters tbody');
    tbody.innerHTML = '';

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
    // Use per-window data if non-30d window selected
    const windows = get(snap, 'sales.windows') || [];
    const windowData = currentWindow !== 30 ? windows.find(w => w.window_days === currentWindow) : null;
    const closers = (windowData && windowData.per_closer) || get(snap, 'sales.per_closer') || [];
    const tbody = document.querySelector('#table-closers tbody');
    tbody.innerHTML = '';

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

  // ── Commission Detail (from Payout Log + Closer Detail) ──
  function renderCommissionDetail(snap) {
    const container = document.getElementById('commission-detail-expanded');
    if (!container) return;

    const detail = get(snap, 'sales.commission_detail');
    if (!detail) {
      container.innerHTML = '';
      return;
    }

    const hasSetters = detail.per_setter && detail.per_setter.length > 0;
    const hasCloser = detail.closer && detail.closer.deals && detail.closer.deals.length > 0;
    const payoutStatus = detail.payout_status;

    if (!hasSetters && !hasCloser) {
      container.innerHTML = '';
      return;
    }

    let html = '';

    // ── Payout Status Summary ──────────────────────────────
    if (payoutStatus) {
      html += `<div class="comm-detail-section" style="margin-bottom:12px;">
        <div class="comm-detail-title">Payout Status</div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;padding:8px 0;">
          <div class="comm-stat" style="flex:1;min-width:120px;">
            <div class="comm-stat-value" style="color:var(--amber)">${fmt$(payoutStatus.grand_total_owed)}</div>
            <div class="comm-stat-label">Total Owed</div>
          </div>
          <div class="comm-stat" style="flex:1;min-width:120px;">
            <div class="comm-stat-value" style="color:var(--green)">${fmt$(payoutStatus.setter_paid)}</div>
            <div class="comm-stat-label">Setter Paid</div>
          </div>
          <div class="comm-stat" style="flex:1;min-width:120px;">
            <div class="comm-stat-value" style="color:var(--red)">${fmt$(payoutStatus.setter_pending)}</div>
            <div class="comm-stat-label">Setter Pending</div>
          </div>
          <div class="comm-stat" style="flex:1;min-width:120px;">
            <div class="comm-stat-value" style="color:var(--amber)">${fmt$(payoutStatus.closer_owed)}</div>
            <div class="comm-stat-label">Closer Owed</div>
          </div>
        </div>
      </div>`;
    }

    // ── Cross-check warnings ──────────────────────────────
    const crossChecks = detail.cross_checks;
    if (crossChecks && crossChecks.length > 0) {
      html += '<div style="margin-bottom:10px;">';
      crossChecks.forEach(function(msg) {
        html += '<div style="font-size:11px;color:var(--amber);padding:2px 0;">&#9888; ' + esc(msg) + '</div>';
      });
      html += '</div>';
    }

    // ── Setter Payout Detail ──────────────────────────────
    if (hasSetters) {
      html += '<div class="comm-detail-section"><div class="comm-detail-title">Setter Payout Detail</div>';

      detail.per_setter.forEach(function(setter) {
        const deals = setter.deals || [];
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - currentWindow);
        const filteredDeals = currentWindow !== 30
          ? deals.filter(function(d) { return d.date && new Date(d.date) >= cutoff; })
          : deals;

        const cardId = 'setter-card-' + esc(setter.name).replace(/\s/g, '-');
        html += '<div class="comm-setter-card" id="' + cardId + '">';
        html += '<div class="comm-setter-header" onclick="this.parentElement.classList.toggle(\'expanded\')" style="cursor:pointer;">';
        html += '<span class="comm-setter-name">' + esc(setter.name) + ' <span style="font-size:10px;color:var(--text-muted);">(' + (setter.sets_count || deals.length) + ' deals)</span></span>';
        html += '<div class="comm-setter-totals">';
        html += '<span>Owed: <strong style="color:var(--amber)">' + fmt$(setter.total_owed) + '</strong></span>';
        html += '<span>Paid: <strong style="color:var(--green)">' + fmt$(setter.total_paid) + '</strong></span>';
        html += '<span>Due: <strong style="color:var(--red)">' + fmt$(setter.still_due) + '</strong></span>';
        html += '</div></div>';

        html += '<div class="comm-setter-deals">';
        if (filteredDeals.length > 0) {
          html += '<table class="comm-deal-table"><thead><tr>';
          html += '<th>Date</th><th>Business</th><th>Status</th><th>Cash</th><th>Fee</th><th>Total</th><th>Paid</th>';
          html += '</tr></thead><tbody>';
          filteredDeals.forEach(function(d) {
            html += '<tr>';
            html += '<td>' + esc(d.date) + '</td>';
            html += '<td>' + esc(d.business) + '</td>';
            html += '<td>' + (d.won ? '<span style="color:var(--green)">Won</span>' : esc(d.show_status)) + '</td>';
            html += '<td>' + fmt$(d.cash_collected) + '</td>';
            html += '<td>' + fmt$(d.set_fee) + '</td>';
            html += '<td>' + fmt$(d.total_owed) + '</td>';
            html += '<td>' + (esc(d.paid_status) || '\u2014') + '</td>';
            html += '</tr>';
          });
          html += '</tbody></table>';
        } else {
          html += '<div style="font-size:11px;color:var(--text-muted);padding:4px 0;">No deals in ' + currentWindow + 'd window</div>';
        }
        html += '</div></div>';
      });

      html += '</div>';
    }

    // ── Closer Payout Detail ──────────────────────────────
    if (hasCloser) {
      const closer = detail.closer;
      html += '<div class="comm-detail-section"><div class="comm-detail-title">Closer Payout Detail';
      if (closer.closer_name) html += ' \u2014 ' + esc(closer.closer_name);
      html += '</div>';

      html += '<div style="display:flex;gap:12px;flex-wrap:wrap;padding:4px 0 8px;">';
      html += '<span style="font-size:12px;">Deals: <strong>' + closer.deal_count + '</strong></span>';
      html += '<span style="font-size:12px;">Commission (sheet): <strong style="color:var(--amber)">' + fmt$(closer.total_commission_sheet) + '</strong></span>';
      html += '<span style="font-size:12px;">Expected (rate table): <strong style="color:var(--text-muted)">' + fmt$(closer.total_commission_expected) + '</strong></span>';
      html += '</div>';

      const closerDeals = closer.deals || [];
      const cutoff2 = new Date();
      cutoff2.setDate(cutoff2.getDate() - currentWindow);
      const filteredCloserDeals = currentWindow !== 30
        ? closerDeals.filter(function(d) { return d.date && new Date(d.date) >= cutoff2; })
        : closerDeals;

      if (filteredCloserDeals.length > 0) {
        html += '<table class="comm-deal-table"><thead><tr>';
        html += '<th>Date</th><th>Business</th><th>Offer</th><th>Cash</th><th>Comm (Sheet)</th><th>Comm (Expected)</th><th>Match</th>';
        html += '</tr></thead><tbody>';
        filteredCloserDeals.forEach(function(d) {
          var match;
          if (d.mismatch) {
            match = '<span style="color:var(--red)" title="' + esc(d.mismatch) + '">&#10007;</span>';
          } else if (d.commission_expected != null) {
            match = '<span style="color:var(--green)">&#10003;</span>';
          } else {
            match = '<span style="color:var(--text-muted)">\u2014</span>';
          }
          html += '<tr>';
          html += '<td>' + esc(d.date) + '</td>';
          html += '<td>' + esc(d.business) + '</td>';
          html += '<td>' + esc(d.offer) + '</td>';
          html += '<td>' + fmt$(d.cash_collected) + '</td>';
          html += '<td>' + fmt$(d.commission_sheet) + '</td>';
          html += '<td>' + (d.commission_expected != null ? fmt$(d.commission_expected) : '<span style="color:var(--text-muted)">N/A</span>') + '</td>';
          html += '<td>' + match + '</td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
      } else {
        html += '<div style="font-size:11px;color:var(--text-muted);padding:4px 0;">No closer deals in ' + currentWindow + 'd window</div>';
      }
      html += '</div>';
    }

    // ── Paid log timeline ──────────────────────────────────
    if (detail.paid_log && detail.paid_log.length > 0) {
      html += '<div class="comm-paid-log"><div class="comm-detail-title">Payment Log</div>';
      detail.paid_log.forEach(function(p) {
        html += '<div class="comm-paid-entry">';
        html += '<span>' + esc(p.date_paid) + '</span>';
        html += '<span>' + esc(p.deal_name) + '</span>';
        html += '<span>' + esc(p.what_paid) + '</span>';
        html += '<span class="amount">' + fmt$(p.amount) + '</span>';
        html += '</div>';
      });
      html += '</div>';
    }

    container.innerHTML = html;
  }

  // ── Cohort Retention ─────────────────────────────────────
  function renderCohortRetention(snap) {
    const container = $('#cohort-grid');
    const ch = snap.client_health;
    if (!ch || !ch.clients || ch.clients.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No client data for cohort analysis</div>';
      return;
    }

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

    const sortedKeys = Object.keys(cohorts).sort();

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

    const displayCols = monthCols.slice(-12);

    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    function fmtMonth(key) {
      if (key === 'Unknown') return 'Unknown';
      const [y, m] = key.split('-').map(Number);
      return monthNames[m - 1] + ' ' + String(y).slice(2);
    }

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
        if (key === 'Unknown' || col < key) {
          html += '<td><span class="cohort-cell empty">—</span></td>';
          return;
        }

        const active = clients.filter(c => {
          if ((c.current_mrr || 0) <= 0 && col === currentKey) return false;
          if (c.contract_end) {
            const endKey = c.contract_end.slice(0, 7);
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

  // ── Growth Constraints (Deficiency Analysis) ────────────
  function renderDeficiency(snap) {
    var body = document.getElementById('deficiency-body');
    if (!body) return;
    var da = snap.deficiency_analysis;
    if (!da || !da.deficiencies || da.deficiencies.length === 0) {
      body.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:12px;">No deficiency data available</div>';
      return;
    }

    var html = '';

    // Interaction insights (compound effects)
    if (da.interaction_insights && da.interaction_insights.length > 0) {
      html += '<div style="background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.2);border-radius:8px;padding:10px 14px;margin-bottom:12px;">';
      html += '<div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px;">KEY INSIGHT</div>';
      da.interaction_insights.forEach(function(insight) {
        html += '<div style="font-size:12px;line-height:1.5;color:var(--text);">' + esc(insight) + '</div>';
      });
      html += '</div>';
    }

    // Ranked deficiencies
    da.deficiencies.forEach(function(d, i) {
      var sevColor = d.severity === 'critical' ? 'var(--red)' : d.severity === 'high' ? 'var(--amber)' : 'var(--text-muted)';
      html += '<div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border);">';
      html += '<span style="font-weight:700;color:' + sevColor + ';min-width:18px;font-size:13px;">' + (i + 1) + '</span>';
      html += '<div style="flex:1;">';
      html += '<div style="font-size:13px;font-weight:600;color:var(--text);">' + esc(d.name) + ' <span style="font-size:11px;color:var(--text-muted);">(' + esc(d.category) + ')</span></div>';
      html += '<div style="font-size:12px;color:var(--text-muted);margin-top:2px;">Current: <strong>' + esc(d.current) + '</strong> → Target: ' + esc(d.target) + '</div>';
      if (d.impact) html += '<div style="font-size:12px;color:' + sevColor + ';margin-top:2px;">' + esc(d.impact) + '</div>';
      if (d.fix) html += '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Fix: ' + esc(d.fix) + '</div>';
      html += '</div></div>';
    });

    body.innerHTML = html;
  }

  // ── Team Model + Hiring ─────────────────────────────────
  function renderTeamModel(snap) {
    var body = document.getElementById('team-body');
    if (!body) return;
    var tm = snap.team_model;
    var hc = snap.hiring_context;
    if (!tm || !tm.available) {
      body.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:12px;">Team data not available</div>';
      return;
    }

    var html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px;">';
    html += '<div class="kpi"><div class="kpi-label">Team Size</div><div class="kpi-value">' + tm.headcount + '</div></div>';
    html += '<div class="kpi"><div class="kpi-label">Team Salary</div><div class="kpi-value">' + fmt$(tm.total_team_salary) + '</div><div class="kpi-sub">/mo (excl. owner)</div></div>';
    html += '<div class="kpi"><div class="kpi-label">Total w/ Owner</div><div class="kpi-value">' + fmt$(tm.total_with_owner) + '</div><div class="kpi-sub">/mo</div></div>';
    if (hc && hc.monthly_headroom != null) {
      html += '<div class="kpi"><div class="kpi-label">Monthly Headroom</div><div class="kpi-value' + (hc.monthly_headroom < 0 ? ' critical' : '') + '">' + fmt$(hc.monthly_headroom) + '</div><div class="kpi-sub">/mo after costs</div></div>';
    }
    html += '</div>';

    // By function breakdown
    html += '<div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:6px;">By Function</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:6px;">';
    for (var fn in tm.by_function) {
      var fd = tm.by_function[fn];
      var isSPOF = (tm.single_points_of_failure || []).indexOf(fn) >= 0;
      html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:6px;padding:8px 10px;' + (isSPOF ? 'border-left:3px solid var(--amber);' : '') + '">';
      html += '<div style="font-size:11px;font-weight:700;color:var(--text);text-transform:uppercase;">' + esc(fn.replace(/_/g, ' ')) + '</div>';
      html += '<div style="font-size:12px;color:var(--text-muted);">' + fd.headcount + ' people · ' + fmt$(fd.total) + '/mo</div>';
      if (isSPOF) html += '<div style="font-size:10px;color:var(--amber);margin-top:2px;">⚠ single point of failure</div>';
      html += '</div>';
    }
    html += '</div>';

    body.innerHTML = html;
  }

  // ── Hiring Scenario Form Handler ──────────────────────
  function initHiringForm() {
    var btn = document.getElementById('hire-submit');
    if (!btn) return;
    btn.addEventListener('click', function() {
      var role = document.getElementById('hire-role').value.trim() || 'New hire';
      var cost = parseFloat(document.getElementById('hire-cost').value) || 0;
      var isRevenue = document.getElementById('hire-revenue').checked;
      var resultDiv = document.getElementById('hiring-result');
      if (cost <= 0) {
        resultDiv.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">Enter a monthly cost</div>';
        return;
      }
      resultDiv.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">Analyzing...</div>';

      fetch('/dashboard/api/hiring-scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: role, monthly_cost: cost, is_revenue_generating: isRevenue }),
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) {
          resultDiv.innerHTML = '<div style="color:var(--red);font-size:12px;">' + esc(data.error) + '</div>';
          return;
        }
        var html = '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.6;">';
        html += '<div style="font-weight:700;margin-bottom:6px;">' + esc(data.proposed_role) + ' @ ' + fmt$(data.proposed_cost) + '/mo</div>';
        html += '<div>Can afford: <strong style="color:' + (data.can_afford ? 'var(--green)' : 'var(--red)') + '">' + (data.can_afford ? 'Yes' : 'No') + '</strong></div>';
        html += '<div>Headroom after hire: <strong>' + fmt$(data.headroom_after_hire) + '/mo</strong></div>';
        if (data.additional_closes_needed != null) {
          html += '<div>Needs <strong>' + data.additional_closes_needed + ' closes/mo</strong> to self-fund</div>';
        }
        if (data.cost_as_pct_of_mrr != null) {
          html += '<div>Team cost would be <strong>' + data.cost_as_pct_of_mrr + '%</strong> of MRR (target: &lt;40%)</div>';
        }
        html += '<div>MRR threshold for this hire: <strong>' + fmt$(data.mrr_threshold_for_hire) + '</strong></div>';
        html += '<div style="font-size:11px;color:var(--text-muted);margin-top:6px;font-style:italic;">' + esc(data.note) + '</div>';
        html += '</div>';
        resultDiv.innerHTML = html;
      })
      .catch(function(e) {
        resultDiv.innerHTML = '<div style="color:var(--red);font-size:12px;">Failed: ' + e.message + '</div>';
      });
    });
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

  // ── Section Navigation (scroll spy) ─────────────────────
  function initNavigation() {
    const nav = $('#section-nav');
    if (!nav) return;

    // Smooth scroll
    nav.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', function(e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });

    // Scroll spy
    const sections = Array.from(nav.querySelectorAll('.nav-link')).map(link => {
      const id = link.getAttribute('href').slice(1);
      return { link, el: document.getElementById(id) };
    }).filter(s => s.el);

    let ticking = false;
    window.addEventListener('scroll', function() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function() {
        const scrollY = window.scrollY + 120;
        let activeIdx = 0;
        sections.forEach((s, i) => {
          if (s.el.offsetTop <= scrollY) activeIdx = i;
        });
        sections.forEach((s, i) => {
          s.link.classList.toggle('active', i === activeIdx);
        });
        ticking = false;
      });
    });
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
    initNavigation();
    initGlobalWindowSelector();
    initHiringForm();
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
