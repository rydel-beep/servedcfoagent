/* adsapp.js — SERVED AD TRACKING, the dedicated dashboard.
   RENDER + DRILL + FLAGS over the one engine (/ads/api/board + /ads/api/roster).
   Zero math beyond display formatting.

   THE TOGGLE FIX (the finance-section bug, root-caused in AD_DASHBOARD_REPORT):
   - ONE atomic /ads/api/board call per window — scoreboard, scorecard, rows together.
   - Latest-wins request token: a late response for a window you've left is DISCARDED.
   - The response echoes its window; a mismatch with current state = console.error +
     nothing rendered (the stale-mix guard, exercised by PASS 3).
   - Window state lives in the URL (?window=60) — a shared link opens on that window. */
(function () {
  'use strict';

  var state = { days: 30, sort: 'spend', sortDir: -1, verdict: null, creative: null,
                q: '', gq: '', board: null, shown: 0, reqToken: 0, level: 'creative',
                basis: 'cohort', market: 'all', rows: 70 };
  // ROW CONTROL: 70/150/300/'all' — a RENDER window only. Sort and find always
  // run over the FULL dataset before the slice; tier rows stay pinned outside it.
  try {
    var savedRows = localStorage.getItem('adx-rows');
    if (savedRows) state.rows = savedRows === 'all' ? 'all' : (+savedRows || 70);
  } catch (e) {}
  function rowLimit() { return state.rows === 'all' ? Infinity : +state.rows; }

  function $(s) { return document.querySelector(s); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function money(v) { return v == null ? '—' : '$' + Math.round(v).toLocaleString(); }
  function num(v) { return v == null ? '—' : String(v); }

  // plain-language tooltips — Romano lives here (AD_DASHBOARD_REPORT Phase 5)
  var TIPS = {
    leads: 'Leads that entered the tracker in this window and trace to this creative (first touch).',
    qualified: 'Leads that passed all three checks: setter outcome not DQ, revenue band $20k+/month, form answered. Fit, not contact — see Reached.',
    reached: 'Qualified leads with real contact evidence: a tracker set/show/close, or GHL conversation evidence (sweep-backed). Qualified-but-unreached = right audience, contact problem.',
    sets: 'Leads the setter booked a call for.',
    shows: 'Booked calls where the lead actually showed.',
    closes: 'Deals won in this window (by close date).',
    cash: 'Cash actually collected on those closes.',
    spend: 'Meta ad spend for this creative in the window.',
    cost_per_lead: 'Ad spend divided by leads.',
    cost_per_qualified: 'Ad spend divided by qualified leads.',
    cost_per_set: 'Ad spend divided by sets.',
    cost_per_close: 'Ad spend divided by closes (ad money only).',
    cost_per_close_loaded: 'Cost per close including sales commissions, not just ad spend.',
    ltgp_cac: 'Lifetime gross profit returned per $1 of acquisition cost. 3.0x is the floor.',
    verdict: 'DOUBLE DOWN / KILL / WATCH, from the verdict engine. WATCH means not enough data yet.',
    n: 'Sample size behind the verdict: leads / closes.',
  };
  var COLS = [
    { k: 'creative', label: 'Creative' }, { k: 'verdict', label: 'Verdict' },
    { k: 'leads', label: 'Leads' }, { k: 'qualified', label: 'Qualified' },
    { k: 'reached', label: 'Reached' },
    { k: 'sets', label: 'Sets' }, { k: 'shows', label: 'Shows' },
    { k: 'closes', label: 'Closes' }, { k: 'cash', label: 'Cash', money: 1 },
    { k: 'spend', label: 'Spend', money: 1 }, { k: 'cost_per_lead', label: 'CPL', money: 1 },
    { k: 'cost_per_qualified', label: 'C/Qual', money: 1 },
    { k: 'cost_per_set', label: 'C/Set', money: 1 },
    { k: 'cost_per_close', label: 'C/Close (ad)', money: 1 },
    { k: 'cost_per_close_loaded', label: 'C/Close (loaded)', money: 1 },
    { k: 'ltgp_cac', label: 'LTGP:CAC' },
  ];
  var DRILLABLE = { leads: 1, qualified: 1, reached: 1, sets: 1, shows: 1, closes: 1 };
  // column visibility (persisted per user) — hiding is PRESENTATION only
  var hiddenCols = [];
  try { hiddenCols = JSON.parse(localStorage.getItem('adx-cols-hidden') || '[]'); } catch (e) {}
  function activeCols() {
    return COLS.filter(function (c) {
      return c.k === 'creative' || hiddenCols.indexOf(c.k) < 0;
    });
  }

  // ── the atomic window fetch (latest-wins + echo guard) ─────────────────────
  var stalePoll = null;
  function expectedDays() { return state.days === 'all' ? 3650 : +state.days; }
  function loadBoard(days, basis, market) {
    state.days = days;
    if (basis) state.basis = basis;
    if (market) state.market = market;
    var token = ++state.reqToken;
    document.querySelectorAll('.adx-win').forEach(function (b) {
      b.classList.toggle('active', String(b.dataset.days) === String(days));
    });
    document.querySelectorAll('.adx-basis').forEach(function (b) {
      b.classList.toggle('active', b.dataset.basis === state.basis);
    });
    document.querySelectorAll('.adx-market').forEach(function (b) {
      b.classList.toggle('active', b.dataset.market === state.market);
    });
    try { history.replaceState(null, '', '?window=' + days + '&basis=' + state.basis +
      '&market=' + state.market + '&sort=' + state.sort + '.' + (state.sortDir === -1 ? 'desc' : 'asc') +
      '&rows=' + state.rows); } catch (e) {}
    $('#adx-banner').innerHTML = '<span class="adx-skel">Loading ' + days + (days === 'all' ? '' : 'd') + ' · ' + state.basis +
      (state.market !== 'all' ? ' · ' + state.market.toUpperCase() : '') + '…</span>';
    document.body.classList.add('adx-loading');
    clearTimeout(stalePoll);
    fetch('/ads/api/board?days=' + days + '&basis=' + state.basis + '&market=' + state.market,
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (token !== state.reqToken) return;              // latest wins — stale dropped
        document.body.classList.remove('adx-loading');
        if (!data) { $('#adx-banner').textContent = 'Engine unreachable — nothing rendered rather than stale numbers.'; return; }
        if (!data.window || data.window.days !== expectedDays() ||
            (data.basis && data.basis !== state.basis) ||
            (data.market && data.market !== state.market)) {
          console.error('STALE-MIX GUARD: response (window/basis)', data.window, data.basis,
                        'does not match state', state.days, state.basis, '— discarded');
          return;
        }
        state.board = data;
        renderAll();
        if (data.stale) {           // a labelled rollup — poll for the fresh build
          stalePoll = setTimeout(function () { loadBoard(state.days); }, 8000);
        }
      })
      .catch(function () {
        if (token !== state.reqToken) return;
        document.body.classList.remove('adx-loading');
        $('#adx-banner').textContent = 'Board fetch failed — toggle a window to retry.';
      });
  }

  function windowStamp() {
    var d = state.board.window.days;
    return d >= 3650 ? 'All time' : d + 'd';
  }

  var levelChosen = false;   // the user's explicit pick beats the default
  function renderAll() {
    if (!levelChosen && state.board.ladder && state.board.ladder.default_level) {
      state.level = state.board.ladder.default_level;
    }
    renderBanner(); renderHeadline(); renderScorecard(); renderHygiene(); renderScoreboard(); renderRows(true);
    $('#adx-table-window').textContent = '· ' + windowStamp() + ' window' + (state.gq ? ' · FILTERED VIEW (aggregates unchanged)' : '') + (state.market !== 'all' ? ' · market: ' + state.market.toUpperCase() : '');
  }

  function renderHygiene() {
    var h = state.board.hygiene;
    var sec = $('#adx-hygiene');
    if (!h) { sec.style.display = 'none'; return; }
    sec.style.display = '';
    var ag = h.agreement || {};
    var line = 'Tracker (authority): <strong>' + h.tracker_closes + '</strong> close(s) in ' +
      h.window_days + 'd · GHL closed-won moved: <strong>' + (h.ghl_won_in_window == null ? '?' : h.ghl_won_in_window) +
      '</strong>' + (ag.tracker_vs_ghl === true ? ' <span class="adx-ok">in sync</span>'
                     : ag.tracker_vs_ghl === false ? ' <span class="adx-lag">lane lags</span>' : '') +
      ' · Stripe: ' + ((h.stripe || {}).checked || '?') + ' charges, ' +
      ((h.stripe || {}).missing_from_tracker != null ? (h.stripe.missing_from_tracker + ' missing') : '?');
    var all = (h.disagreements || []);
    // THE DATELESS RAIL: events that exist but can't be windowed — first-class
    // bucket (excluded ≠ deleted), each item a door to its deal evidence.
    var dateless = all.filter(function (d) {
      return d.kind === 'tracker_blank_close_date' || d.kind === 'tracker_blank_input_date'; });
    var ds = all.filter(function (d) { return dateless.indexOf(d) < 0; });
    // group by CONTACT with event-type chips; entries with a derivation move to
    // the collapsed "Derived (awaiting source)" section — visible, never vanishing
    var dd = state.board.derived_dates || {};
    var byName = {};
    dateless.forEach(function (d) {
      var nm = (d.detail || '').split(':')[0];
      var ev = d.kind === 'tracker_blank_close_date' ? 'close' : 'input';
      (byName[nm] = byName[nm] || []).push(ev);
    });
    var open = [], resolved = [];
    Object.keys(byName).forEach(function (nm) {
      var key = nm.toLowerCase().replace(/[^a-z0-9 @.]/g, '').trim();
      var got = dd[key] || {};
      var evs = byName[nm];
      var allDerived = evs.every(function (ev) {
        return got[ev === 'close' ? 'close_date' : 'input_date']; });
      var chip = '<button class="adx-deal-open adx-door" data-deal="' + esc(nm) + '">' +
        esc(nm) + (evs.length > 1 ? ' ×' + evs.length : '') + ' · ' + evs.join(' · ') + '</button>';
      (allDerived ? resolved : open).push(chip);
    });
    var ushows = state.board.unverified_shows || [];
    var ushowHtml = ushows.length
      ? '<details class="adx-dateless"><summary><strong>Unverified shows (' + ushows.length + ')</strong> — status-only attendance; a call record or your word verifies (\u201cconfirm attendance for <name>\u201d)</summary>' +
        ushows.map(function (u) {
          return '<button class="adx-deal-open adx-door" data-deal="' + esc(u.name) + '">' + esc(u.name) + '</button>' +
            (u.near_miss ? ' <span class="adx-prov">' + esc(String(u.near_miss.duration)) + 's call ' + esc(u.near_miss.date || '') + '</span>' : '');
        }).join(' ') + '</details>' : '';
    var railHtml = ushowHtml + (open.length
      ? '<div class="adx-dateless"><strong>Dateless (' + open.length + ' contact(s))</strong> — real events the clocks cannot place; a filled source date clears them automatically: ' +
        open.join(' ') + '</div>' : '') +
      (resolved.length
      ? '<details class="adx-dateless adx-derived-rail"><summary><strong>Derived (' + resolved.length + ')</strong> — dated from evidence, awaiting the source fix (the queue item lives until Piolo lands the date)</summary>' +
        resolved.join(' ') + '</details>' : '');
    var items = ds.slice(0, 8).map(function (d) {
      var nm = (d.detail || '').indexOf(':') > 0 ? (d.detail || '').split(':')[0] : null;
      return '<div class="adx-hyg-item adx-sev' + d.severity + '"><span>' +
        (nm && nm.length < 40 ? '<button class="adx-deal-open adx-door" data-deal="' + esc(nm) + '">' + esc(nm) + '</button>' + esc((d.detail || '').slice(nm.length)) : esc(d.detail)) + '</span>' +
        '<span class="adx-hyg-fix">fix: ' + esc(d.fix) + ' · ' + esc(d.owner || '') + '</span></div>';
    }).join('') + railHtml;
    var ident = state.board.identity;
    var identLine = '';
    if (ident) {
      identLine = '<div class="adx-hyg-line">Identity: <strong>' +
        (ident.exact_id_rate_pct != null ? ident.exact_id_rate_pct + '%' : '—') +
        '</strong> exact-id resolution · ' + (ident.ambiguous_leads || 0) +
        ' ambiguous (quarantined) · ' + (ident.unattributed_leads || 0) + ' unattributed · ' +
        'contact→tracker ' + (((ident.hops || {}).hop2_contact_to_tracker || {}).match_rate_pct || '—') + '%' +
        (ident.trailing_exact_id_rate_pct != null ? ' · trailing 90d exact-id ' + ident.trailing_exact_id_rate_pct + '%' : '') +
        '</div>';
    }
    $('#adx-hygiene-body').innerHTML = identLine + '<div class="adx-hyg-line">' + line + '</div>' +
      (ds.length ? items + (ds.length > 8 ? '<div class="adx-hyg-more">+' + (ds.length - 8) + ' more in the action feed</div>' : '')
                 : '<div class="adx-hyg-clean">No open disagreements — systems agree.</div>');
  }

  function renderDefs() {
    var b = state.board || {};
    var qr = b.qualified_rule || {};
    var sc = (b.scoreboard || {});
    var floorLine = (sc.verdict_floor || 3.0);
    $('#adx-defs-body').innerHTML = [
      ['A close', 'A tracker row marked won by the closer, counted on its Close Date (the tracker is the one authority — Rydel-confirmed). Duplicate rows count once and are flagged. GHL stage moves and Stripe cash are validators that raise flags, never counts.'],
      ['Qualified', 'Setter outcome is not DQ, AND the venue\'s revenue band is at or above $' + Math.round((qr.floor_monthly || 20000) / 1000) + 'k/month (tracker cell first, the GHL form answer fills gaps; unknown revenue is excluded and shown), AND the form was answered.'],
      ['Attribution', 'First-touch by default: the ad that created the lead (utmAdId from the lead form, exact ids first). Last-touch is stored and labelled, never blended. Tiers: ad-level · IG-DM channel · unattributed — always visible.'],
      ['Verdicts + min-n', 'DOUBLE DOWN needs LTGP:CAC ≥ ' + floorLine + 'x with margin at 3+ closes. KILL needs 30+ leads below the floor. Below those: TRENDING labels are provisional signal, never decisions.'],
      ['Windows', 'Leads/qualified/sets/shows are counted by Input Date in the window (cohort). Closes and cash are counted by Close Date in the window. Closes trail leads by weeks — 60/90d is the honest read for close-based verdicts.'],
      ['Cost bases', 'CPL/C-Qual/C-Set/C-Close (ad) use ad spend only. C/Close (loaded) adds closer + setter commissions. Contracted = contract value; Cash = money actually collected (Stripe-validated).'],
    ].map(function (d) {
      return '<div class="adx-def"><div class="adx-def-t">' + d[0] + '</div><div class="adx-def-b">' + d[1] + '</div></div>';
    }).join('');
  }

  function renderHeadline() {
    var h = (state.board.scoreboard || {}).headline;
    var el = $('#adx-headline');
    if (!h) { el.innerHTML = ''; return; }
    function tiers(t) {
      var names = { ad: 'attributed', ambiguous: 'ambiguous', ig_dm: 'IG-DM', unattributed: 'unattributed' };
      return Object.keys(t || {}).filter(function (k) { return t[k]; })
        .map(function (k) { return (names[k] || k) + ' ' + t[k]; }).join(' · ') || '—';
    }
    el.innerHTML =
      '<div class="adx-head-tile"><div class="adx-head-num">' + num(h.closes_total) + '</div>' +
      '<div class="adx-head-label">CLOSES · ' + windowStamp() + ' · ' + esc(h.basis) + ' clock</div>' +
      '<div class="adx-head-tiers">' + tiers(h.closes_tiers) + '</div></div>' +
      '<div class="adx-head-tile"><div class="adx-head-num">' + num(h.leads_total) + '</div>' +
      '<div class="adx-head-label">LEADS</div>' +
      '<div class="adx-head-tiers">' + tiers(h.leads_tiers) + '</div></div>' +
      '<div class="adx-head-tile"><div class="adx-head-num">' + money(h.cash_total) + '</div>' +
      '<div class="adx-head-label">CASH COLLECTED</div>' +
      '<div class="adx-head-tiers">' + tiers(h.cash_tiers) + '</div></div>' +
      '<div class="adx-head-tile"><div class="adx-head-num">' + money(h.spend_total) + '</div>' +
      '<div class="adx-head-label">SPEND</div><div class="adx-head-tiers">Meta engine, reconciled</div></div>';
    // HEADLINE DELTAS: vs the prior equal-length window — same engine, second
    // invocation, clearly labelled (numbers arrive computed; nothing derived here).
    var cmp = state.board.compare;
    if (cmp && cmp.deltas) {
      var f = function (v, money) {
        if (v == null) return '—';
        var s = (v > 0 ? '+' : '') + (money ? '$' + Math.round(Math.abs(v)).toLocaleString() : v);
        return v < 0 && money ? '−$' + Math.round(Math.abs(v)).toLocaleString() : s;
      };
      el.innerHTML += '<div class="adx-compare">' + esc(cmp.label) + ': leads ' + f(cmp.deltas.leads) +
        ' · closes ' + f(cmp.deltas.closes) + ' · cash ' + f(cmp.deltas.cash, 1) +
        ' · spend ' + f(cmp.deltas.spend, 1) + '</div>';
    }
    if (state.board.market_note) {
      el.innerHTML += '<div class="adx-market-note">' + esc(state.board.market_note) + '</div>';
    }
    // THE ACTIVITY CASH STRIP (cohort view only): finance truth on its own labelled
    // clock — one line, one engine, never mixed into grid math.
    var strip = state.board.cash_strip;
    el.innerHTML += strip
      ? '<div class="adx-cash-strip">' + esc(strip.label) + ' <em>(separate clock — the grid above is lead-cohort)</em></div>'
      : '';
  }

  function renderBanner() {
    var b = state.board.scoreboard.banner || {};
    var fr = b.freshness || {};
    var qr = state.board.qualified_rule || {};
    $('#adx-banner').innerHTML =
      '<strong>' + (b.attribution_rate_pct != null ? b.attribution_rate_pct + '%' : '—') +
      '</strong> of window leads ad-attributed (' + (b.attributed_leads || 0) + '/' + (b.leads || 0) + ')' +
      ' · window <strong>' + windowStamp() + '</strong>' +
      ' · qualified = ≠DQ + revenue ≥ $' + Math.round((qr.floor_monthly || 20000) / 1000) + 'k/mo + form answered' +
      ' · contacts synced ' + esc(String(fr.contacts_synced || '').slice(11, 16) || '—') +
      ' · sheet mirror ~90s' +
      ' · <span class="adx-basis-label">' + esc(state.board.basis_label || state.basis) + '</span>' +
      (state.board.stale ? ' · <span class="adx-stale">showing the last rollup (' +
        Math.round((state.board.stale_age_s || 0) / 60) + 'm old) — refreshing…</span>' : '') +
      (state.days === 30 && state.basis === 'cohort' ? ' · <span class="adx-guide">30d cohort: closes still landing — 60/90d is the honest read for close-based verdicts</span>' : '');
    if (!(b.leads)) {
      $('#adx-banner').innerHTML = 'No leads in this ' + windowStamp() + ' window. ' +
        '<button class="adx-win-inline" onclick="AdsApp.setWindow(90)">view 90d instead</button>';
    }
  }

  function renderScorecard() {
    var sc = state.board.scorecard || {};
    var L = $('#adx-leaders');
    L.innerHTML = (sc.leaders || []).map(function (c) {
      return '<div class="adx-lead-card" data-window="' + windowStamp() + '">' +
        '<div class="adx-lead-title">' + esc(c.title) + '</div>' +
        '<div class="adx-lead-value">' + esc(c.value) + '</div>' +
        '<div class="adx-lead-line">' + esc(c.line) + '</div></div>';
    }).join('') || '<div class="adx-lead-empty">No leaders yet in this window.</div>';
    var cl = $('#adx-constraint');
    if (sc.constraint_line) { cl.textContent = sc.constraint_line; cl.style.display = ''; }
    else cl.style.display = 'none';
    var F = $('#adx-flags');
    var flags = sc.flags || [];
    F.innerHTML = flags.length ? flags.map(function (f) {
      return '<div class="adx-flag adx-sev' + f.severity + '" data-window="' + windowStamp() + '">' +
        '<div class="adx-flag-head">' + (f.creative ? esc(f.creative.slice(0, 44)) : 'ACCOUNT') + '</div>' +
        '<div class="adx-flag-line">' + esc(f.headline) + '</div>' +
        '<div class="adx-flag-q">' + esc(f.question) + '</div></div>';
    }).join('') : '<div class="adx-flag adx-sev-none">No flags in this window — thresholds all clear.</div>';
  }

  var VERDICT_RANK = { 'KILL': 0, 'WATCH': 1, 'DOUBLE DOWN': 3 };
  function sortRows(rows) {
    var k = state.sort, dir = state.sortDir;
    return rows.slice().sort(function (a, b) {
      // tier rows stay PINNED below creative rows — never interleaved
      var at = a.tier !== 'ad' ? 1 : 0, bt = b.tier !== 'ad' ? 1 : 0;
      if (at !== bt) return at - bt;
      var av, bv;
      if (k === 'worst') {
        // the VERDICT ENGINE's ranking: KILL first, provisional-weak next,
        // then worst unit economics (highest CPL) as tiebreak — no new math.
        av = VERDICT_RANK[a.verdict] != null ? VERDICT_RANK[a.verdict]
             : (a.provisional && a.provisional.trend === 'weak' ? 0.5 : 2);
        bv = VERDICT_RANK[b.verdict] != null ? VERDICT_RANK[b.verdict]
             : (b.provisional && b.provisional.trend === 'weak' ? 0.5 : 2);
        if (av !== bv) return av - bv;
        return (b.cost_per_lead || 0) - (a.cost_per_lead || 0);
      }
      av = a[k]; bv = b[k];
      if (av == null && bv == null) { }
      else if (av == null) return 1;
      else if (bv == null) return -1;
      else if (av < bv) return -dir;
      else if (av > bv) return dir;
      // stable secondary key: spend desc
      return (b.spend || 0) - (a.spend || 0);
    });
  }

  function badge(row) {
    var v = row.verdict, n = row.n || (row.gates ? { leads: row.gates.n_leads, closes: row.gates.n_closes } : {});
    var reason = esc(row.verdict_driver || row.gate || '');
    if (v === 'DOUBLE DOWN') return '<span class="adx-badge adx-dd" title="' + reason + '">DOUBLE DOWN</span>';
    if (v === 'KILL') return '<span class="adx-badge adx-kill" title="' + reason + '">KILL</span>';
    // below min-n: the PROVISIONAL layer — visually distinct, never a decision
    var p = row.provisional;
    if (p) {
      var cls = p.trend === 'strong' ? 'adx-prov-strong' : p.trend === 'weak' ? 'adx-prov-weak' : 'adx-prov-early';
      return '<span class="adx-badge adx-prov ' + cls + '" title="' + esc(p.why + ' · ' + p.progress) + '">' +
        esc(p.label) + '</span>';
    }
    if (v === 'WATCH') return '<span class="adx-badge adx-watch" title="' + reason + '">WATCH <span class="adx-n">n=' + (n.leads || 0) + '/' + (n.closes || 0) + '</span></span>';
    return '<span class="adx-badge adx-none">—</span>';
  }

  function levelRows() {
    var b = state.board;
    if (state.level === 'creative') return b.scoreboard.rows;
    var lad = b.ladder || {};
    if (state.level === 'account') {
      var a = lad.account;
      return a ? [Object.assign({ creative: a.label, tier: 'ad', n: { leads: a.gates.n_leads, closes: a.gates.n_closes } }, a)] : [];
    }
    return (lad[state.level] || []).map(function (a) {
      return Object.assign({ creative: a.label + ' (' + a.members + ' creatives)', tier: 'ad',
                             n: { leads: a.gates.n_leads, closes: a.gates.n_closes } }, a);
    });
  }

  function renderScoreboard() {
    var sb = state.board.scoreboard;
    document.querySelectorAll('.adx-level').forEach(function (b) {
      b.classList.toggle('active', b.dataset.level === state.level);
    });
    $('#adx-table-title').childNodes[0].textContent =
      { creative: 'Ads ', name: 'Creative names (all campaigns) ', batch: 'Batches ',
        campaign: 'Campaigns ', account: 'Account ' }[state.level];
    var thead = $('#adx-scoreboard thead'), tbody = $('#adx-scoreboard tbody');
    var VCOLS = activeCols();
    thead.innerHTML = '<tr>' + VCOLS.map(function (c) {
      var cls = c.k === state.sort ? (state.sortDir === -1 ? 'sorted desc' : 'sorted asc') : '';
      return '<th data-sort="' + c.k + '" class="' + cls + '" title="' + esc(TIPS[c.k] || '') + '">' + c.label + '</th>';
    }).join('') + '</tr>';
    var rows = levelRows().filter(function (r) {
      if (r.tier !== 'ad') return true;
      if (state.verdict && r.verdict !== state.verdict) return false;
      if (state.gq && String(r.creative || '').toLowerCase().indexOf(state.gq) < 0) return false;
      return (r.spend || r.leads || r.closes);
    });
    if (state.level !== 'creative') rows = rows.filter(function (r) { return r.tier === 'ad'; });
    // ROW CONTROL: sort the FULL dataset, then render a window of ad rows;
    // tier rows are pinned BELOW at every size (never sliced away).
    var sorted = sortRows(rows);
    var adRows = sorted.filter(function (r) { return r.tier === 'ad'; });
    var tierRows = sorted.filter(function (r) { return r.tier !== 'ad'; });
    var lim = rowLimit();
    var windowed = adRows.slice(0, lim).concat(tierRows);
    var cut = adRows.length - Math.min(adRows.length, lim);
    document.querySelectorAll('.adx-rowlimit').forEach(function (b) {
      b.classList.toggle('active', String(b.dataset.rows) === String(state.rows));
    });
    tbody.innerHTML = windowed.map(function (r) {
      var cls = 'adx-tier-' + r.tier + (state.creative === r.creative_key ? ' adx-selected' : '');
      if (r.integrity_error) {
        return '<tr class="adx-integrity-error" data-window="' + windowStamp() + '">' +
          '<td class="adx-name">' + esc(r.creative) + '</td>' +
          '<td colspan="' + (VCOLS.length - 1) + '">⚠ this row failed an integrity check — ' +
          esc(r.integrity_error) + ' — see the hygiene panel</td></tr>';
      }
      return '<tr class="' + cls + '" data-key="' + esc(r.creative_key) + '" data-tier="' + r.tier + '" data-window="' + windowStamp() + '">' +
        '<td class="adx-name">' + (r.tier === 'ad' ? esc(r.creative) : '<em>' + esc(r.creative) + '</em>') + '</td>' +
        (VCOLS.some(function (c) { return c.k === 'verdict'; }) ? '<td>' + (r.tier === 'ad' ? badge(r) : '—') + '</td>' : '') +
        VCOLS.filter(function (c) { return c.k !== 'creative' && c.k !== 'verdict'; }).map(function (c) {
          var v = r[c.k];
          // EVERY FUNNEL NUMBER OPENS ITS PEOPLE: all tabs, tier rows, zero cells
          // (a zero opens an honest empty state with the reason — never a dead click)
          var drill = DRILLABLE[c.k] ?
            ' class="adx-cell-drill" data-stage="' + c.k + '"' : '';
          var extra = (c.k === 'closes' && r.earlier_closes) ?
            ' <span class="adx-earlier adx-door" data-anom="earlier_closes" data-key="' + esc(r.creative_key) + '" title="' + r.earlier_closes + ' close(s) from leads that entered before this window (activity clock) — click for the deals">↤' + r.earlier_closes + '</span>' : '';
          // funnel-lag annotations (Case B): sets/shows that happened before this
          // window get the same ↤ treatment closes already had — never a bare
          // "0 sets, 1 close" row on the activity clock.
          if (c.k === 'sets' && r.earlier_sets) {
            extra += ' <span class="adx-earlier adx-door" data-anom="earlier_sets" data-key="' + esc(r.creative_key) + '" title="' + r.earlier_sets + ' closing deal(s) whose set call happened before this window (activity clock) — click for the deals">↤' + r.earlier_sets + '</span>';
          }
          if (c.k === 'shows' && r.earlier_shows) {
            extra += ' <span class="adx-earlier adx-door" data-anom="earlier_shows" data-key="' + esc(r.creative_key) + '" title="' + r.earlier_shows + ' show(s) before this window (activity clock) — click for the deals">↤' + r.earlier_shows + '</span>';
          }
          if (c.k === 'shows' && r.shows_unverified) {
            var sv = (r.shows || 0) - r.shows_unverified;
            extra += ' <span class="adx-earlier adx-door" data-anom="shows_unverified" data-key="' + esc(r.creative_key) + '" title="Shows ' + r.shows + ' = ' + sv + ' verified · ' + r.shows_unverified + ' unverified (status-only — attendance unproven; click for the cards)">' + sv + 'v·' + r.shows_unverified + 'u</span>';
          }
          if (c.k === 'sets' && r.undated_sets) {
            extra += ' <span class="adx-earlier adx-door" data-anom="undated_sets" data-key="' + esc(r.creative_key) + '" title="' + r.undated_sets + ' closing deal(s) whose set exists in the tracker but has NO Set Date — click for the deal, the evidence, and the queue item">◔' + r.undated_sets + '</span>';
          }
          // provenance always visible when any part of a count is derived
          if (c.k === 'sets' && r.sets_src) {
            extra += ' <span class="adx-prov" title="provenance">' + r.sets_src.tracker + ' tracker · ' + r.sets_src.derived + ' derived</span>';
          }
          if (c.k === 'shows' && r.shows_src) {
            extra += ' <span class="adx-prov" title="provenance">' + r.shows_src.tracker + ' tracker · ' + r.shows_src.derived + ' derived</span>';
          }
          return '<td' + drill + '>' + (c.money ? money(v) : num(v)) + extra + '</td>';
        }).join('') + '</tr>';
    }).join('') + (cut > 0 ? '<tr class="adx-rowcut"><td colspan="' + VCOLS.length + '">' +
      cut + ' more row(s) — raise the rows control (sort + find already ran over the full set)</td></tr>' : '');
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
    var thead = $('#adx-rows thead'), tbody = $('#adx-rows tbody');
    thead.innerHTML = '<tr><th>Lead</th><th>Business</th><th>In</th><th title="Monthly revenue band; amber = not captured">Revenue</th>' +
      '<th>Setter</th><th>Set</th><th>Show</th><th>Close</th><th>Cash</th><th>Creative</th></tr>';
    var rows = (state.board.rows || []).filter(rowMatches);
    if (reset) state.shown = 0;
    // ROW CONTROL: the selector sets the render window here too; "show more"
    // extends by the same step. Search always ran over the full dataset above.
    var step = state.rows === 'all' ? rows.length || 1 : +state.rows;
    state.shown = Math.min(rows.length, state.shown + step);
    tbody.innerHTML = rows.slice(0, state.shown).map(function (r, i) {
      var h = r.highlights || {};
      var cls = ['adx-row'];
      if (h.close) cls.push('adx-row-close');
      if (h.threshold_met === true) cls.push('adx-row-met');
      if (h.revenue_unknown) cls.push('adx-row-unknown');
      var rev = r.revenue || {};
      var revCell = rev.state === 'unknown' ? '<span class="adx-rev-unknown">revenue?</span>'
        : esc(rev.band || '—') + (rev.source === 'ghl_form' ? '<span class="adx-rev-src" title="from the GHL form answer">ᵍ</span>' : '');
      return '<tr class="' + cls.join(' ') + '" data-i="' + i + '" data-window="' + windowStamp() + '">' +
        '<td class="adx-name">' + esc(r.name) + (r.qualified ? ' <span class="adx-q" title="qualified">Q</span>' : '') + '</td>' +
        '<td>' + esc(r.business || '') + '</td><td>' + esc(r.input_date) + '</td>' +
        '<td>' + revCell + '</td><td>' + esc(r.setter_outcome || '—') + '</td>' +
        '<td>' + esc(r.set_date || '—') + '</td><td>' + (r.show ? '✓' : '—') + '</td>' +
        '<td>' + (r.close_date ? esc(r.close_date) : '—') + '</td>' +
        '<td class="adx-cash">' + (r.cash != null ? money(r.cash) : '—') + '</td>' +
        '<td class="adx-cr">' + esc((r.creative.label || '').slice(0, 40)) + '</td></tr>';
    }).join('');
    var more = $('#adx-more');
    more.style.display = state.shown < rows.length ? '' : 'none';
    more.textContent = 'show more rows (' + (rows.length - state.shown) + ' remaining)';
    $('#adx-rows-title').textContent = 'Live tracker — ' + rows.length + ' row(s)' +
      (state.creative ? ' · filtered' : '') + (state.q ? ' · “' + state.q + '”' : '');
  }

  // ── THE DRILL ──────────────────────────────────────────────────────────────
  function openDrill(title, html) {
    $('#adx-drill-title').innerHTML = title;
    $('#adx-drill-body').innerHTML = html;
    $('#adx-drill-scrim').style.display = '';
  }
  function closeDrill() { $('#adx-drill-scrim').style.display = 'none'; }

  function candidatesNote(p) {
    var cands = (p.creative && p.creative.candidates) || p.candidates;
    if (!cands || !cands.length) return '';
    return '<div class="adx-cands">name matches ' + cands.length + ' ads — candidates: ' +
      cands.map(function (c) { return esc(c.ad_id) + ' [' + esc(c.campaign || '?') + ']'; }).join(' · ') +
      ' — QUARANTINED, not assigned</div>';
  }

  function identityChip(p) {
    if (!p.identity) return '';
    var cls = p.identity === 'id-linked' ? 'adx-id-ok'
      : p.identity.indexOf('ambiguous') === 0 ? 'adx-id-amb'
      : p.identity.indexOf('name-match') === 0 ? 'adx-id-name' : 'adx-id-only';
    return '<span class="adx-chip adx-id ' + cls + '" title="tracker↔GHL identity">' + esc(p.identity) + '</span>';
  }
  function funnelChips(p) {
    return (p.funnel || []).map(function (c) {
      return '<span class="adx-chip' + (c.on ? ' on' : '') + '"' +
        (c.provenance ? ' title="' + esc(c.provenance) + '"' : '') + '>' + esc(c.chip) + '</span>';
    }).join('');
  }
  function personCard(p) {
    var rev = p.revenue || {};
    var revLine = rev.state === 'unknown' ? '<span class="adx-rev-unknown">revenue not captured</span>'
      : esc(rev.band || '—') + (rev.source ? ' <span class="adx-note-src">(' + esc(rev.source) + ')</span>' : '');
    var notes = (p.notes || []).map(function (n) {
      return '<div class="adx-note"><span class="adx-note-body">' + esc(n.body) + '</span>' +
        '<span class="adx-note-src">' + esc(n.source) + (n.date ? ' · ' + esc(n.date) : '') + '</span></div>';
    }).join('') || '<div class="adx-note adx-note-empty">no notes recorded</div>';
    var ev = p.event || {};
    var evLine = ev.kind ? '<div class="adx-person-event">' + esc(ev.kind) + ' ' +
      (ev.date ? esc(ev.date) : '<em>no date</em>') +
      ' <span class="adx-prov" title="provenance">' + esc(ev.provenance || '') + '</span>' +
      (ev.note ? ' <em>' + esc(ev.note) + '</em>' : '') + '</div>' : '';
    return '<div class="adx-person">' + candidatesNote(p) +
      '<div class="adx-person-head"><strong>' + esc(p.name) + '</strong>' +
      (p.name_discrepancy ? ' <span class="adx-chip adx-id-amb" title="tracker vs GHL name differ — both shown">name discrepancy: GHL says “' + esc(p.ghl_name) + '”</span>' : '') +
      (p.business && p.business !== p.name ? ' · ' + esc(p.business) : '') +
      ' ' + identityChip(p) +
      (p.ghl_link ? ' <a class="adx-ghl" href="' + esc(p.ghl_link) + '" target="_blank" rel="noopener">GHL ↗</a>' : '') +
      (p.tracker_link ? ' <a class="adx-ghl" href="' + esc(p.tracker_link) + '" target="_blank" rel="noopener" title="Lead-to-Cash tracker (find the row by name — row anchors are unsafe under the clean view)">tracker ↗</a>' : '') + '</div>' +
      evLine +
      (p.tier_reason ? '<div class="adx-warnline">' + esc(p.tier_reason) + '</div>' : '') +
      '<div class="adx-person-chips">' + funnelChips(p) + '</div>' +
      '<div class="adx-person-meta">in ' + esc(p.input_date || '—') +
      ' · revenue ' + revLine +
      ' · setter: ' + esc(p.setter_outcome || '—') +
      (p.pipeline_stage ? ' · stage: ' + esc(p.pipeline_stage) : '') +
      (p.close_date ? ' · <strong>closed ' + esc(p.close_date) + '</strong>' +
        (p.contract != null ? ', contract ' + money(p.contract) : '') +
        (p.cash != null ? ', cash ' + money(p.cash) : '') : '') + '</div>' +
      notes + '</div>';
  }

  // ── EVERY NUMBER IS A DOOR: anomaly panel → deal panel → dossier ──────────
  var ANOM_COPY = {
    earlier_closes: 'close(s) from leads that entered before this window — true on the activity clock, annotated never phantom',
    earlier_sets: 'set call(s) that happened before this window — the close landed here, the conversation earlier',
    earlier_shows: 'show(s) before this window',
    shows_unverified: 'show rests on appointment status alone (no completed/showed status exists in GHL) — attendance needs a call record or a downstream close; confirm with \u201cconfirm attendance for <name>\u201d',
    undated_sets: 'set exists in the tracker but its Set Date cell is BLANK — the activity clock cannot place it (Piolo queue: fill at source)'
  };
  function anomalyPanel(creativeKey, kind) {
    // THE ROSTER ENGINE serves anomaly classes too (?metric=earlier_sets etc.) —
    // the old client-side filter over board.rows was a parallel person list; deleted.
    var row = (state.board.scoreboard.rows || []).filter(function (r) {
      return r.creative_key === creativeKey; })[0] || {};
    openDrill(esc(String(row.creative || creativeKey).slice(0, 50)) + ' · anomaly · ' + windowStamp() +
              ' · ' + state.basis + ' clock',
              '<div class="adx-skel">Loading the deals…</div>');
    var note = '<div class="adx-roster-note">' + esc(ANOM_COPY[kind] || kind) + '</div>';
    fetch('/ads/api/roster?days=' + state.days + '&basis=' + encodeURIComponent(state.basis) +
          '&market=' + encodeURIComponent(state.market) +
          '&level=' + encodeURIComponent(state.level) +
          '&key=' + encodeURIComponent(creativeKey) + '&metric=' + encodeURIComponent(kind),
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = note + '<div class="adx-roster-note">' + esc((d && d.error) || 'fetch failed') + '</div>'; return; }
        rosterState.people = d.people || [];
        rosterState.head = note + (d.empty_reason ? '<div class="adx-roster-note">' + esc(d.empty_reason) + '</div>' : '');
        renderRosterPeople();
      })
      .catch(function () { $('#adx-drill-body').innerHTML = note + 'fetch failed'; });
  }
  function dealPanel(name) {
    openDrill(esc(name) + ' · deal evidence', '<div class="adx-skel">Loading the evidence…</div>');
    fetch('/ads/api/deal?name=' + encodeURIComponent(name), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = '<div class="adx-roster-note">' + esc((d && d.error) || 'fetch failed') + '</div>'; return; }
        var t = d.tracker || {};
        var html = '<div class="adx-person">' +
          '<div class="adx-person-name">' + esc(d.name) + (d.business ? ' · ' + esc(d.business) : '') +
          (d.market ? ' <span class="adx-prov">' + esc(d.market.toUpperCase()) + '</span>' : '') +
          (d.ghl_link ? ' <a class="adx-ghl" href="' + esc(d.ghl_link) + '" target="_blank" rel="noopener">GHL ↗</a>' : '') + '</div>' +
          '<div class="adx-person-meta">tracker: in ' + esc(t.input_date || '—') + ' · setter ' + esc(t.setter_outcome || '—') +
          ' · set ' + esc(t.set || '—') + ' (date ' + esc(t.set_date || 'BLANK') + ') · show ' + esc(t.show || '—') +
          ' · closer ' + esc(t.closer_outcome || '—') + ' · close date ' + esc(t.close_date || 'BLANK') +
          (d.derived_dates ? ' · <span class="adx-prov">derived: ' + esc(Object.keys(d.derived_dates).map(function (f) {
            return f + ' ' + d.derived_dates[f].date + ' (' + d.derived_dates[f].provenance + ')'; }).join(' · ')) + '</span>' : '') +
          ' · contract ' + esc(t.contract || '—') + ' · cash ' + esc(t.cash || '—') + '</div>' +
          (d.why_invisible ? '<div class="adx-warnline">' + d.why_invisible.map(esc).join('<br>') + '</div>' : '') +
          '<div class="adx-queue">' + (d.queue || []).map(function (q) {
            return '<div class="adx-queue-item"><span class="adx-queue-state">' + esc(q.state) + '</span> ' + esc(q.detail || '') + '</div>';
          }).join('') + '</div>' +
          '<div class="adx-person-meta">resolution lane: ' + esc(d.resolution_lane || '—') + '</div></div>';
        $('#adx-drill-body').innerHTML = html;
      })
      .catch(function () { $('#adx-drill-body').textContent = 'Deal fetch failed.'; });
  }
  function openDossier(creativeKey) {
    openDrill('Creative dossier · ' + windowStamp() + ' · ' + state.basis + ' clock',
              '<div class="adx-skel">Assembling the dossier…</div>');
    try { history.replaceState(null, '', location.search.replace(/&?dossier=[^&]*/, '') + '&dossier=' + encodeURIComponent(creativeKey)); } catch (e) {}
    fetch('/ads/api/dossier?days=' + state.days + '&basis=' + state.basis + '&market=' + state.market +
          '&creative=' + encodeURIComponent(creativeKey), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = '<div class="adx-roster-note">' + esc((d && d.error) || 'fetch failed') + '</div>'; return; }
        var id = d.identity || {};
        function econRow(label, e) {
          if (!e) return '<div class="adx-dossier-econ"><strong>' + label + '</strong>: no leads in this scope (honest zero — not an error)</div>';
          return '<div class="adx-dossier-econ"><strong>' + label + '</strong>: ' +
            'leads ' + num(e.leads) + ' · qual ' + num(e.qualified) + ' · reached ' + num(e.reached) +
            ' · sets ' + num(e.sets) + ' · shows ' + num(e.shows) + ' · closes ' + num(e.closes) +
            ' · cash ' + money(e.cash) + ' · spend ' + money(e.spend) +
            ' · CPL ' + money(e.cost_per_lead) + ' · C/Qual ' + money(e.cost_per_qualified) +
            ' · C/Set ' + money(e.cost_per_set) + ' · C/Close ' + money(e.cost_per_close) +
            (e.verdict ? ' · verdict ' + esc(e.verdict) : '') +
            (e.provisional ? ' <span class="adx-prov">' + esc(e.provisional.label || 'provisional') + '</span>' : '') +
            '</div>';
        }
        // the ledger arrives from THE roster engine (leads roster for this cell) —
        // identity + provenance chips identical to every other roster surface
        var ledger = (d.ledger || []).map(function (v) {
          return '<div class="adx-ledger-row"><button class="adx-deal-open adx-door" data-deal="' + esc(v.name) + '">' + esc(v.name) + '</button>' +
            (v.name_discrepancy ? ' <span class="adx-chip adx-id-amb" title="tracker vs GHL name differ">GHL: “' + esc(v.ghl_name) + '”</span>' : '') +
            (v.business ? ' · ' + esc(v.business) : '') + ' · in ' + esc(v.input_date || '—') +
            ' ' + identityChip(v) + ' ' + funnelChips(v) +
            (v.cash != null && v.close_date ? ' · ' + money(v.cash) : '') +
            (v.ghl_link ? ' <a class="adx-ghl" href="' + esc(v.ghl_link) + '" target="_blank" rel="noopener">GHL ↗</a>' : '') +
            (v.tracker_link ? ' <a class="adx-ghl" href="' + esc(v.tracker_link) + '" target="_blank" rel="noopener">tracker ↗</a>' : '') +
            '</div>';
        }).join('');
        $('#adx-drill-body').innerHTML =
          '<div class="adx-dossier-sec"><h3>Identity & delivery</h3>' +
          '<div class="adx-person-meta">' + esc(d.label) + ' · tier ' + esc(d.tier) +
          (d.campaigns && d.campaigns.length ? ' · ' + d.campaigns.map(esc).join(', ') : '') +
          (id.status ? ' · status ' + esc(id.status) : '') +
          (id.created_time ? ' · created ' + esc(String(id.created_time).slice(0, 10)) + ' <em>(' + esc(id.created_time_note || '') + ')</em>' : '') +
          (d.history ? ' · <span class="adx-prov">(archived history)</span>' : '') + '</div></div>' +
          '<div class="adx-dossier-sec"><h3>Unit economics <span class="adx-h2-sub">one engine · min-n labels intact</span></h3>' +
          econRow(windowStamp(), d.econ_window) + econRow('All time', d.econ_all_time) +
          (state.board.market_note ? '<div class="adx-market-note">' + esc(state.board.market_note) + '</div>' : '') + '</div>' +
          '<div class="adx-dossier-sec"><h3>Lead ledger <span class="adx-h2-sub">' + d.ledger_count + ' lead(s) · newest first · window-scoped (switch window to All for history)</span></h3>' +
          (ledger || '<div class="adx-roster-note">' + esc(d.ledger_empty_reason || 'no leads in this window for this creative — honest empty, not an error') + '</div>') + '</div>';
      })
      .catch(function () { $('#adx-drill-body').textContent = 'Dossier fetch failed.'; });
  }

  var rosterState = { people: [], sort: 'event', head: '', title: '' };
  function rosterSortBtns() {
    return '<div class="adx-roster-sorts">sort: ' + ['event', 'state', 'cash'].map(function (k) {
      return '<button class="adx-roster-sort' + (rosterState.sort === k ? ' active' : '') +
        '" data-rsort="' + k + '">' + (k === 'event' ? 'event date' : k) + '</button>';
    }).join(' ') + '</div>';
  }
  function renderRosterPeople() {
    var ppl = rosterState.people.slice();
    if (rosterState.sort === 'event') {
      ppl.sort(function (a, b) { return String((b.event || {}).date || '').localeCompare(String((a.event || {}).date || '')); });
    } else if (rosterState.sort === 'state') {
      ppl.sort(function (a, b) { return (b.state_rank || 0) - (a.state_rank || 0); });
    } else if (rosterState.sort === 'cash') {
      ppl.sort(function (a, b) { return (b.cash || 0) - (a.cash || 0); });
    }
    $('#adx-drill-body').innerHTML = rosterState.head +
      (ppl.length ? rosterSortBtns() : '') + ppl.map(personCard).join('');
  }
  function loadRoster(level, key, label, metric, expected) {
    // the drill INHERITS the clicked cell's clock (I11) and states it in the header
    openDrill(esc(String(label || key).slice(0, 50)) + ' · ' + metric + ' · ' + windowStamp() +
              ' · ' + state.basis + ' clock',
              '<div class="adx-skel">Loading the humans…</div>');
    var spec = 'level=' + encodeURIComponent(level) + '&key=' + encodeURIComponent(key) +
               '&metric=' + encodeURIComponent(metric);
    try { history.replaceState(null, '', location.search.replace(/&?roster=[^&]*/, '') +
      '&roster=' + encodeURIComponent(level + '~' + key + '~' + metric)); } catch (e) {}
    fetch('/ads/api/roster?days=' + state.days + '&basis=' + encodeURIComponent(state.basis) +
          '&market=' + encodeURIComponent(state.market) + '&' + spec,
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : r.json().then(function (j) { return j; }).catch(function () { return null; }); })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = '<div class="adx-roster-note">' + esc((d && d.error) || 'Roster fetch failed.') + '</div>'; return; }
        var head = '<div class="adx-roster-note">' + esc(d.clock_note || '') + '</div>';
        var i17 = d.i17 || {};
        if (i17.ok === false) {
          head += '<div class="adx-roster-count">I17 DRIFT: the cell reads ' + i17.cell +
            ' but the roster carries ' + i17.roster + ' — flagged loudly in the truth sweep; do not trust this cell until it clears</div>';
        } else if (expected != null && !isNaN(expected) && +expected !== d.count) {
          head += '<div class="adx-roster-count">' + metric + ': grid ' + expected +
            ' vs engine ' + d.count + ' — a render/engine skew (stale board?); reload the window</div>';
        } else {
          head += '<div class="adx-roster-count">' + d.count + ' ' + metric +
            ' <span class="adx-match">— matches the cell ✓ (' + esc(d.basis || state.basis) + ' clock)</span></div>';
        }
        if (d.empty_reason) head += '<div class="adx-roster-note">' + esc(d.empty_reason) + '</div>';
        rosterState.people = d.people || [];
        rosterState.head = head;
        renderRosterPeople();
      })
      .catch(function () { $('#adx-drill-body').textContent = 'Roster fetch failed.'; });
  }

  // ── events ─────────────────────────────────────────────────────────────────
  function init() {
    var m = (location.search.match(/[?&]window=(\d{1,3}|all)/) || [])[1];
    var days = m === 'all' ? 'all' : ([30, 60, 90].indexOf(+m) >= 0 ? +m : 30);
    var rowsParam = (location.search.match(/[?&]rows=(\d{1,4}|all)/) || [])[1];
    if (rowsParam) state.rows = rowsParam === 'all' ? 'all' : +rowsParam;
    document.querySelectorAll('.adx-rowlimit').forEach(function (b) {
      b.addEventListener('click', function () {
        state.rows = b.dataset.rows === 'all' ? 'all' : +b.dataset.rows;
        try { localStorage.setItem('adx-rows', String(state.rows)); } catch (err) {}
        try { history.replaceState(null, '', location.search.replace(/([?&])rows=[^&]*/, '$1rows=' + state.rows)); } catch (err) {}
        renderScoreboard(); renderRows(true);
      });
    });
    var mk = (location.search.match(/[?&]market=(au|us|unknown|all)/) || [])[1];
    if (mk) state.market = mk;
    var so = (location.search.match(/[?&]sort=([a-z_]+)\.(asc|desc)/) || []);
    if (so[1]) { state.sort = so[1]; state.sortDir = so[2] === 'asc' ? 1 : -1; }
    var bParam = (location.search.match(/[?&]basis=(cohort|activity)/) || [])[1];
    if (bParam) state.basis = bParam;
    document.querySelectorAll('.adx-basis').forEach(function (b) {
      b.addEventListener('click', function () { loadBoard(state.days, b.dataset.basis); });
    });
    var vParam = (location.search.match(/[?&]verdict=([^&]+)/) || [])[1];
    if (vParam) state.verdict = decodeURIComponent(vParam);
    var cParam = (location.search.match(/[?&]creative=([^&]+)/) || [])[1];
    if (cParam) state.creative = decodeURIComponent(cParam);
    document.querySelectorAll('.adx-win').forEach(function (b) {
      b.addEventListener('click', function () { loadBoard(+b.dataset.days); });
    });
    $('#adx-scoreboard').addEventListener('click', function (e) {
      var door = e.target.closest('.adx-door[data-anom]');
      if (door) { anomalyPanel(door.dataset.key, door.dataset.anom); return; }
      var th = e.target.closest('th[data-sort]');
      if (th) {
        var k = th.dataset.sort;
        if (state.sort === k) state.sortDir = -state.sortDir; else { state.sort = k; state.sortDir = -1; }
        try { history.replaceState(null, '', location.search.replace(/([?&])sort=[^&]*/, '$1sort=' + state.sort + '.' + (state.sortDir === -1 ? 'desc' : 'asc'))); } catch (err) {}
        renderScoreboard(); return;
      }
      var td = e.target.closest('td.adx-cell-drill');
      var tr = e.target.closest('tr[data-key]');
      if (td && tr) {
        loadRoster(state.level, tr.dataset.key, tr.querySelector('.adx-name').textContent,
                   td.dataset.stage, parseInt(td.textContent, 10));
        return;
      }
      // THE DOSSIER: clicking the creative NAME opens the whole story
      var nameCell = e.target.closest('td.adx-name');
      if (nameCell && tr && tr.dataset.tier === 'ad' && state.level === 'creative') {
        openDossier(tr.dataset.key); return;
      }
      if (tr && tr.dataset.tier === 'ad') {
        state.creative = state.creative === tr.dataset.key ? null : tr.dataset.key;
        renderScoreboard(); renderRows(true);
      }
    });
    // deal-panel doors anywhere (hygiene rail, anomaly panels, dossier ledger)
    document.addEventListener('click', function (e) {
      var dbtn = e.target.closest('.adx-deal-open[data-deal]');
      if (dbtn) { dealPanel(dbtn.dataset.deal); return; }
      var lbtn = e.target.closest('.adx-deal-list[data-key]');
      if (lbtn) { loadRoster('creative', lbtn.dataset.key, lbtn.dataset.key, 'closes', null); return; }
      var rsort = e.target.closest('.adx-roster-sort[data-rsort]');
      if (rsort) { rosterState.sort = rsort.dataset.rsort; renderRosterPeople(); }
    });
    document.querySelectorAll('.adx-market').forEach(function (b) {
      b.addEventListener('click', function () { loadBoard(state.days, null, b.dataset.market); });
    });
    $('#adx-preset').addEventListener('change', function () {
      var v = $('#adx-preset').value;
      if (!v) return;
      var parts = v.split('.');
      state.sort = parts[0]; state.sortDir = parts[1] === 'asc' ? 1 : -1;
      renderScoreboard();
      $('#adx-preset').value = '';
    });
    var gdeb = null;
    $('#adx-grid-find').addEventListener('input', function () {
      clearTimeout(gdeb);
      var v = $('#adx-grid-find').value;
      gdeb = setTimeout(function () { state.gq = v.trim().toLowerCase(); renderScoreboard(); }, 150);
    });
    // column picker (presentation only — persisted)
    (function () {
      var body = $('#adx-colpick-body');
      if (!body) return;
      body.innerHTML = COLS.filter(function (c) { return c.k !== 'creative'; }).map(function (c) {
        return '<label class="adx-colpick-item"><input type="checkbox" data-col="' + c.k + '"' +
          (hiddenCols.indexOf(c.k) < 0 ? ' checked' : '') + '> ' + esc(c.label) + '</label>';
      }).join('');
      body.addEventListener('change', function (e) {
        var cb = e.target.closest('input[data-col]');
        if (!cb) return;
        var k = cb.dataset.col;
        if (cb.checked) hiddenCols = hiddenCols.filter(function (x) { return x !== k; });
        else if (hiddenCols.indexOf(k) < 0) hiddenCols.push(k);
        try { localStorage.setItem('adx-cols-hidden', JSON.stringify(hiddenCols)); } catch (err) {}
        renderScoreboard();
      });
    })();
    $('#adx-rows').addEventListener('click', function (e) {
      var tr = e.target.closest('tr[data-i]');
      if (!tr) return;
      var rows = (state.board.rows || []).filter(rowMatches);
      var r = rows[+tr.dataset.i];
      if (!r) return;
      openDrill(esc(r.name), '<div class="adx-skel">Loading…</div>');
      // one person: reuse the roster endpoint for their stage cohort, filter client-side
      fetch('/ads/api/roster?days=' + state.days + '&stage=leads&creative=' +
            encodeURIComponent(r.creative.key), { credentials: 'same-origin' })
        .then(function (x) { return x.ok ? x.json() : null; })
        .then(function (d) {
          var p = d && (d.people || []).filter(function (x) { return x.name === r.name; })[0];
          $('#adx-drill-body').innerHTML = p ? personCard(p) : 'Person not found in the cohort.';
        });
    });
    $('#adx-drill-close').addEventListener('click', closeDrill);
    $('#adx-drill-scrim').addEventListener('click', function (e) {
      if (e.target === $('#adx-drill-scrim')) closeDrill();
    });
    document.querySelectorAll('.adx-level').forEach(function (b) {
      b.addEventListener('click', function () {
        levelChosen = true; state.level = b.dataset.level; renderScoreboard();
      });
    });
    $('#adx-defs-btn').addEventListener('click', function () {
      renderDefs(); $('#adx-defs-scrim').style.display = '';
    });
    $('#adx-defs-close').addEventListener('click', function () { $('#adx-defs-scrim').style.display = 'none'; });
    $('#adx-defs-scrim').addEventListener('click', function (e) {
      if (e.target === $('#adx-defs-scrim')) $('#adx-defs-scrim').style.display = 'none';
    });
    var deb = null;
    $('#adx-search').addEventListener('input', function () {
      clearTimeout(deb);
      var v = $('#adx-search').value;
      deb = setTimeout(function () { state.q = v.trim(); renderRows(true); }, 200);
    });
    $('#adx-more').addEventListener('click', function () { renderRows(false); });
    fetch('/dashboard/api/whoami', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (w) { if (w) $('#adx-who').textContent = w.display || w.user || ''; });
    var dossierParam = (location.search.match(/[?&]dossier=([^&]+)/) || [])[1];
    var dealParam = (location.search.match(/[?&]deal=([^&]+)/) || [])[1];
    var rosterParam = (location.search.match(/[?&]roster=([^&]+)/) || [])[1];
    loadBoard(days);
    if (dossierParam) setTimeout(function () { openDossier(decodeURIComponent(dossierParam)); }, 600);
    else if (dealParam) setTimeout(function () { dealPanel(decodeURIComponent(dealParam)); }, 600);
    else if (rosterParam) setTimeout(function () {
      // ?roster=<level>~<key>~<metric> — a linkable cell-spec
      var parts = decodeURIComponent(rosterParam).split('~');
      if (parts.length === 3) loadRoster(parts[0], parts[1], parts[1], parts[2], null);
    }, 600);
  }

  window.AdsApp = {
    setWindow: loadBoard,
    setVerdict: function (v) { state.verdict = v || null; renderScoreboard(); },
    state: function () { return { days: state.days, creative: state.creative, verdict: state.verdict }; },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
