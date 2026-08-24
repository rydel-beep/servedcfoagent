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
                range: null, rangeLabel: null, clockChosen: false,
                // BOARD v2: view = table|board (URL-stated ?view=); status
                // filter chips + spend-band toggle apply on BOTH views; role
                // arrives from whoami (server enforces regardless).
                view: 'table', statusFilter: 'all', setFilter: 'all', role: null };

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
    status: 'LIVE = effective delivery, never the toggle alone. GREEN = delivering (recent impressions, daily archive). AMBER = enabled but not delivering (reason named where knowable). GREY = paused (the pausing layer named). Freshness-stamped; DEGRADED when Meta is unreachable.',
  };
  var COLS = [
    { k: 'creative', label: 'Creative' }, { k: 'status', label: 'Live' },
    { k: 'verdict', label: 'Verdict' },
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
        '&rows=' + state.rows +
        (state.view !== 'table' ? '&view=' + state.view : '') +
        (state.statusFilter !== 'all' ? '&status=' + state.statusFilter : '') +
        (state.setFilter !== 'all' ? '&set=' + state.setFilter : '');
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
    // RANGE FLOW: NON-BLOCKING HONEST LOADING. No dim, no pointer lock —
    // structure stays visible and interactive; the header claims the TARGET
    // state (pending-marked) and the numeric cells skeleton AT THE SAME
    // FRAME, so old-range numbers never sit under a new-range label.
    enterPending();
    $('#adx-banner').innerHTML = '<span class="adx-skel">Loading ' +
      esc(state.windowLabel || '') + ' · ' + state.basis +
      (state.market !== 'all' ? ' · ' + state.market.toUpperCase() : '') + '…</span>';
    clearTimeout(stalePoll);
    // RACE GUARD: superseded in-flight requests are CANCELLED, not just
    // discarded — reqToken remains the paint gate for anything that slips by.
    if (inflight) { try { inflight.abort(); } catch (e) {} }
    inflight = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    fetch('/ads/api/board?' + windowQS(),
          { credentials: 'same-origin', signal: inflight && inflight.signal })
      .then(function (r) {
        if (r.ok) return r.json();
        return r.json().then(function (j) { return { _httpError: true, error: j.error }; })
                       .catch(function () { return null; });
      })
      .then(function (data) {
        if (token !== state.reqToken) return;              // latest wins — stale dropped
        if (!data) {
          exitPendingToLastGood('Engine unreachable — nothing rendered rather than stale numbers.');
          return;
        }
        if (data._httpError) {       // the server's friendly range refusal, verbatim
          exitPendingToLastGood(null);
          $('#adx-banner').innerHTML = '<span class="adx-range-err">' + esc(data.error || 'bad request') + '</span>';
          return;
        }
        if (!echoMatches(data)) {
          console.error('STALE-MIX GUARD: response (window/basis)', data.window, data.basis,
                        'does not match state', state.range || state.days, state.basis, '— discarded');
          return;
        }
        state.board = data;
        renderAll();                 // rebuilds cells + drops the pending marks
        if (data.stale) {           // a labelled rollup — poll for the fresh build
          stalePoll = setTimeout(function () { loadBoard(null); }, 8000);
        }
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;      // superseded — the newer request owns the UI
        if (token !== state.reqToken) return;
        exitPendingToLastGood('Board fetch failed — pick any range to retry.');
      });
  }

  var inflight = null;
  function enterPending() {
    // the header claims the TARGET (pending-marked); numbers skeleton in the
    // same frame. Controls untouched — no blanket, no dim.
    var tw = $('#adx-table-window');
    if (tw) tw.textContent = '· ' + pendingHeaderLine() + ' · loading…';
    var sb = $('#adx-scoreboard');
    if (sb) sb.classList.add('adx-pending');
    var rowsT = $('#adx-rows');
    if (rowsT) rowsT.classList.add('adx-pending');
    var hl = $('#adx-headline');
    if (hl) hl.classList.add('adx-pending-head');
  }
  function clearPending() {
    var sb = $('#adx-scoreboard');
    if (sb) sb.classList.remove('adx-pending');
    var rowsT = $('#adx-rows');
    if (rowsT) rowsT.classList.remove('adx-pending');
    var hl = $('#adx-headline');
    if (hl) hl.classList.remove('adx-pending-head');
  }
  function pendingHeaderLine() {
    // TARGET state from the CONTROLS (the board hasn't arrived): range dates
    // are known exactly; a days-window's exact edges arrive with the data.
    var span = state.range ? state.range.replace('..', ' → ') : 'updating…';
    return clockStamp() + ' · ' + (state.windowLabel || '?') + ' · ' + span;
  }
  function exitPendingToLastGood(bannerMsg) {
    // fetch failed / refused: revert the CONTROLS + header to the last-good
    // board so the visible numbers and their label agree again — old numbers
    // never sit under the target label.
    clearPending();
    var b = state.board;
    if (b && b.window) {
      var w = b.window;
      state.basis = b.basis || state.basis;
      var std = { 30: 1, 60: 1, 90: 1 }[w.days];
      if (w.days >= 3650) {
        state.range = null; state.days = 'all';
      } else if (std && String(w.end) === sydToday()) {
        state.range = null; state.days = w.days;    // a trailing standard window
      } else if (w.start && w.end) {
        state.range = String(w.start) + '..' + String(w.end);
        state.rangeLabel = 'Custom';
      }
      state.windowLabel = state.range ? 'Custom' :
        ({ 30: 'Last 30 days', 60: 'Last 60 days', 90: 'Last 90 days',
           all: 'Maximum' }[state.days] || (state.days + 'd'));
      syncPresetSelect();
      writeUrl();
      renderAll();
    }
    if (bannerMsg) $('#adx-banner').textContent = bannerMsg;
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
    clearPending();          // data matching the header is here — skeletons off
    if (!levelChosen && state.board.ladder && state.board.ladder.default_level) {
      state.level = state.board.ladder.default_level;
    }
    renderBanner(); renderHeadline(); renderScorecard(); renderHygiene(); renderScoreboard(); renderRows(true);
    renderStatusBar(); applyView();
    if (state.view === 'board') renderBoard();
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
      ['The R-A2 strategy (review cycles)', 'Four standing ad sets run continuously — Broad video (no interest targeting), Targeted video, Graphics, Retargeting — mapped by Meta adset id on the strategy panel. Creatives share a set budget, so Meta\u2019s delivery allocation is itself a signal. REVIEW CYCLE: every 7\u20138 days each running creative comes DUE; the ritual is keep-or-pull. PULL CANDIDATES are PEER-RELATIVE within the creative\u2019s own ad set over the review window \u2014 zero leads at \u2265 set-median delivery share, CPL > 1.5\u00d7 set median (needs \u22653 leads \u2014 a 1-lead fluke never flags), or STARVED (<5% delivery share two cycles running \u2014 an allocation problem, not an expense problem; the flag names which signal fired). No absolute spend threshold exists; retargeting only ever compares against itself; the system flags, humans decide \u2014 nothing auto-pulls. DELIVERY SHARE = the creative\u2019s slice of its set\u2019s spend over the window (from the daily archive).'],
      ['Live status (the triad)', 'LIVE (green) = delivering — impressions within the freshness horizon per the daily-delivery archive, never the toggle alone. NOT DELIVERING (amber) = the ad itself is ENABLED but Meta isn’t delivering it — the reason is in the label (campaign paused / ad set paused / in review / billing / has issues / reason unknown); this is the dangerous middle state. PAUSED (grey) = parked at the ad’s own layer, deliberately. STATUS UNKNOWN = the Meta source is degraded — stated, never a stale green. Hover any status for the full detail + fetch time. Want just the live ads? The “Delivering” filter chip above the table does exactly that in one click.'],
      ['Intraday numbers', 'A window that includes TODAY shows Meta spend/impressions that are still moving — Meta restates recent days for ~72h. They render with the intraday note and firm up as days close. Funnel counts (tracker) are unaffected.'],
    ].map(function (d) {
      return '<div class="adx-def"><div class="adx-def-t">' + d[0] + '</div><div class="adx-def-b">' + d[1] + '</div></div>';
    }).join('');
  }

  // #140: the signed-vs-collected gap — signed value with collection still
  // outstanding is a REAL signal, shown, never collapsed into one number.
  function contractGap(h) {
    if (h.contract_total == null || h.cash_total == null) return '';
    var gap = Math.round(h.contract_total - h.cash_total);
    if (gap <= 0) return '';
    return '<div class="adx-money-gap">' + money(h.contract_total) + ' signed · ' +
      money(h.cash_total) + ' collected · <strong>' + money(gap) + ' outstanding</strong></div>';
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
      // CASH + CONTRACT side by side (#140): two DIFFERENT truths at different
      // trust levels — cash = reconciled (Stripe/Xero), contract = tracker
      // (owner-entered). Never swapped; each provenance-chipped; the gap is the
      // signal. Both drill to the closes behind them (every number is a door).
      '<div class="adx-head-tile adx-head-money">' +
      '<div class="adx-money-line"><span class="adx-head-num adx-door" data-headdrill="closes">' + money(h.cash_total) + '</span>' +
      ' <span class="adx-money-prov" title="banked + Stripe/Xero-reconciled">cash · reconciled</span></div>' +
      '<div class="adx-money-line"><span class="adx-head-num2 adx-door" data-headdrill="closes">' +
      (h.contract_total != null ? money(h.contract_total) : '—') +
      '</span> <span class="adx-money-prov adx-money-prov-tracker" title="signed value from the Lead-to-Cash tracker — owner-entered, NOT reconciled">contract · tracker</span></div>' +
      contractGap(h) +
      '<div class="adx-head-label">CASH COLLECTED · CONTRACT VALUE · ' + clockStamp() + '</div>' +
      (h.contract_missing ? '<div class="adx-money-missing adx-door" data-headdrill="contract_missing" title="closes with a blank Contract Value cell — click to fix at source (blank ≠ $0)">' +
        h.contract_missing + ' close' + (h.contract_missing === 1 ? '' : 's') + ' missing contract value</div>' : '') +
      '</div>' +
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
        (cmp.deltas.contract != null ? ' · contract ' + f(cmp.deltas.contract, 1) : '') +
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
      (state.board.spend_intraday_note ? ' · <span class="adx-intraday" title="' + esc(state.board.spend_intraday_note) + '">⏳ spend includes today — intraday, not final</span>' : '') +
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
      // Board v2: the kill cards are the Board's kill-lane computation —
      // clicking one deep-links to the Board (?view=board) at the card.
      var deep = f.kind === 'review_due'
        ? ' adx-flag-door" data-session="1' : '';
      return '<div class="adx-flag adx-sev' + f.severity + deep + '" data-window="' + windowStamp() + '">' +
        '<div class="adx-flag-head">' + (f.creative ? esc(f.creative.slice(0, 44)) : 'ACCOUNT') +
        '</div>' +
        '<div class="adx-flag-line">' + esc(f.headline) + '</div>' +
        '<div class="adx-flag-q">' + esc(f.question) +
        (deep ? ' <span class="adx-prov">→ board</span>' : '') + '</div></div>';
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
      if (k === 'status') {
        // the classifier's ordinal — desc = LIVE first, then NOT DELIVERING,
        // then PAUSED, unknown last; spend desc as the stable tiebreak
        av = statusRank(a.creative_key); bv = statusRank(b.creative_key);
        if (av !== bv) return dir === -1 ? bv - av : av - bv;
        return (b.spend || 0) - (a.spend || 0);
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

  // ── BOARD v2 · LIFECYCLE (Laws 1–4). This whole section is RENDER-ONLY:
  // lanes/status/rotation arrive computed from ads_lifecycle (one classifier);
  // stances arrive from the one discussion store. Zero board-local math. ─────
  function lifeBlock() { return (state.board && state.board.lifecycle) || {}; }
  function lifeCard(key) { return (lifeBlock().cards || {})[key] || null; }
  function stancesOf(key) { return (lifeBlock().stances || {})[key] || null; }

  var STATUS_META = {
    delivering: { cls: 'adx-st-green' },
    enabled_not_delivering: { cls: 'adx-st-amber' },
    paused: { cls: 'adx-st-grey' },
    unknown: { cls: 'adx-st-unknown' },
  };
  // STATUS CLARITY (ruled): every state renders its server-built LABEL —
  // "LIVE" / "NOT DELIVERING · {reason}" / "PAUSED" — no glyph needs
  // decoding. Hover = the full detail (reason, layer, last delivery,
  // status fetch time). The label text comes from the one classifier.
  function statusDot(card, compact, row) {
    if (!card || !card.status) {
      // labeled, never a bare dash: this row has no lifecycle record —
      // say so and say what it means
      return '<span class="adx-st adx-st-unknown" title="no lifecycle/status record for this row — the lifetime engine leg has no card for this key (usually a stale rollup refreshing, or a name-keyed creative with no resolved ad id); status unknowable until it lands">NO STATUS · no lifecycle record</span>';
    }
    var st = card.status;
    var m = STATUS_META[st.status] || STATUS_META.unknown;
    var lin = (row && row.lineage) || {};
    var tip = (st.reason || '') +
      (st.layer ? ' · layer: ' + st.layer : '') +
      (lin.last_delivery ? ' · last delivered ' + lin.last_delivery : '') +
      (st.as_of ? ' · status as of ' + st.as_of : '');
    var label = st.label || st.status;
    return '<span class="adx-st ' + m.cls + '" title="' + esc(tip) + '">' +
      '<span class="adx-st-dot"></span>' + (compact ? '' : ' ' + esc(label)) + '</span>';
  }
  // LIVE SORT (bug fix): the header was wired to sortRows but keyed on
  // r['status'] — a field that does not exist on engine rows, so every
  // comparison was null==null and the order never changed. The real key is
  // the classifier's ORDINAL (status.rank: LIVE 3 → NOT DELIVERING 2 →
  // PAUSED 1 → unknown 0) — engine-computed, view-read.
  function statusRank(key) {
    var c = lifeCard(key);
    return (c && c.status && typeof c.status.rank === 'number') ? c.status.rank : -1;
  }
  function statusMatches(key) {
    if (state.statusFilter === 'all') return true;
    var c = lifeCard(key);
    var s = c && c.status && c.status.status;
    if (state.statusFilter === 'delivering') return s === 'delivering';
    if (state.statusFilter === 'not_delivering') return s === 'enabled_not_delivering' || s === 'unknown';
    if (state.statusFilter === 'paused') return s === 'paused';
    return true;
  }
  function setMatches(key) {
    // R-A2 set filter: membership from the engine block's card.sets (mapped
    // Meta adset ids — the view never re-derives membership)
    if (state.setFilter === 'all') return true;
    var c = lifeCard(key);
    if (state.setFilter === 'unmapped') return !!(c && c.unmapped_set);
    return !!(c && (c.sets || []).indexOf(state.setFilter) >= 0);
  }
  function renderStatusBar() {
    var bar = $('#adx-status-bar');
    if (!bar) return;
    var lb = lifeBlock();
    if (lb.degraded && !(lb.cards && Object.keys(lb.cards).length)) {
      bar.style.display = '';
      $('#adx-status-chips').innerHTML = '<span class="adx-degraded" title="' + esc(lb.degraded) + '">STATUS DEGRADED</span>';
      $('#adx-set-chips').innerHTML = '';
      $('#adx-status-asof').textContent = '';
      return;
    }
    bar.style.display = '';
    var chips = [['all', 'All'], ['delivering', 'Delivering'],
                 ['not_delivering', 'Not delivering'], ['paused', 'Paused']];
    $('#adx-status-chips').innerHTML = chips.map(function (c) {
      return '<button class="adx-status-chip' + (state.statusFilter === c[0] ? ' active' : '') +
        '" data-sfilter="' + c[0] + '">' + c[1] + '</button>';
    }).join('');
    var sets = [['all', 'All'], ['broad_video', 'Broad'], ['targeted_video', 'Targeted'],
                ['graphics', 'Graphics'], ['retargeting', 'Retarget'], ['unmapped', 'Unmapped']];
    $('#adx-set-chips').innerHTML = '<span class="adx-band-label" title="the four standing ad sets (R-A2) — membership by Meta adset id">set:</span> ' +
      sets.map(function (b) {
        return '<button class="adx-status-chip' + (state.setFilter === b[0] ? ' active' : '') +
          '" data-sset="' + b[0] + '">' + b[1] + '</button>';
      }).join('');
    var asof = '';
    var anyKey = Object.keys(lb.cards || {})[0];
    var any = anyKey && lb.cards[anyKey];
    if (any && any.status && any.status.as_of) asof = 'status as of ' + any.status.as_of;
    $('#adx-status-asof').textContent = asof;
  }
  function applyView() {
    document.querySelectorAll('.adx-view').forEach(function (b) {
      b.classList.toggle('active', b.dataset.view === state.view);
    });
    var bp = $('#adx-board-panel'), tp = $('#adx-table-panel');
    if (bp) bp.style.display = state.view === 'board' ? '' : 'none';
    if (tp) tp.style.display = state.view === 'board' ? 'none' : '';
  }

  function stanceChip(key) {
    var s = stancesOf(key);
    if (!s || !s.counts) return '';
    var parts = [];
    ['kill', 'scale', 'hold'].forEach(function (k) {
      if (s.counts[k]) parts.push(s.counts[k] + ' ' + k);
    });
    if (!parts.length) return '';
    var who = Object.keys(s.by || {}).map(function (u) {
      return (s.display && s.display[u] || u) + ': ' + s.by[u];
    }).join(' · ');
    return '<span class="adx-stance-chip" title="team stances (latest per person) — opinions, never votes: ' +
      esc(who) + '">' + esc(parts.join(' · ')) + '</span>';
  }

  function decisionChip(card) {
    var d = card && card.decision;
    if (!d) return '';
    var verb = d.state === 'marked_to_scale' ? 'SCALE' : 'PULL';
    var preRa2 = d.pre_ra2 ? ' <span class="adx-prov" title="decided under the retired rotation ruling — history kept, never erased">pre-R-A2</span>' : '';
    var h = '<div class="adx-decision-chip' + (d.executed ? ' adx-decision-done' : '') + '">' +
      '<strong>' + verb + '</strong>' + preRa2 + ' — ' + esc(d.by_display || d.by) + ' · ' + esc(d.at) +
      ' · “' + esc((d.reason || '').slice(0, 120)) + '”';
    if (d.executed) {
      h += '<div class="adx-decision-conv">✓ ' + esc(d.convergence || 'executed') + '</div>';
    } else {
      h += '<div class="adx-decision-pending">action pending — ' +
        (d.state === 'marked_to_scale' ? 'scale' : 'pause') + ' it in Ads Manager' +
        (d.age_days >= 1 ? ' · <strong>marked ' + d.age_days + 'd ago by ' +
          esc(d.by_display || d.by) + ' — still ' +
          (card.status && card.status.status === 'delivering' ? 'delivering' : 'unexecuted') +
          '</strong>' : '') + '</div>';
    }
    if (d.below_min_n) {
      h += '<div class="adx-prov">recorded below the evidence threshold — a review-cycle call, not a verdict</div>';
    }
    return h + '</div>';
  }

  function reviewLine(card) {
    var rv = card && card.review;
    var setChips = ((card && card.sets) || []).map(function (r) {
      return '<span class="adx-set-chip adx-set-' + esc(r) + '">' + esc(r.replace('_video', '').replace('_', ' ')) + '</span>';
    }).join('') + (card && card.unmapped_set ? '<span class="adx-set-chip adx-set-unmapped" title="this creative\'s ad set is not mapped to a role — map it on the strategy panel">unmapped set</span>' : '');
    if (!rv) {
      return '<div class="adx-rot-line adx-prov" title="the review clock starts at FIRST DELIVERY — none recorded yet">review clock: unavailable (no first delivery recorded)</div>' +
        (setChips ? '<div class="adx-card-sets">' + setChips + '</div>' : '');
    }
    var pulls = ((card.pull_flags || {}).signals || []).map(function (sg) {
      return '<span class="adx-pull-sig adx-pull-' + esc(sg.signal) + '" title="' + esc(sg.detail) + '">' + esc(sg.signal.replace(/_/g, ' ')) + '</span>';
    }).join('');
    return '<div class="adx-rot-line" title="' + esc(rv.clock_note || '') + '">' +
      '⏱ ' + esc(rv.label) + (rv.due ? ' <span class="adx-due-chip">DUE</span>' : '') +
      (card.injected ? ' <span class="adx-injected-chip" title="new in a mapped set this cycle">injected</span>' : '') +
      '</div>' +
      (setChips ? '<div class="adx-card-sets">' + setChips + '</div>' : '') +
      (pulls ? '<div class="adx-card-pulls" title="peer-relative within this creative\'s ad set — a flag, never an auto-pull; humans decide">' + pulls + '</div>' : '');
  }

  function boardCardHtml(row, card) {
    var key = row.creative_key;
    var st = card && card.status || {};
    var accent = (STATUS_META[st.status] || STATUS_META.unknown).cls;
    var dn = (state.board.discussion_counts || {})[key] || 0;
    var lin = row.lineage || {};
    var dgd = degradedEntryFor('spend');
    var h = '<div class="adx-card ' + accent + '" draggable="true" data-key="' + esc(key) + '">' +
      '<div class="adx-card-head">' + statusDot(card, true, row) +
      '<span class="adx-card-name" title="open the dossier">' + esc(String(row.creative || '').slice(0, 46)) + '</span>' +
      (lin.preview_link ? ' <a class="adx-preview" href="' + esc(lin.preview_link) + '" target="_blank" rel="noopener">↗</a>' : '') +
      '</div>' +
      // every non-LIVE card states its label in words (no decoding a color)
      (st.status && st.status !== 'delivering'
        ? '<div class="adx-card-amber" title="' + esc((st.reason || '') + (st.as_of ? ' · status as of ' + st.as_of : '')) + '">' +
          (st.status === 'enabled_not_delivering' ? '⚠ ' : '') + esc(st.label || st.status) + '</div>' : '') +
      reviewLine(card) +
      // WINDOW-scoped funnel line — the SAME engine row the table renders,
      // labelled with the table's clock+window (two clocks, each named).
      '<div class="adx-card-funnel" title="window-scoped (' + esc(clockStamp()) + ' · ' + esc(windowStamp()) + ') — same numbers as the table row">' +
      num(row.leads) + ' leads · ' + num(row.sets) + ' sets · ' + num(row.closes) + ' closes' +
      ' <span class="adx-prov">' + esc(windowStamp()) + '</span></div>' +
      '<div class="adx-card-money">' +
      (dgd ? degradedChip(dgd) : ('spend ' + money(row.spend) +
        (row.cost_per_lead != null ? ' · CPL ' + money(row.cost_per_lead) : ''))) + '</div>' +
      '<div class="adx-card-badges">' + badge(row) + ' ' + stanceChip(key) +

      (card && card.disagreement ? ' <span class="adx-disagree" title="the human decision pins this card; the engine currently computes a different lane">' +
        esc(card.disagreement) + '</span>' : '') +
      '</div>' +
      decisionChip(card) +
      (card && card.archive_label ? '<div class="adx-prov">' + esc(card.archive_label) + '</div>' : '') +
      '<div class="adx-card-foot">' +
      '<button class="adx-card-btn adx-disc-open" data-danchor="' + esc(key) + '" data-dlabel="' +
      esc(String(row.creative || '').slice(0, 40)) + '">💬' + (dn || '+') + '</button>' +
      (!card || !card.decision || card.decision.executed
        ? (lifeCard(key) && (lifeCard(key).review || {}).due
            ? '<button class="adx-card-btn adx-keep-btn" data-mkey="' + esc(key) + '" title="reset the review clock — reason optional, encouraged">keep</button>' : '') +
          '<button class="adx-card-btn adx-move-btn" data-mkey="' + esc(key) + '" data-mto="pull">mark pull</button>' +
          '<button class="adx-card-btn adx-move-btn" data-mkey="' + esc(key) + '" data-mto="scale">mark scale</button>'
        : (state.role === 'owner'
            ? '<button class="adx-card-btn adx-rev-btn" data-mkey="' + esc(key) + '">reverse</button>' : '') +
          (card.decision.state === 'marked_to_scale'
            ? '<button class="adx-card-btn adx-exec-btn" data-mkey="' + esc(key) + '">confirm executed</button>' : '')) +
      '</div></div>';
    return h;
  }

  function renderBoard() {
    var lanesEl = $('#adx-board-lanes');
    if (!lanesEl) return;
    var lb = lifeBlock();
    var sub = $('#adx-board-sub');
    if (sub) {
      sub.textContent = '· ' + headerLine() + ' · review clock is per-creative, resets on review (labelled on cards)' +
        (lb.stale ? ' · lifetime leg from a rollup (refreshing)' : '');
    }
    if (lb.degraded && !(lb.cards && Object.keys(lb.cards).length)) {
      lanesEl.innerHTML = '<div class="adx-degraded-strip">⚠ ' + esc(lb.degraded) + '</div>';
      return;
    }
    var rows = (state.board.scoreboard.rows || []).filter(function (r) {
      return r.tier === 'ad' && statusMatches(r.creative_key) && setMatches(r.creative_key);
    });
    var byLane = {};
    rows.forEach(function (r) {
      var c = lifeCard(r.creative_key);
      var lane = (c && c.lane) || 'testing';
      (byLane[lane] = byLane[lane] || []).push({ row: r, card: c });
    });
    // lifetime-only cards (no window activity → not in the window rows) still
    // belong on the board: archive/testing entries from the lifecycle block
    // whose key has no window row render from the all-time lifecycle data only.
    var seen = {};
    rows.forEach(function (r) { seen[r.creative_key] = 1; });
    Object.keys(lb.cards || {}).forEach(function (key) {
      if (seen[key] || !statusMatches(key) || !setMatches(key)) return;
      var c = lb.cards[key];
      var pseudo = { creative_key: key, creative: (c.decision && c.decision.label) || key,
                     tier: 'ad', leads: null, sets: null, closes: null,
                     spend: (c.lifetime || {}).spend, cost_per_lead: null, lineage: {} };
      (byLane[c.lane] = byLane[c.lane] || []).push({ row: pseudo, card: c, quiet: true });
    });
    var order = lb.lanes_order || [];
    var labels = lb.lane_labels || {};
    var laneDesc = {
      running: 'in cycle (R-A2: review every ' + ((lb.rules || {}).review_cycle_days || 7) +
        '–' + ((lb.rules || {}).review_due_through || 8) + ' days) — campaigns never stop',
      due_for_review: 'the review clock hit day ' + ((lb.rules || {}).review_cycle_days || 7) +
        ' — bring to the Session; pull flags are PEER-RELATIVE within the ad set, never absolute',
      marked_to_pull: 'human decision recorded — awaiting Ads Manager; ages until Meta shows paused',
      watch: 'at evidence — the verdict layer is accumulating; review judgments stay provisional',
      scale_candidate: 'VERDICT-BACKED only (past min-n) — under R-A2 scale = keep + replicate',
      marked_to_scale: 'human decision recorded — converges on duplication, or confirm executed',
      archive: 'verified-in-Meta terminal states — collapsed, browsable, never deleted',
    };
    lanesEl.innerHTML = order.map(function (lane) {
      var items = byLane[lane] || [];
      var cards = items.map(function (it) { return boardCardHtml(it.row, it.card); }).join('') ||
        '<div class="adx-lane-empty">empty</div>';
      var inner = '<div class="adx-lane-head" title="' + esc(laneDesc[lane] || '') + '">' +
        esc(labels[lane] || lane) + ' <span class="adx-lane-n">' + items.length + '</span></div>' +
        '<div class="adx-lane-cards" data-lane="' + lane + '">' + cards + '</div>';
      if (lane === 'archive') {
        return '<details class="adx-lane adx-lane-archive"><summary>' + esc(labels[lane] || lane) +
          ' (' + items.length + ')</summary><div class="adx-lane-cards" data-lane="archive">' +
          cards + '</div></details>';
      }
      return '<div class="adx-lane" data-lanewrap="' + lane + '">' + inner + '</div>';
    }).join('');
  }

  // ── the MOVE dialog (Law 2 / R-B / R-C): meaning stated · reason MANDATORY ·
  // the team's opinions + stances IN FRONT of the decider · friction below
  // min-n. A drag/confirm records a decision — it does not control Meta. ─────
  var moveState = { key: null, to: null };
  function openMoveDialog(key, to) {
    moveState.key = key; moveState.to = to;
    var row = findLevelRow(key) || { creative: key };
    var card = lifeCard(key) || {};
    var verb = (to === 'pull' || to === 'kill') ? 'pause' : 'scale';
    var meaning = 'This records the decision and creates the human action: <strong>' +
      verb + ' “' + esc(String(row.creative || key).slice(0, 40)) + '” in Ads Manager</strong>. ' +
      'This board does not control Meta — the card converges when the next status sync sees Meta actually changed.';
    var friction = card.below_min_n
      ? '<label class="adx-friction"><input type="checkbox" id="adx-move-confirm"> ' +
        'below evidence threshold — this is a <strong>review-cycle call, not a verdict</strong>; tick to confirm</label>'
      : '';
    openDrill('Mark to ' + esc(to.toUpperCase()) + ' · ' + esc(String(row.creative || key).slice(0, 40)),
      '<div class="adx-move-meaning">' + meaning + '</div>' +
      (card.engine_why ? '<div class="adx-roster-note">engine: ' + esc(card.engine_why) + '</div>' : '') +
      '<div class="adx-move-reason"><textarea id="adx-move-reason" rows="2" maxlength="500" ' +
      'placeholder="reason (required — blank is rejected)"></textarea></div>' +
      friction +
      '<button id="adx-move-send" class="adx-range-apply">record the decision</button>' +
      '<span id="adx-move-err" class="adx-range-err"></span>' +
      '<div class="adx-dossier-sec"><h3>The team’s takes <span class="adx-h2-sub">stances are opinions — this move is the decision</span></h3>' +
      '<div id="adx-move-opinions"><span class="adx-skel">loading…</span></div></div>');
    var send = $('#adx-move-send');
    if (send) send.addEventListener('click', submitMove);
    // R-C: current opinions + stances for THIS card, in front of the decider
    fetch('/ads/api/discussion?creative=' + encodeURIComponent(key), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var box = $('#adx-move-opinions');
        if (!box) return;
        var s = stancesOf(key);
        var chip = s ? stanceChip(key) : '';
        var notes = ((d && d.notes) || []).slice(0, 6).map(function (n) {
          if (n.state === 'tombstone') return '';
          return '<div class="adx-disc-note"><div class="adx-disc-head"><strong>' +
            esc(n.author.display) + '</strong>' +
            (n.stance ? ' <span class="adx-stance-tag adx-stance-' + esc(n.stance) + '">' + esc(n.stance.toUpperCase()) + '</span>' : '') +
            ' · ' + esc(n.created) + '</div>' +
            (n.body ? '<div class="adx-disc-body">' + esc(n.body) + '</div>' : '<div class="adx-disc-body adx-prov">(stance only)</div>') + '</div>';
        }).join('');
        box.innerHTML = (chip ? '<div class="adx-move-stancesum">' + chip + '</div>' : '') +
          (notes || '<div class="adx-roster-note">no notes or stances on this card yet</div>');
      })
      .catch(function () {
        var box = $('#adx-move-opinions');
        if (box) box.innerHTML = '<div class="adx-roster-note">opinions unavailable</div>';
      });
  }
  function submitMove() {
    var reason = ($('#adx-move-reason') || {}).value || '';
    var errEl = $('#adx-move-err');
    var confirmEl = $('#adx-move-confirm');
    if (!reason.trim()) {
      if (errEl) errEl.textContent = 'a reason is required — blank is rejected';
      return;
    }
    fetch('/ads/api/lifecycle/move', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creative: moveState.key, to: moveState.to,
                             reason: reason.trim(),
                             confirm_below_min_n: !!(confirmEl && confirmEl.checked) })
    }).then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); })
      .then(function (res) {
        if (res.s === 409 && res.j && res.j.friction) {
          if (errEl) errEl.textContent = res.j.note + ' (tick the confirm box)';
          return;
        }
        if (res.j && res.j.error) { if (errEl) errEl.textContent = res.j.error; return; }
        closeDrill();
        loadBoard(null);          // the decision chip + feed item render on refresh
      })
      .catch(function () { if (errEl) errEl.textContent = 'move failed — try again'; });
  }
  function reverseDecision(key) {
    var reason = prompt('Reversal reason (required — journaled):');
    if (!reason || !reason.trim()) return;
    fetch('/ads/api/lifecycle/reverse', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creative: key, reason: reason.trim() })
    }).then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.error) { alert(d.error); return; } loadBoard(null); });
  }
  function confirmExecuted(key) {
    var note = prompt('Confirm executed in Ads Manager — optional note:');
    fetch('/ads/api/lifecycle/confirm-executed', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creative: key, note: note || null })
    }).then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.error) { alert(d.error); return; } loadBoard(null); });
  }

  // ── the STRATEGY panel (R-A2): config + THE SET MAPPING, journaled ────────
  function loadRulesPanel() {
    var body = $('#adx-rules-body');
    if (!body) return;
    body.innerHTML = '<span class="adx-skel">loading…</span>';
    fetch('/ads/api/strategy', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error) { body.innerHTML = esc((d && d.error) || 'unavailable'); return; }
        var st = d.strategy || {};
        var canEdit = state.role === 'owner' || state.role === 'coo';
        var journal = (d.journal || []).slice(-6).reverse().map(function (j) {
          return '<div class="adx-prov">' + esc(j.at) + ' · ' + esc(j.who) + ': ' +
            esc(j.key) + ' ' + esc(String(j.old)) + ' → ' + esc(String(j.new)) + '</div>';
        }).join('') || '<div class="adx-prov">no edits — the R-A2 defaults are live</div>';
        // THE SET MAPPING: live adset ids + names from the entity store —
        // ids are truth; the owner assigns roles here (journaled, reversible)
        var roles = d.set_roles || {};
        var live = d.live_adsets || {};
        var roleOpts = function (cur) {
          return ['', 'broad_video', 'targeted_video', 'graphics', 'retargeting']
            .map(function (r) {
              return '<option value="' + r + '"' + ((cur || '') === r ? ' selected' : '') + '>' +
                (r || 'unmapped') + '</option>'; }).join('');
        };
        var mapRows = Object.keys(live).sort(function (a, b) {
          return (live[b].ads || 0) - (live[a].ads || 0);
        }).slice(0, 20).map(function (sid) {
          return '<div class="adx-map-row"><span class="adx-map-name" title="adset id ' + esc(sid) + '">' +
            esc((live[sid].name || sid).slice(0, 44)) + ' <span class="adx-prov">(' + live[sid].ads + ' ads)</span></span>' +
            (canEdit ? '<select class="adx-map-role" data-mapsid="' + esc(sid) + '">' + roleOpts(roles[sid]) + '</select>'
                     : '<span class="adx-prov">' + esc(roles[sid] || 'unmapped') + '</span>') + '</div>';
        }).join('');
        body.innerHTML =
          '<div class="adx-rules-line">' + esc(d.ruling || '') + '</div>' +
          '<div class="adx-rules-form">' +
          'review cycle <input type="number" id="adx-rule-cycle" value="' + (+st.review_cycle_days || 7) + '" min="3" max="21"' + (canEdit ? '' : ' disabled') + '> days (due through ' +
          '<input type="number" id="adx-rule-due" value="' + (+st.review_due_through || 8) + '" min="3" max="28"' + (canEdit ? '' : ' disabled') + '>) · ' +
          'pull: CPL ×<input type="number" step="0.1" id="adx-rule-cplx" value="' + (+st.pull_cpl_mult || 1.5) + '" min="1.1" max="5"' + (canEdit ? '' : ' disabled') + '> set median · ' +
          'starved <<input type="number" id="adx-rule-starve" value="' + (+st.starved_share_pct || 5) + '" min="1" max="25"' + (canEdit ? '' : ' disabled') + '>% ×2 cycles' +
          (canEdit ? ' <button id="adx-rules-save" class="adx-range-apply">save (journaled)</button>'
                   : ' <span class="adx-prov">edits are owner/coo — these parameterize R-A2</span>') +
          '<span id="adx-rules-err" class="adx-range-err"></span></div>' +
          '<div class="adx-map-head">SET MAPPING — Meta ad set → role (ids are truth; unmapped renders honestly)</div>' +
          (mapRows || '<div class="adx-prov">no live ad sets in the entity store yet</div>') +
          '<div class="adx-rules-journal"><strong>edit journal</strong>' + journal + '</div>';
        var save = $('#adx-rules-save');
        if (save) save.addEventListener('click', function () {
          fetch('/ads/api/strategy', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ review_cycle_days: +($('#adx-rule-cycle').value),
                                   review_due_through: +($('#adx-rule-due').value),
                                   pull_cpl_mult: +($('#adx-rule-cplx').value),
                                   starved_share_pct: +($('#adx-rule-starve').value) })
          }).then(function (r) { return r.json(); })
            .then(function (res) {
              var errEl = $('#adx-rules-err');
              if (res && res.error) { if (errEl) errEl.textContent = res.error; return; }
              loadRulesPanel();
              loadBoard(null);        // lanes re-read the new thresholds
            });
        });
        body.querySelectorAll('.adx-map-role').forEach(function (sel) {
          sel.addEventListener('change', function () {
            fetch('/ads/api/strategy/map-set', {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ adset_id: sel.dataset.mapsid,
                                     role: sel.value || 'unmapped' })
            }).then(function (r) { return r.json(); })
              .then(function (res) {
                if (res && res.error) { alert(res.error); return; }
                loadBoard(null);      // set chips + lanes re-read the mapping
              });
          });
        });
      })
      .catch(function () { body.textContent = 'strategy unavailable'; });
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
    if (state.level === 'sets') { renderSetsView(); return; }
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
      // Law 3 filter chips apply on the TABLE too (creative level only —
      // groups have no single live status)
      if (state.level === 'creative' &&
          (!statusMatches(r.creative_key) || !setMatches(r.creative_key))) return false;
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
      var dn = (state.board.discussion_counts || {})[r.creative_key];
      var discBadge = dn ? ' <span class="adx-disc-badge adx-door" data-disc="' + esc(r.creative_key) +
        '" title="' + dn + ' open note(s) — click to read/reply">💬' + dn + '</span>' : '';
      return '<tr class="' + cls + '" data-key="' + esc(r.creative_key) + '" data-tier="' + r.tier + '" data-window="' + windowStamp() + '">' +
        '<td class="adx-name">' + (r.tier === 'ad' ? esc(r.creative) : '<em>' + esc(r.creative) + '</em>') + discBadge + '</td>' +
        // Law 3: the dot+label column — the SAME status classifier as the
        // Board's card accents (lifecycle block; groups carry no single status)
        (VCOLS.some(function (c) { return c.k === 'status'; })
          ? '<td class="adx-status-cell">' + (r.tier === 'ad' && state.level === 'creative'
              ? statusDot(lifeCard(r.creative_key), false, r)
              : '<span class="adx-prov" title="group/channel rows fold several ads — no single live status exists; open a creative row for its status">n/a (group)</span>') + '</td>' : '') +
        (VCOLS.some(function (c) { return c.k === 'verdict'; }) ? '<td>' + (r.tier === 'ad' ? badge(r) : '—') + '</td>' : '') +
        VCOLS.filter(function (c) { return c.k !== 'creative' && c.k !== 'verdict' && c.k !== 'status'; }).map(function (c) {
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
      // #140: contract (tracker) beside cash (reconciled) on the close row —
      // a blank contract cell reads "not recorded" (blank ≠ $0), never omitted.
      (p.close_date ? ' · <strong>closed ' + esc(p.close_date) + '</strong>' +
        ' · <span class="adx-money-prov-tracker" title="signed value — tracker, owner-entered">contract ' +
        (p.contract != null ? money(p.contract) : '<em>not recorded</em>') + '</span>' +
        (p.cash != null ? ' · <span title="banked — reconciled">cash ' + money(p.cash) + '</span>' : '') : '') + '</div>' +
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
    html += previewLine(lin);
    html += '<div class="adx-hover-line adx-prov">source: Meta insights (first-impression day; account-timezone Sydney days)</div>';
    return html;
  }
  // PREVIEW LINKS: the live shareable link, or the HONEST chip — never a dead link
  function previewLine(lin) {
    if (!lin) return '';
    if (lin.preview_state === 'link' && lin.preview_link) {
      return '<div class="adx-hover-line"><a class="adx-preview" href="' + esc(lin.preview_link) +
        '" target="_blank" rel="noopener" title="Meta ad preview — shareable link (needs any Facebook login to view)">Preview ↗</a></div>';
    }
    if (lin.preview_state === 'deleted') {
      return '<div class="adx-hover-line"><span class="adx-preview-chip">ad deleted · no preview available</span></div>';
    }
    return '';
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

  // ── DISCUSSION (#136): one store, many renders. Bodies are UNTRUSTED —
  // esc() at every render; identity comes from the session server-side (the
  // client sends no author, ever); stamps arrive server-computed.
  function stampChip(st) {
    if (!st) return '';
    var m = st.metrics || {};
    var bits = [];
    if (st.creative) bits.push(st.creative);
    if (st.clock) bits.push(st.clock);
    if (st.window) bits.push(st.window);
    if (m.cpl != null) bits.push('CPL ' + money(m.cpl));
    // display formatting only — String() concat, never arithmetic on metrics (I16)
    if (m.leads != null && st.creative == null) bits.push(String(m.leads).concat(' leads'));
    if (m.verdict) bits.push(m.verdict);
    if (st.degraded) bits.push('stamp degraded');
    if (!bits.length) return '';
    return '<span class="adx-disc-stamp" title="what the author was viewing at post time — server-captured">viewing: ' +
      bits.map(function (b) { return esc(String(b)); }).join(' · ') + '</span>';
  }
  function noteHtml(n, isReply) {
    var mine = state.me && n.author && n.author.user === state.me;
    if (n.state === 'tombstone') {
      return '<div class="adx-disc-note adx-disc-tomb' + (isReply ? ' adx-disc-reply' : '') + '">' +
        esc(n.tombstone_text || 'comment removed') + '</div>';
    }
    var h = '<div class="adx-disc-note' + (isReply ? ' adx-disc-reply' : '') +
      (n.state === 'resolved' ? ' adx-disc-resolved' : '') + '" data-note="' + n.id + '">' +
      '<div class="adx-disc-head"><strong>' + esc(n.author.display) + '</strong>' +
      (n.stance ? ' <span class="adx-stance-tag adx-stance-' + esc(n.stance) +
        (n.stance_superseded_by ? ' adx-stance-old" title="superseded by a newer stance from the same person' : '') +
        '">' + esc(n.stance.toUpperCase()) + (n.stance_superseded_by ? ' (superseded)' : '') + '</span>' : '') +
      ' · ' + esc(n.created) +
      (n.was_edited ? ' <span class="adx-prov">edited</span>' : '') + ' ' + stampChip(n.context_stamp) + '</div>' +
      (n.body ? '<div class="adx-disc-body">' + esc(n.body) + '</div>'
              : '<div class="adx-disc-body adx-prov">(stance only — no note)</div>');
    if (n.state === 'resolved') {
      h += '<div class="adx-disc-resline">resolved by ' + esc(n.resolved_by || '') +
        (n.resolution_note ? ' — ' + esc(n.resolution_note) : '') + '</div>';
    }
    h += '<div class="adx-disc-actions">' +
      (!isReply && n.state === 'active' ? '<button class="adx-disc-act" data-dreply="' + n.id + '">reply</button>' +
        '<button class="adx-disc-act" data-dresolve="' + n.id + '">resolve</button>' : '') +
      (mine && n.state === 'active' ? '<button class="adx-disc-act" data-dedit="' + n.id + '">edit</button>' +
        '<button class="adx-disc-act" data-ddelete="' + n.id + '">delete</button>' : '') + '</div>';
    return h + '</div>';
  }
  var discState = { anchor: null, label: null };
  function openDiscussion(anchor, label) {
    discState.anchor = anchor || null;
    discState.label = label || null;
    openDrill('Discussion · ' + esc(String(label || 'the board').slice(0, 40)),
              '<div class="adx-skel">Loading the notes…</div>');
    var q = anchor ? '?creative=' + encodeURIComponent(anchor) : '';
    fetch('/ads/api/discussion' + q, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error) { $('#adx-drill-body').innerHTML = '<div class="adx-roster-note">' + esc((d && d.error) || 'fetch failed') + '</div>'; return; }
        renderDiscussion(d.notes || []);
      })
      .catch(function () { $('#adx-drill-body').textContent = 'Discussion fetch failed.'; });
  }
  function renderDiscussion(notes) {
    // STANCE (R-C): an optional tag on the note — creative-anchored panels
    // only (a board-level stance has no card to summarize onto).
    var stanceSel = discState.anchor
      ? '<select id="adx-disc-stance" title="optional stance — an OPINION for the summary chip, never a vote; your newest stance supersedes your old one">' +
        '<option value="">no stance</option><option value="kill">Kill</option>' +
        '<option value="scale">Scale</option><option value="hold">Hold</option></select>'
      : '';
    var box = '<div class="adx-disc-post"><textarea id="adx-disc-input" rows="2" maxlength="2000" ' +
      'placeholder="add a note' + (discState.label ? ' on ' + esc(discState.label) : ' (board-level)') + '…"></textarea>' +
      stanceSel +
      '<button id="adx-disc-send" class="adx-range-apply">post</button>' +
      '<span class="adx-prov">Ctrl+Enter posts · your view (window + clock + live numbers) is stamped server-side' +
      (discState.anchor ? ' · a stance without text is allowed, text is better' : '') + '</span></div>';
    var body = notes.length
      ? notes.map(function (n) {
          return noteHtml(n, false) + (n.replies || []).map(function (rp) { return noteHtml(rp, true); }).join('');
        }).join('')
      : '<div class="adx-roster-note">no notes yet' + (discState.label ? ' on this creative' : '') + ' — the first observation starts the thread</div>';
    $('#adx-drill-body').innerHTML = box + body;
    var inp = $('#adx-disc-input');
    if (inp) {
      inp.focus();
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) postNote();
      });
    }
    var send = $('#adx-disc-send');
    if (send) send.addEventListener('click', postNote);
  }
  function postNote(replyTo) {
    var inp = $('#adx-disc-input');
    var body = inp && inp.value.trim();
    var stanceEl = $('#adx-disc-stance');
    var stance = (stanceEl && stanceEl.value) || null;
    if (!body && !stance) return;      // stance-only posts allowed (R-C)
    fetch('/ads/api/discussion?' + windowQS(), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: body || '', anchor: discState.anchor || 'board',
                             reply_to: replyTo || null, stance: stance })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.error) { alert(d.error); return; }
        openDiscussion(discState.anchor, discState.label);   // re-render fresh
        loadBoard(null);                                      // badge counts update
      });
  }
  function discAction(url, payload) {
    fetch(url, { method: 'POST', credentials: 'same-origin',
                 headers: { 'Content-Type': 'application/json' },
                 body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.error) { alert(d.error); return; }
        openDiscussion(discState.anchor, discState.label);
      });
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
    lines += previewLine(lin).replace('adx-hover-line', 'adx-person-meta');
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
        // #138: PER-LEG degradation scoping — each econ leg consults ITS OWN
        // degraded list (e.degraded), so a failed all-time pull degrades only
        // the all-time row while the window row stays live. A clamp truncation
        // renders a NAMED note (not a red badge).
        function dmoney(colKey, v, legDegraded) {
          var dg = degradedEntryFor(colKey, legDegraded || []);
          return dg ? degradedChip(dg) : money(v);
        }
        function econRow(label, e) {
          if (!e) return '<div class="adx-dossier-econ"><strong>' + label + '</strong>: no leads in this scope (honest zero — not an error)</div>';
          var ld = e.degraded || [];
          return '<div class="adx-dossier-econ"><strong>' + label + '</strong>: ' +
            'leads ' + num(e.leads) + ' · qual ' + num(e.qualified) + ' · reached ' + num(e.reached) +
            ' · sets ' + num(e.sets) + ' · shows ' + num(e.shows) + ' · closes ' + num(e.closes) +
            ' · cash ' + money(e.cash) + ' · spend ' + dmoney('spend', e.spend, ld) +
            ' · CPL ' + dmoney('cost_per_lead', e.cost_per_lead, ld) + ' · C/Qual ' + dmoney('cost_per_qualified', e.cost_per_qualified, ld) +
            ' · C/Set ' + dmoney('cost_per_set', e.cost_per_set, ld) + ' · C/Close ' + dmoney('cost_per_close', e.cost_per_close, ld) +
            (e.verdict ? ' · verdict ' + esc(e.verdict) : '') +
            (e.provisional ? ' <span class="adx-prov">' + esc(e.provisional.label || 'provisional') + '</span>' : '') +
            (e.clamp_note ? '<div class="adx-clamp-note">' + esc(e.clamp_note) + '</div>' : '') +
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
          (ledger || '<div class="adx-roster-note">' + esc(d.ledger_empty_reason || 'no leads in this window for this creative — honest empty, not an error') + '</div>') + '</div>' +
          '<div class="adx-dossier-sec"><h3>Notes (' +
          ((state.board.discussion_counts || {})[creativeKey] || 0) + ')</h3>' +
          '<button class="adx-disc-open adx-range-apply" data-danchor="' + esc(creativeKey) +
          '" data-dlabel="' + esc(String(d.label || '').slice(0, 40)) + '">open the discussion</button></div>';
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
                        undated_sets: 1, shows_unverified: 1, contract_missing: 1 };

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

  // ── THE REVIEW SESSION (R-A2 — the weekly ritual as a stepper) ─────────────
  var _rsState = { cohort: [], i: 0, sets: null };
  function openReviewSession() {
    var lb = lifeBlock();
    var cohort = Object.keys(lb.cards || {}).filter(function (k) {
      return lb.cards[k].lane === 'due_for_review';
    });
    if (!cohort.length) {
      openDrill('Review Session', '<div class="adx-roster-note">Nothing due for review — every running creative is inside its cycle. The ritual returns when clocks hit day ' + ((lb.rules || {}).review_cycle_days || 7) + '.</div>');
      return;
    }
    _rsState = { cohort: cohort, i: 0, sets: null };
    fetch('/ads/api/sets?' + windowQS(), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { _rsState.sets = d; renderReviewStep(); });
    openDrill('Review Session · ' + cohort.length + ' due',
              '<div class="adx-skel">Assembling the cohort…</div>');
  }
  function renderReviewStep() {
    var ks = _rsState.cohort;
    if (_rsState.i >= ks.length) {
      $('#adx-drill-body').innerHTML =
        '<div class="adx-good-note">Session complete — ' + ks.length + ' reviewed. The dated session record is saved (journal + /ads/api/review/sessions); pulled creatives converge as Meta shows them paused.</div>';
      loadBoard(null);
      return;
    }
    var key = ks[_rsState.i];
    var row = findLevelRow(key) || { creative: key };
    var card = lifeCard(key) || {};
    var rv = card.review || {};
    var g = (row.gates || row.n) ? (row.gates || {}) : {};
    var nLeads = (row.n || {}).leads != null ? row.n.leads : (g.n_leads || 0);
    var pulls = ((card.pull_flags || {}).signals || []).map(function (sg) {
      return '<div class="adx-pull-sig adx-pull-' + esc(sg.signal) + '" title="peer-relative within this set">' + esc(sg.detail) + '</div>';
    }).join('');
    // the peer table for this creative's set (from /ads/api/sets)
    var peers = '';
    var roles = card.sets || [];
    if (_rsState.sets && roles.length) {
      var role = roles[0];
      var rk = (((_rsState.sets.roles || {})[role] || {}).ranking) || [];
      peers = '<table class="adx-table" style="font-size:11px"><thead><tr><th>peer (' + esc(role) + ')</th><th>share</th><th>spend 7d</th><th>leads</th><th>CPL</th></tr></thead><tbody>' +
        rk.slice(0, 10).map(function (p) {
          return '<tr' + (p.creative_key === key ? ' class="adx-selected"' : '') + '><td>' + esc(String(p.label || '').slice(0, 32)) + '</td>' +
            '<td>' + p.delivery_share_pct + '%</td><td>' + money(p.window_spend) + '</td>' +
            '<td>' + (p.leads != null ? p.leads : '<span class="adx-prov" title="' + esc(p.spans_note || '') + '">n/a</span>') + '</td>' +
            '<td>' + (p.cpl != null ? money(p.cpl) : '—') + '</td></tr>';
        }).join('') + '</tbody></table>';
    }
    var html = '<div class="adx-rs-step">creative ' + (_rsState.i + 1) + ' of ' + ks.length + '</div>' +
      '<div class="adx-rs-name">' + esc(String(row.creative || key).slice(0, 60)) + '</div>' +
      '<div class="adx-rot-line">⏱ ' + esc(rv.label || '') + (card.injected ? ' · <span class="adx-injected-chip">injected this cycle</span>' : '') + '</div>' +
      '<div class="adx-person-meta">evidence so far: ' + nLeads + '/30 leads toward a verdict ' + badge(row) + '</div>' +
      (pulls ? '<div class="adx-card-pulls">' + pulls + '</div>'
             : '<div class="adx-prov">no pull flags — holding its own against set peers</div>') +
      peers +
      '<div class="adx-dossier-sec"><h3>Team takes</h3><div id="adx-rs-stances"><span class="adx-skel">loading…</span></div></div>' +
      '<div class="adx-rs-actions">' +
      '<textarea id="adx-rs-reason" rows="2" placeholder="reason (required for PULL; encouraged for KEEP)"></textarea>' +
      '<button class="adx-range-apply" id="adx-rs-keep">KEEP RUNNING (resets clock)</button>' +
      '<button class="adx-range-apply adx-rs-pullbtn" id="adx-rs-pull">PULL (mandatory reason)</button>' +
      '<span id="adx-rs-err" class="adx-range-err"></span></div>';
    $('#adx-drill-title').innerHTML = 'Review Session · ' + (ks.length - _rsState.i) + ' remaining';
    $('#adx-drill-body').innerHTML = html;
    fetch('/ads/api/discussion?creative=' + encodeURIComponent(key), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var box = $('#adx-rs-stances');
        if (!box) return;
        var chip = stanceChip(key);
        var notes = ((d && d.notes) || []).slice(0, 4).map(function (n) {
          if (n.state === 'tombstone') return '';
          return '<div class="adx-disc-note"><strong>' + esc(n.author.display) + '</strong>' +
            (n.stance ? ' <span class="adx-stance-tag adx-stance-' + esc(n.stance) + '">' + esc(n.stance.toUpperCase()) + '</span>' : '') +
            (n.body ? ': ' + esc(String(n.body).slice(0, 140)) : ' (stance only)') + '</div>';
        }).join('');
        box.innerHTML = (chip || '') + (notes || '<div class="adx-prov">no notes/stances on this card</div>');
      });
    $('#adx-rs-keep').addEventListener('click', function () {
      keepCreative(key, ($('#adx-rs-reason') || {}).value || null, function () {
        _rsState.i++; renderReviewStep();
      });
    });
    $('#adx-rs-pull').addEventListener('click', function () {
      var reason = (($('#adx-rs-reason') || {}).value || '').trim();
      var errEl = $('#adx-rs-err');
      if (!reason) { if (errEl) errEl.textContent = 'a PULL needs its reason — blank is rejected'; return; }
      fetch('/ads/api/lifecycle/move', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ creative: key, to: 'pull', reason: reason,
                               confirm_below_min_n: true, session: true })
      }).then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); })
        .then(function (res) {
          if (res.j && res.j.error) { if (errEl) errEl.textContent = res.j.error; return; }
          _rsState.i++; renderReviewStep();
        });
    });
  }
  function keepCreative(key, reason, done) {
    fetch('/ads/api/review/keep', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creative: key, reason: reason })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.error) { alert(d.error); return; }
        if (done) done(); else loadBoard(null);
      });
  }

  // ── THE SETS VIEW (R-A2 — the ad set as first-class unit) ─────────────────
  var _setsCache = null;
  function renderSetsView() {
    var thead = $('#adx-scoreboard thead'), tbody = $('#adx-scoreboard tbody');
    $('#adx-table-title').childNodes[0].textContent = 'Ad sets (R-A2) ';
    thead.innerHTML = '<tr><th>Set</th><th>Budget/day</th><th>Actual y\u2019day</th><th>7d avg</th>' +
      '<th>Leads</th><th>Sets</th><th>Closes</th><th>Status</th><th>Injected</th></tr>';
    tbody.innerHTML = '<tr><td colspan="9"><span class="adx-skel">Loading the sets…</span></td></tr>';
    fetch('/ads/api/sets?' + windowQS(), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.error) { tbody.innerHTML = '<tr><td colspan="9">' + esc((d && d.error) || 'sets unavailable') + '</td></tr>'; return; }
        _setsCache = d;
        var rows = '';
        Object.keys(d.roles || {}).forEach(function (role) {
          var v = d.roles[role];
          var budget = v.intended_daily ? '$' + v.intended_daily[0] + '–$' + v.intended_daily[1]
            : '<span class="adx-prov" title="no intended budget configured — set it via the strategy panel (edits journaled)">not set</span>';
          var st = v.status_rollup || {};
          var stTxt = ['delivering', 'enabled_not_delivering', 'paused'].map(function (k) {
            return st[k] ? st[k] + (k === 'delivering' ? ' live' : k === 'paused' ? ' paused' : ' amber') : null;
          }).filter(Boolean).join(' · ') || '—';
          rows += '<tr class="adx-set-row" data-setrole="' + esc(role) + '">' +
            '<td class="adx-name">' + esc(role.replace('_', ' ')) + ' <span class="adx-prov">(' + v.creatives + ' creatives · ' + (v.adset_names || []).filter(Boolean).slice(0, 2).map(esc).join(', ') + ')</span></td>' +
            '<td>' + budget + '</td>' +
            '<td' + (v.budget_drift ? ' class="adx-drift" title="' + esc(v.budget_drift) + '"' : '') + '>' + money(v.actual_yesterday) + (v.budget_drift ? ' ⚠' : '') + '</td>' +
            '<td>' + money(v.actual_daily_avg) + '</td>' +
            '<td>' + num(v.funnel_window.leads) + '</td><td>' + num(v.funnel_window.sets) + '</td><td>' + num(v.funnel_window.closes) + '</td>' +
            '<td>' + stTxt + '</td><td>' + (v.injected_this_cycle || '—') + '</td></tr>';
          // within-set peer ranking (expand row)
          rows += '<tr class="adx-set-rank"><td colspan="9"><details><summary>within-set ranking (' + (v.ranking || []).length + ') — delivery share is Meta\u2019s allocation signal</summary>' +
            '<table class="adx-table" style="font-size:11px"><thead><tr><th>creative</th><th>share</th><th>spend 7d</th><th>leads</th><th>CPL</th><th>verdict</th><th>flags</th></tr></thead><tbody>' +
            (v.ranking || []).map(function (p) {
              return '<tr><td>' + esc(String(p.label || '').slice(0, 40)) + (p.injected ? ' <span class="adx-injected-chip">injected</span>' : '') + (p.due ? ' <span class="adx-due-chip">DUE</span>' : '') + '</td>' +
                '<td>' + p.delivery_share_pct + '%</td><td>' + money(p.window_spend) + '</td>' +
                '<td>' + (p.leads != null ? p.leads : '<span class="adx-prov" title="' + esc(p.spans_note || '') + '">n/a</span>') + '</td>' +
                '<td>' + (p.cpl != null ? money(p.cpl) : '—') + '</td>' +
                '<td>' + esc(p.verdict || p.provisional || '—') + '</td>' +
                '<td>' + (p.pull_flags || []).map(function (f) { return '<span class="adx-pull-sig adx-pull-' + esc(f) + '">' + esc(f.replace(/_/g, ' ')) + '</span>'; }).join(' ') + '</td></tr>';
            }).join('') + '</tbody></table>' +
            (v.funnel_note ? '<div class="adx-prov">' + esc(v.funnel_note) + '</div>' : '') + '</details></td></tr>';
        });
        (d.unmapped || []).forEach(function (u) {
          rows += '<tr class="adx-set-row adx-set-unmapped-row"><td class="adx-name">UNMAPPED: ' + esc(u.adset_name || u.adset_id) +
            ' <span class="adx-prov">(' + u.ads + ' ads — map it on the strategy panel)</span></td>' +
            '<td>—</td><td colspan="2">' + money(u.window_spend) + ' over the window</td><td colspan="5">surfaced, never silently binned</td></tr>';
        });
        var part = d.partition || {};
        rows += '<tr class="adx-rowcut"><td colspan="9">' + esc(part.invariant || '') + ': ' +
          (part.ok ? '✓ holds' : '✗ VIOLATED') + ' (mapped ' + money(part.mapped) + ' + unmapped ' + money(part.unmapped) +
          ' + no-adset-record ' + money(part.no_adset_record) + ' = ' + money(part.total) + ')</td></tr>';
        tbody.innerHTML = rows;
      })
      .catch(function () { tbody.innerHTML = '<tr><td colspan="9">sets fetch failed</td></tr>'; });
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
    // #133 hover wiring: any campaign/creative NAME cell shows the lineage card.
    // The card is INTERACTIVE (Preview ↗ is clickable): leaving the table toward
    // the card keeps it open; leaving the card closes it.
    var sbEl = $('#adx-scoreboard');
    function _intoHover(e) {
      var rt = e.relatedTarget;
      return !!(rt && rt.closest && rt.closest('#adx-hover'));
    }
    sbEl.addEventListener('mouseover', function (e) {
      var nameCell = e.target.closest('td.adx-name');
      var tr = e.target.closest('tr[data-key]');
      if (nameCell && tr && state.board) showHover(e, tr.dataset.key);
      else if (!e.target.closest('#adx-hover')) hideHover();
    });
    sbEl.addEventListener('mousemove', function (e) {
      if ($('#adx-hover').style.display !== 'none' && !e.target.closest('#adx-hover')) positionHover(e);
    });
    sbEl.addEventListener('mouseleave', function (e) {
      if (!_intoHover(e)) hideHover();
    });
    $('#adx-hover').addEventListener('mouseleave', hideHover);
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#adx-hover a')) hideHover();
    });
    document.addEventListener('scroll', hideHover, true);

    // #140: the scoreboard money tiles are doors — cash/contract → the closes
    // roster (account level); the missing-contract note → the blank-contract
    // closes. Every number opens its people.
    $('#adx-headline').addEventListener('click', function (e) {
      var hd = e.target.closest('.adx-door[data-headdrill]');
      if (hd) {
        // ALL-TIERS door (sweep-2 fix): the money tiles total across tiers
        // (#140), so their door opens the all-tiers account cell — the old
        // __account__ (ad-ladder-only) door showed 0 people whenever the
        // window's closes were IG-DM/unattributed-tier.
        loadRoster('account', '__account_all__', 'Account · closes (all tiers)',
                   hd.dataset.headdrill, null);
      }
    });
    $('#adx-scoreboard').addEventListener('click', function (e) {
      var disc = e.target.closest('.adx-disc-badge[data-disc]');
      if (disc) {
        var drow = findLevelRow(disc.dataset.disc);
        openDiscussion(disc.dataset.disc, drow ? drow.creative : disc.dataset.disc);
        return;
      }
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
      // discussion actions (inside the drill — delegated)
      var dr = e.target.closest('.adx-disc-act');
      if (dr) {
        if (dr.dataset.dreply) {
          var rb = prompt('Reply:');
          if (rb && rb.trim()) {
            fetch('/ads/api/discussion?' + windowQS(), {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ body: rb.trim(), anchor: discState.anchor || 'board',
                                     reply_to: +dr.dataset.dreply })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                if (d && d.error) { alert(d.error); return; }
                openDiscussion(discState.anchor, discState.label);
              });
          }
        } else if (dr.dataset.dresolve) {
          var note = prompt('Resolution note (optional):') || null;
          discAction('/ads/api/discussion/resolve', { id: +dr.dataset.dresolve, note: note });
        } else if (dr.dataset.dedit) {
          var noteEl = dr.closest('.adx-disc-note');
          var cur = noteEl ? noteEl.querySelector('.adx-disc-body').textContent : '';
          var nb = prompt('Edit note:', cur);
          if (nb && nb.trim()) discAction('/ads/api/discussion/edit', { id: +dr.dataset.dedit, body: nb.trim() });
        } else if (dr.dataset.ddelete) {
          if (confirm('Remove this note? (a tombstone stays — nothing vanishes)')) {
            discAction('/ads/api/discussion/delete', { id: +dr.dataset.ddelete });
          }
        }
        return;
      }
      var dopen = e.target.closest('.adx-disc-open[data-danchor]');
      if (dopen) {
        openDiscussion(dopen.dataset.danchor === 'board' ? null : dopen.dataset.danchor,
                       dopen.dataset.dlabel || null);
        return;
      }
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
    // ── BOARD v2 wiring ──────────────────────────────────────────────────────
    var viewParam = (location.search.match(/[?&]view=(board|table)/) || [])[1];
    if (viewParam) state.view = viewParam;
    var sfParam = (location.search.match(/[?&]status=(delivering|not_delivering|paused)/) || [])[1];
    if (sfParam) state.statusFilter = sfParam;
    var setParam = (location.search.match(/[?&]set=(broad_video|targeted_video|graphics|retargeting|unmapped)/) || [])[1];
    if (setParam) state.setFilter = setParam;
    applyView();
    document.querySelectorAll('.adx-view').forEach(function (b) {
      b.addEventListener('click', function () {
        state.view = b.dataset.view;
        writeUrl(); applyView();
        if (state.board) { renderStatusBar(); if (state.view === 'board') renderBoard(); }
      });
    });
    $('#adx-status-bar').addEventListener('click', function (e) {
      var sf = e.target.closest('[data-sfilter]');
      var sb = e.target.closest('[data-sset]');
      if (!sf && !sb) return;
      if (sf) state.statusFilter = sf.dataset.sfilter;
      if (sb) state.setFilter = sb.dataset.sset;
      writeUrl(); renderStatusBar(); renderScoreboard();
      if (state.view === 'board') renderBoard();
    });
    var boardEl = $('#adx-board-lanes');
    if (boardEl) {
      boardEl.addEventListener('click', function (e) {
        var mv = e.target.closest('.adx-move-btn');
        if (mv) { openMoveDialog(mv.dataset.mkey, mv.dataset.mto); return; }
        var kp = e.target.closest('.adx-keep-btn');
        if (kp) { keepCreative(kp.dataset.mkey, null); return; }
        var rv = e.target.closest('.adx-rev-btn');
        if (rv) { reverseDecision(rv.dataset.mkey); return; }
        var ex = e.target.closest('.adx-exec-btn');
        if (ex) { confirmExecuted(ex.dataset.mkey); return; }
        if (e.target.closest('.adx-disc-open') || e.target.closest('a')) return;
        var cardEl = e.target.closest('.adx-card[data-key]');
        if (cardEl) openDossier(cardEl.dataset.key);   // click card → the dossier
      });
      // DRAG: a drop on MARKED TO KILL/SCALE opens the SAME dialog (Law 2 —
      // the drag itself decides nothing; the reasoned confirm does).
      var dragKey = null;
      boardEl.addEventListener('dragstart', function (e) {
        var c = e.target.closest('.adx-card[data-key]');
        dragKey = c ? c.dataset.key : null;
        if (dragKey && e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
      });
      boardEl.addEventListener('dragover', function (e) {
        var lane = e.target.closest('.adx-lane-cards[data-lane]');
        if (!lane || !dragKey) return;
        var ln = lane.dataset.lane;
        if (ln === 'marked_to_pull' || ln === 'marked_to_scale') {
          e.preventDefault();
          lane.classList.add('adx-lane-over');
        }
      });
      boardEl.addEventListener('dragleave', function (e) {
        var lane = e.target.closest('.adx-lane-cards');
        if (lane) lane.classList.remove('adx-lane-over');
      });
      boardEl.addEventListener('drop', function (e) {
        var lane = e.target.closest('.adx-lane-cards[data-lane]');
        if (!lane || !dragKey) return;
        e.preventDefault();
        lane.classList.remove('adx-lane-over');
        var ln = lane.dataset.lane;
        if (ln === 'marked_to_pull') openMoveDialog(dragKey, 'pull');
        else if (ln === 'marked_to_scale') openMoveDialog(dragKey, 'scale');
        dragKey = null;
      });
    }
    var rulesPanel = $('#adx-rules-panel');
    if (rulesPanel) rulesPanel.addEventListener('toggle', function () {
      if (rulesPanel.open) loadRulesPanel();
    });
    // the review-cycle flag card opens the Review Session
    $('#adx-flags').addEventListener('click', function (e) {
      var fd = e.target.closest('.adx-flag-door[data-session]');
      if (!fd) return;
      state.view = 'board';
      writeUrl(); applyView(); renderBoard();
      openReviewSession();
    });

    fetch('/dashboard/api/whoami', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (w) {
        if (w) {
          $('#adx-who').textContent = w.display || w.user || '';
          state.me = w.user || null;
          state.role = w.role || null;
          if (state.view === 'board' && state.board) renderBoard();  // owner buttons
        }
      });
    var dossierParam = (location.search.match(/[?&]dossier=([^&]+)/) || [])[1];
    var dealParam = (location.search.match(/[?&]deal=([^&]+)/) || [])[1];
    var rosterParam = (location.search.match(/[?&]roster=([^&]+)/) || [])[1];
    if (state.range) loadBoard(null); else loadBoard(days);
    if (/[?&]session=1/.test(location.search)) {
      setTimeout(function () {
        state.view = 'board'; applyView();
        if (state.board) { renderBoard(); openReviewSession(); }
      }, 900);
    }
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
