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


  // ── THE SIMULATOR, LOCK-FREE (two inputs, one output) ────────────────────
  // Rydel's failure was lock semantics silently dropping his CPL edits.
  // NOW: SPEND and CPL are ALWAYS inputs; LEADS is ALWAYS the worked-out
  // answer. Elasticity mode makes CPL explicitly read-only-derived (visibly
  // disabled — never an editable-looking field that ignores typing).
  // Target mode is a separate labelled toggle where SPEND becomes the
  // answer. All arithmetic = SimCore (the SAME file the parity test runs
  // against the engine); on settle the server re-checks and WINS on any
  // real mismatch (logged to telemetry).
  var SIM = null;           // engine aggregates (from the server first paint)
  var simState = { spend: 0, cpl: 0, curve: false, mode: 'forward',
                   set: 0, show: 0, close: 0 };
  function agg() { return SIM; }
  function rates() { return { set: simState.set, show: simState.show, close: simState.close }; }

  function simInit() {
    var payload = window.__SCALE_SIM__ || null;
    if (!payload || !window.SimCore) return;
    SIM = payload;
    simState.spend = payload.spend;
    simState.cpl = payload.cpl_base;
    simState.set = payload.rates.set; simState.show = payload.rates.show;
    simState.close = payload.rates.close;
    simForward('init');
  }

  function currentChain() {
    return window.SimCore.chain(simState.spend, simState.cpl, rates(), agg(), simState.curve);
  }

  function set$(id, v) { var el = $(id); if (el) el.textContent = v; }

  function simForward(source) {
    if (!SIM) return;
    var c = currentChain();
    var leadsEl = $('sim-leads');
    if (leadsEl) leadsEl.textContent = Math.round(c.leads).toLocaleString();
    // keep number + slider views of each INPUT in sync (never fighting the
    // field being typed in)
    if (source !== 'spend-num' && $('sim-spend')) $('sim-spend').value = Math.round(simState.spend);
    if (source !== 'spend-slider' && $('sim-spend-slider')) $('sim-spend-slider').value = Math.round(simState.spend);
    if (simState.curve) {
      if ($('sim-cpl')) $('sim-cpl').value = c.cpl_effective.toFixed(2);
      var n = $('sim-cpl-note');
      if (n) n.textContent = 'effective CPL at this spend: $' + c.cpl_effective.toFixed(2) +
        ' (your base $' + simState.cpl.toFixed(2) + ' climbs as spend grows)';
    } else {
      if (source !== 'cpl-num' && $('sim-cpl')) $('sim-cpl').value = simState.cpl.toFixed(2);
      if (source !== 'cpl-slider' && $('sim-cpl-slider')) $('sim-cpl-slider').value = Math.round(simState.cpl);
      var n2 = $('sim-cpl-note'); if (n2) n2.textContent = '';
    }
    set$('sim-sentence', 'At $' + Math.round(simState.spend).toLocaleString() + '/mo and $' +
      c.cpl_effective.toFixed(2) + ' per lead → ' + Math.round(c.leads) + ' leads/month.');
    renderChain(c);
    drawSimChart();
    updateTravellingLink();
    settleCheck();
  }

  // the "Show how we're travelling" button carries WHAT'S ON SCREEN — the
  // live month is then laid against exactly what you just modelled
  function updateTravellingLink() {
    var a = $('btn-travelling');
    if (!a) return;
    try {
      var payload = {
        spend_path: { shape: 'flat', start: simState.spend },
        cpl0: simState.cpl, set_rate: simState.set,
        show_rate: simState.show, close_rate: simState.close
      };
      var b64 = btoa(JSON.stringify(payload))
        .replace(/\+/g, '-').replace(/\//g, '_');
      a.href = '/dashboard/scale/travelling?compare=scenario&window=mtd&s=' + b64;
    } catch (e) { /* the plain link still works */ }
  }

  /* ── REQUIRED-RATE SOLVE (5.1) ──────────────────────────────────────
     Typing a count into a stage asks: what rate would that stage need,
     from the traffic already above it? Upstream is held; only this stage's
     rate moves, and the flag says whether the answer is achievable. */
  var SOLVED = {};        // stage → the solved rate, while it is in force

  /* The band a rate has actually been measured within — the 95% interval
     around the measured rate given its own sample size (the same interval
     the travelling status bands use). NOT the Monte-Carlo path bands, which
     describe MRR and cash, not rates. */
  /* The rate as MEASURED — never the one a solve has since applied. */
  function measuredRate(key) {
    var d = (window.__SCALE_DEFAULTS__ || {}).items || {};
    var it = d[{set: 'set_rate', show: 'show_rate', close: 'close_rate'}[key]] || {};
    if (typeof it.value === 'number') return it.value;
    if (MEASURED && typeof MEASURED[key + '_rate'] === 'number')
      return MEASURED[key + '_rate'];
    return null;
  }

  function rateBands() {
    var d = (window.__SCALE_DEFAULTS__ || {}).items || {};
    var out = {};
    [['set', 'set_rate'], ['show', 'show_rate'], ['close', 'close_rate']]
      .forEach(function (pair) {
        var it = d[pair[1]] || {};
        var p = it.value, n = it.n;
        if (typeof p !== 'number' || !n || n < 2) return;
        var half = 1.96 * Math.sqrt(Math.max(p * (1 - p), 0) / n);
        out[pair[0]] = [Math.max(p - half, 0), Math.min(p + half, 1)];
      });
    return out;
  }

  function clearSolved(stage) {
    if (stage) delete SOLVED[stage]; else SOLVED = {};
    ['calls', 'shows', 'clients'].forEach(function (st) {
      if (stage && st !== stage) return;
      var box = $('req-' + st);
      if (box) { box.hidden = true; box.textContent = ''; box.className = 'req-rate'; }
      var rst = document.querySelector('.count-reset[data-stage="' + st + '"]');
      if (rst) rst.hidden = true;
    });
  }

  function solveStage(stage, raw) {
    var wanted = parseFloat(raw);
    if (raw === '' || isNaN(wanted)) {           // cleared → back to derived
      clearSolved(stage);
      simForward('rates');
      return;
    }
    // Compare against the MEASURED rate, not the one a previous solve just
    // wrote into the field — otherwise a second keystroke reads "0 points
    // above" and the comparison that is the whole point disappears. The
    // behaviour gate caught exactly this.
    var live = { set: simState.set, show: simState.show, close: simState.close };
    var sol = SimCore.requiredRate(
      stage, wanted, simState.spend, simState.cpl, live,
      agg(), simState.curve, rateBands());
    if (sol && sol.required !== null) {
      var key = SimCore.RATE_OF[stage];
      var m = measuredRate(key);
      if (m !== null) {
        sol.measured = m;
        sol.points = (sol.required - m) * 100;
      }
    }
    if (!sol) return;
    var box = $('req-' + stage);
    var rst = document.querySelector('.count-reset[data-stage="' + stage + '"]');
    if (rst) rst.hidden = false;
    if (box) {
      box.hidden = false;
      box.className = 'req-rate is-' + sol.flag;
      if (sol.required === null) {
        box.textContent = sol.note;
      } else {
        var pts = Math.abs(sol.points).toFixed(0);
        box.textContent =
          'required ' + (sol.required * 100).toFixed(0) + '%, measured ' +
          (sol.measured * 100).toFixed(0) + '%, ' + pts + ' point' +
          (pts === '1' ? '' : 's') + ' ' +
          (sol.points >= 0 ? 'above' : 'below') + ' — ' + sol.note;
      }
    }
    if (sol.required !== null && sol.flag !== 'impossible') {
      SOLVED[stage] = sol;
      var rateEl = $('rate-' + sol.rate_key);
      if (rateEl) rateEl.value = (sol.required * 100).toFixed(0);
      simState[sol.rate_key] = sol.required;
      simForward('solve');
    }
  }

  function renderChain(c) {
    setCount('chain-calls-v', Math.round(c.calls));
    setCount('chain-shows-v', Math.round(c.shows));
    setCount('chain-clients-v', c.clients.toFixed(1));
    set$('chain-cash-v', fmt$(c.cash_this_month));
    set$('chain-cashterm-v', fmt$(c.cash_over_term));
    set$('chain-mrr-v', fmt$(c.mrr_added));
    set$('chain-cac-v', c.cac ? fmt$(c.cac) : '—');
    set$('chain-cacso-v', c.cac_spend_only ? fmt$(c.cac_spend_only) : '—');
    set$('chain-ltgp-v', c.ltgp_cac ? c.ltgp_cac.toFixed(2) : '—');
    // the cost card — what a client costs apart from ads (#159)
    var card = $('cost-card');
    if (card && c.cost_card) {
      card.innerHTML = c.cost_card.map(function (x) {
        return '<li><span>' + x.label + '</span><b>' + fmt$(x.amount) + '</b></li>';
      }).join('');
    }
    if (CURRENT) {
      CURRENT.spend_path.start = simState.spend;
      CURRENT.cpl0 = simState.cpl;
      CURRENT.set_rate = simState.set; CURRENT.show_rate = simState.show;
      CURRENT.close_rate = simState.close;
    }
    renderShowMath(c);
  }

  function setCount(id, v) {
    var el = $(id);
    if (!el) return;
    // never overwrite the field the user is typing into
    if (document.activeElement === el) return;
    if ('value' in el) el.value = v; else el.textContent = v;
  }

  function renderShowMath(c) {
    var out = $('show-math-out');
    if (!out) return;
    var on = $('chk-show-math') && $('chk-show-math').checked;
    out.style.display = on ? '' : 'none';
    if (!on) return;
    out.textContent =
      '$' + Math.round(simState.spend).toLocaleString() + ' ÷ $' + c.cpl_effective.toFixed(2) + ' per lead = ' + Math.round(c.leads) + ' leads\n' +
      Math.round(c.leads) + ' leads × ' + (simState.set * 100).toFixed(1) + '% booking rate = ' + Math.round(c.calls) + ' calls\n' +
      Math.round(c.calls) + ' calls × ' + (simState.show * 100).toFixed(1) + '% turn-up rate = ' + Math.round(c.shows) + ' shows\n' +
      Math.round(c.shows) + ' shows × ' + (simState.close * 100).toFixed(1) + '% close rate = ' + c.clients.toFixed(1) + ' new clients\n' +
      c.clients.toFixed(1) + ' clients × ' + Math.round(SIM.m0_share * 100) + '% first-month share × $' + Math.round(SIM.contract_avg).toLocaleString() + ' avg contract = ' + fmt$(c.cash_this_month) + ' cash this month\n' +
      c.clients.toFixed(1) + ' clients × $' + Math.round(SIM.contract_avg).toLocaleString() + ' = ' + fmt$(c.cash_over_term) + ' over the term · × $' + Math.round(SIM.mrr_avg).toLocaleString() + '/mo = ' + fmt$(c.mrr_added) + '/mo revenue added\n' +
      '($' + Math.round(simState.spend).toLocaleString() + ' ads + ' + fmt$(c.commissions_over_term) + ' commissions + $' + Math.round(SIM.tooling).toLocaleString() + ' sales tools) ÷ ' + c.clients.toFixed(1) + ' clients = ' + (c.cac ? fmt$(c.cac) : '—') + ' per client';
  }

  // ── PARITY ON SETTLE: the engine re-checks; on real mismatch it WINS ────
  // STALE-RESPONSE GUARD: a check sent for an earlier state must never
  // clobber a newer one (the behaviour gate caught exactly that race on
  // real network latency — an in-flight CPL check overwrote a fresh
  // target-mode solve).
  var settleTimer = null;
  var settleSeq = 0;
  function settleCheck() {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(async function () {
      var seq = ++settleSeq;
      var sent = { spend: simState.spend, cpl: simState.cpl,
                   curve: simState.curve, set: simState.set,
                   show: simState.show, close: simState.close };
      try {
        var r = await fetch('/dashboard/api/scale/simulate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ spend: sent.spend, cpl: sent.cpl,
            cpl_curve: sent.curve,
            inputs: { set_rate: sent.set, show_rate: sent.show,
                      close_rate: sent.close } }) });
        if (!r.ok) return;
        var server = await r.json();
        // superseded by a newer check, or the state moved since we sent —
        // this response may only be compared against the state it was for
        if (seq !== settleSeq || sent.spend !== simState.spend ||
            sent.cpl !== simState.cpl || sent.curve !== simState.curve ||
            sent.set !== simState.set || sent.show !== simState.show ||
            sent.close !== simState.close) return;
        var c = currentChain();
        var off = Math.abs(server.leads - c.leads) > 1.5 ||
                  Math.abs(server.clients - c.clients) > 0.15;
        if (off) {
          try { window.__reportClientError && window.__reportClientError({
            kind: 'sim_parity_mismatch',
            detail: 'client leads=' + c.leads.toFixed(1) + ' clients=' + c.clients.toFixed(2) +
                    ' vs engine leads=' + server.leads + ' clients=' + server.clients }); } catch (e) {}
          // the ENGINE'S value wins on screen
          var leadsEl = $('sim-leads');
          if (leadsEl) leadsEl.textContent = Math.round(server.leads).toLocaleString();
          renderChain(window.SimCore.chain(server.spend, simState.cpl, rates(), agg(), simState.curve));
        }
      } catch (e) { /* offline — the client math stands until the next settle */ }
    }, 700);
  }

  // ── inputs: number fields + sliders, both directions, no locks ──────────
  document.addEventListener('input', function (e) {
    if (!SIM) return;
    var id = e.target.id;
    if (simState.mode !== 'forward' && ['sim-spend', 'sim-spend-slider', 'sim-cpl', 'sim-cpl-slider'].indexOf(id) >= 0) return;
    if (id === 'sim-spend') { simState.spend = Math.max(0, +e.target.value || 0); simForward('spend-num'); }
    else if (id === 'sim-spend-slider') { simState.spend = +e.target.value; simForward('spend-slider'); }
    else if (id === 'sim-cpl' && !simState.curve) { simState.cpl = Math.max(0.01, +e.target.value || simState.cpl); simForward('cpl-num'); }
    else if (id === 'sim-cpl-slider' && !simState.curve) { simState.cpl = +e.target.value; simForward('cpl-slider'); }
    // rates are typed as PERCENTAGES (5.1) — "25", not "0.25"
    else if (id === 'rate-set') { simState.set = (+e.target.value || 0) / 100; clearSolved(); simForward('rates'); }
    else if (id === 'rate-show') { simState.show = (+e.target.value || 0) / 100; clearSolved(); simForward('rates'); }
    else if (id === 'rate-close') { simState.close = (+e.target.value || 0) / 100; clearSolved(); simForward('rates'); }
    // A STAGE COUNT was typed → solve the rate that stage needs, holding
    // everything upstream exactly where it is (brief 36's missing half).
    else if (id === 'chain-calls-v') { solveStage('calls', e.target.value); }
    else if (id === 'chain-shows-v') { solveStage('shows', e.target.value); }
    else if (id === 'chain-clients-v') { solveStage('clients', e.target.value); }
    else if (id === 'iwant-value' && simState.mode === 'target') { runTarget(); }
  });

  function setCplEditable(on) {
    ['sim-cpl', 'sim-cpl-slider'].forEach(function (i) { var el = $(i); if (el) el.disabled = !on; });
    var io = $('sim-cpl-io');
    if (io) { io.textContent = on ? 'input' : 'worked out at this spend'; io.classList.toggle('out', !on); }
  }
  function setSpendEditable(on) {
    ['sim-spend', 'sim-spend-slider'].forEach(function (i) { var el = $(i); if (el) el.disabled = !on; });
    var io = $('sim-spend-io');
    if (io) { io.textContent = on ? 'input' : 'worked out from your goal'; io.classList.toggle('out', !on); }
  }

  document.addEventListener('change', function (e) {
    if (e.target.id === 'sim-cpl-mode') {
      simState.curve = e.target.checked;
      setCplEditable(!simState.curve && simState.mode === 'forward');
      simForward('curve');
    }
    if (e.target.id === 'chk-show-math' && SIM) renderChain(currentChain());
    if (e.target.id === 'mode-forward' || e.target.id === 'mode-target') {
      var target = e.target.id === 'mode-target';
      simState.mode = target ? 'target' : 'forward';
      var fl = $('mode-forward-lbl'), tl = $('mode-target-lbl');
      if (fl) fl.classList.toggle('active', !target);
      if (tl) tl.classList.toggle('active', target);
      setSpendEditable(!target);
      setCplEditable(!target && !simState.curve);
      // switching modes never silently changes values
      if (!target) simForward('mode');
    }
  });

  // ── TARGET MODE: spend is the answer ────────────────────────────────────
  function runTarget() {
    if (!SIM) return;
    var kind = $('iwant-kind').value, val = +$('iwant-value').value || 0;
    var req = window.SimCore.requiredSpend(kind, val, simState.cpl, rates(), agg(), simState.curve);
    simState.spend = req.spend;
    var c = currentChain();
    if ($('sim-spend')) $('sim-spend').value = Math.round(req.spend);
    if ($('sim-spend-slider')) $('sim-spend-slider').value = Math.round(req.spend);
    var leadsEl = $('sim-leads');
    if (leadsEl) leadsEl.textContent = Math.round(c.leads).toLocaleString();
    set$('sim-sentence', 'To get ' + val.toLocaleString() + ' ' + kindWord(kind) +
      ' at $' + c.cpl_effective.toFixed(2) + '/lead, a ' + (simState.set * 100).toFixed(1) +
      '% booking rate, ' + (simState.show * 100).toFixed(1) + '% turn-up and ' +
      (simState.close * 100).toFixed(1) + '% close — you need $' +
      Math.round(req.spend).toLocaleString() + '/mo.');
    renderChain(c);
    drawSimChart();
    settleCheck();
    // the fuller answer with the 35% delta
    var req35 = window.SimCore.requiredSpend(kind, val, simState.cpl,
      { set: simState.set, show: simState.show, close: 0.35 }, agg(), simState.curve);
    var delta = (kind !== 'leads' && kind !== 'calls' && Math.abs(simState.close - 0.35) > 0.001)
      ? ' If the close rate were 35% instead of ' + (simState.close * 100).toFixed(1) + '%, you would need ' + fmt$(req35.spend) + '/mo.'
      : '';
    var out = $('iwant-out');
    if (out) out.innerHTML = '<b>' + fmt$(req.spend) + '/mo of ad spend.</b> What has to be true: ' +
      Math.round(c.leads) + ' leads → ' + Math.round(c.calls) + ' calls → ' + Math.round(c.shows) +
      ' turn up → ' + c.clients.toFixed(1) + ' sign.' + delta +
      ' <span style="opacity:.7">what-if — nothing recorded</span>';
  }
  function kindWord(k) {
    return { leads: 'leads/month', calls: 'booked calls/month', clients: 'new clients/month',
             cash: 'dollars of cash this month', mrr: 'dollars of monthly revenue added' }[k] || k;
  }

  // ── the chart: a VIEW of the same numbers (never a second calculation) ──
  function drawSimChart() {
    var cv = $('sim-chart');
    if (!cv || !SIM || !cv.getContext) return;
    var ctx = cv.getContext('2d');
    var W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    var maxS = Math.max(simState.spend * 2.2, 20000);
    var top = window.SimCore.chain(maxS, simState.cpl, rates(), agg(), simState.curve);
    var maxLeads = Math.max(top.leads, 1);
    ctx.strokeStyle = 'rgba(91,155,208,0.9)'; ctx.lineWidth = 2; ctx.beginPath();
    for (var x = 0; x <= 60; x++) {
      var sp = maxS * x / 60;
      var pt = window.SimCore.chain(sp, simState.cpl, rates(), agg(), simState.curve);
      var px = 30 + (W - 40) * sp / maxS;
      var py = H - 18 - (H - 30) * (pt.leads / (maxLeads * 1.05));
      x === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.stroke();
    var cur = currentChain();
    var px0 = 30 + (W - 40) * simState.spend / maxS;
    var py0 = H - 18 - (H - 30) * (cur.leads / (maxLeads * 1.05));
    ctx.fillStyle = '#E8B445'; ctx.beginPath(); ctx.arc(px0, py0, 5, 0, 7); ctx.fill();
    ctx.fillStyle = 'rgba(167,188,210,0.8)'; ctx.font = '10px Archivo';
    ctx.fillText('$' + Math.round(simState.spend).toLocaleString() + ' → ' + Math.round(cur.leads) + ' leads', Math.min(px0 + 8, W - 130), Math.max(py0 - 8, 12));
    ctx.fillText('spend →', W - 55, H - 4);
    ctx.save(); ctx.translate(10, H / 2); ctx.rotate(-Math.PI / 2); ctx.fillText('leads →', 0, 0); ctx.restore();
    cv.dataset.point = Math.round(cur.leads);   // behaviour gate: chart == fields
  }
  function chartDrag(ev) {
    if (simState.mode !== 'forward') return;
    var cv = $('sim-chart');
    if (!cv) return;
    var r = cv.getBoundingClientRect();
    var frac = (ev.clientX - r.left - 30 * r.width / cv.width) / (r.width * (cv.width - 40) / cv.width);
    var maxS = Math.max(simState.spend * 2.2, 20000);
    simState.spend = Math.max(500, Math.min(maxS, frac * maxS));
    simForward('chart');
  }
  var dragging = false;
  document.addEventListener('pointerdown', function (e) { if (e.target.id === 'sim-chart') { dragging = true; chartDrag(e); } });
  document.addEventListener('pointermove', function (e) { if (dragging) chartDrag(e); });
  document.addEventListener('pointerup', function () { dragging = false; });

  document.addEventListener('click', function (e) {
    var sr = e.target.closest && e.target.closest('.sim-reset');
    if (sr && SIM) {
      e.preventDefault();
      guard('simreset', function () {
        if (sr.dataset.sr === 'spend') simState.spend = SIM.spend;
        if (sr.dataset.sr === 'cpl') simState.cpl = SIM.cpl_base;
        simForward('preset');
      });
      return;
    }
    var cr = e.target.closest && e.target.closest('.count-reset');
    if (cr) {
      e.preventDefault();
      clearSolved(cr.getAttribute('data-stage'));
      simForward('rates');
      return;
    }
    var rr = e.target.closest && e.target.closest('.rate-reset');
    if (rr && SIM) {
      e.preventDefault();
      var k = rr.dataset.r;
      simState[k] = SIM.rates[k];
      var el = $('rate-' + k); if (el) el.value = SIM.rates[k];
      simForward('rates');
      return;
    }
    var pr = e.target.closest && e.target.closest('.sim-preset');
    if (pr && SIM) {
      guard('preset', function () {
        if (pr.dataset.preset === 'measured') {
          simState.spend = SIM.spend; simState.cpl = SIM.cpl_base;
          simState.set = SIM.rates.set; simState.show = SIM.rates.show; simState.close = SIM.rates.close;
          ['set', 'show', 'close'].forEach(function (k) { var el = $('rate-' + k); if (el) el.value = SIM.rates[k]; });
        } else if (pr.dataset.preset === 'plus50') {
          simState.spend = SIM.spend * 1.5;
        } else if (pr.dataset.preset === 'close35') {
          simState.close = 0.35;
          var el = $('rate-close'); if (el) el.value = 0.35;
        } else if (pr.dataset.preset === 'plan2027') {
          var pi = window.__SCALE_PLAN_INPUTS__ || null;
          if (pi) {
            if (pi.spend_path && pi.spend_path.start) simState.spend = pi.spend_path.start;
            if (pi.cpl0) simState.cpl = pi.cpl0;
            if (pi.set_rate) simState.set = pi.set_rate;
            if (pi.show_rate) simState.show = pi.show_rate;
            if (pi.close_rate) simState.close = pi.close_rate;
            ['set', 'show', 'close'].forEach(function (k) {
              var el2 = $('rate-' + k);
              if (el2) el2.value = simState[k];
            });
          }
        }
        simForward('preset');
      });
      return;
    }
    if (e.target.id === 'btn-iwant') {
      guard('iwant', function () {
        var mt = $('mode-target');
        if (mt && !mt.checked) { mt.checked = true; mt.dispatchEvent(new Event('change', { bubbles: true })); }
        runTarget();
      });
    }
  });


  // ── NORTH STAR what-ifs (labelled; write nothing) + calibration browse ──
  document.addEventListener('click', function (e) {
    var w = e.target.closest && e.target.closest('.ns-whatif');
    if (!w || !SIM || !window.SimCore) return;
    guard('ns-whatif', function () {
      var base = window.SimCore.chain(SIM.spend, SIM.cpl_base, SIM.rates, SIM, false);
      var alt;
      var label;
      if (w.dataset.w === 'spend20') {
        alt = window.SimCore.chain(SIM.spend * 1.2, SIM.cpl_base, SIM.rates, SIM, false);
        label = '+20% spend at the current cost per lead';
      } else if (w.dataset.w === 'close35') {
        alt = window.SimCore.chain(SIM.spend, SIM.cpl_base,
          { set: SIM.rates.set, show: SIM.rates.show, close: 0.35 }, SIM, false);
        label = 'close rate at 35%';
      } else {
        alt = window.SimCore.chain(SIM.spend, Math.max(SIM.cpl_base - 10, 1), SIM.rates, SIM, false);
        label = 'cost per lead $10 lower';
      }
      function d(k, money) {
        var v = alt[k] - base[k];
        var s = (v >= 0 ? '+' : '−') + (money ? '$' + Math.round(Math.abs(v)).toLocaleString() : Math.abs(v).toFixed(1));
        return s;
      }
      var cacD = (alt.cac && base.cac) ? ((alt.cac - base.cac >= 0 ? '+' : '−') + '$' + Math.round(Math.abs(alt.cac - base.cac)).toLocaleString()) : '—';
      $('ns-whatif-out').innerHTML = '<b>' + label + ':</b> ' +
        d('leads') + ' leads · ' + d('clients') + ' clients · ' + d('cash_this_month', true) +
        ' cash this month · cost per client ' + cacD +
        ' <span style="opacity:.7">what-if — nothing recorded</span>';
    });
  });
  async function loadCalLog() {
    var wrap = $('callog-wrap');
    if (!wrap) return;
    try {
      var r = await fetch('/dashboard/api/scale/calibration-log');
      if (!r.ok) return;
      var d = await r.json();
      var rows = d.log || [];
      if (!rows.length) { wrap.innerHTML = '<div class="scale-note">the first monthly prediction is written at the next refresh — scores appear when the month ends</div>'; return; }
      var html = '<b class="scale-note">MONTHLY PREDICTIONS — written at each month start, scored when the month ends</b>' +
        '<table class="scale-table"><thead><tr><th>month</th><th>predicted leads/calls/clients</th><th>actual</th><th>error</th></tr></thead><tbody>';
      rows.slice().reverse().forEach(function (rr) {
        var p2 = rr.predicted || {};
        var sc = rr.scored || {};
        var a = sc.actual || {};
        var e2 = sc.error_pct || {};
        html += '<tr><td>' + rr.month + '</td><td>' + Math.round(p2.leads || 0) + ' / ' + Math.round(p2.calls || 0) + ' / ' + (p2.clients || 0).toFixed(1) + '</td>' +
          '<td>' + (sc.actual ? (a.leads + ' / ' + a.calls + ' / ' + a.clients) : 'month still running') + '</td>' +
          '<td>' + (sc.actual ? ('±' + (e2.leads != null ? e2.leads : '—') + '% / ±' + (e2.calls != null ? e2.calls : '—') + '% / ±' + (e2.clients != null ? e2.clients : '—') + '%') : '—') + '</td></tr>';
      });
      wrap.innerHTML = html + '</tbody></table>';
    } catch (e) { /* quiet */ }
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
    guard('callog', loadCalLog);
  })();
})();
