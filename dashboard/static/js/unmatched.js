/* unmatched.js — attaching money to a client, in one click.
 *
 * The row already knows the payer, the charge and the best guess. This turns
 * that into a confirmation the owner makes deliberately: reveal the name,
 * confirm it, and the alias is written, journalled and applied — the row
 * clears and the numbers rebuild behind it.
 *
 * Owner-only by construction: the button is not rendered for anyone else and
 * the route refuses them anyway. No dialogs — an inline row, so nothing ever
 * blocks the page.
 */
(function () {
  'use strict';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function say(row, msg, bad) {
    var note = row.querySelector('.up-note') || el('div', 'up-note s-card-sub');
    note.className = 'up-note s-card-sub' + (bad ? ' is-bad' : '');
    note.textContent = msg;
    row.querySelector('td:last-child').appendChild(note);
  }

  function confirmRow(btn) {
    var row = btn.closest('tr');
    if (!row || row.dataset.open === '1') return;
    row.dataset.open = '1';

    var cell = row.querySelector('td:last-child');
    var wrap = el('div', 'up-form');
    var input = el('input', 'up-client');
    input.type = 'text';
    input.value = btn.dataset.client || '';
    input.placeholder = 'which client is this?';
    input.setAttribute('aria-label', 'client this payment belongs to');
    var go = el('button', 's-door', 'Confirm');
    go.type = 'button';
    var cancel = el('button', 's-door', 'Cancel');
    cancel.type = 'button';

    cancel.addEventListener('click', function () {
      wrap.remove();
      row.dataset.open = '';
      btn.hidden = false;
    });

    go.addEventListener('click', function () {
      var client = (input.value || '').trim();
      if (!client) { say(row, 'Name the client first.', true); return; }
      go.disabled = true;
      go.textContent = 'saving…';
      fetch('/dashboard/api/unmatched/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          payer: btn.dataset.payer, client: client,
          charge_id: btn.dataset.charge
        })
      }).then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
        .then(function (pair) {
          var status = pair[0], j = pair[1];
          if (status !== 200 || !j.ok) {
            go.disabled = false;
            go.textContent = 'Confirm';
            say(row, 'Not saved — ' + (j.error || ('the server said ' + status)), true);
            return;
          }
          /* the row is done: fade it, say what moved, and leave the page
             otherwise untouched — no full re-render */
          row.style.opacity = '0.45';
          wrap.remove();
          say(row, 'Attached to ' + client + '. ' +
                   ((j.rescan && j.rescan.count != null)
                     ? (j.rescan.count + ' payment(s) still unattached.')
                     : 'Saved.'));
        })
        .catch(function (e) {
          go.disabled = false;
          go.textContent = 'Confirm';
          say(row, 'Not saved — ' + (e && e.message ? e.message : e), true);
        });
    });

    wrap.appendChild(input);
    wrap.appendChild(go);
    wrap.appendChild(cancel);
    cell.appendChild(wrap);
    btn.hidden = true;
    input.focus();
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.up-confirm');
    if (btn) { e.preventDefault(); confirmRow(btn); }
  });
})();
