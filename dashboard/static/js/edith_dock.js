/* edith_dock.js — THE SAME EDITH, ON EVERY OWNER PAGE.
 *
 * Not a second EDITH and not a second voice pipeline. This is a thin client
 * onto the routes that already exist:
 *
 *   /dashboard/api/chat-stream   the ONE brain, with channel="dashboard" so
 *                                the dock is its own thread on shared memory
 *                                — exactly as the Timeline bridge is
 *   /dashboard/api/tts           the server-to-server ElevenLabs proxy (the
 *                                key never reaches the browser)
 *   Web Speech                   the same STT the HUD uses
 *
 * The rules this file exists to keep:
 *   · nothing audible on load, ever — audio plays only after a tap
 *   · the microphone is requested on the FIRST TAP, never before
 *   · a tap or a word interrupts her, and the audio stops immediately
 *   · a failure is LOUD and says which part failed
 *   · this whole file runs after first paint, and if it dies the page lives
 */
(function () {
  'use strict';

  var CFG = {};
  try {
    CFG = JSON.parse(document.getElementById('ed-dock-cfg').textContent || '{}');
  } catch (e) { CFG = {}; }

  var $ = function (id) { return document.getElementById(id); };
  var pill = $('ed-pill'), dock = $('ed-dock'), log = $('ed-log'),
      text = $('ed-text'), send = $('ed-send'), mic = $('ed-mic'),
      status = $('ed-status'), ctx = $('ed-ctx'), closeBtn = $('ed-close');
  if (!pill || !dock) return;

  var history = [];
  var audio = null;           // the one audio element — never autoplayed
  var recog = null;
  var listening = false;
  var micGranted = false;

  function fail(where, reason) {
    /* LOUD and CLASSIFIED — never a silent robot. */
    if (!status) return;
    status.hidden = false;
    status.className = 'ed-status is-fail';
    status.textContent = 'EDITH ' + where + ' unavailable — ' + reason;
  }
  function note(msg) {
    if (!status) return;
    if (!msg) { status.hidden = true; status.textContent = ''; return; }
    status.hidden = false;
    status.className = 'ed-status';
    status.textContent = msg;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function bubble(role, content) {
    var d = document.createElement('div');
    d.className = 'ed-msg ed-' + role;
    d.innerHTML = esc(content);
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  /* ── page context: what she can see that you are looking at ──────────── */
  function pageContext() {
    var metrics = [];
    try {
      metrics = Array.prototype.slice
        .call(document.querySelectorAll('[data-metric][data-value]'))
        .slice(0, 40)
        .map(function (el) {
          return {metric: el.dataset.metric, window: el.dataset.window || '',
                  clock: el.dataset.clock || '', basis: el.dataset.basis || '',
                  value: el.dataset.value};
        });
    } catch (e) {}
    return {
      page: (document.body.dataset.page || location.pathname),
      path: location.pathname + location.search,
      title: document.title,
      metrics: metrics
    };
  }

  function openDock(prefill) {
    dock.hidden = false;
    pill.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(function () { dock.classList.add('is-open'); });
    if (ctx) ctx.textContent = (document.body.dataset.page || '').replace(/-/g, ' ');
    if (prefill) { text.value = prefill; }
    text.focus();
  }
  function closeDock() {
    dock.classList.remove('is-open');
    pill.setAttribute('aria-expanded', 'false');
    stopAudio();
    setTimeout(function () { dock.hidden = true; }, 180);
  }

  pill.hidden = false;
  pill.addEventListener('click', function () {
    dock.hidden ? openDock() : closeDock();
  });
  if (closeBtn) closeBtn.addEventListener('click', closeDock);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !dock.hidden) closeDock();
  });

  /* ── "Explain this" on any tile ──────────────────────────────────────── */
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-explain], .s-door');
    if (!t) return;
    var holder = t.closest('[data-metric]');
    var metric = (holder && holder.dataset.metric) || t.getAttribute('data-explain');
    if (!metric) return;
    e.preventDefault();
    var label = '';
    try {
      label = (holder.querySelector('.s-card-label, .exec-tile-label') || {}).innerText || metric;
    } catch (err) { label = metric; }
    openDock('Explain ' + String(label).trim().toLowerCase() + ' — where does it come from?');
  });

  /* ── asking ──────────────────────────────────────────────────────────── */
  function ask(message, spoken) {
    if (!message || !message.trim()) return;
    note('');
    bubble('you', message);
    history.push({role: 'user', content: message});
    text.value = '';
    var out = bubble('edith', '…');
    var full = '';

    fetch('/dashboard/api/chat-stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        history: history, voice: !!spoken,
        channel: 'dashboard',              /* one brain, its own thread */
        ui: pageContext()
      })
    }).then(function (resp) {
      if (resp.status === 403) { out.textContent = ''; fail('chat', 'this is owner-only'); return null; }
      if (!resp.ok || !resp.body) throw new Error('stream unavailable (' + resp.status + ')');
      var reader = resp.body.getReader(), dec = new TextDecoder(), buf = '';
      function pump() {
        return reader.read().then(function (rd) {
          if (rd.done) return;
          buf += dec.decode(rd.value, {stream: true});
          var parts = buf.split('\n\n'); buf = parts.pop();
          parts.forEach(function (frame) {
            var ev = (frame.match(/^event:\s*(.+)$/m) || [])[1];
            var dl = (frame.match(/^data:\s*([\s\S]+)$/m) || [])[1];
            if (!ev || !dl) return;
            var p; try { p = JSON.parse(dl); } catch (e) { return; }
            if (ev === 'delta' && p.text) { full += p.text; out.textContent = full; log.scrollTop = log.scrollHeight; }
            else if (ev === 'done') { full = p.reply || full; out.textContent = full; }
            else if (ev === 'error') { fail('chat', p.error || 'the model did not answer'); }
          });
          return pump();
        });
      }
      return pump();
    }).then(function () {
      if (!full) return;
      history.push({role: 'assistant', content: full});
      if (spoken) speak(full);
    }).catch(function (e) {
      out.textContent = '';
      fail('chat', String(e && e.message || e));
    });
  }

  send.addEventListener('click', function () { ask(text.value, false); });
  text.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(text.value, false); }
  });

  /* ── voice out: ONLY after a tap, and always interruptible ───────────── */
  function stopAudio() {
    if (audio) { try { audio.pause(); audio.src = ''; } catch (e) {} audio = null; }
  }

  function speak(msg) {
    stopAudio();
    try {
      audio = new Audio('/dashboard/api/tts?text=' + encodeURIComponent(msg.slice(0, 1200)));
      audio.addEventListener('error', function () {
        fail('voice', 'the speech service did not return audio — text is above');
      });
      var p = audio.play();
      if (p && p.catch) p.catch(function (err) {
        /* a browser refusing playback is NOT a silent failure */
        fail('voice', 'the browser blocked playback (' + (err && err.name) + ') — tap the mic again');
      });
    } catch (e) {
      fail('voice', String(e && e.message || e));
    }
  }

  /* a tap anywhere in the dock, or any new speech, interrupts her */
  dock.addEventListener('pointerdown', function () { if (audio) stopAudio(); }, true);

  /* ── voice in: the mic is requested on the FIRST TAP, never before ───── */
  mic.addEventListener('click', function () {
    if (listening) { stopListening(); return; }
    stopAudio();                     /* barge-in */
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { fail('voice', 'this browser has no speech recognition'); return; }
    try {
      recog = new SR();
      recog.lang = 'en-AU';
      recog.interimResults = true;
      recog.continuous = false;
      recog.onstart = function () {
        listening = true; micGranted = true;
        mic.classList.add('is-live'); note('listening…');
      };
      recog.onresult = function (e) {
        var said = '';
        for (var i = e.resultIndex; i < e.results.length; i++) said += e.results[i][0].transcript;
        text.value = said;
        if (e.results[e.results.length - 1].isFinal) {
          stopListening();
          ask(said, true);          /* the transcript lands in the SAME thread */
        }
      };
      recog.onerror = function (e) {
        stopListening();
        var why = e && e.error;
        fail('voice', why === 'not-allowed'
          ? 'the microphone was blocked — allow it in the browser and tap again'
          : ('speech recognition failed: ' + why));
      };
      recog.onend = function () { stopListening(); };
      recog.start();
    } catch (e) {
      fail('voice', String(e && e.message || e));
    }
  });

  function stopListening() {
    listening = false;
    mic.classList.remove('is-live');
    note('');
    if (recog) { try { recog.stop(); } catch (e) {} }
  }

  /* nothing above runs on load: no audio, no getUserMedia, no recognition.
     The first tap is what starts any of it. */
  window.EdithDock = {open: openDock, close: closeDock, ask: ask,
                      context: pageContext, micGranted: function () { return micGranted; }};
})();
