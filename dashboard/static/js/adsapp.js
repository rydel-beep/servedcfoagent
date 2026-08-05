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
                q: '', board: null, shown: 0, reqToken: 0, level: 'creative' };
  var PAGE = 150;

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
    qualified: 'Leads that passed all three checks: setter outcome not DQ, revenue band $20k+/month, form answered.',
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
    { k: 'sets', label: 'Sets' }, { k: 'shows', label: 'Shows' },
    { k: 'closes', label: 'Closes' }, { k: 'cash', label: 'Cash', money: 1 },
    { k: 'spend', label: 'Spend', money: 1 }, { k: 'cost_per_lead', label: 'CPL', money: 1 },
    { k: 'cost_per_qualified', label: 'C/Qual', money: 1 },
    { k: 'cost_per_set', label: 'C/Set', money: 1 },
    { k: 'cost_per_close', label: 'C/Close (ad)', money: 1 },
    { k: 'cost_per_close_loaded', label: 'C/Close (loaded)', money: 1 },
    { k: 'ltgp_cac', label: 'LTGP:CAC' },
  ];
  var DRILLABLE = { leads: 1, qualified: 1, sets: 1, shows: 1, closes: 1 };

  // ── the atomic window fetch (latest-wins + echo guard) ─────────────────────
  function loadBoard(days) {
    state.days = days;
    var token = ++state.reqToken;
    document.querySelectorAll('.adx-win').forEach(function (b) {
      b.classList.toggle('active', +b.dataset.days === days);
    });
    try { history.replaceState(null, '', '?window=' + days); } catch (e) {}
    $('#adx-banner').innerHTML = '<span class="adx-skel">Loading ' + days + 'd window…</span>';
    document.body.classList.add('adx-loading');
    fetch('/ads/api/board?days=' + days, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (token !== state.reqToken) return;              // latest wins — stale dropped
        document.body.classList.remove('adx-loading');
        if (!data) { $('#adx-banner').textContent = 'Engine unreachable — nothing rendered rather than stale numbers.'; return; }
        if (!data.window || data.window.days !== state.days) {
          console.error('STALE-MIX GUARD: response window', data.window,
                        'does not match state', state.days, '— discarded');
          return;
        }
        state.board = data;
        renderAll();
      })
      .catch(function () {
        if (token !== state.reqToken) return;
        document.body.classList.remove('adx-loading');
        $('#adx-banner').textContent = 'Board fetch failed — toggle a window to retry.';
      });
  }

  function windowStamp() { return state.board.window.days + 'd'; }

  var levelChosen = false;   // the user's explicit pick beats the default
  function renderAll() {
    if (!levelChosen && state.board.ladder && state.board.ladder.default_level) {
      state.level = state.board.ladder.default_level;
    }
    renderBanner(); renderScorecard(); renderHygiene(); renderScoreboard(); renderRows(true);
    $('#adx-table-window').textContent = '· ' + windowStamp() + ' window';
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
    var ds = (h.disagreements || []);
    var items = ds.slice(0, 8).map(function (d) {
      return '<div class="adx-hyg-item adx-sev' + d.severity + '"><span>' + esc(d.detail) + '</span>' +
        '<span class="adx-hyg-fix">fix: ' + esc(d.fix) + ' · ' + esc(d.owner || '') + '</span></div>';
    }).join('');
    $('#adx-hygiene-body').innerHTML = '<div class="adx-hyg-line">' + line + '</div>' +
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
      (state.days === 30 ? ' · <span class="adx-guide">closes trail leads — 60/90d is the honest read for LTGP:CAC verdicts</span>' : '');
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

  function sortRows(rows) {
    var k = state.sort, dir = state.sortDir;
    return rows.slice().sort(function (a, b) {
      var at = a.tier !== 'ad' ? 1 : 0, bt = b.tier !== 'ad' ? 1 : 0;
      if (at !== bt) return at - bt;
      var av = a[k], bv = b[k];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av < bv ? -dir : av > bv ? dir : 0;
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
      { creative: 'Creatives ', batch: 'Batches ', campaign: 'Campaigns ', account: 'Account ' }[state.level];
    var thead = $('#adx-scoreboard thead'), tbody = $('#adx-scoreboard tbody');
    thead.innerHTML = '<tr>' + COLS.map(function (c) {
      var cls = c.k === state.sort ? (state.sortDir === -1 ? 'sorted desc' : 'sorted asc') : '';
      return '<th data-sort="' + c.k + '" class="' + cls + '" title="' + esc(TIPS[c.k] || '') + '">' + c.label + '</th>';
    }).join('') + '</tr>';
    var rows = levelRows().filter(function (r) {
      if (r.tier !== 'ad') return true;
      if (state.verdict && r.verdict !== state.verdict) return false;
      return (r.spend || r.leads || r.closes);
    });
    if (state.level !== 'creative') rows = rows.filter(function (r) { return r.tier === 'ad'; });
    tbody.innerHTML = sortRows(rows).map(function (r) {
      var cls = 'adx-tier-' + r.tier + (state.creative === r.creative_key ? ' adx-selected' : '');
      return '<tr class="' + cls + '" data-key="' + esc(r.creative_key) + '" data-tier="' + r.tier + '" data-window="' + windowStamp() + '">' +
        '<td class="adx-name">' + (r.tier === 'ad' ? esc(r.creative) : '<em>' + esc(r.creative) + '</em>') + '</td>' +
        '<td>' + (r.tier === 'ad' ? badge(r) : '—') + '</td>' +
        COLS.slice(2).map(function (c) {
          var v = r[c.k];
          var drill = DRILLABLE[c.k] && r.tier === 'ad' && v && state.level === 'creative' ?
            ' class="adx-cell-drill" data-stage="' + c.k + '"' : '';
          return '<td' + drill + '>' + (c.money ? money(v) : num(v)) + '</td>';
        }).join('') + '</tr>';
    }).join('');
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
    state.shown = Math.min(rows.length, state.shown + PAGE);
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

  function personCard(p) {
    var rev = p.revenue || {};
    var revLine = rev.state === 'unknown' ? '<span class="adx-rev-unknown">revenue not captured</span>'
      : esc(rev.band || '—') + (rev.source ? ' <span class="adx-note-src">(' + esc(rev.source) + ')</span>' : '');
    var notes = (p.notes || []).map(function (n) {
      return '<div class="adx-note"><span class="adx-note-body">' + esc(n.body) + '</span>' +
        '<span class="adx-note-src">' + esc(n.source) + (n.date ? ' · ' + esc(n.date) : '') + '</span></div>';
    }).join('') || '<div class="adx-note adx-note-empty">no notes recorded</div>';
    return '<div class="adx-person">' +
      '<div class="adx-person-head"><strong>' + esc(p.name) + '</strong>' +
      (p.business && p.business !== p.name ? ' · ' + esc(p.business) : '') +
      (p.ghl_link ? ' <a class="adx-ghl" href="' + esc(p.ghl_link) + '" target="_blank" rel="noopener">GHL ↗</a>' : '') + '</div>' +
      '<div class="adx-person-meta">in ' + esc(p.input_date || '—') +
      ' · revenue ' + revLine +
      ' · setter: ' + esc(p.setter_outcome || '—') +
      (p.pipeline_stage ? ' · stage: ' + esc(p.pipeline_stage) : '') +
      (p.close_date ? ' · <strong>closed ' + esc(p.close_date) + '</strong>' +
        (p.contract != null ? ', contract ' + money(p.contract) : '') +
        (p.cash != null ? ', cash ' + money(p.cash) : '') : '') + '</div>' +
      notes + '</div>';
  }

  function loadRoster(creativeKey, creativeLabel, stage, expected) {
    openDrill(esc(creativeLabel.slice(0, 50)) + ' · ' + stage + ' · ' + windowStamp(),
              '<div class="adx-skel">Loading the humans…</div>');
    fetch('/ads/api/roster?days=' + state.days + '&stage=' + stage +
          (creativeKey ? '&creative=' + encodeURIComponent(creativeKey) : ''),
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) { $('#adx-drill-body').textContent = 'Roster fetch failed.'; return; }
        var head = '<div class="adx-roster-count">' + d.count + ' ' + stage +
          (expected != null && +expected !== d.count
            ? ' <span class="adx-mismatch">⚠ cell said ' + expected + ' — mismatch, report this</span>'
            : ' <span class="adx-match">— matches the cell ✓</span>') + '</div>';
        $('#adx-drill-body').innerHTML = head + (d.people || []).map(personCard).join('');
      })
      .catch(function () { $('#adx-drill-body').textContent = 'Roster fetch failed.'; });
  }

  // ── events ─────────────────────────────────────────────────────────────────
  function init() {
    var m = (location.search.match(/[?&]window=(\d{1,3})/) || [])[1];
    var days = [30, 60, 90].indexOf(+m) >= 0 ? +m : 30;
    var vParam = (location.search.match(/[?&]verdict=([^&]+)/) || [])[1];
    if (vParam) state.verdict = decodeURIComponent(vParam);
    var cParam = (location.search.match(/[?&]creative=([^&]+)/) || [])[1];
    if (cParam) state.creative = decodeURIComponent(cParam);
    document.querySelectorAll('.adx-win').forEach(function (b) {
      b.addEventListener('click', function () { loadBoard(+b.dataset.days); });
    });
    $('#adx-scoreboard').addEventListener('click', function (e) {
      var th = e.target.closest('th[data-sort]');
      if (th) {
        var k = th.dataset.sort;
        if (state.sort === k) state.sortDir = -state.sortDir; else { state.sort = k; state.sortDir = -1; }
        renderScoreboard(); return;
      }
      var td = e.target.closest('td.adx-cell-drill');
      var tr = e.target.closest('tr[data-key]');
      if (td && tr) {
        loadRoster(tr.dataset.key, tr.querySelector('.adx-name').textContent,
                   td.dataset.stage, td.textContent.trim());
        return;
      }
      if (tr && tr.dataset.tier === 'ad') {
        state.creative = state.creative === tr.dataset.key ? null : tr.dataset.key;
        renderScoreboard(); renderRows(true);
      }
    });
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
    loadBoard(days);
  }

  window.AdsApp = {
    setWindow: loadBoard,
    setVerdict: function (v) { state.verdict = v || null; renderScoreboard(); },
    state: function () { return { days: state.days, creative: state.creative, verdict: state.verdict }; },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
