/* shell.js — the layer ON TOP of the server-rendered shell.
 *
 * Nothing here fills a value or draws a nav. The nav is already in the HTML;
 * this adds the command palette, the keyboard shortcuts, sortable/findable
 * tables, drawers, and URL state. Every block is guarded: if one throws, the
 * rest of the page keeps working and the error is reported as telemetry.
 */
(function () {
  'use strict';

  function boundary(name, fn) {
    try { fn(); } catch (e) {
      try {
        console.error('[shell:' + name + ']', e);
        navigator.sendBeacon && navigator.sendBeacon(
          '/dashboard/api/client-error',
          new Blob([JSON.stringify({
            where: 'shell:' + name, message: String(e && e.message || e),
            stack: String(e && e.stack || '').slice(0, 900),
            url: location.pathname
          })], { type: 'application/json' }));
      } catch (_) { /* telemetry must never itself break the page */ }
    }
  }

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ── ⌘K command palette ───────────────────────────────────────────── */
  boundary('palette', function () {
    var data = $('#s-palette-data');
    var box = $('#s-palette'), scrim = $('#s-palette-scrim');
    var input = $('#s-palette-input'), list = $('#s-palette-list');
    if (!data || !box || !input || !list) return;

    var targets = [];
    try { targets = JSON.parse(data.textContent || '[]'); } catch (e) { targets = []; }
    var shown = [], active = 0;

    function score(t, q) {
      var l = (t.label || '').toLowerCase();
      if (!q) return 1;
      var i = l.indexOf(q);
      if (i === 0) return 100 - l.length * 0.01;
      if (i > 0) return 50 - i;
      // subsequence match, so "trv" finds "How we're travelling"
      var j = 0;
      for (var k = 0; k < l.length && j < q.length; k++) if (l[k] === q[j]) j++;
      return j === q.length ? 10 : -1;
    }

    function render() {
      var q = (input.value || '').trim().toLowerCase();
      shown = targets.map(function (t) { return { t: t, s: score(t, q) }; })
        .filter(function (x) { return x.s >= 0; })
        .sort(function (a, b) { return b.s - a.s; })
        .slice(0, 40).map(function (x) { return x.t; });
      if (q) {
        shown.push({ kind: 'ask', label: 'Ask EDITH: “' + input.value.trim() + '”',
                     href: null, hint: 'opens the chat with this question' });
      }
      active = 0;
      if (!shown.length) {
        list.innerHTML = '<li class="s-palette-empty">Nothing matches that.</li>';
        return;
      }
      list.innerHTML = shown.map(function (t, i) {
        return '<li class="s-palette-item' + (i === 0 ? ' is-active' : '') +
          '" role="option" data-i="' + i + '">' +
          '<span class="s-palette-kind">' + t.kind + '</span>' +
          '<span>' + (t.label || '').replace(/</g, '&lt;') + '</span>' +
          (t.hint ? '<span class="s-muted" style="margin-left:auto">' + t.hint + '</span>' : '') +
          '</li>';
      }).join('');
    }

    function open() {
      box.hidden = false; scrim.hidden = false;
      box.classList.add('is-open'); scrim.classList.add('is-open');
      input.value = ''; render(); input.focus();
    }
    function close() {
      box.classList.remove('is-open'); scrim.classList.remove('is-open');
      box.hidden = true; scrim.hidden = true;
    }
    function choose(i) {
      var t = shown[i];
      if (!t) return;
      if (t.kind === 'ask') {
        close();
        var ask = input.value.trim();
        var chat = $('#btn-chat-toggle');
        if (chat) {
          chat.click();
          var ta = $('#chat-input');
          if (ta) { ta.value = ask; ta.focus(); }
        } else {
          location.href = '/dashboard/today?ask=' + encodeURIComponent(ask);
        }
        return;
      }
      location.href = t.href;
    }
    function move(d) {
      var items = $$('.s-palette-item', list);
      if (!items.length) return;
      items[active] && items[active].classList.remove('is-active');
      active = (active + d + items.length) % items.length;
      items[active].classList.add('is-active');
      items[active].scrollIntoView({ block: 'nearest' });
    }

    var openBtn = $('#s-palette-open');
    if (openBtn) openBtn.addEventListener('click', open);
    scrim.addEventListener('click', close);
    input.addEventListener('input', render);
    list.addEventListener('click', function (e) {
      var li = e.target.closest('.s-palette-item');
      if (li) choose(parseInt(li.dataset.i, 10));
    });
    document.addEventListener('keydown', function (e) {
      var isOpen = box.classList.contains('is-open');
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault(); isOpen ? close() : open(); return;
      }
      if (!isOpen) return;
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') { e.preventDefault(); choose(active); }
    });
  });

  /* ── keyboard shortcuts — single keys, never while typing ─────────── */
  boundary('shortcuts', function () {
    var GO = { t: '/dashboard/today', a: '/ads', s: '/dashboard/sales',
               m: '/dashboard/view/cash', p: '/dashboard/scale',
               d: '/dashboard/view/decisions', y: '/dashboard/view/system' };
    document.addEventListener('keydown', function (e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      var el = document.activeElement;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
                 el.isContentEditable || el.tagName === 'SELECT')) return;
      if (e.key === '?') {
        e.preventDefault();
        alert('Shortcuts\n\n⌘K  jump to anything\ng then t/a/s/m/p/d/y  go to ' +
              'Today, Ads, Sales, Money, Plan, Decisions, System\n/  find in table\n' +
              'Esc  close');
        return;
      }
      if (e.key === 'g') { window.__sGo = true; setTimeout(function () { window.__sGo = false; }, 900); return; }
      if (window.__sGo && GO[e.key]) { e.preventDefault(); location.href = GO[e.key]; return; }
      if (e.key === '/') {
        var f = $('.s-find');
        if (f) { e.preventDefault(); f.focus(); f.select(); }
      }
    });
  });

  /* ── tables: sort + find, with URL state ──────────────────────────── */
  boundary('tables', function () {
    $$('.s-table').forEach(function (table) {
      var tbody = table.tBodies[0];
      if (!tbody) return;

      function cellValue(tr, i) {
        var td = tr.cells[i];
        if (!td) return '';
        var raw = td.getAttribute('data-value');
        if (raw !== null && raw !== '') {
          var n = parseFloat(raw);
          return isNaN(n) ? raw : n;
        }
        var txt = (td.innerText || '').trim();
        var num = parseFloat(txt.replace(/[$,%×\s]/g, ''));
        return (txt && !isNaN(num)) ? num : txt.toLowerCase();
      }

      $$('thead th', table).forEach(function (th, i) {
        if (th.getAttribute('data-nosort') !== null) return;
        th.setAttribute('tabindex', '0');
        function sort() {
          var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
          $$('thead th', table).forEach(function (o) { o.removeAttribute('aria-sort'); });
          th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
          var rows = $$('tr', tbody);
          rows.sort(function (a, b) {
            var x = cellValue(a, i), y = cellValue(b, i);
            if (x === y) return 0;
            return (x > y ? 1 : -1) * dir;
          });
          rows.forEach(function (r) { tbody.appendChild(r); });
          setParam('sort', i + (dir === 1 ? 'a' : 'd'));
        }
        th.addEventListener('click', sort);
        th.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); }
        });
      });

      var find = table.closest('.s-panel') && $('.s-find', table.closest('.s-panel'));
      if (find) {
        find.addEventListener('input', function () {
          var q = (find.value || '').trim().toLowerCase();
          $$('tr', tbody).forEach(function (tr) {
            tr.style.display = (!q || (tr.innerText || '').toLowerCase().indexOf(q) >= 0)
              ? '' : 'none';
          });
          setParam('find', q || null);
        });
      }
    });
  });

  /* ── URL state: every view is a link you can send someone ─────────── */
  function setParam(k, v) {
    try {
      var u = new URL(location.href);
      if (v === null || v === undefined || v === '') u.searchParams.delete(k);
      else u.searchParams.set(k, v);
      history.replaceState(null, '', u.toString());
    } catch (e) { /* URL state is a convenience, never a requirement */ }
  }

  boundary('restore-url-state', function () {
    var u = new URL(location.href);
    var find = u.searchParams.get('find');
    if (find) {
      var f = $('.s-find');
      if (f) { f.value = find; f.dispatchEvent(new Event('input')); }
    }
    var sort = u.searchParams.get('sort');
    if (sort) {
      var i = parseInt(sort, 10);
      var th = $$('.s-table thead th')[i];
      if (th) {
        if (sort.slice(-1) === 'd') th.setAttribute('aria-sort', 'ascending');
        th.click();
      }
    }
    var ask = u.searchParams.get('ask');
    if (ask) {
      var chat = $('#btn-chat-toggle');
      if (chat) {
        chat.click();
        var ta = $('#chat-input');
        if (ta) { ta.value = ask; ta.focus(); }
      }
    }
  });

  /* ── drawers ──────────────────────────────────────────────────────── */
  boundary('drawers', function () {
    document.addEventListener('click', function (e) {
      var opener = e.target.closest('[data-drawer]');
      if (opener) {
        var d = document.getElementById(opener.getAttribute('data-drawer'));
        if (d) { d.classList.add('is-open'); d.removeAttribute('hidden'); }
        return;
      }
      if (e.target.closest('[data-drawer-close]')) {
        var open = $('.s-drawer.is-open');
        if (open) { open.classList.remove('is-open'); open.setAttribute('hidden', ''); }
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var open = $('.s-drawer.is-open');
      if (open) { open.classList.remove('is-open'); open.setAttribute('hidden', ''); }
    });
  });

  /* ── sparklines: drawn from data the server already rendered ──────── */
  boundary('sparklines', function () {
    $$('svg.s-trend[data-series]').forEach(function (svg) {
      var pts;
      try { pts = JSON.parse(svg.getAttribute('data-series') || '[]'); } catch (e) { return; }
      pts = pts.filter(function (p) { return typeof p === 'number' && isFinite(p); });
      if (pts.length < 2) return;
      var w = 100, h = 30, pad = 2;
      var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
      var span = (hi - lo) || 1;
      var d = pts.map(function (v, i) {
        var x = pad + (i / (pts.length - 1)) * (w - pad * 2);
        var y = h - pad - ((v - lo) / span) * (h - pad * 2);
        return (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
      }).join(' ');
      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      svg.setAttribute('preserveAspectRatio', 'none');
      svg.innerHTML = '<path d="' + d + '" fill="none" stroke="currentColor" ' +
        'stroke-width="1.5" vector-effect="non-scaling-stroke" opacity="0.75"/>';
    });
  });
})();
