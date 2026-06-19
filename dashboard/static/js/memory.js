/* memory.js — EDITH Memory management UI (Phase 5). Talks to /dashboard/memory/api/* */
(function () {
  'use strict';
  var B = '/dashboard/memory/api';
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function fmtDate(s) { if (!s) return ''; try { return new Date(s).toLocaleString(); } catch (e) { return s; } }

  async function jget(url) { var r = await fetch(url); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }
  async function jsend(url, method, body) {
    var r = await fetch(url, { method: method, headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined });
    return r.json().catch(function () { return {}; });
  }

  function banner(status) {
    var el = $('banner');
    if (status && status.online) { el.className = 'banner on'; el.textContent = '● Persistent memory online'; }
    else { el.className = 'banner off'; el.textContent = '● Persistent memory OFFLINE — running on in-session memory' + (status && status.reason ? ' (' + status.reason + ')' : ''); }
  }

  // ── Facts ──────────────────────────────────────────────────────────
  async function loadFacts() {
    var inactive = $('show-inactive').checked ? '?inactive=1' : '';
    var data = await jget(B + '/facts' + inactive);
    var host = $('facts'); host.innerHTML = '';
    var cats = Object.keys(data.by_category || {});
    if (!cats.length) { host.innerHTML = '<div class="empty">No distilled facts yet. EDITH builds these from conversations.</div>'; return; }
    cats.sort();
    cats.forEach(function (cat) {
      data.by_category[cat].forEach(function (f) { host.appendChild(factCard(f)); });
    });
  }

  function factCard(f) {
    var card = document.createElement('div'); card.className = 'card';
    var dim = f.active ? '' : 'opacity:.5;';
    card.style.cssText = dim;
    card.innerHTML =
      '<div class="row">' +
        '<div class="fact-text" data-id="' + f.id + '">' +
          '<span class="pill ' + esc(f.category) + '">' + esc(f.category) + '</span>' +
          '<span class="ft">' + esc(f.fact) + '</span>' +
        '</div>' +
        '<div class="btns">' +
          '<button class="edit">Edit</button>' +
          '<button class="toggle">' + (f.active ? 'Deactivate' : 'Activate') + '</button>' +
          '<button class="del danger">Delete</button>' +
        '</div>' +
      '</div>' +
      '<div class="meta">weight ' + (f.weight != null ? f.weight.toFixed(1) : '?') +
        ' · last recalled ' + fmtDate(f.last_referenced_at) + (f.active ? '' : ' · INACTIVE') + '</div>';

    var ftSpan = card.querySelector('.ft');
    card.querySelector('.edit').onclick = function () {
      if (ftSpan.isContentEditable) {
        ftSpan.contentEditable = 'false'; ftSpan.parentElement.classList.remove('fact-text');
        jsend(B + '/facts/' + f.id, 'POST', { fact: ftSpan.textContent.trim() }).then(load);
      } else {
        ftSpan.contentEditable = 'true'; ftSpan.parentElement.classList.add('fact-text'); ftSpan.focus();
        this.textContent = 'Save';
      }
    };
    card.querySelector('.toggle').onclick = function () {
      jsend(B + '/facts/' + f.id, 'POST', { active: !f.active }).then(load);
    };
    card.querySelector('.del').onclick = function () {
      if (confirm('Delete this fact permanently?')) jsend(B + '/facts/' + f.id, 'DELETE').then(load);
    };
    return card;
  }

  // ── Conversations ──────────────────────────────────────────────────
  async function loadConversations() {
    var arch = $('show-archived').checked ? '?archived=1' : '';
    var data = await jget(B + '/conversations' + arch);
    banner(data.memory);
    var host = $('conversations'); host.innerHTML = '';
    if (!data.conversations || !data.conversations.length) {
      host.innerHTML = '<div class="empty">No conversations stored yet.</div>'; return;
    }
    data.conversations.forEach(function (c) { host.appendChild(convCard(c)); });
  }

  function convCard(c) {
    var card = document.createElement('div'); card.className = 'card';
    var title = c.title || ('Conversation #' + c.id);
    card.innerHTML =
      '<div class="row">' +
        '<div><b>' + esc(title) + '</b> <span class="pill">' + esc(c.channel) + '</span>' +
          (c.archived ? '<span class="pill" style="color:#f0b8a6">archived</span>' : '') +
          '<div class="meta">' + (c.message_count || 0) + ' messages · ' + fmtDate(c.last_active_at) + '</div>' +
          (c.summary ? '<div class="meta">' + esc(c.summary) + '</div>' : '') +
        '</div>' +
        '<div class="btns">' +
          '<button class="open">Transcript</button>' +
          (c.archived ? '' : '<button class="arch">Forget</button>') +
          '<button class="del danger">Delete</button>' +
        '</div>' +
      '</div>' +
      '<div class="transcript" id="t' + c.id + '"></div>';

    card.querySelector('.open').onclick = function () { toggleTranscript(c.id, card); };
    var arch = card.querySelector('.arch'); if (arch) arch.onclick = function () {
      if (confirm('Forget (archive) this conversation? It stays in the DB but is hidden.')) jsend(B + '/conversation/' + c.id + '/archive', 'POST').then(load);
    };
    card.querySelector('.del').onclick = function () {
      if (confirm('Permanently DELETE this conversation and all its messages?')) jsend(B + '/conversation/' + c.id, 'DELETE').then(load);
    };
    return card;
  }

  async function toggleTranscript(id, card) {
    var el = $('t' + id);
    if (el.style.display === 'block') { el.style.display = 'none'; return; }
    el.style.display = 'block'; el.innerHTML = '<div class="meta">loading…</div>';
    var data = await jget(B + '/conversation/' + id);
    if (!data.messages || !data.messages.length) { el.innerHTML = '<div class="empty">empty</div>'; return; }
    el.innerHTML = data.messages.map(function (m) {
      return '<div class="msg ' + esc(m.role) + '"><span class="who">' + esc(m.role) +
        (m.intent ? ' · ' + esc(m.intent) : '') + '</span><div>' + esc(m.content) + '</div></div>';
    }).join('');
  }

  // ── Clear all ──────────────────────────────────────────────────────
  $('clear-all').onclick = async function () {
    if (!confirm('This wipes ALL of EDITH\'s memory — every fact and transcript. Continue?')) return;
    var typed = prompt('Type CLEAR to confirm permanent deletion of all memory:');
    if (typed !== 'CLEAR') { alert('Cancelled.'); return; }
    var r = await jsend(B + '/clear-all', 'POST', { confirm: 'CLEAR', include_transcripts: true });
    alert(r.ok ? 'All memory cleared.' : 'Failed: ' + (r.error || 'unknown'));
    load();
  };

  function load() {
    loadConversations().catch(function (e) { banner({ online: false, reason: e.message }); });
    loadFacts().catch(function () {});
  }
  $('refresh').onclick = load;
  $('show-inactive').onchange = loadFacts;
  $('show-archived').onchange = loadConversations;
  load();
})();
