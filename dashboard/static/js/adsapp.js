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
                basis: 'cohort', market: 'all', rows: 70,
                // #133 META-STYLE DATE CONTROL: range = 'YYYY-MM-DD..YYYY-MM-DD' or
                // null (standard windows). clockChosen: the user's explicit clock
                // pick survives preset switches; otherwise presets default to
                // ACTIVITY (the Meta-native reading) and the standard windows keep
                // the ruled cohort default.
                range: null, rangeLabel: null, clockChosen: false };

  // Sydney "today" — the date control's boundaries are SYDNEY days (F8
  // discipline), never the browser's local day.
  function sydToday() {
    try {
      return new Date().toLocaleDateString('en-CA', { timeZone: 'Australia/Sydney' });
    } catch (e) { return new Date().toISOString().slice(0, 10); }
  }
  function isoShift(iso, days) {
    var d = new Date(iso + 'T12:00:00Z');       // noon UTC — immune to date rollover
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }
  var RANGE_RE = /^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$/;
  // the window part of every engine query — board, roster, dossier, anomaly
  // panels all inherit the SAME box + clock (drills inherit the exact box)
  function windowQS() {
    return (state.range ? 'range=' + state.range : 'days=' + state.days) +
      '&clock=' + state.basis + '&market=' + state.market;
  }
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

  // ── F5: LOUD DEGRADATION (audit F5 — the loud-fallback doctrine on the money
  // columns). A dead upstream must be UNMISTAKABLE from a true zero: any metric
  // whose source is degraded renders a DEGRADED chip carrying the source + reason
  // — never $0, never a '—' that reads as real-zero.
  var SPEND_COLS = { spend: 1, cost_per_lead: 1, cost_per_qualified: 1, cost_per_set: 1,
                     cost_per_close: 1, cost_per_close_loaded: 1, ltgp_cac: 1 };
  function degradedEntryFor(colKey, list) {
    list = list || (state.board && state.board.degraded) || [];
    for (var i = 0; i < list.length; i++) {
      var m = String(list[i].metric || '');
      // Meta spend/entity failure poisons every spend-derived column
      if (SPEND_COLS[colKey] && m.indexOf('meta') === 0) return list[i];
      if (colKey === 'cost_per_close_loaded' && m === 'attribution_loaded_inputs') return list[i];
      if (colKey === 'ltgp_cac' && m === 'attribution_ltgp_cac') return list[i];
    }
    return null;
  }
  function degradedChip(d) {
    return '<span class="adx-degraded" title="' + esc((d.metric || 'source') + ': ' +
      (d.reason || 'upstream degraded')) + '">DEGRADED</span>';
  }
  function degradedStrip(list) {
    if (!list || !list.length) return '';
    return '<div class="adx-degraded-strip">⚠ DEGRADED SOURCE' + (list.length > 1 ? 'S' : '') +
      ' (' + list.length + '): ' + list.map(function (d) {
        return '<strong>' + esc(d.metric || 'source') + '</strong> — ' + esc(d.reason || '');
      }).join(' · ') + ' · affected cells are marked DEGRADED, not rendered as $0</div>';
  }

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
  // #133 D3 SOURCE MAP: Meta-sourced columns and hybrids (Meta ÷ engine) are
  // LABELLED on the header everywhere — no range view may render a Meta-sourced
  // metric as an unlabelled plain number (grep-asserted in tests).
  var SRC_META = { spend: 1 };            // pure Meta insights (impressions/clicks too, if shown)
  var SRC_HYBRID = { cost_per_lead: 1, cost_per_qualified: 1, cost_per_set: 1,
                     cost_per_close: 1, cost_per_close_loaded: 1, ltgp_cac: 1 };
  function srcChip(k) {
    if (SRC_META[k]) return ' <span class="adx-src-chip adx-src-meta" title="source: Meta insights — Meta’s number for this box, not engine-recomputable; degrades loudly if the Meta source dies">META</span>';
    if (SRC_HYBRID[k]) return ' <span class="adx-src-chip adx-src-hybrid" title="hybrid: Meta spend ÷ engine count — degrades if EITHER side degrades">HYB</span>';
    return '';
  }
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
  function writeUrl() {
    try {
      var qs = (state.range ? '?range=' + state.range : '?window=' + state.days) +
        '&clock=' + state.basis + '&market=' + state.market +
        '&sort=' + state.sort + '.' + (state.sortDir === -1 ? 'desc' : 'asc') +
        '&rows=' + state.rows;
      history.replaceState(null, '', qs);
    } catch (e) {}
  }
  function loadBoard(days, basis, market, range) {
    // Semantics: a non-null `days` is a STANDARD-window pick (clears any range);
    // a non-null `range` ('A..B') activates the date box; null/undefined args
    // keep current state (clock/market toggles preserve the active box).
    if (range != null) {
      state.range = range;
    } else if (days != null) {
      state.range = null;
      state.rangeLabel = null;
      state.days = days;
    }
    if (basis) state.basis = basis;
    if (market) state.market = market;
    if (!state.range) {
      state.windowLabel = { 30: 'Last 30 days', 60: 'Last 60 days',
                            90: 'Last 90 days', all: 'Maximum' }[state.days] ||
                          (state.days + 'd');
    } else {
      state.windowLabel = state.rangeLabel || 'Custom';
    }
    var token = ++state.reqToken;
    document.querySelectorAll('.adx-basis').forEach(function (b) {
      b.classList.toggle('active', b.dataset.basis === state.basis);
    });
    document.querySelectorAll('.adx-market').forEach(function (b) {
      b.classList.toggle('active', b.dataset.market === state.market);
    });
    syncPresetSelect();
    writeUrl();
    $('#adx-banner').innerHTML = '<span class="adx-skel">Loading ' +
      (state.range ? esc(state.range) : state.days + (state.days === 'all' ? '' : 'd')) +
      ' · ' + state.basis +
      (state.market !== 'all' ? ' · ' + state.market.toUpperCase() : '') + '…</span>';
    document.body.classList.add('adx-loading');
    clearTimeout(stalePoll);
    fetch('/ads/api/board?' + windowQS(), { credentials: 'same-origin' })
      .then(function (r) {
        if (r.ok) return r.json();
        return r.json().then(function (j) { return { _httpError: true, error: j.error }; })
                       .catch(function () { return null; });
      })
      .then(function (data) {
        if (token !== state.reqToken) return;              // latest wins — stale dropped
        document.body.classList.remove('adx-loading');
        if (!data) { $('#adx-banner').textContent = 'Engine unreachable — nothing rendered rather than stale numbers.'; return; }
        if (data._httpError) {       // the server's friendly range refusal, verbatim
          $('#adx-banner').innerHTML = '<span class="adx-range-err">' + esc(data.error || 'bad request') + '</span>';
          return;
        }
        if (!echoMatches(data)) {
          console.error('STALE-MIX GUARD: response (window/basis)', data.window, data.basis,
                        'does not match state', state.range || state.days, state.basis, '— discarded');
          return;
        }
        state.board = data;
        renderAll();
        if (data.stale) {           // a labelled rollup — poll for the fresh build
          stalePoll = setTimeout(function () { loadBoard(null); }, 8000);
        }
      })
      .catch(function () {
        if (token !== state.reqToken) return;
        document.body.classList.remove('adx-loading');
        $('#adx-banner').textContent = 'Board fetch failed — toggle a window to retry.';
      });
  }

  function echoMatches(data) {
    // the stale-mix guard, range-aware: a range response must echo the requested
    // box (a server-clamped end is legitimate ONLY when the clamp note says so)
    if (!data.window) return false;
    if ((data.basis && data.basis !== state.basis) ||
        (data.market && data.market !== state.market)) return false;
    if (state.range) {
      var parts = state.range.split('..');
      if (String(data.window.start) !== parts[0]) return false;
      return String(data.window.end) === (parts[1] || parts[0]) || !!data.range_note;
    }
    return data.window.days === expectedDays();
  }

  function windowStamp() {
    var w = state.board.window || {};
    if (state.range) {
      var lbl = w.start === w.end ? w.start : w.start + ' → ' + w.end;
      return (state.rangeLabel ? state.rangeLabel + ' · ' : '') + lbl;
    }
    var d = w.days;
    return d >= 3650 ? 'All time' : d + 'd';
  }
  function clockStamp() {
    return state.basis === 'activity' ? 'Activity' : 'Cohort';
  }
  // the card header ALWAYS renders the resolved state (#134):
  // "{Clock} · {label} · {start} → {end}" — the box is never implicit
  function headerLine() {
    var w = (state.board || {}).window || {};
    var span = w.start === w.end ? String(w.start || '') :
      String(w.start || '?') + ' → ' + String(w.end || '?');
    return clockStamp() + ' · ' + (state.windowLabel || '?') + ' · ' + span;
  }
  // the select mirrors the active state — the control DISPLAYS what governs
  function syncPresetSelect() {
    var sel = $('#adx-range-preset');
    if (!sel) return;
    var v;
    if (!state.range) {
      v = { 30: '30d', 60: '60d', 90: '90d', all: 'max' }[state.days] || 'custom';
    } else {
      v = { 'Today': 'today', 'Yesterday': 'yesterday', 'Last 7 days': '7d',
            'Last 14 days': '14d', 'This month': 'thismonth',
            'Last month': 'lastmonth' }[state.rangeLabel] || 'custom';
    }
    sel.value = v;
  }

  var levelChosen = false;   // the user's explicit pick beats the default
  function renderAll() {
    if (!levelChosen && state.board.ladder && state.board.ladder.default_level) {
      state.level = state.board.ladder.default_level;
    }
    renderBanner(); renderHeadline(); renderScorecard(); renderHygiene(); renderScoreboard(); renderRows(true);
    // #134: the resolved state, always — "{Clock} · {label} · {start} → {end}"
    $('#adx-table-window').textContent = '· ' + headerLine() +
      (state.gq ? ' · FILTERED VIEW (aggregates unchanged)' : '') +
      (state.market !== 'all' ? ' · market: ' + state.market.toUpperCase() : '');
  }

  function renderHygiene() {
    var h = state.board.hygiene;
    var sec = $('#adx-hygiene');
    if (!h) {
      // F5 family: a dead integrity sweep must not silently vanish the section
      sec.style.display = '';
      $('#adx-hygiene-body').innerHTML =
        '<div class="adx-degraded-strip">⚠ integrity/hygiene block unavailable this build — ' +
        'the close-integrity sweep did not return; treat agreement state as UNKNOWN, not clean</div>';
      return;
    }
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
      ['Launched + days running', 'Launched = the first day Meta recorded impressions for the ad (first delivery, #133) — never the created date (the object’s birthday, shown as secondary when it differs) and never the ad-set schedule (ad sets are reused). Days running = days with actual delivery; a paused ad does not accrue runtime.'],
      ['Sources', 'Spend/impressions carry the META chip — Meta’s own numbers for the box, not recomputable from the tracker. CPL and every C/* carry the HYB chip: Meta spend ÷ engine counts — they degrade if EITHER side degrades. Funnel counts (leads → closes) are engine-authoritative from the tracker and stay live when Meta dies.'],
      ['The date box + clock', 'The range picker sets a Sydney-day box and asks ONE of two questions: ACTIVITY (events that happened inside the box) or COHORT (what the box’s arrivals went on to become). The toggle beside the picker declares which; every label carries the active clock; the engine refuses cross-clock math (I11).'],
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
      '<div class="adx-head-tile"><div class="adx-head-num">' +
      (degradedEntryFor('spend') ? degradedChip(degradedEntryFor('spend')) : money(h.spend_total)) + '</div>' +
      '<div class="adx-head-label">SPEND</div><div class="adx-head-tiers">' +
      (degradedEntryFor('spend') ? 'Meta source degraded — see banner' : 'Meta engine, reconciled') + '</div></div>';
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

  function cohortIsYoung() {
    // a cohort view on a short/recent box carries the maturity note (#133 §2.2)
    var w = (state.board || {}).window || {};
    if (!w.end) return false;
    var ageDays = Math.round((new Date(sydToday()) - new Date(String(w.end))) / 864e5);
    return ageDays <= 21;
  }

  function renderBanner() {
    var b = state.board.scoreboard.banner || {};
    var fr = b.freshness || {};
    var qr = state.board.qualified_rule || {};
    $('#adx-banner').innerHTML = degradedStrip(state.board.degraded) +
      '<strong>' + (b.attribution_rate_pct != null ? b.attribution_rate_pct + '%' : '—') +
      '</strong> of window leads ad-attributed (' + (b.attributed_leads || 0) + '/' + (b.leads || 0) + ')' +
      ' · window <strong>' + windowStamp() + '</strong>' +
      ' · qualified = ≠DQ + revenue ≥ $' + Math.round((qr.floor_monthly || 20000) / 1000) + 'k/mo + form answered' +
      ' · contacts synced ' + esc(String(fr.contacts_synced || '').slice(11, 16) || '—') +
      ' · sheet mirror ~90s' +
      ' · <span class="adx-basis-label">' + esc(state.board.basis_label || state.basis) + '</span>' +
      (state.board.stale ? ' · <span class="adx-stale">showing the last rollup (' +
        Math.round((state.board.stale_age_s || 0) / 60) + 'm old' +
        (state.board.stale_reason ? ' · ' + esc(state.board.stale_reason) : '') +
        ') — refreshing…</span>' : '') +
      (state.board.range_note ? ' · <span class="adx-clock-note">' + esc(state.board.range_note) + '</span>' : '') +
      (state.range && state.basis === 'cohort' && cohortIsYoung()
        ? ' · <span class="adx-clock-note">young cohort — leads this recent are still maturing (closes lag weeks); the activity clock answers “what happened in this box”</span>' : '') +
      (!state.range && state.days === 30 && state.basis === 'cohort' ? ' · <span class="adx-guide">30d cohort: closes still landing — 60/90d is the honest read for close-based verdicts</span>' : '');
    if (!(b.leads)) {
      $('#adx-banner').innerHTML = degradedStrip(state.board.degraded) +
        'No leads in this ' + windowStamp() + ' window. ' +
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
      if (k === 'launch' || k === 'active_days') {
        // #133: launch sorts read the ONE engine lineage field (the same value
        // the hover card and dossier show) — never a client-side recompute
        av = (a.lineage || {})[k === 'launch' ? 'launch' : 'active_days'];
        bv = (b.lineage || {})[k === 'launch' ? 'launch' : 'active_days'];
        if (av == null && bv == null) return (b.spend || 0) - (a.spend || 0);
        if (av == null) return 1;
        if (bv == null) return -1;
        if (av < bv) return -dir;
        if (av > bv) return dir;
        return (b.spend || 0) - (a.spend || 0);
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
      return '<th data-sort="' + c.k + '" class="' + cls + '" title="' + esc(TIPS[c.k] || '') + '">' + c.label + srcChip(c.k) + '</th>';
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
          // F5: a degraded upstream renders DEGRADED on ad-tier rows — a dead
          // Meta token must never read as a real $0 spend / $0 CPL. Channel
          // rows keep their by-design '—' (no ads → no spend, not degradation).
          var dgd = (r.tier === 'ad' && (c.money || c.k === 'ltgp_cac')) ? degradedEntryFor(c.k) : null;
          if (dgd) return '<td' + drill + '>' + degradedChip(dgd) + '</td>';
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
  // #134 CONSULT DATETIME: the scheduled-for display (server-formatted by the
  // ONE formatter — this renders verbatim, zero client date math). Every state
  // is honest: a tracker-only set says so, a pending fetch says so, and a
  // cancelled appointment never appears as "the consult".
  function consultSlot(p) {
    var c = p.consult;
    if (!c) return '';
    if (c.state === 'scheduled') {
      return ' <span class="adx-consult' + (c.upcoming ? ' adx-consult-up' : '') +
        '" title="' + esc(c.provenance || '') + '">consult: <strong>' + esc(c.formatted) + '</strong>' +
        (c.tz_label ? ' <span class="adx-consult-tz" title="US-market lead — this time is Sydney local">' + esc(c.tz_label) + '</span>' : '') +
        (c.upcoming ? ' <span class="adx-consult-chip">upcoming</span>' : '') +
        (c.rebooked ? ' <span class="adx-consult-chip adx-consult-rebook" title="' + c.rebooked + ' cancelled/invalid appointment(s) in the chain — the KEPT one is shown">rebooked ×' + c.rebooked + '</span>' : '') +
        '</span>';
    }
    if (c.state === 'no_appointment') {
      return ' <span class="adx-consult adx-consult-none" title="an honesty chip — no time is fabricated for a tracker-only set">' + esc(c.note) + '</span>';
    }
    if (c.state === 'unfetched') {
      return ' <span class="adx-consult adx-consult-none" title="' + esc(c.note) + '">consult: fetch pending</span>';
    }
    if (c.state === 'tracker_only') {
      return ' <span class="adx-consult adx-consult-none">' + esc(c.note) + '</span>';
    }
    return '';
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
      (p.tracker_link ? ' <a class="adx-ghl" href="' + esc(p.tracker_link) + '" target="_blank" rel="noopener" title="Lead-to-Cash tracker (find the row by name — row anchors are unsafe under the clean view)">tracker ↗</a>' : '') +
      consultSlot(p) + '</div>' +
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

  // ── #133 LAUNCH LINEAGE HOVER: board-payload-fed (zero fetch — the <150ms
  // budget is structural), position:fixed (zero layout shift). The values ARE
  // the engine row's lineage field — identical to the dossier and the sorts.
  function daysBetween(a, b) {
    try { return Math.round(Math.abs(new Date(a) - new Date(b)) / 864e5); }
    catch (e) { return 0; }
  }
  function lineageCard(r) {
    var title = '<div class="adx-hover-title">' + esc(String(r.creative || '').slice(0, 60)) + '</div>';
    var lin = r.lineage;
    if (r.tier && r.tier !== 'ad') {
      return title + '<div class="adx-hover-line">channel row — no ad identity exists, so no launch date exists (not a data gap)</div>';
    }
    if (!lin) {
      return title + '<div class="adx-hover-line adx-hover-degraded">launch lineage unavailable — lineage engine returned nothing for this row (degraded, not zero)</div>';
    }
    if (lin.degraded) {
      return title + '<div class="adx-hover-line adx-hover-degraded">DEGRADED: ' + esc(lin.degraded) + '</div>';
    }
    var html = title;
    if (lin.never_delivered) {
      html += '<div class="adx-hover-line">never delivered — lifetime impressions 0 (spend without delivery is impossible; this ad simply never ran)</div>';
      return html;
    }
    html += '<div class="adx-hover-line">launched <span class="adx-hover-launch">' + esc(lin.launch || '?') + '</span>' +
      (lin.launch_approx ? ' <em>(on or before — lifetime probe pending)</em>' : '') +
      (lin.status ? ' · ' + esc(lin.status) : '') + '</div>';
    if (lin.active_days != null) {
      html += '<div class="adx-hover-line"><strong>' + lin.active_days + ' active day' +
        (lin.active_days === 1 ? '' : 's') + '</strong> running' +
        (lin.calendar_days != null && lin.calendar_days !== lin.active_days
          ? ' · ' + lin.calendar_days + ' calendar days since launch (gaps = paused)' : '') +
        (lin.last_delivery && !lin.delivered_recently
          ? ' · last delivered ' + esc(lin.last_delivery) : '') + '</div>';
    }
    // window-aware money off the SAME row the grid shows (F5 degradation honoured)
    var dgd = degradedEntryFor('spend');
    html += '<div class="adx-hover-line">' + clockStamp() + ' · ' + windowStamp() + ': ' +
      (dgd ? degradedChip(dgd) : ('spend ' + money(r.spend) +
        (r.cost_per_lead != null ? ' · CPL ' + money(r.cost_per_lead) : ''))) + '</div>';
    // created shown as SECONDARY, only when it materially differs (>1 day) —
    // created_time is the object's birthday, never "launched" (#133)
    if (lin.created_time && lin.launch && daysBetween(lin.created_time, lin.launch) > 1) {
      html += '<div class="adx-hover-line adx-prov">created ' + esc(lin.created_time) +
        ' (object created — not first delivery)</div>';
    }
    html += '<div class="adx-hover-line adx-prov">source: Meta insights (first-impression day; account-timezone Sydney days)</div>';
    return html;
  }
  var hoverTimer = null;
  function findLevelRow(key) {
    var rows = levelRows();
    for (var i = 0; i < rows.length; i++) if (rows[i].creative_key === key) return rows[i];
    return null;
  }
  function positionHover(e) {
    var el = $('#adx-hover');
    var x = e.clientX + 14, y = e.clientY + 12;
    var w = el.offsetWidth || 320, h = el.offsetHeight || 100;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - 10;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - 10;
    el.style.left = Math.max(4, x) + 'px';
    el.style.top = Math.max(4, y) + 'px';
  }
  function showHover(e, key) {
    var r = findLevelRow(key);
    var el = $('#adx-hover');
    if (!r || !el) return;
    el.innerHTML = lineageCard(r);
    el.style.display = '';
    positionHover(e);
  }
  function hideHover() {
    var el = $('#adx-hover');
    if (el) el.style.display = 'none';
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
    fetch('/ads/api/roster?' + windowQS() +
          '&level=' + encodeURIComponent(state.level) +
          '&key=' + encodeURIComponent(creativeKey) + '&metric=' + encodeURIComponent(kind),
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = note + '<div class="adx-roster-note">' + esc((d && d.error) || 'fetch failed') + '</div>'; return; }
        rosterState.people = d.people || [];
        rosterState.head = note +
          (d.stale ? '<div class="adx-roster-note adx-stale">served from the rollup (' +
            esc(d.stale_reason || '') + ') — a fresh build is warming</div>' : '') +
          (d.empty_reason ? '<div class="adx-roster-note">' + esc(d.empty_reason) + '</div>' : '');
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
  // #133: the dossier's full lineage — the three dates DISTINGUISHED (launch =
  // first delivery; created = the object's birthday; ad-set scheduled start =
  // context only, ad sets are reused), active vs calendar days, and the exact
  // delivery timeline (gaps = pauses; omitted where daily data was never
  // fetched — never interpolated).
  function timelineHtml(lin, days) {
    if (!days || !days.length || !lin || !lin.launch) return '';
    var set = {};
    days.forEach(function (d) { set[d] = 1; });
    var start = lin.launch, end = sydToday();
    var span = daysBetween(start, end) + 1;
    var step = span > 240 ? 7 : 1;
    var cells = '';
    for (var i = 0; i < span; i += step) {
      var on = false;
      for (var j = i; j < Math.min(i + step, span); j++) {
        if (set[isoShift(start, j)]) { on = true; break; }
      }
      cells += '<span class="adx-tl-day' + (on ? ' on' : '') + '"></span>';
    }
    return '<div class="adx-timeline">' + cells +
      '<span class="adx-tl-cap">' + esc(start) + ' → ' + esc(end) +
      ' · green = delivery' + (step > 1 ? ' (weekly buckets)' : '') +
      ' · gaps = paused / not delivering · exact days from Meta insights, never interpolated</span></div>';
  }
  function lineageSection(d) {
    if (d.tier && d.tier !== 'ad') return '';
    var lin = d.lineage;
    var head = '<div class="adx-dossier-sec"><h3>Launch lineage <span class="adx-h2-sub">launched = first delivery (#133) · source: Meta insights</span></h3>';
    if (!lin) {
      return head + '<div class="adx-roster-note">lineage unavailable for this creative — treat launch/runtime as UNKNOWN, not zero</div></div>';
    }
    if (lin.degraded) {
      return head + '<div class="adx-warnline">DEGRADED: ' + esc(lin.degraded) + '</div></div>';
    }
    if (lin.never_delivered) {
      return head + '<div class="adx-person-meta">never delivered — lifetime impressions 0</div></div>';
    }
    var id = d.identity || {};
    var lines = '<div class="adx-person-meta"><strong>launched ' + esc(lin.launch || '?') + '</strong>' +
      (lin.launch_approx ? ' <em>(on or before — the lifetime probe hasn’t pinned the exact day yet)</em>' : '') +
      ' — first day Meta recorded impressions</div>';
    var created = lin.created_time || (id.created_time ? String(id.created_time).slice(0, 10) : null);
    if (created) {
      var cdiff = lin.launch ? daysBetween(created, lin.launch) : 0;
      lines += '<div class="adx-person-meta">created ' + esc(created) +
        ' — the ad OBJECT’s birthday' +
        (cdiff >= 1 ? ' (' + cdiff + ' day' + (cdiff === 1 ? '' : 's') + ' before first delivery)'
                    : ' (same day as launch)') + '</div>';
    }
    if (lin.scheduled_start) {
      lines += '<div class="adx-person-meta">ad-set scheduled start ' + esc(lin.scheduled_start) +
        ' — the AD SET’s schedule; ad sets are reused here, so this is NOT this ad’s launch (context only)</div>';
    }
    if (lin.active_days != null) {
      lines += '<div class="adx-person-meta"><strong>' + lin.active_days + ' active delivery day' +
        (lin.active_days === 1 ? '' : 's') + '</strong>' +
        (lin.calendar_days != null ? ' vs ' + lin.calendar_days + ' calendar days since launch' +
          (lin.calendar_days !== lin.active_days ? ' — the difference is paused/not-delivering time' : '') : '') +
        (lin.last_delivery ? ' · last delivered ' + esc(lin.last_delivery) : '') +
        (lin.status ? ' · status ' + esc(lin.status) : '') + '</div>';
    }
    if (d.lineage_window_note) {
      lines += '<div class="adx-warnline">' + esc(d.lineage_window_note) + '</div>';
    }
    return head + lines + timelineHtml(lin, d.delivery_days) + '</div>';
  }

  function openDossier(creativeKey) {
    openDrill('Creative dossier · ' + windowStamp() + ' · ' + state.basis + ' clock',
              '<div class="adx-skel">Assembling the dossier…</div>');
    try { history.replaceState(null, '', location.search.replace(/&?dossier=[^&]*/, '') + '&dossier=' + encodeURIComponent(creativeKey)); } catch (e) {}
    fetch('/ads/api/dossier?' + windowQS() +
          '&creative=' + encodeURIComponent(creativeKey), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = '<div class="adx-roster-note">' + esc((d && d.error) || 'fetch failed') + '</div>'; return; }
        var id = d.identity || {};
        // F5: the dossier's money legs honour the same degradation contract
        function dmoney(colKey, v) {
          var dg = degradedEntryFor(colKey, d.degraded);
          return dg ? degradedChip(dg) : money(v);
        }
        function econRow(label, e) {
          if (!e) return '<div class="adx-dossier-econ"><strong>' + label + '</strong>: no leads in this scope (honest zero — not an error)</div>';
          return '<div class="adx-dossier-econ"><strong>' + label + '</strong>: ' +
            'leads ' + num(e.leads) + ' · qual ' + num(e.qualified) + ' · reached ' + num(e.reached) +
            ' · sets ' + num(e.sets) + ' · shows ' + num(e.shows) + ' · closes ' + num(e.closes) +
            ' · cash ' + money(e.cash) + ' · spend ' + dmoney('spend', e.spend) +
            ' · CPL ' + dmoney('cost_per_lead', e.cost_per_lead) + ' · C/Qual ' + dmoney('cost_per_qualified', e.cost_per_qualified) +
            ' · C/Set ' + dmoney('cost_per_set', e.cost_per_set) + ' · C/Close ' + dmoney('cost_per_close', e.cost_per_close) +
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
            // the deep view carries BOTH dates, labelled (#134): booked-on
            // (the windowing clock) and the scheduled-for consult (display)
            (v.booked_date ? ' · <span class="adx-prov" title="booked-on — the setter action; the Sets windowing clock (#128)">booked ' + esc(v.booked_date) + '</span>' : '') +
            consultSlot(v) +
            '</div>';
        }).join('');
        $('#adx-drill-body').innerHTML = degradedStrip(d.degraded) +
          (d.stale ? '<div class="adx-roster-note adx-stale">served from the rollup (' +
            esc(d.stale_reason || '') + ') — a fresh build is warming</div>' : '') +
          '<div class="adx-dossier-sec"><h3>Identity & delivery</h3>' +
          '<div class="adx-person-meta">' + esc(d.label) + ' · tier ' + esc(d.tier) +
          (d.campaigns && d.campaigns.length ? ' · ' + d.campaigns.map(esc).join(', ') : '') +
          (id.status ? ' · status ' + esc(id.status) : '') +
          (id.created_time ? ' · created ' + esc(String(id.created_time).slice(0, 10)) + ' <em>(' + esc(id.created_time_note || '') + ')</em>' : '') +
          (d.history ? ' · <span class="adx-prov">(archived history)</span>' : '') + '</div></div>' +
          (d.range_note ? '<div class="adx-clock-note">' + esc(d.range_note) + '</div>' : '') +
          lineageSection(d) +
          '<div class="adx-dossier-sec"><h3>Unit economics <span class="adx-h2-sub">one engine · min-n labels intact · clock: ' + esc(d.clock || d.basis || state.basis) + '</span></h3>' +
          econRow(windowStamp(), d.econ_window) + econRow('All time', d.econ_all_time) +
          (state.board.market_note ? '<div class="adx-market-note">' + esc(state.board.market_note) + '</div>' : '') + '</div>' +
          '<div class="adx-dossier-sec"><h3>Lead ledger <span class="adx-h2-sub">' + d.ledger_count + ' lead(s) · newest first · window-scoped (switch window to All for history)</span></h3>' +
          (ledger || '<div class="adx-roster-note">' + esc(d.ledger_empty_reason || 'no leads in this window for this creative — honest empty, not an error') + '</div>') + '</div>';
      })
      .catch(function () { $('#adx-drill-body').textContent = 'Dossier fetch failed.'; });
  }

  // F12 (audit): the ?roster= deep link is ATTACKER-CONTROLLABLE input. level and
  // metric are whitelisted client-side BEFORE any render, and every URL-derived
  // string is esc()'d into the drill title — the reflected-XSS vector is closed
  // at the boundary, before server validation can even be consulted.
  var VALID_LEVELS = { creative: 1, name: 1, batch: 1, campaign: 1, account: 1 };
  var VALID_METRICS = { leads: 1, qualified: 1, reached: 1, sets: 1, shows: 1, closes: 1,
                        earlier_closes: 1, earlier_sets: 1, earlier_shows: 1,
                        undated_sets: 1, shows_unverified: 1 };

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
    // the drill INHERITS the clicked cell's clock (I11) and states it in the header.
    // F12: metric/level arrive from the URL on deep links — whitelist + escape.
    if (!VALID_METRICS[metric] || !VALID_LEVELS[level]) {
      console.error('F12 guard: invalid roster spec discarded', level, metric);
      return;
    }
    openDrill(esc(String(label || key).slice(0, 50)) + ' · ' + esc(metric) + ' · ' + windowStamp() +
              ' · ' + state.basis + ' clock',
              '<div class="adx-skel">Loading the humans…</div>');
    var spec = 'level=' + encodeURIComponent(level) + '&key=' + encodeURIComponent(key) +
               '&metric=' + encodeURIComponent(metric);
    try { history.replaceState(null, '', location.search.replace(/&?roster=[^&]*/, '') +
      '&roster=' + encodeURIComponent(level + '~' + key + '~' + metric)); } catch (e) {}
    fetch('/ads/api/roster?' + windowQS() + '&' + spec,
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : r.json().then(function (j) { return j; }).catch(function () { return null; }); })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = '<div class="adx-roster-note">' + esc((d && d.error) || 'Roster fetch failed.') + '</div>'; return; }
        var head = degradedStrip(d.degraded) +
          (d.stale ? '<div class="adx-roster-note adx-stale">served from the rollup (' +
            Math.round((d.stale_age_s || 0) / 60) + 'm old · ' + esc(d.stale_reason || '') +
            ') — a fresh build is warming</div>' : '') +
          '<div class="adx-roster-note">' + esc(d.clock_note || '') + '</div>';
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
    // #133: URL-stated range + clock (?range=A..B&clock=activity) — shareable,
    // refresh-proof. The range is STRICTLY validated before any use (F12 class).
    var ckParam = (location.search.match(/[?&]clock=(cohort|activity)/) || [])[1];
    if (ckParam) { state.basis = ckParam; state.clockChosen = true; }
    var rgParam = (location.search.match(/[?&]range=([0-9.\-]{10,25})/) || [])[1];
    if (rgParam && RANGE_RE.test(rgParam)) {
      state.range = rgParam;
      if (!ckParam && !bParam) state.basis = 'activity';   // box default
    }
    document.querySelectorAll('.adx-basis').forEach(function (b) {
      b.addEventListener('click', function () {
        state.clockChosen = true;              // an explicit pick survives presets
        loadBoard(null, b.dataset.basis);      // clock flip keeps the active box
      });
    });
    var vParam = (location.search.match(/[?&]verdict=([^&]+)/) || [])[1];
    if (vParam) state.verdict = decodeURIComponent(vParam);
    var cParam = (location.search.match(/[?&]creative=([^&]+)/) || [])[1];
    if (cParam) state.creative = decodeURIComponent(cParam);
    // ── THE date control (#133/#134): ONE control, in the card header ────────
    // Short/recent boxes default ACTIVITY (Meta-native); Last 30/60/90 days and
    // Maximum are the ruled standard windows (cohort default; rollup-backed).
    // An explicit clock pick always wins over either default.
    function applyPreset(v) {
      var t = sydToday();
      var r = null, label = null;
      if (v === 'today') { r = t + '..' + t; label = 'Today'; }
      else if (v === 'yesterday') {
        r = isoShift(t, -1) + '..' + isoShift(t, -1); label = 'Yesterday';
      }
      else if (v === '7d') { r = isoShift(t, -6) + '..' + t; label = 'Last 7 days'; }
      else if (v === '14d') { r = isoShift(t, -13) + '..' + t; label = 'Last 14 days'; }
      else if (v === '30d' || v === '60d' || v === '90d') {
        $('#adx-range-custom').style.display = 'none';
        if (!state.clockChosen) state.basis = 'cohort';
        loadBoard(parseInt(v, 10));
        return;
      }
      else if (v === 'thismonth') { r = t.slice(0, 8) + '01..' + t; label = 'This month'; }
      else if (v === 'lastmonth') {
        var prevEnd = isoShift(t.slice(0, 8) + '01', -1);
        r = prevEnd.slice(0, 8) + '01..' + prevEnd; label = 'Last month';
      }
      else if (v === 'max') {
        $('#adx-range-custom').style.display = 'none';
        if (!state.clockChosen) state.basis = 'cohort';
        loadBoard('all');
        return;
      }
      else if (v === 'custom') {
        var c = $('#adx-range-custom');
        c.style.display = '';
        $('#adx-range-end').value = t;
        $('#adx-range-start').value = isoShift(t, -6);
        return;
      }
      if (r) {
        $('#adx-range-custom').style.display = 'none';
        state.rangeLabel = label;
        if (!state.clockChosen) state.basis = 'activity';
        loadBoard(null, null, null, r);
      }
    }
    var presetSel = $('#adx-range-preset');
    if (presetSel) {
      presetSel.addEventListener('change', function () {
        if (presetSel.value) applyPreset(presetSel.value);
      });
    }
    var applyBtn = $('#adx-range-apply');
    if (applyBtn) {
      applyBtn.addEventListener('click', function () {
        var s = $('#adx-range-start').value, e = $('#adx-range-end').value;
        var err = null;
        if (!s || !e) err = 'pick both dates';
        else if (s > e) err = 'start is after end — swap them';
        else if (s > sydToday()) err = 'starts in the future (Sydney) — nothing to show yet';
        var old = $('#adx-range .adx-range-err');
        if (old) old.remove();
        if (err) {
          applyBtn.insertAdjacentHTML('afterend', '<span class="adx-range-err">' + esc(err) + '</span>');
          return;
        }
        state.rangeLabel = 'Custom';
        if (!state.clockChosen) state.basis = 'activity';
        loadBoard(null, null, null, s + '..' + e);   // server re-validates + clamps
      });
    }
    // #133 hover wiring: any campaign/creative NAME cell shows the lineage card
    var sbEl = $('#adx-scoreboard');
    sbEl.addEventListener('mouseover', function (e) {
      var nameCell = e.target.closest('td.adx-name');
      var tr = e.target.closest('tr[data-key]');
      if (nameCell && tr && state.board) showHover(e, tr.dataset.key);
      else hideHover();
    });
    sbEl.addEventListener('mousemove', function (e) {
      if ($('#adx-hover').style.display !== 'none') positionHover(e);
    });
    sbEl.addEventListener('mouseleave', hideHover);
    document.addEventListener('click', hideHover);
    document.addEventListener('scroll', hideHover, true);

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
      b.addEventListener('click', function () { loadBoard(null, null, b.dataset.market); });
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
      fetch('/ads/api/roster?' + windowQS() + '&stage=leads&creative=' +
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
    if (state.range) loadBoard(null); else loadBoard(days);
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
