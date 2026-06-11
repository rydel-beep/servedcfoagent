/* dashboard.js v4 — Full executive dashboard with all features */
(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  let currentSnap = null;
  let historyData = null;
  let refreshCooldown = false;

  // ── Helpers ──────────────────────────────────────────────
  // Number craft: currency 0dp, thousands-separated; raw floats never render.
  function fmt$(v) {
    if (v == null) return '—';
    const n = Number(v);
    if (isNaN(n) || !isFinite(n)) return '—';
    return '$' + n.toLocaleString('en-AU', {maximumFractionDigits: 0});
  }
  function fmtPct(v) { return v != null && isFinite(Number(v)) ? v + '%' : '—'; }
  function fmtX(v) { return v != null && isFinite(Number(v)) ? v + '\u00d7' : '—'; }
  function fmtDays(v) { return v != null && isFinite(Number(v)) ? Math.round(v) + 'd' : '—'; }
  function fmtK(v) {
    if (v == null) return '—';
    const n = Number(v);
    if (isNaN(n) || !isFinite(n)) return '—';
    if (Math.abs(n) >= 1000) return '$' + (n/1000).toFixed(1) + 'k';
    return '$' + n.toFixed(0);
  }
  function fmtDelta(v, formatter) {
    if (v == null || isNaN(Number(v)) || !isFinite(Number(v))) return '';
    const f = formatter || fmt$;
    const n = Number(v);
    const cls = n > 0 ? 'delta-up' : (n < 0 ? 'delta-down' : 'delta-flat');
    const sign = n > 0 ? '+' : (n < 0 ? '−' : '');
    return '<span class="' + cls + '">' + sign + f(Math.abs(n)) + '</span>';
  }

  // ── Chart system: one consistent style for every chart ──
  const CHART = {
    brand: '#5B9BD0',
    brandSoft: 'rgba(91,155,208,0.6)',
    brandFillTop: 'rgba(91,155,208,0.12)',
    green: '#34C98E',
    amber: '#E8B445',
    red: '#E8616B',
    grid: 'rgba(122,154,191,0.10)',
    tick: '#71889F',
  };
  if (window.Chart) {
    Chart.defaults.font.family = "'Archivo', -apple-system, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = CHART.tick;
    Chart.defaults.borderColor = CHART.grid;
    Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(14,24,40,0.95)';
    Chart.defaults.plugins.tooltip.borderColor = 'rgba(122,154,191,0.28)';
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.titleColor = '#E8EFF6';
    Chart.defaults.plugins.tooltip.bodyColor = '#A7BCD2';
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.displayColors = false;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.boxHeight = 10;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
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


  // ── Stage E: KPI trends, chat chips, command palette, count-ups ──

  function _historySeries(field) {
    if (!historyData) return [];
    return historyData.map(function(h) { return h[field]; }).filter(function(v) { return v != null; });
  }

  function renderKpiTrends() {
    if (!historyData || historyData.length < 2) return;
    var last = historyData[historyData.length - 1];
    var prev = historyData[historyData.length - 2];
    var defs = [
      { sub: 'sub-sheet-mrr', field: 'mrr', fmt: fmt$ },
      { kpi: 'kpi-cash', field: 'stripe_collected_30d', fmt: fmt$ },
      { sub: 'sub-clients', field: 'active_clients', fmt: function(v) { return String(Math.round(v)); } },
    ];
    defs.forEach(function(d) {
      var series = _historySeries(d.field);
      if (series.length < 2) return;
      var delta = (last[d.field] != null && prev[d.field] != null) ? last[d.field] - prev[d.field] : null;
      var holder = d.sub ? document.getElementById(d.sub) : document.querySelector('#' + d.kpi + ' .kpi-sub');
      if (!holder) return;
      var old = holder.querySelector('.kpi-trend');
      if (old) old.remove();
      var span = document.createElement('span');
      span.className = 'kpi-trend';
      var spark = sparklineSVG(series.slice(-14), 'rgba(91,155,208,0.8)');
      span.innerHTML = ' ' + spark + (delta ? ' ' + fmtDelta(delta, d.fmt) + ' <span style="color:var(--text-muted)">1d</span>' : '');
      holder.appendChild(span);
    });
  }

  // Context-aware Jarvis suggested questions
  function renderChatChips(snap) {
    var wrap = document.getElementById('chat-chips');
    if (!wrap) return;
    var chips = ["What's our real runway?"];
    var ch = snap.client_health || {};
    if ((ch.revenue_at_risk_30d || 0) > 0 || (ch.mrr_delta || 0) < -1000) {
      chips.push('What if 50% of expiring clients re-sign?');
    }
    var hc = snap.hiring_context || {};
    if ((hc.monthly_net_income || 0) > 3000) {
      chips.push('Can I afford the creative hire?');
    } else {
      chips.push('What has to change before I can hire?');
    }
    var def = (snap.deficiency_analysis || {}).binding_constraint;
    if (def && def.name) chips.push('How do I fix ' + def.name.toLowerCase() + '?');
    chips.push('What moved since yesterday?');
    wrap.innerHTML = chips.slice(0, 4).map(function(c) {
      return '<button class="chat-chip" data-q="' + esc(c) + '">' + esc(c) + '</button>';
    }).join('');
  }

  // Number count-up on first load only — subtle, 500ms
  var _countedUp = false;
  function countUpKpis() {
    if (_countedUp) return;
    _countedUp = true;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    document.querySelectorAll('.kpi-value, .brief-cash-value').forEach(function(el) {
      var text = el.textContent || '';
      var m = text.match(/^\$?([\d,]+)/);
      if (!m) return;
      var target = parseInt(m[1].replace(/,/g, ''), 10);
      if (!target || target < 10) return;
      var prefix = text.startsWith('$') ? '$' : '';
      var suffix = text.slice(m[0].length);
      var start = null;
      function step(ts) {
        if (!start) start = ts;
        var p = Math.min((ts - start) / 500, 1);
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = prefix + Math.round(target * eased).toLocaleString('en-AU') + suffix;
        if (p < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }

  // ── Cmd+K command palette ──
  var _paletteOpen = false;
  var _paletteItems = [];

  function _buildPaletteItems() {
    var items = [];
    document.querySelectorAll('.nav-link').forEach(function(a) {
      items.push({ label: 'Go to ' + a.textContent, hint: 'section', run: function() { a.click(); } });
    });
    items.push({ label: 'Refresh data', hint: 'action', run: function() { var b = $('#btn-refresh'); if (b) b.click(); } });
    items.push({ label: 'Download CFO briefing PDF', hint: 'action', run: function() { var b = $('#btn-briefing-pdf'); if (b) b.click(); } });
    items.push({ label: 'Export sales summary', hint: 'action', run: function() { var b = $('#btn-export-sales'); if (b) b.click(); } });
    items.push({ label: 'Ask Jarvis\u2026', hint: '/ to chat', run: function() { var b = $('#btn-chat-toggle'); if (b) b.click(); } });
    return items;
  }

  function _ensurePalette() {
    if (document.getElementById('cmdk-overlay')) return;
    var overlay = document.createElement('div');
    overlay.id = 'cmdk-overlay';
    overlay.className = 'cmdk-overlay';
    overlay.innerHTML = '<div class="cmdk"><input id="cmdk-input" class="cmdk-input" placeholder="Jump to a section or run a command\u2026" autocomplete="off"><div id="cmdk-list" class="cmdk-list"></div><div class="cmdk-hint">\u2191\u2193 navigate \u00b7 Enter run \u00b7 Esc close \u00b7 shortcuts: g c cash, g f funnel, / chat</div></div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function(e) { if (e.target === overlay) togglePalette(false); });
    var input = document.getElementById('cmdk-input');
    var sel = 0;
    function refresh() {
      var q = input.value.toLowerCase();
      var list = document.getElementById('cmdk-list');
      var matches = _paletteItems.filter(function(it) { return it.label.toLowerCase().indexOf(q) !== -1; });
      if (sel >= matches.length) sel = Math.max(0, matches.length - 1);
      list.innerHTML = matches.map(function(it, i) {
        return '<div class="cmdk-item' + (i === sel ? ' active' : '') + '" data-i="' + i + '">' + esc(it.label) + '<span class="cmdk-item-hint">' + esc(it.hint) + '</span></div>';
      }).join('') || '<div class="cmdk-empty">No matches</div>';
      list.querySelectorAll('.cmdk-item').forEach(function(el) {
        el.addEventListener('click', function() {
          var it = matches[parseInt(this.dataset.i)];
          togglePalette(false);
          if (it) it.run();
        });
      });
      return matches;
    }
    input.addEventListener('input', function() { sel = 0; refresh(); });
    input.addEventListener('keydown', function(e) {
      var matches = _paletteItems.filter(function(it) { return it.label.toLowerCase().indexOf(input.value.toLowerCase()) !== -1; });
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, matches.length - 1); refresh(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); refresh(); }
      else if (e.key === 'Enter') { e.preventDefault(); var it = matches[sel]; togglePalette(false); if (it) it.run(); }
      else if (e.key === 'Escape') { togglePalette(false); }
    });
    overlay._refresh = refresh;
  }

  function togglePalette(open) {
    _ensurePalette();
    var overlay = document.getElementById('cmdk-overlay');
    _paletteOpen = open != null ? open : !_paletteOpen;
    overlay.classList.toggle('open', _paletteOpen);
    if (_paletteOpen) {
      _paletteItems = _buildPaletteItems();
      var input = document.getElementById('cmdk-input');
      input.value = '';
      overlay._refresh();
      setTimeout(function() { input.focus(); }, 30);
    }
  }

  function initKeyboardShortcuts() {
    var gPending = false, gTimer = null;
    document.addEventListener('keydown', function(e) {
      var tag = (document.activeElement || {}).tagName;
      var typing = tag === 'INPUT' || tag === 'TEXTAREA' || _paletteOpen;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); togglePalette(); return;
      }
      if (typing) return;
      if (e.key === '/') {
        e.preventDefault();
        var b = $('#btn-chat-toggle'); if (b) b.click();
        return;
      }
      if (e.key === 'g') {
        gPending = true;
        clearTimeout(gTimer);
        gTimer = setTimeout(function() { gPending = false; }, 800);
        return;
      }
      if (gPending) {
        gPending = false;
        var map = { c: 'section-cash-position', f: 'section-funnel', b: 'section-brief', t: 'section-team', m: 'section-trend' };
        var target = map[e.key.toLowerCase()];
        if (target) {
          var el = document.getElementById(target);
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
    });
  }

  // ── Morning Brief: the 60-second read ────────────────────
  function renderMorningBrief(snap) {
    var body = document.getElementById('brief-body');
    if (!body || !snap) return;

    var cp = snap.cash_position || {};
    var ch = snap.client_health || {};
    var def = snap.deficiency_analysis || {};
    var verdicts = snap.verdicts || {};

    var dateEl = document.getElementById('brief-date');
    if (dateEl && snap.generated_at) {
      dateEl.textContent = new Date(snap.generated_at).toLocaleDateString('en-AU',
        { weekday: 'long', day: 'numeric', month: 'long' });
    }

    var html = '';

    // Hero grid: cash+runway / MRR+trajectory / clients
    html += '<div class="brief-grid">';

    var runway = cp.runway_months;
    var runwayColor = runway == null ? 'var(--text-muted)' : runway < 3 ? 'var(--red)' : runway < 6 ? 'var(--amber)' : 'var(--green)';
    html += '<div>';
    html += '<div class="brief-stat-label">Cash on hand <span class="info-icon" data-metric="cash_in_bank">&#9432;</span></div>';
    html += '<div class="brief-cash-value">' + fmt$(cp.cash_in_bank) + '</div>';
    html += '<div class="brief-stat-sub" style="color:' + runwayColor + ';">' +
      (runway != null ? runway + ' months runway' : 'runway unknown') +
      ' at ' + fmt$(cp.total_monthly_burn) + '/mo burn' +
      (cp.stripe_incoming ? ' &middot; +' + fmt$(cp.stripe_incoming) + ' in transit' : '') + '</div>';
    html += '</div>';

    var delta = ch.mrr_delta;
    var arrow = delta == null ? '' : delta > 500 ? '<span class="brief-arrow" style="color:var(--green);">&#8599;</span>'
      : delta < -500 ? '<span class="brief-arrow" style="color:var(--red);">&#8600;</span>'
      : '<span class="brief-arrow" style="color:var(--text-muted);">&#8594;</span>';
    html += '<div>';
    html += '<div class="brief-stat-label">MRR <span class="info-icon" data-metric="current_mrr">&#9432;</span></div>';
    html += '<div class="brief-stat-value">' + fmt$(ch.current_mrr) + arrow + '</div>';
    html += '<div class="brief-stat-sub">next month ' + fmt$(ch.next_mrr) +
      (delta != null ? ' (' + fmtDelta(delta) + ')' : '') + '</div>';
    html += '</div>';

    var ac = snap.active_clients || {};
    html += '<div>';
    html += '<div class="brief-stat-label">Active clients</div>';
    html += '<div class="brief-stat-value">' + (ac.active_count != null ? ac.active_count : '—') + '</div>';
    var risk30 = ch.revenue_at_risk_30d;
    html += '<div class="brief-stat-sub">' + (risk30 ? fmt$(risk30) + ' MRR at risk in 30d' : 'no near-term renewal risk flagged') + '</div>';
    html += '</div>';

    html += '</div>';

    // Top movers since yesterday (history-driven)
    var movers = _computeMovers();
    if (movers.length > 0) {
      html += '<div class="brief-movers">';
      html += '<span class="brief-stat-label" style="margin:0;align-self:center;">Since yesterday</span>';
      movers.forEach(function(m) {
        var anomaly = m.rel > 0.15 ? ' anomaly' : '';
        html += '<span class="brief-mover' + anomaly + '">' + (anomaly ? '<span class="anomaly-dot"></span>' : '') + esc(m.label) + ' ' + fmtDelta(m.delta, m.fmt) + '</span>';
      });
      html += '</div>';
    }

    // Binding constraint, named in one sentence
    var bc = def.binding_constraint;
    if (bc && bc.name) {
      html += '<div class="brief-constraint"><strong>' + esc(bc.name) + '</strong> is the binding constraint — ' +
        esc(bc.impact || '') + (bc.current ? ' (now ' + esc(String(bc.current)) + ', target ' + esc(String(bc.target || '?')) + ')' : '') + '.</div>';
    }

    // The single recommended focus
    var focus = (bc && bc.fix) ? bc.fix : ((verdicts.top_leaks && verdicts.top_leaks[0]) ? verdicts.top_leaks[0].read : null);
    if (focus) {
      html += '<div class="brief-focus"><strong>Today\u2019s focus:</strong> ' + esc(focus) + '</div>';
    }

    body.innerHTML = html;
  }

  function _computeMovers() {
    if (!historyData || historyData.length < 2) return [];
    var curr = historyData[historyData.length - 1];
    var prev = historyData[historyData.length - 2];
    if (!curr || !prev) return [];
    var candidates = [
      { label: 'MRR', a: prev.mrr, b: curr.mrr, fmt: fmt$ },
      { label: 'Cash', a: prev.cash_in_bank, b: curr.cash_in_bank, fmt: fmt$ },
      { label: 'Collected 30d', a: prev.stripe_collected_30d, b: curr.stripe_collected_30d, fmt: fmt$ },
      { label: 'Clients', a: prev.active_clients, b: curr.active_clients, fmt: function(v) { return String(Math.round(v)); } },
      { label: 'Closes', a: prev.funnel && prev.funnel.closes, b: curr.funnel && curr.funnel.closes, fmt: function(v) { return String(Math.round(v)); } },
      { label: 'Failed charges', a: prev.failed_charges, b: curr.failed_charges, fmt: function(v) { return String(Math.round(v)); } },
    ];
    return candidates
      .filter(function(c) { return c.a != null && c.b != null && c.b - c.a !== 0; })
      .map(function(c) {
        var rel = c.a !== 0 ? Math.abs((c.b - c.a) / c.a) : 1;
        return { label: c.label, delta: c.b - c.a, fmt: c.fmt, rel: rel };
      })
      .sort(function(x, y) { return y.rel - x.rel; })
      .slice(0, 3);
  }

  // ── Metric definition tooltips (canonical definitions from metrics engine) ──
  function initMetricTips() {
    var tip = document.getElementById('metric-tip');
    if (!tip) return;
    document.addEventListener('mouseover', function(e) {
      var icon = e.target.closest && e.target.closest('.info-icon');
      if (!icon || !currentSnap || !currentSnap.metrics) return;
      var m = currentSnap.metrics[icon.dataset.metric];
      if (!m) return;
      var kindLabel = m.kind === 'FLOW' ? 'FLOW \u00b7 ' + (m.window || 'per period') : 'BALANCE \u00b7 point-in-time';
      tip.innerHTML = '<span class="tip-kind">' + kindLabel + '</span><br>' + esc(m.definition || '');
      tip.style.display = 'block';
      var r = icon.getBoundingClientRect();
      var top = r.bottom + 8;
      var left = Math.min(r.left, window.innerWidth - 320);
      tip.style.top = top + 'px';
      tip.style.left = Math.max(8, left) + 'px';
    });
    document.addEventListener('mouseout', function(e) {
      if (e.target.closest && e.target.closest('.info-icon')) tip.style.display = 'none';
    });
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

  // ── Lazy render: below-the-fold heavies wait until scrolled near ──
  var _lazySeen = {};
  var _lazyPending = {};
  var _lazyObserver = ('IntersectionObserver' in window) ? new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (!entry.isIntersecting) return;
      var id = entry.target.id;
      _lazySeen[id] = true;
      if (_lazyPending[id]) { var fn = _lazyPending[id]; delete _lazyPending[id]; fn(); }
      _lazyObserver.unobserve(entry.target);
    });
  }, { rootMargin: '400px' }) : null;

  function lazyRender(sectionId, fn) {
    var el = document.getElementById(sectionId);
    if (!el || !_lazyObserver || _lazySeen[sectionId]) { fn(); return; }
    _lazyPending[sectionId] = fn;
    _lazyObserver.observe(el);
  }

  // ── Render ───────────────────────────────────────────────
  function render(snap) {
    if (!snap) return;
    currentSnap = snap;

    renderStatus(snap);
    renderMorningBrief(snap);
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
    lazyRender('section-offers', function() { renderOfferChart(snap); });
    renderLeadSourceROI(snap);
    renderCommissions(snap);
    renderCommissionDetail(snap);
    renderMetrics(snap);
    renderSetters(snap);
    renderClosers(snap);
    lazyRender('section-cohort', function() { renderCohortRetention(snap); });
    renderForwardProjection(snap);
    renderDeficiency(snap);
    renderTeamModel(snap);
    renderTeamRoster(snap);
    renderQuality(snap);

    if (snap.generated_at) {
      $('#chat-context').textContent = timeAgo(snap.generated_at);
    }

    renderKpiTrends();
    renderChatChips(snap);
    countUpKpis();

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
    const cashPos = snap.cash_position || {};
    const burn = snap.monthly_burn || {};

    const stripeCash = get(stripe, 'revenue.current.total_aud');

    // Use full-outflow burn (from opex_pull) or fall back to team-only
    const totalBurn = cashPos.total_monthly_burn || burn.total_recurring_burn || null;
    const cashInflow = stripeCash || null;

    let html = '<div class="cash-grid">';

    // Cash in bank
    if (cashPos.cash_in_bank != null) {
      const confirmedAge = cashPos.confirmed_age_days;
      const confirmedStale = confirmedAge != null && confirmedAge > 7;
      html += `<div class="cash-card">
        <div class="cash-card-label">Cash in Bank <span class="info-icon" data-metric="cash_in_bank">&#9432;</span></div>
        <div class="cash-card-value" style="color:var(--green)">${fmt$(cashPos.cash_in_bank)}</div>
        <div class="cash-card-sub" ${confirmedStale ? 'style="color:var(--amber)"' : ''}>${cashPos.source === 'override'
          ? 'confirmed ' + (cashPos.confirmed_date || '') + (confirmedStale ? ' \u26a0 reconfirm' : '')
          : 'from Xero'}</div>
      </div>`;
    }

    // Dual deployable cash
    if (cashPos.aggressive_deployable != null) {
      html += `<div class="cash-card">
        <div class="cash-card-label">Aggressive War Chest</div>
        <div class="cash-card-value" style="color:var(--accent)">${fmt$(cashPos.aggressive_deployable)}</div>
        <div class="cash-card-sub">cash minus tax reserve</div>
      </div>`;
    }
    if (cashPos.conservative_deployable != null) {
      html += `<div class="cash-card">
        <div class="cash-card-label">Conservative War Chest</div>
        <div class="cash-card-value">${fmt$(cashPos.conservative_deployable)}</div>
        <div class="cash-card-sub">also excludes delivery reserve (${fmt$(cashPos.delivery_reserve)})</div>
      </div>`;
    }

    // Tax reserved
    if (cashPos.tax_reserved != null) {
      html += `<div class="cash-card">
        <div class="cash-card-label">Tax Reserved</div>
        <div class="cash-card-value" style="color:var(--text-muted)">${fmt$(cashPos.tax_reserved)}</div>
        <div class="cash-card-sub">BAS / tax set aside</div>
      </div>`;
    }

    // Stripe incoming
    if (cashPos.stripe_incoming != null && cashPos.stripe_incoming > 0) {
      html += `<div class="cash-card">
        <div class="cash-card-label">Stripe Incoming</div>
        <div class="cash-card-value" style="color:var(--accent)">${fmt$(cashPos.stripe_incoming)}</div>
        <div class="cash-card-sub">pending payout</div>
      </div>`;
    }

    // Stripe cash collected (trailing 30d)
    html += `<div class="cash-card">
      <div class="cash-card-label">Stripe Cash (30d)</div>
      <div class="cash-card-value" style="color:var(--accent)">${fmt$(stripeCash)}</div>
      <div class="cash-card-sub">collected from clients</div>
    </div>`;

    // Total monthly burn with breakdown
    if (totalBurn != null) {
      html += `<div class="cash-card" style="grid-column: span 2;">
        <div class="cash-card-label">Total Monthly Burn</div>
        <div class="cash-card-value" style="color:var(--red)">${fmt$(totalBurn)}</div>
        <div class="cash-card-sub" style="line-height:1.6">`;
      if (burn.available) {
        html += `Team ${fmt$(burn.team)} · Owner ${fmt$(burn.owner_pay)} · Ad ${fmt$(burn.ad_spend)} · Subs ${fmt$(burn.subscriptions)} · Other ${fmt$(burn.other_opex)}`;
      }
      html += `</div></div>`;
    }

    // Net cash flow (revenue minus TOTAL burn)
    if (cashInflow != null && totalBurn != null) {
      const netFlow = cashInflow - totalBurn;
      html += `<div class="cash-card">
        <div class="cash-card-label">Net Cash Flow</div>
        <div class="cash-card-value" style="color:${netFlow >= 0 ? 'var(--green)' : 'var(--red)'}">${netFlow >= 0 ? '+' : ''}${fmt$(netFlow)}</div>
        <div class="cash-card-sub">Stripe cash minus total burn</div>
      </div>`;
    }

    html += '</div>';

    // Runway on total burn
    const runwayMonths = cashPos.runway_months || null;
    if (runwayMonths != null && totalBurn != null) {
      const barPct = Math.min(runwayMonths / 12 * 100, 100);
      const color = runwayMonths >= 6 ? 'var(--green)' : runwayMonths >= 3 ? 'var(--amber)' : 'var(--red)';
      html += `<div class="runway-bar-bg"><div class="runway-bar-fill" style="width:${barPct}%;background:${color}"></div></div>`;
      html += `<div class="runway-note">Cash runway: <strong style="color:${color}">${runwayMonths.toFixed ? runwayMonths.toFixed(1) : runwayMonths} months</strong> at total burn (${fmt$(totalBurn)}/mo). ${runwayMonths >= 6 ? 'Comfortable.' : runwayMonths >= 3 ? 'Monitor closely.' : 'Critical — under 3 months.'}</div>`;

      badge.textContent = (runwayMonths.toFixed ? runwayMonths.toFixed(1) : runwayMonths) + 'mo runway';
      badge.style.background = runwayMonths >= 6 ? 'var(--green-dim)' : runwayMonths >= 3 ? 'var(--amber-dim)' : 'var(--red-dim)';
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
        // Window badges reflect the selected window everywhere
        ['win-badge-perf', 'win-badge-comm', 'win-badge-reps'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) el.textContent = currentWindow + 'd';
        });
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
      if (i === currentIdx) return CHART.brand;
      if (i < currentIdx) return CHART.brandSoft;
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
            if (!chartArea) return CHART.brand;
            const gradient = c.createLinearGradient(chartArea.left, 0, chartArea.right, 0);
            const splitPct = currentIdx >= 0 ? currentIdx / (trend.length - 1) : 1;
            gradient.addColorStop(0, 'rgba(91,155,208,0.85)');
            gradient.addColorStop(Math.min(splitPct, 0.99), 'rgba(91,155,208,0.85)');
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
              if (!chartArea) return 'rgba(91,155,208,0.05)';
              const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
              gradient.addColorStop(0, 'rgba(91,155,208,0.12)');
              gradient.addColorStop(1, 'rgba(91,155,208,0)');
              return gradient;
            },
          },
          tension: 0.3,
        },
        // Projection: base (dashed blue)
        ...(projection && projection.months_forward ? [{
          data: baseData,
          borderColor: 'rgba(91,155,208,0.5)',
          borderWidth: 2,
          borderDash: [6, 3],
          pointRadius: 3,
          pointBackgroundColor: 'rgba(91,155,208,0.5)',
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
    if (funnelLabel) funnelLabel.textContent = currentWindow + 'd';
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
      'rgba(91,155,208,0.75)', 'rgba(52,201,142,0.7)',
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

    var fp = snap.financial_position || {};
    var headline = fp.headline || {};
    var cashB = fp.cash_basis;
    var recB = fp.recognized_basis;

    var html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px;">';
    html += '<div class="kpi"><div class="kpi-label">Team Size</div><div class="kpi-value">' + tm.headcount + '</div></div>';
    html += '<div class="kpi"><div class="kpi-label">Team Cost</div><div class="kpi-value">' + fmt$(tm.total_with_owner) + '</div><div class="kpi-sub">/mo (incl. owner)</div></div>';

    // Dual-basis net — show both if available, otherwise headline
    if (cashB && cashB.monthly_net != null) {
      var cNet = cashB.monthly_net;
      html += '<div class="kpi"><div class="kpi-label">Cash Net</div><div class="kpi-value' + (cNet < 0 ? ' critical' : '') + '">' + fmt$(cNet) + '</div><div class="kpi-sub">/mo (Stripe)</div></div>';
    }
    if (recB && recB.monthly_net != null) {
      var rNet = recB.monthly_net;
      html += '<div class="kpi"><div class="kpi-label">Recognized Net</div><div class="kpi-value' + (rNet < 0 ? ' critical' : '') + '">' + fmt$(rNet) + '</div><div class="kpi-sub">/mo (Xero P&L)</div></div>';
    }
    if (!cashB && !recB && headline.monthly_net != null) {
      var hNet = headline.monthly_net;
      html += '<div class="kpi"><div class="kpi-label">Monthly Net</div><div class="kpi-value' + (hNet < 0 ? ' critical' : '') + '">' + fmt$(hNet) + '</div><div class="kpi-sub">/mo (' + (headline.basis || '?') + ')</div></div>';
    }

    // Cash on hand
    var cashPos = snap.cash_position || {};
    if (cashPos.cash_in_bank != null) {
      html += '<div class="kpi"><div class="kpi-label">Cash on Hand</div><div class="kpi-value">' + fmt$(cashPos.cash_in_bank) + '</div><div class="kpi-sub">' + (cashPos.source === 'override' ? 'confirmed' : 'xero') + '</div></div>';
    }

    // Team cost ratio
    var fpCosts = fp.costs || {};
    if (fpCosts.team_cost_pct_of_mrr != null) {
      var ratio = fpCosts.team_cost_pct_of_mrr;
      var bench = fpCosts.team_cost_benchmark;
      var ratioColor = bench === 'healthy' ? '' : bench === 'elevated' ? ' warning' : ' critical';
      html += '<div class="kpi"><div class="kpi-label">Team/MRR</div><div class="kpi-value' + ratioColor + '">' + ratio + '%</div><div class="kpi-sub">target &lt;45%</div></div>';
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

  // ── Hiring Scenario Form Handler (multi-role) ──────────
  var _hireRoleIdCounter = 0;

  function _addHireRoleRow() {
    var list = document.getElementById('hire-roles-list');
    if (!list) return;
    _hireRoleIdCounter++;
    var id = _hireRoleIdCounter;
    var row = document.createElement('div');
    row.className = 'hire-role-row';
    row.id = 'hire-row-' + id;
    row.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px;';
    row.innerHTML =
      '<input type="text" class="hire-role-input" placeholder="Role" style="background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:120px;">' +
      '<input type="number" class="hire-cost-input" placeholder="$/mo" style="background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:90px;">' +
      '<label style="font-size:11px;color:var(--text-muted);display:flex;align-items:center;gap:4px;">' +
      '<input type="checkbox" class="hire-revenue-input"> Rev-gen' +
      '</label>' +
      '<button class="hire-remove-btn" data-row="hire-row-' + id + '" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;padding:2px 6px;opacity:0.6;" title="Remove">&times;</button>';
    list.appendChild(row);
    row.querySelector('.hire-remove-btn').addEventListener('click', function() {
      var target = document.getElementById(this.getAttribute('data-row'));
      if (target) target.remove();
    });
  }

  function _collectHireRoles() {
    var rows = document.querySelectorAll('.hire-role-row');
    var roles = [];
    for (var i = 0; i < rows.length; i++) {
      var role = rows[i].querySelector('.hire-role-input').value.trim() || 'New hire';
      var cost = parseFloat(rows[i].querySelector('.hire-cost-input').value) || 0;
      var isRev = rows[i].querySelector('.hire-revenue-input').checked;
      if (cost > 0) {
        roles.push({ role: role, monthly_cost: cost, is_revenue_generating: isRev });
      }
    }
    return roles;
  }

  function _renderHiringResult(data) {
    var html = '';
    var c = data.combined;
    var cur = data.current;

    // ── Current financial state (dual-basis) ──
    html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.7;margin-bottom:10px;">';
    html += '<div style="font-weight:700;margin-bottom:6px;color:var(--text);">Current State</div>';
    html += '<div>Team cost: <strong>' + fmt$(cur.true_team_cost) + '/mo</strong></div>';
    html += '<div>MRR: <strong>' + fmt$(cur.current_mrr) + '</strong></div>';
    if (cur.team_cost_pct_of_mrr != null) {
      var tcColor = cur.team_cost_benchmark === 'healthy' ? 'var(--green)' : cur.team_cost_benchmark === 'elevated' ? 'var(--yellow)' : 'var(--red)';
      html += '<div>Team/MRR: <strong style="color:' + tcColor + '">' + cur.team_cost_pct_of_mrr + '%</strong> <span style="color:var(--text-muted);font-size:10px;">(' + esc(cur.team_cost_benchmark) + ')</span></div>';
    }
    // Show dual basis if available
    if (cur.cash_basis && cur.cash_basis.monthly_net != null) {
      var cashNet = cur.cash_basis.monthly_net;
      html += '<div>Cash net (Stripe): <strong style="color:' + (cashNet >= 0 ? 'var(--green)' : 'var(--red)') + '">' + fmt$(cashNet) + '/mo</strong> — ' + esc(cur.cash_basis.status.label) + '</div>';
    }
    if (cur.recognized_basis && cur.recognized_basis.monthly_net != null) {
      var recNet = cur.recognized_basis.monthly_net;
      html += '<div>Recognized net (Xero): <strong style="color:' + (recNet >= 0 ? 'var(--green)' : 'var(--red)') + '">' + fmt$(recNet) + '/mo</strong> — ' + esc(cur.recognized_basis.status.label) + '</div>';
    }
    // Headline fallback if neither basis shown
    if ((!cur.cash_basis || cur.cash_basis.monthly_net == null) && (!cur.recognized_basis || cur.recognized_basis.monthly_net == null) && cur.headline_net != null) {
      html += '<div>Monthly net: <strong style="color:' + (cur.headline_net >= 0 ? 'var(--green)' : 'var(--red)') + '">' + fmt$(cur.headline_net) + '/mo</strong></div>';
    }
    html += '</div>';

    // ── Per-role breakdown ──
    if (data.per_role.length > 0) {
      html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.7;margin-bottom:10px;">';
      html += '<div style="font-weight:700;margin-bottom:6px;color:var(--text);">Per Role</div>';
      for (var i = 0; i < data.per_role.length; i++) {
        var r = data.per_role[i];
        html += '<div style="padding:4px 0;' + (i > 0 ? 'border-top:1px solid var(--border);margin-top:4px;' : '') + '">';
        html += '<strong>' + esc(r.role) + '</strong> @ ' + fmt$(r.monthly_cost) + '/mo';
        if (r.is_revenue_generating) html += ' <span style="color:var(--accent);font-size:10px;">REV-GEN</span>';
        html += '<br>';
        if (r.closes_to_self_fund != null) {
          html += 'Self-fund: <strong>' + r.closes_to_self_fund + ' closes/mo</strong><br>';
        }
        if (r.closes_to_offset != null) {
          html += 'Closes to offset: <strong>' + r.closes_to_offset + '</strong><br>';
        }
        if (r.additional_mrr_needed != null) {
          html += 'MRR needed to offset: <strong>' + fmt$(r.additional_mrr_needed) + '</strong><br>';
        }
        if (r.self_funding_note) html += '<span style="color:var(--text-muted);font-size:11px;">' + esc(r.self_funding_note) + '</span>';
        if (r.offset_note) html += '<span style="color:var(--text-muted);font-size:11px;">' + esc(r.offset_note) + '</span>';
        html += '</div>';
      }
      html += '</div>';
    }

    // ── Raises ──
    if (data.raises && data.raises.length > 0) {
      html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.7;margin-bottom:10px;">';
      html += '<div style="font-weight:700;margin-bottom:6px;color:var(--text);">Raises</div>';
      for (var ri = 0; ri < data.raises.length; ri++) {
        var ra = data.raises[ri];
        html += '<div style="padding:4px 0;' + (ri > 0 ? 'border-top:1px solid var(--border);margin-top:4px;' : '') + '">';
        html += '<strong>' + esc(ra.role) + '</strong>: ' + fmt$(ra.current_salary) + ' &rarr; ' + fmt$(ra.new_salary) + ' (+' + fmt$(ra.monthly_increase) + '/mo)';
        if (ra.is_spof) html += ' <span style="color:var(--amber);font-size:10px;">SPOF — retention critical</span>';
        html += '</div>';
      }
      html += '</div>';
    }

    // ── Combined impact ──
    html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.7;margin-bottom:10px;">';
    html += '<div style="font-weight:700;margin-bottom:6px;color:var(--text);">Combined Impact (' + c.role_count + ' role' + (c.role_count > 1 ? 's' : '') + ')</div>';
    html += '<div>Added cost: <strong>' + fmt$(c.total_added_cost) + '/mo</strong></div>';
    html += '<div>Can afford: <strong style="color:' + (c.can_afford ? 'var(--green)' : 'var(--red)') + '">' + (c.can_afford ? 'Yes' : 'No') + '</strong></div>';
    html += '<div>Monthly net: ' + fmt$(c.monthly_net_before) + ' &rarr; <strong style="color:' + (c.monthly_net_after >= 0 ? 'var(--green)' : 'var(--red)') + '">' + fmt$(c.monthly_net_after) + '/mo</strong></div>';
    html += '<div>After: <strong>' + esc(c.status_after.label) + '</strong></div>';
    if (c.combined_closes_to_offset != null) {
      html += '<div>Closes to offset all hires: <strong>' + c.combined_closes_to_offset + '/mo</strong></div>';
    }
    if (c.cost_as_pct_of_mrr != null) {
      html += '<div>Team cost would be <strong>' + c.cost_as_pct_of_mrr + '%</strong> of MRR (target: &lt;40%)</div>';
    }
    html += '<div>MRR threshold: <strong>' + fmt$(c.mrr_threshold_for_hires) + '</strong></div>';
    html += '</div>';

    // ── 3-month forecast ──
    if (data.forecast_3mo && data.forecast_3mo.length > 0) {
      html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.7;margin-bottom:10px;">';
      html += '<div style="font-weight:700;margin-bottom:6px;color:var(--text);">3-Month Forecast (with hires)</div>';
      html += '<table style="width:100%;border-collapse:collapse;font-size:11px;">';
      html += '<tr style="color:var(--text-muted);border-bottom:1px solid var(--border);">';
      html += '<th style="text-align:left;padding:3px 4px;">Month</th>';
      html += '<th style="text-align:right;padding:3px 4px;">Proj. MRR</th>';
      html += '<th style="text-align:right;padding:3px 4px;">Net/mo</th>';
      html += '<th style="text-align:right;padding:3px 4px;">Cumulative</th>';
      html += '<th style="text-align:center;padding:3px 4px;">Afford?</th>';
      html += '</tr>';
      for (var fi = 0; fi < data.forecast_3mo.length; fi++) {
        var f = data.forecast_3mo[fi];
        var netColor = f.projected_net >= 0 ? 'var(--green)' : 'var(--red)';
        html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">';
        html += '<td style="padding:3px 4px;">M+' + f.month + '</td>';
        html += '<td style="text-align:right;padding:3px 4px;">' + fmt$(f.projected_mrr) + '</td>';
        html += '<td style="text-align:right;padding:3px 4px;color:' + netColor + ';">' + fmt$(f.projected_net) + '</td>';
        html += '<td style="text-align:right;padding:3px 4px;">' + fmt$(f.cumulative_cash_impact) + '</td>';
        html += '<td style="text-align:center;padding:3px 4px;">' + (f.can_afford_at_this_point ? '<span style="color:var(--green);">&#10003;</span>' : '<span style="color:var(--red);">&#10007;</span>') + '</td>';
        html += '</tr>';
      }
      html += '</table>';
      if (data.affordable_at_month != null) {
        html += '<div style="margin-top:6px;color:var(--yellow);font-size:11px;">&#9888; Becomes affordable at Month +' + data.affordable_at_month + ' based on MRR growth</div>';
      }
      html += '</div>';
    }

    // ── Forward MRR sustainability lens ──
    var fwd = data.forward_sustainability;
    if (fwd) {
      html += '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;line-height:1.7;margin-bottom:10px;">';
      html += '<div style="font-weight:700;margin-bottom:6px;color:var(--text);">Forward Recognized MRR (churn-adjusted)</div>';

      // Key metrics
      html += '<div>Current recognized MRR: <strong>' + fmt$(fwd.current_recognized_mrr) + '/mo</strong> (' + fwd.active_clients + ' clients)</div>';
      html += '<div>MTM floor (recurring): <strong>' + fmt$(fwd.mtm_floor) + '/mo</strong></div>';
      html += '<div>Avg contribution/client: <strong>' + fmt$(fwd.avg_monthly_per_client) + '/mo</strong></div>';
      if (fwd.starting_cash != null) {
        html += '<div>Starting cash: <strong>' + fmt$(fwd.starting_cash) + '</strong></div>';
      }
      if (fwd.clients_to_fund_hire != null) {
        html += '<div>Clients to fund this hire: <strong>' + fwd.clients_to_fund_hire + '</strong></div>';
      }
      if (fwd.new_clients_to_replace_churn_monthly != null) {
        html += '<div>Avg churn rate: <strong>~' + fwd.new_clients_to_replace_churn_monthly + ' clients/mo</strong> expiring</div>';
      }

      // Sustainability summary
      if (fwd.summary) {
        var s = fwd.summary;
        html += '<div style="margin-top:4px;">';
        if (s.unsustainable_months > 0) {
          html += '<span style="color:var(--red);font-weight:600;">&#9888; ' + s.healthy_months + ' healthy, ' + s.tight_months + ' tight, ' + s.unsustainable_months + ' unsustainable out of ' + s.total_months + ' months</span>';
        } else if (s.tight_months > 0) {
          html += '<span style="color:var(--yellow);font-weight:600;">' + s.healthy_months + ' healthy, ' + s.tight_months + ' tight out of ' + s.total_months + ' months</span>';
        } else {
          html += '<span style="color:var(--green);font-weight:600;">Healthy across all ' + s.total_months + ' months</span>';
        }
        html += '</div>';
      }

      // Cash runway warning
      if (fwd.cash_runway_month) {
        html += '<div style="color:var(--red);margin-top:4px;font-weight:600;">&#9888; Cash runs out by ' + esc(fwd.cash_runway_month) + '</div>';
      }

      // Forward forecast table with graded sustainability + cash balance
      if (fwd.forward_forecast && fwd.forward_forecast.length > 0) {
        html += '<table style="width:100%;border-collapse:collapse;font-size:11px;margin-top:8px;">';
        html += '<tr style="color:var(--text-muted);border-bottom:1px solid var(--border);">';
        html += '<th style="text-align:left;padding:3px 4px;">Month</th>';
        html += '<th style="text-align:right;padding:3px 4px;">Rec. MRR</th>';
        html += '<th style="text-align:center;padding:3px 4px;">Cl.</th>';
        html += '<th style="text-align:right;padding:3px 4px;">Net (w/ hire)</th>';
        html += '<th style="text-align:right;padding:3px 4px;">Cash Bal.</th>';
        html += '<th style="text-align:center;padding:3px 4px;">Team %</th>';
        html += '<th style="text-align:center;padding:3px 4px;">Status</th>';
        html += '</tr>';
        for (var ffi = 0; ffi < fwd.forward_forecast.length; ffi++) {
          var ff = fwd.forward_forecast[ffi];
          var ffNetColor = ff.net_after_hire >= 0 ? 'var(--green)' : 'var(--red)';
          var cashColor = ff.cash_balance != null && ff.cash_balance < 0 ? 'var(--red)' : 'var(--text)';
          var sus = ff.sustainability || {};
          var gradeColor = sus.grade === 'healthy' ? 'var(--green)' : sus.grade === 'tight' ? 'var(--yellow)' : 'var(--red)';
          var gradeIcon = sus.grade === 'healthy' ? '&#10003;' : sus.grade === 'tight' ? '&#9888;' : '&#10007;';
          var gradeLabel = sus.grade || '?';
          html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">';
          html += '<td style="padding:3px 4px;font-size:10px;">' + esc(ff.month) + '</td>';
          html += '<td style="text-align:right;padding:3px 4px;">' + fmt$(ff.recognized_mrr) + '</td>';
          html += '<td style="text-align:center;padding:3px 4px;">' + (ff.clients || '-') + '</td>';
          html += '<td style="text-align:right;padding:3px 4px;color:' + ffNetColor + ';">' + fmt$(ff.net_after_hire) + '</td>';
          html += '<td style="text-align:right;padding:3px 4px;color:' + cashColor + ';">' + fmt$(ff.cash_balance) + '</td>';
          html += '<td style="text-align:center;padding:3px 4px;">' + (ff.team_cost_pct != null ? ff.team_cost_pct + '%' : '-') + '</td>';
          html += '<td style="text-align:center;padding:3px 4px;color:' + gradeColor + ';" title="' + esc(sus.reason || '') + '">' + gradeIcon + ' ' + gradeLabel + '</td>';
          html += '</tr>';
        }
        html += '</table>';
      }

      // Verdict
      if (fwd.verdict) {
        html += '<div style="margin-top:8px;padding:8px;background:rgba(255,255,255,0.02);border-radius:6px;font-size:11px;line-height:1.6;">';
        html += '<strong>Verdict:</strong> ' + esc(fwd.verdict);
        html += '</div>';
      }

      html += '<div style="font-size:10px;color:var(--text-muted);margin-top:4px;">Renewal rate: ' + esc(fwd.renewal_rate || '0% historical') + '</div>';
      html += '</div>';
    }

    // ── Constraint context ──
    if (data.constraint_context) {
      html += '<div style="background:rgba(255,200,0,0.05);border:1px solid var(--yellow);border-radius:8px;padding:10px;font-size:11px;line-height:1.6;margin-bottom:10px;">';
      html += '<div style="font-weight:700;color:var(--yellow);margin-bottom:4px;">Binding Constraint</div>';
      html += '<div>Current bottleneck: <strong>' + esc(data.constraint_context.binding_constraint) + '</strong></div>';
      html += '<div style="color:var(--text-muted);font-style:italic;">' + esc(data.constraint_context.note) + '</div>';
      html += '</div>';
    }

    // ── Note ──
    html += '<div style="font-size:11px;color:var(--text-muted);font-style:italic;">' + esc(data.note) + '</div>';

    return html;
  }

  // ── Raise Form Handler ──────────────────────────
  var _raiseIdCounter = 0;

  function _addRaiseRow() {
    var list = document.getElementById('raise-list');
    if (!list) return;
    _raiseIdCounter++;
    var id = _raiseIdCounter;
    var row = document.createElement('div');
    row.className = 'raise-row';
    row.id = 'raise-row-' + id;
    row.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px;';
    row.innerHTML =
      '<input type="text" class="raise-role-input" placeholder="Role" style="background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:120px;">' +
      '<input type="number" class="raise-current-input" placeholder="Current $/mo" style="background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:100px;">' +
      '<input type="number" class="raise-new-input" placeholder="New $/mo" style="background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:12px;width:100px;">' +
      '<button class="raise-remove-btn" data-row="raise-row-' + id + '" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;padding:2px 6px;opacity:0.6;" title="Remove">&times;</button>';
    list.appendChild(row);
    row.querySelector('.raise-remove-btn').addEventListener('click', function() {
      var target = document.getElementById(this.getAttribute('data-row'));
      if (target) target.remove();
    });
  }

  function _collectRaises() {
    var rows = document.querySelectorAll('.raise-row');
    var raises = [];
    for (var i = 0; i < rows.length; i++) {
      var role = rows[i].querySelector('.raise-role-input').value.trim();
      var current = parseFloat(rows[i].querySelector('.raise-current-input').value) || 0;
      var newSal = parseFloat(rows[i].querySelector('.raise-new-input').value) || 0;
      var increase = newSal - current;
      if (increase > 0) {
        raises.push({ role: role || 'Employee', current_salary: current, new_salary: newSal, monthly_increase: increase });
      }
    }
    return raises;
  }

  function initHiringForm() {
    var addBtn = document.getElementById('hire-add-role');
    var raiseBtn = document.getElementById('raise-add');
    var submitBtn = document.getElementById('hire-submit');
    if (!submitBtn) return;

    // Start with one empty row
    _addHireRoleRow();

    if (addBtn) addBtn.addEventListener('click', function() { _addHireRoleRow(); });
    if (raiseBtn) raiseBtn.addEventListener('click', function() { _addRaiseRow(); });

    submitBtn.addEventListener('click', function() {
      var roles = _collectHireRoles();
      var raises = _collectRaises();
      var resultDiv = document.getElementById('hiring-result');
      if (roles.length === 0 && raises.length === 0) {
        resultDiv.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">Add at least one hire or raise</div>';
        return;
      }
      resultDiv.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">Analyzing...</div>';

      var payload = { roles: roles };
      if (raises.length > 0) payload.raises = raises;

      fetch('/dashboard/api/hiring-scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) {
          resultDiv.innerHTML = '<div style="color:var(--red);font-size:12px;">' + esc(data.error) + '</div>';
          return;
        }
        resultDiv.innerHTML = _renderHiringResult(data);
      })
      .catch(function(e) {
        resultDiv.innerHTML = '<div style="color:var(--red);font-size:12px;">Failed: ' + esc(e.message) + '</div>';
      });
    });
  }

  // ── Forward Projection (standalone, with re-sign slider) ──
  function renderForwardProjection(snap) {
    var body = document.getElementById('forward-projection-body');
    if (!body) return;

    var fwd = snap.forward_mrr;
    if (!fwd || !fwd.forward_months || fwd.forward_months.length === 0) {
      body.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:12px;">Forward MRR data not available</div>';
      return;
    }

    var resignPct = parseInt(document.getElementById('resign-slider').value) || 0;
    _renderForwardTable(snap, resignPct);
  }

  // Shared forward model: identical math for table and chart (display-side
  // re-sign adjustment over engine-provided forward months; engines untouched).
  function _computeForwardModel(fwdMonths, fwd, totalBurn, startingCash, resignPct) {
    var runningCash = startingCash;
    var rows = [];
    for (var i = 0; i < fwdMonths.length; i++) {
      var fm = fwdMonths[i];
      var baseMrr = fm.recognized_mrr || 0;
      var baseClients = fm.clients || 0;
      var resignUplift = 0;
      var resignClients = 0;
      if (resignPct > 0 && i > 0) {
        var prevMrr = fwdMonths[i - 1].recognized_mrr || 0;
        var drop = prevMrr - baseMrr;
        if (drop > 0) {
          resignUplift = drop * (resignPct / 100);
          var avgPerClient = fwd.avg_monthly_per_client || 2200;
          resignClients = avgPerClient > 0 ? Math.round(resignUplift / avgPerClient) : 0;
        }
      }
      if (i > 0 && rows[i - 1]) {
        resignUplift += rows[i - 1].cumulativeResign || 0;
        resignClients += rows[i - 1].cumulativeResignClients || 0;
      }
      var adjustedMrr = baseMrr + resignUplift;
      var adjustedClients = baseClients + resignClients;
      var netCash = adjustedMrr - totalBurn;
      runningCash = runningCash + netCash;
      var teamCostPct = adjustedMrr > 0 ? Math.round(totalBurn / adjustedMrr * 100) : null;
      var grade = 'healthy';
      var gradeReason = '';
      if (runningCash < 0) { grade = 'unsustainable'; gradeReason = 'Cash negative'; }
      else if (teamCostPct !== null && teamCostPct > 80) { grade = 'unsustainable'; gradeReason = 'Burn > 80% of MRR'; }
      else if (netCash < -5000) { grade = 'unsustainable'; gradeReason = 'Net loss > $5k/mo'; }
      else if (teamCostPct !== null && teamCostPct > 50) { grade = 'tight'; gradeReason = 'Burn > 50% of MRR'; }
      else if (netCash < 0) { grade = 'tight'; gradeReason = 'Slightly negative'; }
      else { gradeReason = 'Healthy'; }
      rows.push({
        month: fm.month,
        baseMrr: baseMrr,
        adjustedMrr: adjustedMrr,
        clients: adjustedClients,
        resignUplift: resignUplift,
        cumulativeResign: resignUplift,
        cumulativeResignClients: resignClients,
        net: netCash,
        cashBalance: runningCash,
        teamCostPct: teamCostPct,
        grade: grade,
        gradeReason: gradeReason,
      });
    }
    return rows;
  }

  function _renderForwardTable(snap, resignPct) {
    var body = document.getElementById('forward-projection-body');
    if (!body) return;

    var fwd = snap.forward_mrr;
    if (!fwd || !fwd.forward_months) return;

    var burn = snap.monthly_burn || {};
    var totalBurn = burn.total_recurring_burn || 0;
    var cashPos = snap.cash_position || {};
    var startingCash = cashPos.cash_in_bank || 0;  // cash_in_bank ONLY, not total_available

    var fwdMonths = fwd.forward_months.slice(0, 7);
    var expiryByMonth = {};
    (fwd.expiry_schedule || []).forEach(function(e) {
      expiryByMonth[e.month] = e;
    });

    var rows = _computeForwardModel(fwdMonths, fwd, totalBurn, startingCash, resignPct);

    // Summary stats
    var healthyCount = rows.filter(function(r) { return r.grade === 'healthy'; }).length;
    var tightCount = rows.filter(function(r) { return r.grade === 'tight'; }).length;
    var unsustCount = rows.filter(function(r) { return r.grade === 'unsustainable'; }).length;
    var cashRunoutMonth = null;
    for (var ri = 0; ri < rows.length; ri++) {
      if (rows[ri].cashBalance < 0) { cashRunoutMonth = rows[ri].month; break; }
    }

    var html = '';

    // Key metrics bar
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0;">';
    html += '<div class="kpi"><div class="kpi-label">Current MRR</div><div class="kpi-value">' + fmt$(fwd.current_recognized_mrr) + '</div><div class="kpi-sub">' + fwd.active_clients + ' clients</div></div>';
    html += '<div class="kpi"><div class="kpi-label">MTM Floor</div><div class="kpi-value">' + fmt$(fwd.mtm_floor) + '</div><div class="kpi-sub">' + fwd.mtm_clients + ' mtm</div></div>';
    html += '<div class="kpi"><div class="kpi-label">Starting Cash</div><div class="kpi-value">' + fmt$(startingCash) + '</div><div class="kpi-sub">CommBank</div></div>';
    html += '<div class="kpi"><div class="kpi-label">Monthly Burn</div><div class="kpi-value">' + fmt$(totalBurn) + '</div><div class="kpi-sub">full outflow</div></div>';

    // Sustainability summary
    var summaryColor = unsustCount > 0 ? 'var(--red)' : tightCount > 0 ? 'var(--amber)' : 'var(--green)';
    html += '<div class="kpi"><div class="kpi-label">Outlook</div><div class="kpi-value" style="font-size:14px;color:' + summaryColor + ';">';
    if (unsustCount > 0) {
      html += healthyCount + '/' + rows.length + ' healthy';
    } else if (tightCount > 0) {
      html += healthyCount + ' ok, ' + tightCount + ' tight';
    } else {
      html += 'All healthy';
    }
    html += '</div>';
    if (cashRunoutMonth) html += '<div class="kpi-sub" style="color:var(--red);">Cash out by ' + cashRunoutMonth.split(' ')[0].substring(0, 3) + '</div>';
    html += '</div>';
    html += '</div>';

    // Re-sign value callout (only when slider > 0)
    if (resignPct > 0) {
      var lastRowBase = fwdMonths[fwdMonths.length - 1] ? (fwdMonths[fwdMonths.length - 1].recognized_mrr || 0) : 0;
      var lastRowAdj = rows[rows.length - 1] ? rows[rows.length - 1].adjustedMrr : 0;
      var retentionValue = lastRowAdj - lastRowBase;
      html += '<div style="background:var(--accent-dim);border:1px solid rgba(59,130,246,0.2);border-radius:6px;padding:8px 12px;font-size:11px;margin-bottom:8px;">';
      html += '<strong style="color:var(--accent);">' + resignPct + '% re-sign rate</strong> preserves <strong>' + fmt$(Math.round(retentionValue)) + '/mo</strong> by ' + (rows[rows.length - 1] ? rows[rows.length - 1].month.split(' ')[0].substring(0, 3) : 'end') + '. ';
      html += 'Every 25% improvement = ~' + fmt$(Math.round(retentionValue * 25 / resignPct)) + '/mo.';
      html += '</div>';
    }

    // Comparative forward cash chart: 0% churn-cliff baseline vs selected re-sign
    html += '<div class="chart-wrap" style="height:190px;margin:4px 0 14px;"><canvas id="forward-chart"></canvas></div>';

    // Forward table
    html += '<table class="data-table" style="width:100%;font-size:11px;">';
    html += '<thead><tr>';
    html += '<th style="text-align:left;">Month</th>';
    html += '<th class="col-num" style="text-align:right;">Rec. MRR</th>';
    if (resignPct > 0) html += '<th class="col-num" style="text-align:right;color:var(--accent);">+ Re-sign</th>';
    html += '<th style="text-align:center;">Cl.</th>';
    html += '<th class="col-num" style="text-align:right;">Net</th>';
    html += '<th class="col-num" style="text-align:right;">Cash Bal.</th>';
    html += '<th style="text-align:center;">Burn %</th>';
    html += '<th style="text-align:center;">Status</th>';
    html += '</tr></thead><tbody>';

    for (var ri = 0; ri < rows.length; ri++) {
      var r = rows[ri];
      var netColor = r.net >= 0 ? 'var(--green)' : 'var(--red)';
      var cashColor = r.cashBalance < 0 ? 'var(--red)' : 'var(--text)';
      var gradeColor = r.grade === 'healthy' ? 'var(--green)' : r.grade === 'tight' ? 'var(--amber)' : 'var(--red)';
      var gradeIcon = r.grade === 'healthy' ? '&#10003;' : r.grade === 'tight' ? '&#9888;' : '&#10007;';
      var shortMonth = r.month.split(' ')[0].substring(0, 3) + ' \'' + r.month.split(' ')[1].substring(2);

      html += '<tr style="border-bottom:1px solid var(--border);">';
      html += '<td style="padding:6px 8px;font-weight:500;">' + shortMonth + '</td>';
      html += '<td class="col-num" style="text-align:right;padding:6px 8px;">' + fmt$(Math.round(r.baseMrr)) + '</td>';
      if (resignPct > 0) {
        html += '<td class="col-num" style="text-align:right;padding:6px 8px;color:var(--accent);">' + (r.resignUplift > 0 ? '+' + fmt$(Math.round(r.resignUplift)) : '—') + '</td>';
      }
      html += '<td style="text-align:center;padding:6px 8px;color:var(--text-muted);">' + r.clients + '</td>';
      html += '<td class="col-num" style="text-align:right;padding:6px 8px;color:' + netColor + ';">' + fmt$(Math.round(r.net)) + '</td>';
      html += '<td class="col-num" style="text-align:right;padding:6px 8px;color:' + cashColor + ';font-weight:600;">' + fmt$(Math.round(r.cashBalance)) + '</td>';
      html += '<td style="text-align:center;padding:6px 8px;color:var(--text-muted);">' + (r.teamCostPct != null ? r.teamCostPct + '%' : '—') + '</td>';
      html += '<td style="text-align:center;padding:6px 8px;color:' + gradeColor + ';" title="' + esc(r.gradeReason) + '">' + gradeIcon + '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>';

    // Expiry schedule
    var expiries = fwd.expiry_schedule || [];
    if (expiries.length > 0) {
      html += '<div style="margin-top:10px;font-size:10px;color:var(--text-muted);">';
      html += '<strong>Expiries:</strong> ';
      var parts = [];
      for (var ei = 0; ei < Math.min(expiries.length, 6); ei++) {
        var e = expiries[ei];
        parts.push(e.month + ': ' + e.contracts_expiring + ' cl. (' + fmt$(e.mrr_at_risk) + ')');
      }
      html += parts.join(' · ');
      html += '</div>';
    }

    html += '<div style="margin-top:6px;font-size:10px;color:var(--text-muted);">Renewal rate: 0% historical (0/12). Cash bal. = prior + (rec. MRR − burn). Source: RECOGNIZED tab, live pull.</div>';

    body.innerHTML = html;
    _drawForwardChart(fwdMonths, fwd, totalBurn, startingCash, resignPct, rows);
  }

  var _forwardChart = null;
  function _drawForwardChart(fwdMonths, fwd, totalBurn, startingCash, resignPct, rows) {
    var canvas = document.getElementById('forward-chart');
    if (!canvas || !window.Chart) return;
    if (_forwardChart) { _forwardChart.destroy(); _forwardChart = null; }

    var labels = rows.map(function(r) {
      return r.month.split(' ')[0].substring(0, 3);
    });
    var selectedSeries = rows.map(function(r) { return Math.round(r.cashBalance); });
    var datasets = [];

    if (resignPct > 0) {
      var baseline = _computeForwardModel(fwdMonths, fwd, totalBurn, startingCash, 0);
      datasets.push({
        label: '0% re-sign (churn cliff)',
        data: baseline.map(function(r) { return Math.round(r.cashBalance); }),
        borderColor: 'rgba(113,136,159,0.7)',
        borderDash: [5, 4],
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.3,
        fill: false,
      });
    }
    datasets.push({
      label: resignPct > 0 ? resignPct + '% re-sign' : 'Cash balance (0% re-sign)',
      data: selectedSeries,
      borderColor: CHART.brand,
      backgroundColor: CHART.brandFillTop,
      borderWidth: 2,
      pointRadius: 2.5,
      pointBackgroundColor: CHART.brand,
      tension: 0.3,
      fill: true,
    });

    _forwardChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', align: 'end' },
          tooltip: {
            callbacks: {
              label: function(ctx) { return ctx.dataset.label + ': ' + fmt$(ctx.parsed.y); }
            }
          }
        },
        scales: {
          y: {
            grid: {
              color: function(ctx) {
                return ctx.tick && ctx.tick.value === 0 ? 'rgba(232,97,107,0.55)' : CHART.grid;
              },
              lineWidth: function(ctx) {
                return ctx.tick && ctx.tick.value === 0 ? 1.5 : 1;
              }
            },
            ticks: { callback: function(v) { return fmtK(v); } }
          },
          x: { grid: { display: false } }
        }
      }
    });
  }

  function initForwardSlider() {
    var slider = document.getElementById('resign-slider');
    var pctLabel = document.getElementById('resign-pct');
    if (!slider || !pctLabel) return;
    slider.addEventListener('input', function() {
      pctLabel.textContent = this.value + '%';
      if (currentSnap) _renderForwardTable(currentSnap, parseInt(this.value));
    });
  }

  // ── Team Roster (editable scratch layer) ─────────────────
  var _rosterScratch = null;   // null = use actual, array = edited
  var _rosterActual = null;    // source-of-truth from snapshot
  var _rosterActualTotals = null;

  function _rosterData() {
    return _rosterScratch || _rosterActual || [];
  }

  function _fmtPhp(v) {
    if (v == null || v === 0) return '—';
    return '₱' + Math.round(v).toLocaleString('en-AU');
  }

  function renderTeamRoster(snap) {
    var wrap = document.getElementById('roster-table-wrap');
    if (!wrap) return;

    var roster = (snap.team_roster || {}).roster;
    if (!roster || roster.length === 0) {
      wrap.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:12px;">Roster data not available</div>';
      return;
    }

    _rosterActual = roster.map(function(p) { return Object.assign({}, p); });
    _rosterActualTotals = (snap.team_roster || {}).totals || {};

    _renderRosterTable(_rosterScratch || _rosterActual);
  }

  function _renderRosterTable(people) {
    var wrap = document.getElementById('roster-table-wrap');
    if (!wrap) return;

    var isEdited = _rosterScratch !== null;

    // Show/hide modeling badge
    var badge = document.getElementById('roster-mode-badge');
    if (badge) badge.style.display = isEdited ? 'inline-flex' : 'none';

    // Group by department
    var depts = {};
    var totalAud = 0, totalPhp = 0;
    for (var i = 0; i < people.length; i++) {
      var p = people[i];
      var dept = p.department || 'UNKNOWN';
      if (!depts[dept]) depts[dept] = [];
      depts[dept].push(p);
      totalAud += (p.salary_aud || 0);
      totalPhp += (p.salary_php || 0);
    }

    var html = '<table class="roster-table">';
    html += '<thead><tr>';
    html += '<th>Name</th>';
    html += '<th>Role</th>';
    html += '<th class="col-num">AUD/mo</th>';
    html += '<th class="col-num">PHP/mo</th>';
    if (isEdited) html += '<th style="width:28px;"></th>';
    html += '</tr></thead><tbody>';

    var deptKeys = Object.keys(depts).sort();
    for (var di = 0; di < deptKeys.length; di++) {
      var dept = deptKeys[di];
      var members = depts[dept];
      var deptAud = 0, deptPhp = 0;
      for (var mi = 0; mi < members.length; mi++) {
        deptAud += (members[mi].salary_aud || 0);
        deptPhp += (members[mi].salary_php || 0);
      }

      // Department header row
      var colSpan = isEdited ? 5 : 4;
      html += '<tr class="roster-dept-row">';
      html += '<td colspan="2"><span class="roster-dept-label">' + esc(dept) + '</span><span class="roster-dept-count">' + members.length + '</span></td>';
      html += '<td class="col-num"><span class="roster-dept-subtotal">' + (deptAud > 0 ? fmt$(deptAud) : '') + '</span></td>';
      html += '<td class="col-num"><span class="roster-dept-subtotal">' + (deptPhp > 0 ? _fmtPhp(deptPhp) : '') + '</span></td>';
      if (isEdited) html += '<td></td>';
      html += '</tr>';

      for (var mi = 0; mi < members.length; mi++) {
        var p = members[mi];
        var idx = people.indexOf(p);
        html += '<tr data-roster-idx="' + idx + '">';

        // Name
        html += '<td>';
        if (isEdited) {
          html += '<input type="text" class="roster-edit-input roster-edit-name" data-idx="' + idx + '" value="' + esc(p.first_name + ' ' + p.last_name) + '" style="width:100%;">';
        } else {
          html += '<span class="roster-name">' + esc(p.first_name + ' ' + p.last_name) + '</span>';
        }
        html += '</td>';

        // Role
        html += '<td><span class="roster-role">' + esc(p.role) + '</span></td>';

        // AUD
        html += '<td class="col-num">';
        if (isEdited) {
          html += '<input type="number" class="roster-edit-input num roster-edit-aud" data-idx="' + idx + '" value="' + (p.salary_aud || 0) + '">';
        } else {
          html += (p.salary_aud > 0 ? fmt$(p.salary_aud) : '—');
        }
        html += '</td>';

        // PHP
        html += '<td class="col-num">';
        if (isEdited) {
          html += '<input type="number" class="roster-edit-input num roster-edit-php" data-idx="' + idx + '" value="' + (p.salary_php || 0) + '">';
        } else {
          html += (p.salary_php > 0 ? _fmtPhp(p.salary_php) : '—');
        }
        html += '</td>';

        // Remove button (edit mode only)
        if (isEdited) {
          html += '<td><button class="roster-remove roster-remove-btn" data-idx="' + idx + '" title="Remove">&times;</button></td>';
        }

        html += '</tr>';
      }
    }

    // Total row
    html += '<tr class="roster-total-row">';
    html += '<td colspan="2">Total <span style="color:var(--text-muted);font-weight:400;font-size:11px;">(' + people.length + ' people)</span></td>';
    html += '<td class="col-num">' + fmt$(Math.round(totalAud)) + '</td>';
    html += '<td class="col-num">' + _fmtPhp(totalPhp) + '</td>';
    if (isEdited) html += '<td></td>';
    html += '</tr>';

    html += '</tbody></table>';
    wrap.innerHTML = html;

    if (isEdited) _bindRosterEditEvents();
    _renderRosterReadout(people);
  }

  function _renderRosterReadout(people) {
    var readout = document.getElementById('roster-readout');
    if (!readout) return;

    var modeledAud = 0, modeledPhp = 0;
    for (var i = 0; i < people.length; i++) {
      modeledAud += (people[i].salary_aud || 0);
      modeledPhp += (people[i].salary_php || 0);
    }

    var actualAud = _rosterActualTotals ? (_rosterActualTotals.total_aud || 0) : 0;
    var actualPhp = _rosterActualTotals ? (_rosterActualTotals.total_php || 0) : 0;

    var isEdited = _rosterScratch !== null;
    var burn = (currentSnap || {}).monthly_burn || {};
    var totalBurn = burn.total_recurring_burn || 0;
    var cashPos = (currentSnap || {}).cash_position || {};
    var cashInBank = cashPos.cash_in_bank || 0;

    if (!isEdited) {
      var html = '<div class="roster-readout">';
      html += '<span class="roster-readout-label">Team payroll</span> ';
      html += '<span class="roster-readout-value">' + fmt$(Math.round(actualAud)) + '</span>';
      html += ' <span style="color:var(--text-muted);">AUD + ' + _fmtPhp(actualPhp) + ' PHP</span>';
      if (totalBurn > 0) {
        html += '<br><span class="roster-readout-label">Recurring burn</span> ' + fmt$(Math.round(totalBurn)) + '/mo';
        if (cashInBank > 0) {
          html += ' &middot; <span class="roster-readout-label">Runway</span> ' + (cashInBank / totalBurn).toFixed(1) + ' months';
        }
      }
      html += '<br><span style="color:var(--text-muted);font-size:10px;">Click any row or "+ Add person" to model changes</span>';
      html += '</div>';
      readout.innerHTML = html;
      return;
    }

    // Modeled vs actual — compute AUD delta only (PHP stays as-is from sheet)
    var audDelta = modeledAud - actualAud;
    var phpDelta = modeledPhp - actualPhp;
    // For burn impact, approximate PHP delta in AUD
    var fxRate = 44;
    var el = document.getElementById('roster-fx-rate');
    if (el) { var v = parseFloat(el.value); if (v > 0) fxRate = v; }
    var totalDelta = audDelta + (phpDelta / fxRate);

    var baseBurn = totalBurn;
    var modeledBurn = baseBurn + totalDelta;
    var actualRunway = baseBurn > 0 && cashInBank > 0 ? (cashInBank / baseBurn) : null;
    var modeledRunway = modeledBurn > 0 && cashInBank > 0 ? (cashInBank / modeledBurn) : null;
    var deltaColor = totalDelta > 0 ? 'var(--red)' : totalDelta < 0 ? 'var(--green)' : 'var(--text-muted)';
    var deltaSign = totalDelta > 0 ? '+' : '';

    // Count scratch edits vs actual so modeling state is always explicit
    var changeCount = 0;
    if (_rosterScratch && _rosterActual) {
      var maxLen = Math.max(_rosterScratch.length, _rosterActual.length);
      for (var ci = 0; ci < maxLen; ci++) {
        var sp = _rosterScratch[ci], ap = _rosterActual[ci];
        if (!sp || !ap) { changeCount++; continue; }
        if ((sp.salary_aud || 0) !== (ap.salary_aud || 0) ||
            (sp.salary_php || 0) !== (ap.salary_php || 0) ||
            (sp.first_name || '') !== (ap.first_name || '')) changeCount++;
      }
    }

    var html = '<div class="roster-readout">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">';
    html += '<span style="font-weight:600;color:var(--text);font-size:12px;">Modeled Impact</span>';
    html += '<span style="font-size:11px;color:var(--amber);">\u26a0 ' + changeCount + ' change' + (changeCount === 1 ? '' : 's') + ' from actual \u2014 <a href="#" onclick="document.getElementById(\'roster-reset\').click();return false;" style="color:var(--accent);">reset</a></span>';
    html += '</div>';
    html += '<div class="roster-readout-grid">';

    html += '<div><div class="roster-readout-label">Actual team</div><div class="roster-readout-value">' + fmt$(Math.round(actualAud)) + '</div></div>';
    html += '<div><div class="roster-readout-label">Modeled team</div><div class="roster-readout-value">' + fmt$(Math.round(modeledAud)) + '</div></div>';
    html += '<div><div class="roster-readout-label">Delta</div><div class="roster-readout-value" style="color:' + deltaColor + ';">' + deltaSign + fmt$(Math.round(totalDelta)) + '/mo</div></div>';

    html += '<div><div class="roster-readout-label">Actual burn</div><div style="font-size:12px;color:var(--text-secondary);">' + fmt$(Math.round(baseBurn)) + '/mo</div></div>';
    html += '<div><div class="roster-readout-label">Modeled burn</div><div style="font-size:12px;color:var(--text-secondary);">' + fmt$(Math.round(modeledBurn)) + '/mo</div></div>';
    html += '<div><div class="roster-readout-label">Runway</div>';
    if (modeledRunway != null && actualRunway != null) {
      var runDelta = modeledRunway - actualRunway;
      html += '<div style="font-size:12px;color:' + (runDelta < 0 ? 'var(--red)' : 'var(--green)') + ';">' + actualRunway.toFixed(1) + ' → ' + modeledRunway.toFixed(1) + ' mo</div>';
    } else {
      html += '<div style="font-size:12px;color:var(--text-muted);">—</div>';
    }
    html += '</div>';
    html += '</div></div>';

    readout.innerHTML = html;
  }

  function _bindRosterEditEvents() {
    document.querySelectorAll('.roster-edit-aud').forEach(function(el) {
      el.addEventListener('change', function() {
        var idx = parseInt(this.getAttribute('data-idx'));
        if (_rosterScratch && _rosterScratch[idx]) {
          _rosterScratch[idx].salary_aud = parseFloat(this.value) || 0;
          _renderRosterTable(_rosterScratch);
        }
      });
    });
    document.querySelectorAll('.roster-edit-php').forEach(function(el) {
      el.addEventListener('change', function() {
        var idx = parseInt(this.getAttribute('data-idx'));
        if (_rosterScratch && _rosterScratch[idx]) {
          _rosterScratch[idx].salary_php = parseFloat(this.value) || 0;
          _renderRosterTable(_rosterScratch);
        }
      });
    });
    document.querySelectorAll('.roster-remove-btn').forEach(function(el) {
      el.addEventListener('click', function() {
        var idx = parseInt(this.getAttribute('data-idx'));
        if (_rosterScratch) {
          _rosterScratch.splice(idx, 1);
          _renderRosterTable(_rosterScratch);
        }
      });
    });
  }

  function _enterRosterEditMode() {
    if (_rosterScratch) return;
    if (!_rosterActual) return;
    _rosterScratch = _rosterActual.map(function(p) { return Object.assign({}, p); });
    _renderRosterTable(_rosterScratch);
  }

  function _resetRoster() {
    _rosterScratch = null;
    if (_rosterActual) _renderRosterTable(_rosterActual);
  }

  function _addRosterPerson() {
    _enterRosterEditMode();
    if (!_rosterScratch) return;
    _rosterScratch.push({
      first_name: 'New', last_name: 'Hire', role: '', department: 'UNKNOWN',
      sheet_department: '', status: '', salary_aud: 0, salary_php: 0,
    });
    _renderRosterTable(_rosterScratch);
  }

  function initRosterControls() {
    var resetBtn = document.getElementById('roster-reset');
    if (resetBtn) resetBtn.addEventListener('click', _resetRoster);

    var addBtn = document.getElementById('roster-add');
    if (addBtn) addBtn.addEventListener('click', _addRosterPerson);

    var fxInput = document.getElementById('roster-fx-rate');
    if (fxInput) {
      fxInput.addEventListener('change', function() {
        _renderRosterTable(_rosterData());
      });
    }

    var wrap = document.getElementById('roster-table-wrap');
    if (wrap) {
      wrap.addEventListener('click', function(e) {
        if (_rosterScratch) return;
        var tr = e.target.closest('tr[data-roster-idx]');
        if (tr) _enterRosterEditMode();
      });
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

  // ── Briefing PDF download ────────────────────────────────
  $('#btn-briefing-pdf').addEventListener('click', async function() {
    const btn = this;
    btn.disabled = true;
    btn.classList.add('loading');
    try {
      const resp = await fetch('/dashboard/api/briefing-pdf');
      if (!resp.ok) {
        // Try to read the error detail from JSON response
        let detail = 'HTTP ' + resp.status;
        try {
          const err = await resp.json();
          detail = err.error || detail;
          if (err.traceback) console.error('PDF traceback:', err.traceback);
        } catch (_) {}
        throw new Error(detail);
      }
      const ct = resp.headers.get('Content-Type') || '';
      if (!ct.includes('application/pdf')) {
        throw new Error('Server returned non-PDF response (Content-Type: ' + ct + ')');
      }
      const blob = await resp.blob();
      if (blob.size < 500) {
        throw new Error('PDF too small (' + blob.size + ' bytes) — likely an error response');
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'served-cfo-briefing.pdf';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('PDF download failed:', e);
      alert('CFO Briefing PDF failed: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.classList.remove('loading');
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
  function _showError(show) {
    var banner = document.getElementById('error-banner');
    if (banner) banner.style.display = show ? 'flex' : 'none';
  }

  function _setUpdating(on) {
    var txt = $('#status-text');
    if (!txt) return;
    if (on) { txt.dataset.prev = txt.textContent; txt.textContent = 'Updating\u2026'; }
    else if (currentSnap) renderStatus(currentSnap);
  }

  async function loadAll() {
    var hadSnap = !!currentSnap;
    if (hadSnap) _setUpdating(true);
    const [snap, history] = await Promise.all([fetchSnapshot(), fetchHistory()]);
    if (history) historyData = history;
    if (snap) {
      _showError(false);
      render(snap);
    } else if (!currentSnap) {
      _showError(true);
    }
    if (hadSnap) _setUpdating(false);
    if (historyData && historyData.length > 1) {
      $('#reps-sparkline-status').textContent = historyData.length + ' days of history';
    }
  }

  (async function init() {
    initNavigation();
    initGlobalWindowSelector();
    initHiringForm();
    initRosterControls();
    initForwardSlider();
    initMetricTips();
    initKeyboardShortcuts();
    var retry = document.getElementById('error-retry');
    if (retry) retry.addEventListener('click', function() { _showError(false); loadAll(); });
    // Instant paint: render the server-inlined snapshot before any fetch
    if (window.__SNAP__) {
      try { render(window.__SNAP__); } catch (e) { console.error('boot render failed:', e); }
    }
    await loadAll();
  })();

  // Auto-refresh every 10 minutes
  setInterval(async () => {
    const snap = await fetchSnapshot();
    if (snap) render(snap);
  }, 600000);

})();
