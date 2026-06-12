/* edith.js — EDITH voice suite, single-audio-authority rebuild.
   One brain (the chat endpoint via window.JarvisChat). One AudioContext.
   One mixer. One state machine. Every sound in this file is created and
   started ONLY through audioManager — the iron rule: one voice at a time.
   No metric is computed here — engines only. */
(function() {
  'use strict';

  var CFG = window.__EDITH_CFG__ || {};
  var TEST_LINE = 'Good evening, Rydel. EDITH online. Cash position is ninety-one thousand dollars; runway three point six months.';

  // ── utils ────────────────────────────────────────────────
  function lsGet(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function lsNum(k, d) { var v = parseFloat(lsGet(k, '')); return isNaN(v) ? d : v; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function log() { try { console.log.apply(console, ['[EDITH]'].concat([].slice.call(arguments))); } catch (e) {} }

  var hasSTT = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  // ═════════════════════════════════════════════════════════
  //  STATE MACHINE — guarded transitions; wrong-state triggers
  //  are ignored and logged. This kills the double-greeting.
  // ═════════════════════════════════════════════════════════
  var S = { IDLE: 'idle', BOOTING: 'booting', GREETING: 'greeting',
            LISTENING: 'listening', THINKING: 'thinking', SPEAKING: 'speaking' };
  var ALLOWED = {
    idle:      [S.BOOTING, S.LISTENING, S.SPEAKING],
    booting:   [S.GREETING, S.IDLE],
    greeting:  [S.LISTENING, S.IDLE, S.SPEAKING],
    listening: [S.THINKING, S.IDLE, S.BOOTING, S.SPEAKING],
    thinking:  [S.SPEAKING, S.IDLE, S.LISTENING],
    speaking:  [S.LISTENING, S.IDLE, S.THINKING],
  };
  var state = S.IDLE;
  function transition(to, why) {
    if (state === to) return true;
    if ((ALLOWED[state] || []).indexOf(to) === -1) {
      log('transition BLOCKED', state, '→', to, '(' + (why || '') + ')');
      return false;
    }
    log('state', state, '→', to, why ? '(' + why + ')' : '');
    var from = state;
    state = to;
    setOrb(to === S.BOOTING || to === S.GREETING ? 'thinking' : to);
    try {
      window.dispatchEvent(new CustomEvent('edith:state', { detail: { from: from, to: to, why: why } }));
    } catch (e) {}
    return true;
  }

  // ═════════════════════════════════════════════════════════
  //  AUDIO MANAGER — the single authority. Mixer: master →
  //  voice(1.0) / sfx(0.25) / music(0.5). One voice at a time.
  // ═════════════════════════════════════════════════════════
  var audioManager = (function() {
    var ctx = null;
    var master, chVoice, chSfx, chMusic, sfxLimiter, voiceAnalyser;
    var currentUtterance = 0;     // token: stale playback discards itself
    var currentEl = null;         // the live TTS <audio> element
    var musicEl = null;
    var speakingFlag = false;

    function mixDefault(name) { return { master: 1.0, voice: 1.0, sfx: 0.25, music: 0.5 }[name]; }
    function mixGet(name) { return Math.min(1.5, Math.max(0, lsNum('edith-mix-' + name, mixDefault(name)))); }

    function ensure() {
      if (ctx) { if (ctx.state === 'suspended') ctx.resume(); return ctx; }
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain();
      master.gain.value = mixGet('master');
      master.connect(ctx.destination);
      chVoice = ctx.createGain(); chVoice.gain.value = mixGet('voice');
      chMusic = ctx.createGain(); chMusic.gain.value = mixGet('music');
      // sfx runs through a limiter so a synth can never blast full-scale
      chSfx = ctx.createGain(); chSfx.gain.value = mixGet('sfx');
      sfxLimiter = ctx.createDynamicsCompressor();
      sfxLimiter.threshold.value = -14; sfxLimiter.knee.value = 6;
      sfxLimiter.ratio.value = 12; sfxLimiter.attack.value = 0.002; sfxLimiter.release.value = 0.18;
      voiceAnalyser = ctx.createAnalyser(); voiceAnalyser.fftSize = 256;
      chVoice.connect(voiceAnalyser); voiceAnalyser.connect(master);
      chSfx.connect(sfxLimiter); sfxLimiter.connect(master);
      chMusic.connect(master);
      return ctx;
    }

    function setMix(name, v) {
      lsSet('edith-mix-' + name, String(v));
      if (!ctx) return;
      var node = { master: master, voice: chVoice, sfx: chSfx, music: chMusic }[name];
      if (node) node.gain.setTargetAtTime(parseFloat(v), ctx.currentTime, 0.05);
    }

    // ── ducking automation: voice starts → sfx+music dip; release after ──
    var duckTimer = null;
    function duck() {
      if (!ctx) return;
      clearTimeout(duckTimer);
      chMusic.gain.cancelScheduledValues(ctx.currentTime);
      chMusic.gain.linearRampToValueAtTime(Math.min(mixGet('music'), 0.15), ctx.currentTime + 0.15);
      chSfx.gain.linearRampToValueAtTime(Math.min(mixGet('sfx'), 0.1), ctx.currentTime + 0.15);
    }
    function release() {
      if (!ctx) return;
      clearTimeout(duckTimer);
      duckTimer = setTimeout(function() {
        if (!ctx || speakingFlag) return;
        chMusic.gain.setTargetAtTime(mixGet('music'), ctx.currentTime, 0.2);
        chSfx.gain.setTargetAtTime(mixGet('sfx'), ctx.currentTime, 0.2);
      }, 400);
    }

    // ── the voice effects graph (Phase 2) — MANDATORY routing ──
    // source → HP/LP → comb resonance → micro-double → plate → wet/dry → voice ch
    // EDITH character: compressor (even = synthetic), bandpass, +2.5dB sheen,
    // comb, forward micro-double, capped shimmer ring-mod, bright plate.
    var PRESETS = {
      off:    { wet: 0.00, hp: 0,   lp: 20000, shelf: 0,   comb: 0,    dbl: 0,    shim: 0,    rev: 0,    comp: false },
      subtle: { wet: 0.12, hp: 120, lp: 8000,  shelf: 1.5, comb: 0.12, dbl: 0.25, shim: 0,    rev: 0.12, comp: true },
      edith:  { wet: 0.28, hp: 140, lp: 9000,  shelf: 2.5, comb: 0.15, dbl: 0.30, shim: 0.03, rev: 0.14, comp: true },
      system: { wet: 0.45, hp: 200, lp: 5800,  shelf: 3.0, comb: 0.26, dbl: 0.44, shim: 0.05, rev: 0.22, comp: true },
    };
    function fxParams(presetName) {
      var p = Object.assign({}, PRESETS[presetName] || PRESETS.edith);
      if (lsGet('edith-fx-custom', '0') === '1') {
        ['wet', 'hp', 'lp', 'shelf', 'comb', 'dbl', 'shim', 'rev'].forEach(function(k) {
          var v = lsGet('edith-fx-' + k, null);
          if (v != null) p[k] = parseFloat(v);
        });
        p.shim = Math.min(0.10, p.shim || 0);   // >0.08 = Dalek; hard cap
      }
      return p;
    }
    function fxEnabled() { return lsGet('edith-fx-on', '1') === '1'; }
    function activePreset(context) {
      if (!fxEnabled()) return 'off';
      if (context === 'system') return 'system';
      var stored = lsGet('edith-fx-preset', 'edith');
      if (!PRESETS[stored]) stored = 'edith';   // stale keys resolve to the default, never silently down
      return stored;
    }
    function makeImpulse(c, ms) {
      var len = Math.max(1, Math.round(c.sampleRate * ms / 1000));
      var buf = c.createBuffer(1, len, c.sampleRate);
      var d = buf.getChannelData(0);
      for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.2);
      return buf;
    }
    function routeThroughFx(el, presetName, crushFirstWord, fxOverride) {
      var c = ensure();
      var p = fxOverride || fxParams(presetName);
      log('fx route:', presetName, 'wet=' + p.wet, 'ctx=' + c.state);
      var src = c.createMediaElementSource(el);

      // COMPRESSOR first — the whole signal gets the ultra-even AI dynamics
      var head = src;
      if (p.comp !== false) {
        var comp = c.createDynamicsCompressor();
        comp.threshold.value = -28; comp.ratio.value = 4;
        comp.attack.value = 0.005; comp.release.value = 0.15;
        src.connect(comp);
        head = comp;
      }

      // dry path FIRST — an exception below can never mute the voice
      var dryG = c.createGain(); dryG.gain.value = 1 - p.wet * 0.5;
      head.connect(dryG); dryG.connect(chVoice);
      try {
        var hp = c.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = p.hp || 1;
        var lp = c.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = p.lp;
        head.connect(hp); hp.connect(lp);

        // presence sheen: the crisp digital edge
        var shelf = c.createBiquadFilter(); shelf.type = 'highshelf';
        shelf.frequency.value = 6500; shelf.gain.value = p.shelf || 0;
        lp.connect(shelf);

        var combDelay = c.createDelay(0.05); combDelay.delayTime.value = 0.005;
        var combFb = c.createGain(); combFb.gain.value = Math.min(0.5, p.comb * 2.2);
        var combMix = c.createGain(); combMix.gain.value = p.comb;
        shelf.connect(combDelay); combDelay.connect(combFb); combFb.connect(combDelay);
        combDelay.connect(combMix);

        var dbl = c.createDelay(0.06); dbl.delayTime.value = 0.014;
        var lfo = c.createOscillator(); lfo.frequency.value = 0.8;
        var lfoG = c.createGain(); lfoG.gain.value = 0.00075;   // ≈10 cents perceived
        lfo.connect(lfoG); lfoG.connect(dbl.delayTime); lfo.start();
        var dblMix = c.createGain(); dblMix.gain.value = p.dbl;
        shelf.connect(dbl); dbl.connect(dblMix);

        // shimmer: very low-mix ring-mod ~3kHz — a glassy synthetic glint
        var shimMix = c.createGain(); shimMix.gain.value = 0;
        if (p.shim > 0) {
          var ring = c.createGain(); ring.gain.value = 0;
          var shimOsc = c.createOscillator(); shimOsc.frequency.value = 3000;
          shimOsc.connect(ring.gain); shimOsc.start();
          shelf.connect(ring);
          shimMix.gain.value = Math.min(0.10, p.shim);
          ring.connect(shimMix);
        }

        var conv = c.createConvolver(); conv.buffer = makeImpulse(c, 100);
        var revMix = c.createGain(); revMix.gain.value = p.rev;
        shelf.connect(conv); conv.connect(revMix);

        var wet = c.createGain(); wet.gain.value = p.wet;
        shelf.connect(wet); combMix.connect(wet); dblMix.connect(wet);
        shimMix.connect(wet); revMix.connect(wet);
        wet.connect(chVoice);

        if (crushFirstWord) {
          var shaper = c.createWaveShaper();
          var curve = new Float32Array(256);
          for (var i = 0; i < 256; i++) curve[i] = Math.round(((i / 128) - 1) * 6) / 6;
          shaper.curve = curve;
          var crushG = c.createGain(); crushG.gain.value = 0.5;
          shelf.connect(shaper); shaper.connect(crushG); crushG.connect(chVoice);
          setTimeout(function() { try { crushG.gain.setTargetAtTime(0, c.currentTime, 0.02); } catch (e) {} }, 80);
        }
        return true;
      } catch (e) {
        log('fx graph failed — playing clean:', e.message);
        note('AI filter bypassed this line (' + (e.message || 'audio error').slice(0, 40) + ')');
        return false;
      }
    }

    // ── speak: THE IRON RULE — hard-stop anything current, then speak ──
    // Fallback gating: browser TTS fires ONLY on confirmed ElevenLabs failure
    // (HTTP/element error, or no first audio byte within FALLBACK_TIMEOUT_MS).
    // A late-arriving ElevenLabs stream after fallback started is DISCARDED.
    var FALLBACK_TIMEOUT_MS = 4000;

    function speak(text, opts) {
      opts = opts || {};
      return new Promise(function(resolve) {
        if (!text) return resolve();
        stopVoice();                       // one voice at a time, no exceptions
        var my = ++currentUtterance;       // stale playback self-discards
        speakingFlag = true;
        ensure();
        duck();
        startWave();
        caption(text, true);

        var settled = false;               // exactly ONE engine speaks
        var done = function(engine) {
          if (currentUtterance !== my) return;     // an interrupt already cleaned up
          speakingFlag = false;
          currentEl = null;
          stopWave();
          caption('');
          release();
          resolve(engine);
        };

        if (!voiceStatus) {
          // resolve the status rather than guessing an engine
          refreshVoiceStatus().then(function() {
            if (currentUtterance !== my) return resolve();
            speakingFlag = false;
            speak(text, opts).then(resolve);
          });
          return;
        }
        if (!voiceStatus.elevenlabs_configured) {
          fallbackBadge('ElevenLabs not configured');
          browserSpeak(text, my).then(function() { done('fallback'); });
          return;
        }

        var url = '/dashboard/api/tts?text=' + encodeURIComponent(text);
        if (opts.voiceId) url += '&voice_id=' + encodeURIComponent(opts.voiceId);
        try { window.dispatchEvent(new CustomEvent('edith:tts', { detail: { phase: 'synth', text: text } })); } catch (ev) {}
        var el = new Audio(url);
        el.volume = 1;                     // gain lives in the mixer, not the element
        currentEl = el;
        var presetName = opts.fxOverride ? 'probe' : activePreset(opts.context);
        var routed = routeThroughFx(el, presetName, !!opts.crushFirstWord, opts.fxOverride);
        if (!routed) log('utterance playing without fx');
        fxBadge(routed ? (presetName === 'off' ? 'OFF' : presetName.toUpperCase()) : 'BYPASS');

        // bypass self-detection: element advancing while the post-fx analyser is
        // silent = audio escaping the graph. Detect, badge, and report.
        var bypassCheck = setTimeout(function() {
          if (currentUtterance !== my || !voiceAnalyser) return;
          if (el.currentTime > 1 && !el.paused) {
            var b = new Uint8Array(voiceAnalyser.fftSize);
            voiceAnalyser.getByteTimeDomainData(b);
            var peak = 0;
            for (var i = 0; i < b.length; i++) peak = Math.max(peak, Math.abs(b[i] - 128));
            if (peak < 2) {
              log('BYPASS DETECTED: element playing but post-fx analyser silent');
              fxBadge('BYPASS!');
              note('FX routing bypass detected — report this. Audio is playing outside the graph.', 8000);
            } else {
              log('routing verified: post-fx analyser carrying signal (peak ' + peak + ')');
            }
          }
        }, 1500);

        var firstByte = false;
        var fellBack = false;
        var watchdog = setTimeout(function() {
          if (firstByte || settled || currentUtterance !== my) return;
          fellBack = true;
          log('ElevenLabs first-byte timeout (' + FALLBACK_TIMEOUT_MS + 'ms) — confirmed failure');
          try { el.pause(); } catch (e) {}
          fallbackBadge('timeout');
          browserSpeak(text, my).then(function() { settled = true; done('fallback'); });
        }, FALLBACK_TIMEOUT_MS);

        el.addEventListener('playing', function() {
          if (fellBack) { try { el.pause(); } catch (e) {} return; }   // late success → discard
          firstByte = true;
          clearTimeout(watchdog);
          try { window.dispatchEvent(new CustomEvent('edith:tts', { detail: { phase: 'playing' } })); } catch (ev) {}
        });
        el.addEventListener('ended', function() {
          if (settled || fellBack) return;
          settled = true; clearTimeout(watchdog); clearTimeout(bypassCheck);
          done('elevenlabs');
        });
        el.addEventListener('error', function() {
          if (settled || fellBack || currentUtterance !== my) return;
          clearTimeout(watchdog);
          if (el.currentTime > 0.4) { settled = true; done('elevenlabs'); return; }  // mostly played
          fellBack = true;
          fallbackBadge('stream error');
          browserSpeak(text, my).then(function() { settled = true; done('fallback'); });
        });
        el.play().catch(function(err) {
          if (settled || fellBack || currentUtterance !== my) return;
          clearTimeout(watchdog);
          if (err && err.name === 'NotAllowedError') {
            settled = true;
            note('Browser blocked audio without a click — tap anywhere, then ask again.', 8000);
            done('blocked');
            return;
          }
          fellBack = true;
          fallbackBadge('play failed');
          browserSpeak(text, my).then(function() { settled = true; done('fallback'); });
        });
      });
    }

    function browserSpeak(text, token) {
      return new Promise(function(resolve) {
        if (!window.speechSynthesis) { note('Voice unavailable — text only.'); return resolve(); }
        var u = new SpeechSynthesisUtterance(text);
        u.volume = Math.min(1, mixGet('voice') * mixGet('master'));
        u.rate = 1.02; u.pitch = 1.05;
        var voices = speechSynthesis.getVoices() || [];
        // never the default: female en-AU/en-GB by name heuristics first
        var v = voices.find(function(x) { return /karen|catherine|moira|serena|female/i.test(x.name) && /^en/i.test(x.lang); })
             || voices.find(function(x) { return /en[-_](AU|GB)/i.test(x.lang); });
        if (v) u.voice = v;
        var guard = setInterval(function() {
          if (token !== currentUtterance) { speechSynthesis.cancel(); clearInterval(guard); resolve(); }
        }, 150);
        u.onend = function() { clearInterval(guard); resolve(); };
        u.onerror = function() { clearInterval(guard); resolve(); };
        speechSynthesis.speak(u);
      });
    }

    function stopVoice() {
      currentUtterance++;
      if (currentEl) { try { currentEl.pause(); } catch (e) {} currentEl = null; }
      if (window.speechSynthesis) speechSynthesis.cancel();
      speakingFlag = false;
      stopWave();
      release();
    }

    // ── music channel ──
    function playMusic(url) {
      stopMusic();
      var c = ensure();
      musicEl = new Audio(url);
      musicEl.volume = 1;
      try {
        var src = c.createMediaElementSource(musicEl);
        src.connect(chMusic);
      } catch (e) { musicEl.volume = mixGet('music'); }   // raw fallback, still leveled
      musicEl.play().catch(function(err) { log('music blocked/failed:', err && err.name); });
      return musicEl;
    }
    function fadeOutMusic(seconds) {
      if (!musicEl || !ctx) return stopMusic();
      chMusic.gain.cancelScheduledValues(ctx.currentTime);
      chMusic.gain.setTargetAtTime(0.0001, ctx.currentTime, (seconds || 2) / 4);
      setTimeout(function() {
        stopMusic();
        if (ctx) chMusic.gain.setValueAtTime(mixGet('music'), ctx.currentTime);
      }, (seconds || 2) * 1000);
    }
    function stopMusic() {
      if (musicEl) { try { musicEl.pause(); } catch (e) {} musicEl = null; }
    }

    // ── sfx: synthesized, peak-limited, polite by construction (Phase 3) ──
    function reactor() {
      _markSfx();
      try {
        var c = ensure();
        var t0 = c.currentTime;
        var out = c.createGain(); out.gain.value = 0.8; out.connect(chSfx);

        // (a) low hum: detuned sine pair fading in
        [55, 55.7].forEach(function(f) {
          var o = c.createOscillator(); o.type = 'sine'; o.frequency.value = f;
          var g = c.createGain();
          g.gain.setValueAtTime(0.0001, t0);
          g.gain.linearRampToValueAtTime(0.25, t0 + 0.8);
          g.gain.setTargetAtTime(0.0001, t0 + 1.7, 0.25);
          o.connect(g); g.connect(out); o.start(t0); o.stop(t0 + 2.4);
        });
        // (b) the charge: saw 110→880 through an opening lowpass, slight stereo
        [-0.3, 0.3].forEach(function(pan, idx) {
          var o = c.createOscillator(); o.type = 'sawtooth';
          o.frequency.setValueAtTime(110 * (idx ? 1.003 : 1), t0 + 0.2);
          o.frequency.exponentialRampToValueAtTime(880, t0 + 1.4);
          var f = c.createBiquadFilter(); f.type = 'lowpass'; f.Q.value = 4;
          f.frequency.setValueAtTime(400, t0 + 0.2);
          f.frequency.exponentialRampToValueAtTime(6000, t0 + 1.4);
          var g = c.createGain();
          g.gain.setValueAtTime(0.0001, t0 + 0.2);
          g.gain.linearRampToValueAtTime(0.16, t0 + 1.0);
          g.gain.setTargetAtTime(0.0001, t0 + 1.5, 0.12);
          var p = c.createStereoPanner ? c.createStereoPanner() : null;
          o.connect(f); f.connect(g);
          if (p) { p.pan.value = pan; g.connect(p); p.connect(out); } else g.connect(out);
          o.start(t0 + 0.2); o.stop(t0 + 1.8);
        });
        // (c) noise riser underneath
        var nb = c.createBuffer(1, c.sampleRate * 1.4, c.sampleRate);
        var nd = nb.getChannelData(0);
        for (var i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;
        var n = c.createBufferSource(); n.buffer = nb;
        var nf = c.createBiquadFilter(); nf.type = 'bandpass'; nf.Q.value = 1.8;
        nf.frequency.setValueAtTime(400, t0 + 0.2);
        nf.frequency.exponentialRampToValueAtTime(5000, t0 + 1.5);
        var ng = c.createGain();
        ng.gain.setValueAtTime(0.0001, t0 + 0.2);
        ng.gain.linearRampToValueAtTime(0.07, t0 + 1.2);
        ng.gain.setTargetAtTime(0.0001, t0 + 1.5, 0.15);
        n.connect(nf); nf.connect(ng); ng.connect(out); n.start(t0 + 0.2);
        // (d) resolve: harmonic bloom + gentle high chime as ONLINE lands
        [[440, 0.10], [554.4, 0.08], [659.3, 0.08], [880, 0.05]].forEach(function(pair) {
          var o = c.createOscillator(); o.type = 'sine'; o.frequency.value = pair[0];
          var g = c.createGain();
          g.gain.setValueAtTime(0.0001, t0 + 1.45);
          g.gain.linearRampToValueAtTime(pair[1], t0 + 1.6);
          g.gain.setTargetAtTime(0.0001, t0 + 1.9, 0.3);
          o.connect(g); g.connect(out); o.start(t0 + 1.45); o.stop(t0 + 2.5);
        });
        var ch = c.createOscillator(); ch.type = 'sine';
        ch.frequency.setValueAtTime(1318, t0 + 1.5);
        ch.frequency.exponentialRampToValueAtTime(2637, t0 + 1.62);
        var chg = c.createGain();
        chg.gain.setValueAtTime(0.0001, t0 + 1.5);
        chg.gain.linearRampToValueAtTime(0.12, t0 + 1.56);
        chg.gain.setTargetAtTime(0.0001, t0 + 1.7, 0.2);
        ch.connect(chg); chg.connect(out); ch.start(t0 + 1.5); ch.stop(t0 + 2.3);
      } catch (e) { log('reactor synth failed:', e.message); }
    }

    function chime(kind) {
      _markSfx();
      try {
        var c = ensure();
        var t0 = c.currentTime;
        var o = c.createOscillator(); o.type = 'sine';
        var g = c.createGain();
        if (kind === 'ack') {
          o.frequency.setValueAtTime(1046, t0);
          o.frequency.exponentialRampToValueAtTime(1568, t0 + 0.1);
        } else if (kind === 'clap') {
          // lights-on: two quick snaps
          o.frequency.setValueAtTime(1568, t0);
          o.frequency.setValueAtTime(1046, t0 + 0.07);
          o.frequency.setValueAtTime(1568, t0 + 0.14);
        } else {
          o.frequency.setValueAtTime(880, t0);
          o.frequency.exponentialRampToValueAtTime(1318, t0 + 0.12);
        }
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.linearRampToValueAtTime(0.35, t0 + 0.03);
        g.gain.setTargetAtTime(0.0001, t0 + 0.18, 0.08);
        o.connect(g); g.connect(chSfx); o.start(t0); o.stop(t0 + 0.5);
      } catch (e) {}
    }

    // ── UI sound kit (Phase 4): synthesized, tiny, behind the toggle ──
    function uiOn() { return lsGet('edith-ui-sounds', document.body.classList.contains('focus-mode') ? '0' : '1') === '1'; }

    var humNodes = null;
    function startHum() {
      if (!uiOn() || humNodes) return;
      try {
        var c = ensure();
        var nb = c.createBuffer(1, c.sampleRate * 2, c.sampleRate);
        var nd = nb.getChannelData(0);
        for (var i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;
        var n = c.createBufferSource(); n.buffer = nb; n.loop = true;
        var nf = c.createBiquadFilter(); nf.type = 'bandpass'; nf.frequency.value = 800; nf.Q.value = 2;
        var ng = c.createGain(); ng.gain.value = 0.04;
        var o = c.createOscillator(); o.type = 'sine'; o.frequency.value = 62;
        var og = c.createGain(); og.gain.value = 0.05;
        var lfo = c.createOscillator(); lfo.frequency.value = 1.4;
        var lg = c.createGain(); lg.gain.value = 0.025;
        lfo.connect(lg); lg.connect(og.gain);
        n.connect(nf); nf.connect(ng); ng.connect(chSfx);
        o.connect(og); og.connect(chSfx);
        n.start(); o.start(); lfo.start();
        humNodes = { n: n, o: o, lfo: lfo, ng: ng, og: og };
      } catch (e) {}
    }
    function stopHum() {
      if (!humNodes) return;
      try {
        var c = ensure();
        humNodes.ng.gain.setTargetAtTime(0.0001, c.currentTime, 0.06);
        humNodes.og.gain.setTargetAtTime(0.0001, c.currentTime, 0.06);
        var h = humNodes;
        setTimeout(function() { try { h.n.stop(); h.o.stop(); h.lfo.stop(); } catch (e) {} }, 300);
      } catch (e) {}
      humNodes = null;
    }

    function uiTick() {
      if (!uiOn()) return;
      _markSfx();
      try {
        var c = ensure(); var t0 = c.currentTime;
        var o = c.createOscillator(); o.type = 'square'; o.frequency.value = 2200;
        var g = c.createGain();
        g.gain.setValueAtTime(0.03, t0);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.012);
        o.connect(g); g.connect(chSfx); o.start(t0); o.stop(t0 + 0.02);
      } catch (e) {}
    }
    function uiConfirm() {
      if (!uiOn()) return;
      _markSfx();
      try {
        var c = ensure(); var t0 = c.currentTime;
        [880, 1318].forEach(function(f, i) {
          var o = c.createOscillator(); o.type = 'sine'; o.frequency.value = f;
          var g = c.createGain();
          g.gain.setValueAtTime(0.0001, t0 + i * 0.06);
          g.gain.linearRampToValueAtTime(0.06, t0 + i * 0.06 + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.06 + 0.12);
          o.connect(g); g.connect(chSfx); o.start(t0 + i * 0.06); o.stop(t0 + i * 0.06 + 0.15);
        });
      } catch (e) {}
    }
    function uiComplete() {
      if (!uiOn()) return;
      chime('ack');
    }
    function uiError() {
      if (!uiOn()) return;
      _markSfx();
      try {
        var c = ensure(); var t0 = c.currentTime;
        var o = c.createOscillator(); o.type = 'sawtooth'; o.frequency.value = 110;
        var f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = 400;
        var g = c.createGain();
        g.gain.setValueAtTime(0.05, t0);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.12);
        o.connect(f); f.connect(g); g.connect(chSfx); o.start(t0); o.stop(t0 + 0.14);
      } catch (e) {}
    }

    var _lastSfxAt = 0;
    function _markSfx() { _lastSfxAt = performance.now(); }
    function isOutputting() {
      if (speakingFlag) return true;
      if (musicEl && !musicEl.paused) return true;
      if (humNodes) return true;
      return performance.now() - _lastSfxAt < 400;
    }

    function stopAll() { stopVoice(); stopMusic(); stopHum(); }

    return {
      ensure: ensure, speak: speak, stopVoice: stopVoice, stopAll: stopAll,
      playMusic: playMusic, fadeOutMusic: fadeOutMusic, stopMusic: stopMusic,
      reactor: reactor, chime: chime, setMix: setMix, mixGet: mixGet,
      fxParams: fxParams, fxEnabled: fxEnabled,
      startHum: startHum, stopHum: stopHum,
      uiTick: uiTick, uiConfirm: uiConfirm, uiComplete: uiComplete, uiError: uiError,
      isOutputting: isOutputting,
      isSpeaking: function() { return speakingFlag; },
      analyser: function() { return voiceAnalyser; },
    };
  })();

  // probe parameter sets (fxOverride payloads)
  var PROBE_RAW = { wet: 0, hp: 0, lp: 20000, shelf: 0, comb: 0, dbl: 0, shim: 0, rev: 0, comp: false };
  var PROBE_MUFFLE = { wet: 1, hp: 0, lp: 300, shelf: 0, comb: 0, dbl: 0, shim: 0, rev: 0, comp: false };
  function audioManagerSampleRate() {
    try { return audioManager.ensure().sampleRate; } catch (e) { return 44100; }
  }

  // ── shared voice status ──────────────────────────────────
  var voiceStatus = null;
  var lastSpokenText = '';
  async function refreshVoiceStatus() {
    try {
      var resp = await fetch('/dashboard/api/voice-status');
      if (resp.ok) voiceStatus = await resp.json();
    } catch (e) { voiceStatus = null; }
  }

  function fallbackBadge(reason) {
    note('voice fallback (' + reason + ')', 6000);
    fxBadge('FALLBACK');
  }

  // speak wrapper: tracks transcript for the echo filter + latency metric
  var _speakStartedAt = 0;
  function say(text, context, opts) {
    lastSpokenText = text;
    _speakStartedAt = performance.now();
    transition(S.SPEAKING, 'say');
    return audioManager.speak(text, Object.assign({ context: context }, opts || {}));
  }

  // ═════════════════════════════════════════════════════════
  //  UI: orb, captions, notes, wave, brackets
  // ═════════════════════════════════════════════════════════
  var orb, ringEl, captionEl, noteEl, waveCanvas, fxBadgeEl;

  function fxBadge(label) {
    if (!fxBadgeEl) return;
    fxBadgeEl.textContent = 'FX: ' + label;
    fxBadgeEl.className = 'edith-fx-badge show' +
      (label === 'OFF' || label === 'BYPASS' || label === 'BYPASS!' || label === 'FALLBACK' ? ' warn' : '');
    clearTimeout(fxBadgeEl._t);
    fxBadgeEl._t = setTimeout(function() { fxBadgeEl.classList.remove('show'); }, 6000);
  }

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
    captionEl.id = 'jarvis-caption'; captionEl.className = 'jarvis-caption';
    document.body.appendChild(captionEl);

    noteEl = document.createElement('div');
    noteEl.id = 'jarvis-note'; noteEl.className = 'jarvis-note';
    document.body.appendChild(noteEl);

    waveCanvas = document.createElement('canvas');
    waveCanvas.id = 'edith-wave'; waveCanvas.className = 'edith-wave';
    waveCanvas.width = 180; waveCanvas.height = 28;
    document.body.appendChild(waveCanvas);

    fxBadgeEl = document.createElement('div');
    fxBadgeEl.className = 'edith-fx-badge';
    document.body.appendChild(fxBadgeEl);

    var brackets = document.createElement('div');
    brackets.id = 'edith-brackets'; brackets.className = 'edith-brackets';
    brackets.innerHTML = '<i class="tl"></i><i class="tr"></i><i class="bl"></i><i class="br"></i>';
    document.body.appendChild(brackets);

    orb.addEventListener('click', onOrbClick);
    if (!hasSTT) { orb.classList.add('no-stt'); note('Voice input needs Chrome — EDITH can still speak.', 6000); }
  }

  function setOrb(visual) {
    if (orb) orb.className = 'jarvis-orb ' + visual + (hasSTT ? '' : ' no-stt') +
      ((wakeArmed || clapArmed) ? ' armed' : '') + (sessionActive ? ' session' : '');
  }
  function setSessionFx(on) {
    if (lsGet('edith-cinematic', '1') !== '1') on = false;
    document.body.classList.toggle('edith-session', !!on);
  }
  function setRing(p) {
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

  // SPEAKING wave + orb pulse read the POST-effects voice channel
  var waveRAF = null;
  function startWave() {
    if (!waveCanvas || lsGet('edith-cinematic', '1') !== '1') return;
    var an = audioManager.analyser();
    if (!an) return;
    waveCanvas.classList.add('show');
    var g = waveCanvas.getContext('2d');
    var buf = new Uint8Array(128);
    (function loop() {
      if (!audioManager.isSpeaking()) return;
      an.getByteTimeDomainData(buf);
      g.clearRect(0, 0, 180, 28);
      g.strokeStyle = 'rgba(91,155,208,0.85)'; g.lineWidth = 1.4;
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
    if (waveCanvas) { waveCanvas.classList.remove('show'); waveCanvas.getContext('2d').clearRect(0, 0, 180, 28); }
    if (orb) orb.style.setProperty('--speak-level', '0');
  }

  // ── mic level (endpointing VAD + listening glow) ─────────
  var micStream = null, micAnalyser = null, micBuf = null;
  async function ensureMic() {
    if (micStream) return micStream;
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    var c = audioManager.ensure();
    var src = c.createMediaStreamSource(micStream);
    micAnalyser = c.createAnalyser();
    micAnalyser.fftSize = 2048;                 // ~46ms window: a 12ms clap can't fall between frames
    micAnalyser.smoothingTimeConstant = 0.3;    // fresher spectrum for the transient flatness check
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
  function micPeak() {
    if (!micAnalyser) return 0;
    micAnalyser.getByteTimeDomainData(micBuf);
    var peak = 0;
    for (var i = 0; i < micBuf.length; i++) { var d = Math.abs((micBuf[i] - 128) / 128); if (d > peak) peak = d; }
    return peak;
  }

  // ═════════════════════════════════════════════════════════
  //  ENDPOINTING (Phase 6 — preserved): adaptive silence ×
  //  continuation cues × energy VAD; ring shows the countdown
  // ═════════════════════════════════════════════════════════
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
    r.lang = 'en-AU'; r.interimResults = true; r.continuous = true;
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
      if (!listening) return;
      if (pendingText) finalizeUtterance();
      else { try { r.start(); } catch (e) {} }
    };
    return r;
  }

  async function startListening(viaHold) {
    if (!hasSTT || listening) return;
    if (!transition(S.LISTENING, viaHold ? 'hold' : 'listen')) return;
    audioManager.stopVoice();
    stopBrowserWake();
    recognition = recognition || initRecognition();
    if (!recognition) return;
    try { await ensureMic(); } catch (e) {}
    pendingText = '';
    lastChangeAt = performance.now();
    holdMode = !!viaHold;
    listening = true;
    try { recognition.start(); } catch (e) {}
    caption('listening…', true);
    runEndpointLoop();
    runMicGlow();
  }

  function stopListening(silent) {
    listening = false; holdMode = false;
    clearInterval(endpointTimer); endpointTimer = null;
    if (levelRAF2) cancelAnimationFrame(levelRAF2); levelRAF2 = null;
    setRing(0);
    if (recognition) { try { recognition.stop(); } catch (e) {} }
    if (state === S.LISTENING) transition(S.IDLE, 'listen end');
    if (!silent) caption('');
    if (orb) orb.style.setProperty('--mic-level', '0');
    setTimeout(resumeWakeIfArmed, 600);
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
      if (holdMode) { setRing(0); return; }
      if (!pendingText) { setRing(0); return; }
      var win = patienceMs();
      if (CONTINUATIONS.test(pendingText)) win *= 2;
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
    else caption('');
  }

  // ═════════════════════════════════════════════════════════
  //  CONVERSATION FLOW (Phase 6)
  // ═════════════════════════════════════════════════════════
  var sessionActive = false;
  var bootedThisSession = false;
  var convoTimer = null;
  var pendingBriefOffer = false;
  var SIGNOFF = /\b(thanks edith|thank you edith|that'?s all|go to sleep|goodnight edith|that'?ll be all)\b/i;

  function convoEnabled() { return lsGet('edith-convo', '1') === '1'; }

  function _isSelfEcho(text) {
    if (!lastSpokenText) return false;
    var t = text.toLowerCase().replace(/[^a-z0-9 ]/g, '');
    var s = lastSpokenText.toLowerCase().replace(/[^a-z0-9 ]/g, '');
    if (t.length < 8) return false;
    return s.indexOf(t) !== -1 || t.indexOf(s.slice(0, 60)) !== -1;
  }

  async function handleTranscript(text) {
    if (!text) return;
    if (_isSelfEcho(text)) { caption(''); transition(S.IDLE, 'echo discard'); return; }
    if (/^\s*(hey\s+)?(edith|jarvis)[\s.,!?]*$/i.test(text)) return wakeFired('transcript');
    var stripped = text.replace(/^\s*(hey\s+)?(edith|jarvis)[\s.,!?]*/i, '');
    if (stripped !== text && stripped.trim()) text = stripped.trim();

    if (SIGNOFF.test(text)) {
      sessionActive = false;
      await say('Very good, Rydel.', 'reply');
      transition(S.IDLE, 'signoff');
      setSessionFx(false);
      setTimeout(resumeWakeIfArmed, 600);
      return;
    }
    if (pendingBriefOffer && /^(yes|yeah|yep|sure|ok|okay|go|brief|please)\b/i.test(text)) {
      pendingBriefOffer = false;
      return runBrief();
    }
    pendingBriefOffer = false;
    if (/^(brief me|morning brief|daily brief|read my priorities)\b/i.test(text)) return runBrief();

    if (!window.JarvisChat) return;
    transition(S.THINKING, 'query');
    var sentAt = performance.now();
    var reply = await window.JarvisChat.ask(text, true);
    if (reply) {
      await speakWithBargeIn(reply, 'reply');
      log('latency send→speech-start:', Math.round(_speakStartedAt - sentAt) + 'ms');
      afterReply();
    } else {
      transition(S.IDLE, 'no reply');
      note('No reply — check the chat panel.');
    }
  }

  // barge-in: sustained HUMAN-level energy (>0.17 RMS, 600ms) stops her
  function speakWithBargeIn(text, context, opts) {
    return new Promise(function(resolve) {
      var bargeStart = null, raf = null, finished = false;
      function watch() {
        if (finished) return;
        if (audioManager.isSpeaking() && micAnalyser) {
          if (micRMS() > 0.17) {
            if (!bargeStart) bargeStart = performance.now();
            else if (performance.now() - bargeStart > 600) {
              audioManager.stopVoice();
              finished = true;
              startListening();
              return resolve();
            }
          } else bargeStart = null;
        }
        raf = requestAnimationFrame(watch);
      }
      watch();
      say(text, context, opts).then(function() {
        finished = true;
        if (raf) cancelAnimationFrame(raf);
        resolve();
      });
    });
  }

  function afterReply() {
    if (!convoEnabled() || !sessionActive) {
      transition(S.IDLE, 'reply done');
      setTimeout(resumeWakeIfArmed, 600);
      return;
    }
    clearTimeout(convoTimer);
    startListening();
    note('listening for a follow-up…', 5500);
    convoTimer = setTimeout(function() {
      if (listening && !pendingText) stopListening();
    }, 6000);
  }

  async function runBrief() {
    transition(S.THINKING, 'brief');
    caption('composing your brief…', true);
    try {
      var resp = await fetch('/dashboard/api/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      var data = await resp.json();
      if (data.text) {
        if (window.JarvisChat) window.JarvisChat.addAssistantMessage(data.text);
        await speakWithBargeIn(data.text, 'reply');
        afterReply();
      } else { transition(S.IDLE, 'brief fail'); note(data.error || 'Brief unavailable.'); }
    } catch (e) { transition(S.IDLE, 'brief error'); note('Brief failed — network?'); }
  }

  // ═════════════════════════════════════════════════════════
  //  BOOT (Phase 5) + GREETING — single entry, state-guarded
  // ═════════════════════════════════════════════════════════
  var musicPresent = false;

  async function refreshMusicStatus() {
    try {
      var resp = await fetch('/dashboard/api/entrance-audio');
      if (resp.ok) {
        var d = await resp.json();
        musicPresent = !!d.present;
        return d;
      }
    } catch (e) {}
    musicPresent = false;
    return null;
  }

  async function bootSequence() {
    if (!transition(S.BOOTING, 'boot')) return;   // double-trigger dies here
    sessionActive = true;
    bootedThisSession = true;
    setSessionFx(true);

    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // t=0: music (if uploaded) + synth power-up + dim + orb ignition
    if (musicPresent) audioManager.playMusic('/dashboard/audio/entrance');
    audioManager.reactor();

    if (!reduced) {
      var hud = document.createElement('div');
      hud.className = 'edith-boot-hud';
      hud.innerHTML =
        '<div class="ebh-dim"></div><div class="ebh-sweep"></div><div class="ebh-scan"></div>' +
        '<canvas class="ebh-grid" width="640" height="360"></canvas>' +
        '<div class="ebh-console" id="ebh-console"></div>' +
        '<div class="ebh-progress"><div class="ebh-progress-fill" id="ebh-pfill"></div><span class="ebh-pct" id="ebh-pct">0%</span></div>' +
        '<div class="ebh-caption" id="ebh-typed"></div>';
      document.body.appendChild(hud);
      document.body.classList.add('boot-seq');

      // wireframe grid pass (the one canvas layer)
      try {
        var gc = hud.querySelector('.ebh-grid').getContext('2d');
        var gt0 = performance.now();
        (function gridLoop() {
          if (!hud.isConnected) return;
          var p = (performance.now() - gt0) / 2200;
          if (p > 1) return;
          gc.clearRect(0, 0, 640, 360);
          gc.strokeStyle = 'rgba(91,155,208,' + (0.18 * (1 - p)) + ')';
          gc.lineWidth = 0.5;
          var off = p * 40;
          for (var x = -40 + off; x < 680; x += 40) {
            gc.beginPath(); gc.moveTo(x, 0); gc.lineTo(x - 60, 360); gc.stroke();
          }
          for (var y = -40 + off; y < 400; y += 40) {
            gc.beginPath(); gc.moveTo(0, y); gc.lineTo(640, y - 20); gc.stroke();
          }
          requestAnimationFrame(gridLoop);
        })();
      } catch (e) {}

      // systems console
      var SYSTEMS = ['ARC CORE', 'CASH ENGINE', 'FORWARD MRR MODEL', 'FUNNEL TELEMETRY',
                     'CLIENT HEALTH GRID', 'COMMS ARRAY', 'EDITH CORE'];
      var consoleEl = hud.querySelector('#ebh-console');
      var pfill = hud.querySelector('#ebh-pfill');
      var pct = hud.querySelector('#ebh-pct');
      SYSTEMS.forEach(function(name, i) {
        setTimeout(function() {
          if (!consoleEl.isConnected) return;
          var row = document.createElement('div');
          row.className = 'ebh-line';
          row.innerHTML = '<span class="ebh-sys">' + name + '</span><span class="ebh-dots"></span><span class="ebh-ok">ONLINE</span>';
          consoleEl.appendChild(row);
          var p = Math.round(((i + 1) / SYSTEMS.length) * 100);
          pfill.style.width = p + '%'; pct.textContent = p + '%';
        }, 250 + i * 230);
      });

      // t≈2.0: "EDITH — ONLINE" types on with a cursor
      var typed = hud.querySelector('#ebh-typed');
      var label = 'EDITH — ONLINE';
      setTimeout(function() {
        var i = 0;
        var tt = setInterval(function() {
          if (!typed.isConnected) return clearInterval(tt);
          typed.textContent = label.slice(0, ++i);
          typed.classList.add('typing');
          if (i >= label.length) { clearInterval(tt); typed.classList.remove('typing'); }
        }, 55);
      }, 1900);

      var cleanup = function() {
        document.body.classList.remove('boot-seq');
        hud.remove();
        document.removeEventListener('click', skipper, true);
      };
      var skipper = function() { cleanup(); };
      setTimeout(function() { document.addEventListener('click', skipper, true); }, 200);
      setTimeout(cleanup, 3600);
      await new Promise(function(r) { setTimeout(r, 2600); });
    } else {
      await new Promise(function(r) { setTimeout(r, 400); });
    }

    // GREETING — fires ONLY from BOOTING, once
    if (!transition(S.GREETING, 'boot complete')) return;
    var text = null;
    try {
      var resp = await fetch('/dashboard/api/greeting');
      if (resp.ok) { text = (await resp.json()).text; }
      else note('Greeting endpoint returned ' + resp.status + ' — fallback greeting.', 6000);
    } catch (e) { note('Greeting fetch failed — fallback greeting.', 6000); }
    if (!text) {
      var hour = new Date().getHours();
      text = 'Good ' + (hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening') + ', Rydel. EDITH online. What do you need?';
    }
    if (window.JarvisChat) window.JarvisChat.addAssistantMessage(text);
    await speakWithBargeIn(text, 'system', { crushFirstWord: true });
    if (musicPresent && lsGet('edith-music-keep', '0') !== '1') audioManager.fadeOutMusic(2);
    startListening();
  }

  // ── wake entry — idempotent: debounce + state guard ──
  var _interacted = false;
  function audioUnlocked() {
    if (navigator.userActivation && navigator.userActivation.hasBeenActive) return true;
    return _interacted;
  }
  function _unlockAudio() { _interacted = true; try { audioManager.ensure(); } catch (e) {} }
  document.addEventListener('pointerdown', _unlockAudio, true);
  document.addEventListener('keydown', _unlockAudio, true);

  function showPowerPrompt() {
    if (document.getElementById('edith-power-prompt')) return;
    var el = document.createElement('div');
    el.id = 'edith-power-prompt'; el.className = 'edith-power-prompt';
    el.innerHTML = '<div class="epp-core"></div><div class="epp-text">EDITH READY — TAP TO POWER UP</div>';
    document.body.appendChild(el);
    el.addEventListener('click', function() {
      el.remove(); _unlockAudio(); bootSequence();
    });
  }

  var _wakeAt = 0;
  function wakeFired(source) {
    var now = performance.now();
    if (now - _wakeAt < 1500) { log('wake debounced (' + source + ')'); return; }
    _wakeAt = now;
    if (state !== S.IDLE && state !== S.LISTENING) { log('wake ignored in state', state); return; }
    if (!audioUnlocked()) { showPowerPrompt(); return; }
    if (listening) stopListening(true);

    if (!bootedThisSession) return bootSequence();

    audioManager.chime('ack');
    sessionActive = true;
    setSessionFx(true);
    say('Yes, Rydel?', 'reply').then(function() { startListening(); });
  }

  // ═════════════════════════════════════════════════════════
  //  WAKE WORD — Porcupine on-device, or browser-STT interim
  // ═════════════════════════════════════════════════════════
  var porcupine = null;
  var wakeArmed = false;

  function wakePhrase() {
    if (CFG.picovoiceKey) return CFG.wakePpnPresent ? 'Hey Edith' : 'Jarvis';
    return 'Hey Edith';
  }

  var browserWake = null;
  var browserWakeActive = false;
  var WAKE_RX = /\b(hey\s+)?(edith|jarvis)\b\s*$/i;

  function startBrowserWake() {
    if (browserWakeActive || !hasSTT) return;
    // single-mic, no-self-hearing rule: idle only
    if (listening || audioManager.isSpeaking() || state !== S.IDLE) return;
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    browserWake = browserWake || (function() {
      var r = new SR();
      r.lang = 'en-AU'; r.interimResults = true; r.continuous = true;
      r.onresult = function(e) {
        var txt = '';
        for (var i = e.results.length - 1; i >= 0 && i >= e.results.length - 2; i--) {
          txt = e.results[i][0].transcript + ' ' + txt;
        }
        if (WAKE_RX.test(txt.trim())) {
          stopBrowserWake();
          wakeFired('browser-wake');      // debounce + state guard make this safe
        }
      };
      r.onerror = function(e) {
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          note('Mic blocked — wake word off.', 6000);
          lsSet('edith-wake', '0');
          wakeArmed = false; browserWakeActive = false; setOrb(state);
        }
      };
      r.onend = function() {
        if (browserWakeActive && wakeArmed && !listening && !document.hidden) {
          try { r.start(); } catch (e) {}
        }
      };
      return r;
    })();
    try { browserWake.start(); browserWakeActive = true; } catch (e) {}
  }
  function stopBrowserWake() {
    browserWakeActive = false;
    if (browserWake) { try { browserWake.stop(); } catch (e) {} }
  }
  function resumeWakeIfArmed() {
    if (!wakeArmed || CFG.picovoiceKey || document.hidden) return;
    if (listening || audioManager.isSpeaking() || state !== S.IDLE) return;
    setTimeout(function() {
      if (wakeArmed && !listening && state === S.IDLE) startBrowserWake();
    }, 400);
  }

  function loadScript(src) {
    return new Promise(function(resolve, reject) {
      var s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  async function armWakeWord() {
    if (wakeArmed) return;
    if (!CFG.picovoiceKey) {
      if (!hasSTT) { note('Wake word needs Chrome.', 6000); lsSet('edith-wake', '0'); return; }
      try { await ensureMic(); } catch (e) {
        note('Mic blocked — click the lock icon to allow it.', 7000);
        lsSet('edith-wake', '0');
        return;
      }
      wakeArmed = true;
      setOrb(state);
      startBrowserWake();
      note('Wake word armed — say "Hey Edith" (browser mode; on-device once Picovoice key is added)', 7000);
      return;
    }
    try {
      if (!window.PorcupineWeb) {
        await loadScript('https://cdn.jsdelivr.net/npm/@picovoice/porcupine-web@3.0.3/dist/iife/index.js');
        await loadScript('https://cdn.jsdelivr.net/npm/@picovoice/web-voice-processor@4.0.9/dist/iife/index.js');
      }
      var keyword = CFG.wakePpnPresent
        ? { publicPath: CFG.wakePpnPath, label: 'Hey Edith', sensitivity: lsNum('edith-wake-sens', 0.6) }
        : { builtin: 'Jarvis', sensitivity: lsNum('edith-wake-sens', 0.6) };
      porcupine = await window.PorcupineWeb.PorcupineWorker.create(
        CFG.picovoiceKey, [keyword],
        function() { wakeFired('porcupine'); },
        { publicPath: 'https://cdn.jsdelivr.net/npm/@picovoice/porcupine-web@3.0.3/lib/common/porcupine_params.pv' }
      );
      await window.WebVoiceProcessor.WebVoiceProcessor.subscribe(porcupine);
      wakeArmed = true;
      setOrb(state);
      note('Wake word armed (on-device) — say "' + wakePhrase() + '"', 6000);
    } catch (e) {
      log('porcupine init failed:', e.message);
      note('Wake word unavailable — click / hold-V still work.', 7000);
      lsSet('edith-wake', '0');
      wakeArmed = false;
    }
  }

  async function disarmWakeWord() {
    wakeArmed = false;
    setOrb(state);
    stopBrowserWake();
    try {
      if (porcupine) {
        await window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
        porcupine.release(); porcupine = null;
      }
    } catch (e) {}
    if (!clapArmed) releaseMic();
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

  // ═════════════════════════════════════════════════════════
  //  DOUBLE-CLAP WAKE — on-device transient detection
  //  A clap = broadband impulse: fast attack, spectrally flat,
  //  decays <~120ms. Two of them 150–800ms apart = wake.
  // ═════════════════════════════════════════════════════════
  var clapArmed = false;
  var clapRAF = null;
  var clapFreqBuf = null;
  var _noiseFloor = 0.01;
  var _clapTimes = [];          // qualified clap timestamps
  var _clapCooldownUntil = 0;
  var _onset = null;            // in-flight transient awaiting decay check
  var _prevRms = [0, 0, 0];
  var _clapLoopCost = [];       // CPU measurement
  var _calib = null;            // calibration overlay state

  function clapSens() { return Math.min(3, Math.max(0.5, lsNum('edith-clap-sens', 1.5))); }
  // higher slider = more sensitive: threshold = floor × (9 / sens), absolute floor 0.04 peak
  function clapThreshold() { return Math.max(0.04, _noiseFloor * (9 / clapSens())); }

  var _ctxSuspendedNoted = false;
  function _clapCtxAlive() {
    try {
      var c = audioManager.ensure();
      if (c.state === 'suspended') {
        c.resume();   // sticks after the first user gesture
        if (!_ctxSuspendedNoted) {
          _ctxSuspendedNoted = true;
          note('Clap wake is waiting for one click/tap (browser audio policy) — then it hears you.', 8000);
        }
        return false;
      }
      _ctxSuspendedNoted = false;
      return true;
    } catch (e) { return false; }
  }

  function spectralFlatness() {
    if (!micAnalyser) return 0;
    if (!clapFreqBuf) clapFreqBuf = new Uint8Array(micAnalyser.frequencyBinCount);
    micAnalyser.getByteFrequencyData(clapFreqBuf);
    var logSum = 0, sum = 0, n = 0;
    for (var i = 4; i < clapFreqBuf.length; i++) {   // skip DC/sub bins
      var v = clapFreqBuf[i] / 255 + 1e-4;
      logSum += Math.log(v); sum += v; n++;
    }
    var gm = Math.exp(logSum / n), am = sum / n;
    return am > 0 ? gm / am : 0;                      // 1 = white noise, ~0 = tonal
  }

  function clapLoop() {
    if (!clapArmed) return;
    clapRAF = requestAnimationFrame(clapLoop);
    if (hiddenTab() || !micAnalyser) return;
    if (!_clapCtxAlive()) return;   // suspended ctx = silent analyser; resume + wait
    var t0 = performance.now();

    // HARD GATE: never listen for claps while EDITH outputs anything —
    // Back in Black's drum hits must not self-trigger. Resume 250ms after.
    if (audioManager.isOutputting()) { _gateUntil = performance.now() + 250; _onset = null; return; }
    if (performance.now() < _gateUntil) return;
    // state guard: claps act only from IDLE (and not mid-listen)
    if (listening || state !== S.IDLE) { _onset = null; return; }

    var peak = micPeak();   // claps are spikes — peak beats RMS for onsets
    var now = performance.now();

    // adaptive noise floor on peaks: slow EMA, never learns during a transient
    if (!_onset && peak < clapThreshold()) {
      _noiseFloor = _noiseFloor * 0.99 + peak * 0.01;
      _noiseFloor = Math.max(0.004, Math.min(0.15, _noiseFloor));
    }

    if (_onset) {
      // decay check: spike must die within ~180ms, else reject (tonal/sustained)
      if (now - _onset.at > 180) {
        var decayed = peak < Math.max(_noiseFloor * 3.5, 0.05);
        var verdict = decayed && _onset.flat > 0.15;
        log('clap onset:', verdict ? 'ACCEPT' : 'reject',
            'peak=' + _onset.peak.toFixed(3), 'flat=' + _onset.flat.toFixed(2),
            'decayed=' + decayed, 'floor=' + _noiseFloor.toFixed(3));
        if (verdict) registerClap(_onset);
        else if (_calib) calibBlip(_onset, false, decayed ? 'tonal (flat ' + _onset.flat.toFixed(2) + ')' : 'no decay');
        _onset = null;
      } else {
        if (peak > _onset.peak) _onset.peak = peak;   // track the true spike height
        // the FFT window lags the impulse — flatness peaks mid-transient,
        // so keep the MAX observed across the transient's lifetime
        var f = spectralFlatness();
        if (f > _onset.flat) _onset.flat = f;
      }
    } else {
      var fastRise = _prevRms[0] < clapThreshold() * 0.6;
      if (peak > clapThreshold() && fastRise) {
        _onset = { at: now, peak: peak, flat: spectralFlatness() };
      }
    }
    _prevRms.shift(); _prevRms.push(peak);

    _clapLoopCost.push(performance.now() - t0);
    if (_clapLoopCost.length > 400) _clapLoopCost.shift();
  }
  var _gateUntil = 0;
  function hiddenTab() { return document.hidden; }

  function registerClap(onset) {
    var now = performance.now();
    if (now < _clapCooldownUntil) return;
    if (_calib) calibBlip(onset, true);
    _clapTimes.push(now);
    _clapTimes = _clapTimes.filter(function(t) { return now - t < 1200; });

    if (_clapTimes.length >= 2) {
      var gap = _clapTimes[_clapTimes.length - 1] - _clapTimes[_clapTimes.length - 2];
      if (gap >= 150 && gap <= 800) {
        // a third immediate transient cancels (applause ≠ command)
        var first = _clapTimes[_clapTimes.length - 2], second = now;
        setTimeout(function() {
          var extras = _clapTimes.filter(function(t) { return t > second && t - second < 300; });
          if (extras.length) { log('clap: cancelled (burst)'); if (_calib) calibFlash('cancelled — burst'); return; }
          _clapCooldownUntil = performance.now() + 1500;
          _clapTimes = [];
          if (_calib && _calib.testOnly) { calibFlash('DOUBLE CLAP ✓ (test mode — not waking)'); return; }
          if (_calib) calibFlash('DOUBLE CLAP ✓');
          log('clap: double-clap wake (gap ' + Math.round(gap) + 'ms)');
          audioManager.chime('clap');
          wakeFired('double-clap');
        }, 310);
      }
    }
  }

  async function armClap() {
    if (clapArmed) return;
    try { await ensureMic(); } catch (e) {
      // a gesture-less load can fail transiently — retry on first interaction,
      // never silently persist the toggle off
      log('clap arm deferred (mic not available yet):', e && e.name);
      var retry = function() {
        document.removeEventListener('pointerdown', retry, true);
        if (lsGet('edith-clap', '1') === '1') armClap();
      };
      document.addEventListener('pointerdown', retry, true);
      return;
    }
    clapArmed = true;
    setOrb(state);
    clapLoop();
    log('clap detector armed (floor adapts; thresh=' + clapThreshold().toFixed(3) + ')');
  }
  function disarmClap() {
    clapArmed = false;
    if (clapRAF) cancelAnimationFrame(clapRAF);
    clapRAF = null;
    _onset = null; _clapTimes = [];
    setOrb(state);
    if (!wakeArmed) releaseMic();   // mic fully released when nothing needs it
    if (_clapLoopCost.length) {
      var avg = _clapLoopCost.reduce(function(a, b) { return a + b; }, 0) / _clapLoopCost.length;
      log('clap detector CPU: avg ' + avg.toFixed(3) + 'ms/frame over ' + _clapLoopCost.length + ' frames');
    }
  }
  window.__CLAP_STATE__ = function() {
    var ctxState = null;
    try { ctxState = audioManager.ensure().state; } catch (e) { ctxState = 'err:' + e.message; }
    return {
      armed: clapArmed, micAnalyser: !!micAnalyser, micStream: !!micStream,
      ctx: ctxState, floor: _noiseFloor, thresh: clapThreshold(),
      state: state, listening: listening,
      outputting: audioManager.isOutputting(),
      loopFrames: _clapLoopCost.length,
      peakNow: micPeak(),
    };
  };
  window.__CLAP_CPU__ = function() {
    if (!_clapLoopCost.length) return null;
    var avg = _clapLoopCost.reduce(function(a, b) { return a + b; }, 0) / _clapLoopCost.length;
    return { avg_ms_per_frame: Math.round(avg * 1000) / 1000, frames: _clapLoopCost.length };
  };

  // ── calibration overlay ──
  function calibBlip(onset, ok, why) {
    if (!_calib || !_calib.list) return;
    var row = document.createElement('div');
    row.className = 'calib-blip ' + (ok ? 'ok' : 'rej');
    row.textContent = (ok ? '👏 clap' : '× ' + (why || 'rejected')) +
      ' · peak ' + onset.peak.toFixed(3) + ' · flat ' + onset.flat.toFixed(2);
    _calib.list.prepend(row);
    while (_calib.list.children.length > 6) _calib.list.lastChild.remove();
  }
  function calibFlash(msg) {
    if (!_calib || !_calib.flash) return;
    _calib.flash.textContent = msg;
    _calib.flash.classList.add('show');
    setTimeout(function() { if (_calib) _calib.flash.classList.remove('show'); }, 1800);
  }
  function openCalibration() {
    if (_calib) return;
    var el = document.createElement('div');
    el.className = 'calib-panel';
    el.innerHTML =
      '<div class="jh-title">👏 Clap calibration</div>' +
      '<div class="jh-row ep-dim">Clap twice now. Tune sensitivity until YOUR claps register and desk thumps don\u2019t.</div>' +
      '<canvas class="calib-meter" width="280" height="44"></canvas>' +
      '<div class="calib-flash"></div>' +
      '<div class="calib-list"></div>' +
      '<div class="jh-row">Sensitivity <input type="range" id="calib-sens" min="0.5" max="3" step="0.1" value="' + clapSens() + '"> <span id="calib-sens-v">' + clapSens().toFixed(1) + '\u00d7</span></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="calib-testonly" checked> test only (don\u2019t wake)</label></div>' +
      '<div class="jh-row ep-presets"><button class="ep-preset" id="calib-close">close</button></div>';
    document.body.appendChild(el);
    _calib = {
      el: el,
      list: el.querySelector('.calib-list'),
      flash: el.querySelector('.calib-flash'),
      testOnly: true,
      meter: el.querySelector('.calib-meter').getContext('2d'),
    };
    el.querySelector('#calib-sens').addEventListener('input', function() {
      lsSet('edith-clap-sens', this.value);
      el.querySelector('#calib-sens-v').textContent = parseFloat(this.value).toFixed(1) + '\u00d7';
    });
    el.querySelector('#calib-testonly').addEventListener('change', function() { _calib.testOnly = this.checked; });
    el.querySelector('#calib-close').addEventListener('click', closeCalibration);
    if (!clapArmed) armClap();   // calibration needs the detector live
    var readout = document.createElement('div');
    readout.className = 'jh-row ep-dim calib-readout';
    el.insertBefore(readout, el.querySelector('.calib-flash'));
    (function meterLoop() {
      if (!_calib) return;
      var g = _calib.meter;
      g.clearRect(0, 0, 280, 44);
      var pk = micPeak();
      var ctxOk = false;
      try { ctxOk = audioManager.ensure().state === 'running'; } catch (e) {}
      g.fillStyle = pk > clapThreshold() ? 'rgba(52,201,142,0.9)' : 'rgba(91,155,208,0.8)';
      g.fillRect(0, 14, Math.min(pk * 350, 280), 16);
      var fx = Math.min(_noiseFloor * 350, 280);
      g.fillStyle = 'rgba(122,154,191,0.8)'; g.fillRect(fx, 6, 1.5, 32);
      var tx = Math.min(clapThreshold() * 350, 280);
      g.fillStyle = 'rgba(232,180,69,0.95)'; g.fillRect(tx, 2, 2, 40);
      readout.textContent = ctxOk
        ? ('peak ' + pk.toFixed(3) + ' · floor ' + _noiseFloor.toFixed(3) + ' · trigger ' + clapThreshold().toFixed(3))
        : '⚠ audio engine suspended — click anywhere once, then the meter goes live';
      requestAnimationFrame(meterLoop);
    })();
  }
  function closeCalibration() {
    if (!_calib) return;
    _calib.el.remove();
    _calib = null;
    if (lsGet('edith-clap', '1') !== '1') disarmClap();
  }

  // ═════════════════════════════════════════════════════════
  //  ORB + KEYBOARD
  // ═════════════════════════════════════════════════════════
  function onOrbClick() {
    if (audioManager.isSpeaking()) { audioManager.stopVoice(); transition(S.IDLE, 'orb interrupt'); return; }
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
      if (e.key === 'Escape') {
        audioManager.stopAll();
        stopListening();
        if (state !== S.IDLE) transition(S.IDLE, 'esc');
        return;
      }
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

  // ═════════════════════════════════════════════════════════
  //  SETTINGS PANEL
  // ═════════════════════════════════════════════════════════
  function togglePanel() {
    var el = document.getElementById('edith-panel');
    if (el) { el.remove(); return; }
    el = document.createElement('div');
    el.id = 'edith-panel';
    el.className = 'jarvis-help edith-panel';
    var p = audioManager.fxParams(lsGet('edith-fx-preset', 'edith'));
    el.innerHTML =
      '<div class="jh-title">EDITH</div>' +
      '<div class="jh-row"><b>Click orb / hold V or Space</b> talk &middot; <b>Esc</b> stop &middot; <b>B</b> brief</div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-wake" ' + (lsGet('edith-wake', '1') === '1' ? 'checked' : '') + '> &#127908; Wake word: "' + wakePhrase() + '"' + (CFG.picovoiceKey ? '' : ' <span class="ep-dim">(browser mode)</span>') + '</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-clap" ' + (lsGet('edith-clap', '1') === '1' ? 'checked' : '') + '> &#128079; Double-clap wake</label> <button class="ep-preset" id="ep-calib" style="margin-left:8px;">calibrate</button></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-convo" ' + (lsGet('edith-convo', '1') === '1' ? 'checked' : '') + '> Conversation mode</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-cine" ' + (lsGet('edith-cinematic', '1') === '1' ? 'checked' : '') + '> Cinematic mode</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-stark" ' + (lsGet('edith-stark', '1') === '1' ? 'checked' : '') + '> Stark mode (Shift+S)</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-uisounds" ' + (lsGet('edith-ui-sounds', '1') === '1' ? 'checked' : '') + '> UI sounds</label></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-loadanim" ' + (lsGet('edith-load-anim', '1') === '1' ? 'checked' : '') + '> Boot animation on page load</label></div>' +
      '<div class="jh-row">Patience <input type="range" id="ep-patience" min="0.8" max="3" step="0.1" value="' + lsNum('edith-patience', 1.4) + '"> <span id="ep-patience-v">' + lsNum('edith-patience', 1.4).toFixed(1) + 's</span></div>' +
      '<div class="ep-section">Mixer</div>' +
      ['master', 'voice', 'sfx', 'music'].map(function(chn) {
        return '<div class="jh-row">' + chn + ' <input type="range" data-mix="' + chn + '" min="0" max="1.2" step="0.05" value="' + audioManager.mixGet(chn) + '"></div>';
      }).join('') +
      '<div class="ep-section">AI Voice Character</div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-fx" ' + (audioManager.fxEnabled() ? 'checked' : '') + '> AI processing</label></div>' +
      '<div class="jh-row ep-presets">' +
        ['edith', 'subtle', 'system', 'off'].map(function(name) {
          var cur = lsGet('edith-fx-preset', 'edith');
          return '<button class="ep-preset' + (cur === name ? ' active' : '') + '" data-p="' + name + '">' + name + '</button>';
        }).join('') +
      '</div>' +
      '<details class="ep-adv"><summary>advanced</summary>' +
        '<div class="jh-row">HP <input type="range" data-fx="hp" min="0" max="400" step="10" value="' + p.hp + '"></div>' +
        '<div class="jh-row">LP <input type="range" data-fx="lp" min="3000" max="16000" step="250" value="' + p.lp + '"></div>' +
        '<div class="jh-row">Resonance <input type="range" data-fx="comb" min="0" max="0.4" step="0.02" value="' + p.comb + '"></div>' +
        '<div class="jh-row">Double <input type="range" data-fx="dbl" min="0" max="0.6" step="0.02" value="' + p.dbl + '"></div>' +
        '<div class="jh-row">Sheen <input type="range" data-fx="shelf" min="0" max="6" step="0.5" value="' + (p.shelf || 0) + '"></div>' +
        '<div class="jh-row">Shimmer <input type="range" data-fx="shim" min="0" max="0.10" step="0.01" value="' + (p.shim || 0) + '"></div>' +
        '<div class="jh-row">Reverb <input type="range" data-fx="rev" min="0" max="0.4" step="0.02" value="' + p.rev + '"></div>' +
        '<div class="jh-row">Wet <input type="range" data-fx="wet" min="0" max="0.7" step="0.02" value="' + p.wet + '"></div>' +
      '</details>' +
      '<div class="ep-section">Voice (locked: FRIDAY)</div>' +
      '<div class="jh-row"><input type="text" id="ep-voice-id" class="ep-input" placeholder="ElevenLabs voice ID (audition)"></div>' +
      '<div class="jh-row ep-presets"><button id="ep-audition" class="ep-preset">audition</button>' +
      '<button id="ep-ab" class="ep-preset">A/B raw vs fx</button>' +
      '<button id="ep-probe" class="ep-preset">muffle probe</button>' +
      '<button id="ep-voice-set" class="ep-preset">set</button>' +
      '<button id="ep-voice-reset" class="ep-preset">reset to default</button></div>' +
      '<div class="ep-section">Entrance music</div>' +
      '<div class="jh-row ep-dim" id="ep-track-status">checking…</div>' +
      '<div class="jh-row"><input type="file" id="ep-track" accept="audio/mpeg,audio/mp3,audio/mp4,audio/x-m4a" class="ep-input"></div>' +
      '<div class="jh-row ep-presets"><button id="ep-track-up" class="ep-preset">upload</button><button id="ep-track-rm" class="ep-preset">remove</button><button id="ep-track-test" class="ep-preset">test</button></div>' +
      '<div class="jh-row"><label><input type="checkbox" id="ep-music-keep" ' + (lsGet('edith-music-keep', '0') === '1' ? 'checked' : '') + '> keep playing after boot</label></div>' +
      '<div class="ep-section">Status</div>' +
      '<div class="jh-row ep-dim" id="ep-status">checking…</div>' +
      '<div class="jh-close">esc or ? to close</div>';
    document.body.appendChild(el);

    (async function fillStatus() {
      await refreshVoiceStatus();
      var d = await refreshMusicStatus();
      var trackEl = el.querySelector('#ep-track-status');
      if (trackEl) trackEl.textContent = (d && d.present)
        ? ('uploaded ✓ (' + Math.round((d.bytes || 0) / 1024 / 1024 * 10) / 10 + 'MB)' + (d.volatile ? ' — re-upload after each deploy (no volume mounted)' : ''))
        : 'none — upload YOUR OWN legally-obtained track (nothing copyrighted ships with this dashboard)';
      var s = el.querySelector('#ep-status');
      if (!s) return;
      if (!voiceStatus) { s.textContent = 'voice-status unreachable'; return; }
      s.innerHTML =
        'ElevenLabs: <b style="color:' + (voiceStatus.elevenlabs_configured ? 'var(--green)' : 'var(--red)') + '">' +
        (voiceStatus.elevenlabs_configured ? 'configured' : 'NOT CONFIGURED — add ELEVENLABS_API_KEY') + '</b><br>' +
        'Voice: ' + esc(voiceStatus.voice_id || '?') + (voiceStatus.voice_id === voiceStatus.default_voice_id ? ' (locked default)' : ' (override)') + '<br>' +
        'Wake mode: ' + (CFG.picovoiceKey ? 'on-device (Picovoice)' : 'browser (interim)') + '<br>' +
        'TTS today: ' + (voiceStatus.daily_chars_used || 0) + ' / ' + voiceStatus.daily_char_cap + ' chars<br>' +
        'State: ' + state;
    })();

    el.querySelector('#ep-wake').addEventListener('change', function() {
      lsSet('edith-wake', this.checked ? '1' : '0');
      if (this.checked) armWakeWord(); else disarmWakeWord();
    });
    el.querySelector('#ep-clap').addEventListener('change', function() {
      lsSet('edith-clap', this.checked ? '1' : '0');
      if (this.checked) armClap(); else disarmClap();
    });
    el.querySelector('#ep-calib').addEventListener('click', openCalibration);
    el.querySelector('#ep-convo').addEventListener('change', function() { lsSet('edith-convo', this.checked ? '1' : '0'); });
    el.querySelector('#ep-cine').addEventListener('change', function() { lsSet('edith-cinematic', this.checked ? '1' : '0'); });
    el.querySelector('#ep-stark').addEventListener('change', function() {
      lsSet('edith-stark', this.checked ? '1' : '0');
      document.body.classList.toggle('stark-mode', this.checked);
      document.body.classList.toggle('focus-mode', !this.checked);
    });
    el.querySelector('#ep-uisounds').addEventListener('change', function() { lsSet('edith-ui-sounds', this.checked ? '1' : '0'); });
    el.querySelector('#ep-loadanim').addEventListener('change', function() { lsSet('edith-load-anim', this.checked ? '1' : '0'); });
    el.querySelector('#ep-music-keep').addEventListener('change', function() { lsSet('edith-music-keep', this.checked ? '1' : '0'); });
    el.querySelector('#ep-patience').addEventListener('input', function() {
      lsSet('edith-patience', this.value);
      el.querySelector('#ep-patience-v').textContent = parseFloat(this.value).toFixed(1) + 's';
    });
    el.querySelectorAll('[data-mix]').forEach(function(sl) {
      sl.addEventListener('input', function() { audioManager.setMix(this.dataset.mix, this.value); });
    });
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
      say(TEST_LINE, 'reply', vid ? { voiceId: vid } : {}).then(function() {
        if (state === S.SPEAKING) transition(S.IDLE, 'audition done');
      });
    });
    // A/B: raw first, 600ms gap, then through current settings — the ear's test
    el.querySelector('#ep-ab').addEventListener('click', async function() {
      var line = 'EDITH online. This is the raw voice.';
      note('A: raw…', 2500);
      await say(line, 'reply', { fxOverride: PROBE_RAW });
      await new Promise(function(r) { setTimeout(r, 600); });
      note('B: through current settings…', 2500);
      await say('EDITH online. This is the processed voice.', 'reply');
      if (state === S.SPEAKING) transition(S.IDLE, 'ab done');
    });
    // Muffle probe: 100% wet through a 300Hz lowpass. If the voice is not
    // obviously underwater, the chain is NOT in the signal path. The analyser
    // verdict prints alongside what you hear.
    el.querySelector('#ep-probe').addEventListener('click', async function() {
      note('Muffle probe: this line should sound underwater…', 5000);
      var verdictTimer = setTimeout(function() {
        var an = audioManager.analyser();
        if (!an) return;
        var freq = new Uint8Array(an.frequencyBinCount);
        an.getByteFrequencyData(freq);
        var cut = Math.round(600 / (audioManagerSampleRate() / 2) * freq.length);
        var low = 0, high = 0;
        for (var i = 0; i < freq.length; i++) { if (i <= cut) low += freq[i]; else high += freq[i]; }
        var pass = low > 200 && high < low * 0.25;
        note('MUFFLE PROBE ' + (pass ? 'PASS — chain is in the signal path ✓' : 'FAIL — high-band energy present; routing suspect') , 9000);
        log('muffle probe:', pass ? 'PASS' : 'FAIL', 'low=' + low, 'high=' + high);
      }, 2200);
      await say('Testing the audio chain. If this sounds clear, the routing is broken.', 'reply', { fxOverride: PROBE_MUFFLE });
      clearTimeout(verdictTimer);
      if (state === S.SPEAKING) transition(S.IDLE, 'probe done');
    });
    el.querySelector('#ep-voice-set').addEventListener('click', async function() {
      var vid = el.querySelector('#ep-voice-id').value.trim();
      if (!vid) return note('Paste a voice ID first.');
      await fetch('/dashboard/api/voice-config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ voice_id: vid }) });
      note('Voice set — next reply uses it.');
      refreshVoiceStatus();
    });
    el.querySelector('#ep-voice-reset').addEventListener('click', async function() {
      await fetch('/dashboard/api/voice-config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      note('Voice reset to the locked default.');
      refreshVoiceStatus();
    });
    el.querySelector('#ep-track-up').addEventListener('click', async function() {
      var f = el.querySelector('#ep-track').files[0];
      if (!f) return note('Choose an MP3/M4A first.');
      var fd = new FormData(); fd.append('file', f);
      var resp = await fetch('/dashboard/api/entrance-audio', { method: 'POST', body: fd });
      var data = await resp.json();
      note(data.ok ? 'Track uploaded — say "Hey Edith".' : ('Upload failed: ' + (data.error || resp.status)));
      refreshMusicStatus();
    });
    el.querySelector('#ep-track-rm').addEventListener('click', async function() {
      await fetch('/dashboard/api/entrance-audio', { method: 'DELETE' });
      note('Track removed.');
      refreshMusicStatus();
    });
    el.querySelector('#ep-track-test').addEventListener('click', async function() {
      await refreshMusicStatus();
      if (!musicPresent) return note('No track uploaded.');
      audioManager.playMusic('/dashboard/audio/entrance');
      setTimeout(function() { audioManager.fadeOutMusic(1.5); }, 5000);
    });
  }

  // ── load-time visual boot (silent, autoplay-safe) ────────
  function loadBootVisuals() {
    if (lsGet('edith-load-anim', '1') !== '1') return;
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) return;
    document.body.classList.add('boot-seq');
    setTimeout(function() { document.body.classList.remove('boot-seq'); }, 2400);
  }

  function initEntranceTrigger() {
    var reactor = document.querySelector('.reactor');
    if (!reactor) return;
    reactor.style.cursor = 'pointer';
    reactor.title = 'Power up EDITH';
    reactor.addEventListener('click', function() {
      bootedThisSession = false;
      if (state !== S.IDLE) { audioManager.stopAll(); stopListening(true); state = S.IDLE; }
      bootSequence();
    });
    if (lsGet('jarvis-entrance-invite', '0') === '1') reactor.classList.add('invite');
  }

  // ── public surface for the Stark HUD layer (stark-hud.js) ──
  window.EDITH = {
    getState: function() { return state; },
    micRMS: micRMS,
    analyser: function() { return audioManager.analyser(); },
    audio: {
      startHum: audioManager.startHum, stopHum: audioManager.stopHum,
      uiTick: audioManager.uiTick, uiConfirm: audioManager.uiConfirm,
      uiComplete: audioManager.uiComplete, uiError: audioManager.uiError,
    },
    isListening: function() { return listening; },
  };

  // ── init ─────────────────────────────────────────────────
  (async function init() {
    buildUI();
    initKeys();
    initEntranceTrigger();
    loadBootVisuals();
    await Promise.all([refreshVoiceStatus(), refreshMusicStatus()]);
    if (lsGet('edith-wake', '1') === '1') armWakeWord();
    if (lsGet('edith-clap', '1') === '1') armClap();        // double-clap wake, on-device
  })();

})();
