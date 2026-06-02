/* export.js — Sales Summary export modal logic */
(function() {
  'use strict';

  var btn = document.getElementById('btn-export-sales');
  var overlay = document.getElementById('export-overlay');
  var modal = document.getElementById('export-modal');
  var closeBtn = document.getElementById('export-close');
  var body = document.getElementById('export-body');
  var copyBtn = document.getElementById('export-copy');
  var copiedMsg = document.getElementById('export-copied');
  var periodEl = document.getElementById('export-period');

  var isOpen = false;
  var currentMarkdown = '';

  function getWindowDays() {
    // Read from the global window bar's active button
    var active = document.querySelector('#global-window-bar .global-window-btn.active');
    return active ? parseInt(active.dataset.window) || 30 : 30;
  }

  function open() {
    isOpen = true;
    overlay.classList.add('open');
    modal.classList.add('open');
    body.textContent = 'Loading...';
    periodEl.textContent = '';
    copiedMsg.style.opacity = '0';

    var windowDays = getWindowDays();

    fetch('/dashboard/api/sales-summary?window_days=' + windowDays)
      .then(function(resp) { return resp.json(); })
      .then(function(data) {
        if (data.error) {
          body.textContent = 'Error: ' + data.error;
          return;
        }
        currentMarkdown = data.markdown || '';
        body.textContent = currentMarkdown;
        periodEl.textContent = 'Trailing ' + (data.window_days || windowDays) + ' days';
      })
      .catch(function(e) {
        body.textContent = 'Failed to fetch summary: ' + e.message;
      });
  }

  function close() {
    isOpen = false;
    overlay.classList.remove('open');
    modal.classList.remove('open');
  }

  function copyToClipboard() {
    if (!currentMarkdown) return;
    navigator.clipboard.writeText(currentMarkdown).then(function() {
      copiedMsg.style.opacity = '1';
      setTimeout(function() { copiedMsg.style.opacity = '0'; }, 2000);
    }).catch(function() {
      // Fallback for older browsers
      var ta = document.createElement('textarea');
      ta.value = currentMarkdown;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      copiedMsg.style.opacity = '1';
      setTimeout(function() { copiedMsg.style.opacity = '0'; }, 2000);
    });
  }

  btn.addEventListener('click', open);
  overlay.addEventListener('click', close);
  closeBtn.addEventListener('click', close);
  copyBtn.addEventListener('click', copyToClipboard);

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && isOpen) close();
  });
})();
