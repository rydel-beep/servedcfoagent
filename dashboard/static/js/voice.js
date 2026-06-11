/* voice.js — Jarvis voice suite: STT in, ElevenLabs TTS out, presence orb,
   spoken brief, entrance sequence. One brain (chat.js / the chat endpoint),
   two mouths. No metric is computed here — engines only. */
(function() {
  'use strict';

  // ── State ────────────────────────────────────────────────
  var orb, captionEl, noteEl;
  var orbState = 'idle';          // idle | listening | thinking | speaking
  var recognition = null;
  var recognizing = false;
  var holdMode = false;           // push-to-talk in progress
  var currentAudio = null;        // playing Audio element
  var voiceStatus = null;         // /api/voice-status payload
  var ttsFallbackNoted = false;
  var pendingBriefOffer = false;
  var micStream = null, analyser = null, levelRAF = null;
  var entranceAudio = null;

  var hasSTT = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  function lsGet(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  function volume() { return lsGet('jarvis-muted', '0') === '1' ? 0 : parseFloat(lsGet('jarvis-vol', '1')) || 1; }

  // ── Orb + captions UI ────────────────────────────────────
  function buildUI() {
    orb = document.createElement('div');
    orb.id = 'jarvis-orb';
    orb.className = 'jarvis-orb idle';
    orb.title = hasSTT ? 'Talk to Jarvis (click, or hold V)' : 'Voice input not supported in this browser';
    orb.innerHTML = '<div class="orb-core"></div><div class="orb-ring"></div><div class="orb-spin"></div>';
    document.body.appendChild(orb);

    captionEl = document.createElement('div');
    captionEl.id = 'jarvis-caption';
    captionEl.className = 'jarvis-caption';
    document.body.appendChild(captionEl);

    noteEl = document.createElement('div');
    noteEl.id = 'jarvis-note';
    noteEl.className = 'jarvis-note';
    document.body.appendChild(noteEl);

    orb.addEventListener('click', onOrbClick);

    if (!hasSTT) {
      orb.classList.add('no-stt');
      note('Voice input needs Chrome — Jarvis can still speak replies.', 6000);
    }
  }

  function setOrb(state) {
    orbState = state;
    if (!orb) return;
    orb.className = 'jarvis-orb ' + state + (hasSTT ? '' : ' no-stt');
  }

  var captionTimer = null;
  function caption(text, sticky) {
    if (!captionEl) return;
    captionEl.textContent = text || '';
    captionEl.classList.toggle('show', !!text);
    clearTimeout(captionTimer);
    if (text && !sticky) captionTimer = setTimeout(function() { captionEl.classList.remove('show'); }, 6000);
  }

  var noteTimer = null;
  function note(text, ms) {
    if (!noteEl) return;
    noteEl.textContent = text || '';
    noteEl.classList.toggle('show', !!text);
    clearTimeout(noteTimer);
    if (text) noteTimer = setTimeout(function() { noteEl.classList.remove('show'); }, ms || 4000);
  }

  // ── Mic level → orb ring (Web Audio analyser) ────────────
  async function startLevelMeter() {
    try {
      if (!navigator.mediaDevices) return;
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var src = ctx.createMediaStreamSource(micStream);
      analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      var buf = new Uint8Array(analyser.frequencyBinCount);
      (function loop() {
        if (!analyser) return;
        analyser.getByteTimeDomainData(buf);
        var peak = 0;
        for (var i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128));
        var level = Math.min(peak / 50, 1);
        if (orb) orb.style.setProperty('--mic-level', level.toFixed(2));
        levelRAF = requestAnimationFrame(loop);
      })();
    } catch (e) { /* level meter is decoration; STT handles real mic errors */ }
  }

  function stopLevelMeter() {
    if (levelRAF) cancelAnimationFrame(levelRAF);
    levelRAF = null; analyser = null;
    if (micStream) { micStream.getTracks().forEach(function(t) { t.stop(); }); micStream = null; }
    if (orb) orb.style.setProperty('--mic-level', '0');
  }

  // ── Speech-to-text ───────────────────────────────────────
  function initRecognition() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return null;
    var r = new SR();
    r.lang = 'en-AU';
    r.interimResults = true;
    r.continuous = false;

    r.onresult = function(e) {
      var interim = '', final = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) final += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      if (interim) caption('hearing: ' + interim, true);
      if (final) {
        caption('heard: ' + final.trim());
        handleTranscript(final.trim());
      }
    };
    r.onerror = function(e) {
      stopListening();
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        note('Mic blocked — click the lock icon in the address bar to allow it.', 8000);
      } else if (e.error === 'no-speech') {
        note('Didn’t catch anything.');
      } else {
        note('Voice input error: ' + e.error);
      }
    };
    r.onend = function() {
      recognizing = false;
      if (orbState === 'listening') setOrb('idle');
      stopLevelMeter();
    };
    return r;
  }

  function startListening() {
    if (!hasSTT || recognizing) return;
    interrupt(); // Jarvis shuts up when Rydel wants to talk
    recognition = recognition || initRecognition();
    if (!recognition) return;
    try {
      recognition.start();
      recognizing = true;
      setOrb('listening');
      caption('listening…', true);
      startLevelMeter();
    } catch (e) { /* double-start race; ignore */ }
  }

  function stopListening() {
    if (recognition && recognizing) { try { recognition.stop(); } catch (e) {} }
    recognizing = false;
    if (orbState === 'listening') setOrb('idle');
    stopLevelMeter();
  }

  // ── Text-to-speech with fallback chain ───────────────────
  function speak(text) {
    return new Promise(function(resolve) {
      if (!text) return resolve();
      interrupt();
      setOrb('speaking');
      caption(text, true);

      var useEleven = voiceStatus && voiceStatus.elevenlabs_configured;
      if (useEleven) {
        // GET streams progressively through the <audio> pipeline — first word fast.
        var audio = new Audio('/dashboard/api/tts?text=' + encodeURIComponent(text));
        audio.volume = volume();
        currentAudio = audio;
        var fellBack = false;
        audio.addEventListener('error', function() {
          if (fellBack) return; fellBack = true;
          browserSpeak(text).then(done);
        });
        audio.addEventListener('ended', done);
        audio.play().catch(function() {
          if (fellBack) return; fellBack = true;
          browserSpeak(text).then(done);
        });
      } else {
        browserSpeak(text).then(done);
      }

      function done() {
        currentAudio = null;
        if (orbState === 'speaking') setOrb('idle');
        caption('');
        resolve();
      }
    });
  }

  function browserSpeak(text) {
    return new Promise(function(resolve) {
      if (!window.speechSynthesis) { note('Voice unavailable — text only.'); return resolve(); }
      if (!ttsFallbackNoted) { note('Using fallback voice (ElevenLabs unavailable).'); ttsFallbackNoted = true; }
      var u = new SpeechSynthesisUtterance(text);
      u.volume = volume();
      u.rate = 1.02;
      var voices = speechSynthesis.getVoices();
      var v = voices.find(function(x) { return /en[-_](GB|AU)/i.test(x.lang); });
      if (v) u.voice = v;
      u.onend = resolve;
      u.onerror = resolve;
      speechSynthesis.speak(u);
    });
  }

  function interrupt() {
    if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }
    if (window.speechSynthesis) speechSynthesis.cancel();
    if (entranceAudio) { try { entranceAudio.pause(); } catch (e) {} entranceAudio = null; }
    if (orbState === 'speaking') { setOrb('idle'); caption(''); }
  }

  // ── Conversation flow ────────────────────────────────────
  async function handleTranscript(text) {
    if (!text) return;
    if (pendingBriefOffer && /^(yes|yeah|yep|sure|ok|okay|go|brief|please)\b/i.test(text)) {
      pendingBriefOffer = false;
      return runBrief();
    }
    pendingBriefOffer = false;
    if (/^(brief me|morning brief|daily brief|read my priorities)\b/i.test(text)) {
      return runBrief();
    }
    if (!window.JarvisChat) return;
    window.JarvisChat.openPanel();
    setOrb('thinking');
    var reply = await window.JarvisChat.ask(text, true);
    if (reply) await speak(reply);
    else { setOrb('idle'); note('No reply — check the chat panel.'); }
  }

  async function runBrief() {
    setOrb('thinking');
    caption('composing your brief…', true);
    try {
      var resp = await fetch('/dashboard/api/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      var data = await resp.json();
      if (data.text) {
        if (window.JarvisChat) { window.JarvisChat.openPanel(); window.JarvisChat.addAssistantMessage(data.text); }
        await speak(data.text);
      } else {
        setOrb('idle');
        note(data.error || 'Brief unavailable.');
      }
    } catch (e) {
      setOrb('idle');
      note('Brief failed — network?');
    }
  }

  // ── Orb interaction ──────────────────────────────────────
  function onOrbClick() {
    if (orbState === 'speaking') return interrupt();
    if (recognizing) return stopListening();
    startListening();
  }

  // ── Keyboard: hold-V / hold-Space push-to-talk, Esc, B ──
  function initKeys() {
    var vHeld = false;
    document.addEventListener('keydown', function(e) {
      var tag = (document.activeElement || {}).tagName;
      var typing = tag === 'INPUT' || tag === 'TEXTAREA';
      if (e.key === 'Escape') { interrupt(); stopListening(); return; }
      if (typing) return;
      if ((e.key === 'v' || e.key === 'V' || (e.code === 'Space' && hasSTT)) && !vHeld && !e.metaKey && !e.ctrlKey) {
        if (e.code === 'Space') e.preventDefault();
        vHeld = true;
        holdMode = true;
        startListening();
      }
      if ((e.key === 'b' || e.key === 'B') && !e.metaKey && !e.ctrlKey) { runBrief(); }
      if (e.key === '?') { toggleHelp(); }
    });
    document.addEventListener('keyup', function(e) {
      if (e.key === 'v' || e.key === 'V' || e.code === 'Space') {
        if (vHeld) { vHeld = false; holdMode = false; stopListening(); }
      }
    });
  }

  // ── Help overlay ─────────────────────────────────────────
  function toggleHelp() {
    var el = document.getElementById('jarvis-help');
    if (el) { el.remove(); return; }
    el = document.createElement('div');
    el.id = 'jarvis-help';
    el.className = 'jarvis-help';
    var muted = lsGet('jarvis-muted', '0') === '1';
    var invite = lsGet('jarvis-entrance-invite', '0') === '1';
    el.innerHTML =
      '<div class="jh-title">Jarvis voice</div>' +
      '<div class="jh-row"><b>Click orb / hold V</b> talk to Jarvis</div>' +
      '<div class="jh-row"><b>Hold Space</b> also talks (outside inputs)</div>' +
      '<div class="jh-row"><b>Esc</b> interrupt &middot; <b>B</b> daily brief</div>' +
      '<div class="jh-row"><b>Reactor (top-left)</b> entrance sequence</div>' +
      '<div class="jh-row jh-controls">' +
        '<label><input type="checkbox" id="jh-mute" ' + (muted ? 'checked' : '') + '> mute</label>' +
        '<label>vol <input type="range" id="jh-vol" min="0" max="1" step="0.1" value="' + lsGet('jarvis-vol', '1') + '"></label>' +
      '</div>' +
      '<div class="jh-row"><label><input type="checkbox" id="jh-invite" ' + (invite ? 'checked' : '') + '> entrance invitation pulse on load</label></div>' +
      '<div class="jh-close">esc or ? to close</div>';
    document.body.appendChild(el);
    el.querySelector('#jh-mute').addEventListener('change', function() { lsSet('jarvis-muted', this.checked ? '1' : '0'); });
    el.querySelector('#jh-vol').addEventListener('input', function() { lsSet('jarvis-vol', this.value); });
    el.querySelector('#jh-invite').addEventListener('change', function() { lsSet('jarvis-entrance-invite', this.checked ? '1' : '0'); });
  }

  // ── Entrance sequence (click-triggered = autoplay-compliant) ──
  function speechMoney(v) {
    if (v == null) return 'unknown';
    return '$' + Math.round(v / 1000) + ' thousand';
  }

  async function entrance() {
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // 1) Entrance audio: user slot first (gitignored), else the default sting
    var src = '/dashboard/static/audio/entrance.mp3';
    try {
      var head = await fetch(src, { method: 'HEAD' });
      if (!head.ok) src = '/dashboard/static/audio/entrance-default.wav';
    } catch (e) { src = '/dashboard/static/audio/entrance-default.wav'; }
    entranceAudio = new Audio(src);
    entranceAudio.volume = volume();
    entranceAudio.play().catch(function() {});

    // 2) Boot animation: panels ignite in sequence (skippable by click)
    if (!reduced) {
      document.body.classList.add('boot-seq');
      var skip = function() { document.body.classList.remove('boot-seq'); document.removeEventListener('click', skip, true); };
      setTimeout(function() { document.addEventListener('click', skip, true); }, 100);
      setTimeout(skip, 3200);
    }

    // 3) Duck music → greeting with the single most important headline
    setTimeout(async function() {
      if (entranceAudio) {
        var duck = setInterval(function() {
          if (!entranceAudio) return clearInterval(duck);
          entranceAudio.volume = Math.max(0.08, entranceAudio.volume - 0.12);
          if (entranceAudio.volume <= 0.09) clearInterval(duck);
        }, 120);
      }
      var snap = window.__CURRENT_SNAP__ || window.__SNAP__ || {};
      var cp = snap.cash_position || {};
      var hour = new Date().getHours();
      var tod = hour < 12 ? 'morning' : (hour < 18 ? 'afternoon' : 'evening');
      var headline = cp.cash_in_bank != null
        ? ('Cash ' + speechMoney(cp.cash_in_bank) + ', runway ' + (cp.runway_months != null ? cp.runway_months + ' months' : 'unknown') + '.')
        : '';
      var greeting = 'Good ' + tod + ', Rydel. Systems online. ' + headline + ' Want the full brief?';
      pendingBriefOffer = true;
      if (window.JarvisChat) { window.JarvisChat.openPanel(); window.JarvisChat.addAssistantMessage(greeting); }
      await speak(greeting);
      // fade out any remaining music after the greeting
      if (entranceAudio) { try { entranceAudio.pause(); } catch (e) {} entranceAudio = null; }
    }, reduced ? 300 : 2300);
  }

  function initEntranceTrigger() {
    var reactor = document.querySelector('.reactor');
    if (!reactor) return;
    reactor.style.cursor = 'pointer';
    reactor.title = 'Power up (entrance sequence)';
    reactor.addEventListener('click', entrance);
    if (lsGet('jarvis-entrance-invite', '0') === '1') reactor.classList.add('invite');
  }

  // ── Init ─────────────────────────────────────────────────
  (async function init() {
    buildUI();
    initKeys();
    initEntranceTrigger();
    try {
      var resp = await fetch('/dashboard/api/voice-status');
      if (resp.ok) voiceStatus = await resp.json();
    } catch (e) { voiceStatus = null; }
  })();

})();
