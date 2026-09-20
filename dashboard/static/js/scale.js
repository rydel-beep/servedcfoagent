/* scale.js — THE SCALING COMPASS interactive layer (bounded enhancement).
   The hero headline is SERVER-RENDERED; everything here runs inside guards —
   a failure renders an honest block, never a blank. Every run is a LABELLED
   SCENARIO through the compass lane; nothing here can write actuals. */
(function () {
  'use strict';
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function $(id) { return document.getElementById(id); }
  function guard(name, fn) {
    try { return fn(); }
    catch (e) {
      console.error('[scale]', name, e);
      try { window.__reportClientError && window.__reportClientError({ kind: 'panel_boundary', detail: 'scale:' + name + ': ' + String(e && e.message || e).slice(0, 300) }); } catch (t) {}
    }
  }
  function fmt$(v) { return v == null ? '—' : '$' + Math.round(v).toLocaleString(); }
  function fmtN(v, d) { return v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d }); }

  var DEFAULTS = window.__SCALE_DEFAULTS__ || {};
  var ITEMS = (DEFAULTS.items || {});
  var CURRENT = null;      // current inputs (from /api/scale/defaults)
  var MEASURED = null;     // pristine measured inputs for reset
  var LAST_RUN = window.__SCALE_BASE_RUN__ || null;
  var BANDS = null;

  // ── inputs panel ─────────────────────────────────────────────────────────
  var CTLS = [
    { k: 'spend_start', label: 'monthly ad spend (start) $', get: function (i) { return i.spend_path.start; }, set: function (i, v) { i.spend_path.start = +v; }, item: 'monthly_spend_baseline' },
    { k: 'spend_shape', label: 'spend shape', select: ['flat', 'ramp'], get: function (i) { return i.spend_path.shape; }, set: function (i, v) { i.spend_path.shape = v; } },
    { k: 'ramp_pct', label: 'ramp %/month', get: function (i) { return i.spend_path.ramp_pct; }, set: function (i, v) { i.spend_path.ramp_pct = +v; } },
    { k: 'cpl0', label: 'CPL₀ $', get: function (i) { return i.cpl0; }, set: function (i, v) { i.cpl0 = +v; }, item: 'cpl' },
    { k: 'epsilon', label: 'CPL elasticity ε', get: function (i) { return i.epsilon; }, set: function (i, v) { i.epsilon = +v; }, item: 'cpl_epsilon' },
    { k: 'set_rate', label: 'set rate (sets ÷ leads)', get: function (i) { return i.set_rate; }, set: function (i, v) { i.set_rate = +v; }, item: 'set_rate' },
    { k: 'show_rate', label: 'show rate (÷ sets, verified)', get: function (i) { return i.show_rate; }, set: function (i, v) { i.show_rate = +v; }, item: 'show_rate' },
    { k: 'close_rate', label: 'close rate (÷ shows)', get: function (i) { return i.close_rate; }, set: function (i, v) { i.close_rate = +v; }, item: 'close_rate' },
    { k: 'renewal_rate', label: 'renewal / resign rate', get: function (i) { return i.renewal_rate; }, set: function (i, v) { i.renewal_rate = +v; }, item: 'renewal_rate' },
    { k: 'commission', label: 'commissions (% of new cash)', get: function (i) { return i.commission_pct_of_cash; }, set: function (i, v) { i.commission_pct_of_cash = +v; }, item: 'commission_pct_of_cash' },
    { k: 'opex', label: 'OpEx ex-tax $/mo', get: function (i) { return i.opex_monthly_ex_tax; }, set: function (i, v) { i.opex_monthly_ex_tax = +v; }, item: 'opex_monthly_ex_tax' },
    { k: 'buffer', label: 'minimum cash buffer $', get: function (i) { return i.min_cash_buffer; }, set: function (i, v) { i.min_cash_buffer = +v; } },
    { k: 'hire_lead', label: 'hire lead time (weeks)', get: function (i) { return i.hire_lead_weeks; }, set: function (i, v) { i.hire_lead_weeks = +v; } }
  ];

  function provChip(itemKey) {
    var it = ITEMS[itemKey];
    if (!it) return '<span class="prov-chip">config</span>';
    var cls = it.assumption ? 'prov-chip prov-assumption' : 'prov-chip';
    var label = it.assumption ? 'ASSUMPTION' : 'measured';
    return '<span class="' + cls + '" title="' + esc(it.provenance || '') + '">' + label +
      (it.n ? ' · n=' + it.n : '') + '</span>' +
      '<div class="scale-prov">' + esc(String(it.provenance || '').slice(0, 120)) + '</div>';
  }

  function renderInputs() {
    var box = $('inputs-body');
    if (!box || !CURRENT) return;
    var html = '';
    CTLS.forEach(function (c) {
      var v = c.get(CURRENT);
      html += '<div class="scale-ctl"><label>' + esc(c.label) +
        ' <a href="#" class="scale-note ctl-reset" data-k="' + c.k + '">reset</a></label>';
      if (c.select) {
        html += '<select data-ctl="' + c.k + '">' + c.select.map(function (o) {
          return '<option value="' + o + '"' + (o === v ? ' selected' : '') + '>' + o + '</option>';
        }).join('') + '</select>';
      } else {
        html += '<input type="number" step="any" data-ctl="' + c.k + '" value="' + (v == null ? '' : v) + '">';
      }
      html += provChip(c.item) + '</div>';
    });
    // deal mix — editable per package (shares normalised by the engine)
    var mix = CURRENT.deal_mix || {};
    html += '<div class="scale-ctl"><label>deal mix by package (shares — engine normalises)</label>';
    Object.keys(mix).forEach(function (k) {
      html += '<div style="display:flex;gap:6px;align-items:center;margin:2px 0">' +
        '<span class="scale-prov" style="min-width:110px">' + esc(k) + '</span>' +
        '<input type="number" step="0.05" min="0" max="1" data-mix="' + esc(k) + '" value="' + mix[k] + '" style="width:80px;background:var(--bg-inset-strong);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:2px 6px"></div>';
    });
    html += provChip('deal_mix') + '</div>';
    var lag = CURRENT.lag_curve || [];
    html += '<div class="scale-ctl"><label>lag curve (t / t+1 / t+2)</label><div class="scale-prov">' +
      lag.map(function (x) { return Math.round(x * 100) + '%'; }).join(' / ') + '</div>' + provChip('lag_curve') + '</div>';
    html += '<div class="scale-ctl"><label>lanes</label><div class="scale-prov">' +
      esc(JSON.stringify((ITEMS.lanes || {}).value || {})) + ' — US falls back to AU rates (labelled)</div></div>';
    box.innerHTML = html;
  }

  document.addEventListener('input', function (e) {
    var mx = e.target.closest('[data-mix]');
    if (mx && CURRENT) {
      guard('mix', function () { CURRENT.deal_mix[mx.dataset.mix] = +mx.value || 0; });
      return;
    }
    var t = e.target.closest('[data-ctl]');
    if (!t || !CURRENT) return;
    var c = CTLS.find(function (x) { return x.k === t.dataset.ctl; });
    if (c) guard('ctl', function () { c.set(CURRENT, t.value); });
  });
  document.addEventListener('click', function (e) {
    var r = e.target.closest('.ctl-reset');
    if (r && CURRENT && MEASURED) {
      e.preventDefault();
      var c = CTLS.find(function (x) { return x.k === r.dataset.k; });
      if (c) guard('reset', function () { c.set(CURRENT, c.get(JSON.parse(JSON.stringify(MEASURED)))); renderInputs(); });
    }
  });


  // ── THE SIMULATOR (Spend ↔ CPL ↔ Leads → the chain) ──────────────────────
  // Pure arithmetic mirroring /api/scale/simulate exactly (the gate compares
  // the rendered numbers against the server for the same inputs). A labelled
  // what-if — nothing here can write anything.
  var SIM = null;   // aggregates from the server first paint / defaults
  var simState = { spend: 0, cpl: 0, leads: 0, lock: 'cpl', curve: false,
                   set: 0, show: 0, close: 0 };
  function simInit() {
    var payload = window.__SCALE_SIM__ || null;
    if (!payload) return;
    SIM = payload;
    simState.spend = payload.spend; simState.cpl = payload.cpl_base;
    simState.leads = payload.leads;
    simState.set = payload.rates.set; simState.show = payload.rates.show;
    simState.close = payload.rates.close;
    simRecompute('spend');
    drawSimChart();
  }
  function cplEff(spend, cplBase) {
    if (!simState.curve || !SIM) return cplBase;
    var S0 = SIM.spend_baseline || 1;
    return cplBase * Math.pow(Math.max(spend, 1) / S0, SIM.epsilon || 0);
  }
  function simRecompute(edited) {
    if (!SIM) return;
    var st = simState;
    // the locked field never moves; the edited field drives; the third answers
    if (edited === 'spend') {
      if (st.lock === 'cpl') st.leads = st.spend / cplEff(st.spend, st.cpl);
      else if (st.lock === 'leads') st.cpl = st.leads ? st.spend / st.leads : st.cpl;
      else st.leads = st.spend / cplEff(st.spend, st.cpl);
    } else if (edited === 'leads') {
      if (st.lock === 'cpl') st.spend = st.leads * cplEff(st.spend, st.cpl);
      else if (st.lock === 'spend') st.cpl = st.leads ? st.spend / st.leads : st.cpl;
      else st.spend = st.leads * cplEff(st.spend, st.cpl);
    } else if (edited === 'cpl') {
      if (st.lock === 'spend') st.leads = st.spend / cplEff(st.spend, st.cpl);
      else if (st.lock === 'leads') st.spend = st.leads * cplEff(st.spend, st.cpl);
      else st.leads = st.spend / cplEff(st.spend, st.cpl);
    }
    renderSim(edited);
  }
  function chainNumbers() {
    var st = simState;
    var eff = cplEff(st.spend, st.cpl);
    var leads = st.spend / (eff || 1);
    var calls = leads * st.set, shows = calls * st.show, clients = shows * st.close;
    var cashNow = clients * SIM.m0_share * SIM.contract_avg;
    var cashTerm = clients * SIM.contract_avg;
    var mrr = clients * SIM.mrr_avg;
    var comm = SIM.comm_rate * cashTerm;
    var cac = clients >= 0.01 ? (st.spend + comm + SIM.tooling) / clients : null;
    var cacSO = clients >= 0.01 ? st.spend / clients : null;
    var ltgp = SIM.contract_avg * SIM.margin_avg;
    return { eff: eff, leads: leads, calls: calls, shows: shows, clients: clients,
             cashNow: cashNow, cashTerm: cashTerm, mrr: mrr, comm: comm,
             cac: cac, cacSO: cacSO, ltgp: ltgp,
             ltgpCac: cac ? ltgp / cac : null };
  }
  function set$(id, v) { var el = $(id); if (el) el.textContent = v; }
  function renderSim(edited) {
    var st = simState, c = chainNumbers();
    if (edited !== 'spend' && $('sim-spend')) $('sim-spend').value = Math.round(st.spend);
    if (edited !== 'leads' && $('sim-leads')) $('sim-leads').value = Math.round(c.leads);
    if ($('sim-cpl') && document.activeElement !== $('sim-cpl')) $('sim-cpl').value = c.eff.toFixed(2);
    set$('sim-sentence', 'At $' + Math.round(st.spend).toLocaleString() + '/mo and $' +
      c.eff.toFixed(2) + ' per lead → ' + Math.round(c.leads) + ' leads/month.' +
      (simState.curve ? ' (CPL climbing with spend is ON)' : ''));
    set$('chain-calls-v', Math.round(c.calls));
    set$('chain-shows-v', Math.round(c.shows));
    set$('chain-clients-v', c.clients.toFixed(1));
    set$('chain-cash-v', fmt$(c.cashNow));
    set$('chain-cashterm-v', fmt$(c.cashTerm));
    set$('chain-mrr-v', fmt$(c.mrr));
    set$('chain-cac-v', c.cac ? fmt$(c.cac) : '—');
    set$('chain-cacso-v', c.cacSO ? fmt$(c.cacSO) : '—');
    set$('chain-ltgp-v', c.ltgpCac ? c.ltgpCac.toFixed(2) : '—');
    // keep the deep-plan inputs in sync so Run/Solve use the same what-if
    if (CURRENT) {
      CURRENT.spend_path.start = st.spend;
      CURRENT.cpl0 = st.cpl;
      CURRENT.set_rate = st.set; CURRENT.show_rate = st.show;
      CURRENT.close_rate = st.close;
    }
    renderShowMath(c);
    drawSimChart();
  }
  function renderShowMath(c) {
    var out = $('show-math-out');
    if (!out) return;
    var on = $('chk-show-math') && $('chk-show-math').checked;
    out.style.display = on ? '' : 'none';
    if (!on) return;
    var st = simState;
    out.textContent =
      '$' + Math.round(st.spend).toLocaleString() + ' ÷ $' + c.eff.toFixed(2) + ' per lead = ' + Math.round(c.leads) + ' leads\n' +
      Math.round(c.leads) + ' leads × ' + Math.round(st.set * 100) + '% booking rate = ' + Math.round(c.calls) + ' calls\n' +
      Math.round(c.calls) + ' calls × ' + Math.round(st.show * 100) + '% turn-up rate = ' + Math.round(c.shows) + ' shows\n' +
      Math.round(c.shows) + ' shows × ' + Math.round(st.close * 100) + '% close rate = ' + c.clients.toFixed(1) + ' new clients\n' +
      c.clients.toFixed(1) + ' clients × ' + Math.round(SIM.m0_share * 100) + '% first-month share × $' + Math.round(SIM.contract_avg).toLocaleString() + ' avg contract = ' + fmt$(c.cashNow) + ' cash this month\n' +
      c.clients.toFixed(1) + ' clients × $' + Math.round(SIM.contract_avg).toLocaleString() + ' = ' + fmt$(c.cashTerm) + ' over the term · × $' + Math.round(SIM.mrr_avg).toLocaleString() + '/mo = ' + fmt$(c.mrr) + '/mo revenue added\n' +
      '($' + Math.round(st.spend).toLocaleString() + ' ads + ' + fmt$(c.comm) + ' commissions + $' + Math.round(SIM.tooling).toLocaleString() + ' sales tools) ÷ ' + c.clients.toFixed(1) + ' clients = ' + (c.cac ? fmt$(c.cac) : '—') + ' per client';
  }
  function drawSimChart() {
    var cv = $('sim-chart');
    if (!cv || !SIM || !cv.getContext) return;
    var ctx = cv.getContext('2d');
    var W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    var maxS = Math.max(simState.spend * 2.2, 20000);
    ctx.strokeStyle = 'rgba(91,155,208,0.9)'; ctx.lineWidth = 2; ctx.beginPath();
    var maxLeads = maxS / cplEff(maxS, simState.cpl);
    if (!simState.curve) maxLeads = maxS / simState.cpl;
    for (var x = 0; x <= 60; x++) {
      var sp = maxS * x / 60;
      var ld = sp / (cplEff(sp, simState.cpl) || 1);
      var px = 30 + (W - 40) * sp / maxS;
      var py = H - 18 - (H - 30) * (ld / (maxLeads * 1.05 || 1));
      x === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.stroke();
    // current point
    var cp = chainNumbers();
    var px0 = 30 + (W - 40) * simState.spend / maxS;
    var py0 = H - 18 - (H - 30) * (cp.leads / (maxLeads * 1.05 || 1));
    ctx.fillStyle = '#E8B445'; ctx.beginPath(); ctx.arc(px0, py0, 5, 0, 7); ctx.fill();
    ctx.fillStyle = 'rgba(167,188,210,0.8)'; ctx.font = '10px Archivo';
    ctx.fillText('$' + Math.round(simState.spend).toLocaleString() + ' → ' + Math.round(cp.leads) + ' leads', Math.min(px0 + 8, W - 130), Math.max(py0 - 8, 12));
    ctx.fillText('spend →', W - 55, H - 4);
    ctx.save(); ctx.translate(10, H / 2); ctx.rotate(-Math.PI / 2); ctx.fillText('leads →', 0, 0); ctx.restore();
  }
  function chartDrag(ev) {
    var cv = $('sim-chart');
    if (!cv) return;
    var r = cv.getBoundingClientRect();
    var frac = (ev.clientX - r.left - 30 * r.width / cv.width) / (r.width * (cv.width - 40) / cv.width);
    var maxS = Math.max(simState.spend * 2.2, 20000);
    var sp = Math.max(500, Math.min(maxS, frac * maxS));
    if (simState.lock !== 'spend') { simState.spend = sp; simRecompute('spend'); }
  }
  var dragging = false;
  document.addEventListener('pointerdown', function (e) { if (e.target.id === 'sim-chart') { dragging = true; chartDrag(e); } });
  document.addEventListener('pointermove', function (e) { if (dragging) chartDrag(e); });
  document.addEventListener('pointerup', function () { dragging = false; });

  document.addEventListener('input', function (e) {
    if (!SIM) return;
    var id = e.target.id;
    if (id === 'sim-spend' && simState.lock !== 'spend') { simState.spend = +e.target.value || 0; simRecompute('spend'); }
    if (id === 'sim-leads' && simState.lock !== 'leads') { simState.leads = +e.target.value || 0; simRecompute('leads'); }
    if (id === 'sim-cpl' && simState.lock !== 'cpl') { simState.cpl = +e.target.value || simState.cpl; simRecompute('cpl'); }
    if (id === 'rate-set') { simState.set = +e.target.value || 0; simRecompute('rates'); }
    if (id === 'rate-show') { simState.show = +e.target.value || 0; simRecompute('rates'); }
    if (id === 'rate-close') { simState.close = +e.target.value || 0; simRecompute('rates'); }
  });
  document.addEventListener('change', function (e) {
    if (e.target.id === 'sim-cpl-mode') { simState.curve = e.target.checked; simRecompute('spend'); }
    if (e.target.id === 'chk-show-math') renderSim('none');
  });
  document.addEventListener('click', function (e) {
    var lk = e.target.closest && e.target.closest('.sim-lock');
    if (lk) {
      e.preventDefault();
      simState.lock = lk.dataset.lock;
      document.querySelectorAll('.sim-lock').forEach(function (b) {
        var on = b.dataset.lock === simState.lock;
        b.classList.toggle('locked', on);
        b.textContent = on ? '🔒' : '🔓';
      });
      return;
    }
    var rr = e.target.closest && e.target.closest('.rate-reset');
    if (rr && SIM) {
      e.preventDefault();
      var k = rr.dataset.r;
      simState[k] = SIM.rates[k];
      var el = $('rate-' + k); if (el) el.value = SIM.rates[k];
      simRecompute('rates');
      return;
    }
    var pr = e.target.closest && e.target.closest('.sim-preset');
    if (pr && SIM) {
      guard('preset', function () {
        if (pr.dataset.preset === 'measured') {
          simState.spend = SIM.spend; simState.cpl = SIM.cpl_base;
          simState.set = SIM.rates.set; simState.show = SIM.rates.show; simState.close = SIM.rates.close;
          ['set','show','close'].forEach(function (k) { var el = $('rate-' + k); if (el) el.value = SIM.rates[k]; });
        } else if (pr.dataset.preset === 'plus50') {
          simState.spend = SIM.spend * 1.5;
        } else if (pr.dataset.preset === 'close35') {
          simState.close = 0.35;
          var el = $('rate-close'); if (el) el.value = 0.35;
        }
        simRecompute('spend');
      });
      return;
    }
    if (e.target.id === 'btn-iwant') { guard('iwant', iWant); }
  });
  function iWant() {
    if (!SIM) return;
    var kind = $('iwant-kind').value, val = +$('iwant-value').value || 0;
    var st = simState;
    // work backwards to the clients / leads needed, then the spend
    var perClientCash = SIM.m0_share * SIM.contract_avg;
    var clients = null;
    if (kind === 'clients') clients = val;
    if (kind === 'cash') clients = val / (perClientCash || 1);
    if (kind === 'mrr') clients = val / (SIM.mrr_avg || 1);
    var leads;
    if (kind === 'leads') leads = val;
    else if (kind === 'calls') leads = val / (st.set || 1);
    else leads = clients / ((st.set * st.show * st.close) || 1);
    // spend at the current CPL (solve the curve by iteration when it's on)
    var spend = leads * st.cpl;
    if (simState.curve) {
      for (var i = 0; i < 30; i++) spend = leads * cplEff(spend, st.cpl);
    }
    var calls = leads * st.set, shows = calls * st.show;
    var signs = shows * st.close;
    // what changes if close = 35%
    var leads35 = (clients != null ? clients : signs) / ((st.set * st.show * 0.35) || 1);
    var spend35 = leads35 * st.cpl;
    if (simState.curve) { for (var j = 0; j < 30; j++) spend35 = leads35 * cplEff(spend35, st.cpl); }
    var showsClause = (kind === 'clients' || kind === 'cash' || kind === 'mrr')
      ? ' What has to be true: ' + Math.round(leads) + ' leads → ' + Math.round(calls) + ' calls → ' + Math.round(shows) + ' turn up → ' + signs.toFixed(1) + ' sign.'
      : ' That books ' + Math.round(calls) + ' calls and ' + signs.toFixed(1) + ' signings at today\u2019s rates.';
    var deltaClause = (kind !== 'leads' && kind !== 'calls')
      ? ' If the close rate were 35% instead of ' + Math.round(st.close * 100) + '%, the spend needed drops to ' + fmt$(spend35) + '/mo.'
      : '';
    $('iwant-out').innerHTML = '<b>' + fmt$(spend) + '/mo of ad spend</b> at $' + st.cpl.toFixed(2) +
      ' per lead' + (simState.curve ? ' (with CPL climbing as spend grows)' : '') + '.' +
      showsClause + deltaClause + ' <span style="opacity:.7">what-if — nothing recorded</span>';
  }

  // ── run + views ──────────────────────────────────────────────────────────
  async function runForward() {
    var st = $('run-status');
    st.textContent = 'running the compass…';
    try {
      var r = await fetch('/dashboard/api/scale/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ inputs: CURRENT }) });
      if (!r.ok) { st.textContent = 'run failed (' + r.status + ')'; return; }
      LAST_RUN = await r.json();
      BANDS = null;
      if ($('chk-bands').checked) {
        st.textContent = 'computing ranges (Monte Carlo)…';
        var rb = await fetch('/dashboard/api/scale/bands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ inputs: CURRENT }) });
        if (rb.ok) BANDS = await rb.json();
      }
      st.textContent = 'scenario computed · ' + (LAST_RUN.label || '');
      renderAll();
    } catch (e) { st.textContent = 'run failed: ' + String(e); }
  }

  function renderRoadmap() {
    var wrap = $('roadmap-wrap');
    if (!wrap || !LAST_RUN) return;
    var lbl = $('roadmap-label');
    if (lbl) lbl.textContent = '· capital dip ' + fmt$(LAST_RUN.capital_dip) + ' · ' + (LAST_RUN.label || '');
    var p25 = BANDS && BANDS.mrr ? BANDS.mrr.p25 : null;
    var p75 = BANDS && BANDS.mrr ? BANDS.mrr.p75 : null;
    var html = '<table class="scale-table"><thead><tr>' +
      '<th>month</th><th>spend</th><th>CPL</th><th>leads</th><th>calls</th><th>shows</th><th>closes</th>' +
      '<th>new MRR</th><th>churn</th><th>net MRR</th>' + (p25 ? '<th>MRR P25–P75</th>' : '') +
      '<th>cash: new cohort</th><th>cash: existing book</th><th>cash in</th><th>costs</th><th>net cash</th><th>position</th><th>CAC (period, loaded)</th><th>CAC (spend-only)</th><th>LTGP:CAC</th>' +
      '<th>heads</th><th>binding constraint</th></tr></thead><tbody>';
    LAST_RUN.months.forEach(function (m, i) {
      var b = m.binding_constraint || {};
      var bcls = 'bind-' + (b.name || '').split(' ')[0].replace(/[^A-Z]/g, '');
      var heads = m.headcount_effective || {};
      html += '<tr><td>' + m.month + '</td><td>' + fmt$(m.spend) + '</td><td>' + fmt$(m.cpl) + '</td>' +
        '<td>' + fmtN(m.leads, 0) + '</td><td>' + fmtN(m.calls_booked, 0) + '</td><td>' + fmtN(m.shows, 0) + '</td>' +
        '<td>' + fmtN(m.closes, 1) + '</td><td>' + fmt$(m.mrr_new) + '</td><td>' + fmt$(m.churn_mrr) + '</td>' +
        '<td><b>' + fmt$(m.net_mrr) + '</b></td>' +
        (p25 ? '<td>' + fmt$(p25[i]) + '–' + fmt$(p75[i]) + '</td>' : '') +
        '<td>' + fmt$(m.cash_new_cohort) + '</td><td>' + fmt$(m.cash_existing_book) + '</td>' +
        '<td>' + fmt$(m.cash_in) + '</td><td>' + fmt$(m.costs_total) + '</td><td>' + fmt$(m.net_cash) + '</td>' +
        '<td>' + fmt$(m.position) + '</td><td>' + fmt$(m.cac_period) + '</td><td>' + fmt$(m.cac_period_spend_only) + '</td><td>' + fmtN(m.ltgp_cac, 2) + '×</td>' +
        '<td>' + fmtN((heads.setters || 0) + (heads.closers || 0) + (heads.delivery || 0), 1) + '</td>' +
        '<td class="' + bcls + '" title="' + esc(b.why || '') + '">' + esc(b.name || '') + ' — ' + esc((b.why || '').slice(0, 60)) + '</td></tr>';
    });
    wrap.innerHTML = html + '</tbody></table>';
  }

  function renderMoney() {
    var wrap = $('money-wrap');
    if (!wrap || !LAST_RUN) return;
    var html = '<table class="scale-table"><thead><tr><th>lead month</th><th>cohort CAC (loaded)</th>' +
      '<th>cohort CAC (spend-only)</th><th>eventual closes</th><th>payback (months)</th></tr></thead><tbody>';
    (LAST_RUN.cohorts || []).forEach(function (c) {
      html += '<tr><td>' + c.lead_month + '</td><td>' + fmt$(c.cac_cohort) + '</td><td>' + fmt$(c.cac_cohort_spend_only) + '</td><td>' +
        fmtN(c.closes_eventual, 1) + '</td><td>' + (c.payback_months == null ? 'beyond the schedule' : c.payback_months) + '</td></tr>';
    });
    wrap.innerHTML = html + '</tbody></table>';
    var m0 = LAST_RUN.months[0] || {};
    $('money-note').textContent = 'period CAC ≠ cohort CAC under lag (both shown — never conflated) · ' +
      'client-financed check month 1: ' + fmtN(m0.client_financed_check, 2) + '× (30-day cash ÷ CAC; 2.0 = benchmark, not target) · ' +
      (LAST_RUN.tax_beside && LAST_RUN.tax_beside.note || '');
  }

  function renderTeam() {
    var wrap = $('team-wrap');
    if (!wrap || !LAST_RUN) return;
    var rows = LAST_RUN.months.filter(function (_, i) { return i % 3 === 0; });
    var html = '<table class="scale-table"><thead><tr><th>month</th><th>setter util</th><th>closer util</th><th>delivery util</th></tr></thead><tbody>';
    rows.forEach(function (m) {
      var u = m.utilisation || {};
      html += '<tr><td>' + m.month + '</td><td>' + fmtN(u.setters, 0) + '%</td><td>' + fmtN(u.closers, 0) + '%</td><td>' + fmtN(u.delivery, 0) + '%</td></tr>';
    });
    html += '</tbody></table>';
    html += '<div style="margin-top:8px"><b class="scale-note">HIRE CARDS</b>';
    (LAST_RUN.hire_cards || []).forEach(function (c) { html += '<div class="exp-row">' + esc(c) + '</div>'; });
    if (!(LAST_RUN.hire_cards || []).length) html += '<div class="scale-note">no hires required inside the horizon</div>';
    wrap.innerHTML = html + '</div>';
  }

  function renderBacktest() {
    var bt = window.__SCALE_BACKTEST__;
    var wrap = $('backtest-wrap');
    if (!wrap || !bt || !bt.months) return;
    var html = '<table class="scale-table"><thead><tr><th>month</th><th>spend</th>' +
      '<th>leads p/a</th><th>sets p/a</th><th>shows p/a</th><th>closes p/a</th></tr></thead><tbody>';
    bt.months.forEach(function (m) {
      if (m.error) { html += '<tr><td>' + m.month + '</td><td colspan="5">' + esc(m.error) + '</td></tr>'; return; }
      function pa(x) { return x.pred + ' / ' + x.actual + (x.ape_pct != null ? ' (±' + x.ape_pct + '%)' : ''); }
      html += '<tr><td>' + m.month + '</td><td>' + fmt$(m.spend_actual) + '</td><td>' + pa(m.leads) +
        '</td><td>' + pa(m.sets) + '</td><td>' + pa(m.shows) + '</td><td>' + pa(m.closes) + '</td></tr>';
    });
    wrap.innerHTML = html + '</tbody></table>';
  }

  function renderAll() {
    guard('roadmap', renderRoadmap);
    guard('money', renderMoney);
    guard('team', renderTeam);
  }

  // ── solver ───────────────────────────────────────────────────────────────
  async function solveTarget() {
    var out = $('solver-out');
    out.textContent = 'bisecting the spend path…';
    try {
      var target = { kind: $('tgt-kind').value, month: $('tgt-month').value, value: +$('tgt-value').value };
      var r = await fetch('/dashboard/api/scale/solve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: target, inputs: CURRENT }) });
      var d = await r.json();
      if (d.error) { out.textContent = d.error; return; }
      if (!d.feasible) {
        out.innerHTML = '<b>INFEASIBLE</b> under the current rates/constraints — first break: <b>' +
          esc((d.breaks_first || {}).name || '') + '</b> (' + esc((d.breaks_first || {}).why || '') + '). ' +
          'Nearest feasible outcome at ' + d.nearest.scale + '× spend: ' + fmt$(d.nearest.outcome) + '.';
        return;
      }
      var req = d.required || {};
      var m0 = (req.spend_by_month || [])[0] || {};
      var mEnd = (req.spend_by_month || [])[req.spend_by_month.length - 1] || {};
      out.innerHTML = '<b>Feasible at ' + d.scale + '× the current spend shape.</b> ' +
        'Required: spend ' + fmt$(m0.spend) + '/mo now → ' + fmt$(mEnd.spend) + '/mo by ' + esc(mEnd.month || '') +
        ' · leads ' + fmtN(m0.leads, 0) + '→' + fmtN(mEnd.leads, 0) +
        ' · calls ' + fmtN(m0.calls, 0) + '→' + fmtN(mEnd.calls, 0) +
        ' · closes ' + fmtN(m0.closes, 1) + '→' + fmtN(mEnd.closes, 1) + '/mo' +
        ' · capital dip ' + fmt$(req.capital_dip) +
        ' · hires: ' + (req.hires && req.hires.length ? esc(req.hires.join(' · ')) : 'none') +
        ' · achieved ' + fmt$(d.achieved) + ' (target ' + fmt$(target.value) + ') — ' + esc(d.label || '');
      LAST_RUN = d.roadmap; BANDS = null;
      renderAll();
    } catch (e) { out.textContent = 'solver failed: ' + String(e); }
  }

  // ── scenarios + plan ─────────────────────────────────────────────────────
  async function saveScenario() {
    var name = $('sc-name').value.trim();
    var out = $('sc-out');
    if (!name) { out.textContent = 'name the scenario first'; return; }
    var r = await fetch('/dashboard/api/scale/scenarios', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name, inputs: CURRENT }) });
    var d = await r.json();
    out.textContent = d.error || ('saved "' + name + '" (' + d.count + ' scenarios)');
  }
  async function compareScenarios() {
    var out = $('sc-out');
    var r = await fetch('/dashboard/api/scale/scenarios?full=1');
    var d = await r.json();
    var list = (d.scenarios || []);
    if (!list.length) { out.textContent = 'no saved scenarios yet — Save current inputs first'; return; }
    out.textContent = 'running ' + list.length + ' scenario(s) side by side…';
    var html = '<table class="scale-table"><thead><tr><th>scenario</th><th>end month</th>' +
      '<th>end net MRR</th><th>closes (total)</th><th>capital dip</th><th>first non-lead constraint</th></tr></thead><tbody>';
    for (var i = 0; i < list.length; i++) {
      try {
        var rr = await fetch('/dashboard/api/scale/run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ inputs: list[i].inputs || {} }) });
        if (!rr.ok) { html += '<tr><td>' + esc(list[i].name) + '</td><td colspan="5">run failed (' + rr.status + ')</td></tr>'; continue; }
        var run = await rr.json();
        var last = run.months[run.months.length - 1];
        var closes = run.months.reduce(function (a, m) { return a + (m.closes || 0); }, 0);
        var bind = run.months.map(function (m) { return m.binding_constraint || {}; })
          .find(function (b) { return b.name && b.name.indexOf('LEADS') !== 0; });
        html += '<tr><td>' + esc(list[i].name) + '</td><td>' + last.month + '</td><td><b>' + fmt$(last.net_mrr) +
          '</b></td><td>' + fmtN(closes, 0) + '</td><td>' + fmt$(run.capital_dip) + '</td><td>' +
          esc(bind ? bind.name : 'none — spend is the lever') + '</td></tr>';
      } catch (e) {
        html += '<tr><td>' + esc(list[i].name) + '</td><td colspan="5">' + esc(String(e)) + '</td></tr>';
      }
    }
    out.innerHTML = html + '</tbody></table><div class="scale-note">every row is a LABELLED SCENARIO — deltas, never actuals</div>';
  }
  async function commitPlan() {
    var name = $('sc-name').value.trim();
    var out = $('sc-out');
    if (!name) { out.textContent = 'name (and save) the scenario to commit'; return; }
    if (!window.confirm('Commit "' + name + '" as Plan 2027 (versioned plan-of-record — a labelled scenario, never actuals)?')) return;
    var r = await fetch('/dashboard/api/scale/commit-plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name, confirm: true }) });
    var d = await r.json();
    out.textContent = d.error || ('Plan 2027 committed — version ' + d.version + ' (' + d.months + ' months). The dashboard pacing row reads it.');
    loadPacing();
  }
  async function loadPacing() {
    var box = $('pacing-out');
    try {
      var r = await fetch('/dashboard/api/scale/plan-vs-actual');
      var d = await r.json();
      if (!d.available) { box.innerHTML = '<span class="scale-note">' + esc(d.note || '') + '</span>'; return; }
      var html = '<b class="scale-note">PLAN v' + d.version + ' (' + esc(d.name) + ') vs ACTUAL</b>' +
        '<table class="scale-table"><thead><tr><th>month</th><th>spend p/a</th><th>leads p/a</th><th>closes p/a</th><th>cause hints</th></tr></thead><tbody>';
      (d.rows || []).forEach(function (m) {
        if (m.error) { html += '<tr><td>' + m.month + '</td><td colspan="4">' + esc(m.error) + '</td></tr>'; return; }
        html += '<tr><td>' + m.month + (m.partial ? ' (partial)' : '') + '</td>' +
          '<td>' + fmt$(m.spend.plan) + ' / ' + fmt$(m.spend.actual) + '</td>' +
          '<td>' + fmtN(m.leads.plan, 0) + ' / ' + m.leads.actual + '</td>' +
          '<td>' + fmtN(m.closes.plan, 1) + ' / ' + m.closes.actual + '</td>' +
          '<td>' + esc((m.cause_hints || []).join('; ')) + '</td></tr>';
      });
      box.innerHTML = html + '</tbody></table>';
    } catch (e) { box.textContent = 'pacing failed: ' + String(e); }
  }

  // ── boot ─────────────────────────────────────────────────────────────────
  (async function init() {
    guard('sim', simInit);
    guard('backtest', renderBacktest);
    if (LAST_RUN) renderAll();
    try {
      var r = await fetch('/dashboard/api/scale/defaults');
      if (r.ok) {
        var d = await r.json();
        CURRENT = d.inputs;
        MEASURED = JSON.parse(JSON.stringify(d.inputs));
        if (d.defaults && d.defaults.items) { ITEMS = d.defaults.items; }
        renderInputs();
      } else {
        $('inputs-body').innerHTML = '<div class="panel-boundary-fail">inputs unavailable (' + r.status + ')</div>';
      }
    } catch (e) {
      $('inputs-body').innerHTML = '<div class="panel-boundary-fail">inputs failed: ' + esc(String(e)) + '</div>';
    }
    var b;
    (b = $('btn-run')) && b.addEventListener('click', function () { guard('run', runForward); });
    (b = $('btn-solve')) && b.addEventListener('click', function () { guard('solve', solveTarget); });
    (b = $('btn-save-sc')) && b.addEventListener('click', function () { guard('save', saveScenario); });
    (b = $('btn-compare-sc')) && b.addEventListener('click', function () { guard('compare', compareScenarios); });
    (b = $('btn-commit-plan')) && b.addEventListener('click', function () { guard('commit', commitPlan); });
    (b = $('btn-reset-all')) && b.addEventListener('click', function () {
      guard('resetAll', function () { CURRENT = JSON.parse(JSON.stringify(MEASURED)); renderInputs(); });
    });
    guard('pacing', loadPacing);
  })();
})();
