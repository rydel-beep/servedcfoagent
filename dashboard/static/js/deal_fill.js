/* deal_fill.js — THE FILL-IN FORM, MATCH CARDS, STATEMENT (#171).
 *
 * One small script for the three truth-engine panels:
 *   · "Deals missing details" → the fill-in form (package from the rate
 *     card + custom, term, contract ex-GST, schedule rows with account
 *     BUSINESS/PERSONAL, closer, setter, notes). Submitting is a ruling.
 *   · "Payments to confirm" → Confirm / Reject / someone else, with the
 *     optional package + start + contract in the same step.
 *   · "Today's numbers, verified" → Generate now.
 * Inline, no dialogs; every refusal is shown in words beside the button.
 */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); });
  }
  var RATE = null;
  function rateCard() {
    if (RATE) return Promise.resolve(RATE);
    return fetch('/dashboard/api/register/rate-card', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { packages: [] }; })
      .then(function (j) { RATE = j.packages || []; return RATE; })
      .catch(function () { return []; });
  }

  // ── the fill-in form ───────────────────────────────────────────────────
  function schedRow(n) {
    var row = el('div', 'mdq-sched-row');
    row.innerHTML =
      '<span class="s-card-sub">payment ' + n + '</span>' +
      '<input class="s-input" data-f="amount" placeholder="amount" inputmode="decimal" style="width:7em">' +
      '<select class="s-input" data-f="gst"><option value="inc">inc GST</option><option value="ex">ex GST</option></select>' +
      '<input class="s-input" data-f="due" type="date" title="due date">' +
      '<input class="s-input" data-f="received" type="date" title="received on (leave blank if not yet)">' +
      '<select class="s-input" data-f="account"><option value="">account…</option><option value="business">BUSINESS account</option><option value="personal">PERSONAL account</option></select>' +
      '<input class="s-input" data-f="evidence_id" placeholder="bank-feed / charge id (if known)" style="width:12em">';
    return row;
  }
  function openForm(seed) {
    var host = $('#mdq-form-host');
    if (!host) return;
    host.hidden = false;
    host.innerHTML = '';
    var known = seed.known || {};
    var box = el('div', 'cl-dialog mdq-form');
    box.innerHTML =
      '<h3 class="s-panel-title" style="font-size:1rem">' + (seed.isNew ? 'Record a new close' : 'Fill in the details — ' + (seed.client || seed.person || '')) + '</h3>' +
      '<div class="s-card-sub">Everything you enter is recorded as your ruling (who, when, your words), is reversible, and the numbers recompute the moment you submit. ' +
      'A payment into a PERSONAL account is recorded as received outside business accounts — it never counts as business cash until it appears in Xero.</div>' +
      '<div class="mdq-grid">' +
      '<label>Contact (who signed) <input class="s-input" data-f="person" value="' + esc(seed.person || '') + '"' + (seed.isNew ? '' : ' readonly') + '></label>' +
      '<label>Client / venue <input class="s-input" data-f="client" value="' + esc(seed.client || '') + '"></label>' +
      '<label>Close date <input class="s-input" data-f="close_date" type="date" value="' + esc(seed.close_date || '') + '"></label>' +
      '<label>Package <select class="s-input" data-f="package"><option value="">choose…</option></select></label>' +
      '<label class="mdq-custom" hidden>Custom package — describe it <input class="s-input" data-f="package_custom" placeholder="e.g. photography + 3 months ads"></label>' +
      '<label>Term (months) <input class="s-input" data-f="term_months" inputmode="numeric" value="' + esc(known.term_months || '') + '"></label>' +
      '<label>Contract value ex-GST <input class="s-input" data-f="contract_ex_gst" inputmode="decimal" value="' + esc(known.contract_ex_gst || '') + '"></label>' +
      '<label>Payment type <select class="s-input" data-f="payment_type"><option value="">—</option><option value="PIF">paid in full</option><option value="split">split</option><option value="monthly">monthly</option></select></label>' +
      '<label>Closer <input class="s-input" data-f="closer" value="' + esc(known.closer || '') + '" placeholder="kalin / coby"></label>' +
      '<label>Setter <input class="s-input" data-f="setter" value="' + esc(known.setter || '') + '" placeholder="maran / coby / akila"></label>' +
      '<label style="grid-column:1/-1">Notes <input class="s-input" data-f="notes" placeholder="anything the next person should know"></label>' +
      '</div>' +
      '<div class="s-card-sub" style="margin-top:8px"><b>Payment schedule</b> — one row per instalment (amount, due, received, which account)</div>' +
      '<div class="mdq-sched"></div>' +
      '<button class="s-door mdq-add-row" type="button">+ add a payment row</button>' +
      '<div style="margin-top:10px"><button class="s-btn mdq-submit" type="button">Submit as my ruling</button> ' +
      '<button class="s-door mdq-cancel" type="button">Cancel</button></div>' +
      '<div class="mdq-out s-card-sub" aria-live="polite"></div>';
    host.appendChild(box);
    var sched = $('.mdq-sched', box);
    sched.appendChild(schedRow(1));
    $('.mdq-add-row', box).addEventListener('click', function () {
      sched.appendChild(schedRow(sched.children.length + 1));
    });
    $('.mdq-cancel', box).addEventListener('click', function () { host.hidden = true; host.innerHTML = ''; });
    rateCard().then(function (pk) {
      var sel = $('[data-f=package]', box);
      pk.forEach(function (p) {
        var o = el('option'); o.value = p.label; o.textContent = p.label + (p.term_months ? ' · ' + p.term_months + ' months' : '');
        o.dataset.term = p.term_months || ''; o.dataset.key = p.key;
        if (known.package && String(known.package).toLowerCase().indexOf(p.label.toLowerCase().split(' ')[0]) === 0) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener('change', function () {
        var o = sel.options[sel.selectedIndex];
        $('.mdq-custom', box).hidden = (o.dataset.key !== 'custom');
        if (o.dataset.term && !$('[data-f=term_months]', box).value) $('[data-f=term_months]', box).value = o.dataset.term;
      });
    });
    $('.mdq-submit', box).addEventListener('click', function () {
      var body = { key: seed.key || null };
      box.querySelectorAll('.mdq-grid [data-f]').forEach(function (i) { body[i.dataset.f] = i.value; });
      body.schedule = [];
      sched.querySelectorAll('.mdq-sched-row').forEach(function (r) {
        var row = {};
        r.querySelectorAll('[data-f]').forEach(function (i) { row[i.dataset.f] = i.value; });
        if (row.amount) body.schedule.push(row);
      });
      var out = $('.mdq-out', box);
      out.textContent = 'recording your ruling…';
      post('/dashboard/api/register/fill', body).then(function (res) {
        if (res.status !== 200 || !res.j.ok) { out.textContent = 'Refused — ' + (res.j.error || ('the server said ' + res.status)); return; }
        var left = res.j.gaps_left || [];
        var pl = res.j.piolo_line && res.j.piolo_line.edits ? ' Piolo line: ' + res.j.piolo_line.edits.join('; ') + '.' : '';
        var pa = res.j.personal_account_payments ? ' ' + res.j.personal_account_payments + ' payment(s) recorded as received outside business accounts (not business cash).' : '';
        out.textContent = 'Recorded as your ruling. ' + (left.length ? 'Still missing: ' + left.join(', ') + '.' : 'This close is now complete.') + pa + pl + ' Reloading…';
        setTimeout(function () { location.reload(); }, 1600);
      }).catch(function (e) { out.textContent = 'request failed — ' + e; });
    });
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function esc(s) { var d = document.createElement('i'); d.textContent = String(s == null ? '' : s); return d.innerHTML; }

  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.mdq-fill');
    if (b) {
      e.preventDefault();
      var tr = b.closest('tr');
      if (!tr) { openForm({ isNew: true, close_date: new Date().toISOString().slice(0, 10) }); return; }
      var known = {};
      try { known = JSON.parse(tr.dataset.known || '{}'); } catch (err) {}
      openForm({ key: tr.dataset.key, person: tr.dataset.person, client: tr.dataset.client,
                 close_date: tr.dataset.closeDate, known: known });
      return;
    }
    var rv = e.target.closest && e.target.closest('.mdq-revoke');
    if (rv) {
      e.preventDefault();
      var tr2 = rv.closest('tr');
      rv.disabled = true; rv.textContent = 'reversing…';
      post('/dashboard/api/register/fill/revoke', { key: tr2.dataset.key }).then(function (res) {
        rv.textContent = (res.status === 200 && res.j.ok) ? 'reversed — reloading…' : ('not reversed: ' + (res.j.error || res.status));
        if (res.status === 200 && res.j.ok) setTimeout(function () { location.reload(); }, 900);
        else rv.disabled = false;
      });
    }
  });

  // ── match cards ────────────────────────────────────────────────────────
  function cardTerms(card) {
    var w = el('div', 'mc-terms');
    w.innerHTML = '<div class="s-card-sub">Optional — record what they bought in the same step (leave blank to only attach the money):</div>' +
      '<input class="s-input" data-t="package" placeholder="package (e.g. Growth Pro)" style="width:11em"> ' +
      '<input class="s-input" data-t="term_months" placeholder="months" inputmode="numeric" style="width:5em"> ' +
      '<input class="s-input" data-t="contract_ex_gst" placeholder="contract ex-GST" inputmode="decimal" style="width:9em"> ' +
      '<input class="s-input" data-t="start_date" type="date" title="start date">';
    card.appendChild(w);
    return w;
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.mc-act');
    if (!b) return;
    e.preventDefault();
    var card = b.closest('.mc-card');
    var out = $('.mc-out', card);
    var decision = b.dataset.decision;
    if (card.dataset.open === decision) return;
    card.dataset.open = decision;
    var form = $('.mc-form', card);
    if (form) form.remove();
    form = el('div', 'mc-form');
    var nameInput = null;
    if (decision === 'someone_else') {
      nameInput = el('input', 's-input'); nameInput.placeholder = 'the client this money belongs to'; nameInput.setAttribute('list', 'up-client-names');
      form.appendChild(nameInput);
    } else if (decision === 'confirm') {
      form.appendChild(el('span', 's-card-sub', 'Attach to ' + card.dataset.proposed + '? '));
    } else {
      nameInput = el('input', 's-input'); nameInput.placeholder = 'why (optional)';
      form.appendChild(nameInput);
    }
    var terms = (decision !== 'reject') ? cardTerms(form) : null;
    var go = el('button', 's-door', decision === 'reject' ? 'Reject this match' : 'Yes — record it');
    go.type = 'button';
    var cancel = el('button', 's-door', 'Cancel'); cancel.type = 'button';
    cancel.addEventListener('click', function () { form.remove(); card.dataset.open = ''; });
    go.addEventListener('click', function () {
      var body = { id: card.dataset.id, decision: decision };
      if (decision === 'someone_else') { body.client = (nameInput.value || '').trim(); if (!body.client) { out.textContent = 'Name the client first.'; return; } }
      if (decision === 'reject') body.words = nameInput.value || '';
      if (terms) {
        var t = {};
        terms.querySelectorAll('[data-t]').forEach(function (i) { if (i.value) t[i.dataset.t] = i.value; });
        if (Object.keys(t).length) body.terms = t;
      }
      go.disabled = true; go.textContent = 'saving…';
      post('/dashboard/api/match-proposals/decide', body).then(function (res) {
        if (res.status !== 200 || !res.j.ok) { go.disabled = false; go.textContent = 'Yes — record it'; out.textContent = 'Not saved — ' + (res.j.error || res.status); return; }
        card.style.opacity = '0.5';
        form.remove();
        var t = res.j.terms;
        out.textContent = (decision === 'reject' ? 'Rejected and journaled.' : 'Attached and journaled.') +
          (t ? (t.ok ? ' Package and contract recorded as your ruling.' : ' Terms not recorded: ' + (t.error || '')) : '') +
          (res.j.remeasure && res.j.remeasure.requested ? ' The renewal measurement will re-run within minutes.' : '');
      }).catch(function (err) { go.disabled = false; out.textContent = 'request failed — ' + err; });
    });
    form.appendChild(go); form.appendChild(cancel);
    card.appendChild(form);
    if (nameInput) nameInput.focus();
  });

  // ── the statement ──────────────────────────────────────────────────────
  var gen = $('#vs-generate');
  if (gen) gen.addEventListener('click', function () {
    gen.disabled = true;
    $('#vs-generate-out').textContent = 'adding it up by hand…';
    post('/dashboard/api/statement/generate', {}).then(function (res) {
      $('#vs-generate-out').textContent = (res.status === 200 && res.j.identity)
        ? (res.j.identity.ok ? 'hand check passed — reloading…' : 'CHECK FAILED — ' + res.j.identity.detail)
        : ('not generated: ' + (res.j.error || res.status));
      if (res.status === 200) setTimeout(function () { location.reload(); }, 1200);
      else gen.disabled = false;
    });
  });
})();
