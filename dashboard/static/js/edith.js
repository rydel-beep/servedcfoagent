/* edith.js — EDITH voice suite.
   One brain (the existing chat endpoint via window.JarvisChat), this file is
   the I/O layer: wake word (on-device Porcupine WASM) → conversational
   endpointing STT → chat → ElevenLabs TTS → AI-character effects graph →
   speakers. No metric is computed here — engines only. */
(function() {
  'use strict';

  var CFG = window.__EDITH_CFG__ || {};
  var TEST_LINE = 'Good evening, Rydel. EDITH online. Cash position is ninety-one thousand dollars; runway three point six months.';

  // ── tiny utils ───────────────────────────────────────────
  function lsGet(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function lsNum(k, d) { var v = parseFloat(lsGet(k, '')); return isNaN(v) ? d : v; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function volume() { return lsGet('edith-muted', '0') === '1' ? 0 : lsNum('edith-vol', 1); }

  var hasSTT = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  // ── DOM: orb, ring, captions, notes, ambience ────────────
  var orb, ringEl, captionEl, noteEl, waveCanvas, hudRing;
  var orbState = 'idle';

  function buildUI() {
    orb = document.createElement('div');
    orb.id = 'jarvis-orb';
    orb.className = 'jarvis-orb idle';
    orb.title = hasSTT ? 'Talk to EDITH (click, hold V, or say "' + wakePhrase() + '")' : 'Voice input not supported in this browser';
    orb.innerHTML =
      '<svg class="orb-progress" viewBox="0 0 56 56"><circle cx="28" cy="28" r="26" fill="none"/></svg>' +
      '<div class="orb-core"></div><div class="orb-ring"></div><div class="orb-spin"></div>' +
      '<div class="orb-armed" title="Wake word armed"></div>';
    document.body.appendChild(orb);
    ringEl = orb.querySelector('.orb-progress circle');

    captionEl = document.createElement('div');
    captionEl.id = 'jarvis-caption';
    captionEl.className = 'jarvis-caption';
    document.body.appendChild(captionEl);

    noteEl = document.createElement('div');
    noteEl.id = 'jarvis-note';
    noteEl.className = 'jarvis-note';
    document.body.appendChild(noteEl);

    waveCanvas = document.createElement('canvas');
    waveCanvas.id = 'edith-wave';
    waveCanvas.className = 'edith-wave';
    waveCanvas.width = 180; waveCanvas.height = 28;
    document.body.appendChild(waveCanvas);

    hudRing = document.createElement('div');
    hudRing.id = 'edith-hud-ring';
    hudRing.className = 'edith-hud-ring';
    document.body.appendChild(hudRing);

    orb.addEventListener('click', onOrbClick);
    if (!hasSTT) { orb.classList.add('no-stt'); note('Voice input needs Chrome — EDITH can still speak.', 6000); }
  }

  function setOrb(state) {
    orbState = state;
    if (orb) orb.className = 'jarvis-orb ' + state + (hasSTT ? '' : ' no-stt') + (wakeArmed ? ' armed' : '') + (sessionActive ? ' session' : '');
  }
  function setRing(p) { // 0..1 silence-countdown progress
    if (!ringEl) return;
    var C = 2 * Math.PI * 26;
    ringEl.style.strokeDasharray = C;
    ringEl.style.strokeDashoffset = C * (1 - Math.max(0, Math.min(1, p)));
    ringEl.parentElement.classList.toggle('show', p > 0.02);
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
    if (text) noteTimer = setTimeout(function() { noteEl.classList.remove('show'); }, ms || 4500);
  }

  // ── Audio foundation: shared context, mic, analysers ─────
  var actx = null;
  function audioCtx() {
    if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === 'suspended') actx.resume();
    return actx;
  }

  var micStream = null, micAnalyser = null, micBuf = null;
  async function ensureMic() {
    if (micStream) return micStream;
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    var src = audioCtx().createMediaStreamSource(micStream);
    micAnalyser = audioCtx().createAnalyser();
    micAnalyser.fftSize = 512;
    src.connect(micAnalyser);
    micBuf = new Uint8Array(micAnalyser.fftSize);
    return micStream;
  }
  function releaseMic() {
    if (micStream) { micStream.getTracks().forEach(function(t) { t.stop(); }); micStream = null; micAnalyser = null; }
  }
  function micRMS() {
    if (!micAnalyser) return 0;
    micAnalyser.getByteTimeDomainData(micBuf);
    var sum = 0;
    for (var i = 0; i < micBuf.length; i++) { var d = (micBuf[i] - 128) / 128; sum += d * d; }
    return Math.sqrt(sum / micBuf.length);
  }

  // ── PHASE 5: the AI voice character (effects graph) ──────
  // source → bandpass → metallic comb → micro-doubling (chorus detune)
  //        → short plate convolver → wet/dry → analyser → out
  var PRESETS = {
    off:       { wet: 0.0,  hp: 0,    lp: 20000, comb: 0,    dbl: 0,    rev: 0 },
    subtle:    { wet: 0.10, hp: 110,  lp: 9000,  comb: 0.08, dbl: 0.18, rev: 0.08 },
    assistant: { wet: 0.15, hp: 120,  lp: 8000,  comb: 0.12, dbl: 0.25, rev: 0.12 },
    system:    { wet: 0.28, hp: 160,  lp: 6500,  comb: 0.2,  dbl: 0.34, rev: 0.2 },
  };

  function fxParams(presetName) {
    var p = Object.assign({}, PRESETS[presetName] || PRESETS.subtle);
    // advanced overrides (persisted)
    ['wet', 'hp', 'lp', 'comb', 'dbl', 'rev'].forEach(function(k) {
      var v = lsGet('edith-fx-' + k, null);
      if (v != null && lsGet('edith-fx-custom', '0') === '1') p[k] = parseFloat(v);
    });
    return p;
  }

  function makeImpulse(ctx, ms) {
    var len = Math.max(1, Math.round(ctx.sampleRate * ms / 1000));
    var buf = ctx.createBuffer(1, len, ctx.sampleRate);
    var d = buf.getChannelData(0);
    for (var i = 0; i < len; i++) {
      d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.2);
    }
    return buf;
  }

  var fxAnalyser = null; // post-processed signal drives the orb + wave strip

  function buildFxChain(audioEl, presetName, crushFirstWord) {
    var ctx = audioCtx();
    var p = fxParams(presetName);
    var src = ctx.createMediaElementSource(audioEl);

    var dry = ctx.createGain();
    var wetIn = ctx.createGain();
    src.connect(dry); src.connect(wetIn);

    // [1] comms bandpass
    var hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = p.hp || 1;
    var lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = p.lp;
    wetIn.connect(hp); hp.connect(lp);

    // [2] metallic resonance: short feedback comb (5ms)
    var combIn = ctx.createGain();
    var combDelay = ctx.createDelay(0.05); combDelay.delayTime.value = 0.005;
    var combFb = ctx.createGain(); combFb.gain.value = Math.min(0.55, p.comb * 2.4);
    var combMix = ctx.createGain(); combMix.gain.value = p.comb;
    lp.connect(combIn);
    combIn.connect(combDelay); combDelay.connect(combFb); combFb.connect(combDelay);
    combDelay.connect(combMix);

    // [3] micro-doubling: 14ms delayed copy, LFO-modulated (~8 cents perceived)
    var dbl = ctx.createDelay(0.06); dbl.delayTime.value = 0.014;
    var lfo = ctx.createOscillator(); lfo.frequency.value = 0.7;
    var lfoGain = ctx.createGain(); lfoGain.gain.value = 0.0006;
    lfo.connect(lfoGain); lfoGain.connect(dbl.delayTime); lfo.start();
    var dblMix = ctx.createGain(); dblMix.gain.value = p.dbl;
    lp.connect(dbl); dbl.connect(dblMix);

    // [4] short metallic plate (generated 120ms impulse)
    var conv = ctx.createConvolver(); conv.buffer = makeImpulse(ctx, 120);
    var revMix = ctx.createGain(); revMix.gain.value = p.rev;
    lp.connect(conv); conv.connect(revMix);

    // wet bus
    var wetOut = ctx.createGain();
    lp.connect(wetOut);            // filtered base
    combMix.connect(wetOut);
    dblMix.connect(wetOut);
    revMix.connect(wetOut);

    // master wet/dry
    var wetGain = ctx.createGain(); wetGain.gain.value = p.wet;
    var dryGain = ctx.createGain(); dryGain.gain.value = 1 - p.wet * 0.5; // keep voice forward
    wetOut.connect(wetGain); dry.connect(dryGain);

    var master = ctx.createGain(); master.gain.value = 1;
    wetGain.connect(master); dryGain.connect(master);

    // optional ~80ms bit-crush flicker on the very first word (boot greeting only)
    if (crushFirstWord) {
      var shaper = ctx.createWaveShaper();
      var curve = new Float32Array(256);
      for (var i = 0; i < 256; i++) {
        var x = (i / 128) - 1;
        curve[i] = Math.round(x * 6) / 6; // coarse quantize
      }
      shaper.curve = curve;
      var crushGain = ctx.createGain(); crushGain.gain.value = 0.5;
      lp.connect(shaper); shaper.connect(crushGain); crushGain.connect(master);
      setTimeout(function() { try { crushGain.gain.setTargetAtTime(0, ctx.currentTime, 0.02); } catch (e) {} }, 80);
    }

    fxAnalyser = ctx.createAnalyser(); fxAnalyser.fftSize = 256;
    master.connect(fxAnalyser);
    fxAnalyser.connect(ctx.destination);
    return master;
  }

  // ── TTS playback (ElevenLabs stream → fx graph; fallback chain) ──
  var currentAudio = null;
  var voiceStatus = null;
  var ttsFallbackNoted = false;

  function fxEnabled() { return lsGet('edith-fx-on', '1') === '1'; }
  function activePreset(context) {
    if (!fxEnabled()) return 'off';
    if (context === 'system') return 'system';
    return lsGet('edith-fx-preset', 'subtle');
  }

  function speak(text, context, opts) {
    opts = opts || {};
    return new Promise(function(resolve) {
      if (!text) return resolve();
      stopSpeaking();
      setOrb('speaking');
      caption(text, true);
      startWave();

      var useEleven = voiceStatus && voiceStatus.elevenlabs_configured;
      if (useEleven) {
        var url = '/dashboard/api/tts?text=' + encodeURIComponent(text);
        if (opts.voiceId) url += '&voice_id=' + encodeURIComponent(opts.voiceId);
        var audio = new Audio(url);
        audio.crossOrigin = 'use-credentials';
        audio.volume = volume();
        currentAudio = audio;
        try { buildFxChain(audio, activePreset(context), !!opts.crushFirstWord); } catch (e) { /* play raw */ }
        var fell = false;
        audio.addEventListener('error', function() { if (!fell) { fell = true; browserSpeak(text).then(done); } });
        audio.addEventListener('ended', done);
        audio.play().catch(function() { if (!fell) { fell = true; browserSpeak(text).then(done); } });
      } else {
        browserSpeak(text).then(done);
      }

      function done() {
        currentAudio = null;
        stopWave();
        if (orbState === 'speaking') { setOrb('idle'); caption(''); }
        resolve();
      }
    });
  }

  function browserSpeak(text) {
    return new Promise(function(resolve) {
      if (!window.speechSynthesis) { note('Voice unavailable — text only.'); return resolve(); }
      if (!ttsFallbackNoted) { note('Using fallback voice (ElevenLabs unavailable). Effects bypassed.'); ttsFallbackNoted = true; }
      var u = new SpeechSynthesisUtterance(text);
      u.volume = volume(); u.rate = 1.02;
      var v = (speechSynthesis.getVoices() || []).find(function(x) { return /en[-_](GB|AU)/i.test(x.lang); });
      if (v) u.voice = v;
      u.onend = resolve; u.onerror = resolve;
      speechSynthesis.speak(u);
    });
  }

  function stopSpeaking() {
    if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }
    if (window.speechSynthesis) speechSynthesis.cancel();
    stopWave();
    if (orbState === 'speaking') { setOrb('idle'); caption(''); }
  }

  // ── Waveform strip + speaking pulse from the POST-fx signal ──
  var waveRAF = null;
  function startWave() {
    if (!waveCanvas || lsGet('edith-cinematic', '1') !== '1') return;
    waveCanvas.classList.add('show');
    var g = waveCanvas.getContext('2d');
    var buf = new Uint8Array(128);
    (function loop() {
      if (!fxAnalyser || !currentAudio) { return; }
      fxAnalyser.getByteTimeDomainData(buf);
      g.clearRect(0, 0, 180, 28);
      g.strokeStyle = 'rgba(91,155,208,0.85)';
      g.lineWidth = 1.4;
      g.beginPath();
      var peak = 0;
      for (var i = 0; i < 128; i++) {
        var y = 14 + ((buf[i] - 128) / 128) * 13;
        peak = Math.max(peak, Math.abs(buf[i] - 128) / 128);
        if (i === 0) g.moveTo(0, y); else g.lineTo(i * (180 / 127), y);
      }
      g.stroke();
      if (orb) orb.style.setProperty('--speak-level', peak.toFixed(2));
      waveRAF = requestAnimationFrame(loop);
    })();
  }
  function stopWave() {
    if (waveRAF) cancelAnimationFrame(waveRAF);
    waveRAF = null;
    if (waveCanvas) { waveCanvas.classList.remove('show'); var g = waveCanvas.getContext('2d'); g.clearRect(0, 0, 180, 28); }
    if (orb) orb.style.setProperty('--speak-level', '0');
  }

  // ── PHASE 2: conversational endpointing ──────────────────
  var CONTINUATIONS = /\b(and|but|so|or|because|then|also|plus|like|um|uh|hmm|well|which|with|to|the|a|of|for|if|when|that)\s*$|,\s*$/i;

  var recognition = null;
  var listening = false;
  var holdMode = false;
  var pendingText = '';
  var lastChangeAt = 0;
  var endpointTimer = null;
  var levelRAF2 = null;

  function patienceMs() { return lsNum('edith-patience', 1.4) * 1000; }

  function initRecognition() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return null;
    var r = new SR();
    r.lang = 'en-AU';
    r.interimResults = true;
    r.continuous = true;

    r.onresult = function(e) {
      var txt = '';
      for (var i = 0; i < e.results.length; i++) txt += e.results[i][0].transcript;
      txt = txt.trim();
      if (txt !== pendingText) {
        pendingText = txt;
        lastChangeAt = performance.now();
        caption('hearing: ' + txt, true);
      }
    };
    r.onerror = function(e) {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        stopListening();
        note('Mic blocked — click the lock icon in the address bar to allow it.', 8000);
      } else if (e.error !== 'no-speech' && e.error !== 'aborted') {
        note('Voice input error: ' + e.error);
      }
    };
    r.onend = function() {
      // Chrome ends recognition on its own sometimes — if we're mid-listen with
      // text pending, treat as an endpoint; if listening with nothing, restart.
      if (!listening) return;
      if (pendingText) finalizeUtterance();
      else { try { r.start(); } catch (e) {} }
    };
    return r;
  }

  async function startListening(viaHold) {
    if (!hasSTT || listening) return;
    stopSpeaking();
    recognition = recognition || initRecognition();
    if (!recognition) return;
    try { await ensureMic(); } catch (e) { /* analyser optional; SR prompts its own */ }
    stopBrowserWake();   // hand the mic recognizer to the query listener
    pendingText = '';
    lastChangeAt = performance.now();
    holdMode = !!viaHold;
    listening = true;
    try { recognition.start(); } catch (e) {}
    setOrb('listening');
    caption('listening…', true);
    runEndpointLoop();
    runMicGlow();
  }

  function stopListening(silent) {
    listening = false;
    holdMode = false;
    clearInterval(endpointTimer); endpointTimer = null;
    if (levelRAF2) cancelAnimationFrame(levelRAF2); levelRAF2 = null;
    setRing(0);
    if (recognition) { try { recognition.stop(); } catch (e) {} }
    if (orbState === 'listening') { setOrb('idle'); if (!silent) caption(''); }
    if (orb) orb.style.setProperty('--mic-level', '0');
    resumeWakeIfArmed();
  }

  function runMicGlow() {
    (function loop() {
      if (!listening) return;
      if (orb) orb.style.setProperty('--mic-level', Math.min(micRMS() * 8, 1).toFixed(2));
      levelRAF2 = requestAnimationFrame(loop);
    })();
  }

  function runEndpointLoop() {
    clearInterval(endpointTimer);
    endpointTimer = setInterval(function() {
      if (!listening) return clearInterval(endpointTimer);
      if (holdMode) { setRing(0); return; }   // hold-to-talk: release decides
      if (!pendingText) { setRing(0); return; }

      var win = patienceMs();
      if (CONTINUATIONS.test(pendingText)) win *= 2;   // linguistic continuation

      // energy VAD: resumed speech instantly resets the countdown
      if (micRMS() > 0.055) { lastChangeAt = performance.now(); setRing(0); return; }

      var elapsed = performance.now() - lastChangeAt;
      setRing(elapsed / win);
      if (elapsed >= win) finalizeUtterance();
    }, 80);
  }

  function finalizeUtterance() {
    var text = pendingText.trim();
    pendingText = '';
    setRing(1);
    stopListening(true);
    setTimeout(function() { setRing(0); }, 250);
    if (text) handleTranscript(text);
    else { setOrb('idle'); caption(''); }
  }

  // ── PHASE 4: conversation mode + flow ────────────────────
  var sessionActive = false;     // entered via wake word or boot
  var bootedThisSession = false;
  var convoTimer = null;
  var pendingBriefOffer = false;

  function convoEnabled() { return lsGet('edith-convo', '1') === '1'; }

  var SIGNOFF = /\b(thanks edith|thank you edith|that'?s all|go to sleep|goodnight edith|that'?ll be all)\b/i;

  async function handleTranscript(text) {
    if (!text) return;
    if (SIGNOFF.test(text)) {
      sessionActive = false;
      await speak('Very good, Rydel.', 'reply');
      setOrb('idle');
      return;
    }
    if (pendingBriefOffer && /^(yes|yeah|yep|sure|ok|okay|go|brief|please)\b/i.test(text)) {
      pendingBriefOffer = false;
      return runBrief();
    }
    pendingBriefOffer = false;
    if (/^(brief me|morning brief|daily brief|read my priorities)\b/i.test(text)) return runBrief();

    if (!window.JarvisChat) return;
    window.JarvisChat.openPanel();
    setOrb('thinking');
    var reply = await window.JarvisChat.ask(text, true);
    if (reply) {
      await speakInterruptible(reply, 'reply');
      afterReply();
    } else {
      setOrb('idle');
      note('No reply — check the chat panel.');
    }
  }

  // barge-in: sustained speech energy (>300ms) while EDITH talks stops her
  function speakInterruptible(text, context, opts) {
    return new Promise(function(resolve) {
      var bargeStart = null, raf = null;
      var done = false;
      function watch() {
        if (done) return;
        if (currentAudio && micAnalyser) {
          if (micRMS() > 0.08) {
            if (!bargeStart) bargeStart = performance.now();
            else if (performance.now() - bargeStart > 300) {
              stopSpeaking();
              startListening();
              done = true;
              return resolve();
            }
          } else bargeStart = null;
        }
        raf = requestAnimationFrame(watch);
      }
      watch();
      speak(text, context, opts).then(function() {
        done = true;
        if (raf) cancelAnimationFrame(raf);
        resolve();
      });
    });
  }

  function afterReply() {
    if (!convoEnabled() || !sessionActive) return;
    // soft re-listen window (~6s) — a follow-up needs no click
    clearTimeout(convoTimer);
    startListening();
    note('listening for a follow-up…', 5500);
    convoTimer = setTimeout(function() {
      if (listening && !pendingText) stopListening();
    }, 6000);
  }

  async function runBrief() {
    setOrb('thinking');
    caption('composing your brief…', true);
    try {
      var resp = await fetch('/dashboard/api/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      var data = await resp.json();
      if (data.text) {
        if (window.JarvisChat) { window.JarvisChat.openPanel(); window.JarvisChat.addAssistantMessage(data.text); }
        await speakInterruptible(data.text, 'reply');
        afterReply();
      } else { setOrb('idle'); note(data.error || 'Brief unavailable.'); }
    } catch (e) { setOrb('idle'); note('Brief failed — network?'); }
  }

  // ── PHASE 3: boot HUD + greeting ─────────────────────────
  function chime() {
    try {
      var ctx = audioCtx();
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine'; o.frequency.setValueAtTime(880, ctx.currentTime);
      o.frequency.exponentialRampToValueAtTime(1318, ctx.currentTime + 0.12);
      g.gain.setValueAtTime(0.0001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.18 * volume() || 0.0001, ctx.currentTime + 0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
      o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + 0.4);
    } catch (e) {}
  }

  var entranceAudio = null;
  async function playEntranceAudio() {
    var src = '/dashboard/static/audio/entrance.mp3';
    try {
      var head = await fetch(src, { method: 'HEAD' });
      if (!head.ok) src = '/dashboard/static/audio/entrance-default.wav';
    } catch (e) { src = '/dashboard/static/audio/entrance-default.wav'; }
    entranceAudio = new Audio(src);
    entranceAudio.volume = volume();
    entranceAudio.play().catch(function() {});
  }
  function duckEntrance() {
    if (!entranceAudio) return;
    var duck = setInterval(function() {
      if (!entranceAudio) return clearInterval(duck);
      entranceAudio.volume = Math.max(0.06, entranceAudio.volume - 0.12);
      if (entranceAudio.volume <= 0.07) clearInterval(duck);
    }, 110);
  }
  function stopEntrance() {
    if (entranceAudio) { try { entranceAudio.pause(); } catch (e) {} entranceAudio = null; }
  }

  async function bootSequence(withAudio) {
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    sessionActive = true;
    bootedThisSession = true;

    if (withAudio) playEntranceAudio();

    if (!reduced) {
      var hud = document.createElement('div');
      hud.className = 'edith-boot-hud';
      hud.innerHTML = '<div class="ebh-sweep"></div><div class="ebh-scan"></div><div class="ebh-caption">EDITH — ONLINE</div>';
      document.body.appendChild(hud);
      document.body.classList.add('boot-seq');
      var cleanup = function() {
        document.body.classList.remove('boot-seq');
        hud.remove();
        document.removeEventListener('click', skipper, true);
      };
      var skipper = function() { cleanup(); };
      setTimeout(function() { document.addEventListener('click', skipper, true); }, 150);
      setTimeout(cleanup, 3300);
      setOrb('thinking');
      await new Promise(function(r) { setTimeout(r, 2300); });
    } else {
      await new Promise(function(r) { setTimeout(r, 250); });
    }

    duckEntrance();

    // greeting: server-composed (Sydney time + live Newcastle weather + engine headline)
    var text = null;
    try {
      var resp = await fetch('/dashboard/api/greeting');
      var data = await resp.json();
      text = data.text;
    } catch (e) {}
    if (!text) {
      var hour = new Date().getHours();
      text = 'Good ' + (hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening') + ', Rydel. EDITH online. What do you need?';
    }
    if (window.JarvisChat) { window.JarvisChat.openPanel(); window.JarvisChat.addAssistantMessage(text); }
    await speakInterruptible(text, 'system', { crushFirstWord: true });
    stopEntrance();
    // mic auto-opens — the conversation is the point
    startListening();
  }

  function wakeFired() {
    chime();
    if (!bootedThisSession) return bootSequence(true);
    if (orbState === 'speaking') { stopSpeaking(); }
    sessionActive = true;
    speak('Yes, Rydel?', 'reply').then(function() { startListening(); });
  }

  // ── PHASE 1: wake word (Porcupine WASM, on-device) ───────
  var porcupine = null;
  var wakeArmed = false;
  var usingBuiltinJarvis = false;

  function wakePhrase() {
    if (CFG.picovoiceKey) return CFG.wakePpnPresent ? 'Hey Edith' : 'Jarvis';
    return 'Hey Edith';   // browser-STT fallback matches the transcript directly
  }

  function loadScript(src) {
    return new Promise(function(resolve, reject) {
      var s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  // ── Browser-STT wake fallback (interim until Picovoice approval) ──
  // Honest trade-off: this uses the browser's speech service (audio leaves the
  // device while armed), unlike Porcupine's on-device WASM. The code prefers
  // Porcupine automatically once PICOVOICE_ACCESS_KEY exists.
  var browserWake = null;
  var browserWakeActive = false;
  var WAKE_RX = /\b(hey\s+)?(edith|edith\b|jarvis)\b\s*$/i;

  function startBrowserWake() {
    if (browserWakeActive || !hasSTT) return;
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    browserWake = new SR();
    browserWake.lang = 'en-AU';
    browserWake.interimResults = true;
    browserWake.continuous = true;
    browserWake.onresult = function(e) {
      var txt = '';
      for (var i = e.results.length - 1; i >= 0 && i >= e.results.length - 2; i--) {
        txt = e.results[i][0].transcript + ' ' + txt;
      }
      if (WAKE_RX.test(txt.trim())) {
        stopBrowserWake();
        wakeFired();
      }
    };
    browserWake.onerror = function(e) {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        note('Mic blocked — wake word off.', 6000);
        lsSet('edith-wake', '0');
        wakeArmed = false; browserWakeActive = false; setOrb(orbState);
      }
    };
    browserWake.onend = function() {
      // browser ends recognition periodically — re-arm unless we stopped on purpose
      if (browserWakeActive && wakeArmed && !listening && !document.hidden) {
        try { browserWake.start(); } catch (e) {}
      }
    };
    try { browserWake.start(); browserWakeActive = true; } catch (e) {}
  }

  function stopBrowserWake() {
    browserWakeActive = false;
    if (browserWake) { try { browserWake.stop(); } catch (e) {} }
  }

  // the query listener and the wake listener can't share the mic recognizer —
  // pause wake while actively listening, resume after
  function resumeWakeIfArmed() {
    if (wakeArmed && !CFG.picovoiceKey && !listening && !document.hidden) {
      setTimeout(function() { if (wakeArmed && !listening) startBrowserWake(); }, 400);
    }
  }

  async function armWakeWord() {
    if (wakeArmed) return;
    if (!CFG.picovoiceKey) {
      if (!hasSTT) {
        note('Wake word needs Chrome.', 6000);
        lsSet('edith-wake', '0');
        refreshPanel();
        return;
      }
      try { await ensureMic(); } catch (e) {
        note('Mic blocked — click the lock icon to allow it.', 7000);
        lsSet('edith-wake', '0');
        refreshPanel();
        return;
      }
      wakeArmed = true;
      setOrb(orbState);
      startBrowserWake();
      note('Wake word armed — say "Hey Edith" (browser mode: uses the browser speech service; switches to on-device Picovoice once the key is added)', 8000);
      return;
    }
    try {
      if (!window.PorcupineWeb) {
        await loadScript('https://cdn.jsdelivr.net/npm/@picovoice/porcupine-web@3.0.3/dist/iife/index.js');
        await loadScript('https://cdn.jsdelivr.net/npm/@picovoice/web-voice-processor@4.0.9/dist/iife/index.js');
      }
      var keyword;
      if (CFG.wakePpnPresent) {
        keyword = { publicPath: CFG.wakePpnPath, label: 'Hey Edith', sensitivity: lsNum('edith-wake-sens', 0.6) };
        usingBuiltinJarvis = false;
      } else {
        keyword = { builtin: 'Jarvis', sensitivity: lsNum('edith-wake-sens', 0.6) };
        usingBuiltinJarvis = true;
      }
      porcupine = await window.PorcupineWeb.PorcupineWorker.create(
        CFG.picovoiceKey,
        [keyword],
        function() { wakeFired(); },
        { publicPath: 'https://cdn.jsdelivr.net/npm/@picovoice/porcupine-web@3.0.3/lib/common/porcupine_params.pv' }
      );
      await window.WebVoiceProcessor.WebVoiceProcessor.subscribe(porcupine);
      wakeArmed = true;
      setOrb(orbState);
      note('Wake word armed — say "' + wakePhrase() + '"' + (usingBuiltinJarvis ? ' (interim until hey_edith .ppn is added)' : ''), 6000);
    } catch (e) {
      console.error('wake word init failed:', e);
      note('Wake word unavailable (' + (e.message || 'init failed').slice(0, 60) + ') — click / hold-V still work.', 7000);
      lsSet('edith-wake', '0');
      wakeArmed = false;
      refreshPanel();
    }
  }

  async function disarmWakeWord() {
    wakeArmed = false;
    setOrb(orbState);
    stopBrowserWake();
    try {
      if (porcupine) {
        await window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
        porcupine.release();
        porcupine = null;
      }
    } catch (e) {}
    releaseMic(); // mic fully released — browser indicator goes dark
  }

  document.addEventListener('visibilitychange', function() {
    if (!wakeArmed) return;
    if (porcupine) {
      try {
        if (document.hidden) window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
        else window.WebVoiceProcessor.WebVoiceProcessor.subscribe(porcupine);
      } catch (e) {}
    } else {
      if (document.hidden) stopBrowserWake();
      else resumeWakeIfArmed();
    }
  });

  // ── Orb + keyboard ───────────────────────────────────────
  function onOrbClick() {
    if (orbState === 'speaking') return stopSpeaking();
    if (listening) {
      if (pendingText) return finalizeUtterance();
      sessionActive = false;
      return stopListening();
    }
    startListening();
  }

  function initKeys() {
    var vHeld = false;
    document.addEventListener('keydown', function(e) {
      var tag = (document.activeElement || {}).tagName;
      var typing = tag === 'INPUT' || tag === 'TEXTAREA';
      if (e.key === 'Escape') { stopSpeaking(); stopListening(); return; }
      if (typing) return;
      if ((e.key === 'v' || e.key === 'V' || (e.code === 'Space' && hasSTT)) && !vHeld && !e.metaKey && !e.ctrlKey) {
        if (e.code === 'Space') e.preventDefault();
        vHeld = true;
        startListening(true);
      }
      if ((e.key === 'b' || e.key === 'B') && !e.metaKey && !e.ctrlKey) runBrief();
      if (e.key === '?') togglePanel();
    });
    document.addEventListener('keyup', function(e) {
      if ((e.key === 'v' || e.key === 'V' || e.code === 'Space') && vHeld) {
        vHeld = false;
        if (listening && holdMode) finalizeUtterance();
      }
    });
  }

  // ── Voice panel (settings + AI character tuning + audition) ──
  function refreshPanel() {
    var el = document.getElementById('edith-panel');
    if (el) { el.remove(); togglePanel(); }
  }

  function togglePanel() {
    var el = document.getElementById('edith-panel');
    if (el) { el.remove(); return; }
    el = document.createElement('div');
    el.id = 'edith-panel';
    el.className = 'jarvis-help edith-panel';
    var wakeOn = lsGet('edith-wake', '0') === '1';
    var p = fxParams(lsGet('edith-fx-preset', 'subtle'));
    el.innerHTML =
      '<div class="jh-title">EDITH</div>' +
      '<div class="jh-row"><b>Click orb / hold V or Space</b> talk &middot; <b>Esc</b> interrupt &middot; <b>B</b> brief</div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-wake" ' + (wakeOn ? 'checked' : '') + '> &#127908; Wake word: say "' + wakePhrase() + '"' + (CFG.picovoiceKey ? (CFG.wakePpnPresent ? '' : ' <span class="ep-dim">(interim — train "Hey Edith" .ppn)</span>') : ' <span class="ep-dim">(browser mode — on-device once Picovoice key is added)</span>') + '</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-convo" ' + (lsGet('edith-convo', '1') === '1' ? 'checked' : '') + '> Conversation mode (auto re-listen)</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-cine" ' + (lsGet('edith-cinematic', '1') === '1' ? 'checked' : '') + '> Cinematic mode</label></div>' +
      '<div class="jh-row">Patience <input type="range" id="ep-patience" min="0.8" max="3" step="0.1" value="' + lsNum('edith-patience', 1.4) + '"> <span id="ep-patience-v">' + lsNum('edith-patience', 1.4).toFixed(1) + 's</span></div>' +
      '<div class="jh-row jh-controls"><label><input type="checkbox" id="ep-mute" ' + (lsGet('edith-muted', '0') === '1' ? 'checked' : '') + '> mute</label>' +
      '<label>vol <input type="range" id="ep-vol" min="0" max="1" step="0.1" value="' + lsNum('edith-vol', 1) + '"></label></div>' +
      '<div class="ep-section">AI Voice Character</div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-fx" ' + (fxEnabled() ? 'checked' : '') + '> AI processing</label></div>' +
      '<div class="jh-row ep-presets">' +
        ['subtle', 'assistant', 'system', 'off'].map(function(name) {
          var cur = lsGet('edith-fx-preset', 'subtle');
          return '<button class="ep-preset' + (cur === name ? ' active' : '') + '" data-p="' + name + '">' + name + '</button>';
        }).join('') +
      '</div>' +
      '<details class="ep-adv"><summary>advanced</summary>' +
        '<div class="jh-row">HP <input type="range" data-fx="hp" min="0" max="400" step="10" value="' + p.hp + '"></div>' +
        '<div class="jh-row">LP <input type="range" data-fx="lp" min="3000" max="16000" step="250" value="' + p.lp + '"></div>' +
        '<div class="jh-row">Resonance <input type="range" data-fx="comb" min="0" max="0.4" step="0.02" value="' + p.comb + '"></div>' +
        '<div class="jh-row">Double <input type="range" data-fx="dbl" min="0" max="0.6" step="0.02" value="' + p.dbl + '"></div>' +
        '<div class="jh-row">Reverb <input type="range" data-fx="rev" min="0" max="0.4" step="0.02" value="' + p.rev + '"></div>' +
        '<div class="jh-row">Wet <input type="range" data-fx="wet" min="0" max="0.6" step="0.02" value="' + p.wet + '"></div>' +
      '</details>' +
      '<div class="ep-section">Voice (locked: FRIDAY)</div>' +
      '<div class="jh-row"><input type="text" id="ep-voice-id" class="ep-input" placeholder="ElevenLabs voice ID (audition)" value=""></div>' +
      '<div class="jh-row ep-presets"><button id="ep-audition" class="ep-preset">audition</button>' +
      '<button id="ep-voice-set" class="ep-preset">set</button>' +
      '<button id="ep-voice-reset" class="ep-preset">reset to default</button></div>' +
      '<div class="jh-close">esc or ? to close</div>';
    document.body.appendChild(el);

    el.querySelector('#ep-wake').addEventListener('change', function() {
      lsSet('edith-wake', this.checked ? '1' : '0');
      if (this.checked) armWakeWord(); else disarmWakeWord();
    });
    el.querySelector('#ep-convo').addEventListener('change', function() { lsSet('edith-convo', this.checked ? '1' : '0'); });
    el.querySelector('#ep-cine').addEventListener('change', function() { lsSet('edith-cinematic', this.checked ? '1' : '0'); });
    el.querySelector('#ep-patience').addEventListener('input', function() {
      lsSet('edith-patience', this.value);
      el.querySelector('#ep-patience-v').textContent = parseFloat(this.value).toFixed(1) + 's';
    });
    el.querySelector('#ep-mute').addEventListener('change', function() { lsSet('edith-muted', this.checked ? '1' : '0'); });
    el.querySelector('#ep-vol').addEventListener('input', function() { lsSet('edith-vol', this.value); });
    el.querySelector('#ep-fx').addEventListener('change', function() { lsSet('edith-fx-on', this.checked ? '1' : '0'); });
    el.querySelectorAll('.ep-preset[data-p]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        lsSet('edith-fx-preset', this.dataset.p);
        lsSet('edith-fx-custom', '0');
        el.querySelectorAll('.ep-preset[data-p]').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
      });
    });
    el.querySelectorAll('[data-fx]').forEach(function(sl) {
      sl.addEventListener('input', function() {
        lsSet('edith-fx-' + this.dataset.fx, this.value);
        lsSet('edith-fx-custom', '1');
      });
    });
    el.querySelector('#ep-audition').addEventListener('click', function() {
      var vid = el.querySelector('#ep-voice-id').value.trim();
      speak(TEST_LINE, 'reply', vid ? { voiceId: vid } : {});
    });
    el.querySelector('#ep-voice-set').addEventListener('click', async function() {
      var vid = el.querySelector('#ep-voice-id').value.trim();
      if (!vid) return note('Paste a voice ID first.');
      await fetch('/dashboard/api/voice-config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ voice_id: vid }) });
      note('Voice set — next reply uses it. "reset to default" restores FRIDAY.');
      refreshVoiceStatus();
    });
    el.querySelector('#ep-voice-reset').addEventListener('click', async function() {
      await fetch('/dashboard/api/voice-config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      note('Voice reset to the locked default.');
      refreshVoiceStatus();
    });
  }

  async function refreshVoiceStatus() {
    try {
      var resp = await fetch('/dashboard/api/voice-status');
      if (resp.ok) voiceStatus = await resp.json();
    } catch (e) { voiceStatus = null; }
  }

  // ── Entrance trigger (reactor) + init ────────────────────
  function initEntranceTrigger() {
    var reactor = document.querySelector('.reactor');
    if (!reactor) return;
    reactor.style.cursor = 'pointer';
    reactor.title = 'Power up EDITH';
    reactor.addEventListener('click', function() {
      bootedThisSession = false;   // power button always replays the boot
      bootSequence(true);
    });
    if (lsGet('jarvis-entrance-invite', '0') === '1') reactor.classList.add('invite');
  }

  (async function init() {
    buildUI();
    initKeys();
    initEntranceTrigger();
    await refreshVoiceStatus();
    if (lsGet('edith-wake', '0') === '1') armWakeWord();
  })();

})();
